# 别馆模式 · 工具箱五面板（迁移自 Bekkan/STOOL_part/STOOL.py 的 UI 部分）
# 按钮指向 core 的 op；选择父级已从废弃的 object.select_parent_visn 重接到
# pond.select_parents（语义等价，见 合并对照清单.md 第 4 节）。
import bpy
import json

from .prefs import module_enabled
from ...core import breath
from ...core import skirt_autosway


def _size_report_tab_changed(self, context):
    self.report_page = 1


class BEKKAN_OT_file_size_report(bpy.types.Operator):
    bl_idname = 'wm.file_size_report_visn'
    bl_label = '文件体积检查报告'
    bl_description = '查看上次文件体积检查的占比和数据排名'
    bl_options = {'INTERNAL'}

    report_json: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    report_tab: bpy.props.EnumProperty(name='内容', items=(
        ('SUMMARY', '占比概览', ''), ('IMAGE', '贴图', ''),
        ('GEOMETRY', '几何', ''), ('OTHER', '其他数据', ''),
        ('EXTERNAL', '外部图片', ''),
    ), default='SUMMARY', options={'SKIP_SAVE'}, update=_size_report_tab_changed)
    report_page: bpy.props.IntProperty(name='页码', default=1, min=1, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        from ...core.file_size_audit import last_report
        report = last_report()
        if report is None or report['filepath'] != bpy.data.filepath:
            self.report({'INFO'}, '请先检查当前文件的体积')
            return {'CANCELLED'}
        self.report_json = json.dumps(report, ensure_ascii=False)
        return context.window_manager.invoke_popup(self, width=1050)

    def draw(self, context):
        import textwrap
        from ...core.file_size_audit import format_bytes
        report = json.loads(self.report_json)
        layout = self.layout
        header = layout.box()
        row = header.row()
        row.scale_y = 1.5
        row.label(text=f'文件体积：{format_bytes(report["disk_bytes"])}', icon='FILE_BLEND')
        row.label(text='已压缩保存' if report['compressed'] else '未压缩保存')
        header.label(text=report['filepath'])
        if report['compressed']:
            header.label(text=f'压缩前 {format_bytes(report["raw_bytes"])}；以下占比按压缩前的实际数据计算')
        else:
            header.label(text='以下占比按最后保存的文件计算')
        if report['dirty'] or bpy.data.is_dirty:
            row = header.row()
            row.alert = True
            row.label(text='当前有未保存改动：体积来自最后保存版本，引用与拓扑信息来自当前工程', icon='INFO')
        layout.prop(self, 'report_tab', expand=True)
        if self.report_tab == 'SUMMARY':
            box = layout.box()
            for category in report['categories']:
                row = box.row()
                split = row.split(factor=0.78)
                split.progress(factor=category['percent'] / 100, type='BAR',
                               text=f'{category["label"]}  {category["percent"]:.1f}%')
                split.label(text=format_bytes(category['bytes']))
            layout.label(text='提交前可检查：大贴图分辨率 / 重复图片 / 无实际引用的数据 / 不需要的 UV、属性及形态键')
            layout.label(text='几何按已保存数据计算，共用网格只计一份；包含 UV、属性和形态键。')
            layout.label(text='外部图片不计入 .blend 体积；需要随工程提交时，可在“外部图片”页查看。')
        else:
            if self.report_tab == 'EXTERNAL':
                entries = report['externals']
                layout.label(text=f'唯一外部图片路径 {len(entries)} 个；可统计的文件合计 {format_bytes(report["external_bytes"])}')
            elif self.report_tab == 'OTHER':
                entries = [e for e in report['entries'] if e['category'] not in {'IMAGE', 'GEOMETRY'}]
            else:
                entries = [e for e in report['entries'] if e['category'] == self.report_tab]
            pages = max(1, (len(entries) + 7) // 8)
            page = min(self.report_page, pages)
            row = layout.row()
            row.label(text=f'按体积从大到小：{len(entries)} 项 / 共 {pages} 页')
            row.prop(self, 'report_page', text=f'页码（最多 {pages}）')
            for entry in entries[(page - 1) * 8:page * 8]:
                box = layout.box()
                row = box.row()
                split = row.split(factor=0.67)
                if entry['code'] == 'ME':
                    split.operator('wm.select_size_mesh_visn', text=entry['name'], icon='MESH_DATA',
                                   emboss=False).mesh_name = entry['name']
                else:
                    split.label(text=entry['name'], icon='IMAGE_DATA' if entry['code'] == 'IM' else 'FILE')
                values = split.row()
                values.label(text=format_bytes(entry['bytes']))
                if self.report_tab != 'EXTERNAL':
                    values.label(text=f'{entry["percent"]:.2f}%')
                for line in textwrap.wrap(entry['detail'], width=90):
                    box.label(text=line)
            if not entries:
                layout.label(text='没有这一类数据', icon='CHECKMARK')
        layout.label(text='这是手动检查快照。修改并保存后再次检查；报告不会自动清理或修改工程。', icon='INFO')

    def execute(self, context):
        return {'FINISHED'}


class BEKKAN_OT_workspace_setup_report(bpy.types.Operator):
    bl_idname = 'wm.workspace_setup_report_visn'
    bl_label = 'Setup 执行报告'
    bl_description = '查看上次 setup 实际修改的设置、原本一致的设置和场景处理结果'
    bl_options = {'INTERNAL'}

    report_json: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    report_tab: bpy.props.EnumProperty(name='报告内容', items=(
        ('CHANGED', '本次修改', '显示运行前与运行后的具体设置值'),
        ('UNCHANGED', '原本一致', '这些设置运行前就已符合 setup'),
        ('SCENE', '场景处理', '查看新增、保留和跳过的内容'),
    ), default='CHANGED', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not self.report_json:
            from ...core.workspace_setup import last_setup_report
            report = last_setup_report(context.scene)
            if report is None:
                self.report({'INFO'}, '当前场景还没有 setup 执行记录')
                return {'CANCELLED'}
            self.report_json = json.dumps(report, ensure_ascii=False)
        report = json.loads(self.report_json)
        if not report['changed'] and self.report_tab == 'CHANGED':
            self.report_tab = 'SCENE' if any(action['status'] != 'PRESERVED'
                                           for action in report['scene_actions']) else 'UNCHANGED'
        return context.window_manager.invoke_popup(self, width=960)

    def draw(self, context):
        report = json.loads(self.report_json)
        layout = self.layout
        header = layout.box()
        row = header.row()
        row.scale_y = 1.6
        row.label(text='工作区 Setup · 执行结果', icon='CHECKMARK')
        header.label(text=f"场景识别：{report['mode']}")
        row = header.row()
        row.label(text=f"修改 {len(report['changed'])} 项设置", icon='FILE_REFRESH')
        row.label(text=f"原本一致 {len(report['unchanged'])} 项", icon='CHECKMARK')
        added = sum(action['status'] != 'PRESERVED' for action in report['scene_actions'])
        row.label(text=f'场景操作 {added} 项', icon='ADD')
        layout.prop(self, 'report_tab', expand=True)
        box = layout.box()
        if self.report_tab == 'SCENE':
            for action in report['scene_actions']:
                row = box.row()
                split = row.split(factor=0.17)
                split.label(text=action['label'], icon='CHECKMARK'
                            if action['status'] == 'PRESERVED' else 'ADD')
                split.label(text=action['detail'])
        else:
            entries = report['changed' if self.report_tab == 'CHANGED' else 'unchanged']
            if not entries:
                box.label(text='没有需要修改的设置', icon='CHECKMARK')
            group = None
            group_order = ('Eevee', 'Cycles', '通用', '色彩', '输出', '外部数据')
            for entry in sorted(entries, key=lambda entry: group_order.index(entry['group'])):
                if group != entry['group']:
                    group = entry['group']
                    box.separator(factor=0.5)
                    box.label(text=group)
                row = box.row()
                split = row.split(factor=0.4)
                split.label(text=entry['label'])
                if self.report_tab == 'CHANGED':
                    values = split.row()
                    values.label(text=entry['old'])
                    values.label(text='→')
                    values.label(text=entry['new'])
                else:
                    split.label(text=entry['new'], icon='CHECKMARK')
        layout.label(text='这是本次运行时的记录。关闭后可用 setup 旁的 ⓘ 按钮重新查看。', icon='INFO')

    def execute(self, context):
        return {'FINISHED'}


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
        row = col.row(align=True)
        row.operator('view3d.setup_workspace_visn', icon='SETTINGS')
        row.operator('wm.workspace_setup_report_visn', text='', icon='INFO')
        col.separator()
        col.operator("object.fast_camera_visn", icon='CAMERA_DATA')
        col.operator("object.cspzt_camera_visn", icon='VIEW_CAMERA')
        from ...core.stage import camera_space_enabled
        camera_mode = camera_space_enabled(context.scene)
        row = col.row(align=True)
        row.alert = camera_mode
        row.operator('view3d.toggle_camera_space_visn',
                     text='● 视角空间编辑中 · 点击恢复' if camera_mode
                     else '开启摄像机视角空间编辑',
                     icon='VIEW_CAMERA', depress=camera_mode)
        if camera_mode:
            col.label(text='当前：View 坐标系 / 3D Cursor 枢轴点', icon='INFO')
        elif (context.scene.transform_orientation_slots[0].type == 'VIEW'
              and context.scene.tool_settings.transform_pivot_point == 'CURSOR'):
            col.label(text='当前是 View / 3D Cursor，但没有恢复记录', icon='ERROR')
        col.operator("object.delete_empty_null_visn", icon='X')
        col.operator("camera.create_focus_object", icon='VIEW_CAMERA')
        col.operator("object.checkerboard_layout_visn", icon='MESH_GRID')
        col.operator("object.legacy_fbx_import_visn", icon='IMPORT')
        row = col.row(align=True)
        row.operator("object.anchor_to_top_visn", text="锚点到顶部中心", icon='ANCHOR_TOP')
        row.operator("object.anchor_to_bottom_visn", text="锚点到底部中心", icon='ANCHOR_BOTTOM')
        col.operator("object.clear_all_fake_users_visn", icon='X')
        col.separator()
        row = col.row(align=True)
        row.operator('wm.audit_file_size_visn', icon='FILE_BLEND')
        from ...core.file_size_audit import last_report
        report = last_report()
        info = row.row(align=True)
        info.enabled = report is not None and report['filepath'] == bpy.data.filepath
        info.operator('wm.file_size_report_visn', text='', icon='INFO')
        props = context.scene.visibility_audit
        col.operator('view3d.check_visibility_visn', icon='VIEWZOOM')
        col.prop(props, 'exclusions', text='排除')
        if props.has_scan:
            box = self.layout.box()
            box.label(text=f'上次检查：{len(props.results)} 个不一致',
                      icon='ERROR' if props.results else 'CHECKMARK')
            box.label(text=f'视图层：{props.scanned_layer}')
            if props.exclusions != props.scanned_exclusions or context.view_layer.name != props.scanned_layer:
                box.label(text='排除项或视图层已更改，请重新检查', icon='INFO')
            if props.results:
                row = box.row()
                row.label(text='点击名称定位；右侧为检查时状态')
                box.template_list('BEKKAN_UL_visibility_audit', '', props, 'results',
                                  props, 'index', rows=min(6, len(props.results)))
            box.label(text=f'已排除：吸光体 {props.ignored_absorbers} / 关键词 {props.ignored_keywords}')
            box.label(text='调整可见性后，请再次点击检查')


class BEKKAN_UL_visibility_audit(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index, flt_flag=0):
        obj = item.object
        if obj is None:
            layout.label(text='对象已删除，请重新检查', icon='INFO')
            return
        row = layout.row(align=True)
        split = row.split(factor=0.62, align=True)
        op = split.operator('view3d.activate_visibility_result_visn', text=obj.name, emboss=False)
        op.object_name = obj.name
        states = split.row(align=True)
        states.label(text='视', icon='HIDE_OFF' if item.viewport_visible else 'HIDE_ON')
        states.label(text='渲', icon='RESTRICT_RENDER_OFF' if item.render_visible else 'RESTRICT_RENDER_ON')


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


class VIEW3D_PT_rig_animation_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = 'VIEW3D_PT_rig_animation_visn'
    bl_label = '🦴 绑定动画'

    @classmethod
    def poll(cls, context):
        return module_enabled('show_rig_animation')

    def draw(self, context):
        col = self.layout.column(align=True)
        col.enabled = context.mode == 'POSE' and context.active_object is not None and context.active_object.type == 'ARMATURE'
        col.operator('pose.swap_limb_pose_visn', text='左右手姿态交换', icon='ARMATURE_DATA').part = 'ARMS'
        col.operator('pose.swap_limb_pose_visn', text='左右腿姿态交换', icon='ARMATURE_DATA').part = 'LEGS'
        if not col.enabled:
            self.layout.label(text='请选中骨架并进入姿态模式', icon='INFO')


class VIEW3D_PT_anime_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_anime_visn"
    bl_label = "动画工具"
    bl_parent_id = "VIEW3D_PT_rig_animation_visn"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return module_enabled("show_rig_animation")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.add_noise_anim", text="Wiggle（添加/更新Noise）", icon='MOD_NOISE')
        col.operator("object.remove_all_animations_visn", icon='CANCEL')
        col.operator('object.sync_armature_psr_visn')


class VIEW3D_PT_breath_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_breath_visn"
    bl_label = "呼吸 · 体态与NLA层"
    bl_parent_id = "VIEW3D_PT_rig_animation_visn"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        lay = self.layout
        rig = breath.rig_from_context(context)
        lay.operator('visn_breath.setup', text='匹配骨骼 / 创建或更新呼吸', icon='ARMATURE_DATA')
        ctrl = breath.controller_for(rig)
        if ctrl is None:
            lay.label(text='选骨架或姿态骨，然后点击上方按钮')
            return
        lay.prop(ctrl, '["enabled"]', text='启用呼吸')
        for key, label in [('strength', '总幅度'), ('width_percent', '宽度扩张（%）'),
                           ('depth_percent', '厚度扩张（%）'), ('length_percent', '长度扩张（%）'),
                           ('abdomen_ratio', '腹部比例')]:
            lay.prop(ctrl, '["' + key + '"]', text=label)
        for key, label in [('chest_lift_mm', '胸部抬升（毫米）'),
                           ('head_lift_mm', '头部额外抬升（毫米）'),
                           ('shoulder_lift_mm', '双肩额外抬升（毫米）')]:
            lay.prop(ctrl, '["' + key + '"]', text=label)
        if rig.animation_data:
            track = rig.animation_data.nla_tracks.get(breath.TRACK)
            if track and track.strips:
                lay.prop(track, 'mute', text='静音呼吸NLA')
                lay.prop(track.strips[0], 'influence', text='NLA影响')
        lay.separator()
        for key, label in [('period_seconds', '周期（秒）'), ('phase', '相位（周期）'),
                           ('inhale_ratio', '吸气比例')]:
            lay.prop(ctrl, '["' + key + '"]', text=label)
        lay.operator('visn_breath.refresh', icon='FILE_REFRESH')
        lay.label(text='胸腔：' + ctrl.get('chest', ''))
        if ctrl.get('abdomen'):
            lay.label(text='腹部：' + ctrl['abdomen'])
        lay.operator('visn_breath.view_layer', icon='NLA')
        lay.operator('visn_breath.remove', icon='TRASH')


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
        col.operator("autosway.clear_sway", text='清除选中及子级摆动', icon='TRASH')

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


class VIEW3D_PT_skirt_autosway_visn(BekkanPanelBase, bpy.types.Panel):
    bl_idname = 'VIEW3D_PT_skirt_autosway_visn'
    bl_label = '裙摆 AutoSway'
    bl_parent_id = 'VIEW3D_PT_anime_visn'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        if context.mode != 'POSE' or context.active_pose_bone is None:
            layout.label(text='姿态模式下选中裙摆总骨骼', icon='INFO')
            return
        root = context.active_pose_bone
        group = skirt_autosway._group_for(root, context.scene)
        props = context.scene.autosway_settings
        layout.label(text=f'{root.name} · 直属裙摆链 {len(root.children)} 条')
        if group is None:
            layout.prop(props, 'my_enum')
        for key in ('my_swayAngle', 'my_incrementalAngle',
                    'my_loopFrame', 'my_staggeredFrames', 'my_offsetFrame',
                    'skirt_loop_wave'):
            layout.prop(props, key)
        row = layout.row(align=True)
        add = row.row(align=True)
        add.enabled = group is None
        add.operator('autosway.add_skirt', text='一键添加', icon='ADD')
        adjust = row.row(align=True)
        adjust.enabled = group is not None
        adjust.operator('autosway.adjust_skirt', text='一键调整', icon='FILE_REFRESH')
        remove = row.row(align=True)
        remove.enabled = group is not None
        remove.operator('autosway.remove_skirt', text='一键删除', icon='TRASH')
        layout.label(text='裙片相位自动绕一周；错帧量作用于链内', icon='INFO')


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


# 面板按注册顺序在侧边栏中排列
class BEKKAN_PT_plugin_debug(BekkanPanelBase, bpy.types.Panel):
    bl_idname = 'BEKKAN_PT_plugin_debug'
    bl_label = '插件调试'

    def draw(self, context):
        self.layout.operator('wm.reload_pond_bekkan_visn')
        self.layout.operator("render.open_addon_folder",
                             text="打开插件所在文件夹", icon='FILE_FOLDER')


_classes = (
    BEKKAN_OT_file_size_report,
    BEKKAN_OT_workspace_setup_report,
    BEKKAN_UL_visibility_audit,
    VIEW3D_PT_parents_visn,
    VIEW3D_PT_stage_visn,
    VIEW3D_PT_rig_animation_visn,
    VIEW3D_PT_texture_visn,
    VIEW3D_PT_anime_visn,
    VIEW3D_PT_anime_autosway_visn,
    VIEW3D_PT_skirt_autosway_visn,
    VIEW3D_PT_breath_visn,
    VIEW3D_PT_render_preset_visn,
    BEKKAN_PT_plugin_debug,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
