"""隔离 GUI：Shader 材质/World 白膜入口、旧组升级和原生撤销重做。"""
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
tools = importlib.import_module(ROOT.name + '.core.texture')
panels = importlib.import_module(ROOT.name + '.ui.bekkan.shader_panel')
ui.apply_mode('BEKKAN')
panels.unregister()
original_draw = panels.BEKKAN_PT_shader_scripts.draw
state = {'step': 0, 'draws': 0, 'draw_error': None}


def draw(self, context):
    try:
        original_draw(self, context)
        state['draws'] += 1
    except Exception:
        state['draw_error'] = traceback.format_exc()
        raise


panels.BEKKAN_PT_shader_scripts.draw = draw
panels.register()
group = bpy.data.node_groups.new('Cy白膜适配', 'ShaderNodeTree')
group['bekkan_cycles_clay'] = 1
group.interface.new_socket(name='BSDF', in_out='OUTPUT', socket_type='NodeSocketShader')
diffuse = group.nodes.new('ShaderNodeBsdfDiffuse')
output = group.nodes.new('NodeGroupOutput')
output.location = (240, 0)
group.links.new(diffuse.outputs[0], output.inputs['BSDF'])
material = bpy.data.materials.new('Clay UI')
if material.node_tree is None:
    material.use_nodes = True
cube = bpy.data.objects['Cube']
cube.data.materials.clear()
cube.data.materials.append(material)
cycles = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
cycles.target = 'CYCLES'
cycles.location = (400, -300)
node = material.node_tree.nodes.new('ShaderNodeGroup')
node.name = 'ClayInstance'
node.node_tree = group
node.location = (60, -300)
material.node_tree.links.new(node.outputs[0], cycles.inputs['Surface'])
world = bpy.data.worlds.new('Clay World UI')
if world.node_tree is None:
    world.use_nodes = True
bpy.context.scene.world = world
world.node_tree.nodes['Background'].location = (-220, 0)
world.node_tree.nodes['World Output'].location = (160, 0)
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.type = 'NODE_EDITOR'
area.spaces.active.tree_type = 'ShaderNodeTree'
area.spaces.active.shader_type = 'OBJECT'
area.spaces.active.show_region_ui = True
bpy.context.preferences.view.show_splash = False
OUTPUT = ROOT / 'temp' / f'clay-ui{bpy.app.version[0]}{bpy.app.version[1]}'
OUTPUT.mkdir(parents=True, exist_ok=True)


def counts():
    group = bpy.data.node_groups['Cy白膜适配']
    world = bpy.data.worlds['Clay World UI']
    material = bpy.data.materials['Clay UI']
    return [len(group.nodes), len(group.interface.items_tree), len(group.links),
            len(material.node_tree.nodes), len(world.node_tree.nodes), len(world.node_tree.links)]


def signature():
    result = []
    for owner in (bpy.data.materials['Clay UI'], bpy.data.worlds['Clay World UI']):
        tree = owner.node_tree
        result.append((sorted((n.name, getattr(n, 'target', ''), getattr(n, 'is_active_output', None),
                               bool(n.get('bekkan_cancelled_cycles_output'))) for n in tree.nodes),
                       sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
                              for l in tree.links)))
    return result


def finish(error=None):
    result = {'ok': error is None and state['draw_error'] is None,
              'blender': bpy.app.version_string, **state, 'error': error}
    (OUTPUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result['ok'] else 1)


def advance():
    try:
        with bpy.context.temp_override(window=window, area=area,
                region=next(r for r in area.regions if r.type == 'WINDOW')):
            step = state['step']
            group = bpy.data.node_groups['Cy白膜适配']
            material = bpy.data.materials['Clay UI']
            world = bpy.data.worlds['Clay World UI']
            if step == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                state['before'] = counts()
                bpy.ops.ed.undo_push(message='Before clay upgrade')
            elif step == 1:
                assert bpy.ops.material.cycles_clay_visn('EXEC_DEFAULT', True) == {'FINISHED'}
            elif step == 2:
                assert len(group.interface.items_tree) == 4
                assert abs(material.node_tree.nodes['ClayInstance'].inputs['Value'].default_value - 0.8) < 1e-6
                assert world.node_tree.get_output_node('CYCLES').inputs['Surface'].links[0].from_node.type == 'BACKGROUND'
                state['after'] = counts()
                bpy.ops.ed.undo()
            elif step == 3:
                assert counts() == state['before'], (counts(), state['before'])
                bpy.ops.ed.redo()
            elif step == 4:
                assert counts() == state['after']
                assert state['draws'] > 0
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'panel.png'))
                area.type = 'NODE_EDITOR'
                area.spaces.active.tree_type = 'ShaderNodeTree'
                area.spaces.active.shader_type = 'OBJECT'
            elif step == 5:
                node = material.node_tree.nodes['ClayInstance']
                for n in material.node_tree.nodes:
                    n.select = n == node
                material.node_tree.nodes.active = node
                bpy.ops.node.view_all()
            elif step == 6:
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'instance.png'))
                assert bpy.ops.node.group_edit(exit=False) == {'FINISHED'}
                bpy.ops.node.view_all()
            elif step == 7:
                assert area.spaces.active.edit_tree == group
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'group.png'))
                bpy.ops.node.group_edit(exit=True)
                area.spaces.active.shader_type = 'WORLD'
                bpy.ops.node.view_all()
            elif step == 8:
                assert area.spaces.active.edit_tree == world.node_tree
                assert panels.BEKKAN_PT_shader_scripts.poll(bpy.context)
                assert world.node_tree.get_output_node('EEVEE') != world.node_tree.get_output_node('CYCLES')
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'world.png'))
                assert bpy.ops.material.cycles_clay_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert counts() == state['after']
                state['before_cancel'] = signature()
            elif step == 9:
                assert bpy.ops.material.cancel_cycles_clay_visn('EXEC_DEFAULT', True) == {'FINISHED'}
            elif step == 10:
                for tree in (material.node_tree, world.node_tree):
                    outputs = [n for n in tree.nodes if n.type in {'OUTPUT_MATERIAL', 'OUTPUT_WORLD'}]
                    cancelled = [n for n in outputs if n.get('bekkan_cancelled_cycles_output')]
                    assert len(cancelled) == 1 and not any(s.is_linked for s in cancelled[0].inputs)
                    assert not cancelled[0].is_active_output
                    assert all(n.target == 'ALL' for n in outputs)
                    assert tree.get_output_node('CYCLES').inputs['Surface'].is_linked
                state['after_cancel'] = signature()
                bpy.ops.ed.undo()
            elif step == 11:
                assert signature() == state['before_cancel']
                bpy.ops.ed.redo()
            elif step == 12:
                assert signature() == state['after_cancel']
                bpy.ops.node.view_all()
            elif step == 13:
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'world-cancelled.png'))
                area.spaces.active.shader_type = 'OBJECT'
                bpy.ops.node.view_all()
            elif step == 14:
                bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'material-cancelled.png'))
                assert bpy.ops.material.cancel_cycles_clay_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert signature() == state['after_cancel']
                finish()
        state['step'] += 1
        area.tag_redraw()
        return 1.0
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1)
