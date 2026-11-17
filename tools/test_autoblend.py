"""隔离实测：blender --background --factory-startup --python-exit-code 1 --python tools/test_autoblend.py"""
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
PKG = ROOT.name
addon = addon_utils.enable(PKG, default_set=False)
assert addon is not None
ab = importlib.import_module(PKG + ".core.autoblend")
ui = importlib.import_module(PKG + ".ui")
assert ab.compositor_tree(bpy.context.scene) is None  # 注册没有改场景。
scene = bpy.context.scene
layer = bpy.context.view_layer


def success(op, **kwargs):
    assert op(**kwargs) == {"FINISHED"}


def failure(op, **kwargs):
    try:
        result = op(**kwargs)
        assert result == {"CANCELLED"}
    except RuntimeError as exc:
        # Blender 把 operator 的 ERROR report 提升为调用异常。
        print("EXPECTED_FAILURE", str(exc))


failure(bpy.ops.render.autoblend_add_visn)
failure(bpy.ops.render.autoblend_setup_visn, enable_compositor=False)
failure(bpy.ops.render.autoblend_setup_visn, enable_z_pass=False)
success(bpy.ops.render.autoblend_setup_visn)
tree = ab.compositor_tree(scene)
node = ab.get_autoblend_node(tree)
assert tree.bl_idname == "CompositorNodeTree"
assert node.node_tree.name == ab.GROUP_NAME
assert layer.use_pass_z and layer.use_pass_cryptomatte_material and layer.use_pass_cryptomatte_object
assert scene.render.compositor_device == "GPU" and scene.render.compositor_precision == "FULL"
output = next(n for n in tree.nodes if n.bl_idname == "NodeGroupOutput")
assert output.inputs["Image"].links[0].from_node == node
crypto = ab.get_material_node(tree)
assert crypto.layer_name == layer.name + ".CryptoMaterial"
assert tree.nodes[ab.OBJ_NAME].layer_name == layer.name + ".CryptoObject"
node.inputs["Blend Distance"].default_value = 0.123
crypto.matte_id = "Existing"
count = len(tree.nodes)
success(bpy.ops.render.autoblend_setup_visn)
assert len(tree.nodes) == count

# 5.3 效果栈：切换其他活跃效果后仍找到原 AutoBlend，不堆叠或改顺序。
if hasattr(scene, "compositor_effects"):
    effect = ab.compositor_effect(scene)
    extra = scene.compositor_effects.new(name="Other Active Effect")
    extra.node_group = bpy.data.node_groups.new("Other Effect Tree", "CompositorNodeTree")
    assert extra.is_active
    assert ab.compositor_tree(scene) == tree
    effect_count = len(scene.compositor_effects)
    success(bpy.ops.render.autoblend_setup_visn)
    assert len(scene.compositor_effects) == effect_count
    assert extra.is_active and extra.node_group.name == "Other Effect Tree"
    assert ab.compositor_effect(scene) == effect
    scene.compositor_effects.remove(extra)
assert abs(node.inputs["Blend Distance"].default_value - 0.123) < 1e-6
assert crypto.matte_id == "Existing"
crypto.name = "Renamed Material Cryptomatte"
object_crypto = tree.nodes[ab.OBJ_NAME]
object_crypto.name = "Renamed Object Cryptomatte"
success(bpy.ops.render.autoblend_setup_visn)
assert len(tree.nodes) == count
assert object_crypto.inputs["Image"].links[0].from_node != node
other_layer = scene.view_layers.new("Other Working View Layer")
assert ab.render_source(tree, node, scene, other_layer).layer == layer.name
scene.view_layers.remove(other_layer)

# GPU 开关和视图合成开关独立；避免原插件的错误条件。
scene.render.compositor_device = "CPU"
success(bpy.ops.render.autoblend_setup_visn, enable_gpu_compositing=False)
assert scene.render.compositor_device == "CPU"
success(bpy.ops.render.autoblend_setup_visn, enable_viewport_compositor=False)
assert scene.render.compositor_device == "GPU"

# Noise/Voronoi、重复创建、链接开关和缺失节点保护。
success(bpy.ops.render.autoblend_mask_visn, mask_type="NOISE")
assert layer.use_pass_position
mask = node.inputs["Mask"].links[0].from_node
assert mask.bl_idname == "ShaderNodeTexNoise"
assert mask.inputs["Vector"].links[0].from_socket.name == "Position"
mask.inputs["Scale"].default_value = 21
count = len(tree.nodes)
success(bpy.ops.render.autoblend_mask_visn, mask_type="NOISE")
assert len(tree.nodes) == count and mask.inputs["Scale"].default_value == 21
node.inputs["Mask"].links[0].is_muted = True
assert node.inputs["Mask"].links[0].is_muted
node.inputs["Mask"].links[0].is_muted = False
success(bpy.ops.render.autoblend_mask_visn, mask_type="VORONOI")
assert len(tree.nodes) == count
assert node.inputs["Mask"].links[0].from_node.bl_idname == "ShaderNodeTexVoronoi"

# 材质去重、空槽和特殊字符；共用同材质的对象仍引用同一数据。
cube = bpy.data.objects["Cube"]
cube.data.materials.clear()
mat = bpy.data.materials.new("AutoBlend, Special\\Name")
cube.data.materials.append(mat)
cube.data.materials.append(mat)
cube.data.materials.append(None)
bpy.ops.object.select_all(action="DESELECT")
cube.select_set(True)
bpy.context.view_layer.objects.active = cube
success(bpy.ops.render.autoblend_add_visn)
assert ab._matte_tokens(crypto.matte_id) == ["Existing", ab._matte_token(mat.name)]
success(bpy.ops.render.autoblend_add_visn)
assert len(ab._matte_tokens(crypto.matte_id)) == 2
success(bpy.ops.render.autoblend_remove_visn)
assert crypto.matte_id == "Existing"
bpy.ops.object.select_all(action="DESELECT")
failure(bpy.ops.render.autoblend_remove_visn)

# 升级时保留输入值、Mask 连线和输出连线。
node.node_tree = node.node_tree.copy()
node.node_tree.name = "_AUTOBLEND_legacy_test"
node.inputs["Mask"].links[0].is_muted = True
success(bpy.ops.render.autoblend_upgrade_visn)
assert node.node_tree.name == ab.GROUP_NAME
assert abs(node.inputs["Blend Distance"].default_value - 0.123) < 1e-6
assert node.inputs["Mask"].is_linked and output.inputs["Image"].links[0].from_node == node
assert node.inputs["Mask"].links[0].is_muted
node.inputs["Mask"].links[0].is_muted = False

# 已有合成器多路下游，以及多个场景共用同一合成器。
old_tree = tree
second_scene = bpy.data.scenes.new("AutoBlend Shared Scene")
second_scene.compositing_node_group = old_tree
old_count = len(old_tree.nodes)
success(bpy.ops.render.autoblend_mask_visn, mask_type="NOISE")
tree = ab.compositor_tree(scene)
assert tree != old_tree and second_scene.compositing_node_group == old_tree
assert len(old_tree.nodes) == old_count
assert ab.get_autoblend_node(old_tree).inputs["Mask"].links[0].from_node.bl_idname == "ShaderNodeTexVoronoi"

scene.compositing_node_group = bpy.data.node_groups.new("Existing Pipeline", "CompositorNodeTree")
tree = scene.compositing_node_group
tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
output = tree.nodes.new("NodeGroupOutput")
render = tree.nodes.new("CompositorNodeRLayers")
render.scene = scene
render.layer = layer.name
adjust = tree.nodes.new("CompositorNodeBrightContrast")
viewer = tree.nodes.new("CompositorNodeViewer")
tree.links.new(render.outputs["Image"], adjust.inputs["Image"])
tree.links.new(adjust.outputs["Image"], output.inputs["Image"])
tree.links.new(render.outputs["Image"], viewer.inputs["Image"])
success(bpy.ops.render.autoblend_setup_visn)
node = ab.get_autoblend_node(tree)
assert adjust.inputs["Image"].links[0].from_node == node
assert viewer.inputs["Image"].links[0].from_node == node
assert output.inputs["Image"].links[0].from_node == adjust
count = len(tree.nodes)
success(bpy.ops.render.autoblend_setup_visn)
assert len(tree.nodes) == count

# 不把来自其他管线的输出覆盖掉。
scene.compositing_node_group = bpy.data.node_groups.new("Unrelated Output", "CompositorNodeTree")
tree = scene.compositing_node_group
tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
output = tree.nodes.new("NodeGroupOutput")
rgb = tree.nodes.new("CompositorNodeRGB")
tree.links.new(rgb.outputs[0], output.inputs["Image"])
failure(bpy.ops.render.autoblend_setup_visn)
assert output.inputs["Image"].links[0].from_node == rgb
assert ab.get_autoblend_node(tree) is None

# 5.3 效果的 Group Input 管线保留；Depth/ID 仍来自对应渲染层。
if hasattr(scene, "compositor_effects"):
    effect = ab.compositor_effect(scene)
    tree = bpy.data.node_groups.new("Effect Input Pipeline", "CompositorNodeTree")
    effect.node_group = tree
    tree.interface.new_socket(name="Image", in_out="INPUT", socket_type="NodeSocketColor")
    tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    group_input = tree.nodes.new("NodeGroupInput")
    output = tree.nodes.new("NodeGroupOutput")
    adjust = tree.nodes.new("CompositorNodeBrightContrast")
    tree.links.new(group_input.outputs["Image"], adjust.inputs["Image"])
    tree.links.new(adjust.outputs["Image"], output.inputs["Image"])
    success(bpy.ops.render.autoblend_setup_visn)
    node = ab.get_autoblend_node(tree)
    assert node.inputs["Image"].links[0].from_node == group_input
    assert adjust.inputs["Image"].links[0].from_node == node
    assert output.inputs["Image"].links[0].from_node == adjust

# UI 切换顺序、禁用及热重载：新面板只属于别馆。
ui.apply_mode("BEKKAN")
assert hasattr(bpy.types, "BEKKAN_PT_autoblend")
ui.apply_mode("POND")
assert not hasattr(bpy.types, "BEKKAN_PT_autoblend")
ui.apply_mode("BEKKAN")
assert hasattr(bpy.types, "BEKKAN_PT_autoblend")
icons = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items.keys()
assert all(i in icons for i in ("TOOL_SETTINGS", "FILE_REFRESH", "ERROR", "ADD", "REMOVE"))
addon_utils.disable(PKG, default_set=False)
assert not hasattr(bpy.types, "BEKKAN_PT_autoblend")
importlib.reload(addon)
assert addon_utils.enable(PKG, default_set=False) is not None
addon_utils.disable(PKG, default_set=False)
print("AUTOBLEND_TEST_OK", bpy.app.version_string)
