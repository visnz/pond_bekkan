"""一次性图形实例测试：blender --factory-startup -P 本文件。"""
import json
import os
from pathlib import Path
import sys
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_workspace_setup import addon, setup, assert_settings, assert_bootstrap

RESULT = ROOT / 'temp/workspace_setup_ui_result.json'
RESULT.parent.mkdir(exist_ok=True)
RESULT.write_text('{"ok":false,"status":"running"}', encoding='utf-8')
# 测试实例默认展开搭建面板，以验证按钮绘制；不修改实际插件默认折叠行为。
addon.ui.bekkan.panels.VIEW3D_PT_stage_visn.bl_options = set()
state = {'step': 0}
report_class = addon.ui.bekkan.panels.BEKKAN_OT_workspace_setup_report
original_invoke = report_class.invoke
def capture_popup(self, context, event):
    state['popup'] = self
    return original_invoke(self, context, event)
report_class.invoke = capture_popup
addon.register()
entry = bpy.context.preferences.addons.new()
entry.module = addon.__name__
addon.ui.apply_mode('BEKKAN')
if hasattr(bpy.context.preferences.view, 'show_splash'):
    bpy.context.preferences.view.show_splash = False
window = bpy.context.window
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.show_region_ui = True
scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'
scene.cycles.denoising_input_passes = 'RGB_ALBEDO_NORMAL'
scene.cycles.denoising_prefilter = 'ACCURATE'
scene.cycles.denoising_quality = 'HIGH'
scene.cycles.denoising_use_gpu = True
scene.render.fps = 24
scene.render.fps_base = 1.001


def scene_state():
    scene = bpy.context.scene
    return ({obj.name: (obj.type, tuple(obj.location)) for obj in scene.objects},
            scene.render.engine, scene.render.fps, scene.render.fps_base,
            scene.render.filepath, scene.view_settings.view_transform,
            bpy.data.colorspace.working_space,
            scene.camera.name if scene.camera else None,
            scene.world.name if scene.world else None)


def finish(ok, error=None):
    RESULT.write_text(json.dumps({'ok': ok, 'step': state['step'], 'error': error,
                                 'blender': bpy.app.version_string,
                                 'checks': ['native_report_three_tabs', 'complete_setup', 'single_undo_redo',
                                            'working_space_undo', 'autopack_stays_enabled',
                                            'repeat_preserves_scene', 'report_reopen']},
                                ensure_ascii=False), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if ok else 1)


def advance():
    try:
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(window=window, area=area, region=region):
            step = state['step']
            if step == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                state['before'] = scene_state()
                bpy.ops.ed.undo_push(message='Before workspace setup')
            elif step == 1:
                assert bpy.ops.view3d.setup_workspace_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert_settings(bpy.context.scene, 'BLENDER_EEVEE')
                assert_bootstrap(bpy.context.scene)
                assert state['popup'].report_tab == 'CHANGED'
                assert len(json.loads(state['popup'].report_json)['changed']) > 0
                state['after'] = scene_state()
            elif step == 2:
                bpy.ops.screen.screenshot(filepath=str(ROOT / 'temp/workspace_report_changed.png'))
                # invoke_popup 内部保留 RNA 副本；原 invoke 对象的赋值不会改变已绘制窗口。
                # 用真实原生弹窗入口指定页签，分别验证三种页面的实际绘制。
                bpy.ops.wm.workspace_setup_report_visn('INVOKE_DEFAULT',
                    report_json=state['popup'].report_json, report_tab='UNCHANGED')
            elif step == 3:
                bpy.ops.screen.screenshot(filepath=str(ROOT / 'temp/workspace_report_unchanged.png'))
                bpy.ops.wm.workspace_setup_report_visn('INVOKE_DEFAULT',
                    report_json=state['popup'].report_json, report_tab='SCENE')
            elif step == 4:
                bpy.ops.screen.screenshot(filepath=str(ROOT / 'temp/workspace_report_scene.png'))
                bpy.ops.ed.undo()
            elif step == 5:
                assert scene_state() == state['before'], (scene_state(), state['before'])
                # use_autopack 属于文件选项，和插件启用状态一样不在 Blender 场景撤销栈中。
                assert bpy.data.use_autopack
                bpy.ops.ed.redo()
            elif step == 6:
                assert scene_state() == state['after']
                assert_settings(bpy.context.scene, 'BLENDER_EEVEE')
                assert_bootstrap(bpy.context.scene)
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
                assert bpy.ops.view3d.setup_workspace_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert scene_state() == state['after']
                report = json.loads(state['popup'].report_json)
                assert not report['changed']
                assert all(a['status'] == 'PRESERVED' for a in report['scene_actions'])
            elif step == 7:
                # 不再执行 setup 也能重新查看最后一次运行时的记录。
                assert bpy.ops.wm.workspace_setup_report_visn('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                assert json.loads(state['popup'].report_json) == setup.last_setup_report(bpy.context.scene)
                finish(True)
        state['step'] += 1
        return 0.8
    except Exception:
        finish(False, traceback.format_exc())
    return None


bpy.app.timers.register(advance, first_interval=2)
