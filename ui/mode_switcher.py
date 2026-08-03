# 快速模式切换：仅合体版注册，显示在 Blender 窗口底部状态栏最右侧。
# 不在 N 面板里占「池塘/别馆」两个 tab，也避免切换时注销当前 operator 导致崩溃。
import bpy

from .. import _build_mode


_root_pkg = __package__.split(".")[0]


class POND_BEKKAN_OT_switch_mode(bpy.types.Operator):
    bl_idname = "pond_bekkan.switch_mode"
    bl_label = "切换模式"
    bl_options = {'REGISTER'}

    mode: bpy.props.EnumProperty(
        name="目标模式",
        items=[
            ("POND", "蛙灾模式", ""),
            ("BEKKAN", "别馆模式", ""),
        ],
    )

    def execute(self, context):
        prefs = context.preferences.addons[_root_pkg].preferences
        prefs.mode = self.mode
        return {'FINISHED'}


def _draw_mode_switcher_status(self, context):
    """绘制在 STATUSBAR_HT_header 最右侧；仅合体版可见。"""
    if _build_mode.BUILD_MODE != "combined":
        return
    try:
        prefs = context.preferences.addons[_root_pkg].preferences
    except (KeyError, AttributeError):
        return
    layout = self.layout
    layout.alignment = 'RIGHT'
    row = layout.row(align=True)
    row.scale_x = 0.9
    if prefs.mode == "POND":
        row.label(text="当前: 蛙灾")
        op = row.operator(
            "pond_bekkan.switch_mode",
            text="切到别馆",
            icon='FILE_REFRESH',
        )
        op.mode = "BEKKAN"
    else:
        row.label(text="当前: 别馆")
        op = row.operator(
            "pond_bekkan.switch_mode",
            text="切到蛙灾",
            icon='FILE_REFRESH',
        )
        op.mode = "POND"


_registered = False


def register():
    global _registered
    if _registered or _build_mode.BUILD_MODE != "combined":
        return
    bpy.utils.register_class(POND_BEKKAN_OT_switch_mode)
    bpy.types.STATUSBAR_HT_header.append(_draw_mode_switcher_status)
    _registered = True


def unregister():
    global _registered
    if not _registered:
        return
    try:
        bpy.types.STATUSBAR_HT_header.remove(_draw_mode_switcher_status)
    except RuntimeError:
        pass
    try:
        bpy.utils.unregister_class(POND_BEKKAN_OT_switch_mode)
    except RuntimeError:
        pass
    _registered = False
