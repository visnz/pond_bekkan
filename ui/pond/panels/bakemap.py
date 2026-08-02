# 烘焙贴图面板（逻辑在 core/bakemap.py）
import bpy

from ..prefs import module_enabled


class POND_PT_bakemap(bpy.types.Panel):
    bl_label = "烘焙贴图"
    bl_idname = "POND_PT_bakemap"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 5
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_bakemap")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        row = layout.row(align=True)
        row.prop(wm, "pond_bake_res", text="")
        row.prop(wm, "pond_bake_margin")
        row = layout.row(align=True)
        row.prop(wm, "pond_bake_color", text="基础色", toggle=True)
        row.prop(wm, "pond_bake_rough", text="糙度", toggle=True)
        row.prop(wm, "pond_bake_metal", text="金属度", toggle=True)
        row = layout.row(align=True)
        row.prop(wm, "pond_bake_normal", text="法线", toggle=True)
        row.prop(wm, "pond_bake_bump", text="凹凸", toggle=True)
        row.prop(wm, "pond_bake_alpha", text="透明度", toggle=True)
        row = layout.row(align=True)
        row.prop(wm, "pond_bake_emit", text="自发光", toggle=True)
        row.prop(wm, "pond_bake_ao", text="AO", toggle=True)
        layout.prop(wm, "pond_bake_uvmode", text="排UV")
        layout.operator("pond.bakemap", icon="RENDER_STILL")
        row = layout.row(align=True)
        row.operator("pond.bakemap_use_baked", icon="TEXTURE")
        row.operator("pond.bakemap_use_orig", icon="LOOP_BACK")
        layout.label(text="图存在工程旁 textures/ 里", icon="INFO")


_classes = (
    POND_PT_bakemap,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
