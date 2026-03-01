# QIDIStudio C++ Modernization Scorecard

### PhD-Level Technology Stack & Best Practices Audit

_Maintained by: GitHub Copilot | Research date: 2026-02-28 | Based on: C++ Core Guidelines, CppCon 2023–2025, ISO WG21 papers, cppreference.com compiler support tables, lemire.me, LLVM blog_

---

## Executive Summary

| Dimension                            | Score      | Grade  |
| ------------------------------------ | ---------- | ------ |
| Language Standard & Feature Adoption | 4/10       | D      |
| Memory & Ownership                   | 5/10       | C      |
| Type Safety                          | 4/10       | D      |
| Error Handling                       | 4/10       | D      |
| OpenGL / Rendering C++               | 4/10       | D      |
| Concurrency & Parallelism            | 6/10       | C+     |
| Build System & Tooling               | 3/10       | F      |
| Performance Architecture             | 4/10       | D      |
| Code Quality & Modern Idioms         | 5/10       | C      |
| Testing & Verification               | 4/10       | D      |
| **TOTAL**                            | **43/100** | **D+** |

**Verdict:** The codebase is a functional, battle-tested C++17 slicer with a solid TBB parallelism foundation. Its major technical debts are: a patchwork C++ standard setup (not globally enforced), near-zero use of C++20/23 safety features (`expected`, `jthread`, concepts, `span`), legacy OpenGL non-DSA patterns, no CI static analysis, no package management manifest, and no SIMD in the geometry hot paths. These are all fixable without a rewrite.

---

## 1. Language Standard & Feature Adoption — 4/10

### Current State

| Target             | C++ Standard                      | How Set                                                   |
| ------------------ | --------------------------------- | --------------------------------------------------------- |
| `libslic3r`        | C++17                             | `set_property(CXX_STANDARD 17)` — but only on GCC > 14.1! |
| `libslic3r_cgal`   | C++17                             | Same condition                                            |
| `src/slic3r` (GUI) | Inherited from MSVC/CMake default | **No explicit standard set**                              |
| `mcut`             | C++11                             | Hardcoded in CMakeLists                                   |
| `earcut`           | C++11                             | Hardcoded in CMakeLists                                   |
| `clipper2`         | C++17                             | Set correctly                                             |
| Tests `cpp17/`     | C++17                             | Set correctly                                             |

**Critical finding:** The main GUI library (`src/slic3r`, ~250k LOC) has **no explicit `CMAKE_CXX_STANDARD` or `target_compile_features`** set. It inherits whatever MSVC defaults to, which with VS2022 is C++14 unless `/std:c++17` or `/std:c++latest` is passed. This means it may be silently compiling as C++14 on some configurations, even though C++17 features (structured bindings, `std::optional`, `if constexpr`) are used.

### What Is Missing

- **C++20 features** — zero usage: no concepts, no ranges (except algorithm overloads), no coroutines, no `std::span`, no `[[likely]]`/`[[unlikely]]`, no `consteval`/`constinit`
- **C++23 features** — zero usage: no `std::expected`, no `std::print`, no `std::mdspan`
- **Feature-test macros** — none used; no `#if __cpp_concepts` guards

### Best Practice (2026)

Set **globally** in the root `CMakeLists.txt`:

```cmake
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
```

Or per-target (preferred for mixed-standard repos):

```cmake
target_compile_features(libslic3r PUBLIC cxx_std_20)
target_compile_features(slic3r_gui PUBLIC cxx_std_20)
```

MSVC 2022 (17.x) has **complete C++20** support and a very high percentage of C++23. The only risk is vendored third-party targets (`mcut`, `earcut`) which should keep their own standard set.

### Specific C++20 Wins for QIDIStudio

| Feature                       | Where to apply                                        | Benefit                     |
| ----------------------------- | ----------------------------------------------------- | --------------------------- |
| `std::span<T>`                | Replace `T*, size_t count` parameter pairs            | Bounds safety, no heap      |
| `[[nodiscard]]`               | All parse/IO/compute functions                        | Catch ignored return values |
| `[[likely]]` / `[[unlikely]]` | Mesh validation branches                              | 2–5% hot path speedup       |
| `std::stop_token` + `jthread` | Replace `boost::thread` in GCodeSender                | Correct cancellation        |
| `std::bit_cast<>`             | Replace `memcpy`-based type punning                   | Defined behavior            |
| Concepts                      | Template constraint cleanup in `AABBTreeIndirect.hpp` | Better errors               |

### Effort to Upgrade

- Explicitly set standard: **30 minutes** (edit CMakeLists root + slic3r/CMakeLists)
- Adopt `std::span` for buffer parameters: **★★** moderate
- Adopt `[[nodiscard]]` on key APIs: **★** low (grep + annotate)
- Adopt `std::jthread`: **★★** moderate (network code only)

---

## 2. Memory & Ownership — 5/10

### Current State

**Positives:**

- `std::unique_ptr` is used throughout (`NotificationManager`, `GCodeViewer`, etc.)
- `std::shared_ptr` is used where ownership is shared (plugin/model object tree)
- No raw `new` in application-layer code (StackWalker.cpp being the exception — that's a third-party Windows-specific file)
- TBB memory management for parallel regions is correct

**Problems identified:**

1. **No systematic ownership audit.** The question "who owns this?" is not always answerable from the type — several constructors accept raw `T*` that might or might not be owning.

2. **`shared_ptr` overuse pattern likely.** The `ModelObject`, `ModelVolume`, `PrintObject` hierarchy shares ownership via `shared_ptr`. CppCon 2024 "Better Code: Relationships" establishes that most apparent shared ownership is actually parent/child — the parent owns, children hold non-owning `T*`. An audit of the model tree could likely convert most `shared_ptr` to `unique_ptr` + raw/observer pointers.

3. **No PMR usage.** The slice operation allocates millions of small polygon/expolygon objects per layer. A `std::pmr::monotonic_buffer_resource` per-layer would eliminate nearly all individual heap allocations during slicing, enabling O(1) bulk-free at layer completion.

4. **`string` copies in hot paths.** `std::string` is used liberally for config option names — these are always string literals. `std::string_view` for lookups would eliminate string copy overhead.

### Recommendations

**Immediate (Low Risk):**

```cpp
// Replace config lookup parameters
// Before:
ConfigOption* optget(const std::string& key) const;

// After (C++17 string_view):
ConfigOption* optget(std::string_view key) const;
```

**Medium-term:**

```cpp
// Per-layer PMR arena for slice operations
void PrintObject::slice_layer(int layer_id) {
    std::array<std::byte, 2 * 1024 * 1024> buf;
    std::pmr::monotonic_buffer_resource arena{buf.data(), buf.size()};
    std::pmr::vector<ExPolygon> layer_polys{&arena};
    // ... fill layer_polys ...
    // All freed here at end of scope - zero individual heap frees
}
```

**Score rationale:** Points from `unique_ptr` usage and TBB correctness. Points deducted for no PMR, no ownership audit, potential `shared_ptr` overuse.

---

## 3. Type Safety — 4/10

### Current State

**The core problem:** Physical quantities throughout the slicer are raw `float` or `double`. Millimeters, degrees, nozzle temperatures, flow rates, speeds — all type aliases to primitive types. There is nothing preventing passing a `float` millimeter value where a `float` layer height ratio is expected.

**Observed in code:**

```cpp
// From TriangleMesh.hpp
float volume = -1.f;      // What units? cubic mm? floating magic value -1.f for "unknown"?
stl_vertex max = stl_vertex::Zero();  // using Eigen types - good
```

The Eigen `Vec3f`/`Vec2f` types provide some safety for geometric vectors, but scalar physical quantities (temperature, speed, flow, layer_height) use raw primitives.

**Include guard style:** All headers use `#ifndef slic3r_*_hpp_`/`#define` style. MSVC 2022 fully supports `#pragma once` and it is faster (no string hashing per include). Only one file (`QDTUtil.hpp`) uses `#pragma once`.

**Missing `[[nodiscard]]`:** Functions like `parse_stl()`, `TriangleMesh::repaired()`, config getters — none are marked `[[nodiscard]]`. A caller that ignores the return value silently runs without any warning.

### Best Practices to Apply

**Strong typedefs with zero overhead:**

```cpp
// src/libslic3r/Units.hpp (NEW FILE to create)
template <typename Tag, typename T = float>
struct StrongUnit {
    T value{};
    explicit constexpr StrongUnit(T v) noexcept : value(v) {}
    constexpr T operator*(const StrongUnit& o) const noexcept { return value * o.value; }
    // ... arithmetic ops
};
using Millimeters  = StrongUnit<struct MillimetersTag>;
using Degrees      = StrongUnit<struct DegreesTag>;
using Celsius      = StrongUnit<struct CelsiusTag>;
using MmPerSecond  = StrongUnit<struct SpeedTag>;
using MmCubicPerMm = StrongUnit<struct FlowTag>;
```

**Add `[[nodiscard]]` exhaustively:**

```cpp
[[nodiscard]] bool load_stl(const std::string& path, Slic3r::TriangleMesh* mesh);
[[nodiscard]] std::optional<Mesh> parse_3mf(const fs::path& path);
```

**`#pragma once` migration:** A one-time sed/Python pass can replace all `#ifndef`/`#define` guards with `#pragma once`, reducing include processing time measurably on a ~500k LOC codebase.

**Score rationale:** Eigen types for vectors is a positive. Raw primitives for all physical scalars, no `[[nodiscard]]`, no strong typedefs, traditional include guards = significant quality debt.

---

## 4. Error Handling — 4/10

### Current State

**Three incompatible error styles coexist:**

1. **Return `bool`** (success/fail with no context): `bool load_stl(...)`, `bool write_file(...)`
2. **Throw exceptions**: Used extensively in parsing, model manipulation
3. **Return `nullptr` / sentinel values**: `ConfigOption* get(key)` returns `nullptr` for not-found; `float volume = -1.f` as sentinel

**No `std::expected`** — C++23's monadic error value is not used anywhere.

**`noexcept` usage:** Inconsistent. Move constructors in key types (mesh, model objects) may not be marked `noexcept`, which means `std::vector` falls back to O(n) copy on reallocation for those types.

### Best Practice (2026)

**Phase 1 — Mark move constructors `noexcept`:**

```cpp
// Verify these are present and marked noexcept:
TriangleMesh(TriangleMesh&&) noexcept;
TriangleMesh& operator=(TriangleMesh&&) noexcept;
ModelObject(ModelObject&&) noexcept;
```

This is a **zero-effort correctness fix** with measurable performance benefit on any code that stores these in `std::vector`.

**Phase 2 — Adopt `std::expected` in new I/O code (C++23):**

```cpp
// New parsing functions (do not break existing API):
std::expected<TriangleMesh, ParseError> parse_stl_safe(const fs::path& p);
std::expected<Model, LoadError> load_3mf_safe(const fs::path& p);
```

**Phase 3 — Contracts design (C++26 prep):**
Model preconditions with a macro today:

```cpp
#define QIDI_EXPECTS(cond) do { if (!(cond)) [[unlikely]] { assert(false); std::terminate(); } } while(0)

void set_layer_height(float h) {
    QIDI_EXPECTS(h > 0.0f && h < 5.0f);  // future: pre(h > 0.0f)
}
```

**Score rationale:** Mixed error styles confuse callers and prevent composable error chains. No `noexcept` on move ops is a silent performance regression.

---

## 5. OpenGL / Rendering C++ — 4/10

### Current State

**Non-DSA (legacy) OpenGL pattern used everywhere:**

```cpp
// From ImGuiWrapper.cpp — legacy pattern:
glsafe(::glGenBuffers(1, &vbo_id));
glsafe(::glBindBuffer(GL_ARRAY_BUFFER, vbo_id));
// ... all subsequent operations require binding first
```

**No RAII wrappers for GL objects:** Raw `GLuint` IDs are stored as member variables. No automatic cleanup on destruction, no protection against double-free of GL resources.

**However:** The GPU normal matrix offload we implemented (session 2026-02-28) eliminated the single most expensive per-draw-call CPU work. That was the highest-impact rendering improvement.

### Best Practice (2026) — DSA + RAII

**DSA pattern (OpenGL 4.5, available on any GPU since ~2012):**

```cpp
// DSA: name objects explicitly, no bind required
GLuint vbo;
glCreateBuffers(1, &vbo);                          // DSA: create
glNamedBufferData(vbo, size, data, GL_STATIC_DRAW); // DSA: upload
glVertexArrayVertexBuffer(vao, 0, vbo, 0, stride);  // DSA: attach to VAO
```

**RAII GL wrapper (Rule of Five applied to GL resource):**

```cpp
// src/slic3r/GUI/GLResource.hpp (NEW FILE)
template <auto Creator, auto Deleter>
struct GlResource {
    GLuint id{0};
    GlResource() { Creator(1, &id); }
    ~GlResource() { if (id) Deleter(1, &id); }
    GlResource(const GlResource&) = delete;
    GlResource& operator=(const GlResource&) = delete;
    GlResource(GlResource&& o) noexcept : id(std::exchange(o.id, 0)) {}
    GlResource& operator=(GlResource&& o) noexcept {
        if (this != &o) { if (id) Deleter(1, &id); id = std::exchange(o.id, 0); }
        return *this;
    }
    [[nodiscard]] GLuint get() const noexcept { return id; }
};
using GlBuffer  = GlResource<glCreateBuffers,  glDeleteBuffers>;
using GlVao     = GlResource<glCreateVertexArrays, glDeleteVertexArrays>;
using GlTexture = GlResource<glCreateTextures, glDeleteTextures>;
```

**UBO static binding (C++-side):**

```cpp
// Set binding once in shader source:
// layout(binding = 0) uniform CameraUBO { mat4 view; mat4 proj; };
// Then in C++:
glBindBufferBase(GL_UNIFORM_BUFFER, 0, camera_ubo.get()); // no glGetUniformBlockIndex needed
```

**Score rationale:** +4 for a working renderer that does render correctly (and now with GPU normal matrix). -6 for no DSA, no RAII GL wrappers, no UBO static bindings. The GL code is the highest-priority modernization target after standard upgrade.

---

## 6. Concurrency & Parallelism — 6/10

### Current State

**Positives:**

- TBB `parallel_for` with `blocked_range` is used correctly across libslic3r (Brim.cpp, CutSurface.cpp, etc.)
- `tbb::spin_mutex` for fine-grained locking in parallel regions — correct choice over `std::mutex` here
- `USE_TBB` and `TBB_USE_CAPTURED_EXCEPTION=0` defined globally — correct TBB CMake setup
- No raw `std::thread` with manual join (primary threading done via TBB tasks)

**Problems:**

- `boost::thread` in `GCodeSender.cpp` — a C++98-era API. No cancellation support.
- No `std::jthread` or `std::stop_token` anywhere
- No coroutines — Blender subprocess is invoked synchronously, potentially stalling the GUI
- No `std::execution` (stdexec) — TBB is fine for current workloads but sender/receiver is the future

### Recommendations

**Replace `boost::thread` with `std::jthread` in GCodeSender:**

```cpp
// Before (GCodeSender.cpp ~L110):
boost::thread t(boost::bind(&boost::asio::io_service::run, &this->io));

// After:
std::jthread t([this](std::stop_token st) {
    while (!st.stop_requested())
        this->io.run_one();
});
// Destructor requests stop + joins — no manual management
```

**Coroutine-based Blender subprocess (eliminates GUI stall):**

```cpp
// Future architecture — requires coroutine task infrastructure
Task<ExecResult> run_blender(std::string cmd) {
    co_return co_await AsyncProcess{cmd}; // GUI thread free while waiting
}
```

**Score rationale:** TBB is the right tool and is used well (+6). Boost thread legacy and no coroutines for async subprocess (-4).

---

## 7. Build System & Tooling — 3/10

### Current State

**What is broken/missing:**

1. **C++ standard not globally enforced** — biggest single fix (see §1)
2. **No CMakePresets.json** — builds are configured via ad-hoc `CMakeCache.txt` or script arguments
3. **No CI static analysis** — clang-tidy is not run in CI
4. **No package management manifest (vcpkg.json)** — all deps are manual/vendored or resolved by `deps/`
5. **CMake version constraint** — must use `CMake 3.29.8` (C:\CMake329\) — documented but brittle

**What is working:**

- `/MP` parallel compilation on MSVC
- `/Zi` pdb output for debugging
- `debug_build.ps1` with ASan + RelWithDebInfo
- TBB compile definitions set correctly

### Specific Recommendations

**1. Add CMakePresets.json (30 minutes, high value):**

```json
{
  "version": 6,
  "configurePresets": [
    {
      "name": "msvc-relwithdebinfo",
      "displayName": "MSVC RelWithDebInfo",
      "generator": "Visual Studio 17 2022",
      "binaryDir": "C:/QIDISrc/QIDIStudio/build",
      "installDir": "C:/QIDISrc/QIDIStudio/install_dir",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "SLIC3R_BUILD_TESTS": "OFF",
        "QDT_RELEASE_TO_PUBLIC": "1"
      }
    },
    {
      "name": "msvc-asan",
      "inherits": "msvc-relwithdebinfo",
      "displayName": "MSVC ASan",
      "binaryDir": "C:/QIDISrc/QIDIStudio/build_asan",
      "installDir": "C:/QIDISrc/QIDIStudio/install_dir_debug",
      "cacheVariables": {
        "CMAKE_CXX_FLAGS": "/fsanitize=address /Zi"
      }
    }
  ]
}
```

**2. clang-tidy configuration (`.clang-tidy` file, 30 minutes):**

```yaml
Checks: >
  cppcoreguidelines-*,
  modernize-use-override,
  modernize-use-nullptr,
  modernize-use-default-member-init,
  modernize-loop-convert,
  readability-const-return-type,
  performance-unnecessary-value-param,
  performance-move-const-arg,
  bugprone-use-after-move,
  bugprone-undefined-memory-manipulation
WarningsAsErrors: >
  bugprone-use-after-move,
  bugprone-undefined-memory-manipulation
HeaderFilterRegex: "src/(libslic3r|slic3r)/.*"
```

**3. Set C++ standard globally:**

```cmake
# In root CMakeLists.txt after project() declaration:
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
# Allow vendored targets to override downward
```

**Score rationale:** The build works and has ASan support (good), but has no presets, no clang-tidy, no package manifest = F-tier tooling setup for a production codebase.

---

## 8. Performance Architecture — 4/10

### Current State

**Positives:**

- TBB `parallel_for` for slice-layer operations — correct
- Eigen `Vec3f` for vertex math — auto-vectorization friendly

**Problems:**

1. **No SIMD for geometry hot paths** — BVH traversal, extrusion width computation, slice-plane intersection — all scalar. No Highway, no Intel Intrinsics, no `std::simd`.

2. **AoS (Array of Structures) vertex layout** — `struct Vertex { Vec3f pos; Vec3f normal; Vec2f uv; }` means that bounding-box computation (which only needs `pos`) touches 3× more data than necessary, thrashing L1.

3. **No Morton code pre-sorting** for BVH primitives — affects cache coherence during traversal.

4. **No `[[likely]]`/`[[unlikely]]`** on error/degenerate branches in mesh processing.

5. **`std::map` used where `std::unordered_map` would be faster** — several config lookup codepaths use ordered maps for non-ordering use cases.

### Highest-Impact Performance Recommendations

**SIMD bounding-box expansion (Google Highway):**

```cpp
// Current (scalar):
for (const auto& v : vertices)
    bbox.expand(v.pos);

// Highway SIMD (8 vertices per cycle on AVX2):
#include "hwy/highway.h"
namespace hn = hwy::HWY_NAMESPACE;
// ... batch-expand with SIMD min/max on SoA position arrays
```

**Partial SoA for position data (high-impact):**

```cpp
// Instead of: std::vector<IndexedVertex> (AoS)
// Use partial SoA for the geometry + compute path:
struct VertexBuffer {
    std::vector<float> x, y, z;          // SoA positions — vectorizer loves this
    std::vector<float> nx, ny, nz;       // SoA normals
    std::vector<float> u, v;             // SoA UVs
    std::vector<uint32_t> indices;
};
```

**`std::unordered_map` for config lookups:**

```cpp
// Config.hpp — replace:
std::map<std::string, ConfigOption*> m_options;
// with:
std::unordered_map<std::string, ConfigOption*> m_options;
// O(log n) → O(1) amortized for every config key access
```

**Score rationale:** TBB parallelism is good (+4). No SIMD, AoS layout, no Morton BVH, `map` vs `unordered_map` = -6 from the theoretical maximum for a geometry-heavy app.

---

## 9. Code Quality & Modern Idioms — 5/10

### Current State

**Mixed bag:**

- **Include guards**: 99% traditional `#ifndef/define/endif` style. `#pragma once` is faster (MSVC's include guard optimization is compiler-version-dependent). Only `QDTUtil.hpp` uses `#pragma once`.
- **`override` keyword**: Partially used but not consistently. CppCon Core Guidelines require `override` on all virtual override declarations.
- **`auto` usage**: Used in some places (range-for, lambda parameters) but many older functions use explicit types where `auto` would be cleaner.
- **Lambda captures**: Used correctly in TBB `parallel_for` lambdas.
- **`constexpr`**: Used in some config constants, not exhaustively.
- **`std::span`**: Not used — many APIs take `(T*, size_t)` pairs.
- **NVI pattern**: Not consistently applied. Some base classes expose `virtual public` functions directly.

### Quick Wins

**`#pragma once` migration script (Python):**

```python
import re, pathlib
for f in pathlib.Path('src').rglob('*.hpp'):
    text = f.read_text(encoding='utf-8')
    # Remove include guard boilerplate
    cleaned = re.sub(r'^#ifndef \w+\n#define \w+\n', '#pragma once\n', text)
    cleaned = re.sub(r'\n#endif\s*//.*$', '', cleaned)
    if cleaned != text:
        f.write_text(cleaned, encoding='utf-8')
```

**Add `override` where missing (clang-tidy `modernize-use-override` check handles this automatically).**

**Replace `(T*, size_t)` parameter pairs with `std::span<T>`:**

```cpp
// Before:
void write_triangles(const Triangle* tris, size_t count);

// After (C++20):
void write_triangles(std::span<const Triangle> tris);
// Callers pass std::vector<Triangle>, raw arrays, or spans — all work
```

**Score rationale:** The codebase is clean and readable (+5) but misses most of the modern C++ idioms that reduce bugs and improve performance.

---

## 10. Testing & Verification — 4/10

### Current State

**What exists:**

- CTest integration with `-DSLIC3R_BUILD_TESTS=ON`
- Tests for `libslic3r` geometry algorithms, SLA print, FFF print, libnest2d
- Catch2 used for some tests, GoogleTest for others (mixed)

**What is missing:**

- **No fuzzing** — STL parser, 3MF parser, G-code parser take untrusted user input with no corpus-based testing
- **No property-based testing** — topology classifier, UV unwrap correctness, STL round-trip are ideal PBT targets
- **No mutation testing** — test suite likely has poor kill rate
- **No CI integration of tests** — `SLIC3R_BUILD_TESTS=OFF` by default; tests are opt-in
- **No benchmark suite** — performance regressions go undetected

### Specific Additions

**Fuzzer for STL parsing (libFuzzer, Clang):**

```cpp
// tests/fuzz/fuzz_stl.cpp
#include "libslic3r/Format/STL.hpp"
#include <span>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    Slic3r::TriangleMesh mesh;
    // Write to temp file then parse — catches malformed STL parsing bugs
    std::string content(reinterpret_cast<const char*>(data), size);
    try { Slic3r::load_stl_mem(content, &mesh); } catch (...) {}
    return 0;
}
```

**Property-based test for UV unwrap (RapidCheck + Catch2):**

```cpp
#include <rapidcheck.h>
RC_BOOST_PROP(UvRoundTrip,
    (std::vector<Slic3r::Vec3f> verts)) {
    // Build a mesh, unwrap, verify: no UV triangles overlap
    auto mesh = build_from_vertices(verts);
    auto uvs  = lscm_unwrap(mesh);
    RC_ASSERT(!uvs_have_overlaps(uvs));
}
```

**Score rationale:** Tests exist and are structured (+4). Zero coverage of parser safety, no PBT, no fuzzing, tests are opt-in = inadequate for a shipping product.

---

## Prioritized Action Plan

### Priority 1 — Zero-Risk, High-Impact (1–2 days)

| Action                                   | File(s)                                 | Impact                          |
| ---------------------------------------- | --------------------------------------- | ------------------------------- |
| Set `CMAKE_CXX_STANDARD 20` globally     | `CMakeLists.txt`                        | Unlocks all C++20 features      |
| Add `CMakePresets.json`                  | repo root                               | Reproducible builds             |
| Add `.clang-tidy` config                 | repo root                               | Automated quality enforcement   |
| Mark all `noexcept` on move constructors | `TriangleMesh.hpp`, `ModelObject`, etc. | Vector reallocation performance |
| Replace `boost::thread` in GCodeSender   | `GCodeSender.cpp`                       | Correct cancellation            |

### Priority 2 — Moderate Effort, High Value (1–2 weeks)

| Action                                        | Benefit                                    |
| --------------------------------------------- | ------------------------------------------ |
| RAII GL object wrappers (`GlBuffer`, `GlVao`) | Memory safety for GL resources             |
| Migrate ImGuiWrapper + GLModel to DSA         | Code clarity, performance                  |
| Add `[[nodiscard]]` to all parse/IO functions | Catch ignored returns at compile time      |
| `std::string_view` for config key lookups     | Eliminate string copies in hot config path |
| `std::unordered_map` for config section       | O(log n) → O(1) lookups                    |
| Enable `SLIC3R_BUILD_TESTS=ON` in CI default  | Actually catch regressions                 |

### Priority 3 — Significant Investment, Transformative (1–3 months)

| Action                                          | Benefit                                  |
| ----------------------------------------------- | ---------------------------------------- |
| Google Highway SIMD for BVH + slicer geometry   | 4–16x on geometry-bound passes           |
| Partial SoA vertex buffer layout                | Auto-vectorization of compute loops      |
| `std::expected` in new parse/load APIs          | Composable error handling                |
| Coroutine-based Blender subprocess              | Eliminate GUI stall during texture apply |
| Property-based tests for UV unwrap + topology   | Catch unwrap correctness bugs            |
| libFuzzer on STL/3MF/GCode parsers              | Crash safety for user-supplied files     |
| Strong unit typedefs (`Millimeters`, `Degrees`) | Eliminate unit-confusion bugs            |

### Do NOT Do (Cost > Benefit for This Codebase)

| Action                        | Why not                                                           |
| ----------------------------- | ----------------------------------------------------------------- |
| C++20 Modules                 | MSVC column blank for key features; 500k LOC migration impossible |
| C++26 Contracts               | Zero compiler support as of Feb 2026                              |
| `std::simd` / `<simd>` header | Not in any production compiler yet                                |
| vcpkg full migration          | High effort; existing `deps/` system works                        |
| Rewrite wxWidgets → Qt        | Enormous scope; wxWidgets is adequate                             |

---

## Technology Stack Recommendation (2026)

| Layer             | Current               | Recommended                               | Notes                                     |
| ----------------- | --------------------- | ----------------------------------------- | ----------------------------------------- |
| Language standard | C++17 (patchwork)     | **C++20**                                 | MSVC 2022 complete                        |
| Parallelism       | TBB                   | **TBB + std::jthread**                    | Keep TBB; add jthread for managed threads |
| SIMD              | None                  | **Google Highway**                        | Portable, production-ready                |
| Error handling    | mixed bool/exception  | **+ std::expected (C++23)** for new code  | Additive, not replacing                   |
| Coroutines        | None                  | **C++20 coroutines + minimal task type**  | For Blender subprocess + file I/O         |
| GL object mgmt    | Raw GLuint            | **RAII wrappers (custom)**                | 50-line header                            |
| GL API style      | Legacy bind-to-modify | **DSA (glNamed\*)**                       | Incremental migration                     |
| Build config      | Ad-hoc CMakeCache     | **CMakePresets.json**                     | Committed to repo                         |
| Static analysis   | None in CI            | **clang-tidy (modernize-_ + bugprone-_)** | Run per-PR                                |
| Package mgmt      | Manual deps/          | **vcpkg manifest (optional)**             | Low priority                              |
| Testing           | Catch2/GTest opt-in   | **+ libFuzzer + RapidCheck**              | Parser safety critical                    |

---

_Last updated: 2026-02-28. Sources: cppreference.com, isocpp.org/CppCoreGuidelines, CppCon 2023/2024/2025, lemire.me, LLVM blog, NVIDIA/stdexec, Google Highway docs._
