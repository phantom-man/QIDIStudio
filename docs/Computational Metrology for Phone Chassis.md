# Computational Metrology for Prismatic CAD Manifolds

A comprehensive treatment of high-fidelity measurement, spectral parameterization, and tolerance analysis for complex filleted CAD geometry — integrating computational metrology with UV mapping theory.

---

## I. Metrology Foundation

### 1.1 GD&T Tolerance Framework

For a filleted prismatic shell (e.g. phone chassis, electronics enclosure), the primary geometric tolerances are:

| Feature | Symbol | Typical Tolerance | Measurement Method |
|---------|--------|------------------|------------------|
| Overall dimensions | Size | ±0.1 mm | CMM or photogrammetry |
| Flatness of back face | ⏥ | 0.05 mm | Reference plane fit |
| Cylindricity of side radii | ⌀ | 0.02 mm | Least-squares circle fit |
| Position of camera cutout | ⊕ | ±0.15 mm | Centroid from point cloud |
| Perpendicularity of sides | ⊾ | 0.03 mm/mm | Normal vector deviation |

### 1.2 Reference Frame Establishment

The model coordinate frame is established by a **Datum Reference Frame (DRF)** with three mutually perpendicular datum planes $A$, $B$, $C$:
- Datum A: back face (primary — 3 points)
- Datum B: long edge (secondary — 2 points)
- Datum C: short edge (tertiary — 1 point)

```python
import numpy as np

def fit_reference_frame(
    back_pts: np.ndarray,   # (N, 3) point cloud of back face
    long_edge: np.ndarray,  # (M, 3) point cloud of long edge
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (R, t): rotation matrix and translation that aligns
    the mesh to the DRF with back face = XY plane.
    """
    # Datum A: fit a plane via SVD
    centroid = back_pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(back_pts - centroid)
    normal_A = Vt[-1]   # smallest singular vector = plane normal
    # Ensure normal points in +Z direction
    if normal_A[2] < 0:
        normal_A = -normal_A
    # Datum B: project long_edge to Datum A plane, then fit direction
    proj = long_edge - np.outer((long_edge - centroid) @ normal_A, normal_A)
    _, _, Vt2 = np.linalg.svd(proj - proj.mean(axis=0))
    dir_B = Vt2[0]
    # Build rotation matrix
    z = normal_A
    x = dir_B - np.dot(dir_B, z) * z
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z], axis=1)
    return R, -R.T @ centroid
```

---

## II. Spectral Parameterization

### 2.1 Shape DNA for Manifold Identification

The **Shape DNA** (Reuter et al., 2006) is the spectrum of eigenvalues $\{\lambda_i\}$ of the Laplace-Beltrami operator $\Delta_{\mathcal{M}}$, normalized to unit scale:

$$\text{DNA} = \left\{\frac{\lambda_1}{A^{1/2}}, \frac{\lambda_2}{A^{1/2}}, \dots, \frac{\lambda_k}{A^{1/2}}\right\}$$

where $A = \text{surface area}$.

For a given manifold topology, the Shape DNA uniquely identifies the geometry up to isometry. Two meshes with matching DNA (within tolerance $\epsilon_\lambda = 0.01$) are isometric.

```python
import scipy.sparse as sp
import scipy.sparse.linalg as spla

def shape_dna(mesh, k: int = 32) -> np.ndarray:
    """Compute k Shape DNA eigenvalues."""
    from .spectral import cotan_laplacian, voronoi_mass_matrix
    L = cotan_laplacian(mesh)
    M = voronoi_mass_matrix(mesh)
    A = float(mesh.area)
    vals, _ = spla.eigsh(-L, k=k, M=M, sigma=0, which="LM")
    return np.sort(np.abs(vals)) / np.sqrt(A)
```

---

## III. Surface Reconstruction Error

### 3.1 Hausdorff Distance

The **directed Hausdorff distance** from reconstructed mesh $\hat{\mathcal{M}}$ to reference $\mathcal{M}$:

$$d_H(\hat{\mathcal{M}}, \mathcal{M}) = \max_{\mathbf{p} \in \hat{\mathcal{M}}} \min_{\mathbf{q} \in \mathcal{M}} \|\mathbf{p} - \mathbf{q}\|_2$$

The symmetric Hausdorff distance $d_{sym} = \max(d_H(\hat{\mathcal{M}}, \mathcal{M}), d_H(\mathcal{M}, \hat{\mathcal{M}}))$ bounds the worst-case reconstruction error.

```python
import trimesh

def hausdorff_distance(mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh) -> float:
    """Approximate symmetric Hausdorff distance by sampling."""
    pts_a = trimesh.sample.sample_surface(mesh_a, 10_000)[0]
    pts_b = trimesh.sample.sample_surface(mesh_b, 10_000)[0]
    # Nearest-neighbour distances using trimesh proximity
    dist_ab, _ = trimesh.proximity.closest_point(mesh_b, pts_a)
    dist_ba, _ = trimesh.proximity.closest_point(mesh_a, pts_b)
    return float(max(dist_ab.max(), dist_ba.max()))
```

### 3.2 RMSE Surface Deviation

For tolerance analysis, mean surface deviation is more useful than the worst-case Hausdorff:

$$\text{RMSE} = \sqrt{\frac{1}{N} \sum_{i=1}^N d(\mathbf{p}_i, \mathcal{M})^2}$$

Target: RMSE $< 0.02$ mm for consumer electronics tolerances.

---

## IV. UV Mapping Quality for Metrology

### 4.1 Conformal Distortion Constraint

For texture-based metrology (e.g. fringe projection, structured light), the UV map must be **nearly conformal** to avoid measurement scale errors:

$$E_{conformal} = \frac{1}{|F|} \sum_{f \in F} \left(\sigma_1(\mathbf{J}_f) - \sigma_2(\mathbf{J}_f)\right)^2 < 0.01$$

A high-conformal map ensures that physical distances measured on the texture correspond accurately to real-world distances on the surface.

---

## V. Full Metrology Pipeline

```
1. Point cloud acquisition  →  photogrammetry / structured light
2. Reference frame alignment  →  DRF/GD&T (Datum A–C)
3. Mesh reconstruction  →  Poisson surface reconstruction
4. Hausdorff audit  →  RMSE < 0.02 mm, Hausdorff < 0.1 mm
5. Shape DNA comparison  →  |DNA_ref - DNA_reconstructed| < ε_λ
6. UV parameterization  →  LSCM or ARAP (E_conformal < 0.01)
7. Texture projection  →  xAtlas + texelsPerUnit = 500 px/mm
```

---

## References

- Reuter, M. et al. (2006). Laplace–Spectra as Fingerprints for Shape Matching. *SPM 2006*.
- Jaklic, A. et al. (2000). Segmentation and Recovery of Superquadrics. *Springer*.
- Roth, S.D. (1982). Ray Casting for Modeling Solids. *Computer Graphics and Image Processing*, 18(2).
- ISO 1101:2017 Geometrical product specifications (GPS) — Geometrical tolerancing.
