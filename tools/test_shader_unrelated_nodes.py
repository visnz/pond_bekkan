"""隔离测试：blender -b --factory-startup --python-exit-code 1 -P 本文件。"""
import importlib
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
tools = importlib.import_module(ROOT.name + '.core.shader_tools')


def example():
    material = bpy.data.materials.new('UnrelatedNodeTest')
    tree = material.node_tree
    shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL')
    shared = tree.nodes.new('ShaderNodeValue')
    shared.name = 'Shared source'
    shared.outputs[0].default_value = 0.37
    tree.links.new(shared.outputs[0], shader.inputs['Roughness'])
    orphan = [tree.nodes.new(kind) for kind in
              ('ShaderNodeValue', 'ShaderNodeMath', 'ShaderNodeMath', 'NodeReroute')]
    for index, node in enumerate(orphan):
        node.name = 'Unused ' + str(index + 1)
        node.select = False
    for source, target in zip(orphan, orphan[1:]):
        tree.links.new(source.outputs[0], target.inputs[0])
    tree.links.new(shared.outputs[0], orphan[1].inputs[1])
    return material, shader, output, shared, orphan


def selected(tree):
    return {node.name for node in tree.nodes if node.select}


def signature(tree, names=None):
    nodes = {node.name: (node.bl_idname, tuple(node.location), node.parent.name if node.parent else None)
             for node in tree.nodes if names is None or node.name in names}
    links = {(link.from_node.name, link.from_socket.identifier,
              link.to_node.name, link.to_socket.identifier)
             for link in tree.links if names is None or
             (link.from_node.name in names and link.to_node.name in names)}
    return nodes, links


def test_four_node_branch_and_delete():
    material, shader, output, shared, orphan = example()
    tree = material.node_tree
    names = {n.name for n in orphan}
    before = signature(tree)
    live_names = {shader.name, output.name, shared.name}
    live = signature(tree, live_names)
    tree.nodes.active = shader
    assert tools.select_nodes_unrelated_to_output(tree) == 4
    assert selected(tree) == names, selected(tree)
    assert tree.nodes.active in orphan and signature(tree) == before
    assert shared.outputs[0].default_value > 0.36
    for node in list(tree.nodes):
        if node.select:
            tree.nodes.remove(node)
    assert signature(tree) == live, '删除候选后有效输出分支应完整保留'
    for node in tree.nodes:
        node.select = True
    assert tools.select_nodes_unrelated_to_output(tree) == 0
    assert selected(tree) == set() and tree.nodes.active is None


def test_multiple_outputs_and_sockets():
    material, shader, output, shared, orphan = example()
    tree = material.node_tree
    output.target = 'CYCLES'
    volume = tree.nodes.new('ShaderNodeVolumePrincipled')
    displacement = tree.nodes.new('ShaderNodeDisplacement')
    tree.links.new(volume.outputs[0], output.inputs['Volume'])
    tree.links.new(displacement.outputs[0], output.inputs['Displacement'])
    for target in ('CYCLES', 'EEVEE', 'ALL'):
        other = tree.nodes.new('ShaderNodeOutputMaterial')
        other.target = target
        emission = tree.nodes.new('ShaderNodeEmission')
        tree.links.new(emission.outputs[0], other.inputs['Surface'])
    assert any(not n.is_active_output for n in tree.nodes if n.type == 'OUTPUT_MATERIAL')
    aov = tree.nodes.new('ShaderNodeOutputAOV')
    aov.aov_name = 'Test AOV'
    aov_source = tree.nodes.new('ShaderNodeRGB')
    tree.links.new(aov_source.outputs[0], aov.inputs['Color'])
    assert tools.select_nodes_unrelated_to_output(tree) == 4
    assert selected(tree) == {n.name for n in orphan}


def test_groups_and_frames():
    material, shader, output, shared, orphan = example()
    tree = material.node_tree
    group_tree = bpy.data.node_groups.new('ShaderSelectionGroup', 'ShaderNodeTree')
    group_tree.interface.new_socket(name='Value', in_out='OUTPUT', socket_type='NodeSocketFloat')
    internal = group_tree.nodes.new('ShaderNodeValue')
    unused = group_tree.nodes.new('ShaderNodeMath')
    for _ in range(2):
        group_output = group_tree.nodes.new('NodeGroupOutput')
        group_tree.links.new(internal.outputs[0], group_output.inputs[0])
    group = tree.nodes.new('ShaderNodeGroup')
    group.node_tree = group_tree
    tree.links.new(group.outputs[0], shader.inputs['Metallic'])
    frame = tree.nodes.new('NodeFrame')
    nested = tree.nodes.new('NodeFrame')
    nested.parent = frame
    shader.parent = frame
    orphan[0].parent = nested
    group_state = signature(group_tree), selected(group_tree)
    assert tools.select_nodes_unrelated_to_output(tree) == 4
    assert selected(tree) == {n.name for n in orphan}
    assert (signature(group_tree), selected(group_tree)) == group_state
    assert not frame.select and not nested.select and not group.select
    outer_selection = selected(tree)
    assert tools.select_nodes_unrelated_to_output(group_tree) == 1
    assert selected(group_tree) == {unused.name}
    assert selected(tree) == outer_selection


def test_missing_output_preserves_selection():
    tree = bpy.data.node_groups.new('NoOutput', 'ShaderNodeTree')
    node = tree.nodes.new('ShaderNodeValue')
    other = tree.nodes.new('ShaderNodeMath')
    node.select, other.select = True, False
    tree.nodes.active = node
    before = signature(tree), selected(tree)
    try:
        tools.select_nodes_unrelated_to_output(tree)
    except ValueError as error:
        assert '没有输出节点' in str(error)
    else:
        raise AssertionError('无输出时必须取消')
    assert (signature(tree), selected(tree)) == before and tree.nodes.active == node


def test_cycles_and_muted_branches():
    material, shader, output, shared, orphan = example()
    tree = material.node_tree
    tree.links.new(orphan[2].outputs[0], orphan[1].inputs[0])
    assert tools.select_nodes_unrelated_to_output(tree) == 4
    # 环一旦通向输出，整个依赖环都保留；不会因为 mute 就剪掉输入。
    tree.links.new(orphan[2].outputs[0], shader.inputs['Metallic'])
    orphan[2].mute = True
    assert tools.select_nodes_unrelated_to_output(tree) == 2
    assert selected(tree) == {orphan[0].name, orphan[3].name}


def add_driver(destination, source_id, path, id_type='NODETREE'):
    curve = destination.driver_add('default_value')
    driver = curve.driver
    driver.type = 'SCRIPTED'
    variable = driver.variables.new()
    variable.name = 'source'
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id_type = id_type
    variable.targets[0].id = source_id
    variable.targets[0].data_path = path
    driver.expression = 'source'
    return curve


def test_driver_dependencies():
    material, shader, output, shared, orphan = example()
    tree = material.node_tree
    source = tree.nodes.new('ShaderNodeValue')
    source.name = 'Driver "quoted" \\ source'
    source.outputs[0].default_value = 0.28
    add_driver(shader.inputs['Metallic'], tree, source.outputs[0].path_from_id('default_value'))
    # 另一个材质的内嵌节点树驱动，引用本树悬空链的中段：保护被引用节点及其上游。
    external = bpy.data.materials.new('ExternalDriverOwner')
    external_shader = next(n for n in external.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    add_driver(external_shader.inputs['Roughness'], material,
               'node_tree.' + orphan[2].inputs[0].path_from_id('default_value'), 'MATERIAL')
    assert tools.select_nodes_unrelated_to_output(tree) == 1
    assert selected(tree) == {orphan[3].name}
    external_shader.inputs['Roughness'].driver_remove('default_value')
    # 物体驱动同样可能引用节点，不能只扫描 shader tree 的 animation_data。
    obj = bpy.data.objects.new('ExternalObjectDriver', None)
    curve = obj.driver_add('location', 0)
    variable = curve.driver.variables.new()
    variable.type = 'SINGLE_PROP'
    variable.targets[0].id_type = 'NODETREE'
    variable.targets[0].id = tree
    variable.targets[0].data_path = orphan[1].inputs[0].path_from_id('default_value')
    assert tools.select_nodes_unrelated_to_output(tree) == 2
    assert selected(tree) == {orphan[2].name, orphan[3].name}
    # 数字下标依赖节点顺序，删除任意节点可能导致索引改变，应全部保留。
    variable.targets[0].data_path = 'nodes[0].inputs[0].default_value'
    assert tools.select_nodes_unrelated_to_output(tree) == 0


def run():
    tools.register()
    try:
        for test in (test_four_node_branch_and_delete, test_multiple_outputs_and_sockets,
                     test_groups_and_frames, test_missing_output_preserves_selection,
                     test_cycles_and_muted_branches, test_driver_dependencies):
            test()
            print('PASS', test.__name__)
        icons = bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items
        assert 'RESTRICT_SELECT_OFF' in icons
        assert bpy.ops.node.select_unrelated_shader_nodes_visn.get_rna_type()
        print('PASS_SHADER_UNRELATED_NODES', bpy.app.version_string)
    finally:
        tools.unregister()


if __name__ == '__main__':
    run()
