"""
inject.py — Called by the UserPromptSubmit hook to load the full knowledge base.

Modes:
  (default)       Compact manifest: all topic+decision rows, grouped by source.
                  Gives the agent the full map of what's in memory.
  --full          Dump all content verbatim (complete text of every chunk).
  --query <text>  Semantic search → return full content of matching chunks.
  --count         Just print row count and exit (for health checks).

VS Code hook usage (default — compact manifest):
  python memory/inject.py

Agent usage (get full text of a topic):
  python memory/inject.py --query "cmake build command"

"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))


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
            "knowledge-doc":        "QIDISTUDIO KNOWLEDGE",
            "langsmith-prompt":     "LANGSMITH SYSTEM PROMPT",
        }.get(src, src.upper())
        lines.append(f"┌─ {label} ({len(src_rows)} chunks)")

        for r in src_rows:
            topic    = r.get("topic",    "")
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
            lines.append('='*60)
        lines.append(f"\n--- {r.get('topic', '')} ---")
        lines.append(r.get("content") or r.get("decision", ""))

    lines.append("\n━━━ END KNOWLEDGE BASE ━━━")
    lines.append("use Context7")
    return "\n".join(lines)


def _format_query_results(rows: list[dict], query: str) -> str:
    """Full content of semantically matching chunks."""
    if not rows:
        return f"No results for '{query}'\nuse Context7"

    lines = [
        f"━━━ KNOWLEDGE BASE QUERY: '{query}' ({len(rows)} matches) ━━━",
        "",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(f"[{i}] {r.get('topic', '')}  ({r.get('source', '')})")
        lines.append("-" * 60)
        lines.append(r.get("content") or r.get("decision", ""))
        lines.append("")

    lines.append("━━━ END QUERY RESULTS ━━━")
    lines.append("use Context7")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="QIDIStudio knowledge injection")
    parser.add_argument("--full",    action="store_true", help="Dump all content verbatim")
    parser.add_argument("--query",   default="",          help="Semantic search query")
    parser.add_argument("--n",       type=int, default=8, help="Number of results for --query")
    parser.add_argument("--count",   action="store_true", help="Print row count and exit")
    args = parser.parse_args()

    context = ""
    try:
        from memory.store import get_all, query_similar, count as store_count

        if args.count:
            n = store_count()
            output = {"hookSpecificOutput": {
                "hookEventName":   "UserPromptSubmit",
                "additionalContext": f"LanceDB rows: {n}",
            }}
            print(json.dumps(output))
            return

        if args.query.strip():
            matches = query_similar(args.query, n=args.n)
            context = _format_query_results(matches, args.query)

        elif args.full:
            rows    = get_all()
            context = _format_full(rows)

        else:
            # Default: compact manifest of all rows
            rows    = get_all()
            context = _format_manifest(rows)

    except Exception as e:
        # Fail gracefully — still inject Context7 hint
        context = (
            "use Context7\n"
            f"[memory module error: {e}]\n"
            "[Run: python memory/extract.py  to initialise the knowledge store]"
        )

    output = {
        "hookSpecificOutput": {
            "hookEventName":    "UserPromptSubmit",
            "additionalContext": context,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
