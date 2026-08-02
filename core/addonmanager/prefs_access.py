"""颈椎拯救者：偏好设置访问入口
原 AddonManager/preferences.py 硬编码 bl_idname="bekkan_visn"；合并后一个插件
只能有一个 AddonPreferences（在包根 prefs.py），这里按根包名动态回查。
独立别馆版打包时根包名仍为 bekkan_visn，行为与原版一致。
"""
import bpy

_ROOT_PKG = __package__.split(".")[0]


def get_preferences():
    addon = bpy.context.preferences.addons.get(_ROOT_PKG)
    return addon.preferences if addon else None
