"""
agents/hardware_feedback.py — Print Outcome → LangSmith Trace Feedback Loop.

This closes the "Self-Healing Factory" loop:
  1. Print finishes (success or failure)
  2. Operator calls record_print_outcome(run_id, success, ...)
  3. This module annotates the originating LangSmith trace with the outcome
  4. export_failure_dataset() mines all FAIL traces → JSONL for PyTorch retraining
  5. torch_tools.fine_tune_stress_gnn(jsonl) retrains on that dataset

This implements the LangSmith Feedback Loop from "AI-Powered Cyber-Physical
Feedback Loop" document:
  "After the print finishes, you send a 'Success' or 'Failure' signal back to
   that specific LangSmith trace. Use LangSmith to filter all failure traces.
   Export as JSONL to fine-tune your PyTorch model."

Usage:
    from agents.hardware_feedback import record_print_outcome, export_failure_dataset

    # After print completes:
    record_print_outcome(
        run_id="ls_run_id_from_manufacturing_graph",
        part_name="vacuum_nozzle_lower",
        success=False,
        notes="Layer delamination at Z=12mm — likely stress hotspot near hinge",
        photo_paths=["fail_photo_1.jpg"],
    )

    # Periodically, export FAIL traces and retrain:
    jsonl_path = export_failure_dataset(min_failures=10)
    if jsonl_path:
        from agents.torch_tools import fine_tune_stress_gnn
        summary = fine_tune_stress_gnn(jsonl_path)
        print(summary)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

# ── LangSmith ────────────────────────────────────────────────────────────────
try:
    from langsmith import Client as LangSmithClient

    _ls_client = LangSmithClient()
    _LANGSMITH_OK = True
except Exception:
    _ls_client = None  # type: ignore[assignment]
    _LANGSMITH_OK = False

# ── LanceDB ───────────────────────────────────────────────────────────────────
try:
    from memory.store import upsert_learning

    _LANCEDB_OK = True
except Exception:
    _LANCEDB_OK = False

# ── Dataset storage ───────────────────────────────────────────────────────────
_FEEDBACK_DIR = REPO_ROOT / "scripts" / "pipeline_exports" / "feedback"
_FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

_FEEDBACK_LOG = _FEEDBACK_DIR / "print_outcomes.jsonl"


# ═══════════════════════════════════════════════════════════════════════════════
# I.  Record Hardware Feedback
# ═══════════════════════════════════════════════════════════════════════════════


def record_print_outcome(
    part_name: str,
    success: bool,
    run_id: str | None = None,
    notes: str = "",
    photo_paths: list[str] | None = None,
    sensor_log: dict | None = None,
    stl_path: str | None = None,
) -> dict:
    """
    Record the physical print outcome and annotate the LangSmith trace.

    Args:
        part_name:    Part identifier (matches manufacturing_graph run).
        success:      True = print succeeded; False = failure.
        run_id:       LangSmith run ID from manufacturing_graph (optional).
                      If provided, the outcome is attached to that specific trace.
        notes:        Human observation (e.g. "delamination at Z=12mm").
        photo_paths:  Paths to failure / success photos.
        sensor_log:   Dict of sensor data (pressure, temp, flow_rate arrays).
        stl_path:     STL file path (used for RLHF dataset generation).

    Returns:
        dict with status, langsmith_annotated, lancedb_stored flags.
    """
    outcome = "SUCCESS" if success else "FAIL"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "part_name": part_name,
        "outcome": outcome,
        "run_id": run_id,
        "notes": notes,
        "photo_paths": photo_paths or [],
        "sensor_log": sensor_log or {},
        "stl_path": stl_path or "",
    }

    # Append to local JSONL log
    with open(_FEEDBACK_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    # Annotate LangSmith trace
    ls_annotated = False
    if run_id and _LANGSMITH_OK and _ls_client is not None:
        try:
            _ls_client.update_run(
                run_id=run_id,
                end_time=datetime.now(timezone.utc),
                outputs={"print_outcome": outcome, "notes": notes},
                error=notes if not success else None,
                extra={
                    "print_outcome": outcome,
                    "hardware_feedback": True,
                    "photo_count": len(photo_paths or []),
                },
            )
            # Add LangSmith feedback score (0 = fail, 1 = pass)
            try:
                _ls_client.create_feedback(
                    run_id=run_id,
                    key="print_success",
                    score=1.0 if success else 0.0,
                    comment=notes,
                )
            except Exception:
                pass  # feedback API may not be available in all SDK versions
            ls_annotated = True
        except Exception as exc:
            ls_annotated = False
            record["langsmith_error"] = str(exc)

    # Write to LanceDB
    lancedb_stored = False
    if _LANCEDB_OK:
        try:
            upsert_learning(
                topic=f"print outcome: {part_name} {outcome}",
                decision=(
                    f"{outcome}: {notes or 'no notes'}"
                    + (f" | run_id={run_id}" if run_id else "")
                ),
                content=json.dumps(record, default=str),
                category="workflow",
                source="hardware_feedback",
            )
            lancedb_stored = True
        except Exception:
            pass

    return {
        "status": "recorded",
        "outcome": outcome,
        "langsmith_annotated": ls_annotated,
        "lancedb_stored": lancedb_stored,
        "log_path": str(_FEEDBACK_LOG),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# II.  Export Failure Dataset for PyTorch Retraining (RLHF loop)
# ═══════════════════════════════════════════════════════════════════════════════


def export_failure_dataset(
    min_failures: int = 5,
    include_langsmith_traces: bool = True,
    output_path: str | None = None,
) -> str | None:
    """
    Mine LangSmith + local log for FAIL traces and export a JSONL dataset
    for retraining torch_tools.MeshStressGNN.

    Each JSONL row:
        {
          "run_id": str,
          "part_name": str,
          "vertices": [[x,y,z], ...],
          "normals": [[nx,ny,nz], ...],
          "label": 1.0 (failure) or 0.0 (success),
          "notes": str,
          "timestamp": str,
        }

    Returns:
        Path to JSONL file, or None if not enough data.
    """
    rows: list[dict] = []

    # 1. Mine local feedback log
    if _FEEDBACK_LOG.exists():
        for line in _FEEDBACK_LOG.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if not rec.get("stl_path"):
                continue
            label = 0.0 if rec["outcome"] == "SUCCESS" else 1.0
            verts, norms = _extract_vertices(rec["stl_path"])
            if verts:
                rows.append(
                    {
                        "run_id": rec.get("run_id"),
                        "part_name": rec["part_name"],
                        "vertices": verts[:5_000],  # cap for JSONL size
                        "normals": norms[:5_000],
                        "label": label,
                        "notes": rec.get("notes", ""),
                        "timestamp": rec.get("timestamp", ""),
                        "source": "local_log",
                    }
                )

    # 2. Mine LangSmith for manufacturing-pipeline runs with print_success feedback
    if include_langsmith_traces and _LANGSMITH_OK and _ls_client is not None:
        try:
            # List runs from manufacturing project with feedback
            runs_iter = _ls_client.list_runs(
                project_name=os.getenv("LANGCHAIN_PROJECT", "qidistudio-manufacturing"),
                execution_order=1,
                limit=200,
            )
            for run in runs_iter:
                try:
                    feedbacks = list(_ls_client.list_feedback(run_ids=[str(run.id)]))
                    for fb in feedbacks:
                        if fb.key == "print_success" and fb.score is not None:
                            stl = (run.inputs or {}).get("stl_path", "")
                            verts, norms = _extract_vertices(stl)
                            if verts:
                                rows.append(
                                    {
                                        "run_id": str(run.id),
                                        "part_name": (run.inputs or {}).get(
                                            "part_name", "unknown"
                                        ),
                                        "vertices": verts[:5_000],
                                        "normals": norms[:5_000],
                                        "label": 0.0 if fb.score >= 0.5 else 1.0,
                                        "notes": fb.comment or "",
                                        "timestamp": (
                                            run.start_time.isoformat()
                                            if run.start_time
                                            else ""
                                        ),
                                        "source": "langsmith",
                                    }
                                )
                except Exception:
                    continue
        except Exception:
            pass

    # Require minimum sample count
    fail_count = sum(1 for r in rows if r["label"] == 1.0)
    if fail_count < min_failures:
        print(
            f"[hardware_feedback] Only {fail_count} failure samples "
            f"(need {min_failures}). Dataset not exported."
        )
        return None

    # Write JSONL
    out = (
        Path(output_path)
        if output_path
        else (
            _FEEDBACK_DIR
            / f"rlhf_dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        )
    )
    with open(out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")

    print(
        f"[hardware_feedback] Exported {len(rows)} samples "
        f"({fail_count} failures, {len(rows) - fail_count} successes) → {out}"
    )

    # Log to LanceDB
    if _LANCEDB_OK:
        try:
            upsert_learning(
                topic="RLHF dataset export",
                decision=f"{len(rows)} samples ({fail_count} fail) → {out.name}",
                content=json.dumps(
                    {
                        "n_total": len(rows),
                        "n_fail": fail_count,
                        "n_success": len(rows) - fail_count,
                        "path": str(out),
                    }
                ),
                category="workflow",
                source="hardware_feedback",
            )
        except Exception:
            pass

    return str(out)


# ═══════════════════════════════════════════════════════════════════════════════
# III.  Full Retraining Cycle
# ═══════════════════════════════════════════════════════════════════════════════


def run_retraining_cycle(
    min_failures: int = 5,
    epochs: int = 20,
    lr: float = 1e-3,
) -> dict:
    """
    One-call RLHF cycle:
      1. Export failure dataset from LangSmith + local log
      2. Fine-tune MeshStressGNN on that dataset
      3. Log results to LanceDB

    Returns summary dict.
    """
    jsonl_path = export_failure_dataset(min_failures=min_failures)
    if jsonl_path is None:
        return {
            "status": "skipped",
            "reason": f"insufficient failures (need {min_failures})",
        }

    from agents.torch_tools import fine_tune_stress_gnn

    summary = fine_tune_stress_gnn(jsonl_path, epochs=epochs, lr=lr)
    summary["dataset_path"] = jsonl_path

    if _LANCEDB_OK:
        try:
            upsert_learning(
                topic="GNN retraining cycle",
                decision=f"status={summary.get('status')} loss={summary.get('final_loss')}",
                content=json.dumps(summary, default=str),
                category="workflow",
                source="hardware_feedback",
            )
        except Exception:
            pass

    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# IV.  LangSmith Dataset Builder  (separate from RLHF — for eval harness)
# ═══════════════════════════════════════════════════════════════════════════════


def build_langsmith_eval_dataset(
    dataset_name: str = "qidistudio-texture-eval",
    max_runs: int = 100,
) -> dict:
    """
    Export manufacturing-pipeline LangSmith runs as a named LangSmith Dataset
    for use in evaluation harnesses.

    Dataset format:
        inputs:  {stl_path, part_name, query}
        outputs: {verdict, uniformity, seam, beauty, print_outcome}

    Returns dict with dataset_id and run count.
    """
    if not _LANGSMITH_OK or _ls_client is None:
        return {"status": "skipped", "reason": "LangSmith not available"}

    try:
        # Get or create dataset
        try:
            dataset = _ls_client.create_dataset(
                dataset_name=dataset_name,
                description=(
                    "QIDIStudio manufacturing pipeline runs for texture + stress evaluation. "
                    "Used to track performance regression and trigger RLHF retraining."
                ),
            )
        except Exception:
            # Dataset already exists — fetch it
            datasets = list(_ls_client.list_datasets(dataset_name=dataset_name))
            if not datasets:
                return {"status": "error", "reason": "could not create or find dataset"}
            dataset = datasets[0]

        # Pull recent runs
        runs = list(
            _ls_client.list_runs(
                project_name=os.getenv("LANGCHAIN_PROJECT", "qidistudio-manufacturing"),
                execution_order=1,
                limit=max_runs,
            )
        )

        added = 0
        for run in runs:
            try:
                inputs = {
                    "stl_path": (run.inputs or {}).get("stl_path", ""),
                    "part_name": (run.inputs or {}).get("part_name", ""),
                    "query": (run.inputs or {}).get("query", ""),
                }
                outputs = {
                    "verdict": (run.outputs or {}).get("verdict", "UNKNOWN"),
                    "uniformity_score": (run.outputs or {}).get("uniformity_score"),
                    "seam_score": (run.outputs or {}).get("seam_score"),
                    "beauty_score": (run.outputs or {}).get("beauty_score"),
                    "print_outcome": (run.outputs or {}).get(
                        "print_outcome", "PENDING"
                    ),
                    "failure_probability": (run.outputs or {}).get(
                        "failure_probability"
                    ),
                }
                _ls_client.create_example(
                    inputs=inputs,
                    outputs=outputs,
                    dataset_id=dataset.id,
                    source_run_id=str(run.id),
                )
                added += 1
            except Exception:
                continue

        return {
            "status": "ok",
            "dataset_name": dataset_name,
            "dataset_id": str(dataset.id),
            "examples_added": added,
        }

    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════════
# V.  Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _extract_vertices(stl_path: str) -> tuple[list[list[float]], list[list[float]]]:
    """Extract vertices from STL — reuses manufacturing_graph._load_stl_vertices."""
    try:
        from agents.manufacturing_graph import _load_stl_vertices

        return _load_stl_vertices(stl_path)
    except Exception:
        return [], []


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "record":
        # python hardware_feedback.py record <part_name> <success|fail> [run_id] [notes]
        part = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        ok = (sys.argv[3] if len(sys.argv) > 3 else "fail").lower() in (
            "success",
            "1",
            "true",
        )
        rid = sys.argv[4] if len(sys.argv) > 4 else None
        notes = sys.argv[5] if len(sys.argv) > 5 else ""
        result = record_print_outcome(
            part_name=part, success=ok, run_id=rid, notes=notes
        )
        print(json.dumps(result, indent=2))

    elif cmd == "export":
        path = export_failure_dataset()
        print(f"Dataset: {path}")

    elif cmd == "retrain":
        summary = run_retraining_cycle()
        print(json.dumps(summary, indent=2))

    elif cmd == "dataset":
        result = build_langsmith_eval_dataset()
        print(json.dumps(result, indent=2))

    else:
        print(
            f"[hardware_feedback] log={_FEEDBACK_LOG}, langsmith={_LANGSMITH_OK}, lancedb={_LANCEDB_OK}"
        )
