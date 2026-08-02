# PondBekkan —— 池塘 × 别馆 合并插件
# 逻辑层（core）一套代码共同维护；UI 层（ui）两套皮肤：
#   蛙灾模式 = 池塘四抽屉（岁岁）  别馆模式 = 别馆工具箱（visn）
# 发行三版本（build.py 产出，改 _build_mode.py 与 bl_info 名称）：
#   合体版 pond_bekkan（偏好设置里切换模式，默认蛙灾）
#   蛙灾独立版 Pond ／ 别馆独立版 bekkan_visn（无开关，打开即原 UI）
bl_info = {
    "name": "PondBekkan",
    "category": "3D View",
    "author": "visnz & 岁岁",
    "blender": (5, 2, 0),  # 仅支持 Blender 5.2
    "location": "View3D > Sidebar（N 面板）",
    "description": "池塘与别馆的合并工具箱：一套核心，两套界面",
    "version": (1, 0, 0),
}

import bpy

# ── 开发期热重载（禁用/启用或 F8 时子模块一并刷新） ──
import importlib
import sys


def _reload_submodules():
    pkg = __name__
    mods = sorted((m for m in sys.modules if m.startswith(pkg + ".")),
                  reverse=True)
    for name in mods:
        try:
            importlib.reload(sys.modules[name])
        except Exception as e:
            print(f"[pond_bekkan] reload {name} 失败: {e}")


# 顶层模块被 Blender 重新导入时（F8 / 重新勾选），刷新所有子模块
if "_addon_loaded" in globals():
    _reload_submodules()
_addon_loaded = True

from . import prefs as _prefs
from . import core as _core
from . import ui as _ui


def register():
    _prefs.register()
    _core.register()
    _ui.register()  # 内部按构建版本/偏好设置决定初始模式


def unregister():
    _ui.unregister()
    _core.unregister()
    _prefs.unregister()
