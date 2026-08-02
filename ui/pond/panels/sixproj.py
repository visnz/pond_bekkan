# 六面投射面板（逻辑在 core/sixproj.py）
import bpy

from ..prefs import module_enabled
from ....core.sixproj import FACES, missing_faces


class POND_PT_sixproj(bpy.types.Panel):
    bl_label = "六面投射"
    bl_idname = "POND_PT_sixproj"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_sixproj")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.pond_sixway

        # ① 贴图：文件夹一键识别，缺哪张才露哪张
        box = layout.box()
        row = box.row(align=True)
        row.prop(settings, "source_dir", text="")
        row.operator("pond.swb_scan_folder", text="", icon="FILE_REFRESH")
        miss = missing_faces(settings)
        if miss:
            for key, label in miss:
                r = box.row()
                r.alert = True
                r.prop(settings, f"{key}_path", text=label)
        else:
            row = box.row(align=True)
            row.label(text="六张图已就位", icon="CHECKMARK")
            row.prop(settings, "show_paths", text="",
                     icon="TRIA_DOWN" if settings.show_paths else "TRIA_LEFT",
                     emboss=False)
            if settings.show_paths:
                for key, label in FACES:
                    box.prop(settings, f"{key}_path", text=label)

        # 面选项卡：点谁调谁，控件只摊开当前这一面的
        row = box.row(align=True)
        row.prop(settings, "active_face", expand=True)
        key = settings.active_face
        sub = box.column(align=True)
        r = sub.row(align=True)
        r.prop(settings, f"{key}_rotation", text="角度")
        op = r.operator("pond.swb_view_face", text="", icon="RESTRICT_VIEW_OFF")
        op.face_key = key
        r = sub.row(align=True)
        r.prop(settings, f"{key}_offset_u", text="U 移")
        r.prop(settings, f"{key}_offset_v", text="V 移")
        r = sub.row(align=True)
        r.prop(settings, f"{key}_scale_u", text="U 缩")
        r.prop(settings, f"{key}_scale_v", text="V 缩")
        r = sub.row(align=True)
        r.prop(settings, f"{key}_flip_u", text="水平翻", toggle=True)
        r.prop(settings, f"{key}_flip_v", text="垂直翻", toggle=True)

        # ② 投射
        box = layout.box()
        row = box.row(align=True)
        row.prop(settings, "thickness_axis")
        row.prop(settings, "length_axis")
        box.prop(settings, "blend_power")
        box.operator("pond.swb_setup", icon="MATERIAL")
        box.operator("pond.swb_show_source", icon="HIDE_OFF")

        # ③ 烘焙
        box = layout.box()
        row = box.row(align=True)
        row.prop(settings, "final_uv_name", text="")
        row.prop(settings, "use_existing_uv", text="沿用UV", toggle=True)
        box.operator("pond.swb_final_uv", icon="UV")
        row = box.row(align=True)
        row.prop(settings, "resolution", text="")
        row.prop(settings, "margin")
        box.prop(settings, "output_dir", text="")
        box.prop(settings, "output_name", text="")
        row = box.row(align=True)
        row.prop(settings, "show_matopts", text="材质微调",
                 icon="TRIA_DOWN" if settings.show_matopts else "TRIA_RIGHT",
                 emboss=False)
        if settings.show_matopts:
            col = box.column(align=True)
            col.prop(settings, "roughness")
            col.prop(settings, "sss_weight")
            col.prop(settings, "coat_weight")
            col.prop(settings, "bump_strength")
        box.operator("pond.swb_bake", icon="RENDER_STILL")
        box.operator("pond.swb_show_final", icon="CHECKMARK")


_classes = (
    POND_PT_sixproj,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
