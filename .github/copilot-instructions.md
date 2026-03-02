# QIDIStudio Copilot — Session Bootstrap

You are **GitHub Copilot**, engineering AI for the **QIDIStudio** fork.
Repo : `C:\Users\User\source\repos\QIDIStudio\`  
GitHub: `phantom-man/QIDIStudio`
Model : Claude Sonnet 4.6

---

## YOUR KNOWLEDGE IS IN LanceDB, NOT IN THIS FILE

The **UserPromptSubmit** hook has already called `memory/inject.py` before this prompt arrived.  
Look above — you should see `━━━ QIDISTUDIO KNOWLEDGE BASE ━━━`.

**If you see it:** knowledge base is loaded. Proceed.  
**If you do NOT see it:** run this in the `scripts` terminal, then read the output:

```powershell
& 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory/inject.py
```

---

## Memory Commands

> All memory commands use the **universal memory venv**: `memory_env\Scripts\python.exe`

| Purpose                              | Command                                                                     |
| ------------------------------------ | --------------------------------------------------------------------------- |
| Compact manifest (all topics)        | `memory_env\Scripts\python.exe memory/inject.py`                            |
| Full text dump (everything verbatim) | `memory_env\Scripts\python.exe memory/inject.py --full`                     |
| Semantic search                      | `memory_env\Scripts\python.exe memory/inject.py --query "cmake build"`      |
| Re-index docs to LanceDB             | `memory_env\Scripts\python.exe memory/extract.py`                           |
| Push prompt to LangSmith Hub         | `memory_env\Scripts\python.exe memory/push_prompt.py`                       |
| Push ALL agent prompts to Hub        | `memory_env\Scripts\python.exe agents/push_all_prompts.py`                  |
| Re-install deps                      | `.\memory_env\Scripts\python.exe -m pip install -r memory\requirements.txt` |
| Run agent fleet                      | `memory_env\Scripts\python.exe agents/orchestrator.py "your request"`       |

---

## ⚡ ALWAYS PARALLEL — NON-NEGOTIABLE

These rules are **mandatory**. Violating them is the #1 performance problem.

### Parallelism Rules

1. **NEVER use `captureOutput: true`** on terminal commands. They block until the shell
   closes. Instead: pipe to a file (`2>&1 | Tee-Object out.txt`) then `read_file` it.

2. **NEVER wait sequentially** for unrelated operations. Fire all independent tool calls
   in a single `<function_calls>` block. If calls don't depend on each other, they run together.

3. **NEVER poll a terminal** more than once. If you need output, write it to a file,
   move on to other work, and come back to read the file as a separate step.

4. **Delegate blocking work to `runSubagent`.** If a task involves: running a build,
   waiting on a long install, reading many files, or doing research — spawn a subagent.
   You are the director. You keep your context clean.

5. **Multi-step tasks: plan first, execute in parallel batches.**
   Use `manage_todo_list` to lay out the plan, then execute all non-dependent steps
   in the same tool call block.

6. **Sub-agents get full context upfront.** Load them heavy with everything they need.
   No back-and-forth. Trust LanceDB to hold the detail.

### Agent Fleet (sub-agents for heavy tasks)

| Agent        | Purpose                                      | Key Capability             |
| ------------ | -------------------------------------------- | -------------------------- |
| `researcher` | Technical research, documentation deep-dives | Gemini + Google Search     |
| `builder`    | C++ / Python / CMake implementation          | Gemini + Code Execution    |
| `verifier`   | Code review, bug-pattern check               | Gemini, structured verdict |
| `scribe`     | Memory sync, knowledge base write            | LanceDB tools              |

Invoke via: `memory_env\Scripts\python.exe agents/orchestrator.py "task description"`

---

## Minimal Reference (in case memory is unavailable)

- **Build source**: `C:\QIDISrc\QIDIStudio\build\`
- **Install dir** : `C:\QIDISrc\QIDIStudio\install_dir\`
- **bpy script** : `resources\scripts\apply_texture_bpy.py`
- **Blender** : `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`
- **Memory venv** : `memory_env\Scripts\python.exe` (LangSmith + LanceDB + sentence-transformers — use for ALL memory commands)
- **Python 3.13** : `C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe` (general scripts, NOT memory)
- **Python 3.11** : `bpy_env\Scripts\python.exe` (Blender bpy pip package, not for general use)

**Build command:**

```powershell
Set-Location C:\QIDISrc\QIDIStudio\build
cmake --build . --target install --config Release -- /m:16 2>&1 | Tee-Object build_out.txt; echo "DONE" >> build_out.txt
```

---

## Session Learnings Log

Append rows here — `memory/extract.py` auto-indexes them into LanceDB.

| Date       | Category         | Topic                                             | Decision                                                                                                                                                                                                                                                         | Rationale                                                                                                                       |
| ---------- | ---------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 2026-03-02 | hooks_and_memory | Compaction flag mechanism                         | `precompact_hook.ps1` writes `memory/_compaction_pending.txt` on every PreCompact. `inject.py` detects it and injects a hard warning banner into every subsequent prompt. `extract.py` deletes the flag after successful sync.                                   | Prevents agent from silently skipping session learning capture after a compaction event.                                        |
| 2026-03-02 | hooks_and_memory | Archive indexing — heading mismatch               | `session_learnings_archive.md` must be parsed with inline `_parse_learnings_table()` call directly on file content, NOT via `extract_learnings_table()` which requires a `## Session Learnings Log` heading. Archive uses `# Session Learnings Archive`.         | Caused 0 rows parsed from archive on every prior extract run, silently losing 86 archived learnings on each full table rebuild. |
| 2026-03-02 | hooks_and_memory | replace_all=True prevents orphan row accumulation | `sync_to_lancedb()` calls `batch_upsert(rows, replace_all=True)` — full table delete before re-add. Fixed store going from 273 (with orphans) to correct 137 section-chunk rows.                                                                                 | Without replace_all, renamed/deleted topics silently accumulate across extract runs, inflating the row count.                   |
| 2026-03-02 | hooks_and_memory | IN-delete fallback for GCS LanceDB                | Large `topic IN (...)` deletes can silently fail on GCS-backed LanceDB. Added per-row fallback loop: iterate escaped topics and call `table.delete(f"topic = '{esc}'")` individually after IN-clause exception.                                                  | GCS LanceDB may reject oversized SQL predicates; silent failure caused phantom rows to pile up.                                 |
| 2026-03-02 | hooks_and_memory | LanceDB store target row count = 223              | After fixing archive indexing and replace_all rebuild: 137 section-chunk rows + 86 archived learnings = 223. This is the stable post-fix baseline.                                                                                                               | Reference count for detecting future corruption or orphan accumulation.                                                         |
| 2026-03-02 | tools_and_env    | LanceDB v0.30 still in beta                       | As of 2026-03-02, latest is `lancedb==0.30.0b3` (beta.3); no stable v0.30.0 release exists yet. The sole Python breaking change in v0.30.0-beta.0 was adding RecordBatch overload to `create_table()`/`Table.add()` — dict-based `table.add([...])` still works. | Do not block upgrades on this; beta.3 is safe to install. Pin as `lancedb==0.30.0b3` or `lancedb>=0.30.0b3`.                    |
| 2026-03-02 | tools_and_env    | LanceDB Time Travel API                           | `db.open_table(name, version=N)` or `db.open_table(name, timestamp="ISO8601")` pins the connection to a historical snapshot. v0.30 adds background dataset update so coordinator agents can update while worker agents stay pinned to a version.                 | Critical for agent safety: corrupt table state can be recovered by rewinding to a known-good version number from GCS manifest.  |
