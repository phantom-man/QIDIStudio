# AI Debugging 3D Texture Mapping Pipelines

Debugging a production 3D texture mapping pipeline requires moving beyond ad-hoc visual inspection into systematic distortion analysis grounded in differential geometry. This document defines the measurement-first debugging workflow used in QIDIStudio: how to compute UV distortion metrics, how to interpret them geometrically, how to render diagnostic visualizations, and how to integrate an AI model as a structured critic in the feedback loop.

---

## I. The Measurement-First Debugging Principle

UV mapping errors fall into three orthogonal categories, each with distinct symptoms and algebraic signatures. Diagnosing by visual impression conflates all three; correct debugging isolates them:

| Error class | Symptom | Root metric |
|-------------|---------|-------------|
| Conformal distortion | Texture shear / skew — right angles in the texture appear oblique on the surface | $E_C = \|\sigma_1/\sigma_2 - 1\|$ (singular value ratio deviation) |
| Isometric distortion | Texel density non-uniformity — same mm² of surface gets different numbers of texels in different regions | $E_A = \|\sigma_1\sigma_2 - 1\|$ (area Jacobian deviation) |
| Stretch energy | Visible compression bands — one direction is highly compressed while the other is expanded | $E_D = \sum_i \max(s_i-1,0)^2 \cdot a_{3,i}$ |

where $\sigma_1, \sigma_2$ are the singular values of the face Jacobian $J_i = \partial\phi/\partial\mathbf{x}$ and $s_i$ is the normalised stretch of face $i$.

All three reduce to a common expression for face $i$ with 3D area $a_{3,i}$ and UV area $a_{u,i}$:

$$s_i = \frac{a_{3,i} \cdot \sum_j a_{u,j}}{a_{u,i} \cdot \sum_j a_{3,j}}$$

The sum ratio ensures scale-invariance: the metric captures the **shape** of the parameterization, not the absolute tile scale.

---

## II. Diagnostic Metrics Implementation

```python
import bpy, bmesh
import numpy as np

def calculate_uv_stretch_metrics(obj) -> dict:
    """Compute per-face stretch and aggregate UV quality metrics.

    Returns:
        E_D             — aggregate stretch energy (dimensionless, lower is better)
        high_energy_frac — fraction of 3D area in faces with s_i > 3
        mean_stretch     — area-weighted mean stretch across all faces
    """
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if not uv_layer:
        return {"E_D": float("nan"), "high_energy_frac": float("nan"), "mean_stretch": float("nan")}

    uv_data = uv_layer.data
    areas_3d = []
    areas_uv = []

    for poly in mesh.polygons:
        a3 = poly.area
        loops = list(poly.loop_indices)
        uvs = [uv_data[li].uv for li in loops]
        a_uv = 0.0
        n = len(uvs)
        for k in range(n):
            u0, v0 = uvs[k]
            u1, v1 = uvs[(k+1) % n]
            a_uv += u0 * v1 - u1 * v0
        a_uv = abs(a_uv) * 0.5
        areas_3d.append(a3)
        areas_uv.append(a_uv)

    areas_3d = np.array(areas_3d)
    areas_uv = np.array(areas_uv)

    sum_3d = areas_3d.sum()
    sum_uv = areas_uv.sum()
    if sum_uv < 1e-12:
        return {"E_D": float("nan"), "high_energy_frac": float("nan"), "mean_stretch": float("nan")}

    s = (areas_3d * sum_uv) / (areas_uv * sum_3d + 1e-15)

    E_D = float(np.sum(np.maximum(s - 1.0, 0.0)**2 * areas_3d))
    high_frac = float(np.sum(areas_3d[s > 3.0]) / sum_3d)
    mean_s = float(np.sum(s * areas_3d) / sum_3d)

    return {"E_D": E_D, "high_energy_frac": high_frac, "mean_stretch": mean_s}
```

**Quality thresholds for CAD parts:**

| Metric | Excellent | Acceptable | Fail — investigate |
|--------|-----------|-----------|-------------------|
| $E_D$ | $< 10$ | $< 50$ | $\geq 50$ |
| High-energy fraction | $< 5\%$ | $< 15\%$ | $\geq 15\%$ |
| Mean stretch $\bar{s}$ | $[0.9, 1.1]$ | $[0.8, 1.5]$ | outside |

---

## III. Rendering Diagnostic Visualizations

### III.1 UV Stretch Heatmap (Vertex Colour)

Encoding stretch energy as vertex colours provides a GPU-renderable diagnostic that can be screenshotted and fed to a vision-language model:

```python
def apply_stretch_heatmap(obj):
    """Paint per-face stretch as vertex colour.
    Red = compressed (s>3), green = isometric (s~1), blue = expanded (s<0.33)."""
    mesh = obj.data
    if "stretch_debug" not in mesh.vertex_colors:
        mesh.vertex_colors.new(name="stretch_debug")
    vc = mesh.vertex_colors["stretch_debug"]

    uv_data = mesh.uv_layers.active.data
    areas_3d = np.array([p.area for p in mesh.polygons])
    areas_uv = []
    for poly in mesh.polygons:
        uvs = [uv_data[li].uv for li in poly.loop_indices]
        a = 0.0
        for k in range(len(uvs)):
            u0, v0 = uvs[k]; u1, v1 = uvs[(k+1) % len(uvs)]
            a += u0*v1 - u1*v0
        areas_uv.append(abs(a)*0.5)
    areas_uv = np.array(areas_uv)
    sum_3d, sum_uv = areas_3d.sum(), areas_uv.sum()
    s = (areas_3d * sum_uv) / (areas_uv * sum_3d + 1e-15)

    for poly_idx, poly in enumerate(mesh.polygons):
        si = float(s[poly_idx])
        if si > 3.0:   colour = (1.0, 0.0, 0.0, 1.0)
        elif si < 0.5: colour = (0.0, 0.0, 1.0, 1.0)
        else:          colour = (0.0, 1.0, 0.0, 1.0)
        for li in poly.loop_indices:
            vc.data[li].color = colour

    mesh.vertex_colors.active = vc
```

### III.2 Checkerboard Diagnostic Render

```python
def apply_checkerboard_diagnostic(obj, checker_size=50):
    """Apply a 2-colour checkerboard texture for visual UV inspection."""
    img_name = "__checker_diag__"
    if img_name in bpy.data.images:
        img = bpy.data.images[img_name]
    else:
        img = bpy.data.images.new(img_name, 512, 512)
        px = []
        for y in range(512):
            for x in range(512):
                cell = (x // checker_size + y // checker_size) % 2
                c = 0.9 if cell else 0.1
                px += [c, c, c, 1.0]
        img.pixels = px

    mat = bpy.data.materials.new("__checker_mat__")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    tex_node = nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    bsdf = nodes.new("ShaderNodeBsdfDiffuse")
    out  = nodes.new("ShaderNodeOutputMaterial")
    links.new(tex_node.outputs["Color"], bsdf.inputs["Color"])
    links.new(bsdf.outputs["BSDF"],      out.inputs["Surface"])

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
```

---

## IV. AI Critic Integration

### IV.1 Diagnostic Packet Schema

```python
def build_diagnostic_packet(obj, mesh_class: str) -> dict:
    metrics = calculate_uv_stretch_metrics(obj)
    failures = []
    if metrics["E_D"] >= 50:
        failures.append({
            "metric": "E_D",
            "value": metrics["E_D"],
            "threshold": 50,
            "hypothesis": "Conical taper or seam spanning a high-curvature region"
        })
    if metrics["high_energy_frac"] >= 0.15:
        failures.append({
            "metric": "high_energy_frac",
            "value": metrics["high_energy_frac"],
            "threshold": 0.15,
            "hypothesis": "UV island too large — seams needed at sharp edges"
        })
    return {
        "object": obj.name,
        "mesh_class": mesh_class,
        "metrics": metrics,
        "pass": len(failures) == 0,
        "failures": failures
    }
```

### IV.2 AI Critic System Prompt

```
ROLE: Computational Geometry QA — UV Parameterization Review

INPUT: A JSON diagnostic packet (stretch energy metrics) + optional PNG checkerboard render.

TASK:
1. Classify each failing metric by root cause:
   - E_D >= 50 on REVOLUTION mesh -> likely conical taper; recommend _mesh_is_conical() check
   - high_energy_frac >= 15% -> likely missing seams at dihedral >=30 degrees
   - mean_stretch outside [0.8, 1.5] -> wrong tile scale; run calibrate_tile_scale()

2. Cite the specific distortion energy formula motivating the classification.
3. Provide a one-line Python fix targeting the specific failure mode.

OUTPUT FORMAT:
{
  "diagnosis": "<root cause>",
  "geometry_principle": "<which distortion type>",
  "fix_code": "<one-liner Python>",
  "expected_E_D_after_fix": "<estimated value>"
}
```

### IV.3 Debugging Loop

```
Pipeline run
    |
    +-- compute_uv_stretch_metrics(obj)
    |
    +-- PASS -----> proceed to displace
    |
    +-- FAIL
         |
         +-- render checkerboard + build_diagnostic_packet()
         |
         +-- send to AI critic
         |
         +-- apply suggested fix
         |
         +-- re-run (max 3 iterations)
```

---

## V. Common Failure Modes and Patches

| Failure signature | Root cause | Fix |
|------------------|------------|-----|
| $E_D > 100$ on REVOLUTION | Conical frustum — cylinder_project degenerates | `_mesh_is_conical(obj)` -> switch to `method='CONFORMAL'` |
| `high_energy_frac > 0.25` on PRISMATIC | Missing seams at flat face boundaries | Reduce `seam_angle_deg` from 60 to 30 |
| $\bar{s} > 3$ everywhere | UV scale not calibrated | Run `calibrate_tile_scale(obj, tile_size_mm)` |
| Isolated red island | Camera island UV chart unscaled | Force equal-area packing in xAtlas |
| $E_C > 0.3$ on smooth organic | ARAP not initialised with LSCM | Run LSCM first, then ARAP refine (10 iterations) |

---

## VI. References

1. Sander, P.V., Snyder, J., Gortler, S.J., & Hoppe, H. (2001). Texture mapping progressive meshes. *ACM SIGGRAPH*, 409-416.
2. Levy, B., Petitjean, S., Ray, N., & Maillot, J. (2002). Least squares conformal maps for automatic texture atlas generation. *ACM SIGGRAPH*, 362-371.
3. Hormann, K., & Greiner, G. (2000). MIPS: an efficient global parameterization method. *Curve and Surface Design*, 153-162.
4. QIDIStudio `apply_texture_bpy.py`: `_calculate_uv_stretch_metrics`, `_do_uv_unwrap`, `_mesh_is_conical`
