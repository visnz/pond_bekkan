"""一次性 GUI：几何编辑器侧栏、独立入口、Panel 及单步撤销/重做。"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
ui = importlib.import_module(ROOT.name + '.ui')
tools = importlib.import_module(ROOT.name + '.core.geometry_tools')
panel = importlib.import_module(ROOT.name + '.ui.bekkan.geometry_panel')
ui.apply_mode('BEKKAN')
state = {'step': 0, 'draws': 0, 'draw_error': None}
panel.unregister()
original_draw = panel.BEKKAN_PT_geometry_scripts.draw
def draw(self, context):
    try:
        original_draw(self, context)
        state['draws'] += 1
    except Exception:
        state['draw_error'] = traceback.format_exc()
        raise
panel.BEKKAN_PT_geometry_scripts.draw = draw
panel.register()

source = bpy.data.node_groups.new('落雪演示', 'GeometryNodeTree')
g = source.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
source.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
snow = source.interface.new_panel(name='落雪')
depth = source.interface.new_socket(name='厚度', in_out='INPUT', socket_type='NodeSocketFloat', parent=snow)
depth.default_value = 1
depth.subtype = 'DISTANCE'
direction = source.interface.new_panel(name='落雪方向', default_closed=True)
source.interface.move_to_parent(direction, snow, 0)
source.interface.new_socket(name='方向', in_out='INPUT', socket_type='NodeSocketVector', parent=direction)
wind = source.interface.new_panel(name='风吹落雪')
source.interface.new_socket(name='随机种子', in_out='INPUT', socket_type='NodeSocketInt', parent=wind)
sg = source.nodes.new('NodeGroupInput')
so = source.nodes.new('NodeGroupOutput')
transform = source.nodes.new('GeometryNodeTransform')
source.links.new(sg.outputs[g.identifier], transform.inputs['Geometry'])
source.links.new(sg.outputs[depth.identifier], transform.inputs['Translation'])
source.links.new(transform.outputs['Geometry'], so.inputs['Geometry'])
parent = bpy.data.node_groups.new('封装入口演示', 'GeometryNodeTree')
parent.is_modifier = True
parent.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
parent.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
gi = parent.nodes.new('NodeGroupInput')
gi.location = (-400, 400)
node = parent.nodes.new('GeometryNodeGroup')
node.node_tree = source
node.name = 'SelectedGroup'
node.location = (0, 400)
node.inputs[depth.identifier].default_value = 3.5
go = parent.nodes.new('NodeGroupOutput')
go.location = (400, 400)
parent.links.new(gi.outputs['Geometry'], node.inputs['Geometry'])
parent.links.new(node.outputs['Geometry'], go.inputs['Geometry'])
for n in parent.nodes:
    n.select = n == node
parent.nodes.active = node
bpy.data.objects['Cube'].modifiers.new('演示', 'NODES').node_group = parent
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.type = 'NODE_EDITOR'
space = area.spaces.active
space.tree_type = 'GeometryNodeTree'
space.pin = True
space.node_tree = parent
space.show_region_ui = True
for a in window.screen.areas:
    if a.type == 'PROPERTIES':
        a.spaces.active.context = 'MODIFIER'
bpy.context.preferences.view.show_splash = False
directory = ROOT / 'temp' / f'geometry-ui{bpy.app.version[0]}{bpy.app.version[1]}'
directory.mkdir(parents=True, exist_ok=True)


def signature():
    tree = bpy.data.node_groups['封装入口演示']
    return ([(i.name, i.item_type, i.parent.name if i.parent else None) for i in tree.interface.items_tree],
            sorted(n.name for n in tree.nodes),
            sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links))


def finish(error=None):
    result = {'ok': error is None and state['draw_error'] is None,
              'blender': bpy.app.version_string, **state, 'error': error}
    (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0 if result['ok'] else 1)


def advance():
    try:
        with bpy.context.temp_override(window=window, area=area,
                region=next(r for r in area.regions if r.type == 'WINDOW')):
            step = state['step']
            if step == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                assert tools.current_geometry_tree(bpy.context) == bpy.data.node_groups['封装入口演示']
                state['before'] = signature()
                bpy.ops.ed.undo_push(message='Before expose')
            elif step == 1:
                assert state['draws'] > 0
                bpy.ops.screen.screenshot(filepath=str(directory / 'before.png'))
                assert bpy.ops.node.expose_group_inputs_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                state['after'] = signature()
                assert len(state['after'][0]) == 8
                bpy.ops.node.view_all()
            elif step == 2:
                bpy.ops.screen.screenshot(filepath=str(directory / 'after.png'))
                bpy.ops.ed.undo()
            elif step == 3:
                assert signature() == state['before']
                bpy.ops.ed.redo()
            elif step == 4:
                assert signature() == state['after']
                bpy.ops.screen.screenshot(filepath=str(directory / 'redo.png'))
                assert bpy.ops.node.expose_group_inputs_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert signature() == state['after']
                space.tree_type = 'ShaderNodeTree'
                assert tools.current_geometry_tree(bpy.context) is None
                assert not panel.BEKKAN_PT_geometry_scripts.poll(bpy.context)
            elif step == 5:
                finish()
        state['step'] += 1
        area.tag_redraw()
        return 0.8
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1.5)
