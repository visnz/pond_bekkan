# ui 层模式分发：按当前界面模式注册/注销两套 UI。
# combined 构建下 apply_mode() 供偏好设置里的「蛙灾模式/别馆模式」开关调用。
import bpy

from .. import _build_mode
from . import bekkan as _bekkan
from . import pond as _pond
from . import mode_switcher as _mode_switcher

_active = None  # "POND" / "BEKKAN" / None


def _register_one(mode):
    if mode == "POND":
        _pond.register()
    else:
        _bekkan.register()


def _unregister_one(mode):
    if mode == "POND":
        _pond.unregister()
    else:
        _bekkan.unregister()


def default_mode():
    """addon 启用时的初始模式：独立版锁定；合体版读偏好设置（默认蛙灾）"""
    bm = _build_mode.BUILD_MODE
    if bm == "pond":
        return "POND"
    if bm == "bekkan":
        return "BEKKAN"
    try:
        pkg = __package__.split(".")[0]
        addon = bpy.context.preferences.addons.get(pkg)
        if addon and hasattr(addon.preferences, "mode"):
            return addon.preferences.mode
    except Exception:
        pass
    return "POND"  # 决策点 4：合体版默认蛙灾模式


def current_mode():
    return _active


def register(mode=None):
    """注册指定模式的 UI；mode_switcher 全局只注册一次"""
    global _active
    _mode_switcher.register()
    if mode is None:
        mode = default_mode()
    if _active == mode:
        return
    if _active is not None:
        _unregister_one(_active)
    _register_one(mode)
    _active = mode


def unregister():
    global _active
    if _active is not None:
        _unregister_one(_active)
        _active = None
    _mode_switcher.unregister()


def apply_mode(mode):
    """合体版偏好设置开关的入口"""
    register(mode)
