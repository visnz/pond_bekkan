"""裙摆 AutoSway：从一根总骨骼的直属子骨骼生成环形摆动链。"""
import math
import uuid

import bpy
from bpy.props import FloatProperty
from mathutils import Vector


_TAG = "_visn_skirt_autosway"
_PARAMS = ("angle", "incremental", "loop", "stagger", "offset", "loop_wave")


def _chains(root):
    """每个直属子骨骼各成一链；分叉也按父到子的稳定次序遍历。"""
    children = list(root.children)
    center = sum((child.bone.head_local for child in children), Vector()) / len(children)
    direction = root.bone.tail_local - root.bone.head_local
    if direction.length < 1e-6:
        direction = Vector((0, 0, 1))
    direction.normalize()
    axis = Vector((1, 0, 0))
    axis -= direction * axis.dot(direction)
    if axis.length < 1e-6:
        axis = Vector((0, 1, 0))
        axis -= direction * axis.dot(direction)
    axis.normalize()
    other = direction.cross(axis)

    def angle(child):
        radial = child.bone.head_local - center
        if radial.length < 1e-6:
            radial = child.bone.tail_local - center
        return math.atan2(radial.dot(other), radial.dot(axis))

    ordered = sorted(children, key=lambda bone: (angle(bone), bone.name))

    def descendants(bone):
        result = [bone]
        for child in sorted(bone.children, key=lambda b: b.name):
            result.extend(descendants(child))
        return result

    return [descendants(child) for child in ordered]


def _group_for(root, scene):
    group = root.bone.get(_TAG)
    return group if group and f"{group}_angle" in scene else None


def _driver_for(bone, axis, scene, group, chain_index, chain_count, depth):
    # 保留添加时的基础角度；重建时只移除本工具先前创建的驱动。
    old = bone.id_data.animation_data
    if old:
        path = bone.path_from_id("rotation_euler")
        for fc in old.drivers:
            if fc.data_path == path and fc.array_index == axis:
                bone.driver_remove("rotation_euler", axis)
                break
    initial = bone.rotation_euler[axis]
    bone.rotation_mode = 'XYZ'
    driver = bone.driver_add('rotation_euler', axis).driver
    driver.type = 'SCRIPTED'
    for key in _PARAMS:
        var = driver.variables.new()
        var.name = key
        var.type = 'SINGLE_PROP'
        var.targets[0].id_type = 'SCENE'
        var.targets[0].id = scene
        var.targets[0].data_path = f'["{group}_{key}"]'
    theta = 2 * math.pi * chain_index / chain_count
    # 环绕一周时偏移正好一整个周期；相邻裙片相位连续。
    period = f"max(1.0, loop + loop_wave * cos({theta:.12g}))"
    driver.expression = (
        f"{initial:.12g} - (angle + incremental * {depth}) * "
        f"sin(2 * pi * (frame + offset + loop * {chain_index}/{chain_count} "
        f"- stagger * {depth}) / {period}) * pi / 180"
    )


def _refresh_sway(context):
    """场景自定义属性改完后，立即重算当前帧的驱动结果。"""
    scene = context.scene
    context.active_object.update_tag(refresh={'OBJECT'})
    scene.update_tag()
    scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
    context.view_layer.update()


class AUTOSWAY_OT_AddSkirt(bpy.types.Operator):
    bl_idname = 'autosway.add_skirt'
    bl_label = '一键添加裙摆 AutoSway'
    bl_description = '以活动骨骼的直属子骨骼为裙摆链，沿圆周错开相位并统一控制参数'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'POSE' and context.active_pose_bone is not None
                and context.active_object is not None and context.active_object.type == 'ARMATURE')

    def execute(self, context):
        root = context.active_pose_bone
        if len(root.children) < 2:
            self.report({'ERROR'}, '活动骨骼至少需要两条直属子骨骼链')
            return {'CANCELLED'}
        scene = context.scene
        props = scene.autosway_settings
        chains = _chains(root)
        axis = int(props.my_enum[-1]) - 1
        group = _group_for(root, scene)
        if group is not None:
            self.report({'WARNING'}, '这根骨骼已有裙摆 AutoSway，请使用一键调整')
            return {'CANCELLED'}
        # 原有其他驱动不覆盖：避免意外替换角色上已有的动画逻辑。
        for chain in chains:
            for bone in chain:
                anim = bone.id_data.animation_data
                if not anim:
                    continue
                for fc in anim.drivers:
                    if fc.data_path == bone.path_from_id('rotation_euler') and fc.array_index == axis:
                        self.report({'ERROR'}, f'{bone.name} 的目标旋转轴已有其他驱动，请先处理冲突')
                        return {'CANCELLED'}
        group = 'autosway_skirt_' + uuid.uuid4().hex[:12]
        values = dict(angle=props.my_swayAngle, incremental=props.my_incrementalAngle,
                      loop=props.my_loopFrame, stagger=props.my_staggeredFrames,
                      offset=props.my_offsetFrame, loop_wave=props.skirt_loop_wave)
        for key, value in values.items():
            scene[f'{group}_{key}'] = value
        root.bone[_TAG] = group
        for chain_index, chain in enumerate(chains):
            for depth, bone in enumerate(chain):
                _driver_for(bone, axis, scene, group, chain_index, len(chains), depth)
        _refresh_sway(context)
        self.report({'INFO'}, f'已设置 {len(chains)} 条裙摆链、{sum(map(len, chains))} 根骨骼；下方可统一调参')
        return {'FINISHED'}


class AUTOSWAY_OT_AdjustSkirt(bpy.types.Operator):
    bl_idname = 'autosway.adjust_skirt'
    bl_label = '一键调整裙摆 AutoSway'
    bl_description = '把面板中的参数一次应用到活动总骨骼下全部裙摆链'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return AUTOSWAY_OT_AddSkirt.poll(context)

    def execute(self, context):
        scene = context.scene
        group = _group_for(context.active_pose_bone, scene)
        if group is None:
            self.report({'WARNING'}, '这根骨骼还没有裙摆 AutoSway，请先添加')
            return {'CANCELLED'}
        props = scene.autosway_settings
        values = dict(angle=props.my_swayAngle, incremental=props.my_incrementalAngle,
                      loop=props.my_loopFrame, stagger=props.my_staggeredFrames,
                      offset=props.my_offsetFrame, loop_wave=props.skirt_loop_wave)
        for key, value in values.items():
            scene[f'{group}_{key}'] = value
        _refresh_sway(context)
        self.report({'INFO'}, f'已调整 {len(context.active_pose_bone.children)} 条链：角度 {values["angle"]:g}°，递增 {values["incremental"]:g}°，周期 {values["loop"]:g} 帧')
        return {'FINISHED'}


class AUTOSWAY_OT_RemoveSkirt(bpy.types.Operator):
    bl_idname = 'autosway.remove_skirt'
    bl_label = '移除裙摆 AutoSway'
    bl_description = '仅移除当前活动总骨骼所建的裙摆驱动与控制参数'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return AUTOSWAY_OT_AddSkirt.poll(context)

    def execute(self, context):
        root = context.active_pose_bone
        scene = context.scene
        group = _group_for(root, scene)
        if group is None:
            self.report({'WARNING'}, '这根骨骼没有裙摆 AutoSway')
            return {'CANCELLED'}
        count = 0
        for chain in _chains(root):
            for bone in chain:
                anim = bone.id_data.animation_data
                if not anim:
                    continue
                for fc in list(anim.drivers):
                    if fc.data_path != bone.path_from_id('rotation_euler'):
                        continue
                    if any(v.targets and v.targets[0].id == scene and
                           v.targets[0].data_path == f'["{group}_angle"]'
                           for v in fc.driver.variables):
                        axis = fc.array_index
                        bone.driver_remove('rotation_euler', axis)
                        bone.rotation_euler[axis] = 0.0
                        count += 1
        for key in _PARAMS:
            if f'{group}_{key}' in scene:
                del scene[f'{group}_{key}']
        del root.bone[_TAG]
        _refresh_sway(context)
        self.report({'INFO'}, f'已移除 {count} 根骨骼的裙摆摆动')
        return {'FINISHED'}


_classes = (AUTOSWAY_OT_AddSkirt, AUTOSWAY_OT_AdjustSkirt, AUTOSWAY_OT_RemoveSkirt)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
