"""独立渲染：真实 4K 材质、UV 法线与 Value→Mapping 缩放生效。"""
import importlib
import json
from pathlib import Path
import sys

import addon_utils
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
SAMPLE = Path(r'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary\Worn_Concrete_Ceiling-2da64c55\texture-set\high\worn_concrete_ceiling_ug_extracted')
scene = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
monkey = bpy.context.object
tree = monkey.active_material.node_tree
scale = next(n for n in tree.nodes if n.type == 'VALUE')
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.render.resolution_x = scene.render.resolution_y = 256
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.film_transparent = True
bpy.ops.object.camera_add(location=(3.2, -6, 2.3))
camera = bpy.context.object
camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 3.8
scene.camera = camera
bpy.ops.object.light_add(type='AREA', location=(1.5, -3, 4))
key = bpy.context.object
key.data.energy = 500
key.data.shape = 'DISK'
key.data.size = 3
key.rotation_euler = (-key.location).to_track_quat('-Z', 'Y').to_euler()
OUTPUT = ROOT / 'temp' / f'fab-render{bpy.app.version[0]}{bpy.app.version[1]}'
OUTPUT.mkdir(parents=True, exist_ok=True)
pixels = []
for number in (1, 2):
    scale.outputs[0].default_value = number
    scene.render.filepath = str(OUTPUT / f'scale-{number}.png')
    assert bpy.ops.render.render(write_still=True) == {'FINISHED'}
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    pixels.append(list(image.pixels))
    bpy.data.images.remove(image)
foreground = [i for i in range(0, len(pixels[0]), 4) if pixels[0][i + 3] > 0.9]
assert len(foreground) > 5000
changed = sum(any(abs(pixels[0][i + c] - pixels[1][i + c]) > 0.02 for c in range(3)) for i in foreground)
assert changed > 1000, changed
assert monkey.active_material.displacement_method == 'BUMP'
result = {'ok': True, 'blender': bpy.app.version_string,
          'foreground_pixels': len(foreground), 'changed_pixels': changed}
(OUTPUT / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('FAB_MATERIAL_RENDER_OK', result)
