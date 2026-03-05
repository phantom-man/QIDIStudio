# Thermal Dissipation Design: Non-Euclidean Surface Topology

A rigorous treatment of heat transfer optimization on complex curved surfaces — covering gyroid minimal surface geometry, topology-informed fin design, and differential-geometric heat flow analysis.

---

## I. Theoretical Framework

### 1.1 Heat Equation on Riemannian Manifolds

For a surface $\mathcal{M}$ embedded in $\mathbb{R}^3$ with metric tensor $g_{ij}$, the heat equation is:

$$\frac{\partial u}{\partial t} = \Delta_{\mathcal{M}} u$$

where $\Delta_{\mathcal{M}}$ is the **Laplace-Beltrami operator**:

$$\Delta_{\mathcal{M}} f = \frac{1}{\sqrt{|g|}} \sum_{i,j} \frac{\partial}{\partial x^i}\left(\sqrt{|g|} g^{ij} \frac{\partial f}{\partial x^j}\right)$$

For a flat plate $\Delta_{\mathcal{M}} = \nabla^2$; for a highly curved surface, the metric modulates the diffusion direction and rate.

### 1.2 Surface Area Efficiency

The **surface area enhancement ratio** (SAER) of a textured surface over a flat one:

$$\text{SAER} = \frac{A_{textured}}{A_{flat}} = \frac{1}{A_{flat}} \iint_{\mathcal{M}} \sqrt{|g|} \, du \, dv$$

For a gyroid surface at unit cell scale $L$, SAER $\approx 3.09$, meaning a $69$ mm × $69$ mm flat plate is thermally equivalent to a $40$ mm × $40$ mm gyroid surface.

---

## II. Gyroid Minimal Surface

### 2.1 Equation

The gyroid is a triply periodic minimal surface defined by:

$$\sin(x)\cos(y) + \sin(y)\cos(z) + \sin(z)\cos(x) = 0$$

It has zero mean curvature ($H = 0$) everywhere, which minimizes the **Willmore energy** $\mathcal{W} = \int H^2 \, dA$. For heat dissipation, zero mean curvature implies uniform thermal stress distribution — no hot-spot concentration.

### 2.2 Generating a Gyroid Mesh

```python
import numpy as np
import trimesh
from skimage import measure

def gyroid_mesh(
    resolution: int = 64,
    scale: float = 2 * np.pi,
    threshold: float = 0.0,
) -> trimesh.Trimesh:
    """Generate a gyroid surface mesh via marching cubes."""
    x = np.linspace(0, scale, resolution)
    y = np.linspace(0, scale, resolution)
    z = np.linspace(0, scale, resolution)
    X, Y, Z = np.meshgrid(x, y, z, indexing="ij")
    field = (np.sin(X) * np.cos(Y)
           + np.sin(Y) * np.cos(Z)
           + np.sin(Z) * np.cos(X))
    verts, faces, normals, _ = measure.marching_cubes(field, threshold)
    return trimesh.Trimesh(vertices=verts, faces=faces, vertex_normals=normals)
```

---

## III. Thermal Resistance Analysis

### 3.1 Fin Efficiency

The fin efficiency $\eta_f$ for a surface element with convection coefficient $h$ and thermal conductivity $k$:

$$\eta_f = \frac{\tanh(mL)}{mL}, \quad m = \sqrt{\frac{h P}{k A_c}}$$

where $P$ is the perimeter, $A_c$ is the cross-sectional area, and $L$ is the fin length.

For a gyroid with cell size 3 mm on a 1 mm thick Ti-6Al-4V shell ($k = 6.7$ W/(m·K), $h = 25$ W/(m²·K)):

$$m = \sqrt{\frac{25 \cdot 0.003}{6.7 \cdot \pi \cdot (0.0005)^2}} \approx 15.4 \text{ m}^{-1}$$
$$\eta_f = \frac{\tanh(15.4 \cdot 0.003)}{15.4 \cdot 0.003} \approx 0.98$$

Almost full efficiency — the periodic structure is short enough relative to the thermal decay length.

### 3.2 Total Thermal Resistance

$$R_{th} = \frac{1}{\eta_f h A_{total}} = \frac{1}{0.98 \cdot 25 \cdot \text{SAER} \cdot A_{flat}}$$

A gyroid structure with SAER = 3.09 reduces $R_{th}$ by a factor of $\approx 3$, equivalent to tripling the base plate area.

---

## IV. FDM-Printable Thermal Design

### 4.1 Material Constraints

| Material | $k$ (W/m·K) | Max Temp (°C) | FDM-Printable |
|---------|------------|-------------|--------------|
| PLA | 0.13 | 60 | ✓ (prototype only) |
| PETG | 0.25 | 85 | ✓ |
| PA12+CF | 0.42 | 150 | ✓ (0.4 mm nozzle) |
| PEEK | 0.25 | 250 | ✓ (high-temp hotend) |
| Ti-6Al-4V | 6.70 | >1000 | ✗ (DMLS only) |

For FDM applications, PA12+CF (Nylon 12 + carbon fibre) offers the best balance of printability, thermal conductivity, and mechanical stiffness.

### 4.2 Design Rules for Printable Gyroid

- Minimum wall thickness: $\geq 0.8$ mm (2× nozzle diameter)
- Cell size: $\geq 3$ mm for 0.4 mm nozzle; $\geq 2$ mm for 0.25 mm nozzle
- Orientation: isotropic — no preferred print direction (gyroid is cubic symmetric)

---

## References

- Schoen, A.H. (1970). Infinite periodic minimal surfaces without self-intersections. NASA Technical Note D-5541.
- Bertoldi, K. et al. (2017). Flexible mechanical metamaterials. *Nature Reviews Materials*, 2(11), 1–11.
- Incropera, F.P. et al. (2006). *Fundamentals of Heat and Mass Transfer*, 6th ed. Wiley.
- Crane, K. et al. (2013). Geodesics in Heat: A New Approach to Computing Distance Based on Heat Flow. *ACM Trans. Graphics*, 32(5).
