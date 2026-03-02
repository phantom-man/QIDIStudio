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

| Date       | Category         | Topic                                                        | Decision                                                                                                                                                                                                                                                                                                             | Rationale                                                                                                                                                     |
| ---------- | ---------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-03-02 | agent_design | Tavily replaced by google_search explicit tool | `tavily_search` removed from tools.py. Replaced with `@tool google_search` using `google.genai.Client(vertexai=True)` + `types.Tool(google_search=types.GoogleSearch())`. ADC auth — no extra API key. Tool call is explicit in the ReAct loop and visible in LangSmith traces. `pip install google-genai` required. | Tavily was a visibility workaround; constructor-level Gemini built-ins were opaque to LangGraph. Explicit tool is the correct pattern. |
| 2026-03-02 | agent_design | Remove \_GEMINI_SEARCH/CODE_TOOLS constructor injection | `_GEMINI_SEARCH_TOOLS` and `_GEMINI_CODE_TOOLS` dicts passed via `model_kwargs={"tools": ...}` in `make_researcher`/`make_builder` were removed. Web search and code execution are now handled by explicit `@tool` functions (google_search, run_command) in RESEARCHER_TOOLS/BUILDER_TOOLS. | Constructor injection bypasses LangGraph's tool-call tracing. Explicit LangChain tools are traceable, testable, and mockable. |
| 2026-03-02 | agent_design | phd_pipeline.py: no duplication, delegate to get_agent() | phd_pipeline.py formerly duplicated `_llm()`, `_load_prompt()`, `make_librarian/skeptic/synthesizer()`, all GCP constants, and Tavily fallback. All removed. Now imports `get_agent` from `agents.agents` and `memory_write` from `agents.tools` only. ~120 lines deleted. | Single source of truth: agent definitions live in agents.py registry only. phd_pipeline is an orchestration script, not an agent factory. |
| 2026-03-02 | agent_design | thread_id in LangGraph — use run_config dict, not os.environ | OLD (buggy): `os.environ["LANGCHAIN_TAGS"] = thread_id`. CORRECT: `run_config = {"configurable": {"thread_id": tid}, "run_name": "phd-research", "tags": ["phd-pipeline"], "metadata": {...}}` then `agent.invoke(input=..., config=run_config)`. `thread_id` also returned in result dict. | Setting `LANGCHAIN_TAGS` via env is a global mutation that leaks across concurrent calls; `configurable` is the LangGraph-idiomatic per-invocation mechanism. |
| 2026-03-02 | tools_and_env | \_store_fns module-level cache in tools.py | `_store_fns: tuple \ | None = None` caches `(query_similar, upsert, count)` from `memory.store` after first import. `_get_store()` returns the tuple, importing on demand. Replaces repeated `sys.path.insert` + import inside every `memory_read`/`memory_write` call. |
