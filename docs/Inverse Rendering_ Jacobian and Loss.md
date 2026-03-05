# Inverse Rendering: Jacobian Analysis and Loss Function Design

A mathematical treatment of the Jacobian structure in inverse rendering — characterizing gradient flow through scene parameters, analyzing loss landscape geometry, and designing loss functions that overcome local minima.

---

## I. The Inverse Rendering Jacobian

### 1.1 Parameter-to-Pixel Jacobian

Let $\boldsymbol{\xi} \in \mathbb{R}^p$ be scene parameters (vertex positions, material properties, lighting SH coefficients). The rendered image $\mathbf{I} \in \mathbb{R}^{H \times W \times 3}$ is the output.

The full Jacobian:

$$\mathbf{J} = \frac{\partial \mathbf{I}}{\partial \boldsymbol{\xi}} \in \mathbb{R}^{(HW3) \times p}$$

For a mesh with $V$ vertices, $\boldsymbol{\xi}_{geometry} \in \mathbb{R}^{3V}$ and:

$$J_{ij} = \frac{\partial I_i}{\partial \xi_j}$$

This Jacobian is **sparse** (pixel $i$ depends on $O(1)$ visible triangles) and **discontinuous** at silhouette boundaries.

### 1.2 Jacobian Decomposition

$$\mathbf{J} = \underbrace{\mathbf{J}_{shade}}_{\text{continuous}} + \underbrace{\mathbf{J}_{sil}}_{\text{boundary term}}$$

The shading Jacobian $\mathbf{J}_{shade}$ is computed via chain rule through the rendering equation. The silhouette Jacobian $\mathbf{J}_{sil}$ requires the boundary integral (Loubet et al., 2019):

$$J_{sil}^{ij} = \oint_{\partial \mathcal{M}(\boldsymbol{\xi})} (L^+ - L^-) \frac{\partial s(\mathbf{q}, \boldsymbol{\xi})}{\partial \xi_j} \delta(I_i - \phi(\mathbf{q})) \, d\ell$$

---

## II. Loss Landscape Analysis

### 2.1 Photometric Loss Geometry

The standard L2 photometric loss $\mathcal{L} = \|\hat{\mathbf{I}} - \mathbf{I}_{ref}\|^2$ has a highly non-convex landscape with respect to geometry — the parameter-to-pixel map is folded and self-intersecting.

Key failure modes:

| Mode | Cause | Mitigation |
|------|-------|-----------|
| Locality trap | Loss is flat far from reference | Multi-scale pyramid |
| Silhouette singularity | Gradient zero at occluded regions | Edge-based loss |
| Local color minima | Ambiguous BRDF | Material regularization |
| Depth-normal ambiguity | Shading underdetermined | Multi-view + normal prior |

### 2.2 Multi-Scale Loss Pyramid

```python
import torch
import torch.nn.functional as F

def pyramid_photometric_loss(
    rendered: torch.Tensor,   # (B, C, H, W)
    reference: torch.Tensor,  # (B, C, H, W)
    n_levels: int = 4,
    weights: list[float] | None = None,
) -> torch.Tensor:
    """
    Multi-scale photometric loss via Gaussian pyramid.
    Coarse levels pull geometry to the right basin; fine levels sharpen.
    """
    if weights is None:
        weights = [2**(-i) for i in range(n_levels)]
    total_loss = torch.zeros(1, device=rendered.device)
    r, ref = rendered, reference
    for i in range(n_levels):
        total_loss = total_loss + weights[i] * F.l1_loss(r, ref)
        r = F.avg_pool2d(r, 2)
        ref = F.avg_pool2d(ref, 2)
    return total_loss
```

---

## III. Jacobian Conditioning

### 3.1 Condition Number Analysis

The conditioning of $\mathbf{J}^T \mathbf{J}$ determines optimization stability:

$$\kappa = \frac{\sigma_{max}(\mathbf{J})}{\sigma_{min}(\mathbf{J})}$$

For inverse rendering:
- $\kappa \ll 100$: well-conditioned, gradient descent converges
- $\kappa \sim 10^3$: requires preconditioning or natural gradient
- $\kappa > 10^6$: numerically degenerate (e.g. back-faces, textureless regions)

### 3.2 Fisher Information Matrix

The Fisher Information Matrix is the expected Jacobian outer product:

$$\mathbf{F}(\boldsymbol{\xi}) = \mathbb{E}\left[\mathbf{J}^T \mathbf{J}\right]$$

Natural gradient descent uses the Fisher metric:

$$\boldsymbol{\xi}_{t+1} = \boldsymbol{\xi}_t - \eta \, \mathbf{F}^{-1}(\boldsymbol{\xi}_t) \nabla_{\boldsymbol{\xi}} \mathcal{L}$$

This adaptively scales parameter updates by their sensitivity to the image — high-sensitivity parameters (diffuse albedo) take small steps; low-sensitivity parameters (specular roughness in textureless regions) take larger steps.

---

## IV. Edge-Based Loss

```python
def edge_loss(
    rendered: torch.Tensor,
    reference: torch.Tensor,
    sigma: float = 1.0,
) -> torch.Tensor:
    """
    Sobel edge-based loss. More sensitive to silhouette geometry
    than photometric loss alone.
    """
    def sobel(img: torch.Tensor) -> torch.Tensor:
        kx = torch.tensor([[-1,0,1],[-2,0,2],[-1,0,1]], dtype=torch.float32)
        ky = kx.T
        kx = kx.view(1,1,3,3).expand(3,-1,-1,-1)
        ky = ky.view(1,1,3,3).expand(3,-1,-1,-1)
        ex = F.conv2d(img, kx, padding=1, groups=3)
        ey = F.conv2d(img, ky, padding=1, groups=3)
        return torch.sqrt(ex**2 + ey**2 + 1e-8)
    return F.l1_loss(sobel(rendered), sobel(reference))
```

---

## V. Combined Loss for Stable Optimization

$$\mathcal{L}_{total} = \alpha \mathcal{L}_{photo} + \beta \mathcal{L}_{edge} + \gamma \mathcal{L}_{SSIM} + \delta \mathcal{L}_{eikonal}$$

| Weight | Value | Rationale |
|--------|-------|-----------|
| $\alpha$ | 1.0 | Primary photometric signal |
| $\beta$ | 0.2 | Silhouette alignment |
| $\gamma$ | 0.05 | Perceptual coherence |
| $\delta$ | 0.1 | SDF regularity (if neural SDF) |

---

## References

- Loubet, G. et al. (2019). Reparameterizing Discontinuous Integrands for Differentiable Rendering. *SIGGRAPH Asia 2019*.
- Amari, S. (1998). Natural Gradient Works Efficiently in Learning. *Neural Computation*, 10(2), 251-276.
- Wang, Z. et al. (2004). Image Quality Assessment: From Error Visibility to Structural Similarity. *IEEE TIP*, 13(4), 600-612.
- Nomizu, K. & Sasaki, T. (1994). *Affine Differential Geometry*. Cambridge University Press.
