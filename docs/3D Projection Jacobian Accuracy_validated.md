# 3D Projection Jacobian Accuracy

A rigorous treatment of projection Jacobians in computer graphics and computer vision — covering perspective projection distortion, its effect on UV parameterization, and methods for correcting or accounting for it.

---

## I. Mathematical Foundation

### 1.1 Perspective Projection

[Claim requires primary source verification]

[Claim requires primary source verification]

[Claim requires primary source verification]

### 1.2 The Projection Jacobian

[Claim requires primary source verification]

[Claim requires primary source verification]

[Claim requires primary source verification] [Claim requires primary source verification]

---

## II. Area and Angle Distortion

### 2.1 Area Distortion Factor

The area distortion of the projection at point $\mathbf{P}$ is:

[Claim requires primary source verification]

[Claim requires primary source verification]

### 2.2 Angular Distortion

[Claim requires primary source verification] The departure from conformality:

[Claim requires primary source verification]

[Claim requires primary source verification]

---

## III. Computing Jacobians for Mesh Faces

### 3.1 Per-Face Projection Jacobian

For a triangle mesh face $f = (v_0, v_1, v_2)$ in camera coordinates:

```python
import numpy as np

def perspective_jacobian(
    P: np.ndarray,   # (3,) camera-space point
    fx: float, fy: float,
) -> np.ndarray:
[Claim requires primary source verification]
    X, Y, Z = P
    return np.array([
        [fx / Z,      0,  -fx * X / Z**2],
        [     0, fy / Z,  -fy * Y / Z**2],
    ])

def face_jacobian_condition(
    face_verts: np.ndarray,  # (3, 3) triangle vertices in camera space
    fx: float, fy: float,
) -> float:
[Claim requires primary source verification]
    centroid = face_verts.mean(axis=0)
    J = perspective_jacobian(centroid, fx, fy)
    sv = np.linalg.svd(J, compute_uv=False)
    return float(sv[0] / (sv[1] + 1e-12))
```

### 3.2 Batch Audit of Full Mesh

```python
import trimesh

def audit_projection_distortion(
    mesh: trimesh.Trimesh,
    R: np.ndarray,  # (3, 3) rotation matrix (world → camera)
    t: np.ndarray,  # (3,) translation (world → camera)
[Claim requires primary source verification]
[Claim requires primary source verification]
[Claim requires primary source verification]
) -> dict:
    """
[Claim requires primary source verification]
[Claim requires primary source verification]
    """
    # Transform vertices to camera space
    verts_cam = (mesh.vertices @ R.T) + t  # (V, 3)
    centroids = verts_cam[mesh.faces].mean(axis=1)  # (F, 3)

    # Vectorized Jacobian condition numbers
    X, Y, Z = centroids[:, 0], centroids[:, 1], centroids[:, 2]
    # Singular values of J = [[fx/Z, 0, -fx*X/Z^2], [0, fy/Z, -fy*Y/Z^2]]
    sv1 = np.sqrt((fx / Z)**2 + (fx * X / Z**2)**2)
    sv2 = np.sqrt((fy / Z)**2 + (fy * Y / Z**2)**2)
    kappa = np.maximum(sv1, sv2) / (np.minimum(sv1, sv2) + 1e-12)

    return {
        "mean_kappa": float(kappa.mean()),
        "max_kappa": float(kappa.max()),
        "p95_kappa": float(np.percentile(kappa, 95)),
        "high_distortion_faces": np.where(kappa > threshold)[0].tolist(),
        "pass": bool(kappa.mean() < threshold),
    }
```

---

## IV. Correcting for Projection Distortion

### 4.1 Cylindrical Equidistant Projection

[Claim requires primary source verification]

[Claim requires primary source verification]

The Jacobian is:

[Claim requires primary source verification]

[Claim requires primary source verification]

### 4.2 Importance-Weighted UV Packing

[Claim requires primary source verification]

```python
def compute_uv_budget_weights(
    kappa: np.ndarray,            # (F,) per-face condition numbers
    area_3d: np.ndarray,          # (F,) 3D surface areas
[Claim requires primary source verification]
) -> np.ndarray:
    """
    UV budget weight inversely proportional to projection distortion.
    Returns normalized weights summing to 1.
    """
    kappa_clamped = np.minimum(kappa, kappa_clip)
    weights = area_3d / kappa_clamped      # penalise high-distortion faces
    return weights / weights.sum()
```

---

## V. Accuracy Benchmarks

| Surface Type | Mean $\kappa$ | Max $\kappa$ | Projection Method |
|-------------|--------------|-------------|------------------|
[Claim requires primary source verification]
[Claim requires primary source verification]
[Claim requires primary source verification]
[Claim requires primary source verification]

---

## References

- Hartley, R. & Zisserman, A. (2003). *Multiple View Geometry in Computer Vision*. Cambridge University Press.
- [Claim requires primary source verification]
- [Claim requires primary source verification]
