#!/usr/bin/env python3
"""
ai_bridge_server.py — NexusSlicer AI Bridge Server
====================================================
FastAPI-style HTTP server (stdlib only — no uvicorn required) on port 17234.
The VS Code extension's AiBridge.ts connects here to expose the full
cyber-physical AI stack in the editor:

  GET  /api/ai/status                    → health check, model load status
  POST /api/ai/analyze-stress            → structural integrity (MeshStressGNN)
  POST /api/ai/run-texture-pipeline      → full LangGraph manufacturing pipeline
  GET  /api/ai/results/<part_name>       → latest run from LanceDB
  POST /api/ai/record-outcome            → RLHF feedback after physical print
  GET  /api/ai/uv-quality/<part_name>    → UV stats for WebGPU heatmap overlay
  GET  /api/ai/jobs/<job_id>             → async job status poll

Architecture:
  • Long-running AI tasks (stress analysis, texture pipeline) are dispatched to
    background threads and return a {job_id} immediately.
  • The extension polls /api/ai/jobs/<id> until status == "done" | "error".
  • Bridge runs as a sidecar to QIDIStudio — launch with:
      memory_env\\Scripts\\python.exe scripts/ai_bridge_server.py
  • The C++ StudioApiServer on 17233 adds a /api/ai/launch endpoint that starts
    this script as a subprocess, and /api/ai/proxy-status to report its health.

Run with:
    memory_env\\Scripts\\python.exe scripts/ai_bridge_server.py [--port 17234] [--no-reload]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ── Ensure repo root is on path ───────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="[AiBridge] %(levelname)s %(message)s",
)
log = logging.getLogger("ai_bridge")

# ── Lazy imports so the server starts even if deps are partially missing ──────
_torch_ok: bool = False
_lancedb_ok: bool = False
_pipeline_ok: bool = False

try:
    from agents.torch_tools import (  # type: ignore
        evaluate_mesh_structural_integrity,
        predict_texture_quality_from_uv_stats,
    )

    _torch_ok = True
    log.info("torch_tools loaded ✓")
except Exception as e:
    log.warning(f"torch_tools unavailable: {e}")

try:
    from agents.manufacturing_graph import run_manufacturing_pipeline  # type: ignore

    _pipeline_ok = True
    log.info("manufacturing_graph loaded ✓")
except Exception as e:
    log.warning(f"manufacturing_graph unavailable: {e}")

try:
    from agents.hardware_feedback import (  # type: ignore
        record_print_outcome,
        export_failure_dataset,
    )

    _lancedb_ok = True
    log.info("hardware_feedback loaded ✓")
except Exception as e:
    log.warning(f"hardware_feedback unavailable: {e}")

try:
    from memory.store import get_all as lancedb_get_all  # type: ignore

    _lancedb_ok = _lancedb_ok  # already set
    log.info("LanceDB store loaded ✓")
except Exception as e:
    log.warning(f"LanceDB store unavailable: {e}")


# ── In-memory job registry ────────────────────────────────────────────────────
_jobs: dict[str, dict[str, Any]] = {}  # job_id → {status, result, error}
_jobs_lock = threading.Lock()

# Cache the most recent stress result per part so support-regions can be
# fetched without re-running inference.
_stress_cache: dict[str, dict] = {}  # part_name → last stress result
_stress_cache_lock = threading.Lock()


def _new_job() -> str:
    jid = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[jid] = {"status": "pending", "result": None, "error": None}
    return jid


def _finish_job(jid: str, result: Any) -> None:
    with _jobs_lock:
        _jobs[jid]["status"] = "done"
        _jobs[jid]["result"] = result


def _fail_job(jid: str, error: str) -> None:
    with _jobs_lock:
        _jobs[jid]["status"] = "error"
        _jobs[jid]["error"] = error


def _get_job(jid: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs.get(jid, {}))


# ── Async job dispatch ────────────────────────────────────────────────────────
def _run_stress_analysis(jid: str, stl_path: str, part_name: str) -> None:
    """Background thread: load STL, run structural integrity tool, return JSON."""
    try:
        if not _torch_ok:
            _fail_job(jid, "torch_tools not available — install torch>=2.2.0")
            return
        if not Path(stl_path).exists():
            _fail_job(jid, f"STL file not found: {stl_path}")
            return

        import numpy as np

        # Load STL with trimesh
        try:
            import trimesh

            mesh = trimesh.load(stl_path, force="mesh")
            verts = np.array(mesh.vertices, dtype=np.float32)
            normals = np.array(mesh.vertex_normals, dtype=np.float32)
        except Exception as e:
            _fail_job(jid, f"STL load failed: {e}")
            return

        # Pass vertices and normals separately (tool signature requires two lists)
        result = evaluate_mesh_structural_integrity.invoke(
            {
                "vertices": verts.tolist(),
                "normals": normals.tolist(),
            }
        )
        _finish_job(jid, result)
        with _stress_cache_lock:
            _stress_cache[part_name] = result  # cache for /api/ai/support-regions
        log.info(
            f"[job:{jid}] stress analysis done — fp={result.get('failure_probability', '?')}, "
            f"{len(result.get('support_regions', []))} support region(s)"
        )
    except Exception as e:
        _fail_job(jid, traceback.format_exc())
        log.error(f"[job:{jid}] stress analysis failed: {e}")


def _run_texture_pipeline(
    jid: str, part_name: str, query: str, stl_path: str | None
) -> None:
    """Background thread: run full LangGraph manufacturing pipeline."""
    try:
        if not _pipeline_ok:
            _fail_job(jid, "manufacturing_graph not available")
            return
        result = run_manufacturing_pipeline(
            stl_path=stl_path or "",
            part_name=part_name,
            query=query,
        )
        _finish_job(jid, result)
        log.info(
            f"[job:{jid}] texture pipeline done — verdict={result.get('verdict', '?')}"
        )
    except Exception as e:
        _fail_job(jid, traceback.format_exc())
        log.error(f"[job:{jid}] texture pipeline failed: {e}")


# ── Route helpers ─────────────────────────────────────────────────────────────
def _json_response(handler: "AiBridgeHandler", status: int, data: Any) -> None:
    body = json.dumps(data, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: "AiBridgeHandler") -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw)


# ── Request handler ───────────────────────────────────────────────────────────
class AiBridgeHandler(BaseHTTPRequestHandler):
    """Single handler class — routes all GET/POST/OPTIONS for /api/ai/*."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug(f"{self.address_string()} {format % args}")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        p = self.path.split("?")[0]

        # GET /api/ai/status
        if p == "/api/ai/status":
            _json_response(
                self,
                200,
                {
                    "status": "ok",
                    "version": "1.0",
                    "port": 17234,
                    "capabilities": {
                        "stress_analysis": _torch_ok,
                        "texture_pipeline": _pipeline_ok,
                        "rlhf_feedback": _lancedb_ok,
                        "uv_quality": _torch_ok,
                    },
                },
            )

        # GET /api/ai/jobs/<id>
        elif m := re.fullmatch(r"/api/ai/jobs/([a-f0-9]{8})", p):
            jid = m.group(1)
            job = _get_job(jid)
            if not job:
                _json_response(self, 404, {"error": f"Unknown job_id: {jid}"})
            else:
                _json_response(self, 200, job)

        # GET /api/ai/results/<part_name>
        elif m := re.fullmatch(r"/api/ai/results/(.+)", p):
            part_name = m.group(1)
            self._get_results(part_name)

        # GET /api/ai/support-regions/<part_name>
        elif m := re.fullmatch(r"/api/ai/support-regions/(.+)", p):
            part_name = m.group(1)
            with _stress_cache_lock:
                cached = _stress_cache.get(part_name)
            if cached is None:
                _json_response(
                    self,
                    404,
                    {
                        "error": f"No stress analysis cached for part '{part_name}'. "
                        "Run POST /api/ai/analyze-stress first."
                    },
                )
            else:
                _json_response(
                    self,
                    200,
                    {
                        "part_name": part_name,
                        "support_regions": cached.get("support_regions", []),
                        "failure_probability": cached.get("failure_probability"),
                        "risk_label": cached.get("risk_label"),
                        "n_regions": len(cached.get("support_regions", [])),
                    },
                )

        # GET /api/ai/uv-quality/<part_name>
        elif m := re.fullmatch(r"/api/ai/uv-quality/(.+)", p):
            part_name = m.group(1)
            self._get_uv_quality(part_name)

        else:
            _json_response(self, 404, {"error": f"Unknown endpoint: {p}"})

    def do_POST(self) -> None:  # noqa: N802
        p = self.path.split("?")[0]

        # POST /api/ai/analyze-stress
        if p == "/api/ai/analyze-stress":
            body = _read_json_body(self)
            stl_path = body.get("stl_path", "")
            part_name = body.get(
                "part_name", Path(stl_path).stem if stl_path else "unknown"
            )
            jid = _new_job()
            threading.Thread(
                target=_run_stress_analysis,
                args=(jid, stl_path, part_name),
                daemon=True,
            ).start()
            _json_response(
                self,
                202,
                {"job_id": jid, "status": "pending", "poll": f"/api/ai/jobs/{jid}"},
            )

        # POST /api/ai/run-texture-pipeline
        elif p == "/api/ai/run-texture-pipeline":
            body = _read_json_body(self)
            part_name = body.get("part_name", "unknown")
            query = body.get("query", "Generate a high-quality texture for this part.")
            stl_path = body.get("stl_path", None)
            jid = _new_job()
            threading.Thread(
                target=_run_texture_pipeline,
                args=(jid, part_name, query, stl_path),
                daemon=True,
            ).start()
            _json_response(
                self,
                202,
                {"job_id": jid, "status": "pending", "poll": f"/api/ai/jobs/{jid}"},
            )

        # POST /api/ai/record-outcome
        elif p == "/api/ai/record-outcome":
            body = _read_json_body(self)
            self._record_outcome(body)

        else:
            _json_response(self, 404, {"error": f"Unknown endpoint: {p}"})

    # ── Sub-handlers ──────────────────────────────────────────────────────────

    def _get_results(self, part_name: str) -> None:
        """Return latest pipeline run results from LanceDB for a given part."""
        try:
            from memory.store import get_all as _get_all  # type: ignore

            rows = _get_all()
            # Filter rows mentioning this part and containing pipeline results
            matching = [
                r
                for r in rows
                if part_name.lower()
                in (r.get("topic", "") + r.get("content", "")).lower()
                and any(
                    k in r.get("content", "")
                    for k in ("verdict", "failure_probability", "uv_score")
                )
            ]
            # Return the most recent 5
            latest = sorted(
                matching, key=lambda r: r.get("timestamp", ""), reverse=True
            )[:5]
            _json_response(self, 200, {"part_name": part_name, "results": latest})
        except Exception as e:
            _json_response(self, 500, {"error": str(e)})

    def _get_uv_quality(self, part_name: str) -> None:
        """Return predicted UV quality stats for WebGPU heatmap overlay."""
        try:
            if not _torch_ok:
                _json_response(self, 503, {"error": "torch not available"})
                return

            # Look for the latest skin file for this part
            exports_dir = REPO_ROOT / "scripts" / "pipeline_exports"
            skin_files = list(exports_dir.glob(f"{part_name}*.png"))
            if not skin_files:
                skin_files = list(
                    (REPO_ROOT / "scripts" / "skins").glob(f"*{part_name}*.png")
                )

            if not skin_files:
                _json_response(
                    self, 404, {"error": f"No skin found for part: {part_name}"}
                )
                return

            # Use ai_beauty_scorer to get UV stats, then torch MLP for quality
            skin_path = max(skin_files, key=lambda f: f.stat().st_mtime)
            from scripts.ai_beauty_scorer import analyse_skin_file  # type: ignore

            metrics = analyse_skin_file(str(skin_path))

            uv_stats = [
                metrics.get("uniformity_score", 0.5),
                metrics.get("seam_score", 0.5),
                metrics.get("artifact_score", 0.5),
                metrics.get("beauty_score", 0.5),
                metrics.get("symmetry_score", 0.5),
                metrics.get("spectral_entropy", 0.5),
                float(metrics.get("in_golden_zone", False)),
            ]

            quality = predict_texture_quality_from_uv_stats.invoke(
                {
                    "uv_stats": uv_stats,
                    "part_name": part_name,
                }
            )
            _json_response(
                self,
                200,
                {
                    "part_name": part_name,
                    "skin_file": skin_path.name,
                    "uv_metrics": metrics,
                    "predicted_quality": quality,
                },
            )
        except Exception as e:
            _json_response(self, 500, {"error": str(e)})

    def _record_outcome(self, body: dict) -> None:
        """Record a physical print outcome for RLHF loop."""
        try:
            if not _lancedb_ok:
                _json_response(self, 503, {"error": "hardware_feedback not available"})
                return

            part_name = body.get("part_name", "unknown")
            success = bool(body.get("success", False))
            run_id = body.get("run_id", None)
            notes = body.get("notes", "")
            photo_paths = body.get("photo_paths", [])
            stl_path = body.get("stl_path", "")

            record_print_outcome(
                part_name=part_name,
                success=success,
                run_id=run_id,
                notes=notes,
                photo_paths=photo_paths,
                stl_path=stl_path,
            )
            _json_response(
                self,
                200,
                {
                    "status": "recorded",
                    "part_name": part_name,
                    "success": success,
                },
            )
        except Exception as e:
            _json_response(self, 500, {"error": str(e)})


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="NexusSlicer AI Bridge Server")
    parser.add_argument(
        "--port", type=int, default=17234, help="Port to listen on (default: 17234)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload on file changes (default: auto-reload)",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AiBridgeHandler)
    log.info(f"NexusSlicer AI Bridge listening on {args.host}:{args.port}")
    log.info("Endpoints:")
    log.info("  GET  /api/ai/status")
    log.info("  POST /api/ai/analyze-stress        {stl_path, part_name}")
    log.info("  POST /api/ai/run-texture-pipeline  {part_name, query, stl_path}")
    log.info("  GET  /api/ai/results/<part_name>")
    log.info("  GET  /api/ai/uv-quality/<part_name>")
    log.info("  GET  /api/ai/support-regions/<part_name>   (after analyze-stress)")
    log.info("  POST /api/ai/record-outcome        {part_name, success, run_id, notes}")
    log.info("  GET  /api/ai/jobs/<job_id>")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
