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
        col.operator("camera.create_focus_object", icon='VIEW_CAMERA')


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


class VIEW3D_PT_anime_autosway_visn(BekkanPanelBase, bpy.types.Panel):
    """AutoSway 骨骼摆动（合并自独立插件 autosway.py），折叠进动画类面板，用时再展开"""
    bl_idname = "VIEW3D_PT_anime_autosway_visn"
    bl_label = "AutoSway（骨骼摆动）"
    bl_parent_id = "VIEW3D_PT_anime_visn"
    bl_options = {'DEFAULT_CLOSED'}
    # 不用 bl_context = "posemode"：那样非姿态模式下整个子面板会直接消失，
    # 展开的小三角看起来像是丢了。改成始终可展开，非姿态模式下展开只给提示。

    def draw(self, context):
        layout = self.layout

        if context.mode != 'POSE':
            layout.label(text="需要在姿态模式(Pose Mode)下使用", icon='INFO')
            return

        scene = context.scene
        props = scene.autosway_settings

        box = layout.box()
        box.label(text="基本参数:")
        box.prop(props, "my_enum", text="轴向")
        box.prop(props, "my_swayAngle")
        box.prop(props, "my_incrementalAngle")
        box.prop(props, "my_loopFrame")
        box.prop(props, "my_staggeredFrames")
        box.prop(props, "my_offsetFrame")

        col = layout.column(align=True)
        col.operator("autosway.add_sway", icon='DRIVER')
        col.operator("autosway.clear_sway", icon='TRASH')

        self._draw_control_groups(layout, scene, props)

    def _draw_control_groups(self, layout, scene, props):
        control_groups = []
        for key in scene.keys():
            if key.startswith("autosway_Control_Group_") and key.endswith("_angle"):
                control_groups.append(key[len("autosway_"):-len("_angle")])
        control_groups.sort(key=lambda x: int(x.split("_")[-1]))

        if not control_groups:
            return

        box = layout.box()
        box.label(text="控制组管理:")

        row = box.row()
        for i, group in enumerate(control_groups):
            prop_group_name = f"autosway_{group}"
            display_name = scene.get(f"{prop_group_name}_display_name", group)
            op = row.operator("autosway.select_control_group", text=display_name,
                               depress=(props.active_control_group == prop_group_name))
            op.group_name = prop_group_name
            if len(control_groups) > 3 and (i + 1) % 3 == 0:
                row = box.row()

        if not props.active_control_group:
            return

        self._draw_control_group_params(box, scene, props.active_control_group)

        rename_box = box.box()
        rename_box.label(text="重命名控制组:")
        row = rename_box.row()
        row.prop(props, "rename_group_name", text="")
        row.operator("autosway.rename_control_group", text="重命名", icon='SORTALPHA')

        box.operator("autosway.keyframe_all_parameters", icon='KEYINGSET')
        box.operator("autosway.remove_control_group", icon='TRASH')

    def _draw_control_group_params(self, layout, scene, prop_group_name):
        box = layout.box()
        box.label(text="动态参数:")

        params = (
            ("angle", "摆动角度", -10, 10),
            ("incremental", "递增角度", -10, 10),
            ("loop", "循环帧数", 10, 200),
            ("stagger", "错帧量", 5, 20),
            ("offset", "帧偏移", 0, 200),
        )

        for param, label, min_val, max_val in params:
            prop_path = f"{prop_group_name}_{param}"
            if prop_path not in scene:
                continue

            row = box.row()
            row.label(text=label)
            row.label(text=f"{scene[prop_path]:.2f}")

            step = 0.1 if param in ("angle", "incremental") else 1
            op_minus = row.operator("autosway.adjust_parameter", text="", icon='REMOVE')
            op_minus.parameter_path = prop_path
            op_minus.adjustment = -step
            op_plus = row.operator("autosway.adjust_parameter", text="", icon='ADD')
            op_plus.parameter_path = prop_path
            op_plus.adjustment = step
            op_key = row.operator("autosway.keyframe_parameter", text="", icon='KEY_HLT')
            op_key.parameter_path = prop_path

            row = box.row()
            row.prop(scene, f'["{prop_path}"]', text=label, slider=False)


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
    VIEW3D_PT_anime_autosway_visn,
    VIEW3D_PT_render_preset_visn,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
