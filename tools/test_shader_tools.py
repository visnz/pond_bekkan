"""隔离后台测试：blender -b --factory-startup --python-exit-code 1 -P 本文件。"""
import importlib
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
tools = importlib.import_module(ROOT.name + '.core.shader_tools')


def example():
    material = bpy.data.materials.new('ShaderLayoutTest')
    tree = material.node_tree
    shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL')
    coordinate = tree.nodes.new('ShaderNodeTexCoord')
    mapping = tree.nodes.new('ShaderNodeMapping')
    bump = tree.nodes.new('ShaderNodeBump')
    images = [tree.nodes.new('ShaderNodeTexImage') for _ in range(4)]
    for node, name in zip(images, ('Color', 'Roughness', 'Height', 'Alpha')):
        node.name = name
    tree.links.new(coordinate.outputs['UV'], mapping.inputs['Vector'])
    for node in images:
        tree.links.new(mapping.outputs['Vector'], node.inputs['Vector'])
    tree.links.new(images[0].outputs['Color'], shader.inputs['Base Color'])
    tree.links.new(images[1].outputs['Color'], shader.inputs['Roughness'])
    tree.links.new(images[2].outputs['Color'], bump.inputs['Height'])
    tree.links.new(bump.outputs['Normal'], shader.inputs['Normal'])
    tree.links.new(images[3].outputs['Alpha'], shader.inputs['Alpha'])
    for i, node in enumerate(tree.nodes):
        node.location = ((i % 3) * 45, -30 * (i % 2))
    return material, images, output


def topology(tree):
    return {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
            for l in tree.links}


def check_layout(tree):
    for a, b in combinations(tree.nodes, 2):
        if a.parent != b.parent:
            continue
        aw, ah = tools._node_size(a, 1)
        bw, bh = tools._node_size(b, 1)
        x_overlap = min(a.location.x + aw, b.location.x + bw) - max(a.location.x, b.location.x)
        y_overlap = min(a.location.y, b.location.y) - max(a.location.y - ah, b.location.y - bh)
        assert x_overlap <= 0 or y_overlap <= 0, (a.name, b.name, 'overlap')
    for link in tree.links:
        if link.from_node.parent == link.to_node.parent:
            assert link.to_node.location.x >= link.from_node.location.x + tools._node_size(link.from_node, 1)[0]


addon.register()
try:
    material, images, output = example()
    tree = material.node_tree
    original_topology = topology(tree)
    original_output = output.location.copy()
    selection = {n.name: n.select for n in tree.nodes}
    default_roughness = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Roughness'].default_value
    assert tools.arrange_shader_tree(tree) == 9
    check_layout(tree)
    assert topology(tree) == original_topology and output.location == original_output
    assert {n.name: n.select for n in tree.nodes} == selection
    assert next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Roughness'].default_value == default_roughness
    positions = {n.name: tuple(n.location) for n in tree.nodes}
    tools.arrange_shader_tree(tree)
    assert positions == {n.name: tuple(n.location) for n in tree.nodes}, '重复排列应稳定'

    # 框架和备用节点：父级/链接不变，框架内也整理；不展开或修改引用节点组。
    frame = tree.nodes.new('NodeFrame')
    frame.label = 'Texture Sources'
    nested = tree.nodes.new('NodeFrame')
    nested.parent = frame
    for image in images:
        image.parent = nested
    spare = tree.nodes.new('ShaderNodeValue')
    group_tree = bpy.data.node_groups.new('UnchangedNestedShader', 'ShaderNodeTree')
    internal = group_tree.nodes.new('ShaderNodeValue')
    internal.location = (113, -217)
    group = tree.nodes.new('ShaderNodeGroup')
    group.node_tree = group_tree
    parent_before = {n: n.parent for n in tree.nodes}
    tools.arrange_shader_tree(tree)
    assert {n: n.parent for n in tree.nodes} == parent_before
    assert topology(tree) == original_topology
    assert tuple(internal.location) == (113, -217)
    check_layout(tree)

    # Shader Editor 材质上下文专用；禁用 World/Geometry/其他编辑器。
    space = SimpleNamespace(type='NODE_EDITOR', tree_type='ShaderNodeTree',
                            shader_type='OBJECT', id=material, edit_tree=tree)
    context = SimpleNamespace(space_data=space)
    assert tools.current_material_tree(context) == tree
    space.edit_tree = group_tree
    assert tools.current_material_tree(context) == group_tree
    space.shader_type = 'WORLD'
    assert tools.current_material_tree(context) is None
    space.shader_type, space.tree_type = 'OBJECT', 'GeometryNodeTree'
    assert tools.current_material_tree(context) is None
    space.type = 'VIEW_3D'
    assert tools.current_material_tree(context) is None

    # 只改选中贴图引用；共用图片去重，无图节点与其他类型忽略。
    for node in tree.nodes:
        node.select = False
    first = bpy.data.images.new('SharedSelectedImage', 1, 1)
    second = bpy.data.images.new('UnselectedImage', 1, 1)
    first.colorspace_settings.name = second.colorspace_settings.name = 'sRGB'
    images[0].image = images[1].image = first
    images[2].image = second
    images[0].select = images[1].select = images[3].select = True
    spare.select = True
    assert tools.selected_images_to_non_color(tree) == (1, 0, 0)
    assert first.colorspace_settings.name == 'Non-Color'
    assert second.colorspace_settings.name == 'sRGB'
    assert tools.selected_images_to_non_color(tree) == (0, 1, 0)
    for node in tree.nodes:
        node.select = False
    assert tools.selected_images_to_non_color(tree) == (0, 0, 0)

    # 循环图取消前不改变任何位置。
    cycle = bpy.data.node_groups.new('CycleGuard', 'ShaderNodeTree')
    a, b = cycle.nodes.new('ShaderNodeMath'), cycle.nodes.new('ShaderNodeMath')
    cycle.links.new(a.outputs[0], b.inputs[0])
    cycle.links.new(b.outputs[0], a.inputs[0])
    before = {n.name: tuple(n.location) for n in cycle.nodes}
    try:
        tools.arrange_shader_tree(cycle)
    except ValueError:
        pass
    else:
        raise AssertionError('循环图应给出可理解的取消结果')
    assert before == {n.name: tuple(n.location) for n in cycle.nodes}

    icons = bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items
    assert 'NODETREE' in icons and 'IMAGE_DATA' in icons
    for mode in ('BEKKAN', 'POND', 'BEKKAN'):
        addon.ui.apply_mode(mode)
        panel = bpy.types.Panel.bl_rna_get_subclass_py('BEKKAN_PT_shader_scripts')
        assert (panel is not None) == (mode == 'BEKKAN')
        if panel:
            assert panel.bl_space_type == 'NODE_EDITOR'
    print('PASS_SHADER_TOOLS', bpy.app.version_string,
          '9-node reference, no overlap, left-to-right links, frames, spare nodes, nested group preservation, idempotence, context, selected Non-Color, cycles, UI registration')
finally:
    addon.unregister()
