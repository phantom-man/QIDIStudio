# AI Debugging Texture Mapping Glitches

A systematic diagnostic framework for identifying and correcting artifact classes in 3D texture mapping pipelines using metric-driven analysis and AI-assisted visual inspection.

---

## I. Artifact Taxonomy

### 1.1 Primary Glitch Classes

| Class | Name | Root Cause | Metric |
|-------|------|-----------|--------|
| T1 | Anisotropic Stretch | UV Jacobian singular value imbalance | $E_D = \sigma_1/\sigma_2 > 2$ |
| T2 | Seam Visibility | Normal discontinuity across UV boundary | $E_N > 0.1$ |
| T3 | Texel Density Mismatch | Non-uniform UV area element | $\text{CV}(\rho) > 0.3$ |
| T4 | Pinch Fold | UV triangle winding reversal | $A_{UV} < 0$ for any triangle |
| T5 | Mip Bleeding | UV island margin too small | margin $< 2 \cdot \lceil\log_2 res\rceil$ px |

### 1.2 Anisotropy Deep Dive

For a UV map $\phi: M \to [0,1]^2$, the distortion at face $f$ is measured via the **per-face Jacobian** $\mathbf{J}_f \in \mathbb{R}^{2 \times 3}$:

$$\mathbf{J}_f = \begin{pmatrix} \frac{\partial u}{\partial x} & \frac{\partial u}{\partial y} & \frac{\partial u}{\partial z} \\ \frac{\partial v}{\partial x} & \frac{\partial v}{\partial y} & \frac{\partial v}{\partial z} \end{pmatrix}$$

The singular values $\sigma_1 \geq \sigma_2$ of $\mathbf{J}_f$ give the conformal distortion $E_D = \sigma_1/\sigma_2$ and the area distortion $E_A = \sigma_1 \sigma_2$. A perfect conformal map has $E_D = 1$ everywhere.

---

## II. Diagnostic Shader: Fragment-Level Metrics

### 2.1 Checkerboard Diagnostic

A uniform checkerboard in UV space reveals stretch as non-square cells on the surface:

```python
import numpy as np
import trimesh

def apply_checkerboard_uv_diagnostic(
    mesh: trimesh.Trimesh,
    checker_res: int = 8,
) -> trimesh.Trimesh:
    """Colour vertices by checkerboard pattern in UV space to reveal stretch."""
    if not hasattr(mesh.visual, "uv") or mesh.visual.uv is None:
        raise ValueError("Mesh has no UV coordinates")
    uv = mesh.visual.uv
    # checkerboard: (floor(u*N) + floor(v*N)) mod 2
    checker = (np.floor(uv[:, 0] * checker_res).astype(int)
             + np.floor(uv[:, 1] * checker_res).astype(int)) % 2
    colors = np.where(checker[:, None], [230, 230, 230, 255], [30, 30, 30, 255])
    mesh.visual.vertex_colors = colors.astype(np.uint8)
    return mesh
```

### 2.2 Stretch Heatmap

```python
def compute_per_face_stretch(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return per-face E_D (anisotropic distortion ratio) array."""
    uv = mesh.visual.uv  # shape (V, 2)
    faces = mesh.faces    # shape (F, 3)
    e_d = np.zeros(len(faces))
    for i, (a, b, c) in enumerate(faces):
        # 3D edge vectors
        p0, p1, p2 = mesh.vertices[[a, b, c]]
        d3 = np.stack([p1 - p0, p2 - p0], axis=1)  # (3,2)
        # UV edge vectors
        u0, u1, u2 = uv[[a, b, c]]
        d2 = np.stack([u1 - u0, u2 - u0], axis=1)  # (2,2)
        # Jacobian J = d3 @ pinv(d2)  shape (3,2)
        if abs(np.linalg.det(d2)) < 1e-12:
            e_d[i] = 1.0
            continue
        J = d3 @ np.linalg.inv(d2)
        sv = np.linalg.svd(J, compute_uv=False)
        e_d[i] = sv[0] / (sv[1] + 1e-9)
    return e_d

def colorize_stretch_heatmap(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Assign face colours from blue (good) → red (bad) based on E_D."""
    e_d = compute_per_face_stretch(mesh)
    norm = np.clip((e_d - 1.0) / 4.0, 0, 1)     # 0=no distortion, 1=E_D>=5
    r = (norm * 255).astype(np.uint8)
    b = ((1 - norm) * 255).astype(np.uint8)
    g = np.zeros_like(r)
    a = np.full_like(r, 255)
    mesh.visual.face_colors = np.stack([r, g, b, a], axis=1)
    return mesh
```

---

## III. Texel Density Audit

### 3.1 Density Uniformity

The texel density at face $f$ is:

$$\rho_f = \frac{\text{resolution} \cdot \sqrt{A_{UV,f}}}{\sqrt{A_{3D,f}}}$$

where $A_{UV,f}$ is the UV-space area and $A_{3D,f}$ is the 3D surface area. Ideal mapping: $\rho_f = \text{const}$.

Coefficient of variation threshold: $\text{CV}(\rho) = \sigma_\rho / \mu_\rho < 0.3$ for acceptable uniformity.

```python
def texel_density_cv(mesh: trimesh.Trimesh, resolution: int = 2048) -> float:
    """Compute coefficient of variation of texel density across all faces."""
    uv = mesh.visual.uv
    fa, fb, fc = mesh.faces[:, 0], mesh.faces[:, 1], mesh.faces[:, 2]
    # 3D areas
    area_3d = mesh.area_faces  # (F,)
    # UV areas (cross product z-component)
    u0, u1, u2 = uv[fa], uv[fb], uv[fc]
    area_uv = 0.5 * np.abs((u1 - u0)[:, 0] * (u2 - u0)[:, 1]
                          - (u1 - u0)[:, 1] * (u2 - u0)[:, 0])
    density = resolution * np.sqrt(np.maximum(area_uv, 1e-12) /
                                   np.maximum(area_3d, 1e-12))
    return float(density.std() / (density.mean() + 1e-9))
```

---

## IV. AI Critic Diagnostic Packet

```python
def build_diagnostic_packet(mesh: trimesh.Trimesh, mesh_name: str) -> dict:
    e_d = compute_per_face_stretch(mesh)
    e_n = compute_seam_normal_discontinuity(mesh)   # from §II of AI Debugging 3D Texture Mapping
    cv_rho = texel_density_cv(mesh)
    pinch_count = int((e_d < 0).sum())              # negative UV area = winding flip
    return {
        "mesh": mesh_name,
        "mean_E_D": float(e_d.mean()),
        "max_E_D": float(e_d.max()),
        "p95_E_D": float(np.percentile(e_d, 95)),
        "seam_E_N": float(e_n),
        "texel_density_CV": float(cv_rho),
        "pinch_fold_count": pinch_count,
        "pass": (e_d.mean() < 2.0 and e_n < 0.1 and cv_rho < 0.3 and pinch_count == 0),
    }
```

---

## V. Failure Mode Reference

| Symptom | Probable Class | First Fix |
|---------|---------------|-----------|
| Grid lines converge to a point | T1 + T4 | Add seam at convergence pole; re-unwrap LSCM |
| Visible line across smooth surface | T2 | `bpy.ops.uv.seams_from_islands()` + normal bake |
| Texture appears smaller on curved face | T3 | Pack with `texelsPerUnit` constraint (xAtlas) |
| Texture appears to "fold" over itself | T4 | Flip UV island or correct winding pre-unwrap |
| Bleed between texture islands at distance | T5 | Increase island margin to $\geq 4$ px at $2048^2$ |

---

## References

- Sander, P.V. et al. (2001). Texture Mapping Progressive Meshes. *SIGGRAPH 2001*.
- Lévy, B. et al. (2002). Least Squares Conformal Maps. *SIGGRAPH 2002*.
- McGuire, M. (2022). *Computer Graphics Archive*, texel density section. Graphics.cs.williams.edu.
- xAtlas library: https://github.com/jpcy/xatlas (MIT, C++/C API)
