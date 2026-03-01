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

## Agent fleet protocol

Full protocol: `docs/AGENT_PROTOCOL.md` — read it before invoking any sub-agent.

**When to invoke the fleet** (use `agents/orchestrator.run(request, thread_id?)`):

- Live web research needed (library API, upstream commit check, external bug lookup) → `researcher`
- Complex multi-file C++/Python/CMake implementation → `builder` + `verifier`
- Session learnings to persist in LanceDB → `scribe`
- Any combination of the above in one logical task → full fleet (director decomposes automatically)

**When NOT to invoke the fleet**:

- Single-file reads/edits → direct tools
- Git operations → GitKraken tools
- Question answered by the LanceDB manifest already in context → answer directly
- Anything satisfiable in ≤ 3 tool calls → do it directly

**How to invoke** (in a Python code snippet or terminal):

```python
import sys; sys.path.insert(0, r'C:\Users\User\source\repos\QIDIStudio')
from agents.orchestrator import run
print(run("your request", thread_id="slug-001"))
```

**Thread ID convention**: `<scope>-<slug>-<nnn>` e.g. `texture-lscm-fix-001`  
**Auth**: Vertex AI ADC (not API key) — `gcloud auth application-default login`  
**Memory venv**: `memory_env\Scripts\python.exe` for all memory/agent commands

## External docs/tools

- Use Context7 for up-to-date third-party library docs before changing dependency APIs.

## Session Learnings Log

Canonical table lives in `memory/langsmith_prompt.md §7`. Append new rows here **and** there after every significant session. Run `python memory/extract.py` then commit.

| Date       | Category       | Topic                                      | Decision                                                                                                                                                                                                        | Rationale                                                                                                     |
| ---------- | -------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 2026-02-28 | build_system   | C++ standard not globally enforced         | No `CMAKE_CXX_STANDARD` on GUI target; `libslic3r` sets C++17 only under GCC condition; fix: add `set(CMAKE_CXX_STANDARD 20)` + `CMAKE_CXX_STANDARD_REQUIRED ON` + `CMAKE_CXX_EXTENSIONS OFF` after `project()` | Without explicit standard MSVC may silently compile at C++14 default; C++20 features break without warning    |
| 2026-02-28 | build_system   | C++20 safe on MSVC 2022; C++26 not         | MSVC 2022 17.x has complete C++20 and mostly-complete C++23; C++26 (contracts P2900, static reflection P2996, `std::simd` P1928, `inplace_vector` P0843) has zero MSVC support                                  | Do NOT set `cxx_std_26` in production builds; C++23 acceptable for new files only                             |
| 2026-02-28 | architecture   | Modernization score 43/100                 | Codebase scored 43/100; documented in `docs/CPP_MODERNIZATION_SCORE.md` and §21 of `docs/QIDISTUDIO_KNOWLEDGE.md`                                                                                               | Baseline for tracking C++ modernization roadmap progress                                                      |
| 2026-02-28 | cpp_gotcha     | boost::thread in GCodeSender obsolete      | `src/libslic3r/GCodeSender.cpp:110` uses `boost::thread`; replace with `std::jthread` (C++20) for automatic join + `std::stop_token` cancellation                                                               | `std::jthread` eliminates manual join/detach RAII boilerplate; `boost::thread` redundant on C++20             |
| 2026-02-28 | cpp_gotcha     | No RAII GL wrappers; raw GLuint members    | All GL objects are raw `GLuint` members; add `GLResource.hpp` with `template<auto Creator, auto Deleter>` + Rule of Five + `std::exchange(o.id, 0)` move pattern (~50 lines)                                    | Prevents GL resource leaks; single template covers all GL object types                                        |
| 2026-02-28 | cpp_gotcha     | Non-DSA OpenGL throughout                  | All GL uses legacy bind-to-modify (`glBindBuffer`+`glBufferData`); DSA (`glNamedBufferData`) available on GL 4.5 (hardware since 2012)                                                                          | DSA eliminates bind-state boilerplate and reduces GL state mutation bugs                                      |
| 2026-02-28 | cpp_gotcha     | No SIMD geometry; use Google Highway       | BVH, slice-plane, UV compute all scalar; use Google Highway (Chromium/libjxl); `std::simd`/`<simd>` P1928 have zero production compiler support                                                                 | Highway portable across AVX2/NEON/SVE; never use `std::simd` until C++26 compilers ship                       |
| 2026-02-28 | cpp_gotcha     | std::ranges views no MSVC vectorization    | Dan Lemire Oct 2025: `views::filter\|transform` chained pipelines break contiguous-iterator contract on MSVC x64; `ranges::sort`/`ranges::find` algorithm overloads are fine                                    | Avoid chained view pipelines in mesh compute hot paths                                                        |
| 2026-02-28 | cpp_gotcha     | std::expected available now                | `std::expected<T,E>` (C++23) supported on MSVC VS2022 17.3+, GCC 12+, Clang 16+; codebase has 3 incompatible error styles (bool, exception, -1.0f sentinel)                                                     | Adopt `std::expected` for all new parse/IO functions                                                          |
| 2026-02-28 | cpp_gotcha     | Move ctors need noexcept for vector        | `std::vector` falls back to copy on realloc if move ctor is not `noexcept`; verify `TriangleMesh`, `ModelObject`, `ModelVolume` move ctors                                                                      | Silently causes O(n) copy on every vector growth in mesh processing loops                                     |
| 2026-02-28 | build_system   | CMakePresets.json missing                  | No `CMakePresets.json` in repo; add `msvc-relwithdebinfo` and `msvc-asan` presets committed to repo                                                                                                             | Enables one-command configure in CI and new dev machines; eliminates per-machine flag drift                   |
| 2026-02-28 | build_system   | clang-tidy not in CI                       | No `.clang-tidy` config; add: `modernize-use-override`, `bugprone-use-after-move`, `performance-move-const-arg`, `modernize-use-nullptr`, `cppcoreguidelines-pro-type-member-init`                              | These 5 checks catch the most common UB and performance regressions introduced during active development      |
| 2026-02-28 | cpp_gotcha     | std::map for config lookup is O(log n)     | Config option lookup uses `std::map<std::string, ConfigOption*>` (O(log n)); replace with `std::unordered_map` for O(1) amortized                                                                               | Hot path called on every config key access during slicing                                                     |
| 2026-02-28 | build_system   | #pragma once migration pending             | 99% of headers use `#ifndef/#define` guards; only `QDTUtil.hpp` uses `#pragma once`; single Python regex pass migrates all; MSVC 2022 fully supports it                                                         | `#pragma once` guarantees include-guard optimization; eliminates ODR bugs from mismatched guard macros        |
| 2026-02-28 | implementation | C++20 standard IMPLEMENTED                 | `set(CMAKE_CXX_STANDARD 20)` + `REQUIRED ON` + `EXTENSIONS OFF` added to `CMakeLists.txt` after `project(QIDIStudio)`; score Language Standard: 4→6/10                                                          | Global enforcement via root CMakeLists is the safest approach; per-target overrides for mcut/earcut preserved |
| 2026-02-28 | implementation | CMakePresets.json IMPLEMENTED              | `CMakePresets.json` created with 5 presets: `base`, `msvc-release`, `msvc-relwithdebinfo`, `msvc-asan`, `msvc-tests`; score Build System: 3→7/10                                                                | Eliminates per-developer CMakeCache drift; enables `cmake --preset msvc-relwithdebinfo` one-liner             |
| 2026-02-28 | implementation | .clang-tidy IMPLEMENTED                    | `.clang-tidy` created with bugprone-use-after-move, bugprone-suspicious-memset as WarningsAsErrors; modernize-_ + performance-_ as warnings; HeaderFilterRegex targets only src/libslic3r + src/slic3r          | Tier 1 (errors) vs Tier 2 (warnings) split prevents noisy CI while catching real bugs                         |
| 2026-02-28 | implementation | boost::thread REPLACED with jthread        | `GCodeSender.hpp` now includes `<thread>` + `<boost/thread/mutex.hpp>` (not full `<boost/thread.hpp>`); member changed to `std::jthread`; `.swap(t)` → `= std::move(t)`; thread lambda uses `std::stop_token`   | `std::jthread` auto-joins on destruction; stop_token enables future cooperative cancellation                  |
| 2026-02-28 | implementation | noexcept move ctors ADDED to TriangleMesh  | `TriangleMesh(TriangleMesh&&) noexcept = default` + `operator=(TriangleMesh&&) noexcept = default` + explicit copy ops added for Rule-of-Five symmetry                                                          | `std::vector<TriangleMesh>` now uses O(1) move on reallocation; previously fell back to O(n) copy             |
| 2026-02-28 | implementation | GLResource.hpp RAII wrappers CREATED       | `src/slic3r/GUI/GLResource.hpp` — `template<auto Creator, auto Deleter> class GlResource` with Rule of Five; `GlBuffer`, `GlVao`, `GlFramebuffer`, `GlRenderbuffer`, `GlTexture` typedefs using DSA creators    | Template covers all GL object types in ~130 lines; DSA glCreate* not glGen* for OpenGL 4.5 correctness        |
| 2026-02-28 | implementation | [[nodiscard]] ADDED to parse/IO APIs       | `TriangleMesh.hpp`: from_stl, ReadSTLFile, write_ascii, write_binary, volume(); `Format/STL.hpp`: all load_stl, store_stl; `Format/AMF.hpp`: load_amf — all now [[nodiscard]]                                   | Compiler will warn on ignored return values at every call site; catches silent parse failure bugs             |
| 2026-02-28 | implementation | #pragma once PILOTED on format headers     | `Format/STL.hpp` and `Format/AMF.hpp` converted from #ifndef guards to #pragma once; `scripts/migrate_pragma_once.py` created for bulk migration with --dry-run + --backup options                              | Run `python scripts/migrate_pragma_once.py --dry-run` to preview full migration across all src/\*.hpp         |
| 2026-02-28 | architecture   | Modernization score 43->54/100             | After P1+P2 implementation: Language 4->6, BuildSystem 3->7, Concurrency 6->7, TypeSafety 4->5, ErrorHandling 4->5, GL 4->5, CodeQuality 5->6; total 43->54/100 C-grade                                         | Score updated in CPP_MODERNIZATION_SCORE.md; next target: P3 Google Highway SIMD + enable SLIC3R_BUILD_TESTS  |
| 2026-02-28 | cpp_gotcha     | Config.hpp sorted-map iteration dependency | `options: std::map<t_config_option_key, unique_ptr<ConfigOption>>` has exposed `cbegin()/cend()` API; changing to unordered_map would break alphabetical serialization order in save-to-JSON                    | Defer until a full Config serialization audit confirms iteration order is not depended upon                   |
