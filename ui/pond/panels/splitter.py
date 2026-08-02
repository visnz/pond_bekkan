# 拆分物体面板（逻辑在 core/splitter.py）
import bpy

from ..prefs import module_enabled


class POND_PT_splitter(bpy.types.Panel):
    bl_label = "拆分物体"
    bl_idname = "POND_PT_splitter"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 6
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_splitter")

    def draw(self, context):
        wm = context.window_manager
        col = self.layout.column(align=True)
        col.prop(wm, "pond_split_merge", text="先按距离焊点")
        col.operator("pond.split", text="按松散块拆开", icon="MOD_EXPLODE")
        self.layout.prop(wm, "pond_split_center", text="拆完原点各自居中")


_classes = (
    POND_PT_splitter,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
