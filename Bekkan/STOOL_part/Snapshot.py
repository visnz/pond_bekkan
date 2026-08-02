import bpy, time, gpu, blf, traceback  # type: ignore
import numpy as np  # type: ignore
from gpu_extras.batch import batch_for_shader  # type: ignore
from bpy.app.handlers import persistent  # type: ignore

# 按 Blender 版本选择实现：
# < 5.0  → 旧式 GPUShader + 自定义 GLSL（支持不透明度/亮度/对比度/伽马，仅 OpenGL）
# >= 5.0 → GPUShaderCreateInfo 自定义 shader（旧式构造器在 5.2 已删除）
# 仅支持 Blender 5.2：以下版本判断已注释，直接锁定 5.2 分支
# IS_BLENDER5 = bpy.app.version >= (5, 0, 0)
IS_BLENDER5 = True

# 画回色彩校准（2026-08-01 本机 5.2 实测，tools/test_snap_visual.py 灰阶斜坡标定）：
# 5.2 的 POST_PIXEL 输出到最终上屏被叠加了两次 sRGB 编码（S = enc(enc(T))，逐 bin 拟合误差 <0.01），
# 而离屏捕获（float + do_color_management）只含视图变换、不含最终 EOTF（C = dec(D)，D 为屏幕字节），
# 直通画回 = enc²(dec(D)) = enc(D)，整体偏亮一级。故 5.2+ 画回 shader 做一次 srgb_to_linear
# 预解码抵消（enc²(dec(C)) = D）。5.0/5.1 未经实测暂保持直通，实测后按结果修改此判断
# _DRAW_DECODE_SRGB = bpy.app.version >= (5, 2, 0)
_DRAW_DECODE_SRGB = True

_snaps = {}        # key -> {"tex": GPUTexture, "w": int, "h": int, "label": str}，纯显存、会话级
_next_id = [1]     # 列表包一层，避免函数内 global 声明
disp_snap = {}     # area_id -> key（存在即显示）
draw_hdl = {}      # area_id -> 绘制句柄

addon_keymaps = []

# ---- 4.x 分支专用 GLSL（含不透明度/亮度/对比度/伽马调节）----
vert_shader = '''
    uniform mat4 ModelViewProjectionMatrix;
    in vec2 pos;
    in vec2 texCoord;
    out vec2 texCoord_interp;
    void main() {
        gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);
        texCoord_interp = texCoord;
    }
'''

frag_shader = '''
    uniform sampler2D image;
    uniform float opacity;
    uniform float brightness;
    uniform float contrast;
    uniform float gamma;
    in vec2 texCoord_interp;
    out vec4 fragColor;
    void main() {
        vec4 color = texture(image, texCoord_interp);
        color.rgb *= brightness-0.02;
        color.rgb = (color.rgb - 0.5) * (contrast+0.002) + 0.5;
        color.rgb = pow(color.rgb, vec3(2.2 / (gamma-0.02)));
        fragColor = vec4(color.rgb, color.a * opacity);
    }
'''

# ---- 5.x 分支 shader 源码（GPUShaderCreateInfo 路线；pos 为 CPU 侧换算的 NDC）----
_VERT5 = """
void main()
{
    uv = texCoord;
    gl_Position = vec4(pos, 0.0, 1.0);
}
"""

_FRAG5_PASS = """
void main()
{
    fragColor = texture(image, uv);
}
"""

_FRAG5_DECODE = """
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

shader = line_shader = None


def get_shader():
    """延迟初始化主 shader，确保 Blender 上下文已就绪"""
    global shader
    if shader is None:
        try:
            if IS_BLENDER5:
                interface = gpu.types.GPUStageInterfaceInfo("bekkan_snap")
                interface.smooth("VEC2", "uv")
                info = gpu.types.GPUShaderCreateInfo()
                info.vertex_in(0, "VEC2", "pos")
                info.vertex_in(1, "VEC2", "texCoord")
                info.vertex_out(interface)
                info.fragment_out(0, "VEC4", "fragColor")
                info.sampler(0, "FLOAT_2D", "image")
                info.vertex_source(_VERT5)
                info.fragment_source(_FRAG5_DECODE if _DRAW_DECODE_SRGB else _FRAG5_PASS)
                shader = gpu.shader.create_from_info(info)
            else:
                from gpu.types import GPUShader  # 延迟导入，避免 5.x 下顶层导入失败
                shader = GPUShader(vert_shader, frag_shader)
        except Exception:  # Vulkan 后端或其他不支持的配置
            print("Warning: shader initialization failed")
    return shader


def get_line_shader():
    """延迟初始化分割线 shader"""
    global line_shader
    if line_shader is None:
        try:
            line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        except Exception:
            print("Warning: UNIFORM_COLOR shader initialization failed")
    return line_shader


def aid(area):
    """3D 视图窗口 ID（每个窗口独立保存一组快照）"""
    return str(hash(area.as_pointer()) % 10000).zfill(4)


def _ndc(rw, rh, x, y):
    """像素坐标 -> NDC（5.x 无 gpu.matrix 可取矩阵，CPU 侧换算）"""
    return (x / rw) * 2.0 - 1.0, (y / rh) * 2.0 - 1.0


def redraw_view3d(screen):
    for a in screen.areas:
        if a.type == 'VIEW_3D':
            for r in a.regions:
                if r.type == 'WINDOW':
                    r.tag_redraw()


def _rm_handler(area_id):
    """安全移除绘制句柄：区域被合并/关闭后句柄已失效，忽略 ReferenceError"""
    h = draw_hdl.get(area_id)
    if h:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
        except ReferenceError:
            pass
    draw_hdl[area_id] = None


def _free_res(area_id):
    """关闭某窗口的快照显示：移除绘制句柄并清除显示记录"""
    _rm_handler(area_id)
    disp_snap.pop(area_id, None)


def _ensure_handler(area_id):
    """确保指定窗口的绘制句柄存在"""
    if draw_hdl.get(area_id):
        return
    draw_hdl[area_id] = bpy.types.SpaceView3D.draw_handler_add(
        draw_snap, (area_id,), 'WINDOW', 'POST_PIXEL')


@persistent
def _reset_on_load(_=None):
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


def _srgb_encode(rgb):
    """sRGB 编码（标准分段曲线）。Snapshot 本体已不再使用，
    保留给 tools/test_snap_visual.py 做色彩链路标定"""
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)


def _srgb_decode(rgb):
    """sRGB 解码（标准分段曲线），导出图像数据块时把显示值换回 scene-linear"""
    return np.where(rgb <= 0.04045, rgb / 12.92, np.power((rgb + 0.055) / 1.055, 2.4))


def _capture_offscreen(context, area, space, region):
    """离屏重画当前视口并转为 RGBA8 纹理（非 RENDERED 着色模式的捕获路径）。
    draw_view3d 一次同步渲出全部采样（EEVEE 无采样竞态，比旧延时截图更可靠）；
    do_color_management=True 的 float 输出只含视图变换、不含最终 EOTF（5.2 实测：
    捕获值 C = srgb_dec(屏幕字节 D)），存储语义与渲染 PNG 加载后的线性像素一致，
    画回侧的预解码（_DRAW_DECODE_SRGB）以此为基准。面板等 region UI 天然不入镜。
    大场景拍摄会同步阻塞，属预期"""
    w, h = int(region.width), int(region.height)
    rv3d = space.region_3d
    # 离屏必须 RGBA32F：其 read() 返回 FLOAT Buffer，可直接喂 GPUTexture（RGBA8 离屏返回 UBYTE 喂不回）
    off = gpu.types.GPUOffScreen(w, h, format='RGBA32F')
    try:
        with context.temp_override(area=area, region=region, space_data=space):
            off.draw_view3d(context.scene, context.view_layer, space, region,
                            rv3d.view_matrix, rv3d.window_matrix,
                            do_color_management=True)
        buf = off.texture_color.read()
        buf.dimensions = w * h * 4
        tex = gpu.types.GPUTexture((w, h), format='RGBA8', data=buf)  # 内部量化，零 numpy
    finally:
        off.free()  # GPUOffScreen 必须显式释放；GPUTexture 无 free()，靠解除引用 + GC
    return tex, w, h


def _finish_capture(scene, area, area_id, tex, w, h):
    """拍摄成功后的公共收尾：登记纹理与快照列表、切换显示、刷新窗口"""
    key = "s%d" % _next_id[0]
    _next_id[0] += 1
    label = time.strftime("%H:%M:%S")
    _snaps[key] = {"tex": tex, "w": w, "h": h, "label": label}
    item = scene.snapshot_list.add()
    item.name, item.area_id, item.key = label, area_id, key
    scene.snapshot_list_index = len(scene.snapshot_list) - 1
    disp_snap[area_id] = key
    _ensure_handler(area_id)
    for r in area.regions:
        if r.type == 'WINDOW':
            r.tag_redraw()


class SnapItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    area_id: bpy.props.StringProperty()
    key: bpy.props.StringProperty()  # _snaps 的键


class TakeSnap(bpy.types.Operator):
    bl_idname = "object.take_snapshot"
    bl_label = "拍摄"
    bl_description = "拍摄3D视口画布快照（离屏重画，大场景时可能同步阻塞数秒）"

    def execute(self, context):
        area = context.area
        if area is None or area.type != 'VIEW_3D':
            self.report({'WARNING'}, "请在3D视口中使用")
            return {'CANCELLED'}
        space = context.space_data
        scene = context.scene
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None or getattr(space, 'region_3d', None) is None:
            self.report({'ERROR'}, "找不到视口")
            return {'CANCELLED'}
        area_id = aid(area)
        # 拍摄期间摘下本窗口的显示标志：若离屏重画触发 Python 绘制回调，防止旧叠加被拍进新快照；
        # 失败时回滚。op 内不写任何 RNA，旧版「undo 推入撤销 show_region_*」的崩溃面整体消失
        prev = disp_snap.pop(area_id, None)
        try:
            # 一律离屏重画（draw_view3d 在 SOLID/材质/RENDERED 下都渲染，跨版本稳定；
            # 旧版 use_full_render 完整渲染路径在 5.0/5.1 下 EEVEE 空白、Cycles 灰屏，已移除）
            tex, w, h = _capture_offscreen(context, area, space, region)
        except Exception as e:
            if prev is not None:
                disp_snap[area_id] = prev
            traceback.print_exc()
            self.report({'ERROR'}, f"快照没拍成: {e}")
            return {'CANCELLED'}
        _finish_capture(scene, area, area_id, tex, w, h)
        self.report({'INFO'}, f"快照 {scene.snapshot_list[-1].name} 已存")
        return {'FINISHED'}


class ToggleSnapDisplay(bpy.types.Operator):
    bl_idname = "object.toggle_snapshot_display"
    bl_label = "快照开关"
    bl_description = "控制是否显示快照，眼睛图形睁开为启用"

    def execute(self, context):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "请在3D视口中使用")
            return {'CANCELLED'}
        area_id = aid(context.area)
        if area_id in disp_snap:
            _free_res(area_id)
        else:
            i = context.scene.snapshot_list_index
            if 0 <= i < len(context.scene.snapshot_list):
                item = context.scene.snapshot_list[i]
                if item.key in _snaps and item.area_id == area_id:
                    disp_snap[area_id] = item.key
                    _ensure_handler(area_id)
                    self.report({'INFO'}, f"显示快照 {item.name}")
                else:
                    self.report({'WARNING'}, "快照不存在或不属于本窗口")
            else:
                self.report({'WARNING'}, "没有选中的快照")
        context.window_manager.update_tag()
        redraw_view3d(context.screen)
        return {'FINISHED'}


class SelectSnap(bpy.types.Operator):
    bl_idname = "object.select_snapshot"
    bl_label = "选择快照"
    bl_description = "选择用于展示的快照"

    def execute(self, context):
        lst = context.scene.snapshot_list
        idx = context.scene.snapshot_list_index
        if not lst or not (0 <= idx < len(lst)):
            self.report({'WARNING'}, "没有可选的快照")
            return {'CANCELLED'}
        item = lst[idx]
        if item.key not in _snaps:
            self.report({'WARNING'}, "快照已失效（显存纹理不跨会话保留）")
            return {'FINISHED'}
        orig_id = item.area_id
        # 先关闭所有窗口的快照显示
        for a in context.screen.areas:
            if a.type == 'VIEW_3D' and aid(a) in disp_snap:
                _free_res(aid(a))
                for r in a.regions:
                    if r.type == 'WINDOW':
                        r.tag_redraw()
        # 再在快照原属窗口中显示
        for a in context.screen.areas:
            if a.type == 'VIEW_3D' and aid(a) == orig_id:
                disp_snap[orig_id] = item.key
                _ensure_handler(orig_id)
                self.report({'INFO'}, f"显示快照 {item.name}")
                for r in a.regions:
                    if r.type == 'WINDOW':
                        r.tag_redraw()
                break
        return {'FINISHED'}


class ClearSnapList(bpy.types.Operator):
    bl_idname = "object.clear_snapshot_list"
    bl_label = "清除快照列表"
    bl_description = "清除快照列表并释放全部显存纹理"

    def execute(self, context):
        context.scene.snapshot_list_index = -1
        context.scene.snapshot_list.clear()
        _snaps.clear()
        for area_id in list(draw_hdl):
            _free_res(area_id)
        redraw_view3d(context.screen)
        self.report({'INFO'}, "快照列表已清空，全部快照已关闭")
        return {'FINISHED'}


def draw_snap(area_id):
    sh = get_shader()
    if sh is None:
        return
    cur_area = bpy.context.area
    if not cur_area or aid(cur_area) != area_id:
        return
    rec = _snaps.get(disp_snap.get(area_id))
    if rec is None:
        return
    try:
        scene = bpy.context.scene
        region = next(r for r in cur_area.regions if r.type == 'WINDOW')
        # 快照宽度与窗口宽度保持一致，高度按比例缩放并垂直居中（窗口尺寸变化适配）
        scale = region.width / rec["w"]
        w, h = rec["w"] * scale, rec["h"] * scale
        y = (region.height - h) / 2
        p = scene.slider_position / 100.0
        x0 = w * p  # 白线位置 = 比例（0-100%），拖鼠标时白线跟鼠标走；快照在白线左侧
        if IS_BLENDER5:
            rw, rh = region.width, region.height
            verts = [_ndc(rw, rh, 0, y), _ndc(rw, rh, x0, y),
                     _ndc(rw, rh, x0, y + h), _ndc(rw, rh, 0, y + h)]
        else:
            verts = [(0, y), (x0, y), (x0, y + h), (0, y + h)]
        batch = batch_for_shader(
            sh, 'TRI_FAN',
            {"pos": verts,
             "texCoord": ((0, 0), (p, 0), (p, 1), (0, 1))})
        gpu.state.blend_set('ALPHA')
        sh.bind()
        if not IS_BLENDER5:
            # 旧版自定义 shader：支持不透明度/亮度/对比度/伽马
            sh.uniform_float("opacity", scene.snapshot_opacity / 100)
            sh.uniform_float("brightness", scene.snapshot_brightness)
            sh.uniform_float("contrast", scene.snapshot_contrast)
            sh.uniform_float("gamma", scene.snapshot_gamma)
        sh.uniform_sampler("image", rec["tex"])
        batch.draw(sh)
        gpu.state.blend_set('NONE')
        # 绘制分割线
        ls = get_line_shader()
        if ls:
            lverts = [(x0, y, 0), (x0, y + h, 0)] if IS_BLENDER5 else [(x0, y), (x0, y + h)]
            line_batch = batch_for_shader(ls, 'LINES', {"pos": lverts})
            gpu.state.blend_set('ALPHA')
            ls.bind()
            ls.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
            line_batch.draw(ls)
            gpu.state.blend_set('NONE')
        # 角标：快照在白线左侧，角标显示在左上角
        text = f"快照 {rec['label']}"
        blf.size(0, 13)
        bx, by = 10, region.height - 26
        blf.position(0, bx - 1, by - 1, 0)
        blf.color(0, 0.1, 0.1, 0.1, 0.9)
        blf.draw(0, text)
        blf.position(0, bx, by, 0)
        blf.color(0, 1.0, 1.0, 1.0, 0.95)
        blf.draw(0, text)
    except ReferenceError:
        # 区域/纹理已失效，清理该窗口状态
        _free_res(area_id)
    except Exception as e:
        print(f"Error in draw_snap: {e}")
        traceback.print_exc()


class BEKKAN_UL_snap_list(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name)


def update_snap_sel(self, context):
    try:
        bpy.ops.object.select_snapshot()
    except RuntimeError:
        # 列表为空或索引越界时操作符会报告警告，此处吞掉异常避免刷屏 console
        pass


class SnapPanel(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_snapshot_panel_Snapshot"
    bl_label = "📸 快照"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '别馆'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        area_id = aid(context.area)
        # 内容整体右缩进一点，让各分段像一层层叠下来
        split = layout.split(factor=0.07)
        split.separator()
        col = split.column()
        # 左：显示开关（眼睛）；右：拍摄（相机+文字），铺满一行
        row = col.row(align=True)
        row.operator("object.toggle_snapshot_display", text="",
                     icon='HIDE_OFF' if area_id in disp_snap else 'HIDE_ON')
        row.operator("object.take_snapshot", text="拍摄", icon='RESTRICT_RENDER_OFF')
        col.separator()
        col.template_list("BEKKAN_UL_snap_list", "snapshot_list", scene, "snapshot_list",
                          scene, "snapshot_list_index")
        col.separator()
        # 裸滑块：0-100，默认 50 = 左右各半（Alt+右键进视口拖动模式，左键确认）
        col.prop(scene, "slider_position", text="", slider=True)
        if not IS_BLENDER5:
            # 图像设置仅旧版自定义 shader 使用（5.x 直通绘制不支持这些参数）
            col.separator()
            box = col.box()
            row = box.row()
            row.prop(scene, "show_image_settings", text="",
                     icon="TRIA_DOWN" if scene.show_image_settings else "TRIA_RIGHT", emboss=False)
            row.label(text="图像设置")
            if scene.show_image_settings:
                box.prop(scene, "snapshot_opacity")
                box.prop(scene, "snapshot_brightness")
                box.prop(scene, "snapshot_contrast")
                box.prop(scene, "snapshot_gamma")


class DragSlider(bpy.types.Operator):
    bl_idname = "object.drag_slider"
    bl_label = "拖动"
    bl_description = "Alt+右键在视口里拖动分割线，比较快照和当前3D视图"

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            # mouse_region_x 相对鼠标当前所在 region，除以 3D 视图 WINDOW 区宽
            region = next((r for r in context.area.regions if r.type == 'WINDOW'), None) if context.area else None
            if region and region.width:
                # 从左往右拖 = 数值 0→100 递增（快照占比增加）；Alt+右键松手后仍可继续自由滑动
                context.scene.slider_position = (event.mouse_region_x / region.width) * 100
                context.area.tag_redraw()
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # 左键点击确认结束（Alt+右键松手不结束，可松开 Alt 只靠鼠标自由滑动）
            return {'FINISHED'}
        elif event.type == 'ESC':
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.area and context.area.type == 'VIEW_3D':
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}


all_cls = [
    SnapItem, TakeSnap, ToggleSnapDisplay, SelectSnap, ClearSnapList,
    BEKKAN_UL_snap_list, SnapPanel, DragSlider
]

# (属性名, 属性定义)，注册时挂到 Scene，注销时统一删除
scene_props = {
    "snapshot_opacity": bpy.props.IntProperty(name="不透明度", description="快照覆盖在画面的不透明度", default=100, min=0, max=100),
    "snapshot_brightness": bpy.props.FloatProperty(name="亮度", description="快照亮度", default=1.0, min=0.0, max=5.0),
    "snapshot_contrast": bpy.props.FloatProperty(name="对比度", description="快照对比度", default=1.0, min=0.0, max=5.0),
    "snapshot_gamma": bpy.props.FloatProperty(name="伽马", description="快照伽马", default=2.2, min=0.1, max=10.0),
    "show_image_settings": bpy.props.BoolProperty(name="Show Image Settings", default=False),
    "snapshot_list": bpy.props.CollectionProperty(type=SnapItem),
    "snapshot_list_index": bpy.props.IntProperty(name="Index for snapshot_list", default=0, update=update_snap_sel),
    "slider_position": bpy.props.FloatProperty(name="对比比例", description="对比分割线位置：0%=不显示快照，100%=全屏快照（默认50%=各半；Alt+右键可拖动）", default=50, min=0, max=100, subtype='PERCENTAGE'),
}


def register():
    for cls in all_cls:
        bpy.utils.register_class(cls)
    for name, prop in scene_props.items():
        setattr(bpy.types.Scene, name, prop)
    if _reset_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_reset_on_load)

    # 设置快捷键
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        km.keymap_items.new(DragSlider.bl_idname, 'RIGHTMOUSE', 'PRESS', alt=True)
        km.keymap_items.new(TakeSnap.bl_idname, 'RIGHTMOUSE', 'PRESS', ctrl=True, alt=True)
        addon_keymaps.append(km)


def unregister():
    for area_id in list(draw_hdl):
        _rm_handler(area_id)
    draw_hdl.clear()
    _snaps.clear()      # 纹理靠解除引用 + GC 释放（GPUTexture 无 free()）
    disp_snap.clear()
    if _reset_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reset_on_load)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        for km in addon_keymaps:
            kc.keymaps.remove(km)
    addon_keymaps.clear()
    for name in scene_props:
        delattr(bpy.types.Scene, name)
    for cls in all_cls:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
