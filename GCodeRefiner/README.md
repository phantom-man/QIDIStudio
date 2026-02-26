# GCode Refiner

Feature-aware GCode post-processor for 3D printing on the Qidi Q2.

Reads a `.gcode` file, detects **feature types** from slicer comment markers
(`; TYPE:OUTER_WALL` etc.), and injects parameter overrides (temperature, fan,
acceleration) optimized for the active filament + nozzle + geometry combination.

---

## Quick Start

### As QIDISlicer Post-Processing Script (recommended)

1. Open QIDIStudio → Printer Settings → Custom G-code → **Post-processing scripts**
2. Add this line:
   ```
   "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\User\source\repos\3DPrinting\GCodeRefiner\refiner.py" --rules m2_gear --verbose
   ```
3. Save to your Q2 0.4 nozzle printer preset (or a process preset per-project)
4. Slice as normal — the refiner runs automatically on every export

QIDISlicer passes the gcode file path as the last argument automatically.
The script modifies the file **in-place** (same path, same filename).

### Standalone CLI

```powershell
# Standard run
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py input.gcode --rules m2_gear --profile asa_gf_04mm

# Dry run (no file changes — shows what would be injected)
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py input.gcode --rules m2_gear --dry-run --verbose

# List available profiles and rules
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py --list-profiles
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" refiner.py --list-rules
```

---

## Installation

```powershell
# Install GcodeTools (required for feature detection)
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" -m pip install GcodeTools

# Verify
& "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" -c "import GcodeTools; print('GcodeTools OK')"
```

> **Note:** The core refiner works without GcodeTools using raw slicer comment
> parsing. GcodeTools is used for advanced flow-rate analysis features.

---

## Available Profiles (`profiles/`)

| File | Filament | Nozzle | Description |
|------|---------|--------|-------------|
| `asa_gf_04mm.py` | ASA-GF (Fibreheart) | 0.4mm hardened steel | Qidi Q2 base envelope |

---

## Available Rule Sets (`rules/`)

| File | Use Case | Key Optimizations |
|------|---------|-------------------|
| `m2_gear.py` | M2 module involute gears | Slow outer walls (20mm/s), fan=0% on perimeters, +5°C tooth surfaces |

---

## What the Refiner Does

For each feature type transition (detected from `; TYPE:...` slicer comments):

1. **Injects temperature command** (`M104`) if the rule overrides nozzle temp
2. **Injects fan command** (`M106`/`M107`) if the rule overrides fan speed
3. **Injects acceleration command** (`M204`) if the rule overrides accel
4. **Modifies `F` parameter** in G1 move lines if the rule overrides print speed

Injection only happens when a value *changes* — no redundant commands.

### Example: M2 Gear Injections

For `; TYPE:OUTER_WALL` (gear tooth surfaces):
```gcode
; TYPE:OUTER_WALL
M104 S275 ; refiner: M2 outer wall: slow + hot + no fan
M107 ; refiner: M2 outer wall: slow + hot + no fan
M204 P1000 ; refiner: M2 outer wall: slow + hot + no fan
G1 X... Y... E... F1200         ; (was F2400, now limited to 20mm/s = 1200mm/min)
```

For `; TYPE:BRIDGE`:
```gcode
; TYPE:BRIDGE
M104 S265 ; refiner: M2 bridge: max fan, under-extrude
M106 S255 ; refiner: M2 bridge: max fan, under-extrude
M204 P1500 ; refiner: M2 bridge: max fan, under-extrude
```

---

## Adding New Rule Sets

Copy `rules/m2_gear.py` to `rules/my_rules.py` and edit the `OVERRIDES` dict.
The only required interface is:

```python
def get_override(move_type: str, layer: int, profile: object) -> dict | None:
    """Return dict with speed_mm_s, nozzle_temp, fan, flow_ratio, accel, comment
    or None to use profile defaults."""
    ...
```

Then use `--rules my_rules` in the CLI or post-processing script entry.

---

## Planned Extensions

- `rules/tr8x2_screw.py` — TR8×2 lead screw threads (slower flanks, 15mm/s outer, 0.10mm layer height advisory)
- `rules/fine_detail.py` — General fine-feature rule (anything requiring sub-0.5mm feature fidelity)
- `rules/structural_asa.py` — Maximum bonding strength (fan=0 everywhere, slow everywhere)
- Flow ratio injection via GcodeTools `block.move.set_flowrate()` once API stabilizes
- pyGCodeDecode integration for velocity simulation pre-analysis pass

---

## Slicer Configuration Notes

### QIDIStudio / OrcaSlicer Feature Labels

Ensure **`Label objects`** is enabled in Printer Settings if you want per-object
feature detection. For plain feature-type detection (speed/temp per feature),
this is not required.

The refiner reads the standard `; TYPE:...` comment markers that QIDIStudio and
OrcaSlicer emit. These are always present regardless of `Label objects` setting.

### Required Slicer Settings for ASA-GF Gears

Set these in the slicer BEFORE the refiner runs (refiner only tunes, not replaces):
- `layer_height`: `0.15` (recommended) or `0.1` for ultra-fine
- `wall_loops`: 4–6 (fills most of M2 tooth cross-section)
- `sparse_infill_density`: 80–100% for structural gears
- `sparse_infill_pattern`: `concentric` (100%-compatible, avoids cubic swap bug)
- `wall_generator`: `arachne` (fills thin tooth tips)
- `detect_thin_wall`: `1`

---

## Research Notes

See [gcode_research.md](gcode_research.md) for full survey of existing tools,
architecture decisions, and M2 gear optimization data.
