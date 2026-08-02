# 色卡面板（逻辑在 core/palette.py）
import bpy

from ..prefs import module_enabled
from ....core.palette import _float, _active_palette


class POND_PT_palette(bpy.types.Panel):
    bl_label = "色卡"
    bl_idname = "POND_PT_palette"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_palette")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.palette_from_file", icon="IMPORT")
        col.operator("pond.palette_from_image", icon="IMAGE_RGB")
        col.operator("pond.palette_float", icon="WINDOW", depress=_float["on"])
        ts = context.tool_settings
        pal = _active_palette(context)
        if pal:
            if hasattr(self.layout, "template_palette"):
                self.layout.template_palette(ts.image_paint, "palette", color=True)
            elif len(pal.colors):
                # Blender 5.2 删掉了 template_palette,手画色块网格
                grid = self.layout.grid_flow(row_major=True, columns=8, align=True)
                for pc in pal.colors:
                    grid.prop(pc, "color", text="")
        row = self.layout.row(align=True)
        row.enabled = pal is not None or any(
            p.name.endswith("_色卡") for p in bpy.data.palettes)
        row.operator("pond.palette_delete", icon="TRASH", text="删除当前")
        row.operator("pond.palette_clear_all", icon="X", text="清空导入")


_classes = (
    POND_PT_palette,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
