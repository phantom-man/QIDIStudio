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
        print(msg, flush=True)
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
        bpy.ops.import_mesh.stl(filepath=path)
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


def _smart_uv_project(obj, log: Logger):
    """UV-unwrap with Smart UV Project (angle-based islands, no seam waste)."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    log.log(f"  UV unwrap complete on '{obj.name}'")


def _gamma_correct_image(img, gamma: float, log: Logger):
    """Apply per-pixel gamma correction to a loaded Image."""
    if abs(gamma - 1.0) < 0.01:
        return
    px = list(img.pixels[:])
    g_inv = 1.0 / gamma
    for i in range(0, len(px), 4):   # RGBA
        px[i]   = max(0.0, px[i]  ) ** g_inv
        px[i+1] = max(0.0, px[i+1]) ** g_inv
        px[i+2] = max(0.0, px[i+2]) ** g_inv
        # alpha channel unchanged
    img.pixels[:] = px
    img.update()
    log.log(f"  Gamma correction applied (γ={gamma})")


def _apply_displacement(obj, skin_path: str, tile_size: float,
                        relief: float, invert: bool, gamma: float,
                        log: Logger):
    """
    Subdivide the mesh (Simple) and apply a Displace modifier.

    Texture coordinates use an Empty object scaled to tile_size mm so the
    skin repeats every tile_size mm in world space — no UV seam artifacts.
    """
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # ── 1. Subdivision (Simple — preserves hard edges) ──────────────
    sub = obj.modifiers.new("Subd_tex", type="SUBSURF")
    sub.subdivision_type = "SIMPLE"
    sub.levels = 3
    # Ensure subdivision runs before displacement
    while obj.modifiers[0].name != sub.name:
        bpy.ops.object.modifier_move_up(modifier=sub.name)

    # ── 2. Load image and apply gamma ────────────────────────────────
    img = bpy.data.images.load(skin_path)
    img.colorspace_settings.name = "Non-Color"  # displacement = data, not colour
    _gamma_correct_image(img, gamma, log)

    # ── 3. Image texture (legacy texture API — used by Displace modifier) ──
    tex = bpy.data.textures.new("skin_tex", type="IMAGE")
    tex.image = img

    # ── 4. Mapping Empty ─────────────────────────────────────────────
    # Scale = tile_size → the displacement repeats every tile_size world
    # units (mm, given scale_length = 0.001).
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, 0.0, 0.0))
    mapping_empty = bpy.context.active_object
    mapping_empty.name = "tex_mapping_empty"
    mapping_empty.scale = (tile_size, tile_size, tile_size)

    # ── 5. Displace modifier ─────────────────────────────────────────
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("Displace_tex", type="DISPLACE")
    mod.texture              = tex
    mod.texture_coords        = "OBJECT"
    mod.texture_coords_object = mapping_empty
    mod.direction            = "NORMAL"
    mod.strength             = (-relief if invert else relief)
    mod.mid_level            = 0.5    # 0.5 = grey = zero displacement

    # ── 6. Apply all modifiers ────────────────────────────────────────
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    for m in list(obj.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=m.name)
        except Exception as exc:
            log.log(f"  WARNING: could not apply modifier '{m.name}': {exc}")

    log.log(f"  Displacement applied: relief={mod.strength:.2f}mm "
            f"tile={tile_size}mm invert={invert}")


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
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        if args.mode == "modifier":
            # ── MODIFIER: displace the original mesh in-place, then replace ──
            _smart_uv_project(original_obj, log)
            _apply_displacement(
                original_obj, args.skin_path,
                args.tile_size, args.relief,
                args.invert, args.gamma, log,
            )
            _export_stl(original_obj, out_path, log)

        else:
            # ── PART / NEGATIVE: duplicate mesh, displace copy, export copy ──
            # UV the original first so the duplicate inherits correct UV layout
            _smart_uv_project(original_obj, log)

            bpy.context.view_layer.objects.active = original_obj
            bpy.ops.object.select_all(action="DESELECT")
            original_obj.select_set(True)
            bpy.ops.object.duplicate()
            displaced_obj = bpy.context.active_object
            displaced_obj.name = original_obj.name + "_tex"

            # For NEGATIVE: flip displacement so the shell sticks outward
            # (QIDIStudio booleans it INTO the parent, creating carved relief)
            invert_mode = (not args.invert) if args.mode == "negative" else args.invert

            _apply_displacement(
                displaced_obj, args.skin_path,
                args.tile_size, args.relief,
                invert_mode, args.gamma, log,
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
