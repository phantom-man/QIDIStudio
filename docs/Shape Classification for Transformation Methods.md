# Shape Classification for Geometric Transformation Method Selection

Automated classification of 3D shapes into geometric categories (planar, cylindrical, spherical, toroidal, freeform) enables optimal texture mapping, UV parameterization, and surface processing algorithm selection — avoiding heuristic guessing through principled spectral and differential geometry analysis.

---

## I. Shape Taxonomy

| Class | Gaussian curvature $K$ | Mean curvature $H$ | Examples |
|-------|----------------------|--------------------|---------|
| Planar | 0 | 0 | Flat faces, PCB boards |
| Developable | 0 | $\neq 0$ | Cylinders, cones |
| Spherical | $+K_0$ (const) | $H_0$ (const) | Spheres, hemispheres |
| Toroidal | $K$ varies $\pm$ | Varies | Donuts, tubes |
| Saddle/hyperbolic | $-K_0$ (const) | $\approx 0$ | Minimal surfaces |
| Freeform | Irregular $K$ | Irregular $H$ | Organic shapes, phones |
| Multi-genus | $K < 0$ regions + handles | — | High-genus solids |

The Gauss-Bonnet theorem relates total curvature to topology:

$$\int_{\mathcal{S}} K \, dA = 2\pi \chi(\mathcal{S}) = 2\pi(2 - 2g)$$

where $\chi$ is the Euler characteristic and $g$ is the genus.

---

## II. Curvature Estimation from Meshes

### 2.1 Discrete Mean and Gaussian Curvature

For vertex $v_i$ with 1-ring neighborhood $\mathcal{N}(v_i)$:

$$K(v_i) = \frac{2\pi - \sum_j \theta_j}{A_{mixed}}$$

$$H(v_i) = \frac{1}{4 A_{mixed}} \left\| \sum_{j \in \mathcal{N}} (\cot \alpha_j + \cot \beta_j)(v_j - v_i) \right\|$$

```python
import numpy as np
import trimesh

def compute_curvatures(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """
    Estimate Gaussian and mean curvature at each vertex.
    Returns: (K: (N,), H: (N,))
    """
    # Use trimesh's discrete curvature estimation
    K = trimesh.curvature.discrete_gaussian_curvature_measure(
        mesh, mesh.vertices, 0.01 * mesh.scale
    ) / trimesh.curvature.sphere_ball_intersection(0.01 * mesh.scale)
    H = trimesh.curvature.discrete_mean_curvature_measure(
        mesh, mesh.vertices, 0.01 * mesh.scale
    ) / trimesh.curvature.sphere_ball_intersection(0.01 * mesh.scale)
    return K, H
```

---

## III. Feature Vector Construction

```python
import numpy as np
import trimesh
from dataclasses import dataclass
from enum import Enum, auto

class ShapeClass(Enum):
    PLANAR = auto()
    CYLINDRICAL = auto()
    SPHERICAL = auto()
    TOROIDAL = auto()
    FREEFORM = auto()

@dataclass
class ShapeFeatureVector:
    mean_K: float          # Mean Gaussian curvature
    std_K: float           # Std of Gaussian curvature
    mean_H: float          # Mean mean curvature
    std_H: float           # Std of mean curvature
    K_positive_frac: float # Fraction with K > 0
    K_negative_frac: float # Fraction with K < 0
    K_near_zero_frac: float# Fraction |K| < threshold
    euler_characteristic: int
    pca_ratio_12: float    # PCA eigenvalue ratio λ1/λ2
    pca_ratio_23: float    # PCA eigenvalue ratio λ2/λ3

def extract_shape_features(mesh: trimesh.Trimesh) -> ShapeFeatureVector:
    """Compute the shape feature vector from mesh geometry."""
    K, H = compute_curvatures(mesh)
    thresh = 0.01 * np.abs(K).mean()

    # PCA on vertices
    centered = mesh.vertices - mesh.vertices.mean(0)
    eigvals = np.linalg.svd(centered, compute_uv=False)[:3]

    return ShapeFeatureVector(
        mean_K=float(K.mean()),
        std_K=float(K.std()),
        mean_H=float(H.mean()),
        std_H=float(H.std()),
        K_positive_frac=float((K > thresh).mean()),
        K_negative_frac=float((K < -thresh).mean()),
        K_near_zero_frac=float((np.abs(K) <= thresh).mean()),
        euler_characteristic=int(mesh.euler_number),
        pca_ratio_12=float(eigvals[0] / max(eigvals[1], 1e-10)),
        pca_ratio_23=float(eigvals[1] / max(eigvals[2], 1e-10)),
    )
```

---

## IV. Classification Logic

```python
def classify_shape(fv: ShapeFeatureVector) -> ShapeClass:
    """
    Rule-based shape classifier using curvature statistics.
    Handles genus-0 shapes; multi-genus needs topological extension.
    """
    # Mostly flat
    if fv.K_near_zero_frac > 0.80 and fv.std_H < 0.05:
        return ShapeClass.PLANAR

    # Developable: K~0, H varies (cylinders, cones)
    if fv.K_near_zero_frac > 0.65 and fv.std_H > 0.05:
        return ShapeClass.CYLINDRICAL

    # Spherical: K > 0 everywhere, H nearly constant
    if fv.K_positive_frac > 0.85 and fv.std_K < 0.15 * abs(fv.mean_K):
        return ShapeClass.SPHERICAL

    # Toroidal: mixed positive/negative K
    if 0.3 < fv.K_positive_frac < 0.7 and fv.K_negative_frac > 0.2:
        return ShapeClass.TOROIDAL

    return ShapeClass.FREEFORM
```

---

## V. Transformation Method Selection

| Shape Class | UV Param | Texture wrap | Distance metric |
|-------------|----------|-------------|----------------|
| PLANAR | Orthographic | Direct planar | L2 Euclidean |
| CYLINDRICAL | Cylindrical unwrap | Seam at ruled edge | Geodesic cylinder |
| SPHERICAL | Spherical (equirectangular or octahedral) | Pole correction | Geodesic sphere |
| TOROIDAL | Toroidal coords $(u, v)$ | Dual seams | Torus geodesic |
| FREEFORM | Harmonic maps / ABF++ | LSCM / ARAP | Computing geodesic |

---

## References

- Rusinkiewicz, S. (2004). Estimating curvatures and their derivatives. *3DPVT*, 486-493.
- Sheffer, A. et al. (2006). Mesh parameterization methods and their applications. *FTiCG*, 2(2).
- Kazhdan, M. et al. (2003). Rotation invariant spherical harmonic representation. *SGP*.
- Botsch, M. et al. (2010). *Polygon Mesh Processing*. AK Peters.
