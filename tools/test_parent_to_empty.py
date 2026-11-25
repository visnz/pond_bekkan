"""隔离 P2E 分组回归：中心、父级策略、世界变换/子树及 Pond 行为。"""
import importlib
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
hierarchy = importlib.import_module(ROOT.name + '.core.hierarchy')


def new_scene(name):
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    return scene


def obj(name, location=(0, 0, 0), parent=None, inverse=False):
    result = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(result)
    result.location = location
    if parent is not None:
        result.parent = parent
        if inverse:
            bpy.context.view_layer.update()
            result.matrix_parent_inverse = parent.matrix_world.inverted()
    bpy.context.view_layer.update()
    return result


def select(objects, active=None):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    for selected in objects:
        selected.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[-1]
    bpy.context.view_layer.update()


def close(a, b, epsilon=1e-5):
    return all(abs(x-y) <= max(epsilon, abs(y)*epsilon) for ra, rb in zip(a,b) for x,y in zip(ra,rb))


def group(objects, parent, active=None):
    select(objects, active)
    center = sum((o.matrix_world.translation for o in objects), Vector()) / len(objects)
    scene_objects = tuple(bpy.context.scene.objects)
    worlds = {o: o.matrix_world.copy() for o in scene_objects}
    bases = {o: o.matrix_basis.copy() for o in scene_objects}
    assert bpy.ops.object.parent_to_empty_visn('EXEC_DEFAULT') == {'FINISHED'}
    bpy.context.view_layer.update()
    empty = bpy.context.active_object
    assert empty not in scene_objects and empty.type == 'EMPTY'
    assert empty.parent == parent, (empty.parent, parent)
    assert (empty.matrix_world.translation - center).length < 1e-4
    for original in scene_objects:
        assert close(original.matrix_world, worlds[original]), original.name
        assert original.matrix_basis == bases[original], original.name
    assert list(bpy.context.selected_objects) == [empty]
    return empty


def test_shared_parent():
    for inverse in (False, True):
        new_scene('Shared inverse ' + str(inverse))
        parent = obj('Translated rotated scaled parent', (15, 2, 0))
        parent.rotation_euler.z = math.radians(30)
        parent.scale = (2, 1.5, 1)
        bpy.context.view_layer.update()
        children = [obj('Child '+str(i), (i*4, 0, 0), parent, inverse) for i in range(3)]
        empty = group(children, parent)
        assert all(child.parent == empty for child in children)
        if inverse:
            assert (empty.matrix_world.translation - Vector((4,0,0))).length < 1e-4
        second = group(children, empty)
        assert second.parent == empty
    print('PASS shared_parent_parent_inverse_and_repeat')


def test_different_parents():
    new_scene('Nested parents')
    outer = obj('Outer', (5, 3, 2))
    first = obj('Inner A', (2, 1, 0), outer)
    first.rotation_euler.z = 0.6
    first.scale = (3, 0.5, 2)
    second = obj('Inner B', (-1, 2, 0), first)
    second.rotation_euler.z = -0.4
    bpy.context.view_layer.update()
    children = [obj('A', (1,0,0), first), obj('B', (4,1,0), second)]
    children[0].rotation_euler.z = 0.9  # 非均匀缩放父级 + 子旋转形成剪切。
    children[1].rotation_euler.z = -0.3
    group(children, outer)
    new_scene('Unrelated parents active branch')
    first, second = obj('Root A', (7,0,0)), obj('Root B', (-5,2,0))
    a, b = obj('Selected A', (1,0,0), first), obj('Selected B', (2,0,0), second)
    empty = group([a,b], second, b)
    assert a.parent == b.parent == empty
    new_scene('Root and parented selection')
    parent = obj('Only original parent', (7,0,0))
    a, b = obj('Root object'), obj('Child object', (4,0,0), parent)
    group([a,b], parent, a)
    print('PASS highest_parent_active_branch_and_shear')


def test_selected_parent_child():
    new_scene('Selected parent and child')
    outer = obj('Outer', (2,1,0))
    parent = obj('Selected parent', (3,0,0), outer)
    child = obj('Selected child', (2,0,0), parent)
    descendant = obj('Unselected grandchild', (5,0,0), child)
    group_obj = group([parent, child], outer, child)
    assert parent.parent == group_obj and child.parent == parent and descendant.parent == child
    assert list(group_obj.children) == [parent]
    print('PASS selected_parent_child_subtree_and_no_cycle')


def test_single_and_collections():
    new_scene('Single')
    parent = obj('Parent', (5,2,1))
    parent.rotation_euler = (0.1,0.2,0.4)
    parent.scale = (2,1,0.5)
    child = obj('Single child', (1,3,0), parent, True)
    child.rotation_mode = 'QUATERNION'
    child.rotation_quaternion = (0.98,0,0,0.2)
    group([child], parent)
    new_scene('Collections')
    a,b = obj('A',(0,0,0)), obj('B',(4,0,0))
    first,second = bpy.data.collections.new('First'), bpy.data.collections.new('Second')
    bpy.context.scene.collection.children.link(first)
    bpy.context.scene.collection.children.link(second)
    first.objects.link(a)
    second.objects.link(b)
    bpy.context.scene.collection.objects.unlink(a)
    bpy.context.scene.collection.objects.unlink(b)
    empty = group([a,b], None, b)
    assert set(empty.users_collection) == set(a.users_collection) == set(b.users_collection) == {second}
    print('PASS single_rotation_mode_and_original_collection_policy')


def test_cancel_and_pond():
    new_scene('Singular parent')
    parent = obj('Zero scale parent')
    parent.scale.x = 0
    a,b = obj('A', (1,0,0), parent), obj('B', (3,0,0), parent)
    select([a,b])
    before = set(bpy.context.scene.objects)
    assert bpy.ops.object.parent_to_empty_visn() == {'CANCELLED'}
    assert set(bpy.context.scene.objects) == before and a.parent == b.parent == parent
    new_scene('Pond unchanged')
    outer = obj('Outer', (5,0,0))
    parent = obj('Pond active parent', (3,1,0), outer)
    child = obj('Pond child', (7,2,0))
    select([parent,child], parent)
    world = child.matrix_world.copy()
    assert bpy.ops.pond.group_to_parent() == {'FINISHED'}
    bpy.context.view_layer.update()
    assert child.parent == parent and close(child.matrix_world, world)
    select([child])
    assert bpy.ops.pond.release_up() == {'FINISHED'}
    bpy.context.view_layer.update()
    assert child.parent == outer and close(child.matrix_world, world)
    print('PASS singular_parent_cancel_and_pond_behavior')


def test_constraints_and_restore():
    new_scene('Constraints')
    parent = obj('Constraint parent', (5, 2, 0))
    target = obj('Track target', (8, 3, 4))
    a,b = obj('Tracking child', (1, 0, 0), parent, True), obj('Other child', (3, 0, 0), parent, True)
    constraint = a.constraints.new('TRACK_TO')
    constraint.target = target
    constraint.track_axis = 'TRACK_NEGATIVE_Z'
    bpy.context.view_layer.update()
    group([a,b], parent)
    assert a.constraints[0] == constraint and constraint.target == target
    new_scene('Parent dependent driver rollback')
    parent = obj('Driver parent', (10, 0, 0))
    a,b = obj('Driven child', (0, 0, 0), parent, True), obj('Other child', (2, 0, 0), parent, True)
    # 仅隔离 factory-startup 进程内允许这条测试表达式，不保存用户偏好。
    bpy.context.preferences.filepaths.use_scripts_auto_execute = True
    curve = a.driver_add('location', 0)
    curve.driver.use_self = True
    curve.driver.expression = 'self.parent.location.x'
    a.scale = (-2, 3, 0.5)
    b.delta_location = (0.1, 0.2, 1)
    b.delta_scale = (1.5, 0.5, 2)
    extra = bpy.data.collections.new('Driver extra collection')
    bpy.context.scene.collection.children.link(extra)
    extra.objects.link(a)
    select([a,b], b)
    assert curve.driver.is_valid and a.location.x == 10
    def snapshot():
        bpy.context.view_layer.update()
        return {o.name: (o.parent.name if o.parent else None, o.parent_type, o.parent_bone,
                        o.matrix_basis.copy(), o.matrix_parent_inverse.copy(), o.matrix_world.copy(),
                        set(o.users_collection), o.select_get(), tuple(o.location), tuple(o.scale),
                        tuple(o.rotation_euler), tuple(o.delta_location), tuple(o.delta_scale))
                for o in bpy.context.scene.objects}
    before = snapshot()
    assert bpy.ops.object.parent_to_empty_visn() == {'CANCELLED'}
    assert snapshot() == before
    assert bpy.context.active_object == b and curve.driver.expression == 'self.parent.location.x'
    print('PASS constraints_and_parent_dependent_driver_rollback')


def test_special_parents():
    new_scene('Vertex parent')
    mesh = bpy.data.meshes.new('Parent mesh')
    mesh.from_pydata([(0,0,0), (2,0,0), (0,2,0)], [], [(0,1,2)])
    parent = bpy.data.objects.new('Vertex parent', mesh)
    bpy.context.scene.collection.objects.link(parent)
    parent.location = (2, 3, 1)
    a = obj('Vertex child', (1, 0, 0), parent)
    a.parent_type = 'VERTEX'
    a.parent_vertices[0] = 1
    bpy.context.view_layer.update()
    group([a], parent)
    new_scene('Bone parent')
    armature = bpy.data.armatures.new('Parent armature')
    parent = bpy.data.objects.new('Bone parent', armature)
    bpy.context.scene.collection.objects.link(parent)
    select([parent])
    bpy.ops.object.mode_set(mode='EDIT')
    bone = armature.edit_bones.new('Bone')
    bone.head, bone.tail = (0,0,0), (0,0,2)
    bpy.ops.object.mode_set(mode='OBJECT')
    parent.location = (3, 1, 2)
    a = obj('Bone child', (1, 0, 0), parent)
    a.parent_type, a.parent_bone = 'BONE', 'Bone'
    bpy.context.view_layer.update()
    group([a], parent)
    print('PASS_vertex_and_bone_parent_world_transform')


hierarchy.register()
try:
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        test_shared_parent()
        test_different_parents()
        test_selected_parent_child()
        test_single_and_collections()
        test_cancel_and_pond()
        test_constraints_and_restore()
        test_special_parents()
    print('PASS_PARENT_TO_EMPTY', bpy.app.version_string)
finally:
    hierarchy.unregister()
