"""隔离验证：blender -b --factory-startup --python-exit-code 1 -P 本文件。

可追加 -- --render 验证 Cycles 相机隐藏及遮光；不要在用户工程中运行。
"""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

import addon_utils
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
errors = []
addon = addon_utils.enable(ROOT.name, default_set=False, refresh_handled=True, handle_error=errors.append)
assert addon is not None and not errors, repr(errors)
core = importlib.import_module(ROOT.name + '.core.light_probe')
scene = bpy.context.scene


def choose(*objects):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0] if objects else None


def close(actual, expected):
    assert (Vector(actual) - Vector(expected)).length < 1e-5, (tuple(actual), tuple(expected))


def create():
    before = set(bpy.data.objects)
    assert bpy.ops.object.create_invisible_blocker_visn() == {'FINISHED'}
    plane = bpy.context.active_object
    control = plane.parent
    assert set(bpy.data.objects) - before == {control, plane}
    assert plane.type == 'MESH' and control.type == 'EMPTY'
    assert set(bpy.context.selected_objects) == {plane}
    assert plane.parent == control and control.parent is None
    assert plane.matrix_parent_inverse == Matrix.Identity(4)
    assert tuple(plane.location) == (0, 0, 0)
    assert len(plane.data.vertices) == 4 and len(plane.data.polygons) == 1
    assert plane.display_type == 'BOUNDS' and not plane.visible_camera
    assert plane.visible_shadow and not plane.hide_render and not plane.hide_select
    assert not plane.hide_get() and len(plane.data.materials) == 1
    nodes = plane.active_material.node_tree.nodes
    assert len(nodes) == 1 and nodes[0].bl_idname == 'ShaderNodeOutputMaterial'
    assert not plane.active_material.node_tree.links
    assert nodes[0].is_active_output
    track, = plane.constraints
    assert track.type == 'DAMPED_TRACK' and track.target == control
    assert track.track_axis == 'TRACK_NEGATIVE_Z'
    assert plane not in core._absorbers(), '遮光板不能被吸光体烘焙流程隐藏'
    return control, plane


try:
    target = scene.objects['Cube']
    parent = bpy.data.objects.new('TargetParent', None)
    scene.collection.objects.link(parent)
    parent.location = (3, -4, 2)
    parent.rotation_euler = (0.2, -0.3, 0.4)
    parent.scale = (1.5, 0.75, 2)
    target.parent = parent
    target.location = (1, 2, 3)
    other = bpy.data.objects.new('OtherTarget', None)
    scene.collection.objects.link(other)
    other.location = (-2, 5, 1)
    bpy.context.view_layer.update()
    choose(target, other)
    center = (target.matrix_world.translation + other.matrix_world.translation) / 2
    originals = {obj: obj.matrix_world.copy() for obj in bpy.data.objects}
    cursor = scene.cursor.location.copy()
    collection = bpy.context.view_layer.active_layer_collection
    camera, engine = scene.camera, scene.render.engine
    control, plane = create()
    close(control.location, center)
    close(plane.matrix_world.translation, center)
    assert set(plane.users_collection) == {scene.collection}
    assert set(control.users_collection) == {scene.collection}
    assert collection == bpy.context.view_layer.active_layer_collection
    assert scene.cursor.location == cursor and scene.camera == camera and scene.render.engine == engine
    assert all(obj.matrix_world == matrix for obj, matrix in originals.items())
    plane.location = (3, -2, 4)
    plane.scale = (2, 3, 1)
    bpy.context.view_layer.update()
    direction = (control.matrix_world.translation - plane.matrix_world.translation).normalized()
    close((plane.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized(), direction)
    before_move = plane.matrix_world.translation.copy()
    control.location += Vector((2, 1, -3))
    bpy.context.view_layer.update()
    close(plane.matrix_world.translation - before_move, (2, 1, -3))

    choose(target, other)
    second_control, second = create()
    assert second.data != plane.data and second.parent != plane.parent
    assert second.active_material == plane.active_material
    original_material = plane.active_material
    original_material.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
    choose(target)
    _, third = create()
    assert third.active_material != original_material and len(original_material.node_tree.nodes) == 2

    choose(target)
    counts = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    with patch.object(core, '_blocker_material', side_effect=RuntimeError('TEST_MATERIAL_FAILURE')):
        try:
            core.create_invisible_blocker(bpy.context)
            raise AssertionError('应回滚创建失败')
        except RuntimeError as exc:
            assert 'TEST_MATERIAL_FAILURE' in str(exc)
    assert counts == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials))
    assert set(bpy.context.selected_objects) == {target} and bpy.context.active_object == target
    choose()
    assert not bpy.ops.object.create_invisible_blocker_visn.poll()
    choose(target)
    bpy.ops.object.mode_set(mode='EDIT')
    assert not bpy.ops.object.create_invisible_blocker_visn.poll()
    bpy.ops.object.mode_set(mode='OBJECT')

    BEKKAN_PT_light_compose = importlib.import_module(ROOT.name + '.ui.bekkan.light_compose_panel').BEKKAN_PT_light_compose
    VIEW3D_PT_stage_visn = importlib.import_module(ROOT.name + '.ui.bekkan.panels').VIEW3D_PT_stage_visn
    icons = bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items
    calls = []
    class Layout:
        def operator(self, idname, **kwargs):
            assert kwargs.get('icon') in icons
            calls.append(idname)
        def separator(self):
            pass
    BEKKAN_PT_light_compose.draw(SimpleNamespace(layout=Layout()), bpy.context)
    assert calls[:2] == ['object.add_light_with_constraint', 'object.create_invisible_blocker_visn']
    assert 'object.add_light_with_constraint' not in VIEW3D_PT_stage_visn.draw.__code__.co_consts
    for mode in ('BEKKAN', 'POND', 'BEKKAN'):
        addon.ui.apply_mode(mode)
        assert bpy.ops.object.create_invisible_blocker_visn.poll()
    print('PASS_INVISIBLE_BLOCKER: center, parent/track, mesh, output-only material, visibility, selection, reuse, rollback, UI placement, modes')

    if '--render' in sys.argv:
        render_scene = bpy.data.scenes.new('InvisibleBlockerRenderTest')
        bpy.context.window.scene = render_scene
        render_scene.render.engine = 'CYCLES'
        render_scene.cycles.device = 'CPU'
        render_scene.cycles.samples = 8
        render_scene.cycles.use_denoising = False
        render_scene.render.resolution_x = render_scene.render.resolution_y = 128
        render_scene.render.resolution_percentage = 100
        render_scene.render.image_settings.file_format = 'PNG'
        world = bpy.data.worlds.new('BlackWorld')
        render_scene.world = world
        world.use_nodes = True
        world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
        bpy.ops.mesh.primitive_plane_add(size=12)
        floor = bpy.context.object
        material = bpy.data.materials.new('WhiteFloor')
        material.use_nodes = True
        material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.8, 0.8, 0.8, 1)
        floor.data.materials.append(material)
        render_control, blocker = core.create_invisible_blocker(bpy.context)
        blocker.location.z = 2
        sun_data = bpy.data.lights.new('TestSun', 'SUN')
        sun_data.energy = 2
        sun_data.angle = 0
        sun = bpy.data.objects.new('TestSun', sun_data)
        render_scene.collection.objects.link(sun)
        camera_data = bpy.data.cameras.new('TestCamera')
        camera_data.type = 'ORTHO'
        camera_data.ortho_scale = 7
        render_camera = bpy.data.objects.new('TestCamera', camera_data)
        render_scene.collection.objects.link(render_camera)
        render_camera.location = (0, -6, 7)
        render_camera.rotation_euler = (-render_camera.location).to_track_quat('-Z', 'Y').to_euler()
        render_scene.camera = render_camera
        folder = ROOT / 'temp/invisible_blocker_render'
        folder.mkdir(parents=True, exist_ok=True)
        def render(name):
            render_scene.render.filepath = str(folder / (name + '.png'))
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(render_scene.render.filepath, check_existing=False)
            values = list(img.pixels)
            bpy.data.images.remove(img)
            return values
        blocker.hide_render = True
        baseline = render('baseline')
        blocker.hide_render = False
        blocker.visible_shadow = False
        transparent = render('camera_hidden_shadow_disabled')
        blocker.visible_shadow = True
        occlusion = render('camera_hidden_shadow_enabled')
        blocker.visible_camera = True
        blocker.visible_shadow = False
        camera_visible = render('camera_visible_shadow_disabled')
        def difference(first, second):
            return sum(abs(a - b) for i, (a, b) in enumerate(zip(first, second)) if i % 4 != 3) / (128 * 128 * 3)
        camera_hidden_error = difference(baseline, transparent)
        shadow_effect = difference(transparent, occlusion)
        visible_effect = difference(transparent, camera_visible)
        assert camera_hidden_error < 0.005, camera_hidden_error
        assert shadow_effect > 0.01, shadow_effect
        assert visible_effect > 0.01, visible_effect
        print('PASS_CYCLES_BLOCKER_RENDER:', {'camera_hidden_error': camera_hidden_error,
              'shadow_effect': shadow_effect, 'camera_visible_effect': visible_effect})
finally:
    addon_utils.disable(ROOT.name, default_set=False, refresh_handled=True, handle_error=errors.append)
    assert not errors, repr(errors)
