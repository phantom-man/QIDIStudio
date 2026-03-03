# QIDIStudio — Complete Engineering Knowledge Base

_Maintained by: GitHub Copilot | Last updated: 2026-02-27 (Blender pipeline: vertex group, fail-fast, CAD topology fix, mid_level=0.0, Blender 4.1 API changes) + 2026-02-27 (computational metrology: conformal UV, spectral Shape DNA, libigl, robust_laplacian, trimesh) + 2026-02-28 (topology classifier: MeshClass enum, match/case dispatch, euler characteristic, spectral DNA) + 2026-02-28 (dev workflow: NTFS junction single-source-of-truth, run_texture_pipeline.ps1) + 2026-02-28 (PhD architecture guide, hybrid C++/Python debugging workflow absorbed) + 2026-02-28 (ViL debug harness: --debug-snapshots, \_DebugSession, ai_debug_pipeline.py, §15.14) + 2026-02-28 (§18: PhD Cognitive Architecture — full absorption of PSV loop, System 1/2 thinking, HAVEN, Lean 4, cross-domain isomorphisms, applied to all pipelines) + 2026-02-28 (§19: Computational Aesthetics — Fourier symmetry score, spectral entropy, Leder B(s,σ) model, Golden Zone, skin FFT tile refinement, ai_beauty_scorer.py) + 2025 (§20: 3D Viewer PhD code review — Gouraud/PBR/gamma/lights/FXAA/SSAO/shadow deficiencies catalogued; full report docs/3D_Viewer_Code_Review_Report.md) + 2026-02-28 (§21: C++ Modernization Scorecard — PhD-level tech stack audit, 43/100 baseline score, full action plan; full report docs/CPP_MODERNIZATION_SCORE.md) + 2026-02-28 (§21 update: P1+P2 implemented — C++20 global, CMakePresets.json, .clang-tidy, std::jthread, noexcept move ctors, GLResource.hpp RAII, [[nodiscard]] on parse/IO, #pragma once pilot; score 43→54/100)_

This document captures all reverse-engineered knowledge about QIDIStudio's source code,
build system, configuration, and 3MF format. It serves as the single source of truth
for anyone working on the phantom-man/QIDIStudio fork.

---

## Table of Contents

1. [What QIDIStudio Is](#1-what-qidistudio-is)
2. [Key Websites & References](#2-key-websites--references)
3. [Repository Structure](#3-repository-structure)
4. [Build System](#4-build-system)
5. [Feature Flags](#5-feature-flags--compile-time-switches)
6. [Mode System (Simple / Advanced / Developer)](#6-mode-system)
7. [Configuration File](#7-configuration-file)
8. [3MF Export Format](#8-3mf-export-format)
9. [Networking & HMS System](#9-networking--hms-system)
10. [Slicer Settings Reference](#10-slicer-settings-reference)
11. [Known Bugs & Workarounds](#11-known-bugs--workarounds)
12. [GCode Post-Processing Integration](#12-gcode-post-processing-integration)
13. [Our Modifications vs Upstream](#13-our-modifications-vs-upstream)
14. [§21 C++ Modernization Scorecard](#21-c-modernization-scorecard)

---

## 1. What QIDIStudio Is

QIDIStudio is QIDI Technology's proprietary 3D printing slicer, forked from **OrcaSlicer**
(which was itself forked from **Bambu Studio**, which forked from **PrusaSlicer**). The
lineage is:

```
PrusaSlicer (Prusa Research, open-source)
    └─ Bambu Studio (Bambu Lab, partially open)
           └─ OrcaSlicer (open-source community fork)
                  └─ QIDIStudio (QIDI Technology, closed-source additions on open base)
```

**Key facts:**

- Target printers: QIDI Q2 Pro, X-Series, Plus4, and other QIDI machines
- Core slicer engine: **libslic3r** (shared lineage with PrusaSlicer/OrcaSlicer)
- UI framework: **wxWidgets** (cross-platform, not Qt)
- Build system: **CMake + Visual Studio** (Windows), Ninja option exists
- Source version studied: **v02.04.01.11** (latest as of 2026-02-25)
- Private module: `qidi_networking.dll` — QIDI's closed-source cloud/remote-print module, NOT in the public repo

**Why it "sucks":**

1. Mode switcher buttons (Simple/Advanced/Developer) are entirely commented out — users are stuck in Simple mode with no way to access advanced parameters
2. First-run defaults to Simple mode + staging cloud environment (`iot_environment = "2"`)
3. `qidi_networking.dll` absent from public build → Host Setting cannot save
4. Windows installer (`QIDIStudio_Setup_*.exe`) is regularly shipped as a corrupt EXE (exit 0xc000007b)
5. Temperatures from custom filament presets don't resolve correctly if `filament_settings_id` points to a missing or wrong preset

---

## 2. Key Websites & References

### Primary Sources

| URL                                         | Purpose                                                       |
| ------------------------------------------- | ------------------------------------------------------------- |
| <https://github.com/QIDITECH/QIDIStudio>    | QIDI's official public source repo                            |
| <https://github.com/phantom-man/QIDIStudio> | **Our fork — primary working repo**                           |
| <https://github.com/SoftFever/OrcaSlicer>   | OrcaSlicer upstream (most relevant reference for shared code) |
| <https://github.com/bambulab/BambuStudio>   | Bambu Studio (OrcaSlicer's parent)                            |
| <https://github.com/prusa3d/PrusaSlicer>    | Ultimate upstream for libslic3r                               |

### Build & Dependencies

| URL                                                                    | Purpose                                             |
| ---------------------------------------------------------------------- | --------------------------------------------------- |
| <https://github.com/QIDITECH/QIDIStudio/blob/main/doc/How_to_build.md> | Official build guide (Windows/Mac/Linux)            |
| <https://cmake.org/download/>                                          | CMake — use **3.29.x**, NOT 4.x (see build gotchas) |
| <https://strawberryperl.com/>                                          | Strawberry Perl — required for OpenSSL build step   |
| <https://github.com/nicowillis/pkg-config-lite>                        | pkg-config-lite for Windows                         |

### OrcaSlicer Configuration Reference (applies to QIDIStudio)

| URL                                                                               | Purpose                                                                                            |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| <https://github.com/SoftFever/OrcaSlicer/wiki>                                    | OrcaSlicer wiki — most settings docs apply to QIDIStudio                                           |
| <https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/PrintConfig.cpp> | **Config key definitions + enums** — authoritative source for `sparse_infill_pattern` values, etc. |
| <https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/Config.hpp>      | `ConfigOptionMode` enum definition                                                                 |

### 3MF Format

| URL                                          | Purpose                               |
| -------------------------------------------- | ------------------------------------- |
| <https://3mf.io/specification/>              | Official 3MF consortium specification |
| <https://github.com/3MFConsortium/spec_core> | 3MF core spec source                  |

### Community & Support

| URL                                                  | Purpose                                              |
| ---------------------------------------------------- | ---------------------------------------------------- |
| <https://www.reddit.com/r/QIDI/>                     | QIDI user community — known issues, firmware gotchas |
| <https://github.com/QIDITECH/QIDIStudio/issues>      | Official bug tracker                                 |
| <https://github.com/QIDITECH/QIDIStudio/discussions> | Community Q&A                                        |

---

## 3. Repository Structure

```
QIDIStudio/
├── src/
│   ├── libslic3r/               # Core slicer engine (shared with OrcaSlicer/PrusaSlicer)
│   │   ├── AppConfig.cpp/.hpp   # Application configuration (read/write QIDIStudio.conf)
│   │   ├── Config.hpp           # ConfigOptionMode enum, all config option types
│   │   ├── PrintConfig.cpp      # All printable config keys + their enums/defaults
│   │   └── ...
│   └── slic3r/
│       └── GUI/
│           ├── GUI_App.cpp/.hpp  # Main wx app class — save_mode(), get_mode(), update_mode()
│           ├── MainFrame.cpp     # Main window — first-run defaults, mode initialization
│           ├── wxExtensions.cpp  # ModeSizer — the mode switcher button row
│           └── ...
├── deps/                        # CMake ExternalProject deps (OpenSSL, boost, wxWidgets, etc.)
├── resources/
│   └── profiles/
│       └── Q Series/
│           ├── filament/        # System filament presets (*.json)
│           ├── machine/         # Machine presets (*.json)
│           └── process/         # Process/print presets (*.json)
├── doc/                         # Build documentation
└── CMakeLists.txt               # Top-level build entry point
```

**User data (runtime, not in source repo):**

```
C:\Users\<user>\AppData\Roaming\QIDIStudio\
├── QIDIStudio.conf              # App config JSON (created on first run)
├── user/default/
│   ├── filament/                # User-created filament presets (*.json + *.info)
│   ├── process/                 # User-created process presets
│   └── machine/                 # User-created machine presets
├── cache/                       # Thumbnail cache
├── log/                         # debug_*.log files
└── ota/                         # OTA update metadata
```

---

## 4. Build System

### Prerequisites (Windows)

| Tool            | Version        | Install                                    | Notes                                                          |
| --------------- | -------------- | ------------------------------------------ | -------------------------------------------------------------- |
| CMake           | **3.29.8**     | <https://cmake.org/download/>              | Install to `C:\CMake329\`. Do NOT use CMake 4.x — policy break |
| Visual Studio   | 2022 Community | winget / manual                            | C++ workload required                                          |
| Strawberry Perl | 5.42+          | <https://strawberryperl.com/>              | Required for OpenSSL configure step                            |
| pkg-config-lite | 0.28           | `winget install bloodrock.pkg-config-lite` | Required — libav deps use .pc files                            |
| Ninja           | 1.13+          | optional                                   | Not needed if using VS generator                               |

### Build Script

The orchestrator script `_build_qidi.py` (in `C:\Users\User\Downloads\`) handles the full build:

- Configures deps build (Sequential: `/m:1` — parallel breaks ExternalProject)
- Patches `src/slic3r/CMakeLists.txt` for the QIDINetwork.cpp issue (see §5)
- Configures app build
- Builds + installs app (Parallel: `/m:8` or more)

**Build output:** `C:\QIDISrc\QIDIStudio\install_dir\qidi-studio.exe`

### Manual Commands (if running without the script)

```powershell
# --- DEPS BUILD ---
mkdir C:\QIDISrc\QIDIStudio\deps\build
cd C:\QIDISrc\QIDIStudio\deps\build
& "C:\CMake329\bin\cmake.exe" ../ -G "Visual Studio 17 2022" -A x64 `
    -DDESTDIR=C:\QIDIDeps -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 `
    -DPERL_EXECUTABLE=C:\Strawberry\perl\bin\perl.exe
& "C:\CMake329\bin\cmake.exe" --build . --config Release -- /m:1 /v:minimal

# --- APP BUILD ---
mkdir C:\QIDISrc\QIDIStudio\build
cd C:\QIDISrc\QIDIStudio\build
$env:PKG_CONFIG_PATH = "C:\QIDIDeps\usr\local\lib\pkgconfig"
& "C:\CMake329\bin\cmake.exe" .. -G "Visual Studio 17 2022" -A x64 `
    -DQDT_RELEASE_TO_PUBLIC=0 `
    -DCMAKE_PREFIX_PATH=C:\QIDIDeps/usr/local `
    -DCMAKE_INSTALL_PREFIX=C:\QIDISrc\QIDIStudio\install_dir `
    -DCMAKE_BUILD_TYPE=Release `
    -DWIN10SDK_PATH="C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0" `
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 `
    -DPKG_CONFIG_EXECUTABLE="C:\...\pkg-config.exe"
& "C:\CMake329\bin\cmake.exe" --build . --target install --config Release -- /m:16 /v:minimal
```

### REQUIRED Source Patch Before App Configure

Before running app cmake configure, patch line ~638 of `src/slic3r/CMakeLists.txt`:

```cmake
# BEFORE — cmake old-policy bug makes this always TRUE when QIDINetwork.cpp is absent:
if(QDT_RELEASE_TO_PUBLIC)

# AFTER — explicit string compare, evaluates false when variable is "0" or unset:
if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")
```

---

## 5. Feature Flags / Compile-Time Switches

### `QDT_RELEASE_TO_PUBLIC`

The most important feature flag. Controls whether the app behaves as a "production release":

| Value | Effect                                                                                                                                                       |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `1`   | Production: `iot_environment` defaults to `"3"`, `get_hms_host()` returns production URL, requires `QIDI/QIDINetwork.cpp` (NOT in public repo → build fails) |
| `0`   | Dev/internal: `iot_environment` defaults to `"2"` (PRE/staging). No networking module needed. `get_hms_host()` still gated by `#if !QDT_RELEASE_TO_PUBLIC`   |

**Rule: Always build with `QDT_RELEASE_TO_PUBLIC=0`** — the private networking module (`QIDI/QIDINetwork.cpp`) is not in the public source ZIP.

**Workaround for production host:** Change the `#else` branch default in `AppConfig.cpp` from `"2"` to `"3"` (already done in our fork).

### Other Notable Flags

- `SUPPORT_DARK_MODE` — defined in `AppConfig.hpp`, enables dark mode support
- `_MSW_DARK_MODE` — commented out in `AppConfig.hpp`, Windows-specific dark mode path

---

## 6. Mode System

### Overview

QIDIStudio has 3 UI complexity modes that control which settings are visible:

| Enum value        | String       | Config key value                          | What it shows |
| ----------------- | ------------ | ----------------------------------------- | ------------- |
| `comSimple = 0`   | `"simple"`   | Basic settings only                       |
| `comAdvanced = 1` | `"advanced"` | Most settings                             |
| `comDevelop = 2`  | `"develop"`  | All settings including debug/experimental |

The mode is stored in `QIDIStudio.conf` under key `"user_mode"`.

### Key Source Files

- **`src/libslic3r/Config.hpp:203-207`** — `ConfigOptionMode` enum definition
- **`src/slic3r/GUI/wxExtensions.cpp:1040-1075`** — `ModeSizer` class — the 3-button row in the toolbar
- **`src/slic3r/GUI/GUI_App.cpp:6448-6467`** — `get_mode()` / `save_mode()` — reads/writes `user_mode` to config
- **`src/slic3r/GUI/MainFrame.cpp:196-201`** — First-run defaults

### The Bug (Upstream QIDIStudio)

In the official QIDI source, **all three mode buttons are commented out** in `wxExtensions.cpp`:

```cpp
// UPSTREAM BUG — buttons vector is empty, no mode switcher appears:
std::vector < std::pair < wxString, std::string >> buttons = {
    //{_(L("Simple")),    "mode_simple"},
    //{_(L("Advanced")),  "mode_advanced"},
    //{_CTX(L_CONTEXT("Advanced", "Mode"), "Mode"), "mode_advanced"}
};
```

### Our Fix (phantom-man/QIDIStudio)

Three buttons restored + Developer added:

```cpp
std::vector < std::pair < wxString, std::string >> buttons = {
    {_(L("Simple")),    "mode_simple"},
    {_CTX(L_CONTEXT("Advanced", "Mode"), "Mode"), "mode_advanced"},
    {_(L("Developer")), "mode_develop"},
};
```

Additionally, first-run default changed in `MainFrame.cpp`:

```cpp
// OUR DEFAULT: start in Developer mode
wxGetApp().app_config->set("user_mode", "develop");
wxGetApp().app_config->set_bool("developer_mode", true);
```

### Resetting Mode Manually (if app was already run with old binary)

Edit `C:\Users\<user>\AppData\Roaming\QIDIStudio\QIDIStudio.conf`:

```json
{
  "user_mode": "develop",
  "developer_mode": "true"
}
```

---

## 7. Configuration File

### Location & Format

- **Path:** `C:\Users\<user>\AppData\Roaming\QIDIStudio\QIDIStudio.conf`
- **Format:** JSON (defined by `USE_JSON_CONFIG` macro)
- **Written by:** `AppConfig::save()` in `src/libslic3r/AppConfig.cpp`
- **Written to:** temp file `QIDIStudio.conf.<pid>`, renamed atomically on success

### Key Configuration Parameters

| Key                       | Values                                                            | Notes                                       |
| ------------------------- | ----------------------------------------------------------------- | ------------------------------------------- |
| `user_mode`               | `"simple"`, `"advanced"`, `"develop"`                             | UI complexity level                         |
| `developer_mode`          | `"true"` / `"false"`                                              | Separate boolean, works alongside user_mode |
| `internal_developer_mode` | `"true"` / `"false"`                                              | Force-reset to `false` on every startup     |
| `iot_environment`         | `"0"`=DEV, `"1"`=QA, `"2"`=PRE, `"3"`=PRODUCT                     | Which cloud env to connect to               |
| `sending_interval`        | `"5"`                                                             | Telemetry interval                          |
| `max_send`                | `"3"`                                                             | Max retry count                             |
| `user_mode`               | see above                                                         |                                             |
| `severity_level`          | `"fatal"`, `"error"`, `"warning"`, `"info"`, `"debug"`, `"trace"` | Log verbosity                               |
| `max_recent_count`        | int string e.g. `"18"`                                            | Recent projects count                       |

### `iot_environment` Default Bug

In upstream `AppConfig.cpp`, the `#else` branch (`QDT_RELEASE_TO_PUBLIC=0`) defaults
`iot_environment` to `"2"` (PRE/staging). Our fix changes it to `"3"` (production).

```cpp
// src/libslic3r/AppConfig.cpp ~line 452 — OUR PATCHED VERSION:
#else
    if (get("iot_environment").empty()) {
        set("iot_environment", "3");  // default to production (not PRE/staging)
    }
#endif
```

---

## 8. 3MF Export Format

QIDIStudio requires a very specific 3MF structure. This section documents exactly what
is needed for a 3MF to load successfully with all slicer settings intact.

### Golden Reference

`AxisMounts/_ref_settings.json` in the 3DPrinting repo contains all 519 keys from a
3MF exported directly by QIDIStudio v02.04.01.11. Always use this as the base.

### Required Metadata Files

| File inside 3MF ZIP                | Purpose                                                 |
| ---------------------------------- | ------------------------------------------------------- |
| `3D/3dmodel.model`                 | The mesh geometry (required OPC part)                   |
| `Metadata/project_settings.config` | **The critical one** — all slicer settings as flat JSON |
| `Metadata/model_settings.config`   | Per-object XML + plate definition                       |
| `Metadata/slice_info.config`       | XML with client type/version headers                    |
| `Metadata/cut_information.xml`     | Per-object `<cut_id>` placeholders                      |
| `Metadata/filament_sequence.json`  | `{"plate_1": {"sequence": []}}`                         |
| `[Content_Types].xml`              | Must include PNG and gcode content types                |

### `project_settings.config` Requirements

1. **Application metadata must be** `"QIDIStudio-01.05.00.69"` — if wrong, QIDIStudio ignores all embedded configs and shows `dont_load_config = true` in the log
2. **All values are strings** (or arrays-of-strings) — `"nozzle_diameter": ["0.4"]` not `0.4`
3. **Array-typed keys** use single-element arrays: `["value"]`
4. **Pretty-print** with `indent=4` matching QIDIStudio's `std::setw(4)` output
5. **NO separate preset files** — do NOT include `process_settings_1.config`, `filament_settings_1.config`, or `machine_settings_1.config`
6. `filament_settings_id` must reference a preset that **physically exists** on the user's machine — template variables in gcode (`[nozzle_temperature]` etc.) resolve from the filament preset, NOT from `project_settings.config`

### Critical Key Names (common sources of confusion)

| Key                            | Notes                                                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------------------- |
| `curr_bed_type`                | NOT `bed_type`. Selects which `*_plate_temp` key provides bed temp. Set to `"Textured PEI Plate"` |
| `printer_settings_id`          | Must match system machine preset name e.g. `"Q2 0.4 nozzle"`                                      |
| `print_compatible_printers`    | Array: `["Q2 0.4 nozzle"]`                                                                        |
| `different_settings_to_system` | 3-element array: `[process_diffs, filament_diffs, machine_diffs]` (semicolon-separated key names) |
| `support_chamber_temp_control` | `"1"` — required for chamber heater activation                                                    |

### Infill Pattern Enum Values (config strings, NOT UI labels)

QIDIStudio validates `sparse_infill_pattern` on 3MF load. Invalid values get silently
replaced with `"cubic"`, which then fails at 100% infill density.

**Sparse-only patterns (cannot be used at 100% infill):**
`"grid"`, `"cubic"`, `"gyroid"`, `"triangles"`, `"honeycomb"`, `"zigzag"`, `"crosszag"`,
`"lockedzag"`, `"line"`, `"tri-hexagon"`, `"quartercubic"`, `"adaptivecubic"`,
`"supportcubic"`, `"lightning"`, `"3dhoneycomb"`, `"lateral-honeycomb"`, etc.

**Solid infill patterns (safe for 100% density):**
`"monotonic"`, `"concentric"`, `"zig-zag"` (= UI "Rectilinear"), `"archimedean chords"`,
`"octagram spiral"`, `"hilbert curve"`, `"aligned rectilinear"`

**100% infill recipe (no silent-swap bug):**

```python
"sparse_infill_density": "100%",
"sparse_infill_pattern": "concentric",       # safe for 100%
"internal_solid_infill_pattern": "monotonic", # controls actual fill
```

⚠️ `"zig zag"` (with space) and `"rectilinear"` for `sparse_infill_pattern` are INVALID —
both get silently replaced with `"cubic"` which causes a circular bug at 100%.

⚠️ `"zig-zag"` for `internal_solid_infill_pattern` = UI "Rectilinear" (QIDIStudio quirk).
Do NOT use `"rectilinear"` for this key.

---

## 9. Networking & HMS System

### HMS Host Architecture

QIDIStudio connects to QIDI's cloud (HMS = Hardware Management System) for:

- Remote print monitoring
- Device binding / account
- OTA updates

### `get_hms_host()` in `AppConfig.cpp`

Gated by `#if !QDT_RELEASE_TO_PUBLIC`. Returns host URL based on `iot_environment`:

| `iot_environment` | Enum           | Host                |
| ----------------- | -------------- | ------------------- |
| `"0"`             | `ENV_DEV_HOST` | Internal DEV server |
| `"1"`             | `ENV_QAT`      | QA/testing server   |
| `"2"`             | `ENV_PRE`      | PRE/staging server  |
| `"3"`             | `ENV_PRODUCT`  | Production server   |

**With `QDT_RELEASE_TO_PUBLIC=0`**, the function is compiled in and uses `iot_environment`
to select the host. With `=1`, the function returns production unconditionally (but that
build requires the private networking module).

### `qidi_networking.dll`

QIDI's closed-source networking module. NOT in the public source repo. Load failure logged as
`load dll failed` in `debug_*.log`. With this DLL absent:

- Host Setting dialog opens but **cannot save**
- Device binding / cloud pairing fail
- Remote print monitoring unavailable
- Local Moonraker/Klipper direct connection (manual IP + Moonraker API) still works fine

**Workaround for local printing:** Use the Moonraker REST API directly
(`http://192.168.0.116:7125/`) via a custom upload script. QIDIStudio's local print
send (LAN mode) uses a different path and partially works without the DLL.

---

## 10. Slicer Settings Reference

### Temperature Settings (Qidi Q2, 0.4mm hardened steel nozzle)

| Filament                   | Nozzle | Bed   | Chamber | Notes                                       |
| -------------------------- | ------ | ----- | ------- | ------------------------------------------- |
| ASA-GF (Siraya Fibreheart) | 270°C  | 100°C | 65°C    | Hardened steel runs ~10°C colder than brass |
| PETG Translucent           | 250°C  | 75°C  | 0°C     | No chamber heat — fans off for max clarity  |
| Standard PETG              | 240°C  | 75°C  | 0°C     |                                             |
| QIDI ASA (stock)           | 250°C  | 90°C  | 60°C    | System preset values                        |

### Maximum Strength ASA-GF Settings

```python
settings_override = {
    "print_settings_id": "0.16mm Max Strength @Q2",
    "wall_loops": "8",
    "wall_generator": "arachne",
    "detect_thin_wall": "1",
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "concentric",
    "internal_solid_infill_pattern": "monotonic",
    "infill_wall_overlap": "25%",
    "top_shell_layers": "10",
    "bottom_shell_layers": "10",
    "layer_height": "0.16",
    "outer_wall_speed": "40",
}
```

### Custom Filament Preset Location

```
C:\Users\<user>\AppData\Roaming\QIDIStudio\user\default\filament\
    Siraya Tech Fibreheart ASA-GF @Qidi Q2 0.4 nozzle.json
    Siraya Tech Fibreheart ASA-GF @Qidi Q2 0.4 nozzle.info
```

The preset must include `nozzle_temperature` and `nozzle_temperature_initial_layer`
(not just range keys) for template variables to resolve correctly in gcode.

### `filament_settings_id` Template Variable Resolution

Template variables like `[nozzle_temperature_initial_layer]` in start/end gcode resolve
from the **filament preset** identified by `filament_settings_id`, NOT from
`project_settings.config` overrides. If the preset name doesn't exist on the machine,
variables resolve to empty strings → 0°C in Klipper.

---

## 11. Known Bugs & Workarounds

### Bug 1: Mode Switcher Completely Missing

- **Cause:** `wxExtensions.cpp` ModeSizer buttons vector is empty (all commented out)
- **Fix:** Restore buttons + add Developer (see §6)

### Bug 2: `iot_environment` Defaults to Staging

- **Cause:** `AppConfig.cpp` `#else` branch (QDT_RELEASE_TO_PUBLIC=0) sets `"2"` (PRE)
- **Fix:** Change default from `"2"` to `"3"` in AppConfig.cpp (see §7)

### Bug 3: QIDINetwork.cpp Missing from Public Source

- **Cause:** `src/slic3r/CMakeLists.txt` line ~638 has `if(QDT_RELEASE_TO_PUBLIC)` which
  evaluates TRUE on some CMake policy versions even when the variable is undefined
- **Fix:** Change to `if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")` AND pass
  `-DQDT_RELEASE_TO_PUBLIC=0` to cmake. Both changes required.

### Bug 4: CMake 4.x Policy Break

- **Cause:** CMake 4.x removed backward compat with `cmake_minimum_required < 3.5`
- **Fix:** Use CMake 3.29.8 at `C:\CMake329\` OR pass `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`

### Bug 5: `sparse_infill_pattern "rectilinear"` Silent Swap

- **Cause:** OrcaSlicer/QIDIStudio replaces invalid sparse patterns with `"cubic"` on load
- **Fix:** Use `"concentric"` for 100% infill, `"zigzag"` for standard fractional infill
- **Invalid values:** `"rectilinear"`, `"zig zag"` (with space), `"zig-zag"` for sparse

### Bug 6: 100% Infill + Cubic Pattern Circular Dialog

- **Cause:** `"rectilinear"` → swapped to `"cubic"` → cubic doesn't support 100% → dialog asks to switch to `"rectilinear"` → repeat
- **Fix:** Use `"concentric"` as sparse pattern when density is 100%

### Bug 7: OrcaSlicer Rogue M191 Macro Injection (Klipper)

- **Cause:** OrcaSlicer injects a broken `[gcode_macro M191]` referencing `chamber_heater` instead of Qidi's `chamber`
- **Symptom:** Chamber shows 0% power, hot end at 0°C
- **Fix:** Check `printer.cfg` for rogue macro overrides; restore from backup

### Bug 8: Stale VS Project Files Lock CMake Flags

- **Cause:** After cmake configure, `.vcxproj` files embed the command-line flags. Deleting
  only `CMakeCache.txt` doesn't clear them.
- **Fix:** Wipe the **entire build directory** (`cmd /c rd /s /q <build_dir>`), not just cache

### Bug 9: `cmd /c rd /s /q` Fails on Locked Build Dir

- **Cause:** If any terminal's CWD is inside the build directory, Windows locks it
- **Fix:** Run `cd C:\` in ALL open terminals before deleting

### Bug 10: OpenSSL Fails with MSB8066 Exit 9009

- **Cause:** Either (a) perl not on PATH or (b) parallel build (`/m:N > 1`) causes ExternalProject race
- **Fix:** Pass `-DPERL_EXECUTABLE=C:\Strawberry\perl\bin\perl.exe` to deps cmake; use `/m:1` for deps build

---

## 12. GCode Post-Processing Integration

QIDIStudio supports post-processing scripts via:
**Print Settings → Output Options → Post-processing scripts**

The script receives the gcode file path as its last argument. Modifies in-place.

### GCodeRefiner (our custom post-processor)

See `GCodeRefiner/` directory in this repo.

```
GCodeRefiner/
├── refiner.py              # Main entry point
├── profiles/
│   └── asa_gf_04mm.py     # ASA-GF + 0.4mm hardened steel nozzle envelope
├── rules/
│   └── m2_gear.py         # M2 module gear optimization rules
├── README.md
└── gcode_research.md       # Full survey of existing tools
```

**Quick add to QIDIStudio:**

```
"C:\...\python.exe" "C:\...\GCodeRefiner\refiner.py" --rules m2_gear --verbose
```

**Feature type markers** (from slicer comments `;TYPE:...`):
`OUTER_WALL`, `INNER_WALL`, `SPARSE_INFILL`, `SOLID_INFILL`, `BRIDGE`, `SUPPORT`,
`SKIRT_BRIM`, `PRIME_TOWER`

**M2 gear settings (key overrides):**

| Feature        | Speed  | Temp  | Fan  |
| -------------- | ------ | ----- | ---- |
| Outer wall     | 20mm/s | 275°C | 0%   |
| Bridge         | 20mm/s | 265°C | 100% |
| First 2 layers | 10mm/s | 280°C | 0%   |

---

## 13. Our Modifications vs Upstream

All changes relative to `QIDITECH/QIDIStudio` main branch:

### Applied Changes (in forked source)

| File                                    | Change                                                                                                                                                 | Reason                                                                                    |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `src/slic3r/GUI/wxExtensions.cpp:1048`  | Restored 3 mode buttons (Simple, Advanced, Developer)                                                                                                  | Mode switcher was completely hidden                                                       |
| `src/slic3r/GUI/MainFrame.cpp:197`      | First-run default: `user_mode="develop"`, `developer_mode=true`                                                                                        | Users start in full-access Developer mode                                                 |
| `src/libslic3r/AppConfig.cpp:452`       | `iot_environment` default `"2"` → `"3"` in `QDT_RELEASE_TO_PUBLIC=0` branch                                                                            | Connects to production cloud, not staging                                                 |
| `src/slic3r/CMakeLists.txt:638`         | `if(QDT_RELEASE_TO_PUBLIC)` → `if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")`                                                                            | Prevents false-positive evaluation causing missing-file build error                       |
| `src/slic3r/GUI/Gizmos/GLGizmoText.hpp` | Added public `create_volume(ModelVolumeType, const Vec2d&)` and `create_volume(ModelVolumeType)`                                                       | Enables text volume creation from menu without duplicating placement logic                |
| `src/slic3r/GUI/Gizmos/GLGizmoText.cpp` | Refactored `on_shortcut_key()` to delegate to `create_volume(MODEL_PART)`; `create_volume()` accepts volume type                                       | Fixes menu-invoked text placement                                                         |
| `src/slic3r/GUI/GUI_Factories.cpp`      | Uncommented + fixed text branch: `GLGizmoText`/`GLGizmosManager::Text`; added `append_menu_item_add_text()`; wired into `append_submenu_add_generic()` | "Add Part > Text" menu item was entirely dead (commented out with OrcaSlicer class names) |
| `src/slic3r/GUI/GUI_Factories.hpp`      | Added `append_menu_item_add_text()` declaration                                                                                                        | Header needed for new factory function                                                    |
| `src/slic3r/GUI/Gizmos/GLGizmoSVG.hpp`  | Added `draw_tiling()` declaration; added `m_tile_x=1`, `m_tile_y=1`, `m_tile_gap=0.f` members                                                          | SVG tiling state                                                                          |
| `src/slic3r/GUI/Gizmos/GLGizmoSVG.cpp`  | Added `draw_tiling()` UI function; added tiling replication logic in `process_job()`; wired `draw_tiling()` call into `draw_window()`                  | SVG tiling feature — repeat SVG pattern in a configurable grid                            |
| `src/slic3r/GUI/Plater.cpp`             | Added `apply_skin_to_selection()` + `can_apply_skin()` functions                                                                                       | New "Add Skin…" right-click menu action                                                   |
| `src/slic3r/GUI/Plater.hpp`             | Added `apply_skin_to_selection()`, `can_apply_skin()` declarations                                                                                     | Header for above                                                                          |
| `src/slic3r/GUI/GUI_Factories.cpp`      | Wired "Add Skin…" into object context menu via `append_menu_items_add_skin()`                                                                          | Menu entry to invoke the Add Skin feature                                                 |
| `resources/scripts/apply_skin.py`       | New Python script: heightmap displacement with triplanar projection. Preserves 3MF slicer settings.                                                    | The actual skin application logic called by Plater                                        |

### Feature: "Add Part > Text" Menu (fixed)

**Root cause:** `GUI_Factories.cpp` had the text/emboss branch commented out with `/* ... */`, and the code inside used OrcaSlicer class names (`GLGizmoEmboss`, `GLGizmosManager::Emboss`) instead of QIDI's names (`GLGizmoText`, `GLGizmosManager::Text`).

**QIDI naming vs OrcaSlicer naming:**

| Concept                 | OrcaSlicer                | QIDI                    |
| ----------------------- | ------------------------- | ----------------------- |
| Text emboss gizmo class | `GLGizmoEmboss`           | `GLGizmoText`           |
| EType enum value        | `GLGizmosManager::Emboss` | `GLGizmosManager::Text` |

`GLGizmoText` and OrcaSlicer's `GLGizmoEmboss` are effectively the same codebase with different names. Both use `EmbossShape`, `EmbossJob`, `TextConfiguration`, `StyleManager` infrastructure.

**Neither OrcaSlicer nor QIDI has PNG/Texture-to-geometry support.** `GLGizmoSVG` hard-checks for `.svg` extension. `GLGizmoEmboss`/`GLGizmoText` are font/text only. There is no `GLGizmoImage` in either codebase.

### Feature: "Add Part > SVG" Tiling

Adds a **Tile size** (mm) box, **Auto Tile** button, **Tile X / Tile Y** spinners, and a **Gap** field to the SVG gizmo panel. Setting X/Y > 1 replicates the single-tile polygon grid before meshing, creating a repeating surface pattern.

**Architecture:**

- Tiling happens entirely in `process_job()` — gizmo state always stores a single tile (`m_volume_shape`); replicated grid exists only in the temporary `EmbossShape shape` passed to the background mesh job.
- `BoundingBox tile_bb = get_extents(m_volume_shape.shapes_with_ids)` gives the single-tile extent in integer polygon coords.
- Step formula: `step_x = tile_bb.size().x() + (coord_t)(m_tile_gap / m_volume_shape.scale)`
- Translation: `ep.translate(Point(step_x * ti, step_y * tj))` for each `ExPolygon` in each tile.
- `shape.final_shape = {}` discards the mesh cache so the background job rebuilds cleanly.
- `apply_tile_size()` — private helper; resizes SVG to `m_pixel_size × m_pixel_size` mm using the same `selection.scale()` path as `draw_size()` manual resize
- `apply_auto_tile()` — private helper; reads host object BB, computes tile counts, adjusts size for even fit, enables Use Surface, calls `apply_tile_size()`

**Known bug (FIXED 2026-02-25): Auto Tile reverts to 1×1 after completion**

Root cause: `process_job()` creates a NEW `ModelVolume` for the same SVG each run. The resulting selection change fires `set_volume_by_selection()` which was unconditionally resetting `m_tile_x=1, m_tile_y=1, m_pixel_size=0`. The next draw frame seeded `m_pixel_size` from the SVG bbox width, making it look like Auto Tile "changed the tile size back" and produced a single blank tile block.

Fix: `set_volume_by_selection()` now compares `svg_file->path` between the incoming volume and the current `m_volume`. If paths match (`same_svg=true`), tile state is preserved. Reset only happens when a genuinely different SVG is loaded.

**Key types:**

- `EmbossShape.shapes_with_ids` → `ExPolygonsWithIds` = `std::vector<ExPolygonsWithId>`
- `ExPolygonsWithId` has `.id`, `.expoly` (ExPolygons), `.is_healed`
- `ExPolygon::translate(Point offset)` — single-argument form; do NOT use `translate(coord_t, coord_t)`
- `m_volume_shape.scale` — converts polygon integer coords → mm

**Workflow:**

1. Right-click object → Add Part > SVG → pick SVG file
2. Set **Tile size** (mm) — the SVG is resized to a square of that size
3. Press **Auto Tile** → computes exact tile count for the object surface, enables Use Surface, adjusts size for even fit
4. Fine-tune **Tile X / Tile Y** manually if needed; **Gap** appears when X or Y > 1

**Auto Tile algorithm:**

- Gets bounding box of all `MODEL_PART` volumes on the host (excludes SVG volume itself); falls back to `ModelObject::raw_bounding_box()`
- Sorts the 3 BB dimensions; uses the two largest as `canvas_w × canvas_h`
- `tile_x = round(canvas_w / pixel_size)`, `tile_y = round(canvas_h / pixel_size)`
- Adjusts `pixel_size = canvas_w / tile_x` so tiles fit canvas_w exactly
- Sets `m_volume_shape.projection.use_surface = true` automatically

**Limits:** X and Y clamped to `[1, 50]`; gap clamped to `[-50, 200]` mm; tile size `[0.1, 500]` mm. Gap row only shown when X > 1 or Y > 1.

### Feature: "Add Texture" — Displacement Texture on Mesh via Blender

_Last updated: 2026-02-27. Replaces old trimesh/apply_skin.py pipeline entirely._

Adds **"Add Negative Part → Texture…"** and **"Add Part → Texture…"** items to the 3D object right-click menu. The feature:

1. Lets the user pick a PNG skin asset (heightmap) and set tile size + relief depth
2. Exports the model volume as a temp STL, runs `blender.exe --background --python apply_texture_bpy.py`
3. Blender applies SIMPLE subdivision + Displace modifier (vertex group restricted to top faces)
4. Script writes result STL; C++ loads it and replaces the original volume mesh in-place
5. `ensure_on_bed()` auto-repositions after displacement shifts the Z centroid

**C++ entry points:** `Plater::apply_texture()`, `Plater::adjust_texture_depth()` in `Plater.cpp`

**Script:** `resources/scripts/apply_texture_bpy.py`  
**Invocation:** `"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" --background --python apply_texture_bpy.py -- model.stl skin.png --mode modifier --log out.txt`

**Dev workflow (single source of truth):** See §Appendix D. After one-time junction setup, the workspace file IS what QIDIStudio executes — no Copy-Item, no rebuild. Standalone test: `scripts\run_texture_pipeline.ps1 -Model <stl> -Skin <png> -Output <stl>`. For debugpy attach: add `-Debug` flag.

**Full pipeline (`_apply_displacement_blender()`):**

```
0. Weld duplicate verts (bmesh remove_doubles dist=0.001)  ← STL has 1 vert per tri
1. SIMPLE SUBSURF modifier, adaptive level (≤50→4, ≤500→3, ≤5000→2, else→2)
   → modifier_apply() IMMEDIATELY so vertex group is built on final vertex set
1b. Build vertex group "TopFace": poly.normal.z > 0.5 → weight=1.0
    Walls, hole edges, fillets (normal.z ≤ 0.5) get weight=0 → untouched by Displace
2. Load PNG: colorspace="Non-Color", gamma corrected
3. Create mapping Empty at origin, scale=(tile_size, tile_size, tile_size)
   bpy.context.view_layer.update() — REQUIRED to register empty in depsgraph
4. DISPLACE modifier:
     texture_coords='OBJECT', texture_coords_object=empty
     strength=relief_mm, mid_level=0.0, direction='NORMAL'
     vertex_group="TopFace"
5. modifier_apply("Displace")
6. Export result to STL via pure-Python binary writer (no add-on needed)
   Print "SKIN_OUTPUT: <path>" to stdout + log
```

**C++ reload flow (`apply_texture()`):**

- Export `mo->raw_mesh()` to `%TEMP%\qidi_tex_src_*.stl`
- Run Blender with `wxEXEC_BLOCK` (= `wxEXEC_SYNC | wxEXEC_NOEVENTS` — CRITICAL, see gotcha below)
- Parse `SKIN_OUTPUT:` line from log file
- Load result STL → find first `is_model_part()` volume → `vol->set_mesh(std::move(mesh))`
- `vol->source.input_file = result_stl` — needed for `can_adjust_texture_depth()` check
- Write sidecar JSON: `result_stl + ".texture.json"` with `{png, src_stl, tile_mm, relief, mode}`
- `changed_object(obj_idx)` → `ensure_on_bed()` → reloads 3D scene

**Why Blender instead of trimesh:**

- Blender SIMPLE subdivision handles all edge cases cleanly (CAD parts, organic shapes)
- Displace modifier evaluates per-polygon normals correctly; no vertex-loop artifacts
- Vertex group support restricts displacement to top faces only (critical for CAD holes)
- trimesh `subdivide_to_size` produced "cracked mud" on complex geometry; removed

**Key bugs fixed / design decisions:**

| Bug / Finding                            | Root cause                                                                                                    | Fix/Decision                                                                                                 |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Displacement spikes on CAD parts         | Long thin triangles radiate from holes/fillets in STL; SIMPLE subdiv preserves them; Displace spikes each tip | Vertex group `TopFace` (normal.z > 0.5): walls and holes excluded entirely                                   |
| `calc_normals_split()` AttributeError    | Removed in Blender 4.1+                                                                                       | Use `poly.normal` directly (no method call needed)                                                           |
| Voxel Remesh destroyed holes             | Remesh treats geometry volumetrically, fills bores                                                            | Removed; vertex group instead                                                                                |
| `direction='NORMAL'` radial streaks      | CAD edge-adjacent verts have non-upward normals; NORMAL mapping follows those                                 | `direction='NORMAL'` is correct with vertex group — walls excluded so only truly top-facing normals displace |
| Zero displacement despite correct script | Mapping Empty not in depsgraph when Displace modifier evaluates                                               | `bpy.context.view_layer.update()` after linking Empty, BEFORE adding Displace modifier                       |
| `mid_level=0.5` caused inward push       | [0..1] PNG: dark=0→ delta=-0.5×strength (inward)                                                              | `mid_level=0.0`: black=baseline, white=+relief, no inward push                                               |
| Vertex group invalidated after subdiv    | Group built on pre-subdiv vertices; apply changes indices                                                     | Apply Subdiv FIRST, then build vertex group on final vertex set                                              |
| bpy pip package silent zero displacement | `bpy.ops.object.convert()` unreliable in background mode for bpy package                                      | Hard `sys.exit(1)` if `IS_FULL_BLENDER=False` — no fallback                                                  |
| `wxEXEC_SYNC` crash during bpy execution | Sync runs wx event loop; paint/timer handlers access stale `scene_selection()`                                | Use `wxEXEC_BLOCK` (`= wxEXEC_SYNC \| wxEXEC_NOEVENTS`) — no event pumping                                   |

**CLI / script parameters (`apply_texture_bpy.py`):**

```bash
apply_texture_bpy.py <model.stl> <skin.png>
    [--mode modifier|part|negative]   # always use modifier
    [--tile-size 15]                   # texture repeat in mm (default 15)
    [--relief 1.0]                     # displacement depth in mm (default 1.0)
    [--invert]                         # invert heightmap direction
    [--gamma 0.7]                      # power curve on texture before displacing
    [--log <logfile>]                  # write log to file (C++ reads SKIN_OUTPUT: line)
```

**`_adaptive_subd_level()` table:**

| Face count | Subdiv level | Rationale                  |
| ---------- | ------------ | -------------------------- |
| ≤ 50       | 4            | Primitive test shapes      |
| ≤ 500      | 3            | Simple mechanical parts    |
| ≤ 5000     | 2            | Typical imported part      |
| > 5000     | 2            | Cap to avoid RAM explosion |

**Skin assets location:** `resources/assets/` (subfolders: `armadillo_plates/`, `dragon_scales/`, etc.)  
Assets are AI-generated PNGs (Vertex AI Imagen 3 or Replicate Flux Schnell) via `scripts/generate_skin_assets.py`.

**Sidecar JSON** (`<result_stl>.texture.json`): `{png, src_stl, tile_mm, relief, mode}` — enables `adjust_texture_depth()` to re-run bpy on the original mesh. Note: `src_stl` is a `%TEMP%\qidi_tex_src_*.stl` — valid only for the current session. Long-term fix needed: save src_stl alongside the project.

### Planned Improvements

- [ ] Restore more developer/debug UI elements locked behind `internal_developer_mode`
- [ ] Add QIDIStudio as a build target in GitHub Actions CI
- [ ] Investigate replacing `qidi_networking.dll` with open implementation for LAN printing
- [ ] Expose more filament/process parameters that QIDI hid in presets
- [ ] Add GCodeRefiner as an optional post-processor template in default presets
- [ ] Fix temperature resolution so custom filament presets work correctly in gcode templates

---

## 14. Development Tooling & Memory System

### LanceDB Persistent Memory

Session knowledge is stored in a GCS-backed LanceDB vector DB at `gs://qidistudio-lancedb/lancedb`, table `qidistudio_learnings`.

| Property        | Value                                                                              |
| --------------- | ---------------------------------------------------------------------------------- |
| Embedding model | `all-MiniLM-L6-v2` (sentence-transformers), 384-dim                                |
| Total chunks    | 58 (as of 2026-02-27)                                                              |
| Sources indexed | `copilot-instructions.md`, `QIDISTUDIO_KNOWLEDGE.md`, `memory/langsmith_prompt.md` |

**Key commands:**

```powershell
# Re-index all source docs:
& 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory/extract.py

# Inject manifest into prompt / run query:
& 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory/inject.py
& 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory/inject.py --query "blender pipeline"

# Push system prompt to LangSmith Hub:
& 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory/push_prompt.py
```

### LangSmith Hub — Known Gotchas

**Gotcha 1: Tenant mismatch when using handle prefix**

- `client.push_prompt("damienfosborn/prompt-name", ...)` → `Cannot create a prompt for another tenant. Current tenant: None`
- Fix: Use **simple name** (no `handle/` prefix) + pass `workspace_id` to `Client()`:

  ```python
  ws_id  = os.getenv("LANGSMITH_WORKSPACE_ID")  # "073a725b-..."
  client = Client(api_key=api_key, workspace_id=ws_id)
  client.push_prompt("qidistudio-memory-agent", object=prompt)
  ```

**Gotcha 2: 409 "Nothing to commit" is not an error**

- LangSmith returns HTTP 409 when the pushed prompt is identical to what's already stored.
- Treat it as success: `if "409" in str(exc) and "Nothing to commit" in str(exc): print("OK, up to date")`

**Gotcha 3: ChatPromptTemplate placeholder**

- Use `("placeholder", "{messages}")` not `("human", "{input}")` — placeholder accepts a full message list.

### LanceDB API Gotchas

**Gotcha: `list_tables()` returns `ListTablesResponse` (Pydantic model), not a list**

- `"my_table" in db.list_tables()` fails silently — always evaluates False.
- Fix: `tbl_names = [t.name for t in db.list_tables()]` or `db.list_tables().tables`

**Gotcha: pandas not available in Python 3.13 env**

- `tbl.to_pandas()` raises `ImportError`.
- Fix: Use `tbl.to_arrow()` + PyArrow scanner for all query operations.

### Hooks Architecture

| Hook             | File                                   | What it does                                                      |
| ---------------- | -------------------------------------- | ----------------------------------------------------------------- |
| UserPromptSubmit | `.github/hooks/prompt_submit_hook.ps1` | Calls `memory/inject.py`; outputs manifest as `additionalContext` |
| PreCompact       | `.github/hooks/precompact_hook.ps1`    | Outputs "Save This Protocol" JSON instruction to agent            |

**Critical**: Hook shell commands are NOT visible to the agent. Only the JSON `additionalContext` output reaches the agent. All file writes must be done by the agent itself, not the hook script.

---

## 15. Computational Metrology & Geometry Processing

_PhD-level reference for high-fidelity texture mapping on 3D manifolds. All sources verified 2026-02-27._

This section documents the theory and implementation toolkit needed for **conformal UV parameterization**, **spectral shape analysis**, **geodesic distance computation**, and **inverse error compensation** — the full pipeline for physically-accurate texture projection onto non-uniform 3D surfaces (including QIDIStudio's displacement texture workflow).

---

### 15.1 Core Python Libraries

#### LibIGL Python Bindings

**Install:** `pip install libigl` (no C++ toolchain needed — prebuilt wheels on PyPI)  
**License:** GPL-3.0 / MPL-2.0. Use MPL-2.0 subset to stay LGPL-safe.  
**Docs:** <https://libigl.github.io/libigl-python-bindings/>  
**Latest release:** 2.6.1 (Jul 2025)

Key API examples (all inputs/outputs are numpy arrays or scipy sparse matrices):

```python
import igl
import scipy as sp
import numpy as np

# Load mesh
v, f = igl.read_triangle_mesh("mesh.off")  # v: (V,3) float64, f: (F,3) int32

# Cotangent Laplace-Beltrami operator — NEGATIVE semi-definite (off-diag positive)
# NOTE: sign is OPPOSITE of robust_laplacian — diagonal entries NEGATIVE
L = igl.cotmatrix(v, f)           # (V,V) scipy sparse

# Mass matrix (area weights per vertex)
M = igl.massmatrix(v, f, igl.MASSMATRIX_TYPE_VORONOI)   # (V,V) diagonal sparse
M_bary = igl.massmatrix(v, f, igl.MASSMATRIX_TYPE_BARYCENTRIC)

# Strong Laplacian: Minv @ L
Minv = sp.sparse.diags(1 / M.diagonal())
delta_f = Minv.dot(L.dot(f_scalar))

# Gaussian curvature (angle deficit)
k = igl.gaussian_curvature(v, f)  # (V,) per-vertex

# Principal curvatures and directions
v1, v2, k1, k2 = igl.principal_curvature(v, f)
H = 0.5 * (k1 + k2)  # mean curvature

# Gradient operator G: (F*3, V) maps vertex scalars to per-face gradients
G = igl.grad(v, f)
gu = G.dot(u).reshape(f.shape, order="F")  # u: (V,) scalar field

# Exact geodesic distance (Mitchell 1987 algorithm)
vs = np.array([0])        # source vertices
vt = np.arange(v.shape[0])  # target: all vertices
d = igl.exact_geodesic(v, f, vs, vt)

# Boundary detection
bnd = igl.boundary_loop(f)   # (B,) indices of boundary vertices in order

# --- PARAMETERIZATION ---

# Method 1: Harmonic (fixed circular boundary) — lowest distortion for disks
bnd_uv = igl.map_vertices_to_circle(v, bnd)
uv = igl.harmonic(v, f, bnd, bnd_uv, 1)  # 1=harmonic, 2=biharmonic

# Method 2: LSCM (Least Squares Conformal Maps) — free boundary, angle-preserving
b = np.array([bnd[0], bnd[bnd.size // 2]])
bc = np.array([[0.0, 0.0], [1.0, 0.0]])
_, uv_lscm = igl.lscm(v, f, b, bc)

# Method 3: ARAP (As-Rigid-As-Possible) — preserves distances, init with harmonic
arap = igl.ARAP(v, f, 2, np.zeros(0))
uv_arap = arap.solve(np.zeros((0, 0)), uv)  # uv = harmonic init

# Laplacian smoothing (mean curvature flow)
from scipy.sparse.linalg import spsolve
for _ in range(10):
    M = igl.massmatrix(v, f, igl.MASSMATRIX_TYPE_BARYCENTRIC)
    s = M - 0.001 * L
    v = spsolve(s, M.dot(v))
```

**Critical sign note:** `igl.cotmatrix` returns a **negative** semi-definite matrix (diagonal negative, off-diagonal non-negative). This is OPPOSITE to `robust_laplacian` which is positive semi-definite. When converting between the two, flip the sign.

#### Geometry Central (Sharp et al.)

**Install:** C++ library — no pip wheel. Python bindings are experimental and not on PyPI.  
**License:** MIT  
**Repo:** <https://github.com/nmwsharp/geometry-central>  
**Note:** The PhD manuscript lists this under Python libraries but it is primarily a **C++ geometry library**. For Python workflows, use `robust_laplacian` and `libigl` instead — they expose the same surface geometry algorithms (cotangent Laplacian, heat geodesics, parameterization) as pip-installable wheels. Geometry Central is relevant if the pipeline ever moves to a compiled C++ extension inside QIDIStudio itself.

---

#### Robust Laplacians (Sharp & Crane SGP 2020)

**Install:** `pip install robust_laplacian`  
**License:** MIT  
**Docs:** <https://github.com/nmwsharp/robust-laplacians-py>  
**Key property:** Always symmetric **positive** semi-definite. Works on non-manifold meshes, meshes with boundary, and point clouds. Internally builds an intrinsic Delaunay triangulation + intrinsic mollification.

```python
import robust_laplacian
import scipy.sparse.linalg as sla

# For a triangle mesh
L, M = robust_laplacian.mesh_laplacian(verts, faces)
# L: (V,V) sparse, POSITIVE semi-definite. M: (V,V) diagonal mass matrix

# For a point cloud
L, M = robust_laplacian.point_cloud_laplacian(points, mollify_factor=1e-5, n_neighbors=30)

# Compute first k eigenvectors (spectral basis / Shape DNA)
n_eig = 10
evals, evecs = sla.eigsh(L, n_eig, M, sigma=1e-8)
# evals: smallest eigenvalues, evecs: (V, k) eigenvectors

# Strong Laplacian (for diffusion, smoothing)
# Solve: L x = M y  (Poisson problem)
# Or form M^-1 L for the strong version
```

**Sign convention:** `robust_laplacian` is positive semi-definite — diagonal entries positive, off-diagonal negative. `igl.cotmatrix` is negative semi-definite — the opposite. When mixing the two, always flip the sign.

#### Trimesh

**Install:** `pip install trimesh` (minimal) or `pip install trimesh[easy]` (adds scipy, networkx, etc.)  
**License:** MIT  
**Docs:** <https://trimesh.org>  
**Latest:** 4.11.2 (Feb 2026)

```python
import trimesh
import numpy as np

# Load (supports STL, PLY, OBJ, GLTF/GLB, 3MF, etc.)
mesh = trimesh.load_mesh("model.stl")

# Key properties
mesh.is_watertight      # bool
mesh.volume             # float (only valid if watertight)
mesh.center_mass        # (3,) centroid
mesh.moment_inertia     # (3,3)
mesh.euler_number       # topological invariant
mesh.bounding_box.extents    # axis-aligned BB
mesh.bounding_box_oriented   # OBB

# Vertex/face access
verts  = mesh.vertices   # (V,3)
faces  = mesh.faces      # (F,3)
norms  = mesh.vertex_normals  # (V,3)

# Laplacian smoothing (3 modes available)
# Classic, Taubin (preserves volume), Humphrey
smoothed = trimesh.smoothing.filter_laplacian(mesh, lamb=0.5, iterations=10)
smoothed = trimesh.smoothing.filter_taubin(mesh)

# Boolean ops (requires manifold3d or Blender)
union = trimesh.boolean.union([mesh_a, mesh_b], engine="manifold")
diff  = trimesh.boolean.difference(mesh_a, mesh_b, engine="manifold")

# Surface sampling
points, face_idx = trimesh.sample.sample_surface(mesh, count=10000)

# Nearest point on surface + signed distance
closest, dist, tri_idx = trimesh.proximity.closest_point(mesh, query_points)
signed_dist = trimesh.proximity.signed_distance(mesh, query_points)

# Cross section (for 3D printing simulation)
section = mesh.section(plane_origin=[0,0,0], plane_normal=[0,0,1])  # returns Path3D

# Export
mesh.export("output.stl")
mesh.export("output.ply")
mesh.export("output.glb")

# From raw arrays
mesh2 = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
```

---

### 15.2 Mathematical Foundations

#### Laplace-Beltrami Operator (Cotangent Formula)

The fundamental PDE operator on surfaces. Given scalar function $f$ on a triangle mesh:

$$\Delta f(v_i) = \frac{1}{2A_i} \sum_{j \in N(i)} (\cot \alpha_{ij} + \cot \beta_{ij})(f_j - f_i)$$

where $\alpha_{ij}$ and $\beta_{ij}$ are the two angles opposite to edge $(i,j)$ in the adjacent triangles, $A_i$ is the Voronoi area at vertex $i$, and $N(i)$ are the one-ring neighbours.

**Matrix form:** $L_{ij} = (\cot\alpha_{ij} + \cot\beta_{ij})$ for $j \in N(i)$, $L_{ii} = -\sum_{k \neq i} L_{ik}$.

**Applications:** mesh smoothing, UV parameterization, heat diffusion, spectral analysis, geodesic distance.

#### Shape DNA / Spectral Fingerprint (Reuter 2006)

The eigenvalues of the Laplace-Beltrami operator are isometry-invariant shape descriptors:

$$\Delta \phi_k = \lambda_k \phi_k, \quad \lambda_0 \leq \lambda_1 \leq \lambda_2 \leq \ldots$$

The first $k$ eigenvalues $(\lambda_0, \lambda_1, \ldots, \lambda_{k-1})$ form the **Shape DNA** — a compact fingerprint that is invariant to rigid motions and scaling (if normalized). Use it to:

- Verify that a printed part matches a CAD model (compare DNA before/after printing)
- Detect manufacturing defects (abnormal eigenvalue drift)
- Drive a feedback loop for inverse error compensation

**Python implementation (from the PhD manuscript):**

```python
import numpy as np
import robust_laplacian
import scipy.sparse.linalg as sla

def get_shape_dna(verts, faces, k=20):
    """Returns first k eigenvalues of the Laplace-Beltrami operator.
    Invariant to rigid motions. Good fingerprint for shape comparison."""
    L, M = robust_laplacian.mesh_laplacian(verts, faces)
    # Use sigma close to 0 to get the smallest eigenvalues
    evals, _ = sla.eigsh(L, k=k, M=M, sigma=1e-8, which='LM')
    return np.sort(np.abs(evals))  # sort ascending, abs to handle near-zero numerical noise

def spectral_distance(dna_a, dna_b):
    """Fitness function: inverse of sum of squared differences."""
    return 1.0 / (np.sum((dna_a - dna_b)**2) + 1e-12)
```

#### Conformal Mapping (Angle-Preserving UV Parameterization)

A **conformal map** preserves angles but not necessarily areas. It is the lowest-distortion parameterization for texture mapping. Three implementations available:

| Method                         | Boundary       | Distortion                    | Use case                  |
| ------------------------------ | -------------- | ----------------------------- | ------------------------- |
| Harmonic                       | Fixed (circle) | Area distortion possible      | Simple disk-topology mesh |
| LSCM (Least Squares Conformal) | Free           | Minimizes angular distortion  | General open meshes       |
| ARAP (As-Rigid-As-Possible)    | Free           | Minimizes distance distortion | When distances matter     |
| SCP (Spectral Conformal)       | Free, spectral | Near-optimal conformal        | Research-grade quality    |

The **Spectral Conformal Parameterization (SCP)** algorithm (DDG course, CMU):

1. Build the complex cotangent Laplacian $L_c$
2. Build the area matrix $A$ from boundary halfedge traversal
3. Minimize conformal energy $E_C(z) = E_D(z) - A(z)$
4. Find eigenvector corresponding to smallest eigenvalue via inverse power method

#### Geodesic Distance (Heat Method — Crane 2013)

Computing shortest-path distances on curved surfaces. The **Heat Method** is O(n) after precomputation:

1. **Diffuse heat:** solve $(M - t L) u = \delta_s$ (one step of heat diffusion from source $s$)
2. **Normalize gradient:** $X = -\nabla u / |\nabla u|$ (unit gradient field)
3. **Integrate:** solve $L \phi = \nabla \cdot X$ (Poisson equation for distance $\phi$)

Timestep rule: $t = h^2$ where $h$ = mean edge length.

**In libigl:**

```python
# See igl.heat_geodesics for the full precomputed version
# Manual implementation:
import scipy.sparse.linalg as sla
L = igl.cotmatrix(v, f)
M = igl.massmatrix(v, f, igl.MASSMATRIX_TYPE_VORONOI)
t = igl.avg_edge_length(v, f)**2
A = M - t * L  # heat flow operator
# source: delta at vertex 0
delta = np.zeros(v.shape[0]); delta[0] = 1.0
u = sla.spsolve(A, delta)
# normalize gradient, solve Poisson...
```

---

### 15.3 Full "Perfection" Pipeline for QIDIStudio

This is the closed-loop workflow connecting geometry processing to physical 3D printing verification:

```
STL/3MF design
      │
      ▼
1. CONFORMAL UV PARAMETERIZATION (igl.lscm or igl.harmonic)
      │  Maps 3D surface → 2D UV domain with minimal angle distortion
      ▼
2. TEXTURE APPLICATION (Blender: resources/scripts/apply_texture_bpy.py)
      │  Displacement map applied in UV space, geometry deformed
      ▼
3. SPECTRAL DNA EXTRACTION (robust_laplacian + eigsh)
      │  Compute Laplace-Beltrami eigenvalues → Shape DNA fingerprint
      │  Inject DNA into G-code header as: ; SHAPE_DNA: λ₀,λ₁,...
      ▼
4. SLICE → G-CODE (QIDIStudio)
      ▼
5. PRINT (Qidi Q2)
      ▼
6. SCAN / RECONSTRUCT printed part (photogrammetry or depth sensor → point cloud)
      ▼
6b. HAUSDORFF DISTANCE CHECK (geometric delta-validation)
      │  d_H(A,B) = max(sup_{a∈A} inf_{b∈B} d(a,b), sup_{b∈B} inf_{a∈A} d(a,b))
      │  Measures worst-case geometric deviation between scanned part and CAD model
      │  Python: scipy.spatial.distance.directed_hausdorff or trimesh.proximity.closest_point
      ▼
7. SHAPE DNA COMPARISON
      │  Compute DNA of scanned part; compare to target DNA
      │  Fitness = 1 / Σ(λ_target - λ_printed)²
      ▼
8. INVERSE ERROR COMPENSATION
      │  If fitness < threshold: pre-deform CAD model to cancel expected error
      │  Use KDTree (mathutils or scipy.spatial) for nearest-point mapping
      ▼
      └─ LOOP until fitness converges (evolutionary / gradient descent)
```

**Inverse Error Compensation implementation:**

```python
import numpy as np
from scipy.spatial import KDTree

def compensate_error(verts, gcode_points, alpha=0.8, dist_threshold=0.05):
    """
    Pre-deform mesh vertices to cancel expected print error.
    verts: (V,3) numpy array of mesh vertices (world space)
    gcode_points: (N,3) numpy array of G-code toolpath points
    alpha: correction strength (0=no correction, 1=full correction)
    """
    kd = KDTree(gcode_points)
    dists, idxs = kd.query(verts)
    corrected = verts.copy()
    mask = dists > dist_threshold
    error_vecs = gcode_points[idxs[mask]] - verts[mask]
    corrected[mask] -= error_vecs * alpha
    return corrected

def inject_dna_to_gcode(gcode_path, dna):
    """Prepend Shape DNA to G-code header for traceability."""
    dna_str = ",".join([f"{x:.4f}" for x in dna])
    with open(gcode_path, 'r') as f:
        content = f.readlines()
    with open(gcode_path, 'w') as f:
        f.write(f"; SHAPE_DNA: {dna_str}\n")
        f.writelines(content)
```

---

### 15.4 Blender Conformal UV (bpy API) — PhD Seam Strategy

_Source: "Advanced Texture Wrapping for CAD" (docs/Advanced Texture Wrapping for CAD.md, §II.1)_

**LSCM is correct for ALL manifold meshes — both organic and CAD/prismatic parts.**
The key variable is the **seam-placement threshold**, not the projection method:

| Geometry type                    | Seam angle          | Why                                                                                                                                                           |
| -------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Organic / smooth / curved shells | **60° (1.047 rad)** | Fewer seams → UV flows continuously around curves like skin                                                                                                   |
| CAD / prismatic / vacuum parts   | **30° (0.523 rad)** | Every planar panel gets its own island → zero distortion per face; seams fall exactly at design edges (port shoulders, boss rims, gasket seats, fillet roots) |

**The mathematical guarantee:** LSCM minimises $E_{LSCM}(\mathbf{u,v}) = \int_S |\nabla\mathbf{u} - \mathbf{N} \times \nabla\mathbf{v}|^2 \, dA$, which is angle-preserving by definition. On a flat (planar) face, a conformal map is also an isometry — zero stretch, zero distortion. 30° seams ensure each flat panel is a separate island, so every panel gets an exact isometric mapping.

**Critical mistake to avoid:** Using OBJECT (box-map) projection for angular CAD parts. This seems intuitive but is wrong because:

- World-space box projection is seamless only along axis-aligned faces
- Non-axis-aligned faces (angled ports, chamfers, tapered revolves) get stretch
- It cannot adapt to the per-panel orientation the way UV+seams can

**`_auto_projection()` logic in `apply_texture_bpy.py`:**

```python
# Count edges with dihedral angle >= 30°
# >= 15% → CAD/prismatic → seam_angle = 30°
# <  15% → organic/smooth → seam_angle = 60°
# Always returns ('lscm', seam_angle_rad)
```

**Blender implementation:**

```python
# Step 1: clear stale seams
bpy.ops.mesh.mark_seam(clear=True)
# Step 2: mark seams at design-edge boundaries
bpy.ops.mesh.edges_select_sharp(sharpness=0.523599)  # 30° for CAD
bpy.ops.mesh.mark_seam(clear=False)
# Step 3: LSCM conformal unwrap
bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)
```

When working inside Blender (via `apply_texture_bpy.py`), use Blender's built-in conformal unwrap rather than libIGL:

```python
import bpy, bmesh

def apply_conformal_mapping(obj, uv_name="Conformal_DNA"):
    """Apply conformal UV unwrap to obj. Works in Blender 4.x and 5.x."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    # Ensure UV layer exists
    if not bm.loops.layers.uv.get(uv_name):
        bm.loops.layers.uv.new(uv_name)
    # Select all for unwrap
    for face in bm.faces:
        face.select = True
    bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')

def get_shape_dna_blender(obj, k=10):
    """Compute Shape DNA from Blender mesh object using simple adjacency Laplacian.
    For production use, export to numpy and use robust_laplacian instead."""
    mesh = obj.data
    n = len(mesh.vertices)
    adj = np.zeros((n, n))
    for edge in mesh.edges:
        u, v = edge.vertices
        adj[u, v] = adj[v, u] = 1.0
    deg = np.diag(adj.sum(axis=1))
    laplacian = deg - adj  # combinatorial Laplacian (not cotangent)
    eigenvalues = np.linalg.eigvalsh(laplacian)
    return eigenvalues[:k]
    # NOTE: For high-quality DNA, use robust_laplacian on exported mesh, not this
```

**Note:** The simple combinatorial Laplacian (degree - adjacency) is NOT the cotangent Laplacian. It does not account for vertex areas or angles. Use only for fast approximation or in Blender where you can't easily import libIGL. For production-quality Shape DNA, export the mesh to numpy arrays and use `robust_laplacian.mesh_laplacian()`.

---

### 15.5 Texture Mapping Theory — Key Concepts

From **SIGGRAPH 2017: Rethinking Texture Mapping** (Yuksel, Tarini, Lefebvre):

**Core problem with UV maps:**

- Creating UV maps is time-consuming, requires manual authoring
- Distortions and seams degrade texture filtering quality
- UV maps are tied to a specific mesh resolution — don't survive LOD changes
- Any geometry change requires re-unwrapping

**Alternatives and when to use them:**

| Method                   | Best for                             | Notes                                |
| ------------------------ | ------------------------------------ | ------------------------------------ |
| Traditional UV           | Most cases, hardware-accelerated     | Still dominant for game assets       |
| LSCM / Conformal UV      | Artwork requiring low distortion     | Our approach for displacement maps   |
| Ptex (per-face textures) | Production VFX (Disney/Pixar)        | No seams, per-quad resolution        |
| Mesh Colors              | Direct per-vertex/edge color storage | No UV at all; interpolated at render |
| PolyCube Maps            | Geometry with box-like topology      | Low-distortion for CAD parts         |
| Volume-encoded UV        | Complex topology, no cuts            | UV stored as 3D field in volume      |

**For QIDIStudio displacement workflow:** LSCM conformal mapping is the right choice — it minimizes angular distortion (critical for even displacement), handles arbitrary topology, and produces smooth seams that are easy to hide.

---

### 15.6 DDG Key Algorithms (CMU 15-458)

From Carnegie Mellon's Discrete Differential Geometry course (K. Crane):

#### Hodge Decomposition

Any 1-form $\omega$ on a surface decomposes uniquely:
$$\omega = d\alpha + \delta\beta + \gamma$$
where $d\alpha$ is exact (gradient), $\delta\beta$ is co-exact (curl), $\gamma$ is harmonic.

**Use in QIDIStudio:** Decompose a displacement vector field into its divergence-free and curl-free components before applying it. Helps prevent mesh folding.

#### Vector Field Design (Trivial Connections)

Design smooth tangent vector fields on surfaces by solving:
$$\min_{\delta\beta} \|\delta\beta\|^2 \quad \text{s.t.} \quad d\delta\beta = u$$

where $u$ encodes desired singularities. Used for designing principal stress directions for fiber orientation in FDM printing.

#### Spectral Conformal Parameterization (SCP)

Minimize conformal energy $E_C(z) = E_D(z) - A(z)$ where `A` is the area form. Find the minimum eigenvector of the energy matrix — this gives the least-distorted flattening.

**Python:** `igl.lscm()` implements a closely related method. For true SCP, use the `buildConformalEnergy` + `solveInversePowerMethod` pattern from the CMU DDG exercises.

---

### 15.7 Install Requirements for This Stack

Add to `memory/requirements.txt` for the geometry processing toolkit:

```
# Geometry processing stack (Sec. 15)
libigl>=2.5.0
robust_laplacian>=1.0.0
trimesh[easy]>=4.0.0
scipy>=1.11.0
numpy>=1.24.0
# NOTE: geometry-central (https://github.com/nmwsharp/geometry-central) is C++ only
# — no pip wheel. Use libigl + robust_laplacian as the Python equivalent.
```

**Python version compatibility:**

- `libigl` 2.6.x: Python 3.8–3.13, prebuilt wheels available
- `robust_laplacian` 1.0.0: Python 3.8–3.12, prebuilt wheels available; may need C++ build for 3.13
- `trimesh[easy]`: Python 3.8+, fully pure Python core
- All three work in `bpy_env` (Python 3.11) and `memory_env` (Python 3.13)

**Quick validation:**

```python
import igl; print("libigl OK")
import robust_laplacian; print("robust_laplacian OK")
import trimesh; m = trimesh.creation.icosphere(); print(f"trimesh OK — icosphere: {len(m.vertices)} verts")
```

---

### 15.8 Reference Papers (PhD Manuscript Sources)

Key papers underpinning the computational metrology pipeline:

| Paper                                                                                                                                                    | Authors                                  | Relevance                                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| [Rethinking Texture Mapping](https://www.cemyuksel.com/courses/conferences/siggraph2017-rethinking_texture_mapping/)                                     | Yuksel, Tarini, Lefebvre (SIGGRAPH 2017) | Survey of UV alternatives: Ptex, Mesh Colors, PolyCube, Volume UV                                                                         |
| [Shape DNA: Spectral Geometry](https://reuter.mit.edu/papers/reuter-sig06.pdf)                                                                           | Reuter et al. (2006)                     | Laplace-Beltrami eigenvalues as isometry-invariant shape fingerprint                                                                      |
| [Conformal Geometry of Surfaces](https://archive.ymsc.tsinghua.edu.cn/pacm_download/59/11124-Shing-Tung_Yau_236.pdf)                                     | Gu & Yau                                 | Mathematical foundation for angle-preserving maps on manifolds                                                                            |
| [Texture Synthesis over Arbitrary Manifolds](https://history.siggraph.org/learning/texture-synthesis-over-arbitrary-manifold-surfaces-by-wei-and-levoy/) | Wei & Levoy (SIGGRAPH 2001)              | Patch-based texture synthesis directly on mesh surface — no UV needed                                                                     |
| [Discrete Differential Geometry (DDG)](https://brickisland.net/DDGSpring2024/)                                                                           | Crane et al. (CMU 15-458)                | Cotangent Laplacian, heat geodesics, spectral conformal parameterization                                                                  |
| [Least Squares Conformal Maps (LSCM)](https://alice.loria.fr/publications/papers/2002/lscm/lscm.pdf)                                                     | Levy et al. (2002)                       | Original LSCM paper — the algorithm behind `bpy.ops.uv.unwrap(method='CONFORMAL')`                                                        |
| [Non-Shrinking Laplacian Smoothing](https://graphics.stanford.edu/courses/cs468-12-spring/LectureSlides/06_smoothing.pdf)                                | Taubin (1995)                            | Two-pass λ+μ smoothing preserving volume. λ=0.5, μ=-0.53. **Implemented** in step 6b of `apply_texture_bpy.py` as seam-blend post-process |
| [As-Rigid-As-Possible (ARAP)](https://igl.ethz.ch/projects/ARAP/arap_web.pdf)                                                                            | Sorkine (2007)                           | Deformation preserving local rigidity — relevant for corner compensation                                                                  |
| [Mesh Parameterization Survey](https://www.inf.usi.ch/hormann/papers/Floater.Hormann.2005.SMP.pdf)                                                       | Floater & Hormann (2005)                 | Comprehensive survey of all UV parameterization methods                                                                                   |

**Phone Case / Prismatic Manifold notes** (source: `docs/Phone Case Metrology & Texture Morphing.md`, 2026-02-27):

A phone case is a **disk-topology manifold with holes** — button cutouts are punctures in the manifold. Three techniques from that doc that extend our pipeline:

- **`protect_mechanical_features`** = 30° seam + LSCM. Confirms our existing implementation is correct. ✓
- **Corner compensation** (`apply_corner_compensation`): Push high-curvature corner verts outward along their normal by ~0.05mm to pre-compensate for slicer path compression at filleted corners. _Future work — not yet in `apply_texture_bpy.py`._
- **G-Code DNA injection** (`finalize_metrology`): After slicing, embed Shape DNA eigenvalues as `; PROJECT_PERFECTION_ID: e1,e2,...` in gcode header for post-print verification. Hausdorff metric $d_H = \max_{a \in CAD} \min_{b \in GCode} \|a-b\|$ — if deviation >0.1% texture appears smeared. _Future work._

**Taubin smoothing** (step 6b, implemented 2026-02-27): Replaces the former Blender SMOOTH modifier which (a) shrank the mesh and (b) crashed with `RuntimeError` when `modifier_apply` invalidated the Python vertex-group reference. Pure-Python bmesh implementation — no modifier needed, no stale refs possible.

---

### 15.9 Troubleshooting — Geometry Stack

| Symptom                                          | Cause                                                                           | Fix                                                                                             |
| ------------------------------------------------ | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `igl.cotmatrix` gives wrong sign                 | libigl cotmatrix is negative semi-definite                                      | Flip sign: use `-L` when you need positive semi-definite                                        |
| Shape DNA comparison gives nonsensical distances | Mixed sign conventions between libigl and robust_laplacian                      | Always use one library for a full pipeline; don't mix L matrices                                |
| `eigsh` returns nan                              | Near-degenerate mesh (zero-area faces, duplicate verts)                         | Run `trimesh.repair.fix_normals + fill_holes`, or use `mollify_factor=1e-4` in robust_laplacian |
| UV seams visible in displacement texture         | Conformal map has too much angle distortion at boundary                         | Use LSCM (free boundary) instead of harmonic (fixed boundary)                                   |
| Blender `bpy.ops.uv.unwrap` fails silently       | No faces selected before calling                                                | Add `for face in bm.faces: face.select = True` before `bpy.ops.uv.unwrap()`                     |
| Shape DNA comparison false positives             | Using combinatorial Laplacian (degree-adjacency) instead of cotangent Laplacian | Use `robust_laplacian.mesh_laplacian()` for production DNA                                      |
| Inverse compensation diverges                    | alpha too high, or KDTree matching wrong points                                 | Reduce alpha (try 0.3–0.5), visualize kd.query results first                                    |

---

### 15.10 POCO X6 Pro 5G — Device-Specific PhD Manuscript

_Source: `docs/PhD-Level 3D Model Perfection.md`, Model 2311DRK48G. Absorbed 2026-02-27._

#### Device Geometry

| Property       | Value                                   | Notes                                                               |
| -------------- | --------------------------------------- | ------------------------------------------------------------------- |
| Model          | Xiaomi POCO X6 Pro 5G (2311DRK48G)      |                                                                     |
| Bezel radius   | 1.3 mm                                  | G2-continuous blend — not a simple chamfer                          |
| Rear surface   | 2.5D glass curve                        | K ≈ 0 (developable) — no angle distortion on flat back              |
| Corner fillets | Gaussian curvature K > 0                | Must use LSCM conformal mapping to prevent "Skin Bunching"          |
| Camera island  | ~genus-1 equivalent, 4 circular cutouts | High-stress zone for UV seams — seam must go around island boundary |

The case is a **disk-topology manifold with holes** (button cutouts = punctures). The camera island adds a genus-1 topological handle/hole — standard planar UV unwrap fails here. LSCM with free boundary handles it correctly.

#### Seam Placement Strategy

```python
# Curvature-based seam at camera island boundary
bpy.ops.mesh.edges_select_sharp(sharpness=0.6)   # ~34 degrees
bpy.ops.mesh.mark_seam(clear=False)

# LSCM conformal unwrap — minimises shearing around quad-camera layout
bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.002)
```

`sharpness=0.6` rad (~34°) targets the island boundary. Using CAD_THRESH=0.35 in `_auto_projection()`, this device will be classified as **CAD/prismatic** and receive 30° seams automatically — which is correct.

#### Shape DNA (Per-Device Fingerprint)

The doc uses a **combinatorial Laplacian** (degree matrix − adjacency), NOT cotangent. For device identification (not shape comparison), this is acceptable — the combinatorial Laplacian is fast on large meshes.

```python
import numpy as np

num_verts = len(mesh.vertices)
adj = np.zeros((num_verts, num_verts))
for edge in mesh.edges:
    u, v = edge.vertices
    adj[u, v] = adj[v, u] = 1.0
deg = np.diag(adj.sum(axis=1))
laplacian = deg - adj
dna = np.linalg.eigvalsh(laplacian)[:10]   # first 10 eigenvalues = Shape DNA
print(f"POCO X6 Pro Shape DNA: {dna}")
```

> **Production note:** For texture metrology (comparing printed vs CAD), use `robust_laplacian.mesh_laplacian()` (cotangent). For device ID only, combinatorial is fine.

#### Corner Compensation Formula

At every high-curvature vertex on the corner fillet, apply a pre-deformation $\delta$ along the outward normal:

$$\mathbf{v}_{new} = \mathbf{v} + \alpha(H)\,\mathbf{n}$$

where $H = \frac{\kappa_1 + \kappa_2}{2}$ is the **Mean Curvature** at that vertex.

This "fattens" the model at corners so the slicer's path smoothing shrinks it back to exact CAD dimensions. _Not yet implemented in `apply_texture_bpy.py` — future work._

#### G-Code Metrology Threshold

$$d_H(\text{CAD},\, \text{GCode}) \;=\; \max_{a \in \text{CAD}} \min_{b \in \text{GCode}} \|a - b\| < 0.05\,\text{mm}$$

Tighter than the 0.1% threshold from the previous phone case doc — 0.05 mm absolute is the spec for a well-fitting POCO X6 Pro case. If the camera island shows red in the Hausdorff heatmap, increase LSCM margin.

#### Workflow Summary

1. Load POCO X6 Pro case STL into Blender
2. Curvature seam at camera island boundary (`sharpness=0.6`)
3. LSCM unwrap (`method='CONFORMAL'`, `margin=0.002`)
4. Apply displacement texture via `apply_texture_bpy.py`
5. Compute Shape DNA → embed as `; PROJECT_PERFECTION_ID: e1..e10` in gcode header
6. Slice → compare Hausdorff to CAD → must be < 0.05 mm
7. If fail: increase LSCM margin or apply corner compensation

---

### 15.11 Polymorphic Mesh Topology Classifier (apply_texture_bpy.py)

_Implemented 2026-02-28. Replaces the single-heuristic `_auto_projection()` function._

#### Problem it solves

The old `_auto_projection()` used only **one feature** (sharp-edge fraction >= 35%) to distinguish CAD from organic meshes. This failed for:

- Ornamental flat panels (elvish back shell) where dense channels push sharp fraction below 35% → misclassified as organic → LSCM UV → spike fans
- Tall cylindrical bottles that happen to have many hard edges → misclassified as CAD → OBJECT coords → stretched pattern
- Any new part type that doesn't fit the 35% heuristic

**Core principle:** Stop modifying code per part — measure the mesh's intrinsic topology and dispatch to the correct strategy automatically (Wadler 1998, The Expression Problem).

#### Three-feature classifier

| Feature          | How measured                                     | What it detects               |
| ---------------- | ------------------------------------------------ | ----------------------------- |
| `sharp_fraction` | % of dihedral edges ≥ 30°                        | CAD / prismatic indicator     |
| `z_ratio`        | Z-span / max(X-span, Y-span)                     | Flat shell vs tall/revolution |
| `curvature_std`  | Std-dev of per-vertex Gaussian angle-deficit K_v | Organic curved vs flat        |

Gaussian angle-deficit: `K_v = 2π − Σ(interior angles at v across incident faces)`. Flat vertex → K≈0. Curved/corner vertex → K≠0. (Source: CMU 15-458 DDG §6.)

#### MeshClass enum

```python
class MeshClass(Enum):
    FLAT_SHELL  = auto()   # z_ratio < 0.25  → lid, back panel, tray
    PRISMATIC   = auto()   # sharp_frac >= 0.35  → enclosure, box
    REVOLUTION  = auto()   # z_ratio >= 1.0, low sharp  → bottle, vase
    ORGANIC     = auto()   # everything else  → dragon, figurine
```

#### UV strategy dispatch (match/case, PEP 634)

```python
match sig.mesh_class:
    case MeshClass.FLAT_SHELL | MeshClass.PRISMATIC:
        projection = 'object'   # world-space XY box-map, no UV seams
        full_surface = False    # top-facing faces only
    case MeshClass.REVOLUTION:
        projection = 'lscm'     # conformal UV, 30° seams
        full_surface = True
    case MeshClass.ORGANIC:
        projection = 'lscm'     # conformal UV, 60° seams
        full_surface = True
```

#### Classification thresholds

| Class      | Rule                            | Rationale                                              |
| ---------- | ------------------------------- | ------------------------------------------------------ |
| FLAT_SHELL | z_ratio < 0.25                  | Any plate thinner than 25% of its footprint is a shell |
| REVOLUTION | z_ratio >= 1.0 AND sharp < 0.20 | Taller than wide, smooth → cylindrical                 |
| PRISMATIC  | sharp_frac >= 0.35              | High hard-edge density → box/enclosure CAD             |
| ORGANIC    | everything else                 | Low sharp, moderate height → curved freeform           |

FLAT_SHELL takes precedence over all (checked first in match block).

#### Session log

```
sharp_fraction, z_ratio, K_std → MeshClass → coords + full_surface
elvish_back_shell: sharp=38%, z_ratio=0.12  → FLAT_SHELL → OBJECT, top-face
dragon_body:       sharp=4%,  z_ratio=0.55  → ORGANIC    → LSCM 60°, full
bottle:            sharp=8%,  z_ratio=1.8   → REVOLUTION → LSCM 30°, full
enclosure:         sharp=71%, z_ratio=0.40  → PRISMATIC  → OBJECT, top-face
```

#### References

- Reuter 2006 — Shape DNA: spectral geometry for shape recognition
- Lévy et al. 2002 — Least Squares Conformal Maps for automatic texture atlas generation
- Wadler 1998 — The Expression Problem (open/closed dispatch)
- CMU 15-458 DDG §6 — Discrete Gaussian curvature (angle-deficit)
- Chazal 2009 — Persistence-based Shape Descriptors (Euler characteristic)
- docs/Shape Classification for Transformation Methods.md — absorbed 2026-02-28
- docs/Advanced Python Transform Pipelines.md — absorbed 2026-02-28
- docs/Spectral Shape Analysis and Transforms.md — absorbed 2026-02-28 (Euler char, spectral verification)
- docs/Geometric Shape Classification via Spectral DNA.md — absorbed 2026-02-28 (eigenvalue ratio λ₁/λ₂)

#### Spectral Verification Details (from new papers)

`_compute_shape_dna()` now accepts `expected_class: MeshClass` and logs a `*** TOPOLOGY MISMATCH ***` line if the DNA contradicts the classifier:

| λ₁/λ₂ ratio | Interpretation                                   | Expected class             |
| ----------- | ------------------------------------------------ | -------------------------- |
| > 0.85      | Degenerate eigenvalue pair → rotational symmetry | `REVOLUTION`               |
| 0.50–0.85   | Moderate asymmetry                               | `ORGANIC`                  |
| < 0.50      | Strong asymmetry, spread spectrum                | `FLAT_SHELL` / `PRISMATIC` |

**How to use for debugging:** Run apply texture, open `%TEMP%\qidi_texture.log`, search for `TOPOLOGY MISMATCH`. If found, inspect the three feature values (`sharp`, `z_ratio`, `χ`) to determine which threshold needs adjusting.

#### Euler characteristic as tiebreaker

χ = V − E + F is computed before `bm.free()` and stored in `TopologySignature.euler_characteristic`:

- REVOLUTION dispatch now requires `euler_char <= 0` (annular manifold — has a through-hole)
- Tall smooth mesh with χ > 0 → classified as ORGANIC (e.g. figurine on pedestal), not REVOLUTION
- Phone cases with multiple cutouts have χ << 0 but are already caught by FLAT_SHELL (z_ratio < 0.25) first

---

### 15.12 Strategy Pattern — Polymorphic Dispatch Architecture

_Source: docs/PhD Research Project Architecture Guide.md, absorbed 2026-02-28._

The current `MeshClass` enum + `match/case` dispatch in `_classify_mesh_topology()` IS the Strategy Pattern — each `MeshClass` value selects a distinct transformation strategy. The formal ABC version below shows the canonical PhD-level structure for any future expansion.

#### SRC Layout (canonical project structure)

```
resources/scripts/
├── apply_texture_bpy.py       # Entry point — orchestrates the pipeline
├── core/
│   ├── laplacian.py           # Spectral DNA & heat diffusion (future split-out)
│   └── parameterize.py        # LSCM & ARAP algorithms
├── classification/
│   └── heuristics.py          # TopologySignature + MeshClass (future split-out)
└── io/
    └── blender_api.py         # bpy wrappers (future split-out)
```

Currently all logic lives in `apply_texture_bpy.py`. The SRC layout above is the target split for when the script exceeds ~1500 lines.

#### Formal Strategy Pattern (future refactor target)

```python
from abc import ABC, abstractmethod

class ProjectionStrategy(ABC):
    """Each MeshClass maps to one ProjectionStrategy subclass."""
    @abstractmethod
    def unwrap(self, bm, obj, log) -> None:  # modifies UV layer in-place
        pass

class FlatObjectProjection(ProjectionStrategy):
    """FLAT_SHELL + PRISMATIC: OBJECT projection (no UV unwrap needed)."""
    def unwrap(self, bm, obj, log):
        log("Strategy: FlatObjectProjection")
        # texture_coords='OBJECT' — handled by Displace modifier directly

class LscmProjection(ProjectionStrategy):
    """REVOLUTION + ORGANIC: LSCM conformal unwrap + UV texture coords."""
    def __init__(self, seam_angle_rad: float):
        self.seam_angle_rad = seam_angle_rad
    def unwrap(self, bm, obj, log):
        log(f"Strategy: LscmProjection seam={math.degrees(self.seam_angle_rad):.0f}deg")
        # mark_seams → unwrap(method='CONFORMAL') → texture_coords='UV'
```

The `match/case` dispatcher in `_classify_mesh_topology()` returns the `TopologySignature`, which then selects the strategy. This is **Open/Closed**: adding a new `MeshClass` value only requires adding a new strategy subclass and one `case` arm — the pipeline orchestrator never changes.

#### Property-Based Testing with Hypothesis

_Source: PhD Research Project Architecture Guide.md §III. Install: `pip install hypothesis` in bpy_env._

For the spectral DNA computation — which must be invariant to mesh rotation — property-based tests are the correct methodology:

```python
# tests/test_shape_dna.py
from hypothesis import given, strategies as st
import numpy as np

@given(st.floats(min_value=-180, max_value=180),
       st.floats(min_value=-180, max_value=180))
def test_spectral_invariance_under_rotation(yaw_deg, pitch_deg):
    """
    Shape DNA (λ eigenvalues) must be invariant to rigid rotation.
    Ref: Reuter 2006 — Shape DNA is isometry-invariant.
    """
    mesh = load_test_mesh()  # canonical reference mesh
    dna_original = calculate_shape_dna(mesh)
    mesh_rotated = rotate_mesh(mesh, yaw_deg, pitch_deg)
    dna_rotated = calculate_shape_dna(mesh_rotated)
    assert np.allclose(dna_original, dna_rotated, atol=1e-4)
```

#### Google-Style Docstrings (enforced in apply_texture_bpy.py)

All functions added to `apply_texture_bpy.py` use Google-style docstrings with the mathematical "Why":

```python
def _classify_mesh_topology(obj, log) -> TopologySignature:
    """Classifies mesh topology using 4 geometric features.

    Args:
        obj: Blender Object with mesh data.
        log: Callable accepting a string; writes to pipeline log.

    Returns:
        TopologySignature frozen dataclass containing MeshClass and
        all raw feature values for downstream debugging.

    Note:
        Feature 1: sharp_fraction — edges with dihedral >= 30deg / total edges.
        Feature 2: z_ratio — Z-span / max(X-span, Y-span). > 1.0 = tall part.
        Feature 3: curvature_std — std-dev of discrete Gaussian curvature
            K_v = 2pi - sum(interior angles). Meyer et al. 2003.
        Feature 4: euler_characteristic — chi = V-E+F. chi <= 0 = annular
            manifold (has through-holes). Chazal 2009.
    """
```

---

### 15.13 Hybrid C++/Python Debugging

_Sources: docs/Debugging C++ and Python Systems.md, docs/PhD-Level Hybrid Debugging Workflow.md. Absorbed 2026-02-28._

QIDIStudio is a hybrid system: C++ (`Plater.cpp`) invokes Python (`apply_texture_bpy.py`) via `wxExecute`. The **Abstraction Gap** — Python's debugger cannot see the C++ heap; C++ debuggers see Python objects only as opaque `PyObject*` — is bridged via the techniques below.

#### Applied: faulthandler (already in apply_texture_bpy.py)

```python
import faulthandler, sys
faulthandler.enable(file=sys.stderr, all_threads=True)
```

Added immediately after imports. If Blender's C++ geometry kernel segfaults during Displace modifier evaluation or bmesh operations, Python dumps the last Python frame to stderr before dying. The stderr of the Blender subprocess is captured by QIDIStudio in `tex_log` — so the crash traceback appears in `%TEMP%\qidi_texture.log`.

#### Debug Build (Windows)

When hunting geometry bugs that only appear in Release builds, use `scripts\debug_build.ps1`:

```powershell
.\scripts\debug_build.ps1
```

What it does:

- Configures CMake with `CMAKE_BUILD_TYPE=RelWithDebInfo` (optimized + debug symbols `/Zi`)
- Enables MSVC AddressSanitizer (`/fsanitize=address`) to catch buffer overruns in mesh processing
- Output goes to `C:\QIDISrc\QIDIStudio\build_debug\`

MSVC ASan equivalent of GCC's `-fsanitize=address`: add `/fsanitize=address` to `CMAKE_CXX_FLAGS`. Requires VS 2019 16.9+ or VS 2022.

#### Mixed-Mode Debugging (C++ stepping from Python callsite)

For stepping from `Plater.cpp`'s `wxExecute` call into C++ geometry code:

1. Open the project in full Visual Studio (not VS Code)
2. Project → Properties → Debugging → **Debugger Type: Mixed**
3. Set breakpoint in C++ (`Plater.cpp apply_texture()`) and Python (`apply_texture_bpy.py _apply_displacement_blender()`)
4. VS will context-switch between Python frames and C++ frames in the same call stack view

#### debugpy Attach (Python-only, most common)

For Blender Python-only debugging (no C++ stepping needed):

```powershell
.\scripts\run_texture_pipeline.ps1 -Model model.stl -Skin skin.png -Output out.stl -Debug
# VS Code: Run & Debug -> Python: Remote Attach -> localhost:5678
```

`-Debug` sets `QIDI_BPY_DEBUG=1` which triggers `debugpy.listen(5678); debugpy.wait_for_client()` inside the script.

#### Golden Buffer Dump (geometry crash isolation)

When a geometry crash only reproduces inside a specific mesh:

```python
# Add to _apply_displacement_blender() before the crashing modifier_apply call:
import numpy as np
verts = np.array([v.co for v in obj.data.vertices])
np.save(r'C:\Temp\crash_verts.npy', verts)
faces = np.array([list(p.vertices) for p in obj.data.polygons], dtype=object)
np.save(r'C:\Temp\crash_faces.npy', faces)
log("CRASH_DUMP: saved verts/faces to C:\\Temp\\crash_*.npy")
```

Then reproduce in a standalone Python script without Blender overhead.

#### Debugging Bibliography (applied to this codebase)

| Resource                        | Applied where                                      |
| ------------------------------- | -------------------------------------------------- |
| faulthandler (Python stdlib)    | `apply_texture_bpy.py` — catches C++/bpy segfaults |
| debugpy + VS Code Remote Attach | `run_texture_pipeline.ps1 -Debug` flag             |
| MSVC `/fsanitize=address`       | `scripts/debug_build.ps1` CMake config             |
| Mixed-Mode Debugging (VS)       | Full Visual Studio, Debugger Type=Mixed            |
| GDB `py-bt`                     | Linux/Mac dev machines only                        |
| Golden Buffer Dump              | Inline npy export before crashing bpy call         |

---

### 15.14 Vision-in-the-Loop (ViL) — Autonomous AI Debug Architecture

_Absorbed 2026-02-28. Sources: AI-Driven Visual Debugging Orchestration.md, AI Debugging Visual Geometry Pipeline.md. External refs: GPT-4V (arXiv 2303.08774), Keenan Crane CMU 15-458 DDG Spring 2024, VQA (visualqa.org)._

#### Concept

ViL is a self-directed debug loop that requires **no human operator**:

```
Observe  →  Orient  →  Decide  →  Act
 (JSON       (compare     (identify    (edit
  telemetry   vs expected  threshold    classifier
  + PNGs)     class)       anomaly)     code)
```

This is Boyd's OODA loop applied to geometric ML. GPT-4V (arXiv 2303.08774) validates that
multimodal models can reason over image+JSON inputs to produce corrective text — here the
"image" is the curvature heatmap PNG and the "JSON" is the telemetry record.

#### Infrastructure

**`apply_texture_bpy.py` additions (2026-02-28)**

| Symbol                            | Purpose                                                                                                     |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `_DebugSession` dataclass         | Accumulates `stages` list; created in `main()` when `--debug-snapshots` is set                              |
| `_export_debug_snapshot()`        | Writes stage JSON + rolling `session_summary.json`; called at `post_weld`, `post_classify`, `post_displace` |
| `_render_curvature_heatmap()`     | EEVEE vertex-colour render of Gaussian K_v; activated by `--render-heatmap`                                 |
| `--debug-snapshots` argparse flag | Activates telemetry export                                                                                  |
| `--snapshots-dir` argparse flag   | Output directory (default: same dir as `--log`)                                                             |

#### JSON Telemetry Schema

Each stage writes one JSON file `{stage}.json` and a rolling `session_summary.json`:

```json
{
  "model": "/path/to/source.3mf",
  "skin": "/path/to/skin.png",
  "timestamp": "2026-02-28T15:30:00",
  "stage": "post_classify",
  "mesh_class": "FLAT_SHELL",
  "features": {
    "sharp_fraction": 0.12,
    "z_ratio": 0.08,
    "curvature_std": 0.03,
    "euler_characteristic": -4
  },
  "projection": "object",
  "full_surface": false,
  "seam_angle_deg": 30.0,
  "geometry": {
    "verts": 9248,
    "polys": 18432,
    "bbox_mm": [72.4, 148.3, 8.2]
  },
  "heatmap_png": null,
  "weld_before": 18432,
  "weld_after": 9248
}
```

#### Autonomous Debug Script

**`scripts/ai_debug_pipeline.py`** — run `python scripts/ai_debug_pipeline.py` from any Python.

```
Usage:
  python scripts/ai_debug_pipeline.py                   # all test cases
  python scripts/ai_debug_pipeline.py --case poco_x6_phone_case
  python scripts/ai_debug_pipeline.py --render-heatmap  # include EEVEE PNGs (slow)
```

Writes `scripts/debug_runs/<run_id>/ai_debug_report.txt` and `.json`.
The AI reads `ai_debug_report.txt` in a subsequent session to generate targeted threshold edits.

#### Test Case Registry

| Name                    | 3MF Path                                                | Expected Class | Notes                          |
| ----------------------- | ------------------------------------------------------- | -------------- | ------------------------------ |
| `poco_x6_phone_case`    | `3DPrinting/PhoneCase/STL/protection-poco-x6.3mf`       | `FLAT_SHELL`   | 148×73×8 mm flat slab          |
| `elvish_tpu_inner`      | `3DPrinting/PhoneCase/STL/elvish_tpu_inner.3mf`         | `FLAT_SHELL`   | Ornamental flat back panel     |
| `vacuum_nozzle_lower`   | `3DPrinting/VacuumNozzle/STL/vacuum_nozzle_lower.3mf`   | `REVOLUTION`   | Rotational body, tall cylinder |
| `vacuum_crevice_nozzle` | `3DPrinting/VacuumNozzle/STL/vacuum_crevice_nozzle.3mf` | `PRISMATIC`    | Tapered rectangular prism      |

All 3MF files are in `C:\Users\User\source\repos\3DPrinting\` — used READ-ONLY.

#### How the AI Uses This

1. Run `python scripts/ai_debug_pipeline.py` → writes `ai_debug_report.txt`
2. Open the report — see PASS/FAIL for each case with measured feature values
3. If FAIL: the report supplies a **REMEDIATION HINT** naming which threshold to edit in `_classify_mesh_topology()`
4. Edit the threshold → re-run pipeline → confirm pass

No Blender UI, no human action needed. The AI is both the test runner and the code editor.

#### Curvature Heatmap (optional)

`_render_curvature_heatmap()` computes discrete Gaussian curvature K_v = 2π − Σ(interior angles)
per vertex and stores it as a Blender vertex-colour layer `"CurvatureMap"`. An overhead
orthographic EEVEE render produces a PNG:

- **Blue** = K ≈ 0 (flat/planar vertex)
- **Red** = K > 0 (convex — sphere-like)
- **Green** = K < 0 (saddle — hyperbolic)

This is the same Gaussian curvature used in the `curvature_std` classifier feature,
making the image a direct visual confirmation of what the classifier measured.

Refs: Chazal 2009 (Spectral Shape Analysis), CMU 15-458 DDG §6 (discrete curvature).

---

### 15.15 UV Diagnostic Debugging — Jacobian Heatmap & Texture Critic

_Implemented 2026-02-28. Sources: docs/AI Debugging 3D Texture Mapping.md, docs/AI Debugging Texture Mapping Glitches.md. External refs: Lévy 2002 (LSCM), Sander 2001 (L2 stretch), Nimier-David 2019 (Mitsuba 2 differentiable rendering), Crane 2024 (CMU 15-458 DDG)._

#### Concept

The "Geometric Microscope" pattern (docs/AI Debugging Texture Mapping Glitches.md §I):
Convert conformal mapping errors into **visual signals** (checkerboard distortion) + **metric signals**
(UV stretch / Dirichlet energy) that an AI can reason over without a human in the loop.

Key insight from Lévy 2002: LSCM minimises Dirichlet energy
$$E_D(\psi) = \int_M |\nabla\psi|^2 \, dA$$
When $E_D > 2.0$, the projection mode is wrong for the mesh topology. The AI computes $E_D$
per-pipeline-run without any rendering required.

#### New Infrastructure (2026-02-28)

**`resources/shaders/uv_diagnostic.glsl`** (new file)

GLSL fragment shader implementing the Jacobian heatmap from docs/AI Debugging Texture Mapping Glitches.md §I.
Three modes via `u_visualMode` uniform:

| Mode           | Value | Description                                                                            |
| -------------- | ----- | -------------------------------------------------------------------------------------- |
| `CHECKERBOARD` | 0.0   | 8×8 procedural grid; aspect-ratio drift > 15% = high $E_D$                             |
| `HEATMAP`      | 1.0   | `dFdx`/`dFdy` Jacobian approximation; green=conformal, red=compression, blue=expansion |
| `HYBRID`       | 2.0   | 50/50 blend weighted by local distortion magnitude                                     |

Colour semantics (HEATMAP mode):

- **Green** = $\log_2(|dx|/|dy|) \approx 0$ — conformal (angle-preserving)
- **Red** = $\log_2 > 0$ — compression zone (camera island, tight corners)
- **Blue** = $\log_2 < 0$ — expansion zone (long flat backs)
- **Yellow ring** = threshold boundary at 15% drift ($|\log_2| \approx 0.20$)

**`apply_texture_bpy.py` additions**

| Symbol                              | Purpose                                                                                                   |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `_render_checkerboard_diagnostic()` | EEVEE render using Blender Checker Texture node; 8×8 grid; shows UV island boundaries as non-square cells |
| `_calculate_uv_stretch_metrics()`   | Per-face L2 area stretch; returns `mean_stretch`, `max_stretch`, `dirichlet_energy`, `high_energy_frac`   |
| `--render-heatmap` argparse flag    | Activates both curvature heatmap AND checkerboard render at each debug stage                              |
| `checker_png` JSON field            | Path to checkerboard diagnostic PNG in each stage record                                                  |
| `uv_stretch` JSON field             | Stretch metrics dict in `post_displace` stage record                                                      |

The `uv_stretch` block is computed even without `--render-heatmap` — it is always populated at
`post_displace` whenever a UV layer exists (LSCM mode).

**`scripts/ai_texture_critic.py`** (new file)

Autonomous texture quality analyser. Reads `session_summary.json`, applies the diagnostic
decision tree, writes `ai_texture_critic_report.txt`:

```
IF uv_stretch.high_energy_frac > 0.20   → seam placement issue
IF uv_stretch.dirichlet_energy  > 2.0   → wrong projection (LSCM vs OBJECT)
IF uv_stretch.max_stretch       > 5.0   → collapsed UV island
IF mesh_class == REVOLUTION and χ > 0   → Euler characteristic tiebreaker failure
IF mean_stretch < 0.5 or > 3.0         → tile_size calibration issue
```

Each issue includes:

- **severity**: ERROR / WARNING / INFO
- **root_cause**: what geometric invariant is violated
- **remediation**: specific line of code or threshold to change

```
# Run after --debug-snapshots pipeline
python scripts/ai_texture_critic.py /tmp/snaps/session_summary.json
```

#### UV Stretch Mathematics

Per-face normalised area stretch (Sander 2001 L2 metric, simplified):
$$s_i = \frac{A_{3D,i} \cdot A_{UV,\text{total}}}{A_{UV,i} \cdot A_{3D,\text{total}}}$$

Normalised Dirichlet energy:
$$E_D = \frac{1}{A_{3D,\text{total}}} \sum_i \max\!\left(s_i,\, \frac{1}{s_i}\right) \cdot A_{3D,i}$$

$E_D = 1.0$ → perfect isometric map. $E_D > 2.0$ → significant conformal distortion.

#### Complete Debugging Workflow

```
1. blender.exe --background --python apply_texture_bpy.py -- \n   model.stl skin.png --debug-snapshots --render-heatmap --snapshots-dir /tmp/snaps

2. python scripts/ai_texture_critic.py /tmp/snaps/
   → reads session_summary.json, writes ai_texture_critic_report.txt

3. AI reads report, identifies failing check, applies specific code edit
   → e.g. lowers sharp_fraction threshold 0.35→0.25 in _classify_mesh_topology()

4. python scripts/ai_debug_pipeline.py  # re-run all test cases
   → confirms pass/fail regression.
```

#### Bibliography

| Source                        | Concept                                                            | Application                                       |
| ----------------------------- | ------------------------------------------------------------------ | ------------------------------------------------- |
| Lévy 2002 (ALICE LORIA)       | LSCM — UV mapping that minimises $E_D$                             | Primary UV algorithm in pipeline                  |
| Sander 2001                   | L2 stretch metric $\Gamma^2 = (a^2+b^2+c^2+d^2)/2A$                | `_calculate_uv_stretch_metrics()`                 |
| Nimier-David 2019 (Mitsuba 2) | Differentiable rendering — gradients of rendering w.r.t. UV params | Conceptual foundation for inverse-rendering debug |
| Crane 2024 CMU 15-458         | DDG §7 conformal parameterisation, SCP algorithm                   | Seam strategy + Euler characteristic tiebreaker   |
| Taubin 1995                   | Non-shrinking Laplacian smoothing                                  | Seam-boundary blending post-displacement          |

---

## §16 PhD Knowledge Acquisition Pipeline

### 16.1 Motivation: Why Standard RAG Is Insufficient

Standard Retrieval-Augmented Generation retrieves similar past answers and injects them into context. For deeply technical research (geometry algorithms, UV theory, C++ compiler internals), this misses:

1. **Cross-domain gaps** — the answer lives in Field B (e.g. topology) but the question is in Field A (e.g. UV mapping).
2. **Falsification debt** — a retrieved answer may have been contradicted by newer work.
3. **Synthesis gap** — no agent formalises _why_ two contradictory findings can coexist.

The PhD pipeline addresses these with a Dialectical Triad (Librarian → Skeptic → Synthesizer) run inside a RAML (Retrieval-Augmented Machine Learning) loop.

### 16.2 Board of Directors Architecture

Each agent in the Board plays a permanent epistemic role — not a task role:

| Agent           | Epistemic Role                                             | Model            | Key Tool                       |
| --------------- | ---------------------------------------------------------- | ---------------- | ------------------------------ |
| **Librarian**   | First-principles retrieval + Knowledge Gap identification  | Gemini 2.5 Flash | `tavily_search`, `memory_read` |
| **Skeptic**     | Popperian falsification + adversarial edge-case generation | Gemini 2.5 Flash | `run_command`, `file_read`     |
| **Synthesizer** | Cross-domain isomorphism + Unified Theory production       | Gemini 2.5 Pro   | `memory_write`                 |
| **Engineer**    | Code execution + regression guard                          | Gemini 2.5 Pro   | `run_command` (via builder)    |

The existing 4-agent fleet (researcher/builder/verifier/scribe) remains the **execution layer**. The Board of Directors is the **research layer** — it feeds _theories_ into the execution layer rather than tasks.

### 16.3 RAML Pattern

RAML = Retrieval-Augmented Machine Learning. Key invariant:

> **Every failure trace is a first-class knowledge asset.**

Implementation (`agents/phd_pipeline.py`):

1. Before any research cycle, call `_retrieve_prior_failures(question)` — returns LanceDB rows tagged with failure context.
2. Inject these rows into the Librarian's prompt as "RAML CONTEXT".
3. After every Synthesizer cycle, call `memory_write` with category `PhD_Synthesis`.
4. The next cycle begins by querying the _updated_ LanceDB — learning compounds.

This is the "perpetual learning" property described in the papers: the knowledge base grows monotonically, so each research cycle is strictly better informed than the last.

### 16.4 Dialectical Loop Flow

```
question
   │
   ▼
[RAML] query_similar(failure traces)     ← LanceDB read
   │
   ▼
[Librarian] First Principles Report      ← memory_read + tavily_search
   │  domain axioms, Knowledge Gap, Hypothesis
   ▼
[Skeptic] Falsification Report           ← file_read + run_command
   │  counter-examples, assumption audit, verdict (ROBUST|FRAGILE|BROKEN)
   ▼
[Synthesizer] Unified Theory             ← memory_write
   │  isomorphism, code consequence, falsifiable prediction
   ▼
[if ROBUST] ── exit ─────────────────────→ result dict
[if FRAGILE/BROKEN] ── next round ──────→ Librarian (with prior synthesis as context)
```

Maximum rounds: 2 (configurable via `max_rounds`). Early exit when Skeptic says ROBUST.

### 16.5 Tavily Search Integration

Tavily provides real-time ArXiv/GitHub/semantic scholar search without a browser headless overhead.

- Key: `TAVILY_API_KEY` in `.env` (added; key in `deepagents-quickstarts/.env`)
- Tool: `agents/tools.py::tavily_search` — wraps `TavilySearchResults` from `langchain_community`
- Protocol: Librarian calls `memory_read` first (≤6 hits). Only calls `tavily_search` if LanceDB misses.
- Results capped at 10 per call; content truncated to 600 chars per hit.

### 16.6 Isomorphism Discovery (Category Theory Layer)

The Synthesizer is explicitly prompted to find mathematical isomorphisms between domains. Examples already discovered in QIDIStudio work:

| Isomorphism                               | Domain A          | Domain B           | Code Consequence              |
| ----------------------------------------- | ----------------- | ------------------ | ----------------------------- |
| Euler characteristic ≅ topological genus  | Discrete Geometry | Algebraic Topology | `chi ≤ -4` → PRISMATIC branch |
| LSCM conformal energy ≅ Dirichlet energy  | UV Mapping        | Harmonic Analysis  | Identical minimisation target |
| Displacement depth ≅ normal map intensity | Mesh Geometry     | Rendering          | Scale-matched thresholds      |

### 16.7 Entry Point

```python
from agents.phd_pipeline import run_phd_research

result = run_phd_research(
    "How should the topology classifier distinguish high-genus PRISMATIC "
    "shapes from simple REVOLUTION shapes using Euler characteristic alone?",
    max_rounds=2,
    persist=True,
    thread_id="topo-chi-001",
)
print(result["synthesis"])
```

Returns: `{"question", "synthesis", "librarian", "skeptic", "rounds", "persisted"}`.

### 16.8 Files Added / Modified

| File                            | Role                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------- |
| `agents/phd_pipeline.py`        | Board of Directors dialectical loop, RAML, entry point                              |
| `agents/prompts/librarian.md`   | Librarian system prompt — first-principles retrieval                                |
| `agents/prompts/skeptic.md`     | Skeptic system prompt — Popperian falsification                                     |
| `agents/prompts/synthesizer.md` | Synthesizer system prompt — unified theory production                               |
| `agents/tools.py`               | Added `tavily_search`, `LIBRARIAN_TOOLS`, `SKEPTIC_TOOLS`, `SYNTHESIZER_TOOLS`      |
| `agents/agents.py`              | Added `make_librarian()`, `make_skeptic()`, `make_synthesizer()`, extended registry |
| `.env`                          | Added `TAVILY_API_KEY`                                                              |
| `memory/requirements.txt`       | Added `tavily-python`, `langchain-community`                                        |

---

## §17 OCP CAD Viewer Integration

### 17.1 Purpose

After the texture pipeline modifies parts, we need to **visualise the texture_modifier STLs** directly in VS Code without launching Blender. OCP CAD Viewer achieves this via a WebSocket + OpenCASCADE renderer embedded in the IDE.

### 17.2 Installation

Install the VS Code extension and Python package:

```powershell
# 1. VS Code Extension (install from Extensions marketplace):
#    Extension ID: twiss.ocp-vscode
#    Name:         OCP CAD Viewer

# 2. Python packages (in your active venv):
pip install build123d ocp_vscode

# Or via the QIDIStudio requirements:
.\memory_env\Scripts\python.exe -m pip install build123d ocp_vscode
```

`build123d` version ≥ 0.8.0 includes `import_stl()` for direct STL loading.

### 17.3 Displaying the 4 Texture-Modified Parts

```python
# scripts/view_texture_parts.py
from build123d import import_stl
from ocp_vscode import show, set_port

set_port(3939)

phone_case    = import_stl(r"C:\...\protection-poco-x6_texture_modifier.stl")
elvish_tpu    = import_stl(r"C:\...\elvish_tpu_inner_texture_modifier.stl")
vac_nozzle    = import_stl(r"C:\...\vacuum_nozzle_lower_texture_modifier.stl")
vac_crevice   = import_stl(r"C:\...\vacuum_crevice_nozzle_texture_modifier.stl")

show(
    phone_case, elvish_tpu, vac_nozzle, vac_crevice,
    names=["Poco X6", "Elvish TPU", "Vacuum Nozzle", "Crevice Tool"],
    colors=[(133,187,243), (89,204,115), (243,174,56), (217,89,89)],
    reset_camera=True,
)
```

Run with: `python scripts/view_texture_parts.py`

### 17.4 Part Inventory

| Part                  | STL Path                                                                 | Classifier | UV Method |
| --------------------- | ------------------------------------------------------------------------ | ---------- | --------- |
| Poco X6 phone case    | `3DPrinting/PhoneCase/STL/protection-poco-x6_texture_modifier.stl`       | PRISMATIC  | OBJECT    |
| Elvish TPU inner      | `3DPrinting/PhoneCase/STL/elvish_tpu_inner_texture_modifier.stl`         | FREEFORM   | LSCM      |
| Vacuum nozzle lower   | `3DPrinting/VacuumNozzle/STL/vacuum_nozzle_lower_texture_modifier.stl`   | REVOLUTION | LSCM      |
| Vacuum crevice nozzle | `3DPrinting/VacuumNozzle/STL/vacuum_crevice_nozzle_texture_modifier.stl` | PRISMATIC  | OBJECT    |

### 17.5 OCP Viewer Protocol

1. Open VS Code → `View` → `OCP CAD Viewer` (or `Ctrl+Shift+P → OCP CAD Viewer: Open`)
2. Run `view_texture_parts.py` — the viewer updates via WebSocket on port 3939.
3. Navigate parts with mouse: `Left drag` to rotate, `Scroll` to zoom, `Right drag` to pan.
4. Toggle individual parts in the left panel tree.

### 17.6 Dependency Notes

- `build123d` uses OpenCASCADE under the hood — requires 64-bit Python and Windows 10+.
- `ocp_vscode` connects to the VS Code extension; the extension must be running before `show()` is called.
- STL files are imported as tessellated meshes — OCC converts them to `TopoDS_Shell` via `BRep`.
- For parametric editing, use `build123d` constructors; for read-only display, `import_stl` is sufficient.

---

## §18 PhD-Level Cognitive Architecture — Applied to Every Pipeline

_Absorbed 2026-02-28. Sources: docs/AI PhD-Level Problem Solving Framework.md, docs/AI PhD-Level Problem Solving Framework 2.md, docs/AI's PhD-Level Thermal Dissipation Design.md, arXiv:2502.10867v1 (LLM Reasoning Tutorial), github.com/miltonian/principles (Principles Framework), AAAI-23 HAVEN paper, lean-lang.org. All links followed and read in full._

---

### 18.1 Why This Changes Everything

Standard "fix-the-bug" AI reasoning is **System 1 thinking** (Kahneman): fast, pattern-matching, analogical. It predicts the next likely token based on training data — constrained by an "intelligence upper bound" determined by the quality of examples it has seen.

PhD-level reasoning is **System 2 thinking**: deliberate, multi-step, self-correcting. It formulates problems as a Markov Decision Process where each intermediate reasoning step is evaluated by a Process Reward Model (PRM), not just the final answer.

**The critical distinction for this codebase:**

| Standard AI                               | PhD-Level AI                                                                                                                                                                                                                                  |
| :---------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "Here is code to fix TopoDS.Vertex error" | "The error persists because `cadquery_ocp 7.8` renamed ALL static casters to `_s` suffix. I will fix at the import boundary with a proxy class, not at 47 call sites."                                                                        |
| "Try LSCM for this mesh"                  | "The mesh has $\chi = V - E + F > 0$, indicating a sphere-like topology. LSCM requires a cut seam to produce a disk for unwrapping. OBJECT projection has no such constraint — it will produce lower distortion for $z_\text{ratio} < 0.25$." |
| "The texture looks patchy"                | "UV Jacobian $J$ has singular values $\sigma_1/\sigma_2 > 4$. This exceeds the acceptable stretch threshold. Root cause: REVOLUTION classifier triggered on $z_\text{ratio} \geq 1$ but $\chi > 0$ — the Euler tiebreaker was missed."        |

---

### 18.2 The Four Doctoral Phases — Mapped to QIDIStudio

Every significant pipeline change must cycle through all four phases in order:

#### Phase 1: First-Principles Deconstruction

Strip the problem to irreducible axioms. Discard "industry standard" shortcuts.

**Mandatory pre-work before ANY pipeline change:**

1. **Assumptions Audit** — List every assumption. For texture mapping: "We must use UV unwrapping" → Question: Is this a mathematical constraint or a legacy choice? Answer: UV unwrapping is one homeomorphism strategy; projection-based methods (OBJECT mode) are equally valid for convex meshes.
2. **Socratic Interrogation** — "Is this a mathematical constraint or an API limitation?" For OCP `_s` suffix: it's an API change, not a mathematical constraint → fix at the import boundary.
3. **Fundamental Truths** — Identify the axioms. For conformal UV: Axiom: A conformal map preserves angles. Corollary: LSCM minimizes angle distortion. Constraint: LSCM requires a topological disk (boundary-free surface requires a cut seam).

**QIDIStudio First Principles Manifest (confirmed truths, do NOT contradict without evidence):**

| Domain               | First Principle                                                                                                                                    |
| :------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------- |
| UV Mapping           | A conformal map preserves angles; the Laplace-Beltrami operator $\Delta f = \nabla \cdot \nabla f$ governs distortion                              |
| Mesh Topology        | $\chi = V - E + F$ determines valid unwrapping strategies; $\chi \leq 0$ = annular/toroidal (REVOLUTION)                                           |
| Texture Displacement | Displacement $d = A \cdot \sin(f \cdot UV + \phi)$ is a vector field on the surface; magnitude determined by sampling height map at UV coordinates |
| OCP/OpenCASCADE      | `TopoDS` static casters are API-version-dependent; fix at import boundary, not at each call site                                                   |
| Blender Pipeline     | Blender's `bpy` API requires an active mesh for UV ops; `bpy.ops.uv.unwrap()` operates on `EDIT_MODE` selection                                    |
| 3MF Format           | QIDIStudio validates `sparse_infill_pattern` on load; invalid values replaced silently                                                             |

#### Phase 2: Differentiable Hypothesis Generation (Tree of Thoughts)

Generate 3–5 competing hypotheses. For each, define **Falsification Criteria** — how you would prove it wrong.

**Template for every non-trivial bug or feature:**

```python
hypotheses = [
    {
        "id": "H1",
        "claim": "The texture is patchy because the UV seam is placed at a high-curvature edge",
        "falsification": "Run ai_debug_pipeline.py --render-heatmap; if Jacobian heatmap shows uniform stretch near seam but patches elsewhere, H1 is false",
        "probability": 0.35,
    },
    {
        "id": "H2",
        "claim": "Wrong MeshClass assigned — REVOLUTION chosen when FLAT_SHELL was correct",
        "falsification": "Check session_summary.json post_classify.mesh_class; if FLAT_SHELL, H2 is false",
        "probability": 0.45,
    },
    {
        "id": "H3",
        "claim": "Displacement depth too low — E_D < 0.1 threshold",
        "falsification": "Check session_summary.json post_displace.displacement_stats.max_delta; if > 0.3mm, H3 is false",
        "probability": 0.20,
    },
]
# ai_texture_critic.py systematically tests all hypotheses against debug snapshot data
```

**Rule**: Never commit a fix that addresses H-MAX-PROBABILITY without having falsified H2 and H3 first.

#### Phase 3: Dialectical Self-Correction (Pre-Mortem)

Before implementing, run the internal peer review:

- **Author**: "My solution is to add Euler characteristic as a REVOLUTION tiebreaker."
- **Reviewer**: "If $\chi \leq 0$ but the mesh is a twisted Möbius band (non-orientable), LSCM will produce garbage. Does the classifier handle non-orientable surfaces?"
- **Synthesizer**: "Add an orientability check (`mesh.is_watertight` proxy) alongside Euler characteristic."

**The Pre-Mortem Question**: _"If this pipeline is producing wrong results in six months, exactly which premise was wrong?"_

Apply this to the `_classify_mesh_topology()` function after every significant change.

#### Phase 4: Synthesis & Meta-Learning

After solving, extract the Generalized Pattern. Add it to the KB. Don't just fix _this_ bug — update the model of _why_ that class of bugs exists.

**Protocol**: After every fix, append to `docs/QIDISTUDIO_KNOWLEDGE.md` Session Learnings Log with:

- Root cause at the axiom level (not symptom level)
- Generalized pattern (what class of problems does this belong to?)
- Falsification criteria that confirmed the fix

---

### 18.3 System 1 vs System 2 Thinking — RL Reasoning Formulation

_Source: arXiv:2502.10867v1, Jun Wang, UCL. "A Tutorial on LLM Reasoning: Relevant Methods behind ChatGPT o1."_

The key insight from OpenAI o1's architecture: **reasoning is a Markov Decision Process**.

$$Q \rightarrow \{R_1, R_2, \ldots, R_n\} \rightarrow A$$

Where:

- $Q$ = the problem (e.g., "classify this mesh topology")
- $R_i$ = intermediate reasoning steps (e.g., "compute sharp_fraction", "compute z_ratio", "check Euler characteristic")
- $A$ = the action taken (e.g., `MeshClass.FLAT_SHELL`)

**The Process Reward Model (PRM)**: Each reasoning step $R_t$ is scored by:
$$v_t = v(R_t \mid Q, R_1, \ldots, R_{t-1})$$

**Applied to our texture pipeline:**

The `_classify_mesh_topology()` function IS a hand-crafted PRM. Each feature extraction step (`sharp_fraction`, `z_ratio`, `curvature_std`, `chi`) is a reasoning step with an intermediate reward. The `MeshClass` assignment is the final answer $A$.

**Practically, this means:**

- If `ai_texture_critic.py` reports wrong classification → the PRM assigned wrong intermediate rewards → one of the feature extraction steps is producing incorrect intermediate state
- Debug by checking each $R_t$ in the debug snapshot, not just the final $A$

**MCTS at inference** (from §4.3 of the paper): For complex mesh classification decisions, use Monte Carlo sampling across multiple projection attempts with different seam placements, evaluated by UV stretch metric. The one with minimum $\sigma_1/\sigma_2$ Jacobian singular value ratio wins.

---

### 18.4 The PSV Loop — Embedded in Agent Fleet

_Source: "AI PhD-Level Problem Solving Framework 2.md"_

**Propose → Solve → Verify** — the three mandatory stages. Our current agent fleet maps as:

| PSV Stage     | QIDIStudio Agent                                  | Current Gap                                              |
| :------------ | :------------------------------------------------ | :------------------------------------------------------- |
| **Propose**   | `director` (LangGraph supervisor decomposes task) | ✅ Working                                               |
| **Solve**     | `builder` (implements C++/Python changes)         | ✅ Working                                               |
| **Verify**    | `verifier` (checks output)                        | ⚠️ Weak — currently just runs tests, no PRM scoring      |
| **Backtrack** | (none)                                            | ❌ Missing — when verifier fails, no root-cause location |

**Adding Backtracking to the fleet:**

When `verifier` returns `FAIL`, the director should:

1. Ask verifier: "Which specific hypothesis failed?" (→ H1/H2/H3 from Phase 2)
2. Route back to `builder` with the specific falsified premise, not a generic "try again"
3. Scribe records the falsified premise + new hypothesis to LanceDB for future sessions

The Principles Framework (github.com/miltonian/principles) validation shows this approach achieves:

- **33% improvement** in success rates on compositional reasoning (TDAG benchmark)
- **28.3% increase** in task completion rates (ALFWorld benchmark)
- **27% performance boost** on interactive tasks (WebShop benchmark)

---

### 18.5 Cross-Domain Isomorphisms Discovered in This Codebase

_Source: "AI PhD-Level Problem Solving Framework 2.md", §IV Cross-Domain Isomorphism_

The hallmark of PhD-level work: recognizing that a problem in **Domain A** is mathematically identical to a solved problem in **Domain B**.

**Known mappings in QIDIStudio:**

| Problem Domain                                 | Isomorphic Domain                         | Borrowed Solution                                          | Status                                        |
| :--------------------------------------------- | :---------------------------------------- | :--------------------------------------------------------- | :-------------------------------------------- |
| UV texture stretch on POCO X6 Pro (flat shell) | Heat diffusion on thin plates             | Laplace-Beltrami operator for UV relaxation                | ✅ Absorbed §15.2                             |
| Mesh topology classification                   | Algebraic topology (Euler characteristic) | $\chi = V - E + F$ as genus indicator                      | ✅ Implemented in `_classify_mesh_topology()` |
| Conformal UV unwrapping on revolution surfaces | Riemann surface theory                    | LSCM = discrete harmonic map (minimizes $\|J - R\|^2$)     | ✅ Implemented in `apply_texture_bpy.py`      |
| OCP API version compatibility                  | Decorator/Proxy pattern (GoF)             | `_TopoDSCompat` proxy class — version-transparent dispatch | ✅ Implemented in `build123d` venv patches    |
| Agent task decomposition                       | Dynamic Programming (Bellman equation)    | Hierarchical value decomposition (HAVEN dual coordination) | ⏳ Partially — HAVEN not yet fully applied    |
| Texture quality scoring                        | Process Reward Models (arXiv:2502.10867)  | PRM scoring intermediate UV steps, not just final geometry | ⏳ Planned for `ai_texture_critic.py` v2      |
| Phone case thermal dissipation                 | Minimal surface geometry (Schoen Gyroid)  | Triply Periodic Minimal Surface = maximum $A/V$ ratio      | 📋 Planned — see §18.6                        |

**The Isomorphism Discovery Protocol** (run at the start of any non-trivial feature):

```python
def find_isomorphism(problem_description: str) -> dict:
    """
    1. Parameterize the problem mathematically (what are the variables, constraints, objective?)
    2. Search LanceDB for 'Mathematical Twins' via semantic similarity
    3. Check §15 (CMU 15-458 DDG), §16 (PhD Pipeline), §18 (this section) for known mappings
    4. If no match: ask researcher agent to search arXiv for analogous formulations
    """
    return {
        "domain_a": problem_description,
        "domain_b": "...",  # from LanceDB / researcher agent
        "mapping": "...",   # the mathematical translation
        "adaptation": "...", # how to adapt constants/parameters
    }
```

---

### 18.6 Thermal Dissipation Application — POCO X6 Pro Gyroid Backplate

_Source: docs/AI's PhD-Level Thermal Dissipation Design.md — Full 5-phase reasoning trace_

This is the most concrete example of PhD-level reasoning applied to this project's hardware context.

**The Problem (First Principles):**

- **Axiom 1** (Thermodynamics): Heat flux $q = -k\nabla T$. Larger surface area $A$ → more dissipation.
- **Axiom 2** (Geometry): A flat Euclidean backplate has minimal $A/V$ ratio. Any non-Euclidean topology improves this.
- **Axiom 3** (Fluid Dynamics): Nusselt number improves with turbulent airflow; complex geometry promotes turbulence.

**The Isomorphism:**

Thermal optimization of a constrained volume = **Minimal Surface** problem from structural engineering. The **Schoen Gyroid** satisfies $H = 0$ (zero mean curvature) at every point — it is a Triply Periodic Minimal Surface (TPMS).

**The Graded Lattice Solution:**

Standard Gyroid is isotropic. The Dimensity 8300 Ultra SoC is a localized heat source. Apply a **Gaussian Radial Basis Function** to lattice density:

$$\omega(d) = \omega_0 + \omega_\text{max} \cdot e^{-d^2 / \sigma^2}$$

where $d$ = distance from SoC center, $\sigma$ = spread parameter (~30mm for POCO X6 Pro form factor).

**Formal Verification (Agent Pipeline):**

```python
import numpy as np

def generate_graded_gyroid(x, y, z, soc_center=(35, 75, 4), sigma=30.0):
    """
    Graded Schoen Gyroid for POCO X6 Pro backplate.
    soc_center: mm coordinates of Dimensity 8300 Ultra SoC from bottom-left
    Isosurface at f=0 defines the TPMS shell.
    """
    dist = np.sqrt(
        (x - soc_center[0])**2 +
        (y - soc_center[1])**2
    )
    # Frequency increases near SoC: finer lattice = more surface area at heat source
    freq = 1.0 + 2.0 * np.exp(-dist**2 / sigma**2)  # omega in [1.0, 3.0]
    # Gyroid equation: sin(fx)cos(fy) + sin(fy)cos(fz) + sin(fz)cos(fx) = 0
    return (
        np.sin(freq * x) * np.cos(freq * y) +
        np.sin(freq * y) * np.cos(freq * z) +
        np.sin(freq * z) * np.cos(freq * x)
    )
```

**Verification Check (Falsification Criteria):**

- Reynolds number: Air gap = pitch / 2. If gap < 1.5mm, stagnant boundary layer forms. Minimum pitch = 3.6mm → $\text{Re} = \rho v L / \mu \approx 120$ (transitional, acceptable).
- Structural integrity: TPU minimum wall thickness = 1.2mm. At $\omega = 3.0$, period = $2\pi/3 \approx 2.1$mm → wall = 1.05mm. **Constraint violated** → cap $\omega_\text{max}$ at 2.5.

**Result**: Predicted 12% peak temperature reduction during AnTuTu stress tests vs flat TPU backplate.

**Implementation Path in QIDIStudio:**

1. Generate Gyroid STL via `scripts/generate_gyroid_backplate.py` (planned)
2. Load as base mesh in QIDIStudio
3. Apply wood-grain texture via Blender pipeline on the Gyroid surface for aesthetic
4. Print in graphene-infused TPU filament (`sparse_infill_pattern = "gyroid"` already native in libslic3r)

---

### 18.7 HAVEN Dual Coordination — Applied to Agent Fleet

_Source: AAAI-23, Xu et al. "HAVEN: Hierarchical Cooperative Multi-Agent Reinforcement Learning with Dual Coordination Mechanism"_

**HAVEN's core insight**: Concurrent optimization across multiple agent levels causes instability. The fix is **dual coordination** via specially designed reward functions at two levels:

1. **Inter-level coordination** (hierarchical): Director-level rewards must be consistent with agent-level rewards. In our fleet: `director` decomposition quality is rewarded only when `builder`/`verifier` succeed.
2. **Inter-agent coordination** (lateral): Agents at the same level must coordinate. In our fleet: `researcher` and `builder` run in parallel but must not produce contradictory assumptions.

**Applied to our LangGraph supervisor:**

```python
# Current: director → parallel fan-out → aggregate
# HAVEN upgrade: add dual coordination reward signals

def _director_reward(task, builder_result, verifier_result):
    """
    Inter-level: Director gets reward proportional to how well decomposition
    matched the actual subtask structure that succeeded.
    """
    if verifier_result.passed:
        return 1.0 * _decomposition_quality_score(task, builder_result)
    else:
        # Penalize poor decomposition — forces director to learn better task splitting
        return -0.5 * _falsified_premise_count(verifier_result)

def _builder_coordination_bonus(builder_output, researcher_output):
    """
    Inter-agent: builder gets bonus when its implementation is consistent
    with researcher's findings (no contradictory API assumptions).
    """
    return 0.2 if _outputs_consistent(builder_output, researcher_output) else 0.0
```

**Key result from AAAI-23:** HAVEN outperforms all MARL baselines on StarCraft II micromanagement tasks including 3s5z (3 Stalkers + 5 Zealots vs mirror). The dual coordination mechanism resolves the non-stationarity problem inherent in concurrent multi-agent optimization.

---

### 18.8 Lean 4 / Property-Based Testing — Formal Verification Protocol

_Source: lean-lang.org (AWS Cedar case study, Terence Tao's formalization work)_

**Lean 4** is an open-source proof assistant. AWS uses it to formally verify Cedar (authorization policy language). For our pipeline, we use the lighter-weight alternative: **property-based testing via `hypothesis`** (already in KB §15.12).

**Lean 4's relevance to QIDIStudio:**

The Lean 4 philosophy applied to Python code: instead of testing specific inputs, prove that properties hold for ALL inputs from a valid domain.

**Properties that must hold for `_classify_mesh_topology()`:**

```python
from hypothesis import given, strategies as st
import pytest

@given(
    sharp_fraction=st.floats(min_value=0.0, max_value=1.0),
    z_ratio=st.floats(min_value=0.0, max_value=10.0),
    curvature_std=st.floats(min_value=0.0, max_value=5000.0),
    chi=st.integers(min_value=-1000, max_value=1000),
)
def test_classify_never_raises(sharp_fraction, z_ratio, curvature_std, chi):
    """Property: classifier never crashes on any valid input combination."""
    sig = TopologySignature(sharp_fraction, z_ratio, curvature_std, chi)
    result = _classify_mesh_topology(sig)
    assert result in list(MeshClass)  # must return a valid class

@given(
    sharp_fraction=st.floats(min_value=0.35, max_value=1.0),  # PRISMATIC condition
    z_ratio=st.floats(min_value=0.0, max_value=2.0),
    curvature_std=st.floats(min_value=0.0, max_value=5000.0),
    chi=st.integers(),
)
def test_prismatic_always_object_projection(sharp_fraction, z_ratio, curvature_std, chi):
    """Property: high sharp_fraction ALWAYS maps to OBJECT projection,
    regardless of z_ratio or chi. Straight edges dominate."""
    sig = TopologySignature(sharp_fraction, z_ratio, curvature_std, chi)
    result = _classify_mesh_topology(sig)
    assert result == MeshClass.PRISMATIC
```

**The Lean 4 Formal Proof Philosophy** (applied to our code decisions):

> "We should not merely unit test — we should identify the mathematical theorem that our algorithm is meant to implement, then prove that the implementation is consistent with the theorem."

For conformal UV: the theorem is "LSCM minimizes $\int_M |\nabla u - R \nabla v|^2 dA$" where $R$ is a rotation. The implementation can be verified against this by checking that the energy functional decreases monotonically during the unwrap solve.

---

### 18.9 First Principles Mandate — Checklist Before Any Pipeline Change

This checklist MUST be completed before committing any change to `apply_texture_bpy.py`, `Plater.cpp`, or `agents/orchestrator.py`:

- [ ] **Axiom check**: What mathematical truth governs this code path?
- [ ] **Assumption audit**: List 3+ assumptions the current code makes. Are any unjustified?
- [ ] **Hypothesis tree**: Generate ≥3 competing explanations for the observed behavior. Assign probability estimates.
- [ ] **Falsification plan**: For each hypothesis, specify the exact observable that would falsify it. Run `ai_debug_pipeline.py --render-heatmap` to collect observables.
- [ ] **Cross-domain check**: Search LanceDB + §18.5 table for an isomorphic solved problem.
- [ ] **Pre-mortem**: "If this change causes a regression in 3 months, which assumption was wrong?"
- [ ] **Verify, not just test**: Does the fix satisfy a mathematical property (provable via `hypothesis` tests)?
- [ ] **Meta-learn**: Append root cause + generalized pattern to Session Learnings Log.

---

### 18.10 The Self-Improving Loop — Closing the Meta-Learning Cycle

_Source: §4.1 of arXiv:2502.10867 — STaR (Self-Taught Reasoner), plus §16 PhD Knowledge Acquisition Pipeline_

STaR's insight: a model can generate its own reasoning steps and use them to improve, without human annotation:

$$\{R_1, \ldots, R_n\} \sim \pi_\text{LLM}(\cdot \mid Q, A)$$

Then test: $A' \sim \pi_\text{LLM}(\cdot \mid Q, \{R\})$. If $A' \approx A$, the reasoning steps $\{R\}$ are valid training data.

**Applied to QIDIStudio agent fleet:**

```
Session Start:
  memory/inject.py → loads prior learnings into context (retrieval)

During Session:
  agents/orchestrator.py → generates reasoning traces (Q → {R} → A)
  ai_texture_critic.py → scores each pipeline run (verifier / PRM)

Session End:
  memory/extract.py → extracts generalized patterns (STaR self-training)
  LanceDB ← new_learnings (persistent world model update)

Next Session:
  The injected context includes the previous session's validated reasoning steps
  → The agent does NOT need to re-derive axioms it already proved
  → Performance improves monotonically across sessions
```

**The GRPO connection**: The agent fleet is effectively implementing Group Relative Policy Optimization at the session level:

- Each session = one "group" of sampled outputs
- `verifier` feedback = process reward signal
- `memory/extract.py` = policy update step

This is why session memory extraction is **mandatory** after every significant session — it is the training step that prevents the agent from repeatedly making the same class of error.

---

### 18.11 Sources Absorbed

| Source                                                                                                  | Key Contribution                                                                              | Applied Where       |
| :------------------------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------- | :------------------ |
| [arXiv:2502.10867v1](https://arxiv.org/abs/2502.10867v1) — "A Tutorial on LLM Reasoning"                | System 1/2 thinking, MDP formulation of reasoning, PRM, STaR, GRPO                            | §18.3, §18.10       |
| [github.com/miltonian/principles](https://github.com/miltonian/principles) — Principles Framework       | First-principles agent decomposition, iterative refinement, TDAG & DRDA validation benchmarks | §18.2, §18.4        |
| [AAAI-23 HAVEN](https://ojs.aaai.org/index.php/AAAI/article/view/26386) — Hierarchical Cooperative MARL | Dual coordination (inter-level + inter-agent), reward function design for multi-agent systems | §18.7               |
| [lean-lang.org](https://lean-lang.org/) — Lean 4                                                        | Formal proof philosophy, AWS Cedar case study, property-based verification                    | §18.8               |
| docs/AI PhD-Level Problem Solving Framework.md                                                          | Doctoral Thinking Framework, Agentic Reasoning table, Optimization vs Invention               | §18.2               |
| docs/AI PhD-Level Problem Solving Framework 2.md                                                        | PSV Pipeline, Dialectical Self-Correction, Cross-Domain Isomorphism, TDAG/DRDA benchmarks     | §18.2, §18.4, §18.5 |
| docs/AI's PhD-Level Thermal Dissipation Design.md                                                       | 5-phase reasoning trace, Schoen Gyroid, Graded RBF lattice, Reynolds number verification      | §18.6               |

---

## §19 PhD-Level Computational Aesthetics — Beauty Scoring for Textures

_Absorbed 2026-02-28. Sources: docs/Symmetry and Beauty_ A PhD Perspective.md, docs/Beauty Score.md, docs/Measuring Aethetics.md, plus live research at Wikipedia/Processing*fluency_theory, Nature doi:10.1038/s41467-022-29330-w.*

### 19.1 Scientific Framework — Why Beauty Is Measurable

Beauty in texture mapping is not subjective at the engineering level. Three converging research pillars each converge on the same mathematical framework:

| Pillar                                                                 | Key Result                                                                                                                                                                                      | Codebase Application                                                             |
| :--------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------- |
| **Kolmogorov Complexity** (Johnston et al. 2022, Nature Comms 13:1858) | $A \propto 1/K(S)$ — aesthetic value ∝ inverse complexity. Symmetry compresses information, reducing K.                                                                                         | Choose skins whose patterns have low Kolmogorov complexity (high symmetry score) |
| **Perceptual Fluency** (Reber, Schwarz & Winkielman 2004)              | Brain rewards ease of visual processing via hedonic signal. Symmetric stimuli → faster processing → perceived as beautiful. Inverted-U (Wundt Curve): too simple = boring, too complex = chaos. | Beauty score B clips at high symmetry _only if_ entropy is also high             |
| **Neuroaesthetics B(s,σ) model** (Leder et al. 2004)                   | $B(s, \sigma) = \omega_1 \cdot \text{Fluency}(s) + \omega_2 \cdot \text{Novelty}(\sigma)$ where $s$ = symmetry, $\sigma$ = spectral entropy                                                     | Implemented as `beauty_score_from_metrics()` in `scripts/ai_beauty_scorer.py`    |

### 19.2 The Two Core Metrics

**Fourier Symmetry Score** — measures bilateral phase coherence:

$$S = \frac{\sum|Re(F)|^2}{\sum|F|^2} \in [0,1]$$

A real-valued centrosymmetric image → $Im(F) \to 0$ everywhere → $S \to 1$. Perfect grid or bilateral pattern: $S \approx 0.9997$. Random noise: $S \approx 0.65$.

**Spectral Entropy** — measures information richness:

$$H_s = -\sum P(u,v) \cdot \log_2 P(u,v) \quad \text{where } P = \frac{|F|^2}{\sum|F|^2}$$

| Pattern Type                | $H_s$ (bits) | Interpretation                          |
| :-------------------------- | :----------- | :-------------------------------------- |
| Simple grid (2 frequencies) | ~2.06        | "Boring symmetry"                       |
| Random noise                | ~4.64        | Chaos — no structure                    |
| Gyroid / complex symmetric  | ~4.62        | **Golden Zone** — ordered but intricate |

### 19.3 The Golden Zone

**Target: $S > 0.90$ AND $H_s > 4.0$ simultaneously.**

This combination (Leder 2004, Measuring Aesthetics §III) gives:

- **High Fluency** → brain processes it as a single cohesive "chunk"
- **High Novelty** → unique visual information stimulates reward centres (PFC)

The Wundt Penalty prevents boring simple patterns from scoring BEAUTIFUL even if $S=1$:
$$B_{\text{final}} = \omega_1 S + \omega_2 \frac{H_s}{H_{\text{random}}} - 0.12 \cdot \max(0,\ 2.0 - H_s)$$

### 19.4 Dominant Spatial Frequency → Optimal Tile Size

The skin PNG's dominant radial FFT frequency $r_{\text{peak}}$ (cycles/image_dim) directly encodes the ideal tile_size:

$$\text{tile\_hint} = r_{\text{peak}} \times \text{FEATURE\_TARGET\_MM} \quad (\text{FEATURE\_TARGET\_MM} = 3.0)$$

This targets a 3mm feature pitch (clearly visible at 0.4mm nozzle; not large enough to reveal the repeat pattern at normal viewing distance).

**Blending in `_compute_optimal_params()`** (after golden-ratio geometric estimate):
$$\text{tile\_final} = \text{snap\_to\_integer\_repeat}(0.55 \cdot \text{tile\_geo} + 0.45 \cdot \text{tile\_hint},\ L_{\text{dominant}})$$

55% geometric (structure-driven) vs 45% skin-driven preserves seam-invisibility while resonating with the pattern's natural scale.

### 19.5 Implementation Files

| File                                                                 | Role                                                                                                                                                                                                      |
| :------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/ai_beauty_scorer.py`                                        | Standalone module: `fft_symmetry_score()`, `spectral_entropy()`, `dominant_radial_frequency()`, `beauty_score_from_metrics()`, `analyse_skin_file()`. Uses numpy + PIL (falls back to stdlib PNG reader). |
| `scripts/ai_texture_critic.py`                                       | Calls `_analyse_beauty()` on the skin path from session_summary.json. Reports S, H_s, B, verdict. Issues WARNING if B < 0.5, INFO for GOLDEN ZONE.                                                        |
| `resources/scripts/apply_texture_bpy.py` `_compute_optimal_params()` | Blender-native (numpy only, no PIL). Loads skin via `bpy.data.images.load()`, computes FFT, finds r_peak, blends with geometric tile. Logs symmetry + entropy as quality signals.                         |

### 19.6 Beauty Score Thresholds

| Score     | Verdict        | Action                                                          |
| :-------- | :------------- | :-------------------------------------------------------------- |
| ≥ 0.80    | **BEAUTIFUL**  | Accept — Golden Zone or near-Golden Zone                        |
| 0.65–0.80 | **GOOD**       | Accept — minor room for skin upgrade                            |
| 0.50–0.65 | **ACCEPTABLE** | INFO — consider richer skin                                     |
| < 0.50    | **POOR**       | WARNING — skin lacks structure; will produce muddy displacement |

### 19.7 Cross-Domain Isomorphism

| Texture beauty                            | Analogous domain                                      | Insight                                                 |
| :---------------------------------------- | :---------------------------------------------------- | :------------------------------------------------------ |
| Symmetry Score $S$ = Real energy fraction | Signal-to-noise ratio in comms theory                 | Phase coherence = signal quality                        |
| Spectral Entropy $H_s$                    | Shannon channel capacity                              | Complex symmetric texture = high-capacity channel       |
| Wundt penalty for $H_s < 2.0$             | Regularisation in ML (penalise overfit to simplicity) | Prevents degenerate "always-symmetric" solutions        |
| $r_{\text{peak}}$ → tile_size             | Nyquist sampling theorem                              | Sample at 2× the dominant frequency to resolve features |

### 19.8 Sources Absorbed

| Source                                          | Key Contribution                                                                                             | Applied Where                                           |
| :---------------------------------------------- | :----------------------------------------------------------------------------------------------------------- | :------------------------------------------------------ |
| docs/Symmetry and Beauty\_ A PhD Perspective.md | Group theory invariance, Kolmogorov complexity, Perceptual Fluency, evolutionary Good Genes, Wundt curve     | §19.1–§19.2                                             |
| docs/Beauty Score.md                            | Fourier Hermitian symmetry proof, Python symmetry score implementation, Symmetric=0.9997 / Asymmetric=0.6528 | §19.2, `ai_beauty_scorer.py` `fft_symmetry_score()`     |
| docs/Measuring Aethetics.md                     | Spectral Entropy implementation, Simple=2.06 / Random=4.64 / Gyroid=4.62, Golden Zone definition             | §19.2–§19.3, `ai_beauty_scorer.py` `spectral_entropy()` |
| Wikipedia: Processing Fluency Theory            | Inverted-U Wundt curve, hedonic marking, fluency-as-information account                                      | §19.1 Wundt penalty derivation                          |
| Nature Comms 13:1858 (Johnston 2022)            | Symmetry as simplicity bias in evolution — directly supports $A \propto 1/K(S)$                              | §19.1 theoretical basis                                 |

---

## §20 3D Viewer Rendering Architecture — PhD-Level Analysis

**Absorbed:** 2025 (this session)  
**Source documents:** `docs/PhD-Level 3D Model Representation.md`, `docs/3D Projection Jacobian Accuracy.md`, `docs/Inverse Rendering_ Jacobian and Loss.md`, `docs/PhD Thesis_ Differentiable Rendering Pipeline.md`, `docs/PhD Whitepaper_ Inverse Graphics Framework.md`  
**Full report:** `docs/3D_Viewer_Code_Review_Report.md`

### §20.1 Current Rendering Stack

| Layer            | Implementation                                 | File                |
| ---------------- | ---------------------------------------------- | ------------------- |
| Shading          | **Gouraud** (per-vertex Blinn-Phong)           | `gouraud.vs`        |
| BRDF             | Non-physical Blinn-Phong, shininess=20         | `gouraud.vs`        |
| Lighting         | 3 hardcoded **eye-space** directional lights   | `gouraud.vs`        |
| Anti-aliasing    | FXAA post-process only (BT.601 luma)           | `fxaa.fs`           |
| Gamma / color    | **None** — linear pipeline, no sRGB encode     | All FS              |
| Environment      | Dead code guard (`ENABLE_ENVIRONMENT_MAP`)     | `gouraud.fs`        |
| Shadows          | None                                           | —                   |
| SSAO             | None — ambient = flat 0.3 constant             | `gouraud.vs`        |
| MSAA (viewport)  | Off by default (`m_multisample_allowed=false`) | `GLCanvas3D.cpp`    |
| MSAA (offscreen) | Full X2/X4/X8/X16 support — thumbnails only    | `OpenGLManager.cpp` |
| Normal matrix    | CPU per draw call, Matrix3d inverse+transpose  | `GLCanvas3D.cpp`    |
| Uniform cache    | Linear search `std::vector<pair<string,int>>`  | `GLShader.cpp`      |
| Tessellation     | Declared in enum, **never instantiated**       | `GLShader.hpp`      |

### §20.2 Critical Deficiencies vs. Rendering Equation

The Rendering Equation requires integrating $f_r(\omega_i, \omega_o) \cdot L_i \cdot (\omega_i \cdot \hat{n})\, d\omega_i$ at every surface point. Current violations:

1. **Gouraud shading** — integrates at vertices, interpolates the _result_, not the normal. SSIM ≈ 0.62 on curved surfaces vs. target 0.98.
2. **Eye-space lights** — lights rotate with camera, destroying shape-from-shading depth cues.
3. **No gamma correction** — output violates sRGB display contract, midtones appear 28% too dark.
4. **No PBR/GGX** — Blinn-Phong violates White Furnace Test (energy not conserved); `INTENSITY_CORRECTION=0.6` is a non-physical patch.
5. **IBL dead code** — ambient is uncorrelated with environment; no indirect light contribution.

### §20.3 Projective Jacobian Connection

From `docs/3D Projection Jacobian Accuracy.md`, the 2×3 projection Jacobian:

$$J_G = \begin{bmatrix} f/z & 0 & -fx/z^2 \\ 0 & f/z & -fy/z^2 \end{bmatrix}$$

The Camera.cpp projection matrix is mathematically correct (standard GL frustum/ortho). The Jacobian eigenvalues are therefore accurate. However, the _shading output_ does not faithfully represent what a correct renderer would produce at those projected coordinates. The viewer shows correct geometry placement but incorrect surface appearance.

### §20.4 Remediation Priority (P0 = immediate)

| P   | Fix                 | 2-line summary                                                                         |
| --- | ------------------- | -------------------------------------------------------------------------------------- |
| P0  | World-space lights  | Pass eye-space transform of world dir as uniform; remove hardcoded eye-space constants |
| P0  | Phong shading       | Move `NdotL` / specular computation from VS to FS; pass normal as varying              |
| P0  | Gamma correction    | Add `pow(rgb, 1/2.2)` at end of all fragment shaders                                   |
| P1  | BT.709 luma in FXAA | `vec3(0.2126, 0.7152, 0.0722)`                                                         |
| P1  | O(1) uniform cache  | Replace `std::vector` with `std::unordered_map` in `GLShader.cpp`                      |
| P2  | Activate IBL        | Pass `ENABLE_ENVIRONMENT_MAP` define in `GLShadersManager.cpp` + provide env texture   |
| P2  | GGX BRDF            | ~60 lines new GLSL: D(h), F(θ), G(l,v) Cook-Torrance                                   |
| P2  | SSAO                | 16-tap hemisphere depth sample in new post-process pass                                |
| P3  | Shadow map          | Depth pre-pass from primary light + PCF sampling in FS                                 |

### §20.5 Source Document Index for §20

| Document                                                | Key Content                                                   | Applied To                  |
| ------------------------------------------------------- | ------------------------------------------------------------- | --------------------------- |
| `docs/PhD-Level 3D Model Representation.md`             | Rendering Equation, Microfacet BRDF, SSIM target > 0.95       | All critical deficiencies   |
| `docs/3D Projection Jacobian Accuracy.md`               | 2×3 Jacobian derivation, metric preservation, pixel footprint | Camera.cpp assessment, AE-2 |
| `docs/Inverse Rendering_ Jacobian and Loss.md`          | Material Jacobian, chain rule, specular manifold sampling     | C-2 PBR remediation         |
| `docs/PhD Thesis_ Differentiable Rendering Pipeline.md` | Structural Loss $\mathcal{L}_{total}$, Sobel structural loss  | AE-3 verification mode      |
| `docs/PhD Whitepaper_ Inverse Graphics Framework.md`    | SSIM > 0.98 target, White Furnace Test, full pipeline design  | Roadmap scoring             |

---

## Appendix A: Windows Registration (Post-Build)

After building, register with Windows (no installer needed):

```powershell
# Run: powershell -ExecutionPolicy Bypass -File _register_qidi.ps1
# File: C:\Users\User\Downloads\_register_qidi.ps1

$exe = 'C:\QIDISrc\QIDIStudio\install_dir\qidi-studio.exe'
$dir = 'C:\QIDISrc\QIDIStudio\install_dir'

# Start Menu shortcut
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\QIDIStudio.lnk")
$Shortcut.TargetPath = $exe
$Shortcut.WorkingDirectory = $dir
$Shortcut.Save()

# App Paths registry
$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\qidi-studio.exe'
New-Item -Path $regPath -Force | Out-Null
Set-ItemProperty -Path $regPath -Name '(default)' -Value $exe
Set-ItemProperty -Path $regPath -Name 'Path' -Value $dir

# Add/Remove Programs
$uninstPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\QIDIStudio'
New-Item -Path $uninstPath -Force | Out-Null
Set-ItemProperty -Path $uninstPath -Name 'DisplayName'    -Value 'QIDI Studio 02.04.01.11'
Set-ItemProperty -Path $uninstPath -Name 'DisplayVersion' -Value '02.04.01.11'
Set-ItemProperty -Path $uninstPath -Name 'Publisher'      -Value 'QIDI Technology'
Set-ItemProperty -Path $uninstPath -Name 'InstallLocation'-Value $dir
Set-ItemProperty -Path $uninstPath -Name 'DisplayIcon'    -Value "$exe,0"
```

## Appendix B: Qidi Q2 Printer Network Config

| Property         | Value                                                           |
| ---------------- | --------------------------------------------------------------- |
| IP               | `192.168.0.116` (static DHCP)                                   |
| Moonraker API    | `http://192.168.0.116:7125/`                                    |
| Web UI (Fluidd)  | `http://192.168.0.116/`                                         |
| Upload endpoint  | `POST /server/files/upload` (multipart: `file` + `root=config`) |
| Firmware restart | `POST /printer/firmware_restart`                                |
| Nozzle           | 0.4mm hardened steel                                            |
| Bed size         | 270×270×256mm                                                   |
| Firmware         | Klipper, CoreXY                                                 |

## Appendix D: Dev Workflow — NTFS Junction (Single Source of Truth)

**Problem:** `resources_dir()` resolves at runtime to `install_dir\resources\` (`QIDIStudio.cpp:~L8000`: `path_to_binary.parent_path() / "resources"`). Without intervention, edits to workspace scripts are invisible to QIDIStudio until copied.

**Solution:** Replace `install_dir\resources\scripts\` with an NTFS directory junction pointing at `workspace\resources\scripts\`. The OS redirects transparently — Blender executes the workspace file directly. No Python involved in the redirect. VS Code debugger breakpoints fire on the workspace file.

**One-time setup (after every clean build):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev_setup.ps1
```

What it does:

1. Derives workspace root from `$PSScriptRoot` — no hardcoded workspace path
2. Checks `install_dir\resources\` exists (build must have run)
3. Removes the real `install_dir\resources\scripts\` directory
4. Creates NTFS junction: `install_dir\resources\scripts` → `workspace\resources\scripts`
5. Idempotent — safe to re-run; already-correct junction is a no-op

**Only hardcoded value:** `$InstallDir = "C:\QIDISrc\QIDIStudio\install_dir"` at top of `dev_setup.ps1`. Change once per machine if your build output is elsewhere.

**Standalone Blender invocation (no QIDIStudio needed):**

```powershell
.\scripts\run_texture_pipeline.ps1 -Model model.stl -Skin skin.png -Output out.stl
```

Blender discovery order (mirrors Plater.cpp `find_bpy_python()`):

1. `$env:QIDI_BLENDER_EXE` (explicit override)
2. Scan `%ProgramFiles%\Blender Foundation\` for newest `blender.exe`

**Debugpy attach workflow:**

```powershell
.\scripts\run_texture_pipeline.ps1 -Model model.stl -Skin skin.png -Output out.stl -Debug
# Then in VS Code: Run & Debug -> Python: Remote Attach -> localhost:5678
```

**Scope of junction:** All files under `resources\scripts\` are covered automatically — any new script added to the workspace folder is immediately live.

---

## Appendix C: `ConfigOptionMode` Enum (verbatim from Config.hpp)

```cpp
// src/libslic3r/Config.hpp:203-207
enum ConfigOptionMode {
    comSimple = 0,   // "simple"  — basic settings only
    comAdvanced,     // "advanced" — most settings
    comDevelop       // "develop"  — all settings including experimental
};
```

Each config option in `PrintConfig.cpp` is tagged with a mode threshold.
Options tagged `comDevelop` only appear when `user_mode = "develop"`.
This is what QIDI documentation calls "Expert Mode".

---

## §21 C++ Modernization Scorecard

_Absorbed: 2026-02-28. **Updated: 2026-02-28 (P1+P2 implemented, score 43→54/10).** Full report: docs/CPP_MODERNIZATION_SCORE.md_

### §21.1 Current Score — 54/100 (C) — previously 43/100 (D+)

| Dimension          | Score               | Status                             |
| ------------------ | ------------------- | ---------------------------------- |
| Language Standard  | ~~4~~/10 → **6/10** | ✅ C++20 set globally              |
| Memory & Ownership | 5/10                | unchanged                          |
| Type Safety        | ~~4~~/10 → **5/10** | ✅ `[[nodiscard]]` added           |
| Error Handling     | ~~4~~/10 → **5/10** | ✅ noexcept move ctors             |
| OpenGL/Rendering   | ~~4~~/10 → **5/10** | ✅ GLResource.hpp RAII             |
| Concurrency        | ~~6~~/10 → **7/10** | ✅ std::jthread in GCodeSender     |
| Build System       | ~~3~~/10 → **7/10** | ✅ CMakePresets.json + .clang-tidy |
| Performance        | 4/10                | P3 (Google Highway)                |
| Code Quality       | ~~5~~/10 → **6/10** | ✅ #pragma once pilot              |
| Testing            | 4/10                | P3 (fuzzing)                       |
| **TOTAL**          | **54/100**          | **+11 points from P1+P2**          |

### §21.2 Technology Stack Recommendation (2026)

| Concern                   | Current              | Target                             | Effort      |
| ------------------------- | -------------------- | ---------------------------------- | ----------- |
| C++ standard              | C++17 patchwork      | **C++20 globally**                 | trivial     |
| Managed threads           | `boost::thread`      | `std::jthread` + `stop_token`      | moderate    |
| SIMD geometry             | None                 | **Google Highway**                 | significant |
| GL object safety          | Raw `GLuint`         | **RAII wrappers** (50-line header) | low         |
| GL API style              | Bind-to-modify       | **DSA (glNamed\*)**                | moderate    |
| Error handling (new code) | bool/exception mix   | `std::expected<T,E>` (C++23)       | low         |
| Async subprocess          | Blocking `wxExecute` | C++20 coroutines                   | moderate    |
| Build config              | Ad-hoc cache         | `CMakePresets.json`                | trivial     |
| Static analysis           | None                 | clang-tidy in CI                   | low         |
| Parser safety             | No fuzzing           | libFuzzer on STL/3MF/GCode         | low         |

### §21.3 Priority 1 Actions (ALL IMPLEMENTED ✅)

1. ✅ Add to root `CMakeLists.txt` after `project()`: `set(CMAKE_CXX_STANDARD 20)` + `set(CMAKE_CXX_STANDARD_REQUIRED ON)` + `set(CMAKE_CXX_EXTENSIONS OFF)`
2. ✅ Created `CMakePresets.json` with 5 presets: `base`, `msvc-release`, `msvc-relwithdebinfo`, `msvc-asan`, `msvc-tests`.
3. ✅ Added `.clang-tidy` with `modernize-use-override`, `bugprone-use-after-move`, `performance-move-const-arg`.
4. ✅ Marked move constructors `noexcept` on `TriangleMesh` (Rule-of-Five with explicit default).
5. ✅ Replaced `boost::thread` in `GCodeSender.hpp/cpp` with `std::jthread`.

### §21.3b Priority 2 Actions (PARTIALLY IMPLEMENTED)

1. ✅ `src/slic3r/GUI/GLResource.hpp` — RAII wrappers for `GlBuffer`, `GlVao`, `GlTexture`, `GlFramebuffer`, `GlRenderbuffer`
2. ✅ `[[nodiscard]]` added to: `TriangleMesh::from_stl`, `ReadSTLFile`, `write_ascii/binary`, `volume()`; `Format/STL.hpp` all 4 functions; `Format/AMF.hpp::load_amf`
3. ✅ `Format/STL.hpp` + `Format/AMF.hpp` converted to `#pragma once`; `scripts/migrate_pragma_once.py` created for bulk migration
4. ⚠️ `Config.hpp` `std::unordered_map` deferred — sorted iteration order dependency (cbegin/cend API exposed)

### §21.3c Priority 3 Actions (PARTIAL — 2026-02-28)

1. ✅ `#pragma once` expanded to 11 more key headers: `Point.hpp`, `BoundingBox.hpp`, `ExPolygon.hpp`, `Polygon.hpp`, `Polyline.hpp`, `Line.hpp`, `Layer.hpp`, `GCode.hpp`, `Surface.hpp`, `GCodeWriter.hpp`, `Print.hpp` — Code Quality 6→7/10
2. ✅ `[[nodiscard]]` on all `std::string`-returning methods in `GCodeWriter.hpp` (25 methods), `GCode.hpp` (10 methods), `Print.hpp` (4 methods) — Type Safety 5→6/10
3. ✅ `src/libslic3r/Result.hpp` created — `std::expected<T, std::string>` + `VoidResult` + `Err()/Ok()` factory helpers
4. ⏳ Google Highway SIMD for BVH geometry — future session
5. ⏳ Adopt `Result<T>` in `load_stl_safe()`/`load_amf_safe()` wrapper functions — future session

### §21.4 OpenGL RAII Canonical Pattern

Single 50-line header `src/slic3r/GUI/GLResource.hpp` using `template <auto Creator, auto Deleter>` wraps the Rule-of-Five for any GL object. Provides `GlBuffer`, `GlVao`, `GlTexture` types that auto-delete on destruction and are move-only with `std::exchange(o.id, 0)` idiom.

### §21.5 DO NOT Adopt (Cost > Benefit in 2026)

- C++20 Modules: MSVC support incomplete; 500k LOC migration risk
- C++26 Contracts (P2900): zero compiler support as of Feb 2026
- `std::simd` / `<simd>` header: not shipped in any production STL yet
- vcpkg full migration: existing deps/ works; high migration risk

### §21.6 Sources

cppreference.com (Feb 2026), C++ Core Guidelines, CppCon 2024 (Sean Parent, Phil Nash, Erez Strauss), Daniel Lemire Oct 2025, NVIDIA/stdexec, C++Now 2024 (Fedor G. Pikus), WG21 Feb 2025 Hagenberg trip report.

---

## 22. Nexus Workshop — Product Sites & Infrastructure

_Last updated: 2026-03-03._

Three product site domains bundled as **Nexus Workshop** (planned VS Code extension pack). All sites are static HTML deployed to Firebase Hosting with custom domains via Cloudflare DNS.

### 22.1 Firebase Hosting

| Firebase Site ID       | Default URL                           | Local folder             | Custom domain               |
| ---------------------- | ------------------------------------- | ------------------------ | --------------------------- |
| `nexuicer`             | https://nexuicer.web.app              | `sites/nexusslicer/`     | `nexusslicer.com`           |
| `nexuicer-desktop`     | https://nexuicer-desktop.web.app      | `sites/nexusslicer-desktop/` | `desktop.nexusslicer.com` |
| `nexusmill-app`        | https://nexusmill-app.web.app         | `sites/nexusmill/`       | `nexusmill.com`             |
| `nexusgauge-app`       | https://nexusgauge-app.web.app        | `sites/nexusgauge/`      | `nexusgauge.com`            |

**Key facts:**
- **Firebase project ID:** `nexuicer` — Firebase auto-truncated "NexusSlicer" on project creation; this is NOT a typo
- **Firebase project number:** `457376060296`
- **Firebase account:** `damienfosborn@gmail.com`
- **gcloud project** (separate, GCS): `crafty-hook-483415-b3`
- Site IDs for mill/gauge use `-app` suffix because Firebase requires site IDs prefixed with the project ID and these names were taken without suffix

**Deploy command (preferred — CLI, not REST API):**
```powershell
cd sites
firebase deploy --only hosting
```

REST API deploy (`sites/deploy_all.py`) hangs on the `populateFiles` endpoint — always use the CLI.

**Key config files:**
- `sites/.firebaserc` — project mapping + hosting targets
- `sites/firebase.json` — 4 hosting targets, cache headers, SPA rewrites
- `sites/FIREBASE_SETTINGS.md` — full reference (project IDs, site IDs, DNS table, deploy commands)

### 22.2 Cloudflare DNS

**Required CNAME records (7 total):**

| Zone             | Record name                   | CNAME target                    | Proxied |
| ---------------- | ----------------------------- | ------------------------------- | ------- |
| nexusslicer.com  | `nexusslicer.com`             | `nexuicer.web.app`              | No      |
| nexusslicer.com  | `www.nexusslicer.com`         | `nexuicer.web.app`              | No      |
| nexusslicer.com  | `desktop.nexusslicer.com`     | `nexuicer-desktop.web.app`      | No      |
| nexusmill.com    | `nexusmill.com`               | `nexusmill-app.web.app`         | No      |
| nexusmill.com    | `www.nexusmill.com`           | `nexusmill-app.web.app`         | No      |
| nexusgauge.com   | `nexusgauge.com`              | `nexusgauge-app.web.app`        | No      |
| nexusgauge.com   | `www.nexusgauge.com`          | `nexusgauge-app.web.app`        | No      |

**`proxied: False` is required** — Firebase must provision its own SSL certificates. Cloudflare proxying (orange cloud) prevents Firebase from seeing the direct CNAME and blocks SSL issuance.

**Automation script:** `sites/cf_dns.py`
- Reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_EMAIL` from `.env`
- Calls `GET /user/tokens/verify` to confirm token is active
- Tries `GET /zones?per_page=50` then per-name fallback for each domain
- Creates or updates each CNAME with `proxied: False`

**CRITICAL PREREQUISITE:** Domains must be **added to the Cloudflare account** (Dashboard → Add a site → enter domain → select plan → update nameservers at registrar) BEFORE running `cf_dns.py`. The error signature for missing zones: `errors=[], result=[]` (token active, no permission error — zones simply don't exist in the account yet).

**Credentials location:** `.env` file in repo root (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_EMAIL`).

### 22.3 SSL Certificate Provisioning

After adding domains to Cloudflare and pointing nameservers, Firebase needs time to provision SSL certs. While awaiting:
1. Cloudflare records must be DNS-only (grey cloud, `proxied: False`)
2. Firebase Hosting → Custom Domains → domain shows "Pending" until cert is issued
3. Once Firebase SSL is active, can optionally re-enable Cloudflare proxying for DDoS protection, but NOT required

### 22.4 Site Design

| Site            | Theme color | Type    | Status |
| --------------- | ----------- | ------- | ------ |
| NexusSlicer     | Dark purple | Full    | Live   |
| NexusSlicer Desktop | Blue    | Full    | Live   |
| NexusMill       | Amber       | Teaser  | Live   |
| NexusGauge      | Teal        | Teaser  | Live   |
