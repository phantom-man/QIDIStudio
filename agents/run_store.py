"""
agents/run_store.py — Durable PostgreSQL store for agent run results.

Every orchestrator.run() and dev_fleet.run_fleet() call persists its full
result here as JSONB AND as structured relational rows that survive terminal
closures, conversation summarizations, and machine reboots.

Schema (3 tables, auto-created idempotent):

  agent_runs                    — raw output blob (one row per run)
  ├─ run_id        TEXT PK
  ├─ thread_id     TEXT         LangGraph checkpoint linkage
  ├─ fleet         TEXT         'orchestrator' | 'dev_fleet'
  ├─ request       TEXT         original user request
  ├─ status        TEXT         'completed' | 'failed'
  ├─ agent_results JSONB        list[AgentResult | TeamResult] verbatim
  ├─ final_response TEXT        synthesized plain-text summary
  ├─ metadata      JSONB        fleet-specific extras
  ├─ created_at    TIMESTAMPTZ
  └─ completed_at  TIMESTAMPTZ

  fleet_runs                    — one structured summary row per run (1 side)
  ├─ run_id        TEXT PK FK→agent_runs.run_id
  ├─ fleet         TEXT
  ├─ subject       TEXT         one-line description of what the run was for
  ├─ request       TEXT         full original request
  ├─ status        TEXT
  ├─ agent_count   INT          how many agents / teams ran
  ├─ total_rows    INT          total data items collected across all agents
  ├─ duration_secs FLOAT        wall-clock seconds
  ├─ tags          TEXT[]       topic tags extracted from request
  ├─ created_at    TIMESTAMPTZ
  └─ completed_at  TIMESTAMPTZ

  fleet_run_agents              — one row per agent per run (many side)
  ├─ id            BIGSERIAL PK
  ├─ run_id        TEXT FK→fleet_runs.run_id (CASCADE DELETE)
  ├─ agent_id      TEXT         'researcher' | 'builder' | 'team_Alpha' etc.
  ├─ agent_type    TEXT         normalized: 'researcher'|'builder'|'verifier'|'scribe'|'coder'|'tester'
  ├─ task_prompt   TEXT         exact task instruction sent to this agent
  ├─ system_prompt_excerpt TEXT first 500 chars of system prompt (if available)
  ├─ rows_collected INT         data items produced (tool outputs, LanceDB rows, file edits)
  ├─ success       BOOLEAN
  ├─ error         TEXT
  ├─ iterations    INT          dev_fleet: coder→tester iteration count
  ├─ final_status  TEXT         'PASS'|'FAIL'|'ESCALATED'|'EXHAUSTED' (dev_fleet teams)
  ├─ result_preview TEXT        first 500 chars of result text
  ├─ result_full   JSONB        full agent result blob (cross-ref to agent_runs.agent_results)
  ├─ duration_secs FLOAT        per-agent wall-clock estimate
  └─ created_at    TIMESTAMPTZ

Quick queries:
    from agents.run_store import list_runs, list_fleet_runs, get_fleet_run

    # Summary table (structured)
    for r in list_fleet_runs(n=5):
        print(r['run_id'], r['subject'], r['agent_count'], r['total_rows'])

    # Full drilldown: run + per-agent detail
    detail = get_fleet_run(run_id)
    print(detail['subject'], detail['total_rows'])
    for a in detail['agents']:
        print(f"  {a['agent_id']:20s} rows={a['rows_collected']} {a['result_preview'][:60]}")

    # Raw blobs (legacy)
    for r in list_runs(n=5):
        print(r['run_id'], r['fleet'], r['status'], r['created_at'])
"""

from __future__ import annotations

import json
import os
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

_DEFAULT_DSN = "postgresql://postgres:d1204l0723@localhost:5432/postgres"
_DSN = os.environ.get("PG_DSN", _DEFAULT_DSN)

_DDL = """
-- ── Raw blob store ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id         TEXT        PRIMARY KEY,
    thread_id      TEXT        NOT NULL,
    fleet          TEXT        NOT NULL DEFAULT 'orchestrator',
    request        TEXT        NOT NULL,
    status         TEXT        NOT NULL DEFAULT 'completed',
    agent_results  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    final_response TEXT,
    metadata       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agent_runs_idx_thread    ON agent_runs (thread_id);
CREATE INDEX IF NOT EXISTS agent_runs_idx_fleet_ts  ON agent_runs (fleet, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_runs_idx_status    ON agent_runs (status);

-- ── Structured run log — 1 row per run (parent) ───────────────────────────────
CREATE TABLE IF NOT EXISTS fleet_runs (
    run_id         TEXT        PRIMARY KEY REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    fleet          TEXT        NOT NULL DEFAULT 'orchestrator',
    subject        TEXT        NOT NULL,   -- one-line: what was this run for?
    request        TEXT        NOT NULL,   -- full original request text
    status         TEXT        NOT NULL DEFAULT 'completed',
    agent_count    INT         NOT NULL DEFAULT 0,
    total_rows     INT         NOT NULL DEFAULT 0,  -- data items collected summed across agents
    duration_secs  FLOAT,
    tags           TEXT[]      NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS fleet_runs_idx_fleet_ts  ON fleet_runs (fleet, created_at DESC);
CREATE INDEX IF NOT EXISTS fleet_runs_idx_tags      ON fleet_runs USING GIN (tags);

-- ── Structured run log — 1 row per agent per run (child, many side) ───────────
CREATE TABLE IF NOT EXISTS fleet_run_agents (
    id                     BIGSERIAL   PRIMARY KEY,
    run_id                 TEXT        NOT NULL REFERENCES fleet_runs(run_id) ON DELETE CASCADE,
    agent_id               TEXT        NOT NULL,  -- 'researcher' | 'team_Alpha' etc.
    agent_type             TEXT        NOT NULL,  -- normalised type bucket
    task_prompt            TEXT,                  -- task string sent to this agent
    system_prompt_excerpt  TEXT,                  -- first 500 chars of system prompt
    rows_collected         INT         NOT NULL DEFAULT 0,
    success                BOOLEAN     NOT NULL DEFAULT TRUE,
    error                  TEXT,
    iterations             INT         NOT NULL DEFAULT 1,  -- dev_fleet coder→tester rounds
    final_status           TEXT,                 -- 'PASS'|'FAIL'|'ESCALATED'|'EXHAUSTED'
    result_preview         TEXT,                 -- first 500 chars of final result text
    result_full            JSONB,                -- full agent result blob
    duration_secs          FLOAT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fra_idx_run_id    ON fleet_run_agents (run_id);
CREATE INDEX IF NOT EXISTS fra_idx_agent_id  ON fleet_run_agents (agent_id);
CREATE INDEX IF NOT EXISTS fra_idx_type      ON fleet_run_agents (agent_type);
"""


# ── Connection ────────────────────────────────────────────────────────────────


def _connect():
    """Return a psycopg3 connection (autocommit=True)."""
    try:
        import psycopg  # psycopg3

        return psycopg.connect(_DSN, autocommit=True)
    except ImportError:
        import psycopg2  # fallback

        conn = psycopg2.connect(_DSN)
        conn.autocommit = True
        return conn


# ── Setup (idempotent DDL) ────────────────────────────────────────────────────

_setup_done = False


def setup() -> None:
    """Create the agent_runs table + indexes if they don't exist. Idempotent."""
    global _setup_done
    if _setup_done:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL)
        _setup_done = True
    except Exception as exc:
        warnings.warn(
            f"run_store.setup() failed — results will NOT be persisted to Postgres: {exc}",
            stacklevel=2,
        )


# ── Write ─────────────────────────────────────────────────────────────────────


def save_run(
    *,
    run_id: str | None = None,
    thread_id: str,
    fleet: str = "orchestrator",
    request: str,
    agent_results: list[dict[str, Any]],
    final_response: str,
    status: str = "completed",
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> str:
    """
    Persist a completed agent run. Returns the run_id.

    ``agent_results`` accepts any list of dicts — AgentResult objects from
    the orchestrator, TeamResult objects from dev_fleet, or mixed.  Unknown
    value types are serialised via json.dumps(default=str) so nothing is lost.

    Creates the table on first call (idempotent).
    Returns run_id even if the Postgres write fails (falls back silently so
    callers are never broken by a DB hiccup).
    """
    setup()
    rid = run_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created = created_at or now

    def _safe_json(obj: Any) -> str:
        return json.dumps(obj, default=str)

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_runs
                        (run_id, thread_id, fleet, request, status,
                         agent_results, final_response, metadata,
                         created_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        status         = EXCLUDED.status,
                        agent_results  = EXCLUDED.agent_results,
                        final_response = EXCLUDED.final_response,
                        metadata       = EXCLUDED.metadata,
                        completed_at   = EXCLUDED.completed_at
                    """,
                    (
                        rid,
                        thread_id,
                        fleet,
                        request,
                        status,
                        _safe_json(agent_results),
                        final_response,
                        _safe_json(metadata or {}),
                        created,
                        now,
                    ),
                )
    except Exception as exc:
        warnings.warn(
            f"run_store.save_run() DB write failed (run_id={rid}): {exc}",
            stacklevel=2,
        )
        return rid

    # ── Write structured log tables (fleet_runs + fleet_run_agents) ──────────
    _save_run_log(
        run_id=rid,
        fleet=fleet,
        request=request,
        agent_results=agent_results,
        final_response=final_response,
        status=status,
        created_at=created,
        completed_at=now,
        metadata=metadata,
    )

    return rid


def save_run_failed(
    *,
    thread_id: str,
    fleet: str = "orchestrator",
    request: str,
    error: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Convenience wrapper: persist a failed run with an error message."""
    return save_run(
        thread_id=thread_id,
        fleet=fleet,
        request=request,
        agent_results=[],
        final_response=f"[FAILED] {error}",
        status="failed",
        metadata={"error": error, **(metadata or {})},
    )


# ── Structured log helpers ────────────────────────────────────────────────────


def _normalize_agent_type(agent_id: str) -> str:
    """Map any agent_id string to a canonical bucket."""
    aid = agent_id.lower()
    for canonical in (
        "researcher",
        "builder",
        "verifier",
        "scribe",
        "coder",
        "tester",
        "librarian",
        "skeptic",
        "synthesizer",
    ):
        if canonical in aid:
            return canonical
    if "team" in aid:
        return "coder"  # dev_fleet teams are coder/tester pairs
    return "unknown"


def _estimate_rows_collected(result: Any) -> int:
    """
    Heuristic: count meaningful data items produced by an agent.
    Tries JSON array length first, then line count of text result.
    Returns 0 on failure.
    """
    if result is None:
        return 0
    # If result is already a dict/list (TeamResult etc.)
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        # dev_fleet history list
        if "history" in result:
            return len(result["history"])
        # orchestrator AgentResult with JSON string result field
        inner = result.get("result", "")
        if isinstance(inner, str):
            try:
                parsed = json.loads(inner)
                if isinstance(parsed, list):
                    return len(parsed)
                if isinstance(parsed, dict):
                    # count top-level keys as a rough proxy
                    return len(parsed)
            except (json.JSONDecodeError, ValueError):
                pass
            return max(1, inner.count("\n"))
        return 1
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                return len(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
        return max(1, result.count("\n"))
    return 1


def _extract_subject(request: str, final_response: str | None) -> str:
    """Derive a ≤120-char subject line: first sentence of request, stripped."""
    text = (request or "").strip()
    # Take everything up to the first sentence break or 120 chars
    for sep in (".", "\n", "?", "!"):
        idx = text.find(sep)
        if 0 < idx < 120:
            return text[:idx].strip()
    return text[:120].strip() or "(no subject)"


def _extract_tags(request: str) -> list[str]:
    """Simple keyword extractor: lower-cased words that look like topic tags."""
    STOP = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "to",
        "in",
        "of",
        "is",
        "it",
        "that",
        "this",
        "we",
        "our",
        "all",
        "any",
        "be",
        "was",
        "are",
        "by",
        "as",
        "at",
        "on",
        "with",
        "from",
        "have",
        "has",
        "do",
        "not",
        "also",
        "need",
        "should",
        "will",
        "can",
    }
    words = set()
    for w in request.lower().split():
        w = w.strip(".,;:\"'()[]{}!?")
        if len(w) >= 4 and w not in STOP and w.isalpha():
            words.add(w)
    # favour known domain words
    DOMAIN = {
        "cmake",
        "build",
        "gcode",
        "schema",
        "lancedb",
        "postgres",
        "agent",
        "fleet",
        "researcher",
        "builder",
        "verifier",
        "scribe",
        "coder",
        "tester",
        "orchestrator",
        "refiner",
        "texture",
        "slicer",
        "nexusmill",
        "nexusslicer",
        "qidistudio",
        "python",
        "typescript",
        "react",
    }
    tags = sorted((words & DOMAIN) | {w for w in words if w in DOMAIN})
    # fill up to 8 generic tags
    generic = sorted(words - set(tags))
    return (tags + generic)[:8]


def _save_run_log(
    run_id: str,
    fleet: str,
    request: str,
    agent_results: list[dict[str, Any]],
    final_response: str | None,
    status: str,
    created_at: "datetime",
    completed_at: "datetime",
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Write fleet_runs (parent) and fleet_run_agents (children) rows for a run.
    Called automatically by save_run().  Silent on DB errors.
    """

    def _safe_json(obj: Any) -> str:
        return json.dumps(obj, default=str)

    subject = _extract_subject(request, final_response)
    tags = _extract_tags(request)
    duration = (
        (completed_at - created_at).total_seconds()
        if completed_at and created_at
        else None
    )

    # ── Collect per-agent rows ────────────────────────────────────────────────
    agent_rows: list[dict[str, Any]] = []
    for res in agent_results:
        if not isinstance(res, dict):
            continue
        agent_id = res.get("agent_id") or res.get("team_name") or "unknown"
        agent_type = _normalize_agent_type(agent_id)

        # Task prompt: the task field for orchestrator, or task field for teams
        task_prompt = res.get("task") or res.get("task_description") or ""

        # rows collected
        rows = _estimate_rows_collected(res)

        success = bool(res.get("success", True))
        error = res.get("error") or (None if success else "unknown error")

        # dev_fleet team fields
        iterations = res.get("iterations_completed", 1)
        final_status = res.get("final_status")  # PASS/FAIL/ESCALATED/EXHAUSTED

        # result text
        raw_result = res.get("result") or res.get("final_status") or ""
        if isinstance(raw_result, dict):
            raw_result = json.dumps(raw_result, default=str)
        result_preview = str(raw_result)[:500]

        agent_rows.append(
            {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "task_prompt": str(task_prompt)[:2000],
                "rows_collected": rows,
                "success": success,
                "error": str(error)[:500] if error else None,
                "iterations": iterations if isinstance(iterations, int) else 1,
                "final_status": final_status,
                "result_preview": result_preview,
                "result_full": res,  # full blob — serialised as JSONB
            }
        )

    total_rows = sum(a["rows_collected"] for a in agent_rows)

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Parent
                cur.execute(
                    """
                    INSERT INTO fleet_runs
                        (run_id, fleet, subject, request, status,
                         agent_count, total_rows, duration_secs, tags,
                         created_at, completed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        status         = EXCLUDED.status,
                        agent_count    = EXCLUDED.agent_count,
                        total_rows     = EXCLUDED.total_rows,
                        duration_secs  = EXCLUDED.duration_secs,
                        tags           = EXCLUDED.tags,
                        completed_at   = EXCLUDED.completed_at
                    """,
                    (
                        run_id,
                        fleet,
                        subject,
                        request,
                        status,
                        len(agent_rows),
                        total_rows,
                        duration,
                        tags,
                        created_at,
                        completed_at,
                    ),
                )
                # Children — delete existing children on re-upsert, then re-insert
                cur.execute("DELETE FROM fleet_run_agents WHERE run_id = %s", (run_id,))
                for a in agent_rows:
                    cur.execute(
                        """
                        INSERT INTO fleet_run_agents
                            (run_id, agent_id, agent_type, task_prompt,
                             rows_collected, success, error,
                             iterations, final_status,
                             result_preview, result_full, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                        """,
                        (
                            run_id,
                            a["agent_id"],
                            a["agent_type"],
                            a["task_prompt"],
                            a["rows_collected"],
                            a["success"],
                            a["error"],
                            a["iterations"],
                            a["final_status"],
                            a["result_preview"],
                            _safe_json(a["result_full"]),
                            created_at,
                        ),
                    )
    except Exception as exc:
        warnings.warn(
            f"run_store._save_run_log() failed for run_id={run_id}: {exc}",
            stacklevel=3,
        )


# ── Read ──────────────────────────────────────────────────────────────────────


def _row_to_dict(row, cursor) -> dict[str, Any]:
    """Convert a DB row + cursor.description into a plain dict."""
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


def get_run(run_id: str) -> dict[str, Any] | None:
    """
    Fetch a single run by run_id.  Returns None if not found.

    The returned dict matches the table schema:
        {run_id, thread_id, fleet, request, status,
         agent_results (list), final_response, metadata (dict),
         created_at, completed_at}
    """
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM agent_runs WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                return _row_to_dict(row, cur)
    except Exception as exc:
        warnings.warn(f"run_store.get_run() failed: {exc}", stacklevel=2)
        return None


def list_runs(
    n: int = 20,
    fleet: str | None = None,
    status: str | None = None,
    thread_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return the most recent ``n`` runs, newest first.

    Filters (all optional):
        fleet      — 'orchestrator' | 'dev_fleet'
        status     — 'completed' | 'failed'
        thread_id  — exact match

    Each row:
        {run_id, thread_id, fleet, request (truncated to 120 chars),
         status, final_response (truncated to 500 chars),
         created_at, completed_at}
    """
    setup()
    clauses: list[str] = []
    params: list[Any] = []
    if fleet:
        clauses.append("fleet = %s")
        params.append(fleet)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if thread_id:
        clauses.append("thread_id = %s")
        params.append(thread_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(n)

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        run_id,
                        thread_id,
                        fleet,
                        LEFT(request, 120)          AS request,
                        status,
                        LEFT(final_response, 500)   AS final_response,
                        jsonb_array_length(agent_results) AS result_count,
                        created_at,
                        completed_at
                    FROM agent_runs
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()
                return [_row_to_dict(r, cur) for r in rows]
    except Exception as exc:
        warnings.warn(f"run_store.list_runs() failed: {exc}", stacklevel=2)
        return []


def get_latest_run(
    fleet: str | None = None,
    status: str = "completed",
) -> dict[str, Any] | None:
    """Return the single most recent completed run (full row with agent_results)."""
    setup()
    clauses = ["status = %s"]
    params: list[Any] = [status]
    if fleet:
        clauses.append("fleet = %s")
        params.append(fleet)
    where = "WHERE " + " AND ".join(clauses)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM agent_runs {where} ORDER BY created_at DESC LIMIT 1",
                    params,
                )
                row = cur.fetchone()
                return _row_to_dict(row, cur) if row else None
    except Exception as exc:
        warnings.warn(f"run_store.get_latest_run() failed: {exc}", stacklevel=2)
        return None


def get_run_result(run_id: str, agent_id: str | None = None) -> str | None:
    """
    Convenience: return the final_response of a run, or (if agent_id is given)
    the result field of that specific agent's AgentResult within the run.

    Returns None if the run or agent is not found.
    """
    run = get_run(run_id)
    if run is None:
        return None
    if agent_id is None:
        return run.get("final_response")
    results = run.get("agent_results") or []
    for r in results:
        if isinstance(r, dict) and r.get("agent_id") == agent_id:
            return r.get("result") or r.get("final_status")
    return None


# ── Structured log reads ──────────────────────────────────────────────────────


def list_fleet_runs(
    n: int = 20,
    fleet: str | None = None,
    status: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return the most recent ``n`` fleet_runs summary rows, newest first.

    Each row: {run_id, fleet, subject, status, agent_count,
               total_rows, duration_secs, tags, created_at, completed_at}

    Filters (all optional):
        fleet   — 'orchestrator' | 'dev_fleet'
        status  — 'completed' | 'failed'
        tag     — match any element in tags array (e.g. 'cmake', 'schema-fix')
    """
    setup()
    clauses: list[str] = []
    params: list[Any] = []
    if fleet:
        clauses.append("fleet = %s")
        params.append(fleet)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if tag:
        clauses.append("%s = ANY(tags)")
        params.append(tag)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(n)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        run_id, fleet, subject, status,
                        agent_count, total_rows, duration_secs,
                        tags, created_at, completed_at
                    FROM fleet_runs
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                return [_row_to_dict(r, cur) for r in cur.fetchall()]
    except Exception as exc:
        warnings.warn(f"run_store.list_fleet_runs() failed: {exc}", stacklevel=2)
        return []


def get_fleet_run(run_id: str) -> dict[str, Any] | None:
    """
    Full drilldown: fleet_runs parent row + all fleet_run_agents children.

    Returns:
        {
            run_id, fleet, subject, request, status,
            agent_count, total_rows, duration_secs, tags,
            created_at, completed_at,
            agents: [
                {id, agent_id, agent_type, task_prompt,
                 rows_collected, success, error, iterations,
                 final_status, result_preview, result_full,
                 duration_secs, created_at},
                ...
            ]
        }
    """
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM fleet_runs WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                parent = _row_to_dict(row, cur)

                cur.execute(
                    """
                    SELECT * FROM fleet_run_agents
                    WHERE run_id = %s
                    ORDER BY id
                    """,
                    (run_id,),
                )
                children = [_row_to_dict(r, cur) for r in cur.fetchall()]
                parent["agents"] = children
                return parent
    except Exception as exc:
        warnings.warn(f"run_store.get_fleet_run() failed: {exc}", stacklevel=2)
        return None


def get_latest_fleet_run(fleet: str | None = None) -> dict[str, Any] | None:
    """Return the latest completed fleet_run with its agents list."""
    setup()
    clauses = ["status = 'completed'"]
    params: list[Any] = []
    if fleet:
        clauses.append("fleet = %s")
        params.append(fleet)
    where = "WHERE " + " AND ".join(clauses)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT run_id FROM fleet_runs {where} ORDER BY created_at DESC LIMIT 1",
                    params,
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return get_fleet_run(row[0])
    except Exception as exc:
        warnings.warn(f"run_store.get_latest_fleet_run() failed: {exc}", stacklevel=2)
        return None


# ── CLI inspection ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    # Ensure ✓/✗ symbols render correctly on Windows cp1252 terminals
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(
        description="Inspect agent_runs / fleet_runs tables. No args = list latest 10 runs."
    )
    parser.add_argument(
        "--run-id", "-r", help="Show full details of a specific run (raw blobs)"
    )
    parser.add_argument("--fleet", "-f", help="Filter by fleet name")
    parser.add_argument(
        "--status", "-s", choices=["completed", "failed"], help="Filter by status"
    )
    parser.add_argument(
        "--n", "-n", type=int, default=10, help="Number of runs to list"
    )
    parser.add_argument(
        "--latest",
        "-l",
        action="store_true",
        help="Show full details of the latest run",
    )
    parser.add_argument(
        "--log", action="store_true", help="Show structured fleet_runs summary table"
    )
    parser.add_argument(
        "--detail", "-d", help="Drilldown: fleet_run + all agent rows for a run_id"
    )
    parser.add_argument(
        "--latest-detail",
        action="store_true",
        help="Drilldown for the latest fleet run",
    )
    parser.add_argument("--tag", "-t", help="Filter fleet_runs by tag")
    args = parser.parse_args()

    # ── Structured fleet_runs table ───────────────────────────────────────────
    if args.log:
        runs = list_fleet_runs(
            n=args.n, fleet=args.fleet, status=args.status, tag=args.tag
        )
        if not runs:
            print("No fleet_runs found.")
            sys.exit(0)
        print(
            f"\n{'RUN_ID':<36}  {'FLEET':<12}  {'S':<1}  {'AGT':>3}  {'ROWS':>5}  {'SECS':>6}  {'CREATED':19}  SUBJECT"
        )
        print("-" * 120)
        for r in runs:
            s = "✓" if r["status"] == "completed" else "✗"
            dur = f"{r['duration_secs']:.1f}" if r.get("duration_secs") else "  ?"
            ts = str(r["created_at"])[:19]
            subj = (r["subject"] or "")[:55]
            print(
                f"{r['run_id']:<36}  {r['fleet']:<12}  {s}  {r['agent_count']:>3}  {r['total_rows']:>5}  {dur:>6}  {ts}  {subj}"
            )
        sys.exit(0)

    # ── Drilldown: fleet_run + agents ─────────────────────────────────────────
    drill_id = args.detail
    if args.latest_detail:
        fr = get_latest_fleet_run(fleet=args.fleet)
        if fr is None:
            print("No completed fleet runs found.", file=sys.stderr)
            sys.exit(1)
        drill_id = fr["run_id"]

    if drill_id:
        fr = get_fleet_run(drill_id)
        if fr is None:
            print(f"Fleet run {drill_id!r} not found.", file=sys.stderr)
            sys.exit(1)
        dur = f"{fr['duration_secs']:.1f}s" if fr.get("duration_secs") else "?"
        print(f"\n{'='*70}")
        print(f"Run ID   : {fr['run_id']}")
        print(f"Fleet    : {fr['fleet']}")
        print(f"Status   : {fr['status']}")
        print(f"Created  : {str(fr['created_at'])[:19]}  ({dur})")
        print(f"Tags     : {', '.join(fr.get('tags') or []) or 'none'}")
        print(f"Subject  : {fr['subject']}")
        print(f"Request  : {(fr['request'] or '')[:300]}")
        print(
            f"\nAgents ({fr['agent_count']})  |  Total rows collected: {fr['total_rows']}"
        )
        print("-" * 70)
        for a in fr.get("agents", []):
            ok = "✓" if a["success"] else "✗"
            itr = f" ×{a['iterations']}" if a["iterations"] > 1 else ""
            fs = f" [{a['final_status']}]" if a.get("final_status") else ""
            print(
                f"  {ok} {a['agent_id']:<22} type={a['agent_type']:<12} rows={a['rows_collected']:>4}{itr}{fs}"
            )
            if a.get("task_prompt"):
                print(f"    prompt: {a['task_prompt'][:120]}")
            if a.get("result_preview"):
                print(f"    result: {a['result_preview'][:160]}")
            if a.get("error"):
                print(f"    ERROR:  {a['error'][:120]}")
        sys.exit(0)

    # ── Raw agent_runs lookup ─────────────────────────────────────────────────
    if args.run_id:
        run = get_run(args.run_id)
        if run is None:
            print(f"Run {args.run_id!r} not found.", file=sys.stderr)
            sys.exit(1)
        print(f"\n{'='*70}")
        print(f"Run ID   : {run['run_id']}")
        print(f"Thread   : {run['thread_id']}")
        print(f"Fleet    : {run['fleet']}")
        print(f"Status   : {run['status']}")
        print(f"Created  : {run['created_at']}")
        print(f"Request  : {run['request'][:200]}")
        print(f"\n--- Final Response ---\n{run['final_response']}")
        print(f"\n--- Agent Results ({len(run['agent_results'] or [])} items) ---")
        for ar in run["agent_results"] or []:
            aid = ar.get("agent_id") or ar.get("team_name", "?")
            res = (ar.get("result") or ar.get("final_status") or "")[:300]
            print(f"  [{aid}] {res}")
    elif args.latest:
        run = get_latest_run(fleet=args.fleet)
        if run is None:
            print("No completed runs found.", file=sys.stderr)
            sys.exit(1)
        print(f"\n--- Latest Run: {run['run_id']} ---")
        print(f"Fleet    : {run['fleet']}")
        print(f"Created  : {run['created_at']}")
        print(f"Request  : {run['request'][:200]}")
        print(f"\n{run['final_response']}")
    else:
        runs = list_runs(n=args.n, fleet=args.fleet, status=args.status)
        if not runs:
            print("No runs found.")
            sys.exit(0)
        print(
            f"\n{'RUN_ID':<36}  {'FLEET':<12}  {'STATUS':<10}  {'#':<3}  {'CREATED':24}  REQUEST"
        )
        print("-" * 110)
        for r in runs:
            cnt = r.get("result_count") or 0
            ts = str(r["created_at"])[:19]
            req = (r["request"] or "")[:50]
            print(
                f"{r['run_id']:<36}  {r['fleet']:<12}  {r['status']:<10}  {cnt:<3}  {ts:24}  {req}"
            )
