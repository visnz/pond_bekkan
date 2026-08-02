# 版本面板（逻辑在 core/version.py）
import os
import bpy

from ..prefs import module_enabled


class POND_PT_version(bpy.types.Panel):
    bl_label = "版本"
    bl_idname = "POND_PT_version"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_version")

    def draw(self, context):
        col = self.layout.column(align=True)
        if bpy.data.filepath:
            stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
            col.label(text=stem, icon="FILE_BLEND")
        col.operator("pond.save_version", icon="DUPLICATE")
        col.operator("pond.sync_output_version", icon="OUTPUT")


_classes = (
    POND_PT_version,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
