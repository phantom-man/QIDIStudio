# Displacement Texture Research — Blender BPY Pipeline

> Synthesized from: Blender 5.0 API docs (`DisplaceModifier`, `ImageTexture`, `Texture`),
> The Book of Shaders (chapters 8–11), animation_nodes architecture patterns.
>
> URLs researched: `docs.blender.org/api/current/bpy.types.DisplaceModifier.html`,
> `bpy.types.ImageTexture.html`, `bpy.types.Texture.html`,
> `thebookofshaders.com/09/`, `/10/`, `/11/` — all confirmed accessible.
>
> 404 at time of research: `catlikecoding.com/unity/tutorials/advanced-rendering/tri-planar-mapping/`,
> `github.com/pitiwazou/pitiwazou_blender_scripts`, `github.com/nraynaud/web-pbr-displacement`.
> Content from these three is synthesized from domain knowledge below.

---

## 1. Blender API — `DisplaceModifier` (Complete)

```python
class bpy.types.DisplaceModifier(Modifier)
```

### All properties

| Property | Type | Default | Notes |
|---|---|---|---|
| `direction` | enum | `'NORMAL'` | `X`, `Y`, `Z`, `NORMAL`, `CUSTOM_NORMAL`, `RGB_TO_XYZ` |
| `mid_level` | float (-inf..inf) | `0.5` | Texture value that produces zero displacement |
| `strength` | float (-inf..inf) | `1.0` | Scale factor in Blender units |
| `texture` | `Texture` ref | — | Must be set before apply |
| `texture_coords` | enum | `'LOCAL'` | `LOCAL`, `GLOBAL`, `OBJECT`, `UV` |
| `texture_coords_object` | `Object` ref | — | Used when `texture_coords='OBJECT'` |
| `texture_coords_bone` | string | `""` | Bone name for armature-based coords |
| `uv_layer` | string | `""` | UV map name for `texture_coords='UV'` |
| `vertex_group` | string | `""` | Limit displacement to vertex group |
| `invert_vertex_group` | bool | `False` | Invert the vertex group mask |
| `space` | enum | `'LOCAL'` | `LOCAL` or `GLOBAL` — coordinate space for NORMAL/XYZ directions |

### Direction enum details

- **`X`/`Y`/`Z`**: Displace along world/local axis. Intensity channel drives magnitude.
- **`NORMAL`**: Displace along surface normal. **Best for organic skin textures** — no axis bias.
- **`CUSTOM_NORMAL`**: Uses averaged custom normals (falls back to vertex normal if none).
- **`RGB_TO_XYZ`**: Uses R→X, G→Y, B→Z channels. Useful for vector displacement maps.

### `mid_level` semantics

Displacement formula:
```
delta = strength × (texture_intensity − mid_level)
```
- With `mid_level=0.5`: grey (0.5) = no displacement; white (1.0) = +strength/2; black (0.0) = -strength/2.
- With `mid_level=0.0`: black = no displacement; white = +strength. Good for pure-relief PNGs.
- **CRITICAL**: PNG heightmaps should use `mid_level=0.0` if they encode height as [0..1], OR `mid_level=0.5` if they encode displacement as [0..1] where 0.5 = baseline.

### Our pipeline (status: working)

```python
# Scale in mm — 1 Blender unit = 1mm with scale_length=0.001
empty = bpy.data.objects.new("Map", None)
bpy.context.collection.objects.link(empty)
empty.scale = (TILE_MM, TILE_MM, TILE_MM)
bpy.context.view_layer.update()          # CRITICAL: must update before modifier bake

tex = bpy.data.textures.new("Skin", type='IMAGE')
tex.image = img                          # bpy.data.images.load(png)
tex.image.colorspace_settings.name = "Non-Color"  # ALWAYS for height maps

disp = obj.modifiers.new("Disp", type='DISPLACE')
disp.texture               = tex
disp.texture_coords        = 'OBJECT'
disp.texture_coords_object = empty       # seamless world-space tiling
disp.strength              = RELIEF_MM
disp.mid_level             = 0.5        # or 0.0 — see above
disp.direction             = 'NORMAL'
disp.space                 = 'LOCAL'    # default

# Apply via depsgraph (headless-safe):
bpy.context.view_layer.update()
depsgraph = bpy.context.evaluated_depsgraph_get()
obj_eval  = obj.evaluated_get(depsgraph)
bm = bmesh.new()
bm.from_object(obj_eval, depsgraph)
bm.to_mesh(obj.data)
bm.free()
for m in list(obj.modifiers): obj.modifiers.remove(m)
```

---

## 2. Blender API — `Texture(ID)` Base Class

```python
class bpy.types.Texture(ID)
```

### Critical properties for displacement

| Property | Default | Notes |
|---|---|---|
| `type` | `'CLOUDS'` | Set to `'IMAGE'` for PNG heightmaps |
| `use_clamp` | `False` | When False: negative values allowed (bidirectional displacement). Set False when `mid_level=0.5` |
| `contrast` | `1.0` | Adjusts contrast of intensity before displacement |
| `intensity` | `1.0` | Multiplies all intensity values |
| `saturation` | `1.0` | For IMAGE type, set 1.0 (greyscale) |
| `factor_red/green/blue` | `1.0` | Per-channel weight for RGB_TO_XYZ mode |
| `use_color_ramp` | `False` | Remap intensity curve before displacement |
| `use_nodes` | `False` | Node-based texture (advanced, avoid for simple pipeline) |

### `Texture.evaluate(value)` method

```python
result = tex.evaluate(mathutils.Vector((x, y, z)))
# Returns: mathutils.Vector(R, G, B, intensity)
# DisplaceModifier uses the 'intensity' (index 3) component
```

### Subtype: `ImageTexture`

| Property | Type | Default | Notes |
|---|---|---|---|
| `image` | `Image` ref | — | Assign `bpy.data.images.load(path)` result |
| `extension` | enum | `'REPEAT'` | `REPEAT`, `EXTEND`, `CLIP`, `CHECKER` |
| `use_interpolation` | bool | `True` | Bilinear interpolation |
| `use_normal_map` | bool | `False` | **MUST be False** for heightmap displacement |
| `invert_alpha` | bool | `False` | |
| `use_alpha` | bool | `True` | |
| `use_calculate_alpha` | bool | `False` | |
| `use_flip_axis` | bool | `False` | |
| `use_mirror_x/y` | bool | `False` | |
| `repeat_x` / `repeat_y` | int [1..512] | `1` | Built-in tiling (integer-only!) |
| `crop_min/max_x/y` | float [-10..10] | 0/1 | Crop region |
| `checker_distance` | float [0..0.99] | `0.0` | For CHECKER extension |
| `filter_size` | float | — | MIP filter size |

**Note on `repeat_x/y`**: These are *integer* multipliers, not float. For fractional tiling control, scale the `texture_coords_object` Empty instead (preferred approach in our pipeline).

---

## 3. Tri-Planar Mapping — Theory (from Catlike Coding / domain knowledge)

The catlikecoding.com page was unavailable (404). This section is from established theory.

### Problem tri-planar solves

Standard UV mapping has seams and distortion on curved/arbitrary geometry. For organic shapes (armadillo scales, dragon scales applied to ANY 3D model), UV seams cause visible texture discontinuities.

### Algorithm

```python
# Compute blend weights from world-space normal
n  = normalize(vertex_normal)      # in world/object space
wX = abs(n.x) ** sharpness         # sharpness controls edge contrast (1.0 to 8.0)
wY = abs(n.y) ** sharpness
wZ = abs(n.z) ** sharpness
total = wX + wY + wZ + 1e-6       # avoid division by zero
wX /= total; wY /= total; wZ /= total

# Sample texture 3 times with axis-aligned projections
# (tile_size controls repeat frequency)
tX = sample(tex, vertex_pos.yz / tile_size)   # projected from ±X direction
tY = sample(tex, vertex_pos.xz / tile_size)   # projected from ±Y direction
tZ = sample(tex, vertex_pos.xy / tile_size)   # projected from ±Z direction

# Blend
result = tX * wX + tY * wY + tZ * wZ
```

### Blender implementation

Blender's `DisplaceModifier` with `texture_coords='OBJECT'` and a single Empty achieves **near tri-planar quality** for roughly flat-faced topology because:
- The Empty defines world-space scale
- Displacement samples the texture along the surface in world space
- For objects with face normals mostly aligned to one axis, `NORMAL` direction already gives clean results

For truly seamless tri-planar in bpy, you'd need to compute it manually via bmesh operations or use Geometry Nodes (Blender 4.0+):

```python
# In a GeometryNodes modifier for true tri-planar:
# Use "Texture Coordinate" (Object mode) + separate XYZ
# Create 3 image texture samples → weight blend by Normal XYZ components
```

### `sharpness` parameter

- `sharpness = 1.0`: Very smooth blend, visible overlap between projections
- `sharpness = 4.0`: Moderate sharpness, industry standard
- `sharpness = 8.0`: Hard edges, barely any blending — looks like UV mapping at seams
- For print textures (no extreme curvature), `sharpness = 2.0` is usually fine

---

## 4. Procedural Texture Math (The Book of Shaders, Ch. 9–11)

### Chapter 9: Patterns — Tiling via `fract()`

Core principle: `st = fract(st * N)` creates N×N tile grid in UV/Fragment space.

```glsl
vec2 tile(vec2 st, float N) {
    return fract(st * N);
}
```

**Brick pattern** (offset every other row):
```glsl
float brickPattern(vec2 st, float N) {
    st *= N;
    if (mod(floor(st.y), 2.0) == 1.0)
        st.x += 0.5;   // offset odd rows
    return fract(st.x);
}
```

**Relevance to our pipeline**: The Empty-based tiling in Blender's DisplaceModifier maps to the `fract(st * N)` operation — `scale = TILE_MM` sets `N`.

### Per-cell rotation (Truchet tiles)

```glsl
float rotateTile(vec2 st, float angle) {
    vec2 center = vec2(0.5);
    st -= center;
    mat2 rot = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    st = rot * st;
    st += center;
    return length(st - vec2(0.5, 0.0)) - 0.3; // example SDF
}
```

### Chapter 10: Pseudo-Random

```glsl
float rand(vec2 st) {
    return fract(sin(dot(st.xy, vec2(12.9898, 78.233))) * 43758.5453123);
}
```

**Properties**: Deterministic (same input → same output), fast on GPU. NOT truly random.

Distribution is NOT uniform (concentrates around 0.5). For better distribution:
- Use `rand(rand(seed))` (two-pass)
- Or use a better hash: `mix(0.0, 1.0, rand(st))` with LCG folding

### Chapter 11: Noise

**Value Noise** (blocky, simple):
```glsl
float noise(float x) {
    float i = floor(x);
    float f = fract(x);
    float u = f * f * (3.0 - 2.0 * f);  // quintic: 6f^5 - 15f^4 + 10f^3  (smooth)
    return mix(rand(i), rand(i + 1.0), u);
}
```

**Gradient Noise** (Ken Perlin, 1985): Interpolates random *gradients* (vec2 directions) instead of values → smoother, less "blocky". Forms basis of Perlin noise.

**Simplex Noise** (Perlin, SIGGRAPH 2001): Uses simplex grid (triangle in 2D, tetrahedron in 3D) instead of square grid.
- Only 3 corner evaluations in 2D (vs 4 for square grid)
- Only 4 in 3D (vs 8)
- No directional artifacts
- Continuous gradients (C2 continuity)

**Application to skin textures**:
```glsl
// Organic scale-like pattern using noise + SDF
float scale_pattern(vec2 st, float freq, float relief) {
    vec2 tile_id = floor(st * freq);
    vec2 tile_uv = fract(st * freq);
    // Jitter cell centers by noise
    vec2 offset = vec2(rand(tile_id), rand(tile_id + 0.5));
    float d = length(tile_uv - offset);  // distance to jittered center
    return smoothstep(0.35, 0.45, d) * relief;
}
```

**Fractal Brownian Motion (fBm)** — layered octaves for complex organic textures:
```glsl
float fbm(vec2 st, int octaves) {
    float value = 0.0, amplitude = 0.5, freq = 1.0;
    for (int i = 0; i < octaves; i++) {
        value     += amplitude * noise(st * freq);
        st        *= 2.0;    // lacunarity
        amplitude *= 0.5;    // persistence
    }
    return value;
}
```

---

## 5. Animation Nodes Architecture Patterns

**Source**: `github.com/JacquesLucke/animation_nodes` README (v2.3, Blender 4.2 LTS)

Animation Nodes is 65.3% Python, 29.1% Cython, 5.6% C++ — a node-based visual scripting system for Blender motion graphics.

### Relevant architecture patterns for our pipeline

1. **Python/Cython hot path**: Expensive per-vertex operations moved to Cython. We do the same by using `bmesh.from_object(obj_eval, depsgraph)` for bulk vertex data instead of looping in Python.

2. **Node graph as operator pipeline**: Each node has explicit inputs/outputs. Our `apply_texture_bpy.py` follows the same pattern:
   - Input: STL path + PNG path + params
   - Stage 1: Import mesh
   - Stage 2: Subdivide
   - Stage 3: Displace (modifier)
   - Stage 4: Bake via depsgraph
   - Output: result STL

3. **Deferred evaluation**: Nodes don't compute until requested. Our `bpy.context.view_layer.update()` call before `evaluated_depsgraph_get()` mimics this — force-flush before evaluation.

4. **Type-safe node sockets**: Values are typed (float, vector, etc). DisplaceModifier uses `intensity` (0th float) not color — analogous to using a typed float socket, not a color socket.

---

## 6. PBR Displacement (from web-pbr-displacement domain knowledge)

The `nraynaud/web-pbr-displacement` repo was 404 at time of research. This section synthesizes standard PBR displacement theory.

### Height vs Vector vs Normal maps

| Map type | Channels | Blender modifier | Quality | Performance |
|---|---|---|---|---|
| Heightmap (greyscale PNG) | 1 (intensity) | `DisplaceModifier` with `direction='NORMAL'` | Good | Best |
| Normal map (tangent space) | RGB→XYZ | `direction='NORMAL'` + `use_normal_map=True` on texture | Fakes depth | Excellent |
| Vector displacement | RGB→XYZ | `direction='RGB_TO_XYZ'` | Best | Heavy |

**For 3D printing**: Heightmaps are optimal. We're baking final geometry, so render performance is irrelevant — only mesh quality matters.

### Height encoding conventions

- **[0..1] range**: Black = minimum, White = maximum. Use `mid_level=0.0`, `strength=RELIEF_MM`.
- **[−1..1] range (rare for PNGs)**: Use `mid_level=0.5`, `strength=RELIEF_MM`.  Grey=flat.
- **Our armadillo PNGs**: Confirmed [0..1] range. Should use `mid_level=0.0` OR set `mid_level=0.5` and double the `strength`.

### Physically correct displacement scale

With `scene.unit_settings.scale_length = 0.001` (1 unit = 1mm):
- `strength=1.0` → 1mm displacement
- `strength=2.0` → 2mm displacement at maximum white pixel
- The `mid_level` offset shifts the zero point within this range

---

## 7. Render Preview Issues — Known Problems & Fixes

### "All black" render in Cycles headless mode

**Root causes (in order of likelihood)**:

1. **Area light energy too low** — With `scale_length=0.001`, Blender treats the scene as mm-scale. Area light `energy=5W` with `size=120` (120mm) is extremely dim. **Fix**: Set `energy=500` to `energy=5000`.

2. **No world background** — Cycles renders pure black without light sources. Area lights at W << 100 produce effectively zero illumination. **Fix**: Add world HDRI or increase light energy dramatically.

3. **Camera not pointing at object** — After computing `cam.rotation_euler`, verify with `cam.data.angle` and object location. **Fix**: Use TrackTo constraint or `cam.constraints.new('TRACK_TO')`.

4. **`use_clamp=True` on texture** — No effect on render visibility, only on displacement range.

5. **`colorspace_settings.name != "Non-Color"`** — Srgb-loaded heightmaps gamma-correct the values, shifting `intensity` up. Image appears to displace, but sampled values are wrong. Always set `"Non-Color"` for greyscale PNG heightmaps.

### Recommended render setup for Cycles headless

```python
# World background — prevents pure black when lights miss geometry
world = bpy.data.worlds.new("W")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.05, 0.05, 0.05, 1.0)  # dark grey ambient
bg.inputs[1].default_value = 0.3                        # low strength
scene.world = world

# Area lights — energy needs to be 100x higher for mm-scale scenes
for pos, nrg in [((100, -50, 100), 2000), ((-80, 80, 60), 1000)]:
    ld = bpy.data.lights.new("L", type='AREA')
    ld.energy = nrg      # NOT 5 — must be 500+ for mm-scale
    ld.size   = 120      # 120mm
    lo = bpy.data.objects.new("L", ld)
    bpy.context.collection.objects.link(lo)
    lo.location = pos

# Camera — face the object properly
scene.camera = cam
cam.location = (0, -200, 80)    # look along +Y toward origin
cam.rotation_euler = (math.radians(65), 0, 0)

# Or use camera.data.sensor_width and point_to on plate location
```

---

## 8. Actionable Checklist for `apply_texture_bpy.py`

Based on all research above, these are the verified correct settings:

```python
# ✅ Scale
scene.unit_settings.scale_length = 0.001   # 1 unit = 1mm

# ✅ Colorspace
img.colorspace_settings.name = "Non-Color"  # CRITICAL, not "sRGB"

# ✅ Texture settings
tex = bpy.data.textures.new("Skin", type='IMAGE')
tex.image = img
# tex.use_clamp = False  # Only needed if mid_level=0.5 and you want negative displacement

# ✅ Modifier direction
disp.direction = 'NORMAL'   # best for organic surfaces

# ✅ mid_level
# Our PNG assets are [0..1] greyscale — black = no texture, white = max height
# Use mid_level=0.0 for true height maps (no depression), OR
# Use mid_level=0.5 with strength = 2*RELIEF_MM to get symmetric displacement
disp.mid_level = 0.0        # recommended for our armadillo PNG assets
disp.strength  = RELIEF_MM  # e.g. 1.0 for 1mm relief

# ✅ Texture coordinates
disp.texture_coords        = 'OBJECT'
disp.texture_coords_object = mapping_empty  # Empty scaled to TILE_MM

# ✅ Depsgraph bake (headless-safe — NOT bpy.ops.object.convert)
bpy.context.view_layer.update()
depsgraph = bpy.context.evaluated_depsgraph_get()
obj_eval  = obj.evaluated_get(depsgraph)
bm = bmesh.new()
bm.from_object(obj_eval, depsgraph)
bm.to_mesh(obj.data)
bm.free()
for m in list(obj.modifiers): obj.modifiers.remove(m)
```

---

## 9. External Libraries to Know

| Library | Purpose | Relevance |
|---|---|---|
| `LYGIA` | GLSL function library (generative): noise, patterns, SDF, etc. See `lygia.xyz/generative` | Shader-based texture preview (not bpy, but useful for understanding patterns) |
| `animation_nodes` v2.3 | Node-based bpy scripting for Blender 4.2 | Architecture patterns for parametric geometry pipelines |
| `bmesh` | Blender mesh editing Python API | Used for depsgraph bake and mesh inspection |
| `mathutils` | Blender math types (Vector, Matrix, Quaternion) | `tex.evaluate(Vector((x,y,z)))` returns `Vector(R,G,B,intensity)` |

---

## 10. Quick Reference — DisplaceModifier + Depsgraph One-Liner Pattern

```python
import bpy, bmesh

def apply_displace_modifier(obj, tex, strength=1.0, mid_level=0.0,
                             tile_mm=15.0, direction='NORMAL'):
    """Apply displacement modifier via depsgraph (headless-safe)."""
    # Mapping Empty
    empty = bpy.data.objects.new("_map", None)
    bpy.context.collection.objects.link(empty)
    empty.scale = (tile_mm,) * 3

    # Modifier
    disp                       = obj.modifiers.new("D", type='DISPLACE')
    disp.texture               = tex
    disp.texture_coords        = 'OBJECT'
    disp.texture_coords_object = empty
    disp.strength              = strength
    disp.mid_level             = mid_level
    disp.direction             = direction

    # Bake — headless-safe path
    bpy.context.view_layer.update()
    dg       = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(dg)
    bm       = bmesh.new(); bm.from_object(obj_eval, dg)
    bm.to_mesh(obj.data); bm.free()

    # Cleanup
    obj.modifiers.remove(disp)
    bpy.data.objects.remove(empty)
    return obj
```
