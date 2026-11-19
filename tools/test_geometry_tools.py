"""隔离后台：接口/嵌套 Panel、默认值、共享组用户、实际输出、重复及失败恢复。"""
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
tools = importlib.import_module(ROOT.name + '.core.geometry_tools')
ui = importlib.import_module(ROOT.name + '.ui')


def inputs(tree):
    return [item for item in tree.interface.items_tree if item.item_type == 'SOCKET' and item.in_out == 'INPUT']


def panels(tree):
    return [item for item in tree.interface.items_tree if item.item_type == 'PANEL']


def bbox(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [tuple(corner) for corner in evaluated.bound_box]


source = bpy.data.node_groups.new('Source', 'GeometryNodeTree')
geometry = source.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
source.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
snow = source.interface.new_panel(name='落雪', description='Snow settings', default_closed=True)
direction = source.interface.new_panel(name='落雪方向', default_closed=False)
source.interface.move_to_parent(direction, snow, 0)
wind = source.interface.new_panel(name='风吹落雪', default_closed=True)
depth = source.interface.new_socket(name='厚度', in_out='INPUT', socket_type='NodeSocketFloat', parent=snow)
depth.subtype = 'DISTANCE'
depth.min_value = -10
depth.max_value = 100
depth.description = 'Snow depth'
depth.default_value = 1
direction_socket = source.interface.new_socket(name='方向', in_out='INPUT', socket_type='NodeSocketVector', parent=direction)
seed = source.interface.new_socket(name='随机种子', in_out='INPUT', socket_type='NodeSocketInt', parent=wind)
reference = source.interface.new_panel(name='参考材质')
object_socket = source.interface.new_socket(name='对象', in_out='INPUT', socket_type='NodeSocketObject', parent=reference)
material = source.interface.new_socket(name='材质', in_out='INPUT', socket_type='NodeSocketMaterial', parent=reference)
rotation = source.interface.new_socket(name='旋转', in_out='INPUT', socket_type='NodeSocketRotation', parent=direction)
animated = source.interface.new_socket(name='动画参数', in_out='INPUT', socket_type='NodeSocketFloat', parent=wind)
keyframed = source.interface.new_socket(name='关键帧参数', in_out='INPUT', socket_type='NodeSocketFloat', parent=wind)
gi = source.nodes.new('NodeGroupInput')
go = source.nodes.new('NodeGroupOutput')
transform = source.nodes.new('GeometryNodeTransform')
source.links.new(gi.outputs[geometry.identifier], transform.inputs['Geometry'])
source.links.new(gi.outputs[depth.identifier], transform.inputs['Translation'])
source.links.new(transform.outputs['Geometry'], go.inputs['Geometry'])

parent = bpy.data.node_groups.new('Parent', 'GeometryNodeTree')
parent.is_modifier = True
parent.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
parent.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
old_depth = parent.interface.new_socket(name='厚度', in_out='INPUT', socket_type='NodeSocketFloat')
old_depth.default_value = 12
old_gi = parent.nodes.new('NodeGroupInput')
old_gi.location = (-340, 0)
old_go = parent.nodes.new('NodeGroupOutput')
node = parent.nodes.new('GeometryNodeGroup')
node.node_tree = source
node.inputs[depth.identifier].default_value = 3.5
node.inputs[direction_socket.identifier].default_value = (0.2, 0.4, 0.6)
node.inputs[seed.identifier].default_value = 42
node.inputs[object_socket.identifier].default_value = bpy.data.objects['Cube']
node.inputs[material.identifier].default_value = bpy.data.materials.new('ReferenceMaterial')
node.inputs[rotation.identifier].default_value = (0.1, 0.2, 0.3)
driver = node.inputs[animated.identifier].driver_add('default_value')
driver.driver.expression = '2'
node.inputs[keyframed.identifier].default_value = 0.1
node.inputs[keyframed.identifier].keyframe_insert('default_value', frame=1)
node.inputs[keyframed.identifier].default_value = 0.7
node.inputs[keyframed.identifier].keyframe_insert('default_value', frame=8)
parent.links.new(old_gi.outputs['Geometry'], node.inputs[geometry.identifier])
parent.links.new(node.outputs['Geometry'], old_go.inputs['Geometry'])
for n in parent.nodes:
    n.select = n == node
parent.nodes.active = node
outer = bpy.data.node_groups.new('Outer', 'GeometryNodeTree')
user = outer.nodes.new('GeometryNodeGroup')
user.node_tree = parent
cube = bpy.data.objects['Cube']
mod = cube.modifiers.new('Geometry Test', 'NODES')
mod.node_group = parent
second = cube.copy()
second.data = cube.data
bpy.context.scene.collection.objects.link(second)
before_bbox = bbox(cube)
before_source = [(item.name, item.identifier) for item in source.interface.items_tree]
before_links = {(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in parent.links}
source_default = node.inputs[depth.identifier].default_value
result = tools.expose_group_inputs(parent, [node])
print('EXPOSED',result['sockets'],result['panels'],result['skipped'])
assert result['sockets'] == 6 and result['panels'] == 4 and result['skipped'] == 2
assert [(item.name, item.identifier) for item in source.interface.items_tree] == before_source
assert all(any((link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) == old for link in parent.links) for old in before_links)
assert len(parent.links) == len(before_links) + 6
ordered_sources = [item.identifier for item in inputs(source)
                   if item.identifier not in (geometry.identifier, animated.identifier, keyframed.identifier)]
exposed_order = []
for item in inputs(parent):
    for link in parent.links:
        if link.from_node == result['entry'] and link.from_socket.identifier == item.identifier:
            exposed_order.append(link.to_socket.identifier)
assert exposed_order == ordered_sources
assert node.select and parent.nodes.active == node
assert old_depth.default_value == 12
assert node.inputs[animated.identifier].is_linked is False
assert node.inputs[keyframed.identifier].is_linked is False
assert bbox(cube) == before_bbox
assert len([n for n in parent.nodes if n.bl_idname == 'NodeGroupInput']) == 2
assert result['entry'].location.y < old_gi.location.y
assert next(p for p in panels(parent) if p.name == '落雪').default_closed
assert next(p for p in panels(parent) if p.name == '落雪方向').parent.name == '落雪'
new_depth = next(s for s in inputs(parent) if s.name == '厚度 (2)')
assert new_depth.parent.name == '落雪' and new_depth.subtype == 'DISTANCE'
assert new_depth.min_value == -10 and new_depth.max_value == 100 and new_depth.description == 'Snow depth'
assert new_depth.default_value == source_default == user.inputs[new_depth.identifier].default_value
assert getattr(mod.properties.inputs, new_depth.identifier).value == source_default
assert getattr(second.modifiers['Geometry Test'].properties.inputs, new_depth.identifier).value == source_default
assert next(s for s in inputs(parent) if s.name == '对象').default_value == cube
assert tuple(next(s for s in inputs(parent) if s.name == '方向').default_value) == tuple(node.inputs[direction_socket.identifier].default_value)
count = len(parent.interface.items_tree), len(parent.nodes), len(parent.links)
again = tools.expose_group_inputs(parent, [node])
assert again['sockets'] == 0 and count == (len(parent.interface.items_tree), len(parent.nodes), len(parent.links))

# 新选择的多个组仍汇入同一个脚本入口，重复名称分别暴露。
node2 = parent.nodes.new('GeometryNodeGroup')
node2.node_tree = source
parent.links.new(old_gi.outputs['Geometry'], node2.inputs[geometry.identifier])
multiple = tools.expose_group_inputs(parent, [node, node2])
assert multiple['sockets'] == 8 and multiple['entry'] == result['entry']
assert next(s for s in inputs(parent) if s.name == '厚度 (3)').parent.name == '落雪'

# 发生中途错误时删除新增接口、面板、连线和用户属性，保留旧图。
failure = bpy.data.node_groups.new('Failure', 'GeometryNodeTree')
failure_node = failure.nodes.new('GeometryNodeGroup')
failure_node.node_tree = source
failure_user = outer.nodes.new('GeometryNodeGroup')
failure_user.node_tree = failure
failure_mod = cube.modifiers.new('Failure Test', 'NODES')
failure_mod.node_group = failure
original_value = tools._value
counter = [0]
def bad_value(socket):
    counter[0] += 1
    return object() if counter[0] == 3 else original_value(socket)
tools._value = bad_value
keys = set(failure_mod.properties.inputs.keys())
try:
    tools.expose_group_inputs(failure, [failure_node])
except Exception:
    pass
else:
    raise AssertionError('Injected failure was ignored')
finally:
    tools._value = original_value
assert len(failure.interface.items_tree) == 0 and len(failure.nodes) == 1 and len(failure.links) == 0
assert set(failure_mod.properties.inputs.keys()) == keys and len(failure_user.inputs) == 0

# 常见输入类型及可开关 Panel、Menu 下拉选项。
typed = bpy.data.node_groups.new('Typed', 'GeometryNodeTree')
toggle_panel = typed.interface.new_panel(name='可开关分组', default_closed=True)
toggle = typed.interface.new_socket(name='启用', in_out='INPUT', socket_type='NodeSocketBool', parent=toggle_panel)
toggle.is_panel_toggle = True
definitions = [('Color', 'NodeSocketColor'), ('Text', 'NodeSocketString'),
               ('Collection', 'NodeSocketCollection'), ('Image', 'NodeSocketImage'),
               ('Matrix', 'NodeSocketMatrix'), ('Bundle', 'NodeSocketBundle'),
               ('EmptyMenu', 'NodeSocketMenu')]
for name, kind in definitions:
    typed.interface.new_socket(name=name, in_out='INPUT', socket_type=kind, parent=toggle_panel)
typed_parent = bpy.data.node_groups.new('TypedParent', 'GeometryNodeTree')
typed_node = typed_parent.nodes.new('GeometryNodeGroup')
typed_node.node_tree = typed
typed_node.inputs['Color'].default_value = (0.2, 0.3, 0.4, 0.5)
typed_node.inputs['Text'].default_value = 'hello'
typed_node.inputs['Collection'].default_value = bpy.context.scene.collection.children[0]
typed_node.inputs['Image'].default_value = bpy.data.images.new('TestReference', width=2, height=2)
typed_result = tools.expose_group_inputs(typed_parent, [typed_node])
assert typed_result['sockets'] == 8
assert next(s for s in inputs(typed_parent) if s.name == toggle.name).is_panel_toggle
assert next(s for s in inputs(typed_parent) if s.name == 'Text').default_value == 'hello'

menu_tree = bpy.data.node_groups.new('MenuGroup', 'GeometryNodeTree')
menu_socket = menu_tree.interface.new_socket(name='选项', in_out='INPUT', socket_type='NodeSocketMenu')
menu_input = menu_tree.nodes.new('NodeGroupInput')
menu_switch = menu_tree.nodes.new('GeometryNodeMenuSwitch')
menu_switch.data_type = 'FLOAT'
menu_switch.enum_items.new('额外选项')
menu_tree.links.new(menu_input.outputs[menu_socket.identifier], menu_switch.inputs['Menu'])
option = menu_switch.enum_items[-1].name
menu_parent = bpy.data.node_groups.new('MenuParent', 'GeometryNodeTree')
menu_node = menu_parent.nodes.new('GeometryNodeGroup')
menu_node.node_tree = menu_tree
menu_node.inputs[menu_socket.identifier].default_value = option
menu_result = tools.expose_group_inputs(menu_parent, [menu_node])
assert menu_result['sockets'] == 1
assert inputs(menu_parent)[0].default_value == option

ui.apply_mode('BEKKAN')
assert hasattr(bpy.types, 'BEKKAN_PT_geometry_scripts')
ui.apply_mode('POND')
assert not hasattr(bpy.types, 'BEKKAN_PT_geometry_scripts')
addon_utils.disable(ROOT.name, default_set=True)
assert addon_utils.enable(ROOT.name, default_set=True) is not None
addon_utils.disable(ROOT.name, default_set=True)
print('GEOMETRY_TOOLS_TEST_OK', bpy.app.version_string)
