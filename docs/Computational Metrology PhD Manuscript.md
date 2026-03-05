# Computational Metrology: Point Cloud Registration, GD&T Inspection, and Uncertainty Quantification

A research-level treatment of the computational metrology pipeline from raw scanner point clouds to ISO 1101-conformant GD&T tolerance reports — covering ICP registration, feature fitting, tolerance zone evaluation, and measurement uncertainty propagation.

---

## I. Point Cloud Acquisition and Preprocessing

### 1.1 Scanner Noise Model

Scanner measurements $\hat{p}_i = p_i + \epsilon_i$ where $\epsilon_i \sim \mathcal{N}(0, \sigma^2 I_3)$. Typical values:

| Scanner type | $\sigma$ (1σ, µm) | Resolution (µm) |
|-------------|------------------|----------------|
| Structured light | 5–15 | 50–200 |
| CMM touch probe | 0.5–2 | 1–5 |
| Photogrammetry | 10–50 | 100–500 |
| Industrial CT | 5–20 | 10–50 |

### 1.2 Statistical Outlier Removal

```python
import numpy as np
from scipy.spatial import KDTree

def remove_statistical_outliers(
    pts: np.ndarray,
    k: int = 20,
    sigma_thresh: float = 2.0,
) -> np.ndarray:
    """
    Remove points whose mean k-NN distance exceeds global_mean + sigma_thresh * std.
    """
    tree = KDTree(pts)
    dists, _ = tree.query(pts, k=k + 1)    # k+1: includes self
    mean_dists = dists[:, 1:].mean(axis=1)  # exclude self
    mu, sigma = mean_dists.mean(), mean_dists.std()
    mask = mean_dists < (mu + sigma_thresh * sigma)
    return pts[mask]
```

---

## II. ICP Registration

The Iterative Closest Point algorithm minimizes:

$$E(R, t) = \sum_{i=1}^N \| R p_i + t - q_{c(i)} \|^2$$

where $c(i) = \arg\min_j \| R p_i + t - q_j \|$ and $(R, t)$ is the SE(3) transform.

### 2.1 SVD-Based ICP Step

```python
from scipy.spatial.transform import Rotation

def icp_step(
    source: np.ndarray,   # (N, 3)
    target: np.ndarray,   # (M, 3)
) -> tuple[np.ndarray, np.ndarray, float]:
    """
    One ICP iteration: find correspondences, compute SVD-based R,t.
    Returns: (R: (3,3), t: (3,), mean_error: float)
    """
    tree = KDTree(target)
    dists, indices = tree.query(source, k=1)
    matched_target = target[indices[:, 0]]

    # Center the matched pairs
    mu_s = source.mean(axis=0)
    mu_t = matched_target.mean(axis=0)
    Xs = source - mu_s
    Xt = matched_target - mu_t

    # SVD
    H = Xs.T @ Xt
    U, S, Vt = np.linalg.svd(H)
    R = (Vt.T @ U.T)

    # Ensure proper rotation (det=+1)
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    t = mu_t - R @ mu_s
    return R, t, float(dists.mean())


def icp_align(
    source: np.ndarray,
    target: np.ndarray,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Full ICP: iterate until convergence. Returns final (R, t)."""
    R_total = np.eye(3)
    t_total = np.zeros(3)
    src = source.copy()
    prev_err = np.inf

    for _ in range(max_iter):
        R, t, err = icp_step(src, target)
        src = (R @ src.T).T + t
        R_total = R @ R_total
        t_total = R @ t_total + t
        if abs(prev_err - err) < tol:
            break
        prev_err = err
    return R_total, t_total
```

---

## III. Feature Fitting for GD&T

### 3.1 Plane Fitting

Fit a plane $\hat{n}^T p = d$ via PCA of the point cloud:

```python
def fit_plane(pts: np.ndarray) -> tuple[np.ndarray, float]:
    """Returns (normal: (3,), d: float) for best-fit plane."""
    centroid = pts.mean(0)
    _, _, Vt = np.linalg.svd(pts - centroid)
    normal = Vt[-1]  # last singular vector = least-variance direction
    d = float(normal @ centroid)
    return normal, d
```

### 3.2 Cylinder Fitting

Use Pratt's algebraic method or nonlinear LSQ:

```python
from scipy.optimize import minimize

def fit_cylinder(pts: np.ndarray) -> dict:
    """Fit a cylinder via nonlinear least squares. Returns axis, point on axis, radius."""
    def cylinder_residuals(params):
        ax, ay, px, py, pz, r = params
        az = np.sqrt(max(1 - ax**2 - ay**2, 0))
        axis = np.array([ax, ay, az])
        axis /= np.linalg.norm(axis)
        point = np.array([px, py, pz])
        v = pts - point
        proj = v - np.outer(v @ axis, axis)
        return ((np.linalg.norm(proj, axis=1) - r) ** 2).sum()

    x0 = [0.0, 0.0, *pts.mean(0), 10.0]
    res = minimize(cylinder_residuals, x0, method="Nelder-Mead")
    ax, ay, px, py, pz, r = res.x
    az = np.sqrt(max(1 - ax**2 - ay**2, 0))
    return {"axis": np.array([ax, ay, az]), "point": np.array([px, py, pz]), "radius": r}
```

---

## IV. GD&T Tolerance Evaluation

| Symbol | ISO 1101 | Tolerance zone type | Code |
|--------|---------|--------------------|----|
| ⊙ Circularity | 6.1 | Radial annulus | `circ` |
| ⊡ Flatness | 5.1 | Two parallel planes | `flat` |
| ∥ Parallelism | 11.3 | Two parallel planes w.r.t. datum | `par` |
| ⊥ Perpendicularity | 11.2 | Two planes w.r.t. datum axis | `perp` |
| ⌀ True position | 12.5 | Cylinder about nominal | `pos` |

```python
def check_flatness(pts: np.ndarray, tolerance_mm: float) -> dict:
    """ISO 1101 §5.1 — flatness: max range of point projections onto fitted normal."""
    n, d = fit_plane(pts)
    projections = pts @ n - d
    flatness = float(projections.max() - projections.min())
    return {"flatness_mm": flatness, "pass": flatness <= tolerance_mm}
```

---

## References

- Besl, P. & McKay, N. (1992). A method for registration of 3-D shapes. *IEEE TPAMI*, 14(2).
- ISO 1101 (2017). Geometrical product specifications — Tolerancing. ISO.
- Shakarji, C.M. (1998). Least-squares fitting algorithms of the NIST algorithm testing system. *J. Res. NIST*, 103(6).
- Zhang, Z. (1994). Iterative point matching for registration of free-form curves. *IJCV*, 13(2).
