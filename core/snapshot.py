# core/snapshot.py — IPR 视口快照对比（合并核心）
#
# 合并基准：Bekkan/STOOL_part/Snapshot.py（桶桶已 debug 的版本）。
# 相比 Pond 旧复制版的优势：逐窗口独立快照（area_id）、RGBA8 纹理（显存 1/4）、
# 画回前 sRGB 预解码校准（5.2 实测 1 LSB 无损）、load_post 自动清理失效纹理。
# 移植自 Pond 的新增：DeleteSnap（删除选中）、ExportSnap（导出为图像数据块）。
# 已删除：4.x 兼容分支与旧 GLSL（合并后整体锁定 Blender 5.2）。
#
# GPU 资源全用「每次启动重新惰性初始化」的模式：
#   - shader / draw handler 只放模块级变量，启动时必是 None
#   - 首次用到时现建，blender --background --python 下取不到 context 也能 import
#
# 色彩链路标定记录（5.2，2026-08-01 实机测试通过）：
#   - 5.x draw_view3d 已直出显示编码 sRGB 字节（视图变换/Filmic 已烘进去）。
#   - 存「显示编码字节」到 RGBA8 纹理，画回前在 shader 里 srgb_to_linear 预解码，
#     硬件再做 encode，round-trip 实测 1 LSB 无损。
#   - 将来要支持 5.0/5.1 时把 _DRAW_DECODE_SRGB 关成 False 即可（那时 draw_view3d
#     出的是线性场景参考色，预解码恰好校正了硬件 encode）。
import time
import bpy
import gpu
import gpu_extras.presets
import blf
import numpy as np
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import location_3d_to_region_2d

# 画回 shader 是否做 sRGB 预解码（校准开关，见文件头标定记录）
_DRAW_DECODE_SRGB = True

# ---- 5.x shader 源码（GPUShaderCreateInfo 路线；pos 为 CPU 侧换算的 NDC）----
_VERT5 = """
void main()
{
    texCoordInterp = texCoord;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FRAG5_DECODE = """
void main()
{
    vec4 c = texture(image, texCoordInterp);
    if(decode > 0.5) c.rgb = pow(max(c.rgb, vec3(0.0)), vec3(2.2));
    fragColor = c;
}
"""

_SHADER = None
_LINE_SHADER = None

_snaps = {}        # key -> {"tex": GPUTexture, "w": int, "h": int, "label": str}
_next_id = [1]     # 列表包一层，避免函数内 global 声明
disp_snap = {}     # area_id -> key（存在即显示）
draw_hdl = {}      # area_id -> 绘制句柄


def _get_shader():
    """延迟初始化主 shader，确保 Blender 上下文已就绪"""
    global _SHADER
    if _SHADER is None:
        try:
            interface = gpu.types.GPUStageInterfaceInfo("bekkan_snap")
            interface.smooth("VEC2", "texCoordInterp")
            info = gpu.types.GPUShaderCreateInfo()
            info.vertex_in(0, "VEC2", "pos")
            info.vertex_in(1, "VEC2", "texCoord")
            info.vertex_out(interface)
            info.fragment_out(0, "VEC4", "fragColor")
            info.sampler(0, "FLOAT_2D", "image")
            info.push_constant("FLOAT", "decode")
            info.vertex_source(_VERT5)
            info.fragment_source(_FRAG5_DECODE)
            _SHADER = gpu.shader.create_from_info(info)
        except Exception:
            print("Warning: snapshot shader initialization failed")
    return _SHADER


def _get_line_shader():
    """延迟初始化分割线 shader"""
    global _LINE_SHADER
    if _LINE_SHADER is None:
        try:
            _LINE_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
        except Exception:
            print("Warning: UNIFORM_COLOR shader initialization failed")
    return _LINE_SHADER


def _ndc(rw, rh, x, y):
    """像素坐标 -> NDC（5.x 无 gpu.matrix 可取矩阵，CPU 侧换算）"""
    return (x / rw) * 2.0 - 1.0, (y / rh) * 2.0 - 1.0


def _aid(area):
    """3D 视图窗口 ID（每个窗口独立保存一组快照）"""
    return str(hash(area.as_pointer()) % 10000).zfill(4)


def _rm_handler(area_id):
    """安全移除绘制句柄：区域被合并/关闭后句柄已失效，忽略 ReferenceError"""
    h = draw_hdl.get(area_id)
    if h:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
        except ReferenceError:
            pass
    draw_hdl[area_id] = None


def _ensure_handler(area_id):
    """确保指定窗口的绘制句柄存在"""
    if draw_hdl.get(area_id):
        return
    draw_hdl[area_id] = bpy.types.SpaceView3D.draw_handler_add(
        _draw, (area_id,), "WINDOW", "POST_PIXEL")


def _free_res(area_id):
    """关闭某窗口的快照显示：移除绘制句柄并清除显示记录"""
    _rm_handler(area_id)
    disp_snap.pop(area_id, None)


def _srgb_encode(rgb):
    """sRGB 编码（标准分段曲线）。Snapshot 本体已不再使用，
    保留给 tools/test_snap_visual.py 做色彩链路标定"""
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)


def _srgb_decode(rgb):
    """sRGB 解码（标准分段曲线），导出图像数据块时把显示值换回 scene-linear"""
    return np.where(rgb <= 0.04045, rgb / 12.92, np.power((rgb + 0.055) / 1.055, 2.4))


def _passepartout_mask(context, space, region, rv3d):
    """算出当前摄像机遮罩需要压黑的矩形（region 像素坐标）与透明度。

    不在摄像机视角/摄像机没开遮罩/取景框投影失败时返回 None（不遮罩，维持原样）。
    取景框算法：camera.view_frame 拿本地空间 4 角点 -> matrix_world 变换到世界坐标
    -> location_3d_to_region_2d 投影到 region 像素坐标，取 min/max 即矩形，自动适配
    Sensor Fit 造成的 letterbox/pillarbox。
    """
    if getattr(rv3d, "view_perspective", None) != "CAMERA":
        return None
    cam_obj = space.camera if getattr(space, "use_local_camera", False) else context.scene.camera
    if cam_obj is None or cam_obj.data is None or not getattr(cam_obj.data, "show_passepartout", False):
        return None
    try:
        frame = cam_obj.data.view_frame(scene=context.scene)
        mat = cam_obj.matrix_world
        pts = [location_3d_to_region_2d(region, rv3d, mat @ corner) for corner in frame]
        if any(p is None for p in pts):
            return None
    except Exception:
        return None
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    x0 = max(0, min(region.width, round(min(xs))))
    x1 = max(0, min(region.width, round(max(xs))))
    y0 = max(0, min(region.height, round(min(ys))))
    y1 = max(0, min(region.height, round(max(ys))))
    return x0, y0, x1, y1, cam_obj.data.passepartout_alpha


def _capture_offscreen(context, area, space, region):
    """离屏重画当前视口并转为 RGBA8 纹理。
    draw_view3d 一次同步渲出全部采样（EEVEE 无采样竞态，比旧延时截图更可靠）；
    do_color_management=True 的 float 输出只含视图变换、不含最终 EOTF（5.2 实测：
    捕获值 C = srgb_dec(屏幕字节 D)），存储语义与渲染 PNG 加载后的线性像素一致，
    画回侧的预解码（_DRAW_DECODE_SRGB）以此为基准。面板等 region UI 天然不入镜。
    摄像机遮罩（Passepartout）是交互视口另外画的 2D 引导层，draw_view3d 不会带出来，
    这里额外读一次遮罩矩形手动压黑做后处理补上。大场景拍摄会同步阻塞，属预期"""
    w, h = int(region.width), int(region.height)
    rv3d = space.region_3d
    # 离屏必须 RGBA32F：其 read() 返回 FLOAT Buffer，可直接喂 GPUTexture
    off = gpu.types.GPUOffScreen(w, h, format="RGBA32F")
    try:
        with context.temp_override(area=area, region=region, space_data=space):
            off.draw_view3d(context.scene, context.view_layer, space, region,
                            rv3d.view_matrix, rv3d.window_matrix,
                            do_color_management=True)
        buf = off.texture_color.read()
        buf.dimensions = w * h * 4
        mask = _passepartout_mask(context, space, region, rv3d)
        if mask is not None:
            x0, y0, x1, y1, alpha = mask
            arr = np.array(buf, dtype=np.float32).reshape(h, w, 4)
            keep = np.zeros((h, w), dtype=bool)
            keep[y0:y1, x0:x1] = True
            arr[~keep, :3] *= (1.0 - alpha)
            buf = gpu.types.Buffer("FLOAT", w * h * 4, arr)
        tex = gpu.types.GPUTexture((w, h), format="RGBA8", data=buf)  # 内部量化
    finally:
        off.free()  # GPUOffScreen 必须显式释放；GPUTexture 无 free()，靠解除引用 + GC
    return tex, w, h


def _finish_capture(scene, area, area_id, tex, w, h):
    """拍摄成功后的公共收尾：登记纹理与快照列表、切换显示、刷新窗口"""
    key = "s%d" % _next_id[0]
    _next_id[0] += 1
    # 序号（三位数占位）+ 拍摄时间点，如 "001 14:30:52"
    label = "%03d %s" % (len(scene.snapshot_list) + 1, time.strftime("%H:%M:%S"))
    _snaps[key] = {"tex": tex, "w": w, "h": h, "label": label}
    item = scene.snapshot_list.add()
    item.name, item.area_id, item.key = label, area_id, key
    scene.snapshot_list_index = len(scene.snapshot_list) - 1
    disp_snap[area_id] = key
    _ensure_handler(area_id)
    for r in area.regions:
        if r.type == "WINDOW":
            r.tag_redraw()


def _draw(area_id):
    """POST_PIXEL 绘制：快照在分割线右侧，左侧为实景"""
    cur_area = bpy.context.area
    if not cur_area or _aid(cur_area) != area_id:
        return
    rec = _snaps.get(disp_snap.get(area_id))
    if rec is None:
        return
    sh = _get_shader()
    if sh is None:
        return
    try:
        scene = bpy.context.scene
        region = next(r for r in cur_area.regions if r.type == "WINDOW")
        # 快照宽度与窗口宽度保持一致，高度按比例缩放并垂直居中（窗口尺寸变化适配）
        scale = region.width / rec["w"]
        w, h = rec["w"] * scale, rec["h"] * scale
        y = (region.height - h) / 2
        p = scene.slider_position / 100.0
        x0 = w * p  # 分割线位置 = 比例（0-100%），拖鼠标时线跟鼠标走；快照在线右侧

        rw, rh = region.width, region.height
        verts = [_ndc(rw, rh, x0, y), _ndc(rw, rh, w, y),
                 _ndc(rw, rh, w, y + h), _ndc(rw, rh, x0, y + h)]
        batch = batch_for_shader(
            sh, "TRI_FAN",
            {"pos": verts,
             "texCoord": ((p, 0), (1, 0), (1, 1), (p, 1))})
        # 显式关掉深度测试：POST_PIXEL 覆盖层必须永远盖在 3D 场景之上，
        # 不能假设上一步（比如 EEVEE 真实阴影管线）帮忙复原好了深度测试状态
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("ALPHA")
        sh.bind()
        sh.uniform_sampler("image", rec["tex"])
        sh.uniform_float("decode", 1.0 if _DRAW_DECODE_SRGB else 0.0)
        batch.draw(sh)
        gpu.state.blend_set("NONE")

        # 绘制分割线
        ls = _get_line_shader()
        if ls:
            lverts = [(x0, y, 0), (x0, y + h, 0)]
            line_batch = batch_for_shader(ls, "LINES", {"pos": lverts})
            gpu.state.blend_set("ALPHA")
            ls.bind()
            ls.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
            line_batch.draw(ls)
            gpu.state.blend_set("NONE")

        # 角标：快照在线右侧，角标显示在右上角
        text = f"快照 {rec['label']}"
        blf.size(0, 13)
        tw, _ = blf.dimensions(0, text)
        bx, by = region.width - tw - 10, region.height - 26
        blf.position(0, bx - 1, by - 1, 0)
        blf.color(0, 0.1, 0.1, 0.1, 0.9)
        blf.draw(0, text)
        blf.position(0, bx, by, 0)
        blf.color(0, 1.0, 1.0, 1.0, 0.95)
        blf.draw(0, text)
    except Exception as e:
        print("快照对比绘制失败:", e)


def _redraw_view3d(screen):
    for a in screen.areas:
        if a.type == "VIEW_3D":
            for r in a.regions:
                if r.type == "WINDOW":
                    r.tag_redraw()


@persistent
def _reset_on_load(_dummy=None):
    """打开/新建工程后区域与纹理全部失效：移除句柄、清空记录；
    快照列表随 .blend 持久化但显存纹理不跨会话，必须逐场景同步清空"""
    for area_id in list(draw_hdl):
        _rm_handler(area_id)
    _snaps.clear()
    disp_snap.clear()
    draw_hdl.clear()
    for sc in bpy.data.scenes:
        try:
            sc.snapshot_list.clear()
            sc.snapshot_list_index = -1
        except (AttributeError, ReferenceError):
            pass
    # 重画 UI，让列表跟着新文件状态
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class SnapItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    area_id: bpy.props.StringProperty()
    key: bpy.props.StringProperty()  # _snaps 的键


class TakeSnap(bpy.types.Operator):
    """拍摄当前 3D 视口快照"""
    bl_idname = "object.take_snapshot"
    bl_label = "拍摄快照"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def execute(self, context):
        area = context.area
        if area is None or area.type != "VIEW_3D":
            self.report({"WARNING"}, "请在3D视口中使用")
            return {"CANCELLED"}
        space = context.space_data
        scene = context.scene
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is None or getattr(space, "region_3d", None) is None:
            self.report({"ERROR"}, "找不到视口")
            return {"CANCELLED"}
        area_id = _aid(area)
        # 拍摄期间摘下本窗口的显示标志：若离屏重画触发 Python 绘制回调，防止旧叠加被拍进新快照；
        # 失败时回滚。op 内不写任何 RNA，旧版「undo 推入撤销 show_region_*」的崩溃面整体消失
        prev = disp_snap.pop(area_id, None)
        try:
            tex, w, h = _capture_offscreen(context, area, space, region)
        except Exception as e:
            if prev is not None:
                disp_snap[area_id] = prev
            self.report({"ERROR"}, f"快照没拍成: {e}")
            return {"CANCELLED"}
        _finish_capture(scene, area, area_id, tex, w, h)
        self.report({"INFO"}, f"快照 {scene.snapshot_list[-1].name} 已存")
        return {"FINISHED"}


class ToggleSnap(bpy.types.Operator):
    """显示/隐藏快照对比"""
    bl_idname = "object.toggle_snapshot_display"
    bl_label = "对比开关"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def execute(self, context):
        area = context.area
        if area is None or area.type != "VIEW_3D":
            self.report({"WARNING"}, "请在3D视口中使用")
            return {"CANCELLED"}
        area_id = _aid(area)
        if area_id in disp_snap:
            _free_res(area_id)
        else:
            i = context.scene.snapshot_list_index
            if 0 <= i < len(context.scene.snapshot_list):
                item = context.scene.snapshot_list[i]
                if item.key in _snaps and item.area_id == area_id:
                    disp_snap[area_id] = item.key
                    _ensure_handler(area_id)
                    self.report({"INFO"}, f"显示快照 {item.name}")
                else:
                    self.report({"WARNING"}, "这条快照的纹理已经不在了")
                    return {"CANCELLED"}
            else:
                self.report({"WARNING"}, "先拍一张快照")
                return {"CANCELLED"}
        _redraw_view3d(context.screen)
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
        _redraw_view3d(context.screen)
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
        # 从 _snaps 中移除纹理引用（GPUTexture 无 free()，靠解除引用 + GC）
        if item.key in _snaps:
            del _snaps[item.key]
        # 如果正在显示，关闭显示
        if disp_snap.get(area_id) == item.key:
            _free_res(area_id)
        scn.snapshot_list.remove(idx)
        scn.snapshot_list_index = min(idx, len(scn.snapshot_list) - 1)
        _redraw_view3d(context.screen)
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
        rec = _snaps.get(item.key)
        if not rec:
            self.report({"WARNING"}, "这条快照的纹理已经不在了（可能换过工程）")
            return {"CANCELLED"}
        buf = rec["tex"].read()  # RGBA8 → UBYTE buffer
        try:
            data = np.frombuffer(buf, dtype=np.uint8).astype(np.float32) / 255.0
        except Exception:
            data = np.array(list(buf), dtype=np.float32) / 255.0
        w, h = rec["w"], rec["h"]
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
            region = context.region
            if region and region.type == "WINDOW":
                x = event.mouse_region_x
                context.scene.slider_position = max(
                    0.0, min(100.0, 100.0 * x / region.width))
            _redraw_view3d(context.screen)
            return {"RUNNING_MODAL"}
        if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "PRESS":
            return {"FINISHED"}
        if event.type == "ESC":
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        if not context.area or context.area.type != "VIEW_3D":
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}


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
    for area_id in list(draw_hdl):
        _rm_handler(area_id)
    draw_hdl.clear()
    _snaps.clear()
    disp_snap.clear()
    del bpy.types.Scene.snap_expanded
    del bpy.types.Scene.snapshot_list_index
    del bpy.types.Scene.snapshot_list
    del bpy.types.Scene.slider_position
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


# ============================================================================
# 【保留待议 · 决策点5】Pond 版快照的交互实现（点分割线附近直接拖、快照在线右）
# 当前合并核心统一用 Bekkan 交互（快照在线左、Alt+右键任意处拖）。
# 若蛙灾日后觉得不合适，再启用以下实现或做两个模式两套交互。
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
