"""隔离后台检查真实启用/禁用与磁盘重载：不要在用户工程中运行。"""
import importlib
from pathlib import Path
import sys
from unittest.mock import patch

import addon_utils
import bpy
from _bpy_restrict_state import RestrictBlend

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
package = ROOT.name
errors = []
locked = bpy.context.scene.objects['Cube']
locked.hide_select = True
locked.display_type = 'WIRE'

module = addon_utils.enable(package, default_set=True, persistent=True,
                            refresh_handled=True, handle_error=errors.append)
assert module is not None and not errors, repr(errors)
core = importlib.import_module(package + '.core.unselectable')
assert bpy.app.timers.is_registered(core._initial_display_sync)
with RestrictBlend():
    assert core._initial_display_sync() == 0.1
print('PASS_RESTRICTED_ENABLE')
addon_utils.disable(package, default_set=False, refresh_handled=True, handle_error=errors.append)
assert not errors, repr(errors)
assert not bpy.app.timers.is_registered(core._initial_display_sync), '同步前禁用应取消计时器'
assert core._on_depsgraph not in bpy.app.handlers.depsgraph_update_post

module = addon_utils.enable(package, default_set=False, persistent=True,
                            refresh_handled=True, handle_error=errors.append)
assert module is not None and not errors, repr(errors)
assert core._initial_display_sync() is None
assert locked.display_type == 'BOUNDS'
prefs = bpy.context.preferences.addons[package].preferences
prefs.mode = 'BEKKAN'
prefs.show_stage = False
for iteration in range(2):
    debug = importlib.import_module(package + '.core.debug')
    old_core = core
    old_module = module
    debug._reload_addon_from_disk()
    module = sys.modules[package]
    core = importlib.import_module(package + '.core.unselectable')
    assert module is not old_module and module.__addon_enabled__
    assert module.__addon_persistent__
    assert not bpy.app.timers.is_registered(old_core._initial_display_sync)
    assert old_core._on_depsgraph not in bpy.app.handlers.depsgraph_update_post
    assert bpy.app.handlers.depsgraph_update_post.count(core._on_depsgraph) == 1
    assert bpy.app.timers.is_registered(core._initial_display_sync)
    assert core._initial_display_sync() is None
    assert bpy.context.preferences.addons[package].preferences.mode == 'BEKKAN'
    assert not bpy.context.preferences.addons[package].preferences.show_stage
    assert module.ui.current_mode() == 'BEKKAN'
    assert bpy.ops.object.manage_unselectable_visn(target_uid=str(locked.session_uid), action='EDIT') == {'FINISHED'}
    assert locked.display_type == 'TEXTURED'
    assert bpy.ops.object.manage_unselectable_visn(target_uid=str(locked.session_uid), action='LOCK') == {'FINISHED'}
    assert locked.display_type == 'BOUNDS'
print('PASS_DISK_RELOAD: twice, preferences preserved, old timers/handlers removed, display linkage')

debug = importlib.import_module(package + '.core.debug')
def fail_disable(*args, **kwargs):
    kwargs['handle_error'](RuntimeError('SIMULATED_DISABLE_ERROR'))
with patch.object(addon_utils, 'disable', side_effect=fail_disable):
    try:
        debug._reload_addon_from_disk()
        raise AssertionError('应报告注销失败')
    except RuntimeError as exc:
        assert 'SIMULATED_DISABLE_ERROR' in str(exc), str(exc)

def fail_enable(*args, **kwargs):
    kwargs['handle_error'](RuntimeError('SIMULATED_ENABLE_ERROR'))
    return None
with patch.object(addon_utils, 'enable', side_effect=fail_enable):
    try:
        debug._reload_addon_from_disk()
        raise AssertionError('应报告启用失败')
    except RuntimeError as exc:
        assert 'SIMULATED_ENABLE_ERROR' in str(exc), str(exc)
assert not bpy.app.timers.is_registered(core._initial_display_sync)
assert core._on_depsgraph not in bpy.app.handlers.depsgraph_update_post
print('PASS_ERROR_CALLBACKS: enable/disable errors preserve the original exception')
