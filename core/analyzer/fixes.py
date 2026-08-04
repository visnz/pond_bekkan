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
    """把当前 View Layer 中的对象设为激活并选中。"""
    bpy.ops.object.select_all(action='DESELECT')
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
    """为当前 Scene 的 Cycles 设置 texture_limit（视口贴图尺寸上限）。

    EEVEE 没有对应的 per-scene 贴图钳制，此修复在 EEVEE 下会失败并提示用户。
    max_size 支持 128/256/512/1024/2048/4096/8192 等 2 的幂；
    对应 CyclesRenderSettings.texture_limit 的枚举标识符 '128'、'256' …… '8192' 以及 'OFF'。
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
        # 渲染限制保持用户自行决定；这里只修复视口限制
        return 1, 0, {"texture_limit": limit_id}
    except Exception:
        return 0, 1, {"reason": f"无法设置 cycles.texture_limit={limit_id}"}


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

    对 Finding.obj_names 里的对象，按 material_slots 的材质 frozenset 重新分组
    （不依赖 check 运行时的内部状态），每组把除保留对象外的对象 join 到保留对象。
    多用户网格保护：users>1 的网格先 make single（复制数据），避免 join 污染共享数据。
    只操作当前 View Layer 可访问的对象，跨 scene / 不可见的对象静默跳过。
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
