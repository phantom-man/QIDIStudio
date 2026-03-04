"""
memory/harvest_quality.py — Harvest cross-session quality metrics into LanceDB.

Reads scripts/quality_metrics.jsonl (written by pipeline_tools.assess_quality)
and upserts each row into the qidistudio_learnings LanceDB table as a structured
knowledge entry.  Safe to run repeatedly — already-indexed rows are skipped via
deduplication on the composite key (part_name + logged_at).

Usage:
    memory_env\\Scripts\\python.exe -B memory/harvest_quality.py

Runs automatically as part of memory/extract.py if quality_metrics.jsonl exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
_JSONL_PATH = _REPO_ROOT / "scripts" / "quality_metrics.jsonl"
_CHECKPOINT_PATH = _REPO_ROOT / "scripts" / "_quality_harvest_cursor.txt"


def _load_cursor() -> int:
    """Return byte offset of the last processed position in the JSONL file."""
    try:
        return int(_CHECKPOINT_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _save_cursor(offset: int) -> None:
    _CHECKPOINT_PATH.write_text(str(offset), encoding="utf-8")


def harvest(dry_run: bool = False) -> int:
    """Read new rows from quality_metrics.jsonl and write to LanceDB.

    Returns the number of rows successfully indexed.
    """
    if not _JSONL_PATH.exists():
        print("[harvest_quality] No quality_metrics.jsonl found — nothing to do.")
        return 0

    # Lazy imports so this module can be imported without memory_env deps
    try:
        from memory.store import upsert_learning  # noqa: PLC0415
    except ImportError as exc:
        print(f"[harvest_quality] Cannot import store — run with memory_env: {exc}")
        return 0

    cursor = _load_cursor()
    rows: list[dict] = []

    with _JSONL_PATH.open("rb") as fh:
        fh.seek(cursor)
        while True:
            line = fh.readline()
            if not line:
                new_cursor = fh.tell()
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped.decode("utf-8"))
                rows.append(entry)
            except json.JSONDecodeError:
                pass
        new_cursor = fh.tell()

    if not rows:
        print("[harvest_quality] No new rows since last harvest.")
        return 0

    print(f"[harvest_quality] Indexing {len(rows)} new quality metric(s)…")
    indexed = 0
    for row in rows:
        part = row.get("part_name", "unknown")
        verdict = row.get("verdict", "?")
        logged_at = row.get("logged_at", "")
        u = row.get("uniformity_score")
        s = row.get("seam_score")
        b = row.get("beauty_score")

        topic = f"Quality: {part} ({verdict}) @ {logged_at[:10]}"
        decision = (
            f"Part '{part}' scored verdict={verdict} "
            f"uniformity={u} seam={s} beauty={b}. "
            f"Notes: {row.get('notes', '')}"
        )
        rationale = (
            f"Auto-logged by assess_quality() in autonomous_pipeline. "
            f"artifact_score={row.get('artifact_score')} "
            f"coverage={row.get('coverage_pct')}% "
            f"faces={row.get('face_count')} "
            f"watertight={row.get('is_watertight')}"
        )
        content = json.dumps(row, indent=2, default=str)

        if dry_run:
            print(f"  [dry-run] Would write: {topic}")
            indexed += 1
            continue

        try:
            upsert_learning(
                topic=topic,
                decision=decision,
                rationale=rationale,
                category="workflow",
                source="pipeline_tools/assess_quality",
                content=content,
            )
            indexed += 1
            print(f"  \u2713 {topic}")
        except Exception as exc:
            print(f"  ✗ {topic} — {exc}")

    if not dry_run and indexed > 0:
        _save_cursor(new_cursor)
        print(f"[harvest_quality] Done. {indexed}/{len(rows)} rows indexed.")

    return indexed


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    n = harvest(dry_run=dry)
    sys.exit(0 if n >= 0 else 1)
