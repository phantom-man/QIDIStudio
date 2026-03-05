# PhD-Level 3D Model Perfection: Manifold Parameterization for Filleted Prismatic Surfaces

Achieving a geometrically faithful texture wrap on prismatic CAD parts — devices with filleted corners, mechanical cutouts, and topological holes — requires a rigorous treatment of surface parameterization theory. This document develops the mathematical and algorithmic framework for computing distortion-minimal UV maps on genus-$g$ prismatic manifolds, with direct application to the QIDIStudio texture pipeline.

---

## I. Differential Geometry of Prismatic Manifolds

### I.1 Curvature Analysis

A prismatic body $\mathcal{M}$ is a piecewise-smooth manifold: flat faces with $K = 0$ (developable), connected by fillets with $K > 0$ (elliptic) and $H > 0$. The curvature tensor at a point $\mathbf{p} \in \mathcal{M}$:

$$\kappa_1(\mathbf{p}), \quad \kappa_2(\mathbf{p}) = \text{principal curvatures}$$
$$K(\mathbf{p}) = \kappa_1 \kappa_2 \quad \text{(Gaussian — intrinsic, preserved under bending)}$$
$$H(\mathbf{p}) = \tfrac{1}{2}(\kappa_1 + \kappa_2) \quad \text{(Mean — extrinsic, drives minimal surfaces)}$$

For a typical phone chassis:

| Region | $K$ | $H$ | Parameterization challenge |
|--------|-----|-----|---------------------------|
| Flat back face | $0$ | $0$ | Developable — planar map is exact |
| Quarter-round fillet (radius $r$) | $1/r^2$ | $1/r$ | LSCM angle error $\propto K$ |
| Camera island rim | $>0$ | $>0$ | Genus-1 boundary loop — needs seam cut |
| Cutout boundary | $\infty$ (crease) | $\infty$ | Non-manifold edge — must be marked as seam |

The **Gauss-Bonnet theorem** constrains any UV parameterization:

$$\int_\mathcal{M} K\, dA + \int_{\partial\mathcal{M}} \kappa_g\, ds = 2\pi\chi(\mathcal{M})$$

For a flat rectangular back with $n_h$ through-holes (camera cutouts, ports): $\chi = 1 - n_h$. Each hole requires one seam cut to reduce the topology to a disk before conformal unwrapping.

### I.2 Topological Preprocessing

For a phone chassis with: camera island (genus-1 hole) + $n$ port cutouts (genus-$n$ holes), the **Euler characteristic** is:

$$\chi = V - E + F = 2 - 2g - n_b$$

where $g$ is genus and $n_b$ is number of boundary components. A disk (contractible 2-manifold with boundary) has Euler characteristic $\chi = 1$; each additional topological through-hole reduces $\chi$ by 1 (annulus: $\chi = 0$; pair-of-pants: $\chi = -1$) [Hatcher, *Algebraic Topology*, Cambridge University Press, 2002, §2.2]. Standard LSCM requires a disk topology ($\chi = 1$) — each hole needs exactly one boundary seam cut.

**Algorithm: Boundary Loop Extraction for Seam Marking**

```python
import bpy, bmesh

def mark_boundary_seams(obj):
    """Mark all non-manifold boundary edges as UV seams.
    This isolates every topological hole (camera cutouts, port holes,
    button openings) as independent UV islands, preventing texture
    distortion across mechanical feature boundaries."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)

    seam_count = 0
    for edge in bm.edges:
        # Boundary edge: exactly one adjacent face (disk boundary)
        if len(edge.link_faces) == 1:
            edge.seam = True
            seam_count += 1

    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')
    return seam_count
```

---

## II. UV Parameterization for Prismatic Geometry

### II.1 Least-Squares Conformal Maps (LSCM)

The LSCM energy functional (Lévy et al., 2002) minimises angular distortion:

$$E_\text{LSCM}(\mathbf{u}) = \int_\mathcal{M} \|\nabla u - \mathbf{N} \times \nabla v\|^2\, dA$$

where $\mathbf{N}$ is the surface normal, and $(u, v)$ are the UV coordinates. This energy vanishes iff the map is conformal (angle-preserving). For a triangle mesh, the discrete form becomes:

$$E_\text{LSCM} = \sum_{t \in F} A_t \left\| \nabla_t u - \mathbf{N}_t \times \nabla_t v \right\|^2$$

Minimising over all free vertices (with 2 pinned for uniqueness) yields a sparse linear system $L\mathbf{u} = \mathbf{b}$ where $L$ is the complex-valued cotangent Laplacian:

$$L_{ij} = \begin{cases} -\frac{1}{2}(\cot\alpha_{ij} + \cot\beta_{ij}) & (i,j) \in E \\ \sum_{k \sim i} \frac{1}{2}(\cot\alpha_{ik} + \cot\beta_{ik}) & i = j \end{cases}$$

**LSCM for CAD parts** (30° seam placement):

```python
def lscm_unwrap_prismatic(obj, seam_angle_deg=30.0):
    """LSCM conformal unwrap for prismatic/CAD geometry.

    Strategy: seams at sharp dihedral edges (>=30°) + all boundary loops.
    - 30° threshold: every flat face panel becomes its own island.
    - Boundary loops: every mechanical cutout is isolated.
    This prevents LSCM angular error from accumulating across hard edges.
    """
    import math
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.mark_seam(clear=True)                        # clear old seams

    # Seams at dihedral >= 30° (CAD hard edges)
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(seam_angle_deg))
    bpy.ops.mesh.mark_seam(clear=False)

    # Seams at all boundary loops (holes, ports)
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_non_manifold(extend=False, use_boundary=True,
                                     use_wire=False, use_multi_face=False,
                                     use_non_contiguous=False, use_verts=False)
    bpy.ops.mesh.mark_seam(clear=False)

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')
```

### II.2 As-Rigid-As-Possible (ARAP) Refinement

ARAP (Sorkine & Alexa, 2007) iteratively minimises the isometric energy:

$$E_\text{ARAP}(\mathbf{u}) = \sum_{t \in F} A_t \sum_{i=1}^{3} \left\| J_t \mathbf{e}_{t,i} - R_t \mathbf{e}_{t,i} \right\|^2$$

where $J_t$ is the UV Jacobian of face $t$, $R_t \in SO(2)$ is the nearest rotation, and $\mathbf{e}_{t,i}$ are the 3D edge vectors. The iteration alternates:
1. **Local step**: $R_t \leftarrow \text{nearest rotation to } J_t$ (closed-form SVD)
2. **Global step**: solve $L\mathbf{u} = \mathbf{b}(R_1, \ldots, R_F)$ (sparse linear solve)

ARAP is primarily used via **libigl** for post-processing the LSCM result:

```python
import igl, numpy as np, scipy.sparse

def arap_refine(V, F, uv_init):
    """Refine LSCM UV with ARAP — reduces area distortion while
    preserving the conformal structure as much as possible."""
    arap_data = igl.arap_precomputation(V, F, dim=2)
    uv = uv_init.copy()
    for _ in range(10):           # 10 iterations is typically sufficient
        uv = igl.arap_solve(np.zeros((0, 2)), arap_data, uv)
    return uv
```

### II.3 Projection Strategy Selection

| Mesh class | Condition | Projection | Rationale |
|------------|-----------|------------|-----------|
| PRISMATIC | $K \approx 0$, sharp edges $> 30\%$ | OBJECT (XY box) | Flat faces: developable, no UV fragmentation |
| REVOLUTION | $z_\text{ratio} \geq 1$, smooth, **not conical** | Cylinder | Single seam, isometric on true cylinder |
| REVOLUTION | Conical taper $> 20\%$ | LSCM 30° | Cylinder_project degenerates on frustum sections |
| ORGANIC | Smooth, low sharp-edge fraction | LSCM 60° | Lévy 2002: angle-preserving on curved manifolds |

---

## III. UV Stretch Metrics for Quality Validation

After parameterization, three metrics quantify distortion. For face $i$ with 3D area $a_{3,i}$ and UV area $a_{u,i}$:

**Normalised stretch** (isometric deviation):
$$s_i = \frac{a_{3,i} \cdot \sum_j a_{u,j}}{a_{u,i} \cdot \sum_j a_{3,j}}$$

$s_i = 1$ is isometric; $s_i > 1$ = UV under-represented (texture compressed in 3D); $s_i < 1$ = UV over-represented (texture stretched in 3D).

**Aggregate stretch energy:**
$$E_D = \sum_{i} \max(s_i - 1, 0)^2 \cdot a_{3,i}$$

**Angular distortion** (conformal error):
$$E_C = \sum_{i} \left\| J_i J_i^T - I \right\|_F^2 \cdot a_{3,i}$$

Threshold values for prismatic CAD:

| Metric | Excellent | Acceptable | Fail |
|--------|-----------|-----------|------|
| $E_D$ (normalised) | $< 10$ | $< 50$ | $\geq 50$ |
| High-energy fraction ($s_i > 3$) | $< 5\%$ | $< 15\%$ | $\geq 15\%$ |
| Mean stretch $\bar{s}$ | $[0.9, 1.1]$ | $[0.8, 1.5]$ | outside |

---

## IV. Genus-Handling: Camera Island Topology

For a phone back with a protruding camera island (topological handle or through-hole), the genus affects the minimum number of seam cuts required by the Riemann uniformization theorem:

- **Flat hole** (punch-through): 1 boundary loop → 1 seam cut per hole
- **Raised island** (solid protrusion, no hole): genus-0 sub-manifold → no extra seam needed; handle as a separate UV chart
- **Island with cutouts** (4 sensor holes in island): 4 seam cuts

**Practical implementation pattern** for 4-camera island:

```python
def handle_camera_island(obj):
    """Process a phone back with camera island:
    1. Separate the island as its own UV chart via sharp-edge seams.
    2. Mark the 4 sensor boundary loops as additional seams.
    3. Run LSCM — each sensor cutout gets an isolated island.
    """
    bpy.ops.object.mode_set(mode='EDIT')

    # Sharp edges at island perimeter (near-90° step)
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.edges_select_sharp(sharpness=1.2217)    # ~70°
    bpy.ops.mesh.mark_seam(clear=False)

    # Sensor hole boundary seams
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_non_manifold(extend=False, use_boundary=True,
                                     use_wire=False, use_multi_face=False,
                                     use_non_contiguous=False, use_verts=False)
    bpy.ops.mesh.mark_seam(clear=False)

    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.002)
    bpy.ops.object.mode_set(mode='OBJECT')
```

---

## V. Spectral Shape Analysis Integration

The Laplace-Beltrami operator $\Delta_\mathcal{M}$ on a compact Riemannian manifold has a discrete eigensystem:

$$L\mathbf{f} = \lambda M\mathbf{f}$$

where $L$ is the cotangent stiffness matrix and $M$ is the diagonal mass matrix. The first $k$ eigenvalues $0 = \lambda_0 < \lambda_1 \leq \ldots \leq \lambda_{k-1}$ form the **Shape DNA** (Reuter et al., 2006) — an isometry-invariant descriptor.

For prismatic classification, three features are computed:

```python
import igl
import numpy as np

def compute_shape_dna(V, F, k=20):
    """Compute Shape DNA: first k eigenvalues of the Laplace-Beltrami operator."""
    L = igl.cotmatrix(V, F)             # cotangent stiffness matrix
    M = igl.massmatrix(V, F, igl.MASSMATRIX_TYPE_VORONOI)
    # Solve generalized eigenproblem Lf = λMf
    # Use ARPACK (shift-invert) for sparse efficiency
    from scipy.sparse.linalg import eigsh
    eigenvalues, _ = eigsh(-L, k=k, M=M, sigma=0, which='LM')
    eigenvalues = np.sort(np.abs(eigenvalues))
    return eigenvalues          # shape[k], invariant under isometry

def shape_dna_distance(dna_a, dna_b):
    """L2 distance between two Shape DNA vectors (normalised)."""
    a = dna_a / np.linalg.norm(dna_a)
    b = dna_b / np.linalg.norm(dna_b)
    return np.linalg.norm(a - b)
```

**Eigenvalue ratio for REVOLUTION detection:** for rotationally symmetric shapes, the first two non-trivial eigenvalues form a degenerate pair: $\lambda_1 \approx \lambda_2$. The ratio $\lambda_1/\lambda_2 > 0.85$ flags a REVOLUTION candidate (Reuter 2006).

---

## VI. Blender Displacement Pipeline Integration

Once UV coordinates are computed, the texture is applied via Blender's Displace modifier with `texture_coords='UV'`:

```python
def apply_texture_displacement(obj, tex_path, tile_size_mm,
                                relief_mm=0.3, invert=False):
    """Apply displacement map using calibrated UV coordinates."""
    # Load texture image
    tex_img = bpy.data.images.load(tex_path)
    tex = bpy.data.textures.new("SkinTex", type='IMAGE')
    tex.image = tex_img

    # Add Displace modifier
    d = obj.modifiers.new("Displace", type='DISPLACE')
    d.texture = tex
    d.texture_coords = 'UV'
    d.uv_layer = obj.data.uv_layers.active.name
    d.strength = relief_mm * (-1 if invert else 1)
    d.mid_level = 0.0           # 0.0 = black pixels = no displacement

    # Apply
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(active_object=obj):
        bpy.ops.object.modifier_apply(modifier="Displace")
```

The `mid_level=0.0` setting is critical: with the standard default of 0.5, black pixels (0) map to -0.5 amplitude (inward), which is undesirable for surface embossing. Setting `mid_level=0.0` maps black → no displacement, white → full `+strength` amplitude.

---

## VII. References

1. Lévy, B., Petitjean, S., Ray, N., & Maillot, J. (2002). Least squares conformal maps for automatic texture atlas generation. *ACM SIGGRAPH*, 362–371.
2. Sorkine, O., & Alexa, M. (2007). As-rigid-as-possible surface modeling. *Eurographics Symposium on Geometry Processing*, 109–116.
3. Reuter, M., Wolter, F.-E., & Peinecke, N. (2006). Laplace-Beltrami spectra as 'Shape-DNA' of surfaces and solids. *CAD 38*(4), 342–366.
4. Floater, M.S., & Hormann, K. (2005). Surface parameterization: a tutorial and survey. *Advances in Multiresolution for Geometric Modelling*, 157–186.
5. Crane, K. (2023). Discrete Differential Geometry (course notes). Carnegie Mellon University.
6. QIDIStudio: `resources/scripts/apply_texture_bpy.py` — `_do_uv_unwrap`, `_mesh_is_conical`, `_calculate_uv_stretch_metrics`
