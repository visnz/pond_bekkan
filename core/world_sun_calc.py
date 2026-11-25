"""World 活跃天空与选中 Sun 的方向双向同步。"""
import math

import bpy
from mathutils import Vector


def sky_angles_to_position(elevation, rotation, radius=1.0):
    """角度单位为度；Blender Multiple Scattering 的 0° 朝 +Y，90° 朝 +X。"""
    if not all(math.isfinite(value) for value in (elevation, rotation, radius)) or radius <= 0:
        raise ValueError('角度和半径必须是有限数值，半径必须大于 0')
    elevation, rotation = math.radians(elevation), math.radians(rotation)
    horizontal = radius * math.cos(elevation)
    return (horizontal * math.sin(rotation), horizontal * math.cos(rotation),
            radius * math.sin(elevation))


def position_to_sky_angles(position):
    """输入世界坐标、目标为世界原点；返回 Elevation、Rotation（度）与半径。"""
    x, y, z = position
    if not all(math.isfinite(value) for value in position):
        raise ValueError('坐标必须是有限数值')
    horizontal = math.hypot(x, y)
    radius = math.hypot(horizontal, z)
    if radius <= 1e-12:
        raise ValueError('坐标不能是世界原点：无法确定太阳方向')
    elevation = math.degrees(math.atan2(z, horizontal))
    rotation = math.degrees(math.atan2(x, y)) % 360 if horizontal > radius * 1e-12 else 0.0
    return elevation, rotation, radius


def _world_editor(context):
    space = context.space_data
    return (getattr(space, 'type', None) == 'NODE_EDITOR'
            and getattr(space, 'tree_type', None) == 'ShaderNodeTree'
            and getattr(space, 'shader_type', None) == 'WORLD')


def _selected_sky(context):
    tree = getattr(context.space_data, 'edit_tree', None)
    if tree is None:
        return None
    active = tree.nodes.active
    if active is not None and active.select and active.type == 'TEX_SKY':
        return active
    return None


def _selected_sun(context):
    suns = [obj for obj in context.selected_objects if obj.type == 'LIGHT' and obj.data.type == 'SUN']
    if context.active_object in suns:
        return context.active_object
    return suns[0] if len(suns) == 1 else None


def _targets(context):
    if not _world_editor(context):
        raise ValueError('请在 World Shader 编辑器运行')
    sky, sun = _selected_sky(context), _selected_sun(context)
    if sky is None:
        raise ValueError('请选中并激活要同步的 Sky Texture 节点')
    if getattr(sky, 'sky_type', None) not in {'MULTIPLE_SCATTERING', 'SINGLE_SCATTERING'}:
        raise ValueError('请选择使用 Elevation / Rotation 的天空类型')
    if sun is None:
        raise ValueError('请选中一个 Sun；多选 Sun 时请将目标 Sun 设为活跃对象')
    return sky, sun


def _world_position(context, sun):
    return sun.evaluated_get(context.evaluated_depsgraph_get()).matrix_world.translation.copy()


def sync_sky_to_sun(context):
    sky, sun = _targets(context)
    if not sun.is_editable:
        raise ValueError('选中的 Sun 不可编辑')
    position = _world_position(context, sun)
    radius = position.length or 1.0
    target = Vector(sky_angles_to_position(math.degrees(sky.sun_elevation),
                                         math.degrees(sky.sun_rotation), radius))
    old_basis = sun.matrix_basis.copy()
    old_location = sun.location.copy()
    try:
        # 用 Blender 的世界矩阵转换处理父级/父级逆矩阵，然后仅保留新的位置。
        matrix = sun.matrix_world.copy()
        matrix.translation = target
        sun.matrix_world = matrix
        local_location = sun.location.copy()
        sun.matrix_basis = old_basis
        sun.location = local_location
        context.view_layer.update()
        if (_world_position(context, sun) - target).length > max(1e-5, radius * 1e-5):
            raise ValueError('Sun 的位置被约束或驱动控制，无法写入目标世界坐标')
    except Exception:
        sun.matrix_basis = old_basis
        sun.location = old_location
        context.view_layer.update()
        raise
    return sky, sun, target, radius


def sync_sun_to_sky(context):
    sky, sun = _targets(context)
    if not sky.id_data.is_editable:
        raise ValueError('活跃 Sky Texture 的节点树不可编辑')
    position = _world_position(context, sun)
    elevation, rotation, radius = position_to_sky_angles(position)
    # Z 轴上方位角无唯一解，保留天空原来的 Rotation。
    if math.hypot(position.x, position.y) <= radius * 1e-12:
        rotation = math.degrees(sky.sun_rotation) % 360
    old = sky.sun_elevation, sky.sun_rotation
    target = math.radians(elevation), math.radians(rotation)
    try:
        sky.sun_elevation, sky.sun_rotation = target
        context.view_layer.update()
        if any(not math.isclose(a, b, abs_tol=1e-6) for a, b in
               zip((sky.sun_elevation, sky.sun_rotation), target)):
            raise ValueError('天空角度被驱动控制，无法写入同步值')
    except Exception:
        sky.sun_elevation, sky.sun_rotation = old
        context.view_layer.update()
        raise
    return sky, sun, elevation, rotation


def _poll_sync(cls, context, to_sun):
    try:
        sky, sun = _targets(context)
        if to_sun and not sun.is_editable:
            raise ValueError('选中的 Sun 不可编辑')
        if not to_sun and not sky.id_data.is_editable:
            raise ValueError('活跃 Sky Texture 的节点树不可编辑')
    except ValueError as error:
        cls.poll_message_set(str(error))
        return False
    return True


class WM_OT_sky_angles_to_sun_coords_visn(bpy.types.Operator):
    bl_idname = 'wm.sky_angles_to_sun_coords_visn'
    bl_label = 'Sky → Sun 位置'
    bl_description = '将活跃 Sky Texture 的角度同步到选中 Sun 的世界位置；保留距世界原点的距离，原点时用距离1；支持撤销'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_sync(cls, context, True)

    def execute(self, context):
        try:
            sky, sun, position, radius = sync_sky_to_sun(context)
        except (ValueError, RuntimeError) as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f'{sky.name} → {sun.name}：世界位置 '
                    f'({position.x:.4f}, {position.y:.4f}, {position.z:.4f})，距离 {radius:.4f}')
        return {'FINISHED'}


class WM_OT_sun_coords_to_sky_angles_visn(bpy.types.Operator):
    bl_idname = 'wm.sun_coords_to_sky_angles_visn'
    bl_label = 'Sun 位置 → Sky'
    bl_description = '将选中 Sun 的世界位置反算并写入活跃 Sky Texture 的 Elevation / Rotation，朝向目标按世界原点；支持撤销'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_sync(cls, context, False)

    def execute(self, context):
        try:
            sky, sun, elevation, rotation = sync_sun_to_sky(context)
        except (ValueError, RuntimeError) as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f'{sun.name} → {sky.name}：Elevation {elevation:.4f}°，Rotation {rotation:.4f}°')
        return {'FINISHED'}


_CLASSES = (WM_OT_sky_angles_to_sun_coords_visn, WM_OT_sun_coords_to_sky_angles_visn)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
