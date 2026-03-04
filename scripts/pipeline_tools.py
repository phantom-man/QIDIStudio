"""
scripts/pipeline_tools.py — Domain tools for Gemini's autonomous texture pipeline.

These plain Python functions are registered as FunctionDeclarations so Gemini
can call them during its agent loop (via google.genai's computer-use-preview
function-calling interface).  Each function has a typed signature and a
docstring that becomes the tool description Gemini reads.

Tool inventory
--------------
  run_texture_pipeline   — Apply displacement skin to an STL via apply_skin.py
  run_blender_bake       — Bake UVs + texture via Blender headless
  assess_quality         — Score mesh quality (uniformity, seam, coverage)
  reload_part            — Signal pipeline to hot-swap mesh in the visualizer
  approve_and_export     — Approve a result and export final artefacts
  list_available_parts   — Query the part registry
  list_available_skins   — Discover skin PNGs in resources/assets
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_APPLY_SKIN_PY = _SCRIPTS_DIR / "apply_skin.py"
_APPLY_BPY_SCRIPT = _REPO_ROOT / "resources" / "scripts" / "apply_texture_bpy.py"
_ASSETS_DIR = _REPO_ROOT / "resources" / "assets"
_EXPORT_DIR = _SCRIPTS_DIR / "pipeline_exports"

# ── Cross-session quality metrics log (stdlib-only, no lancedb dependency) ───
# memory/harvest_quality.py picks this JSONL up and indexes rows to LanceDB.
_QUALITY_METRICS_JSONL = _SCRIPTS_DIR / "quality_metrics.jsonl"


def _log_quality_metric(result: dict[str, Any]) -> None:
    """Append a quality assessment result to the persistent JSONL metrics log.

    Written in append mode so cross-session history accumulates.
    Silently swallows write errors to avoid disrupting the pipeline.
    """
    import datetime  # noqa: PLC0415

    try:
        entry = {
            **result,
            "logged_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        with _QUALITY_METRICS_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # never let logging blow up the pipeline


# ── Optional PyTorch pre-flight scorer ───────────────────────────────────────
# agents/ lives at repo root — add to path so the import resolves whether this
# module is imported from scripts/ or run directly.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from agents.torch_tools import (
        predict_texture_quality_from_uv_stats as _predict_tex_quality,
    )

    _TORCH_PREFLIGHT_AVAILABLE = True
except Exception:
    _predict_tex_quality = None  # type: ignore[assignment]
    _TORCH_PREFLIGHT_AVAILABLE = False

# An optional reference to the live VisualizerComputer instance so
# reload_part() can call computer.load_stl() directly.
# Set by autonomous_pipeline.py before registering tools:
#   pipeline_tools.ACTIVE_COMPUTER = computer
ACTIVE_COMPUTER: Any | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_blender() -> str:
    """Locate Blender executable (mirrors logic in ai_debug_pipeline.py)."""
    env = os.environ.get("QIDI_BLENDER_EXE", "")
    if env and pathlib.Path(env).is_file():
        return env
    candidates = [
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        "/usr/bin/blender",
        "/Applications/Blender.app/Contents/MacOS/Blender",
    ]
    for c in candidates:
        if pathlib.Path(c).is_file():
            return c
    raise FileNotFoundError(
        "Blender not found. Set QIDI_BLENDER_EXE env var or install to a default location."
    )


def _resolve_python() -> str:
    """Return the Python interpreter that has trimesh/numpy/scipy for scripts.

    Prefers .venv (project venv with all 3D deps) over the running interpreter,
    which may be memory_env (google-genai only).
    """
    venv_py = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        return str(venv_py)
    venv_py_unix = _REPO_ROOT / ".venv" / "bin" / "python"
    if venv_py_unix.is_file():
        return str(venv_py_unix)
    return sys.executable


# ── Tool 1: run_texture_pipeline ──────────────────────────────────────────────


def run_texture_pipeline(
    part_name: str,
    stl_path: str,
    skin_path: str,
    tile_mm: float = 15.0,
    relief: float = 1.0,
    gamma: float = 0.7,
    max_edge: float = 2.0,
    projection: str = "auto",
    invert: bool = True,
) -> dict[str, Any]:
    """Apply a displacement-map skin texture to a 3D part STL.

    Runs apply_skin.py as a subprocess.  The CLI takes the source STL and a
    greyscale PNG skin image, applies UV projection and displacement, and writes
    a new 3MF file.  The output path is reported as SKIN_OUTPUT on stdout.

    Args:
        part_name:  Canonical part name (used only for logging).
        stl_path:   Absolute path to the source STL file.
        skin_path:  Absolute path to the skin PNG (greyscale, seamless tile).
        tile_mm:    Tile size in millimetres (default 15). Smaller = denser
                    coverage (try 8-12 for fine detail); larger = coarser feel.
        relief:     Displacement depth in mm (default 1.0). Increase to 1.5-2.0
                    if scales look flat; decrease to 0.3-0.5 for subtle bumps.
        gamma:      Gamma curve for the displacement map (default 0.7). Values
                    <1 round dome profiles (soft scales); >1 sharpen/spike them.
        max_edge:   Maximum edge length for mesh subdivision (default 2.0 mm).
        projection: UV projection mode — "auto" (smart-pick), "cylindrical"
                    (eliminates seams on tubes/nozzles), "triplanar" (blocky/
                    flat parts).  Use "cylindrical" when seam_score < 0.7.
        invert:     Invert the heightmap so dark regions become raised domes
                    (default True). Set False if texture looks like holes.

    Returns:
        {"output_3mf": <path or "">, "exit_code": int, "log": str,
         "part_name": part_name, "status": "ok"|"error",
         "params_used": {tile_mm, relief, gamma, projection, invert}}
    """
    if not _APPLY_SKIN_PY.exists():
        return {
            "part_name": part_name,
            "exit_code": 2,
            "status": "error",
            "log": f"apply_skin.py not found at {_APPLY_SKIN_PY}",
            "output_3mf": "",
        }
    cmd = [
        _resolve_python(),
        str(_APPLY_SKIN_PY),
        str(stl_path),
        str(skin_path),
        "--tile-size",
        str(tile_mm),
        "--relief",
        str(relief),
        "--gamma",
        str(gamma),
        "--max-edge",
        str(max_edge),
        "--projection",
        str(projection),
    ]
    if not invert:
        cmd.append("--no-invert")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
        combined = (result.stdout or "") + (result.stderr or "")
        # Parse output path from sentinel line
        output_3mf = ""
        for line in combined.splitlines():
            if line.startswith("SKIN_OUTPUT:"):
                output_3mf = line.split(":", 1)[1].strip()
                break
        status = "ok" if result.returncode == 0 else "error"
        return {
            "part_name": part_name,
            "exit_code": result.returncode,
            "status": status,
            "output_3mf": output_3mf,
            "log": combined[-4000:],  # truncate for token budget
            "params_used": {
                "tile_mm": tile_mm,
                "relief": relief,
                "gamma": gamma,
                "max_edge": max_edge,
                "projection": projection,
                "invert": invert,
            },
        }
    except subprocess.TimeoutExpired:
        return {
            "part_name": part_name,
            "exit_code": -1,
            "status": "error",
            "output_3mf": "",
            "log": "Timeout after 180 s",
        }
    except Exception as exc:
        return {
            "part_name": part_name,
            "exit_code": -1,
            "status": "error",
            "output_3mf": "",
            "log": str(exc),
        }


# ── Tool 2: run_blender_bake ──────────────────────────────────────────────────


def run_blender_bake(
    part_name: str,
    model_3mf: str,
    skin_path: str,
    projection: str = "auto",
    resolution: int = 512,
) -> dict[str, Any]:
    """Bake UV texture onto a 3MF model using Blender in background mode.

    Invokes apply_texture_bpy.py inside Blender's Python environment with
    --background.  Writes snapshot JSON and a log file to a timestamped
    debug_runs sub-directory.

    Args:
        part_name:  Canonical part name (used for logging and output dir naming).
        model_3mf:  Absolute path to the source 3MF file.
        skin_path:  Absolute path to the skin PNG.
        projection: UV projection type — "auto", "cylinder", "sphere", or "box".
        resolution: Bake texture resolution in pixels (256, 512, 1024, 2048).

    Returns:
        {"exit_code": int, "status": "ok"|"error", "log_file": str,
         "snapshots_dir": str, "part_name": part_name}
    """
    import datetime  # noqa: PLC0415

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = _SCRIPTS_DIR / "debug_runs" / f"bake_{part_name}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = run_dir / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    log_path = run_dir / f"{part_name}_bake.log"
    stdout_log = run_dir / "blender_stdout.log"

    try:
        blender = _find_blender()
    except FileNotFoundError as exc:
        return {
            "part_name": part_name,
            "exit_code": -1,
            "status": "error",
            "log_file": "",
            "snapshots_dir": "",
            "log": str(exc),
        }

    if not _APPLY_BPY_SCRIPT.exists():
        return {
            "part_name": part_name,
            "exit_code": -1,
            "status": "error",
            "log_file": str(log_path),
            "snapshots_dir": str(snap_dir),
            "log": f"apply_texture_bpy.py not found at {_APPLY_BPY_SCRIPT}",
        }
    cmd = [
        blender,
        "--background",
        "--python",
        str(_APPLY_BPY_SCRIPT),
        "--",
        str(model_3mf),
        str(skin_path),
        "--mode",
        "modifier",
        "--projection",
        projection,
        "--debug-snapshots",
        "--snapshots-dir",
        str(snap_dir),
        "--log",
        str(log_path),
    ]
    _win_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    try:
        with open(stdout_log, "w", encoding="utf-8", errors="replace") as fout:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=fout,
                stderr=subprocess.STDOUT,
                timeout=300,
                creationflags=_win_flags,
            )
        status = "ok" if result.returncode == 0 else "error"
        return {
            "part_name": part_name,
            "exit_code": result.returncode,
            "status": status,
            "log_file": str(log_path),
            "snapshots_dir": str(snap_dir),
            "blender_stdout": str(stdout_log),
        }
    except subprocess.TimeoutExpired:
        return {
            "part_name": part_name,
            "exit_code": -1,
            "status": "error",
            "log_file": str(log_path),
            "snapshots_dir": str(snap_dir),
            "log": "Blender timeout after 300 s",
        }
    except Exception as exc:
        return {
            "part_name": part_name,
            "exit_code": -1,
            "status": "error",
            "log_file": str(log_path),
            "snapshots_dir": str(snap_dir),
            "log": str(exc),
        }


# ── Tool 3: assess_quality ────────────────────────────────────────────────────


def assess_quality(
    part_name: str,
    stl_path: str,
    skin_path: str = "",
) -> dict[str, Any]:
    """Analyse texture-displacement quality of a processed STL mesh.

    Examines vertex displacement magnitude distribution, seam indicator
    (boundary edge ratio), and surface coverage.  If *skin_path* is supplied,
    also runs the Fourier-based aesthetic beauty scorer on the skin PNG.

    Args:
        part_name: Canonical part name (used for logging only).
        stl_path:  Absolute path to the *displaced* mesh to evaluate (.3mf or .stl).
        skin_path: Optional path to the skin PNG used to produce this mesh.
                   When provided, beauty_score, symmetry_score, spectral_entropy
                   and in_golden_zone are included in the result.

    Returns:
        {"part_name": str,
         "uniformity_score": float,   # 0.0–1.0 (1.0 = perfectly uniform)
         "seam_score": float,         # 0.0–1.0 (1.0 = no visible seams)
         "artifact_score": float,     # 0.0–1.0 (1.0 = no artifacts)
         "coverage_pct": float,       # 0–100
         "face_count": int,
         "is_watertight": bool,
         "verdict": "PASS"|"FAIL"|"MARGINAL",
         "notes": str,
         "beauty_score": float|None,  # Leder 2004 B(s,σ) — only if skin_path given
         "beauty_verdict": str|None,  # "BEAUTIFUL"|"GOOD"|"ACCEPTABLE"|"POOR"
         "symmetry_score": float|None,# FFT phase coherence 0–1
         "spectral_entropy": float|None, # bits
         "in_golden_zone": bool|None} # S>0.9 AND H_s>4.0
    """
    import trimesh  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    path = pathlib.Path(stl_path)
    if not path.exists():
        return {
            "part_name": part_name,
            "verdict": "FAIL",
            "uniformity_score": 0.0,
            "seam_score": 0.0,
            "artifact_score": 0.0,
            "coverage_pct": 0.0,
            "face_count": 0,
            "is_watertight": False,
            "notes": f"STL not found: {stl_path}",
        }
    try:
        mesh = trimesh.load(str(path), force="mesh")

        # ── 1. Coverage — faces with non-zero displacement ──────────────────
        # We treat any vertex displaced from a reference origin as "covered".
        # A simple proxy: fraction of faces that have non-degenerate area.
        face_areas = mesh.area_faces
        total_faces = len(face_areas)
        nonzero_faces = int((face_areas > 1e-6).sum())
        coverage_pct = round(100.0 * nonzero_faces / max(total_faces, 1), 1)

        # ── 2. Uniformity — std-dev of face areas (lower cv = more uniform) ─
        # Displaced meshes typically have cv in 0.8–2.0 due to the displacement
        # pattern itself (not an artifact).  Divide by 4.0 so that cv=0→1.0,
        # cv=2.0→0.5, cv=4.0→0.0.  Using 3.0 was too punishing for heavily-
        # subdivided armadillo-plate geometry which naturally runs cv ~1.0–1.2.
        area_std = float(np.std(face_areas)) if total_faces > 0 else 0.0
        area_mean = float(np.mean(face_areas)) if total_faces > 0 else 1.0
        cv = area_std / max(area_mean, 1e-12)  # coefficient of variation
        uniformity_score = round(max(0.0, 1.0 - cv / 4.0), 3)

        # ── 3. Seam score — boundary-edge ratio ────────────────────────────
        # Interior edges appear in exactly 2 faces (face_adjacency counts them).
        # Boundary edges = total_unique − interior.  Open meshes (texture
        # modifier STLs) always have some boundary at attachment faces; use a
        # lenient multiplier so that expected open edges don't tank the score.
        try:
            interior_edges = len(mesh.face_adjacency)  # pairs sharing an edge
            total_edges = len(mesh.edges_unique)
            boundary_edges = max(0, total_edges - interior_edges)
            seam_ratio = boundary_edges / max(total_edges, 1)
            # Multiply by 2 (not 10): an open shell with ~40% boundary edges
            # should still score ~0.2 rather than 0.0.
            seam_score = round(max(0.0, 1.0 - min(seam_ratio * 2, 1.0)), 3)
        except Exception:
            seam_score = 0.5  # neutral fallback

        # ── 4. Artifact score — degenerate + flipped faces ─────────────────
        degen = int((face_areas < 1e-8).sum())
        degen_ratio = degen / max(total_faces, 1)
        artifact_score = round(max(0.0, 1.0 - min(degen_ratio * 100, 1.0)), 3)

        # ── 5. Verdict ──────────────────────────────────────────────────────
        if uniformity_score >= 0.65 and seam_score >= 0.6 and artifact_score >= 0.8:
            verdict = "PASS"
        elif uniformity_score < 0.4 or artifact_score < 0.5:
            verdict = "FAIL"
        else:
            verdict = "MARGINAL"

        notes = (
            f"cv={cv:.3f} boundary_ratio={1-seam_score:.3f} "
            f"degen_faces={degen}/{total_faces}"
        )

        # ── 6. Beauty score — FFT aesthetic quality of the skin PNG ──────────
        beauty_score: float | None = None
        symmetry_score: float | None = None
        spectral_entropy_val: float | None = None
        in_golden_zone: bool | None = None
        beauty_verdict: str | None = None
        beauty_screenshot_path: str | None = None
        _beauty_threshold_used: float = 0.62  # default organic GOOD threshold
        if skin_path and pathlib.Path(skin_path).is_file():
            try:
                if str(_SCRIPTS_DIR) not in sys.path:
                    sys.path.insert(0, str(_SCRIPTS_DIR))
                from ai_beauty_scorer import (  # noqa: PLC0415
                    analyse_skin_file,
                    BEAUTY_GOOD,
                    BEAUTY_GOOD_ORGANIC,
                    SYMMETRY_ACCEPTABLE,
                )

                br = analyse_skin_file(skin_path)
                beauty_score = round(br.beauty_score, 3)
                symmetry_score = round(br.symmetry_score, 3)
                spectral_entropy_val = round(br.spectral_entropy, 3)
                in_golden_zone = br.in_golden_zone
                beauty_verdict = br.verdict
                notes += (
                    f" | beauty={beauty_score} [{beauty_verdict}]"
                    f" S={symmetry_score} H={spectral_entropy_val}"
                    + (" \u2605GOLDEN" if in_golden_zone else "")
                )

                # Gate PASS on beauty: a geometrically clean but ugly skin fails.
                # For organic skins (S < SYMMETRY_ACCEPTABLE), use a lower threshold
                # since their aesthetic comes from complexity, not Fourier symmetry.
                beauty_threshold = (
                    BEAUTY_GOOD_ORGANIC
                    if symmetry_score is not None
                    and symmetry_score < SYMMETRY_ACCEPTABLE
                    else BEAUTY_GOOD
                )
                _beauty_threshold_used = beauty_threshold
                if verdict == "PASS" and beauty_score < beauty_threshold:
                    verdict = "MARGINAL"
                    is_organic = beauty_threshold == BEAUTY_GOOD_ORGANIC
                    cat = "organic" if is_organic else "geometric"
                    notes += (
                        f" | beauty below {cat} threshold"
                        f" ({beauty_score:.3f} < {beauty_threshold})"
                    )

                # Save a viewport screenshot when beauty is GOOD or better so the
                # user can visually assess whether the AI is correct.
                if beauty_score >= BEAUTY_GOOD and ACTIVE_COMPUTER is not None:
                    try:
                        import datetime  # noqa: PLC0415

                        review_dir = _EXPORT_DIR / "beauty_review"
                        review_dir.mkdir(parents=True, exist_ok=True)
                        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        shot_path = review_dir / (
                            f"{part_name}_{beauty_verdict.lower()}_{beauty_score:.3f}_{ts}.png"
                        )
                        state = ACTIVE_COMPUTER.current_state()
                        shot_path.write_bytes(state.screenshot)
                        beauty_screenshot_path = str(shot_path)
                        notes += f" | screenshot={shot_path.name}"
                    except Exception as sexp:
                        notes += f" | screenshot_error={sexp}"

            except Exception as bexc:
                notes += f" | beauty_error={bexc}"

        result = {
            "part_name": part_name,
            "uniformity_score": uniformity_score,
            "seam_score": seam_score,
            "artifact_score": artifact_score,
            "coverage_pct": coverage_pct,
            "face_count": total_faces,
            "is_watertight": bool(mesh.is_watertight),
            "verdict": verdict,
            "notes": notes,
            "beauty_score": beauty_score,
            "beauty_verdict": beauty_verdict,
            "symmetry_score": symmetry_score,
            "spectral_entropy": spectral_entropy_val,
            "in_golden_zone": in_golden_zone,
            "beauty_screenshot_path": beauty_screenshot_path,
            # ── Action hint for the agent ──────────────────────────────────
            # When verdict is already PASS and beauty meets the threshold,
            # the agent should call approve_and_export immediately rather than
            # attempting further iterations.  Organic skins (S < 0.65) have a
            # natural symmetry ceiling around S≈0.43; tuning cannot push them
            # above BEAUTY_BEAUTIFUL=0.87.
            "action_hint": (
                "PASS achieved and beauty is GOOD. Call approve_and_export() now "
                "and record_winner() to save this result. Do NOT run_texture_pipeline "
                "again — organic symmetry is at its natural ceiling for this skin."
            ) if verdict == "PASS" and beauty_score is not None
              and beauty_score >= _beauty_threshold_used
            else None,
        }
        _log_quality_metric(result)
        return result
    except Exception as exc:
        return {
            "part_name": part_name,
            "verdict": "FAIL",
            "uniformity_score": 0.0,
            "seam_score": 0.0,
            "artifact_score": 0.0,
            "coverage_pct": 0.0,
            "face_count": 0,
            "is_watertight": False,
            "notes": f"Error during analysis: {exc}",
        }


# ── Tool 4: reload_part ───────────────────────────────────────────────────────


def reload_part(part_name: str, stl_path: str) -> dict[str, Any]:
    """Reload the STL for a part in the live 3D visualizer.

    Calls ACTIVE_COMPUTER.load_stl() if a VisualizerComputer is registered.
    The visualizer will hot-swap the mesh so Gemini's next screenshot shows the
    updated geometry without restarting the plotter.

    Args:
        part_name: Canonical part name to update in the visualizer.
        stl_path:  Absolute path to the new STL file.

    Returns:
        {"part_name": str, "stl_path": str, "status": "reloaded"|"no_computer"|"error"}
    """
    if ACTIVE_COMPUTER is None:
        return {"part_name": part_name, "stl_path": stl_path, "status": "no_computer"}
    try:
        ACTIVE_COMPUTER.load_stl(part_name, stl_path)
        return {"part_name": part_name, "stl_path": stl_path, "status": "reloaded"}
    except Exception as exc:
        return {
            "part_name": part_name,
            "stl_path": stl_path,
            "status": "error",
            "error": str(exc),
        }


# ── Tool 5: approve_and_export ────────────────────────────────────────────────


def approve_and_export(
    part_name: str,
    stl_path: str,
    output_dir: str = "",
) -> dict[str, Any]:
    """Mark a part's texture result as approved and copy to the export directory.

    Writes an approval_manifest.json alongside the exported STL so downstream
    systems can track provenance.

    Args:
        part_name:  Canonical part name.
        stl_path:   Absolute path to the approved STL.
        output_dir: Destination directory. Defaults to scripts/pipeline_exports/.

    Returns:
        {"part_name": str, "exported_to": str, "status": "approved"|"error",
         "manifest": str}
    """
    import datetime  # noqa: PLC0415

    dest_dir = pathlib.Path(output_dir) if output_dir else _EXPORT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(stl_path)
    if not src.exists():
        return {
            "part_name": part_name,
            "exported_to": "",
            "status": "error",
            "error": f"Source STL not found: {stl_path}",
        }
    try:
        dest_stl = dest_dir / f"{part_name}_final.stl"
        shutil.copy2(str(src), str(dest_stl))
        manifest = {
            "part_name": part_name,
            "source_stl": str(src),
            "export_stl": str(dest_stl),
            "approved_at": datetime.datetime.now().isoformat(),
            "status": "approved",
        }
        manifest_path = dest_dir / f"{part_name}_approval_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            "part_name": part_name,
            "exported_to": str(dest_stl),
            "status": "approved",
            "manifest": str(manifest_path),
        }
    except Exception as exc:
        return {
            "part_name": part_name,
            "exported_to": "",
            "status": "error",
            "error": str(exc),
        }


# ── Tool 6: list_available_parts ─────────────────────────────────────────────


def list_available_parts() -> dict[str, Any]:
    """List all 3D parts registered in the pipeline's PARTS dictionary.

    No arguments needed.  Returns canonical part names plus their STL paths
    and topology profiles so Gemini can choose which part to work on.

    Returns:
        {"parts": [{"name": str, "stl_exists": bool, "profile": str,
                    "label": str, "stl_path": str}, ...]}
    """
    # Import lazily to avoid circular import when pipeline_tools is imported
    # before visualizer_computer.
    try:
        from visualizer_computer import PARTS  # noqa: PLC0415
    except ImportError:
        return {"parts": [], "error": "visualizer_computer not importable"}
    results = []
    for name, info in PARTS.items():
        stl = pathlib.Path(info.get("stl", ""))
        results.append(
            {
                "name": name,
                "stl_exists": stl.exists(),
                "stl_path": str(stl),
                "profile": info.get("profile", "UNKNOWN"),
                "label": info.get("label", name),
            }
        )
    return {"parts": results}


# ── Tool 7: list_available_skins ─────────────────────────────────────────────


def list_available_skins() -> dict[str, Any]:
    """List texture skin PNG files available in resources/assets.

    Gemini can use this to discover available skins before calling
    run_texture_pipeline.  Returns paths and file sizes.

    Returns:
        {"skins": [{"name": str, "path": str, "size_kb": float}, ...]}
    """
    if not _ASSETS_DIR.exists():
        return {"skins": [], "error": f"Assets dir not found: {_ASSETS_DIR}"}
    skins = []
    for png in sorted(_ASSETS_DIR.rglob("*.png")):
        skins.append(
            {
                "name": png.stem,
                "path": str(png),
                "size_kb": round(png.stat().st_size / 1024, 1),
            }
        )
    return {"skins": skins}


# ── Tool 8: inspect_and_assess (compound — efficiency boost) ─────────────────


def inspect_and_assess(
    part_name: str,
    stl_path: str,
    skin_path: str = "",
) -> dict[str, Any]:
    """Rotate to 6 cardinal views AND run quality assessment in a single call.

    This compound tool replaces the inefficient pattern of 6 separate
    rotate_view() calls followed by assess_quality() — saving 6 iterations.

    It captures cardinal views internally (0°, 90°, 180°, 270° azimuth,
    top, bottom), then runs assess_quality() and returns the combined result.
    The final view is set to azimuth=45°/elevation=30° (a good overview angle)
    so the next screenshot Gemini sees is a useful summary view.

    Args:
        part_name: Canonical part name.
        stl_path:  Absolute path to the displaced mesh to evaluate.
        skin_path: Optional path to the skin PNG for beauty scoring.

    Returns:
        All fields from assess_quality() PLUS:
        {"views_captured": int, "angles_inspected": list}
    """
    views_captured = 0
    angles_inspected = []

    if ACTIVE_COMPUTER is not None:
        cardinal_angles = [
            (0, 0),
            (90, 0),
            (180, 0),
            (270, 0),
            (0, 90),
            (0, -90),
        ]
        for az, el in cardinal_angles:
            try:
                ACTIVE_COMPUTER.rotate_view(az, el)
                views_captured += 1
                angles_inspected.append((az, el))
            except Exception:
                pass
        # Set a pleasant summary angle for the next iteration's screenshot
        try:
            ACTIVE_COMPUTER.rotate_view(45, 30)
        except Exception:
            pass

    quality = assess_quality(part_name, stl_path, skin_path)
    quality["views_captured"] = views_captured
    quality["angles_inspected"] = angles_inspected
    return quality


# ── Tool 9: record_winner (Spectral DNA library write) ────────────────────────

_DNA_LIBRARY_PATH = _EXPORT_DIR / "texture_dna_library.json"


def record_winner(
    part_name: str,
    stl_path: str,
    skin_name: str,
    params: dict,
    quality: dict,
) -> dict[str, Any]:
    """Record winning texture parameters to the Spectral DNA library.

    Call this immediately after a PASS verdict is confirmed.  Saves the
    winning parameter set keyed by part_name for future lookup via
    load_best_params().  Over time this library becomes the starting-point
    oracle: future runs skip the exploration phase and jump straight to
    near-optimal settings.

    Args:
        part_name: Canonical part name.
        stl_path:  Path to the source STL (used to extract geometry signature).
        skin_name: Short skin identifier e.g. 'armadillo_plates_01'.
        params:    Dict of texture params (tile_mm, relief, gamma, projection,
                   invert, max_edge).
        quality:   Dict from assess_quality() (uniformity_score, seam_score,
                   beauty_score, verdict, etc.).

    Returns:
        {"status": "ok", "library_path": str, "entries": int, "part": part_name}
    """
    import datetime  # noqa: PLC0415

    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    library: dict = {}
    if _DNA_LIBRARY_PATH.exists():
        try:
            library = json.loads(_DNA_LIBRARY_PATH.read_text(encoding="utf-8"))
        except Exception:
            library = {}

    # Geometry signature — lightweight fingerprint for matching future parts
    geom_sig: dict = {}
    try:
        import sys as _sys  # noqa: PLC0415

        _venv_sp = _REPO_ROOT / ".venv" / "Lib" / "site-packages"
        if _venv_sp.is_dir() and str(_venv_sp) not in _sys.path:
            _sys.path.insert(1, str(_venv_sp))
        import trimesh as _tm  # type: ignore  # noqa: PLC0415

        mesh = _tm.load(str(stl_path), force="mesh")
        bb = mesh.bounding_box.extents.tolist()
        geom_sig = {
            "bbox_mm": [round(x, 1) for x in bb],
            "surface_area_mm2": round(float(mesh.area), 1),
            "face_count": len(mesh.faces),
            "is_watertight": bool(mesh.is_watertight),
        }
    except Exception as gexc:
        geom_sig = {"error": str(gexc)}

    entry = {
        "part_name": part_name,
        "skin_name": skin_name,
        "params": params,
        "quality": {
            k: v for k, v in quality.items() if isinstance(v, (int, float, str, bool))
        },
        "geometry_signature": geom_sig,
        "recorded_at": datetime.datetime.now().isoformat(),
    }

    # Keep the best entry per part (highest beauty_score, then uniformity)
    existing = library.get(part_name)
    if existing is None or (
        quality.get("beauty_score", 0)
        > existing.get("quality", {}).get("beauty_score", 0)
        or quality.get("uniformity_score", 0)
        > existing.get("quality", {}).get("uniformity_score", 0)
    ):
        library[part_name] = entry

    _DNA_LIBRARY_PATH.write_text(json.dumps(library, indent=2), encoding="utf-8")
    return {
        "status": "ok",
        "library_path": str(_DNA_LIBRARY_PATH),
        "entries": len(library),
        "part": part_name,
    }


# ── Tool 10: load_best_params (Spectral DNA library lookup) ─────────────────


def load_best_params(part_name: str) -> dict[str, Any]:
    """Look up the best known texture parameters for a part from the Spectral DNA library.

    Returns the highest-scoring set of parameters previously recorded via
    record_winner().  Use these as starting values for run_texture_pipeline()
    instead of defaults — this dramatically reduces the iterations needed to
    converge on a good result.

    Args:
        part_name: Canonical part name.

    Returns:
        {"found": bool, "part_name": str, "params": dict, "quality": dict,
         "skin_name": str, "recorded_at": str}
        If not found: {"found": False, "part_name": str, "params": {}}
    """
    if not _DNA_LIBRARY_PATH.exists():
        return {"found": False, "part_name": part_name, "params": {}}
    try:
        library = json.loads(_DNA_LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"found": False, "part_name": part_name, "params": {}}
    entry = library.get(part_name)
    if entry is None:
        return {"found": False, "part_name": part_name, "params": {}}
    return {
        "found": True,
        "part_name": part_name,
        "params": entry.get("params", {}),
        "quality": entry.get("quality", {}),
        "skin_name": entry.get("skin_name", ""),
        "geometry_signature": entry.get("geometry_signature", {}),
        "recorded_at": entry.get("recorded_at", ""),
    }


# ── All tools (for registration) ──────────────────────────────────────────────

ALL_TOOLS = [
    run_texture_pipeline,
    run_blender_bake,
    assess_quality,
    reload_part,
    approve_and_export,
    list_available_parts,
    list_available_skins,
    inspect_and_assess,
    record_winner,
    load_best_params,
    # PyTorch pre-flight scorer — predicts u/s/b from UV stats before Blender render.
    # Falls back gracefully to None if torch not installed; loop skips it at build time.
    *(
        [_predict_tex_quality]
        if _TORCH_PREFLIGHT_AVAILABLE and _predict_tex_quality
        else []
    ),
]
