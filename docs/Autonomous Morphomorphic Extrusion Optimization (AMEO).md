# Autonomous Morphodynamic Extrusion Optimization (AMEO)

AMEO is a closed-loop extrusion control system that fuses real-time bead width measurement (computer vision), hotend current sensing, and thermal monitoring to continuously adjust flow rate, temperature, and velocity — maintaining dimensional accuracy without slicer re-slicing.

---

## I. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     AMEO Controller                     │
│                                                         │
│  ┌──────────┐   ΔE, ΔV   ┌────────────────────┐        │
│  │  Planner │ ─────────> │ PID Cascade         │        │
│  │ (G-code) │ <───────── │ flow/temp/vel       │        │
│  └──────────┘  feedback  └───────┬─────────────┘        │
│                                  │ commands              │
│                           ┌──────▼──────────┐           │
│                           │  Klipper/Duet   │           │
│                           │  (G-code exec)  │           │
│                           └──────┬──────────┘           │
│  Sensors                         │                      │
│  ┌──────────────┐       ┌────────▼──────────┐           │
│  │ Camera (USB) │──────>│  SensorFusion     │           │
│  │ Current ADC  │──────>│  (state estimate) │           │
│  │ Thermistors  │──────>└───────────────────┘           │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

---

## II. State Machine

```python
from enum import Enum, auto
from dataclasses import dataclass, field

class AMEOState(Enum):
    IDLE = auto()
    CALIBRATING = auto()
    PRINTING = auto()
    ANOMALY_DETECTED = auto()
    PAUSED = auto()
    RECOVERY = auto()
    FAULT = auto()

@dataclass
class AMEOSystemState:
    mode: AMEOState = AMEOState.IDLE
    bead_width_mm: float = 0.0
    target_width_mm: float = 0.45
    temperature_c: float = 210.0
    target_temp_c: float = 210.0
    flow_multiplier: float = 1.0
    velocity_mm_s: float = 60.0
    consecutive_anomalies: int = 0
    history: list[dict] = field(default_factory=list)
```

---

## III. Bead Width Measurement (Computer Vision)

```python
import cv2
import numpy as np

def measure_bead_width(
    frame: np.ndarray,
    roi: tuple[int, int, int, int],   # (x, y, w, h)
    pixel_to_mm: float = 0.042,       # calibrated: mm per pixel
    threshold: int = 60,
) -> float:
    """
    Estimate bead width from a grayscale camera frame.
    Uses horizontal bright-region width in the ROI.
    Returns width in mm.
    """
    x, y, w, h = roi
    crop = frame[y:y+h, x:x+w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    # Width = mean width of bright horizontal stripes
    row_widths = []
    for row in binary:
        nonzero = np.where(row > 0)[0]
        if len(nonzero) > 2:
            row_widths.append(nonzero[-1] - nonzero[0])
    if not row_widths:
        return 0.0
    return float(np.median(row_widths)) * pixel_to_mm
```

---

## IV. PID Controller

```python
@dataclass
class PIDConfig:
    Kp: float
    Ki: float
    Kd: float
    output_min: float
    output_max: float

class PIDController:
    def __init__(self, cfg: PIDConfig):
        self.cfg = cfg
        self._integral = 0.0
        self._prev_error = 0.0

    def step(self, setpoint: float, measurement: float, dt: float) -> float:
        """Compute PID output for one timestep."""
        error = setpoint - measurement
        self._integral += error * dt
        derivative = (error - self._prev_error) / dt if dt > 0 else 0.0
        self._prev_error = error

        output = (
            self.cfg.Kp * error
            + self.cfg.Ki * self._integral
            + self.cfg.Kd * derivative
        )
        return float(np.clip(output, self.cfg.output_min, self.cfg.output_max))
```

---

## V. Anomaly Detection

Three-tier anomaly hierarchy:

| Tier | Trigger | Action |
|------|---------|--------|
| WARNING | $|w - w^*| > 0.1$ mm for 3 consecutive frames | Adjust flow multiplier |
| ANOMALY | $|w - w^*| > 0.2$ mm for 8 frames | Pause + notify |
| FAULT | $|w - w^*| > 0.4$ mm OR temp excursion >15 °C | Emergency stop |

```python
def detect_anomaly(state: AMEOSystemState) -> AMEOState:
    error = abs(state.bead_width_mm - state.target_width_mm)
    if error > 0.4:
        return AMEOState.FAULT
    if error > 0.2 and state.consecutive_anomalies >= 8:
        return AMEOState.ANOMALY_DETECTED
    if error > 0.1:
        return AMEOState.PRINTING  # Adjust flow but continue
    return AMEOState.PRINTING
```

---

## References

- Coogan, T.J. & Kazmer, D.O. (2020). In-line rheological monitoring of FDM. *Polym. Eng. Sci.*
- Sitthi-Amorn, P. et al. (2015). MultiFab: vision-aware multi-material 3D printing. *ACM Trans. Graph.*
- Faes, M. et al. (2019). Process monitoring in FDM via machine vision. *Optik*, 178, 104–115.
