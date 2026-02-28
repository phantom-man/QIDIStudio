"""
agents/tools.py — Shared tools for all QIDIStudio sub-agents.

All tools are @tool decorated functions compatible with LangChain/LangGraph
create_react_agent. They share the same LanceDB instance as inject.py/extract.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from langchain.tools import tool

# Tavily search (optional — requires TAVILY_API_KEY in .env)
try:
    from langchain_community.tools.tavily_search import (
        TavilySearchResults as _TavilyBase,
    )

    _TAVILY_AVAILABLE = True
except ImportError:
    _TAVILY_AVAILABLE = False

# ── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"
INJECT_PY = REPO_ROOT / "memory" / "inject.py"
EXTRACT_PY = REPO_ROOT / "memory" / "extract.py"


# ── LanceDB helpers ───────────────────────────────────────────────────────────


def _get_store():
    """Import memory.store lazily (requires memory_env on sys.path)."""
    sys.path.insert(0, str(REPO_ROOT))
    from memory.store import (
        query_similar,
        upsert,
        count as store_count,
    )  # noqa: PLC0415

    return query_similar, upsert, store_count


# ── Tools ────────────────────────────────────────────────────────────────────


@tool
def memory_read(query: str, n: int = 6) -> str:
    """
    Semantic search in the QIDIStudio LanceDB knowledge base.
    Returns the top-N matching chunks as JSON.
    Use this BEFORE any web search — knowledge base may already have the answer.
    """
    try:
        query_similar, _, _ = _get_store()
        rows = query_similar(query, n=n)
        results = [
            {
                "topic": r.get("topic", ""),
                "decision": r.get("decision", ""),
                "content": (r.get("content") or r.get("decision", ""))[:800],
                "source": r.get("source", ""),
            }
            for r in rows
        ]
        return json.dumps(
            {"query": query, "hits": len(results), "results": results}, indent=2
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "results": []})


@tool
def memory_write(
    topic: str,
    decision: str,
    content: str,
    source: str,
    category: str = "tools_and_env",
) -> str:
    """
    Write a new learning entry to LanceDB.
    topic:    short label (≤ 12 words)
    decision: the confirmed pattern / fact (≤ 30 words)
    content:  full verbatim context (any length)
    source:   file:line or URL
    category: one of C++ | CMake | Build | Memory | LanceDB | LangSmith | tools_and_env | etc.
    Returns: confirmation with new row count.
    """
    try:
        _, upsert, store_count = _get_store()
        upsert(
            topic=topic,
            decision=decision,
            content=content,
            source=f"agents/{source}",
            category=category,
        )
        n = store_count()
        return json.dumps({"status": "ok", "total_rows": n})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@tool
def file_read(path: str, start_line: int = 1, end_line: int = 120) -> str:
    """
    Read lines from a file in the QIDIStudio workspace.
    path:       relative to repo root  OR  absolute path.
    start_line: 1-based inclusive.
    end_line:   1-based inclusive. Max 200 lines per call.
    Returns the file content as a string.
    """
    try:
        p = Path(path)
        if not p.is_absolute():
            p = REPO_ROOT / path
        if not p.exists():
            return json.dumps({"error": f"File not found: {p}"})
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        end_line = min(end_line, start_line + 199, len(lines))
        selected = lines[start_line - 1 : end_line]
        return "\n".join(selected)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool
def tavily_search(query: str, max_results: int = 5) -> str:
    """
    Live web search via Tavily — use for ArXiv papers, GitHub repos, technical docs.
    Always call memory_read FIRST; use this only when the knowledge base misses.
    query:       natural language or academic search query.
    max_results: number of results to return (default 5, max 10).
    Returns JSON list of {title, url, content} hits.
    """
    if not _TAVILY_AVAILABLE:
        return json.dumps(
            {
                "error": "tavily-python not installed. Run: pip install tavily-python langchain-community"
            }
        )
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return json.dumps({"error": "TAVILY_API_KEY not set in .env"})
    try:
        searcher = _TavilyBase(api_key=api_key, max_results=min(max_results, 10))
        raw = searcher.invoke(query)
        # Normalise to list of dicts
        results = []
        for item in raw if isinstance(raw, list) else [raw]:
            if isinstance(item, dict):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", "")[:600],
                    }
                )
        return json.dumps(
            {"query": query, "hits": len(results), "results": results}, indent=2
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool
def file_search(pattern: str, search_type: str = "files") -> str:
    """
    Search the workspace.
    pattern:     glob pattern (files) or text pattern (content).
    search_type: 'files' to find by filename, 'content' to grep inside files.
    Returns JSON list of matches (up to 30).
    """
    import glob

    try:
        if search_type == "files":
            matches = glob.glob(str(REPO_ROOT / "**" / pattern), recursive=True)
            matches = [str(Path(m).relative_to(REPO_ROOT)) for m in matches[:30]]
            return json.dumps({"matches": matches, "count": len(matches)})
        else:
            # content search via grep
            proc = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.cpp",
                    "--include=*.hpp",
                    "--include=*.py",
                    "--include=*.cmake",
                    "--include=CMakeLists.txt",
                    "-l",
                    pattern,
                    str(REPO_ROOT / "src"),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()][:30]
            return json.dumps({"matches": lines, "count": len(lines)})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool
def run_command(cmd: str, output_file: str = "agents/_cmd_out.txt") -> str:
    """
    Run a shell command ASYNCHRONOUSLY and write output to a file.
    Returns immediately with the output file path — do NOT block waiting.
    Read the output file after a reasonable delay.

    cmd:         PowerShell command to run (Windows).
    output_file: relative path for stdout/stderr capture.
    """
    out_path = REPO_ROOT / output_file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Fire and forget — write PID to file header
        full_cmd = f'powershell -NoProfile -Command "& {{ {cmd} }}" 2>&1 | Tee-Object "{out_path}"'
        proc = subprocess.Popen(
            full_cmd,
            shell=True,
            cwd=str(REPO_ROOT),
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            ),
        )
        return json.dumps(
            {
                "status": "launched",
                "pid": proc.pid,
                "output_file": str(out_path.relative_to(REPO_ROOT)),
                "note": "Read output_file after the command completes — do not block.",
            }
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@tool
def reindex_memory() -> str:
    """
    Run memory/extract.py to re-index all source docs into LanceDB.
    Fires asynchronously. Read agents/_extract_out.txt for results.
    """
    out_path = REPO_ROOT / "agents" / "_extract_out.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(
            [str(MEMORY_PY), str(EXTRACT_PY)],
            stdout=open(out_path, "w"),
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
        )
        return json.dumps(
            {
                "status": "launched",
                "pid": proc.pid,
                "output_file": "agents/_extract_out.txt",
            }
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


# ── Tool sets per agent ───────────────────────────────────────────────────────

RESEARCHER_TOOLS = [memory_read, file_read, file_search, tavily_search]
BUILDER_TOOLS = [memory_read, file_read, file_search, run_command]
VERIFIER_TOOLS = [memory_read, file_read, file_search]
SCRIBE_TOOLS = [memory_read, memory_write, file_read, run_command, reindex_memory]
LIBRARIAN_TOOLS = [memory_read, file_read, file_search, tavily_search]
SKEPTIC_TOOLS = [memory_read, file_read, file_search, run_command]
SYNTHESIZER_TOOLS = [memory_read, memory_write, file_read, file_search]
