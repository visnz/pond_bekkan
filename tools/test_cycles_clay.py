"""隔离后台：白膜新接口、旧组升级、默认识别、自然法线与透明/灰度渲染。"""
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
tools = importlib.import_module(ROOT.name + '.core.texture')


def material(name, target='ALL', shader='ShaderNodeBsdfPrincipled'):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    mat.node_tree.nodes.clear()
    output = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
    output.target = target
    if shader:
        node = mat.node_tree.nodes.new(shader)
        mat.node_tree.links.new(node.outputs[0], output.inputs['Surface'])
    return mat, output


def legacy(name, color=(0.8, 0.8, 0.8, 1)):
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    group['bekkan_cycles_clay'] = 1
    interface = group.interface.new_socket(name='BSDF', in_out='OUTPUT', socket_type='NodeSocketShader')
    shader = group.nodes.new('ShaderNodeBsdfDiffuse')
    shader.inputs['Color'].default_value = color
    output = group.nodes.new('NodeGroupOutput')
    output.location = (240, 0)
    group.links.new(shader.outputs[0], output.inputs[interface.identifier])
    return group


def instance(mat, output, group):
    node = mat.node_tree.nodes.new('ShaderNodeGroup')
    node.node_tree = group
    mat.node_tree.links.new(node.outputs['BSDF'], output.inputs['Surface'])
    return node


def check_group(group):
    sockets = [s for s in group.interface.items_tree if s.item_type == 'SOCKET']
    assert [(s.name, s.socket_type) for s in sockets if s.in_out == 'INPUT'] == [
        ('Normal', 'NodeSocketVector'), ('Value', 'NodeSocketFloat')]
    assert [s.name for s in sockets if s.in_out == 'OUTPUT'] == ['BSDF', 'Transparent BSDF']
    value = next(s for s in sockets if s.name == 'Value')
    normal = next(s for s in sockets if s.name == 'Normal')
    assert abs(value.default_value - 0.8) < 1e-6 and value.min_value == 0 and value.max_value == 1
    assert normal.hide_value
    shader = next(n for n in group.nodes if n.type == 'BSDF_DIFFUSE')
    assert shader.inputs['Normal'].links[0].from_socket.identifier == normal.identifier
    assert shader.inputs['Color'].links[0].from_socket.identifier == value.identifier
    transparent = next(n for n in group.nodes if n.type == 'BSDF_TRANSPARENT')
    assert tuple(transparent.inputs['Color'].default_value) == (1, 1, 1, 1)
    output = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
    assert output.inputs['BSDF'].links[0].from_node == shader
    assert output.inputs['Transparent BSDF'].links[0].from_node == transparent


# 旧共享组已用于多个材质；其输出标识和原外层连线必须保留。
group = legacy('Old shared clay')
old_identifier = next(iter(group.interface.items_tree)).identifier
mat_a, out_a = material('A')
cycles_a = mat_a.node_tree.nodes.new('ShaderNodeOutputMaterial')
cycles_a.target = 'CYCLES'
node_a = instance(mat_a, cycles_a, group)
mat_b, out_b = material('B')
cycles_b = mat_b.node_tree.nodes.new('ShaderNodeOutputMaterial')
cycles_b.target = 'CYCLES'
node_b = instance(mat_b, cycles_b, group)
original_links = list(mat_a.node_tree.links)
mat_c, out_c = material('Needs clay')
mat_d, out_d = material('Custom Cycles')
cycles_d = mat_d.node_tree.nodes.new('ShaderNodeOutputMaterial')
cycles_d.target = 'CYCLES'
custom = mat_d.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
mat_d.node_tree.links.new(custom.outputs[0], cycles_d.inputs['Surface'])
mat_e, out_e = material('Only Cycles', target='CYCLES')
assert tools.adapt_cycles_clay([mat_a, mat_b, mat_c, mat_d, mat_e]) == (3, 1, 1, 1)
check_group(group)
assert node_a.outputs['BSDF'].identifier == old_identifier
assert all(link in mat_a.node_tree.links.values() for link in original_links)
assert cycles_a.inputs['Surface'].links[0].from_node == node_a
assert cycles_b.inputs['Surface'].links[0].from_node == node_b
assert cycles_d.inputs['Surface'].links[0].from_node == custom
assert out_e.target == 'CYCLES'
assert node_a.inputs['Value'].default_value == node_b.inputs['Value'].default_value
assert abs(node_a.inputs['Value'].default_value - 0.8) < 1e-6
before = (len(group.nodes), len(group.links), len(group.interface.items_tree), len(mat_c.node_tree.nodes))
assert tools.adapt_cycles_clay([mat_a, mat_b, mat_c, mat_d, mat_e]) == (3, 0, 1, 1)
assert before == (len(group.nodes), len(group.links), len(group.interface.items_tree), len(mat_c.node_tree.nodes))
node_a.inputs['Value'].default_value = 0.3
assert tools.adapt_cycles_clay([mat_a, mat_b]) == (1, 0, 1, 0)
assert abs(node_a.inputs['Value'].default_value - 0.3) < 1e-6
geometry = mat_b.node_tree.nodes.new('ShaderNodeNewGeometry')
mat_b.node_tree.links.new(geometry.outputs['Normal'], node_b.inputs['Normal'])
assert not tools._is_default_cycles_clay(cycles_b)
mat_b.node_tree.links.remove(node_b.inputs['Normal'].links[0])
assert tools._is_default_cycles_clay(cycles_b)

# 自定义灰度、彩色、已连接 Color/Normal，以及非 Diffuse 的旧组不重置。
gray = legacy('Edited gray', (0.4, 0.4, 0.4, 1))
gray_mat, gray_out = material('Edited gray user', target='CYCLES', shader=None)
gray_node = instance(gray_mat, gray_out, gray)
tools._extend_cycles_clay_group(gray)
assert abs(gray_node.inputs['Value'].default_value - 0.4) < 1e-6
assert not tools._is_default_cycles_clay(gray_out)
colored = legacy('Edited color', (0.2, 0.4, 0.6, 1))
colored_diffuse = next(n for n in colored.nodes if n.type == 'BSDF_DIFFUSE')
old_color = tuple(colored_diffuse.inputs['Color'].default_value)
tools._extend_cycles_clay_group(colored)
assert not colored_diffuse.inputs['Color'].is_linked
assert tuple(colored_diffuse.inputs['Color'].default_value) == old_color
linked = legacy('Edited links')
linked_diffuse = next(n for n in linked.nodes if n.type == 'BSDF_DIFFUSE')
rgb = linked.nodes.new('ShaderNodeRGB')
geom = linked.nodes.new('ShaderNodeNewGeometry')
linked.links.new(rgb.outputs[0], linked_diffuse.inputs['Color'])
linked.links.new(geom.outputs['Normal'], linked_diffuse.inputs['Normal'])
tools._extend_cycles_clay_group(linked)
assert linked_diffuse.inputs['Color'].links[0].from_node == rgb
assert linked_diffuse.inputs['Normal'].links[0].from_node == geom
custom_group = legacy('Custom structure')
custom_output = next(n for n in custom_group.nodes if n.type == 'GROUP_OUTPUT')
custom_shader = custom_group.nodes.new('ShaderNodeBsdfPrincipled')
custom_group.links.new(custom_shader.outputs[0], custom_output.inputs['BSDF'])
custom_counts = (len(custom_group.nodes), len(custom_group.interface.items_tree))
assert not tools._extend_cycles_clay_group(custom_group)
assert (len(custom_group.nodes), len(custom_group.interface.items_tree)) == custom_counts

# 单独验证全新节点组的构建分支，同名无关组不复用。
marked = [g for g in bpy.data.node_groups if g.get('bekkan_cycles_clay') == 1]
for existing_group in marked:
    del existing_group['bekkan_cycles_clay']
new_group = tools._cycles_clay_group()
check_group(new_group)
for existing_group in marked:
    existing_group['bekkan_cycles_clay'] = 1

fresh = bpy.data.node_groups.new('Unrelated Cy白膜适配', 'ShaderNodeTree')
fresh.interface.new_socket(name='BSDF', in_out='OUTPUT', socket_type='NodeSocketShader')
assert tools._cycles_clay_group() != fresh
assert len(fresh.interface.items_tree) == 1

def world_fixture(name, target='ALL'):
    world = bpy.data.worlds.new(name)
    if world.node_tree is None:
        world.use_nodes = True
    output = next(n for n in world.node_tree.nodes if n.type == 'OUTPUT_WORLD')
    output.target = target
    return world, output


world_a, world_out_a = world_fixture('World A sky')
background = next(n for n in world_a.node_tree.nodes if n.type == 'BACKGROUND')
sky = world_a.node_tree.nodes.new('ShaderNodeTexSky')
world_a.node_tree.links.new(sky.outputs['Color'], background.inputs['Color'])
old_links = list(world_a.node_tree.links)
world_b, world_out_b = world_fixture('World B empty Cycles')
world_cycles_b = world_b.node_tree.nodes.new('ShaderNodeOutputWorld')
world_cycles_b.target = 'CYCLES'
world_c, world_out_c = world_fixture('World C existing Cycles')
world_cycles_c = world_c.node_tree.nodes.new('ShaderNodeOutputWorld')
world_cycles_c.target = 'CYCLES'
original_bg = next(n for n in world_c.node_tree.nodes if n.type == 'BACKGROUND')
world_c.node_tree.links.new(original_bg.outputs[0], world_cycles_c.inputs['Surface'])
world_d, world_out_d = world_fixture('World D only Cycles', target='CYCLES')
world_e, world_out_e = world_fixture('World E volume Cycles')
volume_output = world_e.node_tree.nodes.new('ShaderNodeOutputWorld')
volume_output.target = 'CYCLES'
volume = world_e.node_tree.nodes.new('ShaderNodeVolumePrincipled')
world_e.node_tree.links.new(volume.outputs[0], volume_output.inputs['Volume'])
worlds = [world_a, world_b, world_c, world_d, world_e]
assert tools.adapt_cycles_worlds(worlds) == (2, 2, 2, 1)
assert all(link in world_a.node_tree.links.values() for link in old_links)
assert background.inputs['Color'].links[0].from_node == sky
assert world_out_a.target == world_out_b.target == 'EEVEE'
assert world_out_d.target == 'CYCLES'
assert world_cycles_c.inputs['Surface'].links[0].from_node == original_bg
assert volume_output.inputs['Volume'].links[0].from_node == volume
assert not volume_output.inputs['Surface'].is_linked
world_sizes = [(len(w.node_tree.nodes), len(w.node_tree.links)) for w in worlds]
assert tools.adapt_cycles_worlds(worlds) == (2, 0, 2, 1)
assert world_sizes == [(len(w.node_tree.nodes), len(w.node_tree.links)) for w in worlds]
world_default_bg = world_cycles_b.inputs['Surface'].links[0].from_node
assert all(abs(a-b) < 1e-6 for a, b in zip(world_default_bg.inputs['Color'].default_value, (0.8, 0.8, 0.8, 1)))
assert world_default_bg.inputs['Strength'].default_value == 1
world_default_bg.inputs['Strength'].default_value = 0.3
assert tools.adapt_cycles_worlds([world_b]) == (0, 0, 1, 0)
assert abs(world_default_bg.inputs['Strength'].default_value - 0.3) < 1e-6
assert bpy.ops.material.cycles_clay_visn() == {'FINISHED'}

if '--render' in sys.argv:
    scene = bpy.context.scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
    sphere = bpy.context.object
    for polygon in sphere.data.polygons:
        polygon.use_smooth = True
    render_mat, render_out = material('Render clay', target='CYCLES', shader=None)
    sphere.data.materials.append(render_mat)
    render_group = legacy('Render legacy')
    render_node = instance(render_mat, render_out, render_group)
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
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_mode = 'RGBA'
    folder = ROOT / 'temp' / f'clay-render{bpy.app.version[0]}{bpy.app.version[1]}'
    folder.mkdir(parents=True, exist_ok=True)
    def render(name):
        scene.render.filepath = str(folder / (name + '.exr'))
        assert bpy.ops.render.render(write_still=True) == {'FINISHED'}
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels = list(image.pixels)
        bpy.data.images.remove(image)
        return pixels
    baseline = render('legacy')
    tools._extend_cycles_clay_group(render_group)
    current = render('extended')
    delta = max(abs(a-b) for a, b in zip(baseline, current))
    assert delta < 0.00001, ('natural normals changed', delta)
    render_node.inputs['Value'].default_value = 0.4
    darker = render('gray04')
    foreground = [i for i in range(0, len(current), 4) if current[i + 3] > 0.99]
    assert len(foreground) > 1000
    light_sum = sum(sum(current[i:i+3]) for i in foreground)
    dark_sum = sum(sum(darker[i:i+3]) for i in foreground)
    assert 0.48 < dark_sum / light_sum < 0.52, dark_sum / light_sum
    geometry = render_mat.node_tree.nodes.new('ShaderNodeNewGeometry')
    tilt = render_mat.node_tree.nodes.new('ShaderNodeVectorMath')
    tilt.operation = 'ADD'
    tilt.inputs[1].default_value = (0.8, 0, 0)
    render_mat.node_tree.links.new(geometry.outputs['Normal'], tilt.inputs[0])
    render_mat.node_tree.links.new(tilt.outputs[0], render_node.inputs['Normal'])
    tilted = render('normal')
    assert sum(abs(a-b) for a, b in zip(darker, tilted)) > 10
    render_mat.node_tree.links.new(render_node.outputs['Transparent BSDF'], render_out.inputs['Surface'])
    transparent = render('transparent')
    assert max(transparent[3::4]) < 1e-6
    # World 实际按引擎选择输出，Cycles 独立背景是线性 0.8。
    scene.world = world_a
    scene.render.film_transparent = False
    world_pixels = render('world-cycles')
    assert all(abs(v - 0.8) < 0.003 for v in world_pixels[:3]), world_pixels[:4]
    assert abs(world_pixels[3] - 1) < 1e-6
    print('CLAY_RENDER_OK', 'normal_delta', delta, 'gray_ratio', dark_sum / light_sum)

addon_utils.disable(ROOT.name, default_set=True)
print('CYCLES_CLAY_TEST_OK', bpy.app.version_string)
