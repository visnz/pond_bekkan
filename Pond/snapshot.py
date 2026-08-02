# 视口快照对比 v2 —— 引擎参考 Buck 的 Render View Compare
# 关键改法：快照直接读帧缓冲(屏幕最终像素)存显存纹理，画回去用同一套编解码着色器，
# 读写对称，色彩管理(含 ACES)插不上手 —— 老版本"存Image再画"的偏色路线废弃
# 对比 = A/B 刮开：拖视口里的竖线；Alt+右键整屏切换的老手感保留
# 快照只活在本次 Blender 会话里（显存纹理不落盘），关软件即清空
import time
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from . import prefs

_snaps = {}            # key -> {"tex": GPUTexture, "w": int, "h": int}
_next_id = [1]
_draw_handler = None
_overlay_restore = None
_last_error = ""
_shader = None
_line_shader = None
_split_running = [False]

_VERT = """
void main()
{
    uv = texCoord;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FRAG = """
vec3 srgb_to_linear(vec3 c)
{
    vec3 lo = c / 12.92;
    vec3 hi = pow(max((c + 0.055) / 1.055, vec3(0.0)), vec3(2.4));
    return mix(hi, lo, lessThanEqual(c, vec3(0.04045)));
}

void main()
{
    vec4 color = texture(image, uv);
    color.rgb = srgb_to_linear(max(color.rgb, vec3(0.0)));
    fragColor = color;
}
"""

_LINE_VERT = """
void main()
{
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_LINE_FRAG = """
void main()
{
    fragColor = color;
}
"""


def _get_shader():
    global _shader
    if _shader is None:
        interface = gpu.types.GPUStageInterfaceInfo("pond_snap_compare")
        interface.smooth("VEC2", "uv")
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC2", "pos")
        info.vertex_in(1, "VEC2", "texCoord")
        info.vertex_out(interface)
        info.fragment_out(0, "VEC4", "fragColor")
        info.sampler(0, "FLOAT_2D", "image")
        info.vertex_source(_VERT)
        info.fragment_source(_FRAG)
        _shader = gpu.shader.create_from_info(info)
    return _shader


def _get_line_shader():
    global _line_shader
    if _line_shader is None:
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, "VEC2", "pos")
        info.fragment_out(0, "VEC4", "fragColor")
        info.push_constant("VEC4", "color")
        info.vertex_source(_LINE_VERT)
        info.fragment_source(_LINE_FRAG)
        _line_shader = gpu.shader.create_from_info(info)
    return _line_shader


def _clip(width, height, x, y):
    return (x / width) * 2.0 - 1.0, (y / height) * 2.0 - 1.0


class PondSnapItem(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()
    image_name: bpy.props.StringProperty()   # _snaps 的 key


def _current_snap(wm):
    items = wm.pond_snap_items
    idx = wm.pond_snap_index
    if not (0 <= idx < len(items)):
        return None
    return _snaps.get(items[idx].image_name)


def _draw_overlay():
    global _last_error
    ctx = bpy.context
    wm = ctx.window_manager
    if not wm.pond_snap_show:
        return
    rec = _current_snap(wm)
    if rec is None:
        return
    try:
        vp = gpu.state.active_framebuffer_get().viewport_get()
        width, height = int(vp[2]), int(vp[3])
        if width <= 0 or height <= 0:
            return
        split = max(0.0, min(1.0, wm.pond_snap_split))
        x0 = width * split
        verts = [_clip(width, height, x0, 0), _clip(width, height, width, 0),
                 _clip(width, height, width, height), _clip(width, height, x0, height)]
        coords = [(split, 0.0), (1.0, 0.0), (1.0, 1.0), (split, 1.0)]
        shader = _get_shader()
        batch = batch_for_shader(shader, "TRIS",
                                 {"pos": verts, "texCoord": coords},
                                 indices=[(0, 1, 2), (0, 2, 3)])
        gpu.state.blend_set("NONE")
        gpu.state.depth_test_set("NONE")
        shader.bind()
        shader.uniform_sampler("image", rec["tex"])
        batch.draw(shader)
        if split > 0.002:
            ls = _get_line_shader()
            th = 1.25
            lx0, lx1 = x0 - th * 0.5, x0 + th * 0.5
            lverts = [_clip(width, height, lx0, 0), _clip(width, height, lx1, 0),
                      _clip(width, height, lx1, height), _clip(width, height, lx0, height)]
            lb = batch_for_shader(ls, "TRIS", {"pos": lverts},
                                  indices=[(0, 1, 2), (0, 2, 3)])
            gpu.state.blend_set("ALPHA")
            ls.bind()
            ls.uniform_float("color", (1.0, 1.0, 1.0, 0.85))
            lb.draw(ls)
            gpu.state.blend_set("NONE")
        # 角标: 右上角写明正在比的是哪张快照
        try:
            label = "快照 " + items[idx].label
            blf.size(0, 13)
            tw, _th = blf.dimensions(0, label)
            bx = min(width - tw - 10, max(width * split + 10, 10))
            blf.position(0, bx, height - 26, 0)
            blf.color(0, 0.1, 0.1, 0.1, 0.9)
            blf.draw(0, label)
            blf.position(0, bx - 1, height - 25, 0)
            blf.color(0, 1.0, 1.0, 1.0, 0.95)
            blf.draw(0, label)
        except Exception:
            pass
        _last_error = ""
    except Exception as e:
        _last_error = str(e)
        print("池塘快照对比绘制失败:", e)


def _ensure_handler(on):
    global _draw_handler
    if on and _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_overlay, (), "WINDOW", "POST_PIXEL")
    elif not on and _draw_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, "WINDOW")
        _draw_handler = None


def _redraw_all(context):
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def _update_split(self, context):
    _redraw_all(context)


def _stop_compare(wm):
    global _overlay_restore
    wm.pond_snap_show = False
    _ensure_handler(False)
    if _overlay_restore is not None:
        try:
            _overlay_restore.overlay.show_overlays = False
        except Exception:
            pass
        _overlay_restore = None


class POND_OT_snap_take(bpy.types.Operator):
    """拍一张当前视口快照存进对比列表（Ctrl+Alt+右键）"""
    bl_idname = "pond.snap_take"
    bl_label = "拍快照"

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == "VIEW_3D"

    def execute(self, context):
        area = context.area
        region = context.region
        if region is None or region.type != "WINDOW":
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
        space = context.space_data
        rv3d = getattr(space, "region_3d", None)
        if region is None or rv3d is None:
            self.report({"ERROR"}, "找不到视口")
            return {"CANCELLED"}
        w, h = int(region.width), int(region.height)
        # 离屏重画当前视口：SOLID/材质/Eevee 都拿得到画面；比读帧缓冲稳
        try:
            off = gpu.types.GPUOffScreen(w, h, format="RGBA32F")
            with context.temp_override(area=area, region=region, space_data=space):
                off.draw_view3d(
                    context.scene, context.view_layer, space, region,
                    rv3d.view_matrix, rv3d.window_matrix,
                    do_color_management=True)
            buf = off.texture_color.read()
            buf.dimensions = w * h * 4
            tex = gpu.types.GPUTexture((w, h), format="RGBA32F", data=buf)
            off.free()
        except Exception as e:
            self.report({"ERROR"}, f"快照没拍成: {e}")
            return {"CANCELLED"}
        wm = context.window_manager
        key = "s%d" % _next_id[0]
        _next_id[0] += 1
        _snaps[key] = {"tex": tex, "w": w, "h": h}
        it = wm.pond_snap_items.add()
        it.label = time.strftime("%H:%M:%S")
        it.image_name = key
        wm.pond_snap_index = len(wm.pond_snap_items) - 1
        # r6 是版本印记：提示里没有它 = Blender 还在跑旧代码，重启
        self.report({"INFO"}, f"[r6] 快照 {it.label} 已存")
        return {"FINISHED"}


class POND_OT_snap_toggle(bpy.types.Operator):
    """开/关对比：竖线右边是快照、左边是现在，拖线刮开看（Alt+右键）"""
    bl_idname = "pond.snap_toggle"
    bl_label = "对比"

    @classmethod
    def poll(cls, context):
        return len(context.window_manager.pond_snap_items) > 0

    def execute(self, context):
        global _overlay_restore
        wm = context.window_manager
        if wm.pond_snap_show:
            _stop_compare(wm)
            _redraw_all(context)
            return {"FINISHED"}
        wm.pond_snap_show = True
        space = context.space_data
        # 叠加层总闸关着时绘制钩子不跑（Blender 规矩），临时打开、关对比时还原
        if space and space.type == "VIEW_3D" and not space.overlay.show_overlays:
            space.overlay.show_overlays = True
            _overlay_restore = space
        _ensure_handler(True)
        _redraw_all(context)
        if not _split_running[0]:
            try:
                bpy.ops.pond.snap_split("INVOKE_DEFAULT")
            except Exception:
                pass
        return {"FINISHED"}


class POND_OT_snap_split(bpy.types.Operator):
    """在视口里直接拖那条 A/B 分割线"""
    bl_idname = "pond.snap_split"
    bl_label = "拖分割线"

    _dragging = False

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return wm.pond_snap_show and len(wm.pond_snap_items) > 0

    def invoke(self, context, event):
        _split_running[0] = True
        self._dragging = False
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.pond_snap_show or not wm.pond_snap_items:
            _split_running[0] = False
            return {"FINISHED"}
        region = context.region
        if region is None:
            return {"PASS_THROUGH"}

        if self._dragging and event.type == "MOUSEMOVE":
            wm.pond_snap_split = max(0.0, min(1.0, event.mouse_region_x / max(1, region.width)))
            _redraw_all(context)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            if abs(event.mouse_region_x - region.width * wm.pond_snap_split) <= 14.0:
                self._dragging = True
                wm.pond_snap_split = max(0.0, min(1.0, event.mouse_region_x / max(1, region.width)))
                _redraw_all(context)
                return {"RUNNING_MODAL"}

        if self._dragging and event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._dragging = False
            return {"RUNNING_MODAL"}

        if self._dragging and event.type in {"ESC", "RIGHTMOUSE"}:
            self._dragging = False
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


class POND_OT_snap_delete(bpy.types.Operator):
    """删掉选中的快照"""
    bl_idname = "pond.snap_delete"
    bl_label = "删除快照"

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return 0 <= wm.pond_snap_index < len(wm.pond_snap_items)

    def execute(self, context):
        wm = context.window_manager
        it = wm.pond_snap_items[wm.pond_snap_index]
        _snaps.pop(it.image_name, None)
        wm.pond_snap_items.remove(wm.pond_snap_index)
        wm.pond_snap_index = min(wm.pond_snap_index, len(wm.pond_snap_items) - 1)
        if not wm.pond_snap_items and wm.pond_snap_show:
            _stop_compare(wm)
        _redraw_all(context)
        return {"FINISHED"}


class POND_OT_snap_export(bpy.types.Operator):
    """把选中的快照导成图像数据块（图像编辑器里选「池塘快照导出」查看）"""
    bl_idname = "pond.snap_export"
    bl_label = "导出选中快照看真身"

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return 0 <= wm.pond_snap_index < len(wm.pond_snap_items)

    def execute(self, context):
        wm = context.window_manager
        it = wm.pond_snap_items[wm.pond_snap_index]
        rec = _snaps.get(it.image_name)
        if rec is None:
            self.report({"ERROR"}, "这张快照的纹理不在了")
            return {"CANCELLED"}
        try:
            buf = rec["tex"].read()
            buf.dimensions = rec["w"] * rec["h"] * 4
        except Exception as e:
            self.report({"ERROR"}, f"纹理读不回来: {e}")
            return {"CANCELLED"}
        name = "池塘快照导出"
        img = bpy.data.images.get(name)
        if img and tuple(img.size) != (rec["w"], rec["h"]):
            bpy.data.images.remove(img)
            img = None
        if img is None:
            img = bpy.data.images.new(name, rec["w"], rec["h"], alpha=False, float_buffer=True)
        for cs in ("Non-Color", "Raw"):
            try:
                img.colorspace_settings.name = cs
                break
            except Exception:
                continue
        img.pixels.foreach_set(buf)
        self.report({"INFO"}, f"已导出为图像「{name}」({it.label})，去图像编辑器里看")
        return {"FINISHED"}


class POND_UL_snaps(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop):
        layout.label(text=item.label, icon="IMAGE_DATA")


class POND_PT_snapshot(bpy.types.Panel):
    bl_label = "快照对比"
    bl_idname = "POND_PT_snapshot"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_snapshot")

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout
        row = layout.row(align=True)
        row.operator("pond.snap_take", icon="RESTRICT_RENDER_OFF")
        row.operator("pond.snap_toggle", icon="ARROW_LEFTRIGHT",
                     depress=wm.pond_snap_show)
        if wm.pond_snap_show:
            layout.prop(wm, "pond_snap_split", text="分割线")
            layout.label(text="线右边是快照，拖线刮开看", icon="INFO")
        if wm.pond_snap_items:
            row = layout.row()
            row.template_list("POND_UL_snaps", "", wm, "pond_snap_items",
                              wm, "pond_snap_index", rows=3)
            col = row.column(align=True)
            col.operator("pond.snap_delete", text="", icon="REMOVE")
            col.operator("pond.snap_export", text="", icon="IMAGE_DATA")
            layout.label(text="快照存在显存里，关 Blender 就没了", icon="INFO")
        if _last_error:
            layout.label(text=f"绘制失败：{_last_error[:60]}", icon="ERROR")


_classes = (
    PondSnapItem,
    POND_OT_snap_take,
    POND_OT_snap_toggle,
    POND_OT_snap_split,
    POND_OT_snap_delete,
    POND_OT_snap_export,
    POND_UL_snaps,
    POND_PT_snapshot,
)


_keymaps = []


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.pond_snap_items = bpy.props.CollectionProperty(type=PondSnapItem)
    bpy.types.WindowManager.pond_snap_index = bpy.props.IntProperty(default=0, update=_update_split)
    bpy.types.WindowManager.pond_snap_show = bpy.props.BoolProperty(default=False)
    bpy.types.WindowManager.pond_snap_split = bpy.props.FloatProperty(
        name="分割线", default=0.5, min=0.0, max=1.0, subtype="FACTOR",
        update=_update_split)
    # 快捷键照她的手感来：Ctrl+Alt+右键拍，Alt+右键切对比
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        _keymaps.append((km, km.keymap_items.new(
            "pond.snap_take", "RIGHTMOUSE", "PRESS", ctrl=True, alt=True)))
        _keymaps.append((km, km.keymap_items.new(
            "pond.snap_toggle", "RIGHTMOUSE", "PRESS", alt=True)))


def unregister():
    global _shader, _line_shader
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    _ensure_handler(False)
    _snaps.clear()
    _shader = None
    _line_shader = None
    _split_running[0] = False
    del bpy.types.WindowManager.pond_snap_split
    del bpy.types.WindowManager.pond_snap_show
    del bpy.types.WindowManager.pond_snap_index
    del bpy.types.WindowManager.pond_snap_items
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
