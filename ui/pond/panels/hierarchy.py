# 父子级面板（逻辑在 core/hierarchy.py）
import bpy

from ..prefs import module_enabled


class POND_PT_hierarchy(bpy.types.Panel):
    bl_label = "父子级"
    bl_idname = "POND_PT_hierarchy"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_hierarchy")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.group_to_parent", text="所选打组", icon="LINKED")
        col.operator("pond.group_each", text="单独每个打组")
        col.separator()
        col.operator("pond.release_up", text="释放到上级", icon="UNLINKED")
        col.operator("pond.extract", text="拎出(带全家)")
        col.operator("pond.extract_delete", text="拎出并删除原层级", icon="TRASH")
        col.separator()
        col.operator("pond.select_parents", text="选择所有父级", icon="RESTRICT_SELECT_OFF")


_classes = (
    POND_PT_hierarchy,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
