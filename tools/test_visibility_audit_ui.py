"""一次性 GUI 实例：搭建类输入框、结果列表、隐藏对象定位和手动刷新。"""
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
panels = importlib.import_module(ROOT.name + '.ui.bekkan.panels')
light_probe = importlib.import_module(ROOT.name + '.core.light_probe')
ui.apply_mode('BEKKAN')
panels.unregister()
panels.VIEW3D_PT_stage_visn.bl_options = set()
state = {'step': 0, 'list_draws': 0, 'draw_error': None}
original_draw = panels.BEKKAN_UL_visibility_audit.draw_item


def draw(self, context, layout, data, item, icon, active_data, active_property, index, flt_flag=0):
    try:
        original_draw(self, context, layout, data, item, icon, active_data, active_property, index, flt_flag)
        state['list_draws'] += 1
    except Exception:
        state['draw_error'] = traceback.format_exc()
        raise


panels.BEKKAN_UL_visibility_audit.draw_item = draw
panels.register()
scene = bpy.context.scene
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.show_region_ui = True
bpy.context.preferences.view.show_splash = False
scene.objects['Cube'].hide_render = True
scene.objects['Camera'].hide_viewport = True
helper = bpy.data.objects.new('AAA_Helper', bpy.data.meshes.new('Helper'))
scene.collection.objects.link(helper)
helper.hide_render = True
scene.visibility_audit.exclusions = 'aaa,bbb,ccc'
light_probe.create_ev_absorber(bpy.context)
directory = ROOT / 'temp' / f'visibility-ui{bpy.app.version[0]}{bpy.app.version[1]}'
directory.mkdir(parents=True, exist_ok=True)


def finish(error=None):
    result = {'ok': error is None and state['draw_error'] is None,
              'blender': bpy.app.version_string, **state, 'error': error}
    (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result['ok'] else 1)


def advance():
    try:
        with bpy.context.temp_override(window=window, area=area,
                region=next(r for r in area.regions if r.type == 'WINDOW')):
            props = scene.visibility_audit
            step = state['step']
            if step == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
            elif step == 1:
                assert bpy.ops.view3d.check_visibility_visn() == {'FINISHED'}
                assert {item.object.name for item in props.results} == {'Camera', 'Cube'}
                assert props.ignored_absorbers == 1 and props.ignored_keywords == 1
            elif step == 2:
                assert state['list_draws'] > 0
                bpy.ops.screen.screenshot(filepath=str(directory / 'mismatches.png'))
                assert bpy.ops.view3d.activate_visibility_result_visn(object_name='Camera') == {'FINISHED'}
                assert bpy.context.view_layer.objects.active == scene.objects['Camera']
                assert scene.objects['Camera'].hide_viewport
            elif step == 3:
                scene.objects['Cube'].hide_render = False
                props.exclusions = 'aaa,bbb,ccc,Camera'
                assert len(props.results) == 2
            elif step == 4:
                bpy.ops.screen.screenshot(filepath=str(directory / 'needs-refresh.png'))
                assert bpy.ops.view3d.check_visibility_visn() == {'FINISHED'}
                assert len(props.results) == 0
            elif step == 5:
                bpy.ops.screen.screenshot(filepath=str(directory / 'clear.png'))
                finish()
        state['step'] += 1
        area.tag_redraw()
        return 0.8
    except Exception:
        finish(traceback.format_exc())


bpy.app.timers.register(advance, first_interval=1)
