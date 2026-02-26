# QIDIStudio — Complete Engineering Knowledge Base

_Maintained by: GitHub Copilot | Last updated: 2026-02-25 (Add Skin feature + triplanar projection + subdivide_to_size)_

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

| URL | Purpose |
|-----|---------|
| <https://github.com/QIDITECH/QIDIStudio> | QIDI's official public source repo |
| <https://github.com/phantom-man/QIDIStudio> | **Our fork — primary working repo** |
| <https://github.com/SoftFever/OrcaSlicer> | OrcaSlicer upstream (most relevant reference for shared code) |
| <https://github.com/bambulab/BambuStudio> | Bambu Studio (OrcaSlicer's parent) |
| <https://github.com/prusa3d/PrusaSlicer> | Ultimate upstream for libslic3r |

### Build & Dependencies

| URL | Purpose |
|-----|---------|
| <https://github.com/QIDITECH/QIDIStudio/blob/main/doc/How_to_build.md> | Official build guide (Windows/Mac/Linux) |
| <https://cmake.org/download/> | CMake — use **3.29.x**, NOT 4.x (see build gotchas) |
| <https://strawberryperl.com/> | Strawberry Perl — required for OpenSSL build step |
| <https://github.com/nicowillis/pkg-config-lite> | pkg-config-lite for Windows |

### OrcaSlicer Configuration Reference (applies to QIDIStudio)

| URL | Purpose |
|-----|---------|
| <https://github.com/SoftFever/OrcaSlicer/wiki> | OrcaSlicer wiki — most settings docs apply to QIDIStudio |
| <https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/PrintConfig.cpp> | **Config key definitions + enums** — authoritative source for `sparse_infill_pattern` values, etc. |
| <https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/Config.hpp> | `ConfigOptionMode` enum definition |

### 3MF Format

| URL | Purpose |
|-----|---------|
| <https://3mf.io/specification/> | Official 3MF consortium specification |
| <https://github.com/3MFConsortium/spec_core> | 3MF core spec source |

### Community & Support

| URL | Purpose |
|-----|---------|
| <https://www.reddit.com/r/QIDI/> | QIDI user community — known issues, firmware gotchas |
| <https://github.com/QIDITECH/QIDIStudio/issues> | Official bug tracker |
| <https://github.com/QIDITECH/QIDIStudio/discussions> | Community Q&A |

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

| Tool | Version | Install | Notes |
|------|---------|---------|-------|
| CMake | **3.29.8** | <https://cmake.org/download/> | Install to `C:\CMake329\`. Do NOT use CMake 4.x — policy break |
| Visual Studio | 2022 Community | winget / manual | C++ workload required |
| Strawberry Perl | 5.42+ | <https://strawberryperl.com/> | Required for OpenSSL configure step |
| pkg-config-lite | 0.28 | `winget install bloodrock.pkg-config-lite` | Required — libav deps use .pc files |
| Ninja | 1.13+ | optional | Not needed if using VS generator |

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

| Value | Effect |
|-------|--------|
| `1` | Production: `iot_environment` defaults to `"3"`, `get_hms_host()` returns production URL, requires `QIDI/QIDINetwork.cpp` (NOT in public repo → build fails) |
| `0` | Dev/internal: `iot_environment` defaults to `"2"` (PRE/staging). No networking module needed. `get_hms_host()` still gated by `#if !QDT_RELEASE_TO_PUBLIC` |

**Rule: Always build with `QDT_RELEASE_TO_PUBLIC=0`** — the private networking module (`QIDI/QIDINetwork.cpp`) is not in the public source ZIP.

**Workaround for production host:** Change the `#else` branch default in `AppConfig.cpp` from `"2"` to `"3"` (already done in our fork).

### Other Notable Flags

- `SUPPORT_DARK_MODE` — defined in `AppConfig.hpp`, enables dark mode support
- `_MSW_DARK_MODE` — commented out in `AppConfig.hpp`, Windows-specific dark mode path

---

## 6. Mode System

### Overview

QIDIStudio has 3 UI complexity modes that control which settings are visible:

| Enum value | String | Config key value | What it shows |
|-----------|--------|-----------------|---------------|
| `comSimple = 0` | `"simple"` | Basic settings only |
| `comAdvanced = 1` | `"advanced"` | Most settings |
| `comDevelop = 2` | `"develop"` | All settings including debug/experimental |

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

| Key | Values | Notes |
|-----|--------|-------|
| `user_mode` | `"simple"`, `"advanced"`, `"develop"` | UI complexity level |
| `developer_mode` | `"true"` / `"false"` | Separate boolean, works alongside user_mode |
| `internal_developer_mode` | `"true"` / `"false"` | Force-reset to `false` on every startup |
| `iot_environment` | `"0"`=DEV, `"1"`=QA, `"2"`=PRE, `"3"`=PRODUCT | Which cloud env to connect to |
| `sending_interval` | `"5"` | Telemetry interval |
| `max_send` | `"3"` | Max retry count |
| `user_mode` | see above | |
| `severity_level` | `"fatal"`, `"error"`, `"warning"`, `"info"`, `"debug"`, `"trace"` | Log verbosity |
| `max_recent_count` | int string e.g. `"18"` | Recent projects count |

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

| File inside 3MF ZIP | Purpose |
|---------------------|---------|
| `3D/3dmodel.model` | The mesh geometry (required OPC part) |
| `Metadata/project_settings.config` | **The critical one** — all slicer settings as flat JSON |
| `Metadata/model_settings.config` | Per-object XML + plate definition |
| `Metadata/slice_info.config` | XML with client type/version headers |
| `Metadata/cut_information.xml` | Per-object `<cut_id>` placeholders |
| `Metadata/filament_sequence.json` | `{"plate_1": {"sequence": []}}` |
| `[Content_Types].xml` | Must include PNG and gcode content types |

### `project_settings.config` Requirements

1. **Application metadata must be** `"QIDIStudio-01.05.00.69"` — if wrong, QIDIStudio ignores all embedded configs and shows `dont_load_config = true` in the log
2. **All values are strings** (or arrays-of-strings) — `"nozzle_diameter": ["0.4"]` not `0.4`
3. **Array-typed keys** use single-element arrays: `["value"]`
4. **Pretty-print** with `indent=4` matching QIDIStudio's `std::setw(4)` output
5. **NO separate preset files** — do NOT include `process_settings_1.config`, `filament_settings_1.config`, or `machine_settings_1.config`
6. `filament_settings_id` must reference a preset that **physically exists** on the user's machine — template variables in gcode (`[nozzle_temperature]` etc.) resolve from the filament preset, NOT from `project_settings.config`

### Critical Key Names (common sources of confusion)

| Key | Notes |
|-----|-------|
| `curr_bed_type` | NOT `bed_type`. Selects which `*_plate_temp` key provides bed temp. Set to `"Textured PEI Plate"` |
| `printer_settings_id` | Must match system machine preset name e.g. `"Q2 0.4 nozzle"` |
| `print_compatible_printers` | Array: `["Q2 0.4 nozzle"]` |
| `different_settings_to_system` | 3-element array: `[process_diffs, filament_diffs, machine_diffs]` (semicolon-separated key names) |
| `support_chamber_temp_control` | `"1"` — required for chamber heater activation |

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

| `iot_environment` | Enum | Host |
|-------------------|------|------|
| `"0"` | `ENV_DEV_HOST` | Internal DEV server |
| `"1"` | `ENV_QAT` | QA/testing server |
| `"2"` | `ENV_PRE` | PRE/staging server |
| `"3"` | `ENV_PRODUCT` | Production server |

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

| Filament | Nozzle | Bed | Chamber | Notes |
|----------|--------|-----|---------|-------|
| ASA-GF (Siraya Fibreheart) | 270°C | 100°C | 65°C | Hardened steel runs ~10°C colder than brass |
| PETG Translucent | 250°C | 75°C | 0°C | No chamber heat — fans off for max clarity |
| Standard PETG | 240°C | 75°C | 0°C | |
| QIDI ASA (stock) | 250°C | 90°C | 60°C | System preset values |

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

| Feature | Speed | Temp | Fan |
|---------|-------|------|-----|
| Outer wall | 20mm/s | 275°C | 0% |
| Bridge | 20mm/s | 265°C | 100% |
| First 2 layers | 10mm/s | 280°C | 0% |

---

## 13. Our Modifications vs Upstream

All changes relative to `QIDITECH/QIDIStudio` main branch:

### Applied Changes (in forked source)

| File | Change | Reason |
|------|--------|--------|
| `src/slic3r/GUI/wxExtensions.cpp:1048` | Restored 3 mode buttons (Simple, Advanced, Developer) | Mode switcher was completely hidden |
| `src/slic3r/GUI/MainFrame.cpp:197` | First-run default: `user_mode="develop"`, `developer_mode=true` | Users start in full-access Developer mode |
| `src/libslic3r/AppConfig.cpp:452` | `iot_environment` default `"2"` → `"3"` in `QDT_RELEASE_TO_PUBLIC=0` branch | Connects to production cloud, not staging |
| `src/slic3r/CMakeLists.txt:638` | `if(QDT_RELEASE_TO_PUBLIC)` → `if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")` | Prevents false-positive evaluation causing missing-file build error |
| `src/slic3r/GUI/Gizmos/GLGizmoText.hpp` | Added public `create_volume(ModelVolumeType, const Vec2d&)` and `create_volume(ModelVolumeType)` | Enables text volume creation from menu without duplicating placement logic |
| `src/slic3r/GUI/Gizmos/GLGizmoText.cpp` | Refactored `on_shortcut_key()` to delegate to `create_volume(MODEL_PART)`; `create_volume()` accepts volume type | Fixes menu-invoked text placement |
| `src/slic3r/GUI/GUI_Factories.cpp` | Uncommented + fixed text branch: `GLGizmoText`/`GLGizmosManager::Text`; added `append_menu_item_add_text()`; wired into `append_submenu_add_generic()` | "Add Part > Text" menu item was entirely dead (commented out with OrcaSlicer class names) |
| `src/slic3r/GUI/GUI_Factories.hpp` | Added `append_menu_item_add_text()` declaration | Header needed for new factory function |
| `src/slic3r/GUI/Gizmos/GLGizmoSVG.hpp` | Added `draw_tiling()` declaration; added `m_tile_x=1`, `m_tile_y=1`, `m_tile_gap=0.f` members | SVG tiling state |
| `src/slic3r/GUI/Gizmos/GLGizmoSVG.cpp` | Added `draw_tiling()` UI function; added tiling replication logic in `process_job()`; wired `draw_tiling()` call into `draw_window()` | SVG tiling feature — repeat SVG pattern in a configurable grid |
| `src/slic3r/GUI/Plater.cpp` | Added `apply_skin_to_selection()` + `can_apply_skin()` functions | New "Add Skin…" right-click menu action |
| `src/slic3r/GUI/Plater.hpp` | Added `apply_skin_to_selection()`, `can_apply_skin()` declarations | Header for above |
| `src/slic3r/GUI/GUI_Factories.cpp` | Wired "Add Skin…" into object context menu via `append_menu_items_add_skin()` | Menu entry to invoke the Add Skin feature |
| `resources/scripts/apply_skin.py` | New Python script: heightmap displacement with triplanar projection. Preserves 3MF slicer settings. | The actual skin application logic called by Plater |

### Feature: "Add Part > Text" Menu (fixed)

**Root cause:** `GUI_Factories.cpp` had the text/emboss branch commented out with `/* ... */`, and the code inside used OrcaSlicer class names (`GLGizmoEmboss`, `GLGizmosManager::Emboss`) instead of QIDI's names (`GLGizmoText`, `GLGizmosManager::Text`).

**QIDI naming vs OrcaSlicer naming:**

| Concept | OrcaSlicer | QIDI |
|---------|-----------|------|
| Text emboss gizmo class | `GLGizmoEmboss` | `GLGizmoText` |
| EType enum value | `GLGizmosManager::Emboss` | `GLGizmosManager::Text` |

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

### Feature: "Add Skin" — Displacement Texture on Mesh

Adds a **"Add Skin…"** item to the 3D object right-click menu. The feature:
1. Lets the user pick a PNG/JPG/SVG skin asset (e.g. dragon scales, damascus steel, chainmail)
2. Runs `resources/scripts/apply_skin.py` as an external Python subprocess
3. The script displaces the mesh vertices along surface normals by the skin heightmap
4. The script writes a `_skin.3mf` adjacent to the source, preserving ALL slicer settings
5. C++ redirects the object's `input_file` to the skin output, then calls `reload_from_disk()`

**C++ entry point:** `Plater::apply_skin_to_selection()` in `Plater.cpp`

**Algorithm (`resources/scripts/apply_skin.py`):**

```
Load 3MF mesh (trimesh)
  → subdivide_to_size(max_edge=3.0mm)     # midpoint, no repositioning = no corner spikes
  → triplanar displacement:
       hmap_XY = tile(skin, sz_x, sz_y, tile_mm)   # top/bottom
       hmap_XZ = tile(skin, sz_x, sz_z, tile_mm)   # front/back
       hmap_YZ = tile(skin, sz_y, sz_z, tile_mm)   # left/right
       for each vertex:
           w_xy = |n_z|, w_xz = |n_y|, w_yz = |n_x|   # blend by normal direction
           height = w_xy*sample(hmap_XY) + w_xz*sample(hmap_XZ) + w_yz*sample(hmap_YZ)
           v' = v + n * height
  → Copy original 3MF zip verbatim, replacing only 3D/3dmodel.model with displaced mesh
  → Print "SKIN_OUTPUT: <path>" to log
```

**C++ reload flow:**
- After `wxExecute` returns 0, C++ reads `SKIN_OUTPUT:` from the log file
- Sets `obj->input_file = skin_output_path` and `volumes[i]->source.input_file = skin_output_path`
- Calls `reload_from_disk()` — existing infrastructure handles scene/UI refresh
- This was critical: `delete_object + load_files` was tried first and FAILED silently (UI didn't refresh)

**Key bugs fixed (2026-02-25):**

| Bug | Root cause | Fix |
|-----|-----------|-----|
| C++ loads original instead of skin | `reload_from_disk()` reads from `obj->input_file`, which still points to original | Redirect `input_file` → skin output before calling `reload_from_disk()` |
| "Stretched single image" on side walls | Pure XY planar projection — vertical faces all get same U or V = degenerate | Triplanar projection: blend XY/XZ/YZ based on vertex normal direction |
| Spike artifacts at cable notch corners | Loop subdivision reshapes sharp corners + averaged vertex normals get large displacements | `subdivide_to_size(max_edge)` midpoint-only subdivision preserves sharp geometry; `max_iter=6` caps vertex count at 64× original |
| Relief nearly invisible (0.333mm) | Default relief 0.5mm × max heightmap 0.66 = too small for 0.4mm nozzle | Relief default 0.5 → **1.5mm** |
| Tiles too small | Default tile 15mm → scales barely visible on larger objects | Tile default 15 → **30mm** |
| Scale bodies flat, crevices raised ("cracked mud" look) | Image is dark-bodied: bright ridges displaced outward, dark scale bodies at zero | **Invert by default** — dark → high displacement so each scale becomes a raised dome |
| Relief wasted (1.006mm actual vs 1.5mm requested) | Scale PNGs have compressed range (mean~53/255, max~0.67) — dividing by 255 wastes 33% of range | **Histogram stretch** `(arr - min) / (max - min)` normalizes to full [0,1] before applying relief |
| 914K verts on 230mm lid (21MB output) | `max_iter=10` allows unlimited 2× doublings until max_edge reached | `max_iter=6` caps at 64× original triangle count |
| **"No mesh objects found" — script produces useless output** | QIDIStudio stores each geometry in `3D/Objects/object_N.model`; script was reading only `3D/3dmodel.model` which contains component references, not mesh data | Scan ALL `*.model` entries in the zip; find `<object>` elements with `<mesh>` across all files |
| **"Unable to reload" for multi-component models** | Only object[0] got displaced; remaining objects kept original vertex counts → mismatched geometry → QIDIStudio 3MF parse failure | Per-object displacement (each `<object>` XML element processed independently, global BB shared for consistent tile phase) |
| **`foo_skin_skin.3mf`** on re-run | Output name always appended `_skin` without checking existing suffix | Strip `_skin` from stem before adding it; re-runs overwrite same file |
| **XML `or` element lookup broken in Python 3.13** | `elem.find(ns) or elem.find(bare)` — `bool(Element)` is unreliable: empty element = False in old Python, always True in new | Replace all `or` fallbacks with explicit two-step `if x is None: x = y` |

**CLI / script parameters:**

```bash
apply_skin.py <model.3mf> <skin.png> [--tile-size 30] [--relief 1.5] [--max-edge 3.0]
              [--invert | --no-invert] [--gamma 0.7]
```

- `--tile-size`: tile pitch in mm (default **30**). Each tile is one copy of the skin image.
- `--relief`: max displacement in mm (default 1.5). Must exceed nozzle diameter to be visible.
- `--max-edge`: subdivide until all mesh edges ≤ this mm (default 3). Set 0 to skip.
- `--invert / --no-invert`: invert heightmap before applying (default ON). Use `--no-invert` for images where white=raised.
- `--gamma`: power curve 0..2 (default 0.7). <1 rounds scale domes, >1 sharpens crispness.

**Heightmap processing pipeline:**
```
Raw image L channel (0..255)
  → /255 → float32 [0..1]
  → histogram stretch: (arr - min) / (max - min)   ← uses full range; scale PNGs are dark (mean~0.2)
  → invert: 1.0 - arr                              ← dark scale bodies → high; bright edges → low
  → gamma: arr ** 0.7                              ← rounds dome profile (0.7 = gentle bell curve)
  → scale: arr * relief_mm                         ← convert to mm
```
Why invert? Dragon/reptile scale images are rendered with **dark scale surfaces** and bright ridge/edge highlights. If you displace by the raw value, the bright edges get pushed out (looks like cracked mud/random noise). Inverted: the dark scale body becomes the raised dome — produces classic overlapping scale look.

Why histogram stretch? Scale PNGs often have max brightness ~0.67 (171/255). Without stretching, effective relief = `0.67 × 1.5mm = 1.0mm` instead of `1.5mm` — you silently lose 33% of depth.

**Skin assets location:** `resources/assets/` (subfolders: `dragon_scales/`, `reptile_scales/`, etc.)
Assets are AI-generated PNGs (Vertex AI Imagen 3 or Replicate Flux Schnell) via `scripts/generate_skin_assets.py`.

**Settings preservation in 3MF:**
The Python script copies the entire original `.3mf` zip verbatim, replacing only `3D/3dmodel.model`.
All of `Metadata/project_settings.config` (temperatures, fan settings, speeds, filament IDs) is preserved intact.
This is critical — loading an `.stl` instead would silently reset all slicer settings to defaults.

### Planned Improvements

- [ ] Restore more developer/debug UI elements locked behind `internal_developer_mode`
- [ ] Add QIDIStudio as a build target in GitHub Actions CI
- [ ] Investigate replacing `qidi_networking.dll` with open implementation for LAN printing
- [ ] Expose more filament/process parameters that QIDI hid in presets
- [ ] Add GCodeRefiner as an optional post-processor template in default presets
- [ ] Fix temperature resolution so custom filament presets work correctly in gcode templates

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

| Property | Value |
|----------|-------|
| IP | `192.168.0.116` (static DHCP) |
| Moonraker API | `http://192.168.0.116:7125/` |
| Web UI (Fluidd) | `http://192.168.0.116/` |
| Upload endpoint | `POST /server/files/upload` (multipart: `file` + `root=config`) |
| Firmware restart | `POST /printer/firmware_restart` |
| Nozzle | 0.4mm hardened steel |
| Bed size | 270×270×256mm |
| Firmware | Klipper, CoreXY |

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
