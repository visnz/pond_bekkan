# 总控：模块显示开关（存在插件偏好设置里，重启不丢）
import bpy

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


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def module_enabled(key):
    """给面板类当 poll 用：总控里关掉的模块不画"""
    @classmethod
    def poll(cls, context):
        p = _prefs(context)
        return getattr(p, key, True) if p else True
    return poll


class PondPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="显示哪些模块")
        row = col.grid_flow(columns=3, align=True)
        for key, label in MODULES:
            row.prop(self, key, text=label)


# BoolProperty 动态挂上去，名单只维护一份
for _key, _label in MODULES:
    PondPreferences.__annotations__[_key] = bpy.props.BoolProperty(
        name=_label, default=True)


_classes = (PondPreferences,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
