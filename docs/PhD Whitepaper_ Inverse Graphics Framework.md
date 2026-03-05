# Inverse Graphics: A Differentiable Framework for Geometry Recovery

A rigorous whitepaper on inverse graphics — recovering 3D geometry, material properties, and lighting from 2D observations — via differentiable rendering, gradient-based optimization, and physics-informed priors.

---

## I. Problem Formulation

Inverse graphics seeks to invert the rendering function $\mathcal{R}$:

$$\mathbf{I} = \mathcal{R}(\mathcal{M}, \boldsymbol{\Phi}, \mathbf{L}, \mathbf{P})$$

where $\mathbf{I}$ is the observed image, $\mathcal{M}$ is the geometry (mesh or SDF), $\boldsymbol{\Phi}$ are material parameters (BRDF), $\mathbf{L}$ is the lighting environment, and $\mathbf{P}$ are camera parameters.

The inverse problem: given $\{\mathbf{I}_k\}_{k=1}^N$ from $N$ views, recover $(\mathcal{M}, \boldsymbol{\Phi}, \mathbf{L})$ by minimizing:

$$\mathcal{L}_{total} = \underbrace{\sum_{k=1}^N \|\mathcal{R}(\mathcal{M}, \boldsymbol{\Phi}, \mathbf{L}, \mathbf{P}_k) - \mathbf{I}_k\|_1}_{\text{photometric loss}} + \lambda_g \underbrace{\mathcal{L}_{geometry}}_{\text{regularization}} + \lambda_s \underbrace{\mathcal{L}_{smooth}}_{\text{smoothness}}$$

---

## II. Differentiable Rendering

### 2.1 Rasterization Gradient via SoftRas

Classical rasterization is not differentiable due to hard triangle boundaries. SoftRasterizer (Liu et al., 2019) replaces the indicator function with a smooth sigmoid:

$$D(q, f_j) = \text{sigmoid}\left(\frac{d(q, f_j)}{\sigma}\right)$$

where $d(q, f_j)$ is the signed distance from pixel $q$ to triangle edge $f_j$ and $\sigma$ controls sharpness.

The aggregated color at pixel $q$:

$$C(q) = \sum_j \frac{w_j(q)}{\sum_l w_l(q)} c_j, \quad w_j(q) = D(q, f_j) \cdot \exp(-z_j / \gamma)$$

This makes $\frac{\partial C}{\partial \mathbf{V}}$ well-defined via backprop through vertex positions $\mathbf{V}$.

### 2.2 Physics-Based Differentiable Rendering (Mitsuba 3)

For physically accurate inverse rendering, the rendering equation:

$$L_o(\mathbf{x}, \omega_o) = \int_\Omega f_r(\mathbf{x}, \omega_i, \omega_o) L_i(\mathbf{x}, \omega_i) |\cos\theta_i| \, d\omega_i$$

is differentiated through Monte Carlo integration using **reparameterization** and **detached sampling** strategies (Jakob et al., 2022).

```python
import mitsuba as mi
import drjit as dr

mi.set_variant("cuda_ad_rgb")

scene = mi.load_file("scene.xml")
params = mi.traverse(scene)

# Differentiate w.r.t. mesh vertex positions
params.keep(["mesh.vertex_positions"])

img_ref = mi.render(scene, spp=64)

def loss(params):
    img = mi.render(scene, params, spp=16)
    return dr.mean(dr.sqr(img - img_ref))

# Gradient-based optimization
opt = mi.ad.Adam(lr=0.01, params=params)
for step in range(100):
    dr.enable_grad(params["mesh.vertex_positions"])
    L = loss(params)
    dr.backward(L)
    opt.step()
    params.update(opt)
```

---

## III. Geometry Representation and Optimization

### 3.1 Implicit SDF Optimization

Represent geometry as a neural SDF $\phi_\theta: \mathbb{R}^3 \to \mathbb{R}$:

```python
import torch
import torch.nn as nn

class NeuralSDF(nn.Module):
    def __init__(self, hidden: int = 256, layers: int = 8):
        super().__init__()
        dims = [3] + [hidden] * layers + [1]
        self.net = nn.Sequential(*[
            nn.Sequential(nn.Linear(dims[i], dims[i+1]),
                          nn.Softplus(beta=100))
            for i in range(len(dims) - 1)
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    def eikonal_loss(self, x: torch.Tensor) -> torch.Tensor:
        """Enforce ||∇φ|| = 1 everywhere."""
        x.requires_grad_(True)
        phi = self(x)
        grad = torch.autograd.grad(phi.sum(), x, create_graph=True)[0]
        return ((grad.norm(dim=-1) - 1.0) ** 2).mean()
```

Geometry loss = photometric loss + $\lambda_e$ eikonal loss + 3D supervision (if available).

---

## IV. Material Recovery (BRDF Estimation)

### 4.1 GGX Microfacet BRDF

The Cook-Torrance microfacet BRDF:

$$f_r(\omega_i, \omega_o) = \frac{D(\mathbf{h}) G(\omega_i, \omega_o) F(\omega_i, \mathbf{h})}{4 (\mathbf{n} \cdot \omega_i)(\mathbf{n} \cdot \omega_o)}$$

where $D$ is the GGX distribution, $G$ is the Smith shadowing-masking term, $F$ is the Fresnel term.

Differentiating $f_r$ w.r.t. roughness $\alpha$ and albedo $\mathbf{k}$ yields closed-form gradients for BRDF optimization.

---

## V. Inverse Graphics Pipeline

```
Input: N multi-view images
  ↓
Camera calibration (COLMAP)
  ↓
Initial geometry: dense point cloud → marching cubes mesh
  ↓
Differentiable rendering (SoftRas / Mitsuba3)
  ↓
Gradient descent on (V, Φ, L) jointly
  ↓
Output: reconstructed mesh + PBR materials + HDR lighting
```

---

## References

- Liu, S. et al. (2019). Soft Rasterizer: A Differentiable Renderer. *ICCV 2019*.
- Jakob, W. et al. (2022). Mitsuba 3: A Retargetable Forward and Inverse Renderer. *SIGGRAPH Asia 2022*.
- Wang, P. et al. (2021). NeuS: Learning Neural Implicit Surfaces by Volume Rendering. *NeurIPS 2021*.
- Yariv, L. et al. (2020). Multiview Neural Surface Reconstruction. *NeurIPS 2020*.
