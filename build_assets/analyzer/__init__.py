# 工程分析 —— 独立插件（从 PondBekkan 合体插件中单独拎出的模块）
bl_info = {
    "name": "工程分析",
    "category": "3D View",
    "author": "桶桶",
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar（N 面板）",
    "description": "扫描并修复当前 .blend 工程中的常见问题",
    "version": (1, 0, 0),
}

import bpy

from . import prefs
from .core import analyzer
from .ui import analyzer_panel


def register():
    prefs.register()
    analyzer.register()
    analyzer_panel.register()


def unregister():
    analyzer_panel.unregister()
    analyzer.unregister()
    prefs.unregister()
