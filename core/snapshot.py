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


def _capture_screenshot(context, area, region):
    """截图路径：Cycles 等渐进采样引擎的视口此刻已经在正常显示流程里收敛好了，
    没必要重新渲染——用 Blender 自带的 screen.screenshot_area 把当前区域此刻
    显示的真实像素存成临时文件再读回来。这是唯一被实测证实能看到 Cycles 真实
    收敛结果的路径：POST_PIXEL 回调里 gpu.state.active_framebuffer_get() 读到的
    不是 Cycles 合成的目标，实测永远是黑图（Cycles 疑似走另一条 GPU 合成路径，
    不经过标准视口 FBO），而 screenshot_area 直接读窗口/编辑器实际显示内容，
    经用户实测确认截出来的画面是正常的。见
    开发计划/2026-08-19_Cycles视口快照黑屏修复.md。

    screenshot_area 截的是整个 area（含标题栏/工具栏/N 面板），必须按 region
    相对 area 的像素偏移裁剪出纯 3D 视口内容；额外按截图实际像素数 / area 逻辑
    尺寸算一个缩放系数，防止 HiDPI/系统缩放下两者不是 1:1（未实测验证过这一步，
    缩放为 1 时等价于不做任何变换）。

    注意：这里不主动触发任何重绘（不调用 wm.redraw_timer）。实测过
    'DRAW_WIN_SWAP'（窗口级）和 'DRAW_SWAP'（区域级）都会让 Cycles / EEVEE Next
    的渐进累积缓冲被当成"场景变了"重置，拍出来是采样几乎为零的灰色占位图——
    这两个都是给性能测试用的调试 API，语义上是"强制走一次完整的场景求值+渲染"，
    不是"轻量把已经画好的东西重新提交一次"，对渐进渲染引擎不安全，因此调用方
    需要的重绘改用 area.tag_redraw() 走 Blender 正常事件循环（见 TakeSnap），
    这里只管截图，不管重绘。"""
    import os
    import tempfile

    aw, ah = int(area.width), int(area.height)
    rw, rh = int(region.width), int(region.height)
    fd, path = tempfile.mkstemp(suffix=".png", prefix="pond_snap_")
    os.close(fd)
    img = None
    try:
        with context.temp_override(area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=path)
        img = bpy.data.images.load(path)
        # 标 Non-Color/Raw：截图字节本身就是最终显示编码值，画回前会在 shader 里
        # 统一做一次预解码（_DRAW_DECODE_SRGB），这里不能再被当成 sRGB 文件先解码一遍
        for cs in ("Non-Color", "Raw"):
            try:
                img.colorspace_settings.name = cs
                break
            except Exception:
                continue
        iw, ih = int(img.size[0]), int(img.size[1])
        arr = np.array(img.pixels[:], dtype=np.float32).reshape(ih, iw, 4)
        sx = (iw / aw) if aw else 1.0
        sy = (ih / ah) if ah else 1.0
        # region/area 原点都是左下角、Y 向上，跟 img.pixels 的行序（从下往上）天然对齐
        off_x = int(round((region.x - area.x) * sx))
        off_y = int(round((region.y - area.y) * sy))
        off_x = max(0, min(iw - 1, off_x))
        off_y = max(0, min(ih - 1, off_y))
        x1 = max(off_x + 1, min(iw, off_x + int(round(rw * sx))))
        y1 = max(off_y + 1, min(ih, off_y + int(round(rh * sy))))
        crop = np.ascontiguousarray(arr[off_y:y1, off_x:x1, :])
        # 截图 PNG 的 alpha 通道未必有意义，强制置 1，避免画回时 ALPHA 混合出现透明
        crop[:, :, 3] = 1.0
        cw, ch = crop.shape[1], crop.shape[0]
        buf = gpu.types.Buffer("FLOAT", cw * ch * 4, crop)
        tex = gpu.types.GPUTexture((cw, ch), format="RGBA8", data=buf)
        return tex, cw, ch
    finally:
        if img is not None:
            bpy.data.images.remove(img)
        try:
            os.remove(path)
        except OSError:
            pass


def _srgb_encode(rgb):
    """sRGB 编码（标准分段曲线）。Snapshot 本体已不再使用，
    保留给 tools/test_snap_visual.py 做色彩链路标定"""
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)


def _srgb_decode(rgb):
    """sRGB 解码（标准分段曲线），导出图像数据块时把显示值换回 scene-linear"""
    return np.where(rgb <= 0.04045, rgb / 12.92, np.power((rgb + 0.055) / 1.055, 2.4))


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
    """拍摄当前 3D 视口快照。

    统一走截图路径：直接读当前视口此刻已经显示在屏幕上的真实像素，不重新触发
    渲染——离屏重渲对 EEVEE 这类同步引擎虽然可行，但会跟屏幕当前画面不一致
    （视角/叠加层可能在拍摄瞬间已经变化），对 Cycles 等渐进采样引擎更是直接
    拍出黑图/半成品（全新 session，零采样）。截图路径不区分引擎，眼见为实。
    见 开发计划/2026-08-19_Cycles视口快照黑屏修复.md。

    如果本窗口当前正显示着旧的对比覆盖层，摘掉显示标记（disp_snap.pop）只是
    清空一个 Python 字典，屏幕上这一刻实际画着的还是摘掉前那一帧（带着旧覆盖
    层）——直接截图会把旧覆盖层拍进新快照。这种情况下需要先等 Blender 走一次
    正常的重绘，再截图；这一等用 modal + wm 定时器实现（tag_redraw 之后等一个
    事件循环节拍），跟平时移动窗口/切换焦点触发的重绘性质完全一样，不会让
    Cycles / EEVEE Next 以为场景变了而重置渐进累积——绝不能用
    wm.redraw_timer 那套调试 API 强制刷新，见 _capture_screenshot 里的说明。
    没有旧覆盖层要摘时（prev is None）当前屏幕已经是干净画面，直接截图，
    不需要这一等，保持原有的"立即拍摄"体验。
    """
    bl_idname = "object.take_snapshot"
    bl_label = "拍摄快照"

    _timer = None
    _area = None
    _region = None
    _area_id = None
    _prev = None
    _scene = None

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def _do_capture(self, context, area, region, scene, area_id, prev):
        try:
            tex, w, h = _capture_screenshot(context, area, region)
        except Exception as e:
            if prev is not None:
                disp_snap[area_id] = prev
            self.report({"ERROR"}, f"快照没拍成: {e}")
            return {"CANCELLED"}
        _finish_capture(scene, area, area_id, tex, w, h)
        self.report({"INFO"}, f"快照 {scene.snapshot_list[-1].name} 已存")
        return {"FINISHED"}

    def execute(self, context):
        area = context.area
        if area is None or area.type != "VIEW_3D":
            self.report({"WARNING"}, "请在3D视口中使用")
            return {"CANCELLED"}
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is None:
            self.report({"ERROR"}, "找不到视口")
            return {"CANCELLED"}
        scene = context.scene
        area_id = _aid(area)
        # 拍摄期间摘下本窗口的显示标志：防止旧叠加被拍进新快照；失败时回滚。
        # op 内不写任何 RNA，旧版「undo 推入撤销 show_region_*」的崩溃面整体消失
        prev = disp_snap.pop(area_id, None)
        if prev is None:
            return self._do_capture(context, area, region, scene, area_id, prev)
        # 有旧覆盖层要摘：等一次自然重绘再截图，见类文档字符串
        self._area, self._region, self._area_id = area, region, area_id
        self._prev, self._scene = prev, scene
        for r in area.regions:
            if r.type == "WINDOW":
                r.tag_redraw()
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        self._timer = None
        return self._do_capture(
            context, self._area, self._region, self._scene,
            self._area_id, self._prev)


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
