# 动画类：Wiggle Noise 动画 / 删除所有动画（合并自 Bekkan/STOOL_part/AnimeOps.py，纯平移）
# + AutoSway 骨骼摆动（合并自独立插件 autosway.py，纯平移，收进动画类面板的子面板）
# 面板在 ui/bekkan/panels.py
import random  # type: ignore
import copy
import bpy  # type: ignore
from mathutils import Matrix
from bpy.props import FloatProperty, EnumProperty, PointerProperty, StringProperty  # type: ignore

# 需要在 execute/invoke 间同步的参数字段
_FIELDS = ('scale_min', 'scale_max', 'strength_min', 'strength_max',
           'phase_min', 'phase_max', 'target_property')

_PATHS = {'LOCATION': 'location', 'ROTATION': 'rotation_euler', 'SCALE': 'scale'}


class NoiseAnimSettings(bpy.types.Operator):
    bl_idname = "object.noise_anim_settings"
    bl_label = "Noise Animation Settings"
    bl_description = "存储Noise动画参数"
    # 这些参数会在插件运行时被更新
    scale_min = 20.0
    scale_max = 60.0
    strength_min = 0.1
    strength_max = 0.5
    phase_min = 0.0
    phase_max = 100.0
    target_property: str = "LOCATION"  # 默认目标属性


class OBJECT_OT_add_noise_anim(bpy.types.Operator):
    bl_idname = "object.add_noise_anim"
    bl_label = "Add/Update Noise Animation"
    bl_description = "为选中对象的Location/Rotation/Scale添加/更新Noise动画"
    bl_options = {'REGISTER', 'UNDO'}

    scale_min: FloatProperty(name="缩放", default=20.0, min=0.1, max=1000.0)  # type: ignore
    scale_max: FloatProperty(name="缩放", default=60.0, min=0.1, max=1000.0)  # type: ignore
    strength_min: FloatProperty(name="强度", default=0.1, min=0.0, max=10.0)  # type: ignore
    strength_max: FloatProperty(name="强度", default=0.5, min=0.0, max=10.0)  # type: ignore
    phase_min: FloatProperty(name="错位", default=0.0, min=0.0, max=1000.0)  # type: ignore
    phase_max: FloatProperty(name="错位", default=100.0, min=0.0, max=1000.0)  # type: ignore
    target_property: EnumProperty(
        name="目标属性",
        items=[
            ('LOCATION', "位置 (Location)", "在物体的位置 (XYZ) 上添加 Noise"),
            ('ROTATION', "旋转 (Rotation)", "在物体的旋转 (XYZ) 上添加 Noise"),
            ('SCALE', "缩放 (Scale)", "在物体的缩放 (XYZ) 上添加 Noise"),
        ],
        default='LOCATION'
    )  # type: ignore

    def execute(self, context):
        # 检查参数合法性
        if self.scale_min > self.scale_max:
            self.report({'ERROR'}, "Scale Min 必须 ≤ Scale Max")
            return {'CANCELLED'}
        if self.strength_min > self.strength_max:
            self.report({'ERROR'}, "Strength Min 必须 ≤ Strength Max")
            return {'CANCELLED'}
        if self.phase_min > self.phase_max:
            self.report({'ERROR'}, "Phase Min 必须 ≤ Phase Max")
            return {'CANCELLED'}

        # 保存参数到类变量
        for f in _FIELDS:
            setattr(NoiseAnimSettings, f, getattr(self, f))

        objs = context.selected_objects
        if not objs:
            self.report({'WARNING'}, "未选中任何对象")
            return {'CANCELLED'}

        data_path = _PATHS[self.target_property]

        for obj in objs:
            if not obj.animation_data:
                obj.animation_data_create()
            # 插入关键帧（确保 F-Curve 存在）
            obj.keyframe_insert(data_path=data_path, frame=0)

            for axis in range(3):  # X/Y/Z
                # 4.4 起 Action 改为分层（slotted）结构，5.0 移除了旧版 action.fcurves；
                # fcurve_ensure_for_datablock 会自动创建/分配 layer、strip、slot
                # 仅支持 Blender 5.2：版本判断已注释，直接走 4.4+ 分层 Action 路径
                fcurve = obj.animation_data.action.fcurve_ensure_for_datablock(
                    obj, data_path, index=axis)

                # 删除旧的NOISE修改器，再加新的
                for mod in fcurve.modifiers:
                    if mod.type == 'NOISE':
                        fcurve.modifiers.remove(mod)
                m = fcurve.modifiers.new('NOISE')
                m.scale = random.uniform(self.scale_min, self.scale_max)
                m.strength = random.uniform(self.strength_min, self.strength_max)
                m.phase = random.uniform(self.phase_min, self.phase_max)
                m.blend_in = 0
                m.blend_out = 0

        self.report({'INFO'}, f"已为 {len(objs)} 个对象的 {self.target_property} 添加Noise动画")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 从类变量加载上次的参数
        for f in _FIELDS:
            setattr(self, f, getattr(NoiseAnimSettings, f))
        return context.window_manager.invoke_props_dialog(self, width=300)


class RemoveAllAnimations(bpy.types.Operator):
    """Remove all animations from selected objects"""
    bl_idname = "object.remove_all_animations_visn"
    bl_label = "删除所选对象的动画"
    bl_description = "删除所选对象的所有动画数据"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        n = 0
        for obj in context.selected_objects:
            if obj.animation_data:
                obj.animation_data_clear()
                n += 1
            # 同时清形态键动画
            sk = getattr(obj.data, 'shape_keys', None)
            if sk and sk.animation_data:
                sk.animation_data_clear()
                n += 1

        # 强制场景重求值刷新视口，否则动画残留显示需手动切换帧才消失
        context.scene.frame_set(context.scene.frame_current)

        self.report({'INFO'}, f"Removed animations from {n} objects")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# AutoSway 骨骼摆动：靠场景自定义属性 + 驱动器让姿态骨骼周期性摆动，无需关键帧。
# 每次"添加摆动"生成一个 Control_Group_N，5 个参数（角度/递增/循环帧/错帧/偏移）
# 存成 scene["autosway_Control_Group_N_xxx"]，驱动器表达式引用这些属性。
# ---------------------------------------------------------------------------
_autosway_group_counter = 0


class AutoSwaySettings(bpy.types.PropertyGroup):
    my_swayAngle: FloatProperty(
        name="摆动角度", description="骨骼基础摆动角度（度）",
        default=20, soft_min=-360, soft_max=360)  # type: ignore
    my_incrementalAngle: FloatProperty(
        name="递增角度", description="每根骨骼相对上一根的角度增量",
        default=1, soft_min=-10, soft_max=10)  # type: ignore
    my_loopFrame: FloatProperty(
        name="循环帧数", description="完整摆动周期所需帧数",
        default=24, min=1, soft_max=240)  # type: ignore
    my_staggeredFrames: FloatProperty(
        name="错帧量", description="骨骼之间的动画延迟帧数",
        default=5, soft_min=-50, soft_max=50)  # type: ignore
    my_offsetFrame: FloatProperty(
        name="帧偏移", description="整体动画起始偏移帧",
        default=0, soft_min=-240, soft_max=240)  # type: ignore
    my_enum: EnumProperty(
        name="摆动轴向", description="驱动器控制的旋转轴向",
        items=[('OP1', "X", "绕 X 轴摆动"),
               ('OP2', "Y", "绕 Y 轴摆动"),
               ('OP3', "Z", "绕 Z 轴摆动")],
        default='OP3')  # type: ignore
    active_control_group: StringProperty(
        name="活动控制组", default="")  # type: ignore
    rename_group_name: StringProperty(
        name="新名称", default="")  # type: ignore


class AUTOSWAY_OT_AddSway(bpy.types.Operator):
    bl_idname = "autosway.add_sway"
    bl_label = "添加摆动"
    bl_description = "为选中的姿态骨骼添加摆动驱动器"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global _autosway_group_counter

        scene = context.scene
        props = scene.autosway_settings

        selected_bones = context.selected_pose_bones
        if not selected_bones:
            self.report({'ERROR'}, "未选择骨骼！")
            return {'CANCELLED'}

        _autosway_group_counter += 1
        control_group_name = f"Control_Group_{_autosway_group_counter}"
        prop_group_name = f"autosway_{control_group_name}"

        self._create_control_properties(scene, prop_group_name, control_group_name, props)
        props.active_control_group = prop_group_name

        axis = int(props.my_enum[-1]) - 1  # OP1/OP2/OP3 -> 0/1/2
        for idx, bone in enumerate(selected_bones):
            current_axis_value = bone.rotation_euler[axis]
            bone.rotation_mode = 'XYZ'

            driver = bone.driver_add('rotation_euler', axis).driver
            driver.type = 'SCRIPTED'

            for param in ('angle', 'incremental', 'loop', 'stagger', 'offset'):
                var = driver.variables.new()
                var.name = param
                var.type = 'SINGLE_PROP'
                var.targets[0].id_type = 'SCENE'
                var.targets[0].id = scene
                var.targets[0].data_path = f'["{prop_group_name}_{param}"]'

            driver.expression = (
                f"{current_axis_value} + "
                f"-(angle + incremental * {idx}) * "
                f"sin(2 * pi * (frame + offset - stagger * {idx}) / loop) * "
                f"pi / 180"
            )

        self.report({'INFO'}, f"已创建控制组: {control_group_name}")
        return {'FINISHED'}

    @staticmethod
    def _create_control_properties(scene, prop_group_name, control_group_name, props):
        scene[f"{prop_group_name}_angle"] = props.my_swayAngle
        scene[f"{prop_group_name}_incremental"] = props.my_incrementalAngle
        scene[f"{prop_group_name}_loop"] = props.my_loopFrame
        scene[f"{prop_group_name}_stagger"] = props.my_staggeredFrames
        scene[f"{prop_group_name}_offset"] = props.my_offsetFrame
        scene[f"{prop_group_name}_display_name"] = control_group_name


class AUTOSWAY_OT_ClearSway(bpy.types.Operator):
    bl_idname = "autosway.clear_sway"
    bl_label = "清除动画"
    bl_description = "移除选中骨骼的摆动驱动器并归零旋转"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_bones = context.selected_pose_bones
        if not selected_bones:
            self.report({'ERROR'}, "未选择骨骼！")
            return {'CANCELLED'}

        for bone in selected_bones:
            for i in range(3):
                bone.driver_remove('rotation_euler', i)
            bone.rotation_euler = (0, 0, 0)

        return {'FINISHED'}


class AUTOSWAY_OT_RemoveControlGroup(bpy.types.Operator):
    bl_idname = "autosway.remove_control_group"
    bl_label = "删除控制组"
    bl_description = "删除当前选中的控制组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        props = scene.autosway_settings

        if not props.active_control_group:
            self.report({'ERROR'}, "没有活动的控制组！")
            return {'CANCELLED'}

        prop_group_name = props.active_control_group
        for param in ('angle', 'incremental', 'loop', 'stagger', 'offset', 'display_name'):
            prop_path = f"{prop_group_name}_{param}"
            if prop_path in scene:
                del scene[prop_path]

        props.active_control_group = ""
        self.report({'INFO'}, "已删除控制组")
        return {'FINISHED'}


class AUTOSWAY_OT_SelectControlGroup(bpy.types.Operator):
    bl_idname = "autosway.select_control_group"
    bl_label = "选择控制组"
    bl_description = "选择此控制组为活动控制组"

    group_name: StringProperty()  # type: ignore

    def execute(self, context):
        context.scene.autosway_settings.active_control_group = self.group_name
        return {'FINISHED'}


class AUTOSWAY_OT_KeyframeParameter(bpy.types.Operator):
    bl_idname = "autosway.keyframe_parameter"
    bl_label = "关键帧参数"
    bl_description = "为该参数插入关键帧"

    parameter_path: StringProperty()  # type: ignore

    def execute(self, context):
        context.scene.keyframe_insert(data_path=f'["{self.parameter_path}"]')
        self.report({'INFO'}, "已为参数设置关键帧")
        return {'FINISHED'}


class AUTOSWAY_OT_KeyframeAllParameters(bpy.types.Operator):
    bl_idname = "autosway.keyframe_all_parameters"
    bl_label = "关键帧所有参数"
    bl_description = "为当前控制组的全部参数插入关键帧"

    def execute(self, context):
        scene = context.scene
        props = scene.autosway_settings

        if not props.active_control_group:
            self.report({'ERROR'}, "没有活动的控制组！")
            return {'CANCELLED'}

        prop_group_name = props.active_control_group
        for param in ('angle', 'incremental', 'loop', 'stagger', 'offset'):
            prop_path = f"{prop_group_name}_{param}"
            if prop_path in scene:
                scene.keyframe_insert(data_path=f'["{prop_path}"]')

        self.report({'INFO'}, "已为所有参数设置关键帧")
        return {'FINISHED'}


class AUTOSWAY_OT_RenameControlGroup(bpy.types.Operator):
    bl_idname = "autosway.rename_control_group"
    bl_label = "重命名控制组"
    bl_description = "重命名当前活动控制组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        props = scene.autosway_settings

        if not props.active_control_group:
            self.report({'ERROR'}, "没有活动的控制组！")
            return {'CANCELLED'}
        if not props.rename_group_name:
            self.report({'ERROR'}, "请输入新名称！")
            return {'CANCELLED'}

        prop_group_name = props.active_control_group
        scene[f"{prop_group_name}_display_name"] = props.rename_group_name
        props.rename_group_name = ""

        self.report({'INFO'}, f"控制组已重命名为: {scene[f'{prop_group_name}_display_name']}")
        return {'FINISHED'}


class AUTOSWAY_OT_AdjustParameter(bpy.types.Operator):
    """微调控制组参数值（面板上的 +/- 按钮）"""
    bl_idname = "autosway.adjust_parameter"
    bl_label = "调整参数"

    parameter_path: StringProperty()  # type: ignore
    adjustment: FloatProperty()  # type: ignore

    _PARAM_RANGES = {
        "angle": (-10, 10),
        "incremental": (-10, 10),
        "loop": (10, 200),
        "stagger": (5, 20),
        "offset": (0, 200),
    }

    def execute(self, context):
        scene = context.scene
        current_value = scene.get(self.parameter_path, 0.0)

        param_type = None
        for key in self._PARAM_RANGES:
            if key in self.parameter_path:
                param_type = key
                break

        new_value = current_value + self.adjustment
        if param_type:
            min_val, max_val = self._PARAM_RANGES[param_type]
            new_value = max(min_val, min(max_val, new_value))
        scene[self.parameter_path] = new_value

        return {'FINISHED'}


class OBJECT_OT_sync_armature_psr(bpy.types.Operator):
    bl_idname = 'object.sync_armature_psr_visn'
    bl_label = '同步骨架姿态 PSR'
    bl_description = '物体模式：最后选中的骨架为源，按同名骨骼复制当前局部位置、旋转、缩放到其余选中骨架；不复制动画、约束、权重或骨架物体变换'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.active_object is not None
                and context.active_object.type == 'ARMATURE'
                and context.active_object in context.selected_objects
                and sum(o.type == 'ARMATURE' for o in context.selected_objects) >= 2)

    def execute(self, context):
        source = context.active_object
        # 先快照源通道，保留欧拉角圈数及四元数/轴角表达，不经过矩阵分解。
        fields = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale')
        values = {b.name: (b.rotation_mode, {f: tuple(getattr(b, f)) for f in fields})
                  for b in source.pose.bones}
        copied = 0
        bones_copied = 0
        skipped = []
        for target in context.selected_objects:
            if target == source or target.type != 'ARMATURE':
                continue
            if not target.is_editable:
                skipped.append(target.name + '（只读）')
                continue
            if len(target.pose.bones) != len(values):
                skipped.append(target.name + '（骨骼数量不同）')
                continue
            for bone in target.pose.bones:
                if bone.name not in values:
                    continue
                mode, channels = values[bone.name]
                bone.rotation_mode = mode
                for field, value in channels.items():
                    setattr(bone, field, value)
                bones_copied += 1
            target.update_tag()
            copied += 1
        if skipped:
            print('[PondBekkan] 姿态同步跳过：' + '；'.join(skipped))
        message = f'源：{source.name}；已处理 {copied} 个骨架，同步 {bones_copied} 根骨骼'
        if skipped:
            message += f'；跳过 {len(skipped)} 个数量不同或只读骨架'
        self.report({'WARNING'} if skipped else {'INFO'}, message)
        return {'FINISHED'} if copied else {'CANCELLED'}


_ARM_WORDS = ('shoulder', 'clavicle', 'collar', 'arm', 'elbow', 'forearm',
              'wrist', 'hand', 'palm', 'finger', 'thumb', 'index', 'middle',
              'ring', 'pinky', 'little', '腕', '肩', '肘', '手', '指')
_LEG_WORDS = ('hip', 'pelvis', 'thigh', 'leg', 'shin', 'calf', 'knee',
              'ankle', 'foot', 'toe', 'heel', 'ball', '胯', '髋', '腿', '膝', '脚', '足', '趾')


def _limb_pose_targets(rig, part):
    """Blender 左右命名走原生镜像；中文/日文左右命名按姿态空间矩阵镜像。"""
    names = {bone.name for bone in rig.pose.bones}
    words = _ARM_WORDS if part == 'ARMS' else _LEG_WORDS
    rigify = bool(rig.data.get('rig_id') or rig.get('rig_id'))
    native = set()
    manual = {}
    for name in names:
        if rigify and (name.startswith(('DEF-', 'MCH-', 'ORG-', 'VIS-', 'VIS_'))
                       or '_ik_target.' in name):
            continue
        if not any(word in name.lower() for word in words):
            continue
        partner = bpy.utils.flip_name(name)
        if partner != name and partner in names:
            native.update((name, partner))
        elif '左' in name and name.replace('左', '右', 1) in names:
            manual[name] = name.replace('左', '右', 1)
        elif '右' in name and name.replace('右', '左', 1) in names:
            manual[name] = name.replace('右', '左', 1)
    if part == 'LEGS' and (native or manual):
        # Rigify 的 hips 和普通骨架的中心 pelvis 自身也要作 X 镜像。
        for name in ('hips', 'Hips', 'pelvis', 'Pelvis', 'hip', 'Hip', '骨盆', '胯'):
            if name in names:
                native.add(name)
    return native, manual


class POSE_OT_swap_limb_pose_visn(bpy.types.Operator):
    bl_idname = 'pose.swap_limb_pose_visn'
    bl_label = '左右肢体姿态镜像交换'
    bl_description = '将活动骨架对应肢体的左右姿态水平镜像交换，包含 Rigify 控制骨和 IK/FK 自定义属性'
    bl_options = {'REGISTER', 'UNDO'}

    part: EnumProperty(
        name='部位',
        items=[('ARMS', '左右手与肩膀', ''), ('LEGS', '左右腿与胯部', '')],
        default='ARMS',
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return (context.mode == 'POSE' and context.active_object is not None
                and context.active_object.type == 'ARMATURE'
                and context.active_object.is_editable)

    def execute(self, context):
        rig = context.active_object
        native, manual = _limb_pose_targets(rig, self.part)
        if not native and not manual:
            self.report({'WARNING'}, '没有找到左右成对的肢体骨骼；支持 .L/.R、Left/Right 或 左/右命名')
            return {'CANCELLED'}
        selected = {bone.name: bone.select for bone in rig.pose.bones}
        mirror = Matrix.Diagonal((-1, 1, 1, 1))
        manual_matrices = {name: rig.pose.bones[name].matrix.copy() for name in manual}
        manual_props = {name: copy.deepcopy(dict(rig.pose.bones[name].items())) for name in manual}
        try:
            if native:
                for bone in rig.pose.bones:
                    bone.select = bone.name in native
                if 'FINISHED' not in bpy.ops.pose.copy():
                    self.report({'ERROR'}, '复制肢体姿态失败')
                    return {'CANCELLED'}
                if 'FINISHED' not in bpy.ops.pose.paste(flipped=True, selected_mask=True):
                    self.report({'ERROR'}, '镜像交换姿态失败')
                    return {'CANCELLED'}
            # 父骨先写，避免子骨矩阵因父级姿态更新而偏移。
            depth = lambda bone: len(bone.parent_recursive)
            for name in sorted(manual, key=lambda item: depth(rig.pose.bones[item])):
                bone = rig.pose.bones[name]
                partner = manual[name]
                bone.matrix = mirror @ manual_matrices[partner] @ mirror
                for key, value in manual_props[partner].items():
                    if key != '_RNA_UI':
                        bone[key] = value
            context.view_layer.update()
        except Exception as exc:
            self.report({'ERROR'}, f'镜像交换姿态失败：{exc}')
            return {'CANCELLED'}
        finally:
            for bone in rig.pose.bones:
                bone.select = selected[bone.name]
        label = '双手与肩膀' if self.part == 'ARMS' else '双腿与胯部'
        self.report({'INFO'}, f'已镜像交换{label}：{len(native) + len(manual)} 根骨骼')
        return {'FINISHED'}


_classes = (
    OBJECT_OT_sync_armature_psr,
    POSE_OT_swap_limb_pose_visn,
    OBJECT_OT_add_noise_anim,
    NoiseAnimSettings,
    RemoveAllAnimations,
    AutoSwaySettings,
    AUTOSWAY_OT_AddSway,
    AUTOSWAY_OT_ClearSway,
    AUTOSWAY_OT_RemoveControlGroup,
    AUTOSWAY_OT_SelectControlGroup,
    AUTOSWAY_OT_KeyframeParameter,
    AUTOSWAY_OT_KeyframeAllParameters,
    AUTOSWAY_OT_RenameControlGroup,
    AUTOSWAY_OT_AdjustParameter,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.autosway_settings = PointerProperty(type=AutoSwaySettings)


def unregister():
    if hasattr(bpy.types.Scene, 'autosway_settings'):
        del bpy.types.Scene.autosway_settings
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
