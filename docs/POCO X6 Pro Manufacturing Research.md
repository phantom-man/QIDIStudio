# Precision Component Manufacturing: Tolerances, Materials, and Metrology

A technical reference for manufacturing analysis of precision consumer electronics enclosures — covering tolerance stack-up, material selection, surface finish specifications, and dimensional verification methods.

---

## I. Mechanical Tolerancing Standards

### 1.1 Tolerance Stack-Up Analysis

For assembled components, dimensional chain analysis determines if parts will assemble without interference. The **worst-case** method:

$$T_{asm} = \sum_{i=1}^n T_i$$

The **statistical (RSS)** method (assuming normal distributions, $\pm 3\sigma$):

$$T_{asm} = \sqrt{\sum_{i=1}^n T_i^2}$$

For a typical enclosure assembly with 6 independent dimensions each at $\pm 0.05$ mm:
- Worst-case: $T_{asm} = 6 \times 0.05 = \pm 0.30$ mm
- RSS: $T_{asm} = \sqrt{6} \times 0.05 = \pm 0.12$ mm

Statistical tolerance is 2.5× tighter and is preferred for high-volume production.

### 1.2 IT Grade Reference

ISO 286-1 defines International Tolerance (IT) grades:

| IT Grade | Application | Tolerance (for 100 mm dim.) |
|---------|------------|---------------------------|
| IT5 | Precision bearing fits | 15 µm |
| IT6 | Standard bearing fits | 22 µm |
| IT7 | General precision machining | 35 µm |
| IT8 | Consumer electronics assembly | 54 µm |
| IT9 | Sheet metal, injection mold | 87 µm |
| IT11 | Die casting | 220 µm |

---

## II. Material Properties for Precision Enclosures

### 2.1 Structural Materials Comparison

| Material | Density (g/cm³) | E (GPa) | σ_y (MPa) | CTE (µm/m·K) | Cost |
|---------|----------------|---------|----------|-------------|------|
| Al 6061-T6 | 2.70 | 69 | 276 | 23.6 | Low |
| Al 7075-T6 | 2.81 | 72 | 503 | 23.4 | Medium |
| Mg AZ31B | 1.77 | 45 | 220 | 26.0 | Medium |
| Titanium Ti-6Al-4V | 4.43 | 114 | 880 | 8.6 | High |
| Stainless 316L | 7.99 | 193 | 290 | 16.0 | Medium |
| CFRP (UD, 0°) | 1.60 | 135 | 1500 | -0.5 | Very High |

### 2.2 Thermal Expansion Mismatch

When bonding dissimilar materials (e.g. aluminum frame + glass back), thermal mismatch stress at the interface:

$$\sigma_{thermal} = \frac{E_1 E_2}{E_1 + E_2} \cdot (\alpha_1 - \alpha_2) \cdot \Delta T$$

For Al/glass ($E_{Al}=69$ GPa, $E_{glass}=72$ GPa, $\alpha_{Al}=23.6$, $\alpha_{glass}=8.5$ µm/m·K) at $\Delta T = 50$ K:

$$\sigma = \frac{69 \times 72}{69 + 72} \cdot (23.6 - 8.5) \times 10^{-6} \times 50 = 26.4 \text{ MPa}$$

This exceeds glass flexural strength (~25 MPa) for thick adhesive layers — explains edge delamination in thermal cycling.

---

## III. Surface Finish Specifications

### 3.1 ISO Ra Values

| Ra (µm) | Process | Application |
|---------|---------|------------|
| 0.05 | Super-finishing, honing | Optical surfaces |
| 0.2 | Precision grinding | Bearing races |
| 0.4 | Fine turning, precision milling | Display glass |
| 0.8 | Standard turning | Chassis exterior |
| 1.6 | CNC milling | Interior structural walls |
| 3.2 | Rough machining | Hidden interfaces |

### 3.2 Shot Peening and Anodizing Stack

A typical Al enclosure surface processing sequence:

```
CNC mill (Ra 0.8) → Tumble deburr → Sand blast (Ra 1.6) →
→ Shot peen (Almen A 0.006-0.010") → Polish (Ra 0.4) →
→ Type III anodize (15-25 µm) → Dye + seal → Laser etch
```

Anodize layer adds $8-15$ µm per side — must be accounted for in nominal dimensions.

---

## IV. Dimensional Inspection Methods

```python
import numpy as np
from scipy.spatial import KDTree

def measure_dimension(
    point_cloud: np.ndarray,  # (N, 3) measured points
    nominal_mesh_vertices: np.ndarray,  # (M, 3) CAD reference
) -> dict[str, float]:
    """
    Compute statistical dimensional deviation between scan and CAD.
    Returns RMSE, max deviation, and 95th-percentile deviation.
    """
    tree = KDTree(nominal_mesh_vertices)
    dists, _ = tree.query(point_cloud)
    return {
        "rmse_mm": float(np.sqrt(np.mean(dists**2))),
        "max_mm": float(dists.max()),
        "p95_mm": float(np.percentile(dists, 95)),
        "p50_mm": float(np.percentile(dists, 50)),
    }
```

---

## V. Manufacturing Capability Index

The process capability index $C_{pk}$ measures how well a manufacturing process meets tolerances:

$$C_{pk} = \min\left(\frac{\mu - LSL}{3\sigma}, \frac{USL - \mu}{3\sigma}\right)$$

Acceptable: $C_{pk} \geq 1.33$ ($\leq 63$ ppm defect rate).

For dimensional control on modern CNC: typical $C_{pk} = 1.5-2.0$, giving $0.34-3.4$ ppm defect rates.

---

## References

- Evans, C.J. (1989). Precision Engineering: An Evolutionary View. Cranfield Press.
- ISO 286-1:2010. Geometrical product specifications — Limits and fits.
- ISO 1302:2002. Surface texture indication on drawings.
- ASM International (2001). *Metals Handbook*, Vol. 2: Properties and Selection: Nonferrous Alloys.
