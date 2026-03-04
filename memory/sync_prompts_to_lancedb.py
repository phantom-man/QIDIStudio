"""
memory/sync_prompts_to_lancedb.py — 30-minute incremental sync job.

What it does (runs every 30 minutes via Windows Task Scheduler):
  1. Queries `responses` WHERE synced_at IS NULL (unsynced pairs) from Postgres.
  2. Pushes each pair to LanceDB as a searchable knowledge row.
  3. Marks each synced response with synced_at = now().
  4. Regenerates memory/session_learnings_archive.md  (ALL pairs, newest first, last 2000)
  5. Regenerates memory/compaction_summaries.md        (compaction-only entries, last 200)

Run manually:
    memory_env\Scripts\python.exe -B memory/sync_prompts_to_lancedb.py

Run via scheduler (see memory/setup_tasks.ps1):
    schtasks /run /tn "QIDIStudio Prompt Sync"
"""

from __future__ import annotations

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

from memory.prompt_store import (
    get_unsynced_pairs,
    get_all_pairs,
    mark_synced,
    setup as ps_setup,
)

ARCHIVE_PATH = REPO_ROOT / "memory" / "session_learnings_archive.md"
COMPACTION_PATH = REPO_ROOT / "memory" / "compaction_summaries.md"

_ARCHIVE_HEADER = """\
# Session Learnings Archive

Auto-generated from PostgreSQL `prompts` + `responses` tables by `memory/sync_prompts_to_lancedb.py`.
**Do not edit manually** — every run regenerates this file from the database.

Each section is a prompt/response pair indexed in LanceDB.
Run `memory_env\\Scripts\\python.exe memory/extract.py` to re-sync after manual inspection.

"""

_COMPACTION_HEADER = """\
# Compaction Summaries

Auto-generated from PostgreSQL `responses WHERE is_compaction = TRUE`.
Contains structured knowledge summaries written by the agent at context-compaction boundaries.

"""


def _make_lancedb_row(pair: dict) -> dict:
    """Convert a prompt+response pair into a LanceDB row."""
    prompt = (pair["prompt_text"] or "").strip()
    response = (pair["response_text"] or "").strip()
    topic = prompt[:100].replace("\n", " ").strip() or "(no prompt)"
    created = str(pair.get("created_at", ""))[:16]

    content = f"**Prompt ({created}):**\n{prompt}\n\n" f"**Response:**\n{response}"
    return {
        "topic": topic,
        "decision": response[:500].replace("\n", " "),
        "rationale": f"Prompt/response pair. Session: {pair.get('session_id','?')}",
        "content": content,
        "category": "session_qa",
        "date": created[:10] if created else None,
        "source": "prompts/session-qa",
    }


def _write_archive(all_pairs: list[dict]) -> int:
    """Regenerate session_learnings_archive.md from all pairs. Returns row count."""
    lines = [_ARCHIVE_HEADER]
    # Reverse so archive is chronological (oldest first)
    for pair in reversed(all_pairs):
        ts = str(pair.get("created_at", ""))[:19]
        sid = pair.get("session_id", "?")[:8]
        prompt = (pair["prompt_text"] or "").strip()
        response = (pair["response_text"] or "").strip()
        snippet = prompt.replace("\n", " ")[:80]

        lines.append(f"## [{ts}] {snippet}\n")
        lines.append(f"**Session:** `{sid}`\n\n")
        lines.append(f"**Prompt:**\n\n{prompt}\n\n")
        lines.append(f"**Response:**\n\n{response}\n\n")
        lines.append("---\n\n")

    ARCHIVE_PATH.write_text("".join(lines), encoding="utf-8")
    return len(all_pairs)


def _write_compaction_summaries(all_pairs: list[dict]) -> int:
    """Regenerate compaction_summaries.md from compaction-flagged pairs only."""
    compaction = [p for p in all_pairs if p.get("is_compaction")]
    lines = [_COMPACTION_HEADER]
    for pair in reversed(compaction[-200:]):
        ts = str(pair.get("created_at", ""))[:19]
        response = (pair["response_text"] or "").strip()
        lines.append(f"## Compaction Summary [{ts}]\n\n{response}\n\n---\n\n")

    COMPACTION_PATH.write_text("".join(lines), encoding="utf-8")
    return len(compaction)


def run_sync() -> dict:
    """Main sync entry point. Returns stats dict."""
    ps_setup()

    print(f"[sync_prompts] {datetime.now(timezone.utc).isoformat()} — starting")

    # ── 1. Push unsynced pairs to LanceDB ────────────────────────────────
    unsynced = get_unsynced_pairs(limit=500)
    print(f"[sync_prompts] Unsynced pairs: {len(unsynced)}")

    pushed = 0
    if unsynced:
        try:
            from memory.store import batch_upsert

            rows = [_make_lancedb_row(p) for p in unsynced]
            inserted, skipped = batch_upsert(rows, replace_all=False)
            print(f"[sync_prompts] LanceDB inserted={inserted} skipped={skipped}")
            pushed = inserted

            # Mark each as synced
            for pair in unsynced:
                mark_synced(pair["response_id"])
        except Exception as exc:
            print(f"[sync_prompts] ERROR pushing to LanceDB: {exc}", file=sys.stderr)

    # ── 2. Regenerate .md files from full history ─────────────────────────
    all_pairs = get_all_pairs(limit=2000)
    print(f"[sync_prompts] Total pairs in DB: {len(all_pairs)}")

    n_archive = _write_archive(all_pairs)
    n_compaction = _write_compaction_summaries(all_pairs)
    print(f"[sync_prompts] Archive rows={n_archive}  Compaction entries={n_compaction}")
    print(f"[sync_prompts] Written: {ARCHIVE_PATH.name}, {COMPACTION_PATH.name}")

    stats = {
        "unsynced_processed": len(unsynced),
        "lancedb_pushed": pushed,
        "archive_rows": n_archive,
        "compaction_entries": n_compaction,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    print(f"[sync_prompts] Done: {stats}")
    return stats


if __name__ == "__main__":
    result = run_sync()
    sys.exit(0)
