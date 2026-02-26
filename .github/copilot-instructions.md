# Copilot Instructions — QIDIStudio + 3D Printing Workspace

## CRITICAL AGENT RULES — Read First

### Never Use `workbench.action.terminal.sendSequence`

**NEVER call `run_vscode_command` with `workbench.action.terminal.sendSequence`** to run terminal commands. This is a VS Code keyboard-sequence injector, not a terminal runner. Using it to execute scripts will cause an infinite retry loop that spams the user with popups and requires manual intervention to stop.

**Always use `terminal-tools_sendCommand`** to run commands in the terminal. Example:
```
terminal-tools_sendCommand(
    terminalName="build",
    command='cd c:\\Users\\User\\source\\repos\\3DPrinting\\DragonJewelryBox; & "C:\\Users\\User\\AppData\\Local\\Programs\\Python\\Python313\\python.exe" modify_axis_models.py',
    workingDirectory='c:\\Users\\User\\source\\repos\\3DPrinting\\DragonJewelryBox'
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
| `scripts` | Python script execution: `apply_texture_bpy.py`, `apply_skin.py`, `generate_skin_assets.py`, etc. |
| `general` | One-off commands, file ops, diagnostics, env checks |

**Additional terminal when working in the 3DPrinting repo:**

| Name | Purpose |
|---|---|
| `3dp` | CadQuery scripts in `C:\Users\User\source\repos\3DPrinting\` |
| `upload` | Moonraker/printer file uploads via `_upload_config.py` |

**Protocol before every `terminal-tools_sendCommand` call:**
1. **Check first** — call `terminal-tools_listTerminals` if unsure whether a terminal exists.
2. **Reuse** — pass the existing name; `terminal-tools_sendCommand` reuses it automatically.
3. **Never call `terminal-tools_createTerminal`** unless a genuinely new purpose arises that has no existing named terminal.
4. **Never open more than 4 terminals total** at any point. If a 5th would be needed, reuse `general`.

**Reading build output:** After sending a long-running build command, read results with `mcp_io_github_won_read_file` on `build_out.txt` rather than polling the terminal repeatedly. Always tee build output: `... 2>&1 | Tee-Object build_out.txt`.

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
mcp_io_github_won_read_file(path="out.txt")  # check for "DONE" sentinel
# If not done yet, do more work and check again — never busy-poll
```

**Rules:**
- Always append a `DONE` sentinel: `; echo "DONE" >> out.txt` so you know when the process finished without re-querying the terminal
- Prefer `mcp_io_github_won_read_file` over `read_file` for polling (faster, no caching issues)
- Never call `terminal_last_command` repeatedly hoping output appeared — read the file
- For parallel independent tasks: fire ALL terminal commands first, do ALL file edits, THEN poll results in one pass
- Max 2 polls before declaring a script hung and investigating the error

---

## Workspace Overview

Python/CadQuery parametric CAD for 3D-printable parts, exported as 3MF with embedded slicer settings. Target printer: **Qidi Q2 2025** (270×270×256mm, Klipper, CoreXY, hardened steel 0.4mm nozzle).

## Repo Structure — Top-Level Directories

```
3DPrinting/
  DragonJewelryBox/   # Dragon jewelry box parts (01-06_*.py, config.py, utils.py)
  AxisMounts/         # modify_axis_models.py, barrel_nut.py, preview_3mf.py, _ref_settings.json
  CNController/       # cnc_controller_box.py
  Dragon/             # Downloaded models re-exported for QIDIStudio (export_dragon_qidi.py)
  VacuumNozzle/       # vacuum_crevice_nozzle.py
  PhoneCase/          # poco_x6_pro_case_b3d.py (Elvish build123d), older phone case scripts
  .venv/              # Python virtual environment
  .github/            # copilot-instructions.md
```

Each project has its own `STL/` output subdirectory. `AxisMounts/` contains the canonical shared utilities that all other projects import:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "AxisMounts"))
from modify_axis_models import export_combined_3mf    # 3MF export with QIDIStudio settings
from preview_3mf import preview_3mf                   # OCP CAD Viewer preview for any 3MF
```

## Local Design Library — LaserFiles

**Location**: `C:\Users\User\Documents\LaserFiles\`

A large collection of laser-cut SVG/DXF design files. Key resources for 3D printing projects:

### Most Useful for Dragon Jewelry Box

| Path | Contents | Use |
|------|----------|-----|
| `500+ Filigree Scroll - SVG\` | 509 numbered SVGs (1.svg–509.svg) — filigree & scroll patterns | **Lid inlay relief, corner accent designs** — clean SVG, directly importable via `svgpathtools` |
| `1\100_dragons\` | 57 named dragon `.tif` bitmaps (e.g. `DRAGONCURL.tif`, `CORNERACCENTDRAGON.tif`, `CLASSICWESTERNDRAGON.tif`, `CELTICCORNERSERPENT.tif`) | Visual reference for dragon pull/knob shape; trace for SVG outlines |
| `new_models_2024\wooden_gift_box_jewellery_box_pen_box_1\` | `.svg`, `.dxf`, `.ai`, `.pdf` jewelry box laser plans | Dimensional reference for box construction |
| `new_models_2024\wooden_gift_box_jewellery_box_pen_box_2\` | Same, second variant | Same |
| `new_models_2024\slider_box_bundle\` | Sliding drawer box files in 5 sizes: 120×180×80, 180×220×100, 220×180×100, 220×260×120, 260×220×120 — `.svg` + `.dxf`, 3mm and 3+18mm plywood variants | Drawer slide mechanism reference |

### Other Notable Packs
- `new_models_2024\` — large collection: trays, key holders, phone stands, clocks, 3D letters, animals, etc.
- `pack_2d_various\` — general 2D vector packs
- `500+ Filigree Scroll - DXF\` — same filigrees in DXF format

### SVG Import Pattern (filigree → CadQuery lid relief)
```python
import svgpathtools
paths, attrs = svgpathtools.svg2paths(r"C:\Users\User\Documents\LaserFiles\500+ Filigree Scroll - SVG\42.svg")
# Convert svg path segments to CadQuery wire, extrude for 3D relief
```
Always check SVG viewBox dimensions — laser files are typically in mm at 1:1 scale but some use px units (1 px = 0.352778 mm at 96 DPI).

---

## Dragon/images — Pattern & SVG Library

**Location**: `c:\Users\User\source\repos\3DPrinting\Dragon\images\`  
**Git status**: Ignored (too large). Never commit this folder.

A massive in-repo collection of SVG/DXF/PNG design assets covering seamless patterns and dragon artwork. Immediately useful for surface textures, embossed reliefs, and shape outlines on any 3D project.

### Critical Collections

| Folder | Files | Format | Best Use |
|--------|-------|--------|----------|
| `Dragon SVG\` | 150 dragon SVGs (`Dragon-01.svg`–`Dragon-150.svg`) + duplicate `(2)` set | SVG | **Dragon pull knob outline, lid centrepiece, jewelry box dragon relief** |
| `dragon scale pattern\New Folder With Items\` | 120 scale patterns (`dragon scale 1.svg`–`120.svg`) + DXF/PNG | SVG+DXF+PNG | **Drawer front texture, lid background fill, phone case back** |
| `damascus steel pattern\svg\` | 120 wavy steel patterns (`Damscus steel 1.svg`–`120.svg`) + DXF/PNG | SVG+DXF+PNG | **Phone case back texture, CNC controller panel, any metallic-look surface** |
| `Pattern Celtic_Knotwork\` | 140 knotwork patterns (`Seamless Celtic Knotwork 1.svg`–`140.svg`) + DXF/PNG | SVG+DXF+PNG | **Jewelry box border inlays, corner accents, lid frame** |
| `ornament patterns\svg\` | Ornamental patterns | SVG | Decorative reliefs |
| `geometric seamless pattern\` | Geometric fills | SVG | Infill-inspired surface patterns |
| `tribal pattern\` | Tribal/primitive patterns | SVG | Exotic accent pieces |
| `Pattern Moroccan Tile\` | Moroccan tile tessellations | SVG | Tray inserts, flat panel textures |
| `mesmerizing patterns\` | Abstract hypnotic patterns | SVG | Statement panels |

### Other Pattern Collections (all SVG+DXF+PNG unless noted)
`aztec pattern`, `chevron pattern`, `fishnet pattern`, `floral flower pattern`, `grunge texture pattern`, `honeycomb pattern`, `knitted yard pattern`, `leaves pattern`, `leopard tiger zebra pattern`, `polka dot pattern`, `rose flower pattern`, `stripe pattern`, `tiger stripes pattern`, `tire pattern`, `tribal pattern`, `watermelon seeds pattern`, `weave pattern`

Seamless packs: `Seamless boho mandala pattern`, `Seamless pattern bohemian feather`, `Seamless pattern hawaiian tiki mask`, `Seamless pattern moroccon tiles`, `Star seamless pattern`

Cultural: `Pattern Aboriginal_Dot_Art`, `Pattern African Mug Cloth`, `Pattern Embroidered_Fabric`, `pattern Japanese_Shibori`, `Pattern Mexican_Talavera`, `Pattern Persia Rug`, `Pattern Rangoli`, `Pattern Scandinavian_Folk_Art`

PNG packs: `PNG 1/`, `png 2/`, `PNG 3/`, `PNG 4/` — raster versions of all patterns.

### SVG Import Pattern (pattern → CadQuery surface relief)
```python
import svgpathtools, os

# Dragon scale tile for drawer front
paths, attrs = svgpathtools.svg2paths(
    r"c:\Users\User\source\repos\3DPrinting\Dragon\images\dragon scale pattern\New Folder With Items\dragon scale 42.svg"
)

# Damascus steel for phone case back
paths, attrs = svgpathtools.svg2paths(
    r"c:\Users\User\source\repos\3DPrinting\Dragon\images\damascus steel pattern\svg\Damscus steel 15.svg"
)

# Dragon silhouette for pull knob / lid relief
paths, attrs = svgpathtools.svg2paths(
    r"c:\Users\User\source\repos\3DPrinting\Dragon\images\Dragon SVG\Dragon-42.svg"
)
```
SVGs are typically px-unit at 96 DPI (1 px = 0.352778 mm). Scale accordingly when converting to CadQuery wires.

### Gallery Scripts
- `Dragon/_browse_gallery.py` — HTML thumbnail browser for any pattern folder (open in browser to pick designs visually)
- `DragonJewelryBox/_gallery_ocp.py` — OCP CAD Viewer gallery for all built jewelry box 3MF parts

---

## Python / CadQuery (DragonJewelryBox)

### Environment

- **Python 3.13.7** — CadQuery is installed in the **system** Python 3.13, NOT in a venv. Run scripts with: `& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" script.py`. Python 3.11 is also installed but does NOT have CadQuery.
- **CadQuery 2.7.0** with OCC kernel
- Run scripts from `DragonJewelryBox/`: `python modify_axis_models.py`, `python generate_all.py`

### Critical CadQuery Rule

**Always pass `clean=False`** to `.union()` and `.cut()` boolean operations. OCC's cleaning pass crashes on complex geometry. Every boolean in this codebase follows this pattern:

```python
result = shape.union(other, clean=False)
result = result.cut(bore, clean=False)
```

### Avoiding Coincident-Surface Artifacts

When a cut cylinder shares the exact radius with the existing bore, OCC produces artifacts. Use an epsilon offset:

```python
bore = cyl_along_y(r + 0.1, ymin - 0.1, ylen + 0.2, cx, cz)  # r+0.1 avoids coincident faces
```

### CadQuery revolve() Axis — 2D Workplane Coordinates Only

`Workplane.revolve(angleDegrees, axisStart, axisEnd)` interprets `axisStart` and `axisEnd` as **2D workplane coordinates**, NOT 3D world points. CadQuery's `toWorldCoords()` only uses the first 2 components of any tuple. Passing 3D tuples like `(0, 0, 0)` and `(0, 0, 1)` maps both to the **same** world point (since only X,Y are read), producing a degenerate axis.

**Correct** (XZ workplane, revolve around world Z axis):
```python
profile.revolve(30, (0, 0), (0, 1))   # 2D: U=0,V=0 → U=0,V=1  (Z axis)
```

**Wrong** (silently degenerates):
```python
profile.revolve(30, (0, 0, 0), (0, 0, 1))  # 3D tuples → both map to same 2D point
```

### CadQuery Compound Union Silently Fails

`cq.Compound.makeCompound(solids)` followed by `body.union(compound, clean=False)` silently returns the body unchanged — no error, no merged geometry. Always use **iterative union**:

```python
result = core
for seg in segments:
    result = result.union(seg, clean=False)
```

### Workplane center() for Off-Origin Features

When cutting features (chamfers, bores) that aren't at the workplane origin, use `.center(u, v)` to reposition the drawing origin. A common bug is creating YZ-plane circles for bore chamfers and forgetting to offset to the bore's Z position:

```python
# BUG: chamfer cut at Z=0 instead of bore center
cone = cq.Workplane("YZ").workplane(offset=x_pos).circle(r).extrude(d)

# FIX: move to bore center
cone = cq.Workplane("YZ").workplane(offset=x_pos).center(0, bore_z).circle(r).extrude(d)
```

### Project Structure — DragonJewelryBox

- `config.py` — All dimensions as named constants. Every part script imports from here; never hardcode dimensions.
- `utils.py` — Shared helpers: `export_stl()`, `validate_print_bounds()`, dragon scale patterns.
- `01_base_tray.py` .. `06_claw_feet.py` — Single-color part generators (each has a `create_*()` function).
- `03_lid_mc.py` .. `06_claw_feet_mc.py` — Multi-color variants returning `[(color, shape), ...]` tuples.
- `export_3mf.py` — Multi-color 3MF exporter with embedded QIDIStudio settings.
- `generate_all.py` — Master script that runs all part generators.

### Project Structure — AxisMounts

- `AxisMounts/modify_axis_models.py` — STEP→3MF pipeline + canonical `export_combined_3mf` + `QIDI_SETTINGS_ASAGF`. All other projects import from here.
- `AxisMounts/preview_3mf.py` — **Universal 3MF→OCP preview module** (see "Previewing 3MF in OCP CAD Viewer" below). Importable from any project.
- `AxisMounts/barrel_nt.py` — TR8×2 cross-dowel barrel nut. Outputs `AxisMounts/STL/barrel_nut.3mf`.
- `AxisMounts/_ref_settings.json` — Golden 519-key QIDIStudio reference settings (must stay next to `modify_axis_models.py`).
- `AxisMounts/_upload_config.py` — Moonraker file upload helper.

### Project Structure — Dragon (Downloaded Models)

- `Dragon/modelo1finalpla.3mf` — Original PrusaSlicer/PLA 3MF downloaded from the internet.
- `Dragon/export_dragon_qidi.py` — Converts the PrusaSlicer 3MF to QIDIStudio-native format with PETG Translucent Clear settings. Run with `--preview` to auto-show in OCP.
- `Dragon/STL/dragon_petg_clear.3mf` — Output: QIDIStudio-ready 3MF. Open directly in QIDIStudio to slice and print.

This is the template for the **Downloaded Model Workflow** (see below). New downloaded models get a similar folder + export script.

### Project Structure — Other Projects

- `VacuumNozzle/vacuum_crevice_nozzle.py` — Parametric vacuum crevice nozzle. Outputs `VacuumNozzle/STL/vacuum_nozzle_lower.3mf`, `vacuum_nozzle_upper.3mf`, `vacuum_nozzle_tips.3mf`.
- `CNController/cnc_controller_box.py` — CNC controller electronics enclosure. Outputs `CNController/STL/cnc_box_tray.3mf`, `cnc_box_lid.3mf`, `cnc_box_door.3mf`.
- `PhoneCase/poco_x6_pro_case_b3d.py` — Elvish phone case (build123d). Outputs `PhoneCase/STL/elvish_*.3mf`.
- `PhoneCase/research/poco_x6_pro_camera_shutter_case.md` — Exhaustive research report (worm drive kinematics, N20 concept superseded).

### 3MF Export for QIDIStudio

QIDIStudio requires specific 3MF structure (verified against a golden reference 3MF exported directly from QIDIStudio v02.04.01.11):

1. **Application metadata** must be `"QIDIStudio-01.05.00.69"` — otherwise all configs are skipped (`dont_load_config = true`).
2. **`Metadata/project_settings.config`** — JSON with header keys `"version"`, `"name": "project_settings"`, `"from": "project"`, then **ALL** flattened slicer settings (process + filament + machine combined).
3. **NO embedded preset files** — do NOT include `process_settings_1.config`, `filament_settings_1.config`, or `machine_settings_1.config`. The reference 3MF from QIDIStudio doesn't have them. Including them causes silent temperature resolution failures (embedded presets load without `recover=true` and can corrupt state).
4. **Required metadata files** beyond project_settings:
   - `Metadata/model_settings.config` — per-object XML + plate definition with `<model_instance>` elements
   - `Metadata/slice_info.config` — XML with `X-QDT-Client-Type` and `X-QDT-Client-Version` headers
   - `Metadata/cut_information.xml` — per-object `<cut_id>` placeholders
   - `Metadata/filament_sequence.json` — `{"plate_1": {"sequence": []}}`
5. All values are **strings** or **arrays of strings** — matching QIDIStudio's `save_to_json()` serialization. Ints/floats like speeds must be `"300"` not `300`.
6. Array-typed keys (speeds, temps, per-extruder values) use `["value"]` format: `"nozzle_diameter": ["0.4"]`.
7. Pretty-print with `indent=4` to match QIDIStudio's `std::setw(4)`.
8. `[Content_Types].xml` must include PNG and gcode content types in addition to rels and model.

### Naming Convention — No OrcaSlicer References

All slicer-related variable names and comments must reference **QIDIStudio**, not OrcaSlicer. The settings dict is `QIDI_SETTINGS_ASAGF` (not `ORCA_SETTINGS_ASAGF`). Comments say "QIDIStudio" not "Orca Slicer". OrcaSlicer caused major problems with this printer (rogue macro injection, broken chamber heating) and should not appear in the codebase. The only acceptable "orca" reference is the `orca_profiles/` directory name (legacy folder path).

### Slicer Settings Location

Settings dict `QIDI_SETTINGS_ASAGF` in `modify_axis_models.py` contains the complete Q2 Strength profile with ASA-GF overrides. When changing print parameters, update this dict — not the export function. All settings are flattened into `project_settings.config` (no separate preset files).

### Temperature Strategy

Temperature constants `_NOZZLE_TEMP`, `_BED_TEMP`, `_CHAMBER_TEMP` are defined before `QIDI_SETTINGS_ASAGF` and flow into the config values (`nozzle_temperature`, `chamber_temperatures`, all `*_plate_temp` keys). Current values: **270 / 100 / 65**.

**Template variables** in gcode (`M104 S[nozzle_temperature_initial_layer]`, `M141 S[chamber_temperatures]`) resolve from the **filament preset** identified by `filament_settings_id`, NOT from `project_settings.config` overrides. This means:
- `filament_settings_id` must reference a preset that actually exists on the user's machine (system OR user-created).
- If the preset name doesn't match, template variables resolve to **empty strings → 0°C** in Klipper.
- If it matches a system preset (e.g., "QIDI ASA"), temps resolve to that preset's values (250°C/90°C), ignoring our overrides.

**Solution**: Reference the user's **custom filament preset** `"Siraya Tech Fibreheart ASA-GF @Qidi Q2 0.4 nozzle"` which has the correct temperatures (270°C nozzle, 100°C bed, 65°C chamber). This preset lives at `AppData\Roaming\QIDIStudio\user\default\filament\` and inherits from the system QIDI ASA preset, overriding only the temperature keys.

### Custom QIDIStudio Presets

User-created presets are stored at `C:\Users\<user>\AppData\Roaming\QIDIStudio\user\default\` under `filament/`, `process/`, and `machine/` subdirectories. Each preset is a `.json` file + `.info` companion. The `.json` uses `"inherits"` to extend a system preset and only contains overridden keys. The `.info` file has sync metadata (`base_id`, `updated_time`).

To create a working custom filament preset, it MUST include `nozzle_temperature` and `nozzle_temperature_initial_layer` — not just `nozzle_temperature_range_high`. The range keys only set the UI slider bounds; the actual temp keys control what goes into gcode.

### Critical Key Names

- **`curr_bed_type`** (not `bed_type`) — selects which `*_plate_temp` key provides the bed temperature. Set to `"Textured PEI Plate"`.
- **`printer_settings_id`**: `"Q2 0.4 nozzle"` — must match the system machine preset name so QIDIStudio loads the correct system config and resolves gcode template variables.
- **`print_compatible_printers`**: `["Q2 0.4 nozzle"]` — links print profile to the machine.
- **`different_settings_to_system`**: 3-element array `[process_diffs, filament_diffs, machine_diffs]` with semicolon-separated key names indicating which settings differ from system defaults.
- **`support_chamber_temp_control`**: `"1"` — required for chamber heater activation.

### 3MF Settings Strategy — Minimal Overrides

The 3MF export uses a **base + overlay** pattern: load all 519 keys from `_ref_settings.json` (a golden reference exported from stock QIDIStudio), then overlay only the keys in `QIDI_SETTINGS_ASAGF` that differ. This means:
- The generated `project_settings.config` always contains the full 519+ key set QIDIStudio expects.
- `QIDI_SETTINGS_ASAGF` should contain **only intentional overrides** — never duplicate stock values.
- If a key exists in the reference with the correct value, do NOT add it to `QIDI_SETTINGS_ASAGF`.
- The 2 keys `infill_anchor_max` and `wall_infill_order` were found in our dict but absent from the reference — they were removed. Always cross-check new keys against `_ref_settings.json`.

### 100% Infill Density — QIDIStudio Bug & Correct Settings

**`sparse_infill_pattern` — confirmed invalid values that get silently swapped to `"cubic"`**:
- `"rectilinear"` — replaced with `"cubic"` (confirmed)
- `"zig zag"` (with space) — replaced with `"cubic"` (confirmed) — **this string was NEVER in the QIDIStudio/OrcaSlicer enum**
- `"zig-zag"` (with hyphen) — legacy format, only valid for `internal_solid_infill_pattern` (mapped to `"rectilinear"` on load)

**Root cause (from OrcaSlicer `PrintConfig.cpp` source)**: The UI label "Zig Zag" corresponds to config value `"zigzag"` (no space, no hyphen). All three of `"rectilinear"`, `"zig zag"`, and `"zig-zag"` are either not in the sparse enum or get remapped. Use `"zigzag"` for the aligned-lines sparse pattern.

At 100% infill density, QIDIStudio treats ALL infill as solid infill. The `sparse_infill_pattern` key becomes irrelevant — the actual fill is controlled by `internal_solid_infill_pattern` (default: `"zig-zag"`). However, QIDIStudio still validates `sparse_infill_pattern` on 3MF load, causing a circular bug:

1. `"rectilinear"` at 100% → QIDIStudio silently swaps to `"cubic"`
2. `"cubic"` doesn't support 100% → dialog asks to switch to `"rectilinear"`
3. Goto 1

**Workaround**: When using `"sparse_infill_density": "100%"`, set `sparse_infill_pattern` to `"concentric"` — the only pattern explicitly recommended for 100% infill. Do NOT use `"rectilinear"` (QIDIStudio silently swaps it to `"cubic"` which then fails) or leave the base config's sparse-only pattern (e.g., `"gyroid"`) in place. Control the actual solid fill via `internal_solid_infill_pattern`:

```python
settings_override = {
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "concentric",       # must be 100%-compatible
    "internal_solid_infill_pattern": "monotonic",  # controls actual 100% fill
}
```

**Patterns that apply to solid infill** (from OrcaSlicer wiki): `monotonic`, `monotonic line`, `rectilinear`, `aligned rectilinear`, `concentric`, `hilbert curve`, `archimedean chords`, `octagram spiral`. Of these, `monotonic` gives the smoothest surface and `concentric` is explicitly recommended for 100% infill.

**QIDIStudio naming quirk for `internal_solid_infill_pattern`**: The config value `"zig-zag"` maps to the UI label **"Rectilinear"** (confirmed by `_ref_settings.json` default and QIDIStudio's own warning when loading 3MF files). Do NOT use the string `"rectilinear"` for this key — QIDIStudio will reject it and substitute its default. Use `"zig-zag"` (rectilinear/default), `"monotonic"` (smoothest surface), or `"concentric"`.

| Config value | QIDIStudio UI label |
|---|---|
| `"zig-zag"` | Rectilinear (default) |
| `"monotonic"` | Monotonic |
| `"concentric"` | Concentric |

**Patterns that apply ONLY to sparse infill** (cannot be used at 100%): `grid`, `cubic`, `gyroid`, `triangles`, `honeycomb`, `zigzag`, `crosszag`, `lockedzag`, `line`, `tri-hexagon`, `quartercubic`, `adaptivecubic`, `supportcubic`, `lightning`, `3dhoneycomb`, `lateral-honeycomb`, `lateral-lattice`, `crosshatch`, `tpmsd`, `tpmsfk`.

**Note**: These are the exact config string values from OrcaSlicer `PrintConfig.cpp` `s_keys_map_InfillPattern`. UI labels differ (e.g., config `"zigzag"` = UI "Zig Zag", config `"tri-hexagon"` = UI "Tri-hexagon"). Never use UI label strings as config values.

### Maximum Strength Print Settings

For maximum part strength (structural/functional parts), use these `settings_override` values:

```python
settings_override = {
    "print_settings_id": "0.16mm Max Strength @Q2",
    "wall_loops": "8",              # max practical walls (fills most small parts solid)
    "wall_generator": "arachne",    # fills thin sections between walls properly
    "detect_thin_wall": "1",        # detect and fill thin features
    "sparse_infill_density": "100%",# fully solid
    "sparse_infill_pattern": "concentric", # must be 100%-compatible — see bug above
    # Do NOT use rectilinear (swapped to cubic) or gyroid (sparse-only)
    "internal_solid_infill_pattern": "monotonic",
    "infill_wall_overlap": "25%",   # better wall-infill bonding (stock: 15%)
    "top_shell_layers": "10",       # thick top shell
    "bottom_shell_layers": "10",    # thick bottom shell
    "layer_height": "0.16",         # thinner layers = better Z bonding (~15-20%)
    "outer_wall_speed": "40",       # slower = better fusion on critical perimeters
}
```

At 0.16mm layer height, Z layer bonding improves ~15-20% vs 0.20mm. Diminishing returns below 0.12mm. For small parts (≤20mm), 8 walls at 0.45mm line width = ~3.6mm per side, which fills most cross-sections nearly solid — the 100% infill just catches whatever gaps remain.

### Previewing 3MF in OCP CAD Viewer

`AxisMounts/preview_3mf.py` is the **universal 3MF mesh previewer** for OCP CAD Viewer. It works with any 3MF file (CadQuery-generated, build123d, PrusaSlicer, Cura, downloaded) by parsing the raw mesh triangles and converting them to OCC `TopoDS_Compound` shapes that OCP can render.

**Import from any project:**
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "AxisMounts"))
from preview_3mf import preview_3mf, preview_3mf_files

# Single file
preview_3mf("STL/my_part.3mf")

# Translucent (for clear/transparent filaments)
preview_3mf("STL/my_part.3mf", translucent=True)

# Multiple files side by side
preview_3mf_files(["STL/part_a.3mf", "STL/part_b.3mf"])
```

**CLI usage:**
```bash
python preview_3mf.py path/to/file.3mf              # preview in OCP
python preview_3mf.py file.3mf --translucent          # 60% opacity for clear filament
python preview_3mf.py file.3mf --info                 # print mesh stats, no preview
python preview_3mf.py a.3mf b.3mf                     # batch preview
```

**Available API functions:**
- `extract_meshes_from_3mf(path)` -- returns list of `{name, vertices, triangles, transform}` dicts
- `meshes_to_occ_shapes(meshes)` -- returns list of `(name, TopoDS_Compound)` tuples
- `meshes_to_cq_shapes(meshes)` -- returns list of `(name, cq.Workplane)` for CadQuery interop
- `preview_3mf(path, color, translucent, reset)` -- display in OCP CAD Viewer
- `preview_3mf_files(paths)` -- batch preview multiple files

**Technical detail:** The module builds `Poly_Triangulation` objects from raw vertex/triangle data, wraps them in `TopoDS_Face` via `BRep_Builder`, then combines into `TopoDS_Compound`. This bypasses CadQuery/build123d geometry entirely -- pure OCC mesh rendering. Works for models with 500K+ triangles.

**When to use:** Anytime a script generates or processes a 3MF file and you want to verify geometry in OCP. Add `--preview` flags to export scripts (see `Dragon/export_dragon_qidi.py` for the pattern).

### Downloaded/External Model Workflow

When the user downloads a 3MF from the internet (Printables, Thingiverse, MakerWorld, etc.) and wants to print it on the Qidi Q2, follow the **Dragon pattern**:

1. **Create a project folder**: `ModelName/` at repo root
2. **Place original file**: Drop the downloaded 3MF into the folder
3. **Create export script**: `ModelName/export_modelname_qidi.py` following the `Dragon/export_dragon_qidi.py` template
4. **Define filament settings**: Create a settings overlay dict for the target filament (e.g., `PETG_TRANSLUCENT_CLEAR`, `ASA_GF_STRENGTH`). Load `_ref_settings.json` as base, overlay only changed keys.
5. **Export**: Script extracts mesh from source 3MF, repacks as QIDIStudio-native 3MF with correct settings into `ModelName/STL/`
6. **Preview**: Add `--preview` flag support that calls `preview_3mf()` for OCP verification
7. **Print**: Open the output 3MF in QIDIStudio, slice, and send to printer

**Key function for raw mesh export** (bypasses CadQuery -- works with any mesh):
```python
from preview_3mf import extract_meshes_from_3mf
# ... then pack vertices/triangles directly into QIDIStudio 3MF structure
# See Dragon/export_dragon_qidi.py: export_raw_mesh_3mf()
```

**Common filament overlay patterns** are stored as dicts in each export script. Do NOT create shared filament config files -- each project's settings may differ (supports, infill, speeds) even for the same filament.

### Optimal Filament Print Settings

Research-backed settings for specific filament types. Sources: Bambu Lab Wiki ("Printing tips for transparent PLA/PETG"), CNC Kitchen/Stefan Hermann ("Transparent FDM 3D Prints are Clearly Stronger!"), Rygar1432 ("How to Print Glass" on Printables, 14k downloads).

#### PETG Translucent

**Two distinct failure modes — diagnose before adjusting settings:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| **Milky/white** (no bubbles) | Optical scatter: micro-voids between extrusion lines | Adjust settings: fan off, lower speed, higher flow ratio |
| **Clear but full of bubbles** | Wet filament: moisture → steam pockets in melt | Dry filament longer/hotter — NOT a settings problem |
| Both milky AND bubbles | Both causes at once | Dry first, then tune settings |

**Confirmed 2026-02-23 (round 1)**: Test print came out **clear (not milky) but full of bubbles.** Settings are correct; filament was wet.

**Confirmed 2026-02-23 (round 2)**: After **12h at 65°C** in filament dryer, re-printed with identical settings — **clear AND bubble-free.** Settings + drying protocol fully validated.

**Drying protocol**: Dry at **65°C for 12 hours minimum**. 6h is insufficient. 8h (Bambu recommendation) is marginal. 12h is the confirmed working duration. Bubbles visible in print = wet filament; do not change settings to fix them.

**Root causes of milkiness** (only relevant if filament is confirmed dry):
1. **Fan cooling too high** -- rapid cooling creates micro-voids between extrusions that scatter light
2. **Flow ratio < 1.0** -- under-extrusion leaves air gaps between lines; material must *overfill* to eliminate voids
3. **Print speed too fast** -- insufficient inter-layer fusion time
4. **Layer height too thick** -- more refraction interfaces per mm
5. **Nozzle temp too low** -- incomplete melt flow (hardened steel runs ~10C colder than brass)
6. **Wet filament** -- moisture = bubbles in the extrusion bead = opaque scatter. Diagnose: bubbles visible in print = dry it first before blaming settings

**Infill pattern matters**: Gyroid/cubic/honeycomb scatter light in every direction. Use **`"zigzag"` at a fixed angle** (0 or 90, NOT alternating) so light passes through aligned parallel lines. Ideal: 100% infill with 0 top/bottom layers (Rygar + Bambu). For practical models, use `"zigzag"` at higher density. Do NOT use `"rectilinear"` or `"zig zag"` (with space) for `sparse_infill_pattern` — both are invalid and QIDIStudio replaces them with `"cubic"`. Correct config value is `"zigzag"` (no space/hyphen).

##### Complex Geometry (e.g., Dragon)

For models with overhangs, thin features, and organic shapes where 0% fan would cause print failures. Compromise settings that maximize translucency while keeping the print viable:

```python
# Dragon-class complex model -- translucency compromise
PETG_TRANSLUCENT_COMPLEX = {
    "layer_height": "0.12",           # thin layers, fewer refraction planes
    "line_width": "0.50",             # wider = fewer line boundaries
    "wall_loops": "2",                # fewer walls = less light scatter
    "top_shell_layers": "3",
    "bottom_shell_layers": "3",
    "sparse_infill_density": "40%",
    "sparse_infill_pattern": "zigzag",    # correct enum: UI "Zig Zag" = config "zigzag" (no space). "zig zag"/"rectilinear" are NOT valid → replaced with "cubic"
    "infill_direction": "0",          # fixed angle, not alternating
    "nozzle_temperature": ["250"],    # high for hardened steel
    "fan_min_speed": ["15"],          # NOT 0 -- overhangs need some cooling
    "fan_max_speed": ["30"],          # well below the 40-70 that causes milkiness
    "overhang_fan_speed": ["50"],     # moderate, not 90
    "close_fan_the_first_x_layers": ["5"],
    "filament_flow_ratio": ["1.02"],  # slight over-extrude fills micro-voids
    "outer_wall_speed": ["25"],       # slow for fusion
    "inner_wall_speed": ["40"],
    "sparse_infill_speed": ["50"],
    "top_surface_speed": ["20"],
    "bridge_speed": ["20"],
}
```

**Trade-off**: Print time roughly 2x vs standard PETG settings due to thinner layers + slower speeds. Translucency significantly better than stock but not glass-clear (complex geometry physically limits clarity due to multi-directional extrusions).

##### Simple Geometry (test pieces, flat objects, vases, washers)

For models with no overhangs, no bridging, and simple cross-sections. Maximum transparency -- follows Rygar/Bambu "glass mode" closely:

```python
# Simple geometry -- maximum glass-like transparency
PETG_TRANSLUCENT_GLASS = {
    "layer_height": "0.10",           # thinnest practical (Rygar: 0.10)
    "line_width": "0.50",             # wider = fewer boundaries
    "wall_loops": "1",                # single wall (Bambu: 1, Rygar: 2)
    "top_shell_layers": "0",          # 0 top layers (Bambu + Rygar)
    "bottom_shell_layers": "0",       # 0 bottom layers
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "concentric",  # 100%-density-safe; avoids QIDIStudio cubic-swap bug
    "internal_solid_infill_pattern": "zig-zag",  # QIDIStudio key for "Rectilinear"; + infill_direction=0 = Aligned Rectilinear
    "infill_direction": "0",          # fixed angle every layer = aligned rectilinear behaviour
    "nozzle_temperature": ["250"],    # 245-250°C recommended; 250 = upper bound for hardened steel
    "fan_min_speed": ["0"],           # ALL FANS OFF (Bambu + Rygar + CNC Kitchen)
    "fan_max_speed": ["0"],           # zero cooling = best clarity
    "overhang_fan_speed": ["0"],
    "first_x_layer_fan_speed": ["0"],
    "close_fan_the_first_x_layers": ["999"],
    # Exhaust/chamber fans — must be explicitly zeroed or the QIDI PETG
    # filament preset's non-zero defaults bleed through and run these fast:
    "during_print_exhaust_fan_speed": ["0"],
    "complete_print_exhaust_fan_speed": ["0"],
    "additional_cooling_fan_speed": ["0"],
    "additional_cooling_fan_speed_unseal": ["0"],
    # Chamber circulation fan — runs at 100% when auxiliary_fan=1 regardless of
    # chamber_temperatures. Must be explicitly disabled for PETG glass printing.
    "auxiliary_fan": "0",
    # Chamber temp — set to 0 for PETG. No chamber heat needed (PETG is not
    # ASA/ABS). Setting any non-zero value causes Klipper to spin the chamber
    # circulation fan at 100% to distribute heat, which cools the print and
    # kills clarity. 0 = Klipper leaves chamber fans completely alone.
    "chamber_temperatures": ["0"],
    # CRITICAL: filament_settings_id must reference a REAL preset name exactly.
    # 'QIDI PETG Translucent @Qidi Q2 0.4 nozzle' is a built-in system preset at
    # C:\Program Files\QIDIStudio\resources\profiles\Q Series\filament\
    # It resolves: nozzle=250, chamber=0, fan_min=10, fan_max=30.
    # fdm_filament_common base sets during_print_exhaust_fan_speed=100 — must override below.
    # Template variables like [chamber_temperatures] resolve from this preset → 0.
    "filament_settings_id": ["QIDI PETG Translucent @Qidi Q2 0.4 nozzle"],
    "filament_flow_ratio": ["1.03"],  # higher over-extrude for glass-like fill
    "outer_wall_speed": ["20"],       # Rygar: 20 mm/s everywhere
    "inner_wall_speed": ["20"],
    "sparse_infill_speed": ["20"],
    "internal_solid_infill_speed": ["20"],
    "top_surface_speed": ["20"],
    "bridge_speed": ["20"],
    "initial_layer_speed": ["15"],
    "enable_support": "0",            # simple geometry = no supports needed
}
```

**CNC Kitchen finding**: At 15 mm/s, parts were clearest. Below 10 mm/s, microbubbles formed from filament sitting too long in the melt zone. Flow multiplier is the "most important parameter" -- parts got clearer up to ~105%, then just over-extruded dimensionally.

**Post-processing tip**: Bottom layer will be matte from bed adhesion. A drop of mineral oil or water reveals the true internal clarity. Polishing/sanding with fine grit (2000+) improves surface clarity.

### Vacuum Crevice Nozzle -- Design & Aerodynamics

Three-piece modular vacuum crevice nozzle for cleaning CNC T-slot grooves. Designed for a 65 CFM wet/dry shop vac with 40mm hose ID.

**Aerodynamic flow direction**: Air flows **tip → body → hose** (suction). The expanding taper is a **diffuser**, NOT a nozzle. Critical distinction — diffusers are flow-separation-sensitive; conical diffusers separate at >7° half-angle.

**v3 architecture** (three pieces, each ≤255mm for Qidi Q2):
- **Piece 1 (lower, 250mm)**: Hose plug (Ø39.6mm) + grip + 175mm lower S-curve taper + 20mm female socket
- **Piece 2 (upper, 245mm)**: 20mm male plug + 205mm upper S-curve taper → ends at a **tip socket** (female joint for interchangeable tips)
- **Piece 3a — Crevice tip**: 14×2.5mm narrow slot, 20mm long, male plug into piece 2. For reaching into individual T-slot grooves.
- **Piece 3b — Shoe/sled tip**: 60×40mm flat shoe body with 14mm wide T-slot opening on underside. Sits ON TOP of the T-slot surface forming a sealed plenum. Internal cavity ~840mm² vs body 1134mm² = only 1.35:1 expansion ratio. Diffuser half-angle drops to ~0.6° (essentially zero). Cp ≈ 0.95.

**S-curve diffuser**: Cosine-based `(1 - cos(πt))/2` profile over 380mm total taper. Max local half-angle ~3.7° — fully attached flow. Pressure recovery Cp ≈ 0.88 for crevice tip, ~0.95 for shoe tip.

**Anti-stall bypass holes**: 2×Ø3mm ports in tip side walls. NASA (2010) found that surface seal against a groove stalls flow; bypass holes maintain minimum flow even when tip is sealed.

**Shoe tip key insight**: Instead of minimizing tip area (which creates a harsh diffuser), making the tip WIDER with a sealed bottom surface creates a large internal plenum that nearly matches the body cross-section. This nearly eliminates the diffuser problem while maintaining 37 m/s (130 km/h) at the T-slot opening. Cleans ~24× more T-slot per pass than the crevice tip.

**Joint design**: 20mm friction-fit overlap, 0.15mm clearance/side (0.30mm diametral). Stadium cross-section at split point follows the S-curve contour.

**Key dimensions**: `PLUG_OD=39.6`, `BODY_OD=42`, `TIP_WIDTH=14`, `TIP_HEIGHT=2.5`, `SHOE_WIDTH=60`, `SHOE_LENGTH=40`, `TAPER_LENGTH=380`, `JOINT_LENGTH=20`, `JOINT_GAP=0.15`.

**Research basis**: NASA TM-89858 (1987) — bell contours 4-8% better discharge than conical. NASA (2010) — seal → stall → bypass holes needed. NASA TM-106066 (1993) — boundary layer dominates at low Re.

### CNC Controller Box — Electronics Enclosure

230×130×100 mm parametric enclosure for a CNC controller. Script: `cnc_controller_box.py`. Standalone pattern (own constants, no `config.py` dependency).

**Three-piece design:**
1. **Tray** (bottom + 3 walls, open front): PSU rails, all connector cutouts, fan, louvers, hinge barrels, lid screw bosses.
2. **Lid** (top plate): screws onto tray with M3, front latch receiver flange with M4 bolt hole.
3. **Door** (hinged front panel): ESP32 CYD screen window, 4× M3 standoff bosses, hinge barrels (interleaving), latch tab.

**Components (all mm):**
- Power supply: 215×114×50 (bottom layer, sits on raised rails for airflow)
- TB6600 stepper driver ×2: 96×63×23 (on top of PSU at opposite ends, faceplates face end walls)
- ESP32-2432S028 CYD: 88×54×10 board, 58×43 active screen, M3 holes at 76×42 spacing
- LM2596 buck converter: 53×26×15 (between TB6600s on DIN rail)
- IEC320 C14 power inlet (Amazon B0BCQMDC26): 47.5×28 mm cutout, rocker switch + fuse + cord
- DB9 RS232 ×2 (Amazon B0DFWNGDST): 30.8×12.5 mm cutout, 24.8 mm M3 screw spacing
- 80mm exhaust fan: 71.5mm M4 screw pattern, 37mm grille radius, finger guard rings

**Wall assignments:**
- **Left end (X−)**: TB6600 #1 bracket mount (2× M4) + 7 intake louvers
- **Right end (X+)**: TB6600 #2 bracket mount (2× M4) + 7 intake louvers
- **Back (Y+)**: IEC C14 snap-in + 2× DB9 (3 holes each: 1 D-sub + 2 M3 screws) + 80 mm exhaust fan (circular opening + 4× M4 corner holes + finger guard rings)
- **Front (Y−)**: Hinged door with ESP32 CYD screen window

**Hinge:** M5 pin through interleaving barrels (3 on tray, 2 on door, Ø12 mm barrels, 15 mm long each). Door opens like a book from bottom front edge.

**Latch:** M4 bolt through tab on top of door → hooks under lid flange.

**Output files:** `CNController/STL/cnc_box_tray.3mf`, `CNController/STL/cnc_box_lid.3mf`, `CNController/STL/cnc_box_door.3mf`.

### Qidi Q2 Printer — Network & Klipper

- **IP**: `192.168.0.116` (static DHCP reservation)
- **API**: Moonraker REST API at `http://192.168.0.116:7125/`
- **Web UI**: Fluidd at `http://192.168.0.116/`
- **Config upload**: `POST /server/files/upload` with multipart form (`file` + `root=config`), then `POST /printer/firmware_restart` to reload.
- **Helper script**: `_upload_config.py` in DragonJewelryBox — uploads a file to the printer's config directory via Moonraker.
- **Config backups**: `DragonJewelryBox/printer_backup_20260217_1218/` — full backup of all 29 Klipper config files from the printer.
- **Local config copies**: `current_gcode_macro.cfg`, `current_printer.cfg`, `current_printer_Orca.cfg` in DragonJewelryBox.

### PRINT_START Macro — Heating Sequence Fix

The original Qidi PRINT_START macro had a flawed heating sequence: `M104 S0` (nozzle OFF) → `M140 S{bedtemp}` (bed on) → `G28` (30s homing) → then finally `M141 S{chambertemp}` (chamber on). This meant 2 of 3 heaters showed 0°C targets when the job started, which QIDIStudio's device view reported as zero thermals.

**Fixed sequence** (in `current_gcode_macro.cfg`, uploaded to printer):
```
M140 S{bedtemp}       # bed on immediately
M141 S{chambertemp}   # chamber on immediately
M104 S150             # nozzle to standby (below melt, no ooze)
# ... fan logic ...
G28                   # home while all 3 heat
# ... later: M109 S{hotendtemp} brings nozzle to full temp before printing
```

**Key insight**: The M141 macro on this printer has a 65°C cap built in: `SET_HEATER_TEMPERATURE HEATER=chamber TARGET={([s, 65]|min)}`. M191 (wait for chamber) has the same cap.

### Axis Mount Geometry — Thrust Bearing Design

The axis mounts use **51100 thrust bearings** (10mm bore × 24mm OD × 9mm thick) press-fit into the existing Φ24mm bore. Key geometry facts:

- **Bore**: Both axes have a clean R=12mm through-hole with NO internal step/lip in the original STEP files. Lips are ADDED by `modify_axis_models.py`.
- **Motor mount lip**: Annular ring at `tri_y + 9mm` (after bearing zone), reduces bore from R=12 to R=10, 2mm thick. Bearing enters from table face, stopped by lip before coupler zone.
- **Bearing mount lip (REVERSED)**: Annular ring at `tri_y` (table face side), R=10, 2mm thick. Bearing enters from cut face, stopped at table face. Shaft collar locks from outside.
- **Bracket relief**: Y-axis only (both motor + bearing mounts). 2mm deep pocket matching face profile with 5mm rim. For stamped metal bracket (~55mm wide, ~1.5mm thick).
- **Shaft sleeve bushing**: 8.2mm ID / 9.8mm OD / 12mm long — adapts 8mm lead screw to 10mm bearing bore.
- **Coupler clearance**: 8×8mm coupler (~20mm OD) fits inside 24mm bore with 2mm/side radial clearance.
- **X-axis**: bore center (-10.0, -1.0), tri_y=-17, sq_y=33, cut_y=23.
- **Y-axis**: bore center (-11.0, 5.0), tri_y=2, sq_y=52, cut_y=42.
- **Output files**: `AxisMounts/STL/Axis_motor_mounts.3mf` (supports ON), `AxisMounts/STL/Axis_bearing_mounts.3mf` (no supports), `AxisMounts/STL/Shaft_sleeve_bushing.3mf`.

### OrcaSlicer Damage — Known Issue

OrcaSlicer can inject a broken `[gcode_macro M191]` into the Qidi's `printer.cfg` that references `chamber_heater` instead of Qidi's `chamber` heater name. This causes silent chamber heating failures. Symptoms: chamber shows 0% power, hot end at 0°C. This is a well-documented community issue (Reddit, GitHub). If OrcaSlicer was ever connected to this printer, check `printer.cfg` for rogue macro overrides.

**DISABLE_BOX_HEATER** in end gcode refers to Qidi's **Filament Drying Module (FDM)**, NOT the chamber heater. It's harmless — do not remove it.

## Visual Reference Log Protocol

Copilot **cannot recover images** from summarized conversations. Once a conversation is summarized, all shared screenshots, renders, and annotated images are permanently lost. To prevent this:

### When the User Shares an Image

1. **Save the image file** to `DragonJewelryBox/images/`:
   - VS Code stores pasted chat images at `%APPDATA%\Code\User\workspaceStorage\vscode-chat-images\` as timestamped JPEG/PNG files.
   - Copy the most recent file(s) from that directory to `DragonJewelryBox/images/IMG-NN.jpeg` (sequential numbering).
   - Use `Get-ChildItem "$env:APPDATA\Code\User\workspaceStorage\vscode-chat-images" | Sort-Object LastWriteTime -Descending` to find the latest images.
2. **Immediately** append an entry to `DragonJewelryBox/VISUAL_REFERENCE_LOG.md` with:
   - Sequential number and date
   - **Embedded image**: `![IMG-N](images/IMG-NN.jpeg)` right after the heading
   - **Detailed text description** of what the image shows (geometry, colors, dimensions, annotations, problem areas) — enough that a future Copilot session can understand the image without seeing it
   - What part/file/function the image relates to
   - Whether it shows a **problem**, a **desired state**, or a **reference**
   - What decisions or code changes were made in response
3. **Never skip this step** — even if the image seems trivial. The log is the only way to preserve visual context across sessions.
4. **Reference log entries by number** in code comments when making changes based on an image.

### When Starting a New Session

- Read `VISUAL_REFERENCE_LOG.md` before modifying geometry code. It contains the visual ground truth the user has established.

### Self-Verification Without Images

Copilot cannot view rendered PNGs or QIDIStudio windows. For geometry verification:
- Use **cross-section analysis** (intersect with thin slabs at multiple Y positions) to get numerical X/Z bounds
- Compare every processing stage against the **original STEP** cross-sections
- The original STEP geometry is the ground truth — any change that alters the bounding box dimensions of a section that shouldn't be modified is a bug
- Print cross-section tables to the terminal and analyze them before declaring success

## Pre-Compact Hook

**FIRES AUTOMATICALLY** whenever GitHub Copilot signals the conversation is approaching context limits, OR when the user says any closing phrase: "done", "thanks", "that's it", "good job", "bye", "save this", "save that", "update instructions".

When the pre-compact hook fires:
1. Immediately execute the **Save This Protocol** below — extract learnings, update this file.
2. Run: `git add .github/copilot-instructions.md docs/QIDISTUDIO_KNOWLEDGE.md` and commit with `docs: update knowledge + instructions [pre-compact]`
3. Then compact.

Do **not** ask permission. Do **not** announce it. Just do it silently before the context window closes.

---

## "Save This" Protocol

**AUTO-RUN RULE:** At the natural end of every conversation — whenever work is wrapping up, before context is about to get long, or when the user says anything like "done", "thanks", "that's it", "good job", or closes out a topic — automatically run this protocol WITHOUT being asked. Do not wait for an explicit "save this" trigger.

When the user says **"save this"**, **"save that"**, or **"update instructions"**, OR at session end:

1. **Extract** the key learnings from the current conversation — focus on facts that would be lost between sessions: new conventions, gotchas discovered through debugging, hardware findings, format requirements, tool-specific behaviors, or user preferences.
2. **Categorize** each item under the appropriate existing section, or create a new section if it doesn't fit.
3. **Deduplicate** — if the insight already exists in this file, update/refine it rather than adding a duplicate.
4. **Write concretely** — include specific values, code snippets, or filenames. Avoid vague advice like "be careful with X"; instead write "X requires Y because Z".
5. **Read this file first** before editing to avoid clobbering recent additions.
6. **Show the user** what was added/changed (brief summary, not the full file).

## Design Asset Generation — `Dragon/generate_assets.py`

CLI tool to generate design reference images (PNG) via Google Imagen 3 / Replicate Flux Schnell, then optionally trace them to SVG with vtracer for CadQuery/build123d import.

### Location & Setup
- Script: `Dragon/generate_assets.py`
- Output PNGs: `Dragon/images/generated/` (git-ignored via `Dragon/images/`)
- Output SVGs: `Dragon/images/generated/svg/`
- Python 3.13 required: `& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" generate_assets.py ...`
- Required packages (already installed): `replicate`, `google-genai`, `vtracer`, `requests`

### Credentials (from `deepagents-quickstarts/.env`)
```
GOOGLE_API_KEY       = AIzaSyDLPeUApoUZtV-FZqyfRxRrWgSU1mmr0
GOOGLE_CLOUD_PROJECT = crafty-hook-483415S
REPLICATE_API_TOKEN  = r8_dfczPIyQHnBt8VjcA3BsWgCLwbzLciI0AdZer
```
These are hardcoded in the script — no `.env` loading needed.

### Auth Flow (automatic)
1. **Vertex AI (ADC)** — probed first via `gcloud auth application-default`. Currently fails (`CONSUMER_INVALID` — `aiplatform.googleapis.com` not enabled on `crafty-hook-483415S`). Fails silently.
2. **Replicate/Flux Schnell** — automatic fallback. Always works. Model: `black-forest-labs/flux-schnell`, 4 inference steps, PNG output.

**Never try to fix Vertex AI** — Replicate produces high-quality results and is already working. Leave the silent fallback in place.

### CLI Usage
```bash
cd Dragon

# Generate by category (fires all prompts in that category):
python generate_assets.py claw              # ball-and-claw furniture foot concepts
python generate_assets.py scales            # dragon scale texture tiles
python generate_assets.py damascus          # damascus steel ball surface patterns
python generate_assets.py knob              # dragon pull knob designs
python generate_assets.py box               # full box panel layouts
python generate_assets.py claw_3d           # 3D render-style reference for CadQuery

# Custom prompt:
python generate_assets.py --prompt "Gothic dragon claw grasping a sphere, 3D render"

# Control count and aspect:
python generate_assets.py scales --count 4 --aspect 1:1

# Trace PNG → SVG after generation:
python generate_assets.py scales --svg --colormode binary

# Trace a specific existing PNG:
python generate_assets.py --trace images/generated/FILENAME.png

# Browse gallery:
python generate_assets.py --browse

# List all generated files:
python generate_assets.py --list
```

### Categories
| Category | Purpose | Use in CAD |
|----------|---------|-----------|
| `claw` | Ball-and-claw furniture foot variations — side view, 3/4 view | Shape reference for `06_claw_feet.py` |
| `scales` | Dragon scale tile patterns — B&W high contrast | SVG trace → emboss on drawer front / box sides |
| `damascus` | Damascus steel swirl patterns | SVG trace → emboss on ball surface of claw foot |
| `knob` | Dragon head pull knob art | Shape reference for `04_dragon_knob` |
| `box` | Full jewellery box panel layouts | Compositional reference |
| `claw_3d` | 3D render / orthographic reference — specifically for CadQuery modelling | Geometry proportions, knuckle detail |

### Adding New Prompts
Add entries to the `PROMPTS` dict in the script. Key rules for best Flux Schnell results:
- Include "isolated on white background" or "black background" for clean SVG tracing
- Use "side view" or "front view" for reference images (not perspective)
- Include "high contrast" for usable SVG traces
- Include "3D render" or "clay render" when you want geometry reference rather than illustration

### SVG Tracing for CadQuery/build123d
```python
import vtracer
vtracer.convert_image_to_svg_py(
    str(png_path), str(svg_path),
    colormode="binary",     # B&W silhouette — best for relief extrusion
    filter_speckle=8,       # removes noise
    corner_threshold=60,
)
# Then import in build123d with:
# import_svg_as_buildline(str(svg_path))  # or use svgpathtools
```

### Reference Images
- `Dragon/images/A clean vector-style.png` — the target aesthetic (1024×1536, baroque ball-and-claw, gold acanthus ankle, metallic sphere, black background)
- `Dragon/images/Dragon SVG/Dragon-105.svg` — dragon shape for drawer knob
- `Dragon/images/Dragon SVG/Dragon-106.svg` — dragon shape for lid + claw foot reference
- `Dragon/images/generated/` — all Flux-generated PNGs (not tracked in git)

### Passing SVGs as Image References to Flux
Flux Schnell (the free fast model) does NOT accept image inputs — text-only. To use a reference image:
1. Use `black-forest-labs/flux-dev` (slower, paid) or `stability-ai/stable-diffusion-3` via Replicate — both accept `image` parameter
2. Or describe the SVG's key features in the prompt text ("four curved talons, segmented knuckles, baroque ankle scroll")
3. The `claw_3d` category prompts are written to describe Dragon-106's specific claw anatomy

---

## Amazon Link Fetching Protocol

When the user asks for Amazon purchase links, follow this exact procedure. Amazon blocks simple `urllib` / `Invoke-WebRequest` calls with CAPTCHAs unless the request looks like a real browser.

### Step 1 — Write a Temporary Python Fetch Script

Create `_fetch_amazon.py` in `DragonJewelryBox/`. Use **Python `urllib.request`** (no pip installs required) with a realistic Chrome User-Agent:

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

### Step 2 — Two-Phase Retrieval (Search → Product Pages)

Amazon search results contain ASINs but **not** readable titles (CAPTCHA-gated HTML). The working approach:

1. **Search phase**: Call `fetch_search("51100 thrust bearing 10x24x9mm")` to extract `data-asin` attributes. This reliably returns 8-10 ASINs even with a CAPTCHA warning in the HTML, because Amazon still renders the product grid.
2. **Product phase**: For the top 5 ASINs, call `fetch_product(asin)` to hit each `/dp/ASIN` page individually. These product pages return the full `<title>` tag with the product name. Add `time.sleep(0.8)` between requests to avoid rate limiting.
3. **Price extraction** often fails (Amazon lazy-loads prices via JS). Report `"N/A"` — the user will see the price when they click through.

### Step 3 — Output Format

Print results as a table the user can scan:

```
SHOPPING LIST:

  ITEM CATEGORY:
    PRICE  Product Title (truncated to 80 chars)
           https://www.amazon.com/dp/BXXXXXXXXX
```

Always include **clickable search URLs** at the bottom as fallback:
```
https://www.amazon.com/s?k=search+terms+here
```

### Step 4 — Present to User in Chat

Format the final answer as a **Markdown table** with clickable links. Include:
- Product name
- Pack quantity (important for bearings/hardware — user needs specific count)
- Direct link
- A note if any result is the wrong size (e.g., 6mm collar in 8mm search results)
- The search URL so the user can browse alternatives

### Key Gotchas

- **Do NOT use `Invoke-WebRequest` in PowerShell** via Desktop Commander `start_process` — the `$` variables in PowerShell commands get stripped by the MCP tool's argument parser, causing syntax errors. Always use a Python script.
- **Do NOT use Desktop Commander's `read_file` with `isUrl=true`** for Amazon — it sends a bare request with no User-Agent and gets HTTP 503.
- **Run the script with Python 3.13**: `& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" _fetch_amazon.py`
- **Delete `_fetch_amazon.py`** after use — it's a throwaway helper, not part of the project.
- **Amazon CAPTCHA**: The search HTML may contain "robot" or "captcha" strings but still includes `data-asin` attributes. Don't abort on CAPTCHA warnings — extract ASINs anyway.
- **404 on some ASINs**: Some guessed/old ASINs return 404. Always prefer ASINs discovered from the live search, not hardcoded ones.

---

## build123d — Algebra Mode Reference

Comprehensive patterns for build123d 0.10.0 (Python 3.13). Used in `PhoneCase/poco_x6_pro_case_b3d.py` and any new parts requiring SVG import, sweep, loft, or worm gears.

### Two Modes — Always Use Algebra Mode in This Codebase

- **Builder mode**: `with BuildPart() as p:` context manager. Objects are implicitly added to the active context. Sequential, UI-like.
- **Algebra mode**: Direct Python expressions using `+`/`-`/`&` operators. No context stack. Explicit, composable, function-friendly.

**In this codebase: always algebra mode.** Builder mode requires every shape-creating call to be inside the `with` block, which breaks function-based design. The `b3d_to_cq` bridge and `export_combined_3mf` expect `Part` objects, not `BuildPart` instances.

### Boolean Operations (algebra mode)

```python
result = shape_a + shape_b       # fuse / union
result = shape_a - shape_b       # cut / subtract
result = shape_a & shape_b       # intersect
result += [list_of_shapes]       # vectorized fuse (ALL at once — more efficient)
result -= [list_of_shapes]       # vectorized cut
```

### Core Operations Quick Reference

**Extrude:**
```python
part = extrude(sketch_or_face, amount=10.0)         # +normal direction
part = extrude(sketch_or_face, amount=-10.0)         # -normal direction
part = extrude(sketch_or_face, amount=10.0, both=True)   # symmetric
part = extrude(sketch_or_face, amount=10.0, taper=5)     # 5° draft angle
part = extrude(sketch_or_face, until=Until.NEXT, target=existing)  # up-to-face
```

**Revolve:**
```python
part = revolve(profile, axis=Axis.Z)
part = revolve(profile, axis=Axis.Z, revolution_arc=180)   # half revolve
# CRITICAL: sketch must be entirely on ONE side of the axis.
# Use split(sketch, bisect_by=Plane.ZY) first to force this.
```

**Sweep:**
```python
# Build path from chained segments
l1 = JernArc(start=(0, 0), tangent=(0, 1), radius=40, arc_size=180)
l2 = JernArc(start=l1 @ 1, tangent=l1 % 1, radius=40, arc_size=-90)
l3 = Line(l2 @ 1, l2 @ 1 + (-40, 40))
path = Curve() + [l1, l2, l3]    # FAST: single OCC op vs l1+l2+l3

profile = Plane.XZ * Rectangle(w, h)   # face on a plane perpendicular to path
part = sweep(profile, path=path)
```

**Loft:**
```python
plane1 = Plane(solid.faces().sort_by().last)
faces_to_loft = Sketch() + [
    plane1 * Circle(r1),
    plane1.offset(height) * Rectangle(w, h),
]
part = loft(faces_to_loft)
# Input faces MUST be parallel to each other — unpredictable otherwise
```

**Shell / offset to thin walls:**
```python
topf = solid.faces().sort_by(Axis.Z).last
result = offset(solid, amount=-wall_thickness, openings=topf)
# Always specify openings= — without it, you get a sealed hollow
# Fails on self-intersecting geometry — apply fillets BEFORE offset
```

**Mirror:**
```python
result = solid + mirror(solid, Plane.YZ)
result = solid + mirror(solid, Plane(some_face))
# mirror does not fuse automatically — use + to combine
```

**Split:**
```python
result = split(solid, bisect_by=Plane.XY)              # keeps +Z half
result = split(solid, bisect_by=Plane.XY.offset(z))    # offset cut plane
result = split(solid, bisect_by=Plane.XY, keep=Keep.BOTH)  # both halves
```

**Fillet / Chamfer:**
```python
result = fillet(solid.edges().filter_by(Axis.Z), radius=r)
result = chamfer(solid.edges().group_by(Axis.Z)[-1], length=d)
# Rule: ALWAYS do fillet/chamfer LAST, after all booleans.
# Doing booleans on filleted geometry frequently fails OCC.
```

### Selectors

```python
# Edges
all_edges  = solid.edges()
z_sorted   = solid.edges().sort_by(Axis.Z)       # ShapeList, lowest first
top_edge   = solid.edges().sort_by(Axis.Z).last  # single shape
bot_edge   = solid.edges().sort_by(Axis.Z).first
top_group  = solid.edges().group_by(Axis.Z)[-1]  # list of all edges at max Z
bot_group  = solid.edges().group_by(Axis.Z)[0]
vert_edges = solid.edges().filter_by(Axis.Z)     # edges parallel to Z axis

# Faces
top_face   = solid.faces().sort_by(Axis.Z).last
bot_face   = solid.faces().sort_by(Axis.Z).first
plane      = Plane(top_face)                     # face → workplane

# "Select Last" pattern (what changed after an operation)
snapshot   = solid.edges()
solid     -= Hole(r, depth=d)
new_edges  = solid.edges() - snapshot           # set subtraction
```

### Locations / Workplanes

```python
# Face → Plane → offset / rotate
plane = Plane(solid.faces().sort_by(Axis.Z).last)
offset_plane = plane.offset(distance)
rotated_plane = Plane.XZ * Rot(0, 50, 0)        # post-multiply to rotate plane

# Place sketch ON a plane
sketch = plane * Rectangle(w, h)
sketch = plane * Pos(x, y) * Circle(r)          # plane first, then local translate

# Multi-location patterns
circles = [loc * Circle(r) for loc in GridLocations(xs, ys, nx, ny)]
circles = [loc * Circle(r) for loc in PolarLocations(radius, count)]
solid  -= extrude([plane * loc * Circle(r) for loc in GridLocations(xs, ys, 2, 2)], -d)

# Pos / Rot shortcuts (algebra mode)
at_pos  = Pos(x, y) * Rectangle(w, h)
rotated = Rot(Z=45) * RegularPolygon(r, 6)
```

### `@`, `%`, `^` Path Operators

These three operators work on any `Edge`, `Wire`, or `Curve` and parameterize the shape by `t ∈ [0.0, 1.0]`:

| Operator | Method | Returns | Use |
|----------|--------|---------|-----|
| `shape @ t` | `position_at(t)` | `Vector` | Point on curve at parameter t |
| `shape % t` | `tangent_at(t)` | `Vector` | Tangent direction at parameter t |
| `shape ^ t` | `location_at(t)` | `Location` | Full Location (pos + orient) at t |

```python
# Chain path segments without repeating coordinates:
l1 = Spline([(55, 30), (50, 35), (40, 30), (30, 20), (10, 20), (0, 20)])
l2 = Line(l1 @ 1, (60, 0))    # start from end of l1
l3 = Line(l2 @ 1, (0, 0))
l4 = Line(l3 @ 1, l1 @ 1)     # close back to start of l1

# Sweep along curved path — place profile perpendicular to path at each point:
loc_mid = path ^ 0.5           # Location at midpoint with path's orientation
profile = loc_mid * Rectangle(w, h)
```

### Performance: Algebra Mode Vectorization

`Curve() + [l1, l2, l3, l4]` is **much faster** than `l1 + l2 + l3 + l4` — the former builds the compound in a single OCCT operation; the latter does N individual operations.

```python
# SLOW — N separate OCC calls:
path = l1 + l2 + l3 + l4

# FAST — single OCC call:
path = Curve() + [l1, l2, l3, l4]

# Same for sketch unions:
sk = Circle(r) + [loc * Rectangle(a, b) for loc in locs]   # fast vectorized
```

### `import_svg` — Full API and Return Type

```python
# Signature:
import_svg(
    svg_file,           # str | Path | TextIO
    flip_y=True,        # compensate for SVG Y-axis (True = flip, almost always wanted)
    align=Align.MIN,    # alignment of SVG viewbox: Align.MIN, CENTER, MAX, or None
    ignore_visibility=False,
    label_by='id',      # XML attribute to use as shape.label
) -> ShapeList[Wire | Face]
```

**Return type depends on SVG content:**
- Closed paths with fill → `Face` objects (filigree SVGs, dragon SVGs, most Inkscape exports)
- Open paths / strokes only → `Wire` objects

For the SVGs in this repo (all from `Dragon/images/` and `LaserFiles/`), `import_svg` always returns `Face`. If mixing SVG types, use `isinstance(shape, Face)`.

**Do NOT:** check `shape.is_closed`, call `make_face()`, or check `Wire` properties — this causes silent `AttributeError` → fallback in try/except → no output.

**Full correct pattern (already in 03_lid.py and 04_dragon_knob.py):**
```python
from build123d import import_svg, extrude, Location, Face

faces = import_svg(svg_path)
all_v = [v for f in faces for v in f.vertices()]
xs = [v.X for v in all_v]; ys = [v.Y for v in all_v]
svg_w = max(xs) - min(xs) or 1.0
svg_h = max(ys) - min(ys) or 1.0
sc   = min(target_w / svg_w, target_h / svg_h)
cx   = (max(xs) + min(xs)) / 2.0
cy   = (max(ys) + min(ys)) / 2.0

result = base_part
for face in faces:
    f   = face.move(Location((-cx, -cy, 0))).scale(sc).move(Location((0, 0, z_offset)))
    seg = extrude(f, amount=relief_depth)
    result = result.fuse(seg)
```

**Rotation recipe for pull knob (dragon facing +Y):**
```python
seg = extrude(f, amount=PULL_BODY_D)            # extrudes in +Z (face lies in XY)
seg = seg.rotate(Axis.X, -90)                   # maps +Z → +Y: dragon now faces viewer
seg = seg.move(Location((0, PULL_BASE_T / 2, 0)))  # translate to front face
```

**`import_svg_as_buildline_code`** — alternative that generates executable BuildLine Python code from SVG paths. Returns `(code_str, builder_name)`. Use when you want editable curves rather than extruded faces.

### Common OCC Failure Modes in build123d

1. **Boolean on filleted solid** — Do ALL fillets/chamfers AFTER all booleans. Performing booleans on filleted geometry regularly fails OCCT.
2. **`offset()` on self-intersecting sketch** — Offset breaks. Simplify SVG paths in Inkscape (Path → Simplify, target 50–100 nodes per path) first.
3. **Loft with non-parallel input faces** — Results unpredictable. All loft profiles must be parallel planes.
4. **Revolve with sketch on both sides of axis** — Must split first: `sk = Plane.XZ * split(sk, bisect_by=Plane.ZY)` then `revolve(sk, Axis.Z)`.
5. **`extrude(both=True)` with `amount` sign** — `both=True` extrudes symmetrically regardless of sign. Use positive amount with `both=True`.
6. **`Place sketch on face` direction confusion** — Positive `amount` = outward from face normal. Check `Plane(face).normal` before assuming direction.

### When to Use build123d vs CadQuery in This Repo

| Use build123d for | Use CadQuery for |
|-------------------|-----------------|
| Phone case (`poco_x6_pro_case_b3d.py`) | All DragonJewelryBox parts (01–06) |
| SVG import → relief extrusion | AxisMounts STEP → 3MF pipeline |
| Complex sweep paths (chained arcs + @/%) | Parts already in CadQuery |
| Worm gears, involute profiles | 3MF export (`export_combined_3mf`) |
| New parts needing loft/shell/offset | Revolve (CadQuery axis convention is stable) |

**Bridge:** `b3d_to_cq(part)` in `utils.py` — zero-copy via shared OCCT kernel. Always use this when a build123d `Part` needs to go through the 3MF export pipeline.

```python
import cadquery as cq
def b3d_to_cq(part):
    return cq.Workplane().newObject([cq.Shape.cast(part.wrapped)])
```

---

## POCO X6 Pro 5G Elvish Phone Case

Script: `PhoneCase/poco_x6_pro_case_b3d.py` (**build123d**, not CadQuery — port from earlier CadQuery prototype)

### Coordinate System (critical — revisit every session)

- **Z=0** = exterior back face (print bed face). **Z<0** = outward away from phone. **Z>0** = inward into phone pocket.
- **+X in model** = LEFT when looking at exterior back. **−X** = exterior RIGHT.
- **+Y** = phone top (no mirroring). QIDIStudio shows the interior face (X is mirrored vs exterior back view).
- Camera apertures, camera slab, worm medallion — all use Z<0 offsets to protrude outward.

### Camera Trough Design

- **Camera slab**: `CAM_BOX_D=5mm` protrudes from Z=0 to Z=−5mm. Full case width × 60mm tall.
- **3-sided raised lip trough**: top lip, bottom lip, **right endcap (model +X)**. Model **−X side is OPEN** for slider entry from exterior right.
- **Top cover bridge**: thin overhang off inner face of top lip, runs from +X endcap toward −X leaving `FIN_ENTRY_SLOT=8mm` gap at the −X entry end. Prevents slider from lifting out.
- **Track grooves**: T-slot profiles cut into inner face of top and bottom lips. Slider fins ride in these grooves.
- **Exit slot**: cut through the model **−X case wall** (exterior right side). Extrude direction = negative (into wall).

### Retention Arrow Fins

Located at model **+X end** of slider (far left when looking at back). Protrude +Y from slider top surface.
- **+X face**: 45° chamfer — cams past the top cover bridge on insertion.
- **−X face**: square catch — locks against bridge edge when pulling slider out.
- `FIN_ENTRY_SLOT=8mm` in the bridge at the −X entry end allows the fins to start under the bridge as the slider is pushed in.
- PETG slider has slight flex at `_FIN_RET_T=1.5mm` fin thickness — enough for snap-fit action.

### Lens Position (caliper-derived 2026-02-21)

All four lenses R=7.0mm. From OUTER_W/2=39.57mm exterior left edge:
- `CAM_MAIN_X=+22.1` / `CAM_ULTRA_X=+2.1` (left & right columns)
- `CAM_MAIN_Y=+12.2` / `CAM_MACRO_Y=−7.8` (from island centre, top & bottom rows)

### Screw Positions

Top screws moved to `_sy_top = CAM_BOX_CY − CAM_BOX_H/2 − 9.0` = just below camera island bottom. Camera trough covers the original top corner positions — never put screws under the camera box footprint.

### Worm Drive Mechanism (IMPLEMENTED)

8-start M0.5 worm + 20T worm wheel driving an X-direction camera shutter via rack-and-pinion. Thumb slider (Y-direction) actuates the worm shaft. Self-locking: shutter stays put when not driven. All parts in `poco_x6_pro_case_b3d.py`.

- `WD_WORM_STARTS=8`, `WD_MOD=0.5`, `WD_WORM_L=14mm`, `WD_WHEEL_OD=11.1mm`, `WD_WHEEL_THK=3.0mm`
- D-shaft: `WD_SHAFT_D=3mm`, MR63ZZ bearings (`BRG_ID=3, BRG_OD=6, BRG_W=2.5mm`)
- T-junction housing at `(_T_WW_CX, _T_WW_CY)` = worm wheel centre on back face
- North slider: Y-travel `NS_CHAN_H - NS_SLIDER_H ≈ 44mm`. East shutter: X-travel `SH_RACK_T × RACK_PITCH ≈ 44mm`

### Build123d Context Manager Rule

**Never put `extrude()` calls inside nested helper functions.** build123d uses a thread-local context stack. When a helper function contains `with BuildSketch(): ... Rectangle(...)` and then calls `extrude()`, the sketch context has already exited by the time `extrude()` fires — even if the helper is called from inside `with BuildPart()`. Error: `ValueError: A face or sketch must be provided`.

**Fix**: Inline every `with Locations(): with BuildSketch(): ... extrude()` block directly inside the `with BuildPart() as p:` body. Use loops and lists to avoid repetition, not nested function calls.

### build123d import_svg API — Correct Usage

`import_svg(path)` in build123d 0.10+ returns a **`ShapeList` of `Face` objects**, NOT `Wire` objects. Many examples online (and previous versions) show a Wire-based approach with `make_face()` — this is **wrong for 0.10+** and causes silent fallback.

**Do NOT do this (wrong in 0.10+):**
```python
wires = import_svg(path)
for w in wires:
    if not w.is_closed: continue   # AttributeError: Face has no is_closed
    face = make_face(w)            # unnecessary: already a Face
    seg = extrude(face, amount=d)
```

**Correct pattern:**
```python
from build123d import import_svg, extrude, Location

faces = import_svg(path)           # ShapeList of Face objects
all_v = [v for f in faces for v in f.vertices()]
xs  = [v.X for v in all_v]; ys = [v.Y for v in all_v]
svg_w = max(xs) - min(xs) or 1.0
svg_h = max(ys) - min(ys) or 1.0
sc   = min(target_w / svg_w, target_h / svg_h)
cx   = (max(xs) + min(xs)) / 2.0
cy   = (max(ys) + min(ys)) / 2.0

for face in faces:
    f   = face.move(Location((-cx, -cy, 0))).scale(sc).move(Location((0, 0, z_offset)))
    seg = extrude(f, amount=relief_depth)   # full Bezier curve fidelity
    result = result.fuse(seg)
```

**SVG plane orientation for drawer pull (faces +Y):** Import faces lie in XY. To make the dragon face +Y (toward viewer), extrude in Z then rotate the *solid* −90° about X, then translate to the front face:
```python
seg = extrude(f, amount=PULL_BODY_D)
seg = seg.rotate(Axis.X, -90).move(Location((0, PULL_BASE_T / 2, 0)))
```
`rotate(Axis.X, −90)` maps Z→+Y: the extruded solid now protrudes toward the viewer.

**Performance trade-offs vs svgpathtools polyline approach:**

| Approach | Lid (184mm) | Pull (34mm) | Fidelity |
|----------|-------------|-------------|----------|
| svgpathtools (80-seg polylines) | 7s, 53K verts | 1s, 2K verts | ≈Bezier |
| build123d import_svg (native Bezier) | 162s, 68K verts | 20s, 204K verts | exact |

The pull at 204K verts on a 34mm part is over-resolved for a 0.4mm nozzle (~0.25mm min feature). If QIDIStudio slicing is slow, consider pre-simplifying the SVG in Inkscape (Path → Simplify) before importing, targeting ~50–100 nodes per path.

**Note on `@` and `%` operators:** build123d edges/wires support `wire @ 0.5` (point at parameter t=0.5) and `wire % 0.5` (tangent vector). Useful for sweep-along-path operations (e.g., talon shape swept along an arc wire), but not needed for SVG relief extrusion.

### 3MF Export for build123d Parts (OCC Bridge)

build123d `Part` objects cannot be passed directly to `export_combined_3mf` (which uses CadQuery internals). Bridge them via the shared OCCT kernel:

```python
import cadquery as cq

def b3d_to_cq(part):
    """Wrap a build123d Part as a CadQuery Workplane — no file I/O, shared OCC."""
    return cq.Workplane().newObject([cq.Shape.cast(part.wrapped)])
```

This works because both libraries use the same `TopoDS_Shape` OCCT objects at the bottom. `part.wrapped` is the raw `TopoDS_Compound`; `cq.Shape.cast()` boxes it for CadQuery. Then pass to `export_combined_3mf` as normal `(cq_shape, name)` pairs.

The phone case exports 4 3MF files:
- `PhoneCase/STL/elvish_case_shell.3mf` — back_shell + front_frame + screw_caps (ASA-GF grey)
- `PhoneCase/STL/elvish_embellishments.3mf` — gold inlay layer (pause at Z=0.8mm to swap filament)
- `PhoneCase/STL/elvish_tpu_inner.3mf` — 85A TPU liner
- `PhoneCase/STL/elvish_mechanism.3mf` — worm + worm_wheel + north_slider + east_shutter (ASA-GF max strength)

### Key Constants

```python
# Case shell
OUTER_W = 79.14;  OUTER_L = 165.25;  SHELL_Z = 13.65
BACK_T = 2.0;  WALL_T = 2.0;  LIP_T = 2.0
PHONE_Y_OFFSET = -80.225   # = -OUTER_L/2 + WALL_T + CLEARANCE

# Camera trough
CAM_BOX_D = 5.0;  CAM_BOX_H = 60.0;  CAM_BOX_CY = 51.625
CAM_LIP_WALL = 4.0;  CAM_LIP_H = 3.5

# East shutter (X-direction camera cover)
SLIDER_T = 3.0    # thickness (fits inside lip trough with 0.5mm clearance)
SLIDER_H = CAM_BOX_H - 2*CAM_LIP_WALL - 0.5   # ≈ 51.5mm

# Worm drive
WD_WORM_STARTS = 8;  WD_MOD = 0.5;  WD_WORM_L = 14.0
WD_WHEEL_OD = 11.1;  WD_WHEEL_THK = 3.0;  WD_SHAFT_D = 3.0
BRG_ID = 3;  BRG_OD = 6;  BRG_W = 2.5
RACK_PITCH = math.pi * WD_MOD   # ≈ 1.571mm
SH_RACK_T = 28   # rack teeth on east shutter

# North slider (Y-direction thumb driver)
NS_CHAN_H = 50.0;  NS_SLIDER_H = 14.0   # 36mm travel

# Embellishments
INLAY_DEPTH = 1.2;  INLAY_LINE_W = 1.8;  INLAY_STAR_W = 1.6
```

---

## GCode Refiner — Feature-Aware Post-Processor

**Location**: `c:\Users\User\source\repos\3DPrinting\GCodeRefiner\`
**Research doc**: `GCodeRefiner/gcode_research.md`
**Status**: v1.0.0 — M2 gear rules + ASA-GF 0.4mm profile implemented

A standalone Python post-processor that parses 3D printing GCode, detects feature types
from slicer comment markers (`; TYPE:OUTER_WALL` etc.), and injects optimized parameters
(temperature, fan, speed, acceleration) per feature type and filament profile.

No existing tool does this end-to-end. See `gcode_research.md` for full survey.

### File Structure

```
GCodeRefiner/
  refiner.py               — main entry point (also works as QIDISlicer post-processing script)
  profiles/
    asa_gf_04mm.py         — ASA-GF + 0.4mm hardened steel nozzle base envelope
  rules/
    m2_gear.py             — M2 module gear optimization rules
  gcode_research.md        — full research: existing tools, architecture, optimization data
  README.md                — usage instructions
```

### Integration as QIDISlicer Post-Processing Script

Add to Print Settings → Output Options → Post-processing scripts:
```
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\User\source\repos\3DPrinting\GCodeRefiner\refiner.py" --rules m2_gear --verbose
```
QIDISlicer appends the gcode file path automatically as the last argument.

### CLI Usage

```powershell
# Process gcode file in-place
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py input.gcode --rules m2_gear

# Dry run (shows what would be injected, no file changes)
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py input.gcode --rules m2_gear --dry-run --verbose

# List available profiles/rules
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py --list-profiles
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py --list-rules
```

### Architecture

```
input.gcode → detect feature type (;TYPE: comments) → lookup override in rules/*.py
            → inject M104/M106/M204/F per feature transition → output.gcode (in-place)
```

No GcodeTools dependency for core operation — uses raw slicer comment parsing which
is stable across slicer versions. GcodeTools (`pip install GcodeTools`) enhances with
flow-rate analysis.

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

Key parameters vs stock QIDIStudio settings:
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
- CMake 3.29.8 → `C:\CMake329\bin\cmake.exe` (**use this, not the winget cmake 4.x — see gotcha below**)
- CMake 4.2.3 winget install → `C:\Program Files\CMake\bin\cmake.EXE` (do NOT use for QIDIStudio, only useful for `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` check)
- Strawberry Perl 5.42.0.1 → `C:\Strawberry\perl\bin\perl.EXE`
- Ninja 1.13.2 (installed but not used — VS generator preferred)
- VS 2022 Community v17.14 → MSBuild at `C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe`
- pkg-config-lite 0.28 → installed via `winget install bloodrock.pkg-config-lite`, at `C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\bloodrock.pkg-config-lite_Microsoft.Winget.Source_8wekyb3d8bbwe\pkg-config-lite-0.28-1\bin\pkg-config.exe`

### Critical Build Gotchas

**CMake 4.x policy break** — CMake 4.x removed backward compat with `cmake_minimum_required < 3.5`. Without the fix, every cmake configure fails immediately with `Compatibility with CMake < 3.5 has been removed`. Fix: add `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` to BOTH deps and app cmake configure commands. Alternatively, just use **cmake 3.29.8** (at `C:\CMake329\bin\cmake.exe`) — it avoids this issue entirely.

**pkg-config not found on Windows** — `src/slic3r/CMakeLists.txt` calls `pkg_check_modules(LIBAV REQUIRED ...)` which is NOT guarded by `if(NOT WIN32)`. cmake configure fails with "pkg-config tool not found". Fix: install `bloodrock.pkg-config-lite` via winget, then pass to cmake:
```
-DPKG_CONFIG_EXECUTABLE=C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\bloodrock.pkg-config-lite_...\bin\pkg-config.exe
```
And set environment: `PKG_CONFIG_PATH=C:\QIDIDeps\usr\local\lib\pkgconfig`. The `.pc` files are at that path after deps build.

**`QIDI/QIDINetwork.cpp` cmake bug — cmake `if(VAR)` policy trap** — This is GitHub issue #120/#126, a RECURRING bug across many QIDIStudio releases. Root cause: cmake's `if(QDT_RELEASE_TO_PUBLIC)` with an **undefined** variable evaluates to **TRUE** in some cmake policy contexts because the unquoted arg `"QDT_RELEASE_TO_PUBLIC"` is treated as a truthy literal string (CMP0012/CMP0054 OLD policy behavior). Since the file `QIDI/QIDINetwork.cpp` doesn't exist in the public source ZIP, configure fails.

**Double fix required** (belt-and-suspenders):
1. **Patch the cmake source** — change `src/slic3r/CMakeLists.txt` line 638:
   - Old: `if(QDT_RELEASE_TO_PUBLIC)` 
   - New: `if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")` — explicit `${}` expansion forces proper variable dereference regardless of cmake policy
2. **Pass explicit zero** — add `-DQDT_RELEASE_TO_PUBLIC=0` to the app cmake configure command. This makes the variable explicitly "0" (a cmake false constant), guaranteeing `if()` is FALSE.

DO NOT pass `-DQDT_RELEASE_TO_PUBLIC=1` — that requires the private cloud-network module files which are not in the public ZIP. Drop the flag entirely (or use `=0`).

**Stale VS project files lock `if(QDT_RELEASE_TO_PUBLIC)` to old value** — If cmake configure runs and creates `.vcxproj`/`.sln` files with certain flags, then those flags are embedded in the project files. On the next cmake run, even if you delete `CMakeCache.txt`, cmake may try to RE-GENERATE using the embedded old command-line (from the previous `.vcxproj`). Fix: **wipe the ENTIRE build directory**, not just CMakeCache.txt.

**Terminal CWD locks the build dir** — `cmd /c rd /s /q` or `shutil.rmtree` on the build dir fails with `[WinError 32] process cannot access the file` if ANY terminal has that directory as its CWD. Fix: run `cd C:\` in ALL open terminals before deleting, then delete with:
```powershell
cmd /c rd /s /q "C:\QIDISrc\QIDIStudio\build"
```
`shutil.rmtree(path, ignore_errors=True)` silently fails when directory is locked — always use `cmd rd /s /q` on Windows build dirs.

**OpenSSL dep fails with MSB8066 exit 9009** — Exit 9009 = "command not found" when OpenSSL's configure step tries to run `perl Configure`. Two causes:
1. CMake wasn't told perl's path explicitly — fix: `-DPERL_EXECUTABLE=C:\Strawberry\perl\bin\perl.exe` in deps cmake configure
2. Parallel MSBuild (`/m:N > 1`) causes ExternalProject race conditions — fix: **always use `/m:1` for deps build**. The app build can use `/m:N` for speed.

**`build_win.bat` targets VS 2019 (v16)** — the bat sets `PS_VERSION_SUPPORTED=16` and `PS_VERSION_EXCEEDED=17`, so it won't find VS 2022 (v17). Don't use `build_win.bat`. Run cmake directly with `-G "Visual Studio 17 2022"`.

**Sequential deps, parallel app** — deps ExternalProject steps are NOT thread-safe; each dep downloads, configures, and compiles internally. Use `/m:1` for deps. App build compiles normal C++ TUs; use `/m:{cpu_count}` there.

### Correct Build Commands (what `_build_qidi.py` does)
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
  -DQDT_RELEASE_TO_PUBLIC=0            # NEVER use =1 (private files not in public ZIP)
  -DCMAKE_PREFIX_PATH=C:\QIDIDeps/usr/local
  -DCMAKE_INSTALL_PREFIX=C:\QIDISrc\QIDIStudio\install_dir
  -DCMAKE_BUILD_TYPE=Release
  -DWIN10SDK_PATH=C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  -DPKG_CONFIG_EXECUTABLE=C:\...\pkg-config.exe

# App build (parallel OK)
cmake --build . --target install --config Release -- /m:16 /v:minimal
```

**Also required — patch `src/slic3r/CMakeLists.txt` before configure**:
```cmake
# Line 638 — change from:
if(QDT_RELEASE_TO_PUBLIC)
# to:
if("${QDT_RELEASE_TO_PUBLIC}" STREQUAL "1")
```

### Expected Timeline
- Deps configure: ~5 min
- Deps build: ~40-60 min (sequential, many deps)
- App configure: ~2 min
- App build + install: ~30-40 min
- **Total: ~90 min on a fast machine**

### Why the Installer Was Broken
The downloaded `QIDIStudio_Setup_02.04.01.11_Win64.exe` returned exit `0xc000007b` (`STATUS_INVALID_IMAGE_FORMAT`) — corrupted EXE, not a missing VC++ runtime issue. All VC++ 2022 x64/x86 runtimes were healthy (confirmed via `_fix_vcpp.py`). Build from source is the correct resolution.

## QIDIStudio — Source Internals & Our Fork

**Fork:** `https://github.com/phantom-man/QIDIStudio` → cloned at `C:\Users\User\source\repos\QIDIStudio\`
**Full knowledge doc:** `C:\Users\User\source\repos\3DPrinting\QIDIStudio_KNOWLEDGE.md` (also in fork at `docs/QIDISTUDIO_KNOWLEDGE.md`)

### Mode System (Simple / Advanced / Developer)

QIDIStudio has 3 UI complexity modes. The **upstream QIDI source has all 3 buttons commented out** — no mode switcher appears in the UI at all. Our fork restores them.

**Enum** (`src/libslic3r/Config.hpp:203-207`):
```cpp
enum ConfigOptionMode {
    comSimple = 0,   // "simple"
    comAdvanced,     // "advanced"
    comDevelop       // "develop"  ← what QIDI docs call "Expert Mode"
};
```

**Our fix** (`src/slic3r/GUI/wxExtensions.cpp:1048`):
```cpp
// All 3 buttons restored; Developer added:
std::vector < std::pair < wxString, std::string >> buttons = {
    {_(L("Simple")),    "mode_simple"},
    {_CTX(L_CONTEXT("Advanced", "Mode"), "Mode"), "mode_advanced"},
    {_(L("Developer")), "mode_develop"},
};
```

**First-run default changed** (`src/slic3r/GUI/MainFrame.cpp:197`) — was `"simple"` + `false`; now `"develop"` + `true`.

**Config keys** (in `C:\Users\<user>\AppData\Roaming\QIDIStudio\QIDIStudio.conf`):
- `user_mode` → `"simple"`, `"advanced"`, or `"develop"`
- `developer_mode` → `"true"` / `"false"` (boolean flag, separate from user_mode)
- `internal_developer_mode` → force-reset to `false` on EVERY startup (can't persist)
- `iot_environment` → `"0"`=DEV, `"1"`=QA, `"2"`=PRE, `"3"`=PRODUCT

**To force Developer mode without rebuild** — edit `QIDIStudio.conf` directly:
```json
{ "user_mode": "develop", "developer_mode": "true", "iot_environment": "3" }
```

### `iot_environment` Default Bug (patched in our fork)
Upstream `AppConfig.cpp` `#else` branch defaults `iot_environment` to `"2"` (PRE/staging) when `QDT_RELEASE_TO_PUBLIC=0`. Our fork changes it to `"3"` (production).

### `qidi_networking.dll` — Missing Closed-Source Module
This DLL is QIDI's private networking module, not in the public source. Without it:
- Host Setting dialog cannot save
- Device binding / cloud pairing fail
- Log shows `load dll failed`

LAN printing via Moonraker REST API (`http://192.168.0.116:7125/`) still works fine.

### Windows Registration Script
After building, run `C:\Users\User\Downloads\_register_qidi.ps1` to create Start Menu shortcut, App Paths registry entry, and Add/Remove Programs entry.

### PowerShell Terminal Command Syntax for QIDIStudio Builds
`&&` is NOT valid PowerShell directory-change syntax. Always use semicolons:
```powershell
# WRONG (parse error):
cd C:\QIDISrc\QIDIStudio\build && cmake --build .

# CORRECT:
Set-Location C:\QIDISrc\QIDIStudio\build; & "C:\CMake329\bin\cmake.exe" --build . ...
```

### `terminal-tools_sendCommand` with `captureOutput:true` is Non-Blocking
`captureOutput:true` returns immediately (0ms) without waiting for the command to finish. Never use it for long-running processes — use `captureOutput:false` (default) and poll an output file instead.

---

## Python Environments — This Repo

Three Python environments in `C:\Users\User\source\repos\QIDIStudio\`:

| Env | Python | Purpose | Activate |
|-----|--------|---------|----------|
| `.venv` | 3.13 | General scripts: trimesh, pyvista, AI image gen, GCodeRefiner | `.venv\Scripts\python.exe` |
| `bpy_env` | 3.11 | Blender headless (bpy pip package) — displacement texturing | `bpy_env\Scripts\python.exe` |
| System Python 3.13 | 3.13 | CadQuery (installed system-wide, NOT in venv) | `C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe` |

**Why bpy requires Python 3.11:** The standalone `bpy` pip package targets Blender 4.x which distributes with Python 3.11. The 3.13 build is not yet available. Never install `bpy` into `.venv` or system Python 3.13 — it will fail at import or install.

**bpy_env location:** `C:\Users\User\source\repos\QIDIStudio\bpy_env\`  
**bpy_env Python executable:** `bpy_env\Scripts\python.exe`

---

## Add Part > Texture / Add Negative Part > Texture — BPY Feature

Right-click menu items that apply a PNG displacement texture to the skin of a selected 3D part using Blender's headless rendering pipeline. Replaces the earlier trimesh `apply_skin.py` approach and the SVG tiling approach — bpy produces dramatically better mesh quality via Blender's Subdivide + Displace workflow.

### Why BPY over trimesh
| | trimesh (`apply_skin.py`) | bpy (`apply_texture_bpy.py`) |
|---|---|---|
| Subdivision | midpoint only, no smoothing | Blender Simple subdivision — preserves hard edges, smoother result |
| Displacement | Python loop per vertex | Blender Displace modifier — GPU-accelerated, seamless UV tiling |
| UV tiling | manual tile_mm math | Empty-object-scaled texture mapping — zero seams |
| Output | 3MF (preserves slicer settings) | STL (C++ reload wraps in 3MF) |
| Mesh quality | 64× vertex limit | Up to 3 subdivision levels (8× per level = 512× original) |

### Script: `resources/scripts/apply_texture_bpy.py`
```
apply_texture_bpy.py  <model_stl>  <skin_asset>
    [--mode part|negative|modifier]   # part=add shell, negative=carved, modifier=replace
    [--tile-size 15]   [--relief 1.0]
    [--invert]         [--gamma 0.7]
    [--log <logfile>]
```
Outputs: `SKIN_OUTPUT: <path>` to stdout + logfile. C++ reads this line to find the result STL.

**Invocation:** `bpy_env\Scripts\python.exe resources\scripts\apply_texture_bpy.py model.stl skin.png --mode modifier --log out.txt`

### Modes
- `modifier` — displaces the original mesh in-place, exports replaced mesh as `<stem>_texture_modifier.stl`
- `part` — duplicates mesh, displaces copy outward, exports as `<stem>_texture_part.stl` (MODEL_PART added to parent)
- `negative` — duplicates mesh, displaces copy outward (flipped), exports as `<stem>_texture_negative.stl` (NEGATIVE_VOLUME carved into parent)

### C++ Wiring (NOT YET IMPLEMENTED — next task)
Needs to be added to `Plater.cpp` + `GUI_Factories.cpp`:
1. **Detect `bpy_env`** — look for `bpy_env\Scripts\python.exe` relative to the QIDIStudio install dir (`resources/` sibling)
2. **`can_apply_texture()`** — returns true when exactly one full-object is selected AND `bpy_env` python exists
3. **`apply_texture_to_selection(mode)`** — file picker for PNG, wxExecute with bpy_env python + script, parse `SKIN_OUTPUT:` from log, redirect `obj->input_file`, call `reload_from_disk()`
4. **`GUI_Factories.cpp`** — add `append_menu_items_add_texture()` to the object right-click menu, wired to `plater()->apply_texture_to_selection(mode)`
5. **Menu items**: `Add Part > Texture...`, `Add Negative Part > Texture...` (same submenu as `Add Part > SVG` and `Add Part > Text`)

### Key bpy API Gotchas
- **`bpy.ops.wm.read_factory_settings(use_empty=True)`** must be called first — Blender initializes with a default cube otherwise
- **Scale length = 0.001** (`scene.unit_settings.scale_length = 0.001`) — 1 Blender unit = 1mm
- **Standalone bpy has no `io_scene_3mf`** — must parse 3MF zip manually (already implemented in `_import_3mf_manual()`)
- **bpy injects args after `--`** — the script strips them: `if "--" in argv: argv = argv[argv.index("--") + 1:]`
- **`mathutils` is bundled** with bpy — import it after `import bpy` succeeds
- **Displace modifier needs an Empty for texture coords** — scaling the Empty to `tile_size` gives seamless world-space tiling without UV seams
- **Output naming** prevents `_texture_modifier_texture_modifier.stl` on re-runs: strips known suffixes before adding them

### Skin Assets
`resources/assets/` — PNG heightmaps generated by `scripts/generate_skin_assets.py`.
Procedural categories (no AI needed): `honeycomb`, `diamond_knurl`, `voronoi_cells`, `chainmail`, `brick_pattern`, `herringbone`, `riveted_metal`.
AI categories via Replicate Flux Schnell: `dragon_scales`, `reptile_scales`, `damascus_steel`, `carbon_fiber`, etc.

---

## Skills — When to Load Which Skill

Skills are in `.agents/skills/`. Load them with `read_file` on demand — don't load all of them blindly. All skill files are SKILL.md inside the named folder.

### C++ / QIDIStudio Core Development
| Trigger | Skill |
|---------|-------|
| Writing or reviewing any C++ code (wxWidgets, OpenGL, Blender API, CMake) | `cpp-pro` |
| Tracking down crashes, wxExecute failures, Python subprocess errors, silent wrong-value bugs | `debugging-wizard` |
| Designing new feature architecture (BPY pipeline, gizmo wiring, C++↔Python bridge, menu system) | `architecture-designer` |
| Reviewing a C++ patch before commit — correctness, safety, style | `code-reviewer` |
| CMake issues, dependency config, build system, CI/CD | `devops-engineer` |
| Refactoring nested conditionals, early returns in C++ | `control-flow` |
| Error handling patterns in C++ or Python | `error-handling` |
| Challenging a design or assumption before a major change | `dissent` |

### Python Scripts
| Trigger | Skill |
|---------|-------|
| Writing or reviewing Python scripts (`apply_texture_bpy.py`, `apply_skin.py`, `generate_skin_assets.py`, GCodeRefiner) | `python-pro` |
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
| `database-optimizer` | If persistent storage is added to companion tools |
| `postgres-pro` | If PostgreSQL-backed companion service is added |
| `sql-pro` | SQL queries in any tooling |
| `csharp-developer` | If C# companion tooling is added |
| `kubernetes-specialist` | Containerized deployment |
| `microservices-architect` | Decomposing monolithic build scripts |
| `mcp-developer` | Building MCP servers for QIDIStudio tooling |
| `fullstack-guardian` | Full-stack companion web UI |