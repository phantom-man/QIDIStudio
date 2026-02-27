# QIDIStudio Copilot — Session Bootstrap

You are **GitHub Copilot**, engineering AI for the **QIDIStudio** fork.
Repo  : `C:\Users\User\source\repos\QIDIStudio\`  
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

| Purpose | Command |
|---------|---------|
| Compact manifest (all topics) | `memory_env\Scripts\python.exe memory/inject.py` |
| Full text dump (everything verbatim) | `memory_env\Scripts\python.exe memory/inject.py --full` |
| Semantic search | `memory_env\Scripts\python.exe memory/inject.py --query "cmake build"` |
| Re-index docs to LanceDB | `memory_env\Scripts\python.exe memory/extract.py` |
| Push prompt to LangSmith Hub | `memory_env\Scripts\python.exe memory/push_prompt.py` |
| Re-install deps | `.\memory_env\Scripts\python.exe -m pip install -r memory\requirements.txt` |

---

## Minimal Reference (in case memory is unavailable)

- **Build source**: `C:\QIDISrc\QIDIStudio\build\`  
- **Install dir** : `C:\QIDISrc\QIDIStudio\install_dir\`  
- **bpy script**  : `resources\scripts\apply_texture_bpy.py`  
- **Blender**     : `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`  
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

| Date | Category | Topic | Decision | Rationale |
|------|----------|-------|----------|-----------|
| 2026-02-27 | PowerShell | Em-dash in double-quoted strings | Replace `—` (U+2014) with plain `-` everywhere in .ps1 hooks | PS parser chokes on Unicode dash in double-quoted strings — encoding mismatch |
| 2026-02-27 | LangSmith | Hub push tenant error | Use simple name `"qidistudio-memory-agent"` (no `handle/` prefix) + `Client(api_key=k, workspace_id=ws_id)` | Handle prefix triggers cross-tenant auth; workspace_id resolves owner from env |
| 2026-02-27 | LangSmith | Hub 409 response | Treat "409 Nothing to commit" as success, not error | LangSmith returns 409 when prompt is identical to what's already on Hub |
| 2026-02-27 | LangSmith | ChatPromptTemplate messages | Use `("placeholder", "{messages}")` not `("human", "{input}")` | deepagents hub_manager.py pattern; placeholder accepts full message list |
| 2026-02-27 | LanceDB | list_tables() return type | `db.list_tables()` returns `ListTablesResponse` (Pydantic model) — access via `.tables` attr | Not a plain list; `in` check on it fails silently, causing table to be re-created |
| 2026-02-27 | LanceDB | PyArrow vs pandas | Use `tbl.to_arrow()` + PyArrow scanner for `get_all()`/`get_recent()`/`count()` | pandas not installed in Python 3.13 env; `to_pandas()` raises ImportError |
| 2026-02-27 | Memory | inject.py confirmed working | Hook log shows "memory inject OK" since commit `ddcde11`; 58 chunks loaded at session start | All source docs chunked verbatim; grouped by source prefix in manifest output |
| 2026-02-27 | Memory | precompact hook limitation | Hook can only inject JSON instruction to agent via stdout; agent must do file writes | Shell commands in precompact hook body are invisible to agent — only `additionalContext` JSON matters |
| 2026-02-27 | LangSmith | push_prompt.py python env | Use `memory_env\Scripts\python.exe memory/push_prompt.py` — universal memory venv; NOT deepagents venv or Python 3.13 | memory_env is the single canonical venv for all LangSmith/LanceDB memory commands |
| 2026-02-27 | LangSmith | Remote prompt confirmed live | `qidistudio-memory-agent` pushed successfully, org `073a725b-0613-4b53-9391-56f740a3e7ea`, rev `ace15015` | push_out.txt was stale (showed old tenant error); actual push was already fixed and working |
| 2026-02-27 | tools_and_env | Universal memory venv | Created `memory_env\` at repo root with Python 3.13; install: `memory_env\Scripts\pip install -r memory\requirements.txt` | Replaces dependency on deepagents venv for all langsmith/lancedb/sentence-transformers operations |
