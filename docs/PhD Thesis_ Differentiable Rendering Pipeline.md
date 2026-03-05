# Differentiable Rendering Pipeline: From Scene Parameters to Gradient Flow

A comprehensive treatment of differentiable rendering — the bridge between 3D scene representation and gradient-based inverse optimization — covering autodiff-compatible ray tracing, reparameterizable sampling, and end-to-end training of geometry and material parameters.

---

## I. Mathematical Foundation

### 1.1 The Rendering Equation as a Differentiable Map

The rendering integral:

$$L(\mathbf{x}, \omega_o) = L_e(\mathbf{x}, \omega_o) + \int_\Omega f_r(\mathbf{x}, \omega_i, \omega_o) L(\mathbf{x}'(\mathbf{x}, \omega_i), -\omega_i) |\cos\theta_i| \, d\omega_i$$

is a fixed-point equation. Differentiating with respect to scene parameters $\boldsymbol{\xi}$ requires differentiating through:
1. The surface intersection $\mathbf{x}'(\mathbf{x}, \omega_i)$ — a discontinuous function of geometry
2. The BRDF $f_r$ — differentiable w.r.t. material parameters
3. The visibility function $V(\mathbf{x}, \mathbf{x}')$ — a step function in geometry

### 1.2 Handling Discontinuities

Three strategies for differentiating through geometric discontinuities:

| Strategy | Method | Bias | Variance |
|----------|--------|------|---------|
| Edge integral sampling | Boundary terms at silhouettes | Unbiased | High |
| Soft geometry (SoftRas) | Sigmoid boundaries | Biased | Low |
| Reparameterization | Auxiliary path sampling | Unbiased | Medium |

---

## II. Implementation with Mitsuba 3 + DrJIT

### 2.1 Scene Parametrization

```python
import mitsuba as mi
import drjit as dr
import numpy as np

mi.set_variant("cuda_ad_rgb")

def build_scene(mesh_path: str, roughness: float = 0.3) -> mi.Scene:
    return mi.load_dict({
        "type": "scene",
        "sensor": {
            "type": "perspective",
            "fov": 45,
            "to_world": mi.ScalarTransform4f.look_at(
                origin=[0, 0, 3], target=[0, 0, 0], up=[0, 1, 0]
            ),
            "film": {"type": "hdrfilm", "width": 512, "height": 512},
        },
        "mesh": {
            "type": "obj",
            "filename": mesh_path,
            "bsdf": {
                "type": "roughconductor",
                "alpha": roughness,
                "distribution": "ggx",
            },
        },
        "light": {"type": "envmap", "filename": "envmap.exr"},
    })
```

### 2.2 Gradient Accumulation Loop

```python
def optimize_scene(
    scene: mi.Scene,
    ref_images: list[np.ndarray],
    n_steps: int = 200,
    lr: float = 5e-3,
) -> dict[str, dr.ArrayXf]:
    """Optimize roughness and vertex positions to match reference images."""
    params = mi.traverse(scene)
    params.keep(["mesh.vertex_positions", "mesh.bsdf.alpha"])

    opt = mi.ad.Adam(lr=lr, params=params)

    for step in range(n_steps):
        total_loss = dr.zeros(dr.llvm.Float)
        for k, ref in enumerate(ref_images):
            ref_t = mi.TensorXf(ref)
            img = mi.render(scene, params, spp=4, seed=step * 100 + k)
            loss_k = dr.mean(dr.sqr(img - ref_t))
            total_loss += loss_k

        dr.backward(total_loss)
        opt.step()
        params.update(opt)

        if step % 20 == 0:
            print(f"step {step:4d}  loss={float(total_loss):.6f}")

    return dict(params)
```

---

## III. Geometry Gradient Flow

### 3.1 Vertex Position Gradients

For a triangle mesh with vertices $\mathbf{V} \in \mathbb{R}^{V \times 3}$, the gradient of the photometric loss:

$$\frac{\partial \mathcal{L}}{\partial \mathbf{V}_i} = \frac{\partial \mathcal{L}}{\partial \mathbf{I}} \frac{\partial \mathbf{I}}{\partial \mathbf{V}_i}$$

The Jacobian $\frac{\partial \mathbf{I}}{\partial \mathbf{V}_i}$ is computed via two contributions:
1. **Shading contribution**: vertex moves → normal changes → shading changes
2. **Silhouette contribution**: vertex moves → triangle boundary shifts → coverage changes

The silhouette contribution requires the **boundary integral** formulation (Loubet et al., 2019):

$$\frac{\partial \mathbf{I}}{\partial \boldsymbol{\xi}} \bigg|_{silhouette} = \oint_{\partial \mathcal{M}} (L^+ - L^-) \frac{\partial s}{\partial \boldsymbol{\xi}} \, d\ell$$

where $s$ is the signed distance to the silhouette edge and $L^{\pm}$ are the foreground/background radiances.

---

## IV. Training a Complete Inverse Renderer

### 4.1 Loss Function Decomposition

$$\mathcal{L} = \underbrace{\alpha \mathcal{L}_{RGB}}_{\text{photometric}} + \underbrace{\beta \mathcal{L}_{SSIM}}_{\text{perceptual}} + \underbrace{\gamma \mathcal{L}_{eikonal}}_{\text{SDF regularity}} + \underbrace{\delta \mathcal{L}_{normal}}_{\text{normal supervision}}$$

| Term | Weight | Formula |
|------|--------|---------|
| $\mathcal{L}_{RGB}$ | 1.0 | $\|\hat{\mathbf{I}} - \mathbf{I}\|_1$ |
| $\mathcal{L}_{SSIM}$ | 0.1 | $1 - \text{SSIM}(\hat{\mathbf{I}}, \mathbf{I})$ |
| $\mathcal{L}_{eikonal}$ | 0.1 | $\mathbb{E}[\|\|\nabla\phi\|\| - 1]^2$ |
| $\mathcal{L}_{normal}$ | 0.05 | $1 - \cos(\hat{\mathbf{n}}, \mathbf{n}_{gt})$ |

---

## V. Performance Benchmarks

| Pipeline | Resolution | SPP | FPS (A100) | Gradient Time |
|---------|-----------|-----|-----------|---------------|
| SoftRas (CPU) | 256² | — | 8 | 120 ms |
| PyTorch3D | 512² | — | 45 | 22 ms |
| Mitsuba 3 (CUDA) | 512² | 16 | 12 | 84 ms |
| Mitsuba 3 + DrJIT | 512² | 64 | 3 | 330 ms |

---

## References

- Jakob, W. et al. (2022). Mitsuba 3: A Retargetable Forward and Inverse Renderer. *SIGGRAPH Asia 2022*.
- Loubet, G. et al. (2019). Reparameterizing Discontinuous Integrands for Differentiable Rendering. *SIGGRAPH Asia 2019*.
- Li, T-M. et al. (2018). Differentiable Monte Carlo Ray Tracing. *SIGGRAPH Asia 2018*.
- Niemeyer, M. et al. (2020). Differentiable Volumetric Rendering. *CVPR 2020*.
