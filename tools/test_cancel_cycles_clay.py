"""隔离后台：材质/World 全部 Cycles 输入断开、All 恢复和实际渲染回归。"""
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
tools = importlib.import_module(ROOT.name + '.core.texture')


def fixture(kind, name):
    owner = getattr(bpy.data, kind).new(name)
    if owner.node_tree is None:
        owner.use_nodes = True
    return owner


def signature(tree):
    return ({n.name: (n.bl_idname, tuple(n.location)) for n in tree.nodes},
            {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
             for l in tree.links})


for kind, output_type, output_name in [('materials', 'OUTPUT_MATERIAL', 'ShaderNodeOutputMaterial'),
                                      ('worlds', 'OUTPUT_WORLD', 'ShaderNodeOutputWorld')]:
    owner = fixture(kind, 'Cancel ' + kind)
    tree = owner.node_tree
    original = next(n for n in tree.nodes if n.type == output_type)
    original.target = 'EEVEE'
    original.is_active_output = True
    cycles = tree.nodes.new(output_name)
    cycles.target = 'CYCLES'
    cycles.is_active_output = True
    # 所有专属输入都断开，包括自定义着色器、Volume、Displacement/Thickness。
    for socket in cycles.inputs:
        if socket.type == 'SHADER':
            shader = tree.nodes.new('ShaderNodeVolumePrincipled' if socket.name == 'Volume' else 'ShaderNodeBsdfPrincipled')
        elif socket.type == 'VECTOR':
            shader = tree.nodes.new('ShaderNodeDisplacement')
        else:
            shader = tree.nodes.new('ShaderNodeValue')
        tree.links.new(shader.outputs[0], socket)
    before = signature(tree)
    removed = {l for socket in cycles.inputs for l in socket.links}
    outside = {l for l in tree.links if l not in removed}
    assert tools.cancel_cycles_clay([owner], output_type) == (1, len(removed), 1, 0)
    assert not any(s.is_linked for s in cycles.inputs)
    assert not cycles.is_active_output and cycles.target == 'ALL'
    assert cycles['bekkan_cancelled_cycles_output']
    assert original.target == 'ALL' and original.is_active_output
    assert tree.get_output_node('CYCLES') == original
    assert tree.get_output_node('EEVEE') == original
    assert signature(tree)[0] == before[0]
    assert set(tree.links) == outside
    assert tools.cancel_cycles_clay([owner], output_type) == (0, 0, 0, 0)

    # 多个 EEVEE/已有 All 时优先使用原活跃 EEVEE。
    alternate = tree.nodes.new(output_name)
    alternate.target = 'EEVEE'
    active = tree.nodes.new(output_name)
    active.target = 'EEVEE'
    source = next(l.from_socket for l in original.inputs['Surface'].links)
    tree.links.new(source, active.inputs['Surface'])
    active.is_active_output = True
    tools.cancel_cycles_clay([owner], output_type)
    assert alternate.target == active.target == 'ALL'
    assert tree.get_output_node('CYCLES') == active
    assert active.inputs['Surface'].is_linked

    # 仅 Cycles 也依用户指令断线，不新建替代节点。
    only = fixture(kind, 'Only Cycles ' + kind)
    only_output = next(n for n in only.node_tree.nodes if n.type == output_type)
    only_output.target = 'CYCLES'
    size = len(only.node_tree.nodes)
    assert tools.cancel_cycles_clay([only], output_type) == (1, 1, 0, 0)
    assert not any(s.is_linked for s in only_output.inputs)
    assert len(only.node_tree.nodes) == size

    empty = fixture(kind, 'Empty ' + kind)
    empty.node_tree.nodes.clear()
    assert tools.cancel_cycles_clay([empty], output_type) == (0, 0, 0, 1)

assert bpy.ops.material.cancel_cycles_clay_visn() == {'FINISHED'}
icons = bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys()
assert 'NODE_MATERIAL' in icons
from types import SimpleNamespace
panel = importlib.import_module(ROOT.name + '.ui.bekkan.shader_panel')
class LayoutRecorder:
    def __init__(self): self.ops = []
    def column(self, **kwargs): return self
    def operator(self, name, **kwargs): self.ops.append(name)
layout = LayoutRecorder()
panel.BEKKAN_PT_shader_scripts.draw(SimpleNamespace(layout=layout), bpy.context)
assert layout.ops.index('material.cancel_cycles_clay_visn') == layout.ops.index('material.cycles_clay_visn') + 1
light_panel = importlib.import_module(ROOT.name + '.ui.bekkan.light_compose_panel')
layout = LayoutRecorder()
light_panel.BEKKAN_PT_light_compose.draw(SimpleNamespace(layout=layout), bpy.context)
assert 'material.cycles_clay_visn' not in layout.ops and 'material.cancel_cycles_clay_visn' not in layout.ops

if '--render' in sys.argv:
    scene = bpy.context.scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
    sphere = bpy.context.object
    for polygon in sphere.data.polygons:
        polygon.use_smooth = True
    mat = fixture('materials', 'Cancel render material')
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (0.4, 0.05, 0.02, 1)
    sphere.data.materials.append(mat)
    world = fixture('worlds', 'Cancel render world')
    background = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
    background.inputs['Color'].default_value = (0.08, 0.12, 0.2, 1)
    scene.world = world
    bpy.ops.object.camera_add(location=(3, -5, 2))
    camera = bpy.context.object
    camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 3
    scene.camera = camera
    bpy.ops.object.light_add(type='AREA', location=(2, -3, 4))
    bpy.context.object.data.energy = 400
    bpy.context.object.data.size = 3
    bpy.context.object.rotation_euler = (-bpy.context.object.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = 96
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_mode = 'RGBA'
    folder = ROOT / 'temp' / f'cancel-clay-render{bpy.app.version[0]}{bpy.app.version[1]}'
    folder.mkdir(parents=True, exist_ok=True)

    def render(name):
        scene.render.filepath = str(folder / (name + '.exr'))
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels = list(image.pixels)
        bpy.data.images.remove(image)
        return pixels

    baseline = render('original')
    tools.adapt_cycles_clay([mat])
    tools.adapt_cycles_worlds([world])
    adapted = render('clay')
    assert sum(abs(a-b) for a, b in zip(baseline, adapted)) > 10
    tools.cancel_cycles_clay([mat], 'OUTPUT_MATERIAL')
    tools.cancel_cycles_clay([world], 'OUTPUT_WORLD')
    restored = render('restored')
    delta = max(abs(a-b) for a, b in zip(baseline, restored))
    assert delta < 1e-5, ('render not restored', delta)
    mat_outputs = [n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL']
    world_outputs = [n for n in world.node_tree.nodes if n.type == 'OUTPUT_WORLD']
    former_cycles = next(n for n in mat_outputs if n.get('bekkan_cancelled_cycles_output'))
    former_world_cycles = next(n for n in world_outputs if n.get('bekkan_cancelled_cycles_output'))
    tools.adapt_cycles_clay([mat])
    tools.adapt_cycles_worlds([world])
    assert former_cycles.target == former_world_cycles.target == 'CYCLES'
    assert former_cycles.inputs['Surface'].is_linked and former_world_cycles.inputs['Surface'].is_linked
    assert mat_outputs == [n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL']
    assert world_outputs == [n for n in world.node_tree.nodes if n.type == 'OUTPUT_WORLD']
    tools.cancel_cycles_clay([mat], 'OUTPUT_MATERIAL')
    tools.cancel_cycles_clay([world], 'OUTPUT_WORLD')
    mat.node_tree.links.new(bsdf.outputs[0], former_cycles.inputs['Surface'])
    tools.adapt_cycles_clay([mat])
    assert former_cycles.target == 'EEVEE' and former_cycles.inputs['Surface'].is_linked
    assert not former_cycles.get('bekkan_cancelled_cycles_output')
    print('CANCEL_CLAY_RENDER_OK', 'max_delta', delta)

addon_utils.disable(ROOT.name, default_set=True)
assert addon_utils.enable(ROOT.name, default_set=True) is not None
addon_utils.disable(ROOT.name, default_set=True)
print('CANCEL_CYCLES_CLAY_TEST_OK', bpy.app.version_string)
