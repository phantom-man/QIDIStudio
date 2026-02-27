"""
extract.py — Parses the Session Learnings Log from copilot-instructions.md
             and syncs all rows into LanceDB.

Run this after the Save This Protocol writes new learnings to the .md file:
  python memory/extract.py

It is idempotent — rows are upserted by topic, so re-running never creates duplicates.
LangSmith tracing is enabled if LANGCHAIN_TRACING_V2=true in .env.
"""

import re
import sys
from pathlib import Path
from typing import Optional

# Allow running from any cwd
REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import os
os.environ.setdefault("LANGCHAIN_PROJECT", "QIDIStudio")


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_learnings_table(md_text: str) -> list[dict]:
    """
    Parse a Markdown table with columns:
      | Date | Category | Topic | Decision | Rationale |
    or the 4-column variant:
      | Date | Topic | Decision | Rationale |
    Returns list of dicts with those keys (lowercase).
    """
    rows = []
    in_table = False
    header_cols: list[str] = []

    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # Header row
        if not in_table:
            header_cols = [c.lower() for c in cells]
            if "topic" in header_cols and "decision" in header_cols:
                in_table = True
            continue

        # Separator row
        if all(set(c) <= set("-: ") for c in cells):
            continue

        if len(cells) < len(header_cols):
            cells.extend([""] * (len(header_cols) - len(cells)))

        row = dict(zip(header_cols, cells))
        if row.get("topic") and row.get("decision"):
            rows.append(row)

    return rows


def _infer_category(topic: str, decision: str) -> str:
    """Heuristic category inference from topic/decision text."""
    combined = (topic + " " + decision).lower()
    if any(k in combined for k in ["blender", "bpy", "displacement", "texture", "apply_texture"]):
        return "bpy_pipeline"
    if any(k in combined for k in ["cmake", "build", "msb", "msbuild", "deps", "sync", "install_dir"]):
        return "build_system"
    if any(k in combined for k in ["wxwidget", "wx", "c++", "plater", "gui", "dialog", "menu", "selection"]):
        return "cpp_gotcha"
    if any(k in combined for k in ["langsmith", "langchain", "hook", "precompact", "memory", "lancedb"]):
        return "hooks_and_memory"
    if any(k in combined for k in ["gcode", "refiner", "feature type", "outer_wall", "asa"]):
        return "gcode_refiner"
    if any(k in combined for k in ["python", "venv", "bpy_env", "blender.exe", "terminal", "powershell"]):
        return "tools_and_env"
    if any(k in combined for k in ["api_key", "api key", "endpoint", "token", "secret"]):
        return "api_key"
    if any(k in combined for k in ["architecture", "design", "pattern", "module", "interface"]):
        return "architecture"
    if any(k in combined for k in ["workflow", "protocol", "convention", "standard", "rule"]):
        return "workflow"
    return "general"


def extract_from_instructions(path: Optional[Path] = None) -> list[dict]:
    """Parse Session Learnings Log table from copilot-instructions.md."""
    path = path or REPO_ROOT / ".github" / "copilot-instructions.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")

    # Find the Session Learnings Log section
    match = re.search(r"## Session Learnings Log(.+?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    if not match:
        return []

    return _parse_learnings_table(match.group(1))


def extract_from_knowledge(path: Optional[Path] = None) -> list[dict]:
    """Parse Session Learnings Log table from QIDISTUDIO_KNOWLEDGE.md if present."""
    path = path or REPO_ROOT / "docs" / "QIDISTUDIO_KNOWLEDGE.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")

    match = re.search(r"## Session Learnings Log(.+?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    if not match:
        return []

    return _parse_learnings_table(match.group(1))


def sync_to_lancedb(rows: list[dict], source: str = "copilot-instructions") -> tuple[int, int]:
    """Upsert all rows into LanceDB. Returns (inserted, skipped)."""
    from memory.store import upsert_learning

    inserted = 0
    skipped  = 0

    for row in rows:
        topic    = row.get("topic", "").strip()
        decision = row.get("decision", "").strip()
        rationale= row.get("rationale", "").strip()
        category = row.get("category", "").strip() or _infer_category(topic, decision)
        dt       = row.get("date", "").strip() or None

        if not topic or not decision:
            skipped += 1
            continue

        try:
            upsert_learning(
                topic=topic,
                decision=decision,
                rationale=rationale,
                category=category,
                source=source,
                learning_date=dt,
            )
            inserted += 1
        except Exception as e:
            print(f"  [WARN] Failed to upsert '{topic[:50]}': {e}", file=sys.stderr)
            skipped += 1

    return inserted, skipped


def main():
    print("QIDIStudio Memory Extractor")
    print(f"Repo: {REPO_ROOT}")
    print()

    all_rows: list[dict] = []

    # 1. copilot-instructions.md
    rows1 = extract_from_instructions()
    print(f"  copilot-instructions.md : {len(rows1)} learnings found")
    all_rows.extend(rows1)

    # 2. QIDISTUDIO_KNOWLEDGE.md
    rows2 = extract_from_knowledge()
    print(f"  QIDISTUDIO_KNOWLEDGE.md : {len(rows2)} learnings found")
    all_rows.extend(rows2)

    if not all_rows:
        print("\nNo learnings found. Make sure the 'Session Learnings Log' table exists in the .md files.")
        return

    print(f"\nSyncing {len(all_rows)} rows to LanceDB...")
    inserted, skipped = sync_to_lancedb(all_rows)
    print(f"  Inserted/updated : {inserted}")
    print(f"  Skipped (empty)  : {skipped}")

    # Report final row count
    from memory.store import count as store_count
    print(f"  Total in store   : {store_count()}")
    print("\nDone.")


if __name__ == "__main__":
    main()
