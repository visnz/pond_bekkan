# 同步体检 + 法线体检面板（逻辑在 core/synccheck.py）
import bpy

from ..prefs import module_enabled
from ....core.synccheck import _GRP_COL, _collapsed, _undo_stack


class POND_PT_synccheck(bpy.types.Panel):
    bl_label = "同步体检"
    bl_idname = "POND_PT_synccheck"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_synccheck")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        layout.operator("pond.sync_scan", icon="VIEWZOOM")

        if not wm.pond_sync_scanned:
            return
        items = wm.pond_sync_items
        if not items:
            layout.label(text="小眼睛和渲染完全一致", icon="CHECKMARK")
            return

        # 按集合分组（保持扫描顺序，「集合本身」垫底）
        order = []
        groups = {}
        for i, it in enumerate(items):
            if it.group not in groups:
                groups[it.group] = []
                order.append(it.group)
            groups[it.group].append(i)
        if _GRP_COL in order:
            order.remove(_GRP_COL)
            order.append(_GRP_COL)

        for gname in order:
            idxs = groups[gname]
            box = layout.box()
            head = box.row(align=True)
            fold = gname in _collapsed
            op = head.operator("pond.sync_fold", text="",
                               icon="TRIA_RIGHT" if fold else "TRIA_DOWN",
                               emboss=False)
            op.group = gname
            head.label(text=f"{gname} ({len(idxs)})",
                       icon="OUTLINER_COLLECTION" if gname != _GRP_COL else "GROUP")
            op = head.operator("pond.sync_apply", text="",
                               icon="RESTRICT_VIEW_OFF")
            op.direction = "TO_RENDER"
            op.group = gname
            op = head.operator("pond.sync_apply", text="",
                               icon="RESTRICT_RENDER_OFF")
            op.direction = "TO_VIEWPORT"
            op.group = gname
            if fold:
                continue
            for i in idxs:
                it = items[i]
                row = box.row(align=True)
                op = row.operator("pond.sync_select", text=it.label,
                                  icon="RESTRICT_SELECT_OFF", emboss=False)
                op.index = i
                row.label(text=it.detail)

        col = layout.column(align=True)
        op = col.operator("pond.sync_apply", text="全部：眼睛对齐渲染",
                          icon="RESTRICT_VIEW_OFF")
        op.direction = "TO_RENDER"
        op.group = ""
        op = col.operator("pond.sync_apply", text="全部：渲染对齐眼睛",
                          icon="RESTRICT_RENDER_OFF")
        op.direction = "TO_VIEWPORT"
        op.group = ""
        col.operator("pond.sync_undo",
                     text="撤回上次对齐(%d)" % len(_undo_stack), icon="LOOP_BACK")
        col.label(text="组头小按钮=只对齐那一组", icon="INFO")


class POND_PT_normalcheck(bpy.types.Panel):
    bl_label = "法线体检"
    bl_idname = "POND_PT_normalcheck"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_synccheck"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        layout.operator("pond.normal_scan", icon="NODE_TEXTURE")
        if not wm.pond_normal_scanned:
            return
        items = wm.pond_normal_items
        if not items:
            layout.label(text="法线贴图全部 Non-Color", icon="CHECKMARK")
            return
        box = layout.box()
        for it in items:
            row = box.row()
            row.label(text=it.label, icon="IMAGE_DATA")
            row.label(text=it.detail)
        layout.operator("pond.normal_fix", icon="TOOL_SETTINGS")


_classes = (
    POND_PT_synccheck,
    POND_PT_normalcheck,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
