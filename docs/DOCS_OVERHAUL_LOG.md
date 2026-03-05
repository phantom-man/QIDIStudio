# QIDIStudio Docs Overhaul — Master Log

> **Created:** 2026-03-05  
> **Executor:** GitHub Copilot (Claude Sonnet 4.6)  
> **Linked from:** [QIDISTUDIO_KNOWLEDGE.md](QIDISTUDIO_KNOWLEDGE.md)

---

## Full Execution Plan

This log tracks a complete overhaul of the `docs/` directory.

### Phase 1 — Fix & Save Three Open Documents

Fix `.md` standards compliance in the three currently-open docs (remove conversational openers, ensure proper H1 title, frontmatter-free body, consistent heading hierarchy). Save to disk.

### Phase 2 — Replace Three Docs in LanceDB

Delete the three original LanceDB entries by document name. Re-index the fixed versions using `memory/extract.py`.

### Phase 3 — Sync QIDISTUDIO_KNOWLEDGE.md (Round 1)

Absorb any knowledge from the 3 fixed docs that was missing or inaccurate in `QIDISTUDIO_KNOWLEDGE.md`. Remove stale references.

### Phase 4 — Texture Pipeline Alignment

Compare `resources/scripts/apply_texture_bpy.py`, `scripts/ai_debug_pipeline.py`, `agents/prompts/vision_beauty_critic.md` against `PhD-Level Texture Application in 3D.md`, `PhD-Level 3D Texturing with Libraries.md`, `Advanced Texture Wrapping for CAD.md`. Identify gaps. Implement required changes.

### Phase 5 — Rewrite All Other Docs at PhD Level

For every remaining `.md` in `docs/` (excluding this log, `QIDISTUDIO_KNOWLEDGE.md`, `private/`): completely rewrite at PhD level, remove ads/promotional language, add high-level code examples, apply consistent `.md` standards, apply best current research understanding.

### Phase 6 — Replace All Docs in LanceDB

Delete all old entries by document name. Re-run `memory/extract.py` to re-index all rewritten documents.

### Phase 7 — Final QIDISTUDIO_KNOWLEDGE.md Audit

Audit `QIDISTUDIO_KNOWLEDGE.md` against all newly rewritten docs. Edit it to be in complete alignment. Add link back to this log file.

### Phase 8 — Commit

Git commit all changes with structured message.

---

## Master Checklist

### Phase 1 — Fix Three Open Docs

- [x] `PyTorch, LangChain, and Cyber-Physical Graphs.md` — remove opener, fix H1
- [x] `PhD-Level Texture Application in 3D.md` — remove opener, fix H1
- [ ] `PhD-Level 3D Texturing with Libraries.md` — already has H1, confirm standards

### Phase 2 — LanceDB (3 docs)

- [ ] Delete `PyTorch, LangChain, and Cyber-Physical Graphs` from LanceDB
- [ ] Delete `PhD-Level Texture Application in 3D` from LanceDB
- [ ] Delete `PhD-Level 3D Texturing with Libraries` from LanceDB
- [ ] Re-index all 3 via `memory/extract.py`

### Phase 3 — KNOWLEDGE.md Round 1

- [x] Absorb UV distortion theory (LSCM, ARAP, ABF++) into §texture pipeline section (already in §15)
- [x] Absorb PBR texture channel math (Cook-Torrance BRDF, NDF, G-term, Fresnel) — **§23.1–§23.4 added 2026-06-09**
- [x] Absorb CPG topology + LangGraph state-machine architecture — **§23.8, §23.10 added 2026-06-09**
- [x] Absorb PyTorch distributed (DDP, FSDP, torch.compile) knowledge — **§23.9 added 2026-06-09**
- [x] Absorb library layer taxonomy (GPU Runtime / Math / Asset Pipeline / Rendering) — **§23.5–§23.7 added 2026-06-09**
- [ ] Remove stale or ad-contaminated content — deferred to Phase 7

### Phase 4 — Texture Pipeline Alignment

- [x] Audit `apply_texture_bpy.py` UV unwrap against ARAP/LSCM standards — **confirmed, conical taper fix applied 2026-06-09**
- [x] Audit cylinder projection tile_size calibration (E_D=230 bug root cause) — **root cause: conical sections, NOT scale; fix: `_mesh_is_conical()` + LSCM fallback; implemented 2026-06-09**
- [ ] Audit `ai_debug_pipeline.py` critic thresholds against Cook-Torrance BRDF theory
- [ ] Audit `vision_beauty_critic.md` Fourier metrics against Texture Application doc §VI
- [ ] Check mip chain generation in pipeline (EWA vs box filter)
- [ ] Check sRGB gamma handling in preview renders vs PBR spec
- [x] Implement E_D=230 UV conical-taper fix — **`_mesh_is_conical()` + LSCM fallback added to `apply_texture_bpy.py` 2026-06-09**

### Phase 5 — Rewrite Docs (58 total minus 3 already fixed, log, knowledge.md, private/)

See "Phase 5 — Individual Document Status" section below.

### Phase 6 — LanceDB (all docs)

- [x] Delete all old entries — **done 2026-06-09 (replace_all=True in batch_upsert)**
- [x] Re-index all via `memory/extract.py` — **done 2026-06-09: 534 rows indexed, 606 total in store (72 agent-sourced rows preserved)**

### Phase 7 — KNOWLEDGE.md Final Audit

- [ ] Cross-reference all rewritten docs vs KNOWLEDGE.md sections
- [ ] Add link to this log file

### Phase 8 — Commit

- [ ] Git commit

---

## Phase 5 — Individual Document Status

| Document                                                    | Status    | Key Enhancement Areas                  |
| ----------------------------------------------------------- | --------- | -------------------------------------- |
| `3D Printing Physics-Informed Function.md`                  | ☐ pending | FEM/topology optimization, SIMP method |
| `3D Projection Jacobian Accuracy.md`                        | ☐ pending | Differentiable rendering Jacobians     |
| `3D_Viewer_Code_Review_Report.md`                           | ☐ pending | Vulkan/PBR corrections                 |
| `Advanced Python Transform Pipelines.md`                    | ☐ pending | Numba/JAX/MLIR pipelines               |
| `Advanced Texture Wrapping for CAD.md`                      | ☐ pending | ARAP, xAtlas, industrial cal           |
| `AGENT_MEMORY_WIRING.md`                                    | ☐ pending | LangGraph checkpointer patterns        |
| `AGENT_PROTOCOL.md`                                         | ☐ pending | Multi-agent supervisor architecture    |
| `AI Debugging 3D Texture Mapping.md`                        | ☐ pending | Differentiable UV debug                |
| `AI Debugging Texture Mapping Glitches.md`                  | ☐ pending | Critic + heuristic framework           |
| `AI Debugging Visual Geometry Pipeline.md`                  | ☐ pending | ViL pipeline                           |
| `AI PhD Knowledge Acquisition Pipeline.md`                  | ☐ pending | RAG + LanceDB architecture             |
| `AI PhD-Level Problem Solving Framework 2.md`               | ☐ pending | HAVEN + PSV loop                       |
| `AI PhD-Level Problem Solving Framework.md`                 | ☐ pending | System 1/2 cognition                   |
| `AI's PhD-Level Thermal Dissipation Design.md`              | ☐ pending | Heat equation FEA                      |
| `AI-Controlled 3D Print Optimization.md`                    | ☐ pending | Bayesian optimization                  |
| `AI-Driven Visual Debugging Orchestration.md`               | ☐ pending | Orchestrator + LangGraph               |
| `AI-Powered Cyber-Physical Feedback Loop.md`                | ☐ pending | CPG + GNN                              |
| `AMEO-Technical-Reference.md`                               | ☐ pending | AMEO extrusion math                    |
| `Autonomous AI Agent Architecture Blueprint.md`             | ☐ pending | Agent topology                         |
| `Autonomous Morphomorphic Extrusion Optimization (AMEO).md` | ☐ pending | AMEO algorithm                         |
| `Beauty Score.md`                                           | ☐ pending | Fourier symmetry + spectral entropy    |
| `Computational Metrology for Phone Chassis.md`              | ☐ pending | GD&T, ISO 1101                         |
| `Computational Metrology PhD Manuscript.md`                 | ☐ pending | Feature extraction, NURBS              |
| `CPP_MODERNIZATION_SCORE.md`                                | ☐ pending | C++23 modernization                    |
| `Cylindrical Texturing for 3D Models.md`                    | ✓ done    | Cylinder UV math                       |
| `Debugging C++ and Python Systems.md`                       | ☐ pending | Sanitizers, rr, py-spy                 |
| `DESKTOP_COMMANDER_MCP.md`                                  | ☐ pending | MCP protocol                           |
| `Directing LLMs_ Advanced Techniques.md`                    | ☐ pending | Constitutional AI, DSPy                |
| `displacement-texture-research.md`                          | ☐ pending | Displacement + tessellation            |
| `G-Code Volumetric Flow Auditing.md`                        | ☐ pending | Volumetric flow math                   |
| `Geometric Shape Classification via Spectral DNA.md`        | ☐ pending | Shape DNA, Laplace-Beltrami            |
| `GPU Agnostic Computing Standards.md`                       | ☐ pending | SYCL/oneAPI/HIP                        |
| `Inverse Rendering_ Jacobian and Loss.md`                   | ☐ pending | Mitsuba3, diff rendering               |
| `Klipper Macro for AMEO Optimization.md`                    | ☐ pending | Klipper Jinja2 macros                  |
| `Klipper Optimization for QIDI Q2.md`                       | ☐ pending | Input shaping, pressure advance        |
| `Measuring Aethetics.md`                                    | ☐ pending | Leder's B(s,σ), perceptual metrics     |
| `Multi-GPU Build Configuration.md`                          | ☐ pending | NCCL, NVLink topology                  |
| `PhD G-code Failure Analysis.md`                            | ☐ pending | Volumetric error model                 |
| `PhD Research Project Architecture Guide.md`                | ☐ pending | Research methodology                   |
| `PhD Thesis_ Differentiable Rendering Pipeline.md`          | ☐ pending | Mitsuba3/drjit                         |
| `PhD Whitepaper_ Inverse Graphics Framework.md`             | ☐ pending | Neural inverse graphics                |
| `PhD-Level 3D Model Perfection.md`                          | ☐ pending | Mesh optimization theory               |
| `PhD-Level 3D Model Representation.md`                      | ☐ pending | Implicit/explicit + neural             |
| `PhD-Level 3D Printing Optimization.md`                     | ☐ pending | Process optimization                   |
| `PhD-Level AI Knowledge Acquisition Pipeline.md`            | ☐ pending | RAG + LanceDB                          |
| `PhD-Level Hybrid Debugging Workflow.md`                    | ☐ pending | Hybrid debug stacks                    |
| `Phone Case Metrology & Texture Morphing.md`                | ☐ pending | Metrology + morphing                   |
| `POCO X6 Pro Manufacturing Research.md`                     | ☐ pending | Manufacturing specs                    |
| `Python-GPU Bridge with SYCL.md`                            | ☐ pending | SYCL Python bindings                   |
| `Shape Classification for Transformation Methods.md`        | ☐ pending | Topology classifier                    |
| `Spectral Shape Analysis and Transforms.md`                 | ☐ pending | Spectral methods                       |
| `SYCL_ GPU-Agnostic C++ Pipeline.md`                        | ☐ pending | oneAPI/DPC++                           |
| `Symmetry and Beauty_ A PhD Perspective.md`                 | ☐ pending | Mathematical aesthetics                |
| `Technical Search for 3D Printer Nozzles.md`                | ☐ pending | Nozzle materials/geometry              |

---

## Findings Log

### 2026-03-05 — Phase 1 Initiated

**`PyTorch, LangChain, and Cyber-Physical Graphs.md`**

- Issue: File begins with conversational opener "This will be a long but rewarding ride. Let's go deep." — not a valid `.md` document header.
- Action: Remove opener, add proper `# PyTorch, LangChain, and Cyber-Physical Graphs` H1 title.
- Status: Fixed ✓

**`PhD-Level Texture Application in 3D.md`**

- Issue: File begins with "This is a rich domain touching mathematics, physics, perception science, and GPU architecture simultaneously. Let's go deep." — not a valid `.md` document header.
- Action: Remove opener, ensure main H1 is `# PhD-Level Texture Application in 3D Parts`.
- Status: Fixed ✓

**`PhD-Level 3D Texturing with Libraries.md`**

- Issue: None — already starts with `# PhD-Level 3D Texturing with Libraries`.
- Action: Verify internal structure consistency.
- Status: Confirmed compliant ✓

### 2026-03-05 — Phase 4 Texture Pipeline Alignment Findings

**UV Scale Bug (nozzle_lower — E_D=230)**

- Root cause from docs: `_calculate_uv_stretch_metrics` is likely measuring stretch _after_ the `su/sv` scaling multiply. The cylinder UV branch applies `su = circumference / tile_size` and `sv = height / tile_size` to the raw `[0,1]` Blender cylinder unwrap. If stretch is measured on the scaled UV instead of the canonical `[0,1]` UV, mean_stretch blows up proportionally with `su`.
- Fix: Move stretch metric calculation to run on the pre-scale UV coordinates. Or normalize the UV back to `[0,1]` before computing stretch.
- Docs alignment gap: UV parameterization docs specify that `E_ARAP` and `E_C` should be computed on the intrinsic parameterization, not on the scaled texture-space coordinates.

**PBR Channel Compliance**

- Current pipeline: EEVEE_NEXT renders with "skin material". Docs specify albedo must be `GL_SRGB8_ALPHA8` (sRGB) and all computation must happen in linear light space.
- Gap: Need to verify EEVEE_NEXT material node graph is properly using linear albedo input (not sRGB in shader math).

**Mip Chain**

- Current pipeline: No explicit mip generation step in preview render.
- Docs requirement: Proper mip chain via EWA/Lanczos3 filter for production textures.

### 2026-06-09 — Phase 3 Complete: §23 Added to KNOWLEDGE.md

**§23 PhD-Level Texture & ML Reference** added — 11 sub-sections:

- §23.1: Cook-Torrance BRDF (GGX NDF, Smith G, Schlick Fresnel, energy conservation)
- §23.2: PBR texture channel specs (albedo sRGB, roughness, metallic, normal BC5, height 16-bit, AO indirect-only, emissive HDR)
- §23.3: GPU texture compression codecs (BC1/3/4/5/6H/7 + ASTC with use cases)
- §23.4: EWA anisotropic filtering + mip LOD λ formula
- §23.5: Vulkan image layout transitions + pipeline barrier code example
- §23.6: xAtlas UV atlas pipeline + texelsPerUnit density normalization
- §23.7: OIIO + OCIO color-managed texture pipeline + ORM channel packing
- §23.8: LangGraph typed state (TypedDict + add_messages reducer + PostgresSaver checkpointing)
- §23.9: torch.compile TorchDynamo/AOTAutograd/Inductor/Triton pipeline
- §23.10: CPG hybrid automata + Fiedler λ₂ algebraic connectivity + structural controllability
- §23.11: Cross-reference table → primary docs + sections

### 2026-06-09 — Phase 4 Fix: E_D=230 UV Conical-Taper Bug

**Root cause confirmed:** UV stretch metric `s_i = (a3_i * total_uv) / (au_i * total_3d)` is scale-invariant (su\*sv cancels). Actual bug: `vacuum_nozzle_lower` is a tapered frustum (REVOLUTION shape with varying XY radius along Z-axis). Blender `cylinder_project` applied to cone/frustum faces produces near-zero UV triangle area (`au_i ≈ 0`) for intermediate-Z faces → `s_i → ∞` → `E_D = 230`.

**Fix implemented (`apply_texture_bpy.py`):**

1. Added `_mesh_is_conical(obj, taper_threshold=0.20)` helper — O(V) algorithm: splits Z-range into top/bottom halves, computes XY bounding-circle radius for each, returns True if radii differ by >20%.
2. In `case MeshClass.REVOLUTION:` block: after setting `projection = "cylinder"`, call `_mesh_is_conical(obj)`. If True → override `projection = "lscm"` with log message.
3. Result: `vacuum_nozzle_lower` (frustum shape) will now use LSCM instead of cylinder_project → E_D should drop from 230 to <50.

Files modified:

- `resources/scripts/apply_texture_bpy.py` — +60 lines (`_mesh_is_conical` function + REVOLUTION case update)
- Pipeline context: Preview renders are 1024×1024 snapshots, not shipped textures. Mip generation is required in the actual texture export path, not the debug preview.

**Fourier Beauty Metrics (vision_beauty_critic.md)**

- Current: `S = Σ|Re(F)|² / Σ|F|²`, `Hₛ = -Σ p·log₂(p)`, PASS: S > 0.90 & Hₛ > 4.0
- Docs: §VI (Procedural Textures) confirms spectral entropy framework. The Fourier symmetry score maps to Perlin noise band-limiting (power spectrum 1/f²). Valid.
- No changes needed.

---

## Phase 5 Progress

_(Updated as docs are rewritten)_

---

## Phase 6 LanceDB Re-index Log

_(Updated after each doc is re-indexed)_

---

## Phase 7 KNOWLEDGE.md Audit Findings

_(Updated during final audit)_

---

_This log is auto-linked from [QIDISTUDIO_KNOWLEDGE.md](QIDISTUDIO_KNOWLEDGE.md) — see §22 Docs Overhaul._
