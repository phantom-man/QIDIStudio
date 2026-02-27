"""
Self-contained: create flat plate -> displace with texture -> render preview.
Usage:
  blender --background --python test_texture_pipeline.py -- <skin.png> [output.png]
"""
import bpy, sys, math, pathlib
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
skin_png = argv[0] if argv else r"C:\QIDISrc\QIDIStudio\install_dir\resources\assets\armadillo_plates\armadillo_plates_01.png"
out_png  = argv[1] if len(argv) > 1 else r"C:\Users\User\source\repos\QIDIStudio\scripts\plate_preview.png"

TILE_MM   = 15.0
RELIEF_MM = 2.0

# 1. Fresh scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system       = "METRIC"
scene.unit_settings.scale_length = 0.001

# 2. Flat plate 90x50mm, well subdivided
bpy.ops.mesh.primitive_grid_add(x_subdivisions=60, y_subdivisions=40, size=1, location=(0, 0, 1.5))
plate = bpy.context.active_object
plate.scale = (90, 50, 1)
bpy.ops.object.transform_apply(scale=True)

sol = plate.modifiers.new("Sol", type='SOLIDIFY')
sol.thickness = 3
with bpy.context.temp_override(active_object=plate, object=plate,
                                selected_objects=[plate], selected_editable_objects=[plate]):
    bpy.ops.object.modifier_apply(modifier="Sol")

print(f"Plate: {len(plate.data.vertices)} verts, {len(plate.data.polygons)} polys")

# 3. Load texture
img = bpy.data.images.load(skin_png)
img.colorspace_settings.name = "Non-Color"
print(f"Texture: {img.size[0]}x{img.size[1]}px")

# 4. Mapping empty (scale = tile size in mm)
empty = bpy.data.objects.new("Map", None)
bpy.context.collection.objects.link(empty)
empty.scale = (TILE_MM, TILE_MM, TILE_MM)
bpy.context.view_layer.update()

# 5. Displace modifier
tex = bpy.data.textures.new("Skin", type='IMAGE')
tex.image = img

disp = plate.modifiers.new("Disp", type='DISPLACE')
disp.texture               = tex
disp.texture_coords        = 'OBJECT'
disp.texture_coords_object = empty
disp.strength              = RELIEF_MM
disp.mid_level             = 0.0       # PNG is [0..1] height: black=flat, white=+RELIEF_MM
disp.direction             = 'NORMAL'

with bpy.context.temp_override(active_object=plate, object=plate,
                                selected_objects=[plate], selected_editable_objects=[plate]):
    bpy.ops.object.modifier_apply(modifier="Disp")

print(f"Displaced: {len(plate.data.vertices)} verts")

out_stl = r"C:\Users\User\source\repos\QIDIStudio\scripts\plate_displaced.stl"
bpy.ops.wm.stl_export(filepath=out_stl, export_selected_objects=True)
print(f"STL: {pathlib.Path(out_stl).stat().st_size//1024} KB")

# 6. Render
cam_data = bpy.data.cameras.new("C"); cam_data.lens = 50
cam = bpy.data.objects.new("C", cam_data)
bpy.context.collection.objects.link(cam)
scene.camera = cam
# Camera centred on plate (origin), pulled back and up
cam.location = (0, -180, 90)
cam.rotation_euler = (math.radians(63), 0, 0)

# World background — REQUIRED for Cycles to show anything without HDRI
world = bpy.data.worlds.new("W")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.15, 0.15, 0.15, 1.0)  # light ambient fill
bg.inputs[1].default_value = 1.2
scene.world = world

# Key + fill lights — cranked high for mm-scale scene
for pos, nrg in [((150, -60, 200), 150000), ((-80, 120, 60), 40000)]:
    ld = bpy.data.lights.new("L", type='AREA'); ld.energy = nrg; ld.size = 150
    lo = bpy.data.objects.new("L", ld)
    bpy.context.collection.objects.link(lo)
    lo.location = pos

mat = bpy.data.materials.new("M"); mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.18, 0.45, 0.85, 1.0)
bsdf.inputs["Roughness"].default_value  = 0.25
plate.data.materials.append(mat)

scene.render.engine = 'CYCLES'
scene.cycles.samples = 128
scene.render.resolution_x = 1000
scene.render.resolution_y = 700
scene.render.filepath = out_png
scene.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)
print(f"PREVIEW_DONE: {out_png}")
