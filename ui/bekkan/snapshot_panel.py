# 别馆模式 · 快照面板（逻辑在 core/snapshot.py，迁移自 Bekkan/STOOL_part/Snapshot.py）
# 布局与蛙灾面板统一：眼睛按钮+拍摄快照平铺一行。
import bpy

from ...core.snapshot import disp_snap, _aid


class BEKKAN_UL_snap_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop):
        layout.label(text=item.name, icon="IMAGE_DATA")


class SnapPanel(bpy.types.Panel):
    bl_label = "📸 快照"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "别馆"

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
        row.template_list(
            "BEKKAN_UL_snap_list", "", scene, "snapshot_list",
            scene, "snapshot_list_index", rows=2)
        btns = row.column(align=True)
        btns.operator("object.delete_snapshot", text="", icon="REMOVE")
        btns.operator("object.export_snapshot", text="", icon="FILE_IMAGE")

        layout.operator("object.clear_snapshot_list", text="清空")


_classes = (
    BEKKAN_UL_snap_list,
    SnapPanel,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
