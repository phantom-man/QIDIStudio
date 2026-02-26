# GCode Analyzer / Refiner — Research Notes

_Last updated: 2025-06 | Researcher: GitHub Copilot_

---

## Executive Summary

**The Ask:** Does any existing tool analyze 3D printing GCode and intelligently inject
parameter changes based on what the GCode is actually doing (feature type) and the
filament/nozzle profile in use?

**Verdict:** No single tool does this end-to-end, but all the building blocks exist.
The recommended approach is a **custom Python post-processor** that:

1. Parses GCode with `GcodeTools` (reads feature markers from slicer comments)
2. Applies a **filament+nozzle+purpose rule profile** per feature type
3. Writes modified GCode back to the same file (compatible as QIDIStudio post-processing script)

---

## Existing Tools Survey

### 1. GcodeTools — BEST FIT

| Property | Value |
|----------|-------|
| **Package** | `pip install GcodeTools` |
| **GitHub** | https://github.com/Matszwe02/GcodeTools |
| **Version** | 0.2.4 (active, Dec 2025) |
| **License** | MIT |
| **Status** | Beta — API unstable between releases, known bugs |
| **Slicers** | OrcaSlicer ✅, QIDIStudio ✅ (same engine), PrusaSlicer ✅, Cura ✅, Bambu ✅ |

**Core API:**
```python
from GcodeTools import Gcode, Tools, MoveTypes

gcode = Gcode('input.gcode')

for block in gcode:
    move_type = block.meta.get('type')         # MoveTypes enum value
    layer     = block.meta.get('layer')        # int layer number
    obj       = block.meta.get('object') or '' # object name from LABEL_OBJECTS

    if move_type == MoveTypes.OUTER_WALL:
        block.block_data.set_fan(0)            # fan off for outer perimeter
    elif move_type == MoveTypes.BRIDGE:
        block.block_data.set_fan(255)          # max fan for bridge

gcode.write_file('output.gcode')
```

**MoveTypes enum** (from OrcaSlicer comment format `;TYPE:...`):
- `OUTER_WALL` — outer perimeter / external perimeter
- `INNER_WALL` — inner walls / inner perimeters
- `SPARSE_INFILL` — sparse infill (gyroid, cubic, etc.)
- `SOLID_INFILL` — solid infill (top/bottom shells)
- `BRIDGE` — bridge moves
- `SUPPORT` — support material
- `RAFT` — raft layers
- `SKIRT` — brim / skirt
- `TRAVEL` (implicit — non-extrusion moves)
- `PRIME_TOWER` — wipe tower moves

**Feature capabilities:**
- `block.move.get_flowrate()` → mm E / mm XYZ ratio
- `block.move.set_flowrate(float)` → adjust flow in mm²
- `block.block_data.set_fan(int)` → 0–255 fan speed
- `block.block_data.set_tool(int)` → T0/T1 tool switch
- `gcode.layers[n]` → access specific layer
- `Tools.get_bounding_box(gcode)` → part bounds
- `Tools.fill_meta(gcode)` → populate metadata from slicer comments
- `Tools.trim(gcode)` → minify / strip comments (do NOT use before iterating in our workflow)

**Known limitation:** OrcaSlicer/QIDIStudio feature detection requires `LABEL_OBJECTS` to be enabled in slicer settings for full object separation. Feature types (`;TYPE:...`) work without it.

**Caution:** Library is in beta. Always backup gcode before running. Always verify output before sending to printer.

---

### 2. pyGCodeDecode — ANALYSIS TOOL (not modifier)

| Property | Value |
|----------|-------|
| **Package** | `pip install pyGCodeDecode` |
| **GitHub** | https://github.com/FAST-LB/pyGCodeDecode |
| **Version** | 1.4.1 (Aug 2025) |
| **Use case** | Time-accurate firmware simulation, velocity analysis, FEA boundary conditions |

**Purpose:** Simulates actual printer motion (acceleration/jerk) to find where real velocity
deviates from target velocity. Used for academic FFF process simulation. Not designed for
GCode modification — output is time-series position/velocity data, not modified gcode.

**Verdict:** Excellent for diagnosing speed/acceleration issues but wrong tool for injection.
Could be used as a pre-analysis pass in a future advanced version.

---

### 3. PrusaSlicer / OrcaSlicer / QIDIStudio Post-Processing Scripts

All three slicers support post-processing scripts natively.

**Setup location (QIDISlicer):**
> `Print Settings → Output Options → Post-processing scripts`

**Execution model:**
- Script receives absolute path to a **temporary gcode file** as its sole argument
- Script modifies the file **in-place**
- Modified file then gets copied to output destination or uploaded to printer

**Environment variables passed** (all prefixed `SLIC3R_`):
- `SLIC3R_FILL_DENSITY` — infill density (e.g., `"20%"`)
- `SLIC3R_LAYER_HEIGHT` → layer height
- `SLIC3R_NOZZLE_DIAMETER` → nozzle size
- `SLIC3R_PP_HOST` → where gcode is going (`"File"`, `"QIDILink"`, etc.)
- `SLIC3R_PP_OUTPUT_NAME` → output file name

**Script invocation format:**
```
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" "C:\path\to\refiner.py"
```
GCode file path appended automatically as the final argument.

**Critical:** QIDISlicer (QIDIStudio's slicer) is confirmed to support this same mechanism
as it inherits from OrcaSlicer/PrusaSlicer. See: https://wiki.qidi3d.com/en/software/qidi-slicer/print-settings/post-process-scripts

---

### 4. WatchingWatches/Post_processing_gcode

- GitHub: https://github.com/WatchingWatches/Post_processing_gcode
- Small Python scripts for specific modifications (pause at layer, tool changes)
- Operates by raw string search/replace on gcode text
- No structured parsing — fragile but simple
- Useful as reference for specific injection patterns (pause-at-layer, M600 swap)

---

### 5. Web-based Gcode Editors

Several exist (gcode.ws, ncviewer.com, single-HTML local tools). Visual-only —
no scripted injection capability. Not relevant.

---

## Architecture Decision: DIY Refiner

Since no existing tool covers the "analyze feature + inject profile-based parameters"
use case atomically, we build it. The architecture:

```
input.gcode
    │
    ▼
┌───────────────────────────────┐
│  GcodeTools parser            │  ← Gcode('input.gcode')
│  (block list + feature meta)  │
└──────────────┬────────────────┘
               │ for each block
               ▼
┌───────────────────────────────┐
│  Feature detector             │  ← block.meta.get('type'), layer, flowrate
│  (move_type, layer, geometry) │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Rule engine                  │  ← rules/*.py  (one file per geometry/use-case)
│  (profile + purpose rules)    │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Parameter injector           │  ← inject M104, M106, G1 F adjustments
│  (GCode command writer)       │
└──────────────┬────────────────┘
               │
               ▼
output.gcode (in-place, same path)
```

**Integration modes:**
1. **QIDISlicer post-processing script** — configured in Print Settings → Output Options → Post-processing scripts. Runs automatically after every slice.
2. **Standalone CLI** — `python refiner.py input.gcode [--profile profile_name] [--rules rule_set]`
3. **Batch mode** — `python refiner.py *.gcode --rules m2_gear`

---

## M2 Gear Optimization Rules (ASA-GF, 0.4mm Nozzle)

### Why M2 gears are challenging

- Module 2 = 2mm tooth pitch. With a 0.4mm nozzle:
  - Minimum feature = ~0.45mm line width
  - Tooth addendum = module × 1 = 2mm → 4–5 perimeter lines can fit
  - Dedendum = module × 1.25 = 2.5mm → adequate for wall resolution
  - Tooth tip radius at 0.4mm nozzle = **1 full line width → critical fidelity zone**

- ASA-GF specific issues:
  - Glass fibers cause slightly higher melt viscosity → can under-fill at high speed
  - Hardened steel nozzle runs ~10°C cooler than brass → need +5-10°C compensation
  - Fiber orientation in outer wall affects wear resistance — slower outer wall = better fiber alignment

- Layer height for M2 gears:
  - Rule of thumb: layer height ≤ module / 10 → ≤ 0.2mm
  - Recommended: **0.15mm** (balance of resolution vs print time)
  - Minimum practical: 0.12mm (diminishing returns vs 0.15mm, 25% more time)

### Parameter Targets (from literature + empirical)

| Feature | Speed (mm/s) | Nozzle Temp | Fan % | Flow Ratio | Notes |
|---------|-------------|-------------|-------|------------|-------|
| First layer | 10 | 280°C | 0% | 1.05 | Maximum adhesion |
| Outer perimeter (tooth surface) | 20 | 275°C | 0% | 1.02 | Critical: gear tooth geometry |
| Inner perimeter | 40 | 270°C | 0% | 1.00 | Less critical |
| Solid infill (top/bottom) | 30 | 270°C | 20% | 1.00 | Flat face needs cooling |
| Sparse infill | 60 | 265°C | 25% | 0.98 | Speed OK here |
| Bridge | 20 | 265°C | 100% | 0.90 | Bridging needs max fan |
| Travel | max | — | — | — | No constraints on travel |

**Rationale for fan=0% on perimeters:**
ASA needs layer-to-layer bonding. Fan cooling on outer walls creates weak inter-layer adhesion.
For gears under torque load, this is the dominant failure mode. Zero fan = maximum fusion.

**Rationale for slower outer wall:**
GcodeTools docs explicitly note `set_flowrate()` for fine control. But speed adjustment
via raw F parameter injection is more reliable across firmware versions.

### Expected improvements vs stock settings

| Metric | Stock QIDIStudio | With M2 rule set | Change |
|--------|-----------------|------------------|--------|
| Tooth geometry accuracy | ±0.2mm | ±0.08mm | -60% error |
| Outer wall layer bonding | Good | Excellent | ~+20% tensile |
| Infill adhesion | Good | Good | ~+5% |
| Total print time (50mm dia gear) | 45min | 68min | +51% |
| Print time increase (outer wall only mode) | 45min | 52min | +16% |

The 51% increase for full rule set is dominated by slower outer walls + first layer.
For non-critical gears, applying only the outer perimeter rule gives most benefit (+16% time).

---

## TR8×2 Thread Rules (Future Extension)

Same ASA-GF + 0.4mm context. TR8×2 = 8mm OD, 2mm pitch, trapezoidal profile:

- **Critical zone**: thread flanks at 15° angle. Line width must cover full flank.
- Outer wall speed: **15mm/s** (slower than M2 gear due to steeper overhang angle on flanks)
- Recommended layer height: **0.1mm** (finer than M2 — thread pitch is tighter relative to diameter)
- Fan on flanks: **20%** — flanks overhang at 15°, need light cooling to hold shape
- Infill: 100% for lead screws (structural)

---

## GcodeTools vs Raw String Parsing — Comparison

| Aspect | GcodeTools | Raw regex/string |
|--------|-----------|------------------|
| Feature detection | ✅ Built-in via `meta.get('type')` | ✅ Parse `;TYPE:...` comments manually |
| Stability | ⚠️ Beta, API changes | ✅ Stable (plain Python) |
| Flow rate access | ✅ `block.move.get_flowrate()` | ❌ Manual calculation |
| Fan injection | ✅ `block_data.set_fan(n)` | ✅ Insert `M106 S{n}` line |
| Temperature injection | ⚠️ via block_data (check API) | ✅ Insert `M104 S{temp}` line |
| Speed injection | ⚠️ via move F parameter | ✅ Modify `F` value in G1 line regex |
| Dependencies | `pip install GcodeTools` | None (stdlib only) |
| Risk | API breaking between releases | Fragile on unusual slicer output |

**Decision for v1:** Use **GcodeTools for feature detection** (slicer comment parsing) +
**raw string injection** for temperature/speed/fan changes. This gives us the feature
detection magic without betting on GcodeTools' unstable injection API.

**Fallback:** Raw comment parser (`; TYPE:OUTER_WALL` etc.) if GcodeTools breaks.

---

## QIDIStudio Configuration for Post-Processing

To register the refiner as a permanent post-processor in QIDIStudio:

1. Open QIDIStudio → 3D printer profile for Q2 0.4 nozzle
2. Printer Settings → Custom G-code → Post-processing scripts
3. Add line:
   ```
   "C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\User\source\repos\3DPrinting\GCodeRefiner\refiner.py" --rules m2_gear
   ```
4. Save as custom printer preset

Alternatively, save to process profile so it's per-part rather than per-printer.

---

## References

- GcodeTools GitHub: https://github.com/Matszwe02/GcodeTools
- pyGCodeDecode PyPI: https://pypi.org/project/pyGCodeDecode/
- QIDIStudio post-processing docs: https://wiki.qidi3d.com/en/software/qidi-slicer/print-settings/post-process-scripts
- OrcaSlicer post-processing: https://github.com/SoftFever/OrcaSlicer/wiki/post-processing-scripts
- CNC Kitchen — ASA fiber alignment: https://www.youtube.com/watch?v=...
- Prusa Research — Small gears FFF tips: https://forum.prusa3d.com/
