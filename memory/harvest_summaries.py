"""memory/harvest_summaries.py — Compaction Summary Harvester

Scans ~/.claude/projects/<QIDIStudio-key>/*/session-memory/summary.md for
summaries written since the last harvest timestamp and appends them to
memory/compaction_summaries.md so that extract.py can index them into
LanceDB — filling in any knowledge gaps caused by premature context compaction.

Claude Code writes a summary.md into session-memory/ whenever compaction occurs.
These files follow the standard session-memory template with sections:
  # Current State, # Task specification, # Files and Functions,
  # Errors & Corrections, # Learnings, # Key results, # Worklog

Run automatically by the Stop hook at the end of every Claude conversation.
Can also be run manually:
  python memory/harvest_summaries.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]

# Claude Code encodes the project path by replacing OS path separators with --.
# C:\\Users\\User\\source\\repos\\QIDIStudio  →  C--Users-User-source-repos-QIDIStudio
_PROJECT_KEY = "C--Users-User-source-repos-QIDIStudio"
_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
_PROJECT_DIR = _CLAUDE_PROJECTS / _PROJECT_KEY

_SUMMARIES_OUT = REPO_ROOT / "memory" / "compaction_summaries.md"
_TS_FILE = REPO_ROOT / "memory" / "_last_harvest.txt"

_SUMMARIES_HEADER = """\
# Compaction Summaries

Auto-harvested by `memory/harvest_summaries.py` from Claude Code session-memory.
These summaries fill knowledge gaps caused by context compaction between sessions.
Append-only — do not edit manually.

---
"""


def _load_last_ts() -> datetime:
    """Return the timestamp of the last successful harvest (or epoch if none)."""
    if _TS_FILE.exists():
        try:
            return datetime.fromisoformat(_TS_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    return datetime.min


def _save_ts() -> None:
    _TS_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")


def harvest() -> int:
    """
    Harvest new compaction summaries from Claude Code session files.
    Returns the count of new summaries appended to compaction_summaries.md.
    """
    if not _PROJECT_DIR.exists():
        print(
            f"[harvest] Project dir not found: {_PROJECT_DIR}\n"
            "[harvest] No Claude Code sessions exist for this project yet — skipping."
        )
        return 0

    last_ts = _load_last_ts()

    new_summaries: list[tuple[datetime, str, str]] = []

    for session_dir in _PROJECT_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        summary_path = session_dir / "session-memory" / "summary.md"
        if not summary_path.exists():
            continue
        try:
            mtime = datetime.fromtimestamp(summary_path.stat().st_mtime)
        except OSError:
            continue
        if mtime > last_ts:
            try:
                content = summary_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                new_summaries.append((mtime, session_dir.name, content))

    if not new_summaries:
        print("[harvest] No new compaction summaries found.")
        return 0

    new_summaries.sort(key=lambda x: x[0])

    # Initialise file with header if it doesn't exist
    if not _SUMMARIES_OUT.exists():
        _SUMMARIES_OUT.write_text(_SUMMARIES_HEADER, encoding="utf-8")

    with open(_SUMMARIES_OUT, "a", encoding="utf-8") as fh:
        for mtime, session_id, content in new_summaries:
            ts_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
            fh.write(f"\n## Compaction Summary [{ts_str}]\n")
            fh.write(f"<!-- session={session_id} -->\n\n")
            fh.write(content)
            fh.write("\n\n---\n")

    _save_ts()
    print(
        f"[harvest] Appended {len(new_summaries)} new summaries → {_SUMMARIES_OUT.name}"
    )
    return len(new_summaries)


if __name__ == "__main__":
    count = harvest()
    sys.exit(0)
