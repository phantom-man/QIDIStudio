# G-Code Volumetric Flow Auditing

A systematic framework for auditing G-code files for volumetric flow correctness — parsing extrusion commands, computing per-segment flow rates, detecting flow violations, and generating diagnostic reports.

---

## I. G-Code Extrusion Model

### 1.1 Absolute vs Relative Extrusion

G-code supports two extrusion modes:
- `M82` (absolute): `E` values are cumulative; $\Delta E = E_{curr} - E_{prev}$
- `M83` (relative): `E` values are already $\Delta E$ per move

The volumetric flow rate for a print move `G1 X{x} Y{y} F{f} E{e}`:

$$Q = \frac{\Delta E \cdot \pi r_f^2}{\Delta t}, \quad \Delta t = \frac{L}{v}$$

where $r_f$ is the filament radius (typically 0.9 mm for 1.75 mm filament), $L = \sqrt{\Delta x^2 + \Delta y^2}$ is the XY move length, and $v = F/60$ (mm/s, F is mm/min).

Simplified volume flow in mm³/s:

$$Q_{mm^3/s} = \Delta E \cdot \pi (0.9)^2 \cdot v / L$$

### 1.2 Commanded Bead Volume

The theoretically deposited volume per move:

$$V_{bead} = h \cdot w \cdot L$$

where $h$ = layer height and $w$ = line width. The extrusion multiplier $EM$ = $\Delta E \cdot \pi r_f^2 / (h \cdot w)$. Correct printing: $EM \in [0.95, 1.05]$.

---

## II. Parser Implementation

```python
import re
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

@dataclass
class GCodeMove:
    x: float
    y: float
    z: float
    e_abs: float      # Absolute filament position (mm)
    feed_rate: float  # mm/min
    delta_e: float    # Extrusion delta for this move
    length: float     # XY distance of move
    flow_mm3s: float  # Volumetric flow rate (mm³/s)

FILAMENT_RADIUS = 0.9  # mm (for 1.75 mm dia)
FILAMENT_AREA = math.pi * FILAMENT_RADIUS ** 2

def parse_gcode(path: str | Path) -> Generator[GCodeMove, None, None]:
    """
    Parse G-code file, yield GCodeMove records for all G1 print moves.
    Handles M82/M83, G90/G91 modes.
    """
    x = y = z = e = 0.0
    feed = 1500.0
    relative_e = False

    for line in Path(path).read_text().splitlines():
        line = line.split(";")[0].strip()
        if not line:
            continue

        if line == "M82":
            relative_e = False
        elif line == "M83":
            relative_e = True
        elif line.startswith("G1 ") or line.startswith("G1\t"):
            params: dict[str, float] = {}
            for m in re.finditer(r"([XYZEF])(-?\d+\.?\d*)", line):
                params[m.group(1)] = float(m.group(2))

            new_x = params.get("X", x)
            new_y = params.get("Y", y)
            new_z = params.get("Z", z)
            new_feed = params.get("F", feed)

            if "E" in params:
                raw_e = params["E"]
                delta_e = raw_e if relative_e else (raw_e - e)
                new_e = e + delta_e if not relative_e else e + raw_e

                dx, dy = new_x - x, new_y - y
                length = math.hypot(dx, dy)

                if length > 0.01 and delta_e > 0.001:
                    v_mms = new_feed / 60.0
                    dt = length / v_mms
                    flow = delta_e * FILAMENT_AREA / dt
                    yield GCodeMove(
                        x=new_x, y=new_y, z=new_z,
                        e_abs=new_e, feed_rate=new_feed,
                        delta_e=delta_e, length=length,
                        flow_mm3s=flow,
                    )
                e = new_e

            x, y, z, feed = new_x, new_y, new_z, new_feed
```

---

## III. Audit Report Generation

```python
@dataclass
class FlowAuditReport:
    filename: str
    mean_flow_mm3s: float
    max_flow_mm3s: float
    min_flow_mm3s: float
    over_flow_count: int   # moves > Q_max
    under_flow_count: int  # moves < Q_min (excluding retracts)
    total_moves: int
    warnings: list[str] = field(default_factory=list)

def audit_flow(
    path: str,
    q_max: float = 20.0,   # mm³/s: max safe flow for most hotends
    q_min: float = 0.5,    # mm³/s: below this is likely under-extrusion
) -> FlowAuditReport:
    flows = [m.flow_mm3s for m in parse_gcode(path)]
    if not flows:
        return FlowAuditReport(path, 0, 0, 0, 0, 0, 0, ["No extrusion moves found"])

    import numpy as np
    arr = np.array(flows)
    over = int((arr > q_max).sum())
    under = int((arr < q_min).sum())
    report = FlowAuditReport(
        filename=path,
        mean_flow_mm3s=float(arr.mean()),
        max_flow_mm3s=float(arr.max()),
        min_flow_mm3s=float(arr.min()),
        over_flow_count=over,
        under_flow_count=under,
        total_moves=len(flows),
    )
    if over > 0:
        report.warnings.append(f"{over} moves exceed Q_max={q_max} mm³/s — clog risk")
    if under > 10:
        report.warnings.append(f"{under} moves below Q_min={q_min} — possible under-extrusion")
    return report
```

---

## IV. Typical Hotend Flow Limits

| Hotend Type | $Q_{max}$ (mm³/s) | Notes |
|------------|------------------|----|
| Stock brass 0.4 mm | 8 | PLA at 215 °C |
| Hardened steel 0.4 mm | 6 | Abrasive materials, reduced bore |
| Volcano 0.6 mm | 18 | Extended melt zone |
| CHT 0.4 mm | 25 | 3-hole insert |
| Dragon HF 0.4 mm | 30 | High-flow design |
| Rapido HF 0.4 mm | 35 | Industry-leading flow |

---

## References

- RepRap Wiki: G-Code Reference. reprap.org/wiki/G-code.
- Bellini, A. et al. (2004). Liquefier dynamics in FDM. *J. Manuf. Sci. Eng.* 126(2).
- Coogan, T.J. & Kazmer, D.O. (2017). Healing simulation for bond prediction in FDM. *Additive Manufacturing*, 15, 25-34.
