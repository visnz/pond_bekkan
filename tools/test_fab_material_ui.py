"""独立 GUI 实例：真实文件夹选择器、面板/节点绘制与单次撤销重做。"""
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
panels = importlib.import_module(ROOT.name + '.ui.bekkan.light_compose_panel')
ui.apply_mode('BEKKAN')
panels.unregister()
panels.BEKKAN_PT_light_compose.bl_options = set()
panels.BEKKAN_PT_fab_material.bl_options = set()
state = {'step': 0, 'draws': 0, 'draw_error': None}
draw_original = panels.BEKKAN_PT_fab_material.draw


def draw(self, context):
    try:
        draw_original(self, context)
        state['draws'] += 1
    except Exception:
        state['draw_error'] = traceback.format_exc()
        raise


panels.BEKKAN_PT_fab_material.draw = draw
panels.register()
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.show_region_ui = True
bpy.context.preferences.view.show_splash = False
SAMPLE = Path(r'C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary\Worn_Concrete_Ceiling-2da64c55\texture-set\high\worn_concrete_ceiling_ug_extracted')
OUTPUT = ROOT / 'temp' / f'fab-ui{bpy.app.version[0]}{bpy.app.version[1]}'
OUTPUT.mkdir(parents=True, exist_ok=True)


def counts():
    return [len(bpy.data.objects), len(bpy.data.materials), len(bpy.data.images)]


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
        if step in (2, 3):
            target = next(((w, a) for w in bpy.context.window_manager.windows
                           for a in w.screen.areas if a.type == 'FILE_BROWSER'), None)
            if target is None:
                raise RuntimeError('文件夹选择窗口未打开')
            browser_window, browser_area = target
            with bpy.context.temp_override(window=browser_window, area=browser_area,
                    region=next(r for r in browser_area.regions if r.type == 'WINDOW')):
                if step == 2:
                    browser_area.spaces.active.params.directory = os.fsencode(str(SAMPLE) + os.sep)
                else:
                    bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'folder-picker.png'))
                    assert bpy.ops.file.execute() == {'FINISHED'}
        else:
            with bpy.context.temp_override(window=window, area=area,
                    region=next(r for r in area.regions if r.type == 'WINDOW')):
                if step == 0:
                    next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                    state['before'] = counts()
                    bpy.ops.ed.undo_push(message='Before Fab Material')
                elif step == 1:
                    assert bpy.ops.material.import_fab_visn('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                elif step == 4:
                    assert bpy.context.object.active_material.name.startswith('Fab · Worn Concrete Ceiling')
                    assert len([n for n in bpy.context.object.active_material.node_tree.nodes if n.type == 'TEX_IMAGE']) == 6
                    state['after'] = counts()
                    bpy.ops.ed.undo()
                elif step == 5:
                    assert counts() == state['before'], (counts(), state['before'])
                    bpy.ops.ed.redo()
                elif step == 6:
                    assert counts() == state['after']
                    assert bpy.context.object.active_material.displacement_method == 'BUMP'
                    assert state['draws'] > 0
                    bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'panel.png'))
                    area.type = 'NODE_EDITOR'
                    area.spaces.active.tree_type = 'ShaderNodeTree'
                    area.spaces.active.shader_type = 'OBJECT'
                elif step == 7:
                    assert area.spaces.active.edit_tree == bpy.context.object.active_material.node_tree
                    bpy.ops.node.view_all()
                elif step == 8:
                    bpy.ops.screen.screenshot(filepath=str(OUTPUT / 'nodes.png'))
                    finish()
        state['step'] += 1
        area.tag_redraw()
        return 1.0
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1)
