"""一次性 GUI：检查入口、五个报告页、分页、几何定位与重新打开。"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
suffix = f'{bpy.app.version[0]}{bpy.app.version[1]}'
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'temp' / f'file-size{suffix}' / 'zst.blend'), load_ui=False)
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
ui = importlib.import_module(ROOT.name + '.ui')
panels = importlib.import_module(ROOT.name + '.ui.bekkan.panels')
audit = importlib.import_module(ROOT.name + '.core.file_size_audit')
ui.apply_mode('BEKKAN')
panels.unregister()
panels.VIEW3D_PT_stage_visn.bl_options = set()
state = {'step': 0, 'draws': {}, 'draw_error': None}
original_draw = panels.BEKKAN_OT_file_size_report.draw


def draw(self, context):
    try:
        original_draw(self, context)
        state['draws'][self.report_tab] = state['draws'].get(self.report_tab, 0) + 1
    except Exception:
        state['draw_error'] = traceback.format_exc()
        raise


panels.BEKKAN_OT_file_size_report.draw = draw
panels.register()
window = None
area = None
bpy.context.preferences.view.show_splash = False
directory = ROOT / 'temp' / f'file-size-ui{suffix}'
directory.mkdir(parents=True, exist_ok=True)
before = (bpy.data.filepath, set(bpy.data.objects.keys()),
          set(bpy.data.images.keys()), set(bpy.data.meshes.keys()), bpy.data.is_dirty)


def finish(error=None):
    result = {'ok': error is None and state['draw_error'] is None,
              'blender': bpy.app.version_string, **state, 'error': error}
    (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result['ok'] else 1)


def advance():
    global window, area
    try:
        if window is None:
            window = bpy.context.window or next(iter(bpy.context.window_manager.windows))
            area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
            area.spaces.active.show_region_ui = True
            area.tag_redraw()
            return 0.8
        with bpy.context.temp_override(window=window, area=area,
                region=next(r for r in area.regions if r.type == 'WINDOW')):
            step = state['step']
            if step == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
            elif step == 1:
                bpy.ops.screen.screenshot(filepath=str(directory / 'sidebar.png'))
                assert bpy.ops.wm.audit_file_size_visn() == {'FINISHED'}
            elif step in range(2, 7):
                tabs = ['SUMMARY', 'IMAGE', 'GEOMETRY', 'OTHER', 'EXTERNAL']
                tab = tabs[step - 2]
                assert state['draws'].get(tab, 0) > 0, state
                bpy.ops.screen.screenshot(filepath=str(directory / f'{tab.lower()}.png'))
                if step < 6:
                    assert bpy.ops.wm.file_size_report_visn('INVOKE_DEFAULT',
                        report_tab=tabs[step - 1]) == {'RUNNING_MODAL'}
                else:
                    assert bpy.ops.wm.file_size_report_visn('INVOKE_DEFAULT',
                        report_tab='OTHER', report_page=2) == {'RUNNING_MODAL'}
            elif step == 7:
                bpy.ops.screen.screenshot(filepath=str(directory / 'page2.png'))
                name = next(e['name'] for e in audit.last_report()['entries'] if e['code'] == 'ME' and e['name'].startswith('大网格'))
                assert bpy.ops.wm.select_size_mesh_visn(mesh_name=name) == {'FINISHED'}
                assert len(bpy.context.selected_objects) == 2
                assert before == (bpy.data.filepath, set(bpy.data.objects.keys()),
                                  set(bpy.data.images.keys()), set(bpy.data.meshes.keys()), bpy.data.is_dirty)
                assert bpy.ops.wm.file_size_report_visn('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
            elif step == 8:
                finish()
        state['step'] += 1
        area.tag_redraw()
        return 0.8
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1.5)
