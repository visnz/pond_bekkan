"""独立低分辨率渲染，对比融合开关与含逗号材质的 Cryptomatte ID。"""
import importlib
import json
from pathlib import Path
import sys

import addon_utils
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=False) is not None
ab = importlib.import_module(ROOT.name + ".core.autoblend")
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 160
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    output = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    emission = mat.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1)
    mat.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return mat


mat1 = material("AutoBlend, Red Test", (0.7, 0.02, 0.01))
mat2 = material("AutoBlend Blue Test", (0.01, 0.03, 0.7))
objects = []
for x, mat in ((-0.6, mat1), (0.6, mat2)):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=(x, 0, 1))
    obj = bpy.context.object
    obj.data.materials.append(mat)
    objects.append(obj)
bpy.ops.mesh.primitive_plane_add(size=20)
bpy.context.object.data.materials.append(material("AutoBlend Ground", (0.04, 0.12, 0.03)))
bpy.ops.object.camera_add(location=(3, -6, 3.5))
camera = bpy.context.object
camera.rotation_euler = (Vector((0, 0, 0.9)) - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type = "ORTHO"
camera.data.ortho_scale = 4.5
scene.camera = camera
assert bpy.ops.render.autoblend_setup_visn(enable_viewport_compositor=False) == {"FINISHED"}
node = ab.get_autoblend_node(ab.compositor_tree(scene))
node.inputs["Blend Distance"].default_value = 0.3
node.inputs["Max Size"].default_value = 1
node.inputs["Hardness"].default_value = 0.5
bpy.ops.object.select_all(action="DESELECT")
objects[0].select_set(True)
bpy.context.view_layer.objects.active = objects[0]
assert bpy.ops.render.autoblend_add_visn() == {"FINISHED"}
version = f"{bpy.app.version[0]}{bpy.app.version[1]}"
directory = ROOT / "temp" / ("autoblend-render" + version)
directory.mkdir(parents=True, exist_ok=True)
pixels = {}
for name, mute in (("off", True), ("on", False)):
    node.mute = mute
    scene.render.filepath = str(directory / (name + ".png"))
    assert bpy.ops.render.render(write_still=True) == {"FINISHED"}
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    pixels[name] = list(image.pixels)
    bpy.data.images.remove(image)
tree = ab.compositor_tree(scene)
crypto = ab.get_material_node(tree)
output = next(n for n in tree.nodes if n.bl_idname == "NodeGroupOutput")
tree.links.new(crypto.outputs["Matte"], output.inputs["Image"])
scene.render.filepath = str(directory / "matte.png")
bpy.ops.render.render(write_still=True)
image = bpy.data.images.load(scene.render.filepath, check_existing=False)
matte = list(image.pixels)
assert sum(v > 0.9 for v in matte[::4]) > 200  # 特殊名称确实选中红球。
assert sum(v < 0.1 for v in matte[::4]) > 200
bpy.data.images.remove(image)
differences = [abs(a - b) for a, b in zip(pixels["on"], pixels["off"])]
changed = sum(any(v > 1e-3 for v in differences[i:i + 3]) for i in range(0, len(differences), 4))
assert changed > 25, (changed, max(differences))
assert all(v == v for v in pixels["on"])
result = {"blender": bpy.app.version_string, "device": scene.render.compositor_device,
          "changed_pixels": changed, "max_difference": max(differences),
          "mean_difference": sum(differences) / len(differences), "ok": True}
(directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("AUTOBLEND_RENDER_OK", result)
