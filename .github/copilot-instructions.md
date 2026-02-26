# Copilot Instructions — QIDIStudio Fork

## CRITICAL AGENT RULES — Read First

### Never Use `workbench.action.terminal.sendSequence`

**NEVER call `run_vscode_command` with `workbench.action.terminal.sendSequence`** to run terminal commands. This is a VS Code keyboard-sequence injector, not a terminal runner. Using it to execute scripts will cause an infinite retry loop that spams the user with popups and requires manual intervention to stop.

**Always use `terminal-tools_sendCommand`** to run commands in the terminal. Example:
```
terminal-tools_sendCommand(
    terminalName="build",
    command='Set-Location C:\\QIDISrc\\QIDIStudio\\build; cmake --build . --target install --config Release -- /m:16 2>&1 | Tee-Object build_out.txt',
    workingDirectory='C:\\QIDISrc\\QIDIStudio\\build'
)
```

### Don't Loop on Failed Tool Calls

If a tool call fails or returns an error, **do not retry it more than twice**. Switch to an alternative tool or approach. Retrying a broken call in a loop is the #1 cause of agent lockups in this workspace.

### Don't Save All Files Unnecessarily

Do not call `workbench.action.files.saveAll` or `workbench.action.files.save` unless the user has explicitly asked you to save something. File edits via `replace_string_in_file` / `create_file` are already persisted to disk.

### Terminal Reuse — Never Spawn Extra Windows

**The user hates having 30 terminal windows open.** Always reuse named terminals. Never create a new terminal if one already exists for that purpose.

**Fixed terminal names for this workspace — always use these exact names:**

| Name | Purpose |
|---|---|
| `build` | CMake builds: `cmake --build . --target install --config Release -- /m:16` (run from `C:\QIDISrc\QIDIStudio\build\`) |
| `git` | All git operations (add, commit, push) |
| `scripts` | Python script execution: `apply_texture_bpy.py`, `generate_skin_assets.py`, GCodeRefiner, etc. |
| `general` | One-off commands, file ops, diagnostics, env checks |

**Protocol before every `terminal-tools_sendCommand` call:**
1. **Check first** — call `terminal-tools_listTerminals` if unsure whether a terminal exists.
2. **Reuse** — pass the existing name; `terminal-tools_sendCommand` reuses it automatically.
3. **Never call `terminal-tools_createTerminal`** unless a genuinely new purpose arises that has no existing named terminal.
4. **Never open more than 4 terminals total** at any point. If a 5th would be needed, reuse `general`.

**Reading build output:** After sending a long-running build command, read the tee'd output file rather than polling the terminal repeatedly. Always tee build output: `... 2>&1 | Tee-Object build_out.txt`.

### Async Terminal Output — Fire-and-Poll Protocol

**NEVER block waiting for terminal output.** After firing a command, immediately do other work (file edits, other tool calls), then poll the output file once. This is the correct pattern:

```
# Step 1 — Fire command, append sentinel, tee to file (DO NOT WAIT)
terminal-tools_sendCommand(
    command='... 2>&1 | Tee-Object out.txt; echo "DONE" >> out.txt'
)

# Step 2 — Do other work immediately (file edits, parallel tasks, etc.)
replace_string_in_file(...)   # <-- run these in parallel, don't stall
create_file(...)

# Step 3 — Poll ONCE by reading the output file
read_file(path="out.txt")  # check for "DONE" sentinel
# If not done yet, do more work and check again — never busy-poll
```

**Rules:**
- Always append a `DONE` sentinel: `; echo "DONE" >> out.txt` so you know when the process finished without re-querying the terminal
- Never call `terminal_last_command` repeatedly hoping output appeared — read the file
- For parallel independent tasks: fire ALL terminal commands first, do ALL file edits, THEN poll results in one pass
- Max 2 polls before declaring a script hung and investigating the error
- **`Tee-Object` buffers output in PowerShell** — `build_out.txt` line count will plateau and seem frozen while MSBuild is still running. Use `Get-Process MSBuild` to check if it's alive; read the file again after MSBuild exits.
- **`captureOutput:true` in `terminal-tools_sendCommand` is non-blocking** — returns immediately (0ms) without waiting. Never use it for long-running processes.

---

## Workspace Overview — QIDIStudio Fork

This workspace is our **fork of QIDIStudio** (`https://github.com/phantom-man/QIDIStudio`), cloned at `C:\Users\User\source\repos\QIDIStudio\`.

Key additions/fixes over upstream QIDI:
- **Mode switcher** — Simple / Advanced / Developer buttons restored (upstream has them commented out)
- **Add Part / Add Negative Part → Texture** — right-click menu wired to bpy headless displacement pipeline
- `iot_environment` default fixed to production (`"3"`) when building without the private network module
- `QIDINetwork.cpp` cmake policy bug patched for public builds

**Full knowledge doc**: `docs/QIDISTUDIO_KNOWLEDGE.md`

---

## Two-Repo Layout — CRITICAL

Source editing and CMake building happen in **two separate directory trees**. Workspace edits are NEVER automatically reflected in the build. Always sync before building.

| Role | Path |
|------|------|
| **Workspace** (editing here) | `C:\Users\User\source\repos\QIDIStudio\` |
| **Build source** (cmake reads from here) | `C:\QIDISrc\QIDIStudio\` |
| **Build output** | `C:\QIDISrc\QIDIStudio\build\` |
| **Install dir** (running app) | `C:\QIDISrc\QIDIStudio\install_dir\` |
| **Launcher** | `qidi-studio.exe` (thin wrapper) — real build product is `QIDIStudio.dll` (92MB) |

### Sync Command (run after every workspace edit, before building)

```powershell
$src = "C:\Users\User\source\repos\QIDIStudio\src\slic3r"
$dst = "C:\QIDISrc\QIDIStudio\src\slic3r"
# Repeat for each changed file:
Copy-Item "$src\GUI\Plater.cpp"               "$dst\GUI\Plater.cpp"               -Force
Copy-Item "$src\GUI\Plater.hpp"               "$dst\GUI\Plater.hpp"               -Force
Copy-Item "$src\GUI\GUI_Factories.cpp"        "$dst\GUI\GUI_Factories.cpp"        -Force
Copy-Item "$src\GUI\GUI_Factories.hpp"        "$dst\GUI\GUI_Factories.hpp"        -Force
Copy-Item "$src\GUI\TextureParamsDialog.cpp"  "$dst\GUI\TextureParamsDialog.cpp"  -Force
Copy-Item "$src\GUI\TextureParamsDialog.hpp"  "$dst\GUI\TextureParamsDialog.hpp"  -Force
```

Also sync scripts that CMake installs:
```powershell
Copy-Item "C:\Users\User\source\repos\QIDIStudio\resources\scripts\apply_texture_bpy.py" `
          "C:\QIDISrc\QIDIStudio\resources\scripts\apply_texture_bpy.py" -Force
Copy-Item "C:\Users\User\source\repos\QIDIStudio\resources\scripts\apply_texture_bpy.py" `
          "C:\QIDISrc\QIDIStudio\install_dir\resources\scripts\apply_texture_bpy.py" -Force
```

### Build Command

```powershell
Set-Location C:\QIDISrc\QIDIStudio\build
cmake --build . --target install --config Release -- /m:16 2>&1 | Tee-Object build_out.txt
echo "DONE" >> build_out.txt
```

### CMake Re-Configure (required when adding new .cpp/.hpp to CMakeLists.txt)

```powershell
Set-Location C:\QIDISrc\QIDIStudio\build
$env:PKG_CONFIG_PATH = "C:\QIDIDeps\usr\local\lib\pkgconfig"
& "C:\CMake329\bin\cmake.exe" .. -G "Visual Studio 17 2022" -A x64 `
    -DQDT_RELEASE_TO_PUBLIC=0 `
    -DCMAKE_PREFIX_PATH=C:\QIDIDeps/usr/local `
    -DCMAKE_INSTALL_PREFIX=C:\QIDISrc\QIDIStudio\install_dir `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 `
    "-DPKG_CONFIG_EXECUTABLE=C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\bloodrock.pkg-config-lite_Microsoft.Winget.Source_8wekyb3d8bbwe\pkg-config-lite-0.28-1\bin\pkg-config.exe"
```

### bpy_env Junction

`bpy_env` lives in the workspace but must be accessible from `install_dir`. Created once:
```
cmd /c mklink /J "C:\QIDISrc\QIDIStudio\install_dir\bpy_env" "C:\Users\User\source\repos\QIDIStudio\bpy_env"
```
Do NOT recreate — the junction persists. Do NOT set `QIDI_BPY_PYTHON` env var unless the junction is missing.

---

## VS Code Agent Hooks

Hooks live in `.github/hooks/` and fire at agent lifecycle points. All log to the shared audit file `.github/hooks/precompact.log` with timestamps.

| File | Event | What it does |
|------|-------|-------------|
| `precompact.json` | `UserPromptSubmit` | Runs `prompt_submit_hook.ps1` → injects `"use Context7"` into every prompt via stdout JSON; logs to `precompact.log` |
| `precompact.json` | `PreCompact` | `git add` + `git commit` of instructions + knowledge docs before context compacts; logs result to `precompact.log` |
| `prompt_submit_hook.ps1` | — | PowerShell script: logs timestamp to `precompact.log`, outputs `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"use Context7"}}` |

**Verify hooks are loaded**: Chat view → right-click → Diagnostics → hooks section.

**Hook log**: `.github/hooks/precompact.log` — one line per fire. Check this if hooks seem not to be running.

---

## Fork Change Log — Divergences from Upstream QIDI

| Change | File(s) | Description |
|--------|---------|-------------|
| Mode switcher restored | `src/slic3r/GUI/wxExtensions.cpp:1048` | All 3 buttons (Simple/Advanced/Developer) added; upstream QIDI has them commented out |
| First-run Developer default | `src/slic3r/GUI/MainFrame.cpp:197` | `"simple"` → `"develop"` so Developer mode is the default on first launch |
| `iot_environment` fix | `src/slic3r/GUI/AppConfig.cpp` | Upstream defaults to `"2"` (PRE/staging) for public builds; our fork defaults to `"3"` (production) |
| `if(QDT_RELEASE_TO_PUBLIC)` patch | `src/slic3r/CMakeLists.txt:638` | Changed to `if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")` to prevent cmake policy trap |
| Texture menus | `GUI_Factories.cpp/hpp`, `Plater.cpp/hpp`, `TextureParamsDialog.cpp/hpp` | Add Part / Add Negative Part → Texture... right-click items with bpy displacement pipeline |
| `TextureParamsDialog` registered | `src/slic3r/CMakeLists.txt` | New dialog files registered for build |
| `apply_texture_bpy.py` | `resources/scripts/` | Headless bpy script for PNG displacement texturing |

**QIDIStudio.conf keys** (in `C:\Users\<user>\AppData\Roaming\QIDIStudio\QIDIStudio.conf`):
- `user_mode` → `"simple"`, `"advanced"`, or `"develop"`
- `developer_mode` → `"true"` / `"false"`
- `internal_developer_mode` → force-reset to `false` on every startup (cannot persist)
- `iot_environment` → `"0"`=DEV, `"1"`=QA, `"2"`=PRE, `"3"`=PRODUCT

**To force Developer mode without rebuild** — edit `QIDIStudio.conf` directly:
```json
{ "user_mode": "develop", "developer_mode": "true", "iot_environment": "3" }
```

### `qidi_networking.dll` — Missing Closed-Source Module
This DLL is QIDI's private networking module, not in the public source. Without it:
- Host Setting dialog cannot save
- Device binding / cloud pairing fail
- Log shows `load dll failed`

LAN printing via Moonraker REST API (`http://192.168.0.116:7125/`) still works fine.

### Windows Registration Script
After building, run `C:\Users\User\Downloads\_register_qidi.ps1` to create Start Menu shortcut, App Paths registry entry, and Add/Remove Programs entry.

### PowerShell Syntax for Build Commands
`&&` is NOT valid PowerShell. Always use semicolons:
```powershell
# WRONG (parse error):
cd C:\QIDISrc\QIDIStudio\build && cmake --build .

# CORRECT:
Set-Location C:\QIDISrc\QIDIStudio\build; & "C:\CMake329\bin\cmake.exe" --build . ...
```

---

## Python Environments — This Repo

| Env | Python | Purpose | Executable |
|-----|--------|---------|------------|
| `.venv` | 3.13 | General scripts: trimesh, pyvista, AI image gen | `.venv\Scripts\python.exe` |
| `bpy_env` | 3.11 | Blender headless (bpy pip package) — displacement texturing | `bpy_env\Scripts\python.exe` |
| System Python 3.13 | 3.13 | CadQuery (installed system-wide, NOT in any venv) | `C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe` |

**Why bpy requires Python 3.11:** The standalone `bpy` pip package targets Blender 4.x which bundles Python 3.11. Never install `bpy` into `.venv` or system Python 3.13 — it will fail.

**bpy_env location:** `C:\Users\User\source\repos\QIDIStudio\bpy_env\`

---

## QIDIStudio — Build From Source (Windows)

Use when the installer is broken (corrupted EXE, silent fail, 0xc000007b).

### Key Paths
- **Source ZIP**: `C:\Users\User\Downloads\QIDIStudio-2.04.01.11.zip` (88 MB)
- **Extracted source**: `C:\QIDISrc\QIDIStudio\`
- **Deps output**: `C:\QIDIDeps\`
- **Install dir**: `C:\QIDISrc\QIDIStudio\install_dir\`
- **Build script**: `C:\Users\User\Downloads\_build_qidi.py`
- **Build log**: `C:\Users\User\Downloads\qidi_build_log.txt`

### Tool Versions (installed via winget, all working)
- CMake 3.29.8 → `C:\CMake329\bin\cmake.exe` (**use this, not winget cmake 4.x — see gotcha below**)
- Strawberry Perl 5.42.0.1 → `C:\Strawberry\perl\bin\perl.EXE`
- VS 2022 Community v17.14 → MSBuild at `C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe`
- pkg-config-lite 0.28 → `C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\bloodrock.pkg-config-lite_Microsoft.Winget.Source_8wekyb3d8bbwe\pkg-config-lite-0.28-1\bin\pkg-config.exe`

### Critical Build Gotchas

**CMake 4.x policy break** — CMake 4.x removed backward compat with `cmake_minimum_required < 3.5`. Fix: use cmake 3.29.8 at `C:\CMake329\bin\cmake.exe`, or add `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`.

**pkg-config not found on Windows** — `src/slic3r/CMakeLists.txt` calls `pkg_check_modules(LIBAV REQUIRED ...)` without a `if(NOT WIN32)` guard. Fix: pass `-DPKG_CONFIG_EXECUTABLE=...` and set `PKG_CONFIG_PATH=C:\QIDIDeps\usr\local\lib\pkgconfig`.

**`QIDINetwork.cpp` cmake policy trap** — cmake's `if(QDT_RELEASE_TO_PUBLIC)` with an undefined variable evaluates TRUE (CMP0012/CMP0054). File doesn't exist in public ZIP → configure fails. Double fix: patch `CMakeLists.txt:638` AND pass `-DQDT_RELEASE_TO_PUBLIC=0`.

**Stale VS project files** — Deleting only `CMakeCache.txt` is not enough. Wipe the ENTIRE build directory, then re-configure.

**Terminal CWD locks build dir** — `rd /s /q` fails with `[WinError 32]` if any terminal has that dir as CWD. Run `cd C:\` in ALL terminals first, then: `cmd /c rd /s /q "C:\QIDISrc\QIDIStudio\build"`

**OpenSSL MSB8066 exit 9009** — perl not found. Fix: `-DPERL_EXECUTABLE=C:\Strawberry\perl\bin\perl.exe`. Also: always use `/m:1` for deps build — parallel ExternalProject causes race conditions.

**`build_win.bat` targets VS 2019** — Don't use it. Run cmake directly with `-G "Visual Studio 17 2022"`.

### Correct Build Commands

```
# Deps configure
cmake ../ -G "Visual Studio 17 2022" -A x64
  -DDESTDIR=C:\QIDIDeps -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  -DPERL_EXECUTABLE=C:\Strawberry\perl\bin\perl.exe

# Deps build (SEQUENTIAL — critical)
cmake --build . --config Release -- /m:1 /v:minimal

# App configure (PKG_CONFIG_PATH must be set in env)
cmake .. -G "Visual Studio 17 2022" -A x64
  -DQDT_RELEASE_TO_PUBLIC=0
  -DCMAKE_PREFIX_PATH=C:\QIDIDeps/usr/local
  -DCMAKE_INSTALL_PREFIX=C:\QIDISrc\QIDIStudio\install_dir
  -DCMAKE_BUILD_TYPE=Release
  -DWIN10SDK_PATH="C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0"
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  -DPKG_CONFIG_EXECUTABLE=C:\...\pkg-config.exe

# App build (parallel OK)
cmake --build . --target install --config Release -- /m:16 /v:minimal
```

**Patch required before app configure:**
```cmake
# src/slic3r/CMakeLists.txt line 638 — change from:
if(QDT_RELEASE_TO_PUBLIC)
# to:
if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")
```

### Expected Timeline
- Deps configure: ~5 min | Deps build: ~40-60 min | App configure: ~2 min | App build + install: ~30-40 min
- **Total: ~90 min on a fast machine**

---

## Add Part > Texture — BPY Feature

Right-click menu items that apply a PNG displacement texture to the skin of a selected 3D part using Blender's headless rendering pipeline.

### Status (as of 2026-02-26)

| Step | Status |
|------|--------|
| Python/bpy pipeline (`apply_texture_bpy.py`) | ✅ Complete, confirmed working |
| C++ wiring (menus, dialog, Plater methods) | ✅ Complete, compiled |
| Menu items visible in running app | ✅ Confirmed (screenshot) |
| bpy_env junction created | ✅ `install_dir\bpy_env` → workspace `bpy_env` |
| Script produces `SKIN_OUTPUT:` + valid STL | ✅ Confirmed manually (56KB, 1.5s) |
| Committed | ✅ `ef2ec27` |
| **Full UX test (texture volume loads in 3D view)** | ✅ Crash fixed (`f5c3436`) — pending live test |
| **"Adjust Texture Depth..." item appears on child** | 🔄 Pending |
| **Depth ±0.2/±0.5 buttons work without compounding** | 🔄 Pending |

### Full UX Test Sequence (next session — pick up here)

1. Kill any running QIDIStudio, launch: `& "C:\QIDISrc\QIDIStudio\install_dir\qidi-studio.exe"`
2. Load any STL model
3. Select it → right-click → **Add Negative Part → Texture...**
4. Pick a PNG from `install_dir\resources\assets\` (e.g. `armadillo_plates_01.png`), tile=15, relief=1.2 → OK
5. Expected: texture volume appears as named child in object list
6. Right-click the texture child → verify **"Adjust Texture Depth..."** appears
7. Click it → verify dialog is prefilled, ±buttons clamp correctly
8. Confirm depth change produces deeper/shallower texture without compounding artifacts

**If "Adjust Texture Depth..." doesn't appear:**
- `can_adjust_texture_depth()` checks `volume_is_texture(vol)` which checks `vol->source.input_file + ".texture.json"` exists
- Verify `load_from_files()` sets `vol->source.input_file` to the result STL path (it should)

### Why BPY over trimesh

| | trimesh (`apply_skin.py`) | bpy (`apply_texture_bpy.py`) |
|---|---|---|
| Subdivision | midpoint only | Blender Simple — preserves hard edges |
| Displacement | Python loop per vertex | Blender Displace modifier |
| UV tiling | manual math | Empty-object-scaled — zero seams |
| Output | 3MF | STL (C++ reload wraps in 3MF) |

### Script: `resources/scripts/apply_texture_bpy.py`

```
apply_texture_bpy.py  <model_stl>  <skin_asset>
    [--mode part|negative|modifier]
    [--tile-size 15]   [--relief 1.0]
    [--invert]         [--gamma 0.7]
    [--log <logfile>]
```

Outputs: `SKIN_OUTPUT: <path>` to stdout. C++ parses this line.

**Invocation:** `bpy_env\Scripts\python.exe resources\scripts\apply_texture_bpy.py model.stl skin.png --mode negative --log out.txt`

### C++ Wiring Summary

**New files:** `src/slic3r/GUI/TextureParamsDialog.hpp/.cpp`

**Modified files:**
- `GUI_Factories.hpp/cpp` — `append_menu_item_add_texture()`, `append_menu_item_adjust_texture_depth()`
- `Plater.hpp/cpp` — `apply_texture()`, `adjust_texture_depth()`, `can_apply_texture()`, `can_adjust_texture_depth()`, `find_bpy_python()` (static), `volume_is_texture()` (static)

**Sidecar JSON** (`<result_stl>.texture.json`) stores `{png, src_stl, tile_mm, relief, mode}` — enables re-adjustment from original clean mesh without compounding artifacts.

**`find_bpy_python()` search order:** `QIDI_BPY_PYTHON` env var → `<resources_dir>/../bpy_env/Scripts/python.exe`

### Key Gotchas

- **`plater() == nullptr` at menu registration time** — Menus are built at startup before plater exists. Any `if (plater() == nullptr) return;` guard in `append_menu_item_*` silently drops the item permanently. Guard only inside the lambdas (at click time / update time), never at registration.

```cpp
// WRONG — kills the item silently at startup:
void MenuFactory::append_menu_item_add_texture(wxMenu* menu, ModelVolumeType type) {
    if (plater() == nullptr) return;  // ← permanent deletion, no second chance
    ...
}

// CORRECT — guard only in lambdas:
void MenuFactory::append_menu_item_add_texture(wxMenu* menu, ModelVolumeType type) {
    append_menu_item(menu, wxID_ANY, item_name, "",
        [type](wxCommandEvent&) { if (plater()) plater()->apply_texture(type); },
        "icon", nullptr,
        []() { return plater() && plater()->can_apply_texture(); },
        m_parent);
}
```

- **`ShowModal()` clears the 3D canvas Selection before returning** — On Windows, a dialog's `WM_DESTROY` fires a focus event on the 3D canvas that clears `Selection` BEFORE `ShowModal()` returns control. Any code reading `scene_selection()` or `get_selection()` after a `ShowModal()` call will see an empty selection set and crash. **Fix pattern:** capture `instance_idx`, `inst_transform`, `instance_offset` into local variables from the live `Selection` BEFORE `ShowModal()`. Never call `ObjectList::load_from_files()` or `ObjectList::load_generic_subobject()` after a dialog close — they both dereference `selection.get_instance_idxs().begin()` without an empty check. Do the `Model::read_from_file` + `mo->add_volume()` + transform setup directly instead.

- **`wxWindowDisabler` during `wxEXEC_SYNC` blocks stdout pipe** — `wxWindowDisabler` blocks the Win32 message pump; `wxEXEC_SYNC` drains the child's stdout via the message pump. Together they deadlock. Fix: use `--log <tmpfile>` IPC instead of stdout, and don't use `wxWindowDisabler` during `wxExecute`.

- **`apply_texture_bpy.py` sync** — CMake installs it from `C:\QIDISrc\QIDIStudio\resources\scripts\` at build time, NOT from the workspace. After editing in workspace, copy to BOTH:
  ```powershell
  $script = "resources\scripts\apply_texture_bpy.py"
  Copy-Item "C:\Users\User\source\repos\QIDIStudio\$script" "C:\QIDISrc\QIDIStudio\$script" -Force
  Copy-Item "C:\Users\User\source\repos\QIDIStudio\$script" "C:\QIDISrc\QIDIStudio\install_dir\$script" -Force
  ```

- **`bpy.ops.wm.read_factory_settings(use_empty=True)`** must be called first — Blender initializes with a default cube otherwise.

- **Scale length** — `scene.unit_settings.scale_length = 0.001` so 1 Blender unit = 1mm.

- **Displace modifier needs an Empty for texture coords** — scaling the Empty to `tile_size` gives seamless world-space tiling.

- **Output naming** prevents `_texture_modifier_texture_modifier.stl` on re-runs by stripping known suffixes before appending.

### Skin Assets

`resources/assets/` — PNG heightmaps generated by `scripts/generate_skin_assets.py`.
- Procedural: `honeycomb`, `diamond_knurl`, `voronoi_cells`, `chainmail`, `brick_pattern`, `herringbone`, `riveted_metal`
- AI (Replicate Flux Schnell): `dragon_scales`, `reptile_scales`, `damascus_steel`, `carbon_fiber`, etc.

---

## GCode Refiner — Feature-Aware Post-Processor

**Location**: `GCodeRefiner/` (this repo, `C:\Users\User\source\repos\QIDIStudio\GCodeRefiner\`)
**Research doc**: `GCodeRefiner/gcode_research.md`
**Status**: v1.0.0 — M2 gear rules + ASA-GF 0.4mm profile implemented

A standalone Python post-processor that parses 3D printing GCode, detects feature types
from slicer comment markers (`; TYPE:OUTER_WALL` etc.), and injects optimized parameters
(temperature, fan, speed, acceleration) per feature type and filament profile.

No existing tool does this end-to-end. See `GCodeRefiner/gcode_research.md` for full survey.

### File Structure

```
GCodeRefiner/
  refiner.py               — main entry point (also works as QIDIStudio post-processing script)
  profiles/
    asa_gf_04mm.py         — ASA-GF + 0.4mm hardened steel nozzle base envelope
  rules/
    m2_gear.py             — M2 module gear optimization rules
  gcode_research.md        — full research: existing tools, architecture, optimization data
  README.md                — usage instructions
```

### Integration as QIDIStudio Post-Processing Script

Add to Print Settings → Output Options → Post-processing scripts:
```
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\User\source\repos\QIDIStudio\GCodeRefiner\refiner.py" --rules m2_gear --verbose
```
QIDIStudio appends the gcode file path automatically as the last argument.

### CLI Usage

```powershell
# Process gcode file in-place
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" .\GCodeRefiner\refiner.py input.gcode --rules m2_gear

# Dry run (shows what would be injected, no file changes)
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" .\GCodeRefiner\refiner.py input.gcode --rules m2_gear --dry-run --verbose

# List available profiles/rules
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" .\GCodeRefiner\refiner.py --list-profiles
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" .\GCodeRefiner\refiner.py --list-rules
```

### Architecture

```
input.gcode → detect feature type (;TYPE: comments) → lookup override in rules/*.py
            → inject M104/M106/M204/F per feature transition → output.gcode (in-place)
```

### Adding Rule Sets

Copy `rules/m2_gear.py` → `rules/my_rules.py`. Required interface:
```python
def get_override(move_type: str, layer: int, profile: object) -> dict | None:
    # Return {'speed_mm_s': 20, 'nozzle_temp': 275, 'fan': 0, 'accel': 1000}
    # or None to use profile defaults
```
Feature type strings: `OUTER_WALL`, `INNER_WALL`, `SPARSE_INFILL`, `SOLID_INFILL`,
`BRIDGE`, `SUPPORT`, `SKIRT_BRIM`, `PRIME_TOWER`.

### M2 Gear Optimization (rules/m2_gear.py)

| Feature | Speed | Temp | Fan | Rationale |
|---------|-------|------|-----|-----------|
| Outer wall (tooth surface) | 20mm/s | 275°C | 0% | Geometry fidelity + max layer bonding |
| Inner wall | 40mm/s | 270°C | 0% | Less critical but still no fan (ASA) |
| Solid infill | 30mm/s | 270°C | 20% | Light cooling for flat hub faces |
| Sparse infill | 80mm/s | 265°C | 31% | Speed up here — interior, not critical |
| Bridge | 20mm/s | 265°C | 100% | Hub bore and tooth tip bridges |
| First 2 layers | 10mm/s | 280°C | 0% | Maximum bed adhesion |

Recommended layer height for M2 gears: **0.15mm** (≤ module/10).

### Planned Extensions

- `rules/tr8x2_screw.py` — TR8×2 lead screw thread flanks (15mm/s outer, 0.10mm layer advisory)
- `rules/structural_asa.py` — Maximum bonding (fan=0 everywhere, optimized for tensile strength)
- `rules/fine_detail.py` — General fine-feature rule (<0.5mm features)
- Flow ratio injection via GcodeTools `block.move.set_flowrate()` (waiting for API to stabilize)

---

## Amazon Link Fetching Protocol

When the user asks for Amazon purchase links, follow this exact procedure. Amazon blocks simple `urllib` / `Invoke-WebRequest` calls with CAPTCHAs unless the request looks like a real browser.

### Step 1 — Write a Temporary Python Fetch Script

Create `_fetch_amazon.py` in the repo root. Use **Python `urllib.request`** (no pip installs required) with a realistic Chrome User-Agent:

```python
import urllib.request, re, time

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

def fetch_search(query):
    """Amazon search → list of ASIN strings."""
    url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    asins, seen = [], set()
    for m in re.finditer(r'data-asin="([A-Z0-9]{10})"', html):
        a = m.group(1)
        if a not in seen:
            seen.add(a)
            asins.append(a)
    return asins[:10]

def fetch_product(asin):
    """Fetch product page → {asin, title, price, url}."""
    url = f"https://www.amazon.com/dp/{asin}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL)
    title = re.sub(r'\s*[-:]\s*Amazon\.com.*$', '',
                   title_m.group(1).strip()) if title_m else "No title"
    price_m = re.search(
        r'class="a-price-whole">(\d+)</span>.*?'
        r'class="a-price-fraction">(\d+)', html, re.DOTALL)
    price = f"${price_m.group(1)}.{price_m.group(2)}" if price_m else "N/A"
    return {"asin": asin, "title": title, "price": price, "url": url}
```

### Step 2 — Two-Phase Retrieval

1. **Search phase**: `fetch_search("query string")` → 8-10 ASINs from `data-asin` attributes (works even with CAPTCHA HTML).
2. **Product phase**: `fetch_product(asin)` for top 5 ASINs; add `time.sleep(0.8)` between requests.
3. **Price** often fails (lazy-loaded via JS) — report `"N/A"`, user sees it on click-through.

### Key Gotchas

- **Do NOT use `Invoke-WebRequest` in PowerShell** via Desktop Commander — `$` vars get stripped by the MCP tool's argument parser. Always use a Python script.
- **Do NOT use Desktop Commander's `read_file` with `isUrl=true`** — bare request gets HTTP 503.
- **Run with Python 3.13**: `& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" _fetch_amazon.py`
- **Delete `_fetch_amazon.py`** after use — throwaway helper, not part of the project.
- **Amazon CAPTCHA**: HTML may say "robot" but still includes `data-asin`. Don't abort — extract ASINs anyway.

### Output Format

Present as a Markdown table with: product name, pack quantity, direct link, search URL fallback. Note wrong-size results explicitly.

---

## Visual Reference Log Protocol

Copilot **cannot recover images** from summarized conversations. Once a conversation is summarized, all shared screenshots and renders are permanently inaccessible.

### When the User Shares an Image

1. **Save the image** to `docs/images/`:
   - VS Code stores pasted chat images at `%APPDATA%\Code\User\workspaceStorage\vscode-chat-images\` as timestamped JPEG/PNG.
   - Find the latest: `Get-ChildItem "$env:APPDATA\Code\User\workspaceStorage\vscode-chat-images" | Sort-Object LastWriteTime -Descending`
   - Copy to `docs/images/IMG-NN.jpeg` (sequential numbering).

2. **Append to `docs/VISUAL_REFERENCE_LOG.md`**:
   - Sequential number + date
   - `![IMG-N](images/IMG-NN.jpeg)`
   - Detailed text description (geometry, colors, dimensions, annotations, problem areas)
   - Which file/function it relates to
   - Whether it shows a **problem**, **desired state**, or **reference**
   - What decisions/code changes were made in response

3. **Never skip** — even trivial images. The log is the only cross-session visual memory.
4. **Reference log entry numbers** in code comments when making changes based on an image.

### When Starting a New Session

Read `docs/VISUAL_REFERENCE_LOG.md` before modifying any geometry or UI code.

### Self-Verification Without Images

Copilot cannot view rendered PNGs or QIDIStudio windows. For geometry verification:
- Use **cross-section analysis** (intersect with thin slabs at multiple positions) for numerical bounds
- Compare every processing stage against the original STEP/reference cross-sections
- Print cross-section tables to terminal and analyze them before declaring success

---

## "Save This" Protocol

**AUTO-RUN RULE:** At the natural end of every conversation — when work is wrapping up, or when the user says "done", "thanks", "that's it", "good job", "save this", "save that", "update instructions" — automatically run this protocol WITHOUT being asked.

1. **Extract** key learnings: new conventions, gotchas from debugging, hardware findings, format requirements, tool-specific behaviors, user preferences.
2. **Categorize** under the appropriate existing section, or create a new section if needed.
3. **Deduplicate** — update/refine existing entries rather than duplicating.
4. **Write concretely** — specific values, code snippets, filenames. Not "be careful with X" but "X requires Y because Z".
5. **Read this file first** before editing to avoid clobbering recent additions.
6. **Show the user** a brief summary of what was added/changed.

The `PreCompact` hook at `.github/hooks/precompact.json` will auto-commit these files when context compacts. The "Save This" protocol is for extracting and writing the knowledge; the hook handles the git commit.

---

## Skills — When to Load Which Skill

Skills are in `.agents/skills/`. Load them with `read_file` on demand. All skill files are `SKILL.md` inside the named folder.

### C++ / QIDIStudio Core Development

| Trigger | Skill |
|---------|-------|
| Writing or reviewing any C++ code (wxWidgets, OpenGL, CMake) | `cpp-pro` |
| Tracking down crashes, wxExecute failures, Python subprocess errors, silent bugs | `debugging-wizard` |
| Designing new feature architecture (BPY pipeline, gizmo wiring, C++↔Python bridge, menu system) | `architecture-designer` |
| Reviewing a C++ patch before commit — correctness, safety, style | `code-reviewer` |
| CMake issues, dependency config, build system, CI/CD | `devops-engineer` |
| Refactoring nested conditionals, early returns in C++ | `control-flow` |
| Error handling patterns in C++ or Python | `error-handling` |
| Challenging a design or assumption before a major change | `dissent` |

### Python Scripts

| Trigger | Skill |
|---------|-------|
| Writing or reviewing Python scripts (`apply_texture_bpy.py`, `generate_skin_assets.py`, GCodeRefiner) | `python-pro` |
| Designing a FastAPI web layer for companion tooling | `fastapi-expert` |
| Real-time printer status dashboard over WebSockets | `websocket-engineer` |

### AI / Generative

| Trigger | Skill |
|---------|-------|
| Vertex AI / Replicate image generation prompts for skin assets | `prompt-engineer` |
| Fine-tuning a diffusion model on custom skin asset training data | `fine-tuning-expert` |

### Process / Collaboration

| Trigger | Skill |
|---------|-------|
| Writing commit messages, structuring commits | `git` |
| Responding to GitHub issues on `phantom-man/QIDIStudio` | `github-issues` |
| Writing or updating `docs/QIDISTUDIO_KNOWLEDGE.md` or this file | `documentation` |
| Summarizing session work for handoff / pre-compact | `progress-summary` |
| Defining a new feature with full spec before implementation | `feature-forge` |
| Brutally honest code/design review | `honesty` |

### Less-Common (load when needed)

| Skill | When |
|-------|------|
| `database-optimizer` | Persistent storage in companion tools |
| `postgres-pro` | PostgreSQL-backed companion service |
| `sql-pro` | SQL queries in any tooling |
| `csharp-developer` | C# companion tooling |
| `kubernetes-specialist` | Containerized deployment |
| `microservices-architect` | Decomposing monolithic build scripts |
| `mcp-developer` | Building MCP servers for QIDIStudio tooling |
| `fullstack-guardian` | Full-stack companion web UI |
