# Morphological Metrology and UV-Morphing for Complex Filleted Shells

Quantitative methods for measuring filleted prismatic manifolds and applying topology-aware UV morphing — unifying computational geometry, conformal mapping, and 3D printing deformation models.

---

## I. Filleted Shell Topology

### 1.1 Feature Decomposition

A filleted shell (thin enclosure with rounded edges) decomposes into:

| Region | Topological Class | Parameterization |
|--------|-----------------|-----------------|
| Back face | Planar rectangle | Affine map |
| Side faces | Ruled strips | Cylindrical projection |
| Corner fillets | Quarter-torus arc | Torus patch (u,v) ∈ [0,1]² |
| Camera cutout | Punched disk $\mathbb{D} \setminus \mathbb{D}_r$ | Annular map |

The full surface has genus $g = 0$ (sphere topology) after closing, but with $k$ camera/button holes the genus becomes $g = k$.

### 1.2 Fillet Radius Estimation

Let $V_i, V_j$ be edge vertices and $\mathbf{n}_i, \mathbf{n}_j$ their vertex normals. The local fillet radius is:

$$r_{fillet} = \frac{\|\mathbf{V}_i - \mathbf{V}_j\|}{2 \sin(\theta / 2)}, \quad \theta = \arccos(\mathbf{n}_i \cdot \mathbf{n}_j)$$

This is the inscribed circle radius of the fillet cross-section.

```python
import numpy as np
import trimesh

def estimate_fillet_radii(mesh: trimesh.Trimesh) -> np.ndarray:
    """
    For each edge, estimate fillet radius from vertex normal deviation.
    Returns array of shape (n_edges,) with radius in world units.
    """
    edges = mesh.edges_unique
    V = mesh.vertices
    N = mesh.vertex_normals
    v0, v1 = edges[:, 0], edges[:, 1]
    edge_vec = V[v1] - V[v0]
    lengths = np.linalg.norm(edge_vec, axis=1)
    cos_theta = np.clip(
        np.sum(N[v0] * N[v1], axis=1), -1.0, 1.0
    )
    theta = np.arccos(cos_theta)
    # Avoid division by small theta (near-flat edges)
    sin_half = np.abs(np.sin(theta / 2.0))
    mask = sin_half > 1e-6
    radii = np.full(len(edges), np.inf)
    radii[mask] = lengths[mask] / (2.0 * sin_half[mask])
    return radii
```

---

## II. UV Morphing Operators

### 2.1 Free-Form UV Deformation

UV morphing maps UV coordinates through a 2D deformation field $\phi: [0,1]^2 \to [0,1]^2$. For smooth deformations, $\phi$ is parametrized as a thin-plate spline (TPS):

$$\phi(\mathbf{u}) = \mathbf{u} + \sum_{i=1}^k w_i \, \rho(\|\mathbf{u} - \mathbf{c}_i\|)$$

where $\rho(r) = r^2 \ln r$ is the radial basis function and $\mathbf{c}_i$ are control point positions with weights $w_i$.

```python
from scipy.interpolate import RBFInterpolator

def tps_morph(
    uv: np.ndarray,      # (N, 2) original UV coordinates
    ctrl_src: np.ndarray, # (K, 2) control point sources
    ctrl_dst: np.ndarray, # (K, 2) control point destinations
) -> np.ndarray:
    """Apply thin-plate-spline UV morphing."""
    delta = ctrl_dst - ctrl_src
    rbf = RBFInterpolator(ctrl_src, delta, kernel="thin_plate_spline")
    displacement = rbf(uv)
    return np.clip(uv + displacement, 0.0, 1.0)
```

### 2.2 Area-Preserving Constraint

For physically consistent texture scaling, apply an area-preserving constraint after TPS morphing. The Jacobian determinant of the morph must satisfy:

$$\det(\mathbf{J}_\phi) = 1 \quad \text{(area-preserving)} \qquad \text{or} \qquad |\det(\mathbf{J}_\phi) - 1| < \epsilon_{area} = 0.05$$

Violation indicates UV chart collapse (content compression) or explosion (content stretching), both yielding visible artifacts.

---

## III. Texture Morphing for Shape Variations

### 3.1 Inter-Shape UV Transfer

To transfer a texture designed for reference shape $\mathcal{M}_0$ to a morphed shape $\mathcal{M}_1$ (e.g. variant with different screen notch):

1. Compute spectral embedding: $\Phi_0, \Phi_1 \in \mathbb{R}^{N \times k}$ (first $k$ Laplace-Beltrami eigenfunctions)
2. Align spectra: orthogonal Procrustes $\min_R \|\Phi_0 - \Phi_1 R\|_F$
3. Establish vertex correspondence: $\pi: V(\mathcal{M}_0) \to V(\mathcal{M}_1)$ via nearest-neighbor in spectral space
4. Transfer UV: $\text{UV}_1[v] = \text{UV}_0[\pi^{-1}(v)]$

---

## IV. Print Deformation Compensation

### 4.1 FDM Warping Model

Thin-wall prismatic shells exhibit in-plane warping due to thermal contraction gradients. The warp displacement field $\mathbf{w}(\mathbf{x})$ follows the linearized plate equation:

$$D \nabla^4 w = \frac{E \alpha \Delta T}{1 - \nu} \nabla^2 T$$

where $D = \frac{E h^3}{12(1-\nu^2)}$ is the plate bending stiffness, $h$ is wall thickness, $\alpha$ is the coefficient of thermal expansion.

For ABS: $\alpha = 7 \times 10^{-5}$ K$^{-1}$, $E = 2.3$ GPa, $\nu = 0.35$.

The UV texture needs to be **pre-distorted** by $\mathbf{w}^{-1}$ so that after printing deformation, the texture aligns correctly.

---

## V. Metrology + UV Quality Checklist

| Check | Target | Method |
|-------|--------|--------|
| Fillet radius consistency | $\sigma_r < 0.02$ mm | `estimate_fillet_radii()` |
| Hausdorff vs nominal | $< 0.05$ mm | `hausdorff_distance()` |
| UV conformal distortion | $E_{conf} < 0.01$ | per-face Jacobian |
| UV area distortion | $|\det J - 1| < 0.05$ | `det(J_f)` per face |
| TPS morph smoothness | $\|w_i\| < 0.01$ | TPS weight norm |
| Print warp compensation | RMSE $< 0.03$ | warp model inversion |

---

## References

- Bookstein, F.L. (1989). Principal Warps: Thin-Plate Splines and The Decomposition of Deformations. *TPAMI* 11(6), 567-585.
- Ovsjanikov, M. et al. (2012). Functional Maps: A Flexible Representation of Maps Between Shapes. *SIGGRAPH 2012*.
- Turner, B.N. et al. (2014). A review of melt extrusion additive manufacturing processes. *Rapid Prototyping J.* 20(3).
- ISO 1101:2017 Geometrical product specifications (GPS) — Geometrical tolerancing.
