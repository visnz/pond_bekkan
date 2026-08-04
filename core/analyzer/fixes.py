"""工程分析：快速修复动作的实现

每个 fix_* 函数接收 (context, finding_item)，返回 (fixed_count, skipped_count, info_dict)。
skipped 通常表示对象/数据不存在，或不在当前 View Layer 无法执行需要上下文的 bpy.ops。
所有会修改数据的 operator 都只操作当前 View Layer 内可访问的对象，跨 scene 数据仅静默跳过。
（合并自 Bekkan/STOOL_part/Analyzer/fixes.py，纯平移）
"""
import bpy  # type: ignore

from . import checks


def _view_layer_objects(context):
    """当前 View Layer 的对象名集合（用于判断对象是否可操作）。"""
    return {o.name for o in context.view_layer.objects}


def _object_names(item):
    """从 finding_item.obj_names 解析名称列表。"""
    return [n for n in item.obj_names.split("\n") if n]


def _set_active_object(context, obj):
    """把当前 View Layer 中的对象设为激活并选中。

    直接对 view_layer.objects 置 select=False，不调用
    bpy.ops.object.select_all——该 operator 的 poll 依赖 3D 视口上下文，
    在不确定调用来源（面板按钮/调试器暂停恢复等）时可能报
    "context is incorrect" 直接抛异常，绕开 operator 层更稳妥。
    """
    for o in context.view_layer.objects:
        o.select_set(False)
    context.view_layer.objects.active = obj
    obj.select_set(True)


def fix_negative_scale(context, item):
    """对负缩放对象应用缩放（保留位置/旋转）。

    若对象网格是多用户共享（users>1），transform_apply 会报错；
    这里先为当前对象复制一份独立数据，再继续应用。
    """
    names = _object_names(item)
    vl_names = _view_layer_objects(context)
    fixed = skipped = made_single = 0
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            skipped += 1
            continue
        if obj.name not in vl_names:
            skipped += 1
            continue

        # 多用户网格需要复制成单用户才能 apply
        data = getattr(obj, 'data', None)
        if data is not None and getattr(data, 'users', 1) > 1:
            try:
                obj.data = data.copy()
                made_single += 1
            except Exception:
                skipped += 1
                continue

        _set_active_object(context, obj)
        try:
            bpy.ops.object.transform_apply(scale=True, location=False, rotation=False)
            fixed += 1
        except Exception:
            skipped += 1
    return fixed, skipped, {"made_single": made_single}


def fix_clamp_textures(context, item, max_size):
    """为当前 Scene 的 Cycles 同时设置 texture_limit（视口）与 texture_limit_render（渲染）。

    EEVEE 没有对应的 per-scene 贴图钳制，此修复在 EEVEE 下会失败并提示用户。
    max_size 支持 128/256/512/1024/2048/4096/8192 等 2 的幂；
    对应 CyclesRenderSettings.texture_limit 的枚举标识符 '128'、'256' …… '8192' 以及 'OFF'。

    关键坑：texture_limit 只是「简化」面板里的一项，只有总开关
    scene.render.use_simplify 打开时才会真正生效——之前只设置了 texture_limit
    没开总开关，用户看不到任何效果。同时用户反馈只钳制视口不够，渲染结果也要一起限制，
    所以这里把 texture_limit_render 也一并设置。
    """
    engine = checks._engine(context)
    if engine != 'CYCLES':
        return 0, 1, {"reason": "EEVEE 没有 scene.cycles.texture_limit，无法自动钳制"}

    limit_id = str(max_size) if max_size else 'OFF'
    cycles = context.scene.cycles
    if not hasattr(cycles, 'texture_limit'):
        return 0, 1, {"reason": "当前 Blender 版本没有 cycles.texture_limit"}

    try:
        cycles.texture_limit = limit_id
        if hasattr(cycles, 'texture_limit_render'):
            cycles.texture_limit_render = limit_id
        context.scene.render.use_simplify = True
        return 1, 0, {"texture_limit": limit_id}
    except Exception:
        return 0, 1, {"reason": f"无法设置 cycles.texture_limit={limit_id}"}


def fix_normal_map_colorspace(context, item):
    """把接在「法线贴图」节点上、色彩空间不对的贴图统一改成 Non-Color。

    算法与 core/synccheck.py 的 POND_OT_normal_fix 一致（应用户要求复用蛙灾侧
    已验证的修复逻辑），改成自包含实现的原因见 checks.check_normal_map_colorspace
    的说明——独立版打包不带 core/synccheck.py，不能跨模块 import。
    """
    fixed = 0
    seen = set()
    for mat in bpy.data.materials:
        if not mat or not mat.use_nodes or mat.library or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type != 'NORMAL_MAP':
                continue
            color_input = node.inputs.get('Color')
            if color_input is None:
                continue
            for link in color_input.links:
                src = link.from_node
                if src.type != 'TEX_IMAGE' or not src.image:
                    continue
                img = src.image
                if img.name in seen or img.colorspace_settings.name == 'Non-Color':
                    continue
                seen.add(img.name)
                try:
                    img.colorspace_settings.name = 'Non-Color'
                    fixed += 1
                except Exception:
                    pass
    return fixed, 0, {}


def fix_cap_subdivision(context, item, max_level):
    """把「简化」面板的细分级数上限（视口 simplify_subdivision + 渲染
    simplify_subdivision_render）都设为 max_level，并开启总开关 use_simplify。

    只设置运行时上限，不修改各修改器自身的 levels/render_levels 数值；
    与 fix_clamp_textures 是同一种「Simplify 总开关钳制」思路。
    """
    render = context.scene.render
    if not hasattr(render, 'simplify_subdivision') or not hasattr(render, 'simplify_subdivision_render'):
        return 0, 1, {"reason": "当前 Blender 版本没有 render.simplify_subdivision"}
    try:
        render.simplify_subdivision = max_level
        render.simplify_subdivision_render = max_level
        render.use_simplify = True
        return 1, 0, {"simplify_subdivision": max_level}
    except Exception:
        return 0, 1, {"reason": f"无法设置 render.simplify_subdivision={max_level}"}


def fix_viewport_to_render_visible(context, item):
    """把「视图可见但渲染不可见」的对象全部改为渲染可见。"""
    names = _object_names(item)
    vl_names = _view_layer_objects(context)
    fixed = skipped = 0
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.name not in vl_names:
            skipped += 1
            continue
        if obj.hide_render:
            obj.hide_render = False
            fixed += 1
    return fixed, skipped, {}


def fix_viewport_to_hidden(context, item):
    """把「视图可见但渲染不可见」的对象全部改为视图不可见。"""
    names = _object_names(item)
    vl_names = _view_layer_objects(context)
    fixed = skipped = 0
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.name not in vl_names:
            skipped += 1
            continue
        if not obj.hide_viewport:
            obj.hide_viewport = True
            fixed += 1
    return fixed, skipped, {}


def fix_purge_unused(context, item):
    """调用 Blender 的 orphans_purge 一键清理未使用数据块。

    该操作是全局的，会清理材质、贴图、Action、网格等所有无引用数据；
    不同 Blender 版本的参数名略有差异，这里做兼容性调用。
    """
    try:
        # 4.x/5.x 通用参数
        bpy.ops.outliner.orphans_purge(
            do_local_ids=True,
            do_linked_ids=False,
            do_recursive=True,
        )
        return 1, 0, {}
    except TypeError:
        # 某些版本参数名不同，回退到最简调用
        try:
            bpy.ops.outliner.orphans_purge()
            return 1, 0, {}
        except Exception:
            return 0, 1, {}
    except Exception:
        return 0, 1, {}


def fix_duplicate_materials(context, item):
    """把节点树相同的重复材质合并为每组第一个材质。

    所有引用重复材质的对象都会被改为引用保留材质，随后删除重复材质。
    """
    groups = checks.collect_duplicate_material_groups()
    if not groups:
        return 0, 0, {}

    fixed = skipped = 0
    for ms in groups:
        keep = ms[0]
        dups = ms[1:]
        for dup in dups:
            try:
                # 替换所有对象对该材质的引用
                for obj in bpy.data.objects:
                    for slot in obj.material_slots:
                        if slot.material == dup:
                            slot.material = keep
                # 删除重复材质
                bpy.data.materials.remove(dup)
                fixed += 1
            except Exception:
                skipped += 1
    return fixed, skipped, {"kept_groups": len(groups)}


def fix_merge_same_material(context, item):
    """把同材质对象组用 Ctrl+J 合并为每组第一个对象。

    修复时从当前数据重新分组（点击时场景可能已变，不依赖 check 运行时的内部状态），
    会把当前 View Layer 内**所有**同材质（≥min_count）的对象组各自合并，不只是
    Finding.obj_names 指向的最大一组——obj_names 仅用于列表定位，不是合并白名单。
    只操作当前 View Layer 可访问的对象，跨 scene / 不可见的对象静默跳过。
    多用户网格保护：users>1 的网格先 make single（复制数据），避免 join 污染共享数据。
    返回 (fixed, skipped, info)。
    """
    groups = checks.collect_merge_same_material_groups()
    if not groups:
        return 0, 0, {}

    vl_names = _view_layer_objects(context)
    fixed = skipped = made_single = 0

    for objs in groups:
        # 只处理这一组里在当前 View Layer 的对象
        in_vl = [o for o in objs if o.name in vl_names]
        if len(in_vl) < 2:
            skipped += len(in_vl)
            continue
        keep = in_vl[0]
        rest = in_vl[1:]

        # 多用户网格先单用户化（join 会要求对象网格数据不共享）
        for o in in_vl:
            data = getattr(o, 'data', None)
            if data is not None and getattr(data, 'users', 1) > 1:
                try:
                    o.data = data.copy()
                    made_single += 1
                except Exception:
                    skipped += 1

        try:
            bpy.ops.object.select_all(action='DESELECT')
            for o in in_vl:
                o.select_set(True)
            context.view_layer.objects.active = keep
            bpy.ops.object.join()
            fixed += len(rest)
        except Exception:
            skipped += len(rest)
    return fixed, skipped, {"made_single": made_single, "groups": len(groups)}


def fix_identical_duplicates(context, item):
    """把几何相同的重复网格改为关联复制（共享 keep mesh 的数据块）。

    重新用 collect_identical_duplicate_groups() 分组（运行后场景可能已变），
    每组 keep=第一个 mesh，把引用其余 mesh 的对象改为 obj.data = keep_mesh。
    带形态键的 mesh 已被 collect 跳过；fix 独立再验一遍 mesh.shape_keys 保底。
    只操作当前 View Layer 可访问的对象。旧 mesh 若 users 归 0 不会自动删，
    报告在 info 里提示留待 Purge。返回 (fixed, skipped, info)。
    """
    groups = checks.collect_identical_duplicate_groups()
    if not groups:
        return 0, 0, {}

    vl_names = _view_layer_objects(context)
    fixed = skipped = 0
    orphan_meshes = 0

    for ms in groups:
        keep = ms[0]
        dups = ms[1:]
        for dup in dups:
            # 形态键保底：collect 已跳，但运行后状态可能变，再验一遍
            if getattr(dup, 'shape_keys', None) is not None:
                skipped += 1
                continue
            # 把引用 dup 的、在当前 View Layer 的对象改为引用 keep
            for o in bpy.data.objects:
                if o.type != 'MESH' or o.data is not dup:
                    continue
                if o.name not in vl_names:
                    skipped += 1
                    continue
                try:
                    o.data = keep
                    fixed += 1
                except Exception:
                    skipped += 1
            # dup 若已无引用，记一笔留待 Purge（不在此删，避免与 purge_unused 重复）
            if getattr(dup, 'users', 1) == 0:
                orphan_meshes += 1
    return fixed, skipped, {"orphan_meshes": orphan_meshes, "groups": len(groups)}


def fix_empty_objects(context, item):
    """删除无内容的空物体，复用「搭建类 → 删除无内容的Empty」现有 op（不重新实现保护逻辑）。

    该 op 作用于 bpy.data.objects 全局，不区分 View Layer；用调用前后的
    EMPTY 对象总数差值作为 fixed 计数。
    """
    before = sum(1 for o in bpy.data.objects if o.type == 'EMPTY')
    try:
        bpy.ops.object.delete_empty_null_visn()
    except Exception:
        return 0, 1, {}
    after = sum(1 for o in bpy.data.objects if o.type == 'EMPTY')
    return max(before - after, 0), 0, {}


def fix_link_orphans(context, item):
    """把不属于任何集合的对象移入一个专用集合，非破坏性（不删除数据）。

    这些对象本身没有 users_collection，因此天然不在任何 View Layer 里，
    不适用其它 fix「只操作当前 View Layer 可访问对象」的惯例；这里改为直接
    核对 users_collection 是否仍为空来判断是否需要处理。
    """
    names = _object_names(item)
    scene = context.scene
    holder = bpy.data.collections.get("_未分类孤立对象")
    if holder is None:
        holder = bpy.data.collections.new("_未分类孤立对象")
    if holder.name not in scene.collection.children:
        scene.collection.children.link(holder)

    fixed = skipped = 0
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.users_collection:
            skipped += 1
            continue
        try:
            holder.objects.link(obj)
            fixed += 1
        except Exception:
            skipped += 1
    return fixed, skipped, {}


def fix_enable_persistent_data(context, item):
    """check_persistent_data 现在只在「未开启」方向触发，这里直接开启即可。"""
    render = context.scene.render
    if getattr(render, 'use_persistent_data', False):
        return 0, 1, {}
    render.use_persistent_data = True
    return 1, 0, {"use_persistent_data": True}


def fix_disable_motion_blur(context, item):
    """关闭运动模糊（该检查只在已开启时触发）。"""
    render = context.scene.render
    if not getattr(render, 'use_motion_blur', False):
        return 0, 1, {}
    render.use_motion_blur = False
    return 1, 0, {}


def fix_shadow_pool(context, item):
    """把 EEVEE 阴影池钳制到 2048（枚举字符串，跨版本防御同 check_eevee_shadows）。"""
    eevee = getattr(context.scene, 'eevee', None)
    if eevee is None or not hasattr(eevee, 'shadow_pool_size'):
        return 0, 1, {"reason": "当前 Blender 版本没有 eevee.shadow_pool_size"}
    try:
        eevee.shadow_pool_size = '2048'
        return 1, 0, {}
    except Exception:
        return 0, 1, {"reason": "无法设置 eevee.shadow_pool_size"}


def fix_device_gpu(context, item):
    """把 Cycles 渲染设备切到 GPU（check 触发时已确认存在可用 GPU）。

    只设置 scene.cycles.device='GPU' 是不够的——如果 Preferences 里的
    compute_device_type 还是 'NONE'（用户从没手动开过 GPU 计算），Cycles 会
    静默退回 CPU 渲染，界面上却已经显示"GPU"，看起来修复生效但实际没用上显卡。
    这里同时把 compute_device_type 切到 check_device 探测到的后端，并把该
    后端下的设备逐个开启（devices[i].use=True），跟手动在 Preferences 里勾选一致。
    """
    if checks._engine(context) != 'CYCLES':
        return 0, 1, {"reason": "当前场景不是 Cycles"}
    cyc = getattr(context.scene, 'cycles', None)
    if cyc is None or not hasattr(cyc, 'device'):
        return 0, 1, {"reason": "当前 Blender 版本没有 scene 级 cycles.device"}
    backend, _names = checks._detect_gpu_backend()
    try:
        prefs = bpy.context.preferences.addons.get('cycles')
        if backend and prefs:
            p = prefs.preferences
            p.compute_device_type = backend
            for d in p.get_devices_for_type(backend):
                if getattr(d, 'type', '') == backend:
                    d.use = True
        cyc.device = 'GPU'
        return 1, 0, {"backend": backend}
    except Exception:
        return 0, 1, {"reason": "无法设置 cycles.device / compute_device_type"}


def fix_cap_bounces(context, item):
    """把反弹/光追/焦散相关参数钳制到 check_bounces 建议的安全上限。"""
    engine = checks._engine(context)
    fixed = 0
    if engine == 'CYCLES':
        cyc = getattr(context.scene, 'cycles', None)
        if cyc is None:
            return 0, 1, {}
        caps = (('max_bounces', 6), ('diffuse_bounces', 4), ('glossy_bounces', 4),
                ('transmission_bounces', 4), ('volume_bounces', 2))
        for name, cap in caps:
            v = checks._as_int(getattr(cyc, name, None))
            if v is not None and v > cap:
                try:
                    setattr(cyc, name, cap)
                    fixed += 1
                except Exception:
                    pass
        for name in ('caustics_reflective', 'caustics_refractive'):
            if getattr(cyc, name, False):
                try:
                    setattr(cyc, name, False)
                    fixed += 1
                except Exception:
                    pass
    elif engine == 'EEVEE':
        eevee = getattr(context.scene, 'eevee', None)
        rto = getattr(eevee, 'ray_tracing_options', None) if eevee else None
        rs = checks._as_int(getattr(rto, 'resolution_scale', None)) if rto else None
        if rs is not None and rs > 2:
            try:
                rto.resolution_scale = 2
                fixed += 1
            except Exception:
                pass
    else:
        return 0, 1, {"reason": "未识别的渲染引擎"}
    return fixed, 0, {}


def fix_output_compression(context, item):
    """按 check_output_format 的压缩建议调整 PNG/EXR 编码（不改动输出格式本身）。"""
    im = context.scene.render.image_settings
    fmt = getattr(im, 'file_format', '')
    if fmt == 'PNG' and getattr(im, 'compression', None) == 0:
        im.compression = 15
        return 1, 0, {}
    if fmt == 'OPEN_EXR':
        codec_attr = 'exr_codec' if hasattr(im, 'exr_codec') else (
            'codec' if hasattr(im, 'codec') else None)
        if codec_attr and getattr(im, codec_attr) == 'NONE':
            setattr(im, codec_attr, 'ZIP')
            return 1, 0, {}
    return 0, 1, {"reason": "已是压缩状态，或涉及合成/序列器切换输出格式的结构性决定，需手动处理"}


def fix_adaptive_sampling(context, item):
    """仅 Cycles：开启自适应采样，视口阈值调到 0.1、渲染阈值调到 0.03
    （EEVEE 采样数需按画面手动权衡）。"""
    if checks._engine(context) != 'CYCLES':
        return 0, 1, {"reason": "EEVEE 采样数需按画面手动权衡，暂不自动修复"}
    cyc = getattr(context.scene, 'cycles', None)
    if cyc is None:
        return 0, 1, {}
    fixed = 0
    if not getattr(cyc, 'use_adaptive_sampling', True):
        cyc.use_adaptive_sampling = True
        fixed += 1
    render_th = getattr(cyc, 'adaptive_threshold', None)
    if render_th is not None and render_th < 0.02:
        cyc.adaptive_threshold = 0.03
        fixed += 1
    if hasattr(cyc, 'preview_adaptive_threshold'):
        preview_th = getattr(cyc, 'preview_adaptive_threshold', None)
        if preview_th is not None and preview_th < 0.05:
            cyc.preview_adaptive_threshold = 0.1
            fixed += 1
    return fixed, 0, {}


def fix_light_perf_toggles(context, item):
    """仅 Cycles：开启 Light Tree 与阴影剔除（EEVEE 无对应属性，返回提示）。"""
    if checks._engine(context) != 'CYCLES':
        return 0, 1, {"reason": "该优化仅适用于 Cycles"}
    cyc = getattr(context.scene, 'cycles', None)
    if cyc is None:
        return 0, 1, {}
    fixed = 0
    for name in ('use_light_tree', 'use_shadow_culling'):
        if hasattr(cyc, name) and not getattr(cyc, name):
            setattr(cyc, name, True)
            fixed += 1
    return fixed, 0, {}
