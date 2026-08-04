"""工程分析（Analyzer）—— core 部分：数据模型 / 状态 / 检查 / 修复 / 操作符 / 属性
合并自 Bekkan/STOOL_part/Analyzer。面板与 UIList 在 ui/bekkan/analyzer_panel.py。
core 常驻注册（scene.analyzer_props 的标记数据随 .blend 保存，模式切换不能丢）。
"""
import bpy  # type: ignore
from bpy.props import PointerProperty  # type: ignore

from . import model, state, checks, fixes, ops, props as _props_mod
from .props import AnalyzerProps, FindingItem
from .ops import (ANALYZER_OT_run, ANALYZER_OT_select, ANALYZER_OT_toggle_mark,
                  ANALYZER_OT_clear_marks, ANALYZER_OT_fix,
                  ANALYZER_OT_export_report)

_CLASSES = [
    FindingItem,            # 先于 AnalyzerProps（CollectionProperty 引用的类型）
    AnalyzerProps,
    ANALYZER_OT_run,
    ANALYZER_OT_select,
    ANALYZER_OT_toggle_mark,
    ANALYZER_OT_clear_marks,
    ANALYZER_OT_fix,
    ANALYZER_OT_export_report,
]


def _on_load(dummy):
    """加载新文件后清空扫描缓存，避免持有旧工程的对象名"""
    model.LAST_RESULTS = []


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.analyzer_props = PointerProperty(type=AnalyzerProps)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if hasattr(bpy.types.Scene, 'analyzer_props'):
        del bpy.types.Scene.analyzer_props
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
