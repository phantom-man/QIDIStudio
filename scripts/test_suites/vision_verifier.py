"""
scripts/test_suites/vision_verifier.py — Vision-based test assertions.

Uses the existing agents/tools.py::read_image() Gemini Vision wrapper
to perform visual quality assertions on screenshots and rendered output.

Usage
-----
  verifier = VisionVerifier()
  result = verifier.assert_image(
      image_path="scripts/pipeline_exports/beauty_review/my_part.png",
      assertion="The texture should be uniformly applied with no visible seams",
      min_confidence=0.7,
  )
  assert result.passed, result.description
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parents[2]
MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"

# Off-screen rendering support — set before any pyvista import
import os
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("DISPLAY", ":99")  # Linux virtual display (Xvfb)


@dataclass
class VisionResult:
    passed: bool
    verdict: str          # "ok" | "defect" | "unclear"
    description: str
    confidence: float
    image_path: str
    raw_analysis: str


class VisionVerifier:
    """
    Wraps agents/tools.py read_image() to provide visual test assertions.

    All calls run through memory_env python so that the google-genai Vertex AI
    credential chain is correct.
    """

    def __init__(self, min_confidence_default: float = 0.65) -> None:
        self.min_confidence_default = min_confidence_default

    # ── Core assertion ────────────────────────────────────────────────────────

    def assert_image(
        self,
        image_path: str | Path,
        assertion: str,
        min_confidence: float | None = None,
    ) -> VisionResult:
        """
        Run Gemini Vision over *image_path*, ask it to evaluate *assertion*.
        Returns a VisionResult with .passed = True if verdict == "ok" and
        confidence >= min_confidence.
        """
        min_conf = min_confidence if min_confidence is not None else self.min_confidence_default
        img = Path(image_path)
        if not img.is_absolute():
            img = REPO_ROOT / img

        if not img.exists():
            return VisionResult(
                passed=False,
                verdict="unclear",
                description=f"Image not found: {img}",
                confidence=0.0,
                image_path=str(img),
                raw_analysis="",
            )

        script = f"""
import sys, json
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv
load_dotenv(r"{REPO_ROOT / '.env'}", override=True)
from agents.tools import read_image
raw = read_image.invoke({{"image_path": r"{img}", "question": {json.dumps(assertion)}}})
print(raw)
"""

        try:
            result = subprocess.run(
                [str(MEMORY_PY), "-B", "-c", script],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(REPO_ROOT),
            )
            output = result.stdout.strip()
            if not output:
                raise RuntimeError(f"read_image returned empty.\nstderr: {result.stderr[:500]}")

            # The read_image tool wraps the Gemini response in JSON
            outer = json.loads(output)
            analysis_text = outer.get("analysis", "{}")

            # Try to parse the inner JSON from Gemini's model response
            # The model is instructed to return: {"verdict": "ok|defect|unclear", ...}
            inner: dict[str, Any] = {}
            try:
                # Try direct JSON parse
                inner = json.loads(analysis_text)
            except json.JSONDecodeError:
                # Try extracting JSON block from markdown-wrapped response
                m = re.search(r"\{.*\}", analysis_text, re.DOTALL)
                if m:
                    try:
                        inner = json.loads(m.group())
                    except json.JSONDecodeError:
                        inner = {}

            verdict = str(inner.get("verdict", "unclear")).lower()
            description = str(inner.get("description", analysis_text[:500]))
            confidence = float(inner.get("confidence", 0.5))

            passed = verdict == "ok" and confidence >= min_conf
            return VisionResult(
                passed=passed,
                verdict=verdict,
                description=description,
                confidence=confidence,
                image_path=str(img),
                raw_analysis=output,
            )

        except Exception as exc:  # noqa: BLE001
            return VisionResult(
                passed=False,
                verdict="unclear",
                description=f"Vision analysis error: {exc}",
                confidence=0.0,
                image_path=str(img),
                raw_analysis="",
            )

    # ── PyVista off-screen screenshot helper ──────────────────────────────────

    @staticmethod
    def screenshot_stl(stl_path: str | Path, output_png: str | Path | None = None) -> Path:
        """
        Render an STL file off-screen using PyVista and return the path to the PNG.
        Uses memory_env python where pyvista is installed.
        """
        stl = Path(stl_path)
        if not stl.is_absolute():
            stl = REPO_ROOT / stl
        if output_png is None:
            out = REPO_ROOT / "logs" / "phd_test_runs" / f"{stl.stem}_snap.png"
        else:
            out = Path(output_png)
        out.parent.mkdir(parents=True, exist_ok=True)

        script = f"""
import pyvista as pv
pv.global_theme.allow_empty_mesh = True
pl = pv.Plotter(off_screen=True, window_size=[800, 600])
pl.set_background("white")
mesh = pv.read(r"{stl}")
pl.add_mesh(mesh, color="#00D4FF", show_edges=True)
pl.reset_camera()
pl.screenshot(r"{out}")
print("DONE:{out}")
"""
        result = subprocess.run(
            [str(MEMORY_PY), "-B", "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )
        if not out.exists():
            raise RuntimeError(
                f"PyVista screenshot failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return out
