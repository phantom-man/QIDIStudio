# Spectral Shape Analysis and Transforms

Spectral analysis on surfaces applies signal processing to geometry: instead of decomposing a time-domain signal into frequency components, we decompose a function defined on a mesh into eigenmodes of the Laplace-Beltrami operator. This document develops the discrete theory — cotangent Laplacian construction, mass matrix options, spectral embedding, and the application to shape description, filtering, and classification — with full implementation using scipy.sparse and libigl.

---

## I. The Laplace-Beltrami Operator

On a compact Riemannian manifold (M, g), the Laplace-Beltrami operator acts on smooth functions f: M -> R:

$$\Delta_\mathcal{M} f = \text{div}(\text{grad}\, f) = \frac{1}{\sqrt{|g|}} \partial_i \left(\sqrt{|g|}\, g^{ij} \partial_j f\right)$$

Key properties:
- **Self-adjoint**: inner products are symmetric under L^2(M)
- **Negative semi-definite**: <Delta_M f, f> <= 0
- **Isometry-invariant**: depends only on the intrinsic metric, not on the R^3 embedding

The eigenproblem Delta_M phi_k = -lambda_k phi_k yields:

$$0 = \lambda_0 < \lambda_1 \leq \lambda_2 \leq \ldots \nearrow +\infty$$

The Weyl asymptotic formula:

$$\lambda_k \sim \frac{4\pi k}{\text{area}(\mathcal{M})}, \quad k \to \infty$$

---

## II. Discrete Construction: Cotangent Laplacian

For a triangulated surface, the standard discrete Laplace-Beltrami approximation is the **cotangent Laplacian** (Pinkall & Polthier 1993):

$$L_{ij} = \begin{cases} \frac{1}{2}(\cot\alpha_{ij} + \cot\beta_{ij}) & (i,j) \in \mathcal{E} \\ -\sum_{k \in N(i)} L_{ik} & i = j \\ 0 & \text{otherwise} \end{cases}$$

where alpha_ij and beta_ij are the angles of the two triangles sharing edge (i,j), opposite to that edge.

**Explicit construction (without libigl):**

```python
import numpy as np
import scipy.sparse as sp

def cotan_laplacian(V: np.ndarray, F: np.ndarray) -> sp.csr_matrix:
    """Build cotangent Laplacian L (positive semi-definite convention: -div*grad).

    Args:
        V: (n, 3) float64 positions
        F: (m, 3) int32 face indices

    Returns:
        L: (n, n) sparse csr_matrix, symmetric, positive semi-definite
    """
    n = V.shape[0]
    row, col, data = [], [], []

    for (i, j, k) in F:
        for a, b, c in [(i, j, k), (j, k, i), (k, i, j)]:
            # Cotan of angle at vertex a, opposite edge b-c
            e1 = V[b] - V[a]
            e2 = V[c] - V[a]
            cross_norm = np.linalg.norm(np.cross(e1, e2))
            dot        = float(np.dot(e1, e2))
            if cross_norm < 1e-12:
                continue
            w = 0.5 * dot / cross_norm
            row += [b, c]; col += [c, b]; data += [-w, -w]
            row += [b, c]; col += [b, c]; data += [ w,  w]

    return sp.csr_matrix((data, (row, col)), shape=(n, n))
```

---

## III. Mass Matrix Options

| Name | M_ii | Properties | Use case |
|------|------|-----------|---------|
| Identity | 1 | Simple, not geometry-aware | Combinatorial graphs |
| Uniform lumped | area(M)/n | Equal weight per vertex | Low-poly meshes |
| Voronoi (barycentric dual) | (1/3) sum_{f containing i} A_f | Geometry-aware, standard | Most meshes (default) |
| Mixed (obtuse correction) | Clamps obtuse triangles | Positive for all triangulations | Meshes with obtuse angles |

```python
def voronoi_mass_matrix(V: np.ndarray, F: np.ndarray) -> sp.diags:
    """Voronoi dual-cell mass matrix (diagonal)."""
    n = V.shape[0]
    mass = np.zeros(n)
    for (i, j, k) in F:
        e1 = V[j] - V[i]
        e2 = V[k] - V[i]
        area = 0.5 * np.linalg.norm(np.cross(e1, e2))
        mass[i] += area / 3.0
        mass[j] += area / 3.0
        mass[k] += area / 3.0
    return sp.diags(mass)
```

---

## IV. Spectral Decomposition

```python
from scipy.sparse.linalg import eigsh

def laplacian_eigensystem(
    V: np.ndarray,
    F: np.ndarray,
    k: int = 20,
    sigma: float = 1e-8
) -> tuple:
    """Compute k smallest eigenvalue/eigenvector pairs of the Laplace-Beltrami operator.

    Uses shift-invert ARPACK (sigma=1e-8) to find eigenvalues near zero.

    Returns:
        eigenvalues:  (k,) float64, sorted ascending
        eigenvectors: (n, k) float64, M-orthonormal eigenfunctions
    """
    L = cotan_laplacian(V, F)
    M = voronoi_mass_matrix(V, F)
    vals, vecs = eigsh(L, k=k, M=M, sigma=sigma, which='LM', tol=1e-10)
    order = np.argsort(vals)
    return vals[order], vecs[:, order]
```

**Numerical notes:**
- sigma=1e-8 (shift-invert): finds eigenvalues nearest 0 via ARPACK
- For large meshes (n > 1e5), use sksparse.cholmod as the sparse Cholesky inner solver

---

## V. Spectral Filtering on Mesh Signals

Given a scalar signal f on the mesh vertices, the spectral decomposition is:

$$\mathbf{f} = \sum_{k=0}^{n-1} \hat{f}_k \phi_k, \quad \hat{f}_k = \phi_k^T M \mathbf{f}$$

A **spectral filter** h(lambda) is applied pointwise in eigenspace:

$$\mathbf{f}^\text{filtered} = \sum_k h(\lambda_k)\, \hat{f}_k\, \phi_k$$

```python
def spectral_filter(
    f: np.ndarray,
    eigenvalues: np.ndarray,
    eigenvectors: np.ndarray,
    M: sp.spmatrix,
    filter_fn
) -> np.ndarray:
    """Apply a spectral filter to a mesh signal.

    Args:
        f:            (n,) signal at vertices
        eigenvalues:  (k,) Laplacian eigenvalues
        eigenvectors: (n, k) M-orthonormal eigenfunctions
        M:            (n, n) mass matrix
        filter_fn:    callable lambda -> h(lambda)

    Returns:
        f_filtered: (n,) filtered signal
    """
    f_hat = eigenvectors.T @ (M @ f)
    h = np.array([filter_fn(lam) for lam in eigenvalues])
    return eigenvectors @ (h * f_hat)

# Common filters:
gaussian_lowpass = lambda lam, sigma2=1.0: np.exp(-lam * sigma2)
heat_kernel      = lambda lam, t=0.1:     np.exp(-lam * t)
highpass         = lambda lam, cutoff=2.0: 0.0 if lam < cutoff else 1.0
```

**Spectral vs Laplacian smoothing:**
- Laplacian smoothing (one Euler step) = first-order approximation of heat kernel filter
- Spectral filtering with exact exp(-lambda*t) = solving heat equation exactly at time t
- For equal compute, spectral filtering gives exact frequency control

---

## VI. Spectral Embedding for Shape Analysis

The first d non-trivial eigenfunctions define a **spectral embedding** Phi: M -> R^d:

$$\Phi(v_i) = \left(\frac{\phi_1(v_i)}{\sqrt{\lambda_1}},\, \ldots,\, \frac{\phi_d(v_i)}{\sqrt{\lambda_d}}\right)$$

The 1/sqrt(lambda_k) weighting produces the **commute-time distance**:

$$d_\text{CT}(v_i, v_j)^2 = \sum_{k=1}^{K} \frac{1}{\lambda_k} \left(\phi_k(v_i) - \phi_k(v_j)\right)^2$$

This is the expected number of steps for a random walk to travel from v_i to v_j and back — a geodesic-like intrinsic distance robust to mesh noise and pose variation.

---

## VII. Spectral Gap and the Fiedler Vector

| Quantity | Interpretation |
|---------|---------------|
| lambda_1 -> 0 | Near-disconnected mesh; two weakly connected components |
| lambda_1 large | Well-connected — fast mixing for heat diffusion |
| phi_1 (Fiedler vector) | Smoothest non-constant function — encodes dominant elongation axis |

```python
def fiedler_axis(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Compute the Fiedler vector and use it to find the mesh principal elongation axis."""
    _, vecs = laplacian_eigensystem(V, F, k=2)
    phi1 = vecs[:, 1]           # Fiedler vector (index 1; index 0 is constant)
    i_min = int(np.argmin(phi1))
    i_max = int(np.argmax(phi1))
    axis  = V[i_max] - V[i_min]
    norm  = np.linalg.norm(axis)
    return axis / norm if norm > 1e-8 else np.array([0.0, 0.0, 1.0])
```

---

## VIII. References

1. Pinkall, U., & Polthier, K. (1993). Computing discrete minimal surfaces and their conjugates. *Experimental Mathematics 2*(1), 15-36.
2. Reuter, M., Wolter, F.-E., & Peinecke, N. (2006). Laplace-Beltrami spectra as 'Shape-DNA' of surfaces and solids. *CAD 38*(4), 342-366.
3. Belkin, M., & Niyogi, P. (2008). Towards a theoretical foundation for Laplacian-based manifold methods. *Journal of Computer and System Sciences 74*(8), 1289-1308.
4. Coifman, R.R., & Lafon, S. (2006). Diffusion maps. *Applied and Computational Harmonic Analysis 21*(1), 5-30.
5. Crane, K. (2023). Discrete Differential Geometry (CMU 15-458 course notes).
6. QIDIStudio `apply_texture_bpy.py`: `_classify_mesh`, `compute_shape_dna`, `laplacian_eigensystem`
