"""一次性图形实例测试：blender --factory-startup -P 本文件。"""
import json
import os
from pathlib import Path
import sys
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_workspace_setup import addon, assert_setup

RESULT = ROOT / 'temp/workspace_setup_ui_result.json'
RESULT.parent.mkdir(exist_ok=True)
RESULT.write_text('{"ok":false,"status":"running"}', encoding='utf-8')
# 测试实例默认展开搭建面板，以验证按钮绘制；不修改实际插件默认折叠行为。
addon.ui.bekkan.panels.VIEW3D_PT_stage_visn.bl_options = set()
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
state = {'step': 0}


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
                                 'checks': ['native_panel', 'complete_setup', 'single_undo_redo',
                                            'working_space_undo', 'autopack_stays_enabled',
                                            'repeat_from_camera_view']},
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
                assert_setup(bpy.context.scene, 'BLENDER_EEVEE')
                state['after'] = scene_state()
            elif step == 2:
                bpy.ops.screen.screenshot(filepath=str(ROOT / 'temp/workspace_setup_ready.png'))
                bpy.ops.ed.undo()
            elif step == 3:
                assert scene_state() == state['before'], (scene_state(), state['before'])
                # use_autopack 属于文件选项，和插件启用状态一样不在 Blender 场景撤销栈中。
                assert bpy.data.use_autopack
                bpy.ops.ed.redo()
            elif step == 4:
                assert scene_state() == state['after']
                assert_setup(bpy.context.scene, 'BLENDER_EEVEE')
                # 主动进入相机视图再重复运行，覆盖 C-P 对齐的上下文分支。
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
                assert bpy.ops.view3d.setup_workspace_visn('EXEC_DEFAULT', True) == {'FINISHED'}
                assert_setup(bpy.context.scene, 'BLENDER_EEVEE')
                finish(True)
        state['step'] += 1
        return 0.8
    except Exception:
        finish(False, traceback.format_exc())
    return None


bpy.app.timers.register(advance, first_interval=2)
