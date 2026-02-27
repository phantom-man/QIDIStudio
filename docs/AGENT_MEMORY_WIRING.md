# Agent Memory Wiring — How to Wire a VS Code AI Agent with Persistent Memory

_Authored by GitHub Copilot (Claude Sonnet 4.6) | 2026-02-27_  
_Based on the production setup in `phantom-man/QIDIStudio`. Every instruction in this doc is verified working._

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
Context window fills → PreCompact hook fires (PowerShell)
      │  1. runs memory/extract.py  ← re-indexes all source docs
      │  2. git add -A && git commit ← saves to disk
      │  3. tells agent: "write any NEW learnings you know"
      │
      ▼
Agent appends new rows to docs → hook was already indexing on next trigger
```

---

## Directory Layout

```
your-repo/
├── .env                              ← API keys (NEVER commit)
├── .gitignore                        ← must exclude .env and data/lancedb/
├── .github/
│   ├── copilot-instructions.md       ← agent bootstrap stub + Session Learnings Log table
│   └── hooks/
│       ├── prompt_submit_hook.ps1    ← UserPromptSubmit → calls inject.py
│       ├── precompact_hook.ps1       ← PreCompact → runs extract.py + git commit
│       └── precompact.log            ← auto-created debug log
├── memory/
│   ├── requirements.txt              ← pip deps for memory module
│   ├── store.py                      ← LanceDB CRUD layer
│   ├── extract.py                    ← indexes source docs into LanceDB
│   ├── inject.py                     ← hook-facing manifest generator
│   ├── push_prompt.py                ← (optional) push system prompt to LangSmith Hub
│   └── langsmith_prompt.md           ← (optional) your full system prompt verbatim
├── data/
│   └── lancedb/                      ← auto-created vector store (gitignore this)
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

Everything is committed. The precompact hook uses `git add -A && git commit`. If git is not on PATH, the autonomous save step silently fails.

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
```

Install into your Python environment:

```powershell
& 'C:\path\to\python.exe' -m pip install -r memory/requirements.txt
```

**Critical notes:**
- `pandas` is NOT required and will NOT work in Python 3.13. All LanceDB queries use PyArrow natively.
- `sentence-transformers` downloads `all-MiniLM-L6-v2` (~90MB) on first use. It caches to `~/.cache/huggingface/`.
- `lancedb` >= 0.6 returns a `ListTablesResponse` from `list_tables()` — it is a Pydantic model, **not** a plain `list`. Access table names via `.tables` attribute. See store.py for the pattern.

---

## Step 3 — Create the .env File

Create `.env` at repo root. **Add `.env` to `.gitignore` immediately.**

```ini
# LanceDB (local vector store)
LANCEDB_PATH=data/lancedb
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
```

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
        "preCompact":       "${workspaceFolder}/.github/hooks/precompact_hook.ps1"
    }
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

## Step 6 — Write the PreCompact Hook

Create `.github/hooks/precompact_hook.ps1`:

```powershell
$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\path\to\your\repo'
$log  = Join-Path $repo '.github\hooks\precompact.log'
$py   = 'C:\path\to\python.exe'

Add-Content -Path $log -Value "$ts [PreCompact] fired - running autonomous save"

Set-Location $repo

# STEP A: Re-index all source docs (runs regardless of agent state)
try {
    $result = & $py memory\extract.py 2>&1
    Add-Content -Path $log -Value "$ts [PreCompact] extract.py: $($result[-1])"
} catch {
    Add-Content -Path $log -Value "$ts [PreCompact] extract.py FAILED: $_"
}

# STEP B: Commit pending disk changes (runs regardless of agent state)
$status = & git status --porcelain 2>&1
if ($status) {
    & git add -A
    & git commit --allow-empty -m "docs: pre-compact auto-save [$date]"
    Add-Content -Path $log -Value "$ts [PreCompact] committed pending changes"
} else {
    Add-Content -Path $log -Value "$ts [PreCompact] nothing to commit"
}

# STEP C: Tell the agent to write any NEW learnings it knows from this conversation
@{
    hookSpecificOutput = @{
        hookEventName     = "PreCompact"
        additionalContext = @"
IMPORTANT: Context is about to be compacted. The precompact hook has already run memory\extract.py and committed any pending file changes. Your job is ONE thing only:

WRITE NEW LEARNINGS: Read this conversation. Identify every new convention, gotcha, bug fix, confirmed value, or architectural decision that is NOT yet in the Session Learnings Log in .github/copilot-instructions.md. Append those rows now. For major discoveries also update your main knowledge doc.

Be specific - real values, real function names, real filenames. Not vague summaries.

After writing, run:
  Set-Location $repo
  & '$py' memory\extract.py
  git add -A
  git commit --allow-empty -m 'docs: pre-compact session learnings [$date]'
"@
    }
} | ConvertTo-Json -Compress
```

**Design rationale:** Steps A and B run as shell commands — they always execute, even if the agent is out of context budget. The agent only needs to handle Step C (writing NEW learnings not yet on disk), which is cheap file edits only.

---

## Step 7 — Write the Core Memory Module

### `memory/store.py`

This is the LanceDB CRUD layer. Key design decisions:

```python
import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

LANCEDB_PATH  = os.getenv("LANCEDB_PATH",  "data/lancedb")
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
# Indexed 70 chunks into data/lancedb/your_project_learnings
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

| Purpose | Command |
|---------|---------|
| Compact manifest (all topics) | `python memory/inject.py` |
| Full text dump | `python memory/inject.py --full` |
| Semantic search | `python memory/inject.py --query "cmake build"` |
| Re-index docs to LanceDB | `python memory/extract.py` |

---

## Minimal Reference (in case memory is unavailable)

- Python: C:\path\to\python.exe
- [any other critical paths that must survive memory outage]

---

## Session Learnings Log

Append rows here — memory/extract.py auto-indexes them into LanceDB.

| Date | Category | Topic | Decision | Rationale |
|------|----------|-------|----------|-----------|
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
3. `data/lancedb/` directory exists and is writable

If you see `memory inject OK` but the manifest isn't showing in the agent context, the hook is registered incorrectly in VS Code settings.

---

## Step 12 — Add to .gitignore

```gitignore
.env
data/lancedb/
memory/__pycache__/
memory/*.txt
*.pyc
__pycache__/
```

Commit `data/lancedb/` to `.gitignore` so the vector files don't bloat the repo. The LanceDB store is always reconstructed from the source markdown files by `extract.py`.

---

## How the Autonomous Save Works

When the context window fills, VS Code fires the PreCompact hook **before** truncating:

1. **Hook shell (invisible to agent, always runs)**
   - `python memory/extract.py` — re-indexes whatever markdown files are on disk
   - `git add -A && git commit` — saves everything, including any edits the agent made this session

2. **`additionalContext` (visible to agent, injected into compaction prompt)**
   - "The hook already ran extract.py and committed. Your one job: write any NEW learnings from this conversation that aren't on disk yet."

The design means even if the agent completely runs out of tokens and can't respond, the disk state is still saved. The agent only needs to handle the case where it *knows* something that isn't written down yet.

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

| Symptom | Cause | Fix |
|---------|-------|-----|
| Hook fires but manifest not in context | Hook not registered in VS Code settings | Add `github.copilot.chat.experimental.codebase.hooks` to settings.json |
| `memory inject FAILED: ImportError: No module named lancedb` | pip packages not installed | `python -m pip install -r memory/requirements.txt` |
| `list_tables() TypeError` | lancedb >= 0.6 returns `ListTablesResponse`, not list | Check via `resp.tables` attr, not direct `in` check |
| `to_pandas() ImportError` | pandas absent from Python 3.13 | Use `table.to_arrow().to_pylist()` instead |
| LangSmith push: "Cannot create prompt for another tenant" | Hub handle prefix in prompt name | Use simple name only + pass `workspace_id` to `Client()` |
| LangSmith push: HTTP 409 | Prompt unchanged | Treat 409 "Nothing to commit" as success, not error |
| PowerShell hook syntax error | Em-dash `—` (U+2014) in double-quoted string | Replace with plain hyphen `-` or use single-quoted strings |
| `git commit` in precompact hook fails silently | git not on PATH | Add git to system PATH, or use full path to git.exe in hook |
| 0 rows in LanceDB after extract.py | Wrong path to source docs | Check `REPO_ROOT` in extract.py resolves correctly |
| Hook log not updating | Log path wrong | Confirm `$logFile` path is absolute and directory exists |

---

## Quick Reference — File Checklist

| File | Must exist | Description |
|------|-----------|-------------|
| `.env` | Yes | API keys. Never commit. |
| `.gitignore` | Yes | Must exclude `.env` and `data/lancedb/` |
| `memory/requirements.txt` | Yes | lancedb, sentence-transformers, etc. |
| `memory/store.py` | Yes | LanceDB CRUD layer |
| `memory/extract.py` | Yes | Indexes source docs |
| `memory/inject.py` | Yes | Hook-facing manifest generator |
| `.github/hooks/prompt_submit_hook.ps1` | Yes | Calls inject.py on every message |
| `.github/hooks/precompact_hook.ps1` | Yes | Autonomous save on context full |
| `.github/copilot-instructions.md` | Yes | Bootstrap stub + Session Learnings Log |
| `docs/YOUR_KNOWLEDGE.md` | Yes | Main knowledge source |
| `memory/langsmith_prompt.md` | Optional | Full system prompt for LangSmith Hub |
| `memory/push_prompt.py` | Optional | Push system prompt to LangSmith Hub |
| `data/lancedb/` | Auto-created | Vector store (gitignored) |

---

_Last verified: 2026-02-27 | 70 rows in production LanceDB | All hooks confirmed firing_
