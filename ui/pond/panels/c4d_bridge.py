# C4D 互导面板（逻辑在 core/c4d_bridge.py）
import bpy

from ..prefs import module_enabled


class POND_PT_c4d(bpy.types.Panel):
    bl_label = "C4D 互导"
    bl_idname = "POND_PT_c4d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_c4d")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.export_c4d", icon="EXPORT")
        col.operator("pond.export_c4d_abc", icon="RENDER_ANIMATION")
        col.operator("pond.import_c4d_restore", icon="IMPORT")
        col.separator()
        col.operator("pond.export_mat_manifest", icon="MATERIAL")


_classes = (
    POND_PT_c4d,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
