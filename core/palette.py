# 色卡转调色板：读色卡图片像素提取主色，生成 Blender 原生调色板
# 直接从像素取色，不吸屏幕，绕开视口色彩变换的偏色
# v0.7.1: 挂载失败不再静默；一键删除/清空；视口可拖动悬浮色卡窗
# （合并自 Pond/palette.py：逻辑层（含视口悬浮色卡窗）；面板在 ui/pond/panels/palette.py）
import os
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from bpy_extras.io_utils import ImportHelper

MAX_COLORS = 24
SAMPLE = 48          # 缩到 48x48 采样
MERGE_DIST = 0.09    # 近似色合并阈值(RGB欧氏距离)


def _extract_colors(img):
    """缩小采样,按出现频率取主色,近似色合并"""
    tmp = img.copy()
    try:
        tmp.scale(SAMPLE, SAMPLE)
        px = list(tmp.pixels)  # RGBA, float
    finally:
        bpy.data.images.remove(tmp)

    buckets = {}
    for i in range(0, len(px), 4):
        r, g, b, a = px[i:i + 4]
        if a < 0.5:
            continue  # 透明区跳过
        key = (round(r * 20) / 20, round(g * 20) / 20, round(b * 20) / 20)
        buckets[key] = buckets.get(key, 0) + 1

    ranked = sorted(buckets.items(), key=lambda kv: -kv[1])
    picked = []
    for (r, g, b), _cnt in ranked:
        if len(picked) >= MAX_COLORS:
            break
        if any((r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2 < MERGE_DIST ** 2
               for pr, pg, pb in picked):
            continue
        picked.append((r, g, b))
    return picked


def _make_palette(name, colors):
    pal = bpy.data.palettes.get(name)
    if pal:
        bpy.data.palettes.remove(pal)
    pal = bpy.data.palettes.new(name)
    for c in colors:
        pc = pal.colors.new()
        pc.color = c
    return pal


def _assign_palette(context, pal):
    """挂到绘画工具上；返回失败信息列表(空=全成功)。不再静默吞异常"""
    ts = context.tool_settings
    errors = []
    for label, paint in (("贴图绘制", ts.image_paint), ("顶点绘制", ts.vertex_paint)):
        try:
            paint.palette = pal
        except Exception as e:
            errors.append(f"{label}: {e}")
    return errors


def _active_palette(context):
    return getattr(context.tool_settings.image_paint, "palette", None)


# ---------- 悬浮色卡窗 ----------
# 视口里一块可拖动的小窗：标题栏拖动、右上角×关闭、点色块=设画笔颜色
SW = 24        # 色块边长
GAP = 2
PAD = 6
TITLE_H = 22
COLS = 8

_float = {"on": False, "handle": None, "pos": [70, 260], "size": (0, 0), "drag": None}


def _tag_redraw():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _float_layout(colors):
    n = len(colors)
    cols = min(COLS, n) if n else 1
    rows = (n + cols - 1) // cols if n else 1
    w = PAD * 2 + cols * SW + (cols - 1) * GAP
    h = TITLE_H + PAD * 2 + rows * SW + (rows - 1) * GAP
    return cols, max(w, 120), h


def _swatch_rects(colors):
    """返回 [(x0,y0,x1,y1,index)]，坐标为悬浮窗本地区域坐标"""
    cols, w, h = _float_layout(colors)
    x, y = _float["pos"]
    rects = []
    for i in range(len(colors)):
        r_i, c_i = divmod(i, cols)
        sx = x + PAD + c_i * (SW + GAP)
        sy = y + h - TITLE_H - PAD - SW - r_i * (SW + GAP)
        rects.append((sx, sy, sx + SW, sy + SW, i))
    return rects


def _close_rect():
    w, h = _float["size"]
    x, y = _float["pos"]
    return (x + w - 18, y + h - TITLE_H + 4, x + w - 4, y + h - 4)


def _draw_float():
    if not _float["on"]:
        return
    try:
        pal = _active_palette(bpy.context)
        colors = [tuple(c.color) for c in pal.colors] if pal else []
        cols, w, h = _float_layout(colors)
        _float["size"] = (w, h)
        x, y = _float["pos"]

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")

        def rect(x0, y0, x1, y1, col):
            batch = batch_for_shader(
                shader, "TRI_FAN",
                {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]})
            shader.uniform_float("color", col)
            batch.draw(shader)

        rect(x, y, x + w, y + h, (0.07, 0.07, 0.08, 0.92))              # 背景
        rect(x, y + h - TITLE_H, x + w, y + h, (0.15, 0.15, 0.17, 0.95))  # 标题栏
        cx0, cy0, cx1, cy1 = _close_rect()
        rect(cx0, cy0, cx1, cy1, (0.55, 0.22, 0.22, 0.9))               # 关闭钮

        for sx, sy, sx1, sy1, i in _swatch_rects(colors):
            c = colors[i]
            rect(sx, sy, sx1, sy1, (c[0], c[1], c[2], 1.0))

        gpu.state.blend_set("NONE")

        blf.size(0, 11)
        blf.color(0, 0.85, 0.85, 0.85, 1.0)
        blf.position(0, x + PAD, y + h - TITLE_H + 7, 0)
        title = pal.name if pal else "没挂载色卡"
        max_w = w - PAD - 22  # 别压到关闭钮
        while title and blf.dimensions(0, title + "…")[0] > max_w:
            title = title[:-1]
        blf.draw(0, (title + "…") if pal and title != pal.name else title)
    except Exception as e:
        # 不做哑巴 except：打印到控制台(快照模块的教训)
        print(f"[池塘·色卡悬浮窗] 绘制出错: {e!r}")


def _remove_float_handle():
    if _float["handle"] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_float["handle"], "WINDOW")
        except Exception:
            pass
        _float["handle"] = None


def _auto_open_float():
    """导入完自动弹出悬浮色卡窗（后台/无窗口环境下静默跳过）"""
    if _float["on"]:
        _tag_redraw()
        return
    try:
        bpy.ops.pond.palette_float("INVOKE_DEFAULT")
    except Exception as e:
        print(f"[池塘·色卡] 自动弹悬浮窗没成: {e!r}")


def _region_local(context, event):
    """把窗口绝对鼠标坐标换算成鼠标所在 3D 视口 WINDOW 区域的本地坐标；不在视口内返回 None"""
    mx, my = event.mouse_x, event.mouse_y
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            if region.x <= mx < region.x + region.width and \
               region.y <= my < region.y + region.height:
                return mx - region.x, my - region.y
    return None


def _hit(px, py, box):
    x0, y0, x1, y1 = box
    return x0 <= px <= x1 and y0 <= py <= y1


class POND_OT_palette_float(bpy.types.Operator):
    """开关视口里的悬浮色卡小窗（拖标题栏移动，点色块换画笔颜色，×关闭）"""
    bl_idname = "pond.palette_float"
    bl_label = "悬浮色卡窗"

    def invoke(self, context, event):
        if _float["on"]:
            _float["on"] = False
            _remove_float_handle()
            _tag_redraw()
            return {"FINISHED"}
        _float["on"] = True
        _float["handle"] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_float, (), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        _tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not _float["on"]:           # 被面板按钮关掉了
            _remove_float_handle()
            _tag_redraw()
            return {"FINISHED"}

        local = _region_local(context, event)

        # 拖动中
        if _float["drag"] is not None:
            if event.type == "MOUSEMOVE":
                if local:
                    ox, oy = _float["drag"]
                    _float["pos"] = [local[0] - ox, local[1] - oy]
                    _tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE":
                _float["drag"] = None
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if local is None:
            return {"PASS_THROUGH"}
        px, py = local
        x, y = _float["pos"]
        w, h = _float["size"]

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if _hit(px, py, _close_rect()):
                _float["on"] = False
                _remove_float_handle()
                _tag_redraw()
                return {"FINISHED"}
            # 标题栏 → 开始拖
            if _hit(px, py, (x, y + h - TITLE_H, x + w, y + h)):
                _float["drag"] = (px - x, py - y)
                return {"RUNNING_MODAL"}
            # 色块 → 设画笔颜色
            pal = _active_palette(context)
            colors = [tuple(c.color) for c in pal.colors] if pal else []
            for sx, sy, sx1, sy1, i in _swatch_rects(colors):
                if _hit(px, py, (sx, sy, sx1, sy1)):
                    self._set_brush_color(context, colors[i])
                    return {"RUNNING_MODAL"}
            # 窗体空白处点击也吞掉，免得误选后面的物体
            if _hit(px, py, (x, y, x + w, y + h)):
                return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    @staticmethod
    def _set_brush_color(context, color):
        ts = context.tool_settings
        ups = getattr(ts, "unified_paint_settings", None)
        if ups and getattr(ups, "use_unified_color", False):
            ups.color = color
        for paint in (ts.image_paint, ts.vertex_paint):
            br = getattr(paint, "brush", None)
            if br:
                try:
                    br.color = color
                except Exception as e:
                    print(f"[池塘·色卡] 设画笔颜色失败: {e!r}")
        _tag_redraw()


# ---------- 删除 ----------
class POND_OT_palette_delete(bpy.types.Operator):
    """删除当前挂载的这块色卡"""
    bl_idname = "pond.palette_delete"
    bl_label = "删除当前色卡"
    bl_options = {"UNDO"}

    def execute(self, context):
        ts = context.tool_settings
        # 挂载失败也要能删：先找挂着的，找不到就删最新导入的那块
        pal = _active_palette(context) or getattr(ts.vertex_paint, "palette", None)
        if not pal:
            cards = [p for p in bpy.data.palettes if p.name.endswith("_色卡")]
            if not cards:
                self.report({"WARNING"}, "没有色卡可删")
                return {"CANCELLED"}
            pal = cards[-1]
        name = pal.name
        bpy.data.palettes.remove(pal)
        rest = [p for p in bpy.data.palettes if p.name.endswith("_色卡")]
        nxt = rest[-1] if rest else None
        for paint in (ts.image_paint, ts.vertex_paint):
            try:
                paint.palette = nxt
            except Exception:
                pass
        _tag_redraw()
        self.report({"INFO"}, "「" + name + "」删掉了" + ("，换上「" + nxt.name + "」" if nxt else ""))
        return {"FINISHED"}


class POND_OT_palette_clear_all(bpy.types.Operator):
    """把所有导入生成的色卡(名字带「_色卡」的)一次清光"""
    bl_idname = "pond.palette_clear_all"
    bl_label = "清空导入的色卡"
    bl_options = {"UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        doomed = [p for p in bpy.data.palettes if p.name.endswith("_色卡")]
        if not doomed:
            self.report({"INFO"}, "没有导入的色卡可清")
            return {"CANCELLED"}
        n = len(doomed)
        for p in doomed:
            bpy.data.palettes.remove(p)
        _tag_redraw()
        self.report({"INFO"}, f"清掉 {n} 块导入色卡")
        return {"FINISHED"}


# ---------- 导入 ----------
class POND_OT_palette_from_file(bpy.types.Operator, ImportHelper):
    """选一张色卡图片，提取主色生成调色板"""
    bl_idname = "pond.palette_from_file"
    bl_label = "导入色卡图"
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.webp;*.tif;*.tiff;*.bmp", options={"HIDDEN"})

    def execute(self, context):
        try:
            img = bpy.data.images.load(self.filepath, check_existing=True)
        except Exception as e:
            self.report({"ERROR"}, f"图读不进来：{e}")
            return {"CANCELLED"}
        colors = _extract_colors(img)
        if not colors:
            self.report({"WARNING"}, "没提出颜色来，这图是不是全透明")
            return {"CANCELLED"}
        name = os.path.splitext(os.path.basename(self.filepath))[0] + "_色卡"
        pal = _make_palette(name, colors)
        errors = _assign_palette(context, pal)
        if errors:
            self.report({"WARNING"},
                        f"「{pal.name}」生成了但没挂上绘画工具({'; '.join(errors)})，去调色板列表手动选一下")
        else:
            self.report({"INFO"}, f"「{pal.name}」{len(colors)} 色已就位，画贴图的调色板里直接点")
        _auto_open_float()
        _tag_redraw()
        return {"FINISHED"}


class POND_OT_palette_from_image(bpy.types.Operator):
    """把已加载的图片（比如贴图/参考图）提取成调色板"""
    bl_idname = "pond.palette_from_image"
    bl_label = "从已有图提取"

    image_name: bpy.props.EnumProperty(
        name="图片",
        items=lambda self, ctx: [(im.name, im.name, "") for im in bpy.data.images
                                 if im.size[0] > 0] or [("NONE", "没有可用图片", "")])

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        img = bpy.data.images.get(self.image_name)
        if not img or img.size[0] == 0:
            self.report({"WARNING"}, "没选到有效图片")
            return {"CANCELLED"}
        colors = _extract_colors(img)
        if not colors:
            self.report({"WARNING"}, "没提出颜色来")
            return {"CANCELLED"}
        pal = _make_palette(img.name + "_色卡", colors)
        errors = _assign_palette(context, pal)
        if errors:
            self.report({"WARNING"},
                        f"「{pal.name}」生成了但没挂上绘画工具({'; '.join(errors)})")
        else:
            self.report({"INFO"}, f"「{pal.name}」{len(colors)} 色已就位")
        _auto_open_float()
        _tag_redraw()
        return {"FINISHED"}


_classes = (
    POND_OT_palette_from_file,
    POND_OT_palette_from_image,
    POND_OT_palette_float,
    POND_OT_palette_delete,
    POND_OT_palette_clear_all,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    _float["on"] = False
    _remove_float_handle()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
