# Agent Almanac

> **One-sentence abstract** — A complete, PhD-grade onboarding guide that equips any AI
> coding agent — in any repository — to adopt the QIDIStudio LangChain/LangSmith
> technology stack, install every required dependency, configure VS Code hooks and
> protocols, run repo-agnostic quality pipelines (hallucination validation, memory
> indexing, 3D texture generation), and operate as a first-class participant in a
> continuously-learning, self-auditing agentic ecosystem.

---

## Table of Contents

1. [Who This Document Is For](#1-who-this-document-is-for)
2. [Technology Stack Overview](#2-technology-stack-overview)
3. [Pre-flight Checklist](#3-pre-flight-checklist)
4. [Environment Variables Template (.env)](#4-environment-variables-template-env)
5. [Python Virtual Environments](#5-python-virtual-environments)
6. [Complete Install Manifest](#6-complete-install-manifest)
7. [VS Code Configuration](#7-vs-code-configuration)
8. [Hooks Setup — The Protocol Enforcement Layer](#8-hooks-setup--the-protocol-enforcement-layer)
9. [Prompt Execution Protocol (Phase 0)](#9-prompt-execution-protocol-phase-0)
10. [Session Log Protocol (PhD Standard)](#10-session-log-protocol-phd-standard)
11. [Startup Health Check Pipeline](#11-startup-health-check-pipeline)
12. [Knowledge Base & Memory System](#12-knowledge-base--memory-system)
13. [Knowledge Validation & Hallucination Repair Pipeline](#13-knowledge-validation--hallucination-repair-pipeline)
14. [Agent Fleet Architecture](#14-agent-fleet-architecture)
15. [Dev Fleet (Coder/Tester) Protocol](#15-dev-fleet-codertester-protocol)
16. [Texture Generator (Blender/bpy Bonus Pipeline)](#16-texture-generator-blenderbpy-bonus-pipeline)
17. [Knowledge Repository Links](#17-knowledge-repository-links)
18. [Quick Reference Card](#18-quick-reference-card)

---

## 1. Who This Document Is For

This almanac targets **AI coding agents** (LLMs embedded in VS Code, Codex, Cursor,
Claude Code, or any similar agentic IDE) that are:

- Being deployed into a **new repository** and need to bootstrap in < 30 minutes
- Seeking compliance with the **highest-tier LangChain/LangSmith observability stack**
- Wanting a **battle-tested protocol** for session logging, hallucination rejection,
  and continuous knowledge accumulation — originally developed for QIDIStudio, a
  production-grade C++ 3D printing slicer fork

The patterns here are **repo-agnostic**. Adapt the paths and project names; keep the
architecture.

---

## 2. Technology Stack Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PRODUCTION STACK                                  │
├─── LLM Layer ───────────────────────────────────────────────────────────┤
│  Google Gemini 2.5 Pro / 2.5 Flash (primary)                            │
│  langchain-google-genai  ←→  google-genai v1.65+                        │
├─── Agent Orchestration ─────────────────────────────────────────────────┤
│  LangGraph 0.2+ (supervisor pattern + Send API for true parallelism)     │
│  LangSmith (universal trace sink — EVERY run traced)                     │
│  langgraph-checkpoint-postgres (state persistence, resumable runs)       │
├─── Memory / Knowledge ──────────────────────────────────────────────────┤
│  LanceDB 0.29+ on GCS  (semantic search, vector store)                  │
│  sentence-transformers 3.0+ (local embeddings, no API cost)             │
│  PostgreSQL 15+ (LangGraph checkpoints + run_store + prompt pairs)       │
├─── External Services ───────────────────────────────────────────────────┤
│  LangSmith Hub (versioned prompts)                                       │
│  Google Cloud (Vertex AI ADC, Firestore, GCS, BigQuery)                 │
│  HuggingFace (sentence-transformers model downloads)                     │
│  GitHub API (slicer profile harvester, knowledge graph)                  │
├─── IDE & Hooks ─────────────────────────────────────────────────────────┤
│  VS Code Copilot with chatHooks (PreToolUse / SessionStart / Stop)       │
│  Desktop Commander MCP (file writes, process management, search)        │
│  Context7 MCP (live library documentation lookup)                       │
│  Firecrawl MCP (web research + structured extraction)                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why LangGraph over raw LangChain?

LangGraph provides typed state machines with built-in checkpointing, enabling:
- **Resumable runs** — crash mid-graph, resume from last checkpoint
- **Parallel agent dispatch** — `Send` API triggers all nodes in a single superstep
- **Human-in-the-loop** — interrupt/resume at any node boundary
- **Full reproducibility** — every state transition stored in PostgreSQL

### Why LangSmith?

Every `langchain` / `langgraph` run is traced automatically when `LANGSMITH_TRACING=true`.
This gives you:
- Full token cost breakdown per agent / node
- Input/output diffs for every LLM call
- Dataset creation from production runs (for fine-tuning)
- Feedback annotation for RLHF pipelines

**Reference:** [LangSmith Docs](https://docs.smith.langchain.com) ·
[LangGraph Docs](https://langchain-ai.github.io/langgraph/)

---

## 3. Pre-flight Checklist

Run this checklist in order before touching any code.

```
[ ] 3.1  Python 3.11+ installed and on PATH
[ ] 3.2  Python 3.13 installed at a known absolute path (recommended for memory_env)
[ ] 3.3  PostgreSQL 15+ running locally or accessible via connection string
[ ] 3.4  Google Cloud SDK installed + Application Default Credentials configured:
           gcloud auth application-default login
[ ] 3.5  Blender 4.0+ installed (for texture pipeline only)
[ ] 3.6  Git repo initialised with .github/hooks/ directory
[ ] 3.7  .env file created from §4 template and all keys populated
[ ] 3.8  memory_env virtual environment created (see §5)
[ ] 3.9  All packages installed (see §6)
[ ] 3.10 VS Code settings updated (see §7)
[ ] 3.11 Hook scripts copied to .github/hooks/ (see §8)
[ ] 3.12 LangSmith projects created: <yourproject>-agents, <yourproject>-dev-fleet
[ ] 3.13 LanceDB table initialised: memory_env\Scripts\python.exe memory/extract.py
[ ] 3.14 Startup health check passes: memory_env\Scripts\python.exe -B scripts/startup_check.py
```

---

## 4. Environment Variables Template (.env)

Create this file at your repository root. **Never commit it to git** — add `.env` to
`.gitignore` immediately.

```dotenv
# ─── LangSmith / LangChain Observability ─────────────────────────────────────
# Get from: https://smith.langchain.com → Settings → API Keys
LANGSMITH_API_KEY=
LANGCHAIN_API_KEY=                     # Same value as LANGSMITH_API_KEY
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=<yourproject>-agents  # Default project for traces

# ─── Google Cloud / Gemini ────────────────────────────────────────────────────
# Vertex AI (authenticated via ADC — run: gcloud auth application-default login)
GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
GOOGLE_CLOUD_LOCATION=us-central1

# Direct Gemini API key (fallback when ADC not available)
# Get from: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY=

# ─── PostgreSQL ───────────────────────────────────────────────────────────────
# LangGraph checkpoints + run_store + prompt/response pairs
# Format: postgresql://user:password@host:port/database
PG_DSN=postgresql://postgres:postgres@localhost:5432/langchain

# ─── LanceDB Vector Store ─────────────────────────────────────────────────────
# Local path (development): ./lancedb
# GCS production:           gs://<your-bucket>/lancedb
LANCEDB_PATH=./lancedb

# ─── HuggingFace ──────────────────────────────────────────────────────────────
# Required to download sentence-transformers models
# Get from: https://huggingface.co/settings/tokens
HF_TOKEN=

# ─── GitHub ───────────────────────────────────────────────────────────────────
# Required for slicer harvester + knowledge graph API calls
# Get from: https://github.com/settings/tokens
GITHUB_TOKEN=

# ─── (Optional) Tavily — real-time web search grounding ──────────────────────
# Get from: https://app.tavily.com
TAVILY_API_KEY=
```

### Validation

After populating:
```powershell
# Quick check that all 11 required keys are non-empty
Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=.+$' } | Measure-Object
# Expect: Count = 11 or more
```

---

## 5. Python Virtual Environments

The stack uses **three isolated virtual environments** with distinct responsibilities.

### 5.1 memory_env — Universal Agent Venv (PRIMARY)

All agent fleet, LangGraph, LanceDB, and memory operations use this venv.
**Python 3.13 recommended** (f-strings, type narrowing, toml stdlib).

```powershell
# Create
C:\Users\...\Python313\python.exe -m venv memory_env

# Activate (Windows PowerShell)
memory_env\Scripts\Activate.ps1

# Install
memory_env\Scripts\python.exe -m pip install -r memory\requirements.txt
```

### 5.2 .venv — Project Source Venv

Used for any project-specific scripts that must match the project's own dependency
graph (e.g. FastAPI apps, Django projects, slicer-specific tooling).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
.venv\Scripts\pip install -r requirements.txt
```

### 5.3 bpy_env — Blender Python (TEXTURE ONLY)

The `bpy` pip package and Blender's embedded Python are ABI-incompatible with other
packages. Keep this isolated.

```powershell
python -m venv bpy_env
bpy_env\Scripts\pip install bpy
# Note: apply_texture_bpy.py MUST be run via blender.exe --background --python
# (the bpy pip package does NOT support the Displace modifier pipeline)
```

---

## 6. Complete Install Manifest

### 6.1 memory_env requirements (memory/requirements.txt)

```pip-requirements
# ─── Core LangChain / LangGraph ──────────────────────────────────────────────
langchain>=0.2.0
langchain-core>=0.2.0
langchain-google-genai>=4.2.0      # ChatGoogleGenerativeAI + Vertex AI ADC
langchain-community>=0.2.0          # Tool loaders, document loaders
langchain-openai>=0.1.0             # Optional: GPT fallback
langgraph>=0.2.0                    # Stateful agent graphs
langgraph-checkpoint-postgres>=2.0.0  # PostgreSQL state persistence
langsmith>=0.1.0                    # Tracing + evaluation

# ─── Google genai SDK (direct, not LangChain wrapper) ────────────────────────
google-genai>=1.65.0                # google.genai.Client (Gemini API v1 stable)

# ─── Vector Store & Memory ───────────────────────────────────────────────────
lancedb>=0.29.2                     # Vector store (local or GCS)
sentence-transformers>=3.0.0        # Local embeddings (all-MiniLM-L6-v2)
pyarrow>=14.0.0                     # Columnar storage for LanceDB

# ─── PostgreSQL Drivers ───────────────────────────────────────────────────────
psycopg2-binary>=2.9.0              # psycopg2 (sync)
psycopg[binary]>=3.1.0              # psycopg3 (async-ready)
psycopg-pool>=3.2.0                 # Connection pooling

# ─── ML / Neural ─────────────────────────────────────────────────────────────
torch>=2.2.0                        # PyTorch (CPU build — see note below)
torchvision>=0.17.0
# For GPU: pip install torch --index-url https://download.pytorch.org/whl/cu121

# ─── Google Cloud ─────────────────────────────────────────────────────────────
google-cloud-firestore>=2.16.0
google-cloud-storage>=2.16.0
google-cloud-bigquery>=3.0.0

# ─── Research & Validation ───────────────────────────────────────────────────
arxiv>=2.1.0                        # arXiv API client
requests>=2.31.0                    # HTTP (CrossRef, PubMed, NIST, Wikipedia)
python-docx>=1.1.0                  # DOCX parsing for knowledge validator
pdfplumber>=0.10.0                  # PDF text extraction
paperscraper>=0.2.8                 # Multi-source academic paper fetching

# ─── Web Search Grounding ─────────────────────────────────────────────────────
tavily-python>=0.3.0                # Tavily real-time web search

# ─── Agent Evaluation ────────────────────────────────────────────────────────
langchain-agentevals>=0.0.4         # LLM-as-judge trajectory evaluation

# ─── Utilities ────────────────────────────────────────────────────────────────
python-dotenv>=1.0.0                # .env loading
numpy-stl>=3.1.0                    # STL vertex extraction
trimesh>=4.0.0                      # Mesh processing
```

### 6.2 One-line install for memory_env

```powershell
memory_env\Scripts\python.exe -m pip install `
    langchain langchain-core langchain-google-genai>=4.2.0 `
    langchain-community langchain-openai `
    langgraph>=0.2.0 langgraph-checkpoint-postgres>=2.0.0 `
    langsmith google-genai>=1.65.0 `
    lancedb>=0.29.2 sentence-transformers pyarrow `
    psycopg2-binary "psycopg[binary]" psycopg-pool `
    google-cloud-firestore google-cloud-storage google-cloud-bigquery `
    arxiv requests python-docx pdfplumber `
    tavily-python python-dotenv numpy-stl trimesh
```

### 6.3 Additional tools (global or project-scoped)

```powershell
# Desktop Commander MCP (file management, process control, search)
# Install via VS Code: Ctrl+Shift+P → "MCP: Add Server"
# Or directly: npx @wonderwhy-er/desktop-commander@latest

# Context7 MCP (live library docs injection)
# npx @upstash/context7-mcp@latest

# Firecrawl MCP (web crawl + extraction)
# npx firecrawl-mcp

# GitHub MCP (PR + issue management)
# npx @github/mcp@latest

# VS Code extensions (install from Marketplace):
#   ms-python.python          — Python language support
#   ms-python.vscode-pylance  — Type checking
#   GitHub.copilot            — AI copilot
#   GitHub.copilot-chat       — Chat interface
```

---

## 7. VS Code Configuration

### 7.1 User Settings (AppData/Roaming/Code/User/settings.json)

Add these to silence all approval dialogs and allow the agent to operate autonomously:

```json
{
  "chat.tools.autoApprove": true,
  "chat.agent.confirmation": false,
  "github.copilot.chat.edits.autoAccept": true
}
```

### 7.2 MCP Server Registration (AppData/Roaming/Code/User/mcp.json)

```json
{
  "servers": {
    "io.github.upstash/context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp@latest"],
      "autoApprove": true
    },
    "io.github.wonderwhy-er/desktop-commander": {
      "command": "npx",
      "args": ["-y", "@wonderwhy-er/desktop-commander@latest"],
      "autoApprove": true
    },
    "firecrawl/firecrawl-mcp-server": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": { "FIRECRAWL_API_KEY": "" },
      "autoApprove": true
    },
    "io.github.github/github-mcp-server": {
      "command": "npx",
      "args": ["-y", "@github/mcp@latest"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "" },
      "autoApprove": true
    }
  }
}
```

### 7.3 Workspace Settings (.vscode/settings.json)

```json
{
  "chat.tools.autoApprove": true,
  "chat.agent.confirmation": false,
  "github.copilot.chat.edits.autoAccept": true,
  "python.defaultInterpreterPath": "${workspaceFolder}/memory_env/Scripts/python.exe",
  "python.analysis.extraPaths": ["${workspaceFolder}"],
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true
  }
}
```

---

## 8. Hooks Setup — The Protocol Enforcement Layer

VS Code's `chatHooks` system fires PowerShell scripts at four lifecycle events.
These hooks implement **automatic memory injection, protocol enforcement, and
knowledge persistence** — without any deliberate invocation from the agent.

### 8.1 Directory structure

```
.github/
  hooks/
    session_start_hook.ps1    ← Fires once per session; injects knowledge base
    pretool_inject_hook.ps1   ← Fires before EVERY tool call; enforces log protocol
    prompt_submit_hook.ps1    ← Fires on user prompt submit; semantic memory search
    stop_hook.ps1             ← Fires when agent finishes; persists to Postgres + LanceDB
    precompact.log            ← Append-only diagnostics log
    _last_injected.txt        ← Dedup fingerprint for memory inject
    _last_prompt.txt          ← Last prompt text for downstream hooks
  copilot-instructions.md     ← Full system prompt (read by VS Code Copilot)
```

### 8.2 Registering hooks (settings.json)

```json
{
  "github.copilot.chat.chatHooks": {
    "SessionStart": "${workspaceFolder}/.github/hooks/session_start_hook.ps1",
    "PreToolUse":   "${workspaceFolder}/.github/hooks/pretool_inject_hook.ps1",
    "Stop":         "${workspaceFolder}/.github/hooks/stop_hook.ps1"
  }
}
```

### 8.3 SessionStart Hook (session_start_hook.ps1)

Fires once per VS Code session. Injects the static knowledge base document as
`additionalContext` so the agent starts each session with full institutional memory.

```powershell
# Key behaviour:
# 1. Reads docs/QIDISTUDIO_KNOWLEDGE.md (or your equivalent)
# 2. Prepends a mandatory protocol banner (Phase 0 steps)
# 3. Emits as hookSpecificOutput.additionalContext

$repo    = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$kbFile  = Join-Path $repo 'docs\QIDISTUDIO_KNOWLEDGE.md'
$kbContent = Get-Content $kbFile -Raw -Encoding UTF8

$out = @{
    hookSpecificOutput = @{
        hookEventName     = 'SessionStart'
        additionalContext = $kbContent
    }
}
Write-Output ($out | ConvertTo-Json -Depth 4 -Compress)
```

**Full implementation:** [`.github/hooks/session_start_hook.ps1`](.github/hooks/session_start_hook.ps1)

### 8.4 PreToolUse Hook (pretool_inject_hook.ps1) — CRITICAL

Fires before **every** tool call. Does two things simultaneously:

1. **Log guard** — scans the transcript JSONL for a `create_file`/DC-write targeting
   `logs/YYYY-MM-DD_HHMMSS_<slug>.md` since the last user message. If not found →
   emits a `⛔ STOP` message forcing the agent to create one before proceeding.

2. **Semantic memory inject** — runs `memory/inject.py` against the current prompt
   text, retrieves top-K relevant LanceDB chunks, emits as `additionalContext`.

**Critical regex detail** — The transcript stores file paths as JSON-encoded strings,
so backslashes become `\\`. The pattern must handle both:
```powershell
$logPattern = [System.Text.RegularExpressions.Regex]::new(
    '(?:create_file|mcp_desktop-comma_write_file).*logs[/\\]{1,2}\d{4}-\d{2}-\d{2}_\d{6}',
    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
)
```

**Full implementation:** [`.github/hooks/pretool_inject_hook.ps1`](.github/hooks/pretool_inject_hook.ps1)

### 8.5 Stop Hook (stop_hook.ps1)

Fires when the agent finishes each turn. Persists:
- Last prompt + response pair → PostgreSQL `prompts`/`responses` tables
- Session stats → `memory/_session_stats.txt`
- Runs `memory/extract.py` to sync new docs to LanceDB
- Auto-commits changed memory files to git

**Full implementation:** [`.github/hooks/stop_hook.ps1`](.github/hooks/stop_hook.ps1)

### 8.6 Hook Output Format

All hooks emit a single JSON object to stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "... text injected into model context ..."
  }
}
```

To suppress context injection but remain silent: `Write-Output '{}'`

---

## 9. Prompt Execution Protocol (Phase 0)

**This protocol is MANDATORY. Execute Phase 0 before any task, tool, or file operation.**

### Step 0.1 — Scan for Unfinished Logs

```powershell
# PowerShell (Windows)
$unfinished = Get-ChildItem logs\*.md -ErrorAction SilentlyContinue |
  Where-Object {
    (Get-Content $_.FullName -Raw) -match '\- \[ \]' -and
    (Get-Content $_.FullName -Raw) -match '## Status: OPEN'
  } | Select-Object -ExpandProperty Name

if ($unfinished) {
    $unfinished | ForEach-Object { Write-Host "  UNFINISHED: $_" }
} else {
    Write-Host "  No unfinished logs found."
}
```

If unfinished logs are found, ask the user YES/NO before proceeding.

### Step 0.2 — Create the Session Log

**The log file MUST be the first `create_file` call of the turn.**

```
Filename:  logs/YYYY-MM-DD_HHMMSS_<meaningful-slug>.md
Timestamp: Get-Date -Format "yyyy-MM-dd_HHmmss"
Slug:      3–6 word kebab-case summary of the prompt's intent
```

**Template:**

```markdown
# Log: <Human-readable title>

**Date:** YYYY-MM-DD
**Time:** HH:MM:SS
**Model:** Claude Sonnet 4.6
**Prompt Summary:** <one precise sentence>

---

## Task Checklist

- [ ] 1. <first atomic action>
- [ ] 2. <second atomic action>

---

## Inherited Tasks

<!-- Populated only when prior unfinished logs are inherited -->

---

## Execution Notes

<!-- Timestamped working notes appended during execution -->

---

## Status: OPEN
```

### Step 0.3 — Execute and Check Off

After completing each task:
```
- [ ] N. <task>   →   - [x] N. <task>  ✓ HH:MM:SS
```

Use `replace_string_in_file` (not a full file rewrite) for surgical check-offs.

### Step 0.4 — Close the Log

When all tasks are `[x]`:
```
## Status: OPEN  →  ## Status: COMPLETE
```

---

## 10. Session Log Protocol (PhD Standard)

### Filename Grammar

```
logs/<date>_<time>_<slug>.md

<date>  ::= YYYY-MM-DD
<time>  ::= HHMMSS  (no colons — filesystem safe)
<slug>  ::= [a-z0-9-]{3,50}  (kebab-case, max 6 words, reflects prompt intent)
```

### Unfinished Log Detection

A log is **UNFINISHED** iff:
- Pattern `- \[ \]` matches anywhere **AND**
- Final status line is `## Status: OPEN`

A log is **COMPLETE** iff:
- No `- \[ \]` lines remain **AND**
- Final status line is `## Status: COMPLETE`

### Completion Marker Syntax

```
- [x] N. <original task text>  ✓ HH:MM:SS
```

The `✓ HH:MM:SS` suffix is required — it provides an audit trail.

---

## 11. Startup Health Check Pipeline

### Overview

`scripts/startup_check.py` runs 15 categories, 75+ individual checks, and gates itself
to once per day via `logs/startup_health.log`. When all pass, it writes:
```
[COMPLETE for YYYY-MM-DD]
```

### Required checks (adapt paths to your repo)

| # | Category | What is verified |
|---|----------|-----------------|
| 1 | `.env` completeness | All 11 keys present and non-empty |
| 2 | Virtual environments | `memory_env`, `.venv` executables + key packages |
| 3 | PostgreSQL | Connection + LangGraph tables + run_store tables |
| 4 | LangGraph checkpointer | `PostgresSaver.setup()` succeeds |
| 5 | LanceDB | Path reachable, `documents` table populated |
| 6 | LangSmith | `Client()` works; your projects exist |
| 7 | Gemini (Vertex AI) | `ChatGoogleGenerativeAI` ping → `ONLINE` |
| 8 | Gemini (direct key) | `google.genai.Client` ping → `ONLINE` |
| 9 | Agent fleet | All graphs compile as `CompiledStateGraph` |
| 10 | GCS buckets | Bucket(s) listable |
| 11 | Firestore | Write + read probe document |
| 12 | BigQuery | Dataset accessible |
| 13 | External APIs | Google Search · GitHub rate-limit · HuggingFace whoami |
| 14 | Pipeline imports | Every entry-point importable |
| 15 | Memory inject | inject.py returns LanceDB results |

### Usage

```powershell
# Standard (gated — runs once per day)
memory_env\Scripts\python.exe -B scripts\startup_check.py

# Force re-run
memory_env\Scripts\python.exe -B scripts\startup_check.py --force

# Auto-repair missing packages / LangGraph tables
memory_env\Scripts\python.exe -B scripts\startup_check.py --force --fix

# Quick check (env vars + imports only, no API calls)
memory_env\Scripts\python.exe -B scripts\startup_check.py --quick

# Show today's entries
memory_env\Scripts\python.exe -B scripts\startup_check.py --summary
```

**Full implementation:** [`scripts/startup_check.py`](../scripts/startup_check.py) (954 lines)

---

## 12. Knowledge Base & Memory System

### Architecture

```
Docs written → memory/extract.py → LanceDB (sentence-transformer embeddings)
                                         ↓
User prompt → memory/inject.py --query → Top-K chunks → agent context
                                         ↓
Agent response → stop_hook.ps1 → memory/prompt_store.py → PostgreSQL
                                         ↓
30-min cron → memory/sync_prompts_to_lancedb.py → LanceDB (prompt pairs)
```

### Key Scripts

| Script | Purpose |
|--------|---------|
| `memory/extract.py` | Index all docs → LanceDB (`documents` table) |
| `memory/inject.py` | Query LanceDB → return additionalContext JSON |
| `memory/prompt_store.py` | Save prompt/response pairs to PostgreSQL |
| `memory/sync_prompts_to_lancedb.py` | Push Postgres pairs → LanceDB |
| `memory/daily_lancedb_dedupe.py` | Remove duplicate vectors daily |

### Usage

```powershell
# Full index rebuild (after docs change)
memory_env\Scripts\python.exe memory/extract.py

# Semantic search (test injection)
memory_env\Scripts\python.exe memory/inject.py --query "cmake build"

# Prompt persistence stats
memory_env\Scripts\python.exe memory/prompt_store.py --daily-stats

# Manual LanceDB sync
memory_env\Scripts\python.exe memory/sync_prompts_to_lancedb.py

# Dedup (daily maintenance)
memory_env\Scripts\python.exe memory/daily_lancedb_dedupe.py
```

### COMPACTION_SUMMARY Block (auto-persist learnings)

Include this block in any agent response to auto-persist the learning via the Stop hook:

```
COMPACTION_SUMMARY:
topic: <topic-name>
content: <key learning or decision — 1–5 sentences>
```

The Stop hook detects this marker and calls `memory/prompt_store.py` to persist it to
PostgreSQL, which is then synced to LanceDB within 30 minutes.

### LanceDB Table Schema

```python
import lancedb
db = lancedb.connect("./lancedb")
table = db.open_table("documents")
# Schema: {"id": str, "text": str, "source": str,
#          "topic": str, "vector": list[float32]}
results = table.search("cmake build system").limit(5).to_pandas()
```

---

## 13. Knowledge Validation & Hallucination Repair Pipeline

This pipeline validates every factual claim in a Markdown document against nine
authoritative external sources, flags hallucinations, and rewrites them with sourced
corrections. It was developed to eliminate hallucinations from a 40-document PhD-level
knowledge base and achieved a **0 outstanding hallucinations** result on first full run.

### Architecture

```
doc.md → DocumentParser → ClaimExtractor → KnowledgeValidator
                                                    ↓
     ┌──── CrossRef (0.92) ─── arXiv (0.90) ─── PubMed (0.91) ─────┐
     │──── NIST (0.95) ──── MathWorld (0.93) ─────────────────────────┤ parallel
     │──── Semantic Scholar (0.88) ── Wikipedia (0.72) ───────────────┤
     └──── Tavily (0.70) ─── GitHub Search (0.65) ────────────────────┘
                                    ↓
              HallucinationReplacer (Gemini 2.5 Flash rewrites)
                                    ↓
              doc_validated.md + doc.validation.json
```

### Confidence Thresholds

| Range | Verdict | Action |
|-------|---------|--------|
| 0.80 – 1.00 | ✅ VERIFIED | No change required |
| 0.60 – 0.79 | 🟢 SUPPORTED | Add citation in References |
| 0.40 – 0.59 | 🟡 UNCERTAIN | Rewrite + hedge language |
| 0.20 – 0.39 | 🟠 DISPUTED | Replace with corrected sentence |
| 0.00 – 0.19 | 🔴 HALLUCINATION | Remove or fully replace |

### Usage

```powershell
# Validate one document
memory_env\Scripts\python.exe scripts\knowledge_validator.py docs\MyDocument.md

# Validate all documents
Get-ChildItem docs\*.md | ForEach-Object {
    memory_env\Scripts\python.exe scripts\knowledge_validator.py $_.FullName
}

# Run the full validation + fix pipeline
memory_env\Scripts\python.exe scripts\validate_all_docs.py

# Fix mode only (apply existing validation.json corrections to source files)
memory_env\Scripts\python.exe scripts\validate_all_docs.py --fix-only
```

### Knowledge Document Creation Workflow

Every durable insight, architectural decision, or protocol MUST be captured in `docs/`.

```
[ ] K1.  Trigger identified (architectural decision, new pipeline, protocol, etc.)
[ ] K2.  Draft document in docs/ using canonical structure (§2 of every doc)
[ ] K3.  All equations in KaTeX LaTeX notation
[ ] K4.  All code blocks typed, fenced, language-tagged
[ ] K5.  Run knowledge_validator.py
[ ] K6.  Review validation.json; apply corrections where confidence < 0.60
[ ] K7.  Re-run validator on corrected doc; confirm zero hallucinations
[ ] K8.  Add validated References section (DOIs where available)
[ ] K9.  Reindex: memory_env\Scripts\python.exe memory/extract.py
[ ] K10. git add docs/<YourDoc>.md docs/<YourDoc>.validation.json && git commit
```

**Full implementation:** [`scripts/knowledge_validator.py`](../scripts/knowledge_validator.py) (1348 lines)

---

## 14. Agent Fleet Architecture

### Overview

The fleet uses a **supervisor pattern** with true parallel dispatch via LangGraph's
`Send` API. Four core agents run as a single superstep:

```
START → plan (Gemini director)
           ↓  LangGraph Send API (parallel superstep)
    ┌────────────────────────────────────┐
    │  researcher  │  builder  │  verifier  │  scribe  │
    └────────────────────────────────────┘
           ↓
     synthesize → END
```

### Agent Roles

| Agent | Trigger | Key Capability | Do NOT use for |
|-------|---------|---------------|----------------|
| `researcher` | Find facts, read docs, web-search | Gemini + Google Search + LanceDB RAG | Writing files |
| `builder` | Write/edit code, fix bugs, implement | Gemini 2.5 Pro + file edits | Pure research |
| `verifier` | Audit code, type safety, edge cases | Structured verdict only | New code |
| `scribe` | Persist facts/decisions to LanceDB | LanceDB upsert | Code changes |

### Health Check (run before any fleet work)

```powershell
memory_env\Scripts\python.exe agents/_agentcomms_check.py > agents\_health.txt 2>&1
# Expected output (all 10 lines must be present):
#   researcher : CompiledStateGraph
#   builder    : CompiledStateGraph
#   verifier   : CompiledStateGraph
#   scribe     : CompiledStateGraph
#   coder      : CompiledStateGraph
#   tester     : CompiledStateGraph
#   dev_fleet  : CompiledStateGraph
#   gemini ping: ONLINE
#   postgres   : ready
#   langsmith  : connected
```

### Invocation (always redirect to file — NEVER use captureOutput)

```powershell
# Standard task dispatch
memory_env\Scripts\python.exe -B agents/orchestrator.py "your task" `
    > agents\_out.txt 2>&1; echo DONE >> agents\_out.txt

# Multi-task parallel fan-out
memory_env\Scripts\python.exe -B agents/orchestrator.py `
    "Task 1 for researcher: ...; Task 2 for builder: ...; Task 3 for verifier: ..." `
    > agents\_parallel_out.txt 2>&1; echo DONE >> agents\_parallel_out.txt
```

### Reading Results (ALWAYS from PostgreSQL, not from text files)

```powershell
# Text files are destroyed when terminals close. Use Postgres.
memory_env\Scripts\python.exe -m agents.run_store --latest
memory_env\Scripts\python.exe -m agents.run_store --latest-detail
memory_env\Scripts\python.exe -m agents.run_store --log
```

```python
from agents.run_store import get_latest_run, get_latest_fleet_run
run = get_latest_run()
print(run['final_response'])
```

### Writing Effective Task Strings

```
[VERB] [SUBJECT] [CONSTRAINT/GOAL] [OUTPUT FORMAT]

Good examples:
  "Audit agents/schema.py for non-Optional int/float fields that Gemini
   might return as null; report every field name and model class"

  "Fix LeadScrew.starts to accept 'single'/'double' strings;
   write @field_validator; verify syntax; output patched snippet"

  "Persist to LanceDB: root cause = Pydantic rejects null from Gemini;
   fix = model_validator strips None; topic = schema-validation"
```

---

## 15. Dev Fleet (Coder/Tester) Protocol

The Dev Fleet adds a **coder→tester iteration loop** that catches bugs before they
reach the main repository. Each team runs independently in parallel.

### Architecture

```
Fleet Director (Gemini 2.5 Flash)
  ├─ Team Alpha: prime → coder (Pro) → tester (Pro/Vision) ──┐
  ├─ Team Beta:  prime → coder (Pro) → tester (Pro/Vision) ──┤ parallel
  └─ Team Gamma: prime → coder (Pro) → tester (Pro/Vision) ──┘
                                              ↑ iterate on FAIL (max 5)
```

### Invocation

```powershell
# Single task
memory_env\Scripts\python.exe -B agents/dev_fleet.py "Implement X feature" `
    > agents\_fleet_alpha_out.txt 2>&1; echo DONE >> agents\_fleet_alpha_out.txt

# Multi-task fan-out (director assigns teams)
memory_env\Scripts\python.exe -B agents/dev_fleet.py `
    "Task 1: implement schema fix; Task 2: add unit tests; Task 3: update docs" `
    > agents\_fleet_out.txt 2>&1; echo DONE >> agents\_fleet_out.txt
```

### Coder Signal Protocol

The Coder always emits a typed JSON signal to the Tester:

```json
{
  "status": "code_ready",
  "changes": [
    {"file": "src/module.py", "operation": "edit", "content": "..."}
  ],
  "test_instructions": {
    "type": "python",
    "command": "memory_env\\Scripts\\python.exe -B -m pytest tests/ -v",
    "expected_behavior": "All 12 tests pass",
    "visual_check": null
  },
  "iteration": 1,
  "prior_failure": null
}
```

### Tester Verdict Protocol

```json
{
  "status": "PASS",
  "counts": {"passed": 12, "failed": 0, "errors": 0},
  "failures": [],
  "next_action": "pass"
}
```

---

## 16. Texture Generator (Blender/bpy Bonus Pipeline)

The autonomous texture loop applies displacement-map-driven surface textures to any
STL/3MF file, producing museum-quality renders and print-ready geometry.

### How It Works

```
Input STL + skin PNG/JPG
        ↓
apply_texture_bpy.py (Blender 4.0+ via --background --python)
  1. Import mesh via bpy.ops.import_scene
  2. Load PNG as image texture → Displace modifier
  3. Apply modifier (requires full Blender — bpy pip inadequate)
  4. Export displaced STL
        ↓
Output STL (raised scales / carved negative / replaced mesh)
```

### Modes

| Mode | Effect | Use case |
|------|--------|----------|
| `part` | Adds raised displacement shell as MODEL_PART | Decorative surface scales |
| `negative` | Adds carved shell as NEGATIVE_VOLUME | Inset patterns |
| `modifier` | Replaces original mesh with displaced version | Final production mesh |

### Usage

```powershell
# Via Blender executable (REQUIRED — bpy pip cannot apply Displace modifier)
& "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" `
    --background --python resources\scripts\apply_texture_bpy.py `
    -- model.stl skin.png `
    --mode modifier `
    --tile-size 15 `
    --relief 1.0 `
    --gamma 0.7

# Output line in stdout:
#   SKIN_OUTPUT: <path-to-displaced.stl>
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--mode` | `modifier` | `part` / `negative` / `modifier` |
| `--tile-size` | `15` | Texture tile size in mm |
| `--relief` | `1.0` | Displacement strength multiplier |
| `--invert` | off | Invert displacement (peaks become valleys) |
| `--gamma` | `0.7` | Gamma correction for texture intensity |
| `--log` | none | Path to write log output |

### Requirements

- **Blender 4.0+** installed as a full executable (NOT the `bpy` pip package)  
  [Download Blender](https://www.blender.org/download/)
- `bpy_env` virtual environment for development/testing only  
  `bpy_env\Scripts\pip install bpy`
- Input: any STL or 3MF mesh file  
- Skin: any PNG/JPG greyscale or colour image (used as displacement map)

**Full implementation:** [`resources/scripts/apply_texture_bpy.py`](../resources/scripts/apply_texture_bpy.py) (2723 lines)

---

## 17. Knowledge Repository Links

### Primary Repositories

| Resource | URL | Authority | Notes |
|----------|-----|-----------|-------|
| LangChain Docs | [python.langchain.com](https://python.langchain.com) | Canonical | Python SDK reference |
| LangGraph Docs | [langchain-ai.github.io/langgraph](https://langchain-ai.github.io/langgraph/) | Canonical | Graph state machines |
| LangSmith Docs | [docs.smith.langchain.com](https://docs.smith.langchain.com) | Canonical | Tracing + evaluation |
| Google Gemini API | [ai.google.dev/api/python](https://ai.google.dev/api/python/docs/reference) | Canonical | google-genai v1+ |
| LanceDB Docs | [lancedb.github.io/lancedb](https://lancedb.github.io/lancedb/) | Canonical | Vector store |
| LangGraph GitHub | [github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | Source | Issues + examples |
| LangSmith Hub | [smith.langchain.com/hub](https://smith.langchain.com/hub) | Live | Versioned prompts |

### Academic Source APIs (used by knowledge_validator.py)

| Source | API | Authority Score |
|--------|-----|----------------|
| CrossRef | [api.crossref.org](https://api.crossref.org) | 0.92 — 145M+ DOI publications |
| arXiv | [arxiv.org/help/api](https://arxiv.org/help/api) | 0.90 — 2.4M+ preprints |
| PubMed/NCBI | [www.ncbi.nlm.nih.gov/home/develop/api](https://www.ncbi.nlm.nih.gov/home/develop/api/) | 0.91 — 37M+ biomedical |
| NIST | [www.nist.gov/services-resources/software/nist-chemistry-webbook](https://webbook.nist.gov) | 0.95 — metrology + standards |
| Semantic Scholar | [api.semanticscholar.org](https://api.semanticscholar.org/graph/v1) | 0.88 — 220M+ papers |
| Wolfram MathWorld | [mathworld.wolfram.com](https://mathworld.wolfram.com) | 0.93 — mathematical definitions |
| Wikipedia REST | [en.wikipedia.org/api/rest_v1](https://en.wikipedia.org/api/rest_v1/) | 0.72 — encyclopaedic baseline |

### MCP Servers (live context injection)

| Server | Install | Purpose |
|--------|---------|---------|
| Context7 | `npx @upstash/context7-mcp@latest` | Live library documentation |
| Desktop Commander | `npx @wonderwhy-er/desktop-commander@latest` | File I/O, processes, search |
| Firecrawl | `npx firecrawl-mcp` | Web crawl + extraction |
| GitHub MCP | `npx @github/mcp@latest` | PR + issue management |

### Related Projects

| Project | URL | Notes |
|---------|-----|-------|
| QIDIStudio | [github.com/phantom-man/QIDIStudio](https://github.com/phantom-man/QIDIStudio) | Source of this almanac |
| sentence-transformers | [sbert.net](https://www.sbert.net) | Embedding models |
| psycopg3 | [www.psycopg.org/psycopg3](https://www.psycopg.org/psycopg3/docs/) | PostgreSQL async driver |
| Blender | [www.blender.org](https://www.blender.org/download/) | Required for texture pipeline |

---

## 18. Quick Reference Card

### Daily Startup

```powershell
# 1. Health check (auto-gated to once/day)
memory_env\Scripts\python.exe -B scripts\startup_check.py

# 2. Memory status
memory_env\Scripts\python.exe memory\inject.py --query "recent work"

# 3. Fleet health
memory_env\Scripts\python.exe agents\_agentcomms_check.py
```

### Common Operations

```powershell
# Run agent task
memory_env\Scripts\python.exe -B agents/orchestrator.py "task text" > _out.txt 2>&1; echo DONE >> _out.txt

# Run dev fleet
memory_env\Scripts\python.exe -B agents/dev_fleet.py "implement X" > _fleet.txt 2>&1; echo DONE >> _fleet.txt

# Query results
memory_env\Scripts\python.exe -m agents.run_store --latest

# Validate docs
memory_env\Scripts\python.exe scripts\knowledge_validator.py docs\MyDoc.md

# Reindex memory
memory_env\Scripts\python.exe memory\extract.py

# View last N log entries
Get-Content logs\startup_health.log -Tail 30
```

### Banned Patterns (NEVER USE)

| ❌ Forbidden | ✅ Replacement |
|-------------|---------------|
| `command \| Tee-Object out.txt` | `command > out.txt 2>&1; echo DONE >> out.txt` |
| `sendCommand(..., captureOutput: true)` | Redirect to file and `read_file` it |
| `python -c "..."` with escaping | Use `mcp_pylance_mcp_s_pylanceRunCodeSnippet` |
| `run store text files` as durable state | Always query PostgreSQL |

### grep Patterns for Session Log Detection (PowerShell)

```powershell
# Detect OPEN logs
Get-ChildItem logs\*.md | Where-Object {
    (Get-Content $_.FullName -Raw) -match '\- \[ \]' -and
    (Get-Content $_.FullName -Raw) -match '## Status: OPEN'
}

# Find today's logs
Get-ChildItem logs\*.md | Where-Object { $_.Name -match (Get-Date -Format 'yyyy-MM-dd') }
```

---

*Document generated 2026-03-05 | Model: Claude Sonnet 4.6 | Repo: phantom-man/QIDIStudio*
*This document is repo-agnostic — adapt paths and project names to your target repository.*
