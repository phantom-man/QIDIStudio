"""
scripts/test_suites — QIDIStudio PhD-Level Autonomous Testing Framework

Groups
------
  A  Python import & smoke tests (every module importable, CLIs functional)
  B  Agent fleet functional tests (all 8 LangGraph graphs compile + ping)
  C  Pipeline end-to-end tests (real inputs → real outputs, no mocks)
  D  TypeScript / VS Code extension tests (npm test + tsc clean build)
  E  C++ / CMake build and compilation gate tests
  F  Vision / aesthetic tests (screenshot → Gemini Vision analysis)
  G  Database integrity tests (LanceDB rows, Postgres schema)
  H  API connectivity tests (external endpoints reachable)
  I  File / asset existence tests (every committed artifact present)

The main orchestrator is scripts/phd_test_pipeline.py.
"""

from __future__ import annotations

GROUPS = ("A", "B", "C", "D", "E", "F", "G", "H", "I")

GROUP_LABELS: dict[str, str] = {
    "A": "Python Import / Smoke Tests",
    "B": "Agent Fleet Functional Tests",
    "C": "Pipeline End-to-End Tests",
    "D": "TypeScript / VS Code Extension Tests",
    "E": "C++ / CMake Build Gate Tests",
    "F": "Vision / Aesthetic Tests",
    "G": "Database Integrity Tests",
    "H": "API Connectivity Tests",
    "I": "File / Asset Existence Tests",
}

__all__ = ["GROUPS", "GROUP_LABELS"]
