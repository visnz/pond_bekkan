# 别馆模式 ·「✨ 灯光合成」独立面板
# 新操作脚本容器：「贴图强制压缩」（三步向导，见
# core/analyzer/ops.py 的 ANALYZER_OT_downscale）；
# Fab 节点导入、修复法线贴图色彩空间入口位于 shader_panel.py。
# 双引擎 Cy 白膜适配：core/texture.py，共用一个白膜节点组。
# 中心约束灯光：core/stage.py；隐形遮光板、探针、EV 吸光体及烘焙：core/light_probe.py。
# 后续脚本以按钮追加。
import bpy
from ...core import autoblend


class BEKKAN_PT_light_compose(bpy.types.Panel):
    bl_label = "✨ 灯光合成"
    bl_idname = "BEKKAN_PT_light_compose"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "别馆"
    bl_parent_id = ""  # 顶层独立面板（bl_parent_id 空串 = 无父）
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator('object.add_light_with_constraint', icon='LIGHT_SPOT')
        col.operator('object.create_invisible_blocker_visn', icon='MESH_PLANE')
        col.operator('camera.create_volume_probe_visn', icon='LIGHTPROBE_VOLUME')
        col.operator('object.create_ev_absorber_visn', icon='CUBE')
        col.operator('object.bake_ev_absorbers_visn', icon='LIGHTPROBE_VOLUME')
        col.operator('material.cycles_clay_visn', icon='NODE_MATERIAL')
        col.operator('material.base_color_direct_visn', icon='NODE_MATERIAL')
        col.operator("analyzer.downscale_textures_visn",
                        text="贴图强制压缩", icon="IMAGE")


class BEKKAN_PT_autoblend(bpy.types.Panel):
    bl_label = "AutoBlend · 物体融合"
    bl_idname = "BEKKAN_PT_autoblend"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "别馆"
    bl_parent_id = "BEKKAN_PT_light_compose"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.operator("render.autoblend_setup_visn", icon="TOOL_SETTINGS")
        tree = autoblend.compositor_tree(context.scene)
        node = autoblend.get_autoblend_node(tree)
        if node is None:
            layout.label(text="先初始化，再加入选中物体的材质")
            return
        if node.node_tree is None or node.node_tree.name != autoblend.GROUP_NAME:
            layout.operator("render.autoblend_upgrade_visn", icon="FILE_REFRESH")
            return
        source = autoblend.render_source(tree, node, context.scene, context.view_layer)
        source_scene = (source.scene or context.scene) if source else context.scene
        layer = source_scene.view_layers.get(source.layer) if source else context.view_layer
        if not layer or not layer.use_pass_z:
            layout.label(text="深度通道未开启", icon="ERROR")
        if not layer or not (layer.use_pass_cryptomatte_material and layer.use_pass_cryptomatte_object):
            layout.label(text="Cryptomatte 通道未开启", icon="ERROR")
        if not getattr(context.scene.render, "use_compositing", True):
            layout.label(text="渲染合成器未开启", icon="ERROR")
        effect = autoblend.compositor_effect(context.scene)
        if effect is not None and not effect.enable_for_render:
            layout.label(text="当前合成效果未启用渲染", icon="ERROR")
        layout.prop(node, "mute", text="启用物体融合", invert_checkbox=True, toggle=True)
        col = layout.column()
        col.enabled = not node.mute
        settings = col.box()
        settings.use_property_split = True
        settings.use_property_decorate = False
        for name, label in (("Blend Distance", "融合距离"), ("Max Size", "最大范围"),
                            ("Thickness Scale", "厚度比例"), ("Mirror Factor", "镜像系数"),
                            ("Hardness", "硬度"), ("Hardness Midlevel", "硬度中值")):
            self.draw_input(settings, node, name, label)
        mask_box = col.box()
        mask_box.label(text="遮罩")
        row = mask_box.row(align=True)
        row.operator("render.autoblend_mask_visn", text="Noise").mask_type = "NOISE"
        row.operator("render.autoblend_mask_visn", text="Voronoi").mask_type = "VORONOI"
        mask_input = autoblend.socket(node.inputs, "Mask")
        if mask_input and mask_input.is_linked:
            link = mask_input.links[0]
            mask_box.prop(link, "is_muted", text="启用遮罩", invert_checkbox=True)
            self.draw_input(mask_box, node, "Mask Power", "遮罩强度")
            self.draw_input(mask_box, node, "Mask Midlevel", "遮罩中值")
            mask_box.label(text=link.from_node.label or link.from_node.name)
            for input_socket in link.from_node.inputs:
                if input_socket.enabled and not input_socket.hide and not input_socket.is_linked and hasattr(input_socket, "default_value"):
                    mask_box.prop(input_socket, "default_value", text=input_socket.name)
        else:
            self.draw_input(mask_box, node, "Mask", "遮罩值")
        materials = col.box()
        materials.label(text="参与融合的材质")
        crypto = autoblend.get_material_node(tree)
        if crypto is None:
            materials.label(text="材质 Cryptomatte 缺失，请重新初始化", icon="ERROR")
        else:
            row = materials.row(align=True)
            row.operator("render.autoblend_add_visn", text="加入选中材质", icon="ADD")
            row.operator("render.autoblend_remove_visn", text="移除", icon="REMOVE")
            materials.prop(crypto, "matte_id", text="")
            materials.label(text="共用同一材质的物体一起生效")
        col.label(text="更多连线控制可在合成器中调整")

    @staticmethod
    def draw_input(layout, node, name, label):
        input_socket = autoblend.socket(node.inputs, name)
        if input_socket is not None and hasattr(input_socket, "default_value"):
            row = layout.row()
            row.enabled = not input_socket.is_linked
            row.prop(input_socket, "default_value", text=label)


_classes = (BEKKAN_PT_light_compose, BEKKAN_PT_autoblend)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
