# 明度检查面板（逻辑在 core/lumen.py）
import bpy

from ..prefs import module_enabled
from ....core.lumen import _get_state


class POND_PT_lumen(bpy.types.Panel):
    bl_label = "明度检查"
    bl_idname = "POND_PT_lumen"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_lumen")

    def draw(self, context):
        wm = context.window_manager
        state = _get_state(wm)
        active = state.get("mode") if state else None
        col = self.layout.column(align=True)
        col.operator("pond.lumen_clay", icon="SHADING_SOLID",
                     depress=(active == "CLAY"))
        col.operator("pond.lumen_light", icon="LIGHT_SUN",
                     depress=(active == "LIGHT"))
        col.operator("pond.lumen_bw", icon="IMAGE_ZDEPTH",
                     depress=(active == "BW"))
        if active:
            col.separator()
            col.operator("pond.lumen_restore", icon="LOOP_BACK")


_classes = (
    POND_PT_lumen,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
