# 蛙灾模式的模块开关视图层：MODULES 名单 + module_enabled 面板 poll。
# 布尔字段本体挂在根 prefs.py 的唯一 AddonPreferences 上（一个插件只能有一个偏好类），
# 这里通过根包名回查。独立蛙灾版（包名 Pond）下同样成立。
import bpy

# 与根 prefs.py 中 BoolProperty 一一对应（名单只维护这一份，根 prefs 从这里导入）
MODULES = (
    ("show_hierarchy", "父子级"),
    ("show_organize", "一键整理"),
    ("show_lumen", "明度检查"),
    ("show_synccheck", "同步体检"),
    ("show_c4d", "C4D 互导"),
    ("show_preset_lib", "预设库"),
    ("show_version", "版本"),
    ("show_snapshot", "快照对比"),
    ("show_cam_rig", "摄像机组"),
    ("show_palette", "色卡"),
    ("show_trace2solid", "图转立体"),
    ("show_sixproj", "六面投射"),
    ("show_lightdesk", "灯光台"),
    ("show_bakemap", "烘焙贴图"),
    ("show_splitter", "拆分物体"),
    ("show_renderlayers", "分层渲染"),
)

# 根包名（pond_bekkan / Pond / bekkan_visn，随打包版本而定）
_ROOT_PKG = __package__.split(".")[0]


def _prefs(context):
    addon = context.preferences.addons.get(_ROOT_PKG)
    return addon.preferences if addon else None


def module_enabled(key):
    """给面板类当 poll 用：总控里关掉的模块不画"""
    @classmethod
    def poll(cls, context):
        p = _prefs(context)
        return getattr(p, key, True) if p else True
    return poll
