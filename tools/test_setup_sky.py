"""隔离天空双背景回归：节点保护及 Cycles 相机/照明光线路由。"""
import json
import math
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_workspace_setup import setup, assert_sky_setup, world_signature

OUT = ROOT / 'temp' / ('setup-sky-' + str(bpy.app.version[1]))
OUT.mkdir(parents=True, exist_ok=True)


def report():
    return {'scene_actions': []}


def test_sources():
    source = bpy.data.worlds.new('Original constant world')
    background = next(n for n in source.node_tree.nodes if n.type == 'BACKGROUND')
    background.inputs['Strength'].default_value = 0.7
    signature = world_signature(source)
    result = report()
    world = setup.create_sky_world(source, result)
    assert world != source and world_signature(source) == signature
    assert math.isclose(background.inputs['Strength'].default_value, 0.7, rel_tol=1e-6)
    assert_sky_setup(world)
    assert sum(n.type == 'BACKGROUND' for n in world.node_tree.nodes) == 2
    assert '强度 3' in result['scene_actions'][0]['detail']
    assert '强度 0.1' in result['scene_actions'][0]['detail']
    # 强度已由节点驱动时，同样保留原世界输出。
    value = source.node_tree.nodes.new('ShaderNodeValue')
    source.node_tree.links.new(value.outputs[0], background.inputs['Strength'])
    signature = world_signature(source)
    result = report()
    world = setup.create_sky_world(source, result)
    assert_sky_setup(world, connected=False)
    assert world_signature(source) == signature
    assert '未自动覆盖' in result['scene_actions'][0]['detail']
    # 自定义 Mix Shader 输出不被天空替换，复制后的既有连线保持完整。
    original_mix = source.node_tree.nodes.new('ShaderNodeMixShader')
    output = next(n for n in source.node_tree.nodes if n.type == 'OUTPUT_WORLD')
    source.node_tree.links.new(background.outputs[0], original_mix.inputs[1])
    source.node_tree.links.new(original_mix.outputs[0], output.inputs['Surface'])
    signature = world_signature(source)
    world = setup.create_sky_world(source, report())
    assert_sky_setup(world, connected=False)
    assert world_signature(source) == signature
    assert world.node_tree.nodes[output.name].inputs['Surface'].links[0].from_node.name == original_mix.name
    print('PASS sky_source_copy_and_custom_environment_preservation')


def render_pixels(scene, filename):
    scene.render.filepath = str(OUT / filename)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    try:
        width, height = image.size
        pixels = list(image.pixels)
        center = ((height // 2) * width + width // 2) * 4
        corner = (2 * width + 2) * 4
        return {'surface': pixels[center:center + 3], 'background': pixels[corner:corner + 3]}
    finally:
        bpy.data.images.remove(image)


def test_ray_routing():
    scene = bpy.data.scenes.new('Sky ray routing')
    bpy.context.window.scene = scene
    scene.world = setup.create_sky_world(None, report())
    assert_sky_setup(scene.world)
    camera = bpy.data.objects.new('Test camera', bpy.data.cameras.new('Test camera'))
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 2)
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 4
    scene.camera = camera
    mesh = bpy.data.meshes.new('White diffuse plane')
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    plane = bpy.data.objects.new(mesh.name, mesh)
    scene.collection.objects.link(plane)
    material = bpy.data.materials.new('Pure diffuse')
    material.node_tree.nodes.clear()
    diffuse = material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(diffuse.outputs[0], output.inputs['Surface'])
    mesh.materials.append(material)
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    # 使用固定天空颜色来精确对比路由，隔离天空积分与采样噪声的影响。
    tree = scene.world.node_tree
    mix = next(n for n in tree.nodes if n.type == 'MIX_SHADER')
    lighting = mix.inputs[1].links[0].from_node
    for socket in (mix.inputs[1], mix.inputs[2]):
        background = socket.links[0].from_node
        tree.links.remove(background.inputs['Color'].links[0])
        background.inputs['Color'].default_value = (0.2, 0.2, 0.2, 1)
    split = render_pixels(scene, 'split.exr')
    output = next(n for n in tree.nodes if n.type == 'OUTPUT_WORLD')
    tree.links.new(lighting.outputs[0], output.inputs['Surface'])
    direct = render_pixels(scene, 'direct.exr')
    for a, b in zip(split['surface'], direct['surface']):
        assert math.isclose(a, b, rel_tol=0.01), (split, direct)
    for a, b in zip(split['background'], direct['background']):
        assert math.isclose(a / b, 1 / 30, rel_tol=0.001), (split, direct)
    assert min(split['surface']) > max(split['background']) * 20, split
    (OUT / 'ray-routing.json').write_text(json.dumps({'blender': bpy.app.version_string,
        'split': split, 'direct': direct}), encoding='utf-8')
    print('PASS sky_ray_routing_same_lighting_and_background_one_thirtieth', split, direct)


test_sources()
test_ray_routing()
print('PASS_SETUP_SKY', bpy.app.version_string)
