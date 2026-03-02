"""
inject.py — Called by the UserPromptSubmit hook to inject relevant memories.

Modes:
  (default / --prompt <text>)
                  Semantic search against the user's prompt text.
                  Returns the N most relevant chunks. Fast — single ANN query.
                  THIS IS THE HOOK PATH. Always pass --prompt.

  --full          Dump all content verbatim (complete text of every chunk).
                  Use manually for full knowledge review.
  --query <text>  Explicit semantic search — same as --prompt but for manual use.
  --count         Just print row count and exit (for health checks).

VS Code hook usage (semantic — fast, targeted):
  python memory/inject.py --prompt "user prompt text here"

Agent usage (get full text of a topic):
  python memory/inject.py --query "cmake build command"

"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

# ── Compaction flag ───────────────────────────────────────────────────────
# Written by precompact_hook.ps1 when VS Code is about to compact the context.
# Detected here on every UserPromptSubmit so the agent is reminded to write
# learnings even after context has already been lost and a new session started.
# Deleted by extract.py after a successful knowledge-base sync.
_COMPACTION_FLAG = Path(__file__).parent / "_compaction_pending.txt"


def _compaction_warning() -> str:
    """Return a high-priority banner if a compaction flag is pending."""
    if not _COMPACTION_FLAG.exists():
        return ""
    ts = _COMPACTION_FLAG.read_text(encoding="utf-8").strip()
    return (
        "\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "  CONTEXT COMPACTION OCCURRED — SESSION LEARNINGS PENDING   \n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        f"  Compaction flagged at: {ts}\n"
        "  The conversation summary above contains the full prior session.\n"
        "  RIGHT NOW, before doing anything else:\n"
        "  1. Read the summary and extract new learnings.\n"
        "  2. Append rows to .github/copilot-instructions.md  \n"
        "     ## Session Learnings Log table.\n"
        "  3. Run: .\\memory_env\\Scripts\\python.exe memory\\extract.py\n"
        "     (this syncs LanceDB + archives + clears the table + removes this banner)\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
    )


# ── Formatters ────────────────────────────────────────────────────────────


def _format_manifest(rows: list[dict]) -> str:
    """
    Compact overview: one bullet per row showing topic + decision.
    Groups by source prefix so the agent sees the structure of the knowledge base.
    """
    if not rows:
        return "use Context7\n[memory store is empty — run: python memory/extract.py]"

    lines = [
        "━━━ QIDISTUDIO KNOWLEDGE BASE (loaded from LanceDB) ━━━",
        "Every section below is stored verbatim. For full text run:",
        "  python memory/inject.py --query '<topic>'",
        "",
    ]

    # Group by source prefix (copilot-instructions, knowledge-doc, etc.)
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        src = r.get("source", "unknown")
        # Shorten to prefix before /
        prefix = src.split("/")[0]
        by_source.setdefault(prefix, []).append(r)

    for src, src_rows in by_source.items():
        label = {
            "copilot-instructions": "AGENT RULES & PROTOCOLS",
            "knowledge-doc": "QIDISTUDIO KNOWLEDGE",
            "langsmith-prompt": "LANGSMITH SYSTEM PROMPT",
        }.get(src, src.upper())
        lines.append(f"┌─ {label} ({len(src_rows)} chunks)")

        for r in src_rows:
            topic = r.get("topic", "")
            decision = r.get("decision", "")
            # Truncate decision to ~120 chars
            if len(decision) > 120:
                decision = decision[:117] + "..."
            lines.append(f"│  • {topic}")
            if decision and decision != topic:
                lines.append(f"│    → {decision}")
        lines.append("│")

    lines.append("━━━ END KNOWLEDGE BASE MANIFEST ━━━")
    lines.append("use Context7")
    return "\n".join(lines)


def _format_full(rows: list[dict]) -> str:
    """Verbatim full text of every chunk, separated by dividers."""
    if not rows:
        return "use Context7\n[memory store is empty]"

    lines = [
        "━━━ QIDISTUDIO FULL KNOWLEDGE BASE ━━━",
        f"({len(rows)} chunks — complete verbatim content)",
        "",
    ]

    current_source = None
    for r in rows:
        src = r.get("source", "")
        if src != current_source:
            current_source = src
            lines.append(f"\n{'='*60}")
            lines.append(f"SOURCE: {src}")
            lines.append("=" * 60)
        lines.append(f"\n--- {r.get('topic', '')} ---")
        lines.append(r.get("content") or r.get("decision", ""))

    lines.append("\n━━━ END KNOWLEDGE BASE ━━━")
    lines.append("use Context7")
    return "\n".join(lines)


# Maximum chars of content per search result injected into context.
# Keeps 8 results from flooding the context window with fat section chunks.
# Full text is always available via: python memory/inject.py --query '<topic>'
_CONTENT_MAX = 1500

# Cosine distance threshold for near-duplicate suppression.
# LanceDB returns L2 distance on normalised vectors, so L2²=2(1-cosine_sim).
# _distance < 0.05  →  cosine_sim > 0.975  →  essentially identical content.
_DEDUP_DISTANCE = 0.05
# Minimum characters of content overlap to count as a duplicate
# (guards against very short topics that accidentally match).
_DEDUP_MIN_LEN = 80

# Maximum L2 distance for a result to be injected.
# L2 distance < 0.9  →  cosine_sim > 0.595  →  loosely relevant.
# Chunks scoring worse than this are topic-drift noise (e.g. querying "context"
# shouldn't return §21 C++ OpenGL RAII or Key Websites & References).
_MAX_DISTANCE = 0.9


def _dedup_results(rows: list[dict]) -> list[dict]:
    """
    Remove near-duplicate and exact-duplicate results from a query result list.

    Two passes:
      1. Exact fingerprint: skip any row whose first _DEDUP_MIN_LEN chars of
         content are identical to an already-kept row (catches the common case
         of the same learning stored as both a /learnings row and embedded
         inside a /section chunk).
      2. Near-duplicate by _distance: if two rows are within _DEDUP_DISTANCE
         of each other in vector space AND share a content prefix, keep only
         the one with the lower (better) distance.

    Both passes are O(n²) but n≤20 so it's trivially fast.
    """
    kept: list[dict] = []
    fingerprints: set[str] = set()

    for row in rows:
        content = (row.get("content") or row.get("decision") or "").strip()
        fp = content[:_DEDUP_MIN_LEN].lower()

        # Pass 1 — exact content fingerprint
        if len(fp) >= _DEDUP_MIN_LEN and fp in fingerprints:
            continue

        # Pass 2 — near-duplicate by vector distance
        dist = row.get("_distance") or row.get("_score") or 1.0
        is_near_dup = False
        for kept_row in kept:
            kept_dist = kept_row.get("_distance") or kept_row.get("_score") or 1.0
            if abs(dist - kept_dist) < _DEDUP_DISTANCE:
                kept_fp = (
                    (kept_row.get("content") or kept_row.get("decision") or "")
                    .strip()[:_DEDUP_MIN_LEN]
                    .lower()
                )
                if fp and kept_fp and fp == kept_fp:
                    is_near_dup = True
                    break

        if is_near_dup:
            continue

        fingerprints.add(fp)
        kept.append(row)

    return kept


def _format_query_results(rows: list[dict], query: str) -> str:
    """Full content of semantically matching chunks (content truncated to _CONTENT_MAX)."""
    if not rows:
        return f"No results for '{query}'\nuse Context7"

    lines = [
        f"━━━ KNOWLEDGE BASE QUERY: '{query}' ({len(rows)} matches) ━━━",
        "",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(f"[{i}] {r.get('topic', '')}  ({r.get('source', '')}")
        lines.append("-" * 60)
        content = r.get("content") or r.get("decision", "")
        if len(content) > _CONTENT_MAX:
            content = (
                content[:_CONTENT_MAX]
                + f"\n... [truncated — {len(content)} chars total. Run: memory/inject.py --query '{r.get('topic','')[:40]}' for full text]"
            )
        lines.append(content)

    lines.append("━━━ END QUERY RESULTS ━━━")
    lines.append("use Context7")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="QIDIStudio knowledge injection")
    parser.add_argument("--full", action="store_true", help="Dump all content verbatim")
    parser.add_argument("--query", default="", help="Explicit semantic search query")
    parser.add_argument(
        "--prompt", default="", help="User prompt text — hook semantic retrieval path"
    )
    parser.add_argument(
        "--n", type=int, default=8, help="Number of results for semantic search"
    )
    parser.add_argument("--count", action="store_true", help="Print row count and exit")
    args = parser.parse_args()

    # --prompt (hook path) and --query (manual path) are equivalent
    query_text = (args.prompt or args.query or "").strip()

    # Prepend compaction banner if flag exists (fires every prompt until extract.py clears it)
    compaction_banner = _compaction_warning()

    context = ""
    try:
        from memory.store import get_all, query_similar, count as store_count

        if args.count:
            n = store_count()
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"LanceDB rows: {n}",
                }
            }
            print(json.dumps(output))
            return

        if args.full:
            rows = get_all()
            context = _format_full(rows)

        elif query_text:
            # HOOK PATH: semantic search — single ANN query, no full table scan
            matches = query_similar(query_text, n=args.n)
            # Drop results that are beyond the relevance floor
            matches = [
                r for r in matches if (r.get("_distance") or 0.0) < _MAX_DISTANCE
            ]
            matches = _dedup_results(matches)
            context = _format_query_results(matches, query_text)

        else:
            # No prompt text (fallback). Do NOT call get_all() over GCS.
            context = (
                "━━━ QIDISTUDIO KNOWLEDGE BASE ━━━\n"
                "Memory available. For full context supply a query:\n"
                "  python memory/inject.py --query 'your topic'\n"
                "━━━ END ━━━\n"
                "use Context7"
            )

    except Exception as e:
        context = (
            "use Context7\n"
            f"[memory module error: {e}]\n"
            "[Run: python memory/extract.py  to initialise the knowledge store]"
        )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                (compaction_banner + context) if compaction_banner else context
            ),
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
