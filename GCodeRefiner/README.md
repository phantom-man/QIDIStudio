# GCode Refiner

Feature-aware, use-case-driven GCode post-processor for 3D printing.

Reads a `.gcode` file, detects **feature types** from slicer comment markers
(`; TYPE:OUTER_WALL` etc.), then applies **three layers of optimization** in order:

1. **Nozzle + material profile** — base temperature, speed, fan, flow envelope
2. **Use-case rules** — per-feature overrides for your specific goal
3. **AMEO live loop** — real-time fine-tuning during the print (Klipper/Moonraker)

The Refiner handles stage 1 + 2 (pre-print, applied to the `.gcode` file).
AMEO handles stage 3 (live, via Moonraker API). See `docs/AMEO-Technical-Reference.md §14`.

---

## Quick Start

### As QIDISlicer Post-Processing Script (recommended)

1. Open QIDIStudio → Printer Settings → Custom G-code → **Post-processing scripts**
2. Add:
   ```
   "<python>" "<path_to>/GCodeRefiner/refiner.py" --rules <use_case>
   ```
3. Save to your printer preset for the active nozzle + a process preset per use case.
4. Slice as normal — the refiner runs automatically on every export.

QIDISlicer passes the gcode file path as the last argument automatically.
The script modifies the file **in-place** (same file, no extra copy).

### Standalone CLI

```powershell
# Apply watertight rules with CHT 0.4 + PLA-HS profile
python refiner.py print.gcode --profile pla_hs_cht_04mm --rules watertight

# Fine detail on ASA-GF
python refiner.py part.gcode --profile asa_gf_04mm --rules fine_detail

# Dry run — see what would be injected
python refiner.py print.gcode --rules m2_gear --dry-run --verbose

# List what's available
python refiner.py --list-profiles
python refiner.py --list-rules
```

---

## Installation

```powershell
# Install GcodeTools (optional — advanced flow-rate analysis)
pip install GcodeTools

# Verify (core refiner works without it via raw comment parser fallback)
python -c "import GcodeTools; print('GcodeTools OK')"
```

---

## Use-Case Catalog (`rules/`)

Choose **one use case per print** based on what you're optimising for.

| Rule file        | Use case              | Key tradeoff               | Best for                                 |
| ---------------- | --------------------- | -------------------------- | ---------------------------------------- |
| `m2_gear.py`     | Precision gears (M2+) | Geometry fidelity vs time  | Involute gears, sprockets, worm gears    |
| `watertight.py`  | Fluid-tight vessels   | No perimeter gaps vs speed | Tanks, enclosures, planters, soap dishes |
| `fine_detail.py` | Surface resolution    | Accuracy vs time           | Miniatures, figurines, jewellery masters |
| `structural.py`  | Load-bearing strength | Layer bonding vs cooling   | Brackets, clips, hinges, mounts          |
| `fast_draft.py`  | Geometry verification | Time vs quality            | Fit checks, prototype iteration          |

### Choosing a use case

```
Is dimensional accuracy the primary goal?
  ├─ Yes, at the 0.1mm level (gear teeth, threads) → m2_gear
  ├─ Yes, on the visible surface (figurine, embossed text) → fine_detail
  └─ Yes, on the OD/ID for fit check → fast_draft (good enough for fit)

Is the print functional / structural?
  ├─ Must hold load or not crack → structural
  └─ Must seal against liquid or air → watertight

Is this a throw-away prototype?
  └─ Yes → fast_draft
```

---

## Nozzle + Material Profiles (`profiles/`)

Profile naming: `{material_id}_{nozzle_shortname}.py`
Where `material_id` matches the Material Registry in `AMEO-Technical-Reference.md §8`
and the nozzle matches the Nozzle Registry in `§9`.

| Profile file             | Filament                 | Nozzle                 | Status     |
| ------------------------ | ------------------------ | ---------------------- | ---------- |
| `asa_gf_04mm.py`         | Siraya Fibreheart ASA-GF | 0.4mm hardened steel   | ✅ Active  |
| `pla_hs_cht_04mm.py`     | PLA-HS (Anycubic/Bambu)  | CHT Diamond 0.4mm (V6) | ⬜ Pending |
| `pla_hs_bimetal_08mm.py` | PLA-HS                   | Bimetal DLC 0.8mm (V6) | ⬜ Pending |
| `petg_cht_04mm.py`       | PETG (eSUN/Bambu)        | CHT Diamond 0.4mm (V6) | ⬜ Pending |
| `abs_qidi_04mm.py`       | ABS (Bambu)              | QIDI stock 0.4mm       | ⬜ Pending |

**QIDISlicer tip:** Create one printer profile preset per nozzle, one process preset per use case.
The `--profile` arg goes in the printer preset; the `--rules` arg goes in the process preset.

---

## What Gets Injected

For each `; TYPE:...` feature transition, the refiner injects before the first move:

```
M104 S<temp>     — nozzle temperature (only when changing)
M106 S<0-255>    — fan speed (or M107 for off)
M204 P<accel>    — print acceleration
M221 S<pct>      — flow rate percentage
```

Then the `F` parameter in every `G1` move within that feature block is rewritten
to the rule-specified speed (mm/s → mm/min conversion).

Injection is **delta-only**: if a value hasn't changed vs the previous injection,
the command is skipped. No redundant commands polluting the file.

### Example: `m2_gear` on `OUTER_WALL`

```gcode
; TYPE:OUTER_WALL
M104 S275 ; refiner: M2 outer wall: slow + hot + no fan
M107      ; refiner: M2 outer wall: slow + hot + no fan
M204 P1000 ; refiner: M2 outer wall: slow + hot + no fan
G1 X... Y... E... F1200   ; was F2400 (40mm/s) → now 1200 (20mm/s)
```

### Example: `watertight` on `BRIDGE`

```gcode
; TYPE:BRIDGE
M104 S<nominal> ; refiner: watertight bridge: max fan, slow, under-extrude
M106 S255       ; 100% fan
M204 P500
M221 S95        ; 95% flow
G1 ... F900     ; 15mm/s
```

---

## Architecture: How Rule Files Work

```python
# Every rule file must expose this function:
def get_override(feature_type: str, layer: int, profile: object) -> dict | None:
    """
    feature_type: canonical string e.g. "OUTER_WALL", "BRIDGE", "SPARSE_INFILL"
    layer:        current layer number (0-based)
    profile:      the loaded profile module (access SPEED_OUTER_WALL etc. as attributes)

    Return a dict with any subset of:
        speed_mm_s : float     — print speed (mm/s)
        nozzle_temp: int       — hotend temp (°C)
        fan        : int       — fan 0–255
        flow_ratio : float     — flow multiplier (1.0 = 100%)
        accel      : int       — M204 acceleration (mm/s²)
        comment    : str       — appended to injected command comments

    Return None → use profile defaults for this feature (no injection).
    """
```

Rule files can compute values **relative to the profile** (e.g. `profile.SPEED_OUTER_WALL * 0.5`)
so they remain nozzle- and filament-agnostic. The parameter resolution chain is:

```
Rule override → Profile default → Slicer default
```

### Adding a new use case

```powershell
# Copy a similar rule as a starting point
Copy-Item rules\structural.py rules\my_new_case.py

# Edit OVERRIDES dict and get_override() in my_new_case.py
# Then use it:
python refiner.py print.gcode --rules my_new_case
```

---

## AMEO Integration

The Refiner and AMEO are complementary, not competing:

```
Slice → Refiner (offline, file) → Print → AMEO live loop (online, Klipper)
```

- Refiner: sets the _intended_ parameters for each feature type
- AMEO: adjusts _actual_ flow% and speed% in real-time based on vision feedback

The same nozzle and material IDs used in `AMEO_LOAD NOZZLE=<id> MATERIAL=<id>`
(Klipper start-gcode) match the profile naming convention here.

See `docs/AMEO-Technical-Reference.md §14` for the full integration map.

---

## Slicer Settings that Refiner _assumes_

The Refiner tunes parameters but cannot change slicer structure. Set these in QIDISlicer first:

| Setting           | Gears    | Watertight      | Fine detail | Structural | Fast draft |
| ----------------- | -------- | --------------- | ----------- | ---------- | ---------- |
| Wall loops        | 4–6      | ≥ 4             | 3–4         | ≥ 4        | 1–2        |
| Top/bottom layers | 4        | ≥ 5             | 4           | 4          | 2          |
| Infill %          | 80–100   | 25–40           | 20–40       | ≥ 40       | 10         |
| Layer height      | 0.1–0.15 | 0.2             | 0.05–0.1    | 0.2        | 0.25–0.3   |
| Wall generator    | Arachne  | Classic/Arachne | Arachne     | Classic    | Classic    |

---

## Research Notes

See [gcode_research.md](gcode_research.md) for full survey of existing tools,
architecture decisions, and M2 gear optimisation data.
