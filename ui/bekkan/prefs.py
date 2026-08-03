# 别馆模块开关：名单唯一来源。
# 在根 prefs.py 中通过 __annotations__ 动态挂到 AddonPreferences 上。

MODULES = [
    ("show_snapshot", "快照对比"),
    ("show_analyzer", "工程分析"),
    ("show_parents", "上下级"),
    ("show_stage", "搭建类"),
    ("show_texture", "贴图索引"),
    ("show_anime", "动画类"),
    ("show_render_preset", "渲染预设"),
    ("show_addonmanager", "颈椎拯救者"),
]


def module_enabled(key: str) -> bool:
    """供面板 poll 查询。"""
    import bpy
    prefs = bpy.context.preferences.addons[
        __package__.split(".")[0]
    ].preferences
    return getattr(prefs, key, True)
