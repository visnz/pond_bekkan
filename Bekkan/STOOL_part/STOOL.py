import bpy  # type: ignore
from bpy.props import PointerProperty  # type: ignore
from .STOOL_part.ParentsOps import SoloPick, SoloPick_delete, P2E, P2E_individual, SelectParent, RAQtoSubparent, CAMERA_OT_create_focus_object, P2E_anim_migrate
from .STOOL_part.StageOps import DeleteEmptyNull, FastCentreCamera, CSPZT_Camera, AddLightWithConstraint, OpenProjectFolderOperator
from .STOOL_part.AnimeOps import OBJECT_OT_add_noise_anim, NoiseAnimSettings, RemoveAllAnimations
from .STOOL_part.RenderOps import RenderPresetSettings, RENDER_OT_create_presets, RENDER_OT_apply_preset, RENDER_OT_open_output_folder, RENDER_OT_open_addon_folder, RENDER_OT_sync_from_scene
from .STOOL_part.TextureOps import TextureSearchProperties, INDEX_OT_build_texture_index, INDEX_OT_find_materials, INDEX_OT_select_objects_with_texture
from .STOOL_part.AddonManager import register as addonmanager_register, unregister as addonmanager_unregister
from .STOOL_part.Analyzer import register as analyzer_register, unregister as analyzer_unregister


class BekkanPanelBase:
    """所有面板共用：3D视图 N 面板「别馆」页，默认折叠"""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '别馆'
    bl_options = {'DEFAULT_CLOSED'}


class VIEW3D_PT_parents_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_parents_visn"
    bl_label = "👪 上下级"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.parent_to_empty_visn", icon='EMPTY_AXIS')
        col.operator("object.parent_to_empty_anim_visn", text="单体迁移动画 到上级", icon='EMPTY_AXIS')
        col.operator("object.parent_to_empty_visn_individual", icon='EMPTY_DATA')
        col.operator("object.select_parent_visn", icon='SELECT_SET')
        col.operator("object.release_all_children_to_subparent_visn", icon='UNLINKED')
        col.operator("object.solo_pick_visn", icon='EXPORT')
        col.operator("object.solo_pick_delete_visn", icon='TRASH')
        col.operator("camera.create_focus_object", icon='VIEW_CAMERA')


class VIEW3D_PT_stage_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_stage_visn"
    bl_label = "🏗 搭建类"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.fast_camera_visn", icon='CAMERA_DATA')
        col.operator("object.cspzt_camera_visn", icon='VIEW_CAMERA')
        col.operator("object.add_light_with_constraint", icon='LIGHT_SPOT')
        col.operator("object.delete_empty_null_visn", icon='X')


class VIEW3D_PT_texture_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_texture_visn"
    bl_label = "🖼 贴图索引"

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

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.add_noise_anim", text="Wiggle（添加/更新Noise）", icon='MOD_NOISE')
        col.operator("object.remove_all_animations_visn", icon='CANCEL')


class VIEW3D_PT_render_preset_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_render_preset_visn"
    bl_label = "🎬 渲染预设"

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
allClass = [
    VIEW3D_PT_parents_visn,
    VIEW3D_PT_stage_visn,
    VIEW3D_PT_texture_visn,
    VIEW3D_PT_anime_visn,
    VIEW3D_PT_render_preset_visn,
    RenderPresetSettings,
    RemoveAllAnimations,
    FastCentreCamera,
    CSPZT_Camera,
    SoloPick,
    SoloPick_delete,
    SelectParent,
    RAQtoSubparent,
    OpenProjectFolderOperator,
    AddLightWithConstraint,
    P2E,
    CAMERA_OT_create_focus_object,
    P2E_individual,
    P2E_anim_migrate,
    OBJECT_OT_add_noise_anim,
    NoiseAnimSettings,
    DeleteEmptyNull,
    RENDER_OT_create_presets,
    RENDER_OT_apply_preset,
    RENDER_OT_open_output_folder,
    RENDER_OT_open_addon_folder,
    RENDER_OT_sync_from_scene,
    TextureSearchProperties,
    INDEX_OT_build_texture_index,
    INDEX_OT_find_materials,
    INDEX_OT_select_objects_with_texture,
]


def register():
    # 工程分析注册在最前，使其面板排在「别馆」页快照之后、其余工具箱之前
    analyzer_register()
    for cls in allClass:
        bpy.utils.register_class(cls)
    bpy.types.Scene.render_preset_settings = PointerProperty(type=RenderPresetSettings)
    bpy.types.Scene.texture_search_props = PointerProperty(type=TextureSearchProperties)
    # 朋友的插件管理器注册在最后，使其面板排在「别馆」页最下方
    addonmanager_register()


def unregister():
    # 先恢复被管理器移动过的面板，再注销本插件类
    addonmanager_unregister()
    for cls in allClass:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.render_preset_settings
    del bpy.types.Scene.texture_search_props
    # 工程分析最后注销（与注册顺序相反）
    analyzer_unregister()


if __name__ == "__main__":
    register()
