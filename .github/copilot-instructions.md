# ⚡ PROMPT EXECUTION PROTOCOL — MANDATORY

> **This protocol governs EVERY prompt without exception.**
> **Execute Phase 0 in full before touching any task, tool, or file.**

---

## Phase 0: Pre-Work Ritual

### Step 0.1 — Scan for Unfinished Logs

**Before starting any work**, scan `logs/` for log files that contain unfinished tasks.
An unfinished log is any file where:

1. At least one line matches `- [ ]`, **AND**
2. The final `## Status:` line reads `OPEN`

Detection command (run in `scripts` terminal, redirect so output is readable):

```powershell
$unfinished = Get-ChildItem logs\*.md -ErrorAction SilentlyContinue |
  Where-Object { (Get-Content $_.FullName -Raw) -match '\- \[ \]' -and
                 (Get-Content $_.FullName -Raw) -match '## Status: OPEN' } |
  Select-Object -ExpandProperty Name
if ($unfinished) {
    $unfinished | ForEach-Object { Write-Host "  UNFINISHED: $_" }
} else {
    Write-Host "  No unfinished logs found."
}
```

If unfinished logs are found, **stop** and present the user with:

```
The following task logs have unfinished items:
  • <filename>  (<N> tasks remaining)
  ...

Would you like me to complete them before working on the current prompt?
  Reply YES (all), YES <filename> (specific), or NO to skip.
```

Wait for the user's reply before proceeding.

- **YES (all)**: Import all unchecked `- [ ]` items from every unfinished log into the current log under `## Inherited Tasks`.
- **YES \<filename\>**: Import only the specified files.
- **NO**: Skip; note in the current log that prior tasks were explicitly deferred.

---

### Step 0.2 — Create the Session Log File

**Immediately** generate a log file for the current prompt.

**Filename format:**

```
logs/YYYY-MM-DD_HHMMSS_<meaningful-slug>.md
```

- `YYYY-MM-DD_HHMMSS` — wall-clock timestamp at prompt receipt (PowerShell: `Get-Date -Format "yyyy-MM-dd_HHmmss"`)
- `<meaningful-slug>` — 3–6 word kebab-case summary that reflects the **intent** of the prompt

**Good slug examples:**

| Prompt intent                 | Slug                               |
| ----------------------------- | ---------------------------------- |
| Add SYCL kernel for GPU saxpy | `add-sycl-saxpy-kernel`            |
| Fix UV projection for cones   | `fix-uv-cone-projection`           |
| Rewrite PhD docs batch B      | `rewrite-phd-docs-batch-b`         |
| Create logs dir and protocol  | `create-logs-dir-and-phd-protocol` |

**Log file template:**

```markdown
# Log: <Human-readable title>

**Date:** YYYY-MM-DD
**Time:** HH:MM:SS
**Model:** Claude Sonnet 4.6
**Prompt Summary:** <one precise sentence describing what was asked>

---

## Task Checklist

- [ ] 1. <first atomic action>
- [ ] 2. <second atomic action>
- [ ] 3. ...

---

## Inherited Tasks

<!-- Populated only when prior unfinished logs are inherited. Otherwise leave this comment. -->

---

## Execution Notes

<!-- Timestamped working notes appended during execution -->

---

## Status: OPEN
```

**Rules for the Task Checklist:**

- Break the prompt into the **smallest independently verifiable actions**.
- Every file creation, edit, tool call, command run, and verification is its own line.
- Minimum 3 tasks; no upper limit.
- Ordered: dependencies come before dependents.

---

### Step 0.3 — Execute and Check Off

Work through tasks in order. After completing each one:

1. Update the log: change `- [ ] N. <task>` → `- [x] N. <task>  ✓ HH:MM:SS`
2. Append a one-line note to `## Execution Notes` with timestamp and outcome.

Use `replace_string_in_file` (or `multi_replace_string_in_file` for batches) to update the log in-place. Never rewrite the whole file to check off a single task.

---

### Step 0.4 — Close the Log

When **all** tasks (including any inherited tasks) are complete:

1. Verify no `- [ ]` lines remain.
2. Change the last line from `## Status: OPEN` to `## Status: COMPLETE`.

---

## Log File Specification (PhD Standard)

### Canonical Structure

```markdown
# Log: <Title>

**Date:** YYYY-MM-DD
**Time:** HH:MM:SS
**Model:** Claude Sonnet 4.6
**Prompt Summary:** <single sentence>

---

## Task Checklist

- [ ] 1. <action> ← unchecked
- [x] 2. <action> ✓ HH:MM:SS ← checked with completion time
- [ ] 3. <action>

---

## Inherited Tasks

<!-- list inherited items here if any, same format as Task Checklist -->

---

## Execution Notes

- HH:MM:SS <note about what happened>
- HH:MM:SS <note about what happened>

---

## Status: OPEN ← OPEN until every task is [x]; then COMPLETE
```

### Filename Grammar

```
logs/<date>_<time>_<slug>.md

<date>  ::= YYYY-MM-DD
<time>  ::= HHMMSS  (no colons — filesystem safe)
<slug>  ::= [a-z0-9-]{3,50}  (kebab-case, max 6 words, reflects prompt intent)
```

### Unfinished Log Detection Rules

A log is **UNFINISHED** iff:

- Pattern `- \[ \]` matches anywhere in the file, **AND**
- Pattern `## Status: OPEN` matches the final status line

A log is **COMPLETE** iff:

- No `- \[ \]` lines remain, **AND**
- Final status line reads `## Status: COMPLETE`

### Completion Marker Syntax

```
- [x] N. <original task text>  ✓ HH:MM:SS
```

The `✓ HH:MM:SS` suffix is required — it provides a per-task audit trail.

---

## Implementation Rules

| Rule                 | Detail                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Timestamp source     | PowerShell: `Get-Date -Format "yyyy-MM-dd_HHmmss"` for filenames; `Get-Date -Format "HH:mm:ss"` for task checkoffs |
| Slug derivation      | Lowercase the prompt intent; replace spaces with `-`; strip punctuation; max 6 tokens; be specific, not generic    |
| Log update method    | `replace_string_in_file` for single task checkoffs; `multi_replace_string_in_file` for batch completions           |
| Phase 0 skippable?   | **Never.** Even "trivial" single-sentence prompts get a log file.                                                  |
| Log storage          | Always in `logs/` at the workspace root — never inside `docs/`, `.github/`, or `agents/`                           |
| Status line position | Must always be the **last non-empty line** of the file                                                             |
| Prior task deferral  | If user says NO to inherited tasks, note `<!-- User deferred prior tasks at HH:MM:SS -->` in Inherited Tasks       |

---

# 📚 KNOWLEDGE DOCUMENT CREATION PROTOCOL — MANDATORY

> **Every durable insight, decision, pattern, or directive generated in this repo MUST be
> captured as a knowledge document in `docs/`.  
> Knowledge not written down does not exist for future agents.**

---

## When to Create a Knowledge Document

Create a knowledge document **immediately** whenever any of the following triggers occur:

| Trigger Category                  | Examples                                                                                  |
| --------------------------------- | ----------------------------------------------------------------------------------------- |
| **Architectural decision**        | Choosing LanceDB over Chroma; adopting SYCL for GPU portability; switching to USM buffers |
| **New pipeline or workflow**      | AI debug pipeline; knowledge-validation pipeline; PhD doc rewrite workflow                |
| **Protocol established**          | Prompt execution protocol; knowledge doc protocol; build protocol                        |
| **Structural / directory change** | New `logs/` dir; `scripts/` reorganisation; `agents/` fleet launch                       |
| **Algorithm or technique adopted**| ICP alignment; AMEO bead-width PID; NURBS vectorisation; CSM symmetry scoring            |
| **Tool or library integrated**    | LangGraph state machines; paperscraper; arXiv.py; Tavily search; pdfplumber              |
| **Agent directive or rule**       | Fleet dispatch protocol; parallelism rules; coder→tester signal protocol                 |
| **Debugging insight**             | Root cause of a non-obvious failure; fix strategy that should never be forgotten          |
| **Research finding**              | Benchmark results; literature survey outcome; hardware characterisation                   |
| **External API behaviour**        | Gemini quota limits; CrossRef polite pool; arXiv rate limiting; NIST endpoint changes    |
| **Security / compliance decision**| API key scoping; .gitignore patterns; credential rotation strategy                        |

**When in doubt, create the doc.**  The cost of an unneeded doc is low.
The cost of a lost architectural decision is a re-investigation.

---

## Anatomy of a Knowledge Document

Every doc in `docs/` MUST follow this canonical structure:

```markdown
# <Title>  (H1 — exactly one, reflects the precise topic)

> **One-sentence abstract** — state what this document establishes and why it matters.

## 1. Motivation

Why does this knowledge exist? What problem does it solve?
Include the context that would help a future agent understand the "why".

## 2. Core Concepts / Background

PhD-level technical exposition. Use LaTeX for all equations:
  - Inline:  $E = mc^2$
  - Display: $$\nabla^2 \phi = \rho / \varepsilon_0$$

Reference primary literature with full citations:
  [Author et al., YYYY, Title, Journal/Conference, DOI]

## 3. Implementation / Decision

Concrete code, CMake, SQL, or configuration that enacts the concept.
All code blocks MUST be typed Python (3.11+), modern C++20, or valid shell.

## 4. Validation Rationale

How was this knowledge verified?  State which sources corroborate it.
(Filled automatically when doc passes through `knowledge_validator.py`.)

## 5. Consequences & Trade-offs

What does adopting this change? What is deferred or deprecated?

## 6. References

- [1] Author, Title, Venue, Year. DOI: …
- [2] …
```

**Layout rules:**
- Title: H1 only; no subtitle H1s. All other headings are H2–H4.
- Math: KaTeX-compatible LaTeX. No Unicode math substitutes (`ℝ` → `$\mathbb{R}$`).
- Code: fenced blocks with language identifier; type-annotated; runnable.
- Length: ≥ 400 words. No maximum. Depth over brevity.
- Tone: third person, technical, PhD thesis register.
- No conversational openers ("In this document we will…").

---

## Knowledge Validation Gate (MANDATORY)

Before finalising or committing any knowledge document, run it through the
**Knowledge Validator** to purge hallucinations and ground every claim in an
authoritative source.

### Step K.1 — Validate a single document

```powershell
# From repo root, scripts terminal
memory_env\Scripts\python.exe scripts\knowledge_validator.py docs\<YourDoc>.md
```

The validator will:
1. Parse the document (`.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.csv`, `.json`, `.tex`, `.py`, `.cpp`)
2. Extract every testable factual claim (numerical, definitional, attributive, methodological)
3. Query all nine authoritative repositories in parallel:
   - **CrossRef** (authority 0.92) — 145M+ DOI publications  
   - **arXiv** (authority 0.90) — 2.4M+ preprints  
   - **PubMed/NCBI** (authority 0.91) — 37M+ biomedical citations  
   - **MathWorld/Wolfram** (authority 0.93) — mathematical definitions  
   - **NIST** (authority 0.95) — metrology and standards  
   - **Semantic Scholar** (authority 0.88) — 220M+ papers  
   - **Wikipedia** (authority 0.72) — encyclopaedic baseline  
   - **Tavily** (authority 0.70) — real-time web search  
   - **GitHub Search** (authority 0.65) — algorithmic implementation check  
4. Score each claim: `confidence = Σ(authority × relevance) / Σ(authority)`
5. Flag claims below the threshold (default 0.60)
6. Use Gemini 2.5 Flash to rewrite flagged sentences with sourced corrections
7. Output `<doc>_validated.md` + `<doc>.validation.json`

### Step K.2 — Validate all docs in bulk

```powershell
Get-ChildItem docs\*.md | ForEach-Object {
    Write-Host "Validating: $($_.Name)"
    memory_env\Scripts\python.exe scripts\knowledge_validator.py $_.FullName
}
```

### Step K.3 — Review the JSON report

```python
import json, pathlib
report = json.loads(pathlib.Path("docs/MyDoc.validation.json").read_text())
for v in report["verdicts"]:
    if v["confidence"] < 0.60:
        print(f"  [{v['confidence']:.2f}] {v['claim']}")
        print(f"       → {v['corrected']}")
```

### Confidence Thresholds

| Confidence Range | Verdict          | Action                                         |
| ---------------- | ---------------- | ---------------------------------------------- |
| 0.80 – 1.00      | ✅ VERIFIED       | No change required                             |
| 0.60 – 0.79      | 🟢 SUPPORTED      | No change; add citation in § References        |
| 0.40 – 0.59      | 🟡 UNCERTAIN      | Rewrite for precision; add hedge language      |
| 0.20 – 0.39      | 🟠 DISPUTED       | Replace with validator-corrected sentence      |
| 0.00 – 0.19      | 🔴 HALLUCINATION  | Remove or fully replace; citation required     |

---

## Knowledge Doc Creation Workflow (Step by Step)

> This workflow is **part of the session log** — each step is a checklist item.

```
[ ] K1.  Trigger identified (see trigger table above)
[ ] K2.  Draft document created in docs/ using canonical structure
[ ] K3.  All equations written in KaTeX LaTeX
[ ] K4.  All code blocks typed, fenced, language-tagged
[ ] K5.  Run knowledge_validator.py
[ ] K6.  Review validation.json; apply all corrections where confidence < 0.60
[ ] K7.  Re-run validator on corrected doc; confirm zero hallucinations
[ ] K8.  Add validated References section (DOIs where available)
[ ] K9.  Run LanceDB reindex: memory_env\Scripts\python.exe memory/extract.py
[ ] K10. git add docs/<YourDoc>.md docs/<YourDoc>.validation.json && git commit
```

Checklist items K1–K10 MUST appear verbatim in the session log Task Checklist
when a knowledge doc is being created.

---

## Storage Rules

| Rule                        | Requirement                                                         |
| --------------------------- | ------------------------------------------------------------------- |
| Location                    | Always `docs/` at workspace root — never `logs/`, `.github/`, `agents/` |
| Naming                      | `Title Case With Spaces.md` — matching the H1 exactly              |
| Validated copy              | `<stem>_validated.md` (auto-generated; DO NOT commit directly)      |
| JSON report                 | `<stem>.validation.json` — commit alongside the doc                 |
| Binary attachments          | `docs/assets/<DocStem>/` — figures, diagrams, data files            |
| Index                       | `docs/QIDISTUDIO_KNOWLEDGE.md` — master manifest; update after each new doc |

---

## Knowledge Doc Quality Gate (Checklist)

Before a doc is considered complete, ALL must be true:

- [ ] H1 title matches filename (sans `.md`)
- [ ] One-sentence abstract present
- [ ] All equations use LaTeX (no Unicode math)
- [ ] All code is typed and syntactically valid
- [ ] At least one primary source cited per major claim
- [ ] `knowledge_validator.py` exit code = 0 (no hallucinations)
- [ ] `validation.json` committed alongside the doc
- [ ] `docs/QIDISTUDIO_KNOWLEDGE.md` manifest updated
- [ ] LanceDB reindexed after commit

---

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

| Purpose                                 | Command                                                                     |
| --------------------------------------- | --------------------------------------------------------------------------- |
| Compact manifest (all topics)           | `memory_env\Scripts\python.exe memory/inject.py`                            |
| Full text dump (everything verbatim)    | `memory_env\Scripts\python.exe memory/inject.py --full`                     |
| Semantic search                         | `memory_env\Scripts\python.exe memory/inject.py --query "cmake build"`      |
| Re-index docs to LanceDB                | `memory_env\Scripts\python.exe memory/extract.py`                           |
| Prompt/response daily stats             | `memory_env\Scripts\python.exe memory/prompt_store.py --daily-stats`        |
| Unsynced pairs (pending LanceDB)        | `memory_env\Scripts\python.exe memory/prompt_store.py --unsynced`           |
| Sync prompts→LanceDB (now in Stop hook) | `memory_env\Scripts\python.exe memory/sync_prompts_to_lancedb.py`           |
| Run daily LanceDB dedup manually        | `memory_env\Scripts\python.exe memory/daily_lancedb_dedupe.py`              |
| Push prompt to LangSmith Hub            | `memory_env\Scripts\python.exe memory/push_prompt.py`                       |
| Push ALL agent prompts to Hub           | `memory_env\Scripts\python.exe agents/push_all_prompts.py`                  |
| Re-install deps                         | `.\memory_env\Scripts\python.exe -m pip install -r memory\requirements.txt` |
| Run agent fleet                         | `memory_env\Scripts\python.exe agents/orchestrator.py "your request"`       |
| List recent fleet runs                  | `memory_env\Scripts\python.exe -m agents.run_store`                         |
| Structured log (agents + rows)          | `memory_env\Scripts\python.exe -m agents.run_store --log`                   |
| Latest run drilldown (per-agent)        | `memory_env\Scripts\python.exe -m agents.run_store --latest-detail`         |
| Show latest run result                  | `memory_env\Scripts\python.exe -m agents.run_store --latest`                |
| Show specific run                       | `memory_env\Scripts\python.exe -m agents.run_store -r <run_id>`             |
| Filter by fleet                         | `memory_env\Scripts\python.exe -m agents.run_store -f dev_fleet -n 5`       |

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

## 🤖 Agentic Fleet Protocol

> **Mandatory reading.** These rules govern every interaction with the four-agent fleet.
> Violating them causes wasted tokens, duplicate work, or silent failures.

### 1 — Agent Roles (decision table)

| Agent        | Use when you need to…                                                     | Do NOT use for…                         |
| ------------ | ------------------------------------------------------------------------- | --------------------------------------- |
| `researcher` | Find facts, read docs, web-search specs, audit external APIs/libraries    | Writing or modifying project files      |
| `builder`    | Write/edit Python, C++, CMake, JSON, fix bugs, implement features         | Research without a concrete code output |
| `verifier`   | Audit code for correctness, type safety, edge cases, security, lint       | Writing new code (verdict only)         |
| `scribe`     | Persist facts/decisions/learnings to LanceDB; update copilot-instructions | Code changes or research                |

Assign **one task per agent per dispatch**. If a job needs multiple roles, give each role its own task — the director will fan them out in parallel.

### 2 — Invocation Methods

**CLI (fire-and-forget, redirect output to a file):**

```powershell
# Always redirect — never use captureOutput or wait synchronously
memory_env\Scripts\python.exe agents/orchestrator.py "task string here" `
  2>&1 | Tee-Object agents\_my_task_out.txt
```

**From terminal tool (non-blocking pattern):**

```powershell
# Send to a named terminal; read the output file as a separate step
memory_env\Scripts\python.exe -B agents/orchestrator.py "task string here" > agents\_out.txt 2>&1; echo DONE >> agents\_out.txt
```

**Python API (inside another script):**

```python
from agents.orchestrator import run
result = run("your natural-language task here")
print(result["final_response"])
```

### 3 — Writing Effective Task Strings

The director LLM (Gemini 2.5 Flash) decomposes your string into typed `AgentTask` objects.
Give it enough context to make the right assignments.

**Good task string anatomy:**

```
[VERB] [SUBJECT] [CONSTRAINT/GOAL] [OUTPUT FORMAT]

Examples:
  "Audit agents/parts_catalog/schema.py for non-Optional int/float fields
   that Gemini might return as strings; report every field name and model class"

  "Fix LeadScrew.starts to accept 'single'/'double' strings;
   write a @field_validator; verify syntax; output patched schema.py snippet"

  "Persist to LanceDB: root cause = Pydantic rejects null from Gemini;
   fix = model_validator strips None before validation; topic = parts-catalog-schema"
```

**Anti-patterns to avoid:**

- Too vague: `"fix the schema"` — director can't plan without knowing what's wrong
- Too broad: `"research everything about CNC parts and then fix all the code"` — split into two dispatches
- No output expectation: always state what you want back (snippet, verdict, LanceDB write, etc.)

### 4 — Parallel Dispatch Pattern

When a problem needs research + implementation + verification, dispatch all three at once:

```powershell
# Terminal: agentcomms — parallel fan-out
memory_env\Scripts\python.exe -B agents/orchestrator.py `
  "Task 1 for researcher: [describe]; Task 2 for builder: [describe]; Task 3 for verifier: [describe]" `
  > agents\_parallel_out.txt 2>&1; echo DONE >> agents\_parallel_out.txt
```

The orchestrator's `Send` API runs all three as a single LangGraph superstep — true parallel.
Copilot should then read all output files in one parallel batch.

### 5 — Output File Conventions

> **PRIMARY STORE: PostgreSQL `agent_runs` table.**
> Every `orchestrator.run()` and `dev_fleet.run_fleet()` call automatically persists its
> full result (all agent outputs as JSONB) to this table BEFORE returning. Text files are
> ephemeral terminal output only — do NOT rely on them across sessions.

**Query results — always from Postgres, not from text files:**

```powershell
# List latest 10 runs (raw blob view)
memory_env\Scripts\python.exe -m agents.run_store

# Structured fleet_runs summary table (agents, rows collected, duration)
memory_env\Scripts\python.exe -m agents.run_store --log

# Drilldown: latest run with per-agent detail
memory_env\Scripts\python.exe -m agents.run_store --latest-detail

# Latest result (full final_response text)
memory_env\Scripts\python.exe -m agents.run_store --latest

# Specific run drilldown (all agent prompts + rows)
memory_env\Scripts\python.exe -m agents.run_store -d <run_id>

# Specific run raw blobs
memory_env\Scripts\python.exe -m agents.run_store -r <run_id>

# Filter to dev_fleet only, last 5
memory_env\Scripts\python.exe -m agents.run_store --log -f dev_fleet -n 5
```

```python
# From Python (in any script or subagent)
from agents.run_store import get_latest_fleet_run, list_fleet_runs, get_fleet_run

# Structured summary for latest run
run = get_latest_fleet_run()
print(run['subject'], 'agents:', run['agent_count'], 'rows:', run['total_rows'])
for a in run['agents']:
    print(f"  {a['agent_id']:20s} rows={a['rows_collected']} prompt={a['task_prompt'][:60]}")

# Raw blob (legacy)
from agents.run_store import get_latest_run, list_runs
run = get_latest_run()
print(run['final_response'])
```

| Optional secondary artifact | File path (terminal stdout only — may not exist) |
| --------------------------- | ------------------------------------------------ |
| Fleet run stdout log        | `agents\_<short_label>_out.txt`                  |
| Dev fleet team output       | `agents\_fleet_alpha_out.txt` etc.               |

The `echo DONE` pattern is still useful for terminal _completion signaling_, but
never use it as the authoritative source of agent output data.

### 6 — Health Check (run before any fleet work)

```powershell
memory_env\Scripts\python.exe agents/_agentcomms_check.py > agents\_health.txt 2>&1
```

Expected output (all lines must be present):

```
researcher : CompiledStateGraph
builder    : CompiledStateGraph
verifier   : CompiledStateGraph
scribe     : CompiledStateGraph
coder      : CompiledStateGraph
tester     : CompiledStateGraph
dev_fleet  : CompiledStateGraph
gemini ping: ONLINE
postgres   : ready
langsmith  : connected
```

If any line is missing or shows an error, **do not dispatch fleet tasks** — diagnose first.

### 7 — When Copilot MUST Use the Fleet

These situations require a fleet dispatch (do not attempt inline):

| Situation                                      | Dispatch to        |
| ---------------------------------------------- | ------------------ |
| Multi-file code audit (>3 files)               | verifier           |
| Web research on library/spec/hardware          | researcher         |
| Schema fix + syntax verify + persist to memory | builder + scribe   |
| Parts catalog harvester debugging              | builder + verifier |
| Any change to LanceDB knowledge base           | scribe             |
| Anything requiring Google Search grounding     | researcher         |

### 8 — Reading Fleet Results

**ALWAYS read from Postgres — not from text files.** Text files are destroyed when terminals
close (e.g. during conversation summarization). The `agent_runs` table is durable.

```powershell
# Standard pattern: dispatch → wait for DONE signal → query Postgres
memory_env\Scripts\python.exe -B agents/orchestrator.py "task" > agents\_out.txt 2>&1; echo DONE >> agents\_out.txt

# Check completion
Select-String "DONE" agents\_out.txt

# Read results from Postgres (NOT from _out.txt)
memory_env\Scripts\python.exe -m agents.run_store --latest
```

The `_out.txt` file only signals _completion_ — all actual content is in Postgres.
Sub-agent results are stored under `agent_results` JSONB column (one entry per agent/team).

If the file is large, tail the end:

```powershell
Get-Content agents\_my_task_out.txt -Tail 40
```

### 9 — Common Failure Modes

| Symptom                                        | Cause                                   | Fix                                                   |
| ---------------------------------------------- | --------------------------------------- | ----------------------------------------------------- |
| `ModuleNotFoundError: agents`                  | Wrong venv or wrong CWD                 | Use `memory_env\Scripts\python.exe`, CWD = repo root  |
| No output file created                         | Process crashed before first write      | Check stderr: `agents\_my_task_out.txt` for traceback |
| "no results" / output file disappeared         | Terminal closed (e.g. summarization)    | Query Postgres: `python -m agents.run_store --latest` |
| `GOOGLE_API_KEY not set`                       | `.env` not loaded                       | Confirm `.env` exists at repo root with key set       |
| `google.api_core.exceptions.ResourceExhausted` | Gemini quota hit (free tier)            | Wait 60 s or switch to `gemini-2.0-flash`             |
| Agent returns empty `final_response`           | Director couldn't parse task string     | Make task string more explicit (see §3)               |
| `Unexpected argument 'tools'`                  | LangChain/google-genai version mismatch | Harmless info log — ignore                            |
| `AFC Remote call N exceeded_limit`             | Automatic Function Calling info log     | Harmless — not an error                               |
| Stale `.pyc` causes AttributeError             | Python bytecode cache out of date       | Always run with `-B` flag: `python -B ...`            |

---

## 🧑‍💻 Dev Fleet Protocol (Coder/Tester Teams)

> Use this fleet for any coding task. Named teams (Alpha, Beta, Gamma) work in
> parallel. Each team runs a coder→tester iteration loop until tests pass or budget exhausts.
> All learnings are persisted to LanceDB after every team completes.

### Quick Start

```powershell
# Single task — director assigns to best team
memory_env\Scripts\python.exe -B agents/dev_fleet.py "Implement X feature" `
  > agents\_fleet_alpha_out.txt 2>&1; echo DONE >> agents\_fleet_alpha_out.txt

# Force a specific team
memory_env\Scripts\python.exe -B agents/dev_fleet.py "Fix Y bug" --teams Alpha `
  > agents\_fleet_alpha_out.txt 2>&1; echo DONE >> agents\_fleet_alpha_out.txt

# Multi-task fan-out (director assigns Alpha/Beta/Gamma automatically)
memory_env\Scripts\python.exe -B agents/dev_fleet.py `
  "Task 1: implement schema fix; Task 2: add unit tests; Task 3: update docs" `
  > agents\_fleet_out.txt 2>&1; echo DONE >> agents\_fleet_out.txt

# Python API
from agents.dev_fleet import run_fleet
result = run_fleet("Implement X", teams=["Alpha"], max_iterations=3)
print(result["final_report"])
```

### Team Architecture

```
Fleet Director (Gemini 2.5 Flash)
  ├─ Team Alpha: coder (Pro) ──→ tester (Pro/Vision) ──┐
  ├─ Team Beta:  coder (Pro) ──→ tester (Pro/Vision) ──┤ ← true parallel
  └─ Team Gamma: coder (Pro) ──→ tester (Pro/Vision) ──┘
                                         ↑ iterate on FAIL (max 5)
```

### Coder → Tester Signal Protocol

The Coder always outputs a JSON signal:

```json
{
  "status": "code_ready",
  "changes": [
    { "file": "...", "operation": "edit|create|delete", "content": "..." }
  ],
  "test_instructions": {
    "type": "python|cpp|cmake|shell",
    "command": "memory_env\\Scripts\\python.exe -B -m pytest agents/... -v",
    "expected_behavior": "All N tests pass",
    "visual_check": "optional path to image for Gemini Vision"
  },
  "iteration": 1,
  "prior_failure": null
}
```

The Tester always outputs a JSON verdict:

```json
{
  "status": "PASS|FAIL|ERROR|VISUAL_FAIL",
  "counts": { "passed": 12, "failed": 0, "errors": 0 },
  "failures": [
    { "test_name": "...", "type": "...", "coder_hint": "specific fix" }
  ],
  "next_action": "pass|fix_and_retry|escalate"
}
```

### Output Files

> **PRIMARY: PostgreSQL `agent_runs` table** — `fleet='dev_fleet'`, all team results as JSONB.
> Query with `python -m agents.run_store -f dev_fleet --latest` — survives terminal closures.

| Secondary artifact (stdout only) | Contents                                                 |
| -------------------------------- | -------------------------------------------------------- |
| `agents/_fleet_alpha_out.txt`    | Alpha team stdout (may not exist after session restarts) |
| `agents/_fleet_beta_out.txt`     | Beta team stdout                                         |
| `agents/_fleet_gamma_out.txt`    | Gamma team stdout                                        |
| `agents/_test_out_alpha_N.txt`   | Raw test output for iteration N                          |

**Structured log queries** (the right way to inspect past runs):

```powershell
# Top-level summary: all fleet runs, agents used, rows collected
memory_env\Scripts\python.exe -m agents.run_store --log

# Per-agent drilldown for the latest run (prompts, rows, pass/fail per team)
memory_env\Scripts\python.exe -m agents.run_store --latest-detail

# Same for a specific run
memory_env\Scripts\python.exe -m agents.run_store -d <run_id>
```

### When to Use Dev Fleet vs Agentic Fleet

| Situation                           | Use                                    |
| ----------------------------------- | -------------------------------------- |
| Implement a new feature / fix a bug | **Dev Fleet** (dev_fleet.py)           |
| Research + implement + verify       | **Dev Fleet** (handles all internally) |
| Research only, no code changes      | Agentic Fleet (orchestrator.py)        |
| Persist facts to LanceDB            | Agentic Fleet scribe agent             |
| Code audit without changes          | Agentic Fleet verifier agent           |

---

## Minimal Reference (in case memory is unavailable)

- **Build source**: `C:\QIDISrc\QIDIStudio\build\`
- **Install dir** : `C:\QIDISrc\QIDIStudio\install_dir\`
- **Deps destdir** : `C:\QIDIDeps\usr\local` — **actual pre-built deps install prefix** (NOT `deps/build/destdir`). `CMakePresets.json` `CMAKE_PREFIX_PATH` must point here.
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

## Active Projects

| Project                          | Repo                                | Spec                                                                    | Status                                                      |
| -------------------------------- | ----------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------- |
| QIDIStudio (C++ slicer fork)     | `phantom-man/QIDIStudio`            | —                                                                       | Active                                                      |
| NexusSlicer Viewer (VS Code ext) | `phantom-man/NexusSlicer` (pending) | —                                                                       | Active — WebGPU PBR viewer, 3-axis precision rotation panel |
| **NexusMill** (VS Code ext)      | `phantom-man/NexusMill` (to create) | [`docs/private/NEXUSMILL_SPEC.md`](../docs/private/NEXUSMILL_SPEC.md)   | **Spec complete — awaiting Phase 1 kick-off**               |
| **NexusGauge** (VS Code panel)   | built into NexusSlicer              | [`docs/private/NEXUSGAUGE_SPEC.md`](../docs/private/NEXUSGAUGE_SPEC.md) | **Spec complete — awaiting Phase 2 NexusSlicer impl**       |
| NexusWorkshop (extension pack)   | —                                   | See NexusMill spec §11                                                  | Bundles NexusSlicer + NexusMill + NexusGauge                |

### NexusMill — 30-second summary

Virtual CNC construction simulator. Emulates real stepper motors (NEMA 17/23/34), real drivers
(TB6600 → DMA860S), and real lead screws (TR8×1 ACME → SFU2005 ball screw).
At NEMA 23 + DMA860S/÷200 + TR8×1: **25 nm step resolution** (nanometer territory).

Key differentiators no one else has:

- **Timeline rewind + branch** — catastrophic failure → rewind to any prior step, re-engineer, replay
- **Full hardware stack emulation** — motor torque curves, driver microstepping tables, lead screw efficiency, backlash compensation
- **VS Code native** — same workspace, same AI pipeline, free, offline, MIT
- **Precision dials everywhere** — the same micrometer-control UI from NexusSlicer's rotation panel applies to every numeric parameter

Full spec: [`docs/private/NEXUSMILL_SPEC.md`](../docs/private/NEXUSMILL_SPEC.md)

### NexusGauge — 30-second summary

Computational metrology engine embedded in the NexusSlicer 3D viewport. Runs the **Dimensional
Digester** on any STL/3MF: auto-classifies every surface into typed features (bores, bosses,
fillets, planes, freeform NURBS), names them, and draws color-coded annotation lines in the
viewport. Hover a hole rim → get diameter, circumference, thread detection. Select multiple
features → get the full distance/angle/GD&T relationship matrix. See sub-visual deviations
(< 50 µm) invisible to the naked eye via a per-triangle heat map. Export as `.nexusgauge.json`
(vectorized — full parametric reconstruction), DXF, CSV, CadQuery script, or PDF inspection
report.

Key differentiators:

- **Mathematical curve display** — curvature κ(t), torsion τ(t), NURBS equation, slope/inflection
- **Sub-visual error detection** — 1 µm flatness errors shown as color map; human eye threshold ~300 µm
- **Vectorization** — reduces a 50K-triangle mesh to ~200 lines of parametric JSON; recreatable in any CAD tool
- **GD&T callout generation** — ISO 1101-compliant tolerance symbols from any relationship pair
- **Free, offline, VS Code native** — no CMM machine, no subscription

Full spec: [`docs/private/NEXUSGAUGE_SPEC.md`](../docs/private/NEXUSGAUGE_SPEC.md)

---

> **DO NOT append learnings to this file.** Learnings live in Postgres (`prompts`/`responses` tables).
> The 30-min sync job (`sync_prompts_to_lancedb.py`) pushes them to LanceDB automatically.
> To record a learning, include a `COMPACTION_SUMMARY` block in your response — the Stop hook persists it.
