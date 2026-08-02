# 图转立体面板（逻辑在 core/trace2solid.py）
import bpy

from ..prefs import module_enabled


class POND_PT_trace2solid(bpy.types.Panel):
    bl_label = "图转立体"
    bl_idname = "POND_PT_trace2solid"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_trace2solid")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.trace_solid", icon="OUTLINER_OB_CURVE")
        col.label(text="logo/剪影专用,照片先转黑白", icon="INFO")


_classes = (
    POND_PT_trace2solid,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
