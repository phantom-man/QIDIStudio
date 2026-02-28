# QIDIStudio Copilot Instructions

## Scope and mental model

- This repo is a QIDIStudio fork (C++ slicer app + Python Blender texture pipeline + local AI/memory tooling).
- Core app code lives in `src/`; texture/displacement pipeline lives in `resources/scripts/apply_texture_bpy.py` and is called from `src/slic3r/GUI/Plater.cpp`.
- `resources/` is runtime-critical: many GUI and calibration paths resolve via `Slic3r::resources_dir()` (`src/libslic3r/utils.cpp`).

## High-impact architecture boundaries

- C++ UI integration: texture actions (`apply_texture`, `adjust_texture_depth`) in `src/slic3r/GUI/Plater.cpp` export mesh -> run Blender -> reimport STL -> update volume + sidecar metadata.
- Python pipeline strategy: `_classify_mesh_topology()` drives projection mode (`object` vs `lscm`) using mesh features and `MeshClass`; avoid part-name heuristics.
- Debug telemetry contract: `--debug-snapshots` writes stage JSON + `session_summary.json`; downstream analyzers (`scripts/ai_texture_critic.py`) depend on these field names.
- Agent tooling boundary: `agents/orchestrator.py` is a LangGraph supervisor (director -> parallel researcher/builder/verifier/scribe); memory injection is in `memory/inject.py`.

## Build and test workflow (Windows-first)

- CMake on Windows is constrained (`CMakeLists.txt` rejects versions >= 4.0 for MSVC/WIN32).
- Default optional targets are OFF: `SLIC3R_BUILD_TESTS`, `SLIC3R_BUILD_SANDBOXES`, `SLIC3R_PERL_XS`.
- Enable C++ tests by configuring with `-DSLIC3R_BUILD_TESTS=ON`, then run `ctest` from the build tree.
- Typical debug config uses `scripts/debug_build.ps1` (RelWithDebInfo + ASan, separate build/install dirs).

## Blender texture pipeline workflow

- Blender executable discovery uses `QIDI_BLENDER_EXE` first (`Plater.cpp`, `scripts/run_texture_pipeline.ps1`).
- Current C++ behavior is fail-fast when Blender is missing (no `bpy_env` fallback in `find_bpy_python()` path).
- For standalone pipeline repro use `scripts/run_texture_pipeline.ps1`; use `-Debug` to wait for debugpy attach.
- Use `scripts/ai_debug_pipeline.py` to regression-check mesh classification behavior across known 3MF cases.

## Resource-path convention (do not break)

- The app consumes scripts/resources from install-time `resources/`; dev workflow uses an NTFS junction created by `scripts/dev_setup.ps1`.
- If texture script edits appear ignored after a clean build, re-run `scripts/dev_setup.ps1` before changing C++.

## Practical editing rules for this codebase

- Keep C++/Python contracts stable: output markers (`SKIN_OUTPUT:`), sidecar `.texture.json` keys, and snapshot JSON schema are consumed cross-component.
- Prefer surgical edits near existing strategy points (`MeshClass` match/case, `Plater.cpp` texture command assembly) over introducing parallel paths.
- Preserve PowerShell script portability for this repo’s workflow scripts; avoid non-ASCII punctuation in quoted strings.

## Useful entry points

- `src/slic3r/GUI/Plater.cpp` — Blender command invocation and mesh replacement flow.
- `resources/scripts/apply_texture_bpy.py` — topology classifier, unwrap/projection, debug snapshot export.
- `scripts/run_texture_pipeline.ps1` — standalone Blender runner.
- `scripts/ai_debug_pipeline.py` / `scripts/ai_texture_critic.py` — autonomous debugging and quality diagnostics.
- `agents/orchestrator.py` / `memory/inject.py` — local agent fleet and LanceDB context injection.

## External docs/tools

- Use Context7 for up-to-date third-party library docs before changing dependency APIs.
