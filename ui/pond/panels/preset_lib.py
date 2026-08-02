# 预设库面板 + UIList（逻辑在 core/preset_lib.py）
import bpy

from ..prefs import module_enabled


class POND_UL_lib(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop):
        kind_icon = "NODETREE" if context.window_manager.pond_lib_tab == "GEO" else "MATERIAL"
        layout.label(text=item.label, icon=kind_icon)

    def filter_items(self, context, data, propname):
        # 搜索连备注一起搜
        items = getattr(data, propname)
        pat = (self.filter_name or "").strip().lower()
        if pat:
            flags = [self.bitflag_filter_item
                     if pat in it.label.lower() or pat in it.desc.lower() else 0
                     for it in items]
        else:
            flags = [self.bitflag_filter_item] * len(items)
        order = []
        if self.use_filter_sort_alpha:
            order = bpy.types.UI_UL_list.sort_items_by_name(items, "label")
        return flags, order


class POND_PT_preset_lib(bpy.types.Panel):
    bl_label = "预设库"
    bl_idname = "POND_PT_preset_lib"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_preset_lib")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        row = layout.row(align=True)
        row.prop(wm, "pond_lib_tab", expand=True)

        row = layout.row()
        row.template_list("POND_UL_lib", "", wm, "pond_lib_items",
                          wm, "pond_lib_index", rows=4)
        col = row.column(align=True)
        col.operator("pond.lib_save", text="", icon="ADD")
        col.operator("pond.lib_delete", text="", icon="REMOVE")
        col.separator()
        col.operator("pond.lib_rename", text="", icon="GREASEPENCIL")
        col.operator("pond.lib_refresh", text="", icon="FILE_REFRESH")

        if 0 <= wm.pond_lib_index < len(wm.pond_lib_items):
            it = wm.pond_lib_items[wm.pond_lib_index]
            if it.desc:
                box = layout.box()
                box.label(text=it.desc, icon="INFO")
        layout.operator("pond.lib_apply", icon="CHECKMARK")


_classes = (
    POND_UL_lib,
    POND_PT_preset_lib,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
