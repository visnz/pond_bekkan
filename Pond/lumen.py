# 明度检查：素模灰 / 灯光显像 / 黑白显像，三种一键切换，随时还原
import json
import bpy

from . import prefs

BW_GROUP_NAME = "池塘_黑白"


def _make_bw_tree():
    """黑白合成节点组：按人眼亮度权重(Rec.709)转灰,不是去色
    去色=每像素取max(RGB),纯蓝会亮成白;亮度权重才是真实明度关系"""
    ng = bpy.data.node_groups.get(BW_GROUP_NAME)
    if ng:
        # 旧版是去色做法,拆掉重建
        if any(n.type in ("HUE_SAT",) for n in ng.nodes):
            bpy.data.node_groups.remove(ng)
            ng = None
    if ng:
        return ng
    ng = bpy.data.node_groups.new(BW_GROUP_NAME, "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    gi.location = (-300, 0)
    go.location = (300, 0)

    conv = ng.nodes.new("CompositorNodeRGBToBW")
    conv.location = (0, 0)
    ng.links.new(gi.outputs[0], conv.inputs.get("Image") or conv.inputs[0])
    ng.links.new(conv.outputs.get("Val") or conv.outputs[0], go.inputs[0])
    return ng


CLAY_MAT_NAME = "池塘_白膜AO"


def _make_clay_mat():
    """白膜材质: 环境光遮蔽AO颜色 → 原理化基础色, 糙度1(照她给的节点图)"""
    mat = bpy.data.materials.get(CLAY_MAT_NAME)
    if mat:
        return mat
    mat = bpy.data.materials.new(CLAY_MAT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (420, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    r = bsdf.inputs.get("Roughness")
    if r is not None:
        r.default_value = 1.0
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.location = (-160, 60)
    ao.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    ao.samples = 16
    nt.links.new(ao.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def _save_state(context):
    sh = context.space_data.shading
    sc = context.scene
    ov = context.view_layer.material_override
    return {
        "shading_type": sh.type,
        "light": sh.light,
        "color_type": sh.color_type,
        "single_color": list(sh.single_color),
        "render_pass": getattr(sh, "render_pass", "COMBINED"),
        "use_compositor": sh.use_compositor,
        "comp_group": sc.compositing_node_group.name if sc.compositing_node_group else None,
        "mat_override": ov.name if ov else None,
    }


def _restore(context, state):
    sh = context.space_data.shading
    sc = context.scene
    try:
        sh.type = state["shading_type"]
        if sh.type == "SOLID":
            sh.light = state["light"]
            sh.color_type = state["color_type"]
        sh.single_color = state["single_color"]
        if sh.type == "RENDERED":
            sh.render_pass = state["render_pass"]
        sh.use_compositor = state["use_compositor"]
        prev = state["comp_group"]
        sc.compositing_node_group = bpy.data.node_groups.get(prev) if prev else None
        ov = state.get("mat_override")
        context.view_layer.material_override = bpy.data.materials.get(ov) if ov else None
        for name, col in (state.get("light_colors") or {}).items():
            lt = bpy.data.lights.get(name)
            if lt:
                lt.color = col
    except Exception:
        pass


def _get_state(wm):
    raw = wm.pond_lumen_state
    return json.loads(raw) if raw else None


def _clear_if_active(context):
    """已经开着某个检查模式就先还原，返回之前的模式名"""
    wm = context.window_manager
    state = _get_state(wm)
    if state:
        _restore(context, state)
        wm.pond_lumen_state = ""
        return state.get("mode")
    return None


class _LumenToggle:
    """同一按钮再按一次 = 还原"""
    mode = ""

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == "VIEW_3D"

    def execute(self, context):
        wm = context.window_manager
        if _clear_if_active(context) == self.mode:
            return {"FINISHED"}  # 关掉即可
        state = _save_state(context)
        state["mode"] = self.mode
        try:
            self.apply(context, state)
        except Exception as e:
            _restore(context, state)
            self.report({"ERROR"}, f"开不起来：{e}")
            return {"CANCELLED"}
        wm.pond_lumen_state = json.dumps(state)
        return {"FINISHED"}


class POND_OT_lumen_clay(_LumenToggle, bpy.types.Operator):
    """白膜：材质覆盖成 AO 白模(AO→基础色,糙度1),渲染视图看纯形体和光影,再按一次还原"""
    bl_idname = "pond.lumen_clay"
    bl_label = "白膜(AO)"
    bl_options = {"REGISTER", "UNDO"}
    mode = "CLAY"

    def apply(self, context, state):
        sh = context.space_data.shading
        sh.type = "RENDERED"
        context.view_layer.material_override = _make_clay_mat()
        # 灯也临时变白光,白膜不吃灯色;退出时各回各的颜色
        cols = {}
        for lt in bpy.data.lights:
            if lt.library:
                continue
            cols[lt.name] = list(lt.color)
            lt.color = (1.0, 1.0, 1.0)
        state["light_colors"] = cols
        if context.scene.render.engine != "CYCLES":
            self.report({"WARNING"}, "材质覆盖只有 Cycles 认,当前引擎下看不到白膜")


class POND_OT_lumen_light(_LumenToggle, bpy.types.Operator):
    """灯光显像：只显示打在表面的漫射光(Diffuse Light通道),剥掉贴图颜色纯看布光,再按一次还原"""
    bl_idname = "pond.lumen_light"
    bl_label = "灯光显像"
    bl_options = {"REGISTER", "UNDO"}
    mode = "LIGHT"

    def apply(self, context, state):
        sh = context.space_data.shading
        sh.type = "RENDERED"
        sh.render_pass = "DIFFUSE_LIGHT"


class POND_OT_lumen_bw(_LumenToggle, bpy.types.Operator):
    """黑白显像：按人眼亮度权重(Rec.709)转灰看明度关系,不是简单去色,再按一次还原"""
    bl_idname = "pond.lumen_bw"
    bl_label = "黑白显像"
    bl_options = {"REGISTER", "UNDO"}
    mode = "BW"

    def apply(self, context, state):
        sh = context.space_data.shading
        sc = context.scene
        sh.type = "RENDERED"
        sc.compositing_node_group = _make_bw_tree()
        sh.use_compositor = "ALWAYS"


class POND_OT_lumen_restore(bpy.types.Operator):
    """还原到进入检查模式前的视图状态"""
    bl_idname = "pond.lumen_restore"
    bl_label = "还原视图"

    def execute(self, context):
        if _clear_if_active(context) is None:
            self.report({"INFO"}, "本来就没开检查模式")
        return {"FINISHED"}


class POND_PT_lumen(bpy.types.Panel):
    bl_label = "明度检查"
    bl_idname = "POND_PT_lumen"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_lumen")

    def draw(self, context):
        wm = context.window_manager
        state = _get_state(wm)
        active = state.get("mode") if state else None
        col = self.layout.column(align=True)
        col.operator("pond.lumen_clay", icon="SHADING_SOLID",
                     depress=(active == "CLAY"))
        col.operator("pond.lumen_light", icon="LIGHT_SUN",
                     depress=(active == "LIGHT"))
        col.operator("pond.lumen_bw", icon="IMAGE_ZDEPTH",
                     depress=(active == "BW"))
        if active:
            col.separator()
            col.operator("pond.lumen_restore", icon="LOOP_BACK")


_classes = (
    POND_OT_lumen_clay,
    POND_OT_lumen_light,
    POND_OT_lumen_bw,
    POND_OT_lumen_restore,
    POND_PT_lumen,
)


def register():
    bpy.types.WindowManager.pond_lumen_state = bpy.props.StringProperty(default="")
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.pond_lumen_state
