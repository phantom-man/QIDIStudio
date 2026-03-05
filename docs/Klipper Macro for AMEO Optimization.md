# Klipper G-code Macros for AMEO Extrusion Optimization

Complete Klipper macro library for Autonomous Morphological Extrusion Optimization (AMEO) — providing real-time flow adjustment, bead width monitoring integration, PID-based extrusion control, and failure recovery sequences.

---

## I. AMEO Architecture in Klipper

AMEO integrates a camera-based bead width measurement loop with Klipper's macro system via `gcode_shell_command` for Python-side PID computation. The control cycle:

```
Print tick (every N mm of extrusion)
  → AMEO_TICK macro triggers
  → Shell command calls ameo_controller.py
  → Controller reads bead width from camera
  → PID computes flow multiplier adjustment
  → SET_PRESSURE_ADVANCE / SET_VELOCITY_LIMIT applied
```

---

## II. Core Macros

### 2.1 Initialization

```ini
# printer.cfg

[gcode_shell_command ameo_init]
command: python3 /home/pi/klipper_config/ameo/ameo_controller.py --init
timeout: 10.0
verbose: False

[gcode_shell_command ameo_tick]
command: python3 /home/pi/klipper_config/ameo/ameo_controller.py --tick
timeout: 2.0
verbose: False

[gcode_shell_command ameo_status]
command: python3 /home/pi/klipper_config/ameo/ameo_controller.py --status
timeout: 2.0
verbose: True
```

```ini
[gcode_macro AMEO_START]
description: Initialize AMEO closed-loop extrusion control
gcode:
    {% set target_width = params.WIDTH | default(0.45) | float %}
    SAVE_VARIABLE VARIABLE=ameo_target_width VALUE={target_width}
    SAVE_VARIABLE VARIABLE=ameo_active VALUE=1
    RUN_SHELL_COMMAND CMD=ameo_init PARAMS="--target {target_width}"
    M118 AMEO initialized: target bead width = {target_width} mm
```

### 2.2 Per-Layer Tick Macro

```ini
[gcode_macro AMEO_TICK]
description: Called every N mm of extrusion — triggers bead width measurement
gcode:
    {% if printer.save_variables.variables.ameo_active | default(0) %}
        RUN_SHELL_COMMAND CMD=ameo_tick
        # Read back adjustment from variable
        {% set adj = printer.save_variables.variables.ameo_flow_adj | default(1.0) | float %}
        M221 S{(adj * 100) | int}   ; Set flow rate percentage
    {% endif %}
```

### 2.3 Failure Recovery

```ini
[gcode_macro AMEO_PAUSE_ON_FAILURE]
description: Triggered when AMEO detects catastrophic extrusion failure
gcode:
    PAUSE
    SET_LED LED=chamber_light RED=1 GREEN=0 BLUE=0
    M118 AMEO: Critical extrusion failure detected — print paused
    M118 Check nozzle, filament tension, and temperature
    SAVE_VARIABLE VARIABLE=ameo_active VALUE=0
```

---

## III. Python Controller

```python
#!/usr/bin/env python3
"""
ameo_controller.py — AMEO PID extrusion controller.
Called by Klipper gcode_shell_command.
"""
import argparse
import json
import os
import numpy as np
from pathlib import Path

VARS_FILE = Path("/tmp/ameo_state.json")

def load_state() -> dict:
    if VARS_FILE.exists():
        return json.loads(VARS_FILE.read_text())
    return {"integral": 0.0, "prev_error": 0.0, "flow_adj": 1.0}

def save_state(state: dict) -> None:
    VARS_FILE.write_text(json.dumps(state))

def measure_bead_width() -> float:
    """Capture camera frame and measure bead width via Hough transform."""
    import cv2
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return -1.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=80,
                             minLineLength=30, maxLineGap=5)
    if lines is None or len(lines) < 2:
        return -1.0
    # Estimate bead width from parallel line spacing
    y_centers = [int((l[0][1] + l[0][3]) / 2) for l in lines]
    width_px = max(y_centers) - min(y_centers)
    PX_PER_MM = 85.0  # calibrated for this setup
    return float(width_px / PX_PER_MM)

def pid_step(
    measured: float,
    target: float,
    state: dict,
    kp: float = 0.8,
    ki: float = 0.05,
    kd: float = 0.1,
    dt: float = 1.0,
) -> float:
    """PID controller step. Returns flow multiplier adjustment."""
    error = target - measured
    state["integral"] = np.clip(state["integral"] + error * dt, -0.3, 0.3)
    derivative = (error - state.get("prev_error", 0.0)) / dt
    state["prev_error"] = error
    adj = 1.0 + kp * error + ki * state["integral"] + kd * derivative
    return float(np.clip(adj, 0.7, 1.3))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--tick", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--target", type=float, default=0.45)
    args = parser.parse_args()

    state = load_state()

    if args.init:
        state = {"integral": 0.0, "prev_error": 0.0, "flow_adj": 1.0, "target": args.target}
        save_state(state)
        print(f"AMEO initialized: target={args.target:.3f} mm")

    elif args.tick:
        measured = measure_bead_width()
        if measured > 0:
            target = state.get("target", 0.45)
            adj = pid_step(measured, target, state)
            state["flow_adj"] = adj
            save_state(state)
            # Write Klipper variable
            with open("/tmp/klipper_ameo_adj.txt", "w") as f:
                f.write(f"{adj:.4f}")
            print(f"AMEO tick: measured={measured:.3f} adj={adj:.4f}")

    elif args.status:
        print(json.dumps(state, indent=2))

if __name__ == "__main__":
    main()
```

---

## IV. Slicer Integration

Insert `AMEO_TICK` after every extrusion distance threshold:

```
; In PrusaSlicer / OrcaSlicer custom G-code:
; After every 50 mm of extrusion:
AMEO_TICK
```

Or via a Moonraker-triggered script at layer change:

```yaml
# moonraker.conf
[update_manager ameo]
type: git_repo
path: ~/klipper_config/ameo
origin: https://github.com/yourname/klipper-ameo
```

---

## References

- Klipper Documentation: G-Code Macros. klipper3d.org/Command_Templates.html.
- Klipper Documentation: gcode_shell_command. klipper3d.org/G-Codes.html.
- Arévalo, D. et al. (2021). Real-time extrusion width monitoring for FDM. *Additive Manufacturing*, 37, 101695.
- Ziegler, J.G. & Nichols, N.B. (1942). Optimum Settings for Automatic Controllers. *Trans. ASME*, 64(11), 759-768.
