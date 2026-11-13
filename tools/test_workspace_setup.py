"""隔离 Blender 场景保护与 setup 报告回归，勿在用户工程中运行。"""
import importlib
import json
from pathlib import Path
import sys
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
setup = importlib.import_module(ROOT.name + '.core.workspace_setup')


def assert_settings(scene, engine):
    assert scene.render.engine == engine
    for owner, field, target in setup.render_settings_plan(scene):
        assert setup._same_value(getattr(owner, field), target, field), field
    assert bpy.data.colorspace.working_space == 'ACEScg'


def assert_bootstrap(scene):
    assert len(scene.objects) == 8, [(o.name, o.type) for o in scene.objects]
    box = next(o for o in scene.objects if o.type == 'MESH')
    assert len(box.data.vertices) == 8 and tuple(box.location) == (0, 0, 0)
    camera = scene.camera
    assert camera.parent.parent.type == 'EMPTY'
    assert camera.parent.constraints[0].target == camera.parent.parent
    assert camera.data.dof.focus_object.parent == camera and camera.data.dof.use_dof
    sun = next(o for o in scene.objects if o.type == 'LIGHT')
    assert sun.data.type == 'SUN' and sun.data.energy == 10
    assert sun.constraints[0].target == sun.parent
    human = next(o for o in scene.objects if o.type == 'ARMATURE')
    assert len(human.data.bones) == 159 and tuple(human.location) == (0, 0, 0)
    assert any(b.rigify_type for b in human.pose.bones)
    assert setup._has_sky(scene.world)


def world_signature(world):
    return ({n.name: (n.type, tuple(n.location)) for n in world.node_tree.nodes},
            {(l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier)
             for l in world.node_tree.links})


def new_scene(name):
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    return scene


def mesh_object(scene, name='Existing Model'):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (2, 0, 0), (0, 2, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    return obj


def test_default_detection(scene):
    assert setup.scene_setup_mode(scene) == 'DEFAULT'
    obj = scene.objects['Cube']
    mutations = [(obj.location, 'x', 0.3), (scene.camera.data, 'shift_x', 0.1)]
    for owner, field, value in mutations:
        old = getattr(owner, field)
        setattr(owner, field, value)
        assert setup.scene_setup_mode(scene) == 'EXISTING'
        setattr(owner, field, old)
    shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    for field in ('Alpha', 'IOR', 'Coat Weight'):
        socket = shader.inputs[field]
        old = socket.default_value
        socket.default_value = 0.4
        assert setup.scene_setup_mode(scene) == 'EXISTING', field
        socket.default_value = old
    old_uv = obj.data.uv_layers[0].data[0].uv.copy()
    obj.data.uv_layers[0].data[0].uv.x += 0.1
    assert setup.scene_setup_mode(scene) == 'EXISTING'
    obj.data.uv_layers[0].data[0].uv = old_uv
    assert setup.scene_setup_mode(scene) == 'DEFAULT'
    old_objects = set(scene.objects)
    original_camera = scene.camera
    other = bpy.data.scenes.new('Shared untouched defaults')
    for collection in scene.collection.children:
        other.collection.children.link(collection)
    report = setup.setup_workspace(bpy.context)
    assert report['mode'] == '原始三件套'
    assert_bootstrap(scene)
    assert scene.camera != original_camera and not (set(scene.objects) & old_objects)
    assert set(other.objects) == old_objects
    return scene


def test_repeat_and_exact_report(scene):
    objects, camera, world = set(scene.objects), scene.camera, scene.world
    sun = next(o for o in scene.objects if o.type == 'LIGHT')
    sun.data.energy = 3.75
    camera.data.dof.aperture_fstop = 9
    report = setup.setup_workspace(bpy.context)
    assert not report['changed'] and len(report['unchanged']) == 28
    assert all(a['status'] == 'PRESERVED' for a in report['scene_actions'])
    assert (set(scene.objects), scene.camera, scene.world) == (objects, camera, world)
    assert sun.data.energy == 3.75 and camera.data.dof.aperture_fstop == 9
    scene.render.fps = 24
    scene.eevee.use_shadow_jitter_viewport = False
    scene.cycles.preview_adaptive_threshold = 0.03
    scene.cycles.denoising_quality = 'FAST'
    scene.render.filepath = '//output\\output.png'
    report = setup.setup_workspace(bpy.context)
    labels = {e['label'] for e in report['changed']}
    assert labels == {'帧率', '视口抖动阴影', '视口 Noise Threshold', '视口去噪质量'}, labels
    entry = next(e for e in report['changed'] if e['label'] == '视口 Noise Threshold')
    assert (entry['old'], entry['new']) == ('0.03', '0.02')
    assert any(e['label'] == '输出路径' for e in report['unchanged'])
    assert setup.last_setup_report(scene) == report
    json.dumps(report, ensure_ascii=False)
    assert_settings(scene, scene.render.engine)


def test_empty_and_preserve_existing():
    scene = new_scene('Empty bootstrap')
    assert setup.scene_setup_mode(scene) == 'EMPTY'
    report = setup.setup_workspace(bpy.context)
    assert report['mode'] == '空场景'
    assert_bootstrap(scene)
    scene = new_scene('Existing complete')
    model = mesh_object(scene)
    camera = bpy.data.objects.new('Artist camera', bpy.data.cameras.new('Artist camera'))
    camera.location = (9, 8, 7)
    scene.collection.objects.link(camera)
    scene.camera = camera
    sun = bpy.data.objects.new('Artist sun', bpy.data.lights.new('Artist sun', 'SUN'))
    sun.data.energy = 2.5
    sun.hide_select = True
    scene.collection.objects.link(sun)
    hidden = mesh_object(scene, 'Hidden unselectable model')
    hidden.hide_viewport = hidden.hide_select = True
    world = scene.world = bpy.data.worlds.new('Existing Sky')
    sky = world.node_tree.nodes.new('ShaderNodeTexSky')
    sky.sun_elevation = 0.21
    state = world_signature(world)
    bpy.context.view_layer.objects.active = model
    model.select_set(True)
    objects = set(scene.objects)
    original = setup._ensure_rigify
    def unexpected_enable():
        raise AssertionError('已有工程不应要求或启用 Rigify')
    setup._ensure_rigify = unexpected_enable
    try:
        report = setup.setup_workspace(bpy.context)
    finally:
        setup._ensure_rigify = original
    assert set(scene.objects) == objects and scene.world == world and scene.camera == camera
    assert sun.data.energy == 2.5 and tuple(camera.location) == (9, 8, 7)
    assert world_signature(world) == state and abs(sky.sun_elevation - 0.21) < 1e-6
    assert bpy.context.active_object == model and model.select_get()
    assert all(a['status'] == 'PRESERVED' for a in report['scene_actions'])


def test_missing_assets_and_world_preservation():
    scene = new_scene('Existing missing assets')
    model = mesh_object(scene)
    model.location = (5, 6, 7)
    model.hide_select = True
    # 模型禁选时，Sun 的临时目标由本脚本创建并清理，不添加额外 Box。
    world = scene.world = bpy.data.worlds.new('HDRI-like world')
    background = next(n for n in world.node_tree.nodes if n.type == 'BACKGROUND')
    rgb = world.node_tree.nodes.new('ShaderNodeRGB')
    world.node_tree.links.new(rgb.outputs[0], background.inputs['Color'])
    before = world_signature(world)
    report = setup.setup_workspace(bpy.context)
    assert model in list(scene.objects) and tuple(model.location) == (5, 6, 7)
    assert len(scene.objects) == 7 and sum(o.type == 'MESH' for o in scene.objects) == 1
    assert not any(o.type == 'ARMATURE' for o in scene.objects)
    assert scene.camera.parent.parent and scene.camera.data.dof.focus_object
    assert scene.world != world and world_signature(world) == before
    copied_background = scene.world.node_tree.nodes[background.name]
    assert copied_background.inputs['Color'].links[0].from_node.type == 'RGB'
    assert setup._has_sky(scene.world)
    assert any('未自动覆盖' in a['detail'] for a in report['scene_actions'])
    objects = set(scene.objects)
    assert not setup.setup_workspace(bpy.context)['changed']
    assert set(scene.objects) == objects
    # 已有非活跃相机保留，缺少活跃相机时另外补建；已有 Sun 不重复添加。
    scene.camera = None
    before_suns = {o for o in scene.objects if o.type == 'LIGHT'}
    setup.setup_workspace(bpy.context)
    assert objects <= set(scene.objects) and len(scene.objects) == 11
    assert {o for o in scene.objects if o.type == 'LIGHT'} == before_suns
    # 节点组内部已有天空也应识别，不再添加。
    grouped = bpy.data.worlds.new('Grouped sky')
    group_tree = bpy.data.node_groups.new('Sky group', 'ShaderNodeTree')
    group_tree.nodes.new('ShaderNodeTexSky')
    group = grouped.node_tree.nodes.new('ShaderNodeGroup')
    group.node_tree = group_tree
    assert setup._has_sky(grouped)


def test_rollback():
    scene = new_scene('Rollback existing')
    model = mesh_object(scene)
    scene.render.fps = 12
    objects = set(scene.objects)
    count = tuple(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.cameras,
                                   bpy.data.lights, bpy.data.collections))
    original = setup.create_sky_world
    def fail_world(*args):
        raise RuntimeError('Injected sky failure')
    setup.create_sky_world = fail_world
    try:
        setup.setup_workspace(bpy.context)
    except RuntimeError as error:
        assert 'Injected' in str(error)
    else:
        raise AssertionError('故障注入应失败')
    finally:
        setup.create_sky_world = original
    assert set(scene.objects) == objects and model in list(scene.objects)
    assert scene.render.fps == 12 and scene.camera is None and scene.world is None
    assert tuple(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.cameras,
                                  bpy.data.lights, bpy.data.collections)) == count


def run():
    addon.register()
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    try:
        with bpy.context.temp_override(area=area, region=region):
            scene = test_default_detection(bpy.context.scene)
            print('PASS strict_default_and_shared_scene')
            test_repeat_and_exact_report(scene)
            print('PASS repeat_without_duplicates_and_exact_report')
            test_empty_and_preserve_existing()
            print('PASS empty_and_existing_scene_protection')
            test_missing_assets_and_world_preservation()
            print('PASS missing_assets_and_world_connections')
            test_rollback()
            print('PASS rollback')
        print('PASS_WORKSPACE_SETUP', bpy.app.version_string)
    finally:
        addon.unregister()


if __name__ == '__main__':
    run()
