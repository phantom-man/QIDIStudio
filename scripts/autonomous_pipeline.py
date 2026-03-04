"""
scripts/autonomous_pipeline.py — Gemini-driven autonomous texture iteration loop.

This is the top-level entry point for Phase 6.7 of the QIDIStudio Master Plan:
"Autonomous Visual AI Loop".  It wires together:

  • VisualizerComputer — PyVista off-screen renderer (the "screen" Gemini sees)
  • pipeline_tools     — Domain functions Gemini can call
  • google.genai        — Gemini 2.5 Computer Use Preview via Vertex AI ADC

Flow
----
  1.  VisualizerComputer renders the part as PNG bytes
  2.  PNG + system prompt → Gemini
  3.  Gemini issues a function call (e.g. run_texture_pipeline, rotate_view)
  4.  We execute the call, update the visualizer, render a new screenshot
  5.  Repeat until Gemini calls approve_and_export or max_iter is reached

Authentication (Vertex AI ADC)
------------------------------
  1. Install ADC:  gcloud auth application-default login
  2. Set project:  gcloud config set project crafty-hook-483415-b3
  NOTE: the computer-use preview model requires location="global".

Usage
-----
  # From memory_env (has google-genai):
  memory_env\\Scripts\\python.exe scripts\\autonomous_pipeline.py \\
      --part vacuum_nozzle_lower \\
      --query "Create a uniform armadillo-plate texture with no visible seams" \\
      --max-iter 12

  # Quick smoke test (no Gemini call):
  memory_env\\Scripts\\python.exe scripts\\autonomous_pipeline.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

# Force UTF-8 line-buffered output on Windows (avoids cp1252 UnicodeEncodeError for box-drawing chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import time
import traceback
from typing import Any

# ── Ensure scripts/ is on path so relative imports work ─────────────────────
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# ── Inject .venv site-packages so pyvista/VTK are available when this script
#    is launched from memory_env (which has google-genai but not pyvista).
_REPO_ROOT = _SCRIPTS_DIR.parent
_VENV_SP = _REPO_ROOT / ".venv" / "Lib" / "site-packages"
if _VENV_SP.is_dir() and str(_VENV_SP) not in sys.path:
    sys.path.insert(1, str(_VENV_SP))

# ── Load .env — MUST come before any os.environ reads ────────────────────────
try:
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

# ── LangSmith tracing — enable before importing langchain/agents ─────────────
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", "qidistudio-pipeline")

# ── Local modules ─────────────────────────────────────────────────────────────
import pipeline_tools  # noqa: E402
from visualizer_computer import PARTS, VisualizerComputer  # noqa: E402

# ── Model / project config ────────────────────────────────────────────────────
_MODEL = "gemini-2.5-computer-use-preview-10-2025"
_PROJECT = "crafty-hook-483415-b3"
_LOCATION = "global"  # computer-use preview is only available via the global endpoint

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an autonomous 3D texture quality engineer for QIDIStudio.
You can see a live PyVista viewport of a 3D-printed part with a displacement texture.
Your goal: iterate parameters until assess_quality returns verdict=PASS, then call
approve_and_export() and record_winner().

━━ AVAILABLE TOOLS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  load_best_params(part_name)          ← START HERE every run — may skip the
                                         exploration phase if this part was
                                         solved before
  list_available_parts()               — see registered parts + STL paths
  list_available_skins()               — see available texture skin PNGs
  run_texture_pipeline(               — apply / re-apply skin texture
      part_name, stl_path, skin_path,
      tile_mm=15,    # 5–30 mm: smaller = denser; start at 15, try 8–12 for fine detail
      relief=1.0,    # 0.3–2.0 mm: depth of bumps; increase if scales look flat
      gamma=0.7,     # 0.3–1.2: <1 softens domes, >1 sharpens/spikes scales
      max_edge=2.0,  # subdivision resolution; lower = smoother but slower
      projection="auto",  # "auto"|"cylindrical"|"triplanar"
      invert=True)        # False if texture looks inverted (holes not bumps)
  reload_part(part_name, stl_path)     — refresh viewport after pipeline run
  inspect_and_assess(                  — ★ COMPOUND: 6-angle inspection + quality
      part_name, stl_path, skin_path)    assessment in ONE call.  USE THIS
                                         instead of 6 rotate_view() calls!
  assess_quality(part_name, stl_path,  — quality metrics only (no camera moves)
      skin_path="")
  rotate_view(azimuth, elevation)      — camera orbit (use sparingly)
  zoom_to_part(part_name)              — focus viewport on part
  get_mesh_stats(part_name)            — face count, bbox, watertight
  run_blender_bake(...)                — bake UVs via Blender (rarely needed)
  approve_and_export(part_name, ...)   — final export (only on PASS)
  record_winner(part_name, stl_path,   — save winning params to DNA library
      skin_name, params, quality)        for next-run fast-start

━━ OPTIMAL WORKFLOW ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1.  load_best_params(part_name)  → if found, use those params as starting point
  2.  list_available_skins()  (if needed)
  3.  run_texture_pipeline() with initial/best params
  4.  reload_part() to hot-swap mesh in viewport
  5.  inspect_and_assess() ← ONE CALL replaces the 6-rotation + assess pattern
  6.  Read verdict + scores; use DECISION TREE below to adjust params
  7.  Repeat steps 3–6 until verdict=PASS
  8.  approve_and_export()  then  record_winner()

━━ EFFICIENCY RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✗ NEVER call rotate_view() 6 times — use inspect_and_assess() instead
  ✗ NEVER approve_and_export() unless verdict=PASS
  ✓ Try at least 3 distinct parameter variants before giving up
  ✓ Change ONE major param per iteration so you can learn its effect

━━ PARAMETER DECISION TREE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  uniformity_score < 0.65:
    → Try smaller tile_mm (8–12) for denser, more even coverage
    → Try projection="cylindrical" for elongated nozzle/tube shapes
    → Try relief=0.8 (shallower — avoids degenerate faces near edges)

  seam_score < 0.70:
    → Switch to projection="cylindrical" (eliminates the azimuth seam on
       revolution-profile parts completely)
    → If already cylindrical: reduce tile_mm (shorter repeat = less seam
       phase mismatch)

  beauty_score < 0.75 with S < 0.5 (low symmetry):
    → The texture tiles lack symmetry — try a different skin PNG or
       change tile_mm to align tile boundaries with part symmetry

  beauty_score < 0.75 with H > 8.0 (too random/noisy):
    → Reduce tile_mm to increase pattern regularity
    → Try gamma=0.5 to broaden scale dome profiles (less sharp/noisy)

  texture looks inverted (holes instead of raised domes):
    → Set invert=False

  all scores good but beauty still <0.75:
    → Try gamma=0.5–0.6 for rounder, more aesthetic scale domes
    → Try relief=1.2–1.5 for more pronounced 3D character

PASS requires: uniformity≥0.65 AND seam≥0.60 AND artifact≥0.80 AND beauty≥0.75.
"""


# ── VisualizerAgent ───────────────────────────────────────────────────────────


class VisualizerAgent:
    """Thin agent loop around Gemini Computer Use Preview.

    Parameters
    ----------
    computer :
        Live VisualizerComputer instance.
    query :
        User goal, e.g. "Create a uniform armadillo-plate texture".
    part_name :
        Which part to focus on.  If None, works across all loaded parts.
    model_name :
        Gemini model to use.
    max_iter :
        Hard limit on agent iterations (safety valve).
    """

    def __init__(
        self,
        computer: VisualizerComputer,
        query: str,
        part_name: str | None = None,
        model_name: str = _MODEL,
        max_iter: int = 20,
        iter_pause: float = 3.0,
    ) -> None:
        # Wire ACTIVE_COMPUTER so reload_part() works
        pipeline_tools.ACTIVE_COMPUTER = computer

        self._computer = computer
        self._query = query
        self._part_name = part_name
        self._model_name = model_name
        self._max_iter = max_iter
        self._iter_pause = iter_pause
        self._iteration = 0
        self._history: list[dict[str, Any]] = []
        self._done = False

        # Rolling contents list — full multi-turn conversation sent to Gemini.
        # Old screenshot-bearing turns are pruned to stay inside the token budget.
        self._contents: list = []
        # Resolved after _build_tools() so _dispatch can use a plain dict.
        self._camera_fn_map: dict = {}

        # ── Observability ─────────────────────────────────────────────────────
        # Track the last N quality verdicts to detect plateaus for escalation
        self._score_history: list[dict] = (
            []
        )  # [{uniformity, seam, beauty, verdict}, ...]
        self._ls_run_id: str | None = None  # LangSmith parent run ID
        self._ls_client = None  # langsmith.Client (lazy)
        self._lancedb_enabled = False  # set True if store import succeeds
        self._init_observability()

        # Build google.genai client lazily so import errors surface clearly
        self._client = self._make_client()
        self._tools = self._build_tools()

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def run_id(self) -> str | None:
        """LangSmith parent run ID for this session.

        After agent_loop() completes, pass this to hardware_feedback.record_print_outcome()
        to annotate the trace with the physical print outcome and close the RLHF loop.

        Example::

            history = agent.agent_loop()
            run_id = agent.run_id
            # ... after physical print finishes ...
            from agents.hardware_feedback import record_print_outcome
            record_print_outcome(part_name="nozzle", success=True, run_id=run_id)
        """
        return self._ls_run_id

    # ── Observability setup ───────────────────────────────────────────────────

    def _init_observability(self) -> None:
        """Wire up LangSmith client and verify LanceDB store is reachable."""
        # LangSmith
        api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get(
            "LANGCHAIN_API_KEY", ""
        )
        if api_key:
            try:
                from langsmith import Client  # noqa: PLC0415

                self._ls_client = Client(api_key=api_key)
                print(
                    "[Agent] LangSmith tracing: ENABLED (project=qidistudio-pipeline)"
                )
            except Exception as lse:
                print(f"[Agent] LangSmith unavailable: {lse}")
        else:
            print("[Agent] LangSmith tracing: DISABLED (no LANGSMITH_API_KEY in .env)")

        # LanceDB
        try:
            _mem_pkg = _REPO_ROOT / "memory"
            if str(_REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(_REPO_ROOT))
            import memory.store  # noqa: PLC0415, F401

            self._lancedb_enabled = True
            print("[Agent] LanceDB learning: ENABLED (GCS-backed store)")
        except Exception as dbe:
            print(f"[Agent] LanceDB unavailable: {dbe}")

    def _ls_create_run(self, run_name: str) -> None:
        """Create a parent LangSmith run for the full pipeline session."""
        if self._ls_client is None:
            return
        try:
            import uuid  # noqa: PLC0415
            from datetime import datetime  # noqa: PLC0415

            self._ls_run_id = str(uuid.uuid4())
            self._ls_client.create_run(
                id=self._ls_run_id,
                name=run_name,
                run_type="chain",
                inputs={"query": self._query, "part_name": self._part_name},
                project_name="qidistudio-pipeline",
                start_time=datetime.utcnow(),
            )
        except Exception as e:
            print(f"[Agent] LangSmith create_run failed: {e}")
            self._ls_run_id = None

    def _ls_update_run(self, outputs: dict, error: str | None = None) -> None:
        """Close the LangSmith parent run with final outputs."""
        if self._ls_client is None or self._ls_run_id is None:
            return
        try:
            from datetime import datetime  # noqa: PLC0415

            self._ls_client.update_run(
                run_id=self._ls_run_id,
                outputs=outputs,
                error=error,
                end_time=datetime.utcnow(),
            )
        except Exception as e:
            print(f"[Agent] LangSmith update_run failed: {e}")

    def _ls_log_child(self, name: str, inputs: dict, outputs: dict) -> None:
        """Log a single function call as a child run under the parent."""
        if self._ls_client is None or self._ls_run_id is None:
            return
        try:
            import uuid  # noqa: PLC0415
            from datetime import datetime  # noqa: PLC0415

            child_id = str(uuid.uuid4())
            now = datetime.utcnow()
            self._ls_client.create_run(
                id=child_id,
                parent_run_id=self._ls_run_id,
                name=name,
                run_type="tool",
                inputs=inputs,
                project_name="qidistudio-pipeline",
                start_time=now,
            )
            self._ls_client.update_run(
                run_id=child_id,
                outputs=outputs,
                end_time=now,
            )
        except Exception:
            pass  # observability must never crash the pipeline

    def _lancedb_log(
        self,
        topic: str,
        decision: str,
        content: str,
        category: str = "workflow",
    ) -> None:
        """Write a learning row to GCS LanceDB.  Silent on error."""
        if not self._lancedb_enabled:
            return
        try:
            from memory.store import upsert_learning  # noqa: PLC0415

            upsert_learning(
                topic=topic,
                decision=decision,
                content=content,
                category=category,
                source=f"autonomous_pipeline/{self._part_name or 'unknown'}",
            )
        except Exception as e:
            print(f"[Agent] LanceDB write skipped: {e}")

    def _maybe_escalate(self) -> str | None:
        """If scores have plateaued for 3 iterations, ask the researcher agent.

        Returns a context hint string to inject into the next Gemini turn,
        or None if escalation is skipped/unavailable.
        """
        if len(self._score_history) < 3:
            return None
        # Check if the last 3 quality results are all MARGINAL/FAIL with
        # negligible uniformity improvement (< 0.02 delta)
        last3 = self._score_history[-3:]
        all_marginal = all(r.get("verdict") in ("MARGINAL", "FAIL") for r in last3)
        u_values = [r.get("uniformity_score", 0) for r in last3]
        plateau = (max(u_values) - min(u_values)) < 0.02
        if not (all_marginal and plateau):
            return None

        # Build a concise research question
        last = last3[-1]
        question = (
            f"Autonomous texture pipeline is stuck for part='{self._part_name}'. "
            f"uniformity={last.get('uniformity_score'):.3f} seam={last.get('seam_score'):.3f} "
            f"beauty={last.get('beauty_score'):.3f} after 3 iterations with no improvement. "
            f"Current params were: {json.dumps(last.get('last_params', {}))}. "
            f"What are the best UV projection mode and tile_mm values for a REVOLUTION-profile "
            f"nozzle part, and why might cylindrical projection still show seams? "
            f"Reply in 3 bullet points max."
        )

        print(f"  [Agent] ⚡ Escalating to researcher agent (plateau detected)...")
        try:
            # Import lazily — only available in memory_env
            if str(_REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(_REPO_ROOT))
            from agents.orchestrator import run as orch_run  # noqa: PLC0415

            result = orch_run(question)
            hint = result.get("final_response", "") or str(result)[:600]
            print(f"  [Agent] Researcher says: {hint[:300]}...")
            # Log the escalation to LanceDB
            self._lancedb_log(
                topic=f"pipeline escalation: {self._part_name} plateau advice",
                decision=hint[:200],
                content=f"Question: {question}\n\nAnswer: {hint}",
                category="workflow",
            )
            return hint
        except Exception as esc_exc:
            print(f"  [Agent] Researcher escalation failed (non-fatal): {esc_exc}")
            return None

    # ── google.genai setup ────────────────────────────────────────────────────

    def _make_client(self):
        try:
            import google.genai as genai  # noqa: PLC0415

            client = genai.Client(
                vertexai=True,
                project=_PROJECT,
                location=_LOCATION,
            )
            print(f"[Agent] google.genai client ready — project={_PROJECT}")
            return client
        except ImportError as exc:
            raise ImportError(
                "google-genai not installed.  Run:\n"
                "  memory_env\\Scripts\\pip install google-genai>=1.0"
            ) from exc

    def _build_tools(self) -> list:
        """Register pipeline_tools functions + Computer camera functions."""
        import google.genai.types as types  # noqa: PLC0415

        # Domain tools from pipeline_tools.py
        fn_decls = []
        for fn in pipeline_tools.ALL_TOOLS:
            try:
                decl = types.FunctionDeclaration.from_callable(
                    client=self._client, callable=fn
                )
                fn_decls.append(decl)
            except Exception as exc:
                print(f"  [Agent] WARNING: could not register {fn.__name__}: {exc}")

        # Camera tools — thin wrappers so Gemini can call them like functions
        def rotate_view(azimuth: float, elevation: float) -> dict:
            """Orbit the 3D viewport camera.

            Args:
                azimuth:   Horizontal rotation in degrees (0–360).
                elevation: Vertical tilt in degrees (−90 to +90).

            Returns:
                {"status": "ok", "azimuth": float, "elevation": float}
            """
            self._computer.rotate_view(azimuth, elevation)
            return {"status": "ok", "azimuth": azimuth, "elevation": elevation}

        def zoom_to_part(part_name: str) -> dict:
            """Focus the viewport on a specific part.

            Args:
                part_name: Canonical part name to zoom to.

            Returns:
                {"status": "ok", "focused_part": part_name}
            """
            self._computer.zoom_to_part(part_name)
            return {"status": "ok", "focused_part": part_name}

        def get_mesh_stats(part_name: str) -> dict:
            """Return geometric stats for a loaded part.

            Args:
                part_name: Canonical part name.

            Returns:
                {"face_count": int, "vertex_count": int, "bounding_box_mm": dict,
                 "is_watertight": bool, "surface_area_mm2": float}
            """
            return self._computer.get_mesh_stats(part_name)

        camera_fns = [rotate_view, zoom_to_part, get_mesh_stats]
        for fn in camera_fns:
            try:
                decl = types.FunctionDeclaration.from_callable(
                    client=self._client, callable=fn
                )
                fn_decls.append(decl)
                # Store in dict for O(1) dispatch
                self._camera_fn_map[fn.__name__] = fn
            except Exception as exc:
                print(f"  [Agent] WARNING: could not register {fn.__name__}: {exc}")

        print(f"[Agent] Registered {len(fn_decls)} function declarations")
        return [types.Tool(function_declarations=fn_decls)]

    # ── Agent loop ────────────────────────────────────────────────────────────

    def agent_loop(self) -> list[dict[str, Any]]:
        """Run until done or max_iter reached.  Returns the iteration history."""
        print(f"\n{'='*60}")
        print(f"[Agent] Starting autonomous pipeline")
        print(f"  Part    : {self._part_name or 'all'}")
        print(f"  Query   : {self._query}")
        print(f"  Model   : {self._model_name}")
        print(f"  Max iter: {self._max_iter}")
        print(f"{'='*60}\n")

        # Open LangSmith parent run
        self._ls_create_run(f"VisualizerAgent/{self._part_name or 'all'}")
        self._last_pipeline_params: dict = {}
        _error: str | None = None

        # Initial camera setup
        if self._part_name:
            self._computer.zoom_to_part(self._part_name)

        while self._iteration < self._max_iter and not self._done:
            self._iteration += 1
            print(f"\n── Iteration {self._iteration}/{self._max_iter} ──")
            try:
                self._run_one_iteration()
            except Exception as exc:
                print(f"[Agent] ERROR in iteration {self._iteration}: {exc}")
                traceback.print_exc()
                _error = str(exc)
                self._lancedb_log(
                    topic=f"pipeline error: {self._part_name} iter{self._iteration}",
                    decision=f"Exception: {exc}",
                    content=traceback.format_exc(),
                    category="workflow",
                )
                break
            if (
                not self._done
                and self._iteration < self._max_iter
                and self._iter_pause > 0
            ):
                print(f"  [Agent] pausing {self._iter_pause:.1f}s …")
                time.sleep(self._iter_pause)

        best = self._score_history[-1] if self._score_history else {}
        if self._done:
            print(f"\n[Agent] ✓ Pipeline complete after {self._iteration} iterations")
            self._lancedb_log(
                topic=f"pipeline success: {self._part_name}",
                decision=(
                    f"PASS after {self._iteration} iters. "
                    f"uniformity={best.get('uniformity_score','?')} "
                    f"seam={best.get('seam_score','?')} beauty={best.get('beauty_score','?')}"
                ),
                content=json.dumps(best, default=str),
                category="workflow",
            )
            self._ls_update_run(
                outputs={"status": "PASS", "iterations": self._iteration, **best}
            )
        else:
            print(
                f"\n[Agent] ⚠ Reached max_iter ({self._max_iter}) without PASS verdict"
            )
            self._lancedb_log(
                topic=f"pipeline timeout: {self._part_name}",
                decision=(
                    f"max_iter={self._max_iter} — no PASS. "
                    f"Best: uniformity={best.get('uniformity_score','?')} "
                    f"seam={best.get('seam_score','?')} beauty={best.get('beauty_score','?')}"
                ),
                content=json.dumps(
                    {"score_history": self._score_history, "query": self._query},
                    default=str,
                ),
                category="workflow",
            )
            self._ls_update_run(
                outputs={"status": "TIMEOUT", "iterations": self._iteration, **best},
                error=_error,
            )

        return self._history

    # How many user turns back to keep inline screenshots.  Older turns have
    # their image parts stripped (text kept) to limit token growth.
    _MAX_SCREENSHOT_TURNS = 3

    def _prune_contents(self) -> None:
        """Strip inline images from user turns older than _MAX_SCREENSHOT_TURNS."""
        from google.genai.types import Content, Part  # noqa: PLC0415

        image_turn_idxs = [
            i
            for i, c in enumerate(self._contents)
            if getattr(c, "role", None) == "user"
            and any(getattr(p, "inline_data", None) for p in (c.parts or []))
        ]
        for idx in image_turn_idxs[: -self._MAX_SCREENSHOT_TURNS]:
            text_parts = [
                p
                for p in (self._contents[idx].parts or [])
                if not getattr(p, "inline_data", None)
            ]
            self._contents[idx] = Content(
                role="user",
                parts=text_parts or [Part.from_text(text="[screenshot omitted]")],
            )

    def _run_one_iteration(self) -> None:
        from google.genai.types import (
            Content,
            GenerateContentConfig,
            Part,
        )  # noqa: PLC0415

        # 1. Render → append as a new user turn in the rolling conversation.
        state = self._computer.current_state()
        print(f"  Screenshot: {len(state.screenshot):,} bytes  url={state.url}")

        self._contents.append(
            Content(
                role="user",
                parts=[
                    Part.from_bytes(data=state.screenshot, mime_type="image/png"),
                    Part.from_text(
                        text=(
                            f"Iteration {self._iteration}. Viewport: {state.url}. "
                            f"Goal: {self._query}"
                            + (
                                f"\nFocus part: {self._part_name}"
                                if self._part_name
                                else ""
                            )
                        )
                    ),
                ],
            )
        )
        self._history.append(
            {
                "iteration": self._iteration,
                "role": "user",
                "screenshot_bytes": len(state.screenshot),
                "url": state.url,
            }
        )

        # Prune old screenshots to stay inside the token budget.
        self._prune_contents()

        # 2. Call Gemini with the full rolling conversation.
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=self._contents,
            config=GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                tools=self._tools,
                temperature=0.2,
                max_output_tokens=2048,
            ),
        )

        # 3. Append model turn to the conversation.
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None:
            print("  [Agent] No candidate returned from Gemini")
            return
        self._contents.append(candidate.content)

        # 4. Execute function calls; collect responses for a single reply turn.
        fn_response_parts: list = []
        for part in candidate.content.parts:
            if part.function_call:
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args or {})
                print(f"  → {fn_name}({_fmt_args(fn_args)})")
                result = self._dispatch(fn_name, fn_args)
                print(f"    {_fmt_result(result)}")
                self._history.append(
                    {
                        "iteration": self._iteration,
                        "role": "model_call",
                        "function": fn_name,
                        "args": fn_args,
                        "result": result,
                    }
                )

                # ── LangSmith child run ──────────────────────────────
                self._ls_log_child(
                    name=fn_name,
                    inputs=fn_args,
                    outputs={k: v for k, v in result.items() if k != "log"},
                )

                # ── Track pipeline params for escalation context ──────
                if fn_name == "run_texture_pipeline":
                    self._last_pipeline_params = result.get("params_used") or {
                        k: v
                        for k, v in fn_args.items()
                        if k not in ("part_name", "stl_path", "skin_path")
                    }

                # ── Quality record: LanceDB + plateau escalation ──────
                if fn_name in ("assess_quality", "inspect_and_assess"):
                    score_entry = {
                        "iteration": self._iteration,
                        "verdict": result.get("verdict"),
                        "uniformity_score": result.get("uniformity_score"),
                        "seam_score": result.get("seam_score"),
                        "artifact_score": result.get("artifact_score"),
                        "beauty_score": result.get("beauty_score"),
                        "beauty_verdict": result.get("beauty_verdict"),
                        "last_params": getattr(self, "_last_pipeline_params", {}),
                    }
                    self._score_history.append(score_entry)
                    verdict = result.get("verdict", "UNKNOWN")
                    self._lancedb_log(
                        topic=(
                            f"texture assessment: {self._part_name} "
                            f"iter{self._iteration} {verdict}"
                        ),
                        decision=(
                            f"{verdict}: u={result.get('uniformity_score'):.3f} "
                            f"s={result.get('seam_score'):.3f} "
                            f"b={result.get('beauty_score', 0):.3f} "
                            f"params={json.dumps(score_entry['last_params'])}"
                        ),
                        content=json.dumps(score_entry, default=str),
                        category="workflow",
                    )
                    # Inject researcher advice if agent has plateaued
                    hint = self._maybe_escalate()
                    if hint:
                        self._contents.append(
                            Content(
                                role="user",
                                parts=[
                                    Part.from_text(
                                        text=(
                                            f"[Researcher agent advice — plateau detected after "
                                            f"{len(self._score_history)} assessments]\n{hint}"
                                        )
                                    )
                                ],
                            )
                        )

                fn_response_parts.append(
                    Part.from_function_response(
                        name=fn_name, response={"result": result}
                    )
                )
                if (
                    fn_name == "approve_and_export"
                    and result.get("status") == "approved"
                ):
                    self._done = True
            elif part.text:
                print(f"  [Gemini] {part.text[:300]}")
                self._history.append(
                    {
                        "iteration": self._iteration,
                        "role": "model_text",
                        "text": part.text,
                    }
                )

        # 5. Send all function responses back as a single user turn.
        if fn_response_parts:
            self._contents.append(Content(role="user", parts=fn_response_parts))

    # ── Function dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, fn_name: str, fn_args: dict[str, Any]) -> dict[str, Any]:
        """Route a Gemini function call to the correct Python handler."""
        # Camera tools — dict built during _build_tools()
        if fn_name in self._camera_fn_map:
            return self._camera_fn_map[fn_name](**fn_args)

        # Pipeline domain tools
        for fn in pipeline_tools.ALL_TOOLS:
            if fn.__name__ == fn_name:
                return fn(**fn_args)

        return {"error": f"Unknown function: {fn_name}"}


# ── Dry-run smoke test ────────────────────────────────────────────────────────


def _dry_run() -> None:
    """Verify LocalComputer renders correctly without calling Gemini."""
    print("=== Dry run — VisualizerComputer + pipeline_tools (no Gemini) ===")
    with VisualizerComputer(PARTS, window_size=(1200, 600)) as computer:
        pipeline_tools.ACTIVE_COMPUTER = computer
        state = computer.current_state()
        out = pathlib.Path(_SCRIPTS_DIR) / "debug_runs"
        out.mkdir(exist_ok=True)
        png_path = out / "dry_run_screenshot.png"
        png_path.write_bytes(state.screenshot)
        print(f"  Screenshot: {len(state.screenshot):,} bytes → {png_path}")

        # Camera orbit
        for az in [0, 90, 180]:
            s = computer.rotate_view(az, 20)
            print(f"  rotate_view({az}, 20) → {len(s.screenshot):,} bytes")

        # Mesh stats
        for pname in computer.list_parts():
            stats = computer.get_mesh_stats(pname)
            print(
                f"  {pname}: faces={stats.get('face_count','N/A')} "
                f"watertight={stats.get('is_watertight','N/A')}"
            )

        # List tools
        print("\nRegistered tools:")
        parts_result = pipeline_tools.list_available_parts()
        for p in parts_result.get("parts", []):
            print(f"  {p['name']}: stl_exists={p['stl_exists']} profile={p['profile']}")

        skins_result = pipeline_tools.list_available_skins()
        print(f"\nAvailable skins: {len(skins_result.get('skins', []))}")
        for s in skins_result.get("skins", [])[:3]:
            print(f"  {s['name']} ({s['size_kb']} KB)")

    print("\n✓ Dry run complete")


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Autonomous Gemini texture pipeline for QIDIStudio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--part",
        default="vacuum_nozzle_lower",
        choices=list(PARTS.keys()),
        help="Part name to process (default: vacuum_nozzle_lower)",
    )
    p.add_argument(
        "--query",
        default="Create a uniform armadillo-plate texture with no visible seams or artifacts",
        help="Natural-language goal for the autonomous agent",
    )
    p.add_argument(
        "--max-iter",
        type=int,
        default=20,
        help="Maximum agent iterations (default: 20)",
    )
    p.add_argument(
        "--window-size",
        default="1600x900",
        help="Viewport size WxH in pixels (default: 1600x900)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Render screenshots and test tools without calling Gemini",
    )
    p.add_argument(
        "--iter-pause",
        type=float,
        default=3.0,
        help="Seconds to wait between iterations (default: 3.0; 0 = no pause)",
    )
    p.add_argument(
        "--save-history",
        default="",
        help="Path to save iteration history JSON (optional)",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    if args.dry_run:
        _dry_run()
        return

    # Parse window size
    w, h = (int(x) for x in args.window_size.lower().split("x"))

    with VisualizerComputer(PARTS, window_size=(w, h)) as computer:
        agent = VisualizerAgent(
            computer=computer,
            query=args.query,
            part_name=args.part,
            max_iter=args.max_iter,
            iter_pause=args.iter_pause,
        )
        history = agent.agent_loop()

    if args.save_history:
        hist_path = pathlib.Path(args.save_history)
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        # Make history JSON-serialisable
        safe_history = []
        for entry in history:
            safe_hist = {}
            for k, v in entry.items():
                try:
                    json.dumps(v)
                    safe_hist[k] = v
                except (TypeError, ValueError):
                    safe_hist[k] = str(v)
            safe_history.append(safe_hist)
        hist_path.write_text(json.dumps(safe_history, indent=2), encoding="utf-8")
        print(f"\n[Agent] History saved to: {hist_path}")


# ── Formatting helpers ────────────────────────────────────────────────────────


def _fmt_args(args: dict[str, Any]) -> str:
    items = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 40:
            items.append(f"{k}=...{len(v)}chars...")
        else:
            items.append(f"{k}={v!r}")
    return ", ".join(items)


def _fmt_result(result: dict[str, Any]) -> str:
    if "verdict" in result:
        notes = result.get("notes", "")
        beauty = result.get("beauty_score")
        gzone = " ★GOLDEN" if result.get("in_golden_zone") else ""
        beauty_str = (
            f"\n    beauty: {beauty} [{result.get('beauty_verdict', '?')}]{gzone}"
            f" S={result.get('symmetry_score','?')} H={result.get('spectral_entropy','?')}"
            if beauty is not None
            else ""
        )
        shot = result.get("beauty_screenshot_path")
        shot_str = f"\n    viewport saved → {shot}" if shot else ""
        return (
            f"verdict={result['verdict']} "
            f"uniformity={result.get('uniformity_score', '?')} "
            f"seam={result.get('seam_score', '?')} "
            f"artifact={result.get('artifact_score', '?')}"
            + (f"\n    notes: {notes}" if notes else "")
            + beauty_str
            + shot_str
        )
    if "output_3mf" in result:
        out = result.get("output_3mf", "")
        log_tail = (result.get("log") or "").strip()[-300:]
        base = f"exit_code={result.get('exit_code')} output={pathlib.Path(out).name if out else 'none'}"
        return f"{base}\n    log: {log_tail}" if log_tail else base
    if "stl_path" in result and "part_name" in result:
        # reload_part result
        status = result.get("status", "?")
        err = result.get("error", "")
        return f"status={status}" + (f" error={err}" if err else "")
    return str(result)[:200]


if __name__ == "__main__":
    main()
