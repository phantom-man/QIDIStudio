# QIDIStudio Agent Fleet — Operating Protocol

_Maintained by: GitHub Copilot | Last updated: 2026-02-28_  
_This document governs how GitHub Copilot (the primary engineering AI) decides when, which, and how to invoke the LangGraph sub-agent fleet._

---

## 0. Quick Reference Card

| I need to…                                       | Use                                        |
| ------------------------------------------------ | ------------------------------------------ |
| Answer a factual question about the codebase     | Direct answer (LanceDB already loaded)     |
| Research a library API or upstream change        | `researcher`                               |
| Implement a C++ / Python / CMake change          | `builder`                                  |
| Review a proposed change for correctness/risk    | `verifier`                                 |
| Save session learnings to LanceDB                | `scribe`                                   |
| Large feature spanning research + build + verify | Full fleet via `orchestrator.run()`        |
| Commit/push git changes                          | GitKraken tools directly (no fleet needed) |
| Read/edit a file                                 | Direct tools (no fleet needed)             |

---

## 1. Architecture Snapshot

```
GitHub Copilot (primary)
    │
    ├─ Direct tools: file read/edit, git, search
    │
    └─ orchestrator.run(request, thread_id?)
           │
           ├─ plan()        ← director LLM (gemini-2.5-flash, structured JSON output)
           │
           └─ dispatch()    ← Send API parallel fan-out
                  ├─ researcher  (gemini-2.5-flash + google_search + url_context + memory_read)
                  ├─ builder     (gemini-2.5-pro   + code_execution + file_read + run_command)
                  ├─ verifier    (gemini-2.5-flash  + file_read + memory_read)
                  └─ scribe      (gemini-2.5-flash  + memory_write + reindex_memory)
                         │
                         └─ synthesize()  ← director LLM collects all results → final string
```

**State persistence**: PostgresSaver → `postgres://localhost:5432/postgres`. If Postgres is down, falls back to MemorySaver (in-process only, lost on restart).  
**Thread continuity**: Pass the same `thread_id` across related `orchestrator.run()` calls to resume a checkpointed session.

---

## 2. The Invocation Decision

### 2.1 Do NOT invoke the fleet when

- The task is a single-file read, edit, or search — use direct tools.
- The answer is already in the LanceDB manifest loaded at session start.
- The task is a git operation — GitKraken tools handle this.
- The user asks a quick factual question — answer directly.
- The change is fully self-contained in ≤ 2 files with no research needed.

**Rule of thumb**: If I can fully satisfy the request myself in ≤ 3 tool calls, do it directly.

### 2.2 DO invoke the fleet when

- The task requires **live web research** (new library API, upstream repo check, bug report lookup).
- The task requires **complex multi-file implementation** with unknown side-effects.
- The task requires **independent code review** of a change I am about to make or just made.
- The task involves **saving non-trivial session knowledge** to persistent memory.
- The user explicitly asks for autonomous agent work ("research and implement", "verify this change", "save what we learned").
- The work decomposes naturally into parallel tracks (research + build simultaneously).

---

## 3. Per-Agent Reference

### 3.1 Researcher

**Model**: gemini-2.5-flash + Google Search + URL Context  
**Tools**: `memory_read`, `file_read`, `file_search`

**Invoke when**:

- Checking whether a third-party API still works the same way (LangGraph, bpy, wxWidgets).
- Finding the correct CMake variable name / flag syntax.
- Verifying an upstream OrcaSlicer/BambuStudio commit exists or was reverted.
- Resolving a "what does this function actually do" question about an external library.

**Do NOT use for**:

- Code that already exists in the workspace (use `file_read` directly).
- Questions answered by the LanceDB manifest injected at the start of every session.

**Output contract** (JSON):

```json
{
  "query": "...",
  "sources": [{ "url": "...", "excerpt": "...", "confidence": 0.9 }],
  "answer": "...",
  "off_domain": false
}
```

**Failure mode**: If `off_domain: true` is returned, stop and tell the user the topic is out of scope.

---

### 3.2 Builder

**Model**: gemini-2.5-pro + Code Execution  
**Tools**: `memory_read`, `file_read`, `file_search`, `run_command`

**Invoke when**:

- Implementing a multi-file C++ or Python change where the full context is too large for a single direct edit.
- Writing a new Python script that needs to be mentally executed and tested.
- CMake changes where I'm uncertain about downstream effects.
- Any change requiring `run_command` (e.g., running a build step to confirm the change compiles).

**Builder must always**:

1. Call `file_read` before editing — never assume file content.
2. Check the 10-point Known Bugs Checklist (in `agents/prompts/builder.md`) before any C++ change.
3. Write only one deliverable per task — no omnibus changes.

**run_command protocol** (builder only):

- `run_command` fires asynchronously and returns immediately with an output file path.
- Builder must: launch → do other reasoning → read output file → report result.
- **Never** pass `capture_output=True` or block in a loop.
- Write output to `agents/_cmd_out.txt` (or a unique name if multiple commands run in parallel).

**Output contract**: Plain text or a JSON diff with `{ "file": "...", "change_summary": "...", "lines_changed": N }`.

---

### 3.3 Verifier

**Model**: gemini-2.5-flash  
**Tools**: `memory_read`, `file_read`, `file_search`

**Invoke when**:

- I have just implemented a change and want an independent review before committing.
- A change touches any of the 10 known-bug files (wxExtensions, AppConfig, CMakeLists, Plater).
- The user asks for a code review.
- The builder returned a result and I want to validate correctness before applying it.

**Verifier output contract** (binary verdict + rationale):

```json
{
  "verdict": "PASS" | "FAIL" | "WARN",
  "issues": [ { "severity": "error|warn|info", "file": "...", "line": N, "description": "..." } ],
  "summary": "One sentence verdict"
}
```

**On FAIL**: Stop. Do not commit. Report the issues to the user and loop back to builder.  
**On WARN**: Commit with a note. Flag warnings in the PR description.  
**On PASS**: Proceed to scribe + git commit.

---

### 3.4 Scribe

**Model**: gemini-2.5-flash  
**Tools**: `memory_read`, `memory_write`, `file_read`, `run_command`, `reindex_memory`

**Invoke when**:

- A session has produced a confirmed new fact, bug fix, or architectural decision.
- `reindex_memory` is needed (new docs added to `docs/`, `memory/langsmith_prompt.md` updated).
- The PreCompact hook fires (automatic — scribe runs without explicit invocation).

**Scribe writes to LanceDB via `memory_write`**:

```
topic:    "Short label ≤ 12 words"
decision: "The confirmed fact ≤ 30 words"
content:  "Full verbatim context (any length)"
source:   "file:line or function name"
category: "C++ | CMake | Build | Memory | LanceDB | LangSmith | tools_and_env | Blender | geometry"
```

**Scribe must always**:

1. Call `memory_read` first — avoid duplicating an already-stored chunk.
2. Call `reindex_memory` after writing new chunks so the next session sees them immediately.
3. After reindexing, confirm row count increased.

**Do NOT use scribe for**:

- File edits — that's builder.
- Git commits — use GitKraken tools directly.

---

## 4. Invocation Patterns

### 4.1 Full Fleet (Research + Build + Verify + Remember)

Use this for any non-trivial feature or bug fix.

```python
from agents.orchestrator import run

result = run(
    "Research the bpy API for Blender 5.0 LSCM unwrap parameters, "
    "then update apply_texture_bpy.py to use the confirmed parameter names, "
    "verify the change is safe, and save the confirmed API to memory.",
    thread_id="texture-lscm-fix-001"   # reusable across follow-up prompts
)
print(result)
```

Director will decompose this into:

- `researcher` → confirm bpy LSCM API (parallel)
- `builder` → implement update (after researcher)
- `verifier` → review change (after builder)
- `scribe` → save confirmed API (parallel with verifier, in practice)

### 4.2 Research Only

```python
result = run("Research whether LangGraph 0.3.x changed the Send API fan-out semantics")
```

Director produces a single `researcher` task. No builder/verifier needed.

### 4.3 Implementation Only (known context)

```python
result = run(
    "In Plater.cpp, change wxEXEC_SYNC to wxEXEC_BLOCK in the apply_texture command. "
    "Context: line ~2400, function on_action_apply_texture."
)
```

Director produces: `builder` (implement) → `verifier` (review) → `scribe` (save).

### 4.4 Verify + Remember Only

```python
result = run(
    "Verify the change I just made to apply_texture_bpy.py is safe. "
    "Then save the confirmed mid_level=0.0 fact to memory."
)
```

Director produces: `verifier` (parallel) + `scribe` (parallel, saves regardless of verdict).

### 4.5 Resume a Thread

```python
# Session 1:
result1 = run("Research the issue", thread_id="bug-123")

# Session 2 (same thread — director has full history from Postgres checkpoint):
result2 = run("Now implement the fix based on your research", thread_id="bug-123")
```

---

## 5. Parallelism Rules (NON-NEGOTIABLE)

1. **All tasks with `depends_on: []` run in the same LangGraph superstep = true parallel.** Group independent tasks aggressively.
2. **NEVER use `captureOutput: true` or sequential blocking waits** — delegate to `run_command` (async) or `runSubagent`.
3. **When reading multiple files**: issue all `file_read` calls in the same parallel batch.
4. **Director must batch research tasks**: if researcher + scribe have no mutual dependency, both run in parallel.
5. **`reindex_memory` is async** — scribe fires it and does not wait; the next session will pick up the new rows.

---

## 6. Memory Lifecycle

```
Session start
    └─ UserPromptSubmit hook → memory/inject.py → LanceDB manifest injected into my context

During session
    └─ Any confirmed new fact → manually invoke scribe OR defer to PreCompact

Session end (context approaching limit)
    └─ PreCompact hook fires automatically:
           ├─ memory/extract.py  (re-index all docs/memory/*.md to LanceDB)
           ├─ git add -A && git commit (auto-saves pending changes)
           └─ Prompt injection: "Save any new learnings you know from this session"
```

**What must be saved** (scribe writes these):

- New confirmed API facts (bpy, wxWidgets, LangGraph, CMake).
- New bug discoveries and their root causes.
- Architecture decisions made during the session.
- Any `thread_id` → task mapping for ongoing multi-session work.
- Verifier verdicts on significant changes.

**What must NOT be saved**:

- Temporary debug output, scratch values, transient log lines.
- Anything already present in LanceDB (check `memory_read` first).

---

## 7. Error Handling

| Scenario                                | Action                                                                                                                                    |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `orchestrator.run()` raises ImportError | Fleet deps not installed in active venv. Run `memory_env\Scripts\pip install -r memory\requirements.txt`.                                 |
| `PostgresSaver` unavailable             | Automatic fallback to MemorySaver. State is in-process only. Re-run with same thread_id when Postgres is back.                            |
| Agent returns `success: False`          | Check `error` field. If it's an LLM quota error, retry after 30s. If it's a tool error, fix the tool call and re-run.                     |
| Researcher returns `off_domain: true`   | Stop fleet. Tell user topic is out of scope. Do not retry.                                                                                |
| Verifier returns `FAIL`                 | Do NOT commit. Return issues to user. Loop: fix → re-verify.                                                                              |
| Scribe reindex hangs                    | Read `agents/_extract_out.txt` for status. If timeout: re-run `memory_env\Scripts\python.exe memory\extract.py` manually.                 |
| Hub prompt pull fails (LangSmith)       | Falls back to local `agents/prompts/<agent_id>.md` automatically.                                                                         |
| `google_api_key` error in agent         | Auth is via Vertex AI ADC (not API key). Run `gcloud auth application-default login`. Check `GOOGLE_CLOUD_PROJECT=crafty-hook-483415-b3`. |

---

## 8. Thread ID Convention

```
<scope>-<brief-slug>-<nnn>

Examples:
  texture-lscm-fix-001
  cmake-qidinetwork-patch-001
  blender-api-research-001
  memory-reindex-2026-02-28
```

Increment `nnn` when restarting a failed run. Use the same slug for follow-up steps in the same logical task.

---

## 9. When to Run the Fleet vs. Direct Tools — Decision Flowchart

```
User request arrives
    │
    ├─ Is the answer in the LanceDB manifest? ──YES──→ Answer directly
    │
    ├─ Is it a file read/edit/search only? ──YES──→ Use direct tools
    │
    ├─ Is it a git operation? ──YES──→ GitKraken tools
    │
    ├─ Does it require live web research? ──YES──→ fleet (researcher ± others)
    │
    ├─ Does it require complex multi-file implementation? ──YES──→ fleet (builder + verifier + scribe)
    │
    ├─ Does it require saving facts to memory? ──YES──→ fleet (scribe) or manual memory_write
    │
    └─ Everything else ──→ Direct tools, answer directly
```

---

## 10. Integration Checklist — Before Every Fleet Run

- [ ] LanceDB manifest was injected at session start (check context for the ━━━ block).
- [ ] `memory_env\Scripts\python.exe` exists and is reachable.
- [ ] `.env` at repo root contains `LANGSMITH_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `PG_DSN`.
- [ ] `gcloud auth application-default login` has been run (Vertex AI ADC).
- [ ] For build tasks: confirm `C:\QIDISrc\QIDIStudio\` and `C:\CMake329\bin\cmake.exe` exist.
- [ ] For Blender tasks: confirm `QIDI_BLENDER_EXE` or default Blender 5.0 path exists.

---

## 11. Copilot Self-Invocation — How I call the fleet

The fleet is callable via the `mcp_pylance_mcp_s_pylanceRunCodeSnippet` tool:

```python
import sys
sys.path.insert(0, r'C:\Users\User\source\repos\QIDIStudio')
from agents.orchestrator import run
result = run("YOUR REQUEST HERE", thread_id="slug-001")
print(result)
```

Or via a terminal command in a named terminal (`terminal-tools_createTerminal` → run):

```powershell
cd C:\Users\User\source\repos\QIDIStudio
memory_env\Scripts\python.exe -c "from agents.orchestrator import run; print(run('YOUR REQUEST', thread_id='slug-001'))"
```

**Important**: Always capture the `thread_id` from the `[thread:xxx]` prefix in the result string for follow-up calls.

---

## 12. Maintenance

- This document is the **single source of truth** for fleet operation.
- When agent prompts change (push to LangSmith Hub via `memory_env\Scripts\python.exe memory\push_prompt.py`), update the relevant section here.
- When new agents are added to `agents/agents.py`, add a §3.x entry here.
- Scribe should update the `Last updated` date header when making changes here.
