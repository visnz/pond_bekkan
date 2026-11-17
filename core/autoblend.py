# AutoBlend 1.1 — Shahzod Boyhonov (Specoolar), GPL-2.0-or-later.
# PondBekkan 适配：逻辑/UI 分离，Blender 5.2+ 合成节点组与插座名称兼容。
# 原节点算法及出处见 autoblend_assets/README.md；注册时不访问场景或加载资源。
from pathlib import Path
import struct

import bpy
from bpy.props import BoolProperty, EnumProperty


GROUP_NAME = "_AUTOBLEND_1_1"
NODE_NAME = "_AUTOBLEND_"
MAT_NAME = "_AUTOBLEND_CM_MAT"
OBJ_NAME = "_AUTOBLEND_CM_OBJ"
MASK_NAME = "_AUTOBLEND_MASK_VISN"


def compositor_effect(scene):
    effects = getattr(scene, "compositor_effects", None)
    if effects is None:
        return None
    # 切换活跃效果不应让已经创建的 AutoBlend 从面板消失。
    for effect in effects:
        if get_autoblend_node(effect.node_group) is not None:
            return effect
    active = next((e for e in effects if e.is_active), None)
    if active is not None and active.node_group is not None:
        return active
    return next((e for e in effects if e.node_group is not None), None) or active


def compositor_tree(scene, create=False):
    """5.3+ 原生效果栈，5.2 场景节点组；保留旧工程接口的防御分支。"""
    if hasattr(scene, "compositor_effects"):
        effect = compositor_effect(scene)
        if effect is None and create:
            effect = scene.compositor_effects.new(name="AutoBlend")
        tree = effect.node_group if effect else None
        if tree is None and create:
            tree = bpy.data.node_groups.new("AutoBlend Compositor", "CompositorNodeTree")
            tree.interface.new_socket(name="Image", in_out="INPUT", socket_type="NodeSocketColor")
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            group_input = tree.nodes.new("NodeGroupInput")
            group_input.location = (-250, 0)
            effect.node_group = tree
        return tree
    if hasattr(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new("AutoBlend Compositor", "CompositorNodeTree")
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            scene.compositing_node_group = tree
        return tree
    if create and hasattr(scene, "use_nodes"):
        scene.use_nodes = True
    return getattr(scene, "node_tree", None)


def _editable_tree(scene):
    tree = compositor_tree(scene)
    if tree is None:
        raise ValueError("请先初始化 AutoBlend")
    if not getattr(tree, "is_editable", True):
        raise ValueError("当前合成器不可编辑，请先将它设为本地数据")
    # 一个合成器可被多个 Scene 复用；只改当前场景。
    shared = any(other != scene and any(group == tree for group in (
        [e.node_group for e in other.compositor_effects] if hasattr(other, "compositor_effects")
        else [compositor_tree(other)])) for other in bpy.data.scenes)
    if shared:
        new_tree = tree.copy()
        if hasattr(scene, "compositor_effects"):
            compositor_effect(scene).node_group = new_tree
        else:
            scene.compositing_node_group = new_tree
        tree = new_tree
    return tree


def socket(sockets, name, *aliases):
    """Noise 的 Fac identifier 保留，但 5.2 的显示名称是 Factor。"""
    for key in (name, *aliases):
        found = sockets.get(key)
        if found is not None:
            return found
    return next((s for s in sockets if s.identifier in (name, *aliases)), None)


def get_autoblend_node(tree):
    if tree is None:
        return None
    node = tree.nodes.get(NODE_NAME)
    if node is not None and node.bl_idname == "CompositorNodeGroup":
        return node
    return next((n for n in tree.nodes if n.bl_idname == "CompositorNodeGroup"
                 and n.node_tree and n.node_tree.name.startswith("_AUTOBLEND_")), None)


def get_material_node(tree):
    return _crypto_node(tree, "Matte", MAT_NAME)


def _crypto_node(tree, input_name, fallback_name):
    node = get_autoblend_node(tree)
    matte = socket(node.inputs, input_name) if node else None
    if matte and matte.is_linked and matte.links[0].from_node.bl_idname == "CompositorNodeCryptomatteV2":
        return matte.links[0].from_node
    found = tree.nodes.get(fallback_name) if tree else None
    return found if found and found.bl_idname == "CompositorNodeCryptomatteV2" else None


def render_source(tree, node=None, scene=None, layer=None):
    if node is not None:
        for name in ("Depth", "Image"):
            input_socket = socket(node.inputs, name)
            if input_socket and input_socket.is_linked:
                source = input_socket.links[0].from_node
                if source.bl_idname == "CompositorNodeRLayers":
                    return source
    return next((n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"
                 and (n.scene is None or n.scene == scene)
                 and (not layer or n.layer == layer.name)), None)


def source_layer(context, source):
    scene = source.scene or context.scene
    layer = scene.view_layers.get(source.layer)
    if scene != context.scene or layer is None:
        raise ValueError("AutoBlend 的渲染层来自其他场景或已失效，请先在合成器中调整")
    return layer


def load_group():
    group = bpy.data.node_groups.get(GROUP_NAME)
    if group is not None:
        if group.bl_idname != "CompositorNodeTree":
            raise ValueError("AutoBlend 节点组名称被其他类型的数据占用")
        return group
    path = Path(__file__).resolve().parent / "autoblend_assets" / "data.blend"
    if not path.is_file():
        raise ValueError("AutoBlend 内置节点资源缺失，请重新安装完整插件")
    with bpy.data.libraries.load(str(path), link=False) as (src, dst):
        if GROUP_NAME not in src.node_groups:
            raise ValueError("内置资源中没有 AutoBlend 1.1 节点组")
        dst.node_groups = [GROUP_NAME]
    group = dst.node_groups[0]
    if group is None:
        raise ValueError("AutoBlend 节点组加载失败")
    return group


def _required(sockets, name, *aliases):
    found = socket(sockets, name, *aliases)
    if found is None:
        raise ValueError(f"当前版本缺少所需插座：{name}")
    return found


def _output_socket(tree, location):
    if any(name in bpy.types.Scene.bl_rna.properties for name in ("compositor_effects", "compositing_node_group")):
        outputs = [n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"]
        output = next((n for n in outputs if n.is_active_output), None)
        if output is None:
            output = tree.nodes.new("NodeGroupOutput")
            output.location = location
        image = socket(output.inputs, "Image")
        if image is None:
            image = next((s for s in output.inputs if s.type == "RGBA"), None)
        if image is None:
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            image = _required(output.inputs, "Image")
    else:
        output = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeComposite"), None)
        if output is None:
            output = tree.nodes.new("CompositorNodeComposite")
            output.location = location
        image = _required(output.inputs, "Image")
    if image.is_linked:
        raise ValueError("现有输出不直接来自当前渲染层；请先在合成器中接好 Render Layers 的 Image")
    return image


def setup_nodes(context, tree, layer):
    node = get_autoblend_node(tree)
    render = render_source(tree, node, context.scene, layer)
    if render is None:
        render = tree.nodes.new("CompositorNodeRLayers")
        render.scene = context.scene
        render.layer = layer.name
    image = _required(render.outputs, "Image")
    depth = _required(render.outputs, "Depth")
    # 5.3 效果栈可以从 Group Input 接收前一个效果的画面，保持该链路。
    if not image.is_linked and node is None:
        group_input = next((n for n in tree.nodes if n.bl_idname == "NodeGroupInput"
                            and socket(n.outputs, "Image") is not None), None)
        if group_input is not None:
            image = group_input.outputs["Image"]
    # 先记录原 Image 的下游；保留色彩调整、File Output、Viewer 等已有处理。
    excluded = {n for n in (node, get_material_node(tree), _crypto_node(tree, "ID", OBJ_NAME)) if n}
    destinations = [link.to_socket for link in image.links if link.to_node not in excluded]
    if not destinations and node is None:
        destinations = [_output_socket(tree, (render.location.x + 950, render.location.y))]
    if node is None:
        group = load_group()
        node = tree.nodes.new("CompositorNodeGroup")
        node.node_tree = group
        node.name = NODE_NAME
        node.label = "AUTO BLEND"
        node.width = 220
        node.location = (render.location.x + 600, render.location.y)
    if node.node_tree is None:
        node.node_tree = load_group()
    for name, suffix, target, output_name, y in (
            (MAT_NAME, "CryptoMaterial", "Matte", "Matte", -150),
            (OBJ_NAME, "CryptoObject", "ID", "Pick", -400)):
        target_socket = _required(node.inputs, target)
        crypto = target_socket.links[0].from_node if target_socket.is_linked else tree.nodes.get(name)
        if crypto is not None and crypto.bl_idname != "CompositorNodeCryptomatteV2":
            # 用户自接的 Matte/ID 保持原样。
            continue
        if crypto is None:
            crypto = tree.nodes.new("CompositorNodeCryptomatteV2")
            crypto.name = name
            crypto.location = (render.location.x + 300, render.location.y + y)
        crypto.scene = context.scene
        crypto.source = "RENDER"
        crypto.layer_name = layer.name + "." + suffix
        crypto_image = _required(crypto.inputs, "Image")
        if not crypto_image.is_linked:
            tree.links.new(image, crypto_image)
        tree.links.new(_required(crypto.outputs, output_name), target_socket)
    if not _required(node.inputs, "Image").is_linked:
        tree.links.new(image, node.inputs["Image"])
    if not _required(node.inputs, "Depth").is_linked:
        tree.links.new(depth, node.inputs["Depth"])
    for dest in destinations:
        tree.links.new(_required(node.outputs, "Image"), dest)
    return node


class AUTOBLEND_OT_setup_visn(bpy.types.Operator):
    bl_idname = "render.autoblend_setup_visn"
    bl_label = "初始化 AutoBlend"
    bl_description = "接入画面空间物体融合，保留已有合成节点及参数"
    bl_options = {"REGISTER", "UNDO"}

    enable_compositor: BoolProperty(name="启用合成器", default=True)
    enable_viewport_compositor: BoolProperty(name="启用当前视图合成器", default=True)
    enable_gpu_compositing: BoolProperty(name="GPU 合成（完整精度）", default=True)
    enable_z_pass: BoolProperty(name="启用深度通道", default=True)
    enable_cryptomatte: BoolProperty(name="启用物体和材质 Cryptomatte", default=True)
    setup_nodes: BoolProperty(name="接入 AutoBlend 节点", default=True)

    def execute(self, context):
        try:
            scene = context.scene
            tree = compositor_tree(scene)
            if self.setup_nodes and tree is None and not self.enable_compositor:
                raise ValueError("尚无合成器，请勾选启用合成器")
            source = render_source(tree, get_autoblend_node(tree), scene, context.view_layer) if tree else None
            layer = source_layer(context, source) if source else context.view_layer
            if self.setup_nodes:
                if not (self.enable_z_pass or layer.use_pass_z):
                    raise ValueError("AutoBlend 需要深度通道")
                if not (self.enable_cryptomatte or (
                        layer.use_pass_cryptomatte_material and layer.use_pass_cryptomatte_object)):
                    raise ValueError("AutoBlend 需要物体和材质 Cryptomatte 通道")
                load_group()  # 在改场景前验证资源可用。
            if self.enable_compositor:
                tree = compositor_tree(scene, create=True)
                if hasattr(scene.render, "use_compositing"):
                    scene.render.use_compositing = True
                effect = compositor_effect(scene)
                if effect is not None:
                    effect.enable_for_render = True
                    if self.enable_viewport_compositor:
                        effect.enable_for_preview = True
            if self.enable_z_pass:
                layer.use_pass_z = True
            if self.enable_cryptomatte:
                layer.use_pass_cryptomatte_object = True
                layer.use_pass_cryptomatte_material = True
            if hasattr(layer, "update_render_passes"):
                layer.update_render_passes()
            if self.setup_nodes:
                tree = _editable_tree(scene)
                setup_nodes(context, tree, layer)
            shading = getattr(context.space_data, "shading", None)
            if self.enable_viewport_compositor and shading is not None:
                shading.use_compositor = "ALWAYS"
            if self.enable_gpu_compositing:
                if hasattr(scene.render, "compositor_device"):
                    scene.render.compositor_device = "GPU"
                if hasattr(scene.render, "compositor_precision"):
                    scene.render.compositor_precision = "FULL"
        except (ValueError, RuntimeError, TypeError, AttributeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "AutoBlend 已初始化；请选择物体并加入材质")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        col = self.layout.column(align=True)
        for name in ("enable_compositor", "enable_viewport_compositor", "enable_gpu_compositing",
                     "enable_z_pass", "enable_cryptomatte", "setup_nodes"):
            col.prop(self, name)


class AUTOBLEND_OT_mask_visn(bpy.types.Operator):
    bl_idname = "render.autoblend_mask_visn"
    bl_label = "创建 AutoBlend 遮罩"
    bl_description = "使用 Position 通道创建 Noise 或 Voronoi 遮罩"
    bl_options = {"REGISTER", "UNDO"}

    mask_type: EnumProperty(name="遮罩类型", items=(
        ("NOISE", "Noise 噪波", ""), ("VORONOI", "Voronoi", "")))

    @classmethod
    def poll(cls, context):
        return get_autoblend_node(compositor_tree(context.scene)) is not None

    def execute(self, context):
        try:
            tree = _editable_tree(context.scene)
            node = get_autoblend_node(tree)
            render = render_source(tree, node, context.scene, context.view_layer)
            if render is None:
                raise ValueError("没有找到 AutoBlend 的 Render Layers 节点")
            layer = source_layer(context, render)
            layer.use_pass_position = True
            layer.update_render_passes()
            position = _required(render.outputs, "Position")
            mask_input = _required(node.inputs, "Mask")
            kind = "ShaderNodeTexNoise" if self.mask_type == "NOISE" else "ShaderNodeTexVoronoi"
            old = mask_input.links[0].from_node if mask_input.is_linked else None
            mask = old if old and old.name.startswith(MASK_NAME) and old.bl_idname == kind else None
            if mask is None:
                mask = tree.nodes.new(kind)
                mask.name = MASK_NAME
                mask.label = "AutoBlend Mask"
                mask.inputs["Scale"].default_value = 15
                if self.mask_type == "VORONOI" and hasattr(mask, "normalize"):
                    mask.normalize = True
                mask.location = (render.location.x + 350, render.location.y - 700)
            factor = _required(mask.outputs, "Factor", "Fac") if self.mask_type == "NOISE" else _required(mask.outputs, "Distance")
            tree.links.new(position, _required(mask.inputs, "Vector"))
            tree.links.new(factor, mask_input)
            if old and old != mask and old.name.startswith(MASK_NAME) and not any(s.is_linked for s in old.outputs):
                tree.nodes.remove(old)
        except (ValueError, RuntimeError, TypeError, AttributeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "AutoBlend 遮罩已接入")
        return {"FINISHED"}


def _material_names(context):
    return list(dict.fromkeys(slot.material.name for obj in context.selected_objects
                              for slot in obj.material_slots if slot.material is not None))


def _change_materials(operator, context, remove=False):
    try:
        selected = _material_names(context)
        if not selected:
            raise ValueError("请选择至少一个带材质的物体")
        tree = _editable_tree(context.scene)
        crypto = get_material_node(tree)
        if crypto is None:
            raise ValueError("没有找到材质 Cryptomatte 节点，请先初始化 AutoBlend")
        ids = _matte_tokens(crypto.matte_id)
        original_count = len(ids)
        selected_hashes = {_name_hash(name) for name in selected}
        before = {_token_hash(token) for token in ids}
        if remove:
            ids = [i for i in ids if _token_hash(i) not in selected_hashes]
        else:
            for name in selected:
                hashed = _name_hash(name)
                if hashed not in before:
                    ids.append(_matte_token(name))
                    before.add(hashed)
        changed = abs(len(ids) - original_count)
        crypto.matte_id = ",".join(ids)
    except (ValueError, RuntimeError, TypeError, AttributeError) as exc:
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}
    operator.report({"INFO"}, f"{'移除' if remove else '加入'} {changed} 个材质")
    return {"FINISHED"}


def _name_hash(name):
    """Cryptomatte 的 MurmurHash3_32/uint32_to_float32（与 Blender 源码一致）。"""
    data = name.encode("utf-8")
    value = 0
    mask = 0xFFFFFFFF

    def rotate(x, bits):
        return ((x << bits) | (x >> (32 - bits))) & mask

    def mix(k):
        return (rotate((k * 0xCC9E2D51) & mask, 15) * 0x1B873593) & mask

    end = len(data) // 4 * 4
    for offset in range(0, end, 4):
        value ^= mix(int.from_bytes(data[offset:offset + 4], "little"))
        value = (rotate(value, 13) * 5 + 0xE6546B64) & mask
    if end < len(data):
        value ^= mix(int.from_bytes(data[end:], "little"))
    value ^= len(data)
    value ^= value >> 16
    value = (value * 0x85EBCA6B) & mask
    value ^= value >> 13
    value = (value * 0xC2B2AE35) & mask
    value ^= value >> 16
    exponent = (value >> 23) & 255
    if exponent in (0, 255):
        value ^= 1 << 23
    return struct.unpack("<f", struct.pack("<I", value))[0]


def _token_hash(token):
    if token.startswith("<") and token.endswith(">"):
        try:
            return struct.unpack("<f", struct.pack("<f", float(token[1:-1])))[0]
        except (ValueError, OverflowError):
            pass
    return _name_hash(token)


def _matte_token(name):
    # Blender matte_id 按逗号分割且修剪首尾空格，不支持反斜线转义。
    # 这类名称改用原生 <float ID> 格式，避免选中错误的材质。
    if "," in name or name != name.strip(" ") or (name.startswith("<") and name.endswith(">")):
        return f"<{_name_hash(name):.9g}>"
    return name


def _matte_tokens(value):
    return list(dict.fromkeys(token.strip(" ") for token in value.split(",") if token.strip(" ")))


class AUTOBLEND_OT_add_visn(bpy.types.Operator):
    bl_idname = "render.autoblend_add_visn"
    bl_label = "加入选中物体材质"
    bl_description = "按材质加入融合名单；共用这些材质的物体一起生效"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _change_materials(self, context)


class AUTOBLEND_OT_remove_visn(bpy.types.Operator):
    bl_idname = "render.autoblend_remove_visn"
    bl_label = "移除选中物体材质"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _change_materials(self, context, remove=True)


class AUTOBLEND_OT_upgrade_visn(bpy.types.Operator):
    bl_idname = "render.autoblend_upgrade_visn"
    bl_label = "升级 AutoBlend 节点"
    bl_description = "换成内置 1.1 节点，按名称保留已有参数和连线"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return get_autoblend_node(compositor_tree(context.scene)) is not None

    def execute(self, context):
        try:
            group = load_group()
            tree = _editable_tree(context.scene)
            node = get_autoblend_node(tree)
            values = {s.name: s.default_value[:] if hasattr(s.default_value, "__len__") else s.default_value
                      for s in node.inputs if hasattr(s, "default_value")}
            inputs = [(link.from_socket, link.to_socket.name, link.is_muted) for link in tree.links if link.to_node == node]
            outputs = [(link.from_socket.name, link.to_socket, link.is_muted) for link in tree.links if link.from_node == node]
            node.node_tree = group
            for name, value in values.items():
                target = socket(node.inputs, name)
                if target is not None and hasattr(target, "default_value"):
                    target.default_value = value
            for source, name, muted in inputs:
                target = socket(node.inputs, name)
                if target is not None:
                    tree.links.new(source, target).is_muted = muted
            for name, target, muted in outputs:
                source = socket(node.outputs, name)
                if source is not None:
                    tree.links.new(source, target).is_muted = muted
        except (ValueError, RuntimeError, TypeError, AttributeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "AutoBlend 已升级为 1.1")
        return {"FINISHED"}


_CLASSES = (AUTOBLEND_OT_setup_visn, AUTOBLEND_OT_mask_visn, AUTOBLEND_OT_add_visn,
            AUTOBLEND_OT_remove_visn, AUTOBLEND_OT_upgrade_visn)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
