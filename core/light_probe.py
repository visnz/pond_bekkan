# 别馆灯光合成：相机角点体积探针、EV 吸光体、隐形遮光板及探针烘焙。
import bpy
import re
from mathutils import Matrix, Vector

from .hierarchy import centro_global


_ABSORBER_TAG = 'pond_bekkan_ev_absorber'
_ABSORBER_NAME = re.compile(r'^EV吸光体_(\d+)$')
_BLOCKER_TAG = 'pond_bekkan_invisible_blocker'


def _absorbers():
    """复制或重命名后仍可识别；兼容按约定命名的旧物体。"""
    return [obj for obj in bpy.data.objects
            if obj.type == 'MESH' and (obj.get(_ABSORBER_TAG) or _ABSORBER_NAME.fullmatch(obj.name))]


def _next_absorber_name():
    numbers = [int(match.group(1)) for obj in bpy.data.objects
               if (match := _ABSORBER_NAME.fullmatch(obj.name))]
    number = max(numbers, default=0) + 1
    while f'EV吸光体_{number:02d}' in bpy.data.objects:
        number += 1
    return f'EV吸光体_{number:02d}'


def _empty_output_material():
    for material in bpy.data.materials:
        if (material.get(_ABSORBER_TAG) and material.use_nodes
                and not any(node.type == 'OUTPUT_MATERIAL' for node in material.node_tree.nodes)):
            return material
    material = bpy.data.materials.new('EV吸光体_无输出')
    material.use_nodes = True
    material.node_tree.nodes.clear()
    material[_ABSORBER_TAG] = True
    return material


def create_ev_absorber(context):
    """在 3D Cursor 创建 2m 立方体；不改变现有选择或游标位置。"""
    collection = context.collection
    if collection is None or not collection.is_editable:
        collection = context.scene.collection
    name = _next_absorber_name()
    mesh = bpy.data.meshes.new(name)
    obj = None
    try:
        mesh.from_pydata(
            [(-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
             (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1)],
            [],
            [(2, 6, 4, 0), (5, 7, 3, 1), (4, 5, 1, 0),
             (3, 7, 6, 2), (1, 3, 2, 0), (6, 7, 5, 4)],
        )
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        obj.location = context.scene.cursor.location.copy()
        obj.data.materials.append(_empty_output_material())
        obj[_ABSORBER_TAG] = True
        obj.display_type = 'WIRE'
        obj.visible_camera = False
        obj.visible_shadow = False
        obj.hide_render = True
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        raise
    return obj


def _blocker_material():
    """复用未被修改的遮光板空输出材质；返回材质及是否为本次新建。"""
    for material in bpy.data.materials:
        if material.get(_BLOCKER_TAG) and material.use_nodes:
            nodes = material.node_tree.nodes
            if len(nodes) == 1 and nodes[0].type == 'OUTPUT_MATERIAL' and not material.node_tree.links:
                return material, False
    material = bpy.data.materials.new('隐形遮光板_空输出')
    try:
        material.use_nodes = True
        material.node_tree.nodes.clear()
        material.node_tree.nodes.new('ShaderNodeOutputMaterial')
        material[_BLOCKER_TAG] = True
    except Exception:
        bpy.data.materials.remove(material)
        raise
    return material, True


def create_invisible_blocker(context):
    """沿用中心约束灯光的世界原点均值与父级跟踪方式，不改变当前选择。"""
    selected = tuple(context.selected_objects)
    if not selected:
        raise ValueError('请先选中用于确定中心的物体')
    collection = context.scene.collection
    if not collection.is_editable:
        raise ValueError('当前场景根集合不可编辑')
    context.view_layer.update()
    center = centro_global(selected)
    control = plane = mesh = material = None
    created_material = False
    try:
        control = bpy.data.objects.new('隐形遮光板组', None)
        collection.objects.link(control)
        control.location = center
        mesh = bpy.data.meshes.new('隐形遮光板')
        mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
        mesh.update()
        plane = bpy.data.objects.new('隐形遮光板', mesh)
        collection.objects.link(plane)
        plane.parent = control
        plane.matrix_parent_inverse = Matrix.Identity(4)
        plane.matrix_basis = Matrix.Identity(4)
        track = plane.constraints.new(type='DAMPED_TRACK')
        track.target = control
        track.track_axis = 'TRACK_NEGATIVE_Z'
        material, created_material = _blocker_material()
        mesh.materials.append(material)
        plane[_BLOCKER_TAG] = True
        plane.display_type = 'BOUNDS'
        if hasattr(plane, 'visible_camera'):
            plane.visible_camera = False
        if hasattr(plane, 'visible_shadow'):
            plane.visible_shadow = True
        plane.hide_render = False
        space = context.space_data
        if space and space.type == 'VIEW_3D' and space.local_view:
            control.local_view_set(space, True)
            plane.local_view_set(space, True)
        context.view_layer.update()
    except Exception:
        # 只回滚本次对象、网格和新材质，不清理用户现有数据。
        if plane is not None:
            bpy.data.objects.remove(plane, do_unlink=True)
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
        if control is not None:
            bpy.data.objects.remove(control, do_unlink=True)
        if created_material:
            bpy.data.materials.remove(material)
        raise
    return control, plane


def _camera_for_context(context):
    """优先用激活的相机，否则用场景相机；不改变场景的渲染相机。"""
    active = context.active_object
    camera = active if active and active.type == 'CAMERA' else context.scene.camera
    if camera and camera.type == 'CAMERA' and camera.name in context.view_layer.objects:
        return camera
    return None


def _corner_orientation(camera, scene):
    """让盒角的内向角平分线朝向视锥中心，而不是让三条棱沿相机 XYZ。

    使用最短旋转保留稳定的绕视线朝向。透视相机的 shift 也计入视锥中心；
    正交相机的射线平行，因此使用相机 -Z。长方体本身不等于四棱视锥。
    """
    direction = Vector((0, 0, -1))
    if camera.data.type == 'PERSP':
        frame = camera.data.view_frame(scene=scene)
        direction = sum(frame, Vector()) / len(frame)
    return Vector((1, 1, -1)).rotation_difference(direction)


def _bind_corner(probe, rotation):
    """Volume 的局部范围为 [-1, 1]，正缩放时把 (-1, -1, +1) 角放在父级原点。

    盒子先转向视锥，再把中心偏移旋转到同一坐标系；不能只旋转盒子而
    继续使用未旋转的 (sx, sy, -sz) 偏移，否则角点会离开控制器。
    位置跟随半尺寸，缩放探针时角点不动；后续整体旋转交给父级空物体。
    驱动只用内置的简单表达式，不依赖 Python 自动运行或插件回调。
    读取变换通道的 TRANSFORM_SPACE，避免 SINGLE_PROP 自引用变换的依赖循环。
    镜像缩放时通道返回分解后的尺寸，单位盒对应的角索引可能交换，仍有一角重合。
    """
    for axis in range(3):
        driver = probe.driver_add('location', axis).driver
        driver.type = 'SCRIPTED'
        for variable in list(driver.variables):
            driver.variables.remove(variable)
        terms = []
        for component, sign in enumerate((1, 1, -1)):
            variable = driver.variables.new()
            variable.name = ('sx', 'sy', 'sz')[component]
            variable.type = 'TRANSFORMS'
            variable.targets[0].id = probe
            variable.targets[0].transform_type = ('SCALE_X', 'SCALE_Y', 'SCALE_Z')[component]
            variable.targets[0].transform_space = 'TRANSFORM_SPACE'
            terms.append(f'({rotation[axis][component] * sign:.17g})*{variable.name}')
        driver.expression = '+'.join(terms)
    probe.lock_location = (True, True, True)
    probe.lock_rotation = (True, True, True)
    probe.lock_rotation_w = True
    probe.lock_rotations_4d = True


def align_camera_volume_probe(probe, scene):
    """校正本工具探针的静置朝向，保留控制器变换、探针缩放和采样设置。"""
    camera = probe.parent.parent
    orientation = _corner_orientation(camera, scene)
    probe.rotation_mode = 'QUATERNION'
    probe.rotation_quaternion = orientation
    _bind_corner(probe, orientation.to_matrix())


def _is_camera_volume_probe(probe):
    """识别本工具生成的驱动结构，兼容没有额外标记的第一版对象。"""
    if (probe.type != 'LIGHT_PROBE' or probe.data.type != 'VOLUME'
            or not probe.parent or probe.parent.type != 'EMPTY'
            or not probe.parent.parent or probe.parent.parent.type != 'CAMERA'):
        return False
    animation = probe.animation_data
    if animation is None:
        return False
    for axis in range(3):
        curve = animation.drivers.find('location', index=axis)
        if curve is None or curve.driver.type != 'SCRIPTED':
            return False
        variables = list(curve.driver.variables)
        if len(variables) not in {1, 3}:
            return False
        for variable in variables:
            target = variable.targets[0]
            if (variable.type != 'TRANSFORMS' or target.id != probe
                    or target.transform_space != 'TRANSFORM_SPACE'
                    or target.transform_type not in {'SCALE_X', 'SCALE_Y', 'SCALE_Z'}):
                return False
    return True


def camera_volume_probe_for_context(context):
    active = context.active_object
    if active is None:
        return None
    if _is_camera_volume_probe(active):
        return active
    if active.type == 'EMPTY':
        probes = [child for child in active.children if _is_camera_volume_probe(child)]
        if len(probes) == 1:
            return probes[0]
    return None


def create_camera_volume_probe(context, camera):
    """返回 (控制空物体, Volume 探针)，不依赖游标或当前选择。"""
    collection = context.collection
    if collection is None or not collection.is_editable:
        collection = context.scene.collection
    control = probe = data = None
    try:
        control = bpy.data.objects.new(f'{camera.name}_探针控制', None)
        collection.objects.link(control)
        control.empty_display_type = 'ARROWS'
        control.empty_display_size = 0.5
        control.show_in_front = True
        control.parent = camera
        control.matrix_parent_inverse = Matrix.Identity(4)
        control.matrix_basis = Matrix.Identity(4)

        data = bpy.data.lightprobes.new(f'{camera.name}_Volume', 'VOLUME')
        probe = bpy.data.objects.new(f'{camera.name}_体积探针', data)
        collection.objects.link(probe)
        probe.parent = control
        probe.matrix_parent_inverse = Matrix.Identity(4)
        probe.location = (1.0, 1.0, -1.0)
        probe.show_in_front = True
        align_camera_volume_probe(probe, context.scene)

        # 从局部视图创建时也能立即看到本次新对象。
        space = context.space_data
        if space and space.type == 'VIEW_3D' and space.local_view:
            control.local_view_set(space, True)
            probe.local_view_set(space, True)
        context.view_layer.update()
    except Exception:
        # 仅回滚本次分配的数据块，不按名字查找或删除用户物体。
        if probe is not None:
            bpy.data.objects.remove(probe, do_unlink=True)
        if data is not None:
            bpy.data.lightprobes.remove(data)
        if control is not None:
            bpy.data.objects.remove(control, do_unlink=True)
        raise
    return control, probe


class CAMERA_OT_create_volume_probe_visn(bpy.types.Operator):
    bl_idname = 'camera.create_volume_probe_visn'
    bl_label = '创建相机体积探针'
    bl_description = (
        '在激活相机（否则场景相机）下创建归零空物体，Volume 探针角点绑定到它且开口朝向视锥中心。'
        '移动/旋转/缩放空物体调整区域，也可单独缩放探针；'
        '选中探针后在数据属性中烘焙。长方体范围需手动对齐画面'
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            cls.poll_message_set('请在物体模式下创建探针')
            return False
        if not context.scene or _camera_for_context(context) is None:
            cls.poll_message_set('请激活一个相机，或设置当前视图层中的场景相机')
            return False
        return True

    def execute(self, context):
        camera = _camera_for_context(context)
        if camera is None:
            self.report({'WARNING'}, '没有可用相机')
            return {'CANCELLED'}
        try:
            control, probe = create_camera_volume_probe(context, camera)
        except Exception as exc:
            self.report({'ERROR'}, f'创建体积探针失败：{exc}')
            return {'CANCELLED'}
        for obj in context.selected_objects:
            obj.select_set(False)
        control.select_set(True)
        context.view_layer.objects.active = control
        self.report({'INFO'}, '已创建角点探针；移动/缩放空物体框定区域，选中探针后在数据属性中烘焙')
        return {'FINISHED'}


class CAMERA_OT_align_volume_probe_visn(bpy.types.Operator):
    bl_idname = 'camera.align_volume_probe_visn'
    bl_label = '校正探针朝向'
    bl_description = '选中本工具的探针或控制空物体，让盒角开口朝向视锥中心；保留控制器变换和探针尺寸，之后需重新烘焙'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        probe = camera_volume_probe_for_context(context)
        if context.mode != 'OBJECT' or probe is None:
            cls.poll_message_set('请在物体模式下选中本工具的探针或控制空物体')
            return False
        return probe.is_editable

    def execute(self, context):
        probe = camera_volume_probe_for_context(context)
        if probe is None:
            return {'CANCELLED'}
        align_camera_volume_probe(probe, context.scene)
        context.view_layer.update()
        self.report({'INFO'}, '已校正盒角朝向，空物体变换已保留；请重新烘焙探针')
        return {'FINISHED'}


class OBJECT_OT_create_ev_absorber_visn(bpy.types.Operator):
    bl_idname = 'object.create_ev_absorber_visn'
    bl_label = '添加EV吸光体'
    bl_description = '在 3D Cursor 创建无材质输出的立方体；视口线框，默认不参与渲染、相机和阴影'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.scene is not None

    def execute(self, context):
        try:
            obj = create_ev_absorber(context)
        except Exception as exc:
            self.report({'ERROR'}, f'创建EV吸光体失败：{exc}')
            return {'CANCELLED'}
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({'INFO'}, f'已创建 {obj.name}')
        return {'FINISHED'}


class OBJECT_OT_create_invisible_blocker_visn(bpy.types.Operator):
    bl_idname = 'object.create_invisible_blocker_visn'
    bl_label = '创建隐形遮光板'
    bl_description = (
        '在所选物体的中心创建空物体和 Plane，移动 Plane 自动朝向中心。'
        '材质仅保留空 Material Output，显示为 Bounds；关闭 Cycles Camera 射线可见性并保留阴影'
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT' or context.scene is None:
            cls.poll_message_set('请在物体模式下创建遮光板')
            return False
        if not context.selected_objects:
            cls.poll_message_set('请先选中用于确定中心的物体')
            return False
        return True

    def execute(self, context):
        try:
            control, plane = create_invisible_blocker(context)
        except Exception as exc:
            self.report({'ERROR'}, f'创建隐形遮光板失败：{exc}')
            return {'CANCELLED'}
        for selected in context.selected_objects:
            selected.select_set(False)
        plane.select_set(True)
        context.view_layer.objects.active = plane
        self.report({'INFO'}, '已创建隐形遮光板；移动/缩放 Plane 调整遮光范围，移动空物体调整中心')
        return {'FINISHED'}


class OBJECT_OT_bake_ev_absorbers_visn(bpy.types.Operator):
    bl_idname = 'object.bake_ev_absorbers_visn'
    bl_label = '烘焙吸光体'
    bl_description = '临时显示所有EV吸光体，烘焙当前视图层的全部Volume探针，结束后隐藏吸光体'
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT' or context.scene is None:
            cls.poll_message_set('请在物体模式下烘焙')
            return False
        if context.scene.render.engine != 'BLENDER_EEVEE':
            cls.poll_message_set('Volume 探针烘焙需要 EEVEE 渲染引擎')
            return False
        return True

    def execute(self, context):
        probes = [obj for obj in context.view_layer.objects
                  if obj.type == 'LIGHT_PROBE' and obj.data.type == 'VOLUME']
        if not probes:
            self.report({'WARNING'}, '当前视图层没有 Volume Light Probe')
            return {'CANCELLED'}
        absorbers = _absorbers()
        try:
            for obj in absorbers:
                obj.hide_render = False
            context.view_layer.update()
            # EXEC_DEFAULT 是 Blender 自带的同步烘焙路径；返回时才恢复可见性。
            result = bpy.ops.object.lightprobe_cache_bake('EXEC_DEFAULT', subset='ALL')
        except Exception as exc:
            self.report({'ERROR'}, f'Volume 探针烘焙失败：{exc}')
            return {'CANCELLED'}
        finally:
            for obj in absorbers:
                if obj.name in bpy.data.objects:
                    obj.hide_render = True
            context.view_layer.update()
        if 'FINISHED' not in result:
            self.report({'WARNING'}, 'Volume 探针烘焙未完成，吸光体已重新隐藏')
            return {'CANCELLED'}
        self.report({'INFO'}, f'已烘焙 {len(probes)} 个 Volume 探针；{len(absorbers)} 个EV吸光体已重新隐藏')
        return {'FINISHED'}


_classes = (
    CAMERA_OT_create_volume_probe_visn,
    CAMERA_OT_align_volume_probe_visn,
    OBJECT_OT_create_ev_absorber_visn,
    OBJECT_OT_create_invisible_blocker_visn,
    OBJECT_OT_bake_ev_absorbers_visn,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
