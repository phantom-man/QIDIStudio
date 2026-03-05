# G-Code Failure Mode Analysis: A Physics-Informed Taxonomy

Systematic classification and root-cause analysis of G-code execution failures in FDM printing — mapping symptom patterns to physical mechanisms, providing detection algorithms and corrective G-code sequences.

---

## I. Failure Mode Taxonomy

### 1.1 Class I: Extrusion Failures

Extrusion failures arise from volumetric flow errors between commanded and actual output.

| Failure Mode | Symptom | Root Cause | Detection Signal |
|-------------|---------|-----------|-----------------|
| Under-extrusion | Lines too thin, gaps | Back-pressure > nozzle flow capacity | Width < 0.85× target |
| Over-extrusion | Blobs, seams | E-steps too high, retraction absent | Width > 1.15× target |
| Filament jam | No extrusion | Heat creep, partial clog | Extruder current spike |
| Grinding | Clicking extruder | Idler pressure too high, brittle filament | Vibration sensor spike |
| Wet filament | Popping, bubbles | Moisture in hygroscopic polymers | Mid-line width variance |

### 1.2 Class II: Thermal Failures

| Failure Mode | Symptom | Root Cause |
|-------------|---------|-----------|
| Heat creep | Progressive jam | Insufficient heatsink cooling, too slow print |
| Warping | Layer separation / lifting | Bed temp too low, no enclosure |
| Layer delamination | Layer splitting | Too much cooling fan, low temp |
| Stringing | Hair between parts | Retraction insufficient, temp too high |

---

## II. Volumetric Flow Error Model

The commanded volumetric flow rate $Q_{cmd}$:

$$Q_{cmd} = v_{print} \cdot h \cdot w$$

The actual extrusion rate $Q_{act}$ depends on the melt pressure dynamics:

$$Q_{act}(t) = Q_{cmd}(t) - \frac{\pi r_n^4}{8 \mu L_n} P_{melt}(t)$$

where $P_{melt}$ is the melt zone pressure from backpressure, decaying as:

$$\dot{P}_{melt} = B \left(Q_{cmd} - Q_{act}\right), \quad B = \frac{8 \mu}{\pi r_n^4 V_{melt}}$$

This explains the characteristic **"pressure advance"** lag at speed transitions.

### 2.1 Pressure Advance Calibration G-code

```gcode
; Klipper pressure advance sweep
SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=1 ACCEL=500
SET_PRESSURE_ADVANCE ADVANCE=0  ; start at 0
; Print a test tower, stepping PA by 0.005 per layer:
; Layer 1-10: PA = 0.000–0.045 (set in slicer variable)
```

Optimal PA value: corners show no bulge AND no pull-back gap.

---

## III. Warp Prediction Model

Corner warp displacement $\delta$ scales with:

$$\delta \propto \alpha \cdot \Delta T \cdot L^2 / (E \cdot t^2)$$

where $L$ is the part footprint dimension, $t$ is wall thickness, and $\Delta T = T_{melt} - T_{glass}$.

For ABS: $\alpha = 7 \times 10^{-5}$ K$^{-1}$, $\Delta T \approx 100$ K — enclosure mandatory for parts $> 50$ mm.

```python
import numpy as np

def warp_risk_index(
    material: str,
    footprint_mm: float,
    wall_thickness_mm: float,
    bed_temp_C: float,
) -> float:
    """
    Returns warp risk index 0-1. Values > 0.5 require enclosure.
    Based on linearized thermal-mechanical plate theory.
    """
    CTE = {"PLA": 6.8e-5, "ABS": 7.0e-5, "PETG": 5.9e-5, "PA12": 7.8e-5}
    T_glass = {"PLA": 60, "ABS": 105, "PETG": 80, "PA12": 170}
    alpha = CTE.get(material, 7e-5)
    T_g = T_glass.get(material, 80)
    dT = max(T_g - bed_temp_C, 0)
    risk = alpha * dT * (footprint_mm ** 2) / (200e3 * wall_thickness_mm ** 2)
    return float(min(risk * 1e-2, 1.0))
```

---

## IV. G-Code Diagnostic Scanner

```python
import re
from dataclasses import dataclass, field

@dataclass
class GCodeAudit:
    filename: str
    missing_fan_delay: bool = False
    retraction_distance: float = 0.0
    max_flow_mm3s: float = 0.0
    pressure_advance_set: bool = False
    warnings: list[str] = field(default_factory=list)

def audit_gcode(path: str) -> GCodeAudit:
    audit = GCodeAudit(filename=path)
    e_prev = 0.0
    with open(path) as f:
        for line in f:
            line = line.strip()
            # Detect retraction
            m = re.match(r"G1.*E(-?\d+\.?\d*)", line)
            if m:
                e = float(m.group(1))
                if e - e_prev < -0.5:
                    audit.retraction_distance = max(abs(e - e_prev), audit.retraction_distance)
                e_prev = e
            # Check pressure advance
            if "SET_PRESSURE_ADVANCE" in line:
                audit.pressure_advance_set = True
    if audit.retraction_distance < 0.2:
        audit.warnings.append("Retraction too short — stringing likely")
    if not audit.pressure_advance_set:
        audit.warnings.append("Pressure advance not configured")
    return audit
```

---

## V. Failure Detection Priority Matrix

| Failure Class | Detect via | Severity | Auto-Recoverable |
|--------------|-----------|----------|-----------------|
| Under-extrusion | Camera (bead width) | High | Yes (flow +5%) |
| Over-extrusion | Camera (bead width) | Medium | Yes (flow -5%) |
| Jam | Motor current | Critical | No (pause+manual) |
| Warp | Z-probe deviation | High | No (abort) |
| Heat creep | Temp sensor trend | Critical | Partial (speed -20%) |
| Stringing | Post-print scan | Low | No (retune) |

---

## References

- Bellini, A. et al. (2004). Liquefier dynamics in FDM. *Journal of Manufacturing Science and Engineering*, 126(2).
- Coogan, T.J. & Kazmer, D.O. (2020). Bond and part strength in FDM. *Rapid Prototyping Journal*, 23(3).
- Klipper Documentation: Pressure Advance. klipper3d.org/Pressure_Advance.html.
- Turner, B.N. et al. (2014). A review of melt extrusion additive manufacturing. *Rapid Prototyping J.* 20(3).
