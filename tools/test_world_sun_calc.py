"""隔离双向同步回归：方向约定、选中目标、父级转换及其他数据保护。"""
import importlib
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
calc = importlib.import_module(ROOT.name + '.core.world_sun_calc')


def run():
    # 独立已知值，避免正反函数共同出现同一种方向错误时互相掩盖。
    known = (-0.5515534897060071, -0.6573158528650077, 0.51354125205817)
    assert all(math.isclose(a, b, abs_tol=1e-12) for a, b in
               zip(calc.sky_angles_to_position(30.9, 220), known))
    for rotation, expected in ((0, (0, 1, 0)), (90, (1, 0, 0)),
                               (180, (0, -1, 0)), (270, (-1, 0, 0))):
        assert all(math.isclose(a, b, abs_tol=1e-12) for a, b in
                   zip(calc.sky_angles_to_position(0, rotation), expected))
    for elevation in (-70, -30, 0, 30.9, 70):
        for rotation in (-40, 0, 90, 220, 359, 400):
            position = calc.sky_angles_to_position(elevation, rotation, 12.5)
            e, r, radius = calc.position_to_sky_angles(position)
            assert math.isclose(e, elevation, abs_tol=1e-10)
            assert math.isclose(r, rotation % 360, abs_tol=1e-10)
            assert math.isclose(radius, 12.5, abs_tol=1e-10)
    assert calc.position_to_sky_angles((0, 0, 2)) == (90, 0, 2)
    assert calc.position_to_sky_angles((0, 0, -2)) == (-90, 0, 2)
    try:
        calc.position_to_sky_angles((0, 0, 0))
    except ValueError:
        pass
    else:
        raise AssertionError('原点应拒绝计算方向')
    print('PASS world_sun_known_direction_axes_roundtrip_and_poles')

    addon.register()
    try:
        scene = bpy.context.scene
        world = scene.world
        sky = world.node_tree.nodes.new('ShaderNodeTexSky')
        sky.sky_type = 'MULTIPLE_SCATTERING'
        sky.sun_elevation, sky.sun_rotation = math.radians(30.9), math.radians(220)
        sun = scene.objects['Light']
        sun.data.type = 'SUN'
        parent = bpy.data.objects.new('Parent', None)
        scene.collection.objects.link(parent)
        parent.location = (2, 3, 4)
        parent.rotation_euler.z = 0.5
        parent.scale = (2, 1.5, 1)
        sun.parent = parent
        sun.location = (1, 2, 3)
        sun.delta_location = (0.1, 0.2, 0.3)
        sun.rotation_euler = (0.2, 0.1, 0.4)
        origin = bpy.data.objects.new('Origin', None)
        scene.collection.objects.link(origin)
        constraint = sun.constraints.new('TRACK_TO')
        constraint.target = origin
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'
        other_sun = bpy.data.objects.new('Other Sun', bpy.data.lights.new('Other Sun', 'SUN'))
        scene.collection.objects.link(other_sun)
        other_sun.location = (9, 8, 7)
        other_sky = world.node_tree.nodes.new('ShaderNodeTexSky')
        other_sky.sun_elevation, other_sky.sun_rotation = 0.5, 0.7
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        sun.select_set(True)
        bpy.context.view_layer.objects.active = sun
        bpy.context.view_layer.update()
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        area.type = 'NODE_EDITOR'
        area.spaces.active.tree_type = 'ShaderNodeTree'
        area.spaces.active.shader_type = 'WORLD'
        area.spaces.active.path.clear()
        area.spaces.active.path.start(world.node_tree)
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            world.node_tree.nodes.active = sky
            sky.select = True
            other_sky.select = True  # 多个天空选中时明确使用活跃的那一个。
            protected = (other_sky.sun_elevation, other_sky.sun_rotation,
                         other_sun.matrix_world.copy(), constraint.target,
                         len(world.node_tree.nodes), len(world.node_tree.links))
            radius = calc._world_position(bpy.context, sun).length
            basis = sun.matrix_basis.to_3x3().copy()
            assert calc._selected_sky(bpy.context) == sky
            assert bpy.ops.wm.sky_angles_to_sun_coords_visn.poll()
            assert bpy.ops.wm.sky_angles_to_sun_coords_visn('EXEC_DEFAULT') == {'FINISHED'}
            expected = Vector(calc.sky_angles_to_position(30.9, 220, radius))
            assert (calc._world_position(bpy.context, sun) - expected).length < 1e-4
            assert all(abs(a - b) < 1e-5 for row1, row2 in zip(basis, sun.matrix_basis.to_3x3())
                       for a, b in zip(row1, row2))
            assert protected == (other_sky.sun_elevation, other_sky.sun_rotation,
                                 other_sun.matrix_world.copy(), constraint.target,
                                 len(world.node_tree.nodes), len(world.node_tree.links))
            # 在更改过的 Sun 世界位置上反算，只改活跃天空的两个角度。
            sky.sun_elevation, sky.sun_rotation = 0.1, 0.2
            position = calc._world_position(bpy.context, sun)
            assert bpy.ops.wm.sun_coords_to_sky_angles_visn('EXEC_DEFAULT') == {'FINISHED'}
            assert math.isclose(math.degrees(sky.sun_elevation), 30.9, abs_tol=1e-4)
            assert math.isclose(math.degrees(sky.sun_rotation), 220, abs_tol=1e-4)
            assert (calc._world_position(bpy.context, sun) - position).length < 1e-6
            assert protected == (other_sky.sun_elevation, other_sky.sun_rotation,
                                 other_sun.matrix_world.copy(), constraint.target,
                                 len(world.node_tree.nodes), len(world.node_tree.links))
            # 多选 Sun 时以活跃对象为准；没有活跃 Sun 的歧义选择不执行。
            other_sun.select_set(True)
            assert calc._selected_sun(bpy.context) == sun
            bpy.context.view_layer.objects.active = scene.objects['Cube']
            assert not bpy.ops.wm.sky_angles_to_sun_coords_visn.poll()
            other_sun.select_set(False)
            assert calc._selected_sun(bpy.context) == sun
            bpy.context.view_layer.objects.active = sun
            sky.select = False
            assert not bpy.ops.wm.sun_coords_to_sky_angles_visn.poll()
            sky.select = True
            sky.sky_type = 'PREETHAM'
            assert not bpy.ops.wm.sun_coords_to_sky_angles_visn.poll()
            sky.sky_type = 'MULTIPLE_SCATTERING'
            # 位置约束导致无法写入时，完整恢复原位置。
            copy = sun.constraints.new('COPY_LOCATION')
            copy.target = other_sun
            bpy.context.view_layer.update()
            location = sun.location.copy()
            assert bpy.ops.wm.sky_angles_to_sun_coords_visn('EXEC_DEFAULT') == {'CANCELLED'}
            assert sun.location == location
            sun.constraints.remove(copy)
            # 原点不能反推方向；正向同步从原点使用距离1。
            sun.parent = None
            sun.delta_location = (0, 0, 0)
            sun.location = (0, 0, 0)
            bpy.context.view_layer.update()
            angles = sky.sun_elevation, sky.sun_rotation
            assert bpy.ops.wm.sun_coords_to_sky_angles_visn('EXEC_DEFAULT') == {'CANCELLED'}
            assert angles == (sky.sun_elevation, sky.sun_rotation)
            assert bpy.ops.wm.sky_angles_to_sun_coords_visn('EXEC_DEFAULT') == {'FINISHED'}
            assert math.isclose(calc._world_position(bpy.context, sun).length, 1, abs_tol=1e-5)
            sun.location = (0, 0, 5)
            sky.sun_rotation = 0.9
            bpy.context.view_layer.update()
            assert bpy.ops.wm.sun_coords_to_sky_angles_visn('EXEC_DEFAULT') == {'FINISHED'}
            assert math.isclose(sky.sun_elevation, math.pi / 2, abs_tol=1e-6)
            assert math.isclose(sky.sun_rotation, 0.9, abs_tol=1e-6)
            area.spaces.active.shader_type = 'OBJECT'
            assert not bpy.ops.wm.sky_angles_to_sun_coords_visn.poll()
            assert not bpy.ops.wm.sun_coords_to_sky_angles_visn.poll()
        print('PASS world_sun_sync_selection_parent_constraints_rollback_and_world_only')
    finally:
        addon.unregister()


run()
print('PASS_WORLD_SUN_CALC', bpy.app.version_string)
