# Computational Aesthetics: Quantitative Models of Visual Beauty

A rigorous treatment of computational aesthetics — formalizing perceptual beauty as measurable geometric, statistical, and information-theoretic quantities, with applications to 3D model and texture evaluation.

---

## I. Theories of Aesthetic Perception

### 1.1 Information-Theoretic Aesthetics (Birkhoff-Bense)

Birkhoff (1933) proposed:

$$M = C / O$$

where $M$ is aesthetic measure, $C$ is order (regularity, symmetry), and $O$ is complexity (element count). Bense extended this to information theory:

$$M = H_{max} - H_{actual}$$

where $H = -\sum p_i \log p_i$ is Shannon entropy. High aesthetic value = maximal complexity with embedded regularity.

For 3D surfaces, this translates to: maximally textured (high H) but with long-range correlations (non-uniform $p_i$) — i.e., fractal patterns at multiple scales.

### 1.2 Symmetry and Coherence

Zeising's Divine Proportion and Weyl's symmetry theory converge on:

$$\text{Symmetry Score} = 1 - \frac{\|\mathbf{I} - \mathbf{R}(\mathbf{I})\|_F}{\|\mathbf{I}\|_F}$$

where $\mathbf{R}$ is a reflection operator (bilateral, rotational, or translational).

---

## II. Computational Beauty Metrics

### 2.1 Global Symmetry Score

```python
import numpy as np
import cv2

def bilateral_symmetry_score(image: np.ndarray) -> float:
    """
    Computes left-right bilateral symmetry score for a grayscale image.
    Returns value in [0, 1] where 1 = perfect mirror symmetry.
    """
    h, w = image.shape[:2]
    left = image[:, :w // 2]
    right = np.flip(image[:, w // 2:w // 2 * 2], axis=1)
    diff = np.abs(left.astype(float) - right.astype(float))
    score = 1.0 - diff.mean() / 255.0
    return float(score)

def rotational_symmetry_score(image: np.ndarray, n: int = 4) -> float:
    """
    Compute n-fold rotational symmetry score (e.g. n=4 for 90° symmetry).
    """
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    angle = 360.0 / n
    total_diff = 0.0
    for k in range(1, n):
        M = cv2.getRotationMatrix2D(center, k * angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h))
        total_diff += np.abs(image.astype(float) - rotated.astype(float)).mean()
    return float(1.0 - total_diff / ((n - 1) * 255.0))
```

### 2.2 Fractal Dimension (Box-Counting)

Visual complexity is characterized by fractal dimension $D_f$:

$$D_f = \lim_{\epsilon \to 0} \frac{\log N(\epsilon)}{\log(1/\epsilon)}$$

where $N(\epsilon)$ is the number of boxes of size $\epsilon$ needed to cover the image edges.

```python
def fractal_dimension(edge_image: np.ndarray) -> float:
    """
    Estimate fractal dimension via box-counting on a binary edge image.
    """
    def box_count(img: np.ndarray, size: int) -> int:
        h, w = img.shape
        count = 0
        for i in range(0, h, size):
            for j in range(0, w, size):
                if img[i:i+size, j:j+size].any():
                    count += 1
        return count

    sizes = [2, 4, 8, 16, 32, 64]
    counts = [box_count(edge_image > 0, s) for s in sizes]
    # Fit log-log: D = slope
    log_s = np.log([1.0 / s for s in sizes])
    log_c = np.log(counts)
    D_f = float(np.polyfit(log_s, log_c, 1)[0])
    return D_f
```

Natural objects: $D_f \approx 1.2$ (coastline), $1.4$ (ferns), $1.3$ (human veins). Aesthetic optimum: $D_f \in [1.3, 1.5]$.

---

## III. 3D Mesh Aesthetic Metrics

### 3.1 Gaussian Curvature Distribution

Aesthetic 3D surfaces exhibit smooth, unimodal Gaussian curvature distributions. Bimodal or heavy-tailed $\kappa$ distributions indicate sharp features perceived as "harsh".

$$\kappa_G = \kappa_1 \cdot \kappa_2, \quad \kappa_H = \frac{\kappa_1 + \kappa_2}{2}$$

**Aesthetic curvature score:**

$$\text{ACS} = \exp\left(-\frac{\sigma_{\kappa_G}}{\mu_{|\kappa_G|} + \epsilon}\right)$$

High ACS: curvature is consistent and smooth. Low ACS: chaotic curvature (perceivably "noisy").

---

## IV. Composite Beauty Score

The composite **Beauty Score (BS)** integrates multiple sub-metrics:

$$\text{BS} = w_1 \cdot S_{sym} + w_2 \cdot f(D_f) + w_3 \cdot \text{ACS} + w_4 \cdot (1 - E_{conf})$$

| Term | Weight | Meaning |
|------|--------|---------|
| $S_{sym}$ | 0.30 | Bilateral + rotational symmetry |
| $f(D_f)$ | 0.25 | Fractal optimality: $\max(0, 1 - \|D_f - 1.4\| / 0.5)$ |
| ACS | 0.25 | Gaussian curvature smoothness |
| $1 - E_{conf}$ | 0.20 | UV conformal quality (low distortion) |

---

## References

- Birkhoff, G.D. (1933). *Aesthetic Measure*. Harvard University Press.
- Weyl, H. (1952). *Symmetry*. Princeton University Press.
- Taylor, R.P. et al. (1999). Fractal analysis of Pollock's drip paintings. *Nature*, 399, 422.
- Berlyne, D.E. (1970). Novelty, complexity, and hedonic value. *Perception and Psychophysics*, 8(5), 279-286.
