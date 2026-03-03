"""QIDIStudio agents package — all imports are lazy to keep server startup fast."""

from __future__ import annotations
from typing import TYPE_CHECKING

__all__ = [
    "run",
    "run_manufacturing_pipeline",
    "record_print_outcome",
    "export_failure_dataset",
    "run_retraining_cycle",
    "build_langsmith_eval_dataset",
]


def __getattr__(name: str):  # noqa: N807
    """Lazy-load heavy submodules only when their symbols are actually accessed."""
    _map = {
        "run": ("agents.orchestrator", "run"),
        "run_manufacturing_pipeline": (
            "agents.manufacturing_graph",
            "run_manufacturing_pipeline",
        ),
        "record_print_outcome": ("agents.hardware_feedback", "record_print_outcome"),
        "export_failure_dataset": (
            "agents.hardware_feedback",
            "export_failure_dataset",
        ),
        "run_retraining_cycle": ("agents.hardware_feedback", "run_retraining_cycle"),
        "build_langsmith_eval_dataset": (
            "agents.hardware_feedback",
            "build_langsmith_eval_dataset",
        ),
    }
    if name in _map:
        module_path, attr = _map[name]
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'agents' has no attribute {name!r}")
