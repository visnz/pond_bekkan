# 分层渲染面板（逻辑在 core/renderlayers.py）
import bpy

from ..prefs import module_enabled
from ....core.renderlayers import PREFIX


class POND_PT_renderlayers(bpy.types.Panel):
    bl_label = "分层渲染"
    bl_idname = "POND_PT_renderlayers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_renderlayers")

    def draw(self, context):
        scene = context.scene
        col = self.layout.column(align=True)
        col.operator("pond.layered_setup", icon="RENDERLAYERS")
        col.operator("pond.layered_clear", icon="X")
        n = sum(1 for vl in scene.view_layers if vl.name.startswith(PREFIX))
        if n:
            self.layout.label(text=f"现有 {n} 个分层视图层", icon="CHECKMARK")
        self.layout.label(text="有可渲染几何的集合=一层", icon="INFO")
        self.layout.label(text="灯/相机/空物体集合每层都带", icon="INFO")
        self.layout.label(text="其他层的东西只留影子和反弹", icon="INFO")


_classes = (
    POND_PT_renderlayers,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
