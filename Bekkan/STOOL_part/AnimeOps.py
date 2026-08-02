import random  # type: ignore
import bpy  # type: ignore
from bpy.props import FloatProperty, EnumProperty  # type: ignore

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
                # if bpy.app.version >= (4, 4, 0):
                fcurve = obj.animation_data.action.fcurve_ensure_for_datablock(
                    obj, data_path, index=axis)
                # else:
                #     fcurve = obj.animation_data.action.fcurves.find(data_path, index=axis) \
                #         or obj.animation_data.action.fcurves.new(data_path, index=axis)

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
