# 图转立体：位图轮廓 → 挤出几何
# 几何模式：自写二值化+轮廓提取+直线简化，出直边 POLY 曲线（logo 几何体感）
# 平滑模式：走内置 potrace（Trace Image to Grease Pencil），贝塞尔圆润边
# （合并自 Pond/trace2solid.py：逻辑层；面板在 ui/pond/panels/trace2solid.py）
import os
import bpy

from bpy_extras.io_utils import ImportHelper

MAX_SIDE = 512  # 大图先缩，直接描高分辨率会出密集噪声


# ── 纯算法部分（不碰 bpy，可单测） ──────────────────────────

def _lum(pixels, i):
    return 0.2126 * pixels[i] + 0.7152 * pixels[i + 1] + 0.0722 * pixels[i + 2]


def _detect_dark_fg(pixels, w, h):
    """图形是暗色还是亮色。
    四角不透明（满幅图）：四角当背景，背景亮则前景暗。
    四角透明（贴纸/水印图）：不透明区的主色就是图形主色，主色暗则前景暗。"""
    spots = ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2))
    corner_opaque = [s for s in spots if pixels[(s[1] * w + s[0]) * 4 + 3] > 0.5]
    if len(corner_opaque) >= len(spots) // 2:
        bg = sum(_lum(pixels, (y * w + x) * 4) for x, y in corner_opaque) / len(corner_opaque)
        return bg > 0.5
    step = max(1, max(w, h) // 128)
    total, n = 0.0, 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            i = (y * w + x) * 4
            if pixels[i + 3] > 0.5:
                total += _lum(pixels, i)
                n += 1
    return (total / n) < 0.5 if n else True  # 主色暗 → 前景暗


def _is_fg(pixels, w, x, y, threshold, use_alpha, dark_fg):
    i = (y * w + x) * 4
    if use_alpha:
        return pixels[i + 3] > 0.5
    if pixels[i + 3] <= 0.5:
        return False
    lum = _lum(pixels, i)
    return (lum < threshold) if dark_fg else (lum > threshold)


def make_grid(pixels, w, h, threshold, use_alpha, max_side=MAX_SIDE, invert=False):
    """全尺寸像素 → 自动判极性 → 裁到图形包围盒 → 降采样成 bool 网格
    返回 (grid, gw, gh)。白底黑图、黑底白图、透明底都吃。"""
    dark_fg = (not use_alpha) and (_detect_dark_fg(pixels, w, h) ^ invert)
    # 粗扫找前景包围盒（分辨率全花在图形上，小字条码才活得下来）
    step = max(1, max(w, h) // 256)
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(0, h, step):
        for x in range(0, w, step):
            if _is_fg(pixels, w, x, y, threshold, use_alpha, dark_fg):
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if x1 < 0:
        return [], 0, 0  # 全空
    pad = max(2, step * 2)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w - 1, x1 + pad), min(h - 1, y1 + pad)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    # 最近邻降采样到 max_side 以内（小图不放大）
    scale = min(1.0, max_side / max(bw, bh))
    gw, gh = max(2, int(bw * scale)), max(2, int(bh * scale))
    grid = [[False] * gw for _ in range(gh)]
    for gy in range(gh):
        sy = y0 + min(bh - 1, int(gy / scale))
        row = grid[gy]
        for gx in range(gw):
            sx = x0 + min(bw - 1, int(gx / scale))
            row[gx] = _is_fg(pixels, w, sx, sy, threshold, use_alpha, dark_fg)
    return grid, gw, gh


def binarize(pixels, w, h, threshold, use_alpha):
    """RGBA float 列表 → bool 网格 grid[y][x]，True=图形（无裁剪，留给单测用）"""
    grid = [[False] * w for _ in range(h)]
    dark_fg = (not use_alpha) and _detect_dark_fg(pixels, w, h)
    for y in range(h):
        row = grid[y]
        for x in range(w):
            row[x] = _is_fg(pixels, w, x, y, threshold, use_alpha, dark_fg)
    return grid


def _cell_segments(tl, tr, bl, br, x, y):
    """marching squares：一个 2x2 cell 输出 0~2 条线段（端点为半格坐标*2 的整数）"""
    case = (tl << 3) | (tr << 2) | (br << 1) | bl
    X, Y = x * 2, y * 2
    top, right = (X + 1, Y), (X + 2, Y + 1)
    bottom, left = (X + 1, Y + 2), (X, Y + 1)
    table = {
        1: [(left, bottom)], 2: [(bottom, right)], 3: [(left, right)],
        4: [(top, right)], 5: [(left, top), (bottom, right)],
        6: [(top, bottom)], 7: [(left, top)],
        8: [(top, left)], 9: [(top, bottom)],
        10: [(top, right), (bottom, left)], 11: [(top, right)],
        12: [(right, left)], 13: [(right, bottom)], 14: [(bottom, left)],
    }
    return table.get(case, [])


def extract_rings(grid, w, h):
    """marching squares 提所有闭合轮廓环，返回 [[(x,y)...], ...]（半格坐标*2）"""
    segs = []
    for y in range(h - 1):
        for x in range(w - 1):
            segs.extend(_cell_segments(
                grid[y][x], grid[y][x + 1], grid[y + 1][x], grid[y + 1][x + 1], x, y))
    # 端点接龙串环（线段当无向边，每个端点度数应为2）
    adj = {}
    for a, b in segs:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    rings = []
    visited = set()
    for start in adj:
        if start in visited:
            continue
        ring = [start]
        prev, cur = None, start
        while True:
            visited.add(cur)
            nbrs = [p for p in adj.get(cur, []) if p != prev]
            if not nbrs:
                break
            step = nbrs[0]
            if step == start:
                rings.append(ring)
                break
            if step in visited:
                break
            ring.append(step)
            prev, cur = cur, step
    return [r for r in rings if len(r) >= 3]


def _pt_seg_dist2(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def rdp(points, eps):
    """Ramer-Douglas-Peucker 直线简化（开链）"""
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    imax, dmax = 0, -1.0
    for i in range(1, len(points) - 1):
        d = _pt_seg_dist2(points[i], a, b)
        if d > dmax:
            imax, dmax = i, d
    if dmax > eps * eps:
        left = rdp(points[:imax + 1], eps)
        right = rdp(points[imax:], eps)
        return left[:-1] + right
    return [a, b]


def simplify_ring(ring, eps):
    """闭环简化：从最远点对拆两段分别 RDP，避免起点被锁死"""
    if len(ring) < 5 or eps <= 0:
        return ring
    a = 0
    b = max(range(len(ring)),
            key=lambda i: (ring[i][0] - ring[a][0]) ** 2 + (ring[i][1] - ring[a][1]) ** 2)
    if b == 0:
        return ring
    seg1 = rdp(ring[a:b + 1], eps)
    seg2 = rdp(ring[b:] + [ring[0]], eps)
    out = seg1[:-1] + seg2[:-1]
    return out if len(out) >= 3 else ring


# ── bpy 部分 ──────────────────────────────────────────────

def _has_useful_alpha(pixels):
    """alpha 通道有明有暗才算有用"""
    sample = pixels[3::40]  # 抽样
    return any(a < 0.5 for a in sample) and any(a > 0.5 for a in sample)


def _rings_to_curve(rings, w, h, name, size, extrude, bevel):
    """环列表 → 直边 POLY 曲线（填充+挤出+倒角），保持图片长宽比，最长边=size"""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = extrude
    cu.bevel_depth = bevel
    scale = size / max(w * 2, h * 2)
    for ring in rings:
        sp = cu.splines.new("POLY")
        sp.points.add(len(ring) - 1)
        for i, (x, y) in enumerate(ring):
            # bpy 像素第一行就在图像底部，和 3D 的 y 向同向，只做居中
            sp.points[i].co = ((x - w) * scale, (y - h) * scale, 0.0, 1.0)
        sp.use_cyclic_u = True
    obj = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(obj)
    return obj


class POND_OT_trace_solid(bpy.types.Operator, ImportHelper):
    """选一张图，矢量化并挤出成立体（logo/剪影专用）"""
    bl_idname = "pond.trace_solid"
    bl_label = "图转立体"
    bl_options = {"REGISTER", "UNDO"}
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.webp;*.tif;*.tiff;*.bmp", options={"HIDDEN"})

    mode: bpy.props.EnumProperty(name="模式", items=[
        ("GEO", "几何", "直边多边形，尖角保尖，logo几何体感"),
        ("SMOOTH", "平滑", "potrace贝塞尔，圆润边"),
    ], default="GEO")
    resolution: bpy.props.EnumProperty(
        name="采样精度", items=[
            ("512", "快 512", "一两秒出活，大轮廓够用"),
            ("1024", "精 1024", "小字条码的甜点档，几秒"),
            ("2048", "极限 2048", "纯Python要跑半分钟，急图别用"),
        ], default="1024",
        description="几何模式的采样上限（配合自动裁切，是图形本身的分辨率）")
    source: bpy.props.EnumProperty(
        name="轮廓依据", items=[
            ("AUTO", "自动", "有透明通道用透明，否则用亮度"),
            ("ALPHA", "透明通道", "按不透明区提形状"),
            ("LUM", "亮度", "按明暗提形状；带白描边的水印图用这个"),
        ], default="AUTO")
    invert: bpy.props.BoolProperty(
        name="反转黑白", default=False,
        description="亮度判定提反了就勾上（提取到背景而不是图形时）")
    threshold: bpy.props.FloatProperty(name="亮度阈值", default=0.5, min=0.02, max=0.98)
    simplify: bpy.props.FloatProperty(
        name="几何简化(px)", default=1.6, min=0.0, max=12.0,
        description="越大越硬朗，直线越长；0为不简化")
    size: bpy.props.FloatProperty(name="目标尺寸", default=2.0, min=0.01, unit="LENGTH")
    extrude: bpy.props.FloatProperty(name="挤出深度", default=0.12, min=0.0, unit="LENGTH")
    bevel: bpy.props.FloatProperty(name="倒角半径", default=0.0, min=0.0, unit="LENGTH")

    def execute(self, context):
        if self.mode == "SMOOTH":
            return self._run_smooth(context)
        return self._run_geo(context)

    def _run_geo(self, context):
        try:
            existed = bpy.data.images.get(bpy.path.basename(self.filepath)) is not None
            img = bpy.data.images.load(self.filepath, check_existing=True)
            w, h = img.size
            px = list(img.pixels)
            if not existed:
                bpy.data.images.remove(img)
        except Exception as e:
            self.report({"ERROR"}, f"图读不进来：{e}")
            return {"CANCELLED"}
        if self.source == "AUTO":
            use_alpha = _has_useful_alpha(px)
        else:
            use_alpha = self.source == "ALPHA"
        grid, gw, gh = make_grid(px, w, h, self.threshold, use_alpha,
                                 max_side=int(self.resolution), invert=self.invert)
        rings = extract_rings(grid, gw, gh) if gw else []
        if not rings:
            self.report({"WARNING"}, "没提出轮廓，试试调阈值（当前按"
                        + ("透明通道" if use_alpha else "亮度") + "判定）")
            return {"CANCELLED"}
        rings = [simplify_ring(r, self.simplify * 2) for r in rings]  # 半格坐标是2倍
        name = os.path.splitext(os.path.basename(self.filepath))[0] + "_立体"
        obj = _rings_to_curve(rings, gw, gh, name, self.size, self.extrude, self.bevel)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj
        total = sum(len(r) for r in rings)
        self.report({"INFO"}, f"{len(rings)} 个轮廓 / {total} 个顶点（"
                    + ("透明通道" if use_alpha else "亮度") + "判定）")
        return {"FINISHED"}

    def _flatten_alpha(self, img):
        """透明底烙白底存临时副本。potrace 把透明当黑，黑图形会沉底"""
        px = list(img.pixels)
        if not _has_useful_alpha(px):
            return img
        for i in range(0, len(px), 4):
            a = px[i + 3]
            px[i] = px[i] * a + (1 - a)
            px[i + 1] = px[i + 1] * a + (1 - a)
            px[i + 2] = px[i + 2] * a + (1 - a)
            px[i + 3] = 1.0
        flat = bpy.data.images.new("池塘_烙白底", img.size[0], img.size[1])
        flat.pixels.foreach_set(px)
        tmp = os.path.join(bpy.app.tempdir, "pond_flat.png")
        flat.filepath_raw = tmp
        flat.file_format = "PNG"
        flat.save()
        bpy.data.images.remove(flat)
        return bpy.data.images.load(tmp, check_existing=False)

    def _run_smooth(self, context):
        # 内置 potrace：建图片Empty → Trace → GP → 转曲线
        empty = bpy.data.objects.new("池塘_描摹底板", None)
        empty.empty_display_type = "IMAGE"
        try:
            src = bpy.data.images.load(self.filepath, check_existing=True)
            empty.data = self._flatten_alpha(src)
        except Exception as e:
            bpy.data.objects.remove(empty)
            self.report({"ERROR"}, f"图读不进来：{e}")
            return {"CANCELLED"}
        context.scene.collection.objects.link(empty)
        bpy.ops.object.select_all(action="DESELECT")
        empty.select_set(True)
        context.view_layer.objects.active = empty

        trace = None
        for ns, op in (("grease_pencil", "trace_image"), ("gpencil", "trace_image"),
                       ("object", "trace_image")):
            cand = getattr(getattr(bpy.ops, ns, None), op, None)
            if cand is None:
                continue
            try:
                cand.get_rna_type()  # bpy.ops 属性是惰性壳,不存在的要调用才炸
            except Exception:
                continue
            trace = cand
            break
        if trace is None:
            bpy.data.objects.remove(empty)
            self.report({"ERROR"}, "这个版本找不到内置描摹，先用几何模式")
            return {"CANCELLED"}
        before = {o.name for o in bpy.data.objects}
        try:
            trace(threshold=self.threshold, target="NEW")
        except TypeError:
            trace()
        except Exception as e:
            bpy.data.objects.remove(empty)
            self.report({"ERROR"}, f"描摹失败：{e}")
            return {"CANCELLED"}

        # 后台跑时 active 不会切过来，用前后差集抓新笔画
        gp = next((o for o in bpy.data.objects if o.name not in before
                   and o.type in {"GREASEPENCIL", "GPENCIL"}), None)
        if gp is None:
            if empty.name in bpy.data.objects:
                bpy.data.objects.remove(empty)
            self.report({"ERROR"}, "描摹没出笔画，换几何模式试试")
            return {"CANCELLED"}

        # GP3 的 convert 到曲线是空转，直接读笔画贝塞尔自己建曲线
        curve_obj, kept, skipped = None, 0, 0
        try:
            strokes = []
            for layer in gp.data.layers:
                for frame in layer.frames:
                    strokes.extend(list(frame.drawing.strokes))
            # 收集点，算总包围盒，过滤描黑底描出来的图片外框
            def _handle_co(h, fallback):
                try:
                    return tuple(h)
                except TypeError:
                    pass
                for attr in ("position", "co"):
                    v = getattr(h, attr, None)
                    if v is not None:
                        return tuple(v)
                return fallback

            stroke_pts = []
            for s in strokes:
                pts = []
                for p in s.points:
                    co = tuple(p.position)
                    pts.append((co, _handle_co(p.handle_left, co),
                                _handle_co(p.handle_right, co)))
                stroke_pts.append((s, pts))
            xs = [c[0][0] for _sp, pl in stroke_pts for c in pl]
            ys = [c[0][1] for _sp, pl in stroke_pts for c in pl]
            span_x, span_y = (max(xs) - min(xs) or 1), (max(ys) - min(ys) or 1)

            stem = os.path.splitext(os.path.basename(self.filepath))[0]
            cu = bpy.data.curves.new(stem + "_立体", "CURVE")
            cu.dimensions = "2D"
            cu.fill_mode = "BOTH"
            cu.extrude = self.extrude
            cu.bevel_depth = self.bevel
            for s, pts in stroke_pts:
                if len(pts) < 2:
                    continue
                pxs = [c[0][0] for c in pts]
                pys = [c[0][1] for c in pts]
                if len(stroke_pts) > 1 and \
                   (max(pxs) - min(pxs)) > span_x * 0.98 and \
                   (max(pys) - min(pys)) > span_y * 0.98:
                    skipped += 1
                    continue  # 整图外框
                sp = cu.splines.new("BEZIER")
                sp.bezier_points.add(len(pts) - 1)
                for i, (co, hl, hr) in enumerate(pts):
                    bp = sp.bezier_points[i]
                    bp.co = co
                    bp.handle_left = hl
                    bp.handle_right = hr
                    bp.handle_left_type = bp.handle_right_type = "FREE"
                sp.use_cyclic_u = bool(getattr(s, "cyclic", True))
                kept += 1
            if kept:
                curve_obj = bpy.data.objects.new(stem + "_立体", cu)
                context.scene.collection.objects.link(curve_obj)
                scale = self.size / max(span_x, span_y)  # 最长边 = 目标尺寸
                curve_obj.scale = (scale, scale, scale)
                bpy.ops.object.select_all(action="DESELECT")
                curve_obj.select_set(True)
                context.view_layer.objects.active = curve_obj
            else:
                bpy.data.curves.remove(cu)
        except Exception as e:
            self.report({"ERROR"}, f"笔画转曲线失败：{e}")

        # 清场：底板和中间 GP 都撤走
        gp_data = gp.data
        bpy.data.objects.remove(gp)
        for coll_name in ("grease_pencils_v3", "grease_pencils"):
            coll = getattr(bpy.data, coll_name, None)
            if coll and gp_data.name in coll and gp_data.users == 0:
                coll.remove(gp_data)
                break
        if empty.name in bpy.data.objects:
            bpy.data.objects.remove(empty)

        if curve_obj:
            self.report({"INFO"}, f"平滑描摹完成：{kept} 条轮廓"
                        + (f"（滤掉外框 {skipped}）" if skipped else ""))
            return {"FINISHED"}
        self.report({"ERROR"}, "描出的笔画没能转成曲线")
        return {"CANCELLED"}


_classes = (
    POND_OT_trace_solid,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
