"""工程分析（Analyzer）—— 独立包，自管注册，由 STOOL.py 调用

沿用 AddonManager 的接入方式：本包自己管理 register()/unregister()
（注册类、挂 Scene 属性、挂 load_post 清理缓存），STOOL.py 在
register() 开头调用本包 register，使其面板排在「别馆」快照面板之后。
"""
import bpy  # type: ignore
from bpy.props import PointerProperty  # type: ignore

from . import model, state, checks, ops, ui, fixes  # fixes 为函数库，无需注册
from .ui import AnalyzerProps, FindingItem, ANALYZER_UL_finding, VIEW3D_PT_analyze_visn
from .ops import (ANALYZER_OT_run, ANALYZER_OT_select, ANALYZER_OT_toggle_mark,
                  ANALYZER_OT_clear_marks, ANALYZER_OT_fix)

_CLASSES = [
    FindingItem,            # 先于 AnalyzerProps（CollectionProperty 引用的类型）
    AnalyzerProps,
    ANALYZER_UL_finding,    # 先于面板（template_list 按类名查找）
    VIEW3D_PT_analyze_visn,
    ANALYZER_OT_run,
    ANALYZER_OT_select,
    ANALYZER_OT_toggle_mark,
    ANALYZER_OT_clear_marks,
    ANALYZER_OT_fix,
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


if __name__ == "__main__":
    register()
