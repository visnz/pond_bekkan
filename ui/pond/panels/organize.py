# 一键整理面板（逻辑在 core/organize.py）
import bpy

from ..prefs import module_enabled


class POND_PT_organize(bpy.types.Panel):
    bl_label = "一键整理"
    bl_idname = "POND_PT_organize"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_organize")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.purge_orphans", icon="ORPHAN_DATA")
        col.operator("pond.merge_dup_materials", icon="MATERIAL")
        col.separator()
        col.operator("pond.origin_center", icon="PIVOT_BOUNDBOX")
        col.operator("pond.origin_bottom", icon="AXIS_TOP")


_classes = (
    POND_PT_organize,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
