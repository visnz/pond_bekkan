# 别馆模式 · 快照面板（逻辑在 core/snapshot.py，迁移自 Bekkan/STOOL_part/Snapshot.py）
import bpy


class BEKKAN_UL_snap_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop):
        layout.label(text=item.name)


class SnapPanel(bpy.types.Panel):
    bl_label = "📸 快照"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "别馆"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.operator("object.take_snapshot", text="拍快照")
        layout.operator("object.toggle_snapshot_display", text="对比")
        layout.prop(scene, "slider_position", slider=True)

        layout.template_list(
            "BEKKAN_UL_snap_list", "", scene, "snapshot_list",
            scene, "snapshot_list_index", rows=2)
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
