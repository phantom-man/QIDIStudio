#!/usr/bin/env python3
"""
apply_texture_bpy.py  —  Blender/bpy displacement texture generator.

Generates a texture-displaced mesh that QIDIStudio loads as a new volume:
  --mode part     → displacement shell added as MODEL_PART  (raised scales)
  --mode negative → displacement shell added as NEGATIVE_VOLUME (carved in)
  --mode modifier → original mesh replaced with displaced version

Invocation by QIDIStudio:
  <bpy_env>/Scripts/python.exe apply_texture_bpy.py
      <model_stl>  <skin_asset>
      [--mode modifier]
      [--tile-size 15]  [--relief 1.0]
      [--invert]  [--gamma 0.7]
      [--log <logfile>]

Output:
  Writes  SKIN_OUTPUT: <path>  to stdout (and log file).
  QIDIStudio parses that line to find the result STL.
"""

import sys
import os
import argparse
import pathlib
import tempfile
import traceback
import zipfile
import xml.etree.ElementTree as ET

# ── bpy import ────────────────────────────────────────────────────────────
try:
    import bpy
except ImportError:
    print("ERROR: bpy not available. Run with bpy_env Python interpreter.", flush=True)
    sys.exit(1)


def _detect_full_blender() -> bool:
    """True when running under a full blender.exe installation (not the bpy pip package).

    Full Blender has a proper GL/viewport context so:
      - bpy.ops.object.convert(target='MESH') reliably applies modifiers
      - The Displace modifier evaluates correctly via the depsgraph
      - No vertex splitting occurs (unlike bmesh.from_object with UV seams)

    The bpy pip package lacks these guarantees even in background mode.
    """
    try:
        bp = bpy.app.binary_path
        if bp and os.path.basename(bp).lower().startswith("blender"):
            return True
    except Exception:
        pass
    # Fallback: blender sets sys.argv[0] to the launcher path
    if sys.argv and os.path.basename(sys.argv[0]).lower().startswith("blender"):
        return True
    return False


IS_FULL_BLENDER: bool = _detect_full_blender()

if not IS_FULL_BLENDER:
    print("ERROR: apply_texture_bpy.py must be run via blender.exe --background --python.", flush=True)
    print("ERROR: The bpy pip package does not support the Displace modifier pipeline.", flush=True)
    print("ERROR: Install Blender from https://www.blender.org/download/ (version >= 4.0)", flush=True)
    sys.exit(1)


# ── argument parsing ──────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate bpy-displaced texture mesh for QIDIStudio"
    )
    p.add_argument("model_path",
                   help="Source STL/3MF to texture")
    p.add_argument("skin_path",
                   help="Skin asset: PNG/JPG for displacement texture")
    p.add_argument("--mode",
                   choices=["part", "negative", "modifier"],
                   default="modifier",
                   help="part=add raised shell, negative=add carved shell, modifier=replace mesh")
    p.add_argument("--tile-size", type=float, default=15.0,
                   help="Texture repeat size in mm (default 15)")
    p.add_argument("--relief",   type=float, default=1.0,
                   help="Displacement amplitude in mm (default 1.0)")
    p.add_argument("--invert",   action="store_true",
                   help="Invert the displacement direction")
    p.add_argument("--gamma",    type=float, default=0.7,
                   help="Gamma applied to the skin image before displacement (default 0.7)")
    p.add_argument("--log",      default="",
                   help="Path for the log file (optional)")
    p.add_argument("--projection",
                   choices=["auto", "conformal", "lscm", "object"],
                   default="auto",
                   help=("UV projection for texture wrapping: "
                         "auto=detect from geometry (default — LSCM for organic, OBJECT for angular CAD), "
                         "lscm=force LSCM conformal UV (angle-preserving, best for smooth curved surfaces), "
                         "object=force world-space box-map (no seams, best for flat/angular CAD parts), "
                         "conformal=Smart-UV-Project (arbitrary island cuts, can spike on CAD parts)"))
    p.add_argument("--full-surface",
                   dest="full_surface",
                   action="store_true",
                   default=True,
                   help="Displace the ENTIRE surface — skin-wrap mode (default ON)")
    p.add_argument("--no-full-surface",
                   dest="full_surface",
                   action="store_false",
                   help="Restrict displacement to top-facing faces only (legacy behaviour for flat CAD parts)")
    # bpy injects its own args after '--'; strip them
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    return p.parse_args(argv)


# ── logger ────────────────────────────────────────────────────────────────
class Logger:
    def __init__(self, path: str):
        self._path = path
        self._buf: list[str] = []

    def log(self, msg: str):
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            # Windows cp1252 terminal can't handle non-Latin chars; ASCII-safe fallback
            print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
        self._buf.append(msg)

    def emit_skin_output(self, out_path: str):
        line = f"SKIN_OUTPUT: {out_path}"
        self.log(line)

    def flush(self):
        if self._path:
            try:
                pathlib.Path(self._path).write_text("\n".join(self._buf), encoding="utf-8")
            except Exception:
                pass


# ── scene helpers ─────────────────────────────────────────────────────────
def _reset_scene():
    """Start with an empty Blender scene in headless mode."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    # Set millimetre units (1 Blender unit = 0.001 m = 1 mm)
    scene.unit_settings.system      = "METRIC"
    scene.unit_settings.scale_length = 0.001


def _import_model(path: str, log: Logger) -> list:
    """Import model file, return list of newly added MESH objects."""
    before = {o.name for o in bpy.data.objects}
    ext = pathlib.Path(path).suffix.lower()

    if ext == ".stl":
        try:
            bpy.ops.wm.stl_import(filepath=path)          # Blender 4+ / bpy 5
        except AttributeError:
            bpy.ops.import_mesh.stl(filepath=path)         # Blender 3.x fallback
    elif ext == ".3mf":
        # Standalone bpy does not bundle io_scene_3mf; parse the zip directly.
        meshes_created = _import_3mf_manual(path, log)
        log.log(f"Imported {len(meshes_created)} mesh(es) from '{pathlib.Path(path).name}'")
        return meshes_created
    elif ext in (".obj", ".OBJ"):
        try:
            bpy.ops.wm.obj_import(filepath=path)          # Blender 4+
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=path)       # Blender 3
    else:
        # Fallback: hope the file is STL-compatible
        bpy.ops.import_mesh.stl(filepath=path)

    after = {o.name for o in bpy.data.objects}
    meshes = [
        bpy.data.objects[n]
        for n in (after - before)
        if bpy.data.objects[n].type == "MESH"
    ]
    log.log(f"Imported {len(meshes)} mesh(es) from '{pathlib.Path(path).name}'")
    return meshes


def _import_3mf_manual(path: str, log: Logger) -> list:
    """
    Parse a 3MF zip, extract all <mesh> vertex/triangle data, and build
    native bpy Mesh objects — no add-on required.
    """
    NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    created = []

    with zipfile.ZipFile(path, "r") as zf:
        model_files = [n for n in zf.namelist()
                       if n.lower().endswith(".model")]
        if not model_files:
            log.log("  WARNING: no .model files found in 3MF zip")
            return created

        obj_index = 0
        for mf in model_files:
            try:
                xml_bytes = zf.read(mf)
            except Exception as e:
                log.log(f"  WARNING: cannot read {mf}: {e}")
                continue

            try:
                root = ET.fromstring(xml_bytes)
            except ET.ParseError as e:
                log.log(f"  WARNING: XML parse error in {mf}: {e}")
                continue

            for mesh_el in root.iter(f"{{{NS}}}mesh"):
                verts_el = mesh_el.find(f"{{{NS}}}vertices")
                tris_el  = mesh_el.find(f"{{{NS}}}triangles")
                if verts_el is None or tris_el is None:
                    continue

                verts = []
                for v in verts_el.findall(f"{{{NS}}}vertex"):
                    try:
                        verts.append((
                            float(v.get("x", 0)),
                            float(v.get("y", 0)),
                            float(v.get("z", 0)),
                        ))
                    except (ValueError, TypeError):
                        continue

                faces = []
                for t in tris_el.findall(f"{{{NS}}}triangle"):
                    try:
                        faces.append((
                            int(t.get("v1")),
                            int(t.get("v2")),
                            int(t.get("v3")),
                        ))
                    except (ValueError, TypeError):
                        continue

                if not verts or not faces:
                    continue

                name = f"3mf_object_{obj_index}"
                obj_index += 1

                mesh_data = bpy.data.meshes.new(name)
                mesh_data.from_pydata(verts, [], faces)
                mesh_data.update()

                obj = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(obj)
                created.append(obj)
                log.log(f"  Mesh '{name}': {len(verts)} verts, {len(faces)} faces")

    return created


def _ops_ctx(obj):
    """temp_override context for single-object bpy.ops calls in background mode."""
    return bpy.context.temp_override(
        active_object=obj,
        object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    )


def _smart_uv_project(obj, log: Logger):
    """UV-unwrap with Smart UV Project (angle-based islands, no seam waste)."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    with _ops_ctx(obj):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
        bpy.ops.object.mode_set(mode="OBJECT")
    log.log(f"  UV unwrap complete on '{obj.name}'")


def _gamma_correct_image(img, gamma: float, log: Logger) -> None:
    """Apply gamma correction to a Blender Image.

    Uses numpy vectorisation (bundled with standalone bpy) — ~1000× faster
    than the per-channel Python loop on real textures.  Falls back to the
    slow path if numpy is somehow absent.
    """
    if abs(gamma - 1.0) < 0.01:
        return
    g_inv = 1.0 / gamma
    try:
        import numpy as np
        px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
        px[:, :3] = np.power(np.clip(px[:, :3], 0.0, None), g_inv)
        img.pixels[:] = px.ravel().tolist()
    except ImportError:
        # numpy absent — pure-Python fallback (slow on large textures)
        px = list(img.pixels[:])
        for i in range(0, len(px), 4):
            px[i]   = max(0.0, px[i]  ) ** g_inv
            px[i+1] = max(0.0, px[i+1]) ** g_inv
            px[i+2] = max(0.0, px[i+2]) ** g_inv
        img.pixels[:] = px
    img.update()
    log.log(f"  Gamma correction applied (g={gamma})")


def _compute_shape_dna(obj, k: int = 10, log: "Logger | None" = None):
    """
    Compute the Shape DNA of a mesh: the first k eigenvalues of the
    combinatorial graph Laplacian (degree matrix − adjacency matrix).

    These eigenvalues are isometry-invariant — they encode the global
    shape topology as a compact fingerprint.  Two geometrically identical
    meshes have the same DNA regardless of position or rotation.

    References:
      Reuter 2006 'Shape DNA: Spectral Geometry for Shape Recognition'
      PhD Manuscript Sec. IV — get_shape_dna()

    NOTE: Uses the combinatorial Laplacian (fast, O(E) edges) rather than
    the cotangent-weighted Laplacian (requires edge angle data).  Sufficient
    for logging/diagnostics.  For production metrology use robust_laplacian
    on the exported STL (see KB § 15.2).

    Skips the computation if the mesh has more than 5 000 vertices to avoid
    O(V²) memory allocation on subdivided meshes.
    """
    try:
        import numpy as np
    except ImportError:
        if log:
            log.log("  Shape DNA: numpy unavailable, skipping")
        return None

    mesh = obj.data
    n = len(mesh.vertices)
    if n > 5000:
        if log:
            log.log(f"  Shape DNA: mesh has {n} verts — too large for in-process DNA, skipping")
        return None

    adj = np.zeros((n, n), dtype=np.float32)
    for edge in mesh.edges:
        u, v = edge.vertices[0], edge.vertices[1]
        adj[u, v] = adj[v, u] = 1.0
    deg = np.diag(adj.sum(axis=1))
    L = deg - adj
    evals = np.linalg.eigvalsh(L)   # sorted ascending
    dna = evals[:k]
    if log:
        dna_str = ",".join(f"{x:.4f}" for x in dna)
        log.log(f"  Shape DNA (k={k}): [{dna_str}]")
    return dna


def _adaptive_subd_level(obj) -> int:
    """
    Choose a subdivision level so the result stays under ~400K triangles.
    Each Simple-Subd level multiplies tri count by 4.

    Formula: level = floor(log4(TARGET / n)), clamped [0, 4].
    This means:
      - High-poly meshes (organic scans, detailed dragons) → level 0 or 1
        (already dense enough for smooth displacement; no need to explode to 6M)
      - Typical CAD STL imports (coarse triangulation) → level 2-3
        (needs subdivision to avoid diagonal-streak artifacts from long thin tris)
    """
    import math
    TARGET = 400_000   # max output triangles
    n = len(obj.data.polygons)
    if n == 0:
        return 0
    raw   = math.log(TARGET / n, 4)
    level = max(0, min(4, int(raw)))
    return level


def _auto_projection(obj, log: Logger) -> tuple:
    """
    Analyse the mesh and choose the LSCM seam angle.

    LSCM (Blender CONFORMAL) is always the correct projection for manifold
    meshes — both organic shapes AND CAD/prismatic/vacuum parts.  The key
    variable is the seam-placement threshold:

      Organic (smooth surfaces, curved shells):  seams at >= 60° edges only.
        Few seams → UV islands match large smooth regions → no ridges.

      CAD / prismatic / revolution parts:  seams at >= 30° edges.
        30° catches every planar-panel boundary (port transitions, gasket
        seats, boss shoulders, filleted corners).  Each geometric panel
        becomes its own UV island with zero distortion on its flat faces.
        Seams fall exactly on design-edge boundaries — not across smooth
        regions — so there are no displacement discontinuities on faces.

    Source: Advanced Texture Wrapping for CAD (PhD manuscript, §II.1).
    Reference: `bpy.ops.mesh.edges_select_sharp(sharpness=0.523599)` — 30°.

    Returns (projection, seam_angle_rad).
    """
    import bmesh, math

    # Measure with the tighter (30°) threshold to classify the mesh type.
    MEASURE_RAD = 0.5236   # 30° — the CAD seam threshold
    ORGANIC_RAD = 1.0472   # 60° — the organic seam threshold
    CAD_THRESH  = 0.35     # >35% of edges ≥ 30° → prismatic/CAD geometry
    # 0.35 calibration:
    #   Organic creature parts with joint stubs (claw feet, limbs): ~25% → organic ✓
    #   Dragon body:                                                  ~4%  → organic ✓
    #   Mechanical/box parts (flat panels):                          ~70%+ → CAD    ✓
    #   0.15 was too low — creature joint transitions pushed organic
    #   parts into CAD mode, causing starburst seam fans at junctions.

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()

    total = 0
    sharp30 = 0
    for e in bm.edges:
        linked = e.link_faces
        total += 1
        if len(linked) != 2:
            sharp30 += 1
            continue
        dot   = max(-1.0, min(1.0, linked[0].normal.dot(linked[1].normal)))
        angle = math.acos(dot)
        if angle >= MEASURE_RAD:
            sharp30 += 1

    bm.free()

    fraction   = sharp30 / total if total > 0 else 0.0
    is_cad     = fraction >= CAD_THRESH
    seam_angle = MEASURE_RAD if is_cad else ORGANIC_RAD
    geometry   = 'CAD/prismatic' if is_cad else 'organic/smooth'
    log.log(f"  Auto-projection: {sharp30}/{total} edges >=30° "
            f"({fraction:.1%}) → {geometry} → seam_angle={math.degrees(seam_angle):.0f}°")
    return ('lscm', seam_angle)


def _do_uv_unwrap(obj, tile_size: float, projection: str, log: Logger,
                  seam_angle_rad: float = 1.0472):
    """
    UV-unwrap the mesh and scale coordinates so 1 UV unit = tile_size mm
    of actual surface distance.

    projection:
      'lscm'      — Blender CONFORMAL (LSCM): Least-Squares Conformal Maps.
                    Minimises E_LSCM = ∫|∇u − N×∇v|² dA — angle-preserving.
                    Seams placed at edges whose dihedral angle >= seam_angle_rad:
                      30° (0.523 rad) for prismatic/CAD parts — every panel face
                        gets its own perfectly-mapped island (PhD: §II.1)
                      60° (1.047 rad) for smooth organic surfaces — fewer seams,
                        continuous UV across curved regions.
      'conformal' — Blender Smart UV Project (fallback): per-island seam
                    detection. Robust on any topology but can spike on CAD.

    seam_angle_rad: dihedral angle threshold for seam placement (default 60°).
      Pass 0.523599 (30°) for prismatic/CAD geometry.

    After this call the active UV layer has coordinates whose repeat period is
    tile_size mm, calibrated from the average 3-D vs UV edge-length ratio across
    up to 2 000 sampled loop edges.
    """
    import mathutils

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)

    with _ops_ctx(obj):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

        if projection == 'lscm':
            # PhD pipeline (Advanced Texture Wrapping for CAD, §II.1):
            # Place seams at design-edge boundaries using the dihedral threshold
            # chosen by _auto_projection:
            #   30° (CAD/prismatic): every planar panel → own island, zero
            #       distortion per-face, seams only at geometric transitions
            #       (port shoulders, boss rims, gasket seats, fillet roots).
            #   60° (organic/smooth): seams only at hard corners — continuous
            #       UV wraps around curved walls like painted skin.
            #
            # Step 1: clear ALL existing seams (stale from import/prior run).
            import math as _math
            seam_deg = _math.degrees(seam_angle_rad)
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.mark_seam(clear=True)
            # Step 2: select edges whose dihedral >= seam_angle_rad, mark as seams.
            bpy.ops.mesh.edges_select_sharp(sharpness=seam_angle_rad)
            bpy.ops.mesh.mark_seam(clear=False)
            bpy.ops.mesh.select_all(action='SELECT')
            try:
                bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.001)
                log.log(f"  UV: LSCM (CONFORMAL) unwrap — seams at >={seam_deg:.0f}° edges")
            except Exception as uv_err:
                log.log(f"  UV: LSCM failed ({uv_err}) — falling back to smart_project")
                bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
        else:  # 'conformal' — Smart UV Project
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
            log.log("  UV: Smart UV Project unwrap completed")

        bpy.ops.object.mode_set(mode='OBJECT')

    # ── Scale UV so 1 UV unit = tile_size mm ─────────────────────────────
    # Estimate mm-per-UV-unit by comparing 3-D edge lengths to UV edge lengths
    # across a random sample of loop edges.  This gives a geodesic calibration
    # that is accurate regardless of mesh scale or UV island packing.
    mesh    = obj.data
    uv_lyr  = mesh.uv_layers.active
    if uv_lyr is None:
        log.log("  UV: WARNING — no UV layer after unwrap; tiling may be incorrect")
        return

    verts   = mesh.vertices
    loops_  = mesh.loops
    uv_data = uv_lyr.data
    total_3d = 0.0
    total_uv = 0.0
    n_samp   = 0

    for poly in mesh.polygons:
        nv = len(poly.loop_indices)
        for k in range(nv):
            l0  = poly.loop_indices[k]
            l1  = poly.loop_indices[(k + 1) % nv]
            v0  = verts[loops_[l0].vertex_index].co
            v1  = verts[loops_[l1].vertex_index].co
            u0  = uv_data[l0].uv
            u1  = uv_data[l1].uv
            d3  = (v1 - v0).length
            du  = ((u1[0] - u0[0]) ** 2 + (u1[1] - u0[1]) ** 2) ** 0.5
            if du > 1e-10 and d3 > 1e-10:
                total_3d += d3
                total_uv  += du
                n_samp    += 1
                if n_samp >= 2000:
                    break
        if n_samp >= 2000:
            break

    if total_uv > 1e-10:
        mm_per_uv = total_3d / total_uv   # current: 1 UV unit = this many mm
        uv_scale  = mm_per_uv / tile_size  # target:  1 UV unit = tile_size mm
    else:
        # Rare fallback — no usable edge pairs (degenerate UV); use bbox
        import mathutils as mu
        bb   = [mu.Vector(c) for c in obj.bound_box]
        max_mm = max(
            max(v.x for v in bb) - min(v.x for v in bb),
            max(v.y for v in bb) - min(v.y for v in bb),
            max(v.z for v in bb) - min(v.z for v in bb),
        )
        uv_scale  = max_mm / tile_size
        mm_per_uv = uv_scale * tile_size
        log.log(f"  UV scale: bbox fallback (max_mm={max_mm:.1f})")

    for loop_item in uv_lyr.data:
        loop_item.uv = (loop_item.uv[0] * uv_scale, loop_item.uv[1] * uv_scale)

    log.log(f"  UV scale: {uv_scale:.3f}x  "
            f"(~{mm_per_uv:.2f} mm/UV_unit → tile_size={tile_size}mm, "
            f"sampled {n_samp} edges)")


def _apply_displacement_blender(obj, skin_path: str, tile_size: float,
                                relief: float, invert: bool, gamma: float,
                                log: Logger, *, mode: str = "modifier",
                                projection: str = "object",
                                full_surface: bool = True):
    """
    Full-Blender displacement pipeline — Displace modifier + Simple subdivision.

    projection = 'conformal' (default) | 'lscm' | 'object'
      conformal / lscm:  UV-based displacement — texture follows the surface
                         geodesically.  The pattern wraps continuously around
                         ALL faces, including vertical walls and the underside,
                         just like paint on a physical object (skin-wrap mode).
      object:            World-space OBJECT-coordinate box-map (legacy).
                         Simple, no UV needed, but stretches on curved faces.

    full_surface = True (default):  displace the ENTIRE surface.
    full_surface = False:           restrict to top-facing faces only (legacy CAD
                                    mode — sharp walls, textured top only).
    """
    import bmesh

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # ── 0. Weld duplicate verts (STL: one copy per triangle) ─────────────
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before_w = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    log.log(f"  Welded: {before_w}→{len(obj.data.vertices)} verts")

    # ── 1. UV unwrap — BEFORE subdivision (clean low-poly topology) ───────
    # UV coordinates survive Simple subdivision: Blender interpolates them
    # linearly across subdivided loops, so the tile scale stays correct.
    # ── 1a. Auto-detect projection mode + seam angle from geometry ───────
    # 'auto' uses geometry analysis (PhD: Advanced Texture Wrapping for CAD):
    #   - always LSCM (angle-preserving conformal maps)
    #   - 30° seams for CAD/prismatic parts, 60° seams for organic shapes
    seam_angle_rad = 1.0472  # default: 60° (organic)
    if projection == 'auto':
        projection, seam_angle_rad = _auto_projection(obj, log)

    use_uv = (projection in ('conformal', 'lscm'))
    if use_uv:
        _do_uv_unwrap(obj, tile_size, projection, log, seam_angle_rad=seam_angle_rad)

    # ── 2. Simple Subdivision ─────────────────────────────────────────────
    sub_level = _adaptive_subd_level(obj)
    if sub_level > 0:
        subd = obj.modifiers.new("Subdiv", type='SUBSURF')
        subd.subdivision_type = 'SIMPLE'
        subd.levels            = sub_level
        subd.render_levels     = sub_level
        log.log(f"  Subdiv modifier: Simple ×{sub_level}")
        with bpy.context.temp_override(
            active_object=obj, object=obj,
            selected_objects=[obj], selected_editable_objects=[obj],
        ):
            bpy.ops.object.modifier_apply(modifier="Subdiv")
        obj.data.update()
        log.log(f"  Subdiv applied: {len(obj.data.vertices)} verts")
    else:
        log.log(f"  Subdiv: skipped (mesh already dense — {len(obj.data.vertices)} verts)")

    # ── 3. Vertex group (optional) ────────────────────────────────────────
    vgroup_name = ""
    if not full_surface:
        # Legacy: restrict to faces pointing upward (normal.z > 0.5).
        # Walls, fillets, holes are excluded — they stay perfectly sharp.
        vg      = obj.vertex_groups.new(name="TopFace")
        mesh    = obj.data
        vert_max_z = [0.0] * len(mesh.vertices)
        for poly in mesh.polygons:
            nz = poly.normal.z
            for vi in poly.vertices:
                if nz > vert_max_z[vi]:
                    vert_max_z[vi] = nz
        top_verts = [i for i, nz in enumerate(vert_max_z) if nz > 0.5]
        vg.add(top_verts, 1.0, 'REPLACE')
        vgroup_name = "TopFace"
        log.log(f"  Vertex group 'TopFace': {len(top_verts)}/{len(mesh.vertices)} verts (normal.z > 0.5)")
    else:
        log.log("  Full-surface mode: no vertex mask — entire surface will be displaced")

    # ── 4. Load & prepare texture ─────────────────────────────────────────
    img = bpy.data.images.load(skin_path)
    img.colorspace_settings.name = "Non-Color"
    _gamma_correct_image(img, gamma, log)
    W, H = img.size[0], img.size[1]
    log.log(f"  Texture loaded: {W}×{H}px  tile_size={tile_size}mm")

    tex           = bpy.data.textures.new("SkinTexture", type='IMAGE')
    tex.image     = img
    tex.extension = 'REPEAT'   # tile seamlessly beyond UV island boundaries

    # ── 5. Displace modifier ──────────────────────────────────────────────
    if mode == "negative":
        strength  = -abs(relief)
        mid_level = 0.0
    else:
        strength  = (-relief if invert else relief)
        mid_level = 0.0

    disp           = obj.modifiers.new("Displace", type='DISPLACE')
    disp.texture   = tex
    disp.strength  = strength
    disp.mid_level = mid_level
    disp.direction = 'NORMAL'
    if vgroup_name:
        disp.vertex_group = vgroup_name

    if use_uv:
        # UV-based: Blender looks up the texture using the mesh's UV coords.
        # Because the UV was computed conformally (angle-preserving) and scaled
        # to tile_size mm per repeat, the displacement pattern follows the
        # surface geodesically — it wraps around curves just like painted skin.
        disp.texture_coords = 'UV'
        log.log(f"  Displace modifier: strength={strength:.2f}mm  "
                f"coords=UV({projection})  mid={mid_level:.1f}  "
                f"vgroup={'TopFace' if vgroup_name else 'none'}")
    else:
        # OBJECT-based: world-space box-map via a scaling Empty (legacy).
        # Works perfectly for box/flat geometry; stretches on curved surfaces.
        empty = bpy.data.objects.new("TexMap", None)
        bpy.context.collection.objects.link(empty)
        empty.scale = (tile_size, tile_size, tile_size)
        bpy.context.view_layer.update()
        disp.texture_coords        = 'OBJECT'
        disp.texture_coords_object = empty
        log.log(f"  Displace modifier: strength={strength:.2f}mm  "
                f"coords=OBJECT  empty_scale={tile_size}mm  mid={mid_level:.1f}  "
                f"vgroup={'TopFace' if vgroup_name else 'none'}")

    # ── 6. Apply Displace modifier ────────────────────────────────────────
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(
        active_object=obj, object=obj,
        selected_objects=[obj], selected_editable_objects=[obj],
    ):
        bpy.ops.object.modifier_apply(modifier="Displace")

    log.log(f"  Modifiers applied: {len(obj.data.vertices)} verts post-apply")
    log.log(f"  Done: relief={strength:.2f}mm  tile={tile_size}mm  mode={mode}  "
            f"projection={'UV('+projection+')' if use_uv else 'OBJECT'}  "
            f"full_surface={full_surface}")

    # ── 7. Shape DNA (diagnostic fingerprint) ────────────────────────────
    # Compute on the post-displacement mesh (before subdivision makes it huge).
    # Log eigenvalues so the user/debugger can verify shape integrity.
    # For meshes subdivided beyond 5 000 verts this is skipped automatically.
    _compute_shape_dna(obj, k=10, log=log)


def _apply_displacement(obj, skin_path: str, tile_size: float,
                        relief: float, invert: bool, gamma: float,
                        log: Logger, *, mode: str = "modifier",
                        projection: str = "object",
                        full_surface: bool = True):
    """Thin wrapper — always delegates to the full-Blender pipeline."""
    _apply_displacement_blender(
        obj, skin_path, tile_size, relief, invert, gamma, log,
        mode=mode, projection=projection, full_surface=full_surface,
    )


def _export_stl(obj, out_path: str, log: Logger):
    """
    Export a single mesh object to binary STL.

    Uses a pure-Python writer so no export add-on is required.
    Applies all modifiers via a dependency-graph evaluated mesh first.
    """
    import struct
    import mathutils  # bundled with bpy

    # Evaluate mesh with modifiers applied
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval  = obj.evaluated_get(depsgraph)
    mesh      = obj_eval.to_mesh()
    mesh.calc_loop_triangles()

    mat = obj.matrix_world  # identity after transform_apply; kept for safety

    with open(out_path, "wb") as f:
        # 80-byte header
        f.write(b"\0" * 80)
        # Triangle count
        tris = mesh.loop_triangles
        f.write(struct.pack("<I", len(tris)))
        for tri in tris:
            # Compute face normal in world space
            v0 = mat @ mathutils.Vector(mesh.vertices[tri.vertices[0]].co)
            v1 = mat @ mathutils.Vector(mesh.vertices[tri.vertices[1]].co)
            v2 = mat @ mathutils.Vector(mesh.vertices[tri.vertices[2]].co)
            edge1 = v1 - v0
            edge2 = v2 - v0
            normal = edge1.cross(edge2)
            length = normal.length
            if length > 1e-10:
                normal /= length
            f.write(struct.pack("<fff", normal.x, normal.y, normal.z))
            for v in (v0, v1, v2):
                f.write(struct.pack("<fff", v.x, v.y, v.z))
            f.write(struct.pack("<H", 0))  # attribute byte count

    obj_eval.to_mesh_clear()
    size_kb = os.path.getsize(out_path) // 1024
    log.log(f"  Exported: '{out_path}'  ({size_kb} KB)")


def _make_output_path(model_path: str, mode: str) -> str:
    p = pathlib.Path(model_path)
    stem = p.stem
    # Avoid accumulating suffixes on repeated runs
    for suffix in ("_texture_modifier", "_texture_part", "_texture_negative", "_texture"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return str(p.parent / f"{stem}_texture_{mode}.stl")


# ── main ──────────────────────────────────────────────────────────────────
def main():
    args = _parse_args()
    log_path = (
        args.log
        or os.path.join(tempfile.gettempdir(), "apply_texture_bpy_log.txt")
    )
    log = Logger(log_path)

    try:
        log.log("=== apply_texture_bpy.py ===")
        log.log(f"IS_FULL_BLENDER={IS_FULL_BLENDER}  binary_path={getattr(bpy.app, 'binary_path', 'n/a')}")
        log.log(f"mode={args.mode}  tile={args.tile_size}mm  "
                f"relief={args.relief}mm  invert={args.invert}  gamma={args.gamma}  "
                f"projection={args.projection}  full_surface={args.full_surface}")
        log.log(f"model: {args.model_path}")
        log.log(f"skin : {args.skin_path}")

        _reset_scene()

        meshes = _import_model(args.model_path, log)
        if not meshes:
            raise RuntimeError("No mesh objects found in model file")

        original_obj = meshes[0]
        out_path = _make_output_path(args.model_path, args.mode)

        # Bake the world transform into vertex coords so the exported STL is in
        # object-local space (same space QIDIStudio uses for ModelVolume geometry).
        # Without this, matrix_world offsets get applied twice → volume floats away.
        bpy.context.view_layer.objects.active = original_obj
        bpy.ops.object.select_all(action="DESELECT")
        original_obj.select_set(True)
        with _ops_ctx(original_obj):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        if args.mode == "modifier":
            # ── MODIFIER: displace the original mesh in-place, then replace ──
            # _apply_displacement handles UV unwrap internally (Step 1).
            _apply_displacement(
                original_obj, args.skin_path,
                args.tile_size, args.relief,
                args.invert, args.gamma, log,
                mode=args.mode,
                projection=args.projection,
                full_surface=args.full_surface,
            )
            _export_stl(original_obj, out_path, log)

        else:
            # ── PART / NEGATIVE: duplicate mesh, displace copy, export copy ──
            # UV is handled inside _apply_displacement_blender → _do_uv_unwrap
            # (no pre-UV step needed here — the LSCM/conformal unwrap runs on
            #  the copy after subdivision, not on the original).

            # Data-API duplicate — bpy.ops.object.duplicate() silently no-ops
            # in headless/background mode, causing displaced_obj to alias
            # original_obj and corrupting the source mesh.
            new_mesh = original_obj.data.copy()
            displaced_obj = original_obj.copy()
            displaced_obj.data = new_mesh
            displaced_obj.name = original_obj.name + "_tex"
            bpy.context.collection.objects.link(displaced_obj)

            # For NEGATIVE: displacement is always inward (mode handles this in
            # _apply_displacement, invert_mode passed for PART only)
            invert_mode = (not args.invert) if args.mode == "negative" else args.invert

            _apply_displacement(
                displaced_obj, args.skin_path,
                args.tile_size, args.relief,
                invert_mode, args.gamma, log,
                mode=args.mode,
                projection=args.projection,
                full_surface=args.full_surface,
            )
            _export_stl(displaced_obj, out_path, log)

        log.emit_skin_output(out_path)
        log.log("=== done ===")

    except Exception as exc:
        log.log(f"ERROR: {exc}")
        log.log(traceback.format_exc())
        sys.exit(1)
    finally:
        log.flush()


if __name__ == "__main__":
    main()
