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
| 2026-03-02 | hooks_and_memory | Agent row protection — scoped delete | `batch_upsert(replace_all=True)` now deletes only `"source NOT LIKE 'agents/%'"` instead of `"id IS NOT NULL"`. Agent-written rows (source starts with `agents/`) survive every extract.py rebuild permanently. Fallback: per-topic delete loop for non-agent rows if LIKE predicate fails on GCS. | Without scoping, every `replace_all=True` rebuild wiped all agent contributions, making persistent agent memory impossible. |
| 2026-03-02 | hooks_and_memory | LanceDB store row count = 230 (post-session 2) | After v0.30-prep changes and 7 new session-learnings rows: stable baseline is 230 rows (all non-agent). 0 agent-written rows exist yet — first agent write will increment above 230. Cross-check: `source NOT LIKE 'agents/%'` filter returns exactly 230. | Updated reference count; deviation from 230 on next non-agent-write rebuild indicates a bug. |
| 2026-03-02 | agent_design | Researcher agent has memory_write access | `RESEARCHER_TOOLS` in `agents/tools.py` now includes `memory_write`. Researcher can persist findings directly to LanceDB with `source="agents/researcher"`. Only `scribe`, `synthesizer`, and `researcher` have write access; `builder`, `verifier`, `librarian`, `skeptic` are read-only. | User decision: researcher findings should be durable, not lost when the conversation ends. |
| 2026-03-02 | tools_and_env | list_tables() membership fails on GCS LanceDB | `"tablename" in db.list_tables()` raises or gives false negatives on GCS because `list_tables()` returns objects, not plain strings. Fix: try/open-first pattern — call `db.open_table(name)` and catch the "doesn't exist" exception. Now in `_get_table()` in store.py. | `table_names()` also deprecated. Open-first is the correct pattern for GCS-backed LanceDB going forward. |
