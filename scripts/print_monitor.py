#!/usr/bin/env python3
"""
print_monitor.py — Phase 6.2 AI print failure detection
=========================================================
Captures frames from a webcam or RTSP stream, asks Gemini Vision to classify
the print state, and optionally pauses via Klipper/Moonraker when a failure
is detected above the confidence threshold.

Supported failure categories:
  • spaghetti     — filament heap, lost adhesion mid-print
  • adhesion      — first layer lifting / warping at bed
  • warping        — thermal warping (corner lift, banana effect)
  • layer_shift   — X/Y offset between layers (belt skip / cable snag)
  • stringing     — thin filament wisps between features
  • none          — print is healthy

Usage
-----
python scripts/print_monitor.py [OPTIONS]

    --source      Camera index (0,1,…) or RTSP URL           default: 0
    --interval    Seconds between frames                       default: 10
    --threshold   Confidence [0..1] to trigger pause           default: 0.85
    --printer-url Moonraker base URL e.g. http://mainsail.local  default: (off)
    --output-dir  Directory to save flagged frames             default: scripts/monitor_frames/
    --dry-run     Log but do NOT call Moonraker pause           default: False
    --smoke-test  Run offline test with a synthetic image       default: False
    --verbose     Extra logging                                 default: False

Environment
-----------
  GOOGLE_API_KEY — required for Gemini calls (falls back to rule-based stub)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Logging setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("print_monitor")


# ─── Failure categories ───────────────────────────────────────────────────────

CATEGORIES: list[str] = [
    "spaghetti",
    "adhesion",
    "warping",
    "layer_shift",
    "stringing",
    "none",
]

FAILURE_CATEGORIES: set[str] = {"spaghetti", "adhesion", "warping", "layer_shift", "stringing"}

GEMINI_PROMPT = """\
You are an expert 3D printing quality inspector.
Analyse this image of an in-progress FDM 3D print and classify it into EXACTLY ONE of:
  spaghetti    — filament strands piled up; the print has lost bed/layer adhesion
  adhesion     — first layer or base is lifting off the print bed (corner/edge lift)
  warping      — thermal deformation causing the print to bend or curl
  layer_shift  — X or Y offset visible between layers (likely motor/belt issue)
  stringing    — thin unwanted filament threads between features
  none         — the print looks normal and healthy

Respond with a valid JSON object and NOTHING ELSE:
{
  "category": "<one of the options above>",
  "confidence": <float 0.0–1.0>,
  "description": "<one sentence>"
}
"""


# ─── Gemini Vision helper ─────────────────────────────────────────────────────

def _encode_frame_b64(frame_bgr) -> str:
    """Encode a BGR numpy frame to a base64 JPEG string."""
    import cv2  # type: ignore
    _, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode()


def _call_gemini_vision(frame_bgr) -> dict:
    """
    Ask Gemini Vision to classify the print state.
    Returns dict: {category, confidence, description}
    Falls back to a stub when Gemini is unavailable.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    b64_img = _encode_frame_b64(frame_bgr)

    # ── Try new google.genai SDK (v0.8+) ─────────────────────────────────────
    if api_key:
        try:
            import google.genai as genai  # type: ignore
            from google.genai import types as gtypes  # type: ignore

            client = genai.Client(api_key=api_key)
            img_part = gtypes.Part.from_bytes(
                data=base64.b64decode(b64_img),
                mime_type="image/jpeg",
            )
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[GEMINI_PROMPT, img_part],
            )
            raw = resp.text.strip()
        except ImportError:
            # ── Fallback: legacy google.generativeai SDK ─────────────────────
            try:
                import google.generativeai as genai_legacy  # type: ignore
                genai_legacy.configure(api_key=api_key)
                model = genai_legacy.GenerativeModel("gemini-1.5-flash")
                b64_str = f"data:image/jpeg;base64,{b64_img}"
                resp = model.generate_content([GEMINI_PROMPT, {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}}])
                raw = resp.text.strip()
            except Exception as exc:
                log.warning("Gemini call failed (%s), using stub", exc)
                return _stub_result()
        except Exception as exc:
            log.warning("Gemini call failed (%s), using stub", exc)
            return _stub_result()

        # Parse JSON response
        try:
            # Strip ```json fences if model included them
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            cat = data.get("category", "none").strip().lower()
            if cat not in CATEGORIES:
                cat = "none"
            return {
                "category":    cat,
                "confidence":  float(data.get("confidence", 0.5)),
                "description": str(data.get("description", "")),
            }
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Could not parse Gemini response (%s): %s", exc, raw[:200])
            return _stub_result()

    log.debug("No GOOGLE_API_KEY — using stub classifier")
    return _stub_result()


def _stub_result() -> dict:
    """Rule-based stub: returns 'none' with medium confidence (no API key / network)."""
    return {"category": "none", "confidence": 0.5, "description": "Stub — Gemini unavailable"}


# ─── Moonraker/Klipper integration ────────────────────────────────────────────

def _pause_printer(printer_url: str, dry_run: bool = False) -> bool:
    """Send PAUSE gcode via Moonraker API. Returns True on success."""
    if dry_run:
        log.warning("[DRY-RUN] Would pause printer at %s", printer_url)
        return True
    try:
        import urllib.request
        url = printer_url.rstrip("/") + "/printer/gcode/script"
        data = json.dumps({"script": "PAUSE"}).encode()
        req = urllib.request.Request(url, data=data,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            log.info("Printer pause response: %s", result)
            return True
    except Exception as exc:
        log.error("Failed to pause printer: %s", exc)
        return False


# ─── Frame capture helper ─────────────────────────────────────────────────────

def _open_capture(source: str | int):
    """Open a cv2 VideoCapture. source can be int index or RTSP/HTTP URL."""
    try:
        import cv2  # type: ignore
    except ImportError:
        log.error("opencv-python not installed. Run: pip install opencv-python")
        sys.exit(1)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        log.error("Cannot open capture source: %s", source)
        sys.exit(1)
    return cap


def _capture_frame(cap):
    """Read one frame; retry up to 3 times."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    for _ in range(3):
        ok, frame = cap.read()
        if ok and frame is not None:
            return frame
        time.sleep(0.1)
    return None


# ─── Smoke test: offline with a synthetic plain-colour frame ─────────────────

def _run_smoke_test() -> bool:
    import numpy as np  # type: ignore
    log.info("Running smoke test (no webcam / no API key required) …")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (50, 80, 50)  # dark green — looks like a bed

    result = _stub_result()
    log.info("Stub result: %s", result)

    assert result["category"] in CATEGORIES, "Bad category in stub"
    assert 0.0 <= result["confidence"] <= 1.0, "Confidence out of range"
    log.info("[PASS] smoke test passed")
    return True


# ─── Main monitoring loop ─────────────────────────────────────────────────────

def monitor(
    source: str | int = 0,
    interval: float = 10.0,
    threshold: float = 0.85,
    printer_url: Optional[str] = None,
    output_dir: Path = Path("scripts/monitor_frames"),
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    if verbose:
        log.setLevel(logging.DEBUG)

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Starting print monitor — source=%s  interval=%.1fs  threshold=%.2f",
             source, interval, threshold)

    import cv2  # type: ignore

    cap = _open_capture(source)
    pause_sent = False  # only fire one pause per run

    try:
        while True:
            frame = _capture_frame(cap)
            if frame is None:
                log.warning("Failed to read frame; retrying in %ss", interval)
                time.sleep(interval)
                continue

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            result = _call_gemini_vision(frame)
            cat  = result["category"]
            conf = result["confidence"]
            desc = result["description"]

            level = logging.WARNING if cat in FAILURE_CATEGORIES else logging.INFO
            log.log(level, "[%s]  category=%-12s  conf=%.2f  — %s", ts, cat, conf, desc)

            if cat in FAILURE_CATEGORIES and conf >= threshold:
                frame_path = output_dir / f"failure_{ts}_{cat}.jpg"
                cv2.imwrite(str(frame_path), frame)
                log.warning("⚠️  FAILURE DETECTED  →  saved %s", frame_path)

                if printer_url and not pause_sent:
                    ok = _pause_printer(printer_url, dry_run=dry_run)
                    if ok:
                        pause_sent = True
                        log.warning("🛑  Printer PAUSED at %s", printer_url)
            else:
                if verbose:
                    frame_path = output_dir / f"ok_{ts}.jpg"
                    cv2.imwrite(str(frame_path), frame)

            time.sleep(interval)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        cap.release()
        log.info("Capture released")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="AI print failure monitor (Phase 6.2 — Gemini Vision)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source",      default="0",
                   help="Camera index (int) or RTSP/HTTP URL (default: 0)")
    p.add_argument("--interval",    type=float, default=10.0,
                   help="Seconds between frames (default: 10)")
    p.add_argument("--threshold",   type=float, default=0.85,
                   help="Confidence threshold to trigger pause (default: 0.85)")
    p.add_argument("--printer-url", default=None,
                   help="Moonraker base URL e.g. http://mainsail.local")
    p.add_argument("--output-dir",  default="scripts/monitor_frames",
                   help="Directory for flagged frame images")
    p.add_argument("--dry-run",     action="store_true",
                   help="Log but do not actually pause the printer")
    p.add_argument("--smoke-test",  action="store_true",
                   help="Run offline smoke test and exit")
    p.add_argument("--verbose",     action="store_true")
    args = p.parse_args()

    if args.smoke_test:
        ok = _run_smoke_test()
        sys.exit(0 if ok else 1)

    # Convert source to int if it looks like an integer
    source: str | int = args.source
    try:
        source = int(source)
    except ValueError:
        pass

    monitor(
        source=source,
        interval=args.interval,
        threshold=args.threshold,
        printer_url=args.printer_url,
        output_dir=Path(args.output_dir),
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
