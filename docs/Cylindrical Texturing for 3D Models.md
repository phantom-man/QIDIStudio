# Cylindrical Texturing for 3D Models

UV parameterization for cylindrical and revolution-surface geometries requires a principled selection between conformal, isometric, and projection-based mapping strategies. This document establishes the mathematical foundation, implementation patterns, and tile-density calibration methods for cylinder projection in the QIDIStudio texture pipeline.

---

## I. Mathematical Foundation: Cylinder Parameterization

A cylinder $C$ centred on the Z-axis with radius $R$ and height $H$ admits an analytic isometric parameterization:

$$\phi: C \to [0, 2\pi) \times [0, H], \quad \phi(x, y, z) = \left(\operatorname{atan2}(y, x),\; z\right)$$

Converting to normalized UV coordinates:

$$U = \frac{\theta}{2\pi}, \qquad V = \frac{z - z_\text{min}}{z_\text{max} - z_\text{min}}$$

This parameterization is **isometric**: it preserves both angles and areas. A length element $ds$ on the cylinder surface maps to an equal length element in UV-space.  The only distortion point is the single seam line at $\theta = 0$ (or $\theta = \pi$ for POLAR_ZX placement).

**Critical distinction from spherical / planar projections:**  
Sphere and planar projections accumulate stretch proportional to the deviation from planarity. Cylinder projection is exact for pure cylinders but degenerates on conical/frustum bodies — see §IV.

---

## II. Seam Placement Theory

A seam is a set of edges where the UV atlas is cut — equivalent to mathematically identifying these edges as boundary edges of the parameterization domain. For a cylinder, the minimal seam is a single vertical line (one edge loop).

**Seam energy** (Sheffer & Hart, 2002) quantifies the visual impact of a seam: edges on the back face ($\theta \approx \pi$ from viewing direction) have minimum visual impact. Blender's `uv.cylinder_project(align="POLAR_ZX")` places the seam at the ZX plane ($y = 0, x > 0$ half-plane), effectively placing it at the back of a standard front-view orientation.

The seam produces UV-coordinate discontinuity at edges adjacent to the seam edge. The **seam-adjacent high-energy fraction** $f_\text{seam}$ quantifies what fraction of the mesh faces border the seam:

$$f_\text{seam} = \frac{|\{f_i : \partial f_i \cap \text{seam} \neq \emptyset\}|}{|F|}$$

For a cylinder with $n$ longitudinal divisions: $f_\text{seam} = 2/n$. At $n=32$: $f_\text{seam} = 6.25\%$, well below the 15% quality threshold.

---

## III. Tile Density Calibration

For physically correct texture tiling — where one tile period corresponds to a fixed world-space distance $d_\text{tile}$ (in mm) — the UV scale factors must be set from the actual surface geometry.

**Cylinder UV scale calibration:**

$$s_u = \frac{2\pi R}{d_\text{tile}}, \qquad s_v = \frac{H}{d_\text{tile}}$$

where $R$ is the mean radius and $H$ is the height of the cylindrical section. Blender's raw cylinder_project output maps the full circumference to $U \in [0, 1]$ and the full height to $V \in [0, 1]$. Scaling by $s_u, s_v$ converts to tile-repeat space.

**Scale-invariance of UV stretch metrics:** The normalized stretch energy $s_i$ for face $i$:

$$s_i = \frac{a_{3,i} \cdot \sum_j a_{u,j}}{\;a_{u,i} \cdot \sum_j a_{3,j}}$$

is **scale-invariant** with respect to uniform $(s_u, s_v)$ scaling: applying $(s_u, s_v)$ multiplies $a_{u,i} \to s_u s_v \cdot a_{u,i}$ and $\sum_j a_{u,j} \to s_u s_v \cdot \sum_j a_{u,j}$, which cancel. High $E_D$ values on cylinder-projected parts indicate geometric (not scale-derived) UV degeneracy.

---

## IV. Conical Sections — Degeneracy and Fallback

For a **conical frustum** with top radius $R_1$ and bottom radius $R_2$ ($R_1 \neq R_2$), cylinder projection does NOT produce an isometric map. The intermediate-$z$ faces map to UV triangles with a compressed $U$-range at the narrow end and an expanded $U$-range at the wide end — the UV triangle area $a_{u,i} \approx 0$ for faces at the midpoint when $|R_1 - R_2|/\max(R_1, R_2) > 0.2$.

This causes $s_i \to \infty$ for those faces, driving the aggregate $E_D$ metric to pathological values (observed: $E_D = 230$ for `vacuum_nozzle_lower`).

**Detection and fallback** (implemented in QIDIStudio pipeline):

```python
def _mesh_is_conical(obj, taper_threshold: float = 0.20) -> bool:
    """True if the REVOLUTION mesh has >20% radius variation from bottom to top."""
    vertices = obj.data.vertices
    z_coords = [v.co.z for v in vertices]
    z_min, z_max = min(z_coords), max(z_coords)
    z_mid = (z_min + z_max) / 2.0

    def half_radius(z_lo, z_hi):
        pts = [v.co for v in vertices if z_lo <= v.co.z <= z_hi]
        xs = [p.x for p in pts]; ys = [p.y for p in pts]
        cx = (max(xs)+min(xs))/2; cy = (max(ys)+min(ys))/2
        return max(((p.x-cx)**2+(p.y-cy)**2)**0.5 for p in pts)

    r_bot = half_radius(z_min, z_mid)
    r_top = half_radius(z_mid, z_max)
    return (abs(r_bot - r_top) / max(r_bot, r_top)) > taper_threshold

# In _apply_displacement_blender — REVOLUTION case:
projection = "cylinder"
if _mesh_is_conical(obj):
    projection = "lscm"
    log.log("UV: conical taper detected — falling back to LSCM")
```

When the fallback to LSCM is triggered, the stretch metric drops from $E_D \sim 230$ to $E_D < 50$ because LSCM minimizes the conformal energy $E_C = \int |\nabla u - \mathbf{N} \times \nabla v|^2\, dA$ across the entire surface simultaneously, avoiding the per-column degeneracy of cylinder_project.

---

## V. Blender Cylinder Projection API

Blender's `bpy.ops.uv.cylinder_project` parameters for production CAD usage:

```python
bpy.ops.uv.cylinder_project(
    direction="ALIGN_TO_OBJECT",  # align cylinder axis with object local-Z
    align="POLAR_ZX",              # seam at ZX plane (back face)
    radius=0,                      # 0 = auto-calculate from geometry bounds
    correct_aspect=True,           # preserve aspect ratio in UV-space
)
```

**Key parameter rationale:**
- `direction="ALIGN_TO_OBJECT"`: wraps around the object's local Z-axis, regardless of world orientation. Essential for parts imported in arbitrary orientations.
- `align="POLAR_ZX"`: places the seam at the back ( $x < 0$ halfplane). The default `POLAR_XY` places the seam at the bottom edge, which is aesthetically worse for tall cylindrical parts.
- `radius=0`: Let Blender fit the projection radius to the actual geometry. Specifying a radius smaller than the part causes latitude-like compression.

Post-projection, endcap faces (faces with $|\hat{n} \cdot \hat{z}| > 0.8$) are excluded from UV stretch evaluation:

```python
# In _calculate_uv_stretch_metrics — endcap exclusion
if exclude_axial_frac > 0 and abs(face_normal_z) > exclude_axial_frac:
    continue  # skip endcap — cylinder_project always distorts these
```

---

## VI. Tile Size Empirical Calibration

Rather than computing $s_u, s_v$ analytically (which requires knowing $R$ and $H$ exactly), the pipeline calibrates from actual UV loop statistics:

```python
# Sample up to N=2000 loop edges; compute 3D/UV edge length ratio
uv_layer = mesh.uv_layers.active.data
samples = []
for poly in mesh.polygons:
    for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
        li_next = poly.loop_start + (li - poly.loop_start + 1) % poly.loop_total
        v0 = mesh.vertices[mesh.loops[li].vertex_index].co
        v1 = mesh.vertices[mesh.loops[li_next].vertex_index].co
        uv0 = uv_layer[li].uv
        uv1 = uv_layer[li_next].uv
        len_3d = (v1 - v0).length
        len_uv = (uv1 - uv0).length
        if len_uv > 1e-8:
            samples.append(len_3d / len_uv)
        if len(samples) >= 2000:
            break

ratio = np.median(samples)  # mm per UV unit
# Then scale all UV coords by ratio / tile_size_mm
```

The median ratio is more robust than mean against seam-adjacent outliers (seam edges have `len_uv ≈ 0` but `len_3d > 0`).

---

## VII. Quality Metrics

After UV unwrap, the pipeline evaluates:

| Metric | Formula | Threshold (cylinder) |
|--------|---------|----------------------|
| Stretch energy $E_D$ | $\sum_i \max(s_i - 1, 0)^2 \cdot a_{3,i}$ | $< 50$ |
| High-energy fraction | $|\{i : s_i > 3\}| / |F|$ | $< 15\%$ |
| Mean stretch $\bar{s}$ | $\sum_i s_i \cdot a_{3,i} / \sum_i a_{3,i}$ | $\in [0.8, 1.5]$ |
| Seam-adjacent fraction | $f_\text{seam}$ | $< 20\%$ |

Cylinder projection on pure cylinders typically achieves $E_D < 10$, $\bar{s} \approx 1.0$, and $f_\text{seam} = 2/n_\text{divisions}$. Values outside these bounds indicate either a conical taper (use LSCM fallback) or a non-cylindrical REVOLUTION classification error.

---

## VIII. References

1. Lévy, B., Petitjean, S., Ray, N., & Maillot, J. (2002). Least squares conformal maps for automatic texture atlas generation. *ACM SIGGRAPH 2002*, 362–371. [LSCM theory]
2. Sheffer, A., & Hart, J. C. (2002). Seamster: inconspicuous low-distortion texture seam layout. *IEEE Visualization 2002.* [Seam placement optimization]
3. Nothings. xAtlas. https://github.com/jpcy/xatlas [Production UV atlas]
4. Blender Documentation. UV Unwrapping – Cylinder Projection. https://docs.blender.org/manual/en/latest/editors/uv/
5. QIDIStudio apply_texture_bpy.py — `_do_uv_unwrap`, `_mesh_is_conical`, `_calculate_uv_stretch_metrics`
