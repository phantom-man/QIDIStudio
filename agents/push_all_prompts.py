"""
agents/push_all_prompts.py — Push all QIDIStudio agent prompts to LangSmith Hub.

Iterates over agents/prompts/*.md, strips metadata comments, and pushes each
to LangSmith Hub as:  qidi-<agent_id>

Usage:
    memory_env/Scripts/python.exe agents/push_all_prompts.py

Push rules:
- Strips lines starting with single '# ' (file title) from the top of each file
- Uses the same org/workspace as push_prompt.py (env-based auth)
- Treats HTTP 409 (nothing to commit) as success
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langsmith import Client

# ── Setup ─────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parents[1]
PROMPTS_DIR = REPO_ROOT / "agents" / "prompts"
load_dotenv(REPO_ROOT / ".env")


def _load_prompt_text(md_path: Path) -> str:
    """Load markdown, strip H1 title line from the top."""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    # Drop leading title line (single `# ` prefix) and blank lines after it
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("# ") and i == 0:
            start = 1
        elif start == 1 and line.strip() == "":
            start = 2
        else:
            break
    return "\n".join(lines[start:]).strip()


def push_all() -> None:
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY", "")
    if not api_key:
        print("[ERROR] LANGSMITH_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    client = Client(api_key=api_key)
    prompt_files = sorted(PROMPTS_DIR.glob("*.md"))

    if not prompt_files:
        print(f"[WARN] No .md files found in {PROMPTS_DIR}", file=sys.stderr)
        return

    errors = []
    for md_path in prompt_files:
        agent_id  = md_path.stem          # e.g. "researcher"
        hub_name  = f"qidi-{agent_id}"    # e.g. "qidi-researcher"
        text      = _load_prompt_text(md_path)

        prompt = ChatPromptTemplate.from_messages([
            ("placeholder", "{messages}"),
            ("system", text),
        ])

        try:
            url = client.push_prompt(hub_name, object=prompt)
            print(f"[OK] {hub_name:25s} -> {url}")
        except Exception as exc:
            msg = str(exc)
            if "409" in msg or "Nothing to commit" in msg:
                print(f"[OK] {hub_name:25s} -> up to date (409)")
            else:
                print(f"[FAIL] {hub_name}: {msg}", file=sys.stderr)
                errors.append((hub_name, msg))

    if errors:
        print(f"\n{len(errors)} push(es) failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\nAll {len(prompt_files)} prompts pushed successfully.")


if __name__ == "__main__":
    push_all()
