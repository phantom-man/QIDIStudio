"""
extract.py — Syncs three knowledge sources from copilot-instructions.md into LanceDB:

  1. Session Learnings Log   — table rows of confirmed gotchas / decisions (category varies)
  2. Protocols               — one row per ## ...Protocol section  (category: workflow)
  3. Skills routing          — one row per skill trigger           (category: workflow)

Also reads QIDISTUDIO_KNOWLEDGE.md for any learnings table there.

Run after the Save This Protocol writes new learnings:
  python memory/extract.py

Idempotent — rows are upserted by topic, so re-running never creates duplicates.
LangSmith tracing enabled if LANGCHAIN_TRACING_V2=true in .env.
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


# ── Protocol extraction ────────────────────────────────────────────────────

_PROTOCOL_NAMES = [
    "Save This",
    "Visual Reference Log",
    "Amazon Link Fetching",
    "Fire-and-Poll",
    "Async Terminal Output",
    "Two-Repo Layout",
]

def extract_protocols(path: Optional[Path] = None) -> list[dict]:
    """
    Parse named protocol sections from copilot-instructions.md.
    Returns one row per protocol with category='workflow'.

    Each row: { topic, decision, rationale, category, date, source }
    """
    path = path or REPO_ROOT / ".github" / "copilot-instructions.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")

    rows: list[dict] = []

    # Find every ## heading that contains "Protocol" or matches known names
    section_re = re.compile(
        r'^(#{1,3} .+?(?:Protocol|Layout|Procedure|Workflow).+?)\n(.*?)(?=^#{1,3} |\Z)',
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )

    for m in section_re.finditer(text):
        heading = m.group(1).strip().lstrip("#").strip().strip('"').strip("'")
        body    = m.group(2).strip()

        if not body:
            continue

        # First non-empty, non-heading paragraph = summary
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        first_para = paragraphs[0] if paragraphs else ""

        # Collapse newlines in para for clean storage
        decision  = re.sub(r'\s+', ' ', first_para)[:400]
        # Steps = remaining text, compacted
        steps_raw = "\n\n".join(paragraphs[1:4]) if len(paragraphs) > 1 else ""
        rationale = re.sub(r'\s+', ' ', steps_raw)[:600] if steps_raw else f"See {path.name} §{heading}"

        rows.append({
            "topic":     f"protocol: {heading}",
            "decision":  decision,
            "rationale": rationale,
            "category":  "workflow",
            "date":      None,
            "source":    "copilot-instructions/protocol",
        })

    return rows


# ── Skills routing extraction ──────────────────────────────────────────────

def extract_skills(path: Optional[Path] = None) -> list[dict]:
    """
    Parse the Skills section from copilot-instructions.md.
    Each 'Trigger | Skill' table row becomes one LanceDB row so the agent gets
    prompted to load the right skill file when the topic matches.

    Returns rows with category='workflow'.
    """
    path = path or REPO_ROOT / ".github" / "copilot-instructions.md"
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")

    # Find the Skills section block
    match = re.search(r'## Skills.+?(?=^## |\Z)', text, re.DOTALL | re.MULTILINE)
    if not match:
        return []

    skills_block = match.group(0)
    rows: list[dict] = []

    # Each table row looks like: | trigger text | `skill-name` |
    row_re = re.compile(r'^\|\s*(.+?)\s*\|\s*`([^`]+)`\s*\|', re.MULTILINE)

    for m in row_re.finditer(skills_block):
        trigger    = m.group(1).strip()
        skill_name = m.group(2).strip()

        # Skip header rows
        if trigger.lower() in ("trigger", "skill", "when"):
            continue

        rows.append({
            "topic":     f"skill: {skill_name}",
            "decision":  f"Load the '{skill_name}' skill when: {trigger}",
            "rationale": f"Skill file: .agents/skills/{skill_name}/SKILL.md — read it with read_file before acting",
            "category":  "workflow",
            "date":      None,
            "source":    "copilot-instructions/skills",
        })

    return rows


def sync_to_lancedb(rows: list[dict], source: str = "copilot-instructions") -> tuple[int, int]:
    """Upsert all rows into LanceDB. Returns (inserted, skipped)."""
    from memory.store import upsert_learning

    inserted = 0
    skipped  = 0

    for row in rows:
        topic    = (row.get("topic")     or "").strip()
        decision = (row.get("decision")  or "").strip()
        rationale= (row.get("rationale") or "").strip()
        category = (row.get("category")  or "").strip() or _infer_category(topic, decision)
        dt       = (row.get("date")      or "").strip() or None
        src      = row.get("source")     or source

        if not topic or not decision:
            skipped += 1
            continue

        try:
            upsert_learning(
                topic=topic,
                decision=decision,
                rationale=rationale,
                category=category,
                source=src,
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

    # 1. Session Learnings Log in copilot-instructions.md
    rows1 = extract_from_instructions()
    print(f"  copilot-instructions.md (learnings)  : {len(rows1)} rows")
    all_rows.extend(rows1)

    # 2. Session Learnings Log in QIDISTUDIO_KNOWLEDGE.md
    rows2 = extract_from_knowledge()
    print(f"  QIDISTUDIO_KNOWLEDGE.md  (learnings) : {len(rows2)} rows")
    all_rows.extend(rows2)

    # 3. Protocol sections
    rows3 = extract_protocols()
    print(f"  copilot-instructions.md  (protocols) : {len(rows3)} rows")
    all_rows.extend(rows3)

    # 4. Skills routing table
    rows4 = extract_skills()
    print(f"  copilot-instructions.md  (skills)    : {len(rows4)} rows")
    all_rows.extend(rows4)

    if not all_rows:
        print("\nNo content found. Check that 'Session Learnings Log' table and '## Skills' section exist in copilot-instructions.md.")
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
