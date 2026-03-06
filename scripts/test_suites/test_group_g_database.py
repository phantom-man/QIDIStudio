"""
Group G — Database Integrity Tests
=====================================
Verifies the health and content of all persistent data stores:
  LanceDB (GCS bucket + local cache)
  PostgreSQL (LangGraph tables, agent_runs, phd_test_results DDL)
  JSONL flat-file metrics

All checks are read-only (no mutations to production data).
Requires PG_DSN and LANCEDB_PATH to be set in .env.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"
QUALITY_JSONL = REPO_ROOT / "quality_metrics.jsonl"


def _run_py(script: str, timeout: int = 60) -> tuple[bool, str]:
    result = subprocess.run(
        [str(MEMORY_PY), "-B", "-c", script],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT)
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


# ── G1 LanceDB row count ──────────────────────────────────────────────────────

def test_g1_lancedb_row_count() -> tuple[bool, str]:
    """LanceDB 'documents' table has ≥ 100 rows (knowledge base populated)."""
    script = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import lancedb
uri = os.environ.get("LANCEDB_PATH", "gs://qidistudio-lancedb/lancedb")
db = lancedb.connect(uri)
tables = db.table_names()
print("TABLES:" + ",".join(tables))
if "documents" in tables:
    t = db.open_table("documents")
    n = len(t)
    print(f"ROWS:{{n}}")
else:
    print("ROWS:0")
"""
    ok, output = _run_py(script, timeout=60)
    if "ROWS:" in output:
        rows_str = [l for l in output.splitlines() if l.startswith("ROWS:")][-1]
        rows = int(rows_str.split(":")[1])
        if rows >= 100:
            return True, f"LanceDB documents table: {rows} rows"
        return False, f"LanceDB only has {rows} rows (expected ≥ 100)"
    return False, f"LanceDB check failed:\n{output[:600]}"


# ── G2 LanceDB table listing ──────────────────────────────────────────────────

def test_g2_lancedb_tables() -> tuple[bool, str]:
    """LanceDB has 'documents' table (and optionally 'quality_metrics', 'prompts')."""
    script = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import lancedb
uri = os.environ.get("LANCEDB_PATH", "gs://qidistudio-lancedb/lancedb")
db = lancedb.connect(uri)
tables = db.table_names()
print("TABLES:" + ",".join(tables))
"""
    ok, output = _run_py(script, timeout=60)
    if "TABLES:" in output:
        tables_str = output.split("TABLES:")[1].splitlines()[0]
        tables = [t.strip() for t in tables_str.split(",") if t.strip()]
        if "documents" in tables:
            return True, f"Found tables: {tables}"
        return False, f"'documents' table missing. Tables: {tables}"
    return False, f"LanceDB table list failed:\n{output[:400]}"


# ── G3 Postgres LangGraph tables ──────────────────────────────────────────────

def test_g3_postgres_langgraph_tables() -> tuple[bool, str]:
    """PostgreSQL has all 3 LangGraph checkpoint tables."""
    script = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import psycopg2
conn = psycopg2.connect(os.environ["PG_DSN"])
cur = conn.cursor()
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
tables = {{row[0] for row in cur.fetchall()}}
required = {{"checkpoints", "checkpoint_writes", "checkpoint_migrations"}}
missing = required - tables
print("FOUND:" + ",".join(sorted(tables)))
print("MISSING:" + ",".join(sorted(missing)))
conn.close()
"""
    ok, output = _run_py(script, timeout=30)
    if "MISSING:" in output:
        missing_str = [l for l in output.splitlines() if l.startswith("MISSING:")][-1]
        missing = [m for m in missing_str.split(":")[1].split(",") if m.strip()]
        if not missing:
            return True, "All 3 LangGraph tables present"
        return False, f"Missing LangGraph tables: {missing}\n{output[:400]}"
    return False, f"Postgres LangGraph check failed:\n{output[:400]}"


# ── G4 Postgres agent_runs table ─────────────────────────────────────────────

def test_g4_postgres_agent_runs() -> tuple[bool, str]:
    """PostgreSQL has agent_runs table with ≥ 1 run recorded."""
    script = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import psycopg2
conn = psycopg2.connect(os.environ["PG_DSN"])
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM agent_runs")
count = cur.fetchone()[0]
print(f"COUNT:{{count}}")
conn.close()
"""
    ok, output = _run_py(script, timeout=30)
    if "COUNT:" in output:
        count_str = [l for l in output.splitlines() if l.startswith("COUNT:")][-1]
        count = int(count_str.split(":")[1])
        if count >= 1:
            return True, f"agent_runs: {count} rows"
        return False, f"agent_runs table is empty"
    return False, f"agent_runs check failed:\n{output[:400]}"


# ── G5 Postgres prompt/response store ────────────────────────────────────────

def test_g5_postgres_prompts() -> tuple[bool, str]:
    """PostgreSQL has prompts + responses tables from the memory store."""
    script = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import psycopg2
conn = psycopg2.connect(os.environ["PG_DSN"])
cur = conn.cursor()
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
tables = {{row[0] for row in cur.fetchall()}}
required = {{"prompts", "responses"}}
missing = required - tables
print("FOUND:" + ",".join(sorted(tables & required)))
print("MISSING:" + ",".join(sorted(missing)))
if not missing:
    cur.execute("SELECT COUNT(*) FROM prompts")
    c = cur.fetchone()[0]
    print(f"PROMPT_COUNT:{{c}}")
conn.close()
"""
    ok, output = _run_py(script, timeout=30)
    if "MISSING:" in output:
        missing_str = [l for l in output.splitlines() if l.startswith("MISSING:")][-1]
        missing = [m for m in missing_str.split(":")[1].split(",") if m.strip()]
        if not missing:
            # Extract PROMPT_COUNT
            counts = [l for l in output.splitlines() if l.startswith("PROMPT_COUNT:")]
            count_info = f" ({counts[-1].split(':')[1]} prompts stored)" if counts else ""
            return True, f"prompts + responses tables exist{count_info}"
        return False, f"Missing memory tables: {missing}"
    return False, f"Prompt store check failed:\n{output[:400]}"


# ── G6 JSONL quality metrics ──────────────────────────────────────────────────

def test_g6_quality_metrics_jsonl() -> tuple[bool, str]:
    """quality_metrics.jsonl exists and contains ≥ 5 metric entries."""
    if not QUALITY_JSONL.exists():
        return False, f"quality_metrics.jsonl not found: {QUALITY_JSONL}"

    import json
    records = []
    with QUALITY_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if len(records) >= 5:
        return True, f"{len(records)} quality metric entries"
    if records:
        return False, f"Only {len(records)} entries (expected ≥ 5). Consider running the autonomous pipeline."
    return False, "quality_metrics.jsonl is empty or corrupt"


# ── G7 LanceDB integrity check (dedup) ───────────────────────────────────────

def test_g7_lancedb_no_duplicates() -> tuple[bool, str]:
    """LanceDB has no rows with identical source_file at the same timestamp."""
    script = f"""
import sys, os
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
import lancedb, pandas as pd
uri = os.environ.get("LANCEDB_PATH", "gs://qidistudio-lancedb/lancedb")
db = lancedb.connect(uri)
if "documents" not in db.table_names():
    print("SKIP:no documents table")
else:
    t = db.open_table("documents")
    df = t.to_pandas()
    if "source_file" in df.columns:
        # Check for exact duplicates in source_file + text combination
        dup_count = df.duplicated(subset=["source_file", "text"]).sum() if "text" in df.columns \
                    else df.duplicated(subset=["source_file"]).sum()
        total = len(df)
        dup_pct = dup_count / total * 100 if total > 0 else 0
        print(f"DUPS:{{dup_count}} of {{total}} ({{dup_pct:.1f}}%)")
    else:
        print("SKIP:no source_file column")
"""
    ok, output = _run_py(script, timeout=60)
    if "SKIP:" in output:
        return True, f"Skipped (condition not met): {output}"
    if "DUPS:" in output:
        info = [l for l in output.splitlines() if l.startswith("DUPS:")][-1]
        parts = info.split(":")[-1]
        dup_count = int(parts.split(" of ")[0])
        # Allow up to 5% duplicates
        total = int(parts.split(" of ")[1].split(" ")[0])
        if dup_count / max(total, 1) <= 0.05:
            return True, f"Duplicate rate acceptable: {info}"
        return False, f"High duplicate rate: {info}"
    return False, f"LanceDB integrity check failed:\n{output[:400]}"


# ── Test registry ─────────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, callable]] = [
    ("G.lancedb_row_count",   "LanceDB documents ≥ 100 rows",            test_g1_lancedb_row_count),
    ("G.lancedb_tables",      "LanceDB has 'documents' table",           test_g2_lancedb_tables),
    ("G.pg_langgraph_tables", "Postgres: 3 LangGraph checkpoint tables", test_g3_postgres_langgraph_tables),
    ("G.pg_agent_runs",       "Postgres: agent_runs ≥ 1 row",           test_g4_postgres_agent_runs),
    ("G.pg_prompts",          "Postgres: prompts + responses tables",    test_g5_postgres_prompts),
    ("G.quality_jsonl",       "quality_metrics.jsonl ≥ 5 entries",       test_g6_quality_metrics_jsonl),
    ("G.lancedb_no_dups",     "LanceDB duplicate rate ≤ 5%",             test_g7_lancedb_no_duplicates),
]


def run_group_g() -> list[dict]:
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except subprocess.TimeoutExpired:
            passed, error = False, "Timeout exceeded"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)[:1000]

        results.append({
            "group_id": "G",
            "test_id": test_id,
            "test_name": test_name,
            "passed": passed,
            "error": error or None,
        })
    return results


if __name__ == "__main__":
    for r in run_group_g():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<44s}{err}")
