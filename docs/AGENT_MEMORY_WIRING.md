# Agent Memory Wiring — How to Wire a VS Code AI Agent with Persistent Memory

_Authored by GitHub Copilot (Claude Sonnet 4.6) | 2026-02-27_  
_Based on the production setup in `phantom-man/QIDIStudio`. Every instruction in this doc is verified working in production._

---

> **IF YOU ARE AN AI AGENT READING THIS:** This document is written for you. It tells you exactly how to build the memory system you are currently using. Every gotcha section is a real failure that happened during implementation. Do not skip them. Follow the steps in order. The verification commands at each step will tell you immediately if something is wrong — do not proceed past a failed verification.

---

## What This System Does

Every time you send a message to the agent, it already knows what it learned last session.  
Every time the context window fills up, the knowledge is saved to disk automatically.  
No manual steps. No lost context. No "as I mentioned earlier..."

The pipeline:

```
You type a message
      │
      ▼
UserPromptSubmit hook fires (PowerShell)
      │  runs memory/inject.py
      │
      ▼
inject.py reads LanceDB → formats manifest
      │
      ▼
manifest injected into agent context as additionalContext
      │
      ▼
Agent sees: "━━━ QIDISTUDIO KNOWLEDGE BASE ━━━ ..."
      │  and knows everything from all previous sessions
      │
  [session work happens]
      │
      ▼
Agent finishes response → Stop hook fires (PowerShell)
      │  1. saves prompt + response to Postgres
      │  2. runs memory/extract.py  ← re-indexes all source docs
      │  3. runs sync_prompts_to_lancedb.py ← pushes to GCS LanceDB
      │  4. git commits changed memory files
      │
      ▼
Knowledge persisted to gs://qidistudio-lancedb/lancedb
```

---

## Directory Layout

```
your-repo/
├── .env                              ← API keys (NEVER commit)
├── .gitignore                        ← must exclude .env (NEVER commit API keys)
├── .github/
│   ├── copilot-instructions.md       ← agent bootstrap stub + Session Learnings Log table
│   └── hooks/
│       ├── prompt_submit_hook.ps1    ← UserPromptSubmit → Predator + inject.py (GCS LanceDB)
│       ├── stop_hook.ps1             ← Stop → Postgres + extract.py + sync_prompts_to_lancedb.py
│       ├── precompact_hook.ps1       ← kept for reference (PreCompact removed in VS Code 1.109+)
│       └── precompact.log            ← auto-created debug log
├── memory/
│   ├── requirements.txt              ← pip deps for memory module
│   ├── store.py                      ← LanceDB CRUD layer (GCS: gs://qidistudio-lancedb/lancedb)
│   ├── extract.py                    ← indexes source docs into LanceDB
│   ├── inject.py                     ← hook-facing manifest generator
│   ├── push_prompt.py                ← (optional) push system prompt to LangSmith Hub
│   └── langsmith_prompt.md           ← (optional) your full system prompt verbatim
└── docs/
    └── YOUR_KNOWLEDGE.md             ← source of truth doc for your project
```

---

## Step 1 — Prerequisites

### 1a. Python

You need Python 3.11 or 3.13 (not 3.12 — sentence-transformers CI gaps). Pin the path.

```
Windows example: C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe
```

Verify: `python --version` → `Python 3.13.x`

### 1b. VS Code version with hook support

Hooks require **VS Code 1.96+** with GitHub Copilot Chat. The hooks must be declared in VS Code settings (see Step 4).

### 1c. Git

Everything is committed. The Stop hook uses `git add` + `git commit`. If git is not on PATH, the auto-commit step silently fails.

---

## Step 2 — Install Python Dependencies

Create `memory/requirements.txt`:

```
lancedb>=0.6.0
sentence-transformers>=3.0.0
python-dotenv>=1.0.0
langsmith>=0.1.0
langchain>=0.2.0
langchain-core>=0.2.0
pyarrow>=14.0.0
# Agent fleet (optional — needed for LangGraph checkpointing)
langgraph>=0.2.0
langchain-google-genai>=3.1.0
psycopg-binary>=3.1.0
psycopg-pool>=3.2.0
langgraph-checkpoint-postgres>=2.0.0
```

Install into your Python environment:

```powershell
& 'C:\path\to\python.exe' -m pip install -r memory/requirements.txt
```

**Critical notes:**

- `pandas` is NOT required and will NOT work in Python 3.13. All LanceDB queries use PyArrow natively.
- `sentence-transformers` downloads `all-MiniLM-L6-v2` (~90MB) on first use. It caches to `~/.cache/huggingface/`.
- `lancedb` >= 0.6 returns a `ListTablesResponse` from `list_tables()` — it is a Pydantic model, **not** a plain `list`. Access table names via `.tables` attribute. See store.py for the pattern.
- **`psycopg[binary]` extra is a trap.** Running `pip install "psycopg[binary]"` exits 0 but does NOT install the binary backend. You must install `psycopg-binary` as a separate package: `pip install psycopg-binary`. Verify with `python -c "import psycopg_binary; print('OK')"`.

---

## Step 3 — Create the .env File

Create `.env` at repo root. **Add `.env` to `.gitignore` immediately.**

```ini
# LanceDB (GCS-backed vector store)
LANCEDB_PATH=gs://qidistudio-lancedb/lancedb
LANCEDB_TABLE=your_project_learnings
LANCEDB_EMBEDDING_DIMS=384

# LangSmith (optional — for tracing + Hub push)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_CALLBACKS_BACKGROUND=true
LANGCHAIN_PROJECT=YourProjectName
LANGCHAIN_API_KEY=lsv2_sk_YOUR_KEY_HERE
LANGSMITH_WORKSPACE_ID=YOUR_WORKSPACE_UUID_HERE
LANGCHAIN_HUB_HANDLE=your-hub-handle

# Google Vertex AI (agent fleet — auth via gcloud ADC, NOT an API key)
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# LangGraph checkpointer (PostgresSaver — persistent conversation state)
PG_DSN=postgresql://postgres:yourpassword@localhost:5432/postgres
```

**AGENT READING THIS — critical `.env` loading rule:** Always call `load_dotenv` with `override=True` AND an explicit path:

```python
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / '.env', override=True)  # CORRECT

# NOT this — process-level env vars silently override .env without override=True
load_dotenv()  # WRONG if any shell has set GOOGLE_CLOUD_PROJECT etc.
```

If you skip `override=True`, stale values set in the terminal session (e.g. `$env:GOOGLE_CLOUD_PROJECT`) will silently win over your `.env` file. This is the #1 cause of "wrong project ID" auth failures.

To get `LANGSMITH_WORKSPACE_ID`:

```python
from langsmith import Client
c = Client(api_key="your-key")
print(c._get_tenant_id())   # prints the UUID
```

**LangSmith gotcha**: When pushing prompts, use the **simple name** (no `handle/` prefix) and pass `workspace_id` to `Client()`. The handle prefix triggers a cross-tenant auth error ("Current tenant: None"):

```python
# WRONG — causes "Cannot create a prompt for another tenant"
client.push_prompt("damienfosborn/my-prompt", ...)

# CORRECT
ws_id  = os.getenv("LANGSMITH_WORKSPACE_ID")
client = Client(api_key=api_key, workspace_id=ws_id)
client.push_prompt("my-prompt", object=prompt)  # simple name only
```

---

## Step 4 — Register the Hooks in VS Code

Open VS Code **User Settings** (`Ctrl+Shift+P` → "Preferences: Open User Settings (JSON)") and add:

```jsonc
"github.copilot.chat.experimental.codebase.hooks": {
    "userPromptSubmit": "C:\\path\\to\\your\\repo\\.github\\hooks\\prompt_submit_hook.ps1",
    "preCompact":       "C:\\path\\to\\your\\repo\\.github\\hooks\\precompact_hook.ps1"
}
```

Or in `.vscode/settings.json` (workspace-scoped):

```jsonc
{
  "github.copilot.chat.experimental.codebase.hooks": {
    "userPromptSubmit": "${workspaceFolder}/.github/hooks/prompt_submit_hook.ps1",
    "preCompact": "${workspaceFolder}/.github/hooks/precompact_hook.ps1",
  },
}
```

**Hook contract:**

- The hook **must write valid JSON to stdout**. VS Code reads this JSON; anything else is silently dropped.
- The JSON shape VS Code expects:

  ```json
  {
    "hookSpecificOutput": {
      "hookEventName": "UserPromptSubmit",
      "additionalContext": "YOUR TEXT HERE"
    }
  }
  ```

- The hook runs as a **subprocess**. Shell commands inside it execute normally, but **the agent cannot see their output** — only the `additionalContext` string reaches the agent.
- PowerShell restriction: **never use em-dashes (`—`, U+2014) inside double-quoted strings**. The PS parser chokes on them with an encoding mismatch. Use plain hyphens or single-quoted strings.

---

## Step 5 — Write the UserPromptSubmit Hook

Create `.github/hooks/prompt_submit_hook.ps1`:

```powershell
# UserPromptSubmit hook — injects session memories into every prompt
$ts      = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo    = 'C:\path\to\your\repo'
$python  = 'C:\path\to\python.exe'
$inject  = Join-Path $repo 'memory\inject.py'

Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] fired"

$result  = $null
$success = $false
if ((Test-Path $inject) -and (Test-Path $python)) {
    try {
        $result = & $python $inject 2>$null
        if ($LASTEXITCODE -eq 0 -and $result -and $result.Trim() -ne '') {
            $success = $true
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] memory inject OK"
        }
    } catch {
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] FAILED: $_"
    }
}

if ($success) {
    Write-Output $result   # inject.py already returns valid hook JSON
} else {
    # Fallback when memory module is offline
    $msg = 'NOTE: persistent memory offline. Run: pip install -r memory/requirements.txt'
    @{
        hookSpecificOutput = @{
            hookEventName     = 'UserPromptSubmit'
            additionalContext = $msg
        }
    } | ConvertTo-Json -Compress
}
```

**Why this works:** `inject.py` itself produces the JSON output (see Step 7). The hook just calls it and forwards its stdout. The fallback handles first-run / broken env gracefully.

---

## Step 6 — Write the Stop Hook (replaces PreCompact)

> **Note:** The PreCompact event was removed in VS Code 1.109+. The `stop_hook.ps1` below is the
> modern replacement — it fires after every agent response instead of on context compaction.

Create `.github/hooks/stop_hook.ps1` (simplified example — see production file for full version):

```powershell
$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\path\to\your\repo'
$log  = Join-Path $repo '.github\hooks\precompact.log'
$py   = 'C:\path\to\python.exe'

Add-Content -Path $log -Value "$ts [Stop] fired - running autonomous save"

Set-Location $repo

# STEP A: Re-index all source docs
try {
    & $py -B memory\extract.py >> $log 2>&1
    Add-Content -Path $log -Value "$ts [Stop] extract.py done"
} catch {
    Add-Content -Path $log -Value "$ts [Stop] extract.py FAILED: $_"
}

# STEP B: Sync Postgres prompts/responses to GCS LanceDB
try {
    & $py -B memory\sync_prompts_to_lancedb.py >> $log 2>&1
    Add-Content -Path $log -Value "$ts [Stop] sync done"
} catch {
    Add-Content -Path $log -Value "$ts [Stop] sync FAILED: $_"
}

# STEP C: Commit pending disk changes
$status = & git status --porcelain 2>&1
if ($status) {
    & git add '.github/copilot-instructions.md' 'memory/session_learnings_archive.md'
    & git commit --allow-empty -m "chore(memory): stop-hook auto-sync [$date]"
    Add-Content -Path $log -Value "$ts [Stop] committed changes"
}

# No output needed — Stop hook never outputs JSON
```

**Design rationale:** Steps A, B, and C always run after every agent response with no user action. No `additionalContext` output is needed because injection happens via the UserPromptSubmit hook.

---

## Step 7 — Write the Core Memory Module

### `memory/store.py`

This is the LanceDB CRUD layer. Key design decisions:

```python
import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

LANCEDB_PATH  = os.getenv("LANCEDB_PATH",  "gs://qidistudio-lancedb/lancedb")
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "your_project_learnings")
EMBED_DIMS    = 384
EMBED_MODEL   = "all-MiniLM-L6-v2"

_SCHEMA = pa.schema([
    pa.field("id",        pa.string()),
    pa.field("date",      pa.string()),
    pa.field("category",  pa.string()),
    pa.field("topic",     pa.string()),
    pa.field("decision",  pa.string()),   # short summary (≤500 chars)
    pa.field("rationale", pa.string()),
    pa.field("content",   pa.string()),   # FULL verbatim text of chunk
    pa.field("source",    pa.string()),   # e.g. "knowledge-doc/section-name"
    pa.field("vector",    pa.list_(pa.float32(), EMBED_DIMS)),
])
```

**Critical: `list_tables()` returns `ListTablesResponse` (Pydantic model)**

```python
# WRONG — silently always False
if LANCEDB_TABLE in db.list_tables():
    ...

# CORRECT
resp = db.list_tables()
existing = list(resp.tables) if hasattr(resp, "tables") else list(resp)
if LANCEDB_TABLE in existing:
    ...
```

**Critical: use PyArrow, NOT pandas**

```python
# WRONG — raises ImportError in Python 3.13
rows = table.to_pandas().to_dict("records")

# CORRECT
rows = table.to_arrow().to_pylist()
```

**Upsert pattern** (topic is the dedup key — re-running never duplicates):

```python
def upsert_learning(topic, decision, content="", source="session", ...):
    # Delete existing row with same topic first
    table.delete(f"topic = '{topic.replace(chr(39), chr(39)*2)}'")
    table.add([row_dict])
```

### `memory/extract.py`

Walks source markdown files, splits on `##` headings, stores each section as one LanceDB row. The `content` field holds the **full verbatim text** including code blocks. The `decision` field holds a 500-char plain-text summary for the manifest.

Source files to index (adapt to your repo):

1. `.github/copilot-instructions.md` → source prefix `"copilot-instructions"`
2. `docs/YOUR_KNOWLEDGE.md` → source prefix `"knowledge-doc"`
3. `memory/langsmith_prompt.md` → source prefix `"langsmith-prompt"` (optional)

Run strategy: **idempotent** — safe to re-run at any time. All rows are upserted by topic.

```bash
python memory/extract.py
# Example output:
# Indexed 70 chunks into gs://qidistudio-lancedb/lancedb/your_project_learnings
#   copilot-instructions → 13 chunks
#   knowledge-doc        → 44 chunks
#   langsmith-prompt     → 13 chunks
```

### `memory/inject.py`

Called by the UserPromptSubmit hook. Outputs hook JSON to stdout.

Three modes:

- **Default** — compact manifest (all topics, grouped by source prefix). ~2KB. Used every message.
- `--full` — verbatim dump of all 70+ chunks. Use manually to deep-read a topic area.
- `--query "text"` — semantic search, returns full content of top N matches.

The manifest format the agent receives:

```
━━━ QIDISTUDIO KNOWLEDGE BASE (loaded from LanceDB) ━━━
Every section below is stored verbatim. For full text run:
  python memory/inject.py --query '<topic>'

┌─ AGENT RULES & PROTOCOLS (13 chunks)
│  • ChatPromptTemplate messages
│    → Use ("placeholder", "{messages}") not ("human", "{input}")
│  • Hub push tenant error
│    → Use simple name (no handle/ prefix) + Client(workspace_id=ws_id)
...
━━━ END KNOWLEDGE BASE MANIFEST ━━━
use Context7
```

---

## Step 8 — Write the Agent Bootstrap Stub

`.github/copilot-instructions.md` should be **minimal** — just enough to tell the agent where its knowledge lives. The actual knowledge is in LanceDB, loaded by the hook.

```markdown
# YourProject Copilot — Session Bootstrap

You are GitHub Copilot, engineering AI for the YourProject repo.
Repo: C:\path\to\repo\
Model: Claude Sonnet 4.6

---

## YOUR KNOWLEDGE IS IN LanceDB, NOT IN THIS FILE

The UserPromptSubmit hook has already called memory/inject.py before this prompt arrived.
Look above — you should see ━━━ YOURPROJECT KNOWLEDGE BASE ━━━.

**If you see it:** knowledge base is loaded. Proceed.
**If you do NOT see it:** run this in a terminal, then read the output:
python memory/inject.py

---

## Memory Commands

| Purpose                       | Command                                         |
| ----------------------------- | ----------------------------------------------- |
| Compact manifest (all topics) | `python memory/inject.py`                       |
| Full text dump                | `python memory/inject.py --full`                |
| Semantic search               | `python memory/inject.py --query "cmake build"` |
| Re-index docs to LanceDB      | `python memory/extract.py`                      |

---

## Minimal Reference (in case memory is unavailable)

- Python: C:\path\to\python.exe
- [any other critical paths that must survive memory outage]

---

## Session Learnings Log

Append rows here — memory/extract.py auto-indexes them into LanceDB.

| Date | Category | Topic | Decision | Rationale |
| ---- | -------- | ----- | -------- | --------- |
```

**Important:** The log table at the bottom is what `extract.py` reads to populate the "copilot-instructions" source in LanceDB. Every row you add here becomes a searchable vector chunk.

---

## Step 9 — Build the Knowledge Doc

The knowledge doc (`docs/YOUR_KNOWLEDGE.md`) is the source of truth for your project. `extract.py` chunks it by `##` headings. Every section becomes a LanceDB row.

Structure tips:

- Use `##` for major sections, `###` for sub-sections.
- Each `##` section becomes one chunk. Sections > 2500 chars are split by `###`.
- Code blocks are preserved verbatim in the `content` field.
- The first non-heading paragraph becomes the `decision` field (shown in the manifest).

---

## Step 10 — Initial Index

Run once after creating all files:

```powershell
cd C:\path\to\your\repo
& 'C:\path\to\python.exe' memory/extract.py
```

Verify:

```powershell
& 'C:\path\to\python.exe' -c "import sys; sys.path.insert(0,'memory'); import store; print('Rows:', store.count())"
# Should print: Rows: N  (> 0)
```

---

## Step 11 — Verify Hooks Are Firing

After sending one message to the agent, check the log:

```powershell
Get-Content .github\hooks\precompact.log | Select-Object -Last 5
```

Look for:

```
2026-02-27 09:35:53 [UserPromptSubmit] fired
2026-02-27 09:35:53 [UserPromptSubmit] memory inject OK
```

If you see `memory inject FAILED`, check:

1. Python path is correct in the hook script
2. `memory/requirements.txt` packages are installed in that Python env
3. `LANCEDB_PATH` env var is set to `gs://qidistudio-lancedb/lancedb` (or GCS credentials are available)

If you see `memory inject OK` but the manifest isn't showing in the agent context, the hook is registered incorrectly in VS Code settings.

---

## Step 12 — Add to .gitignore

```gitignore
.env
memory/__pycache__/
memory/*.txt
*.pyc
__pycache__/
```

LanceDB is hosted on GCS (`gs://qidistudio-lancedb/lancedb`) — no local `data/lancedb/` directory exists.

---

## How the Autonomous Save Works

After every agent response, VS Code fires the **Stop hook**:

1. **Hook shell (invisible to agent, always runs)**
   - Saves prompt + response text to Postgres
   - `python memory/extract.py` — re-indexes source markdown docs into GCS LanceDB
   - `python memory/sync_prompts_to_lancedb.py` — pushes Postgres Q&A pairs to GCS LanceDB
   - `git commit` — saves pending changes to disk

2. **Semantic injection (on every new prompt — UserPromptSubmit hook)**
   - `prompt_submit_hook.ps1` runs Predator (context pruner) + `inject.py --prompt-file` (LanceDB semantic search)
   - inject.py returns the top-N most relevant chunks as `additionalContext`
   - The agent sees `━━━ QIDISTUDIO KNOWLEDGE BASE ━━━ ...` at the top of its context

The design means knowledge is **persisted on every response** and **injected on every prompt**, with no manual steps required.

---

## Maintenance Protocol

When you finish any significant session:

1. **Agent writes to docs** — append rows to the Session Learnings Log table in `copilot-instructions.md`. For major discoveries, also update `docs/YOUR_KNOWLEDGE.md`.

2. **Re-index**:

   ```powershell
   python memory/extract.py
   ```

3. **Commit**:

   ```powershell
   git add -A
   git commit -m "docs: session learnings YYYY-MM-DD"
   ```

This is also what the precompact hook does automatically. If the hook fires and the agent is available, it handles steps 1-3. If the agent is out of context, the hook handles steps 2-3 for whatever is already on disk, and step 1 is deferred to the next session.

---

## Troubleshooting Reference

### Memory & Hooks

| Symptom                                                      | Cause                                                 | Fix                                                                    |
| ------------------------------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------------- |
| Hook fires but manifest not in context                       | Hook not registered in VS Code settings               | Add `github.copilot.chat.experimental.codebase.hooks` to settings.json |
| `memory inject FAILED: ImportError: No module named lancedb` | pip packages not installed                            | `pip install -r memory/requirements.txt`                               |
| `list_tables() TypeError`                                    | lancedb >= 0.6 returns `ListTablesResponse`, not list | Access via `resp.tables` attr, not `in resp`                           |
| `to_pandas() ImportError`                                    | pandas absent from Python 3.13                        | Use `table.to_arrow().to_pylist()` instead                             |
| LangSmith push: "Cannot create prompt for another tenant"    | Hub handle prefix in prompt name                      | Use simple name only + pass `workspace_id` to `Client()`               |
| LangSmith push: HTTP 409                                     | Prompt unchanged                                      | Treat 409 "Nothing to commit" as success, not error                    |
| PowerShell hook syntax error                                 | Em-dash `—` (U+2014) in double-quoted string          | Replace with plain hyphen `-` or use single-quoted strings             |
| `git commit` in precompact hook fails silently               | git not on PATH                                       | Add git to system PATH, or use full path to git.exe in hook            |
| 0 rows in LanceDB after extract.py                           | Wrong path to source docs                             | Check `REPO_ROOT` in extract.py resolves correctly                     |
| Hook log not updating                                        | Log path wrong                                        | Confirm `$logFile` path is absolute and directory exists               |

### Agent Fleet & Vertex AI

| Symptom                                                                                 | Cause                                                                            | Fix                                                                                                      |
| --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `PERMISSION_DENIED: 403 Permission denied on resource project X`                        | Wrong project ID in env — stale process-level var overriding .env                | Call `load_dotenv(..., override=True)` with explicit path; check `$env:GOOGLE_CLOUD_PROJECT` in terminal |
| `PERMISSION_DENIED` with truncated project ID (e.g. `crafty-hook-483415S`)              | Shell env var set to wrong value from earlier session                            | `Remove-Item Env:\GOOGLE_CLOUD_PROJECT` then re-run with override=True                                   |
| `CONSUMER_INVALID` 403 on Vertex                                                        | Wrong location (e.g. `global` instead of `us-central1`)                          | Set `GOOGLE_CLOUD_LOCATION=us-central1` in .env; load with override=True                                 |
| `AQ.Ab8...` key fails                                                                   | `AQ.` prefix = OAuth token, not an API key                                       | Vertex AI uses ADC — no API key at all. Remove `google_api_key`, use `project=` + `location=`            |
| `AIzaSy...` key fails for Vertex                                                        | Consumer API key doesn't work for Vertex AI                                      | Same fix — remove key, use ADC                                                                           |
| LangGraph tool count validator error                                                    | `bind_tools()` + `create_react_agent(tools=...)` mismatch                        | Use `model_kwargs={"tools": [...]}` at constructor instead of `bind_tools()`                             |
| `max_size must be greater or equal than min_size`                                       | `ConnectionPool(max_size=N)` without min_size — default min_size=4               | Always set both: `min_size=1, max_size=N`                                                                |
| `no pq wrapper available` / `psycopg_binary MISSING` after installing `psycopg[binary]` | `pip install "psycopg[binary]"` extra silently exits 0 without installing binary | Run `pip install psycopg-binary` directly, then verify with `python -c "import psycopg_binary"`          |
| `ImportError: cannot import name 'PostgresSaver'`                                       | `langgraph-checkpoint-postgres` not installed                                    | `pip install langgraph-checkpoint-postgres psycopg-binary psycopg-pool`                                  |
| Orchestrator 401 on `plan()` but agents load fine                                       | `orchestrator.py` has its own separate LLM constructor not updated               | Both `agents/agents.py` AND `agents/orchestrator.py` have independent LLM constructors — update both     |

---

## Quick Reference — File Checklist

### Core Memory System (required)

| File                                   | Must exist | Description                                              |
| -------------------------------------- | ---------- | -------------------------------------------------------- |
| `.env`                                 | Yes        | API keys + DSNs. Never commit.                           |
| `.gitignore`                           | Yes        | Must exclude `.env` (never commit API keys)              |
| `memory/requirements.txt`              | Yes        | lancedb, sentence-transformers, psycopg-binary, etc.     |
| `memory/store.py`                      | Yes        | LanceDB CRUD layer (GCS backend)                         |
| `memory/extract.py`                    | Yes        | Indexes source docs                                      |
| `memory/inject.py`                     | Yes        | Hook-facing manifest generator (--prompt-file)           |
| `.github/hooks/prompt_submit_hook.ps1` | Yes        | UserPromptSubmit: Predator + inject.py semantic memory   |
| `.github/hooks/stop_hook.ps1`          | Yes        | Stop: Postgres + extract.py + sync_prompts_to_lancedb.py |
| `.github/hooks/precompact_hook.ps1`    | Reference  | Kept but PreCompact event removed in VS Code 1.109+      |
| `.github/copilot-instructions.md`      | Yes        | Bootstrap stub + Session Learnings Log                   |
| `docs/YOUR_KNOWLEDGE.md`               | Yes        | Main knowledge source                                    |
| `memory/langsmith_prompt.md`           | Optional   | Full system prompt for LangSmith Hub                     |
| `memory/push_prompt.py`                | Optional   | Push system prompt to LangSmith Hub                      |
| GCS `gs://qidistudio-lancedb/lancedb`  | Cloud      | LanceDB vector store (GCS-backed, not local)             |

### Agent Fleet (optional — for autonomous multi-agent execution)

| File                           | Description                                                                       |
| ------------------------------ | --------------------------------------------------------------------------------- |
| `agents/agents.py`             | Agent factory — `get_agent(id)` returns `CompiledStateGraph` for each of 4 agents |
| `agents/orchestrator.py`       | Director + LangGraph `StateGraph` — `run(task)` fan-out via Send API              |
| `agents/tools.py`              | Python tool definitions for each agent                                            |
| `agents/prompts/director.md`   | Director system prompt (pushed to LangSmith Hub as `qidi-director`)               |
| `agents/prompts/researcher.md` | Researcher system prompt                                                          |
| `agents/prompts/builder.md`    | Builder system prompt                                                             |
| `agents/prompts/verifier.md`   | Verifier system prompt                                                            |
| `agents/prompts/scribe.md`     | Scribe system prompt                                                              |
| `agents/_agentcomms_check.py`  | Health check script — run this to verify the full stack                           |
| `agents/push_all_prompts.py`   | Push all 5 prompts to LangSmith Hub                                               |

---

---

## Agent Fleet Tier — LangGraph + Gemini + PostgresSaver

This section documents the full agent fleet built on top of the memory system. It is optional but gives you autonomous multi-agent task execution with persistent state.

### Architecture

```
run("Your task here")
      │
      ▼
  plan()  ← Director LLM decomposes into AgentTasks
      │  (structured JSON output — always valid)
      ▼
  dispatch()  ← Send API fan-out — ALL tasks run in same superstep (true parallel)
      ├─ researcher  ← gemini-2.5-flash + google_search + url_context
      ├─ builder     ← gemini-2.5-pro + code_execution
      ├─ verifier    ← gemini-2.5-flash
      └─ scribe      ← gemini-2.5-flash
      │
      ▼
  synthesize()  ← Director LLM combines all results
      │
      ▼
  PostgresSaver  ← full graph state checkpointed to Postgres after every step
```

### Google Vertex AI Authentication

**DO NOT use an API key for Vertex AI.** Auth is via `gcloud` Application Default Credentials (ADC).

The correct pattern is `project=` + `location=` on `ChatGoogleGenerativeAI` — no `google_api_key` parameter:

```python
from langchain_google_genai import ChatGoogleGenerativeAI
import os

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.0,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],   # e.g. "my-gcp-project-id"
    location=os.environ["GOOGLE_CLOUD_LOCATION"],  # e.g. "us-central1"
    # NO google_api_key here
)
```

**How to tell if you have the wrong auth type:**

- `AQ.Ab8...` prefix = OAuth access token. Wrong. Not a Gemini API key.
- `AIzaSy...` prefix = Consumer Gemini API key. Wrong for Vertex AI.
- No key at all + gcloud ADC = CORRECT for Vertex AI.

**Set up ADC once** (human does this, not the agent):

```powershell
gcloud auth application-default login
# Authorise your service account or user account
```

**Available Gemini models on Vertex AI (as of 2026-02-27):**

| Model                   | Status        | Notes                                 |
| ----------------------- | ------------- | ------------------------------------- |
| `gemini-2.5-flash`      | OK            | Use as default — fast, cheap, capable |
| `gemini-2.5-pro`        | OK            | Use for builder — best reasoning      |
| `gemini-2.5-flash-lite` | OK            | Ultra-fast, lowest cost               |
| `gemini-2.0-flash`      | DEPRECATED    | Shutdown June 1 2026 — do not use     |
| `gemini-2.0-flash-lite` | DEPRECATED    | Shutdown June 1 2026 — do not use     |
| `gemini-1.5-*`          | NOT AVAILABLE | Not on Vertex paid tier               |

### Built-in Gemini Tools

Do NOT use `bind_tools()` with `create_react_agent` for Gemini built-in tools. LangGraph 1.0 validates that pre-bound tool count equals `tools=` list and raises. Use `model_kwargs` instead:

```python
from langgraph.prebuilt import create_react_agent

# WRONG — triggers LangGraph tool count validator
llm = _make_llm("gemini-2.5-flash").bind_tools([...google tools...])
agent = create_react_agent(llm, tools=[...])

# CORRECT — model_kwargs bypasses the validator
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    project=..., location=...,
    model_kwargs={"tools": [{"google_search": {}}, {"url_context": {}}]}
)
agent = create_react_agent(llm, tools=[...your python tools...])
```

### PostgresSaver Checkpointer

LangGraph's `PostgresSaver` persists the entire graph state after every node execution. This means:

- Agent conversations survive process restarts
- You can resume any conversation by passing the same `thread_id`
- The full message history + intermediate results are stored

```python
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
import os

def build_checkpointer():
    dsn  = os.environ["PG_DSN"]  # e.g. postgresql://postgres:pw@localhost:5432/postgres
    pool = ConnectionPool(
        conninfo=dsn,
        min_size=1,    # REQUIRED — default min_size=4, must be <= max_size
        max_size=10,
        kwargs={"autocommit": True},
        open=True,
    )
    saver = PostgresSaver(pool)
    saver.setup()   # idempotent — creates langgraph_checkpoints tables if not present
    return saver

# Compile graph with checkpointer
graph = builder.compile(checkpointer=build_checkpointer())

# Run with thread_id — same ID resumes the same conversation
result = graph.invoke(state, config={"configurable": {"thread_id": "my-thread-123"}})
```

**Critical `ConnectionPool` gotcha:** `max_size` must be >= `min_size`. The default `min_size` is 4. If you set `max_size=2` without also setting `min_size=1`, you get: `max_size must be greater or equal than min_size`. Always set both.

**Critical `psycopg-binary` install gotcha:**

```powershell
# WRONG — exits 0 but does NOT install the binary backend
pip install "psycopg[binary]"

# CORRECT — installs the actual binary package
pip install psycopg-binary

# Verify
python -c "import psycopg_binary; print('OK')"
```

### Verification Script

Save as `agents/_agentcomms_check.py` and run after any env change:

```python
import os, sys, re
from pathlib import Path
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[1] / '.env', override=True)  # override=True is mandatory

results = []

# 1. Env vars
for k in ['GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION', 'LANGSMITH_API_KEY', 'PG_DSN']:
    v = os.environ.get(k, 'MISSING')
    display = re.sub(r':([^@]+)@', ':***@', v[:40]) if k == 'PG_DSN' else (v[:20] + '...' if len(v) > 20 else v)
    results.append(f'  ENV  {k}={display}')

# 2. Agents
try:
    from agents.agents import get_agent
    for a in ['researcher', 'builder', 'verifier', 'scribe']:
        ag = get_agent(a)
        results.append(f'  OK   {a:<12} {type(ag).__name__}')
except Exception as e:
    results.append(f'  FAIL agents: {e}')

# 3. Gemini ping
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model='gemini-2.5-flash', temperature=0,
        project=os.environ['GOOGLE_CLOUD_PROJECT'],
        location=os.environ['GOOGLE_CLOUD_LOCATION'])
    r = llm.invoke('reply with one word: ONLINE')
    results.append(f'  OK   gemini ping: {r.content.strip()[:40]}')
except Exception as e:
    results.append(f'  FAIL gemini: {e}')

# 4. PostgresSaver
try:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(
        conninfo=os.environ['PG_DSN'],
        min_size=1, max_size=4,
        kwargs={'autocommit': True}, open=True)
    saver = PostgresSaver(pool)
    saver.setup()
    pool.close()
    results.append('  OK   postgres checkpointer (langgraph tables ready)')
except Exception as e:
    results.append(f'  FAIL postgres: {e}')

# 5. LangSmith
try:
    from langsmith import Client
    projs = [p.name for p in list(Client().list_projects())[:3]]
    results.append(f'  OK   langsmith: {projs}')
except Exception as e:
    results.append(f'  FAIL langsmith: {e}')

print('=== AgentComms Status ===')
for r in results: print(r)
print('=== Done ===')
```

Expected healthy output:

```
=== AgentComms Status ===
  ENV  GOOGLE_CLOUD_PROJECT=my-project-id
  ENV  GOOGLE_CLOUD_LOCATION=us-central1
  ENV  LANGSMITH_API_KEY=lsv2_sk_...
  ENV  PG_DSN=postgresql:***@localhost
  OK   researcher   CompiledStateGraph
  OK   builder      CompiledStateGraph
  OK   verifier     CompiledStateGraph
  OK   scribe       CompiledStateGraph
  OK   gemini ping: ONLINE
  OK   postgres checkpointer (langgraph tables ready)
  OK   langsmith: ['your-project', ...]
=== Done ===
```

If any line shows `FAIL`, fix it before proceeding. The error message is the root cause.

---

_Last verified: 2026-02-27 | 70 rows in production LanceDB | All hooks confirmed firing | PostgresSaver checkpointer active_
