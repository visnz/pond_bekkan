"""工程分析：简单检查（批 1）+ 深度检查（批 2）的实现

每个检查函数返回一条 Finding 或 None（不适用/未发现问题）。
版本口径：合并后锁定 Blender 5.2，只关注 EEVEE 与 Cycles；
跨版本属性一律用 getattr/hasattr 防御（沿用 _copy_rna_props 的思路）。
深度检查（几何/合并/缩放统计）涉及重计算，运行较慢，仅在「深度检查」模式下执行。
（合并自 Bekkan/STOOL_part/Analyzer/checks.py，纯平移）
"""
import bpy  # type: ignore
from collections import Counter
from mathutils import Vector  # type: ignore

from .model import (Finding, sort_results,
                    IMPACT_HIGH, IMPACT_MED, IMPACT_LOW,
                    EASE_ONE, EASE_HALF, EASE_HARD,
                    CATEGORY_STRUCTURE, CATEGORY_TRANSFORM, CATEGORY_RENDER,
                    CATEGORY_EEVEE, CATEGORY_MATERIAL, CATEGORY_DATA,
                    CATEGORY_VISIBILITY, CATEGORY_OTHER)


# ============================================================
# 调试日志
# ============================================================

def _log(msg):
    print(f"[Analyzer] {msg}")


def _as_int(v):
    """把可能是字符串/枚举的数值属性安全转成 int；失败返回 None。"""
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ============================================================
# 简单检查入口
# ============================================================

def run_quick(context):
    _log(f"开始简单检查，当前引擎={_engine(context)!r}")
    results = []
    for fn in _QUICK_CHECKS:
        try:
            f = fn(context)
        except Exception as e:  # 单个检查失败不中断整体扫描
            _log(f"检查 {fn.__name__} 异常：{e}")
            f = Finding(
                "ERR." + fn.__name__, f"检查失败：{fn.__name__}",
                0, IMPACT_LOW, EASE_HARD, str(e),
                "请把此信息反馈给插件作者", CATEGORY_OTHER,
            )
        if f:
            _log(f"  -> {f.key}: {f.title} ({f.impact}/{f.ease})")
            results.append(f)
    _log(f"简单检查完成，共 {len(results)} 条建议")
    return sort_results(results)


def _objects():
    return [o for o in bpy.data.objects if o is not None]


def _scene_objects(context):
    """当前场景实际链接的对象（跨 Scene 隔离；不同于全文件扫描的 _objects()）。"""
    return [o for o in context.scene.objects if o is not None]


def _materials():
    return [m for m in bpy.data.materials if m is not None]


def _cap_names(names, limit=1000):
    """对象名列表限长：大量同名对象时只保留前 limit 个，避免 UI/选中开销过大"""
    return list(names[:limit])


def _is_real_image(img):
    """排除 Viewer Node / Render Result 等内部中间件，只把真正的贴图纳入统计。"""
    if img is None:
        return False
    if getattr(img, "source", "") == "VIEWER":
        return False
    if getattr(img, "type", "") in {"RENDER_RESULT", "COMPOSITING"}:
        return False
    if getattr(img, "name", "").startswith("Render Result"):
        return False
    return True


def _engine(context):
    """当前渲染引擎分类：'CYCLES' / 'EEVEE' / ''（其它，如 Workbench）。

    引擎标识符跨版本：Cycles 一直为 'CYCLES'；EEVEE 在 4.x 有
    'BLENDER_EEVEE_NEXT'，5.x 回归 'BLENDER_EEVEE'。用子串判断兜底。
    注意 scene.cycles / scene.eevee 是常驻 PointerProperty，永不为 None，
    判断引擎必须看 scene.render.engine，不能看这两个属性是否存在。
    """
    engine = (getattr(context.scene.render, 'engine', None) or '')
    e = engine.upper()
    if e.endswith('CYCLES'):
        return 'CYCLES'
    if 'EEVEE' in e:
        return 'EEVEE'
    return ''


# ============================================================
# A. 场景结构
# ============================================================

def _collection_object_total(coll, _depth=0):
    """集合 + 全部子集合的对象总数（递归）。同一集合被多个父集合链接时两处都算数
    （真实渲染负载如此），只加深度上限防御异常数据，不做去重。"""
    total = len(coll.objects)
    if _depth > 50:
        return total
    for child in coll.children:
        total += _collection_object_total(child, _depth + 1)
    return total


def _layer_collection_object_total(layer_coll, _depth=0):
    """按 View Layer 排除状态递归统计对象总数：exclude 的分支（及其全部子集合）
    完全不计入——被排除的集合不参与该 View Layer 的求值，谈不上拖慢视口/渲染。"""
    if layer_coll.exclude:
        return 0
    total = len(layer_coll.collection.objects)
    if _depth > 50:
        return total
    for child in layer_coll.children:
        total += _layer_collection_object_total(child, _depth + 1)
    return total


def _dense_collection_rows(context):
    """当前 View Layer 里对象数 >=200 的集合，按 total 降序；同时返回最大嵌套深度。

    沿 view_layer.layer_collection 树遍历（不是 scene.collection 数据树），排除
    （exclude from view layer）的集合及其子树直接跳过，不计数、不列出。
    """
    rows = []  # (collection, depth, total, direct)
    max_depth = 0

    def _walk(layer_coll, depth):
        nonlocal max_depth
        if layer_coll.exclude:
            return
        max_depth = max(max_depth, depth)
        if depth > 0:
            coll = layer_coll.collection
            rows.append((coll, depth, _layer_collection_object_total(layer_coll), len(coll.objects)))
        if depth > 50:
            return
        for child in layer_coll.children:
            _walk(child, depth + 1)

    _walk(context.view_layer.layer_collection, 0)
    flagged = sorted((r for r in rows if r[2] >= 200), key=lambda r: r[2], reverse=True)
    return flagged, max_depth


def _instance_stats(context):
    """遍历当前 evaluated depsgraph，统计「真实对象数」与「含实例对象数」两个口径。

    返回 (real, inst, per_source, total_eval)：
      real        非实例条目数（当前场景真实对象，不含虚拟实例）
      inst        实例条目数（几何节点/集合实例生成的虚拟实例）
      per_source  按 inst.parent.original.name 归堆的实例数（定位"元凶"）
      total_eval  real + inst ≈ Blender 视口统计的 Objects 数

    几何节点/集合实例生成的对象在 depsgraph 里是虚拟实例，不在 bpy.data.objects、
    也不在 scene.objects 里——只数真实对象会严重低估实际渲染/导出负载。
    遍历成本 O(实例数)，交互场景下 depsgraph 通常已求值，直接复用不重算。
    """
    try:
        depsgraph = context.evaluated_depsgraph_get()
    except Exception:
        return 0, 0, Counter(), 0
    real = inst = 0
    per_source = Counter()
    for it in depsgraph.object_instances:
        if not getattr(it, 'is_instance', False):
            real += 1
            continue
        inst += 1
        parent = getattr(it, 'parent', None)
        if parent is None:
            continue
        original = getattr(parent, 'original', parent)
        name = getattr(original, 'name', None)
        if name:
            per_source[name] += 1
    return real, inst, per_source, real + inst


def check_object_count(context):
    """场景对象数量过多：总数 + 哪些集合堆得多 + 实例放大，合成一条 Finding。

    两个统计口径都报：
      · 口径一（真实对象）：len(bpy.data.objects)，原有口径
      · 口径二（含实例，同 Blender 视口统计）：evaluated depsgraph 总条目数，
        几何节点/集合实例生成的虚拟实例也计入
    几何节点产生巨量虚拟实例时（如 1 个物体炸出上万实例），口径一远低于真实负载，
    本条会在 detail 里点名实例来源，建议「实例化到点上 + 烘焙」。
    """
    n = len(_objects())
    rows, max_depth = _dense_collection_rows(context)
    _, n_inst, per_source, total_eval = _instance_stats(context)
    amplified = n_inst >= 1000
    if n < 3000 and not rows and not amplified:
        return None

    impact = IMPACT_HIGH if n > 8000 or total_eval > 20000 else IMPACT_MED
    lines = []
    if n >= 3000 or amplified:
        lines.append(f"当前真实对象共 {n} 个。对象过多会拖慢视口、增大文件体积并加重渲染调度。")

    coll_names = []
    if rows:
        for coll, depth, total, direct in rows:
            mark = "⚠ " if total >= 500 else ""
            lines.append(f"📦{mark}「{coll.name}」：{total} 个对象（直属 {direct}，层级深度 {depth}）")
            coll_names.append(coll.name)
        if max_depth > 6:
            lines.append(f"集合嵌套最深达到 {max_depth} 层，过深会拖慢大纲视图操作。")
        if any(total >= 500 for _c, _d, total, _n in rows):
            impact = IMPACT_HIGH

    if amplified:
        lines.append(
            f"按 Blender 统计口径（含实例）共约 {total_eval} 个对象，"
            f"其中虚拟实例约 {n_inst} 个，来自："
        )
        for name, c in per_source.most_common(5):
            lines.append(f"  「{name}」：约 {c} 个")

    other_scene = len(_objects()) - len(_scene_objects(context))
    if other_scene > 200:
        lines.append(
            f"检测到其他 Scene 中还有约 {other_scene} 个未计入本次统计的物体，"
            "如需了解请切换 Scene 后重新运行分析。"
        )

    suggestion = ("建议：用集合实例化重复物件；同材质小件（如水晶吊坠数百个）合并为一个；"
                  "清理无用的辅助对象。")
    if rows:
        suggestion += ("按用途拆分过大的子集合；重复摆放的物件用集合实例代替；"
                        "超大集合可考虑单独整理后打包送烘焙。")
    if amplified:
        suggestion += (f"几何节点产生了约 {n_inst} 个虚拟实例，渲染/导出时会被逐一求值。"
                       "分布类需求尽量用「实例化到点上」而非「实现实例」直接生成网格；"
                       "结果已固定则用「烘焙」缓存几何节点，避免每帧重算。")

    return Finding(
        "STRUCT.object_count", "场景对象数量过多",
        total_eval if amplified else n, impact, EASE_HARD,
        "\n".join(lines),
        suggestion,
        CATEGORY_STRUCTURE, _cap_names(coll_names) if coll_names else None,
    )


def check_collection_instance_multiplier(context):
    refs = Counter()
    empties_by_coll = {}
    for o in _scene_objects(context):
        if o.type != 'EMPTY' or getattr(o, 'instance_type', None) != 'COLLECTION':
            continue
        coll = getattr(o, 'instance_collection', None)
        if coll is None:
            continue
        refs[coll.name] += 1
        empties_by_coll.setdefault(coll.name, []).append(o.name)

    if not refs:
        return None

    flagged = []
    for name, n in refs.items():
        coll = bpy.data.collections.get(name)
        if coll is None:
            continue
        m = _collection_object_total(coll)
        load = n * m
        if load >= 2000:
            flagged.append((name, n, m, load))
    if not flagged:
        return None
    flagged.sort(key=lambda r: r[3], reverse=True)

    lines = [
        f"集合「{name}」被 {n} 个实例引用，该集合含 {m} 个对象，实际渲染负载 ≈ {n}×{m} = {load}"
        for name, n, m, load in flagged
    ]
    obj_names = []
    for name, *_r in flagged:
        obj_names.extend(empties_by_coll.get(name, []))

    impact = IMPACT_HIGH if any(load >= 10000 for _n, _c, _m, load in flagged) else IMPACT_MED
    return Finding(
        "STRUCT.collection_instance_multiplier", "集合实例引用叠加负载过高", len(flagged),
        impact, EASE_HARD,
        "\n".join(lines),
        "建议：确认是否所有实例都需要同样精度；数量多但远景可见的可换成低模 LOD 集合。",
        CATEGORY_STRUCTURE, _cap_names(obj_names),
    )


def check_particle_heavy(context):
    flagged = []  # (obj_name, est, amplified)
    for o in _scene_objects(context):
        systems = getattr(o, 'particle_systems', None)
        if not systems:
            continue
        est_total = 0
        amplified = False
        for ps in systems:
            settings = getattr(ps, 'settings', None)
            if settings is None:
                continue
            base = _as_int(getattr(settings, 'count', 0)) or 0
            child_mult = 1
            if getattr(settings, 'child_type', 'NONE') != 'NONE':
                for attr in ('rendered_child_count', 'child_nbr'):
                    v = _as_int(getattr(settings, attr, None))
                    if v:
                        child_mult = v
                        break
            est_total += base * child_mult
            if getattr(settings, 'render_type', 'NONE') in {'OBJECT', 'COLLECTION'}:
                amplified = True
        if est_total >= 1000:
            flagged.append((o.name, est_total, amplified))

    if not flagged:
        return None
    flagged.sort(key=lambda r: r[1], reverse=True)

    lines = []
    for name, est, amplified in flagged:
        line = f"{name}：约 {est} 根/粒子"
        if amplified:
            line += "（渲染为 Object/Collection，实际几何负载会按渲染对象复杂度再放大）"
        lines.append(line)

    impact = IMPACT_HIGH if any(est >= 10000 for _n, est, _a in flagged) else IMPACT_MED
    return Finding(
        "STRUCT.particle_heavy", "毛发/粒子数量过多", len(flagged),
        impact, EASE_HARD,
        "\n".join(lines),
        "建议：确认密度是否必要；可降低 Child 数量、开启视口精简显示比例，"
        "或结果固定后转换为静态网格。",
        CATEGORY_STRUCTURE, _cap_names([n for n, *_r in flagged]),
    )


def check_geonode_instances(context):
    _, _inst, per_source, total_eval = _instance_stats(context)
    if not per_source:
        return None

    flagged = sorted(
        ((name, n) for name, n in per_source.items() if n >= 200),
        key=lambda r: r[1], reverse=True,
    )

    lines = [f"{name}：几何节点/实例生成约 {n} 个虚拟实例" for name, n in flagged]

    scene_n = len(_scene_objects(context))
    if scene_n > 0 and total_eval > scene_n * 3 and (total_eval - scene_n) > 500:
        lines.append(
            f"全场景真实渲染实例总数约 {total_eval}，远高于场景对象数 {scene_n}，"
            "说明存在隐藏的实例化负载。"
        )

    if not lines:
        return None

    impact = IMPACT_HIGH if any(n >= 2000 for _n, n in flagged) else IMPACT_MED
    return Finding(
        "STRUCT.geonode_instances", "几何节点/实例生成了大量虚拟实例", len(flagged),
        impact, EASE_HARD,
        "\n".join(lines),
        "建议：在几何节点里尽量用『实例化到点上』而非『实现实例』直接生成网格几何；"
        "若结果已固定，可用『烘焙』缓存几何节点结果，避免每帧重新计算。",
        CATEGORY_STRUCTURE, _cap_names([name for name, _n in flagged]),
    )


def check_empty_objects(context):
    empties = [o for o in _objects()
               if o.type == 'EMPTY' and not o.children
               and getattr(o, 'instance_type', None) != 'COLLECTION']
    if len(empties) < 20:
        return None
    impact = IMPACT_HIGH if len(empties) > 200 else IMPACT_MED
    return Finding(
        "STRUCT.empty_objects", "存在过多无内容的空物体", len(empties),
        impact, EASE_ONE,
        "无下级且无数据的空物体通常是遗留辅助对象，白白增加对象数量。",
        "建议：使用「搭建类 → 删除无内容的Empty」一键清理（会自动保护集合实例）。",
        CATEGORY_STRUCTURE, [o.name for o in empties],
    )


def check_orphan_objects(context):
    bad = [o for o in _objects() if not o.users_collection]
    if not bad:
        return None
    return Finding(
        "STRUCT.orphan_objects", "存在不属于任何集合的对象", len(bad),
        IMPACT_LOW, EASE_ONE,
        "这些对象不显示在任意集合中，也不参与渲染，多为误留数据。",
        "建议：删除，或移入正确的集合。",
        CATEGORY_STRUCTURE, [o.name for o in bad],
    )


# ============================================================
# D. 变换
# ============================================================

def check_negative_scale(context):
    bad = [o for o in _objects() if any(v < 0 for v in o.scale)]
    if not bad:
        return None
    return Finding(
        "TRANS.negative_scale", "存在负缩放的物体", len(bad),
        IMPACT_MED, EASE_HALF,
        "负缩放（镜像未应用）会导致法线翻转、烘焙/导出异常，并影响某些修改器结果。",
        "建议：对相关物体应用缩放（Ctrl+A → 应用缩放），或改用镜像修改器。",
        CATEGORY_TRANSFORM, [o.name for o in bad],
    )


def check_tiny_scale(context):
    bad = [o for o in _objects() if any(abs(v) < 0.1 for v in o.scale)]
    if not bad:
        return None
    return Finding(
        "TRANS.tiny_scale", "存在缩放过小的物体", len(bad),
        IMPACT_MED, EASE_HALF,
        "缩放小于 0.1（含 0）通常来自单位混用或未应用缩放，会带来数值精度问题。",
        "建议：检查单位设置（米/厘米），必要时应用缩放归一。注意小尺寸物体可能是正常的，"
        "仅作怀疑提醒。",
        CATEGORY_TRANSFORM, [o.name for o in bad],
    )


def check_big_scale(context):
    bad = [o for o in _objects() if any(abs(v) > 10.0 for v in o.scale)]
    if not bad:
        return None
    return Finding(
        "TRANS.big_scale", "存在缩放过大的物体", len(bad),
        IMPACT_LOW, EASE_HALF,
        "缩放大于 10 同样提示单位或未应用缩放，会造成数值精度与编辑不便。",
        "建议：检查单位设置并应用缩放归一。",
        CATEGORY_TRANSFORM, [o.name for o in bad],
    )


# ============================================================
# I. 数据块 / 动画
# ============================================================

def check_unused_shapekeys(context):
    objs = []
    for o in _objects():
        if o.type != 'MESH' or not o.data or not o.data.shape_keys:
            continue
        if getattr(o.data.shape_keys, 'animation_data', None) is None:
            objs.append(o)
    if len(objs) < 5:  # 少量不提示，避免噪音
        return None
    return Finding(
        "DATA.unused_shapekeys", "存在未使用动画的形态键", len(objs),
        IMPACT_LOW, EASE_HALF,
        "这些网格带有形态键但没有动画引用，多数是遗留数据，增大文件体积。",
        "建议：确认无用后删除形态键（若被多个网格共享，删除会影响全部引用者）。",
        CATEGORY_DATA, [o.name for o in objs],
    )


def check_unused_actions(context):
    unused = [a.name for a in bpy.data.actions if a and a.users == 0]
    if not unused:
        return None
    n = len(unused)
    names_text = ", ".join(unused[:20]) + ("…" if n > 20 else "")
    return Finding(
        "DATA.unused_actions", "存在未使用的 Action", n,
        IMPACT_LOW, EASE_ONE,
        f"{n} 个 Action 无任何引用，占用文件体积：{names_text}",
        "建议：随孤儿数据一并清理（文件 → 清理 → 未使用的数据）。",
        CATEGORY_DATA, unused,
    )


# ============================================================
# J. 视口 / 可见性
# ============================================================

def check_viewport_only(context):
    context.evaluated_depsgraph_get().update()
    bad = [o for o in _objects() if o.hide_render and o.visible_get()]
    if not bad:
        return None
    return Finding(
        "VIS.viewport_only", "渲染不可见但视图可见的对象", len(bad),
        IMPACT_MED, EASE_HALF,
        "这些对象不出现在渲染图里却仍参与视口绘制与求值，白占视口性能。",
        "建议：若确为辅助物体，同时关闭视口显示，或移入专用集合整体管理。",
        CATEGORY_VISIBILITY, [o.name for o in bad],
    )


# ============================================================
# F. 渲染设置
# ============================================================

def check_light_count(context):
    lights = [o for o in _objects() if o.type == 'LIGHT']
    if len(lights) < 15:
        return None
    scene = context.scene
    eng = _engine(context)
    detail = [f"当前共 {len(lights)} 盏灯光"]
    sug = []
    if eng == 'CYCLES':
        cyc = getattr(scene, 'cycles', None)
        if cyc is not None:
            if getattr(cyc, 'use_light_tree', True) is False:
                detail.append("Light Tree 未开启")
                sug.append("开启 Light Tree，可大幅降低多灯光采样成本")
            if getattr(cyc, 'use_shadow_culling', False) is False:
                detail.append("阴影剔除未开启")
                sug.append("开启阴影剔除，减少无效灯光的阴影计算")
        sug.append("对只影响局部的灯用 Light Linking 限定范围；关掉远处灯光阴影")
    elif eng == 'EEVEE':
        sug.append("对只影响局部的灯用 Light Linking 限定范围")
        sug.append("非主体光源关闭阴影投射（灯光数据的 Shadow 选项），能省不少阴影贴图开销")
        sug.append("阴影质量吃紧的话去检查阴影池大小（本工具的「阴影池过大」检查项）")
    else:
        sug.append("对只影响局部的灯用 Light Linking 限定范围；关掉远处灯光阴影")
    return Finding(
        "RENDER.light_count", "灯光数量过多", len(lights),
        IMPACT_MED, EASE_HALF,
        "；".join(detail),
        "建议：" + "；".join(sug),
        CATEGORY_RENDER,
    )


def check_sampling(context):
    scene = context.scene
    detail, sug = [], []
    impact = None
    eng = _engine(context)
    if eng == 'CYCLES':
        cyc = getattr(scene, 'cycles', None)
        if cyc is None:
            return None
        samples = getattr(cyc, 'samples', None)
        if samples is not None and samples > 2048:
            impact = IMPACT_HIGH
            detail.append(f"采样数高达 {samples}")
            sug.append("配合去噪 + 噪点阈值，通常 128~512 采样就够")
        adaptive = getattr(cyc, 'use_adaptive_sampling', None)
        if adaptive is False:
            impact = impact or IMPACT_MED
            detail.append("自适应采样未开启")
            sug.append("开启自适应采样（Adaptive Sampling）")
        # 视口（预览）与渲染的噪点阈值是两个独立属性，目标区间不同：
        # 视口建议 ~0.1（够快即可），渲染建议 0.02~0.04（保画质）。
        render_th = getattr(cyc, 'adaptive_threshold', None)
        if adaptive and render_th is not None and render_th < 0.02:
            impact = impact or IMPACT_MED
            detail.append(f"渲染噪点阈值过低（{round(render_th, 3)}）")
            sug.append("把渲染噪点阈值提升到 0.02~0.04 左右")
        preview_th = getattr(cyc, 'preview_adaptive_threshold', None)
        if adaptive and preview_th is not None and preview_th < 0.05:
            impact = impact or IMPACT_MED
            detail.append(f"视口噪点阈值过低（{round(preview_th, 3)}）")
            sug.append("把视口（预览）噪点阈值提升到 0.1 左右，视口交互会明显更流畅")
    elif eng == 'EEVEE':
        eevee = getattr(scene, 'eevee', None)
        if eevee is None:
            return None
        # 跨版本采样属性：sample_count（旧版）、render_samples（4.2 Next）、
        # taa_render_samples（5.x 渲染采样）。视口采样 taa_samples 不纳入判断。
        for attr in ('sample_count', 'render_samples', 'taa_render_samples'):
            s = _as_int(getattr(eevee, attr, None))
            if s is not None and s > 64:
                impact = IMPACT_MED
                detail.append(f"EEVEE 采样数偏高（{s}）")
                sug.append("EEVEE 采样通常 16~64 即可，可配合去噪")
                break
    else:
        return None
    if not detail:
        return None
    return Finding(
        "RENDER.sampling", "采样 / 噪点设置可优化", 0,
        impact or IMPACT_MED, EASE_HALF,
        "；".join(detail),
        "建议：" + "；".join(sug),
        CATEGORY_RENDER,
    )


def check_bounces(context):
    scene = context.scene
    detail, sug = [], []
    eng = _engine(context)
    if eng == 'CYCLES':
        cyc = getattr(scene, 'cycles', None)
        if cyc is not None:
            max_b = _as_int(getattr(cyc, 'max_bounces', None))
            if max_b is not None and max_b > 8:
                detail.append(f"最大反弹数 {max_b}")
                sug.append("把 max_bounces 降到 4~6，通常无明显画质损失")
            for name, lim in (('diffuse_bounces', 4), ('glossy_bounces', 4),
                              ('transmission_bounces', 4), ('volume_bounces', 2)):
                v = _as_int(getattr(cyc, name, None))
                if v is not None and v > lim:
                    detail.append(f"{name}={v}")
                    sug.append(f"{name} 建议 ≤{lim}")
            if getattr(cyc, 'caustics_reflective', False) or getattr(cyc, 'caustics_refractive', False):
                detail.append("焦散已开启")
                sug.append("确认是否需要焦散；不需要时关闭可显著加速")
    elif eng == 'EEVEE':
        eevee = getattr(scene, 'eevee', None)
        if eevee is not None and getattr(eevee, 'use_raytracing', False):
            rto = getattr(eevee, 'ray_tracing_options', None)
            rs = _as_int(getattr(rto, 'resolution_scale', None)) if rto else None
            if rs is not None and rs > 2:
                detail.append(f"EEVEE 光追分辨率 {rs}")
                sug.append("EEVEE 光追分辨率建议 ≤2，全分辨率很贵")
    else:
        return None
    if not detail:
        return None
    return Finding(
        "RENDER.bounces", "反弹 / 光追 / 焦散成本偏高", 0,
        IMPACT_MED, EASE_HALF,
        "；".join(detail),
        "建议：" + "；".join(sug),
        CATEGORY_RENDER,
    )


def check_persistent_data(context):
    if _engine(context) != 'CYCLES':
        return None
    scene = context.scene
    if getattr(scene.render, 'use_persistent_data', False):
        return None
    if len(_objects()) > 5000:
        return Finding(
            "RENDER.persistent_data", "未开启保留数据（建议开启）", 0,
            IMPACT_MED, EASE_ONE,
            "当前对象较多且未开启 use_persistent_data，渲染时几何数据可能反复加载。",
            "点击下方按钮一键开启「保留数据」，减少重复渲染时的几何加载耗时"
            "（会占用更多内存，若内存紧张可再关闭）。",
            CATEGORY_RENDER,
        )
    return None


def check_motion_blur(context):
    if not getattr(context.scene.render, 'use_motion_blur', False):
        return None
    return Finding(
        "RENDER.motion_blur", "运动模糊已开启", 0,
        IMPACT_LOW, EASE_ONE,
        "运动模糊会增加渲染时间（尤其 Cycles 需要额外采样）。",
        "仅为简单提醒：非必要可关闭，需要时保留。",
        CATEGORY_RENDER,
    )


def check_output_format(context):
    im = context.scene.render.image_settings
    fmt = getattr(im, 'file_format', '')
    detail, sug = [], []
    comp = getattr(context.scene.render, 'use_compositing', False)
    seq = getattr(context.scene.render, 'use_sequencer', False)
    if fmt == 'PNG':
        c = getattr(im, 'compression', None)
        if c is not None and c == 0:
            detail.append("PNG 未启用压缩")
            sug.append("PNG 压缩设为 15（Blender 默认值，兼顾体积与速度；需要更小文件可 50~90）")
        if comp or seq:
            detail.append("启用合成/序列器但输出 PNG")
            sug.append("需多通道/后期时改用 OpenEXR，保留更多信息")
    elif fmt == 'OPEN_EXR':
        codec = getattr(im, 'exr_codec', '') or getattr(im, 'codec', '')
        if codec == 'NONE':
            detail.append("EXR 未压缩")
            sug.append("EXR 编解码建议 ZIP/PIZ，体积更小几乎无损耗")
    elif comp:
        detail.append(f"输出格式 {fmt} 且启用合成")
        sug.append("若需保留多通道，考虑 OpenEXR")
    if not detail:
        return None
    return Finding(
        "RENDER.output_format", "输出格式 / 压缩可优化", 0,
        IMPACT_MED, EASE_HALF,
        "；".join(detail),
        "建议：" + "；".join(sug),
        CATEGORY_RENDER,
    )


# 按推荐优先级排列的 GPU 计算后端；NVIDIA 显卡上 OptiX 通常比 CUDA 更快（有硬件光追加速）。
_GPU_BACKENDS = ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL')


def _detect_gpu_backend():
    """探测系统里实际可用的 GPU 计算后端，不依赖 Preferences 里当前选中的
    compute_device_type——用户可能从没打开过「Cycles 渲染设备」这个开关
    （此时 compute_device_type 是 'NONE'），但机器上可能确实插着能跑
    OptiX/CUDA 的显卡，旧写法（比对 devices 里 type==当前 compute_device_type）
    在 compute_device_type 为 'NONE' 时永远查不到任何设备，漏检了这种情况。

    用 get_devices_for_type() 主动探测每个后端，不改动当前选中的 compute_device_type。
    返回 (backend, [device_name, ...])；backend 为 None 表示没探测到任何 GPU。
    """
    try:
        prefs = bpy.context.preferences.addons.get('cycles')
        if not prefs:
            return None, []
        p = prefs.preferences
        probe = getattr(p, 'get_devices_for_type', None)
        if probe is None:
            return None, []
        for backend in _GPU_BACKENDS:
            try:
                devices = probe(backend)
            except Exception:
                continue
            names = [d.name for d in devices if getattr(d, 'type', '') == backend]
            if names:
                return backend, names
    except Exception:
        pass
    return None, []


def check_device(context):
    if _engine(context) != 'CYCLES':
        return None
    cyc = getattr(context.scene, 'cycles', None)
    if cyc is None:
        return None
    device = getattr(cyc, 'device', None)
    if device is None:  # 该版本无 scene 级设备属性，跳过
        return None
    if device in ('GPU', 'CPU+GPU'):
        return None
    backend, names = _detect_gpu_backend()
    if not backend:
        return None
    return Finding(
        "RENDER.device", "渲染设备未使用 GPU", 0,
        IMPACT_HIGH, EASE_HALF,
        f"当前 Cycles 设备为 {device}，但检测到可用 GPU（{backend}：{'、'.join(names)}）。",
        f"建议：在 Preferences → System 里把 Cycles 计算后端设为 {backend}"
        "（如果还没开启过 GPU 计算，这里会顺手打开），再把场景的 Cycles 设备设为 GPU。",
        CATEGORY_RENDER,
    )


def check_resolution(context):
    r = context.scene.render
    total = r.resolution_x * r.resolution_y * (r.resolution_percentage / 100.0) ** 2
    if total > 33_000_000:
        impact = IMPACT_HIGH
    elif total > 16_000_000:
        impact = IMPACT_MED
    else:
        return None
    return Finding(
        "RENDER.resolution", "渲染分辨率偏高", 0, impact, EASE_HALF,
        f"当前输出 {r.resolution_x}x{r.resolution_y}（{r.resolution_percentage}%），"
        f"总像素约 {int(total / 1e6)}M。",
        "确认该分辨率是否必要；大图可先在低分辨率预览，最终再全分辨率。",
        CATEGORY_RENDER,
    )


# ============================================================
# G. EEVEE Next 专项
# ============================================================

def check_eevee_shadows(context):
    if _engine(context) != 'EEVEE':
        return None
    eevee = getattr(context.scene, 'eevee', None)
    if eevee is None:
        return None
    if getattr(eevee, 'use_shadows', True) is False:
        return None
    detail, sug = [], []
    pool = getattr(eevee, 'shadow_pool_size', None)
    if pool is not None:
        # 阴影池是枚举，返回字符串（如 '512'），需转成数字再比较
        try:
            pool = int(str(pool))
        except (TypeError, ValueError):
            pool = None
    if pool is not None and pool > 2048:
        detail.append(f"阴影池 {pool} MB")
        sug.append("阴影池按场景实际灯量设置，过高浪费显存")
    if not detail:
        return None
    return Finding(
        "EEVEE.shadows", "EEVEE 阴影设置偏高", 0,
        IMPACT_MED, EASE_ONE,
        "；".join(detail),
        "建议：" + "；".join(sug),
        CATEGORY_EEVEE,
    )


def check_world_volume(context):
    if _engine(context) not in ('CYCLES', 'EEVEE'):
        return None
    world = context.scene.world
    if not world or not world.node_tree:
        return None
    has_vol = False
    for node in world.node_tree.nodes:
        if node.type == 'OUTPUT_WORLD':
            for inp in node.inputs:
                if inp.name == 'Volume' and inp.is_linked:
                    has_vol = True
    if not has_vol:
        return None
    return Finding(
        "EEVEE.world_volume", "世界体积雾已启用（全场景开销）", 0,
        IMPACT_HIGH, EASE_HARD,
        "World 的 Volume 输出会对整个场景做体积求值，渲染与显存开销巨大。",
        "建议：改用局部体积容器（Volume Cube + Principled Volume 材质），"
        "只影响需要的区域；或调低体积采样。",
        CATEGORY_EEVEE,
    )


# ============================================================
# H. 材质 / 贴图
# ============================================================

def _material_hash(mat):
    """把材质节点树归一化为哈希，用于检测内容相同、名称不同的重复材质。
    只取节点的类型/名称/标量枚举属性/连线关系，忽略颜色、位置等装饰属性。
    """
    try:
        nt = mat.node_tree
        parts = []
        nodes = list(nt.nodes)
        if len(nodes) > 400:  # 超大节点树跳过哈希
            return None
        for node in sorted(nodes, key=lambda n: (n.type, n.name)):
            parts.append(node.type)
            parts.append(node.name)
            for prop in node.bl_rna.properties:
                if prop.is_readonly or prop.type not in ('BOOLEAN', 'INT', 'FLOAT', 'ENUM', 'STRING'):
                    continue
                if prop.identifier in {'rna_type', 'bl_idname', 'bl_label', 'name',
                                       'location', 'width', 'height', 'dimensions',
                                       'inputs', 'outputs', 'internal_links',
                                       'use_custom_color', 'color', 'select',
                                       'show_options', 'show_preview', 'show_texture',
                                       'hide', 'mute', 'label', 'parent',
                                       'instance_name', 'socket_value', 'bl_icon',
                                       'identifier', 'description', 'translation_context',
                                       'image_user', 'default_value', 'interpolation',
                                       'node_tree', 'ui_open', 'use_custom_color_prev',
                                       'is_active_output', 'bl_static_type', 'poll'}:
                    continue
                try:
                    v = getattr(node, prop.identifier)
                    if isinstance(v, float):
                        v = round(v, 4)
                    parts.append(f"{prop.identifier}={v!r}")
                except Exception:
                    pass
            for inp in node.inputs:
                if inp.is_linked:
                    for lnk in inp.links:
                        parts.append(f"{node.name}:{inp.name}->{lnk.from_node.type}:{lnk.from_socket.name}")
        return hash(tuple(parts))
    except Exception:
        return None


def collect_duplicate_material_groups(limit=3000):
    """返回 [[keep_mat, dup_mat, ...], ...] 的重复材质分组，供修复使用。

    只包含有 node_tree 的材质；每组按名称排序，第一个作为保留对象。
    """
    mats = [m for m in bpy.data.materials if m is not None]
    if len(mats) < 2:
        return []
    groups = {}
    for m in mats[:limit]:
        if not m.node_tree:
            continue
        h = _material_hash(m)
        if h is None:
            continue
        groups.setdefault(h, []).append(m)
    result = []
    for ms in groups.values():
        if len(ms) > 1:
            ms = sorted(ms, key=lambda x: x.name)
            result.append(ms)
    return result


def check_duplicate_materials(context):
    groups = collect_duplicate_material_groups()
    if not groups:
        return None
    n_dup = sum(len(ms) - 1 for ms in groups)

    # 建立 材质名 → 使用对象 的反向索引，供定位
    obj_of_mat = {}
    for o in _objects():
        if o.type != 'MESH':
            continue
        for slot in o.material_slots:
            if slot and slot.material:
                obj_of_mat.setdefault(slot.material.name, []).append(o.name)
    names = []
    detail_lines = []
    for ms in groups:
        keep = ms[0]
        dups = ms[1:]
        detail_lines.append(f"保留 {keep.name}，合并 {', '.join(m.name for m in dups)}")
        for m in dups:
            names.extend(obj_of_mat.get(m.name, []))
    return Finding(
        "MAT.duplicate_materials", "存在内容相同的重复材质", n_dup,
        IMPACT_MED, EASE_HALF,
        f"按节点树比对发现 {len(groups)} 组重复材质（共浪费 {n_dup} 个）。"
        "重复材质会分散管理，且同样贴图加载多份。",
        "建议：点击「合并重复材质」自动替换为每组第一个材质。\n" + "\n".join(detail_lines[:20]),
        CATEGORY_MATERIAL, names,
    )


def check_material_images(context):
    mats = []
    for m in _materials():
        if not m or not m.node_tree:
            continue
        n_imgs = sum(1 for n in m.node_tree.nodes if n.type == 'TEX_IMAGE')
        if n_imgs > 10:
            mats.append((m, n_imgs))
    if not mats:
        return None
    mat_names = {m.name for m, _ in mats}
    total_imgs = sum(n for _, n in mats)
    objs = set()
    for o in _objects():
        if o.type != 'MESH':
            continue
        for slot in o.material_slots:
            if slot and slot.material and slot.material.name in mat_names:
                objs.add(o.name)
    return Finding(
        "MAT.images_per_material", "部分材质使用贴图过多", len(mats),
        IMPACT_MED, EASE_HARD,
        f"共 {len(mats)} 个材质含 10+ 张贴图（累计 {total_imgs} 张），显存与加载压力大。",
        "建议：合图（Texture Atlas）或精简贴图数量，删掉超出需求的通道。",
        CATEGORY_MATERIAL, list(objs),
    )


def check_normal_map_colorspace(context):
    """检测接在「法线贴图」节点上的贴图是否设为 Non-Color 色彩空间。

    算法与 core/synccheck.py 的 _scan_normal_images 是同一套（应用户要求复用
    蛙灾侧已验证的检测逻辑），但不直接 import 那个模块——core/analyzer 独立版
    打包时只带 core/analyzer/ 一个目录（build.py 的 _iter_analyzer_source_files），
    跨到 core/synccheck.py 的 import 会让独立版一加载就 ModuleNotFoundError，
    这里改成同算法的自包含实现，只检测节点连线（不做按名字猜测的兜底，
    避免独立实现和原版行为在边界情况上悄悄分叉）。
    """
    bad = {}
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
                if src.type == 'TEX_IMAGE' and src.image and \
                        src.image.colorspace_settings.name != 'Non-Color':
                    bad.setdefault(src.image.name, mat.name)
    if not bad:
        return None
    names = sorted(bad)
    lines = [f"{n}（接在「{bad[n]}」的法线节点上）" for n in names]
    names_text = "\n".join(lines[:20])
    if len(lines) > 20:
        names_text += f"\n…以及另外 {len(lines) - 20} 张"
    return Finding(
        "MAT.normal_map_colorspace", "法线贴图色彩空间未设为 Non-Color", len(names),
        IMPACT_MED, EASE_ONE,
        f"{len(names)} 张接在「法线贴图」节点上的贴图色彩空间不是 Non-Color，"
        "会被当作 sRGB 颜色数据处理伽马校正，导致法线方向/凹凸细节计算出错。",
        "建议：点击「全部改成 Non-Color」一键修正。\n" + names_text,
        CATEGORY_MATERIAL,
    )


def check_big_textures(context):
    """检查过大贴图；按尺寸从大到小排序并在详情中列出名字。

    与「Cycles 贴图尺寸未做视口/渲染钳制」原本是两个独立检查项，但对使用者来说
    两者说的是同一件事（贴图太大），只是严重程度/处理难度不同——合并成一条，
    只在确实存在过大贴图时才提「顺手把钳制也打开」，避免用户在列表里看到两条
    重复的「贴图太大」提醒却要分别去理解和处理。"""
    big = []
    for img in bpy.data.images:
        if not img or not _is_real_image(img):
            continue
        w, h = getattr(img, 'size', (0, 0))
        if w * h >= 4096 * 4096:
            big.append(img)
    if not big:
        return None
    big.sort(key=lambda i: i.size[0] * i.size[1], reverse=True)
    n8k = sum(1 for i in big if i.size[0] * i.size[1] >= 8192 * 8192)
    impact = IMPACT_HIGH if n8k else IMPACT_MED

    lines = []
    for i in big:
        w, h = i.size
        lines.append(f"{i.name} ({w}×{h})")
    names_text = "\n".join(lines[:20])
    if len(lines) > 20:
        names_text += f"\n…以及另外 {len(lines) - 20} 张"

    suggestion = "建议：按实际使用钳制/缩小贴图尺寸（如 8K→2K），必要时压缩。"
    if _engine(context) == 'CYCLES':
        cycles = context.scene.cycles
        tex_view = getattr(cycles, 'texture_limit', 'OFF')
        tex_render = getattr(cycles, 'texture_limit_render', 'OFF')
        if tex_view == 'OFF' and tex_render == 'OFF':
            suggestion += ("\n当前 Cycles 的「简化 → 纹理限制」在视口与渲染均为关闭，"
                          "点击「限制 2K」或「限制 4K」会同时钳制视口与渲染的纹理尺寸上限。")
    suggestion += "\n" + names_text

    return Finding(
        "MAT.big_textures", "存在过大的贴图", len(big), impact, EASE_HALF,
        f"{len(big)} 张贴图达到 4K+（其中 {n8k} 张 8K+），显存与加载开销大。",
        suggestion,
        CATEGORY_MATERIAL,
    )


_SUBDIV_MOD_TYPES = ('SUBSURF', 'MULTIRES')


def check_subdivision_high(context):
    """细分曲面 / 多分辨率修改器级数过高（视口或渲染 ≥3）：细分面数按约 4^级数 增长，
    级数每 +1 面数约 ×4，级数 5 相对级数 1 面数可达上百倍。"""
    bad = []
    for o in _scene_objects(context):
        if o.type != 'MESH':
            continue
        for mod in o.modifiers:
            if mod.type not in _SUBDIV_MOD_TYPES:
                continue
            view_lv = getattr(mod, 'levels', 0) if getattr(mod, 'show_viewport', True) else 0
            render_lv = getattr(mod, 'render_levels', 0) if getattr(mod, 'show_render', True) else 0
            lv = max(view_lv, render_lv)
            if lv >= 3:
                bad.append((o, mod.type, lv))
    if not bad:
        return None

    bad.sort(key=lambda r: -r[2])
    max_lv = bad[0][2]
    impact = IMPACT_HIGH if max_lv >= 5 else IMPACT_MED
    lines = [f"「{o.name}」的 {mtype} 修改器细分级数 {lv}" for o, mtype, lv in bad[:20]]
    if len(bad) > 20:
        lines.append(f"…以及另外 {len(bad) - 20} 个")

    return Finding(
        "GEOM.subdivision_high", "存在细分级数过高的修改器", len(bad),
        impact, EASE_HALF,
        "\n".join(lines),
        "建议：非近景/非主体物体降低细分级数（尤其渲染级数）；也可点击下方按钮用"
        "「简化」总开关统一钳制全场景细分级数上限（不改各修改器自身的级数值，"
        "只是运行时限制上限，视口与渲染同时生效）。",
        CATEGORY_STRUCTURE, _cap_names([o.name for o, _mt, _lv in bad]),
    )


def check_unused_materials(context):
    unused_mats = [m.name for m in _materials() if m.users == 0]
    unused_imgs = [i.name for i in bpy.data.images
                   if i and i.users == 0 and _is_real_image(i)]
    if not unused_mats and not unused_imgs:
        return None
    detail = []
    names = []
    if unused_mats:
        detail.append(f"{len(unused_mats)} 个未使用材质")
        names.extend(unused_mats)
    if unused_imgs:
        detail.append(f"{len(unused_imgs)} 张未使用贴图")
        names.extend(unused_imgs)
    names_text = "\n".join(names[:20]) + ("\n…" if len(names) > 20 else "")
    return Finding(
        "DATA.unused_materials", "存在未使用的材质 / 贴图", len(names),
        IMPACT_MED, EASE_ONE,
        "，".join(detail) + f"，占用内存并增大 .blend 体积：\n{names_text}",
        "建议：使用 文件 → 清理 → 未使用的数据（或 orphans purge）删除。",
        CATEGORY_DATA, names,
    )


def check_orphan_data(context):
    """统计无引用（users == 0）的数据块。5.x 已移除 bpy.data.orphans，
    改为直查各 bpy.data 集合里 users==0 的项，兼容 4.2~5.2。
    对象归属「场景结构」的孤立对象检查，这里不重复统计。
    """
    by_type = Counter()
    names = []
    total = 0
    for coll_name in ('materials', 'images', 'actions', 'meshes', 'curves',
                      'textures', 'node_groups', 'collections', 'cameras',
                      'lights', 'worlds', 'armatures', 'lattices',
                      'speakers', 'sounds', 'movieclips'):
        coll = getattr(bpy.data, coll_name, None)
        if coll is None:
            continue
        for d in coll:
            if d is None or getattr(d, 'users', 0) != 0:
                continue
            if coll_name == 'images' and not _is_real_image(d):
                continue
            by_type[type(d).__name__] += 1
            names.append(f"{type(d).__name__}:{d.name}")
            total += 1
    if not total:
        return None
    top = "、".join(f"{k}×{v}" for k, v in by_type.most_common(5))
    names_text = ", ".join(names[:20]) + ("…" if len(names) > 20 else "")
    return Finding(
        "DATA.orphans", "存在孤儿数据块", total,
        IMPACT_MED, EASE_ONE,
        f"共 {total} 个无引用数据块：{top}。\n{names_text}",
        "建议：文件 → 清理 → 未使用的数据（会一并删除上述材质/贴图/Action 等）。",
        CATEGORY_DATA, names,
    )


# 简单检查的入口列表（定义在文件末尾，确保引用的函数均已定义）
_QUICK_CHECKS = [
    check_object_count,
    check_collection_instance_multiplier,
    check_particle_heavy,
    check_negative_scale,
    check_tiny_scale,
    check_big_scale,
    check_empty_objects,
    check_orphan_objects,
    check_unused_shapekeys,
    check_viewport_only,
    check_light_count,
    check_sampling,
    check_bounces,
    check_persistent_data,
    check_motion_blur,
    check_output_format,
    check_device,
    check_resolution,
    check_eevee_shadows,
    check_world_volume,
    check_duplicate_materials,
    check_material_images,
    check_normal_map_colorspace,
    check_big_textures,
    check_subdivision_high,
    check_unused_materials,
    check_orphan_data,
    check_unused_actions,
]


# ============================================================
# 深度检查（批 2）：几何 / 合并 / 缩放统计
# ============================================================

def run_deep(context):
    """深度检查 = 简单检查（批 1）全部 + 批 2 重计算项"""
    _log("开始深度检查（简单检查 + 几何/合并/缩放统计）")
    results = run_quick(context)
    for fn in _DEEP_CHECKS:
        try:
            f = fn(context)
        except Exception as e:  # 单个检查失败不中断整体扫描
            _log(f"深度检查 {fn.__name__} 异常：{e}")
            f = Finding(
                "ERR." + fn.__name__, f"检查失败：{fn.__name__}",
                0, IMPACT_LOW, EASE_HARD, str(e),
                "请把此信息反馈给插件作者", CATEGORY_OTHER,
            )
        if f:
            _log(f"  -> {f.key}: {f.title}")
            results.append(f)
    _log(f"深度检查完成，累计 {len(results)} 条建议")
    return sort_results(results)


# ---- A1/A2 缩放统计 ----

def check_scale_range(context):
    """场景内对象缩放跨度过大：最大值/最小值比值异常，多为单位混用"""
    vals = [abs(v) for o in _objects() for v in o.scale if v != 0]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    if hi / lo < 1000:
        return None
    return Finding(
        "TRANS.scale_range", "场景内缩放跨度过大", 0,
        IMPACT_MED, EASE_HARD,
        f"对象缩放范围约 {lo:.4g} ~ {hi:.4g}（比值 {hi / lo:.0f} 倍），"
        "多来自单位混用或未应用缩放，易在烘焙 / 物理 / 导出时出现数值异常。",
        "建议：统一单位；对异常缩放的对象应用缩放（Ctrl+A → 全部变换）归一。",
        CATEGORY_TRANSFORM,
    )


def check_non_uniform_scale(context):
    """非等比缩放（两轴缩放不同）会歪曲法线、破坏布尔 / 修改器 / 烘焙结果"""
    bad = []
    for o in _objects():
        s = [abs(v) for v in o.scale]
        if not s or min(s) == 0:
            continue
        if max(s) / min(s) > 1.01:
            bad.append(o)
    if not bad:
        return None
    return Finding(
        "TRANS.non_uniform_scale", "存在非等比缩放的物体", len(bad),
        IMPACT_LOW, EASE_HARD,
        "非等比缩放（两个轴缩放不同）会让法线、修改器、布尔与烘焙结果异常。",
        "建议：能避免时在编辑模式建模代替缩放；否则应用缩放后再继续操作。",
        CATEGORY_TRANSFORM, _cap_names([o.name for o in bad]),
    )


# ---- A4/A5 合并候选 ----

def collect_merge_same_material_groups(min_count=10):
    """返回 [[obj, obj, ...], ...] 的同材质对象分组，供 check 与 fix 共用。

    只收 mesh 对象，按 material_slots 的材质名 frozenset 分组，
    只保留组内对象数 ≥ min_count 的组。每组按名称排序，第一个作为合并保留对象。
    """
    groups = {}
    for o in _objects():
        if o.type != 'MESH' or not o.data:
            continue
        mats = frozenset(s.material.name for s in o.material_slots
                        if s and s.material)
        if not mats:
            continue
        groups.setdefault(mats, []).append(o)
    result = []
    for objs in groups.values():
        if len(objs) >= min_count:
            result.append(sorted(objs, key=lambda x: x.name))
    return result


def check_merge_same_material(context):
    """同材质对象过多（如水晶吊坠数百个小件）→ 可合并为一个或集合实例化"""
    cands = collect_merge_same_material_groups()
    if not cands:
        return None
    n_objs = sum(len(objs) for objs in cands)
    impact = IMPACT_HIGH if n_objs > 200 else IMPACT_MED
    top = max(cands, key=len)
    return Finding(
        "STRUCT.merge_same_material", "同材质对象过多，可考虑合并", n_objs,
        impact, EASE_HALF,
        f"有 {len(cands)} 组材质相同且对象 ≥10 个（累计 {n_objs} 个对象）。"
        "大量独立对象会拖慢视口与渲染调度，也增大文件体积。",
        "建议：确认后合并（Ctrl+J）或用集合实例化；纯装饰同材质小件"
        "（如水晶吊坠数百个）合并后用顶点色 / 贴图区分，可显著减负。",
        CATEGORY_STRUCTURE, _cap_names([o.name for o in top]),
    )


def _mesh_geom_hash(mesh):
    """把网格几何归一化为哈希（顶点坐标保留 4 位、边 / 面拓扑），
    用于检测内容完全相同但数据块不同的重复网格。超大网格跳过避免开销。"""
    try:
        n_v = len(mesh.vertices)
        if n_v > 50_000:
            return None
        verts = tuple(tuple(round(c, 4) for c in v.co) for v in mesh.vertices)
        edges = tuple(tuple(e.vertices) for e in mesh.edges)
        polys = tuple(tuple(p.vertices) for p in mesh.polygons)
        return (n_v, len(edges), len(polys), verts, edges, polys)
    except Exception:
        return None


def collect_identical_duplicate_groups():
    """返回 [[keep_mesh, dup_mesh, ...], ...] 的几何相同重复网格分组，供 check 与 fix 共用。

    只收无形态键的 mesh（带形态键的有额外意义，不合并）；超大网格（>5万顶点）跳过。
    每组按 mesh 名排序，第一个作为关联复制保留对象。
    """
    groups = {}
    for m in bpy.data.meshes:
        if not m or m.shape_keys:
            continue
        h = _mesh_geom_hash(m)
        if h is not None:
            groups.setdefault(h, []).append(m)
    result = []
    for ms in groups.values():
        if len(ms) >= 2:
            result.append(sorted(ms, key=lambda x: x.name))
    return result


def check_identical_duplicates(context):
    """几何完全相同的重复网格：多为 Shift-D 复制未关联，可改为关联复制 / 实例化。
    带形态键的网格跳过（其数据有额外意义，不适合直接合并）。
    """
    # mesh 名 → 引用它的对象名列表（用于详情/定位）
    mesh_objs = {}
    for o in _objects():
        if o.type == 'MESH' and o.data:
            mesh_objs.setdefault(o.data.name, []).append(o.name)
    dups = collect_identical_duplicate_groups()
    if not dups:
        return None
    n_dup = sum(len(ms) - 1 for ms in dups)
    names = []
    for ms in dups:
        for m in ms[1:]:
            names.extend(mesh_objs.get(m.name, []))
    return Finding(
        "STRUCT.identical_duplicates", "存在几何完全相同的重复网格", n_dup,
        IMPACT_MED, EASE_HARD,
        f"发现 {len(dups)} 组网格几何完全相同但数据块不同（共 {n_dup} 个多余）。"
        "通常是 Shift-D 复制后未做关联，白白重复占用内存与文件体积。",
        "建议：对重复网格改用 Alt+D 关联复制，或改用集合实例化 / 关联数据。",
        CATEGORY_STRUCTURE, _cap_names(names),
    )


# ---- B1/B2 面密度与相机空间占用 ----

_HIGH_POLY_THRESHOLD = 100_000


def check_high_poly(context):
    """单个对象面数过高：占用显存、拖慢交互与渲染"""
    bad = []
    for o in _objects():
        if o.type != 'MESH' or not o.data:
            continue
        n = len(o.data.polygons)
        if n > _HIGH_POLY_THRESHOLD:
            bad.append((o, n))
    if not bad:
        return None
    bad.sort(key=lambda x: -x[1])
    total = sum(n for _, n in bad)
    impact = IMPACT_HIGH if total > 2_000_000 else IMPACT_MED
    return Finding(
        "GEOM.high_poly_count", "存在高面数对象", len(bad),
        impact, EASE_HALF,
        f"{len(bad)} 个对象面数超过 {_HIGH_POLY_THRESHOLD:,}（合计 {total:,} 面）。"
        "高面数占用显存并拖慢交互与渲染。",
        "建议：雕刻 / 扫描高模用重拓扑 + 法线贴图；不近看的部分用 Decimate；"
        "降低细分修改器级数。",
        CATEGORY_STRUCTURE, _cap_names([o.name for o, _ in bad]),
    )


def check_camera_occupancy(context):
    """高面数对象在相机画面中占比极小：细节基本不可见却仍参与渲染。
    仅在场景存在相机时检查（无相机则不提示）。
    """
    scene = context.scene
    cam = scene.camera
    if not cam:
        return None
    from bpy_extras.object_utils import world_to_camera_view
    results = []
    for o in _objects():
        if o.type != 'MESH' or not o.data:
            continue
        if len(o.data.polygons) < 50_000:
            continue
        xmin = ymin = 1e9
        xmax = ymax = -1e9
        in_front = False
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            try:
                x, y, depth = world_to_camera_view(scene, cam, w)
            except Exception:
                continue
            if depth < 0:
                continue
            in_front = True
            xmin, xmax = min(xmin, x), max(xmax, x)
            ymin, ymax = min(ymin, y), max(ymax, y)
        if not in_front:
            continue
        if (xmax - xmin) * (ymax - ymin) < 0.02:
            results.append((o, (xmax - xmin) * (ymax - ymin)))
    if not results:
        return None
    results.sort(key=lambda x: x[1])
    return Finding(
        "GEOM.camera_occupancy", "高面数对象在画面中占比极小", len(results),
        IMPACT_HIGH, EASE_HARD,
        f"{len(results)} 个高面数对象（≥5 万面）在当前相机画面中占比 <2%，"
        "细节基本不可见却仍在渲染。",
        "建议：从相机视图（Ctrl+Numpad0）确认，必要时减面、移出画面或隐藏。",
        CATEGORY_STRUCTURE, _cap_names([o.name for o, _ in results]),
    )


# ---- C1-C3 非流形几何 ----

_NONMANIFOLD_MAX_OBJS = 100   # 只扫前 100 个网格对象，控制耗时
_NONMANIFOLD_MAX_VERTS = 100_000  # 超大网格跳过（bmesh 转换开销过大）


def check_non_manifold(context):
    """非流形边 / 非流形点 / 零面积面：导致布尔、渲染、3D 打印异常"""
    import bmesh
    found = []
    skipped = 0
    total_e = total_v = total_z = 0
    meshes = [o for o in _objects() if o.type == 'MESH' and o.data]
    for o in meshes[:_NONMANIFOLD_MAX_OBJS]:
        m = o.data
        if len(m.vertices) > _NONMANIFOLD_MAX_VERTS:
            skipped += 1
            continue
        bm = bmesh.new()
        try:
            bm.from_mesh(m)
            ne = sum(1 for e in bm.edges if not e.is_manifold)
            nv = sum(1 for v in bm.verts if not v.is_manifold)
            nz = sum(1 for f in bm.faces if f.calc_area() < 1e-6)
        finally:
            bm.free()
        if ne or nv or nz:
            total_e += ne
            total_v += nv
            total_z += nz
            found.append((o.name, ne, nv, nz))
    if not found:
        return None
    top = found[:5]
    detail = (f"扫描到 {len(found)} 个对象含非流形 / 零面积面"
              f"（共 非流形边 {total_e}、非流形点 {total_v}、零面积面 {total_z}）。"
              "非流形会导致布尔 / 渲染 / 3D 打印异常。")
    if skipped:
        detail += f"另有 {skipped} 个超大网格因面数上限未扫描。"
    impact = IMPACT_HIGH if total_e > 100 else IMPACT_MED
    return Finding(
        "GEOM.non_manifold", "存在非流形几何", len(found),
        impact, EASE_HARD,
        detail + " 主要对象：" + "、".join(
            f"{n}（边{ne}/点{nv}/零面{nz}）" for n, ne, nv, nz in top),
        "建议：进入编辑模式 → 网格 → 检查 → 非流形边 / 面，逐一修复；"
        "零面积面可 移除双面 或用「网格清理」工具。",
        CATEGORY_DATA, _cap_names([n for n, *_ in found]),
    )


# 深度检查的入口列表（定义在文件末尾，确保引用的函数均已定义）
_DEEP_CHECKS = [
    check_geonode_instances,
    check_scale_range,
    check_non_uniform_scale,
    check_merge_same_material,
    check_identical_duplicates,
    check_high_poly,
    check_camera_occupancy,
    check_non_manifold,
]
