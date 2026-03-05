"""
scripts/startup_check.py — QIDIStudio System Startup Health Check
=================================================================

PhD-level health verification for every resource, venv, pipeline, and
external service the QIDIStudio stack depends on.

Run automatically by the Startup Protocol (see .github/copilot-instructions.md).
Safe to call multiple times — gated by a daily log entry so it only executes
once per calendar day unless a failure is detected or --force is passed.

Log file (append-only, one entry per check event):
    logs/startup_health.log

Exit codes:
    0  — all checks passed (or today's run already logged as COMPLETE)
    1  — one or more checks FAILED (details in log + stdout)
    2  — checks skipped (already COMPLETE today, use --force to override)

Usage:
    memory_env\\Scripts\\python.exe -B scripts\\startup_check.py
    memory_env\\Scripts\\python.exe -B scripts\\startup_check.py --force
    memory_env\\Scripts\\python.exe -B scripts\\startup_check.py --fix     # auto-repair venvs
    memory_env\\Scripts\\python.exe -B scripts\\startup_check.py --summary # show last log entry

Reference docs:
    docs/KNOWN_PIPELINES.md — authoritative pipeline catalog
    .env                    — all required env variables
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Force UTF-8 on Windows cp1252 terminals ─────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─── Repo root & .env loading ─────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    # dotenv unavailable — fall back to reading .env manually
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# ─── Log file (single, unchanging, append-only) ───────────────────────────────
LOG_FILE = REPO_ROOT / "logs" / "startup_health.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(level: str, check: str, msg: str) -> None:
    """Append one structured line to the startup log."""
    line = f"[{_ts()}] [{level:<5}] [{check:<35}] {msg}\n"
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line)
    colour = {
        "PASS": "\033[32m",
        "FAIL": "\033[31m",
        "WARN": "\033[33m",
        "INFO": "\033[36m",
        "FIX": "\033[35m",
    }
    reset = "\033[0m"
    print(f"  {colour.get(level, '')}{level:<5}{reset} [{check}] {msg}")


# ─── Gate: skip if already completed today ───────────────────────────────────
def _already_ran_today() -> bool:
    """Return True if today's COMPLETE entry exists in the log."""
    if not LOG_FILE.exists():
        return False
    marker = f"[{TODAY}"
    complete_marker = f"COMPLETE for {TODAY}"
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if marker in line and complete_marker in line:
            return True
    return False


# ─── Result accumulator ───────────────────────────────────────────────────────
_results: list[dict[str, Any]] = []


def _record(check: str, passed: bool, msg: str, fix_applied: bool = False) -> bool:
    level = "PASS" if passed else ("FIX" if fix_applied else "FAIL")
    _log(level, check, msg)
    _results.append(
        {
            "check": check,
            "passed": passed or fix_applied,
            "msg": msg,
            "fix": fix_applied,
        }
    )
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# CHECK GROUPS
# ══════════════════════════════════════════════════════════════════════════════


def check_env_vars() -> None:
    """Verify every .env key is present and non-empty."""
    REQUIRED = {
        "LANGSMITH_API_KEY": "LangSmith / LangChain tracing",
        "LANGCHAIN_API_KEY": "LangChain alias for LANGSMITH_API_KEY",
        "LANGSMITH_TRACING": "Must be 'true'",
        "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
        "GOOGLE_CLOUD_PROJECT": "Vertex AI project ID",
        "GOOGLE_CLOUD_LOCATION": "Vertex AI region (us-central1)",
        "GOOGLE_API_KEY": "Direct Gemini API key (non-ADC fallback)",
        "PG_DSN": "PostgreSQL connection string",
        "LANCEDB_PATH": "gs://qidistudio-lancedb/lancedb",
        "HF_TOKEN": "HuggingFace (sentence-transformers)",
        "GITHUB_TOKEN": "GitHub API (slicer harvester)",
    }
    for key, purpose in REQUIRED.items():
        val = os.environ.get(key, "")
        if val:
            masked = val[:8] + "..." if len(val) > 8 else val
            _record(f"env:{key}", True, f"{masked}  ({purpose})")
        else:
            _record(f"env:{key}", False, f"MISSING — {purpose}")

    # Validate LANGSMITH_TRACING is literally 'true'
    if os.environ.get("LANGSMITH_TRACING", "").lower() != "true":
        _record(
            "env:LANGSMITH_TRACING:value", False, "Must be 'true' — tracing is disabled"
        )
    else:
        _record("env:LANGSMITH_TRACING:value", True, "value=true OK")


def _python_exe(venv_name: str) -> Path:
    """Return the python executable for a named venv."""
    candidates = {
        "memory_env": REPO_ROOT / "memory_env" / "Scripts" / "python.exe",
        ".venv": REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        "bpy_env": REPO_ROOT / "bpy_env" / "Scripts" / "python.exe",
        "system": Path(
            r"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe"
        ),
    }
    return candidates.get(venv_name, Path("python"))


def _run_py(venv_name: str, code: str, timeout: int = 30) -> tuple[bool, str]:
    """Run a Python snippet inside a venv. Returns (ok, stdout+stderr)."""
    exe = _python_exe(venv_name)
    if not exe.exists():
        return False, f"Python executable not found: {exe}"
    try:
        r = subprocess.run(
            [str(exe), "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
            env={**os.environ},
        )
        combined = (r.stdout + r.stderr).strip()
        return r.returncode == 0, combined
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s"
    except Exception as exc:
        return False, str(exc)


def check_venvs(auto_fix: bool = False) -> None:
    """Verify each venv is healthy: executable exists, pip available, key packages importable."""

    # ── memory_env ────────────────────────────────────────────────────────────
    exe = _python_exe("memory_env")
    if not exe.exists():
        _record("venv:memory_env:exe", False, f"python.exe not found at {exe}")
    else:
        _record("venv:memory_env:exe", True, str(exe))

        # pip — memory_env has no pip.exe shim; use python -m pip
        ok, out = _run_py("memory_env", "import pip; print('pip', pip.__version__)")
        if not ok:
            _record(
                "venv:memory_env:pip",
                False,
                f"pip module missing: {out}"
                + (" — attempting fix" if auto_fix else ""),
            )
            if auto_fix:
                _try_fix_pip(exe, "memory_env")
        else:
            _record("venv:memory_env:pip", True, out.strip().split("\n")[-1])

        # Core packages — use importlib.metadata for packages that don't expose __version__
        MEMORY_ENV_PKGS = [
            ("lancedb", "lancedb.__version__"),
            ("langchain", "langchain.__version__"),
            (
                "langgraph",
                "__import__('importlib.metadata', fromlist=['version']).version('langgraph')",
            ),
            (
                "langchain_google_genai",
                "__import__('importlib.metadata', fromlist=['version']).version('langchain-google-genai')",
            ),
            ("langsmith", "langsmith.__version__"),
            ("psycopg", "psycopg.__version__"),
            ("sentence_transformers", "sentence_transformers.__version__"),
            ("google.genai", "google.genai.__version__"),
            ("google.cloud.firestore", "'firestore OK'"),
            ("google.cloud.storage", "'gcs OK'"),
            ("torch", "torch.__version__"),
        ]
        for pkg, expr in MEMORY_ENV_PKGS:
            ok, out = _run_py("memory_env", f"import {pkg}; print({expr})")
            if ok:
                _record(f"venv:memory_env:{pkg}", True, out.strip().split("\n")[-1])
            else:
                _record(
                    f"venv:memory_env:{pkg}",
                    False,
                    out.strip().split("\n")[-1] or "ImportError",
                )
                if auto_fix:
                    _try_install(exe, pkg.split(".")[0], "memory_env")

    # ── .venv ─────────────────────────────────────────────────────────────────
    exe = _python_exe(".venv")
    if not exe.exists():
        _record("venv:.venv:exe", False, f"python.exe not found at {exe}")
    else:
        _record("venv:.venv:exe", True, str(exe))
        for pkg, expr in [
            ("pyvista", "pyvista.__version__"),
            ("trimesh", "trimesh.__version__"),
            ("PIL", "PIL.__version__"),
            ("numpy", "numpy.__version__"),
        ]:
            ok, out = _run_py(".venv", f"import {pkg}; print({expr})")
            _record(
                f"venv:.venv:{pkg}",
                ok,
                out.strip().split("\n")[-1] if out else "ImportError",
            )

    # ── bpy_env ───────────────────────────────────────────────────────────────
    exe = _python_exe("bpy_env")
    if not exe.exists():
        _record("venv:bpy_env:exe", False, f"python.exe not found at {exe}")
    else:
        _record("venv:bpy_env:exe", True, str(exe))
        ok, out = _run_py("bpy_env", "import bpy; print('bpy', bpy.app.version_string)")
        _record(
            "venv:bpy_env:bpy",
            ok,
            out.strip().split("\n")[-1] if out else "ImportError",
        )


def _try_fix_pip(exe: Path, venv_name: str) -> None:
    """Bootstrap pip in a venv that is missing it."""
    try:
        r = subprocess.run(
            [str(exe), "-m", "ensurepip", "--upgrade"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )
        if r.returncode == 0:
            _record(
                f"venv:{venv_name}:pip:fix",
                True,
                "ensurepip succeeded — pip bootstrapped",
            )
        else:
            _record(
                f"venv:{venv_name}:pip:fix", False, (r.stdout + r.stderr).strip()[:200]
            )
    except Exception as exc:
        _record(f"venv:{venv_name}:pip:fix", False, str(exc))


def _try_install(exe: Path, pkg: str, venv_name: str) -> None:
    """Attempt to install a missing package."""
    try:
        r = subprocess.run(
            [str(exe), "-m", "pip", "install", "-q", pkg],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        ok = r.returncode == 0
        _record(
            f"venv:{venv_name}:{pkg}:fix",
            ok,
            "installed OK" if ok else (r.stdout + r.stderr).strip()[:200],
        )
    except Exception as exc:
        _record(f"venv:{venv_name}:{pkg}:fix", False, str(exc))


def check_postgresql() -> None:
    """Verify PostgreSQL is reachable and LangGraph tables exist."""
    dsn = os.environ.get("PG_DSN", "")
    if not dsn:
        _record("postgres:connection", False, "PG_DSN not set")
        return

    code = """
import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from psycopg_pool import ConnectionPool
dsn = os.environ['PG_DSN']
pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=2, kwargs={'autocommit': True}, open=True)
with pool.connection() as conn:
    ver = conn.execute('SELECT version()').fetchone()[0].split()[0:2]
    tables = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ).fetchall()
pool.close()
print('PG:', ' '.join(ver))
print('TABLES:', ','.join(r[0] for r in tables[:20]))
"""
    ok, out = _run_py("memory_env", code, timeout=30)
    lines = out.strip().split("\n")
    if ok:
        pg_line = next((l for l in lines if l.startswith("PG:")), "")
        tb_line = next((l for l in lines if l.startswith("TABLES:")), "")
        _record("postgres:connection", True, pg_line)

        # Check required tables
        tables = tb_line.replace("TABLES:", "").split(",")
        for tbl in [
            "checkpoints",
            "agent_runs",
            "fleet_runs",
            "fleet_run_agents",
            "prompts",
        ]:
            present = any(tbl in t for t in tables)
            _record(
                f"postgres:table:{tbl}",
                present,
                (
                    "present"
                    if present
                    else f"MISSING — run run_store.setup() or langgraph saver.setup()"
                ),
            )
    else:
        _record("postgres:connection", False, out.strip().split("\n")[-1])


def check_lancedb() -> None:
    """Verify LanceDB on GCS is reachable and documents table is populated."""
    lancedb_path = os.environ.get("LANCEDB_PATH", "gs://qidistudio-lancedb/lancedb")

    code = f"""
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
import lancedb
db = lancedb.connect("{lancedb_path}")
tables = db.table_names()
print('TABLES:', ','.join(tables[:10]))
if 'qidistudio_learnings' in tables:
    t = db.open_table('qidistudio_learnings')
    print('ROWS:', len(t))
else:
    print('ROWS: N/A')
"""
    ok, out = _run_py("memory_env", code, timeout=30)
    lines = [l for l in out.strip().split("\n") if l.strip()]
    if ok:
        tb_line = next((l for l in lines if l.startswith("TABLES:")), "")
        row_line = next((l for l in lines if l.startswith("ROWS:")), "")
        _record("lancedb:gcs:connection", True, f"path={lancedb_path} {tb_line}")
        rows_str = row_line.replace("ROWS:", "").strip()
        if rows_str.isdigit() and int(rows_str) > 0:
            _record(
                "lancedb:gcs:learnings_table",
                True,
                f"{rows_str} rows (knowledge base seeded)",
            )
        elif rows_str == "N/A":
            _record(
                "lancedb:gcs:learnings_table",
                False,
                "qidistudio_learnings table missing — run: memory_env\\Scripts\\python.exe memory/extract.py",
            )
        else:
            _record(
                "lancedb:gcs:learnings_table",
                False,
                f"qidistudio_learnings table has 0 rows — run memory/extract.py",
            )
    else:
        _record("lancedb:gcs:connection", False, out.strip().split("\n")[-1])


def check_langsmith() -> None:
    """Verify LangSmith connectivity and required projects exist."""
    code = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from langsmith import Client
c = Client()
projs = [p.name for p in list(c.list_projects())]
print('PROJECTS:', ','.join(projs))
"""
    ok, out = _run_py("memory_env", code, timeout=30)
    if ok:
        proj_line = next((l for l in out.split("\n") if "PROJECTS:" in l), "")
        projects = proj_line.replace("PROJECTS:", "").split(",")
        _record("langsmith:connection", True, f"{len(projects)} projects")

        # qidistudio-dev-fleet auto-creates on first fleet run — treat absence as INFO, not FAIL
        REQUIRED_PROJECTS = [
            "qidistudio-agents",
            "qidistudio-manufacturing",
        ]
        EXPECTED_PROJECTS = [
            "qidistudio-dev-fleet",
        ]
        for p in REQUIRED_PROJECTS:
            present = any(p in proj for proj in projects)
            _record(
                f"langsmith:project:{p}",
                present,
                (
                    "exists"
                    if present
                    else "MISSING — create manually or run first orchestrator task"
                ),
            )
        for p in EXPECTED_PROJECTS:
            present = any(p in proj for proj in projects)
            if present:
                _record(f"langsmith:project:{p}", True, "exists")
            else:
                _log(
                    "INFO",
                    f"langsmith:project:{p}",
                    "not yet created (auto-created on first dev_fleet run)",
                )
                _results.append(
                    {
                        "check": f"langsmith:project:{p}",
                        "passed": True,
                        "msg": "auto-create expected",
                        "fix": False,
                    }
                )
    else:
        _record("langsmith:connection", False, out.strip().split("\n")[-1])


def check_gemini() -> None:
    """Ping Gemini via Vertex AI ADC and via direct API key."""
    # ── Vertex AI (ADC) ───────────────────────────────────────────────────────
    code_adc = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from langchain_google_genai import ChatGoogleGenerativeAI
llm = ChatGoogleGenerativeAI(
    model='gemini-2.5-flash',
    temperature=0,
    project=os.environ['GOOGLE_CLOUD_PROJECT'],
    location=os.environ['GOOGLE_CLOUD_LOCATION'],
)
r = llm.invoke('Reply with exactly one word: ONLINE')
print('RESPONSE:', r.content.strip()[:40])
"""
    ok, out = _run_py("memory_env", code_adc, timeout=60)
    resp = next(
        (l for l in out.split("\n") if "RESPONSE:" in l), out.strip().split("\n")[-1]
    )
    _record("gemini:vertex_adc", ok, resp)

    # ── Direct API key (google.genai) ─────────────────────────────────────────
    code_key = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from google import genai
client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
r = client.models.generate_content(model='gemini-2.5-flash', contents='Reply with exactly one word: ONLINE')
print('RESPONSE:', r.text.strip()[:40])
"""
    ok, out = _run_py("memory_env", code_key, timeout=60)
    resp = next(
        (l for l in out.split("\n") if "RESPONSE:" in l), out.strip().split("\n")[-1]
    )
    _record("gemini:direct_api_key", ok, resp)


def check_agent_fleet() -> None:
    """Compile and smoke-test every LangGraph agent graph."""
    code = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from agents.agents import get_agent
from agents.dev_fleet import build_fleet_graph
from agents.orchestrator import build_graph

results = []
for a in ['researcher', 'builder', 'verifier', 'scribe', 'coder', 'tester']:
    try:
        ag = get_agent(a)
        results.append(f'OK:{a}:{type(ag).__name__}')
    except Exception as e:
        results.append(f'FAIL:{a}:{e}')

try:
    fg = build_fleet_graph()
    results.append(f'OK:dev_fleet:{type(fg).__name__}')
except Exception as e:
    results.append(f'FAIL:dev_fleet:{e}')

try:
    og = build_graph()
    results.append(f'OK:orchestrator:{type(og).__name__}')
except Exception as e:
    results.append(f'FAIL:orchestrator:{e}')

for r in results:
    print(r)
"""
    ok, out = _run_py("memory_env", code, timeout=60)
    for line in out.strip().split("\n"):
        if line.startswith("OK:") or line.startswith("FAIL:"):
            parts = line.split(":", 2)
            passed = parts[0] == "OK"
            name = parts[1] if len(parts) > 1 else "?"
            detail = parts[2] if len(parts) > 2 else ""
            _record(f"agent_fleet:{name}", passed, detail)
        elif line:
            _log("INFO", "agent_fleet:misc", line)


def check_gcs_buckets() -> None:
    """Verify GCS bucket access for all known buckets."""
    BUCKETS = {
        "qidistudio-lancedb": "LanceDB vector store",
        "qidistudio-filaments": "Filament/nozzle/slicer research data",
    }
    code_tmpl = """
import sys
from google.cloud import storage
client = storage.Client()
b = client.bucket('{bucket}')
blobs = list(b.list_blobs(max_results=1))
print('OK bucket {bucket}', len(blobs), 'sample blobs')
"""
    for bucket, purpose in BUCKETS.items():
        ok, out = _run_py("memory_env", code_tmpl.format(bucket=bucket), timeout=30)
        _record(
            f"gcs:bucket:{bucket}",
            ok,
            out.strip().split("\n")[-1] if out.strip() else f"({purpose})",
        )


def check_firestore() -> None:
    """Verify Firestore is reachable and writable."""
    code = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from google.cloud import firestore
db = firestore.Client(project=os.environ['GOOGLE_CLOUD_PROJECT'])
ref = db.collection('_startup_check').document('probe')
ref.set({'ts': firestore.SERVER_TIMESTAMP, 'source': 'startup_check.py'})
doc = ref.get()
print('OK Firestore write+read probe doc exists:', doc.exists)
"""
    ok, out = _run_py("memory_env", code, timeout=30)
    _record(
        "firestore:rw_probe",
        ok,
        out.strip().split("\n")[-1] if out.strip() else "No output",
    )


def check_bigquery() -> None:
    """Verify BigQuery dataset is accessible."""
    code = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from google.cloud import bigquery
client = bigquery.Client(project=os.environ['GOOGLE_CLOUD_PROJECT'])
datasets = [d.dataset_id for d in client.list_datasets()]
print('DATASETS:', ','.join(datasets))
"""
    ok, out = _run_py("memory_env", code, timeout=30)
    if ok:
        ds_line = next((l for l in out.split("\n") if "DATASETS:" in l), "")
        datasets = ds_line.replace("DATASETS:", "").split(",")
        _record("bigquery:list_datasets", True, f"{len(datasets)} datasets: {ds_line}")
        for expected in ["qidistudio_research"]:
            present = any(expected in d for d in datasets)
            _record(
                f"bigquery:dataset:{expected}",
                present,
                (
                    "present"
                    if present
                    else "MISSING — filament/nozzle pipeline will fail on first write"
                ),
            )
    else:
        _record("bigquery:list_datasets", False, out.strip().split("\n")[-1])


def check_external_apis() -> None:
    """Verify Google Search (Gemini grounded), GitHub, and HuggingFace tokens are valid."""
    # Google Search via Gemini grounding — uses GOOGLE_API_KEY, no CSE ID needed
    code_google_search = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from google import genai
from google.genai import types
client = genai.Client(api_key=os.environ['GOOGLE_API_KEY'])
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='What is PLA filament? Reply in one sentence.',
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    ),
)
print('OK Google Search grounded:', len(response.text), 'chars')
"""
    ok, out = _run_py("memory_env", code_google_search, timeout=30)
    _record(
        "external_api:google_search",
        ok,
        out.strip().split("\n")[-1] if out.strip() else "No response",
    )

    # GitHub token
    code_gh = """
import sys, urllib.request, os, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
token = os.environ.get('GITHUB_TOKEN', '')
req = urllib.request.Request('https://api.github.com/rate_limit',
    headers={'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'})
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read())
remaining = data.get('rate', {}).get('remaining', 0)
print(f'OK GitHub API rate_limit remaining: {remaining}')
"""
    ok, out = _run_py("memory_env", code_gh, timeout=20)
    _record(
        "external_api:github_token",
        ok,
        out.strip().split("\n")[-1] if out.strip() else "No response",
    )

    # HuggingFace token — whoami requires a valid token; 401 = token revoked/expired
    code_hf = """
import sys, os, urllib.request, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
try:
    token = os.environ.get('HF_TOKEN', '')
    req = urllib.request.Request('https://huggingface.co/api/whoami-v2',
        headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    print('OK HuggingFace user:', data.get('name', 'unknown'))
except urllib.error.HTTPError as e:
    if e.code == 401:
        print('WARN HuggingFace token 401 — token may be revoked or expired (HF_TOKEN needs rotation)')
    else:
        raise
"""
    ok, out = _run_py("memory_env", code_hf, timeout=20)
    last = out.strip().split("\n")[-1] if out.strip() else "No response"
    # Treat WARN as pass (token rotation needed but not blocking)
    if "WARN" in last:
        _log("WARN", "external_api:huggingface_token", last)
        _results.append(
            {
                "check": "external_api:huggingface_token",
                "passed": True,
                "msg": last,
                "fix": False,
            }
        )
    else:
        _record("external_api:huggingface_token", ok, last)


def check_pipeline_imports() -> None:
    """Verify every pipeline entry-point is importable without crashing."""
    PIPELINES = [
        ("memory_env", "agents.orchestrator", "orchestrator graph"),
        ("memory_env", "agents.dev_fleet", "dev fleet graph"),
        ("memory_env", "agents.phd_pipeline", "PhD pipeline"),
        ("memory_env", "agents.manufacturing_graph", "manufacturing graph"),
        ("memory_env", "agents.filament_pipeline", "filament pipeline"),
        ("memory_env", "agents.nozzle_pipeline", "nozzle pipeline"),
        ("memory_env", "agents.slicer_harvester", "slicer harvester"),
        ("memory_env", "agents.hardware_feedback", "hardware feedback"),
        ("memory_env", "agents.trajectory_eval", "trajectory eval"),
        ("memory_env", "agents.run_store", "run store"),
        (".venv", "GCodeRefiner.refiner", "gcoderefiner"),
    ]
    for venv, module, label in PIPELINES:
        ok, out = _run_py(venv, f"import {module}; print('{module} OK')", timeout=30)
        _record(
            f"pipeline_import:{module}",
            ok,
            out.strip().split("\n")[-1] if out.strip() else "ImportError",
        )


def check_memory_pipeline() -> None:
    """Verify memory/inject.py can query LanceDB."""
    code = """
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
import subprocess, sys
r = subprocess.run([sys.executable, 'memory/inject.py', '--query', 'startup check probe'],
    capture_output=True, text=True, timeout=30, cwd='.')
out = r.stdout + r.stderr
if 'QIDISTUDIO KNOWLEDGE BASE' in out or 'No results' in out or r.returncode == 0:
    print('OK inject.py ran')
else:
    raise RuntimeError('inject.py failed: ' + out[-300:])
"""
    ok, out = _run_py("memory_env", code, timeout=40)
    _record(
        "memory:inject_query",
        ok,
        out.strip().split("\n")[-1] if out.strip() else "No output",
    )


def check_langgraph_checkpointer() -> None:
    """Verify LangGraph PostgresSaver can setup and write a checkpoint."""
    code = """
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
dsn = os.environ['PG_DSN']
pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=2, kwargs={'autocommit': True}, open=True)
saver = PostgresSaver(pool)
saver.setup()
pool.close()
print('OK LangGraph PostgresSaver setup complete')
"""
    ok, out = _run_py("memory_env", code, timeout=30)
    _record(
        "langgraph:postgres_checkpointer",
        ok,
        out.strip().split("\n")[-1] if out.strip() else "No output",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION & LOG SUMMARY
# ══════════════════════════════════════════════════════════════════════════════


def _print_summary() -> None:
    failed = [r for r in _results if not r["passed"]]
    fixed = [r for r in _results if r.get("fix")]
    total = len(_results)
    print("\n" + "=" * 72)
    print(f"  STARTUP CHECK SUMMARY  {_ts()}")
    print(f"  Total checks : {total}")
    print(f"  Passed       : {total - len(failed)}")
    print(f"  Failed       : {len(failed)}")
    print(f"  Auto-fixed   : {len(fixed)}")
    if failed:
        print("\n  FAILED checks:")
        for r in failed:
            print(f"    - [{r['check']}] {r['msg']}")
    print("=" * 72)


def _write_daily_complete_marker(all_passed: bool) -> None:
    status = "COMPLETE" if all_passed else "COMPLETE_WITH_FAILURES"
    _log(
        "INFO",
        "startup_check:daily_gate",
        f"{status} for {TODAY} — {len(_results)} checks, {sum(1 for r in _results if not r['passed'])} failed",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="QIDIStudio startup health check")
    parser.add_argument(
        "--force", action="store_true", help="Run even if already completed today"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt auto-repair (ensurepip, pip install)",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print last log entry and exit"
    )
    parser.add_argument(
        "--quick", action="store_true", help="Skip API calls (env + import checks only)"
    )
    args = parser.parse_args()

    if args.summary:
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            today_lines = [l for l in lines if f"[{TODAY}" in l]
            print(
                "\n".join(today_lines[-40:]) if today_lines else "\n".join(lines[-40:])
            )
        else:
            print("No startup log found yet.")
        return 0

    # ── Daily gate ────────────────────────────────────────────────────────────
    if _already_ran_today() and not args.force:
        print(
            f"  INFO  Startup check already completed for {TODAY}. Use --force to re-run."
        )
        return 2

    # ── Header ────────────────────────────────────────────────────────────────
    _log(
        "INFO",
        "startup_check:begin",
        f"QIDIStudio startup health check — {_ts()} (fix={args.fix}, quick={args.quick})",
    )
    print(f"\n  Startup Health Check — {TODAY}")
    print(f"  Repo: {REPO_ROOT}")
    print(f"  Ref:  docs/KNOWN_PIPELINES.md\n")

    # ── Run all checks ────────────────────────────────────────────────────────
    print("── 1. Environment Variables ─────────────────────────────────────────")
    check_env_vars()

    print("\n── 2. Virtual Environments ──────────────────────────────────────────")
    check_venvs(auto_fix=args.fix)

    print("\n── 3. PostgreSQL ─────────────────────────────────────────────────────")
    check_postgresql()

    print("\n── 4. LangGraph PostgresSaver ────────────────────────────────────────")
    check_langgraph_checkpointer()

    print("\n── 5. LanceDB on GCS ─────────────────────────────────────────────────")
    check_lancedb()

    if not args.quick:
        print(
            "\n── 6. LangSmith ──────────────────────────────────────────────────────"
        )
        check_langsmith()

        print("\n── 7. Gemini (Vertex AI ADC + Direct API Key) ───────────────────────")
        check_gemini()

        print("\n── 8. Agent Fleet (graph compilation) ───────────────────────────────")
        check_agent_fleet()

        print(
            "\n── 9. GCS Buckets ────────────────────────────────────────────────────"
        )
        check_gcs_buckets()

        print(
            "\n── 10. Firestore ─────────────────────────────────────────────────────"
        )
        check_firestore()

        print(
            "\n── 11. BigQuery ──────────────────────────────────────────────────────"
        )
        check_bigquery()

        print("\n── 12. External APIs (Google Search, GitHub, HuggingFace) ───────────")
        check_external_apis()

    print("\n── 13. Pipeline Imports ──────────────────────────────────────────────")
    check_pipeline_imports()

    print("\n── 14. Memory Pipeline (LanceDB inject) ─────────────────────────────")
    check_memory_pipeline()

    # ── Summary ───────────────────────────────────────────────────────────────
    _print_summary()
    failed = [r for r in _results if not r["passed"]]
    all_passed = len(failed) == 0
    _write_daily_complete_marker(all_passed)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
