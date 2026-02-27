"""
inject.py — Called by the UserPromptSubmit hook.

Queries LanceDB for recent + relevant session learnings and outputs JSON
that VS Code injects as additionalContext into the next agent prompt.

Usage (from hook):
  python memory/inject.py [--query "some topic"]

Output (stdout):
  JSON in VS Code hook format:
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}

Falls back gracefully if LanceDB not initialised or dependencies missing.
"""

import sys
import json
import argparse
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parents[1]))


def _build_context(learnings: list[dict]) -> str:
    if not learnings:
        return ""

    lines = [
        "--- PERSISTENT MEMORY (from previous sessions) ---",
        "The following learnings were stored in LanceDB from prior engineering sessions.",
        "Treat these as confirmed facts — do not re-investigate or contradict them without explicit evidence.",
        "",
    ]

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for r in learnings:
        cat = r.get("category", "general")
        by_cat.setdefault(cat, []).append(r)

    for cat, rows in by_cat.items():
        lines.append(f"[{cat.upper().replace('_', ' ')}]")
        for r in rows:
            topic    = r.get("topic",     "")
            decision = r.get("decision",  "")
            rationale= r.get("rationale", "")
            dt       = r.get("date",      "")
            lines.append(f"  • {topic} ({dt}): {decision}" + (f" — {rationale}" if rationale else ""))
        lines.append("")

    lines.append("--- END PERSISTENT MEMORY ---")
    lines.append("use Context7")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="", help="Semantic query to find relevant memories")
    parser.add_argument("--n-recent", type=int, default=20,  help="Max recent learnings to include")
    parser.add_argument("--n-similar", type=int, default=10, help="Max semantically similar learnings")
    parser.add_argument("--days", type=int, default=90, help="How many days back to search recent")
    args = parser.parse_args()

    context = ""
    try:
        from memory.store import get_recent, query_similar

        learnings = get_recent(n=args.n_recent, days=args.days)

        # If a query topic was passed, merge in similar results
        if args.query.strip():
            similar = query_similar(args.query, n=args.n_similar)
            seen_ids = {r.get("id") for r in learnings}
            for r in similar:
                if r.get("id") not in seen_ids:
                    learnings.append(r)
                    seen_ids.add(r.get("id"))

        context = _build_context(learnings)
    except Exception as e:
        # Graceful degradation — still inject Context7 directive
        context = f"use Context7\n[memory module unavailable: {e}]"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context if context else "use Context7",
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
