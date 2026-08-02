# 分层渲染：每个顶层集合一个视图层，合成器自动接好
# 规矩：纯灯光的集合每层都在(不然别的层没灯全黑)；其他内容集合转"仅间接光"
# (影子/反弹保留、不出像素)；胶片透明底；合成组 = 各层RenderLayers + AlphaOver 链
import bpy

from . import prefs

PREFIX = "层_"
NG_NAME = "池塘_分层合成"


GEO_TYPES = ("MESH", "CURVE", "SURFACE", "META", "FONT", "GPENCIL", "VOLUME")


def _has_renderable_geo(col):
    """有几何且至少一个没关渲染(MMD控制器形状这类全隐藏的不算)"""
    return any(o.type in GEO_TYPES and not o.hide_render for o in col.all_objects)


def _top_cols(scene):
    return list(scene.collection.children)


def _content_cols(scene):
    """只有真有可渲染几何的集合才独立成层;
    灯光/相机/空物体/全隐藏的集合 = 支援集合,每层都带"""
    return [c for c in _top_cols(scene) if _has_renderable_geo(c)]


class POND_OT_layered_setup(bpy.types.Operator):
    """每个顶层集合建一个视图层并接好合成器（灯光集合每层都带,其余层只留影子反弹）"""
    bl_idname = "pond.layered_setup"
    bl_label = "一键分层渲染"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        tops = _top_cols(scene)
        contents = _content_cols(scene)
        if not contents:
            self.report({"ERROR"}, "场景顶层没有内容集合（东西先分进集合里）")
            return {"CANCELLED"}
        content_names = {c.name for c in contents}

        made = []
        for col in contents:
            name = PREFIX + col.name
            vl = scene.view_layers.get(name)
            if vl is None:
                vl = scene.view_layers.new(name)
            for ch in vl.layer_collection.children:
                cn = ch.collection.name
                ch.exclude = False
                # 别的内容集合转"仅间接光";本层和支援集合(灯/相机/空物体)正常
                ch.indirect_only = (cn in content_names and cn != col.name)
            made.append(name)

        scene.render.film_transparent = True

        ng = bpy.data.node_groups.get(NG_NAME)
        if ng:
            bpy.data.node_groups.remove(ng)
        ng = bpy.data.node_groups.new(NG_NAME, "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT",
                                socket_type="NodeSocketColor")
        go = ng.nodes.new("NodeGroupOutput")
        prev = None
        y = 0
        for i, name in enumerate(made):
            rl = ng.nodes.new("CompositorNodeRLayers")
            rl.location = (-600, y)
            rl.label = name
            try:
                rl.scene = scene
            except Exception:
                pass
            rl.layer = name
            if prev is None:
                prev = rl.outputs["Image"]
            else:
                ao = ng.nodes.new("CompositorNodeAlphaOver")
                ao.location = (-250 + i * 60, y - 120)
                # 5.2 的 AlphaOver 是 Background/Foreground/Factor,按名字接,别按位置
                ng.links.new(prev, ao.inputs["Background"])
                ng.links.new(rl.outputs["Image"], ao.inputs["Foreground"])
                prev = ao.outputs["Image"]
            y -= 320
        go.location = (200, 0)
        ng.links.new(prev, go.inputs[0])
        scene.compositing_node_group = ng

        self.report({"INFO"},
                    "建了 %d 个视图层(%s),合成器接好,透明底已开" % (
                        len(made), "、".join(made)))
        return {"FINISHED"}


class POND_OT_layered_clear(bpy.types.Operator):
    """拆掉分层：删「层_」开头的视图层、断开分层合成组（回到单层渲染）"""
    bl_idname = "pond.layered_clear"
    bl_label = "拆掉分层"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(vl.name.startswith(PREFIX) for vl in context.scene.view_layers)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        keep = [vl for vl in scene.view_layers if not vl.name.startswith(PREFIX)]
        if not keep:
            base = scene.view_layers.new("ViewLayer")
            keep = [base]
        try:
            context.window.view_layer = keep[0]
        except Exception:
            pass
        for vl in [v for v in scene.view_layers if v.name.startswith(PREFIX)]:
            scene.view_layers.remove(vl)
        ng = bpy.data.node_groups.get(NG_NAME)
        if ng:
            if scene.compositing_node_group == ng:
                scene.compositing_node_group = None
            bpy.data.node_groups.remove(ng)
        self.report({"INFO"}, "分层拆掉了，回到单层")
        return {"FINISHED"}


class POND_PT_renderlayers(bpy.types.Panel):
    bl_label = "分层渲染"
    bl_idname = "POND_PT_renderlayers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_renderlayers")

    def draw(self, context):
        scene = context.scene
        col = self.layout.column(align=True)
        col.operator("pond.layered_setup", icon="RENDERLAYERS")
        col.operator("pond.layered_clear", icon="X")
        n = sum(1 for vl in scene.view_layers if vl.name.startswith(PREFIX))
        if n:
            self.layout.label(text=f"现有 {n} 个分层视图层", icon="CHECKMARK")
        self.layout.label(text="有可渲染几何的集合=一层", icon="INFO")
        self.layout.label(text="灯/相机/空物体集合每层都带", icon="INFO")
        self.layout.label(text="其他层的东西只留影子和反弹", icon="INFO")


_classes = (
    POND_OT_layered_setup,
    POND_OT_layered_clear,
    POND_PT_renderlayers,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
