"""
memory/daily_lancedb_dedupe.py — Daily LanceDB deduplication job.

What it does (runs daily via Windows Task Scheduler, e.g. 3:00 AM):
  1. Reads all rows from the LanceDB `qidistudio_learnings` table.
  2. Groups by SHA-256 hash of the `content` field.
  3. Keeps the row with the most information (longest content), deletes dupes.
  4. Also ingests session_learnings_archive.md and compaction_summaries.md
     via extract.py to ensure all pairs are indexed.
  5. Logs stats.

Run manually:
    memory_env\Scripts\python.exe -B memory/daily_lancedb_dedupe.py
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

LOG_PATH = REPO_ROOT / "memory" / "_dedupe.log"


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{ts} {msg}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_dedupe() -> dict:
    _log("daily_lancedb_dedupe — started")

    from memory.store import get_all, batch_upsert

    # ── 1. Read all rows ──────────────────────────────────────────────────
    all_rows = get_all()
    if not all_rows:
        _log("LanceDB is empty — nothing to dedupe")
        return {"total": 0, "dupes_removed": 0}

    _log(f"Total rows in LanceDB: {len(all_rows)}")

    # ── 2. Group by content hash ──────────────────────────────────────────
    by_hash: dict[str, list[dict]] = {}
    for row in all_rows:
        content = (row.get("content") or row.get("decision") or "").strip()
        h = hashlib.sha256(content.encode()).hexdigest()
        by_hash.setdefault(h, []).append(row)

    dupe_groups = [(h, rows) for h, rows in by_hash.items() if len(rows) > 1]
    unique_count = sum(1 for rows in by_hash.values() if len(rows) == 1)
    _log(f"Unique rows: {unique_count}  Duplicate groups: {len(dupe_groups)}")

    if not dupe_groups:
        _log("No duplicates found.")
        return {"total": len(all_rows), "dupes_removed": 0}

    # ── 3. Delete duplicate rows ──────────────────────────────────────────
    # Strategy: for each dupe group, keep the longest-content row.
    # LanceDB delete by topic (unique key we use for upsert).
    try:
        import lancedb  # noqa: PLC0415
        import os

        db_uri = os.environ.get("LANCEDB_URI", "gs://qidistudio-lancedb/lancedb")
        db = lancedb.connect(db_uri)
        tbl_names = [t.name for t in db.list_tables()]
        tbl_name = "qidistudio_learnings"
        if tbl_name not in tbl_names:
            _log(f"Table {tbl_name!r} not found — skipping delete step")
            return {"total": len(all_rows), "dupes_removed": 0}

        tbl = db.open_table(tbl_name)
    except Exception as exc:
        _log(f"ERROR connecting to LanceDB: {exc}")
        return {"total": len(all_rows), "dupes_removed": 0}

    dupes_removed = 0
    for _, dupe_rows in dupe_groups:
        # Sort by content length desc — keep the best (longest) one
        dupe_rows.sort(key=lambda r: len(r.get("content") or ""), reverse=True)
        to_delete = dupe_rows[1:]  # everything except the best

        for row in to_delete:
            topic = row.get("topic", "")
            if not topic:
                continue
            try:
                # LanceDB delete by predicate on the topic column
                safe_topic = topic.replace("'", "''")
                tbl.delete(f"topic = '{safe_topic}'")
                dupes_removed += 1
            except Exception as exc:
                _log(f"  WARN: could not delete topic={topic!r}: {exc}")

    _log(f"Duplicates removed: {dupes_removed}")

    # ── 4. Re-run extract.py to ensure archive + compaction files are indexed ─
    archive_path = REPO_ROOT / "memory" / "session_learnings_archive.md"
    compaction_path = REPO_ROOT / "memory" / "compaction_summaries.md"

    if archive_path.exists() or compaction_path.exists():
        _log("Re-indexing archive + compaction summaries via extract.py...")
        try:
            import subprocess

            py = str(REPO_ROOT / "memory_env" / "Scripts" / "python.exe")
            result = subprocess.run(
                [py, "-B", str(REPO_ROOT / "memory" / "extract.py")],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                timeout=120,
            )
            _log(f"extract.py exit={result.returncode}")
            if result.stdout.strip():
                for line in result.stdout.strip().splitlines()[-10:]:
                    _log(f"  extract: {line}")
        except Exception as exc:
            _log(f"  extract.py call failed: {exc}")

    stats = {
        "total": len(all_rows),
        "dupes_removed": dupes_removed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _log(f"Done: {stats}")
    return stats


if __name__ == "__main__":
    run_dedupe()
    sys.exit(0)
