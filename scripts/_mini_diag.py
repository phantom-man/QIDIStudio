#!/usr/bin/env python3
"""Minimal 2-case test with REVOLUTION cases to find the 4-case hang."""
import sys, pathlib, subprocess, tempfile, json, datetime, traceback

ROOT = pathlib.Path(__file__).parent.parent
OUT = ROOT / "scripts" / "_mini_out.txt"
sys.path.insert(0, str(ROOT))

lines_out = []


def log(msg):
    lines_out.append(msg)
    print(msg, flush=True)


try:
    from scripts.ai_debug_pipeline import (
        _find_blender,
        _find_skin,
        _extract_stl_from_3mf,
        _run_blender,
        _validate_snapshots,
        _remediation_hint,
        TEST_CASES,
        _REPO_ROOT,
    )

    log("Imports OK")

    # Pick just the 2 vacuum cases
    cases = [
        c
        for c in TEST_CASES
        if c["name"] in ("vacuum_nozzle_lower", "vacuum_crevice_nozzle")
    ]
    log(f"Cases: {[c['name'] for c in cases]}")

    blender_exe = _find_blender()
    skin_path = _find_skin()
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = _REPO_ROOT / "scripts" / "debug_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"run_dir: {run_dir}")

    all_results = []
    any_failure = False

    with tempfile.TemporaryDirectory(
        prefix="qidi_mini_", ignore_cleanup_errors=True
    ) as tmp_stl_dir:
        tmp = pathlib.Path(tmp_stl_dir)

        for i, case in enumerate(cases, 1):
            name = case["name"]
            model_3mf = case["model"]
            expected = case["expected_class"]
            proj = case.get("projection", "auto")
            log(f"\n[{i}/{len(cases)}] {name}")

            model_path_for_blender = model_3mf
            extracted = _extract_stl_from_3mf(model_3mf, tmp)
            if extracted:
                model_path_for_blender = str(extracted)
                log(f"  extracted: {extracted.name}")

            case_dir = run_dir / name
            snap_dir = case_dir / "snapshots"
            log_path = case_dir / "blender.log"
            case_dir.mkdir(parents=True, exist_ok=True)
            snap_dir.mkdir(parents=True, exist_ok=True)

            log(f"  running Blender...")
            try:
                rc, _ = _run_blender(
                    blender_exe,
                    model_path_for_blender,
                    str(skin_path),
                    snap_dir,
                    log_path,
                    projection=proj,
                )
                log(f"  rc={rc}")
            except subprocess.TimeoutExpired as te:
                rc = -1
                log(f"  rc=TIMEOUT")

            log(f"  validating snapshots...")
            validation = _validate_snapshots(snap_dir, expected)
            log(f"  hint...")
            hint = _remediation_hint(validation, case)
            ok_str = "PASS" if validation["ok"] else "FAIL"
            log(f"  result: {ok_str} — {validation['remark']}")

            if not validation["ok"]:
                any_failure = True

            entry = {
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
            log(f"  serialisation check...")
            try:
                json.dumps(entry)
                log(f"  serialisation OK")
            except (TypeError, ValueError) as e:
                log(f"  SERIALISATION FAILED: {e}")
                log(f"  Offending entry keys attempted:")
                for k, v in entry.items():
                    try:
                        json.dumps(v)
                    except Exception as ve:
                        log(f"    KEY '{k}' FAILED: {ve}  type={type(v)}")

            all_results.append(entry)
            log(f"  appended to all_results")

        log("\n=== Writing reports ===")
        summary = {
            "run_id": run_id,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "blender": blender_exe,
            "skin": str(skin_path),
            "all_pass": not any_failure,
            "cases": all_results,
        }
        json_report = run_dir / "ai_debug_report.json"
        log(f"Writing JSON to {json_report}")
        with open(json_report, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
        log("JSON written OK")

        txt_report = run_dir / "ai_debug_report.txt"
        log(f"Writing TXT to {txt_report}")
        with open(txt_report, "w", encoding="utf-8") as fh:
            fh.write("MINI REPORT\n")
            fh.write(f"all_pass={not any_failure}\n")
        log("TXT written OK")

    log("\n=== Done ===")
    log(f"Overall: {'ALL PASS' if not any_failure else 'FAILURES'}")

except Exception:
    tb = traceback.format_exc()
    log(f"\nEXCEPTION:\n{tb}")
finally:
    OUT.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"\nOutput saved to: {OUT}")
