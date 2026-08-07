"""工程分析（Analyzer）—— core 部分：数据模型 / 状态 / 检查 / 修复 / 操作符 / 属性
合并自 Bekkan/STOOL_part/Analyzer。面板与 UIList 在 ui/bekkan/analyzer_panel.py。
core 常驻注册（scene.analyzer_props 的标记数据随 .blend 保存，模式切换不能丢）。
"""
import bpy  # type: ignore
from bpy.props import PointerProperty  # type: ignore

from . import model, state, checks, fixes, ops, props as _props_mod
from .props import AnalyzerProps, FindingItem
from .ops import (ANALYZER_OT_run, ANALYZER_OT_select,
                  ANALYZER_OT_copy_names,
                  ANALYZER_OT_toggle_mark,
                  ANALYZER_OT_clear_marks, ANALYZER_OT_fix,
                  ANALYZER_OT_export_report, ANALYZER_OT_downscale,
                  ANALYZER_OT_fix_normal_colorspace)

_CLASSES = [
    FindingItem,            # 先于 AnalyzerProps（CollectionProperty 引用的类型）
    AnalyzerProps,
    ANALYZER_OT_run,
    ANALYZER_OT_select,
    ANALYZER_OT_copy_names,
    ANALYZER_OT_toggle_mark,
    ANALYZER_OT_clear_marks,
    ANALYZER_OT_fix,
    ANALYZER_OT_export_report,
    ANALYZER_OT_downscale,
    ANALYZER_OT_fix_normal_colorspace,
]


def _refresh_downscale_cache():
    """缓存失效时重扫大贴图计数并写入 scene.analyzer_props。

    读未加载贴图的 img.size 会逐个读文件/打包块（实测约 1.4s/300 张）。原先想用
    bpy.app.timers 延后 2s 做「后台预热」，但延后触发的卡顿一样会打断用户——
    只是把"打开文件那一下"的卡顿挪到"打开文件后随便干点什么"的时候，时机更随机、
    体感更差。改为直接并入 load_post：反正打开文件本身就有一下加载耗时，扫描
    合并进同一次卡顿里，不会多一次无法预期的二次卡顿。
    """
    scene = getattr(bpy.context, 'scene', None)
    if scene is None:
        return
    props = getattr(scene, 'analyzer_props', None)
    if props is None:
        return
    if fixes.get_downscale_report(props) is not None:
        return  # 缓存有效，不用重扫
    try:
        n4, n2 = fixes.count_big_textures()
        fixes.update_downscale_report(props, n4, n2)
    except Exception:
        pass


def _on_load(dummy):
    """加载新文件后清空扫描缓存，并同步重扫一次大贴图计数（并入本次加载耗时）。"""
    model.LAST_RESULTS = []
    _refresh_downscale_cache()


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
