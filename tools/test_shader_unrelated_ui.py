"""仅在一次性独立图形实例运行：blender --factory-startup -P 本文件。"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / 'tools'))
from test_shader_unrelated_nodes import example, selected, signature

RESULT = ROOT / 'temp/shader_unrelated_ui_result.json'
RESULT.parent.mkdir(exist_ok=True)
RESULT.write_text('{"ok": false, "status": "running"}', encoding='utf-8')
addon = importlib.import_module(ROOT.name)
tools = importlib.import_module(ROOT.name + '.core.shader_tools')
addon.register()
entry = bpy.context.preferences.addons.new()
entry.module = addon.__name__
addon.ui.apply_mode('BEKKAN')
if hasattr(bpy.context.preferences.view, 'show_splash'):
    bpy.context.preferences.view.show_splash = False
material, shader, output, shared, orphan = example()
bpy.context.object.data.materials.clear()
bpy.context.object.data.materials.append(material)
tree = material.node_tree
shader.hide = True
shader.location = (500, 160)
output.location = (780, 160)
shared.location = (-480, 160)
for index, node in enumerate(orphan):
    node.location = (-480 + 250 * index, -140)
for node in tree.nodes:
    node.select = node == shader
tree.nodes.active = shader
state = {'step': 0, 'material': material.name, 'unrelated': {n.name for n in orphan},
         'original_selection': selected(tree), 'signature': signature(tree)}
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.type = 'NODE_EDITOR'
area.ui_type = 'ShaderNodeTree'
area.spaces.active.shader_type = 'OBJECT'
area.spaces.active.show_region_ui = True


def finish(ok, error=None):
    RESULT.write_text(json.dumps({'ok': ok, 'blender': bpy.app.version_string,
                                 'step': state['step'], 'error': error,
                                 'checks': ['panel_draw', 'operator_select_four', 'undo_redo',
                                            'native_delete_preserves_output', 'zero_candidates',
                                            'missing_output_cancelled']}, ensure_ascii=False),
                      encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    # 只退出本脚本的一次性进程，不写共享 quit.blend 或保存用户偏好。
    os._exit(0 if ok else 1)


def advance():
    try:
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(window=window, area=area, region=region):
            tree = tools.current_material_tree(bpy.context)
            assert tree == bpy.data.materials[state['material']].node_tree
            step = state['step']
            if step == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                bpy.ops.node.view_all()
                bpy.ops.ed.undo_push(message='Before selecting unused nodes')
            elif step == 1:
                assert bpy.ops.node.select_unrelated_shader_nodes_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert selected(tree) == state['unrelated']
                assert signature(tree) == state['signature']
            elif step == 2:
                bpy.ops.screen.screenshot(filepath=str(ROOT / 'temp/shader_unrelated_selected.png'))
                bpy.ops.ed.undo()
            elif step == 3:
                assert selected(tree) == state['original_selection']
                assert signature(tree) == state['signature']
                bpy.ops.ed.redo()
            elif step == 4:
                assert selected(tree) == state['unrelated']
                live_names = {n.name for n in tree.nodes if not n.select}
                state['live'] = signature(tree, live_names)
                assert bpy.ops.node.delete('EXEC_DEFAULT', True) == {'FINISHED'}
            elif step == 5:
                assert signature(tree) == state['live']
                bpy.ops.ed.undo()
            elif step == 6:
                assert signature(tree) == state['signature']
                assert selected(tree) == state['unrelated']
                # 给悬空链补上输出连线后，应清掉之前的四节点选择。
                shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
                tree.links.new(tree.nodes['Unused 4'].outputs[0], shader.inputs['Metallic'])
                assert bpy.ops.node.select_unrelated_shader_nodes_visn() == {'FINISHED'}
                assert selected(tree) == set() and tree.nodes.active is None
                for node in list(tree.nodes):
                    if node.type == 'OUTPUT_MATERIAL':
                        tree.nodes.remove(node)
                shader.select = True
                before = selected(tree), signature(tree)
                assert bpy.ops.node.select_unrelated_shader_nodes_visn() == {'CANCELLED'}
                assert (selected(tree), signature(tree)) == before
                finish(True)
        state['step'] += 1
        return 0.6
    except Exception:
        finish(False, traceback.format_exc())
    return None


bpy.app.timers.register(advance, first_interval=2)
