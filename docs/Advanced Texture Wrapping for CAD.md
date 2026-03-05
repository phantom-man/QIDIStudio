# Advanced Texture Wrapping for CAD Parts

UV texture wrapping on industrial CAD geometry requires a principled application of differential geometry and discrete parameterization theory. Unlike organic sculpts, CAD parts present piecewise-flat manifolds with sharp creases, mechanical cutouts, and prescribed curvature constraints — each of which demands different parameterization strategies. This document establishes the theoretical foundation, algorithm selection criteria, and production implementation for the QIDIStudio texture pipeline.

---

## I. Parameterization Taxonomy for CAD Geometry

A UV parameterization $\phi: \mathcal{M} \to \Omega \subset \mathbb{R}^2$ is evaluated along three distortion axes:

| Distortion type | Measure | Ideal value | Impact |
|----------------|---------|-------------|--------|
| Angular (conformal) | $E_C = \|\sigma_1/\sigma_2 - 1\|$ | 0 | Texture shear / skew |
| Area (isometric) | $E_A = \|(\sigma_1 \sigma_2) - 1\|$ | 0 | Density non-uniformity |
| Stretch (combined) | $E_D = \max(s_i - 1, 0)^2$ | 0 | Visible compression bands |

where $\sigma_1, \sigma_2$ are the singular values of the face Jacobian $J_i = \partial \phi / \partial \mathbf{x}$.

**Gauss-Bonnet constraint:** No bijective map from a curved surface to a plane can minimise all three simultaneously — this is the fundamental impossibility theorem of surface parameterization. The choice of which distortion to minimise is driven by the geometric class of the part.

---

## II. LSCM — Least-Squares Conformal Maps

LSCM (Lévy et al., 2002) minimises the **conformal energy**:

$$E_\text{LSCM}(\mathbf{u}) = \int_\mathcal{M} \|\nabla u - \mathbf{N} \times \nabla v\|^2\, dA$$

The condition $\nabla u = \mathbf{N} \times \nabla v$ is the discrete Cauchy-Riemann equation — it enforces that the map is angle-preserving. Expanding over a triangle mesh:

$$E_\text{LSCM} = \sum_{t \in F} A_t \left\|J_t - R_t\right\|_F^2, \quad R_t \in SO(2)$$

The minimiser satisfies the *complex-valued* Laplacian equation $\tilde{L}\mathbf{z} = \mathbf{0}$ where $\mathbf{z} = u + iv$ and $\tilde{L}$ is the cotangent-weighted complex Laplacian. Two vertices are pinned as boundary conditions to remove the 4-DOF null space (translation, rotation, scaling).

**When to use LSCM for CAD:**
- REVOLUTION surfaces (bottles, nozzles) — LSCM minimises shear across the curved wall
- Organic fillets on prismatic parts — smooth angle variation across the radius transition
- Any surface where ISO 1302 surface texture direction must follow curvature lines

**Blender LSCM implementation:**

```python
import bpy, math

def apply_lscm(obj, seam_angle_deg=30.0):
    """LSCM conformal unwrap for CAD/prismatic geometry.
    seam_angle_deg=30: marks every panel edge (dihedral ≥30°) as a seam.
    This prevents LSCM from accumulating conformal error across hard creases.
    """
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.mark_seam(clear=True)

    # Hard-edge seams (dihedral ≥ seam_angle_deg)
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(seam_angle_deg))
    bpy.ops.mesh.mark_seam(clear=False)

    # Boundary-loop seams (cutouts, ports, camera holes)
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_non_manifold(extend=False, use_boundary=True,
                                     use_wire=False, use_multi_face=False,
                                     use_non_contiguous=False, use_verts=False)
    bpy.ops.mesh.mark_seam(clear=False)

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')
```

---

## III. ARAP — As-Rigid-As-Possible

ARAP (Sorkine & Alexa, 2007) minimises **isometric deviation**:

$$E_\text{ARAP}(\mathbf{u}) = \sum_{t \in F} A_t \sum_{i=1}^{3} \|J_t\,\mathbf{e}_{t,i} - R_t\,\mathbf{e}_{t,i}\|^2$$

where $R_t \in SO(2)$ is the rotation closest to $J_t$ (nearest-rotation projection via SVD). Unlike LSCM, ARAP allows non-conformal maps — it tolerates mild angular distortion in exchange for area preservation. This is preferable when the texture pattern must maintain uniform density across the surface (e.g., hexagonal knurling where each cell must have equal physical size).

**ARAP iteration** (local-global, Sorkine & Alexa §4):

$$\text{Local: } R_t \leftarrow \arg\min_{R \in SO(2)} \|J_t - R\|_F = UV^\top \text{ from SVD}(J_t)$$
$$\text{Global: } L\mathbf{u} = \mathbf{b}(R_1,\ldots,R_F) \quad \text{(sparse Cholesky solve)}$$

```python
import igl, numpy as np

def arap_unwrap(V, F, uv_init, n_iters=10):
    """Run ARAP parameterization using libigl.
    V: (n,3) vertex positions
    F: (f,3) face indices
    uv_init: (n,2) initial UV from LSCM — ARAP requires a good initialisation
    """
    arap_data = igl.arap_precomputation(V, F, dim=2)
    uv = uv_init.copy()
    for _ in range(n_iters):
        uv = igl.arap_solve(np.zeros((0, 2)), arap_data, uv)
    return uv
```

**LSCM vs ARAP decision:**

| Geometry | Prefer LSCM | Prefer ARAP |
|---------|-------------|-------------|
| Curved bottles / nozzles | ✓ low angular distortion | — more area distortion |
| Flat faces with uniform patterns | — | ✓ equal cell sizes |
| High-curvature organic | ✓ fast, good init | ✓ refine after LSCM |
| Large prismatic panel | — (OBJECT projection preferred) | — |

---

## IV. xAtlas — Production UV Atlas Generation

[xAtlas](https://github.com/jpcy/xatlas) (nothings, 2019) implements a complete CPU-side atlas pipeline: chart segmentation → LSCM per chart → skyline bin packing. It is the standard for multi-mesh scenes requiring consistent texel density.

```cpp
#include <xatlas.h>

xatlas::Atlas *atlas = xatlas::Create();

xatlas::MeshDecl decl;
decl.vertexCount         = num_verts;
decl.vertexPositionData  = positions.data();
decl.vertexPositionStride = sizeof(glm::vec3);
decl.vertexNormalData    = normals.data();
decl.vertexNormalStride  = sizeof(glm::vec3);
decl.indexCount          = num_indices;
decl.indexData           = indices.data();
decl.indexFormat         = xatlas::IndexFormat::UInt32;
xatlas::AddMesh(atlas, decl);

xatlas::PackOptions pack;
pack.texelsPerUnit = 256.0f;   // 256 texels per world-unit (mm): consistent density
pack.padding       = 2;        // 2-px gutter prevents chart bleeding
pack.maxChartSize  = 512;

xatlas::Generate(atlas, xatlas::ChartOptions{}, pack);

const xatlas::Mesh &out = atlas->meshes[0];
for (uint32_t i = 0; i < out.vertexCount; ++i) {
    float u = out.vertexArray[i].uv[0] / atlas->width;
    float v = out.vertexArray[i].uv[1] / atlas->height;
    // Store u, v in vertex buffer (may have MORE verts than input — seam duplicates)
}
xatlas::Destroy(atlas);
```

**`texelsPerUnit` density normalization:** The single most important xAtlas parameter. Setting `texelsPerUnit = N` guarantees that every world-unit of surface area receives $N^2$ texels, regardless of mesh scale. Without this, small and large objects in the same scene get radically different texel densities.

**Vertex count expansion:** xAtlas may produce more output vertices than input — UV seam edges require duplicated vertices (one UV per island boundary). Always allocate output buffers based on `out.vertexCount`, not the original vertex count.

---

## V. Seam Placement Strategy

Seam placement is equivalent to finding a **cut graph** $G_c \subset \mathcal{M}$ such that $\mathcal{M} \setminus G_c$ is homeomorphic to a disk. The minimum-cost cut graph minimises seam visibility (Sheffer & Hart, 2002):

$$\text{cost}(e) = w_\text{angle} \cdot \cos\theta_e + w_\text{vis} \cdot v_e + w_\text{len} \cdot \ell_e$$

where $\theta_e$ is the dihedral angle at edge $e$, $v_e$ is the visibility weight (back-facing edges preferred), and $\ell_e$ is the edge length.

**QIDIStudio implementation:**

- **PRISMATIC** (`seam_angle=30°`): seams at all dihedral edges $\geq 30°$. Every flat face panel becomes its own UV island — eliminates spike fans at crease junctions.
- **REVOLUTION** (`seam_angle=30°` + `cylinder_project POLAR_ZX`): single vertical seam at the ZX back plane. $f_\text{seam} = 2/n_\text{divisions} \approx 6\%$ for $n=32$.
- **ORGANIC** (`seam_angle=60°`): fewer, longer seams — minimises seam count on smooth surfaces.

In all cases, **boundary loops** (camera holes, port openings) are always marked as seams, regardless of the seam angle threshold. This is implemented via `bpy.ops.mesh.select_non_manifold(use_boundary=True)`.

---

## VI. Tile Density Calibration

For a texture tile of physical size $d_\text{tile}$ (mm), the UV scale factors enforce that one full tile period covers exactly $d_\text{tile}$ mm on the surface.

**Empirical calibration from edge statistics** (robust to irregular meshing):

```python
import numpy as np

def calibrate_tile_scale(obj, tile_size_mm, n_samples=2000):
    """Compute ratio of 3D edge length to UV edge length.
    Returns scale factor: multiply UV coords by this to set 1 UV unit = tile_size_mm."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.active.data
    ratios = []

    for poly in mesh.polygons:
        loop_start = poly.loop_start
        n = poly.loop_total
        for i in range(n):
            li      = loop_start + i
            li_next = loop_start + (i + 1) % n
            v0 = mesh.vertices[mesh.loops[li].vertex_index].co
            v1 = mesh.vertices[mesh.loops[li_next].vertex_index].co
            len_3d = (v1 - v0).length
            len_uv = (uv_layer[li].uv - uv_layer[li_next].uv).length
            if len_uv > 1e-8:
                ratios.append(len_3d / len_uv)
        if len(ratios) >= n_samples:
            break

    if not ratios:
        return 1.0
    ratio_mm_per_uv = np.median(ratios)   # robust against seam outliers
    return ratio_mm_per_uv / tile_size_mm
```

The **median** is used (not mean) because seam-adjacent loops have `len_uv ≈ 0` but `len_3d > 0`, producing extreme outliers that inflate the mean.

---

## VII. UV Quality Validation

After parameterization, three metrics are computed per face and aggregated:

**Normalised stretch $s_i$** (scale-invariant):
$$s_i = \frac{a_{3,i}\, \sum_j a_{u,j}}{a_{u,i}\, \sum_j a_{3,j}}$$

Scale invariance proof: scaling UV by $(k_u, k_v)$ multiplies $a_{u,i}$ and $\sum_j a_{u,j}$ by $k_u k_v$, which cancels. So $s_i$ depends only on the shape of the parameterization, not the tile scale.

**Aggregate distortion metrics:**

| Metric | Formula | CAD threshold |
|--------|---------|---------------|
| Stretch energy $E_D$ | $\sum_i \max(s_i-1,0)^2 \cdot a_{3,i}$ | $< 50$ |
| High-energy fraction | $|\{i: s_i>3\}|/|F|$ | $< 15\%$ |
| Mean stretch $\bar{s}$ | $\sum_i s_i a_{3,i} / \sum_i a_{3,i}$ | $\in [0.8, 1.5]$ |

High $E_D$ for a REVOLUTION mesh ($E_D > 100$) indicates a conical taper — `cylinder_project` should be replaced by LSCM via `_mesh_is_conical()` fallback.

---

## VIII. References

1. Lévy, B., Petitjean, S., Ray, N., & Maillot, J. (2002). Least squares conformal maps for automatic texture atlas generation. *ACM SIGGRAPH*, 362–371.
2. Sorkine, O., & Alexa, M. (2007). As-rigid-as-possible surface modeling. *Eurographics SGP*, 109–116.
3. Sheffer, A., & Hart, J.C. (2002). Seamster: inconspicuous low-distortion texture seam layout. *IEEE Visualization*, 291–298.
4. Nothings. xAtlas. https://github.com/jpcy/xatlas
5. Crane, K. (2023). Discrete Differential Geometry course notes. CMU.
6. QIDIStudio `apply_texture_bpy.py`: `_do_uv_unwrap`, `_mesh_is_conical`, `_calculate_uv_stretch_metrics`
