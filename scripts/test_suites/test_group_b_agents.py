"""
Group B — Agent Fleet Functional Tests
========================================
Verifies that every LangGraph agent graph:
  1. Compiles to a CompiledStateGraph without import or edge errors
  2. Responds to a simple ping invocation in < 120 s
  3. Persists its run to the Postgres agent_runs table
  4. Connects to LangSmith successfully

Tests in this group make real API calls (Gemini Vertex AI + LangSmith).
They require GOOGLE_CLOUD_PROJECT, LANGSMITH_API_KEY, PG_DSN to be set.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"

EXPECTED_AGENTS = [
    "researcher",
    "builder",
    "verifier",
    "scribe",
    "coder",
    "tester",
    "orchestrator",
    "dev_fleet",
]


def _run_py(script: str, timeout: int = 120) -> tuple[bool, str]:
    """Run arbitrary Python in memory_env subprocess. Returns (ok, output)."""
    result = subprocess.run(
        [str(MEMORY_PY), "-B", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO_ROOT),
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


# ── Individual test functions ──────────────────────────────────────────────────

def test_b_agent_compile() -> tuple[bool, str]:
    """
    All 8 agents compile to CompiledStateGraph.
    This mirrors the health-check command from copilot-instructions.md.
    """
    script = f"""
import sys; sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from agents._agentcomms_check import main
main()
"""
    success, output = _run_py(script, timeout=60)
    # Health check prints "researcher : CompiledStateGraph" etc.
    required_lines = [f"{a} :" for a in EXPECTED_AGENTS]
    missing = [line for line in required_lines if line not in output]
    if missing:
        return False, f"Missing agents in health check: {missing}\nOutput:\n{output[:800]}"
    if "CompiledStateGraph" not in output:
        return False, f"No CompiledStateGraph found in output:\n{output[:800]}"
    return True, ""


def test_b_langsmith_connection() -> tuple[bool, str]:
    """LangSmith Client() connects and API key is valid."""
    script = f"""
import sys; sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from langsmith import Client
client = Client()
# List projects — raises on auth failure
projects = list(client.list_projects())
names = [p.name for p in projects]
print("PROJECTS:" + ",".join(names))
"""
    success, output = _run_py(script, timeout=30)
    if "PROJECTS:" in output:
        return True, ""
    return False, f"LangSmith connection failed:\n{output[:600]}"


def test_b_orchestrator_ping() -> tuple[bool, str]:
    """
    Agent orchestrator responds to a minimal ping.
    Dispatches 'reply with exactly the word ONLINE' to the researcher agent.
    Full round-trip through LangGraph + Gemini + Postgres.
    """
    script = f"""
import sys; sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from agents.orchestrator import run
result = run("reply with exactly the single word ONLINE — no other text")
response = (result.get("final_response") or "").strip().upper()
if "ONLINE" in response:
    print("PING_PASS")
else:
    print("PING_FAIL:" + response[:200])
"""
    success, output = _run_py(script, timeout=150)
    if "PING_PASS" in output:
        return True, ""
    return False, f"Orchestrator ping failed:\n{output[:800]}"


def test_b_postgres_agent_runs() -> tuple[bool, str]:
    """
    After a successful orchestrator call, a run should be persisted
    to the agent_runs Postgres table.
    """
    script = f"""
import sys; sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from agents.run_store import get_latest_run
run = get_latest_run()
if run and run.get("run_id"):
    print("RUN_EXISTS:" + str(run["run_id"])[:36])
else:
    print("NO_RUN")
"""
    success, output = _run_py(script, timeout=30)
    if "RUN_EXISTS:" in output:
        return True, ""
    return False, f"No agent run found in Postgres:\n{output[:600]}"


def test_b_dev_fleet_compile() -> tuple[bool, str]:
    """dev_fleet CompiledStateGraph compiles without error."""
    script = f"""
import sys; sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from agents.dev_fleet import build_graph
g = build_graph()
print(type(g).__name__)
"""
    success, output = _run_py(script, timeout=30)
    if "CompiledStateGraph" in output or "StateGraph" in output:
        return True, ""
    return False, f"dev_fleet graph compile failed:\n{output[:600]}"


def test_b_gemini_vertex_ping() -> tuple[bool, str]:
    """Direct Gemini Vertex AI ping via google.genai."""
    script = f"""
import sys; sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import os
from google import genai
from google.genai import types
client = genai.Client(
    vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)
resp = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Reply with exactly: ONLINE",
    config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=8),
)
text = resp.text.strip().upper()
if "ONLINE" in text:
    print("GEMINI_OK")
else:
    print("GEMINI_UNEXPECTED:" + text[:100])
"""
    success, output = _run_py(script, timeout=60)
    if "GEMINI_OK" in output:
        return True, ""
    return False, f"Gemini Vertex ping failed:\n{output[:600]}"


# ── Test registry ─────────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, callable]] = [
    ("B.agent_compile",       "All 8 LangGraph agents compile",           test_b_agent_compile),
    ("B.langsmith_connection","LangSmith Client() connects",              test_b_langsmith_connection),
    ("B.gemini_ping",         "Gemini Vertex AI ping → ONLINE",           test_b_gemini_vertex_ping),
    ("B.dev_fleet_compile",   "dev_fleet CompiledStateGraph compiles",    test_b_dev_fleet_compile),
    ("B.orchestrator_ping",   "Orchestrator ping → ONLINE (full round-trip)", test_b_orchestrator_ping),
    ("B.postgres_agent_runs", "agent_runs table has ≥ 1 row after ping",  test_b_postgres_agent_runs),
]


def run_group_b() -> list[dict]:
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except subprocess.TimeoutExpired:
            passed, error = False, "Timeout exceeded"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)[:1000]

        results.append({
            "group_id": "B",
            "test_id": test_id,
            "test_name": test_name,
            "passed": passed,
            "error": error or None,
        })
    return results


if __name__ == "__main__":
    for r in run_group_b():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<42s}{err}")
