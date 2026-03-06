# Known Pipelines — QIDIStudio

> **Authoritative catalog of every automated pipeline in the QIDIStudio repository.**
> Every entry lists the entry-point, runtime environment, data stores consumed/produced,
> LangSmith project, health-check criteria, and expected output.
> Referenced by `scripts/startup_check.py` to verify system readiness.

---

## Table of Contents

| #   | Pipeline                                                | Entry-point                      | LangSmith Project          | Stores                                           |
| --- | ------------------------------------------------------- | -------------------------------- | -------------------------- | ------------------------------------------------ |
| 1   | [Agent Orchestrator](#1-agent-orchestrator)             | `agents/orchestrator.py`         | `qidistudio-agents`        | PG · LanceDB                                     |
| 2   | [Dev Fleet (Coder/Tester)](#2-dev-fleet-codertester)    | `agents/dev_fleet.py`            | `qidistudio-dev-fleet`     | PG · LanceDB                                     |
| 3   | [PhD Board of Directors](#3-phd-board-of-directors)     | `agents/phd_pipeline.py`         | `qidistudio-agents`        | LanceDB                                          |
| 4   | [Manufacturing Graph](#4-manufacturing-graph)           | `agents/manufacturing_graph.py`  | `qidistudio-manufacturing` | PG · LanceDB · LangSmith feedback                |
| 5   | [Filament Discovery](#5-filament-discovery)             | `agents/filament_pipeline.py`    | `qidistudio-manufacturing` | Firestore · GCS · BigQuery · Cloud SQL · LanceDB |
| 6   | [Nozzle Research](#6-nozzle-research)                   | `agents/nozzle_pipeline.py`      | `qidistudio-manufacturing` | BigQuery · Cloud SQL · LanceDB                   |
| 7   | [Slicer Profile Harvester](#7-slicer-profile-harvester) | `agents/slicer_harvester.py`     | `qidistudio-manufacturing` | GCS · Firestore                                  |
| 8   | [Autonomous Texture Loop](#8-autonomous-texture-loop)   | `scripts/autonomous_pipeline.py` | `qidistudio-agents`        | LanceDB · GCS                                    |
| 9   | [AI Debug Pipeline](#9-ai-debug-pipeline)               | `scripts/ai_debug_pipeline.py`   | `qidistudio-agents`        | LanceDB                                          |
| 10  | [Knowledge Validation](#10-knowledge-validation)        | `scripts/validate_all_docs.py`   | —                          | `docs/`                                          |
| 11  | [Memory Indexer](#11-memory-indexer)                    | `memory/extract.py`              | `QIDIStudio`               | LanceDB (GCS)                                    |
| 12  | [GCode Refiner](#12-gcode-refiner)                      | `GCodeRefiner/refiner.py`        | —                          | Local file I/O                                   |
| 13  | [Hardware Feedback Loop](#13-hardware-feedback-loop)    | `agents/hardware_feedback.py`    | `qidistudio-manufacturing` | LangSmith feedback · PyTorch JSONL               |
| 14  | [Trajectory Evaluator](#14-trajectory-evaluator)        | `agents/trajectory_eval.py`      | `qidistudio-dev-fleet`     | LangSmith feedback                               |
| 15  | [Print Monitor](#15-print-monitor)                      | `scripts/print_monitor.py`       | `qidistudio-agents`        | Klipper / Moonraker                              |
| 16  | [PhD Test Pipeline](#16-phd-test-pipeline)              | `scripts/phd_test_pipeline.py`   | —                          | PG · LanceDB · JSONL                             |

---

## 1. Agent Orchestrator

**File:** `agents/orchestrator.py`
**Runtime:** `memory_env\Scripts\python.exe` (Python 3.13)
**LangSmith project:** `qidistudio-agents`

### Architecture

Supervisor pattern with true parallel fan-out via LangGraph `Send` API:

```
START → plan (Gemini director) → dispatch ──┬── researcher
                                             ├── builder
                                             ├── verifier
                                             └── scribe
                                                  └── synthesize → END
```

All agent nodes execute as a single LangGraph superstep (parallel).
State is persisted via `PostgresSaver` (LangGraph checkpoint tables).

### Agent Roles

| Agent        | Responsibility                                                                  |
| ------------ | ------------------------------------------------------------------------------- |
| `researcher` | Tavily search + LanceDB RAG + arXiv/CrossRef queries                            |
| `builder`    | Gemini 2.5 Pro code generation + file edits                                     |
| `verifier`   | Code audit, type check, edge-case analysis                                      |
| `scribe`     | LanceDB upsert of learnings → `memory_env\Scripts\python.exe memory/extract.py` |

### Stores

- **PostgreSQL** (`PG_DSN`): LangGraph checkpoint `(checkpoints, writes, sends)` tables
- **LanceDB** (`LANCEDB_PATH = gs://qidistudio-lancedb/lancedb`): semantic memory retrieval (all agents)
- **LangSmith** (`LANGSMITH_API_KEY`): full trace for every run

### Health Criteria

- [ ] `agents.agents.get_agent("researcher")` returns `CompiledStateGraph` without error
- [ ] `agents.orchestrator.run("ping: reply ONLINE in one word")` completes in < 120 s
- [ ] Run persisted to `agent_runs` table in PostgreSQL
- [ ] LangSmith trace visible under project `qidistudio-agents`

### Usage

```powershell
memory_env\Scripts\python.exe -B agents/orchestrator.py "your task here" > agents\_out.txt 2>&1
```

---

## 2. Dev Fleet (Coder/Tester)

**File:** `agents/dev_fleet.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-dev-fleet`

### Architecture

Parallel named teams (Alpha / Beta / Gamma) with coder→tester iteration loop:

```
START → plan_teams → dispatch ──┬── Team Alpha: prime → coder → tester ──┐
                                 ├── Team Beta:  prime → coder → tester ──┤ → report → END
                                 └── Team Gamma: prime → coder → tester ──┘
```

Each team is independently resumable via PostgresSaver `thread_id`.
`agentevals` LLM-as-judge scores every trajectory and submits feedback to LangSmith.

### Coder→Tester Signal Protocol

- **Coder** emits `code_signal` JSON: `{status, changes[], test_instructions}`
- **Tester** emits `test_outcome` JSON: `{status, counts, failures[], next_action}`
- On `FAIL`: coder retries up to `max_iterations` (default 5)
- On `PASS`: scribe persists learnings to LanceDB

### Stores

- **PostgreSQL**: LangGraph checkpoints per team thread
- **LanceDB**: semantic priming (retrieved before first coder call)
- **LangSmith**: iteration trajectories + `evaluate_team_trajectory` feedback scores

### Health Criteria

- [ ] `agents.dev_fleet.build_fleet_graph()` returns compiled `CompiledStateGraph`
- [ ] `run_fleet("smoke test: return 42", teams=["Alpha"], max_iterations=1)` completes
- [ ] `fleet_runs` and `fleet_run_agents` tables queryable via `run_store`

### Usage

```powershell
memory_env\Scripts\python.exe -B agents/dev_fleet.py "Implement X" > agents\_fleet_alpha_out.txt 2>&1
```

---

## 3. PhD Board of Directors

**File:** `agents/phd_pipeline.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-agents`

### Architecture

Dialectical multi-agent loop implementing RAML (Retrieval-Augmented Machine Learning):

```
RAML priming (LanceDB prior failures)
   → librarian (deep RAG + Google Search)
        → skeptic (Popperian falsification)
             → synthesizer (cross-domain unification)
                  → [engineer] (code verification)
                       → scribe (persist to LanceDB)
                            → loop or exit
```

### RAML Pattern

Before every research cycle begins, `_retrieve_prior_failures()` queries LanceDB for
semantically similar past failure traces. This primes the librarian with known failure modes
before any web search, preventing repeated investigation of known dead ends.

### Stores

- **LanceDB** (`docs` table on `gs://qidistudio-lancedb/lancedb`): prior failures + research findings
- **LangSmith**: full dialectical trace per research question

### Health Criteria

- [ ] `agents.phd_pipeline.run_phd_research("smoke test")` returns non-empty `final_response`

### Usage

```powershell
.venv\Scripts\python.exe -m agents.phd_pipeline "How should topology classifier handle high-genus shapes?"
```

---

## 4. Manufacturing Graph

**File:** `agents/manufacturing_graph.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-manufacturing`

### Architecture

Cyber-Physical Feedback Loop as LangGraph `StateGraph`:

```
START → stress_analysis (PyTorch GNN)
             → route_by_stress ──── "redesign" → redesign_node → END
                                └── "texture"  → texture_node
                                                     → quality_gate ──── "pass"    → export_node → END
                                                                     └── "iterate" → texture_node (max 3×)
```

The state schema (`ManufacturingState`) holds both symbolic data (LLM-readable messages,
verdicts) and sub-symbolic data (stress tensors, UV stats, failure probability).

### Three-Layer Architecture

| Layer                   | Technology              | Role                          |
| ----------------------- | ----------------------- | ----------------------------- |
| Cognitive State         | LangGraph StateGraph    | WHY to act                    |
| Differentiable Kernel   | PyTorch (`torch_tools`) | HOW physics works             |
| Proprioceptive Feedback | LangSmith traces        | WHAT happened & WHAT to learn |

### Stores

- **PostgreSQL**: LangGraph checkpoints
- **LanceDB**: texture knowledge, part history
- **LangSmith**: per-node spans with tensor metadata (`hardware_feedback.py` closes the loop)

### Health Criteria

- [ ] `agents.manufacturing_graph.run_manufacturing_pipeline(stl_path, "smoke_part", "test")` completes
- [ ] LangSmith trace appears under `qidistudio-manufacturing`

---

## 5. Filament Discovery

**File:** `agents/filament_pipeline.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-manufacturing`

### Architecture

Background research pipeline. Discovers filament brands and materials via Tavily search

- Gemini extraction, then persists structured data to 5 separate stores.

```
discover_brands (Tavily) → for each brand:
    discover_materials (Gemini) → for each material:
        extract_settings (Gemini structured)
            ├── Firestore  — brands/{id}/materials/{id}
            ├── GCS        — gs://qidistudio-filaments/raw/{brand}/{material}.json
            ├── BigQuery   — qidistudio_research.raw_filament_scrapes
            ├── Cloud SQL  — filament_manufacturers + filaments tables
            └── LanceDB    — qidistudio_filaments table
```

**Progress checkpoint:** `gs://qidistudio-filaments/_progress/filament_pipeline.json`
(safe resume on interruption)

### Stores

- **Firestore**: `brands/{brand_id}/materials/{material_id}` (structured, queryable)
- **GCS** `gs://qidistudio-filaments/`: raw JSON dumps + progress checkpoint
- **BigQuery** `qidistudio_research.raw_filament_scrapes`: append-only audit trail
- **Cloud SQL** (via `PG_DSN`): `filament_manufacturers` + `filaments` tables
- **LanceDB**: description embeddings for semantic search

### Health Criteria

- [ ] Firestore write of test document succeeds
- [ ] GCS `gs://qidistudio-filaments/` bucket is readable + writable
- [ ] BigQuery dataset `qidistudio_research` exists and table is appendable
- [ ] `filament_manufacturers` table exists in Cloud SQL

---

## 6. Nozzle Research

**File:** `agents/nozzle_pipeline.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-manufacturing`

### Architecture

Comprehensive nozzle knowledge builder. Researches every nozzle type (40+ seed slugs)
via Tavily web search + Gemini structured extraction. Evaluated via `ResearchEvaluator`
(LLM-as-judge) before writing.

```
for nozzle_slug in SEED_NOZZLES:
    research_session (Gemini + Tavily)
        → ResearchEvaluator (LLM-as-judge: PASS / FAIL / NEEDS_IMPROVEMENT)
        → [PASS] → write to BigQuery + Cloud SQL + LanceDB
```

### LangSmith Integration

Every `research_session()` call is `@traceable`. `ResearchEvaluator.evaluate()` writes
quality scores as `LangSmith run feedback` to `qidistudio-manufacturing`.

### Stores

- **BigQuery** `qidistudio_research.raw_nozzle_research`
- **Cloud SQL**: `nozzle_types` + `nozzle_filament_settings` tables
- **LanceDB**: nozzle knowledge for `researcher` agent semantic search

### Health Criteria

- [ ] `agents.nozzle_pipeline` imports without error
- [ ] `--dry-run` flag prints plan without API calls

---

## 7. Slicer Profile Harvester

**File:** `agents/slicer_harvester.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-manufacturing`

### Architecture

Downloads machine/printer profiles from 9 major open-source slicers via GitHub API
(using `GITHUB_TOKEN`), normalizes them, and persists to GCS + Firestore.

```
for each SLICER in [OrcaSlicer, BambuStudio, PrusaSlicer, SuperSlicer,
                    Cura, ideaMaker, Klipper, Marlin, Duet]:
    download_profiles (GitHub API, GITHUB_TOKEN)
        → normalize (extract comm_protocol, host_type, gcode templates)
        → GCS:        gs://qidistudio-filaments/slicer-profiles/{slicer}/{machine}/{file}
        → Firestore:  printers/{machine_slug}
```

**Progress checkpoint:** `gs://qidistudio-filaments/_progress/slicer_harvester.json`

### Stores

- **GCS** `gs://qidistudio-filaments/slicer-profiles/`: raw profile files
- **Firestore**: `printers/{machine_slug}` — normalized machine records

### Health Criteria

- [ ] GitHub API call with `GITHUB_TOKEN` returns 200 (rate limit check)
- [ ] GCS write to `gs://qidistudio-filaments/` succeeds

---

## 8. Autonomous Texture Loop

**File:** `scripts/autonomous_pipeline.py`
**Runtime:** `memory_env\Scripts\python.exe` (Vertex AI ADC required)
**LangSmith project:** `qidistudio-agents`

### Architecture

Gemini 2.5 Computer Use Preview drives a recursive vision-action loop:

```
VisualizerComputer.render() → PNG bytes
    → Gemini (computer-use-preview, Vertex AI global)
         → function_call (run_texture_pipeline | rotate_view | adjust_param | approve_and_export)
              → execute call → re-render → loop
```

Max iterations configurable (default 12). `--dry-run` skips Gemini calls.

### Authentication

Requires **Vertex AI ADC** (not Google API key):

```powershell
gcloud auth application-default login
```

Model: `gemini-2.5-flash` on `location="global"` (Computer Use requires global endpoint).

### Stores

- **LanceDB**: writes approved texture configurations
- **GCS**: optional export of approved texture assets

### Health Criteria

- [ ] `gcloud auth application-default print-access-token` succeeds (ADC configured)
- [ ] `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` set in `.env`
- [ ] `--dry-run` completes without error

---

## 9. AI Debug Pipeline

**File:** `scripts/ai_debug_pipeline.py`
**Runtime:** `.venv\Scripts\python.exe` or `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-agents`

### Architecture

AI-driven texture debugging pipeline. Renders 3D part snapshots, passes them to Gemini
vision for diagnosis, proposes and applies fixes, reruns until quality gate passes.

```
render_snapshots (PyVista) → ai_texture_critic (Gemini vision)
    → diagnose_failures → apply_fixes → re-render
         → quality_gate: PASS → export | FAIL → retry (max 4 cases)
```

### Stores

- **LanceDB**: reads known failure patterns; writes diagnosed issues + fixes

### Health Criteria

- [ ] PyVista headless render succeeds (`pyvista.start_xvfb()` or off-screen on Windows)
- [ ] `scripts/ai_debug_pipeline.py` imports without error

---

## 10. Knowledge Validation

**File:** `scripts/validate_all_docs.py` (calls `scripts/knowledge_validator.py`)
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** — (standalone batch job, no LangSmith tracing)

### Architecture

Batch validation of all documents in `docs/`:

```
for each .md in docs/:
    DocumentParser.parse() → ClaimExtractor (Gemini LLM or regex fallback)
        → KnowledgeValidator.validate():
            parallel queries: CrossRef · arXiv · PubMed · MathWorld · NIST ·
                              Semantic Scholar · Wikipedia · Tavily
        → confidence score per claim
        → flag conf < 0.40 as hallucination → LLM correction
        → write {doc}_validated.md + {doc}.validation.json
→ aggregate to docs/HALLUCINATION_REPORT.md + docs/hallucinations.json
```

### Stores

- **`docs/`** directory: reads source docs, writes `_validated.md` and `.validation.json`
- **`docs/HALLUCINATION_REPORT.md`**: consolidated human-readable report
- **`docs/hallucinations.json`**: machine-readable aggregation

### Health Criteria

- [ ] `GOOGLE_API_KEY` set (for LLM claim extraction)
- [ ] `memory_env` has `arxiv`, `beautifulsoup4`, `pdfplumber`, `google.genai` installed
- [ ] `python -m scripts.knowledge_validator --help` prints usage

---

## 11. Memory Indexer

**File:** `memory/extract.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `QIDIStudio`

### Architecture

Reads three canonical knowledge sources, chunks them by heading, embeds with
`sentence-transformers` (all-MiniLM-L6-v2), and upserts to LanceDB on GCS.

```
Sources:
  .github/copilot-instructions.md  → split by ## / ### heading
  docs/QIDISTUDIO_KNOWLEDGE.md     → split by ## / ### heading
  memory/langsmith_prompt.md       → split by ## / ### heading

→ sentence-transformers embedding
→ lancedb.connect("gs://qidistudio-lancedb/lancedb")
→ table.add() / upsert by topic  (idempotent)
```

Also reads from: `memory/inject.py` (semantic query) · `memory/prompt_store.py` (PostgreSQL)
· `memory/sync_prompts_to_lancedb.py` (30-min sync job).

### Stores

- **LanceDB** `gs://qidistudio-lancedb/lancedb` — `documents` table (topic / decision / content / source / category)
- **PostgreSQL** `prompts` + `responses` tables — conversation history (prompt_store.py)

### Health Criteria

- [ ] `lancedb.connect("gs://qidistudio-lancedb/lancedb")` succeeds
- [ ] `table = db.open_table("documents"); len(table)` > 0 (seeded)
- [ ] `memory_env\Scripts\python.exe memory/inject.py --query "test"` returns results
- [ ] PostgreSQL `prompts` + `responses` tables exist and are queryable

---

## 12. GCode Refiner

**File:** `GCodeRefiner/refiner.py`
**Runtime:** `.venv\Scripts\python.exe` (Python 3.13) or any system Python 3.10+
**LangSmith project:** — (pure local processing, no LLM/network calls)

### Architecture

Feature-aware parameter injector for FDM G-code. Invoked as a QIDISlicer
post-processing script or standalone CLI:

```
parse_gcode (GcodeTools or raw comment parser)
    → detect features (;TYPE:... slicer comments)
         → apply_rules (per-feature profile overrides: M104, M106, G1 F)
              → CatastrophicChecker (safety gate: temperature bounds, retraction limits)
                   → write modified gcode (in-place)
```

`GCodeRefiner/llm_optimizer.py` optionally wraps LangChain `ChatGoogleGenerativeAI`
for AI-suggested rule generation (offline fallback always available).

### Stores

- **Local file system**: reads `*.gcode`, writes modified `*.gcode` in-place
- **`GCodeRefiner/rules/`**: JSON rule files per machine/material profile

### Health Criteria

- [ ] `python GCodeRefiner/refiner.py --dry-run` prints plan for a synthetic gcode
- [ ] `GCodeRefiner.refiner` module imports without error in `.venv`

---

## 13. Hardware Feedback Loop

**File:** `agents/hardware_feedback.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-manufacturing`

### Architecture

Closes the cyber-physical loop by annotating LangSmith traces with real print outcomes:

```
record_print_outcome(run_id, success, notes, photo_paths)
    → LangSmith Client.create_feedback(run_id, key="print_outcome", score=1|0)
         → attach photos as run attachments
              → if not success: tag run with failure metadata

export_failure_dataset(min_failures)
    → LangSmith filter: feedback.key="print_outcome" AND score=0
         → export as JSONL
              → torch_tools.fine_tune_stress_gnn(jsonl)  ← PyTorch retraining
```

### Stores

- **LangSmith** feedback API: per-run `print_outcome` tags
- **PyTorch JSONL**: fine-tuning dataset for `MeshStressGNN`

### Health Criteria

- [ ] `LangSmith Client().create_feedback(...)` API callable
- [ ] `agents.hardware_feedback` imports without error

---

## 14. Trajectory Evaluator

**File:** `agents/trajectory_eval.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** `qidistudio-dev-fleet`

### Architecture

LLM-as-judge invoked automatically after every dev_fleet team run:

```
[after team completes iteration loop]
    evaluate_team_trajectory(team_name, task, iteration_history, final_status)
        → Gemini judge (domain-specific 3D parts prompt)
             → score: {overall:bool, convergence_rate:float, iterations:int, reasoning:str}
                  → LangSmith Client.create_feedback(run_id, key="trajectory_quality")
```

### Stores

- **LangSmith** feedback: `trajectory_quality` per team run

### Health Criteria

- [ ] `agents.trajectory_eval.evaluate_team_trajectory(...)` importable and callable

---

## 15. Print Monitor

**File:** `scripts/print_monitor.py`
**Runtime:** `memory_env\Scripts\python.exe` (preferred) or `.venv`
**LangSmith project:** `qidistudio-agents`

### Architecture

Live monitoring of a Klipper/Moonraker printer via HTTP polling + Gemini analysis:

```
LOOP:
    Moonraker REST API → print_stats + extruder temps + position
        → Gemini analysis (anomaly detection, flow rate check)
             → if anomaly: alert + LangSmith trace annotation
                  → optionally: pause / emergency stop (M600 / M112)
```

Supports dual auth: `GOOGLE_API_KEY` (direct) or ADC (Vertex AI).

### Stores

- **LangSmith**: anomaly traces with telemetry annotations
- **Moonraker HTTP API**: read-only polling + optional write commands

### Health Criteria

- [ ] `scripts.print_monitor` imports without error
- [ ] Moonraker endpoint reachable (optional — printer may be offline)

---

## 16. PhD Test Pipeline

**File:** `scripts/phd_test_pipeline.py`
**Runtime:** `memory_env\Scripts\python.exe`
**LangSmith project:** — (results written directly to Postgres + JSONL)

### Architecture

Autonomous multi-group test orchestrator. Runs all 9 test groups sequentially (or a
specified subset), attempts autonomous rectification of failures via `dev_fleet.py`, and
persists every result to Postgres + JSONL + LanceDB.

```
phd_test_pipeline.py
  ├─ Group A: Python import / smoke tests (32 tests)
  ├─ Group B: Agent fleet functional tests (6 tests)
  ├─ Group C: Pipeline end-to-end tests (9 tests)
  ├─ Group D: TypeScript / VS Code extension tests (8 tests)
  ├─ Group E: C++ / CMake build-gate tests (9 tests)
  ├─ Group F: Vision / aesthetic tests (6 tests)
  ├─ Group G: Database integrity tests (7 tests)
  ├─ Group H: API connectivity tests (8 tests)
  └─ Group I: File / asset existence tests (80+ checks)

Per-test flow:
  run_group_X() → PASS → record ✅
                → FAIL → RectificationAgent.attempt_fix() (up to 3×)
                              ↓ dev_fleet.py dispatched → re-test
                         PASS → record ✅  |  BLOCKED → record ❌

RunSummary → persist_results()
  ├─ Postgres: phd_test_results (one row per test)
  ├─ JSONL:    logs/phd_test_runs/YYYY-MM-DD.jsonl
  └─ LanceDB:  best-effort summary upsert (documents table)
```

### Usage

```powershell
# All groups
memory_env\Scripts\python.exe -B scripts/phd_test_pipeline.py

# Specific groups (fast smoke test)
memory_env\Scripts\python.exe -B scripts/phd_test_pipeline.py --groups I,E,A --no-rectify

# API + database only
memory_env\Scripts\python.exe -B scripts/phd_test_pipeline.py --groups H,G --no-rectify

# Plan only (no execution)
memory_env\Scripts\python.exe -B scripts/phd_test_pipeline.py --dry-run

# Include hardware-gated tests (npm/tsc required)
memory_env\Scripts\python.exe -B scripts/phd_test_pipeline.py --groups D --include-hardware
```

### Stores

- **PostgreSQL**: `phd_test_results` table (auto-created — group, test_id, status, duration, error)
- **JSONL**: `logs/phd_test_runs/YYYY-MM-DD.jsonl` (one summary object per run)
- **LanceDB**: `documents` table (best-effort upsert of run summary text)

### Health Criteria

- [ ] All Group I asset-existence checks pass (80+ files present)
- [ ] All Group E C++ header/source/shader checks pass
- [ ] All Group A Python import checks pass
- [ ] Group G database: LanceDB ≥ 100 rows, Postgres `agent_runs` ≥ 1 row
- [ ] Group H API: Gemini, LangSmith, GitHub, HuggingFace all reachable

---

## Pipeline Dependency Map

```
LanceDB (GCS) ──────────────── All pipelines (RAG memory)
PostgreSQL (PG_DSN) ─────────── 1,2,4,11 (LangGraph checkpoints)
LangSmith ───────────────────── 1–9, 13–14 (tracing + feedback)
Vertex AI ADC ───────────────── 1–9, 15 (Gemini model calls)
GOOGLE_API_KEY ──────────────── 10, 15 (direct API fallback)
Firestore ───────────────────── 5, 7 (structured object store)
BigQuery ────────────────────── 5, 6 (audit trail)
GCS (qidistudio-filaments) ──── 5, 7 (raw dumps + checkpoints)
Google Search (Gemini grounded) ── 1, 3, 5, 6 (web search via GOOGLE_API_KEY)
GITHUB_TOKEN ────────────────── 7, 16 (GitHub API for profile download / H4 test)
HF_TOKEN ────────────────────── 11, 16 (sentence-transformers model download / H5 test)
```

---

## Required Environment Variables

| Variable                         | Used By     | Purpose                                   |
| -------------------------------- | ----------- | ----------------------------------------- |
| `LANGSMITH_API_KEY`              | All         | LangSmith trace auth                      |
| `LANGSMITH_TRACING`              | All         | Enable/disable tracing (must be `true`)   |
| `LANGCHAIN_API_KEY`              | All         | Alias for LANGSMITH_API_KEY               |
| `LANGSMITH_ENDPOINT`             | All         | `https://api.smith.langchain.com`         |
| `LANGSMITH_WORKSPACE_ID`         | All         | Workspace scoping                         |
| `GOOGLE_CLOUD_PROJECT`           | 1–9, 15     | Vertex AI project `crafty-hook-483415-b3` |
| `GOOGLE_CLOUD_LOCATION`          | 1–9, 15     | `us-central1`                             |
| `GOOGLE_API_KEY`                 | 10, 15      | Direct Gemini API (non-ADC fallback)      |
| `PG_DSN`                         | 1, 2, 4, 11 | PostgreSQL `postgresql://...`             |
| `LANCEDB_PATH`                   | All         | `gs://qidistudio-lancedb/lancedb`         |
| `GOOGLE_API_KEY`                 | 1, 3, 5, 6  | Google Search via Gemini grounding        |
| `HF_TOKEN`                       | 11          | sentence-transformers download            |
| `GITHUB_TOKEN`                   | 7           | GitHub API (slicer profiles)              |
| `CLOUDFLARE_API_TOKEN`           | sites/      | DNS management                            |
| `CLOUDFLARE_EMAIL`               | sites/      | DNS management                            |
| `TP_LINK_USERNAME/PASSWORD/HOST` | scripts/    | Router configuration                      |

---

## Virtual Environment Map

| venv          | Python | Location                                                           | Primary use                                          |
| ------------- | ------ | ------------------------------------------------------------------ | ---------------------------------------------------- |
| `memory_env`  | 3.13   | `memory_env\Scripts\python.exe`                                    | Agent fleet, LanceDB, LangSmith, Gemini              |
| `.venv`       | 3.13   | `.venv\Scripts\python.exe`                                         | 3D mesh, texture, GCodeRefiner, Blender-free scripts |
| `bpy_env`     | 3.11   | `bpy_env\Scripts\python.exe`                                       | Blender `bpy` package only                           |
| System Python | 3.13   | `C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe` | General scripts                                      |

**Note on `memory_env`:** This environment intentionally does **not** have a `pip.exe`
shim. Always use `memory_env\Scripts\python.exe -m pip` for package management.
