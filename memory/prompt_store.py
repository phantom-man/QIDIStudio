"""
memory/prompt_store.py — PostgreSQL store for every Claude prompt + response.

Schema (auto-created, idempotent):

  prompts                         responses
  ────────────────────────────    ────────────────────────────────
  prompt_id   TEXT PK (UUID)  →   prompt_id   TEXT FK (CASCADE)
  session_id  TEXT                response_id TEXT PK (UUID)
  prompt_text TEXT                session_id  TEXT
  created_at  TIMESTAMPTZ         response_text TEXT
                                  is_compaction BOOLEAN
                                  created_at  TIMESTAMPTZ
                                  synced_at   TIMESTAMPTZ  ← set by sync job

Why two tables:
  The UserPromptSubmit hook writes a row to `prompts` instantly.
  The Stop hook writes the matching row to `responses` after the turn ends.
  The 30-min sync job joins them and pushes new pairs to LanceDB.

CLI (called from PowerShell hooks — all args avoid shell-quoting problems):

  # Save a user prompt (call from UserPromptSubmit hook):
  python -m memory.prompt_store --save-prompt \\
      --prompt-id <uuid> --session-id <sid> --file <path-to-prompt-text-file>

  # Save an assistant response (call from Stop hook):
  python -m memory.prompt_store --save-response \\
      --prompt-id <uuid> --session-id <sid> --file <path-to-response-text-file>

  # Print today's session stats (call from Stop hook — writes to stdout + stats file):
  python -m memory.prompt_store --daily-stats

  # List unsynced pairs (called by sync job):
  python -m memory.prompt_store --unsynced [--limit 200]
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import warnings
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

_DEFAULT_DSN = "postgresql://postgres:d1204l0723@localhost:5432/postgres"
_DSN = os.environ.get("PG_DSN", _DEFAULT_DSN)

# File written by Stop hook so the next turn's UserPromptSubmit can inject today's stats
_STATS_FILE = REPO_ROOT / "memory" / "_session_stats.txt"

# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS prompts (
    prompt_id   TEXT        PRIMARY KEY,
    session_id  TEXT        NOT NULL,
    prompt_text TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS prompts_idx_session ON prompts (session_id);
CREATE INDEX IF NOT EXISTS prompts_idx_date    ON prompts (created_at DESC);

CREATE TABLE IF NOT EXISTS responses (
    response_id    TEXT        PRIMARY KEY,
    prompt_id      TEXT        NOT NULL REFERENCES prompts(prompt_id) ON DELETE CASCADE,
    session_id     TEXT        NOT NULL,
    response_text  TEXT        NOT NULL,
    is_compaction  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    synced_at      TIMESTAMPTZ                         -- NULL = not yet in LanceDB
);
CREATE INDEX IF NOT EXISTS responses_idx_prompt   ON responses (prompt_id);
CREATE INDEX IF NOT EXISTS responses_idx_session  ON responses (session_id);
CREATE INDEX IF NOT EXISTS responses_idx_date     ON responses (created_at DESC);
CREATE INDEX IF NOT EXISTS responses_idx_unsynced ON responses (synced_at) WHERE synced_at IS NULL;
"""

# ── Connection ────────────────────────────────────────────────────────────────


def _connect():
    try:
        import psycopg

        return psycopg.connect(_DSN, autocommit=True)
    except ImportError:
        import psycopg2

        conn = psycopg2.connect(_DSN)
        conn.autocommit = True
        return conn


_setup_done = False


def setup() -> None:
    """Create tables if they don't exist. Idempotent."""
    global _setup_done
    if _setup_done:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL)
        _setup_done = True
    except Exception as exc:
        warnings.warn(f"prompt_store.setup() failed: {exc}", stacklevel=2)


# ── Write ─────────────────────────────────────────────────────────────────────


def save_prompt(prompt_id: str, session_id: str, prompt_text: str) -> bool:
    """Insert a user prompt row. Returns True on success."""
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO prompts (prompt_id, session_id, prompt_text)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (prompt_id) DO NOTHING
                    """,
                    (prompt_id, session_id, prompt_text),
                )
        return True
    except Exception as exc:
        warnings.warn(f"prompt_store.save_prompt() failed: {exc}", stacklevel=2)
        return False


def save_response(
    prompt_id: str,
    session_id: str,
    response_text: str,
    is_compaction: bool = False,
) -> str | None:
    """
    Insert an assistant response row.
    Returns the response_id (UUID) on success, None on failure.
    Idempotent: if a response for prompt_id already exists, returns existing id.
    """
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                # Check if already saved
                cur.execute(
                    "SELECT response_id FROM responses WHERE prompt_id = %s LIMIT 1",
                    (prompt_id,),
                )
                existing = cur.fetchone()
                if existing:
                    return existing[0]

                rid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO responses
                        (response_id, prompt_id, session_id, response_text, is_compaction)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (rid, prompt_id, session_id, response_text, is_compaction),
                )
                return rid
    except Exception as exc:
        warnings.warn(f"prompt_store.save_response() failed: {exc}", stacklevel=2)
        return None


def mark_synced(response_id: str) -> None:
    """Mark a response row as synced to LanceDB."""
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE responses SET synced_at = now() WHERE response_id = %s",
                    (response_id,),
                )
    except Exception as exc:
        warnings.warn(f"prompt_store.mark_synced() failed: {exc}", stacklevel=2)


# ── Read ──────────────────────────────────────────────────────────────────────


def get_unsynced_pairs(limit: int = 500) -> list[dict[str, Any]]:
    """
    Return up to `limit` prompt+response pairs not yet synced to LanceDB.
    Each dict: {prompt_id, response_id, session_id, prompt_text, response_text,
                is_compaction, created_at}
    """
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.prompt_id, r.response_id,
                        p.session_id,
                        p.prompt_text, r.response_text,
                        r.is_compaction, r.created_at
                    FROM responses r
                    JOIN prompts p ON p.prompt_id = r.prompt_id
                    WHERE r.synced_at IS NULL
                    ORDER BY r.created_at ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        warnings.warn(f"prompt_store.get_unsynced_pairs() failed: {exc}", stacklevel=2)
        return []


def get_all_pairs(limit: int = 2000) -> list[dict[str, Any]]:
    """Return all completed Q&A pairs, newest first. Used to regenerate .md files."""
    setup()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.prompt_id, r.response_id,
                        p.session_id,
                        p.prompt_text, r.response_text,
                        r.is_compaction, r.created_at, r.synced_at
                    FROM responses r
                    JOIN prompts p ON p.prompt_id = r.prompt_id
                    ORDER BY r.created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        warnings.warn(f"prompt_store.get_all_pairs() failed: {exc}", stacklevel=2)
        return []


def get_daily_prompts(for_date: date | None = None) -> list[dict[str, Any]]:
    """Return all prompts for a given date (default: today)."""
    setup()
    target = for_date or datetime.now(timezone.utc).date()
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT prompt_id, session_id, prompt_text, created_at
                    FROM prompts
                    WHERE created_at::date = %s
                    ORDER BY created_at ASC
                    """,
                    (target,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        warnings.warn(f"prompt_store.get_daily_prompts() failed: {exc}", stacklevel=2)
        return []


def format_daily_stats(for_date: date | None = None) -> str:
    """Build the daily stats string (used by Stop hook + next-turn injection)."""
    target = for_date or datetime.now(timezone.utc).date()
    prompts = get_daily_prompts(target)
    lines = [
        f"",
        f"━━━ SESSION STATS FOR {target} ({len(prompts)} prompts today) ━━━",
    ]
    for i, p in enumerate(prompts, 1):
        ts = str(p["created_at"])[:16]
        snippet = p["prompt_text"].replace("\n", " ")[:100]
        lines.append(f"  [{i:02d}] {ts}  {snippet}")
    lines.append("━━━ END STATS ━━━")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="prompt_store CLI — called by PowerShell hooks."
    )
    sub = parser.add_subparsers(dest="cmd")

    sp = sub.add_parser("save-prompt")
    sp.add_argument("--prompt-id", required=True)
    sp.add_argument("--session-id", required=True)
    sp.add_argument("--file", required=True, help="Path to file containing prompt text")

    sr = sub.add_parser("save-response")
    sr.add_argument("--prompt-id", required=True)
    sr.add_argument("--session-id", required=True)
    sr.add_argument(
        "--file", required=True, help="Path to file containing response text"
    )
    sr.add_argument(
        "--compaction", action="store_true", help="Mark as compaction summary"
    )

    sub.add_parser("daily-stats")

    su = sub.add_parser("unsynced")
    su.add_argument("--limit", type=int, default=500)

    # Support both subcommand style and flat --flag style (used by existing hooks)
    parser.add_argument("--save-prompt", action="store_true")
    parser.add_argument("--save-response", action="store_true")
    parser.add_argument("--daily-stats", action="store_true")
    parser.add_argument("--unsynced", action="store_true")
    parser.add_argument("--prompt-id")
    parser.add_argument("--session-id")
    parser.add_argument("--file")
    parser.add_argument("--compaction", action="store_true")
    parser.add_argument("--limit", type=int, default=500)

    args = parser.parse_args()

    # Resolve command from either subcommand or flat flags
    cmd = args.cmd
    if not cmd:
        if args.save_prompt:
            cmd = "save-prompt"
        elif args.save_response:
            cmd = "save-response"
        elif args.daily_stats:
            cmd = "daily-stats"
        elif args.unsynced:
            cmd = "unsynced"

    if cmd == "save-prompt":
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        ok = save_prompt(args.prompt_id, args.session_id, text)
        print("OK" if ok else "FAIL")

    elif cmd == "save-response":
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        rid = save_response(
            args.prompt_id,
            args.session_id,
            text,
            is_compaction=bool(args.compaction),
        )
        if rid:
            print(f"OK {rid}")
        else:
            print("FAIL")

    elif cmd == "daily-stats":
        stats = format_daily_stats()
        print(stats)
        # Write to file so next UserPromptSubmit can inject it
        _STATS_FILE.write_text(stats, encoding="utf-8")

    elif cmd == "unsynced":
        pairs = get_unsynced_pairs(args.limit)
        print(json.dumps(pairs, default=str))

    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
