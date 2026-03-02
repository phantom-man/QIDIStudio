"""
scripts/ai_debug_pipeline.py — Autonomous AI Debug Harness for apply_texture_bpy.py
======================================================================================

Vision-in-the-Loop (ViL) autonomous debug pipeline.

How to use (no human required after initial run):
  python scripts/ai_debug_pipeline.py

The script will:
  1. Loop through TEST_CASES (known 3MF files with expected classifications).
  2. Extract the embedded STL from the 3MF (read-only — never modifies source files).
  3. Run Blender in background mode with --debug-snapshots to capture JSON telemetry
     at three pipeline stages: post_weld, post_classify, post_displace.
  4. Read the JSON snapshot files.
  5. Verify mesh_class matches the expected value; flag TOPOLOGY_MISMATCH events.
  6. Write ai_debug_report.json and ai_debug_report.txt to scripts/debug_runs/<run_id>/.

The AI reads ai_debug_report.txt in a subsequent session to identify misclassifications
and then edits classifer thresholds in apply_texture_bpy.py accordingly.

Architecture ref: Observe→Orient→Decide→Act (Boyd OODA loop).
GPT-4V ref:       arXiv 2303.08774 (multimodal image+text reasoning).
DDG ref:          Keenan Crane CMU 15-458 Spring 2024 (conformal parameterisation).
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

# ── Paths ────────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT_PY = _REPO_ROOT / "resources" / "scripts" / "apply_texture_bpy.py"
_SKIN_PNG = pathlib.Path(
    r"C:\QIDISrc\QIDIStudio\install_dir\resources\assets"
    r"\armadillo_plates\armadillo_plates_01.png"
)


# Fallback skin: any PNG inside resources/assets/
def _find_skin() -> pathlib.Path:
    if _SKIN_PNG.exists():
        return _SKIN_PNG
    for p in (_REPO_ROOT / "resources" / "assets").rglob("*.png"):
        return p
    raise FileNotFoundError(
        "No skin PNG found — set _SKIN_PNG manually in ai_debug_pipeline.py"
    )


# ── Blender discovery ─────────────────────────────────────────────────────────
def _find_blender() -> str:
    env = os.environ.get("QIDI_BLENDER_EXE", "")
    if env and pathlib.Path(env).exists():
        return env
    candidates = [
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    ]
    for c in candidates:
        if pathlib.Path(c).exists():
            return c
    hit = shutil.which("blender")
    if hit:
        return hit
    raise FileNotFoundError(
        "Blender not found. Set QIDI_BLENDER_EXE env var or install to default location."
    )


# ── Test suite ────────────────────────────────────────────────────────────────
#
# Add new cases here.  Each entry specifies:
#   name          : short label used in file names and the report
#   model         : absolute path to the source 3MF (READ-ONLY — never modified)
#   expected_class: what _classify_mesh_topology() SHOULD return (string, matches MeshClass.name)
#   projection    : extra hint for the Blender invocation (default "auto")
#
TEST_CASES: list[dict] = [
    {
        "name": "poco_x6_phone_case",
        "model": r"C:\Users\User\source\repos\3DPrinting\PhoneCase\STL\protection-poco-x6.3mf",
        "expected_class": "FLAT_SHELL",
        "projection": "auto",
        "notes": "Flat rectangular shell ~148×73×8 mm. Should use OBJECT coords, no-full-surface.",
    },
    {
        "name": "elvish_tpu_inner",
        "model": r"C:\Users\User\source\repos\3DPrinting\PhoneCase\STL\elvish_tpu_inner.3mf",
        "expected_class": "FLAT_SHELL",
        "projection": "auto",
        "notes": "Ornamental flat back panel — previously misclassified before topology classifier.",
    },
    {
        "name": "vacuum_nozzle_lower",
        "model": r"C:\Users\User\source\repos\3DPrinting\VacuumNozzle\STL\vacuum_nozzle_lower.3mf",
        "expected_class": "REVOLUTION",
        "projection": "auto",
        "notes": "Rotational body (tall cylinder). Should use LSCM 30° seams, full-surface.",
    },
    {
        "name": "vacuum_crevice_nozzle",
        "model": r"C:\Users\User\source\repos\3DPrinting\VacuumNozzle\STL\vacuum_crevice_nozzle.3mf",
        "expected_class": "PRISMATIC",
        "projection": "auto",
        "notes": "Tapered rectangular prism with thin walls — prismatic, not revolution."
        " χ=−8 (complex topology) triggers Rule 2b: tall+smooth+complex → PRISMATIC.",
    },
]


# ── 3MF → STL extraction ──────────────────────────────────────────────────────
def _extract_stl_from_3mf(mf_path: str, out_dir: pathlib.Path) -> pathlib.Path | None:
    """Extract the first .stl or .model geometry from a 3MF archive.

    A 3MF file is a ZIP.  It may contain:
      - 3D/3dmodel.model  (XML — needs a full 3MF→STL converter, skip)
      - *.stl             (pre-sliced STL embedded by some slicers)

    If neither is found, returns None and the caller passes the .3mf path
    directly to Blender (which can import 3MF natively from Blender 4.0+).
    """
    mf = pathlib.Path(mf_path)
    if not mf.exists():
        return None
    try:
        with zipfile.ZipFile(mf, "r") as zf:
            names = zf.namelist()
            stl_names = [n for n in names if n.lower().endswith(".stl")]
            if stl_names:
                target = stl_names[0]
                out_stl = out_dir / f"{mf.stem}_{pathlib.Path(target).stem}.stl"
                with zf.open(target) as src, open(out_stl, "wb") as dst:
                    dst.write(src.read())
                return out_stl
    except (zipfile.BadZipFile, KeyError):
        pass
    return None  # Blender will import the .3mf directly


# ── Blender invocation ────────────────────────────────────────────────────────
def _run_blender(
    blender: str,
    model_path: str,
    skin_path: str,
    snapshots_dir: pathlib.Path,
    log_path: pathlib.Path,
    projection: str = "auto",
) -> tuple[int, str]:
    """Run apply_texture_bpy.py inside Blender background mode.

    Redirect Blender stdout/stderr directly to a file instead of capturing
    via PIPE.  On Windows, PIPE-based capture can hang when Blender spawns
    internal worker threads that inherit the anonymous pipe handle; the pipe
    stays open until every handle-holder exits, blocking communicate().
    File redirection avoids this entirely.  Diagnostic data is in the JSON
    snapshots written by --debug-snapshots and the script's --log file.

    Returns (returncode, "") — empty stderr placeholder; callers only check rc.
    """
    # Blender console output (not the script log) goes here
    stdout_log = log_path.parent / "blender_stdout.log"
    cmd = [
        blender,
        "--background",
        "--python",
        str(_SCRIPT_PY),
        "--",
        str(model_path),
        str(skin_path),
        "--mode",
        "modifier",
        "--projection",
        projection,
        "--debug-snapshots",
        "--snapshots-dir",
        str(snapshots_dir),
        "--log",
        str(log_path),
    ]
    # Windows: CREATE_NEW_PROCESS_GROUP isolates Blender's process group so
    # Ctrl+C / SIGBREAK sent to the parent don't propagate.  DEVNULL for stdin
    # prevents Blender (or any child thread) from blocking on a read from the
    # parent's console handle – the most common cause of silent hangs when
    # running multiple headless Blender invocations sequentially.
    _win_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    with open(stdout_log, "w", encoding="utf-8", errors="replace") as fout:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,  # no terminal read-back
            stdout=fout,
            stderr=subprocess.STDOUT,
            timeout=300,  # 5-minute hard limit per test case
            creationflags=_win_flags,
        )
    return result.returncode, ""


# ── Snapshot validation ───────────────────────────────────────────────────────
def _validate_snapshots(snapshots_dir: pathlib.Path, expected_class: str) -> dict:
    """Read JSON telemetry from snapshots_dir; compare against expected_class.

    Returns a dict with:
      ok           : bool  — True iff actual_class == expected_class
      actual_class : str
      expected_class: str
      mismatch_flag: bool  — True if Blender itself logged TOPOLOGY MISMATCH
      stages       : list of stage dicts
      remark       : human-readable verdict
    """
    summary_path = snapshots_dir / "session_summary.json"
    classify_path = snapshots_dir / "post_classify.json"

    if not summary_path.exists() and not classify_path.exists():
        return {
            "ok": False,
            "actual_class": "MISSING",
            "expected_class": expected_class,
            "mismatch_flag": False,
            "stages": [],
            "remark": "No snapshot files found — Blender may have crashed. Check log file.",
        }

    stages: list[dict] = []
    actual_class = "UNKNOWN"
    mismatch_flag = False

    if summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as fh:
                summary = json.load(fh)
            stages = summary.get("stages", [])
        except json.JSONDecodeError:
            pass

    if classify_path.exists():
        try:
            with open(classify_path, "r", encoding="utf-8") as fh:
                c = json.load(fh)
            actual_class = c.get("mesh_class", "UNKNOWN")
            mismatch_flag = c.get("topology_mismatch", False)
        except json.JSONDecodeError:
            pass
    elif stages:
        for s in stages:
            if s.get("stage") == "post_classify":
                actual_class = s.get("mesh_class", "UNKNOWN")
                mismatch_flag = s.get("topology_mismatch", False)
                break

    ok = actual_class == expected_class
    if ok and not mismatch_flag:
        remark = f"PASS — classified as {actual_class} (expected {expected_class}), no DNA mismatch."
    elif ok and mismatch_flag:
        remark = (
            f"PASS-with-warning — class {actual_class} correct but Shape DNA flagged "
            f"TOPOLOGY MISMATCH. Check eigenvalue ratio."
        )
    else:
        remark = (
            f"FAIL — classified as {actual_class} but expected {expected_class}. "
            f"{'DNA mismatch also flagged.' if mismatch_flag else ''} "
            f"Review sharp_fraction / z_ratio thresholds in _classify_mesh_topology()."
        )

    return {
        "ok": ok,
        "actual_class": actual_class,
        "expected_class": expected_class,
        "mismatch_flag": mismatch_flag,
        "stages": stages,
        "remark": remark,
    }


# ── Remediation hint generator ────────────────────────────────────────────────
def _remediation_hint(result: dict, case: dict) -> str:
    """Generate a specific code-edit suggestion when a test case fails."""
    if result["ok"] and not result["mismatch_flag"]:
        return ""

    actual = result["actual_class"]
    expected = case["expected_class"]
    features: dict = {}
    for s in result["stages"]:
        if s.get("stage") == "post_classify" and s.get("features"):
            features = s["features"]
            break

    lines = ["REMEDIATION HINT:"]
    sf = features.get("sharp_fraction")
    zr = features.get("z_ratio")
    cs = features.get("curvature_std")
    chi = features.get("euler_characteristic")

    lines.append(
        f"  Measured: sharp_fraction={sf}, z_ratio={zr}, "
        f"curvature_std={cs}, euler_characteristic={chi}"
    )

    if actual == "FLAT_SHELL" and expected != "FLAT_SHELL":
        lines.append(
            "  → z_ratio too low — part classified as FLAT_SHELL because z_ratio < threshold."
        )
        lines.append(
            "    Try lowering FLAT_SHELL z_ratio upper bound in _classify_mesh_topology()."
        )

    elif actual == "REVOLUTION" and expected != "REVOLUTION":
        lines.append("  → z_ratio ≥ REVOLUTION threshold and sharp_fraction is low.")
        lines.append(
            "    If model is actually PRISMATIC, raise PRISMATIC sharp_fraction threshold."
        )

    elif actual == "PRISMATIC" and expected == "FLAT_SHELL":
        lines.append("  → sharp_fraction is above PRISMATIC threshold for a flat part.")
        lines.append(
            "    Lower PRISMATIC sharp_fraction threshold or raise FLAT_SHELL guard."
        )

    elif actual == "ORGANIC" and expected != "ORGANIC":
        lines.append("  → curvature_std is above ORGANIC threshold.")
        lines.append(
            "    If this is not organic, raise the ORGANIC curvature_std entry threshold."
        )

    if result["mismatch_flag"]:
        lines.append(
            "  → Shape DNA TOPOLOGY MISMATCH: λ1/λ2 ratio contradicts classifier."
        )
        lines.append("    Check _compute_shape_dna() logs for eigenvalue details.")

    return "\n".join(lines)


# ── Main orchestrator ─────────────────────────────────────────────────────────
def run(cases: list[dict] | None = None, render_heatmap: bool = False) -> int:
    """Run the full debug pipeline.  Returns 0 if all cases pass, 1 otherwise."""
    if cases is None:
        cases = TEST_CASES

    blender_exe = _find_blender()
    skin_path = _find_skin()
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = _REPO_ROOT / "scripts" / "debug_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  QIDIStudio AI Debug Pipeline  —  run {run_id}")
    print(f"  Blender : {blender_exe}")
    print(f"  Skin    : {skin_path}")
    print(f"  Cases   : {len(cases)}")
    print(f"  Output  : {run_dir}")
    print(f"{'='*70}\n")

    all_results: list[dict] = []
    any_failure = False

    with tempfile.TemporaryDirectory(
        prefix="qidi_debug_stl_",
        ignore_cleanup_errors=True,  # Windows AV/indexer may hold temp dir briefly
    ) as tmp_stl_dir:
        tmp = pathlib.Path(tmp_stl_dir)

        for i, case in enumerate(cases, 1):
            name = case["name"]
            model_3mf = case["model"]
            expected = case["expected_class"]
            proj = case.get("projection", "auto")

            print(f"[{i}/{len(cases)}] {name}")
            print(f"         model    : {model_3mf}")
            print(f"         expected : {expected}")

            # Skip missing files gracefully
            if not pathlib.Path(model_3mf).exists():
                msg = f"SKIP — model file not found: {model_3mf}"
                print(f"         {msg}\n")
                all_results.append(
                    {
                        "name": name,
                        "ok": None,
                        "remark": msg,
                        "model": model_3mf,
                    }
                )
                continue

            # Extract STL from 3MF (or use .3mf directly if Blender supports it)
            model_path_for_blender = model_3mf
            extracted = _extract_stl_from_3mf(model_3mf, tmp)
            if extracted:
                model_path_for_blender = str(extracted)
                print(f"         extracted: {extracted.name}")

            # Per-case output dirs
            case_dir = run_dir / name
            snap_dir = case_dir / "snapshots"
            log_path = case_dir / "blender.log"
            case_dir.mkdir(parents=True, exist_ok=True)
            snap_dir.mkdir(parents=True, exist_ok=True)

            # Run Blender
            print("         running Blender...", end=" ", flush=True)
            try:
                rc, blender_stderr = _run_blender(
                    blender_exe,
                    model_path_for_blender,
                    str(skin_path),
                    snap_dir,
                    log_path,
                    projection=proj,
                )
                print(f"rc={rc}")
            except subprocess.TimeoutExpired as _te:
                # Blender exceeded the 300s wall-clock limit.  Flag the case as
                # failed so the report is still written, then continue to the
                # next case.  Caller should check blender.log for the last stage
                # that was reached before the timeout.
                rc = -1
                blender_stderr = (
                    f"TIMEOUT: Blender exceeded {_te.timeout:.0f}s limit. "
                    f"Check {log_path} for last completed stage."
                )
                print(f"rc=TIMEOUT (>{_te.timeout:.0f}s)")

            # Stage output STL to source 3DPrinting directory so the viewer
            # always shows the latest run (temp dir is cleaned up on exit).
            if rc == 0 and extracted:
                src_stl_dir = pathlib.Path(model_3mf).parent
                dest_suffix = "_texture_modifier.stl"
                # Blender writes: <extracted_stem>_texture_modifier.stl in tmp
                for candidate in tmp.glob("*" + dest_suffix):
                    dest = src_stl_dir / f"{pathlib.Path(model_3mf).stem}{dest_suffix}"
                    try:
                        import shutil

                        shutil.copy2(str(candidate), str(dest))
                        print(f"         staged   : {dest.name} -> {src_stl_dir}")
                    except Exception as _ce:
                        print(f"         WARNING: could not stage modifier STL: {_ce}")
                    break  # only copy the first match

            # Validate snapshots
            validation = _validate_snapshots(snap_dir, expected)
            hint = _remediation_hint(validation, case)

            ok_str = "PASS" if validation["ok"] else "FAIL"
            print(f"         result   : {ok_str} — {validation['remark']}")
            if hint:
                for hline in hint.split("\n"):
                    print(f"         {hline}")
            print()

            if not validation["ok"]:
                any_failure = True

            all_results.append(
                {
                    "name": name,
                    "model": model_3mf,
                    "expected_class": expected,
                    "actual_class": validation["actual_class"],
                    "ok": validation["ok"],
                    "mismatch_flag": validation["mismatch_flag"],
                    "remark": validation["remark"],
                    "remediation": hint,
                    "blender_rc": rc,
                    "snapshots_dir": str(snap_dir),
                    "log": str(log_path),
                    "notes": case.get("notes", ""),
                    "stages": validation["stages"],
                }
            )

        # ── Write reports (inside with-block to survive temp dir cleanup) ─────
        print("DEBUG: writing reports...", flush=True)
        summary = {
            "run_id": run_id,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "blender": blender_exe,
            "skin": str(skin_path),
            "all_pass": not any_failure,
            "cases": all_results,
        }
        json_report = run_dir / "ai_debug_report.json"
        txt_report = run_dir / "ai_debug_report.txt"

        with open(json_report, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)

        # Human-readable / AI-readable text report
        lines = [
            f"QIDIStudio Texture Pipeline — AI Debug Report",
            f"Run   : {run_id}",
            f"Date  : {summary['timestamp']}",
            f"Result: {'ALL PASS' if not any_failure else 'FAILURES DETECTED'}",
            "",
            "═" * 70,
        ]
        for r in all_results:
            ok_str = "PASS" if r["ok"] else ("SKIP" if r["ok"] is None else "FAIL")
            lines += [
                f"",
                f"[{ok_str}] {r['name']}",
                f"  model    : {r['model']}",
                f"  expected : {r.get('expected_class', 'n/a')}",
                f"  actual   : {r.get('actual_class', 'n/a')}",
                f"  verdict  : {r['remark']}",
            ]
            if r.get("remediation"):
                for l in r["remediation"].split("\n"):
                    lines.append(f"  {l}")
            if r.get("notes"):
                lines.append(f"  notes    : {r['notes']}")

            # Feature dump from post_classify stage
            for s in r.get("stages", []):
                if s.get("stage") == "post_classify":
                    f_ = s.get("features", {})
                    lines.append(
                        f"  features : sharp={f_.get('sharp_fraction'):.3f}  "
                        f"z_ratio={f_.get('z_ratio'):.3f}  "
                        f"curv_std={f_.get('curvature_std'):.3f}  "
                        f"chi={f_.get('euler_characteristic')}"
                    )
                    g = s.get("geometry", {})
                    lines.append(
                        f"  geometry : {g.get('verts')} verts  "
                        f"{g.get('polys')} polys  "
                        f"bbox={g.get('bbox_mm')} mm"
                    )
                    break

        lines += [
            "",
            "═" * 70,
            "",
            "To diagnose: read this file in a Copilot session and inspect",
            "  resources/scripts/apply_texture_bpy.py → _classify_mesh_topology()",
            "  Adjust match/case thresholds based on measured feature values above.",
            "",
        ]

        with open(txt_report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

        print(f"\nReports written:")
        print(f"  {json_report}")
        print(f"  {txt_report}")
        print(
            f"\nOverall: {'ALL PASS' if not any_failure else 'FAILURES -- see report for remediation hints'}"
        )

    # ── END TemporaryDirectory with-block ─────────────────────────────────────

    return 1 if any_failure else 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Autonomous AI debug harness for apply_texture_bpy.py"
    )
    ap.add_argument(
        "--case",
        action="append",
        default=None,
        help="Run only this case name (repeat for multiple). Default: all cases.",
    )
    ap.add_argument(
        "--render-heatmap",
        action="store_true",
        help="Also render curvature heatmap PNGs via EEVEE (slow).",
    )
    args = ap.parse_args()

    selected = TEST_CASES
    if args.case:
        names = set(args.case)
        selected = [c for c in TEST_CASES if c["name"] in names]
        if not selected:
            print(f"ERROR: no cases matched {args.case}")
            print(f"Available: {[c['name'] for c in TEST_CASES]}")
            sys.exit(2)

    sys.exit(run(selected, render_heatmap=args.render_heatmap))
