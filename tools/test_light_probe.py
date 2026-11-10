"""隔离后台回归：blender -b --factory-startup --python-exit-code 1 -P 本文件。

仅在隔离实例使用：包含测试工程保存/重开，不要在用户现场运行。
"""
import importlib
from itertools import product
import json
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)


def close(actual, expected, label, epsilon=1e-5):
    error = max(abs(a - b) for a, b in zip(actual, expected))
    assert error < epsilon, (label, tuple(actual), tuple(expected), error)
    return error


def check_corner(control, probe):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = probe.evaluated_get(depsgraph)
    # 探针不提供可用的 Object.bound_box；用 Volume 原生单位盒。
    # 镜像缩放会交换单位盒角索引，因此比较八个真实角点，而非绑定固定索引。
    origin = control.evaluated_get(depsgraph).matrix_world.translation
    corners = [evaluated.matrix_world @ Vector(p) for p in product((-1.0, 1.0), repeat=3)]
    corner = min(corners, key=lambda p: (p - origin).length)
    error = close(corner, origin, '角点绑定', epsilon=1e-4)
    assert all(fc.driver.is_valid for fc in probe.animation_data.drivers)
    assert all(fc.driver.is_simple_expression for fc in probe.animation_data.drivers)
    return error


def check_aim(probe, camera):
    # 检查角点三条内向棱的角平分线，而非仅验证角点位置。
    inward_edges = [probe.rotation_quaternion @ Vector(edge)
                    for edge in [(1, 0, 0), (0, 1, 0), (0, 0, -1)]]
    bisector = sum(inward_edges, Vector()).normalized()
    expected = Vector((0, 0, -1))
    if camera.data.type == 'PERSP':
        expected = sum(camera.data.view_frame(scene=bpy.context.scene), Vector()).normalized()
    close(bisector, expected, '盒角朝向视锥中心')
    assert abs(probe.rotation_quaternion.angle) > 0.1, '不能仍按相机 XYZ 摆放'
    if camera.data.shift_x == 0 and camera.data.shift_y == 0:
        assert all(edge.z < 0 for edge in inward_edges), '三条内向棱都应展开到相机前方'


def create():
    before = set(bpy.data.objects)
    assert bpy.ops.camera.create_volume_probe_visn() == {'FINISHED'}
    control = bpy.context.active_object
    added = set(bpy.data.objects) - before
    assert len(added) == 2 and control in added
    assert control.type == 'EMPTY'
    probe, = [o for o in added if o.type == 'LIGHT_PROBE']
    assert probe.data.type == 'VOLUME' and probe.parent == control
    assert set(bpy.context.selected_objects) == {control}
    close(control.location, (0, 0, 0), '控制器位置')
    close(control.rotation_euler, (0, 0, 0), '控制器旋转')
    close(control.scale, (1, 1, 1), '控制器缩放')
    assert control.matrix_parent_inverse == Matrix.Identity(4)
    check_corner(control, probe)
    check_aim(probe, control.parent)
    return control, probe


addon.register()
try:
    scene = bpy.context.scene
    engine = scene.render.engine
    camera = scene.camera
    cursor = scene.cursor.location.copy()
    original_objects = set(bpy.data.objects)
    camera.location = (2.2, -4.7, 7.1)
    camera.rotation_euler = (0.71, -0.32, 1.1)
    camera.scale = (1.3, 0.8, 2.0)
    bpy.context.view_layer.update()

    # 默认激活网格时回退到场景相机，相机局部坐标系须严格继承。
    control, probe = create()
    assert control.parent == camera
    assert control.matrix_world == camera.matrix_world
    max_error = check_corner(control, probe)
    for scale in [(2.5, 0.7, 4.2), (0.15, 6, 1.1), (-2, 3, -1)]:
        probe.scale = scale
        max_error = max(max_error, check_corner(control, probe))
    control.location = (-2, -1.5, -3)
    control.rotation_euler = (0.2, -0.3, 0.1)
    control.scale = (1.2, 2.1, 0.5)
    max_error = max(max_error, check_corner(control, probe))
    camera.location += Vector((3, 1, -2))
    camera.rotation_euler.z += 0.3
    max_error = max(max_error, check_corner(control, probe))

    # 相机局部位移：控制器局部 X 位移应对应相机矩阵的 X 基向量。
    origin_before = control.matrix_world.translation.copy()
    control.location.x += 1.25
    bpy.context.view_layer.update()
    close(control.matrix_world.translation - origin_before,
          camera.matrix_world.to_3x3() @ Vector((1.25, 0, 0)), '相机空间移动')

    # 用户激活其他相机时优先使用该相机，不改变渲染相机。
    other_camera = bpy.data.objects.new('TestOtherCamera', bpy.data.cameras.new('TestOtherCamera'))
    scene.collection.objects.link(other_camera)
    other_camera.data.type = 'ORTHO'
    bpy.context.view_layer.objects.active = other_camera
    other_control, other_probe = create()
    assert other_control.parent == other_camera and scene.camera == camera
    assert probe.animation_data.drivers[0].driver.variables[0].targets[0].id == probe
    assert other_probe.animation_data.drivers[0].driver.variables[0].targets[0].id == other_probe

    # 同一相机重复创建：独立对象和驱动目标，不覆盖旧数据。
    bpy.context.view_layer.objects.active = camera
    extra_control, extra_probe = create()
    assert extra_control.parent == camera and extra_probe.data != probe.data
    assert original_objects <= set(bpy.data.objects)
    assert scene.render.engine == engine and scene.cursor.location == cursor
    # 除测试主动移动相机外，操作符不修改它的变换。
    saved_camera_matrix = camera.matrix_world.copy()
    bpy.ops.camera.create_volume_probe_visn()
    bpy.context.view_layer.update()
    assert camera.matrix_world == saved_camera_matrix

    # 使用第一版的单变量驱动模拟现场旧探针，校正时保留已调好的控制器/探针尺寸。
    control_before = control.matrix_basis.copy()
    probe_scale_before = probe.scale.copy()
    resolution_before = (probe.data.resolution_x, probe.data.resolution_y, probe.data.resolution_z)
    probe.rotation_mode = 'XYZ'
    probe.rotation_euler = (0, 0, 0)
    for axis, sign in enumerate((1, 1, -1)):
        driver = probe.animation_data.drivers.find('location', index=axis).driver
        for variable in list(driver.variables):
            driver.variables.remove(variable)
        variable = driver.variables.new()
        variable.name = 'half_size'
        variable.type = 'TRANSFORMS'
        variable.targets[0].id = probe
        variable.targets[0].transform_type = ('SCALE_X', 'SCALE_Y', 'SCALE_Z')[axis]
        variable.targets[0].transform_space = 'TRANSFORM_SPACE'
        driver.expression = 'half_size' if sign > 0 else '-half_size'
    bpy.context.view_layer.objects.active = probe
    assert bpy.ops.camera.align_volume_probe_visn() == {'FINISHED'}
    check_aim(probe, camera)
    max_error = max(max_error, check_corner(control, probe))
    assert control.matrix_basis == control_before
    assert probe.scale == probe_scale_before
    assert (probe.data.resolution_x, probe.data.resolution_y, probe.data.resolution_z) == resolution_before
    # 选空物体也能校正；重复执行不积累旋转、驱动或偏移。
    bpy.context.view_layer.objects.active = control
    matrix_before = probe.matrix_world.copy()
    assert bpy.ops.camera.align_volume_probe_visn() == {'FINISHED'}
    for row in range(4):
        close(probe.matrix_world[row], matrix_before[row], '重复校正')
    assert len(probe.animation_data.drivers) == 3

    # 偏移镜头的视锥中心也要匹配，而不是固定使用 -Z。
    camera.data.shift_x, camera.data.shift_y = 0.3, -0.15
    camera.data.lens = 35
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    bpy.context.view_layer.objects.active = camera
    shifted_control, shifted_probe = create()
    check_aim(shifted_probe, camera)
    max_error = max(max_error, check_corner(shifted_control, shifted_probe))
    bpy.context.view_layer.objects.active = camera
    assert not bpy.ops.camera.align_volume_probe_visn.poll()

    # 无相机和编辑模式须拒绝执行，不强行改现场模式。
    bpy.context.view_layer.objects.active = control
    scene.camera = None
    assert not bpy.ops.camera.create_volume_probe_visn.poll()
    scene.camera = camera
    mesh = next(o for o in original_objects if o.type == 'MESH')
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    bpy.ops.object.mode_set(mode='EDIT')
    assert not bpy.ops.camera.create_volume_probe_visn.poll()
    bpy.ops.object.mode_set(mode='OBJECT')

    for mode in ('BEKKAN', 'POND', 'BEKKAN'):
        addon.ui.apply_mode(mode)
        panel = bpy.types.Panel.bl_rna_get_subclass_py('BEKKAN_PT_light_compose')
        assert (panel is not None) == (mode == 'BEKKAN')
        assert bpy.ops.camera.create_volume_probe_visn.poll()
        max_error = max(max_error, check_corner(control, probe))

    # 禁用插件、保存重开且禁用 Python 自动执行，原生简单驱动仍能工作。
    control_name, probe_name = control.name, probe.name
    addon.unregister()
    with tempfile.TemporaryDirectory(prefix='visn-probe-test-') as folder:
        path = str(Path(folder) / 'probe.blend')
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path, use_scripts=False)
        control, probe = bpy.data.objects[control_name], bpy.data.objects[probe_name]
        probe.scale = (3, 1.5, 0.75)
        max_error = max(max_error, check_corner(control, probe))
    addon.register()
    assert bpy.ops.camera.create_volume_probe_visn.poll()
    print('PASS_LIGHT_PROBE', json.dumps({
        'blender': bpy.app.version_string,
        'max_corner_error': max_error,
        'checks': ['identity_control', 'camera_space', 'corner_aim', 'shifted_frustum',
                   'legacy_probe_repair', 'idempotent_repair', 'scale_anchor', 'camera_motion',
                   'camera_priority', 'repeat_create', 'context_guards', 'mode_switch',
                   'save_reopen_without_addon_or_scripts', 'reregister'],
    }))
finally:
    addon.unregister()
