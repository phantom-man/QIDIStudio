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


def _adaptive_subd_level(obj) -> int:
    """
    Choose a subdivision level so result stays under ~150K triangles.
    A box starts at 12 tris; each Simple-Subd level = 4× triangles.
    Complex meshes (imported parts) should stay at level 1-2.
    """
    n = len(obj.data.polygons)
    if   n <= 50:    return 3   # primitive test geometry
    elif n <= 500:   return 2
    elif n <= 4000:  return 1
    else:            return 1


def _apply_displacement(obj, skin_path: str, tile_size: float,
                        relief: float, invert: bool, gamma: float,
                        log: Logger, *, mode: str = "modifier"):
    """
    Pure-Python UV displacement pipeline — no Displace modifier, no bmesh.from_object().

    The entire history of seam-streak and shredded-mesh artifacts traced to
    bmesh.from_object(): it splits vertices at UV seam edges so each side
    displaces differently.  This function avoids that entirely:

      0. Weld vertices (STL has one vertex copy per triangle face)
      1. Subdivide via bmesh.ops.subdivide_edges() — pure bmesh, no modifier
      2. Smart UV Project — marks seam edges but does NOT split vertices
      3. Scale UVs so 1 UV unit = tile_size mm across the object
      4. Load image pixels into numpy array (with gamma)
      5. For each vertex: average its UV across all loops, sample texture
         bilinearly (with tiling), displace along vertex normal
      6. Recalculate face normals

    No modifier stack, no depsgraph bake, no vertex splits.
    """
    import bmesh
    try:
        import numpy as np
        HAS_NP = True
    except ImportError:
        HAS_NP = False
        log.log("  WARNING: numpy not found; using slow pixel loop fallback")

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # ── 0. Weld ──────────────────────────────────────────────────────
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before_w = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    after_w = len(obj.data.vertices)
    log.log(f"  Welded: {before_w}→{after_w} verts")

    # ── 1. Subdivide via bmesh.ops (no modifier → nothing to bake) ───
    # bmesh.ops.subdivide_edges bisects each edge — existing vertex
    # positions are never moved, so holes and sharp edges stay intact.
    sub_level = _adaptive_subd_level(obj)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for _ in range(sub_level):
        bmesh.ops.subdivide_edges(
            bm, edges=bm.edges[:], cuts=1, use_grid_fill=True
        )
    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    log.log(f"  Subdivided ×{sub_level} (bmesh.ops): {len(obj.data.vertices)} verts")

    # ── 2. UV unwrap ─────────────────────────────────────────────────
    # Smart UV Project marks seam edges but does NOT split vertices in
    # the stored mesh.  Vertex splits only happen inside bmesh.from_object()
    # when a modifier stack uses UV coords — we never call that here.
    _smart_uv_project(obj, log)

    # ── 3. Scale UVs for tile_size ───────────────────────────────────
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    bbox_x = max(xs) - min(xs)
    bbox_y = max(ys) - min(ys)
    uv_scale = max(max(bbox_x, bbox_y) / tile_size, 1.0) if tile_size > 0 else 1.0
    uv_layer = obj.data.uv_layers.active
    for luv in uv_layer.data:
        luv.uv.x *= uv_scale
        luv.uv.y *= uv_scale
    log.log(f"  UV scale ×{uv_scale:.2f} (bbox={bbox_x:.1f}×{bbox_y:.1f}mm tile={tile_size}mm)")

    # ── 4. Load texture pixels ───────────────────────────────────────
    img = bpy.data.images.load(skin_path)
    img.colorspace_settings.name = "Non-Color"
    _gamma_correct_image(img, gamma, log)
    W, H = img.size[0], img.size[1]
    if HAS_NP:
        px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)
    else:
        px_flat = list(img.pixels[:])
    log.log(f"  Texture loaded: {W}×{H}px")

    def sample(u: float, v: float) -> float:
        """Bilinear sample with repeat tiling."""
        u = u % 1.0
        v = v % 1.0
        fx = u * (W - 1)
        fy = v * (H - 1)
        x0, y0 = int(fx), int(fy)
        x1 = min(x0 + 1, W - 1)
        y1 = min(y0 + 1, H - 1)
        tx, ty = fx - x0, fy - y0
        if HAS_NP:
            c00 = float(px[y0, x0, 0])
            c10 = float(px[y0, x1, 0])
            c01 = float(px[y1, x0, 0])
            c11 = float(px[y1, x1, 0])
        else:
            def idx(yy, xx): return (yy * W + xx) * 4
            c00 = px_flat[idx(y0, x0)]
            c10 = px_flat[idx(y0, x1)]
            c01 = px_flat[idx(y1, x0)]
            c11 = px_flat[idx(y1, x1)]
        return c00*(1-tx)*(1-ty) + c10*tx*(1-ty) + c01*(1-tx)*ty + c11*tx*ty

    # ── 5. Build vert → averaged UV map ─────────────────────────────
    # A vertex at a seam appears in loops with different UVs.  Average
    # them — since the texture tiles, the average of two seam-side UVs
    # may differ by ~1.0; use the fractional average to stay consistent.
    mesh = obj.data
    uv_data = uv_layer.data
    vert_uv_sum = {}   # vi → [sum_u, sum_v, count]
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            uv = uv_data[li].uv
            if vi not in vert_uv_sum:
                vert_uv_sum[vi] = [0.0, 0.0, 0]
            vert_uv_sum[vi][0] += uv.x
            vert_uv_sum[vi][1] += uv.y
            vert_uv_sum[vi][2] += 1

    # ── 6. Displace each vertex along its normal ─────────────────────
    if mode == "negative":
        mid_level = 0.0
        strength  = -abs(relief)
    else:
        mid_level = 0.5
        strength  = (-relief if invert else relief)

    displaced = 0
    for v in mesh.vertices:
        entry = vert_uv_sum.get(v.index)
        if not entry or entry[2] == 0:
            continue
        u = entry[0] / entry[2]
        vc = entry[1] / entry[2]
        pixel_val = sample(u, vc)
        disp = (pixel_val - mid_level) * strength
        n = v.normal
        v.co.x += n.x * disp
        v.co.y += n.y * disp
        v.co.z += n.z * disp
        displaced += 1

    mesh.update()
    log.log(f"  Displaced {displaced}/{len(mesh.vertices)} verts"
            f"  strength={strength:.2f}mm mid={mid_level}")

    # ── 7. Recalculate face normals ──────────────────────────────────
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    log.log(f"  Done: relief={strength:.2f}mm tile={tile_size}mm mode={mode}")


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
        log.log(f"mode={args.mode}  tile={args.tile_size}mm  "
                f"relief={args.relief}mm  invert={args.invert}  gamma={args.gamma}")
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
            )
            _export_stl(original_obj, out_path, log)

        else:
            # ── PART / NEGATIVE: duplicate mesh, displace copy, export copy ──
            # UV the original first so the duplicate inherits correct UV layout
            _smart_uv_project(original_obj, log)

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
