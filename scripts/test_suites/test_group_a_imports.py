"""
Group A — Python Import & Smoke Tests
======================================
Verifies that every key Python module in the QIDIStudio repository:
  1. Can be imported without errors
  2. Exposes its declared public API (functions / classes)
  3. CLI smoke tests pass (--smoke-test or --help flags where applicable)

Each test is expected to complete in < 30 s.
No network calls, no GPU, no external services required.
Failures here indicate broken dependencies or circular imports.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"
VENV_PY = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

# Add repo root to path
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── Helper ────────────────────────────────────────────────────────────────────

def _import_check(module_path: str, python_exe: Path | None = None) -> tuple[bool, str]:
    """
    Attempt to import *module_path* in a subprocess.
    Returns (success: bool, error_message: str).
    """
    py = str(python_exe or MEMORY_PY)
    result = subprocess.run(
        [py, "-B", "-c", f"import {module_path}; print('OK')"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    if result.returncode == 0 and "OK" in result.stdout:
        return True, ""
    return False, (result.stderr or result.stdout)[:1000]


def _attr_check(module_path: str, attr: str, python_exe: Path | None = None) -> tuple[bool, str]:
    """Check that module.attr exists."""
    py = str(python_exe or MEMORY_PY)
    script = f"import {module_path}; m = __import__('{module_path}', fromlist=['']); assert hasattr(m, '{attr}'), f'missing {attr}'; print('OK')"
    result = subprocess.run(
        [py, "-B", "-c", script],
        capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT)
    )
    if result.returncode == 0 and "OK" in result.stdout:
        return True, ""
    return False, (result.stderr or result.stdout)[:600]


def _script_smoke(
    script_path: str,
    args: list[str],
    python_exe: Path | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run a script with args and check for zero exit code."""
    py = str(python_exe or MEMORY_PY)
    result = subprocess.run(
        [py, "-B", script_path, *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT)
    )
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout)[:1000]


# ── Test definitions ──────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, Callable[[], tuple[bool, str]]]] = [
    # (test_id, test_name, callable)

    # Core agent modules
    ("A.agents_import",        "agents.agents importable",         lambda: _import_check("agents.agents")),
    ("A.tools_import",         "agents.tools importable",          lambda: _import_check("agents.tools")),
    ("A.orchestrator_import",  "agents.orchestrator importable",   lambda: _import_check("agents.orchestrator")),
    ("A.dev_fleet_import",     "agents.dev_fleet importable",      lambda: _import_check("agents.dev_fleet")),
    ("A.run_store_import",     "agents.run_store importable",      lambda: _import_check("agents.run_store")),
    ("A.phd_pipeline_import",  "agents.phd_pipeline importable",   lambda: _import_check("agents.phd_pipeline")),
    ("A.mfg_graph_import",     "agents.manufacturing_graph importable", lambda: _import_check("agents.manufacturing_graph")),
    ("A.hw_feedback_import",   "agents.hardware_feedback importable",  lambda: _import_check("agents.hardware_feedback")),
    ("A.torch_tools_import",   "agents.torch_tools importable",    lambda: _import_check("agents.torch_tools")),
    ("A.trajectory_import",    "agents.trajectory_eval importable",lambda: _import_check("agents.trajectory_eval")),
    ("A.slicer_harv_import",   "agents.slicer_harvester importable",lambda: _import_check("agents.slicer_harvester")),

    # Script modules
    ("A.beauty_scorer",        "scripts.ai_beauty_scorer importable",
        lambda: _import_check("scripts.ai_beauty_scorer")),
    ("A.pipeline_tools",       "scripts.pipeline_tools importable",
        lambda: _import_check("scripts.pipeline_tools")),
    ("A.autonomous_pipe",      "scripts.autonomous_pipeline importable",
        lambda: _import_check("scripts.autonomous_pipeline")),
    ("A.visualizer_computer",  "scripts.visualizer_computer importable",
        lambda: _import_check("scripts.visualizer_computer")),
    ("A.knowledge_validator",  "scripts.knowledge_validator importable",
        lambda: _import_check("scripts.knowledge_validator")),
    ("A.ai_bridge_server",     "scripts.ai_bridge_server importable",
        lambda: _import_check("scripts.ai_bridge_server")),
    ("A.support_advisor",      "scripts.support_advisor importable",
        lambda: _import_check("scripts.support_advisor")),
    ("A.text_to_texture",      "scripts.text_to_texture importable",
        lambda: _import_check("scripts.text_to_texture")),
    ("A.print_monitor",        "scripts.print_monitor importable",
        lambda: _import_check("scripts.print_monitor")),

    # Memory modules
    ("A.memory_store",         "memory.store importable",          lambda: _import_check("memory.store")),
    ("A.memory_inject",        "memory.inject importable",         lambda: _import_check("memory.inject")),
    ("A.prompt_store",         "memory.prompt_store importable",   lambda: _import_check("memory.prompt_store")),

    # GCodeRefiner
    ("A.gcode_refiner",        "GCodeRefiner.refiner importable",  lambda: _import_check("GCodeRefiner.refiner")),
    ("A.gcode_llm",            "GCodeRefiner.llm_optimizer importable",
        lambda: _import_check("GCodeRefiner.llm_optimizer")),

    # Public API surface checks
    ("A.beauty_api",           "ai_beauty_scorer.beauty_score_from_metrics exists",
        lambda: _attr_check("scripts.ai_beauty_scorer", "beauty_score_from_metrics")),
    ("A.pipeline_tools_api",   "pipeline_tools.run_texture_pipeline exists",
        lambda: _attr_check("scripts.pipeline_tools", "run_texture_pipeline")),
    ("A.agents_get_agent",     "agents.get_agent function exists",
        lambda: _attr_check("agents.agents", "get_agent")),
    ("A.run_fleet_api",        "dev_fleet.run_fleet exists",
        lambda: _attr_check("agents.dev_fleet", "run_fleet")),

    # CLI smoke tests
    ("A.nl_slicer_smoke",      "nl_slicer.py --smoke-test passes",
        lambda: _script_smoke("scripts/nl_slicer.py", ["--smoke-test"], timeout=90)),
    ("A.support_advisor_smoke","support_advisor.py --help works",
        lambda: _script_smoke("scripts/support_advisor.py", ["--help"])),
    ("A.startup_check_import", "scripts.startup_check importable",
        lambda: _import_check("scripts.startup_check")),
]


# ── Runner (called by phd_test_pipeline) ─────────────────────────────────────

def run_group_a() -> list[dict]:
    """
    Run all Group A tests. Returns a list of result dicts for the orchestrator.
    """
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except subprocess.TimeoutExpired:
            passed, error = False, "Timeout exceeded (30s)"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)

        results.append({
            "group_id": "A",
            "test_id": test_id,
            "test_name": test_name,
            "passed": passed,
            "error": error or None,
        })
    return results


if __name__ == "__main__":
    # Standalone run: print results to stdout
    import json
    for r in run_group_a():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<42s}{err}")
