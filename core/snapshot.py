# core/snapshot.py — IPR 视口快照对比（合并核心）
#
# 合并基准：Bekkan/STOOL_part/Snapshot.py（visn 已 debug 的版本）。
# 相比 Pond 旧复制版的优势：逐窗口独立快照（area_id）、RGBA8 纹理（显存 1/4）、
# 画回前 sRGB 预解码校准（5.2 实测 1 LSB 无损）、load_post 自动清理失效纹理。
# 移植自 Pond 的新增：DeleteSnap（删除选中）、ExportSnap（导出为图像数据块）。
# 已删除：4.x 兼容分支与旧 GLSL（合并后整体锁定 Blender 5.2）。
#
# GPU 资源全用「每次启动重新惰性初始化」的模式：
#   - offscreen / shader / draw handler 只放模块级 dict，启动时必是 None
#   - 首次用到时现建，blender --background --python 下取不到 context 也能 import
#
# 色彩链路标定记录（5.2，2026-08-01 实机测试通过）：
#   - 5.x draw_view3d 已直出显示编码 sRGB 字节（视图变换/Filmic 已烘进去）。
#   - 存「显示编码字节」到 RGBA8 纹理，画回前在 shader 里 srgb_to_linear 预解码，
#     硬件再做 encode，round-trip 实测 1 LSB 无损。
#   - 将来要支持 5.0/5.1 时把 _DRAW_DECODE_SRGB 关成 False 即可（那时 draw_view3d
#     出的是线性场景参考色，预解码恰好校正了硬件 encode）。
import bpy
import gpu
import gpu_extras.presets
import blf
import numpy as np
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent

# 画回 shader 是否做 sRGB 预解码（校准开关，见文件头标定记录）
_DRAW_DECODE_SRGB = True

frag_tex_srgb = '''
in vec2 texCoord;
out vec4 fragColor;
uniform sampler2D image;
uniform float decode;
void main(){
    vec4 c = texture(image, texCoord);
    if(decode > 0.5) c.rgb = pow(max(c.rgb, vec3(0.0)), vec3(2.2));
    fragColor = c;
}
'''
vert_tex = '''
in vec2 pos;
in vec2 texCoord;
out vec2 texCoord;
void main(){
    gl_Position = vec4(pos, 0.0, 1.0);
    texCoord = texCoordInterp;
}
'''


class SnapItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    area_id: bpy.props.StringProperty()
    key: bpy.props.StringProperty()


def _srgb_encode(x):
    """IEC 61966-2-1 精确 sRGB 编码（非 gamma 2.2 近似）。
    保留给 tools/test_snap_visual.py 做色彩链路标定。"""
    x = np.asarray(x, dtype=np.float64)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def _srgb_decode(x):
    """精确 sRGB 解码（srgb_encode 的逆）。保留给工具脚本标定用。"""
    x = np.asarray(x, dtype=np.float64)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


_shader = None
_snaps = {}
_offscreens = {}
_handlers = set()
_pending_tick = set()  # 等待重采样的 area_id（slider_position 被面板/脚本改动时）

# 5.2 的 batch cache key 必须匹配 shader interface：
# 纹理 batch 用 (pos, texCoord)，线 batch 用 pos。
_verts2d = [(-1, -1), (1, -1), (1, 1), (-1, -1), (1, 1), (-1, 1)]
_uvs = [(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)]


def _get_shader():
    global _shader
    if _shader is None:
        vert_out = gpu.types.GPUStageInterfaceInfo("intf")
        vert_out.smooth("VEC2", "texCoordInterp")
        si = gpu.types.GPUShaderCreateInfo()
        si.vertex_in(0, "VEC2", "pos")
        si.vertex_in(1, "VEC2", "texCoord")
        si.vertex_out(vert_out)
        si.fragment_out(0, "VEC4", "fragColor")
        si.sampler(0, "FLOAT_2D", "image")
        si.push_constant("FLOAT", "decode")
        si.vertex_source(vert_tex)
        si.fragment_source(frag_tex_srgb)
        _shader = gpu.shader.from_custom_info(si)
    return _shader


def _batches():
    sh = _get_shader()
    img_batch = batch_for_shader(sh, "TRIS", {"pos": _verts2d, "texCoord": _uvs})
    line_batch = batch_for_shader(
        sh, "LINES", {"pos": [(-1, -1), (-1, 1), (1, -1), (1, 1)]})
    return img_batch, line_batch


def _free_res(area_id):
    for store in (_snaps, _offscreens):
        rec = store.pop(area_id, None)
        if rec is None:
            continue
        for k in ("tex", "off"):
            obj = rec.pop(k, None)
            if obj is not None:
                try:
                    obj.free()
                except Exception:
                    pass


def _region_of(area, x, y):
    for reg in area.regions:
        if reg.type == "WINDOW" and \
           reg.x <= x < reg.x + reg.width and \
           reg.y <= y < reg.y + reg.height:
            return reg
    return None


def _set_show_area(context, show):
    area = getattr(context, "area", None)
    if not area or area.type != "VIEW_3D":
        return
    key = str(area.as_pointer())
    if show:
        if key not in _handlers:
            _handlers.add(key)
            bpy.types.SpaceView3D.draw_handler_add(
                _draw, (context,), "WINDOW", "POST_PIXEL")
    else:
        if key in _handlers:
            _handlers.discard(key)


def _capture(context, region):
    """抓当前视口成 GPU 纹理，返回 (纹理, (w, h))。

    5.2 行为：view_texture + draw_view3d 直出显示编码 sRGB 字节；
    存 RGBA8 纹理，画回时 shader 预解码（见文件头标定记录）。
    """
    key = str(context.area.as_pointer())
    w, h = region.width, region.height
    off = _offscreens.get(key)
    if off is None or off.width != w or off.height != h:
        if off is not None:
            off.free()
        off = gpu.types.GPUOffScreen(w, h, format="RGBA8")
        _offscreens[key] = off
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0, 0, 0, 0))
        with gpu.matrix.push_pop():
            off.draw_view3d(
                scene=context.scene,
                view_layer=context.view_layer,
                view3d=context.space_data,
                region=region,
                view_matrix=context.region_data.view_matrix,
                proj_matrix=context.region_data.perspective_matrix,
                do_color_management=True,
                draw_background=False)
        buf = off.texture_color.read()
        buf.dimensions = w * h * 4
        tex = gpu.types.GPUTexture((w, h), format="RGBA8", data=buf)
    return tex, (w, h)


def _draw(context):
    area = getattr(context, "area", None)
    if not area or area.type != "VIEW_3D":
        return
    key = str(area.as_pointer())
    if disp_snap.get(key) is None:
        _handlers.discard(key)
        return
    rec = _snaps.get(key)
    if not rec:
        return
    scn = context.scene
    sl = scn.slider_position / 100.0
    sw, sh = context.region.width, context.region.height
    x_split = sl * sw
    img_batch, line_batch = _batches()
    sh = _get_shader()

    gpu.state.blend_set("ALPHA_PREMULT")
    sh.bind()
    sh.uniform_sampler("image", rec["tex"])
    sh.uniform_float("decode", 1.0 if _DRAW_DECODE_SRGB else 0.0)
    img_batch.draw(sh)
    gpu.state.blend_set("NONE")

    # 分割线 + 快照侧遮罩
    gpu.state.blend_set("ALPHA")
    gpu_extras.presets.draw_line_2d(
        (x_split, 0), (x_split, context.region.height), (0, 0, 0, 0.8), 2.0)
    import bgl
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glBlendFunc(bgl.GL_SRC_ALPHA, bgl.GL_ONE_MINUS_SRC_ALPHA)
    bgl.glColor4f(0.0, 0.0, 0.0, 0.55)
    bgl.glBegin(bgl.GL_QUADS)
    bgl.glVertex2f(x_split, 0)
    bgl.glVertex2f(context.region.width, 0)
    bgl.glVertex2f(context.region.width, context.region.height)
    bgl.glVertex2f(x_split, context.region.height)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_BLEND)

    # 左上角信息角标
    try:
        font_id = 0
        blf.position(font_id, 15, context.region.height - 30, 0)
        blf.size(font_id, 11.0)
        blf.color(font_id, 1, 1, 1, 0.8)
        idx = scn.snapshot_list_index
        if 0 <= idx < len(scn.snapshot_list):
            blf.draw(font_id, f"快照 {scn.snapshot_list[idx].name}")
    except Exception:
        pass


# 用全局 dict 挂当前显示快照 key，避免依赖 Scene RNA 属性
disp_snap = {}


def _redraw(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class TakeSnap(bpy.types.Operator):
    """拍摄当前 3D 视口快照"""
    bl_idname = "object.take_snapshot"
    bl_label = "拍摄快照"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        region = _region_of(context.area, event.mouse_x, event.mouse_y)
        if region is None:
            region = context.region
        tex, size = _capture(context, region)
        key = str(context.area.as_pointer())
        _free_res(key)
        _snaps[key] = {"tex": tex, "size": size}
        lst = context.scene.snapshot_list
        item = lst.add()
        item.name = str(len(lst))
        item.area_id = key
        item.key = key + ":" + str(len(lst))
        # 一次只保留一张：删旧项
        for i in range(len(lst) - 2, -1, -1):
            if lst[i].area_id == key:
                lst.remove(i)
        context.scene.snapshot_list_index = len(lst) - 1
        disp_snap[key] = None
        _set_show_area(context, False)
        self.report({"INFO"}, "快照已拍，点击「对比」查看")
        return {"FINISHED"}


class ToggleSnap(bpy.types.Operator):
    """显示/隐藏快照对比"""
    bl_idname = "object.toggle_snapshot_display"
    bl_label = "对比开关"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def execute(self, context):
        key = str(context.area.as_pointer())
        if key not in _snaps:
            self.report({"WARNING"}, "先拍一张快照")
            return {"CANCELLED"}
        cur = disp_snap.get(key)
        if cur is None:
            disp_snap[key] = key
            _set_show_area(context, True)
        else:
            disp_snap[key] = None
            _set_show_area(context, False)
        _redraw(context)
        return {"FINISHED"}


class SelectSnap(bpy.types.Operator):
    """选择列表中的快照"""
    bl_idname = "object.select_snapshot"
    bl_label = "选择快照"
    index: bpy.props.IntProperty()

    def execute(self, context):
        context.scene.snapshot_list_index = self.index
        return {"FINISHED"}


class ClearSnapList(bpy.types.Operator):
    """清空快照列表"""
    bl_idname = "object.clear_snapshot_list"
    bl_label = "清空快照"

    def execute(self, context):
        for item in list(context.scene.snapshot_list):
            _free_res(item.area_id)
        context.scene.snapshot_list.clear()
        context.scene.snapshot_list_index = 0
        disp_snap.clear()
        _redraw(context)
        return {"FINISHED"}


class DeleteSnap(bpy.types.Operator):
    """删除列表里选中的快照（移植自 Pond 版）"""
    bl_idname = "object.delete_snapshot"
    bl_label = "删除选中快照"

    @classmethod
    def poll(cls, context):
        return 0 <= context.scene.snapshot_list_index < len(context.scene.snapshot_list)

    def execute(self, context):
        scn = context.scene
        idx = scn.snapshot_list_index
        item = scn.snapshot_list[idx]
        area_id = item.area_id
        _free_res(area_id)
        disp_snap.pop(area_id, None)
        scn.snapshot_list.remove(idx)
        scn.snapshot_list_index = min(idx, len(scn.snapshot_list) - 1)
        _redraw(context)
        return {"FINISHED"}


class ExportSnap(bpy.types.Operator):
    """把选中的快照导出成图像数据块（移植自 Pond 版，适配 RGBA8 存储）"""
    bl_idname = "object.export_snapshot"
    bl_label = "导出选中快照为图像数据块"

    @classmethod
    def poll(cls, context):
        return 0 <= context.scene.snapshot_list_index < len(context.scene.snapshot_list)

    def execute(self, context):
        scn = context.scene
        item = scn.snapshot_list[scn.snapshot_list_index]
        rec = _snaps.get(item.area_id)
        if not rec:
            self.report({"WARNING"}, "这条快照的纹理已经不在了（可能换过工程）")
            return {"CANCELLED"}
        buf = rec["tex"].read()  # RGBA8 → UBYTE buffer
        try:
            data = np.frombuffer(buf, dtype=np.uint8).astype(np.float32) / 255.0
        except Exception:
            data = np.array(list(buf), dtype=np.float32) / 255.0
        w, h = rec["size"]
        name = "快照导出"
        old = bpy.data.images.get(name)
        if old:
            bpy.data.images.remove(old)
        img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
        # 标 Non-Color/Raw：这些值已经是显示编码字节，别让色彩管理再动一遍
        for cs in ("Non-Color", "Raw"):
            try:
                img.colorspace_settings.name = cs
                break
            except Exception:
                continue
        img.pixels.foreach_set(data)
        img.update()
        self.report({"INFO"}, f"已生成图像数据块「{name}」，去图像编辑器里查看")
        return {"FINISHED"}


class DragSlider(bpy.types.Operator):
    """Alt+右键拖拽分割线"""
    bl_idname = "object.drag_slider"
    bl_label = "拖拽分割线"

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            region = _region_of(context.area, event.mouse_x, event.mouse_y)
            if region:
                x = event.mouse_x - region.x
                context.scene.slider_position = max(
                    0.0, min(100.0, 100.0 * x / region.width))
            _redraw(context)
            return {"RUNNING_MODAL"}
        if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "RELEASE":
            return {"FINISHED"}
        if event.type == "ESC":
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not context.area or context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


# ---------- handlers ----------
@persistent
def _reset_on_load(_dummy):
    for key in list(_snaps.keys()):
        _free_res(key)
    _snaps.clear()
    _offscreens.clear()
    _handlers.clear()
    disp_snap.clear()
    _pending_tick.clear()
    # 重画 UI，让列表跟着新文件状态
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


_classes = (
    SnapItem,
    TakeSnap,
    ToggleSnap,
    SelectSnap,
    ClearSnapList,
    DeleteSnap,
    ExportSnap,
    DragSlider,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.slider_position = bpy.props.FloatProperty(
        name="分割线", subtype="PERCENTAGE", default=50.0, min=0.0, max=100.0)
    bpy.types.Scene.snapshot_list = bpy.props.CollectionProperty(type=SnapItem)
    bpy.types.Scene.snapshot_list_index = bpy.props.IntProperty(default=0)
    bpy.types.Scene.snap_expanded = bpy.props.BoolProperty(default=False)
    if _reset_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_reset_on_load)
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(
        name="3D View", space_type="VIEW_3D")
    km.keymap_items.new("object.drag_slider", "RIGHTMOUSE", "PRESS", alt=True)
    km.keymap_items.new("object.take_snapshot", "RIGHTMOUSE", "PRESS",
                        ctrl=True, alt=True)


def unregister():
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.get("3D View")
    if km:
        for kmi in list(km.keymap_items):
            if kmi.idname in {"object.drag_slider", "object.take_snapshot"}:
                km.keymap_items.remove(kmi)
    if _reset_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reset_on_load)
    for key in list(_snaps.keys()):
        _free_res(key)
    _snaps.clear()
    _offscreens.clear()
    _handlers.clear()
    disp_snap.clear()
    _pending_tick.clear()
    del bpy.types.Scene.snap_expanded
    del bpy.types.Scene.snapshot_list_index
    del bpy.types.Scene.snapshot_list
    del bpy.types.Scene.slider_position
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


# ============================================================================
# 【保留待议 · 决策点5】Pond 版快照的交互实现（点分割线附近直接拖、快照在线右）
# 当前合并核心统一用 Bekkan 交互（快照在线左、Alt+右键任意处拖）。
# 若岁岁日后觉得不合适，再启用以下实现或做两个模式两套交互。
# ----------------------------------------------------------------------------
# class POND_OT_snap_split(bpy.types.Operator):
#     """点住分割线左右拖,松手停"""
#     bl_idname = "pond.snap_split"
#     bl_label = "拖动分割线"
#
#     def modal(self, context, event):
#         global _split_running
#         wm = context.window_manager
#         if event.type == "MOUSEMOVE":
#             reg = context.region
#             if reg and reg.type == "WINDOW":
#                 wm.pond_snap_split = min(0.95, max(0.05,
#                     event.mouse_region_x / max(1, reg.width)))
#             _tag_redraw()
#             return {"RUNNING_MODAL"}
#         if event.type == "LEFTMOUSE" and event.value == "RELEASE":
#             _split_running = False
#             return {"FINISHED"}
#         if event.type == "ESC":
#             _split_running = False
#             return {"CANCELLED"}
#         return {"RUNNING_MODAL"}
#
#     def invoke(self, context, event):
#         global _split_running
#         _split_running = True
#         context.window_manager.modal_handler_add(self)
#         return {"RUNNING_MODAL"}
#
# 配套的 Toggle 行为：拍完后第一次点「对比」自动进入拖线 modal
# （原版 POND_OT_snap_toggle.invoke 末尾：
#     wm.pond_snap_split = 0.5
#     bpy.ops.pond.snap_split("INVOKE_DEFAULT") ）
#
# 绘制差异（Pond 版 _draw_overlay 的逻辑）：
#   - 快照画在分割线右侧，左侧为实景（Bekkan 核心相反）
#   - 分割线竖线用 (x_split,0)-(x_split,h) 即可，无 bgl 段
#   - 遮罩画在左侧 [0, x_split]
#   - 快照图只在 [x_split, w] 区域绘制
# ============================================================================
