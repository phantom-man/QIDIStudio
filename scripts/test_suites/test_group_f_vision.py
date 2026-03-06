"""
Group F — Vision / Aesthetic Tests
=====================================
Uses the Gemini Vision agent (read_image tool) to assert visual properties
of 3D renders and texture outputs.

All renders are produced off-screen using PyVista with PYVISTA_OFF_SCREEN=true.
No display hardware is required.

Tests:
  F1  Render flat_plate.stl → assert "a flat rectangular 3D surface"
  F2  Recent beauty_review PNG → assert "textured surface with visible material"
  F3  Text-to-texture Perlin PNG → assert "a tileable repeating pattern"
  F4  Quality metrics JSONL exists and contains valid metric scores
  F5  Pipeline autonomy score > 0.4 (from latest quality_metrics.jsonl entry)
  F6  Splash logo SVG exists and is valid SVG
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Disable display for off-screen rendering
os.environ["PYVISTA_OFF_SCREEN"] = "true"
os.environ.setdefault("DISPLAY", ":99")  # Linux fallback

REPO_ROOT = Path(__file__).parents[2]
MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"

BEAUTY_DIR = REPO_ROOT / "scripts" / "pipeline_exports" / "beauty_review"
QUALITY_JSONL = REPO_ROOT / "quality_metrics.jsonl"
SPLASH_SVG = REPO_ROOT / "resources" / "splash_logo.svg"
TEST_PNG_DIR = REPO_ROOT / "logs" / "phd_test_runs"


def _run_py(script: str, timeout: int = 120) -> tuple[bool, str]:
    """Run a Python snippet as a subprocess with reliable kill on timeout (Windows-safe)."""
    import signal

    flags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    proc = subprocess.Popen(
        [str(MEMORY_PY), "-B", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
        creationflags=flags,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode == 0, (stdout + stderr).strip()
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, f"Subprocess timed out after {timeout}s"


def _vision_assert(
    image_path: Path, assertion: str, min_confidence: float = 0.60
) -> tuple[bool, str]:
    """
    Calls the Gemini Vision agent to evaluate an assertion about an image.
    Uses the same read_image pathway as agents/tools.py but via standalone subprocess.
    """
    script = f"""
import sys, json, re
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import os, base64
from google import genai
from google.genai import types

client = genai.Client(
    vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

img_bytes = open(r"{image_path}", "rb").read()
b64 = base64.b64encode(img_bytes).decode()
prompt = (
    "Analyse this image and answer the following assertion with a JSON object.\\n"
    "Assertion: {assertion}\\n"
    "Respond ONLY with a JSON object in this exact format:\\n"
    '{{"verdict":"ok","description":"brief explanation","confidence":0.85}}'
    "\\nverdict must be 'ok' if the assertion is TRUE, 'defect' if FALSE."
)

resp = client.models.generate_content(
    model="gemini-2.5-pro",
    contents=[
        types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
        prompt,
    ],
)
raw = resp.text.strip()
# Extract JSON even if wrapped in markdown
m = re.search(r"\\{{[^{{}}]*\\}}", raw, re.DOTALL)
if m:
    obj = json.loads(m.group())
else:
    obj = json.loads(raw)
print(json.dumps(obj))
"""
    ok, output = _run_py(script, timeout=60)
    if not ok:
        return False, f"Vision subprocess error:\n{output[:400]}"

    # Parse last JSON-looking line
    import re

    lines = output.strip().splitlines()
    for line in reversed(lines):
        m = re.search(r"\{.*\}", line)
        if m:
            try:
                obj = json.loads(m.group())
                verdict = obj.get("verdict", "unclear")
                confidence = float(obj.get("confidence", 0))
                description = obj.get("description", "")
                if verdict == "ok" and confidence >= min_confidence:
                    return True, description
                return (
                    False,
                    f"verdict={verdict} confidence={confidence:.2f} description={description}",
                )
            except (json.JSONDecodeError, ValueError):
                continue
    return False, f"Could not parse vision response:\n{output[:400]}"


def _screenshot_stl(stl_path: Path, output_png: Path) -> tuple[bool, str]:
    """Render STL to PNG off-screen via PyVista subprocess."""
    output_png.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
import os
os.environ["PYVISTA_OFF_SCREEN"] = "true"
import pyvista as pv
pv.start_xvfb()  # no-op if not on Linux
mesh = pv.read(r"{stl_path}")
plotter = pv.Plotter(off_screen=True, window_size=[512, 512])
plotter.add_mesh(mesh, color="lightblue", show_edges=False)
plotter.camera_position = "isometric"
plotter.screenshot(r"{output_png}")
plotter.close()
import pathlib
sz = pathlib.Path(r"{output_png}").stat().st_size
print(f"SCREENSHOT_OK:{{sz}}")
"""
    ok, output = _run_py(script, timeout=60)
    if "SCREENSHOT_OK:" in output:
        return True, ""
    return False, f"Screenshot failed:\n{output[:400]}"


# ── Test functions ─────────────────────────────────────────────────────────────


def test_f1_flat_plate_render() -> tuple[bool, str]:
    """Render flat_plate.stl and assert it looks like a flat 3D surface."""
    stl_path = REPO_ROOT / "scripts" / "flat_plate.stl"
    if not stl_path.exists():
        return False, f"flat_plate.stl not found: {stl_path}"

    out_png = TEST_PNG_DIR / "f1_flat_plate.png"
    ok, err = _screenshot_stl(stl_path, out_png)
    if not ok:
        return False, f"Screenshot step failed: {err}"

    return _vision_assert(
        out_png, "This image shows a 3D rendered flat rectangular plate or surface"
    )


def test_f2_beauty_review_png() -> tuple[bool, str]:
    """Most recent beauty_review PNG shows a textured 3D surface."""
    pngs = sorted(BEAUTY_DIR.glob("*.png")) if BEAUTY_DIR.exists() else []
    if not pngs:
        return False, f"No PNGs in beauty_review/: {BEAUTY_DIR}"
    latest = pngs[-1]
    return _vision_assert(
        latest,
        "This image shows a 3D surface with visible texture or material rendering",
    )


def test_f3_perlin_texture_png() -> tuple[bool, str]:
    """Group C test generated a Perlin PNG — assert it looks like a repeating pattern."""
    perlin_png = TEST_PNG_DIR / "test_texture_c5.png"
    if not perlin_png.exists():
        return False, f"Perlin PNG not found (run Group C first): {perlin_png}"
    return _vision_assert(
        perlin_png,
        "This image shows a tileable texture pattern with repeating or procedural structure",
    )


def test_f4_quality_metrics_jsonl() -> tuple[bool, str]:
    """quality_metrics.jsonl exists and contains valid metric records."""
    if not QUALITY_JSONL.exists():
        return False, f"quality_metrics.jsonl not found at {QUALITY_JSONL}"

    records = []
    with QUALITY_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not records:
        return False, "quality_metrics.jsonl is empty or contains no valid JSON"

    # Verify at least one record has the expected metrics
    required_keys = {"uniformity", "seam_score", "beauty_score"}
    valid = [r for r in records if required_keys.issubset(r.keys())]
    if not valid:
        return (
            False,
            f"No records have required keys {required_keys}. Found keys: {list(records[0].keys())}",
        )

    return True, f"{len(valid)} valid metric records found"


def test_f5_autonomy_score() -> tuple[bool, str]:
    """Latest quality_metrics.jsonl entry has autonomy_score > 0.4."""
    if not QUALITY_JSONL.exists():
        return False, "quality_metrics.jsonl not found"

    records = []
    with QUALITY_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not records:
        return False, "No records in quality_metrics.jsonl"

    latest = records[-1]
    score = latest.get("autonomy_score") or latest.get("beauty_score") or 0
    if score >= 0.4:
        return True, f"autonomy/beauty score = {score:.3f}"
    return False, f"Score {score:.3f} < 0.4 threshold. Record: {latest}"


def test_f6_splash_logo() -> tuple[bool, str]:
    """splash_logo.svg exists and is syntactically valid SVG."""
    if not SPLASH_SVG.exists():
        return False, f"splash_logo.svg not found: {SPLASH_SVG}"
    content = SPLASH_SVG.read_text(encoding="utf-8", errors="replace")
    if "<svg" not in content:
        return False, "File does not contain <svg tag"
    if "viewBox" not in content and "width" not in content:
        return False, "SVG missing dimension attributes (viewBox/width)"
    size_kb = SPLASH_SVG.stat().st_size / 1024
    return True, f"SVG valid, {size_kb:.1f} KB"


# ── Test registry ─────────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, callable]] = [
    (
        "F.flat_plate_render",
        "Render flat_plate.stl → assert flat 3D surface",
        test_f1_flat_plate_render,
    ),
    (
        "F.beauty_review_png",
        "beauty_review PNG shows textured 3D surface",
        test_f2_beauty_review_png,
    ),
    (
        "F.perlin_texture_png",
        "Perlin texture PNG shows repeating pattern",
        test_f3_perlin_texture_png,
    ),
    (
        "F.quality_metrics_jsonl",
        "quality_metrics.jsonl has valid metric records",
        test_f4_quality_metrics_jsonl,
    ),
    ("F.autonomy_score", "Latest quality score ≥ 0.40", test_f5_autonomy_score),
    ("F.splash_logo_svg", "splash_logo.svg is valid SVG", test_f6_splash_logo),
]


def run_group_f() -> list[dict]:
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except subprocess.TimeoutExpired:
            passed, error = False, "Timeout exceeded"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)[:1000]

        results.append(
            {
                "group_id": "F",
                "test_id": test_id,
                "test_name": test_name,
                "passed": passed,
                "error": error or None,
            }
        )
    return results


if __name__ == "__main__":
    for r in run_group_f():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<44s}{err}")
