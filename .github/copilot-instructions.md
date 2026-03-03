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

## Session Learnings Log

Append rows here — `memory/extract.py` auto-indexes them into LanceDB.

| Date       | Category   | Topic             | Decision                                                  | Rationale                                                                                                     |
| ---------- | ---------- | ----------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 2026-03-03 | Infrastructure | Firebase deploy method | Use Firebase CLI (`firebase deploy --only hosting`) not REST API | REST API `populateFiles` endpoint hung consistently; CLI (Node.js HTTP) works reliably |
| 2026-03-03 | Infrastructure | Firebase project ID | Project ID is `nexuicer` (not `nexus-workshop` or `nexusslicer`) | Firebase auto-truncated "NexusSlicer" on project creation |
| 2026-03-03 | Infrastructure | Firebase site IDs | `nexuicer`, `nexuicer-desktop`, `nexusmill-app`, `nexusgauge-app` | Firebase requires site IDs; `-app` suffix used for mill/gauge due to name availability |
| 2026-03-03 | Infrastructure | Cloudflare DNS | `sites/cf_dns.py` automates all 7 CNAMEs; token in `.env`; `proxied: False` required until Firebase SSL certs provision | Full programmatic control via Cloudflare REST API |
| 2026-03-03 | Infrastructure | Cloudflare zones prerequisite | Domains must be **added to Cloudflare account** (Dashboard → Add a site) before `cf_dns.py` can create records | Token returning `errors=[], result=[]` = zones not in account, not a permissions issue |
| 2026-03-03 | Credentials | Cloudflare API token | Token stored as `CLOUDFLARE_API_TOKEN` in `.env`; email as `CLOUDFLARE_EMAIL` | `.env` is canonical creds store; token verified active |
