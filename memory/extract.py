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
        (
            "bpy_pipeline",
            [
                "blender",
                "bpy",
                "displacement",
                "texture",
                "apply_texture",
                "cycles",
                "depsgraph",
                "armadillo",
                "subdivision",
                "mid_level",
            ],
        ),
        (
            "build_system",
            [
                "cmake",
                "build",
                "msbuild",
                "deps",
                "sync",
                "install_dir",
                "pkgconfig",
                "perl",
                "openssl",
                "qtdir",
                "vcpkg",
            ],
        ),
        (
            "cpp_gotcha",
            [
                "wxwidget",
                "wx",
                "c++",
                "plater",
                "gui",
                "dialog",
                "menu",
                "selection",
                "showmodal",
                "wxexec",
                "takesnapshot",
            ],
        ),
        (
            "hooks_and_memory",
            [
                "langsmith",
                "langchain",
                "hook",
                "precompact",
                "memory",
                "lancedb",
                "prompt_submit",
                "additionalcontext",
                "userpromptsub",
            ],
        ),
        (
            "gcode_refiner",
            ["gcode", "refiner", "outer_wall", "asa", "m2 gear", "filament"],
        ),
        (
            "tools_and_env",
            [
                "python",
                "venv",
                "bpy_env",
                "blender.exe",
                "terminal",
                "powershell",
                "pip install",
                "winget",
                "strawberry",
            ],
        ),
        ("api_key", ["api_key", "api key", "endpoint", "token", "secret", "lsv2_sk"]),
        (
            "architecture",
            [
                "architecture",
                "design",
                "pattern",
                "module",
                "interface",
                "two-repo",
                "fork",
                "pipeline",
            ],
        ),
        (
            "workflow",
            [
                "protocol",
                "convention",
                "standard",
                "rule",
                "skill",
                "save this",
                "fire-and-poll",
                "visual reference",
            ],
        ),
    ]
    for cat, keywords in checks:
        if any(k in combined for k in keywords):
            return cat
    return "general"


# ── Markdown chunking ─────────────────────────────────────────────────────


def _first_para_summary(text: str, max_chars: int = 500) -> str:
    """Extract the first non-heading, non-empty paragraph as a plain-text summary."""
    # Remove code blocks first
    no_code = re.sub(r"```.*?```", "[code block]", text, flags=re.DOTALL)
    paras = [p.strip() for p in no_code.split("\n\n") if p.strip()]
    # Skip heading lines
    for p in paras:
        if not p.startswith("#") and not p.startswith("|"):
            # Strip inline markdown
            clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", p)
            clean = re.sub(r"\*([^*]+)\*", r"\1", clean)
            clean = re.sub(r"`([^`]+)`", r"\1", clean)
            clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            return clean[:max_chars]
    return text[:max_chars]


def _make_chunk(heading_path: str, content: str, source: str) -> dict:
    """Build a single LanceDB row from a heading path and its full text content."""
    summary = _first_para_summary(content)
    category = _infer_category(heading_path, content)
    return {
        "topic": heading_path,
        "decision": summary,
        "rationale": f"Full text in content field. Source: {source}",
        "content": content.strip(),
        "category": category,
        "date": None,
        "source": source,
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
    sections = re.split(r"^(?=## )", text, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.splitlines()
        heading_line = lines[0].strip()
        heading_text = heading_line.lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()

        # If body is long, sub-split on ### headings
        if len(body) > 2500:
            sub_sections = re.split(r"^(?=### )", body, flags=re.MULTILINE)
            has_intro = sub_sections and not sub_sections[0].strip().startswith("###")

            # Store the intro paragraph of the ## section (before first ###)
            if has_intro and sub_sections[0].strip():
                intro_content = f"{heading_line}\n\n{sub_sections[0].strip()}"
                rows.append(
                    _make_chunk(
                        heading_text,
                        intro_content,
                        f"{source_prefix}/section",
                    )
                )
                sub_sections = sub_sections[1:]

            for sub in sub_sections:
                sub = sub.strip()
                if not sub:
                    continue
                sub_lines = sub.splitlines()
                sub_heading = sub_lines[0].lstrip("#").strip()
                sub_body = "\n".join(sub_lines[1:]).strip()
                full_content = f"{heading_line}\n\n### {sub_heading}\n\n{sub_body}"
                topic_path = f"{heading_text} — {sub_heading}"
                rows.append(
                    _make_chunk(
                        topic_path,
                        full_content,
                        f"{source_prefix}/section",
                    )
                )
        else:
            rows.append(
                _make_chunk(
                    heading_text,
                    section,
                    f"{source_prefix}/section",
                )
            )

    return rows


# ── Learnings table extraction (structured rows) ──────────────────────────


def _parse_learnings_table(md_text: str) -> list[dict]:
    """Parse a | Date | Category | Topic | Decision | Rationale | table."""
    rows = []
    in_table = False
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
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"## Session Learnings Log(.+?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE
    )
    if not match:
        return []

    parsed = _parse_learnings_table(match.group(1))
    rows = []
    for r in parsed:
        topic = (r.get("topic") or "").strip()
        decision = (r.get("decision") or "").strip()
        rationale = (r.get("rationale") or "").strip()
        category = (r.get("category") or "").strip() or _infer_category(topic, decision)
        dt = (r.get("date") or "").strip() or None
        if not topic or not decision:
            continue
        rows.append(
            {
                "topic": topic,
                "decision": decision,
                "rationale": rationale,
                "content": f"**{topic}**\n{decision}\n\nRationale: {rationale}",
                "category": category,
                "date": dt,
                "source": source,
            }
        )
    return rows


# ── Sync to LanceDB ───────────────────────────────────────────────────────


def sync_to_lancedb(rows: list[dict]) -> tuple[int, int]:
    """
    Batch-upsert all rows in a single GCS write pair.

    Old approach: N × (table.delete + table.add) = 400+ GCS round trips for 200 rows.
    New approach: one batch embed → one IN-delete → one table.add = ~3 GCS ops total.
    """
    from memory.store import batch_upsert

    try:
        inserted, skipped = batch_upsert(rows)
    except Exception as e:
        print(f"  [ERROR] batch_upsert failed: {e}", file=sys.stderr)
        inserted, skipped = 0, len(rows)
    return inserted, skipped


# ── Learnings pruning (verify → archive → remove from copilot-instructions) ──

ARCHIVE_PATH = REPO_ROOT / "memory" / "session_learnings_archive.md"
INSTRUCTIONS_PATH = REPO_ROOT / ".github" / "copilot-instructions.md"

_ARCHIVE_HEADER = """\
# Session Learnings Archive

All rows here have been verified in LanceDB and pruned from `copilot-instructions.md`.
Append-only. Never edit manually — maintained by `memory/extract.py`.

| Date | Category | Topic | Decision | Rationale |
|------|----------|-------|----------|-----------|
"""


def _load_archive_topics() -> set[str]:
    """Return the set of topic strings already in the archive file."""
    if not ARCHIVE_PATH.exists():
        return set()
    text = ARCHIVE_PATH.read_text(encoding="utf-8")
    rows = _parse_learnings_table(text)
    return {r.get("topic", "").strip() for r in rows if r.get("topic")}


def prune_learnings_from_instructions() -> tuple[int, int, int]:
    """
    For each row in the Session Learnings Log in copilot-instructions.md:
      1. Verify it exists in LanceDB (query by topic).
      2. If verified, append to session_learnings_archive.md.
      3. After all verified, remove the entire table body from copilot-instructions.md
         (replace with a stub row count comment).

    Returns (verified, not_found, archived_new).
    """
    from memory.store import query_similar

    if not INSTRUCTIONS_PATH.exists():
        print("  [prune] copilot-instructions.md not found — skipping")
        return 0, 0, 0

    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"(## Session Learnings Log[\s\S]*?\| Date.*?\n\|[-: |]+\n)((?:\|.*?\n)+)",
        text,
        re.DOTALL,
    )
    if not match:
        print("  [prune] No Session Learnings Log table found — skipping")
        return 0, 0, 0

    header_block = match.group(1)
    table_body = match.group(2)

    rows = _parse_learnings_table(header_block + table_body)
    if not rows:
        print("  [prune] Table found but no data rows parsed — skipping")
        return 0, 0, 0

    already_archived = _load_archive_topics()

    # Load all topics from LanceDB in one shot — avoids N round trips of query_similar()
    from memory.store import get_all

    all_lancedb = get_all()
    lancedb_topics = {(r.get("topic") or "").strip().lower() for r in all_lancedb}

    verified: list[dict] = []
    not_found: list[dict] = []

    for row in rows:
        topic = row.get("topic", "").strip()
        if not topic:
            continue
        if topic.lower() in lancedb_topics:
            verified.append(row)
        else:
            not_found.append(row)

    print(f"  [prune] Verified in LanceDB : {len(verified)}")
    print(f"  [prune] Not found (kept)    : {len(not_found)}")

    # Append new verified rows to archive
    new_archived = 0
    if verified:
        if not ARCHIVE_PATH.exists():
            ARCHIVE_PATH.write_text(_ARCHIVE_HEADER, encoding="utf-8")

        with ARCHIVE_PATH.open("a", encoding="utf-8") as f:
            for row in verified:
                if row.get("topic", "").strip() in already_archived:
                    continue  # already in archive
                date = row.get("date", "").strip() or "—"
                category = row.get("category", "").strip() or "—"
                topic = row.get("topic", "").strip()
                decision = row.get("decision", "").strip()
                rationale = row.get("rationale", "").strip() or "—"
                f.write(
                    f"| {date} | {category} | {topic} | {decision} | {rationale} |\n"
                )
                new_archived += 1

    print(f"  [prune] Newly archived      : {new_archived}")

    # Rebuild the table in copilot-instructions: keep only unverified rows
    if verified:
        if not_found:
            # Reconstruct table with only rows that aren't in LanceDB yet
            kept_lines = []
            for row in not_found:
                date = row.get("date", "").strip() or "—"
                category = row.get("category", "").strip() or "—"
                topic = row.get("topic", "").strip()
                decision = row.get("decision", "").strip()
                rationale = row.get("rationale", "").strip() or "—"
                kept_lines.append(
                    f"| {date} | {category} | {topic} | {decision} | {rationale} |\n"
                )
            new_table_body = "".join(kept_lines)
        else:
            # All rows verified — leave an empty table body
            new_table_body = ""

        new_text = text[: match.start(2)] + new_table_body + text[match.end(2) :]
        INSTRUCTIONS_PATH.write_text(new_text, encoding="utf-8")
        print(f"  [prune] copilot-instructions.md updated — {len(not_found)} rows kept")

    return len(verified), len(not_found), new_archived


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    print("QIDIStudio Memory Extractor — full knowledge base indexing")
    print(f"Repo: {REPO_ROOT}")
    print()

    all_rows: list[dict] = []
    sources = [
        (REPO_ROOT / ".github" / "copilot-instructions.md", "copilot-instructions"),
        (REPO_ROOT / "docs" / "QIDISTUDIO_KNOWLEDGE.md", "knowledge-doc"),
        (REPO_ROOT / "memory" / "langsmith_prompt.md", "langsmith-prompt"),
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
    seen: dict[str, dict] = {}
    for r in all_rows:
        seen[r["topic"]] = r
    deduped = list(seen.values())
    print(f"After dedup        : {len(deduped)}")

    # ── Prune verified learnings FIRST — before indexing ────────────────
    # IMPORTANT: prune must run before sync_to_lancedb so that section chunks
    # capture the already-cleaned file, not the fat unpruned table.
    # If we indexed first, the stale 145k-char Session Learnings Log chunk
    # would persist in GCS and match almost every prompt, consuming huge context.
    print("\nPruning verified learnings from source files before indexing...")
    verified, kept, archived = prune_learnings_from_instructions()
    print(f"  Archive path: {ARCHIVE_PATH}")

    # ── Re-read source files after pruning so section chunks are slim ────
    # Rebuild all_rows from the now-pruned files
    all_rows = []
    for path, prefix in sources:
        chunks = extract_sections(path, prefix)
        all_rows.extend(chunks)
        learnings = extract_learnings_table(path, f"{prefix}/learnings")
        if learnings:
            all_rows.extend(learnings)

    seen = {}
    for r in all_rows:
        seen[r["topic"]] = r
    deduped = list(seen.values())
    print(f"\nPost-prune rows to sync: {len(deduped)}")

    print(
        "\nSyncing to LanceDB (this loads the embedding model — ~15s on first run)..."
    )
    inserted, skipped = sync_to_lancedb(deduped)
    print(f"  Inserted/updated : {inserted}")
    print(f"  Skipped (empty)  : {skipped}")

    from memory.store import count as store_count

    n = store_count()
    print(f"  Total in store   : {n}")

    # Clear compaction flag if present — learnings are now in LanceDB
    flag = REPO_ROOT / "memory" / "_compaction_pending.txt"
    if flag.exists():
        flag.unlink()
        print("  Compaction flag cleared.")

    print("\nDone.")


if __name__ == "__main__":
    main()
