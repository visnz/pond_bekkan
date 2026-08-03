# 别馆模式 · 工具箱五面板（迁移自 Bekkan/STOOL_part/STOOL.py 的 UI 部分）
# 按钮指向 core 的 op；选择父级已从废弃的 object.select_parent_visn 重接到
# pond.select_parents（语义等价，见 合并对照清单.md 第 4 节）。
import bpy

from .prefs import module_enabled


class BekkanPanelBase:
    """所有面板共用：3D视图 N 面板「别馆」页，默认折叠"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '别馆'
    bl_options = {'DEFAULT_CLOSED'}


class VIEW3D_PT_parents_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_parents_visn"
    bl_label = "👪 上下级"

    @classmethod
    def poll(cls, context):
        return module_enabled("show_parents")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.parent_to_empty_visn", icon='EMPTY_AXIS')
        col.operator("object.parent_to_empty_anim_visn", text="单体迁移动画 到上级", icon='EMPTY_AXIS')
        col.operator("object.parent_to_empty_visn_individual", icon='EMPTY_DATA')
        col.operator("pond.select_parents", text="选择所有上级", icon='SELECT_SET')
        col.operator("object.release_all_children_to_subparent_visn", icon='UNLINKED')
        col.operator("object.solo_pick_visn", icon='EXPORT')
        col.operator("object.solo_pick_delete_visn", icon='TRASH')
        col.operator("camera.create_focus_object", icon='VIEW_CAMERA')


class VIEW3D_PT_stage_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_stage_visn"
    bl_label = "🏗 搭建类"

    @classmethod
    def poll(cls, context):
        return module_enabled("show_stage")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.fast_camera_visn", icon='CAMERA_DATA')
        col.operator("object.cspzt_camera_visn", icon='VIEW_CAMERA')
        col.operator("object.add_light_with_constraint", icon='LIGHT_SPOT')
        col.operator("object.delete_empty_null_visn", icon='X')


class VIEW3D_PT_texture_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_texture_visn"
    bl_label = "🖼 贴图索引"

    @classmethod
    def poll(cls, context):
        return module_enabled("show_texture")

    def draw(self, context):
        layout = self.layout
        props = context.scene.texture_search_props
        layout.operator("index.build_texture_index", icon='FILE_REFRESH')
        layout.label(text="选择要查找的贴图:")
        layout.prop_search(props, "texture_search_image", bpy.data, "images", text="")
        layout.operator("index.find_materials", icon='VIEWZOOM')
        layout.operator("index.select_objects_with_texture",
                        text="选中该贴图的材质对象", icon='OBJECT_DATA')


class VIEW3D_PT_anime_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_anime_visn"
    bl_label = "🎞 动画类"

    @classmethod
    def poll(cls, context):
        return module_enabled("show_anime")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.add_noise_anim", text="Wiggle（添加/更新Noise）", icon='MOD_NOISE')
        col.operator("object.remove_all_animations_visn", icon='CANCEL')


class VIEW3D_PT_render_preset_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_render_preset_visn"
    bl_label = "🎬 渲染预设"

    @classmethod
    def poll(cls, context):
        return module_enabled("show_render_preset")

    def draw(self, context):
        layout = self.layout
        layout.operator("render.create_presets", text="创建预设", icon='SETTINGS')
        layout.operator("render.sync_from_scene",
                        text="从其他 Scene 同步渲染设置", icon='FILE_REFRESH')
        props = context.scene.render_preset_settings
        layout.prop(props, "use_absolute_path", text="使用绝对路径", toggle=True)

        box = layout.box()
        row = box.row(align=True)
        row.operator("render.apply_preset", text="HD").preset_type = 'HD'
        row.operator("render.apply_preset", text="Style").preset_type = 'Style'
        row = box.row(align=True)
        row.operator("render.apply_preset", text="prev").preset_type = 'prev'
        row.operator("render.apply_preset", text="demo").preset_type = 'demo'

        layout.separator()
        layout.operator("wm.open_project_folder_visn",
                        text="打开工程所在文件夹", icon='FILE_FOLDER')
        layout.operator("render.open_output_folder",
                        text="打开输出文件夹", icon='FILE_FOLDER')
        layout.operator("render.open_addon_folder",
                        text="打开插件所在文件夹", icon='FILE_FOLDER')


# 面板按注册顺序在侧边栏中排列
_classes = (
    VIEW3D_PT_parents_visn,
    VIEW3D_PT_stage_visn,
    VIEW3D_PT_texture_visn,
    VIEW3D_PT_anime_visn,
    VIEW3D_PT_render_preset_visn,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
