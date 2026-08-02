# 蛙灾模式 · 快照对比面板（逻辑在 core/snapshot.py）
# 面板外观保持 Pond 原版；按钮已重接到合并核心（object.* 系列）。
import bpy

from ..prefs import module_enabled
from ....core.snapshot import disp_snap


class POND_UL_snaps(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop):
        layout.label(text=item.name, icon="IMAGE_DATA")


class POND_PT_snapshot(bpy.types.Panel):
    bl_label = "快照对比"
    bl_idname = "POND_PT_snapshot"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_snapshot")

    def draw(self, context):
        scene = context.scene
        showing = bool(context.area) and disp_snap.get(str(context.area.as_pointer())) is not None
        col = self.layout.column(align=True)
        col.operator("object.take_snapshot", icon="RENDER_STILL")
        col.operator("object.toggle_snapshot_display", icon="HIDE_OFF",
                     depress=showing)
        if showing:
            col.prop(scene, "slider_position", slider=True)
        row = self.layout.row()
        row.template_list("POND_UL_snaps", "", scene, "snapshot_list",
                          scene, "snapshot_list_index", rows=2)
        btns = row.column(align=True)
        btns.operator("object.delete_snapshot", text="", icon="REMOVE")
        btns.operator("object.export_snapshot", text="", icon="FILE_IMAGE")
        self.layout.label(text="Alt+右键 = 拖动分割线", icon="EVENT_ALT")
        self.layout.label(text="Ctrl+Alt+右键 = 拍快照", icon="EVENT_CTRL")


_classes = (
    POND_UL_snaps,
    POND_PT_snapshot,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
