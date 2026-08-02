# 摄像机组面板（逻辑在 core/stage.py）
import bpy

from ..prefs import module_enabled


class POND_PT_cam_rig(bpy.types.Panel):
    bl_label = "摄像机组"
    bl_idname = "POND_PT_cam_rig"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_cam_rig")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.cam_rig_build", icon="CAMERA_DATA")
        col.label(text="对准名字可以自己改", icon="INFO")


_classes = (
    POND_PT_cam_rig,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
