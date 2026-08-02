# 蛙灾模式 · 快照对比面板（逻辑在 core/snapshot.py）
# 布局与别馆面板统一：眼睛按钮+拍摄快照平铺一行。
import bpy

from ..prefs import module_enabled
from ....core.snapshot import disp_snap, _aid


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
        layout = self.layout
        scene = context.scene

        showing = bool(context.area) and disp_snap.get(_aid(context.area)) is not None

        # 眼睛按钮 + 拍摄快照 平铺一行
        row = layout.row(align=True)
        row.operator("object.toggle_snapshot_display", text="",
                     icon="HIDE_OFF", depress=showing)
        row.operator("object.take_snapshot", text="拍摄快照")

        layout.prop(scene, "slider_position", slider=True)

        # 快照列表 + 删除/导出按钮
        row = layout.row()
        row.template_list("POND_UL_snaps", "", scene, "snapshot_list",
                          scene, "snapshot_list_index", rows=2)
        btns = row.column(align=True)
        btns.operator("object.delete_snapshot", text="", icon="REMOVE")
        btns.operator("object.export_snapshot", text="", icon="FILE_IMAGE")

        layout.operator("object.clear_snapshot_list", text="清空")


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
