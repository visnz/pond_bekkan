"""隔离后台：当前材质追加、原图保护、回滚、贴图识别和 Shader 入口。"""
import importlib
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
fab = importlib.import_module(ROOT.name + '.core.fab_material')
shader_tools = importlib.import_module(ROOT.name + '.core.shader_tools')
ui = importlib.import_module(ROOT.name + '.ui')
shader_panel = importlib.import_module(ROOT.name + '.ui.bekkan.shader_panel')
light_panel = importlib.import_module(ROOT.name + '.ui.bekkan.light_compose_panel')
SAMPLE = Path('C:/ProgramData/Epic/EpicGamesLauncher/VaultCache/FabLibrary/Worn_Concrete_Ceiling-2da64c55/texture-set/high/worn_concrete_ceiling_ug_extracted')
TEMP = ROOT / 'temp' / f'fab-material-test{bpy.app.version[0]}{bpy.app.version[1]}'
TEMP.mkdir(parents=True, exist_ok=True)
TEMP = Path(tempfile.mkdtemp(prefix='run-', dir=TEMP))
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
area.type = 'NODE_EDITOR'
space = area.spaces.active
space.tree_type = 'ShaderNodeTree'
space.shader_type = 'OBJECT'


def fixture(name, empty=False):
    material = bpy.data.materials.new(name)
    if material.node_tree is None:
        material.use_nodes = True
    bpy.context.object.data.materials.clear()
    bpy.context.object.data.materials.append(material)
    space.pin = False
    space.path.clear()
    space.path.start(material.node_tree)
    if empty:
        material.node_tree.nodes.clear()
    return material


def graph(tree):
    return ({n.name: (n.bl_idname, tuple(n.location), n.parent.name if n.parent else None,
                     getattr(n, 'is_active_output', None)) for n in tree.nodes},
            {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
             for l in tree.links})


def data_state():
    return (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials), len(bpy.data.images),
            tuple(o.name for o in bpy.context.selected_objects), bpy.context.view_layer.objects.active.name)


def failure(path, material):
    before, old_graph = data_state(), graph(material.node_tree)
    selection = {n.name: n.select for n in material.node_tree.nodes}
    active = material.node_tree.nodes.active
    try:
        assert bpy.ops.material.import_fab_visn(directory=str(path)) == {'CANCELLED'}
    except RuntimeError as exc:
        print('EXPECTED_FAILURE', str(exc))
    assert before == data_state()
    assert old_graph == graph(material.node_tree)
    assert selection == {n.name: n.select for n in material.node_tree.nodes}
    assert active == material.node_tree.nodes.active


def texture_files(folder, stem, maps=fab.ROLES):
    folder.mkdir(parents=True, exist_ok=True)
    for role in maps:
        image = bpy.data.images.new('Test fixture', width=16, height=16)
        image.filepath_raw = str(folder / f'{stem}_{role}.png')
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)


def check_nodes(imported, expected=6, group=False):
    textures = [n for n in imported if n.type == 'TEX_IMAGE']
    assert len(textures) == expected
    coordinate = next(n for n in imported if n.type == 'TEX_COORD')
    mapping = next(n for n in imported if n.type == 'MAPPING')
    value = next(n for n in imported if n.type == 'VALUE')
    shader = next(n for n in imported if n.type == 'BSDF_PRINCIPLED')
    assert mapping.inputs['Vector'].links[0].from_socket == coordinate.outputs['UV']
    assert mapping.inputs['Scale'].links[0].from_node == value
    assert value.outputs[0].default_value == 1
    for node in textures:
        assert node.inputs['Vector'].links[0].from_node == mapping
        assert node.image.colorspace_settings.name == ('sRGB' if node.label == 'Base Color' else 'Non-Color')
        assert node.image.size[0] > 0 and not node.outputs['Alpha'].is_linked
    assert shader.inputs['Base Color'].links[0].from_node.label == 'Base Color'
    if expected == 6:
        assert shader.inputs['Specular IOR Level'].links[0].from_node.label == 'Specular'
        assert shader.inputs['Roughness'].links[0].from_node.label == 'Roughness'
        normal = shader.inputs['Normal'].links[0].from_node
        assert normal.type == 'NORMAL_MAP' and normal.space == 'TANGENT'
        assert normal.inputs['Color'].links[0].from_node.label == 'Normal'
        displacement = next(n for n in imported if n.type == 'DISPLACEMENT')
        assert displacement.inputs['Height'].links[0].from_node.label == 'Displacement'
        if group:
            assert not displacement.outputs[0].is_linked
            assert not any(n.type == 'OUTPUT_MATERIAL' for n in imported)
        else:
            output = next(n for n in imported if n.type == 'OUTPUT_MATERIAL')
            assert output.inputs['Surface'].links[0].from_node == shader
            assert output.inputs['Displacement'].links[0].from_node == displacement
        ao = next(n for n in textures if n.label.startswith('AO'))
        assert not any(s.is_linked for s in ao.outputs)
    for a, b in combinations(imported, 2):
        aw, ah = shader_tools._node_size(a, 1)
        bw, bh = shader_tools._node_size(b, 1)
        x = min(a.location.x + aw, b.location.x + bw) - max(a.location.x, b.location.x)
        y = min(a.location.y, b.location.y) - max(a.location.y - ah, b.location.y - bh)
        assert x <= 0 or y <= 0, ('overlap', a.name, b.name)


with bpy.context.temp_override(area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
    material = fixture('Existing material')
    tree = material.node_tree
    assert shader_tools.current_material_tree(bpy.context) == tree
    frame = tree.nodes.new('NodeFrame')
    frame.location = (2000, 500)
    old_value = tree.nodes.new('ShaderNodeValue')
    old_value.parent = frame
    old_value.location = (300, -100)
    material.displacement_method = 'BOTH'
    failure(TEMP / 'does-not-exist', material)
    empty = TEMP / 'empty'
    empty.mkdir(exist_ok=True)
    failure(empty, material)
    folder, name, resolution, maps = fab.discover_textures(SAMPLE)
    assert name == 'Worn Concrete Ceiling' and resolution == 4 and set(maps) == set(fab.ROLES)
    assert all(m['path'].name.startswith('Worn_Concrete_Ceiling_ugtmehro_4K_') for m in maps.values())
    original, before = graph(tree), data_state()
    existing = set(tree.nodes)
    assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
    imported = [n for n in tree.nodes if n not in existing]
    check_nodes(imported)
    assert data_state()[:3] == before[:3] and data_state()[4:] == before[4:]
    assert material.displacement_method == 'BOTH'
    assert {k: v for k, v in graph(tree)[0].items() if k in original[0]} == original[0]
    assert original[1] <= graph(tree)[1]
    assert all(n.location.x > max(o.location_absolute.x + o.width for o in existing) for n in imported)
    assert not next(n for n in imported if n.type == 'OUTPUT_MATERIAL').is_active_output
    first_images = {n.image for n in imported if n.type == 'TEX_IMAGE'}
    existing = set(tree.nodes)
    assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
    assert {n.image for n in tree.nodes if n not in existing and n.type == 'TEX_IMAGE'} == first_images

    material = fixture('Empty material', empty=True)
    assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
    check_nodes(list(material.node_tree.nodes))
    assert material.displacement_method == 'BUMP'
    assert next(n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL').is_active_output

    both = TEMP / 'resolutions'
    texture_files(both, 'Test_2K')
    texture_files(both, 'Test_4K')
    assert fab.discover_textures(both)[2] == 4
    two = TEMP / '2k'
    texture_files(two, 'Test_2K')
    material = fixture('2K material', empty=True)
    assert bpy.ops.material.import_fab_visn(directory=str(two)) == {'FINISHED'}
    check_nodes(list(material.node_tree.nodes))
    partial = TEMP / 'partial'
    texture_files(partial, 'Partial_2K', ('BaseColor',))
    material = fixture('Partial material', empty=True)
    assert bpy.ops.material.import_fab_visn(directory=str(partial)) == {'FINISHED'}
    check_nodes(list(material.node_tree.nodes), expected=1)
    texture_files(partial, 'OtherAsset_2K', ('BaseColor',))
    failure(partial, material)
    broken = TEMP / 'broken'
    texture_files(broken, 'Broken_2K', ('BaseColor',))
    (broken / 'Broken_2K_Normal.png').write_bytes(b'not an image')
    failure(broken, material)
    existing_image = bpy.data.images.load(str(maps['normal']['path']), check_existing=False)
    existing_image.colorspace_settings.name = 'sRGB'
    assert bpy.ops.material.import_fab_visn(directory=str(SAMPLE)) == {'FINISHED'}
    assert existing_image.colorspace_settings.name == 'sRGB'
    dx = TEMP / 'directx'
    texture_files(dx, 'DX_2K', ('BaseColor', 'Normal_DX'))
    material = fixture('DX material', empty=True)
    assert fab.discover_textures(dx)[3]['normal']['directx']
    assert bpy.ops.material.import_fab_visn(directory=str(dx)) == {'FINISHED'}
    assert {n.operation for n in material.node_tree.nodes if n.type == 'VECT_MATH'} == {'ADD', 'MULTIPLY'}
    texture_files(dx, 'DX_2K', ('Normal_GL',))
    assert not fab.discover_textures(dx)[3]['normal']['directx']

    group = bpy.data.node_groups.new('Nested shader', 'ShaderNodeTree')
    group.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    group.nodes.new('NodeGroupOutput')
    old_graph = graph(group)
    imported, activated = fab.import_material_nodes(material, group, name, maps)
    check_nodes(imported, group=True)
    assert not activated and len(group.interface.items_tree) == 1
    assert old_graph[1] <= graph(group)[1]
    arrange = fab._arrange_imported_nodes
    def injected_error(*args):
        raise ValueError('Injected layout failure')
    fab._arrange_imported_nodes = injected_error
    failure(SAMPLE, material)
    fab._arrange_imported_nodes = arrange

    # 原有全工程法线修复从 Shader 上下文调用仍有效。
    texture = next(n for n in group.nodes if n.type == 'TEX_IMAGE' and n.label == 'Normal')
    texture.image.colorspace_settings.name = 'sRGB'
    group_node = material.node_tree.nodes.new('ShaderNodeGroup')
    group_node.node_tree = group
    assert bpy.ops.analyzer.fix_normal_colorspace_visn() == {'FINISHED'}
    assert texture.image.colorspace_settings.name == 'Non-Color'

    class LayoutRecorder:
        def __init__(self): self.ops = []
        def column(self, **kwargs): return self
        def operator(self, name, **kwargs): self.ops.append(name)
    layout = LayoutRecorder()
    shader_panel.BEKKAN_PT_shader_scripts.draw(SimpleNamespace(layout=layout), bpy.context)
    assert 'material.import_fab_visn' in layout.ops and 'analyzer.fix_normal_colorspace_visn' in layout.ops
    layout = LayoutRecorder()
    light_panel.BEKKAN_PT_light_compose.draw(SimpleNamespace(layout=layout), bpy.context)
    assert 'material.import_fab_visn' not in layout.ops and 'analyzer.fix_normal_colorspace_visn' not in layout.ops
    space.shader_type = 'WORLD'
    assert not bpy.ops.material.import_fab_visn.poll()
    assert not shader_panel.BEKKAN_PT_shader_scripts.poll(bpy.context)
    space.shader_type = 'OBJECT'

ui.apply_mode('BEKKAN')
assert hasattr(bpy.types, 'BEKKAN_PT_shader_scripts') and not hasattr(bpy.types, 'BEKKAN_PT_fab_material')
icons = bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys()
assert 'IMPORT' in icons and 'NODE_MATERIAL' in icons
ui.apply_mode('POND')
assert not hasattr(bpy.types, 'BEKKAN_PT_shader_scripts')
addon_utils.disable(ROOT.name, default_set=True)
assert addon_utils.enable(ROOT.name, default_set=True) is not None
addon_utils.disable(ROOT.name, default_set=True)
print('FAB_MATERIAL_TEST_OK', bpy.app.version_string)
