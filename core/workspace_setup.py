"""别馆新工程 setup：设置分步骤维护，复用既有搭建操作器。"""
import addon_utils
import bpy
import json
import math
from mathutils import Matrix


_DENOISE_FIELDS = (
    'denoiser', 'denoising_input_passes', 'denoising_prefilter',
    'denoising_quality', 'denoising_use_gpu',
)

_REPORTS = {}
_DEFAULT_SHADER_VALUES = {
    'Base Color': (0.8, 0.8, 0.8, 1), 'Roughness': 0.5, 'IOR': 1.5, 'Alpha': 1,
    'Normal': (0, 0, 0), 'Subsurface Radius': (1, 0.2, 0.1), 'Subsurface Scale': 0.005,
    'Subsurface IOR': 1.4, 'Specular IOR Level': 0.5, 'Specular Tint': (1, 1, 1, 1),
    'Tangent': (0, 0, 0), 'Coat Roughness': 0.03, 'Coat IOR': 1.5,
    'Coat Tint': (1, 1, 1, 1), 'Coat Normal': (0, 0, 0), 'Sheen Roughness': 0.5,
    'Sheen Tint': (1, 1, 1, 1), 'Emission Color': (1, 1, 1, 1), 'Thin Film IOR': 1.33,
}
_SETTING_NAMES = {
    'use_shadows': ('Eevee', '阴影'),
    'use_shadow_jitter_viewport': ('Eevee', '视口抖动阴影'),
    'use_raytracing': ('Eevee', '光线追踪'),
    'resolution_scale': ('Eevee', '光追分辨率'),
    'use_high_quality_normals': ('Eevee', '高质量法线'),
    'use_overscan': ('Eevee', 'Film Overscan'),
    'overscan_size': ('Eevee', 'Overscan 比例'),
    'shadow_pool_size': ('Eevee', 'Shadow Pool'),
    'gi_irradiance_pool_size': ('Eevee', 'Volume Pool'),
    'device': ('Cycles', '计算设备'),
    'use_preview_adaptive_sampling': ('Cycles', '视口自适应采样'),
    'preview_adaptive_threshold': ('Cycles', '视口 Noise Threshold'),
    'use_preview_denoising': ('Cycles', '视口去噪'),
    'preview_denoiser': ('Cycles', '视口去噪算法'),
    'preview_denoising_input_passes': ('Cycles', '视口去噪通道'),
    'preview_denoising_prefilter': ('Cycles', '视口去噪预过滤'),
    'preview_denoising_quality': ('Cycles', '视口去噪质量'),
    'preview_denoising_use_gpu': ('Cycles', '视口去噪使用 GPU'),
    'compositor_device': ('通用', '合成器设备'),
    'use_persistent_data': ('Cycles', 'Persistent Data'),
    'view_transform': ('色彩', 'View Transform'),
    'fps': ('输出', '帧率'),
    'fps_base': ('输出', '帧率基准'),
    'filepath': ('输出', '输出路径'),
    'file_format': ('输出', '文件格式'),
    'use_autopack': ('外部数据', '自动打包资源'),
}


def _same_value(left, right, field=''):
    if isinstance(left, float) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-8)
    if field == 'filepath':
        return left.replace('\\', '/') == right.replace('\\', '/')
    return left == right


def _display_value(field, value):
    if isinstance(value, bool):
        return '开启' if value else '关闭'
    if field == 'overscan_size':
        return f'{value:g}%'
    if isinstance(value, float):
        return f'{value:.6g}'
    if field == 'resolution_scale':
        return '1:' + str(value)
    if field in {'shadow_pool_size', 'gi_irradiance_pool_size'}:
        return f'{int(value) / 1024:g} GB' if int(value) >= 1024 else f'{value} MB'
    names = {'BLENDER_EEVEE': 'Eevee', 'BLENDER_WORKBENCH': 'Workbench', 'CYCLES': 'Cycles',
             'OPENIMAGEDENOISE': 'OpenImageDenoise', 'OPTIX': 'OptiX', 'AUTO': '自动',
             'RGB': '仅颜色', 'RGB_ALBEDO': '颜色 + Albedo',
             'RGB_ALBEDO_NORMAL': '颜色 + Albedo + Normal', 'NONE': '无',
             'ACCURATE': '精确', 'FAST': '快速', 'HIGH': '高', 'BALANCED': '均衡'}
    return names.get(value, str(value))


def _setting_entry(field, old, new, group=None, label=None):
    default_group, default_label = _SETTING_NAMES.get(field, ('通用', field))
    return {'group': group or default_group, 'label': label or default_label,
            'old': _display_value(field, old), 'new': _display_value(field, new)}


def _action(report, label, detail, status='PRESERVED'):
    report['scene_actions'].append({'label': label, 'detail': detail, 'status': status})


def last_setup_report(scene):
    return _REPORTS.get(scene.session_uid)


def scene_setup_mode(scene):
    """必须确认是原始三件套，不能仅凭数量/类型清空已编辑的工程。"""
    objects = list(scene.objects)
    if not objects:
        return 'EMPTY'
    defaults = {
        'Cube': ('MESH', (0, 0, 0), (0, 0, 0)),
        'Camera': ('CAMERA', (7.3588915, -6.9257908, 4.9583092), (1.109319, 0, 0.8149282)),
        'Light': ('LIGHT', (4.0762453, 1.0054539, 5.903862), (0.650328, 0.0552171, 1.8663908)),
    }
    if len(objects) != 3 or {o.name for o in objects} != set(defaults):
        return 'EXISTING'
    for obj in objects:
        kind, location, rotation = defaults[obj.name]
        if (obj.type != kind or obj.parent or obj.constraints or obj.modifiers or obj.animation_data
                or obj.data.animation_data or obj.keys() or obj.data.keys() or not obj.is_editable
                or obj.hide_viewport or obj.hide_render or obj.hide_select):
            return 'EXISTING'
        if any(not math.isclose(a, b, abs_tol=1e-5) for values, expected in
               ((obj.location, location), (obj.rotation_euler, rotation), (obj.scale, (1, 1, 1)))
               for a, b in zip(values, expected)):
            return 'EXISTING'
    cube, camera, light = (scene.objects[name] for name in ('Cube', 'Camera', 'Light'))
    mesh = cube.data
    expected_vertices = [(x, y, z) for x in (1, -1) for y in (1, -1) for z in (1, -1)]
    expected_faces = {(0, 4, 6, 2), (3, 2, 6, 7), (7, 6, 4, 5),
                      (5, 1, 3, 7), (1, 0, 2, 3), (5, 4, 0, 1)}
    if ([tuple(v.co) for v in mesh.vertices] != expected_vertices
            or {tuple(p.vertices) for p in mesh.polygons} != expected_faces
            or mesh.shape_keys or any(p.use_smooth for p in mesh.polygons)
            or light.data.type != 'POINT' or not _same_value(light.data.energy, 1000)
            or tuple(light.data.color) != (1, 1, 1) or camera.data.type != 'PERSP'
            or not _same_value(camera.data.lens, 50) or camera.data.dof.use_dof
            or any(not _same_value(getattr(camera.data, field), value) for field, value in
                   (('sensor_width', 36), ('sensor_height', 24), ('shift_x', 0), ('shift_y', 0),
                    ('clip_start', 0.1), ('clip_end', 100)))):
        return 'EXISTING'
    default_uv = [(0.625, 0.5), (0.875, 0.5), (0.875, 0.75), (0.625, 0.75),
                  (0.375, 0.75), (0.625, 0.75), (0.625, 1), (0.375, 1),
                  (0.375, 0), (0.625, 0), (0.625, 0.25), (0.375, 0.25),
                  (0.125, 0.5), (0.375, 0.5), (0.375, 0.75), (0.125, 0.75),
                  (0.375, 0.5), (0.625, 0.5), (0.625, 0.75), (0.375, 0.75),
                  (0.375, 0.25), (0.625, 0.25), (0.625, 0.5), (0.375, 0.5)]
    if (len(mesh.uv_layers) != 1 or mesh.uv_layers[0].name != 'UVMap'
            or [tuple(value.uv) for value in mesh.uv_layers[0].data] != default_uv):
        return 'EXISTING'
    # 自定义材质意味着三件套已被用于工作，不能当作可丢弃的初始内容。
    for material in mesh.materials:
        if material is None:
            continue
        tree = material.node_tree
        shader = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if (material.name != 'Material' or len(tree.nodes) != 2 or shader is None
                or any(node.type not in {'BSDF_PRINCIPLED', 'OUTPUT_MATERIAL'} for node in tree.nodes)
                or len(tree.links) != 1):
            return 'EXISTING'
        for socket in shader.inputs:
            if not hasattr(socket, 'default_value'):
                continue
            expected = _DEFAULT_SHADER_VALUES.get(socket.name, 0)
            value = socket.default_value
            if isinstance(expected, tuple):
                if any(not _same_value(a, b) for a, b in zip(value, expected)):
                    return 'EXISTING'
            elif not _same_value(value, expected):
                return 'EXISTING'
    return 'DEFAULT'


def _has_sky(world):
    pending = [getattr(world, 'node_tree', None)]
    visited = set()
    while pending:
        tree = pending.pop()
        if tree is None or tree in visited:
            continue
        visited.add(tree)
        for node in tree.nodes:
            if node.type == 'TEX_SKY':
                return True
            if node.type == 'GROUP':
                pending.append(node.node_tree)
    return False


def _ensure_rigify():
    try:
        bpy.ops.object.armature_human_metarig_add.get_rna_type()
        return False
    except (AttributeError, KeyError, RuntimeError):
        pass
    # 同时兼容随附插件和扩展包安装；不下载或安装缺失的插件。
    module = next((m.__name__ for m in addon_utils.modules()
                   if m.__name__.rsplit('.', 1)[-1] == 'rigify'), None)
    if module is None or addon_utils.enable(module, default_set=True) is None:
        raise RuntimeError('未找到可启用的 Rigify，请先安装 Rigify 后再运行 setup')
    bpy.ops.object.armature_human_metarig_add.get_rna_type()
    return True


def render_settings_plan(scene):
    """两个引擎的参数可直接写入，无需切换当前渲染器。"""
    eevee = getattr(scene, 'eevee', None)
    cycles = getattr(scene, 'cycles', None)
    ray = getattr(eevee, 'ray_tracing_options', None)
    render = scene.render
    changes = [
        (eevee, 'use_shadows', True),
        (eevee, 'use_shadow_jitter_viewport', True),
        (eevee, 'use_raytracing', True),
        (ray, 'resolution_scale', '1'),
        (render, 'use_high_quality_normals', True),
        (eevee, 'use_overscan', True),
        (eevee, 'overscan_size', 10.0),
        (eevee, 'shadow_pool_size', '2048'),
        (eevee, 'gi_irradiance_pool_size', '1024'),
        (cycles, 'device', 'GPU'),
        (cycles, 'use_preview_adaptive_sampling', True),
        (cycles, 'preview_adaptive_threshold', 0.02),
        (cycles, 'use_preview_denoising', True),
        (render, 'compositor_device', 'GPU'),
        (render, 'use_persistent_data', True),
        (scene.view_settings, 'view_transform', 'ACES 2.0'),
        (render, 'fps', 30),
        (render, 'fps_base', 1.0),
        (render, 'filepath', '//output/output.png'),
        (render.image_settings, 'file_format', 'PNG'),
        (bpy.data, 'use_autopack', True),
    ]
    for field in _DENOISE_FIELDS:
        if cycles is None or not hasattr(cycles, field):
            raise RuntimeError(f'当前 Blender 缺少 Cycles 设置：{field}')
        changes.append((cycles, 'preview_' + field, getattr(cycles, field)))
    for owner, field, _value in changes:
        if owner is None or not hasattr(owner, field):
            raise RuntimeError(f'当前 Blender 不支持所需设置：{field}')
    return changes


def create_sky_world(source, report):
    # 复制已有 World 后追加节点，不改其他场景共用的世界数据。
    world = source.copy() if source else bpy.data.worlds.new('Setup World')
    tree = world.node_tree
    sky = tree.nodes.new('ShaderNodeTexSky')
    output = next((n for n in tree.nodes if n.type == 'OUTPUT_WORLD'
                   and getattr(n, 'is_active_output', False)), None)
    if output is None:
        output = next((n for n in tree.nodes if n.type == 'OUTPUT_WORLD'), None)
    if output is None:
        output = tree.nodes.new('ShaderNodeOutputWorld')
        output.location = (40, 0)
    background = next((link.from_node for link in output.inputs['Surface'].links
                       if link.from_node.type == 'BACKGROUND'), None)
    if background is None:
        background = next((n for n in tree.nodes if n.type == 'BACKGROUND'), None)
    if background is None:
        background = tree.nodes.new('ShaderNodeBackground')
        background.location = (-200, 0)
    sky.location = (background.location.x - 300, background.location.y)
    if not background.inputs['Color'].is_linked:
        tree.links.new(sky.outputs['Color'], background.inputs['Color'])
        detail = '新增 Sky Texture 并连接到 Background；保留原节点和参数'
    else:
        detail = '新增 Sky Texture；已有环境颜色连线保留，未自动覆盖'
    if not output.inputs['Surface'].is_linked:
        tree.links.new(background.outputs[0], output.inputs['Surface'])
    _action(report, '天空', detail, 'ADDED')
    return world


def _select_only(context, obj):
    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _run(operator, **kwargs):
    if operator('EXEC_DEFAULT', **kwargs) != {'FINISHED'}:
        raise RuntimeError(f'搭建步骤未完成：{operator.idname()}')


def create_setup_objects(context, bootstrap, camera, sun, report):
    """完整搭建仅用于空/默认场景；已有工程只补缺少的相机和 Sun。"""
    box = None
    target = next((obj for obj in (context.active_object, *context.selected_objects)
                   if obj and obj.type == 'MESH' and not obj.hide_select
                   and obj.visible_get(view_layer=context.view_layer)), None)
    if bootstrap:
        _run(bpy.ops.mesh.primitive_cube_add, size=2, enter_editmode=False,
             align='WORLD', location=(0, 0, 0), rotation=(0, 0, 0))
        box = target = context.object
        box.name = 'Box'
        _action(report, 'Box', '新增世界原点 2m 方块', 'ADDED')
    else:
        _action(report, 'Box / Human', '已有工程，跳过测试方块和 Human 骨架')

    if camera is None:
        if target:
            _select_only(context, target)
        else:
            for obj in context.selected_objects:
                obj.select_set(False)
        if context.region_data.view_perspective == 'CAMERA':
            context.region_data.view_perspective = 'PERSP'
        cameras_before = set(context.scene.objects)
        _run(bpy.ops.object.fast_camera_visn)
        camera = next(obj for obj in context.scene.objects
                      if obj not in cameras_before and obj.type == 'CAMERA')
        context.scene.camera = camera
        context.space_data.camera = camera
        _run(bpy.ops.camera.create_focus_object)
        _action(report, '摄像机', f'新增 C-P 相机组和对焦对象：{camera.name}', 'ADDED')
    else:
        _action(report, '摄像机', f'保留活跃摄像机及其父级、景深设置：{camera.name}')

    if sun is None:
        temporary_target = None
        if target:
            _select_only(context, target)
        else:
            _run(bpy.ops.object.add, type='EMPTY', location=(0, 0, 0))
            temporary_target = context.object
        _run(bpy.ops.object.add_light_with_constraint)
        sun = context.object
        sun.data.type = 'SUN'
        sun.data.energy = 10
        if temporary_target:
            bpy.data.objects.remove(temporary_target, do_unlink=True)
        _action(report, 'Sun', f'新增中心约束 Sun，强度 10：{sun.name}', 'ADDED')
    else:
        _action(report, 'Sun', f'保留已有 Sun：{sun.name}（强度 {sun.data.energy:g}）')

    if bootstrap:
        _run(bpy.ops.object.armature_human_metarig_add)
        human = context.object
        human.matrix_world = Matrix.Identity(4)
        _action(report, 'Human', '新增世界原点 Rigify Human 元骨架', 'ADDED')
        _select_only(context, box)
    return box


def enable_setup_overlays(space):
    """直接打开调用视图的检查叠加，不计入 setup 设置比较或报告。"""
    overlay = getattr(space, 'overlay', None)
    if overlay is None:
        return
    for field in ('show_overlays', 'show_stats', 'show_performance',
                  'show_wireframes', 'show_face_orientation'):
        if hasattr(overlay, field):
            setattr(overlay, field, True)


def setup_workspace(context):
    """检测场景、按需搭建，并返回本次实际改动；失败恢复原状态。"""
    mode = scene_setup_mode(context.scene)
    bootstrap = mode in {'EMPTY', 'DEFAULT'}
    rigify_enabled = _ensure_rigify() if bootstrap else False
    changes = render_settings_plan(context.scene)
    scene = context.scene
    camera = scene.camera if not bootstrap and scene.camera in list(scene.objects) else None
    sun = next((o for o in scene.objects if o.type == 'LIGHT' and o.data.type == 'SUN'), None)
    if bootstrap:
        sun = None
    has_sky = _has_sky(scene.world)
    report = {'mode': {'EMPTY': '空场景', 'DEFAULT': '原始三件套', 'EXISTING': '已有工程'}[mode],
              'changed': [], 'unchanged': [], 'scene_actions': []}
    if rigify_enabled:
        _action(report, 'Rigify', '已启用 Rigify 插件', 'ADDED')
    old_engine = scene.render.engine
    old_settings = [(owner, field, getattr(owner, field)) for owner, field, _ in changes]
    old_working_space = bpy.data.colorspace.working_space
    old_world, old_camera = scene.world, scene.camera
    old_space_camera = context.space_data.camera
    old_layer = context.view_layer.active_layer_collection
    old_selected = list(context.selected_objects)
    old_active = context.view_layer.objects.active
    old_perspective = context.region_data.view_perspective
    old_view = (context.region_data.view_location.copy(), context.region_data.view_rotation.copy(),
                context.region_data.view_distance)
    old_children = list(scene.collection.children)
    old_root_objects = list(scene.collection.objects)
    # 只清理本次调用新建的数据，绝不按名称猜测用户对象。
    tracked = (bpy.data.objects, bpy.data.meshes, bpy.data.cameras,
               bpy.data.lights, bpy.data.armatures, bpy.data.worlds, bpy.data.collections)
    before = [set(collection) for collection in tracked]
    try:
        # 官方操作器会正确转换已有颜色数据；File 工作空间是整个 .blend 的设置。
        if old_working_space != 'ACEScg':
            _run(bpy.ops.wm.set_working_color_space, working_space='ACEScg', convert_colors=True)
        destination = 'unchanged' if old_working_space == 'ACEScg' else 'changed'
        report[destination].append(_setting_entry('working_space', old_working_space,
                                                 bpy.data.colorspace.working_space,
                                                 '色彩', 'File Working Space'))
        initial_values = {(owner, field): value for owner, field, value in old_settings}
        for owner, field, value in changes:
            old = initial_values[owner, field]
            if not _same_value(getattr(owner, field), value, field):
                setattr(owner, field, value)
            destination = 'unchanged' if _same_value(old, value, field) else 'changed'
            report[destination].append(_setting_entry(field, old, getattr(owner, field)))
        report['unchanged'].append(_setting_entry('engine', old_engine, old_engine,
                                                 '通用', '当前渲染器'))

        collection = None
        if bootstrap or camera is None or sun is None:
            collection = bpy.data.collections.new('Setup')
            scene.collection.children.link(collection)
            context.view_layer.update()
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collection.name]
        box = create_setup_objects(context, bootstrap, camera, sun, report)
        if has_sky:
            _action(report, '天空', '已有 Sky Texture，保留世界材质、天空参数和连线')
        else:
            scene.world = create_sky_world(old_world, report)
        # 中心约束脚本会临时在根集合创建灯光；把本次搭建结果统一收进 Setup。
        for obj in set(bpy.data.objects) - before[0]:
            if collection not in obj.users_collection:
                collection.objects.link(obj)
            for owner in list(obj.users_collection):
                if owner != collection:
                    owner.objects.unlink(obj)

        # 解除当前场景的旧入口，也覆盖隐藏/禁选/被排除集合中的对象。
        # 不全局删除数据，其他 Scene 或实例仍然可以引用原对象/集合。
        if mode == 'DEFAULT':
            for child in old_children:
                scene.collection.children.unlink(child)
            for obj in old_root_objects:
                scene.collection.objects.unlink(obj)
            _action(report, '场景内容', '原始 Cube / Camera / Light 已整套替换为 setup', 'CHANGED')
        else:
            _action(report, '场景内容', '空场景已搭建' if bootstrap else
                    f'原有 {len(before[0] & set(scene.objects))} 个对象及集合全部保留',
                    'ADDED' if bootstrap else 'PRESERVED')
        if not bootstrap:
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj in old_selected:
                obj.select_set(True)
            context.view_layer.objects.active = old_active
            context.view_layer.active_layer_collection = old_layer
        enable_setup_overlays(context.space_data)
        _REPORTS[scene.session_uid] = report
        return report
    except Exception:
        if context.mode != 'OBJECT' and context.object:
            bpy.ops.object.mode_set(mode='OBJECT')
        scene.world, scene.camera = old_world, old_camera
        context.space_data.camera = old_space_camera
        for child in old_children:
            if child.name not in scene.collection.children:
                scene.collection.children.link(child)
        for obj in old_root_objects:
            if obj.name not in scene.collection.objects:
                scene.collection.objects.link(obj)
        context.view_layer.active_layer_collection = old_layer
        for collection, previous in zip(tracked, before):
            for item in set(collection) - previous:
                collection.remove(item, do_unlink=True)
        if bpy.data.colorspace.working_space != old_working_space:
            _run(bpy.ops.wm.set_working_color_space,
                 working_space=old_working_space, convert_colors=True)
        for owner, field, value in reversed(old_settings):
            setattr(owner, field, value)
        for obj in old_selected:
            obj.select_set(True)
        context.view_layer.objects.active = old_active
        context.region_data.view_perspective = old_perspective
        context.region_data.view_location, context.region_data.view_rotation, context.region_data.view_distance = old_view
        raise
    finally:
        if scene.render.engine != old_engine:
            scene.render.engine = old_engine


class VIEW3D_OT_setup_workspace_visn(bpy.types.Operator):
    bl_idname = 'view3d.setup_workspace_visn'
    bl_label = '一键 setup 工作区'
    bl_description = ('设置双引擎、ACES 与输出；空/原始场景完整搭建，已有工程只补缺少的'
                      '相机、Sun 和天空，并显示具体改动报告；场景改动可撤销')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        if not space or space.type != 'VIEW_3D' or context.mode != 'OBJECT':
            cls.poll_message_set('请在 3D 视图的物体模式运行')
            return False
        if getattr(space, 'local_view', None):
            cls.poll_message_set('请先退出局部视图，再初始化工作区')
            return False
        return context.scene.is_editable

    def execute(self, context):
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return {'CANCELLED'}
        try:
            with context.temp_override(region=region):
                report = setup_workspace(context)
        except Exception as error:
            self.report({'ERROR'}, f'setup 未完成：{error}')
            return {'CANCELLED'}
        context.area.tag_redraw()
        self.report({'INFO'}, f"setup 完成：修改 {len(report['changed'])} 项设置，"
                    f"原本一致 {len(report['unchanged'])} 项")
        if not bpy.app.background:
            try:
                bpy.ops.wm.workspace_setup_report_visn('INVOKE_DEFAULT',
                    report_json=json.dumps(report, ensure_ascii=False))
            except (AttributeError, KeyError, RuntimeError):
                pass  # core 常驻，只有别馆 UI 注册报告窗口。
        return {'FINISHED'}


def register():
    bpy.utils.register_class(VIEW3D_OT_setup_workspace_visn)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_setup_workspace_visn)
    _REPORTS.clear()
