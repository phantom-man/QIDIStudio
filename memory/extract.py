"""
extract.py — Indexes the ENTIRE knowledge base into LanceDB.

Sources processed:
  .github/copilot-instructions.md  — every ## / ### section as a verbatim chunk
  docs/QIDISTUDIO_KNOWLEDGE.md     — every ## / ### section
  memory/langsmith_prompt.md       — every ## / ### section

Every heading becomes one LanceDB row:
  topic    = heading text (short phrase)
  decision = first non-code paragraph (≤500 chars, as a readable summary)
  content  = FULL verbatim markdown text of the section (code blocks and all)
  source   = "copilot-instructions/section" | "knowledge-doc/section" | etc.
  category = inferred from topic/content keywords

Run after any edit to the source docs:
  python memory/extract.py

Idempotent — rows are upserted by topic, so re-running never duplicates.
"""

import re
import sys
import textwrap
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import os
os.environ.setdefault("LANGCHAIN_PROJECT", "QIDIStudio")


# ── Category inference ────────────────────────────────────────────────────

def _infer_category(topic: str, text: str) -> str:
    combined = (topic + " " + text[:300]).lower()
    checks = [
        ("bpy_pipeline",   ["blender", "bpy", "displacement", "texture", "apply_texture",
                             "cycles", "depsgraph", "armadillo", "subdivision", "mid_level"]),
        ("build_system",   ["cmake", "build", "msbuild", "deps", "sync", "install_dir",
                             "pkgconfig", "perl", "openssl", "qtdir", "vcpkg"]),
        ("cpp_gotcha",     ["wxwidget", "wx", "c++", "plater", "gui", "dialog", "menu",
                             "selection", "showmodal", "wxexec", "takesnapshot"]),
        ("hooks_and_memory",["langsmith", "langchain", "hook", "precompact", "memory",
                              "lancedb", "prompt_submit", "additionalcontext", "userpromptsub"]),
        ("gcode_refiner",  ["gcode", "refiner", "outer_wall", "asa", "m2 gear", "filament"]),
        ("tools_and_env",  ["python", "venv", "bpy_env", "blender.exe", "terminal",
                             "powershell", "pip install", "winget", "strawberry"]),
        ("api_key",        ["api_key", "api key", "endpoint", "token", "secret", "lsv2_sk"]),
        ("architecture",   ["architecture", "design", "pattern", "module", "interface",
                             "two-repo", "fork", "pipeline"]),
        ("workflow",       ["protocol", "convention", "standard", "rule", "skill",
                             "save this", "fire-and-poll", "visual reference"]),
    ]
    for cat, keywords in checks:
        if any(k in combined for k in keywords):
            return cat
    return "general"


# ── Markdown chunking ─────────────────────────────────────────────────────

def _first_para_summary(text: str, max_chars: int = 500) -> str:
    """Extract the first non-heading, non-empty paragraph as a plain-text summary."""
    # Remove code blocks first
    no_code = re.sub(r'```.*?```', '[code block]', text, flags=re.DOTALL)
    paras = [p.strip() for p in no_code.split('\n\n') if p.strip()]
    # Skip heading lines
    for p in paras:
        if not p.startswith('#') and not p.startswith('|'):
            # Strip inline markdown
            clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', p)
            clean = re.sub(r'\*([^*]+)\*',     r'\1', clean)
            clean = re.sub(r'`([^`]+)`',        r'\1', clean)
            clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
            clean = re.sub(r'\s+', ' ', clean).strip()
            return clean[:max_chars]
    return text[:max_chars]


def _make_chunk(heading_path: str, content: str, source: str) -> dict:
    """Build a single LanceDB row from a heading path and its full text content."""
    summary  = _first_para_summary(content)
    category = _infer_category(heading_path, content)
    return {
        "topic":     heading_path,
        "decision":  summary,
        "rationale": f"Full text in content field. Source: {source}",
        "content":   content.strip(),
        "category":  category,
        "date":      None,
        "source":    source,
    }


def extract_sections(path: Path, source_prefix: str) -> list[dict]:
    """
    Split a markdown file into chunks by ## headings.
    Long ## sections (>2500 chars body) are further split by ### sub-headings.
    Returns list of row dicts.
    """
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    rows: list[dict] = []

    # Split on ## headings (keep the heading in each chunk)
    sections = re.split(r'^(?=## )', text, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines        = section.splitlines()
        heading_line = lines[0].strip()
        heading_text = heading_line.lstrip('#').strip()
        body         = '\n'.join(lines[1:]).strip()

        # If body is long, sub-split on ### headings
        if len(body) > 2500:
            sub_sections = re.split(r'^(?=### )', body, flags=re.MULTILINE)
            has_intro = sub_sections and not sub_sections[0].strip().startswith('###')

            # Store the intro paragraph of the ## section (before first ###)
            if has_intro and sub_sections[0].strip():
                intro_content = f"{heading_line}\n\n{sub_sections[0].strip()}"
                rows.append(_make_chunk(
                    heading_text,
                    intro_content,
                    f"{source_prefix}/section",
                ))
                sub_sections = sub_sections[1:]

            for sub in sub_sections:
                sub = sub.strip()
                if not sub:
                    continue
                sub_lines    = sub.splitlines()
                sub_heading  = sub_lines[0].lstrip('#').strip()
                sub_body     = '\n'.join(sub_lines[1:]).strip()
                full_content = f"{heading_line}\n\n### {sub_heading}\n\n{sub_body}"
                topic_path   = f"{heading_text} — {sub_heading}"
                rows.append(_make_chunk(
                    topic_path,
                    full_content,
                    f"{source_prefix}/section",
                ))
        else:
            rows.append(_make_chunk(
                heading_text,
                section,
                f"{source_prefix}/section",
            ))

    return rows


# ── Learnings table extraction (structured rows) ──────────────────────────

def _parse_learnings_table(md_text: str) -> list[dict]:
    """Parse a | Date | Category | Topic | Decision | Rationale | table."""
    rows      = []
    in_table  = False
    h_cols: list[str] = []

    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not in_table:
            h_cols = [c.lower() for c in cells]
            if "topic" in h_cols and "decision" in h_cols:
                in_table = True
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) < len(h_cols):
            cells.extend([""] * (len(h_cols) - len(cells)))
        row = dict(zip(h_cols, cells))
        if row.get("topic") and row.get("decision"):
            rows.append(row)

    return rows


def extract_learnings_table(path: Path, source: str) -> list[dict]:
    """Extract Session Learnings Log table rows as structured rows."""
    if not path.exists():
        return []
    text  = path.read_text(encoding="utf-8")
    match = re.search(r"## Session Learnings Log(.+?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    if not match:
        return []

    parsed = _parse_learnings_table(match.group(1))
    rows   = []
    for r in parsed:
        topic    = (r.get("topic")     or "").strip()
        decision = (r.get("decision")  or "").strip()
        rationale= (r.get("rationale") or "").strip()
        category = (r.get("category")  or "").strip() or _infer_category(topic, decision)
        dt       = (r.get("date")      or "").strip() or None
        if not topic or not decision:
            continue
        rows.append({
            "topic":     topic,
            "decision":  decision,
            "rationale": rationale,
            "content":   f"**{topic}**\n{decision}\n\nRationale: {rationale}",
            "category":  category,
            "date":      dt,
            "source":    source,
        })
    return rows


# ── Sync to LanceDB ───────────────────────────────────────────────────────

def sync_to_lancedb(rows: list[dict]) -> tuple[int, int]:
    """Upsert all rows. Returns (inserted, skipped)."""
    from memory.store import upsert_learning

    inserted = skipped = 0
    for row in rows:
        topic = (row.get("topic") or "").strip()
        if not topic:
            skipped += 1
            continue
        try:
            upsert_learning(
                topic        = topic,
                decision     = (row.get("decision")  or "").strip(),
                rationale    = (row.get("rationale") or "").strip(),
                category     = (row.get("category")  or "general").strip(),
                source       = (row.get("source")    or "unknown"),
                learning_date= row.get("date"),
                content      = (row.get("content")   or "").strip(),
            )
            inserted += 1
        except Exception as e:
            print(f"  [WARN] Failed to upsert '{topic[:60]}': {e}", file=sys.stderr)
            skipped += 1

    return inserted, skipped


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("QIDIStudio Memory Extractor — full knowledge base indexing")
    print(f"Repo: {REPO_ROOT}")
    print()

    all_rows: list[dict] = []
    sources = [
        (REPO_ROOT / ".github" / "copilot-instructions.md", "copilot-instructions"),
        (REPO_ROOT / "docs"    / "QIDISTUDIO_KNOWLEDGE.md", "knowledge-doc"),
        (REPO_ROOT / "memory"  / "langsmith_prompt.md",     "langsmith-prompt"),
    ]

    for path, prefix in sources:
        # Full-text section chunks
        chunks = extract_sections(path, prefix)
        print(f"  {path.name:<35} sections : {len(chunks)}")
        all_rows.extend(chunks)

        # Structured learnings table rows (if present)
        learnings = extract_learnings_table(path, f"{prefix}/learnings")
        if learnings:
            print(f"  {path.name:<35} learnings: {len(learnings)}")
            all_rows.extend(learnings)

    print(f"\nTotal rows to sync: {len(all_rows)}")

    # Deduplicate by topic (last wins)
    seen:   dict[str, dict] = {}
    for r in all_rows:
        seen[r["topic"]] = r
    deduped = list(seen.values())
    print(f"After dedup        : {len(deduped)}")

    print("\nSyncing to LanceDB (this loads the embedding model — ~15s on first run)...")
    inserted, skipped = sync_to_lancedb(deduped)
    print(f"  Inserted/updated : {inserted}")
    print(f"  Skipped (empty)  : {skipped}")

    from memory.store import count as store_count
    n = store_count()
    print(f"  Total in store   : {n}")
    print("\nDone.")


if __name__ == "__main__":
    main()
