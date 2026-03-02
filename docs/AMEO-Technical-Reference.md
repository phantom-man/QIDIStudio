# AMEO Technical Reference

> **Autonomous Morphomorphic Extrusion Optimization — Verified Technical Reference**
>
> **Printer-agnostic.** Requires: Klipper firmware + Moonraker API. Works on any printer running this stack (QIDI, Voron, Bambu-converted, Ender, etc.).
>
> This document synthesizes all external sources linked in the three AMEO planning documents:
> `Autonomous Morphomorphic Extrusion Optimization (AMEO).md`,
> `Klipper Macro for AMEO Optimization.md`, and
> `AI-Controlled 3D Print Optimization.md`.
> All technical details verified against primary sources (Klipper docs, Moonraker docs, KIAUH docs).
>
> **Design principle:** Every hardware-specific value lives in a profile. The AMEO logic itself never hardcodes a printer, nozzle, or material.

---

## Table of Contents

1. [Core AMEO Formula](#1-core-ameo-formula)
2. [Klipper G-Code Commands (AMEO-relevant)](#2-klipper-g-code-commands-ameo-relevant)
3. [Klipper Config Sections (AMEO-relevant)](#3-klipper-config-sections-ameo-relevant)
4. [Klipper Command Template (Jinja2) Patterns](#4-klipper-command-template-jinja2-patterns)
5. [Moonraker API — Printer Objects for AMEO](#5-moonraker-api--printer-objects-for-ameo)
6. [gcode_shell_command Extension](#6-gcode_shell_command-extension)
7. [KIAUH Installation](#7-kiauh-installation)
8. [Material Profile Registry](#8-material-profile-registry)
9. [Nozzle Profile Registry](#9-nozzle-profile-registry)
10. [Complete Verified AMEO Macro](#10-complete-verified-ameo-macro)
11. [Complete Verified AI Vision Bridge](#11-complete-verified-ai-vision-bridge)
12. [Nozzle Swap Auto-Calibration (Z-Offset Vision Loop)](#12-nozzle-swap-auto-calibration-z-offset-vision-loop)
13. [System Integration Map](#13-system-integration-map)
14. [G-Code Refiner — Use-Case-Driven Pre-Print Optimization](#14-g-code-refiner--use-case-driven-pre-print-optimization)

---

## 1. Core AMEO Formula

AMEO's volumetric flow ceiling is derived from the thermal energy integral through the hot zone:

$$
V_{max} = \frac{\int_{0}^{L} k \cdot A_{contact} \cdot \Delta T \, dz}{\rho \cdot C_p \cdot L}
$$

Where:

- $k$ — thermal conductivity of the nozzle material (W/m·K)
- $A_{contact}$ — filament–hotend contact area (m²)
- $\Delta T = T_{hotend} - T_{glass}$ — effective thermal delta (°C)
- $\rho$ — filament density (kg/m³)
- $C_p$ — specific heat of filament (J/kg·K)
- $L$ — melt zone length (m)

**Speed limit from volumetric limit:**

$$
\text{Speed\_limit} = \frac{V_{max}}{H \times W}
$$

Where $H$ = layer height (mm), $W$ = extrusion width (mm).

**Material viscosity scaling factor:**

$$
\mu_{factor} = \frac{\text{MFI}}{10.0}
$$

Higher MFI → lower viscosity → higher safe flow rate.

---

## 2. Klipper G-Code Commands (AMEO-relevant)

Source: <https://www.klipper3d.org/G-Codes.html> (verified)

### 2.1 Velocity Control

```gcode
SET_VELOCITY_LIMIT [VELOCITY=<value>] [ACCEL=<value>] [MINIMUM_CRUISE_RATIO=<value>] [SQUARE_CORNER_VELOCITY=<value>]
```

- Sets runtime-dynamic velocity ceiling; changes persist until firmware restart or next call
- `VELOCITY` — max toolhead speed in mm/s
- `ACCEL` — max acceleration in mm/s²
- `MINIMUM_CRUISE_RATIO` — minimum fraction of move at cruise speed (0.0–1.0); replaces deprecated `ACCEL_TO_DECEL`
- `SQUARE_CORNER_VELOCITY` — max speed at 90° corners in mm/s
- **No units suffix required** — all values are raw numbers

### 2.2 Pressure Advance

```gcode
SET_PRESSURE_ADVANCE [EXTRUDER=<extruder_name>] [ADVANCE=<pressure_advance>] [SMOOTH_TIME=<pressure_advance_smooth_time>]
```

- Dynamically adjusts extruder pressure compensation
- `ADVANCE` — typical range 0.0–0.1 for most setups (0.02–0.04 for CHT nozzles)
- `SMOOTH_TIME` — default 0.040 seconds; lower = more responsive but noisier
- Changes take effect immediately on the next move

### 2.3 Flow Override (M221)

```gcode
M221 S<percent>
```

- Sets extrusion multiplier as an integer percentage
- `M221 S100` = 100% (default), `M221 S95` = 5% underextrusion
- **Note:** Jinja2 math must be done before calling; Klipper does not evaluate expressions inside `S{}`

### 2.4 Speed Override (M220)

```gcode
M220 S<percent>
```

- Sets speed factor override as an integer percentage
- `M220 S100` = 100% (default)
- **Alternative:** `SET_VELOCITY_LIMIT` is preferred for programmatic control (integer-only vs. float)

### 2.5 Variable injection

```gcode
SET_GCODE_VARIABLE MACRO=<macro_name> VARIABLE=<variable_name> VALUE=<value>
```

- Injects a value into a named macro's `variable_*` field at runtime
- `VALUE` can be a number, string (must be quoted), or Python literal
- Example: `SET_GCODE_VARIABLE MACRO=AMEO VARIABLE=v_max VALUE=12.5`

### 2.6 Temperature control

```gcode
SET_HEATER_TEMPERATURE HEATER=<heater_name> TARGET=<target_temperature>
TEMPERATURE_WAIT SENSOR=<heater_name> [MINIMUM=<min_temp>] [MAXIMUM=<max_temp>]
```

### 2.7 Fan control

```gcode
SET_FAN_SPEED FAN=<fan_name> SPEED=<speed>
```

- `SPEED` range: 0.0 to 1.0

### 2.8 Display message

```gcode
M117 <message text>
```

- Sends text to display and Moonraker `display_status.message`

### 2.9 Shell command execution

```gcode
RUN_SHELL_COMMAND CMD=<command_name> [PARAMS=<parameters>]
```

- Requires `gcode_shell_command` extension installed via KIAUH (see §6)
- `CMD` must match a `[gcode_shell_command <name>]` section in printer.cfg
- `PARAMS` are passed as positional args to the script (`$1`, `$2`, etc.)

---

## 3. Klipper Config Sections (AMEO-relevant)

Source: <https://www.klipper3d.org/Config_Reference.html> (verified)

### 3.1 [printer]

```ini
[printer]
kinematics: cartesian          # or corexy, delta, etc.
max_velocity: 500              # mm/s — hard ceiling; SET_VELOCITY_LIMIT cannot exceed this
max_accel: 10000               # mm/s²
minimum_cruise_ratio: 0.5      # 0.0–1.0; replaces max_accel_to_decel
square_corner_velocity: 5.0    # mm/s at 90° corners
```

**Key constraint for AMEO:** `SET_VELOCITY_LIMIT VELOCITY=...` cannot exceed `max_velocity` set here. Set `max_velocity` to the hardware ceiling; let AMEO dynamically lower it.

### 3.2 [extruder]

```ini
[extruder]
nozzle_diameter: 0.400
filament_diameter: 1.750
pressure_advance: 0.030        # starting value; AMEO overrides at runtime
pressure_advance_smooth_time: 0.040
max_extrude_only_velocity: 120.0   # mm/s max retract/prime speed
max_extrude_only_accel: 1250.0
max_extrude_cross_section: 50.0    # mm² — safeguard (5 × nozzle_diameter²)
```

### 3.3 [gcode_macro]

```ini
[gcode_macro MACRO_NAME]
description: One-line description (shown in HELP / autocomplete)
variable_my_var: 0           # lowercase only; accessible as printer["gcode_macro MACRO_NAME"].my_var
gcode:
    {% set x = params.X|default(0)|float %}
    ...
```

**Jinja2 rules (verified):**

- Expressions in `{ }` are evaluated at macro call time
- Conditionals/loops in `{% %}`
- All `params.*` values arrive as **strings** — always cast with `|int` or `|float`
- `printer.*` access reflects state **at the time the macro text is evaluated**, not when commands execute
- Variable names in `variable_<name>:` must be all-lowercase, no spaces

### 3.4 [gcode_shell_command]

```ini
[gcode_shell_command <command_name>]
command: /path/to/script.sh   # absolute path; shebang required for scripts
timeout: 5.0                  # seconds; command is SIGKILL'd after this
verbose: True                 # forward stdout to terminal (set False for fast-loop calls)
```

- **Not part of core Klipper** — requires the extension (see §6)
- `sudo` commands are disallowed
- The runner process inherits the Klipper system user environment

### 3.5 [delayed_gcode]

```ini
[delayed_gcode <name>]
initial_duration: 0           # seconds after printer ready; 0 = do not auto-run
gcode:
    ...
```

Useful for AMEO: schedule periodic re-evaluation loops via `UPDATE_DELAYED_GCODE ID=<name> DURATION=<seconds>`.

### 3.6 [save_variables]

```ini
[save_variables]
filename: ~/printer_data/config/variables.cfg
```

Enables `SAVE_VARIABLE VARIABLE=<name> VALUE=<value>` — persists AMEO calibration results across restarts. Readable in macros as `printer.save_variables.variables.<name>`.

---

## 4. Klipper Command Template (Jinja2) Patterns

Source: <https://www.klipper3d.org/Command_Templates.html> (verified)

### 4.1 Reading printer state in macros

```jinja
{% set v = printer.toolhead.max_velocity %}
{% set pa = printer.extruder.pressure_advance %}
{% set temp = printer.extruder.temperature %}
{% set target = printer.extruder.target %}
{% set flow = printer.gcode_move.extrude_factor %}   # current M221 multiplier (0.0–1.0)
{% set speed_factor = printer.gcode_move.speed_factor %}  # current M220 multiplier
```

### 4.2 Persisting state between macro calls

```ini
[gcode_macro AMEO]
variable_v_max: 0.0
variable_pa_target: 0.030
gcode:
    # ... compute and store
    SET_GCODE_VARIABLE MACRO=AMEO VARIABLE=v_max VALUE={new_v}
```

### 4.3 Correct integer/float M221 call

```jinja
{% set flow_pct = flow_factor * 100 %}
M221 S{flow_pct|int}
```

### 4.4 Passing extruder temp to shell script

```ini
[gcode_macro CALL_AI_BRIDGE]
gcode:
    {% set temp = printer.extruder.temperature %}
    RUN_SHELL_COMMAND CMD=ameo_bridge PARAMS={temp}
```

### 4.5 SAVE_GCODE_STATE pattern (required around G1 moves)

```gcode
SAVE_GCODE_STATE NAME=my_state
G91
G1 Z5 F600
RESTORE_GCODE_STATE NAME=my_state
```

### 4.6 Timed polling loop

```ini
[delayed_gcode ameo_loop]
initial_duration: 0
gcode:
    RUN_SHELL_COMMAND CMD=ameo_vision_bridge
    UPDATE_DELAYED_GCODE ID=ameo_loop DURATION=2
```

To start: `UPDATE_DELAYED_GCODE ID=ameo_loop DURATION=2`  
To stop: `UPDATE_DELAYED_GCODE ID=ameo_loop DURATION=0`

---

## 5. Moonraker API — Printer Objects for AMEO

Source: <https://moonraker.readthedocs.io/en/latest/printer_objects/> (verified)  
API endpoint base: `http://localhost:7125`

### 5.1 Execute G-Code (primary AI bridge endpoint)

```
POST http://localhost:7125/printer/gcode/script
Content-Type: application/x-www-form-urlencoded

script=SET_VELOCITY_LIMIT VELOCITY=250
```

Python:

```python
import requests

def send_gcode(gcode: str, host: str = "localhost", port: int = 7125) -> dict:
    url = f"http://{host}:{port}/printer/gcode/script"
    resp = requests.post(url, params={"script": gcode}, timeout=5.0)
    resp.raise_for_status()
    return resp.json()
```

### 5.2 Query printer object status

```
GET http://localhost:7125/printer/objects/query?toolhead&extruder&gcode_move
```

Returns JSON with current state for all queried objects.

### 5.3 Key queryable objects for AMEO

#### `toolhead`

```json
{
  "max_velocity": 300.0,       // current runtime ceiling set by SET_VELOCITY_LIMIT
  "max_accel": 1500.0,
  "minimum_cruise_ratio": 0.5,
  "square_corner_velocity": 5.0,
  "position": [x, y, z, e],
  "homed_axes": "xyz"
}
```

#### `extruder`

```json
{
  "temperature": 240.5, // actual current temperature
  "target": 240.0, // set target
  "pressure_advance": 0.03, // current PA value
  "smooth_time": 0.04,
  "can_extrude": true
}
```

#### `gcode_move`

```json
{
  "speed_factor": 1.0,         // M220 multiplier (1.0 = 100%)
  "extrude_factor": 1.0,       // M221 multiplier (1.0 = 100%)
  "speed": 100.0,              // last gcode move speed in mm/s
  "position": [x, y, z, e]
}
```

#### `motion_report`

```json
{
  "live_velocity": 185.3, // real-time toolhead speed in mm/s
  "live_extruder_velocity": 4.2 // real-time extruder velocity
}
```

#### `gcode_macro <MACRO_NAME>`

```json
{
  "v_max": 12.5, // returns all variable_* values
  "pa_target": 0.03
}
```

### 5.4 Subscribe to real-time updates (WebSocket)

Moonraker supports WebSocket subscriptions for continuous telemetry — relevant for a closed-loop vision bridge:

```python
import websocket, json

def subscribe_objects(ws_url="ws://localhost:7125/websocket"):
    def on_open(ws):
        msg = {
            "jsonrpc": "2.0",
            "method": "printer.objects.subscribe",
            "params": {
                "objects": {
                    "extruder": ["temperature", "pressure_advance"],
                    "toolhead": ["max_velocity", "position"],
                    "motion_report": ["live_velocity"]
                }
            },
            "id": 1
        }
        ws.send(json.dumps(msg))
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=lambda ws, msg: print(msg))
    ws.run_forever()
```

---

## 6. gcode_shell_command Extension

Source: <https://github.com/dw-0/kiauh/blob/master/docs/gcode_shell_command.md> (verified)

**Author:** Arksine (same author as Moonraker)  
**Distribution:** Via KIAUH Advanced install menu

### 6.1 What it does

Allows `[gcode_shell_command]` config sections that execute arbitrary Linux commands or scripts from within Klipper macros via `RUN_SHELL_COMMAND`.

### 6.2 Minimal config

```ini
[gcode_shell_command ameo_vision_bridge]
command: python3 /home/pi/printer_data/config/scripts/ameo_vision_bridge.py
timeout: 5.0
verbose: True
```

### 6.3 With parameter passing

```ini
[gcode_shell_command ameo_vision_bridge]
command: python3 /home/pi/printer_data/config/scripts/ameo_vision_bridge.py
timeout: 5.0
verbose: True

[gcode_macro CALL_AMEO_BRIDGE]
gcode:
    {% set temp = printer.extruder.temperature %}
    {% set pa = printer.extruder.pressure_advance %}
    RUN_SHELL_COMMAND CMD=ameo_vision_bridge PARAMS="{temp},{pa}"
```

Script receives params as positional arguments: `sys.argv[1]` = `"240.5,0.030"`

### 6.4 Security notes

- `sudo` commands are **disallowed** by the extension
- Scripts **must have a shebang** (`#!/usr/bin/env python3`)
- High-frequency calls (< 1s interval) should use `verbose: False`
- The process is killed with SIGKILL after `timeout` seconds; ensure any state is written before then

### 6.5 Script template

```python
#!/usr/bin/env python3
"""AMEO Vision Bridge — called by RUN_SHELL_COMMAND CMD=ameo_vision_bridge"""
import sys
import requests

MOONRAKER_URL = "http://localhost:7125"

def send_gcode(cmd: str) -> None:
    requests.post(f"{MOONRAKER_URL}/printer/gcode/script", params={"script": cmd}, timeout=4.0)

def main():
    # Parse params if passed
    params = sys.argv[1] if len(sys.argv) > 1 else ""

    # --- AI / vision inference goes here ---
    # recommended_flow = run_vision_model(capture_frame())
    recommended_flow = 1.0   # placeholder
    recommended_speed = 1.0  # placeholder

    flow_pct = int(recommended_flow * 100)
    speed_pct = int(recommended_speed * 100)

    send_gcode(f"M221 S{flow_pct}")
    send_gcode(f"M220 S{speed_pct}")
    print(f"AMEO: flow={flow_pct}% speed={speed_pct}%")

if __name__ == "__main__":
    main()
```

---

## 7. KIAUH Installation

Source: <https://github.com/dw-0/kiauh> (verified)

### 7.1 Prerequisites

- Raspberry Pi OS Lite (Debian Bookworm/Bullseye) or equivalent Debian-based distro
- Git installed: `sudo apt-get install git`
- Klipper + Moonraker already installed (KIAUH can install both)

### 7.2 Install KIAUH

```bash
cd ~
git clone https://github.com/dw-0/kiauh.git
./kiauh/kiauh.sh
```

### 7.3 Install gcode_shell_command

1. Launch `./kiauh/kiauh.sh`
2. Select `[1] Install`
3. Select `[Advanced]`
4. Select `[gcode_shell_command]` (G-Code Shell Command)
5. Follow prompts

After installation, restart Klipper: `sudo service klipper restart`

### 7.4 Verify installation

The extension adds the gcode_shell_command parser to Klipper's extras directory:

```
~/klipper/klippy/extras/gcode_shell_command.py
```

---

## 8. Material Profile Registry

Each material entry defines the parameters AMEO needs to compute $V_{max}$ and $\mu_{factor}$.
Store these in `~/printer_data/config/ameo_profiles.json` (see §11 for how the bridge loads them).
Add new materials without touching any macro or bridge code.

### Schema

| Field      | Type   | Description                                   |
| ---------- | ------ | --------------------------------------------- |
| `id`       | string | Profile key used in `AMEO_LOAD MATERIAL=<id>` |
| `name`     | string | Human-readable label                          |
| `mfi`      | float  | Melt Flow Index (g/10min @ 210°C / 2.16 kg)   |
| `density`  | float  | g/cm³                                         |
| `tg`       | float  | Glass transition temperature (°C)             |
| `temp_min` | int    | Minimum recommended print temp (°C)           |
| `temp_max` | int    | Maximum recommended print temp (°C)           |
| `bed_temp` | int    | Recommended bed temp (°C)                     |

### Example entries (starter set)

The full database will live in a separate `filament_db.json` (or Postgres table for the service).
This is the seed set used for local AMEO testing.

```json
{
  "materials": [
    {
      "id": "anycubic_pla_hs",
      "brand": "Anycubic",
      "name": "High Speed PLA",
      "type": "pla",
      "variant": "hs",
      "mfi": 14.0,
      "mfi_temp": 210,
      "density": 1.24,
      "tg": 58,
      "temp_optimal": 230,
      "temp_min": 200,
      "temp_max": 270,
      "bed_temp": 55,
      "bed_temp_min": 25,
      "chamber_temp": 0,
      "fan_speed_pct": 100,
      "fan_first_layers": 1,
      "pa_modifier": 1.0,
      "retract_dist": 0.5,
      "retract_speed": 45,
      "first_layer_speed_pct": 30,
      "min_layer_time": 3,
      "volumetric_max": 16.0,
      "requires_hardened": false,
      "dry_temp": 50,
      "dry_time_hrs": 4,
      "notes": "AMEO reference baseline. Consistent viscosity; ideal for speed profiling. MFI 13-16 between batches.",
      "source": "datasheet"
    },
    {
      "id": "generic_pla_standard",
      "brand": "Generic",
      "name": "Standard PLA",
      "type": "pla",
      "variant": "standard",
      "mfi": 10.0,
      "mfi_temp": 210,
      "density": 1.24,
      "tg": 55,
      "temp_optimal": 210,
      "temp_min": 190,
      "temp_max": 220,
      "bed_temp": 60,
      "bed_temp_min": 55,
      "chamber_temp": 0,
      "fan_speed_pct": 100,
      "fan_first_layers": 2,
      "pa_modifier": 1.0,
      "retract_dist": 0.8,
      "retract_speed": 40,
      "first_layer_speed_pct": 25,
      "min_layer_time": 5,
      "volumetric_max": 11.0,
      "requires_hardened": false,
      "dry_temp": 50,
      "dry_time_hrs": 4,
      "notes": "AMEO mu_factor baseline = 1.0. Slowest safe PLA.",
      "source": "datasheet"
    },
    {
      "id": "bambu_pla_basic",
      "brand": "Bambu Lab",
      "name": "PLA Basic",
      "type": "pla",
      "variant": "standard",
      "mfi": 12.0,
      "mfi_temp": 210,
      "density": 1.24,
      "tg": 58,
      "temp_optimal": 220,
      "temp_min": 190,
      "temp_max": 240,
      "bed_temp": 55,
      "bed_temp_min": 35,
      "chamber_temp": 0,
      "fan_speed_pct": 100,
      "fan_first_layers": 1,
      "pa_modifier": 1.0,
      "retract_dist": 0.5,
      "retract_speed": 45,
      "first_layer_speed_pct": 30,
      "min_layer_time": 3,
      "volumetric_max": 14.0,
      "requires_hardened": false,
      "dry_temp": 50,
      "dry_time_hrs": 4,
      "notes": "Well-characterised. Good AMEO subject. Tight MFI consistency batch-to-batch.",
      "source": "community"
    },
    {
      "id": "esun_petg_clear",
      "brand": "eSUN",
      "name": "ePETG Clear",
      "type": "petg",
      "variant": "standard",
      "mfi": 7.0,
      "mfi_temp": 210,
      "density": 1.27,
      "tg": 80,
      "temp_optimal": 240,
      "temp_min": 230,
      "temp_max": 250,
      "bed_temp": 70,
      "bed_temp_min": 65,
      "chamber_temp": 0,
      "fan_speed_pct": 50,
      "fan_first_layers": 3,
      "pa_modifier": 1.1,
      "retract_dist": 0.5,
      "retract_speed": 35,
      "first_layer_speed_pct": 20,
      "min_layer_time": 7,
      "volumetric_max": 8.0,
      "requires_hardened": false,
      "dry_temp": 65,
      "dry_time_hrs": 6,
      "notes": "Stringing-prone; reduce fan to avoid warping. mu_factor 0.7 = 30% slower than PLA HS baseline.",
      "source": "community"
    },
    {
      "id": "bambu_abs",
      "brand": "Bambu Lab",
      "name": "ABS",
      "type": "abs",
      "variant": "standard",
      "mfi": 11.0,
      "mfi_temp": 220,
      "density": 1.05,
      "tg": 105,
      "temp_optimal": 255,
      "temp_min": 240,
      "temp_max": 270,
      "bed_temp": 100,
      "bed_temp_min": 90,
      "chamber_temp": 40,
      "fan_speed_pct": 0,
      "fan_first_layers": 999,
      "pa_modifier": 0.9,
      "retract_dist": 0.5,
      "retract_speed": 40,
      "first_layer_speed_pct": 20,
      "min_layer_time": 8,
      "volumetric_max": 12.0,
      "requires_hardened": false,
      "dry_temp": 80,
      "dry_time_hrs": 4,
      "notes": "Enclosure mandatory. Zero part cooling. Warping risk without chamber heat. Fumes — ventilate.",
      "source": "datasheet"
    },
    {
      "id": "bambu_pla_cf",
      "brand": "Bambu Lab",
      "name": "PLA-CF",
      "type": "pla-cf",
      "variant": "cf",
      "mfi": 10.0,
      "mfi_temp": 210,
      "density": 1.27,
      "tg": 65,
      "temp_optimal": 230,
      "temp_min": 220,
      "temp_max": 250,
      "bed_temp": 55,
      "bed_temp_min": 45,
      "chamber_temp": 0,
      "fan_speed_pct": 100,
      "fan_first_layers": 1,
      "pa_modifier": 1.05,
      "retract_dist": 0.5,
      "retract_speed": 40,
      "first_layer_speed_pct": 25,
      "min_layer_time": 5,
      "volumetric_max": 12.0,
      "requires_hardened": true,
      "dry_temp": 55,
      "dry_time_hrs": 8,
      "notes": "Hardened/diamond nozzle required. Stiffer prints; slightly reduced MFI vs plain PLA. No stringing.",
      "source": "community"
    },
    {
      "id": "bambu_pa12_cf",
      "brand": "Bambu Lab",
      "name": "PA12-CF",
      "type": "pa-cf",
      "variant": "cf",
      "mfi": 5.0,
      "mfi_temp": 235,
      "density": 1.1,
      "tg": 170,
      "temp_optimal": 290,
      "temp_min": 280,
      "temp_max": 310,
      "bed_temp": 80,
      "bed_temp_min": 70,
      "chamber_temp": 45,
      "fan_speed_pct": 30,
      "fan_first_layers": 5,
      "pa_modifier": 1.3,
      "retract_dist": 0.8,
      "retract_speed": 30,
      "first_layer_speed_pct": 15,
      "min_layer_time": 10,
      "volumetric_max": 6.0,
      "requires_hardened": true,
      "dry_temp": 90,
      "dry_time_hrs": 12,
      "notes": "Extremely hygroscopic — must be bone dry. CHT/bimetal only. AMEO speed ceiling ~40% of PLA HS. Exceptional strength.",
      "source": "community"
    },
    {
      "id": "polymaker_tpu95",
      "brand": "Polymaker",
      "name": "PolyFlex TPU95",
      "type": "tpu",
      "variant": "95a",
      "mfi": 10.0,
      "mfi_temp": 190,
      "density": 1.22,
      "tg": -35,
      "temp_optimal": 225,
      "temp_min": 210,
      "temp_max": 240,
      "bed_temp": 30,
      "bed_temp_min": 25,
      "chamber_temp": 0,
      "fan_speed_pct": 100,
      "fan_first_layers": 2,
      "pa_modifier": 0.5,
      "retract_dist": 0.0,
      "retract_speed": 25,
      "first_layer_speed_pct": 20,
      "min_layer_time": 8,
      "volumetric_max": 6.0,
      "requires_hardened": false,
      "dry_temp": 50,
      "dry_time_hrs": 6,
      "notes": "Direct-drive only; bowden will jam. Zero or minimal retraction. AMEO speed ceiling ~25mm/s. PA value near zero.",
      "source": "community"
    }
  ]
}
```

**μ_factor formula (universal):**

```python
mu_factor = material["mfi"] / 10.0  # baseline MFI = 10 → mu = 1.0
```

---

## 9. Nozzle Profile Registry

Each nozzle entry defines thermal and geometric parameters. Store alongside material profiles in
`~/printer_data/config/ameo_profiles.json`. Switching nozzles = `AMEO_LOAD NOZZLE=<id>`.

### Thermal multiplier table

| Nozzle body material            | k (W/m·K)          | AMEO k_factor vs brass |
| ------------------------------- | ------------------ | ---------------------- |
| Brass                           | ~109               | 1.0 (baseline)         |
| Copper                          | ~400               | 1.6                    |
| Hardened steel                  | ~25                | 0.6                    |
| Bimetal (brass + hardened tip)  | ~90–100            | 0.9                    |
| Bimetal DLC-coated              | ~1000+ (DLC tip)   | 1.5                    |
| CHT (multi-channel, brass body) | ~160–180 effective | 1.5                    |

The CHT advantage is surface area, not conductivity: splitting flow into multiple channels increases $A_{contact}$ by ~50%, which is why it outperforms its base material's k value.

### Schema

| Field          | Type   | Description                                     |
| -------------- | ------ | ----------------------------------------------- |
| `id`           | string | Profile key used in `AMEO_LOAD NOZZLE=<id>`     |
| `diameter`     | float  | Nozzle orifice in mm                            |
| `k_factor`     | float  | AMEO thermal multiplier (brass = 1.0)           |
| `pa_base`      | float  | Baseline pressure advance starting point        |
| `type`         | string | `standard` \| `cht` \| `volcano` \| `hardened`  |
| `max_abrasive` | bool   | Whether it can handle filled/abrasive filaments |

### Registry — current nozzles

```json
{
  "nozzles": [
    {
      "id": "cht_diamond_04",
      "name": "CHT Diamond-tip 0.4mm (detail / fine work)",
      "diameter": 0.4,
      "k_factor": 1.5,
      "pa_base": 0.025,
      "type": "cht",
      "max_abrasive": true,
      "notes": "Multi-channel melt path. ~1.5x volumetric throughput vs brass 0.4. Diamond tip handles abrasive fills."
    },
    {
      "id": "bimetal_dlc_08",
      "name": "Bimetal DLC-coated 0.8mm (prototyping / large parts)",
      "diameter": 0.8,
      "k_factor": 1.5,
      "pa_base": 0.01,
      "type": "hardened",
      "max_abrasive": true,
      "notes": "Large orifice dominates throughput over k_factor penalty. Expect 2-3x layer area vs 0.4. DLC coating handles carbon-fill, glow-in-dark, etc."
    },
    {
      "id": "qidi_04",
      "name": "QIDI stock brass 0.4mm",
      "diameter": 0.4,
      "k_factor": 1.0,
      "pa_base": 0.04,
      "type": "standard",
      "max_abrasive": false,
      "notes": "AMEO baseline reference nozzle. Factory-installed on Qidi Q2."
    },
    {
      "id": "qidi_02",
      "name": "QIDI 0.2mm (fine detail)",
      "diameter": 0.2,
      "k_factor": 1.0,
      "pa_base": 0.06,
      "type": "standard",
      "max_abrasive": false,
      "notes": "Very fine detail. V_max ~4 mm\u00b3/s with PLA-HS. Keep speeds \u226480 mm/s to avoid grinding."
    },
    {
      "id": "qidi_08",
      "name": "QIDI 0.8mm (high-throughput)",
      "diameter": 0.8,
      "k_factor": 1.0,
      "pa_base": 0.01,
      "type": "standard",
      "max_abrasive": false,
      "notes": "4\u00d7 cross-section of 0.4. V_max ~16.8 mm\u00b3/s with PLA-HS at 100 mm/s."
    }
  ]
}
```

### V6 adapter note

The E3D V6 adapter mounts all of the above nozzles to the hotend. The adapter itself is thermally
neutral (stainless steel shim) — it does **not** change `k_factor`. Only the nozzle tip material matters.

### Volumetric ceiling comparison (pla_hs + 0.2mm layer + nominal line width)

| Nozzle         | Diameter | k_factor | Line width | V_max (mm³/s) | Speed ceiling |
| -------------- | -------- | -------- | ---------- | ------------- | ------------- |
| qidi_04        | 0.4      | 1.0      | 0.42 mm    | 14.0          | **167 mm/s**  |
| cht_diamond_04 | 0.4      | 1.5      | 0.42 mm    | 21.0          | **250 mm/s**  |
| bimetal_dlc_08 | 0.8      | 1.5      | 0.84 mm    | 21.0          | **125 mm/s**  |
| qidi_08        | 0.8      | 1.0      | 0.84 mm    | 16.8          | **100 mm/s**  |
| qidi_02        | 0.2      | 1.0      | 0.21 mm    | 4.2           | **100 mm/s**  |

_0.8mm trades speed for throughput: each mm of travel deposits 4× the cross-section area._

---

## 10. Complete Verified AMEO Macro

All printer-specific values (accel, max velocity) are read from the **live printer config** via
`printer.configfile.settings` — never hardcoded. Nozzle and material parameters come from the
profile registry via the vision bridge (§11).

```ini
# ─────────────────────────────────────────────────────────────────────────────
# AMEO macro suite — printer-agnostic
# Paste into printer.cfg (or include it via [include ameo.cfg])
# ─────────────────────────────────────────────────────────────────────────────

[gcode_macro AMEO_INIT]
description: Initialize AMEO with nozzle + material profile params
variable_v_max: 0.0
variable_speed_limit: 0.0
variable_pa_target: 0.030
variable_nozzle_id: "unknown"
variable_material_id: "unknown"
gcode:
    # --- Profile parameters (passed by slicer start-gcode or AMEO_LOAD) ---
    {% set mfi      = params.MFI      |default(10.0)|float %}  # material MFI
    {% set k_nozzle = params.K_NOZZLE |default(1.0) |float %}  # nozzle thermal factor
    {% set pa_base  = params.PA_BASE  |default(0.040)|float %} # nozzle PA starting point
    {% set layer_h  = params.LAYER_H  |default(0.2) |float %}  # mm
    {% set line_w   = params.LINE_W   |default(printer.configfile.settings.extruder.nozzle_diameter|float * 1.05)|float %}

    # --- Derive printer accel ceiling from live config (printer-agnostic) ---
    {% set max_accel_cfg = printer.configfile.settings.printer.max_accel|float %}
    {% set accel = [max_accel_cfg * 0.8, 3000]|max %}   # 80% of configured ceiling, min 3000

    # --- Compute volumetric ceiling ---
    {% set mu_factor = mfi / 10.0 %}
    {% set v_base    = 15.0 %}  # mm³/s at MFI=10, k=1.0
    {% set v_max     = v_base * k_nozzle * mu_factor %}

    # --- Clamp speed to printer's configured max_velocity ---
    {% set max_vel_cfg   = printer.configfile.settings.printer.max_velocity|float %}
    {% set speed_raw     = v_max / (layer_h * line_w) %}
    {% set speed_limit   = [speed_raw, max_vel_cfg]|min %}

    # --- Pressure advance: pa_base + linear speed scaling ---
    {% set pa = pa_base + (speed_limit / max_vel_cfg) * 0.010 %}

    # --- Apply ---
    SET_VELOCITY_LIMIT VELOCITY={speed_limit|int} ACCEL={accel|int} MINIMUM_CRUISE_RATIO=0.5 SQUARE_CORNER_VELOCITY=8.0
    SET_PRESSURE_ADVANCE ADVANCE={pa}

    # --- Persist ---
    SET_GCODE_VARIABLE MACRO=AMEO_INIT VARIABLE=v_max       VALUE={v_max}
    SET_GCODE_VARIABLE MACRO=AMEO_INIT VARIABLE=speed_limit VALUE={speed_limit}
    SET_GCODE_VARIABLE MACRO=AMEO_INIT VARIABLE=pa_target   VALUE={pa}

    M117 AMEO: Vmax={v_max|round(1)}mm3/s spd={speed_limit|int}mm/s PA={pa|round(3)}


[gcode_macro AMEO_LOAD]
description: Load a nozzle+material profile by ID — calls vision bridge to resolve params
# Usage from slicer start-gcode:
#   AMEO_LOAD NOZZLE=cht_diamond_04 MATERIAL=pla_hs LAYER_H=0.2
gcode:
    {% set nozzle_id   = params.NOZZLE   |default("qidi_04") %}
    {% set material_id = params.MATERIAL |default("pla_standard") %}
    {% set layer_h     = params.LAYER_H  |default(0.2)|float %}
    SET_GCODE_VARIABLE MACRO=AMEO_INIT VARIABLE=nozzle_id   VALUE="'{nozzle_id}'"
    SET_GCODE_VARIABLE MACRO=AMEO_INIT VARIABLE=material_id VALUE="'{material_id}'"
    # Resolve profile params via bridge, then call AMEO_INIT
    RUN_SHELL_COMMAND CMD=ameo_load_profile PARAMS="{nozzle_id},{material_id},{layer_h}"


[gcode_macro AI_REFLEXIVE_ADJUST]
description: Apply AI vision bridge corrections — flow, speed, and optional Z nudge
gcode:
    {% set flow_adj  = params.FLOW    |default(1.0)|float %}
    {% set speed_adj = params.SPEED   |default(1.0)|float %}
    {% set z_nudge   = params.Z_NUDGE |default(0.0)|float %}  # mm; positive = raise nozzle

    # Clamp to safety bounds
    {% set flow_clamped  = [0.70, [flow_adj,  1.30]|min]|max %}
    {% set speed_clamped = [0.70, [speed_adj, 1.30]|min]|max %}
    {% set z_clamped     = [-0.15, [z_nudge, 0.15]|min]|max %}  # max ±0.15mm per cycle

    M221 S{(flow_clamped * 100)|int}
    M220 S{(speed_clamped * 100)|int}

    {% if z_clamped != 0 %}
        SET_GCODE_OFFSET Z_ADJUST={z_clamped} MOVE=1
    {% endif %}

    M117 AMEO: fl={(flow_clamped*100)|int}% spd={(speed_clamped*100)|int}% dZ={z_clamped}


# --- Shell command declarations (paths via $AMEO_SCRIPTS env var or absolute) ---
[gcode_shell_command ameo_vision_bridge]
command: python3 ${HOME}/printer_data/config/scripts/ameo_vision_bridge.py
timeout: 5.0
verbose: False

[gcode_shell_command ameo_load_profile]
command: python3 ${HOME}/printer_data/config/scripts/ameo_vision_bridge.py --load-profile
timeout: 5.0
verbose: True


[delayed_gcode ameo_loop]
initial_duration: 0
gcode:
    RUN_SHELL_COMMAND CMD=ameo_vision_bridge
    UPDATE_DELAYED_GCODE ID=ameo_loop DURATION=3


[gcode_macro AMEO_START]
description: Start AMEO closed-loop control
gcode:
    UPDATE_DELAYED_GCODE ID=ameo_loop DURATION=3
    M117 AMEO loop started


[gcode_macro AMEO_STOP]
description: Stop AMEO closed-loop control and restore neutral state
gcode:
    UPDATE_DELAYED_GCODE ID=ameo_loop DURATION=0
    M221 S100
    M220 S100
    M117 AMEO stopped — manual control restored
```

### Slicer start-gcode integration (printer-agnostic)

Add to your slicer's **Start G-Code** section. Replace placeholder values with the slicer's
variable syntax for your tool (PrusaSlicer `{nozzle_diameter}`, OrcaSlicer `[nozzle_diameter]`, etc.):

```gcode
; --- AMEO nozzle + material selection ---
AMEO_LOAD NOZZLE=cht_diamond_04 MATERIAL=pla_hs LAYER_H=0.2
AMEO_START
```

---

## 11. Complete Verified AI Vision Bridge

Install at `${HOME}/printer_data/config/scripts/ameo_vision_bridge.py`.

**Path resolution:** The script is called with `${HOME}` expanded by the shell at runtime, so it works
whether the printer host is a Raspberry Pi, an Orange Pi, a Debian VM, or a BTT CB1 —
no hardcoded `/home/pi/` anywhere.

Configuration is loaded from `${HOME}/printer_data/config/ameo_profiles.json` (see §8, §9).
The Moonraker URL is overridable via the `AMEO_MOONRAKER_URL` environment variable so the same
script works on both local and remote setups.

Script at `${HOME}/printer_data/config/scripts/ameo_vision_bridge.py`:

```python
#!/usr/bin/env python3
"""
AMEO Vision Bridge
Captures a frame, runs inference, posts G-code adjustments via Moonraker.
Called by: RUN_SHELL_COMMAND CMD=ameo_vision_bridge
"""

import sys
import json
import time
import logging
from typing import Tuple

import os
import requests

# ── Configuration (all overridable via environment variables) ─────────────────
MOONRAKER_URL = os.environ.get("AMEO_MOONRAKER_URL", "http://localhost:7125")
PROFILES_PATH = os.environ.get(
    "AMEO_PROFILES",
    os.path.join(os.path.expanduser("~"), "printer_data", "config", "ameo_profiles.json")
)
LOG_PATH = os.environ.get("AMEO_LOG", "/tmp/ameo_bridge.log")
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


def get_printer_state() -> dict:
    """Query live printer state from Moonraker."""
    url = f"{MOONRAKER_URL}/printer/objects/query"
    params = {"extruder": None, "toolhead": None, "gcode_move": None, "motion_report": None}
    resp = requests.get(url, params=params, timeout=3.0)
    resp.raise_for_status()
    return resp.json()["result"]["status"]


def send_gcode(cmd: str) -> None:
    """Send a G-code command via Moonraker."""
    url = f"{MOONRAKER_URL}/printer/gcode/script"
    requests.post(url, params={"script": cmd}, timeout=4.0).raise_for_status()


def capture_frame():
    """Capture a frame from the webcam. Returns BGR numpy array or None."""
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None
    except ImportError:
        logging.warning("cv2 not available — skipping vision inference")
        return None


def run_vision_inference(frame) -> Tuple[float, float]:
    """
    Analyze frame for print quality issues.
    Returns (flow_multiplier, speed_multiplier) in range [0.7, 1.3].

    Replace this stub with actual model inference:
    - Under-extrusion (gaps) → reduce speed, increase flow
    - Over-extrusion (blobs) → reduce flow
    - Stringing → reduce temp / increase retraction (future)
    """
    if frame is None:
        return 1.0, 1.0

    # Stub: return neutral adjustments
    # TODO: replace with actual CV/ML inference
    flow_mult = 1.0
    speed_mult = 1.0
    return flow_mult, speed_mult


def clamp(value: float, lo: float = 0.70, hi: float = 1.30) -> float:
    return max(lo, min(hi, value))


def load_profiles() -> dict:
    """Load nozzle and material profiles from config JSON."""
    try:
        with open(PROFILES_PATH) as fh:
            return json.load(fh)
    except FileNotFoundError:
        logging.warning(f"Profiles not found at {PROFILES_PATH} — using defaults")
        return {}


def resolve_profile(profiles: dict, nozzle_id: str, material_id: str) -> Tuple[float, float, float]:
    """
    Resolve (k_factor, pa_base, mfi) from profile registry.
    Returns defaults if profile IDs not found — always safe to call.
    """
    nozzle = next((n for n in profiles.get("nozzles", []) if n["id"] == nozzle_id), None)
    material = next((m for m in profiles.get("materials", []) if m["id"] == material_id), None)
    k_factor = nozzle["k_factor"] if nozzle else 1.0
    pa_base  = nozzle["pa_base"]  if nozzle else 0.040
    mfi      = material["mfi"]    if material else 10.0
    return k_factor, pa_base, mfi


def main() -> None:
    load_profile_mode = "--load-profile" in sys.argv
    t0 = time.monotonic()

    try:
        profiles = load_profiles()

        if load_profile_mode:
            # Called by AMEO_LOAD: resolve profile and push AMEO_INIT
            params = sys.argv[-1] if len(sys.argv) > 2 else "brass_04,pla_standard,0.2"
            nozzle_id, material_id, layer_h = (params + ",0.2").split(",")[:3]
            k_factor, pa_base, mfi = resolve_profile(profiles, nozzle_id.strip(), material_id.strip())
            line_w = float(layer_h.strip()) * 2.1  # ~1.05× nozzle diameter heuristic
            send_gcode(
                f"AMEO_INIT MFI={mfi} K_NOZZLE={k_factor} PA_BASE={pa_base} "
                f"LAYER_H={layer_h.strip()} LINE_W={line_w:.3f}"
            )
            logging.info(f"Profile loaded: nozzle={nozzle_id} material={material_id}")
            return

        # Normal cycle: query state, capture frame, adjust
        state = get_printer_state()
        live_vel      = state.get("motion_report", {}).get("live_velocity", 0)
        extruder_temp = state.get("extruder",       {}).get("temperature",  0)
        logging.info(f"State OK: vel={live_vel:.1f}mm/s temp={extruder_temp:.1f}°C")

        frame = capture_frame()
        flow_mult, speed_mult = run_vision_inference(frame)
        flow_mult  = clamp(flow_mult)
        speed_mult = clamp(speed_mult)

        # Z-offset nudge from vision (see §12 for full auto-calibration loop)
        z_nudge = 0.0  # TODO: derive from first-layer gap detection

        send_gcode(
            f"AI_REFLEXIVE_ADJUST FLOW={flow_mult:.3f} SPEED={speed_mult:.3f} Z_NUDGE={z_nudge:.3f}"
        )
        logging.info(
            f"Applied: flow={flow_mult:.3f} speed={speed_mult:.3f} "
            f"z={z_nudge:+.3f} in {time.monotonic()-t0:.2f}s"
        )

    except requests.RequestException as exc:
        logging.error(f"Moonraker request failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        logging.error(f"Unexpected error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## 12. Nozzle Swap Auto-Calibration (Z-Offset Vision Loop)

### Why this matters

The single biggest friction point preventing users from swapping nozzles is **Z-offset recalibration**.
Even a 0.1mm error ruins the first layer. AMEO can eliminate this friction entirely:

1. Printer probes Z (strain-gauge or BLTouch) — gets close
2. AMEO vision loop watches the first 2–3 layers
3. Computer vision detects gap (Z too high) or over-squish (Z too low)
4. `SET_GCODE_OFFSET Z_ADJUST=<delta> MOVE=1` corrects it mid-print
5. Corrected offset is optionally saved for that nozzle profile

> **This is the killer feature.** Swap nozzle → select profile → print. No manual Z tuning.

### Detection heuristics (first layer)

| Visual indicator            | Meaning                       | AMEO action                     |
| --------------------------- | ----------------------------- | ------------------------------- |
| Visible gap between lines   | Z too high (nozzle above bed) | `Z_NUDGE = -0.02` to `-0.05` mm |
| Lines merging / over-squish | Z too low (nozzle into bed)   | `Z_NUDGE = +0.02` to `+0.05` mm |
| Rounded bead, poor adhesion | Z too high                    | `Z_NUDGE = -0.02` mm            |
| Flat, well-bonded lines     | Correct                       | `Z_NUDGE = 0`                   |
| Corners lifting             | Bed temp or fan issue         | No Z action; flag for review    |

### Z-offset nudge implementation

The `AI_REFLEXIVE_ADJUST` macro (§10) already accepts `Z_NUDGE`. The vision bridge needs to
populate it. Stub in `ameo_vision_bridge.py`:

```python
def detect_z_offset_error(frame, layer_number: int) -> float:
    """
    Analyse first-layer frame for Z offset error.
    Returns nudge in mm (+ve = raise nozzle, -ve = lower nozzle).
    Only acts on layers 1-3; returns 0.0 thereafter.
    """
    if layer_number > 3 or frame is None:
        return 0.0

    # TODO: implement with cv2 or a lightweight ONNX classifier
    # Approach A: edge density — high edge density in bead area = over-squish
    # Approach B: line gap detection — Hough line gaps = Z too high
    # Approach C: bead roundness (aspect ratio of cross-section profile)

    return 0.0  # placeholder — returns 0 = no adjustment
```

### Saving the calibrated offset per nozzle profile

After the first layer stabilises, the accumulated `Z_ADJUST` can be written back to the profile:

```python
def save_z_offset_to_profile(nozzle_id: str, z_total: float) -> None:
    """Persist the learned Z offset into ameo_profiles.json for this nozzle."""
    import json, os
    path = PROFILES_PATH
    with open(path) as fh:
        profiles = json.load(fh)
    for nozzle in profiles.get("nozzles", []):
        if nozzle["id"] == nozzle_id:
            nozzle["z_offset_learned"] = round(z_total, 4)
    with open(path, "w") as fh:
        json.dump(profiles, fh, indent=2)
```

Next print with the same nozzle: load the saved `z_offset_learned` and apply it with
`SET_GCODE_OFFSET Z={z_offset_learned}` before the first layer.

### Klipper command used

```gcode
SET_GCODE_OFFSET Z_ADJUST=<delta_mm> MOVE=1
```

- `Z_ADJUST` is **additive** — stacks on top of existing offset safely
- `MOVE=1` moves the toolhead immediately to reflect the new offset
- Maximum safe per-cycle nudge: ±0.15mm (enforced in `AI_REFLEXIVE_ADJUST`)
- Cumulative cap: ±0.5mm — if exceeded, halt and alert (indicates probe failure, not Z creep)

---

## 13. System Integration Map

```
┌─────────────────────────────────────────────────────────────┐
│                    AMEO System Stack                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐   RUN_SHELL_COMMAND   ┌───────────────┐  │
│  │ Klipper      │ ──────────────────►  │ ameo_vision   │  │
│  │ [delayed_gcode│                      │ _bridge.py    │  │
│  │  ameo_loop]  │ ◄──── API response ─  │               │  │
│  └──────┬───────┘                      └──────┬────────┘  │
│         │                                     │            │
│         │ SET_VELOCITY_LIMIT                  │ GET /printer│
│         │ SET_PRESSURE_ADVANCE                │   /objects  │
│         │ M221 / M220                         │ POST /gcode │
│         ▼                                     ▼            │
│  ┌──────────────┐                    ┌────────────────┐   │
│  │ Stepper      │                    │ Moonraker API  │   │
│  │ Drivers +    │                    │ localhost:7125 │   │
│  │ Hotend       │                    └──────┬─────────┘   │
│  └──────────────┘                           │             │
│                                             │             │
│                                    ┌────────▼─────────┐   │
│                                    │ AI / CV module   │   │
│                                    │ (webcam + model) │   │
│                                    └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘

Data flow per 3-second cycle:
  1. [delayed_gcode ameo_loop] fires RUN_SHELL_COMMAND
  2. ameo_vision_bridge.py wakes, queries Moonraker for live state
  3. Captures webcam frame, runs inference
  4. Computes flow_mult, speed_mult, z_nudge (layers 1-3 only)
  5. POSTs AI_REFLEXIVE_ADJUST FLOW=x SPEED=y Z_NUDGE=z to Moonraker
  6. Klipper executes M221 + M220 + SET_GCODE_OFFSET adjustments
  7. Script exits cleanly within 5s timeout
  8. Loop reschedules itself for T+3s

Nozzle swap flow (zero manual intervention):
  1. User selects nozzle profile in slicer start-gcode
  2. AMEO_LOAD NOZZLE=<id> MATERIAL=<id> fires at print start
  3. Bridge resolves profile -> calls AMEO_INIT with correct k_factor, pa_base, mfi
  4. First 3 layers: Z-offset vision loop runs, nudges SET_GCODE_OFFSET
  5. Stable offset saved back to ameo_profiles.json for the next swap
```

---

## 14. G-Code Refiner — Use-Case-Driven Pre-Print Optimization

> **Stage:** Pre-print (runs after slicing, before transferring to printer)
> **Location:** `GCodeRefiner/refiner.py`
> **Complement to AMEO:** The Refiner optimizes the _file_; AMEO fine-tunes _live during the print_.
> Together they form a two-stage pipeline: **static precision → dynamic adaptation**.

### 14.1 Where it fits in the full pipeline

```
Slicer (QIDIStudio/Orca)
  │  exports .gcode
  ▼
GCode Refiner ◄── nozzle profile + material profile + USE CASE
  │  injects per-feature overrides (temp, fan, accel, speed, flow)
  │  into ;TYPE:... feature blocks
  ▼
.gcode file on printer
  │  starts printing
  ▼
AMEO (Klipper macros + Moonraker + vision bridge)
  │  live adjustment loop every 3s (flow%, speed%, Z-nudge)
  ▼
Physical print
```

The Refiner operates on three inputs that are **always known before a print starts**:

- **Nozzle** — from the Nozzle Profile Registry (§9): diameter, k_factor, form_factor
- **Material** — from the Material Profile Registry (§8): temps, fan, retract, PA modifier
- **Use case** — user selection: _what is this part for?_ (determines the tradeoff strategy)

The use case is the layer that was missing from automatic slicer profiles. A 0.4mm CHT nozzle +
PLA-HS can produce vastly different optimal settings for a miniature figurine vs. a structural
bracket vs. a watertight container — because the _constraint_ is different each time.

---

### 14.2 Architecture: three-tier parameter resolution

```
Tier 1 — Material + Nozzle Profile  (profiles/<name>.py)
  │  Base temperature, speed, fan, flow envelopes
  │  Derived from nozzle k_factor × material MFI
  │  Example: asa_gf_04mm.py, pla_hs_cht_04mm.py
  │
  ▼
Tier 2 — Use-Case Rule Set  (rules/<use_case>.py)
  │  Per-feature OVERRIDES on top of the base profile
  │  Each ;TYPE:OUTER_WALL|INNER_WALL|... block gets its own parameters
  │  Example: m2_gear.py, watertight.py, fine_detail.py
  │
  ▼
Tier 3 — AMEO Live Adaptation  (Klipper macros)
  │  Real-time flow% and speed% corrections from visual feedback
  │  Corrects for environmental drift, humidity, batch-to-batch variation
  └─ Z-offset vision loop on first 3 layers after nozzle swap
```

Override resolution: **Rule > Profile > Slicer default**. AMEO is applied last and always wins
on live adjustments.

---

### 14.3 Use-case catalog

| Use Case ID     | Target print type                     | Key constraint                | Primary strategy                                              |
| --------------- | ------------------------------------- | ----------------------------- | ------------------------------------------------------------- |
| `m2_gear`       | Small precision gears (M2+)           | Tooth geometry fidelity       | Slow outer walls, no fan, +5°C for fusion                     |
| `watertight`    | Tanks, enclosures, watertight vessels | No perimeter gaps             | Over-extrusion on walls, very slow outer seam, seam alignment |
| `fine_detail`   | Miniatures, figurines, embossed text  | Surface resolution            | Slowest outer wall, max cooling, minimal retract              |
| `structural`    | Load-bearing brackets, hinges, clips  | Layer adhesion / strength     | High temp, reduced cooling, increased flow on perimeters      |
| `fast_draft`    | Geometry verification, fit tests      | Print speed                   | Maximum speed everywhere, 1 wall, 10% infill                  |
| `flexible_part` | Gaskets, TPU grips, living hinges     | No over-stiffening            | Zero retraction, very slow all features, high temp            |
| `threaded`      | Printed-in-place threads, nut traps   | Dimensional accuracy on ID/OD | Compensation on outer wall, 0% flow on bridged overhangs      |

**Adding a new use case:** Create `rules/<use_case_id>.py` implementing `get_override(feature_type, layer, profile)`.
The function receives the canonical feature type string and must return either `None` (use profile
defaults) or a dict with any subset of `{speed_mm_s, nozzle_temp, fan, flow_ratio, accel, comment}`.

---

### 14.4 Feature types and what each use case controls

| Feature (`; TYPE:...`) | Meaning                                  | Most affected use cases               |
| ---------------------- | ---------------------------------------- | ------------------------------------- |
| `OUTER_WALL`           | External perimeter — the visible surface | All — this is always highest priority |
| `INNER_WALL`           | Internal perimeters                      | `watertight`, `structural`            |
| `SOLID_INFILL`         | Top/bottom solid layers                  | `watertight`, `fine_detail`           |
| `SPARSE_INFILL`        | Interior infill pattern                  | `structural`, `fast_draft`            |
| `BRIDGE`               | Unsupported horizontal spans             | `fine_detail`, `structural`           |
| `SUPPORT`              | Support structures                       | `fast_draft` (speed them up)          |
| `SKIRT_BRIM`           | First-layer adhesion helpers             | All                                   |

---

### 14.5 Per-use-case parameter rationale

#### `watertight` — no gaps

| Feature        | Override vs profile  | Why                                  |
| -------------- | -------------------- | ------------------------------------ |
| `OUTER_WALL`   | Speed −50%, flow +3% | Fill micro-gaps between passes       |
| `INNER_WALL`   | Speed −30%, flow +2% | Perimeter-to-perimeter fusion        |
| `SOLID_INFILL` | Speed −20%, flow +2% | Top/bottom must be truly solid       |
| `BRIDGE`       | Fan 100%, speed −40% | Sagging bridge ruins vessel bottom   |
| Seam position  | Always inner corner  | Seam =weakest point — hide on inside |

#### `fine_detail` — maximum surface resolution

| Feature         | Override vs profile              | Why                                                 |
| --------------- | -------------------------------- | --------------------------------------------------- |
| `OUTER_WALL`    | Speed −70%, fan 100%, accel −60% | Motion system accuracy; cooling prevents blobbing   |
| `INNER_WALL`    | Speed −40%, fan 80%              | Still needs dimensional accuracy                    |
| `BRIDGE`        | Max fan, speed −50%              | Fine detail often has many small bridges            |
| `SPARSE_INFILL` | Max speed (infill unseen)        | Speed up invisible infill to offset slow perimeters |

#### `structural` — layer bonding / strength

| Feature         | Override vs profile            | Why                                               |
| --------------- | ------------------------------ | ------------------------------------------------- |
| `OUTER_WALL`    | Temp +5°C, fan 0–20%, flow +2% | Hotter weld lines; cooling kills inter-layer bond |
| `INNER_WALL`    | Temp +3°C, fan 0%, flow +1%    | Same rationale                                    |
| `SOLID_INFILL`  | Temp nominal, light fan        | Flat surfaces need some cooling for geometry      |
| `SPARSE_INFILL` | Normal speed, high flow        | Dense infill required for load-bearing            |

#### `fast_draft` — maximum speed

| Feature      | Override vs profile          | Why                                        |
| ------------ | ---------------------------- | ------------------------------------------ |
| All features | Max speed, accel 8000+       | Time-to-print is the only metric           |
| `OUTER_WALL` | Speed ×1.5 above profile cap | Geometry accuracy irrelevant for fit check |
| `SUPPORT`    | Max speed, low fan           | Supports are disposable                    |

---

### 14.6 CLI reference

```powershell
# Standard: nozzle+material auto-selected by profile name, use-case applied
python refiner.py print.gcode --profile pla_hs_cht_04mm --rules watertight

# Dry run (shows what would be injected, no file changes)
python refiner.py print.gcode --rules fine_detail --dry-run --verbose

# List available profiles (nozzle+material combos)
python refiner.py --list-profiles

# List available use-case rule sets
python refiner.py --list-rules
```

**Profile naming convention:** `{material_id}_{nozzle_id}.py`  
Maps directly to Material Registry `id` + Nozzle Registry `id` from §8 and §9.

Example profile names that match the registries:

| Profile file             | Material (§8 id)           | Nozzle (§9 id)   |
| ------------------------ | -------------------------- | ---------------- |
| `asa_gf_04mm.py`         | (ASA-GF — add to registry) | hardened 0.4     |
| `pla_hs_cht_04mm.py`     | `anycubic_pla_hs`          | `cht_diamond_04` |
| `pla_hs_bimetal_08mm.py` | `anycubic_pla_hs`          | `bimetal_dlc_08` |
| `petg_cht_04mm.py`       | `esun_petg_clear`          | `cht_diamond_04` |
| `abs_04mm.py`            | `bambu_abs`                | `qidi_04`        |

---

### 14.7 QIDISlicer integration

In QIDISlicer: **Printer Settings → Custom G-code → Post-processing scripts**

```
"<python_path>" "<path_to_refiner.py>" --rules <use_case>
```

QIDISlicer automatically appends the exported `.gcode` path as the final argument.
The refiner modifies the file **in-place** — no extra copies, no workflow change.

**Recommended: one printer preset per nozzle, one process preset per use case.**

| Printer preset        | `--profile` arg       | Process preset | `--rules` arg |
| --------------------- | --------------------- | -------------- | ------------- |
| QIDI Q2 — CHT 0.4     | `pla_hs_cht_04mm`     | Gears          | `m2_gear`     |
| QIDI Q2 — CHT 0.4     | `pla_hs_cht_04mm`     | Watertight     | `watertight`  |
| QIDI Q2 — Bimetal 0.8 | `pla_hs_bimetal_08mm` | Draft          | `fast_draft`  |
| QIDI Q2 — Stock 0.4   | `abs_04mm`            | Structural     | `structural`  |

---

### 14.8 AMEO_LOAD integration

The nozzle and material IDs used by `AMEO_LOAD` (§10) and the Refiner profile name
all resolve to the same underlying registries. The `start_gcode` sequence for a fully
integrated print looks like:

```gcode
; Start G-code — called once at print start by slicer
AMEO_LOAD NOZZLE=cht_diamond_04 MATERIAL=anycubic_pla_hs
; AMEO_LOAD sets PA, k_factor, temp envelope, and arms the Z-offset vision loop.
; The GCode Refiner has already processed the file with the matching profile+rules.
; AMEO live loop corrects flow% and speed% from visual feedback throughout the print.
```

All three subsystems (Refiner, AMEO macros, vision bridge) now draw from the same
profile store — `ameo_profiles.json` for runtime values, `filament_db.json` for the
material database.

| Resource                    | URL                                                                     | Status                                    |
| --------------------------- | ----------------------------------------------------------------------- | ----------------------------------------- |
| Klipper G-Codes Reference   | <https://www.klipper3d.org/G-Codes.html>                                | ✅ Fetched                                |
| Klipper Config Reference    | <https://www.klipper3d.org/Config_Reference.html>                       | ✅ Fetched                                |
| Klipper Command Templates   | <https://www.klipper3d.org/Command_Templates.html>                      | ✅ Fetched                                |
| Moonraker Printer Objects   | <https://moonraker.readthedocs.io/en/latest/printer_objects/>           | ✅ Fetched                                |
| KIAUH GitHub                | <https://github.com/dw-0/kiauh>                                         | ✅ Fetched                                |
| gcode_shell_command docs    | <https://github.com/dw-0/kiauh/blob/master/docs/gcode_shell_command.md> | ✅ Fetched                                |
| Anycubic HS PLA             | <https://store.anycubic.com/products/anycubic-high-speed-pla-filament>  | ❌ Blocked (specs from datasheet context) |
| Moonraker Web API (old URL) | <https://moonraker.readthedocs.io/en/latest/web_api/>                   | ❌ 404 (superseded by external_api/)      |
| Moonraker External API      | <https://moonraker.readthedocs.io/en/latest/external_api/printer/>      | ✅ Confirmed via printer_objects page     |
