"""别馆新工程 setup：设置分步骤维护，复用既有搭建操作器。"""
import addon_utils
import bpy
from mathutils import Matrix


_DENOISE_FIELDS = (
    'denoiser', 'denoising_input_passes', 'denoising_prefilter',
    'denoising_quality', 'denoising_use_gpu',
)


def _ensure_rigify():
    try:
        bpy.ops.object.armature_human_metarig_add.get_rna_type()
        return
    except (AttributeError, KeyError, RuntimeError):
        pass
    # 同时兼容随附插件和扩展包安装；不下载或安装缺失的插件。
    module = next((m.__name__ for m in addon_utils.modules()
                   if m.__name__.rsplit('.', 1)[-1] == 'rigify'), None)
    if module is None or addon_utils.enable(module, default_set=True) is None:
        raise RuntimeError('未找到可启用的 Rigify，请先安装 Rigify 后再运行 setup')
    bpy.ops.object.armature_human_metarig_add.get_rna_type()


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


def create_sky_world():
    # 使用独立 World，避免改动其他 Scene 共用的世界节点。
    world = bpy.data.worlds.new('Setup World')
    tree = world.node_tree
    tree.nodes.clear()
    sky = tree.nodes.new('ShaderNodeTexSky')
    background = tree.nodes.new('ShaderNodeBackground')
    output = tree.nodes.new('ShaderNodeOutputWorld')
    sky.location, background.location, output.location = (-500, 0), (-200, 0), (40, 0)
    tree.links.new(sky.outputs['Color'], background.inputs['Color'])
    tree.links.new(background.outputs[0], output.inputs['Surface'])
    return world


def _select_only(context, obj):
    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _run(operator, **kwargs):
    if operator('EXEC_DEFAULT', **kwargs) != {'FINISHED'}:
        raise RuntimeError(f'搭建步骤未完成：{operator.idname()}')


def create_setup_objects(context):
    """按用户顺序创建 Box、C-P、对焦、中心约束 Sun 和 Human 元骨架。"""
    _run(bpy.ops.mesh.primitive_cube_add, size=2, enter_editmode=False,
         align='WORLD', location=(0, 0, 0), rotation=(0, 0, 0))
    box = context.object
    box.name = 'Box'

    # 原 C-P 操作器依赖 WINDOW 区域；相机视图中先返回可对齐的透视视图。
    if context.region_data.view_perspective == 'CAMERA':
        context.region_data.view_perspective = 'PERSP'
    cameras_before = set(context.scene.objects)
    _run(bpy.ops.object.fast_camera_visn)
    camera = next(obj for obj in context.scene.objects
                  if obj not in cameras_before and obj.type == 'CAMERA')
    context.scene.camera = camera
    context.space_data.camera = camera
    _run(bpy.ops.camera.create_focus_object)

    _select_only(context, box)
    _run(bpy.ops.object.add_light_with_constraint)
    light = context.object
    light.data.type = 'SUN'
    light.data.energy = 10

    _run(bpy.ops.object.armature_human_metarig_add)
    human = context.object
    human.matrix_world = Matrix.Identity(4)
    _select_only(context, box)
    return box, camera, light, human


def setup_workspace(context):
    """先验证依赖并搭建；全部完成后替换当前场景内容，失败保留原场景。"""
    _ensure_rigify()
    changes = render_settings_plan(context.scene)
    scene = context.scene
    old_engine = scene.render.engine
    old_settings = [(owner, field, getattr(owner, field)) for owner, field, _ in changes]
    old_working_space = bpy.data.colorspace.working_space
    old_world, old_camera = scene.world, scene.camera
    old_space_camera = context.space_data.camera
    old_layer = context.view_layer.active_layer_collection
    old_selected = list(context.selected_objects)
    old_active = context.view_layer.objects.active
    old_perspective = context.region_data.view_perspective
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
        for owner, field, value in changes:
            setattr(owner, field, value)

        collection = bpy.data.collections.new('Setup')
        scene.collection.children.link(collection)
        context.view_layer.update()
        context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collection.name]
        objects = create_setup_objects(context)
        scene.world = create_sky_world()
        # 中心约束脚本会临时在根集合创建灯光；把本次搭建结果统一收进 Setup。
        for obj in set(bpy.data.objects) - before[0]:
            if collection not in obj.users_collection:
                collection.objects.link(obj)
            for owner in list(obj.users_collection):
                if owner != collection:
                    owner.objects.unlink(obj)

        # 解除当前场景的旧入口，也覆盖隐藏/禁选/被排除集合中的对象。
        # 不全局删除数据，其他 Scene 或实例仍然可以引用原对象/集合。
        for child in old_children:
            scene.collection.children.unlink(child)
        for obj in old_root_objects:
            scene.collection.objects.unlink(obj)
        return objects
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
        raise
    finally:
        if scene.render.engine != old_engine:
            scene.render.engine = old_engine


class VIEW3D_OT_setup_workspace_visn(bpy.types.Operator):
    bl_idname = 'view3d.setup_workspace_visn'
    bl_label = '一键 setup 工作区'
    bl_description = ('清空当前场景并设置双引擎、ACES、输出与天空，创建 Box、C-P 相机、'
                      '对焦对象、Sun 和 Rigify Human；保持当前渲染器，场景改动可撤销')
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
                setup_workspace(context)
        except Exception as error:
            self.report({'ERROR'}, f'setup 未完成：{error}')
            return {'CANCELLED'}
        context.area.tag_redraw()
        self.report({'INFO'}, '工作区 setup 完成：双引擎、天空、相机组、Sun 与 Human 已就绪')
        return {'FINISHED'}


def register():
    bpy.utils.register_class(VIEW3D_OT_setup_workspace_visn)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_setup_workspace_visn)
