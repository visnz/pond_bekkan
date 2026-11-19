"""独立 GUI：Shader 侧栏、真实文件夹选择器、当前编辑层和单次撤销重做。"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback
from itertools import combinations
import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
ui = importlib.import_module(ROOT.name + '.ui')
panels = importlib.import_module(ROOT.name + '.ui.bekkan.shader_panel')
tools = importlib.import_module(ROOT.name + '.core.shader_tools')
ui.apply_mode('BEKKAN')
panels.unregister()
state = {'step': 0, 'draws': 0, 'draw_error': None}
draw_original = panels.BEKKAN_PT_shader_scripts.draw


def draw(self, context):
    try:
        draw_original(self, context)
        state['draws'] += 1
    except Exception:
        state['draw_error'] = traceback.format_exc()
        raise


panels.BEKKAN_PT_shader_scripts.draw = draw
panels.register()
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
material = bpy.data.materials.new('Fab UI Existing')
if material.node_tree is None:
    material.use_nodes = True
bpy.context.object.data.materials.clear()
bpy.context.object.data.materials.append(material)
area.type = 'NODE_EDITOR'
area.spaces.active.tree_type = 'ShaderNodeTree'
area.spaces.active.shader_type = 'OBJECT'
area.spaces.active.show_region_ui = True
bpy.context.preferences.view.show_splash = False
SAMPLE = Path('C:/ProgramData/Epic/EpicGamesLauncher/VaultCache/FabLibrary/Worn_Concrete_Ceiling-2da64c55/texture-set/high/worn_concrete_ceiling_ug_extracted')
OUTPUT = ROOT / 'temp' / f'fab-ui{bpy.app.version[0]}{bpy.app.version[1]}'
OUTPUT.mkdir(parents=True, exist_ok=True)


def counts():
    tree = bpy.data.materials['Fab UI Existing'].node_tree
    return [len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials),
            len(bpy.data.images), len(tree.nodes), len(tree.links)]


def graph(tree):
    return ({n.name: (tuple(n.location), getattr(n, 'is_active_output', None)) for n in tree.nodes},
            {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
             for l in tree.links})


def finish(error=None):
    result = {'ok': error is None and state['draw_error'] is None,
              'blender': bpy.app.version_string, **state, 'error': error}
    (OUTPUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result['ok'] else 1)


def advance():
    try:
        step = state['step']
        if step in (2, 3, 11, 12):
            target = next(((w, a) for w in bpy.context.window_manager.windows
                           for a in w.screen.areas if a.type == 'FILE_BROWSER'), None)
            if target is None:
                raise RuntimeError('文件夹选择窗口未打开')
            browser_window, browser_area = target
            with bpy.context.temp_override(window=browser_window, area=browser_area,
                    region=next(r for r in browser_area.regions if r.type == 'WINDOW')):
                if step in (2, 11):
                    browser_area.spaces.active.params.directory = os.fsencode(str(SAMPLE) + os.sep)
                    if step == 11:
                        # 选择器打开后退出组并重命名，仍应导入最初捕获的节点组。
                        area.spaces.active.path.clear()
                        root = bpy.data.materials['Fab UI Existing'].node_tree
                        area.spaces.active.path.start(root)
                        bpy.data.node_groups['Nested import target'].name = 'Renamed import target'
                else:
                    if step == 3:
                        bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'folder-picker.png'))
                    assert bpy.ops.file.execute() == {'FINISHED'}
        else:
            with bpy.context.temp_override(window=window, area=area,
                    region=next(r for r in area.regions if r.type == 'WINDOW')):
                tree = bpy.data.materials['Fab UI Existing'].node_tree
                if step == 0:
                    next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                    assert tools.current_material_tree(bpy.context) == tree
                    state['before'] = counts()
                    state['original_nodes'] = graph(tree)[0]
                    state['original_links'] = sorted(graph(tree)[1])
                    bpy.ops.ed.undo_push(message='Before Fab Nodes')
                elif step == 1:
                    assert bpy.ops.material.import_fab_visn('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                elif step == 4:
                    assert len([n for n in tree.nodes if n.type == 'TEX_IMAGE']) == 6
                    assert graph(tree)[0]['Material Output'] == state['original_nodes']['Material Output']
                    assert set(state['original_links']) <= graph(tree)[1]
                    state['after'] = counts()
                    assert state['before'][:3] == state['after'][:3]
                    bpy.ops.ed.undo()
                elif step == 5:
                    assert counts() == state['before'], (counts(), state['before'])
                    bpy.ops.ed.redo()
                elif step == 6:
                    assert counts() == state['after']
                    assert state['draws'] > 0
                    bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'panel.png'))
                    bpy.ops.node.view_all()
                elif step == 7:
                    # 用真实绘制后的尺寸再查新增节点避让。
                    imported = [n for n in tree.nodes if n.name not in state['original_nodes']]
                    for a, b in combinations(imported, 2):
                        aw, ah = tools._node_size(a, 1)
                        bw, bh = tools._node_size(b, 1)
                        x = min(a.location.x + aw, b.location.x + bw) - max(a.location.x, b.location.x)
                        y = min(a.location.y, b.location.y) - max(a.location.y - ah, b.location.y - bh)
                        assert x <= 0 or y <= 0, ('overlap', a.name, b.name)
                    bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'nodes.png'))
                elif step == 8:
                    texture = next(n for n in tree.nodes if n.type == 'TEX_IMAGE' and n.label == 'Normal')
                    texture.image.colorspace_settings.name = 'sRGB'
                    assert bpy.ops.analyzer.fix_normal_colorspace_visn() == {'FINISHED'}
                    assert texture.image.colorspace_settings.name == 'Non-Color'
                elif step == 9:
                    group = bpy.data.node_groups.new('Nested import target', 'ShaderNodeTree')
                    group.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
                    group.nodes.new('NodeGroupOutput')
                    node = tree.nodes.new('ShaderNodeGroup')
                    node.node_tree = group
                    for n in tree.nodes:
                        n.select = n == node
                    tree.nodes.active = node
                    assert bpy.ops.node.group_edit(exit=False) == {'FINISHED'}
                    state['root_before_nested'] = len(tree.nodes)
                elif step == 10:
                    assert tools.current_material_tree(bpy.context) == bpy.data.node_groups['Nested import target']
                    assert bpy.ops.material.import_fab_visn('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                elif step == 13:
                    group = bpy.data.node_groups['Renamed import target']
                    assert len([n for n in group.nodes if n.type == 'TEX_IMAGE']) == 6
                    assert not any(n.type == 'OUTPUT_MATERIAL' for n in group.nodes)
                    assert len(tree.nodes) == state['root_before_nested']
                    assert len(group.interface.items_tree) == 1
                    assert not hasattr(bpy.types, 'BEKKAN_PT_fab_material')
                    finish()
        state['step'] += 1
        area.tag_redraw()
        return 1.0
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1)
