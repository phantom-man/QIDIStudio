"""
Push the QIDIStudio system prompt to LangSmith Hub.

Run once after editing memory/langsmith_prompt.md:
    python memory/push_prompt.py

Hub path: qidistudio-memory-agent  (resolved to workspace via LANGSMITH_WORKSPACE_ID)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(repo_root / ".env", override=True)
except ImportError:
    pass

api_key  = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
ws_id    = os.getenv("LANGSMITH_WORKSPACE_ID")

if not api_key:
    print("[ERROR] LANGCHAIN_API_KEY not set. Check .env.", file=sys.stderr)
    sys.exit(1)

prompt_file = Path(__file__).parent / "langsmith_prompt.md"
if not prompt_file.exists():
    print(f"[ERROR] Prompt file not found: {prompt_file}", file=sys.stderr)
    sys.exit(1)

# Strip comment-only header lines (lines starting with a single #)
lines = prompt_file.read_text(encoding="utf-8").splitlines()
content_lines = []
in_header = True
for line in lines:
    if in_header and line.startswith("# ") and not line.startswith("## "):
        continue
    in_header = False
    content_lines.append(line)
prompt_content = "\n".join(content_lines).strip()

PROMPT_NAME = "qidistudio-memory-agent"

try:
    from langsmith import Client
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    print("[ERROR] langsmith / langchain_core not installed. Run: pip install -r memory/requirements.txt", file=sys.stderr)
    sys.exit(1)

# Build client — pass workspace_id for org keys (same pattern as hub_manager.py)
client_kwargs: dict = {"api_key": api_key}
if ws_id:
    client_kwargs["workspace_id"] = ws_id
client = Client(**client_kwargs)

# Match deepagents pattern: system + placeholder for messages
prompt = ChatPromptTemplate.from_messages([
    ("system", prompt_content),
    ("placeholder", "{messages}"),
])

print(f"[INFO] Pushing prompt '{PROMPT_NAME}' to LangSmith Hub...")
masked = f"{api_key[:8]}...{api_key[-4:]}"
print(f"[INFO] Key: {masked}  Workspace: {ws_id or '(from env)'}")

try:
    url = client.push_prompt(PROMPT_NAME, object=prompt)
    print(f"[OK]  Pushed successfully.")
    print(f"      URL: {url}")
except Exception as exc:
    exc_str = str(exc)
    if "409" in exc_str and "Nothing to commit" in exc_str:
        print(f"[OK]  Prompt is already up to date (nothing to commit).")
    else:
        print(f"[ERROR] Push failed: {exc}", file=sys.stderr)
        sys.exit(1)


def pull_prompt():
    """Pull the prompt back from Hub for use in agent code."""
    _client_kwargs: dict = {}
    _key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    _ws  = os.getenv("LANGSMITH_WORKSPACE_ID")
    if _key: _client_kwargs["api_key"] = _key
    if _ws:  _client_kwargs["workspace_id"] = _ws
    return Client(**_client_kwargs).pull_prompt(PROMPT_NAME)

