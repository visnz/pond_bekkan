"""隔离测试。启动前设置独立 BLENDER_USER_RESOURCES，然后用 -b --factory-startup -P 本文件。"""
import importlib
from itertools import combinations
from pathlib import Path
import sys

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
fab = importlib.import_module(ROOT.name + '.core.fab_material')
shader_tools = importlib.import_module(ROOT.name + '.core.shader_tools')
ui = importlib.import_module(ROOT.name + '.ui')
SAMPLE = Path(r'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary\Worn_Concrete_Ceiling-2da64c55\texture-set\high\worn_concrete_ceiling_ug_extracted')
TEMP = ROOT / 'temp' / f'fab-material-test{bpy.app.version[0]}{bpy.app.version[1]}'
TEMP.mkdir(parents=True, exist_ok=True)


def failure(path):
    before = (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))
    try:
        assert bpy.ops.material.import_fab_visn(directory=str(path)) == {'CANCELLED'}
    except RuntimeError as exc:
        print('EXPECTED_FAILURE', str(exc))
    assert before == (len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images))


def texture_files(folder, stem, maps=fab.ROLES):
    folder.mkdir(parents=True, exist_ok=True)
    for role in maps:
        image = bpy.data.images.new('Test fixture', width=16, height=16)
        image.filepath_raw = str(folder / f'{stem}_{role}.png')
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)


def check_material(material, expected=6):
    tree = material.node_tree
    textures = [n for n in tree.nodes if n.type == 'TEX_IMAGE']
    assert len(textures) == expected
    coordinate = next(n for n in tree.nodes if n.type == 'TEX_COORD')
    mapping = next(n for n in tree.nodes if n.type == 'MAPPING')
    value = next(n for n in tree.nodes if n.type == 'VALUE')
    shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL')
    assert mapping.inputs['Vector'].links[0].from_socket == coordinate.outputs['UV']
    assert mapping.inputs['Scale'].links[0].from_node == value
    assert value.outputs[0].default_value == 1
    assert material.displacement_method == 'BUMP'
    for node in textures:
        assert node.inputs['Vector'].links[0].from_node == mapping
        assert node.image.colorspace_settings.name == ('sRGB' if node.label == 'Base Color' else 'Non-Color')
        assert node.image.size[0] > 0
        assert not node.outputs['Alpha'].is_linked
    assert shader.inputs['Base Color'].links[0].from_node.label == 'Base Color'
    if expected == 6:
        assert shader.inputs['Specular IOR Level'].links[0].from_node.label == 'Specular'
        assert shader.inputs['Roughness'].links[0].from_node.label == 'Roughness'
        normal = shader.inputs['Normal'].links[0].from_node
        assert normal.type == 'NORMAL_MAP' and normal.space == 'TANGENT'
        assert normal.inputs['Color'].links[0].from_node.label == 'Normal'
        displacement = output.inputs['Displacement'].links[0].from_node
        assert displacement.type == 'DISPLACEMENT'
        assert displacement.inputs['Height'].links[0].from_node.label == 'Displacement'
        ao = next(n for n in textures if n.label.startswith('AO'))
        assert not any(s.is_linked for s in ao.outputs)
    for a, b in combinations(tree.nodes, 2):
        aw, ah = shader_tools._node_size(a, 1)
        bw, bh = shader_tools._node_size(b, 1)
        x = min(a.location.x + aw, b.location.x + bw) - max(a.location.x, b.location.x)
        y = min(a.location.y, b.location.y) - max(a.location.y - ah, b.location.y - bh)
        assert x <= 0 or y <= 0, ('overlap', a.name, b.name)


failure(TEMP / 'does-not-exist')
empty = TEMP / 'empty'
empty.mkdir(exist_ok=True)
failure(empty)
folder, name, resolution, maps = fab.discover_textures(SAMPLE)
assert name == 'Worn Concrete Ceiling' and resolution == 4 and set(maps) == set(fab.ROLES)
assert all(m['path'].name.startswith('Worn_Concrete_Ceiling_ugtmehro_4K_') for m in maps.values())
previous = {o.name: (o.type, tuple(o.location)) for o in bpy.context.scene.objects}
bpy.context.scene.cursor.location = (1, 2, 3)
assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
monkey = bpy.context.object
assert monkey.type == 'MESH' and len(monkey.data.uv_layers) == 1
assert tuple(monkey.location) == (1, 2, 3)
assert len(monkey.data.materials) == 1
assert len(monkey.modifiers) == 1 and monkey.modifiers[0].levels == 2
assert all(p.use_smooth for p in monkey.data.polygons)
material = monkey.active_material
check_material(material)
assert previous == {o.name: (o.type, tuple(o.location)) for o in bpy.context.scene.objects if o.name in previous}
first_images = {n.image for n in material.node_tree.nodes if n.type == 'TEX_IMAGE'}
first_name = monkey.name
assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
assert bpy.context.object.name != first_name and bpy.context.object.active_material != material
assert {n.image for n in bpy.context.object.active_material.node_tree.nodes if n.type == 'TEX_IMAGE'} == first_images

# 同一目录的 2K/4K、大小写、额外图、图片复用和缺少非核心图。
both = TEMP / 'resolutions'
texture_files(both, 'Test_2K')
texture_files(both, 'Test_4K')
texture_files(both, 'Test_4K', ('Gloss', 'Bump', 'Cavity'))
assert fab.discover_textures(both)[2] == 4
two = TEMP / '2k'
texture_files(two, 'Test_2K')
assert bpy.ops.material.import_fab_visn(directory=str(two)) == {'FINISHED'}
check_material(bpy.context.object.active_material)
partial = TEMP / 'partial'
texture_files(partial, 'Partial_2K', ('BaseColor',))
assert bpy.ops.material.import_fab_visn(directory=str(partial)) == {'FINISHED'}
check_material(bpy.context.object.active_material, expected=1)
texture_files(partial, 'OtherAsset_2K', ('BaseColor',))
failure(partial)

# 读取错误不能留下新图片/材质/物体；原有图片的色彩空间不改。
broken = TEMP / 'broken'
texture_files(broken, 'Broken_2K', ('BaseColor',))
(broken / 'Broken_2K_Normal.png').write_bytes(b'not an image')
failure(broken)
original_normal = maps['normal']['path']
existing = bpy.data.images.load(str(original_normal), check_existing=False)
existing.colorspace_settings.name = 'sRGB'
assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
assert existing.colorspace_settings.name == 'sRGB'

# GL 优先；只有 DX 时在 Normal Map 前进行绿色通道翻转。
dx = TEMP / 'directx'
texture_files(dx, 'DX_2K', ('BaseColor', 'Normal_DX'))
assert fab.discover_textures(dx)[3]['normal']['directx']
assert bpy.ops.material.import_fab_visn(directory=str(dx)) == {'FINISHED'}
tree = bpy.context.object.active_material.node_tree
assert {n.operation for n in tree.nodes if n.type == 'VECT_MATH'} == {'ADD', 'MULTIPLY'}
texture_files(dx, 'DX_2K', ('Normal_GL',))
assert not fab.discover_textures(dx)[3]['normal']['directx']

# 只在别馆显示，反向注销与重载保持正常。
ui.apply_mode('BEKKAN')
assert hasattr(bpy.types, 'BEKKAN_PT_fab_material')
assert bpy.types.BEKKAN_PT_fab_material.bl_parent_id == 'BEKKAN_PT_light_compose'
icons = bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys()
assert 'IMPORT' in icons
ui.apply_mode('POND')
assert not hasattr(bpy.types, 'BEKKAN_PT_fab_material')
addon_utils.disable(ROOT.name, default_set=True)
assert not hasattr(bpy.types, 'BEKKAN_PT_fab_material')
assert addon_utils.enable(ROOT.name, default_set=True) is not None
addon_utils.disable(ROOT.name, default_set=True)
print('FAB_MATERIAL_TEST_OK', bpy.app.version_string)
