"""
Push the QIDIStudio system prompt to LangSmith Hub.

Run once after editing memory/langsmith_prompt.md:
    python memory/push_prompt.py

Hub path: damienfosborn/qidistudio-memory-agent
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
    load_dotenv(repo_root / ".env")
except ImportError:
    pass  # dotenv optional for pushing

langchain_api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
if not langchain_api_key:
    print("[ERROR] LANGCHAIN_API_KEY not set. Check .env.", file=sys.stderr)
    sys.exit(1)

prompt_file = Path(__file__).parent / "langsmith_prompt.md"
if not prompt_file.exists():
    print(f"[ERROR] Prompt file not found: {prompt_file}", file=sys.stderr)
    sys.exit(1)

prompt_text = prompt_file.read_text(encoding="utf-8")

# Strip the YAML header comment lines (lines starting with #)
content_lines = [l for l in prompt_text.splitlines() if not l.startswith("#") or l.startswith("##")]
prompt_content = "\n".join(content_lines).strip()

HUB_HANDLE   = os.getenv("LANGSMITH_HUB_HANDLE", "damienfosborn")
PROMPT_NAME  = "qidistudio-memory-agent"
FULL_PATH    = f"{HUB_HANDLE}/{PROMPT_NAME}"

try:
    from langsmith import Client
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:
    print("[ERROR] langsmith / langchain_core not installed. Run: pip install -r memory/requirements.txt", file=sys.stderr)
    sys.exit(1)

client = Client(api_key=langchain_api_key)

# Build a simple system prompt template
prompt = ChatPromptTemplate.from_messages([
    ("system", prompt_content),
    ("human", "{input}"),
])

print(f"[INFO] Pushing prompt to Hub: {FULL_PATH} ...")
try:
    url = client.push_prompt(FULL_PATH, object=prompt)
    print(f"[OK] Pushed successfully.")
    print(f"     Hub URL: {url}")
except Exception as exc:
    print(f"[ERROR] Push failed: {exc}", file=sys.stderr)
    sys.exit(1)


def pull_prompt(as_runnable: bool = True):
    """Pull the prompt back from Hub (use in agent code)."""
    from langsmith import Client as _C
    _api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    _client  = _C(api_key=_api_key)
    obj = _client.pull_prompt(FULL_PATH)
    return obj.as_runnable() if (as_runnable and hasattr(obj, "as_runnable")) else obj


if __name__ == "__main__":
    pass  # main logic runs at import time above
