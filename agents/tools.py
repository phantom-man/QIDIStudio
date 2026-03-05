"""
agents/tools.py — Shared tools for all QIDIStudio sub-agents.

All tools are @tool decorated functions compatible with LangChain/LangGraph
create_react_agent. They share the same LanceDB instance as inject.py/extract.py.

Web search: google_search uses Google Grounding via Vertex AI (ADC auth, no
extra API key). Tavily has been removed — Google Grounding is higher quality,
free under ADC, and fully traceable in the ReAct loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import (
    tool,
)  # canonical import; langchain.tools re-exports this

# ── Paths & GCP config ────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"
INJECT_PY = REPO_ROOT / "memory" / "inject.py"
EXTRACT_PY = REPO_ROOT / "memory" / "extract.py"

_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# Ensure memory/ is importable — done once at module load, not per call.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── LanceDB store — module-level cache ───────────────────────────────────────

_store_fns: tuple | None = None  # (query_similar, upsert, count)


def _get_store():
    """Return cached (query_similar, upsert, count) — imported once."""
    global _store_fns
    if _store_fns is None:
        from memory.store import count as _count
        from memory.store import query_similar as _qs
        from memory.store import upsert as _up

        _store_fns = (_qs, _up, _count)
    return _store_fns


# ── Tools ────────────────────────────────────────────────────────────────────


@tool
def memory_read(query: str, n: int = 6) -> str:
    """
    Semantic search in the QIDIStudio LanceDB knowledge base.
    Returns the top-N matching chunks as JSON.
    Use this BEFORE any web search — knowledge base may already have the answer.
    """
    try:
        qs, _, _ = _get_store()
        rows = qs(query, n=n)
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
        _, up, cnt = _get_store()
        up(
            topic=topic,
            decision=decision,
            content=content,
            source=f"agents/{source}",
            category=category,
        )
        return json.dumps({"status": "ok", "total_rows": cnt()})
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
def google_search(query: str, n_sources: int = 5) -> str:
    """
    Live web search via Google Grounding (Vertex AI, ADC auth — no extra API key).
    Always call memory_read FIRST; use this only when the knowledge base lacks the answer.
    query:     natural language, academic, or code-search query.
    n_sources: number of grounding source citations to return (default 5).
    Returns JSON with response text and source URLs.
    """
    try:
        from google import genai  # pip install google-genai
        from google.genai import types

        client = genai.Client(
            vertexai=True,
            project=_GCP_PROJECT,
            location=_GCP_LOCATION,
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Search and summarize concisely: {query}",
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
            ),
        )
        sources: list[dict] = []
        if response.candidates:
            meta = response.candidates[0].grounding_metadata
            chunks = getattr(meta, "grounding_chunks", []) if meta else []
            for chunk in chunks[:n_sources]:
                web = getattr(chunk, "web", None)
                if web:
                    sources.append(
                        {
                            "title": getattr(web, "title", ""),
                            "uri": getattr(web, "uri", ""),
                        }
                    )
        return json.dumps(
            {
                "query": query,
                "response": response.text or "",
                "sources": sources,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "query": query})


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
        full_cmd = f'powershell -NoProfile -Command "& {{ {cmd} }}" > "{out_path}" 2>&1'
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
        fh = open(out_path, "w")  # noqa: WPS515
        proc = subprocess.Popen(
            [str(MEMORY_PY), str(EXTRACT_PY)],
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
        )
        fh.close()  # hand off fd to subprocess; safe to close after Popen
        return json.dumps(
            {
                "status": "launched",
                "pid": proc.pid,
                "output_file": "agents/_extract_out.txt",
            }
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@tool
def write_file(path: str, content: str) -> str:
    """
    Write (or overwrite) a file in the QIDIStudio workspace.
    path:    relative to repo root OR absolute path.
    content: full UTF-8 text content to write.
    Returns: confirmation JSON with the absolute path and byte count.
    Use this to apply code changes produced by the Coder agent.
    """
    try:
        p = Path(path)
        if not p.is_absolute():
            p = REPO_ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps(
            {"status": "ok", "path": str(p), "bytes": len(content.encode())}
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


@tool
def run_tests(
    command: str,
    output_file: str = "agents/_test_out.txt",
    timeout_seconds: int = 120,
) -> str:
    """
    Run a test command synchronously and return the captured output.
    Designed for the Tester agent — blocks until the test suite completes or times out.

    command:         Full test command, e.g. 'memory_env\\Scripts\\python.exe -B -m pytest
                     agents/parts_catalog/test_schema.py -v'
    output_file:     Relative path where stdout+stderr are also written (for file_read).
    timeout_seconds: Hard limit (default 120 s). Raises TimeoutError if exceeded.
    Returns:         JSON with returncode, stdout (truncated to 4000 chars), output_file path.
    """
    out_path = REPO_ROOT / output_file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(REPO_ROOT),
        )
        combined = result.stdout + (
            "\n--- STDERR ---\n" + result.stderr if result.stderr.strip() else ""
        )
        out_path.write_text(combined, encoding="utf-8", errors="replace")
        # Truncate for inline return; full output always in the file
        preview = combined[:4000]
        if len(combined) > 4000:
            preview += f"\n... [{len(combined) - 4000} chars truncated — read {output_file} for full output]"
        return json.dumps(
            {
                "returncode": result.returncode,
                "passed": "passed" in combined.lower() or result.returncode == 0,
                "output": preview,
                "output_file": str(out_path.relative_to(REPO_ROOT)),
            },
            indent=2,
        )
    except subprocess.TimeoutExpired:
        return json.dumps(
            {
                "returncode": -999,
                "passed": False,
                "output": f"TIMEOUT after {timeout_seconds}s",
                "output_file": output_file,
            }
        )
    except Exception as exc:
        return json.dumps(
            {
                "returncode": -1,
                "passed": False,
                "output": str(exc),
                "output_file": output_file,
            }
        )


@tool
def read_image(image_path: str, question: str) -> str:
    """
    Analyze an image using Gemini Vision (gemini-2.5-pro multimodal).
    For the Tester agent to inspect rendered meshes, screenshots, texture maps,
    toolpath visualizations, and any other visual test artifacts.

    image_path: absolute path to a .png / .jpg / .webp image.
    question:   specific question about what to look for in the image.
    Returns:    JSON with Gemini's analysis and a confidence verdict.
    """
    try:
        import base64
        from google import genai
        from google.genai import types

        img_path = Path(image_path)
        if not img_path.is_absolute():
            img_path = REPO_ROOT / image_path
        if not img_path.exists():
            return json.dumps({"error": f"Image not found: {img_path}"})

        image_bytes = img_path.read_bytes()
        mime = (
            "image/jpeg"
            if img_path.suffix.lower() in (".jpg", ".jpeg")
            else "image/png"
        )

        client = genai.Client(
            vertexai=True,
            project=_GCP_PROJECT,
            location=_GCP_LOCATION,
        )
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                f"Analyze this image carefully and answer: {question}\n"
                'Respond in JSON: {{"verdict": "ok|defect|unclear", '
                '"description": "what you see", "confidence": 0.0-1.0}}',
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return json.dumps(
            {
                "image": str(img_path.name),
                "question": question,
                "analysis": response.text,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "image": image_path})


# ── Tool sets per agent ───────────────────────────────────────────────────────

# google_search is uniform across all web-capable agents — same quality, same ADC auth.
RESEARCHER_TOOLS = [memory_read, memory_write, file_read, file_search, google_search]
BUILDER_TOOLS = [memory_read, file_read, file_search, run_command]
VERIFIER_TOOLS = [memory_read, file_read, file_search]
SCRIBE_TOOLS = [memory_read, memory_write, file_read, run_command, reindex_memory]
LIBRARIAN_TOOLS = [memory_read, file_read, file_search, google_search]
SKEPTIC_TOOLS = [memory_read, file_read, file_search, run_command]
SYNTHESIZER_TOOLS = [memory_read, memory_write, file_read, file_search]

# Coder/Tester dev fleet tool sets
CODER_TOOLS = [
    memory_read,
    memory_write,
    file_read,
    file_search,
    write_file,
    run_command,
]
TESTER_TOOLS = [
    memory_read,
    memory_write,
    file_read,
    file_search,
    run_tests,
    read_image,
]
