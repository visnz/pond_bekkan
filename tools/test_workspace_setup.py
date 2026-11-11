"""隔离 Blender 回归；勿在用户工程中运行。"""
import importlib
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
setup = importlib.import_module(ROOT.name + '.core.workspace_setup')


def configure_test_scene(scene):
    scene.render.engine = 'CYCLES'
    scene.cycles.denoising_prefilter = 'NONE'
    scene.cycles.denoising_quality = 'FAST'
    scene.cycles.denoising_input_passes = 'RGB'
    scene.cycles.denoising_use_gpu = False
    scene.render.fps_base = 1.001
    scene.cursor.location = (8, 9, 10)
    # 共享集合、隐藏/禁选和排除对象都必须从本场景移除，另一场景仍然保留。
    other = bpy.data.scenes.new('SharedScene')
    old_collection = next(iter(scene.collection.children))
    other.collection.children.link(old_collection)
    old_objects = set(scene.objects)
    for obj in old_objects:
        obj.hide_select = True
        obj.hide_viewport = True
    context_layer = bpy.context.view_layer.layer_collection.children[old_collection.name]
    context_layer.exclude = True
    root_object = bpy.data.objects.new('RootHidden', None)
    scene.collection.objects.link(root_object)
    root_object.hide_set(True)
    root_object.hide_select = True
    return other, old_objects | {root_object}, old_collection


def assert_setup(scene, engine):
    assert scene.render.engine == engine
    assert scene.eevee.use_shadow_jitter_viewport and scene.eevee.use_raytracing
    assert scene.eevee.ray_tracing_options.resolution_scale == '1'
    assert scene.render.use_high_quality_normals
    assert scene.eevee.shadow_pool_size == '2048'
    assert scene.eevee.gi_irradiance_pool_size == '1024'
    assert scene.cycles.device == 'GPU'
    assert scene.cycles.use_preview_adaptive_sampling
    assert abs(scene.cycles.preview_adaptive_threshold - 0.02) < 1e-6
    assert scene.cycles.use_preview_denoising
    for field in setup._DENOISE_FIELDS:
        assert getattr(scene.cycles, 'preview_' + field) == getattr(scene.cycles, field), field
    assert scene.render.compositor_device == 'GPU' and scene.render.use_persistent_data
    assert scene.view_settings.view_transform == 'ACES 2.0'
    assert bpy.data.colorspace.working_space == 'ACEScg'
    assert scene.render.fps == 30 and scene.render.fps_base == 1
    assert scene.render.filepath == '//output/output.png'
    assert scene.render.image_settings.file_format == 'PNG' and bpy.data.use_autopack
    tree = scene.world.node_tree
    assert {n.type for n in tree.nodes} == {'TEX_SKY', 'BACKGROUND', 'OUTPUT_WORLD'}
    assert {(link.from_node.type, link.to_node.type) for link in tree.links} == {
        ('TEX_SKY', 'BACKGROUND'), ('BACKGROUND', 'OUTPUT_WORLD')}
    assert len(scene.objects) == 8, [(o.name, o.type) for o in scene.objects]
    box = next(obj for obj in scene.objects if obj.type == 'MESH')
    assert len(box.data.vertices) == 8 and tuple(box.location) == (0, 0, 0)
    camera = scene.camera
    assert camera and camera.type == 'CAMERA'
    protection = camera.parent
    central = protection.parent
    assert central.type == protection.type == 'EMPTY'
    assert tuple(central.location) == (0, 0, 0)
    assert protection.constraints[0].target == central
    assert protection.constraints[0].track_axis == 'TRACK_NEGATIVE_Z'
    assert all(camera.lock_location) and all(camera.lock_rotation)
    focus = camera.data.dof.focus_object
    assert camera.data.dof.use_dof and focus.parent == camera
    assert camera.data.passepartout_alpha == 1
    light = next(obj for obj in scene.objects if obj.type == 'LIGHT')
    assert light.data.type == 'SUN' and light.data.energy == 10
    assert light.parent.type == 'EMPTY' and light.constraints[0].target == light.parent
    assert tuple(light.parent.location) == tuple(box.location)
    human = next(obj for obj in scene.objects if obj.type == 'ARMATURE')
    assert len(human.data.bones) == 159
    assert {'spine', 'upper_arm.L', 'thigh.R'} <= set(human.data.bones.keys())
    assert tuple(human.location) == (0, 0, 0)
    assert tuple(human.rotation_euler) == (0, 0, 0) and tuple(human.scale) == (1, 1, 1)
    assert any(bone.rigify_type for bone in human.pose.bones)
    assert {o for o in scene.objects if o.select_get()} == {box}
    assert len(scene.collection.children) == 1
    assert len(scene.collection.children[0].objects) == 8


def run():
    addon.register()
    try:
        scene = bpy.context.scene
        other, old_objects, old_collection = configure_test_scene(scene)
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.view3d.setup_workspace_visn() == {'FINISHED'}
            assert_setup(scene, 'CYCLES')
            assert not (set(scene.objects) & old_objects)
            assert set(other.objects) == old_objects - {bpy.data.objects['RootHidden']}
            assert old_collection in list(other.collection.children)
            assert tuple(scene.cursor.location) == (8, 9, 10)
            print('PASS setup_and_shared_scene_protection')
            # 连续运行不会累加场景对象，且 EEVEE/Workbench 同样恢复。
            for engine in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH'):
                scene.render.engine = engine
                assert bpy.ops.view3d.setup_workspace_visn() == {'FINISHED'}
                assert_setup(scene, engine)
            print('PASS repeat_setup_and_engine_preservation')
            # 中途失败后恢复原对象入口、设置和原相机，不留下半套 setup。
            before = set(scene.objects), scene.camera, scene.world, scene.render.fps
            count_before = tuple(len(c) for c in (bpy.data.objects, bpy.data.meshes,
                                                bpy.data.armatures, bpy.data.collections))
            original = setup.create_sky_world
            def fail_world():
                raise RuntimeError('Injected sky failure')
            setup.create_sky_world = fail_world
            try:
                setup.setup_workspace(bpy.context)
            except RuntimeError as error:
                assert 'Injected' in str(error), str(error)
            else:
                raise AssertionError('故障注入应失败')
            finally:
                setup.create_sky_world = original
            assert (set(scene.objects), scene.camera, scene.world, scene.render.fps) == before
            assert tuple(len(c) for c in (bpy.data.objects, bpy.data.meshes,
                                         bpy.data.armatures, bpy.data.collections)) == count_before
            print('PASS rollback_after_partial_creation')
        print('PASS_WORKSPACE_SETUP', bpy.app.version_string)
    finally:
        addon.unregister()


if __name__ == '__main__':
    run()
