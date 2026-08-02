# 六面投射（v2 · 合并自 Codex 的六向贴图烘焙助手，页面做了收纳）
# 六向平滑投射 + 每面独立微调(实时预览) + 最终UV + Albedo烘焙 + 最终材质
# 兼容旧场景：物体自定义属性 sixway_source_material / sixway_final_material
# 和材质名 SWB_ 前缀都与独立版一致，旧工程直接接着用
# （合并自 Pond/sixproj.py：逻辑层；面板在 ui/pond/panels/sixproj.py）
import os

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

FACES = (
    ("top", "顶部"),
    ("bottom", "底部"),
    ("right", "右侧"),
    ("left", "左侧"),
    ("front", "正面"),
    ("back", "背面"),
)
AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"}


def active_mesh(context):
    obj = context.active_object
    return obj if obj and obj.type == "MESH" else None


def socket_by_name(node, name):
    return next((s for s in node.inputs if s.name == name), None)


def set_socket(node, name, value):
    s = socket_by_name(node, name)
    if s is not None:
        s.default_value = value


def selected_axes(settings):
    thickness = AXIS_INDEX[settings.thickness_axis]
    length = AXIS_INDEX[settings.length_axis]
    if thickness == length:
        raise ValueError("厚度轴和长度轴不能相同")
    width = next(i for i in (0, 1, 2) if i not in {thickness, length})
    return thickness, length, width


def face_path(settings, key):
    return bpy.path.abspath(getattr(settings, f"{key}_path"))


def missing_faces(settings):
    out = []
    for key, label in FACES:
        p = face_path(settings, key)
        if not p or not os.path.isfile(p):
            out.append((key, label))
    return out


def validate_images(settings):
    miss = missing_faces(settings)
    if miss:
        raise ValueError("缺少贴图：" + "、".join(l for _k, l in miss))


def projected_vector(nodes, links, separated, u_axis, v_axis, settings, key, y):
    u = separated.outputs[u_axis]
    v = separated.outputs[v_axis]
    combine = nodes.new("ShaderNodeCombineXYZ")
    combine.name = f"原始投射坐标_{key}"
    combine.location = (-850, y)
    links.new(u, combine.inputs["X"])
    links.new(v, combine.inputs["Y"])

    sub = nodes.new("ShaderNodeVectorMath")
    sub.operation = "SUBTRACT"
    sub.location = (-650, y)
    sub.inputs[1].default_value = (0.5, 0.5, 0.0)
    links.new(combine.outputs[0], sub.inputs[0])

    mapping = nodes.new("ShaderNodeMapping")
    mapping.name = f"图片变换_{key}"
    mapping.label = "可移动／旋转／缩放"
    mapping.vector_type = "POINT"
    mapping.location = (-430, y)
    flip_u = -1.0 if getattr(settings, f"{key}_flip_u") else 1.0
    flip_v = -1.0 if getattr(settings, f"{key}_flip_v") else 1.0
    mapping.inputs["Location"].default_value = (
        getattr(settings, f"{key}_offset_u"),
        getattr(settings, f"{key}_offset_v"), 0.0)
    mapping.inputs["Rotation"].default_value[2] = getattr(settings, f"{key}_rotation")
    mapping.inputs["Scale"].default_value = (
        getattr(settings, f"{key}_scale_u") * flip_u,
        getattr(settings, f"{key}_scale_v") * flip_v, 1.0)
    links.new(sub.outputs[0], mapping.inputs["Vector"])

    add = nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    add.name = f"投射坐标_{key}"
    add.location = (-210, y)
    add.inputs[1].default_value = (0.5, 0.5, 0.0)
    links.new(mapping.outputs["Vector"], add.inputs[0])
    return add.outputs[0]


def direction_weight(nodes, links, normal_xyz, axis, positive, power, y, label):
    source = normal_xyz.outputs[axis]
    if not positive:
        neg = nodes.new("ShaderNodeMath")
        neg.operation = "MULTIPLY"
        neg.location = (-790, y)
        neg.inputs[1].default_value = -1.0
        links.new(source, neg.inputs[0])
        source = neg.outputs[0]

    mx = nodes.new("ShaderNodeMath")
    mx.operation = "MAXIMUM"
    mx.location = (-610, y)
    mx.inputs[1].default_value = 0.0
    links.new(source, mx.inputs[0])

    weight = nodes.new("ShaderNodeMath")
    weight.operation = "POWER"
    weight.name = f"方向权重_{label}"
    weight.location = (-430, y)
    weight.inputs[1].default_value = power
    links.new(mx.outputs[0], weight.inputs[0])
    return weight.outputs[0]


def build_projection_material(obj, settings):
    validate_images(settings)
    thickness, length, width = selected_axes(settings)
    material_name = f"SWB_六向投射_{obj.name}"
    material = bpy.data.materials.get(material_name) or bpy.data.materials.new(material_name)
    material.use_nodes = True
    material["sixway_baker_source"] = True
    tree = material.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (1120, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.name = "烘焙源_Emission"
    emission.location = (900, 0)
    emission.inputs["Strength"].default_value = 1.0
    links.new(emission.outputs[0], output.inputs["Surface"])

    coordinates = nodes.new("ShaderNodeTexCoord")
    coordinates.name = "局部投射坐标"
    coordinates.location = (-1450, 100)
    generated_xyz = nodes.new("ShaderNodeSeparateXYZ")
    generated_xyz.location = (-1250, 300)
    links.new(coordinates.outputs["Generated"], generated_xyz.inputs[0])

    normal_transform = nodes.new("ShaderNodeVectorTransform")
    normal_transform.vector_type = "NORMAL"
    normal_transform.convert_from = "WORLD"
    normal_transform.convert_to = "OBJECT"
    normal_transform.location = (-1250, -500)
    links.new(coordinates.outputs["Normal"], normal_transform.inputs["Vector"])
    normal_xyz = nodes.new("ShaderNodeSeparateXYZ")
    normal_xyz.location = (-1040, -500)
    links.new(normal_transform.outputs["Vector"], normal_xyz.inputs[0])

    definitions = {
        "top": (thickness, True, length, width),
        "bottom": (thickness, False, length, width),
        "right": (width, True, length, thickness),
        "left": (width, False, length, thickness),
        "front": (length, True, width, thickness),
        "back": (length, False, width, thickness),
    }

    weighted_colors = []
    weights = []
    for index, (key, label) in enumerate(FACES):
        normal_axis, positive, u_axis, v_axis = definitions[key]
        y = 650 - index * 220
        vector = projected_vector(nodes, links, generated_xyz, u_axis, v_axis,
                                  settings, key, y)
        image = nodes.new("ShaderNodeTexImage")
        image.name = f"六向贴图_{label}"
        image.label = label
        image.location = (20, y)
        image.image = bpy.data.images.load(face_path(settings, key), check_existing=True)
        image.image.colorspace_settings.name = "sRGB"
        image.interpolation = "Linear"
        image.extension = "EXTEND"
        links.new(vector, image.inputs["Vector"])

        weight = direction_weight(nodes, links, normal_xyz, normal_axis, positive,
                                  settings.blend_power, -760 - index * 105, label)
        scale = nodes.new("ShaderNodeVectorMath")
        scale.operation = "SCALE"
        scale.location = (0, 520 - index * 165)
        links.new(image.outputs["Color"], scale.inputs[0])
        links.new(weight, scale.inputs[3])
        weighted_colors.append(scale.outputs[0])
        weights.append(weight)

    color_sum = weighted_colors[0]
    for index, color in enumerate(weighted_colors[1:]):
        add = nodes.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        add.location = (250, 370 - index * 100)
        links.new(color_sum, add.inputs[0])
        links.new(color, add.inputs[1])
        color_sum = add.outputs[0]

    weight_sum = weights[0]
    for index, weight in enumerate(weights[1:]):
        add = nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add.location = (250, -430 - index * 80)
        links.new(weight_sum, add.inputs[0])
        links.new(weight, add.inputs[1])
        weight_sum = add.outputs[0]

    inverse = nodes.new("ShaderNodeMath")
    inverse.operation = "DIVIDE"
    inverse.location = (500, -380)
    inverse.inputs[0].default_value = 1.0
    links.new(weight_sum, inverse.inputs[1])
    final_color = nodes.new("ShaderNodeVectorMath")
    final_color.operation = "SCALE"
    final_color.name = "六向融合颜色"
    final_color.location = (680, 0)
    links.new(color_sum, final_color.inputs[0])
    links.new(inverse.outputs[0], final_color.inputs[3])
    links.new(final_color.outputs[0], emission.inputs["Color"])

    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj["sixway_source_material"] = material.name
    return material


def build_final_material(obj, image, settings):
    name = f"SWB_最终材质_{obj.name}"
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    material["sixway_baker_final"] = True
    tree = material.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (800, 80)
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (520, 80)
    principled.name = "最终材质"
    set_socket(principled, "Metallic", 0.0)
    set_socket(principled, "Roughness", settings.roughness)
    set_socket(principled, "IOR", 1.36)
    set_socket(principled, "Subsurface Weight", settings.sss_weight)
    set_socket(principled, "Subsurface Scale", 0.025)
    set_socket(principled, "Subsurface Anisotropy", 0.15)
    set_socket(principled, "Specular IOR Level", 0.34)
    set_socket(principled, "Coat Weight", settings.coat_weight)
    set_socket(principled, "Coat Roughness", 0.12)
    radius = socket_by_name(principled, "Subsurface Radius")
    if radius is not None:
        radius.default_value = (1.0, 0.32, 0.18)
    links.new(principled.outputs[0], output.inputs["Surface"])

    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = settings.final_uv_name
    uv.location = (-500, 180)
    texture = nodes.new("ShaderNodeTexImage")
    texture.name = "最终Albedo"
    texture.image = image
    texture.interpolation = "Linear"
    texture.extension = "EXTEND"
    texture.location = (-260, 180)
    links.new(uv.outputs["UV"], texture.inputs["Vector"])
    links.new(texture.outputs["Color"], principled.inputs["Base Color"])

    coordinates = nodes.new("ShaderNodeTexCoord")
    coordinates.location = (-500, -220)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-270, -220)
    noise.inputs["Scale"].default_value = 150.0
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = 0.7
    links.new(coordinates.outputs["Generated"], noise.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.location = (250, -220)
    bump.inputs["Strength"].default_value = settings.bump_strength
    bump.inputs["Distance"].default_value = 0.006
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    coat_normal = socket_by_name(principled, "Coat Normal")
    if coat_normal is not None:
        links.new(bump.outputs["Normal"], coat_normal)

    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj["sixway_final_material"] = material.name
    return material


def projection_material_for_object(obj):
    if obj is None:
        return None
    name = obj.get("sixway_source_material", "")
    return bpy.data.materials.get(name) if name else None


def show_projection_material(obj, material):
    if obj.active_material != material:
        obj.data.materials.clear()
        obj.data.materials.append(material)


def redraw_viewports(context):
    if context.screen:
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def make_face_transform_update(key):
    def update(self, context):
        obj = active_mesh(context)
        material = projection_material_for_object(obj)
        if material is None or not material.use_nodes:
            return
        mapping = material.node_tree.nodes.get(f"图片变换_{key}")
        if mapping is None:
            return
        flip_u = -1.0 if getattr(self, f"{key}_flip_u") else 1.0
        flip_v = -1.0 if getattr(self, f"{key}_flip_v") else 1.0
        mapping.inputs["Location"].default_value = (
            getattr(self, f"{key}_offset_u"),
            getattr(self, f"{key}_offset_v"), 0.0)
        mapping.inputs["Rotation"].default_value[2] = getattr(self, f"{key}_rotation")
        mapping.inputs["Scale"].default_value = (
            getattr(self, f"{key}_scale_u") * flip_u,
            getattr(self, f"{key}_scale_v") * flip_v, 1.0)
        show_projection_material(obj, material)
        material.node_tree.update_tag()
        redraw_viewports(context)
    return update


def update_blend_power(self, context):
    obj = active_mesh(context)
    material = projection_material_for_object(obj)
    if material is None or not material.use_nodes:
        return
    for _key, label in FACES:
        weight = material.node_tree.nodes.get(f"方向权重_{label}")
        if weight is not None:
            weight.inputs[1].default_value = self.blend_power
    show_projection_material(obj, material)
    material.node_tree.update_tag()
    redraw_viewports(context)


class POND_PG_sixway(bpy.types.PropertyGroup):
    source_dir: StringProperty(name="六面图文件夹", subtype="DIR_PATH")
    top_path: StringProperty(name="顶部", subtype="FILE_PATH")
    bottom_path: StringProperty(name="底部", subtype="FILE_PATH")
    right_path: StringProperty(name="右侧", subtype="FILE_PATH")
    left_path: StringProperty(name="左侧", subtype="FILE_PATH")
    front_path: StringProperty(name="正面", subtype="FILE_PATH")
    back_path: StringProperty(name="背面", subtype="FILE_PATH")
    show_paths: BoolProperty(name="展开六张图的路径", default=False)

    active_face: EnumProperty(
        name="当前面",
        items=[(k, l, "") for k, l in FACES], default="top")

    thickness_axis: EnumProperty(
        name="厚度轴", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")
    length_axis: EnumProperty(
        name="长度轴", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="Z")
    blend_power: FloatProperty(
        name="圆角融合锐度", default=4.0, min=1.0, max=16.0, update=update_blend_power)

    final_uv_name: StringProperty(name="最终 UV", default="UV_最终烘焙")
    use_existing_uv: BoolProperty(
        name="沿用现有UV排布",
        description="直接复制当前活动UV层作为最终UV，不重新展开（保留手工排布）",
        default=True)
    resolution: EnumProperty(
        name="分辨率",
        items=(("1024", "1K", ""), ("2048", "2K", ""), ("4096", "4K", "")),
        default="4096")
    margin: IntProperty(name="烘焙扩边", default=32, min=2, max=128)
    output_dir: StringProperty(name="输出文件夹", subtype="DIR_PATH")
    output_name: StringProperty(name="输出名称", default="T_六向烘焙_Albedo")

    show_matopts: BoolProperty(name="材质微调", default=False)
    roughness: FloatProperty(name="粗糙度", default=0.30, min=0.0, max=1.0)
    sss_weight: FloatProperty(name="SSS", default=0.09, min=0.0, max=1.0)
    coat_weight: FloatProperty(name="湿润薄层", default=0.16, min=0.0, max=1.0)
    bump_strength: FloatProperty(name="微凹凸", default=0.10, min=0.0, max=1.0)


def add_face_controls(cls, key):
    annotations = cls.__annotations__
    update = make_face_transform_update(key)
    annotations[f"{key}_rotation"] = FloatProperty(
        name="旋转", subtype="ANGLE", default=0.0,
        min=-6.283185, max=6.283185, update=update)
    annotations[f"{key}_offset_u"] = FloatProperty(
        name="U 位移", default=0.0, soft_min=-1.0, soft_max=1.0, update=update)
    annotations[f"{key}_offset_v"] = FloatProperty(
        name="V 位移", default=0.0, soft_min=-1.0, soft_max=1.0, update=update)
    annotations[f"{key}_scale_u"] = FloatProperty(
        name="U 缩放", default=1.0, min=0.01, soft_max=4.0, update=update)
    annotations[f"{key}_scale_v"] = FloatProperty(
        name="V 缩放", default=1.0, min=0.01, soft_max=4.0, update=update)
    annotations[f"{key}_flip_u"] = BoolProperty(name="水平翻转", default=False, update=update)
    annotations[f"{key}_flip_v"] = BoolProperty(name="垂直翻转", default=False, update=update)


for _key, _label in FACES:
    add_face_controls(POND_PG_sixway, _key)


class POND_OT_swb_scan_folder(bpy.types.Operator):
    """按文件名里的「顶部/底部/右侧/左侧/正面/背面」自动认六张图"""
    bl_idname = "pond.swb_scan_folder"
    bl_label = "从文件夹识别六面图"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.pond_sixway
        folder = bpy.path.abspath(settings.source_dir)
        if not os.path.isdir(folder):
            self.report({"ERROR"}, "请选择有效文件夹")
            return {"CANCELLED"}
        files = [os.path.join(folder, name) for name in os.listdir(folder)
                 if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS]
        score_words = ("统一", "投射", "重制")
        found = 0
        for key, label in FACES:
            matches = [p for p in files if label in os.path.basename(p)]
            if matches:
                matches.sort(key=lambda p: next(
                    (i for i, w in enumerate(score_words) if w in os.path.basename(p)),
                    len(score_words)))
                setattr(settings, f"{key}_path", matches[0])
                found += 1
        self.report({"INFO"}, f"已识别 {found}/6 张贴图")
        return {"FINISHED"}


class POND_OT_swb_setup(bpy.types.Operator):
    """给选中网格搭六向平滑投射材质（重复点=按当前参数刷新）"""
    bl_idname = "pond.swb_setup"
    bl_label = "建立／刷新六向投射"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "请先选择一个网格物体")
            return {"CANCELLED"}
        try:
            material = build_projection_material(obj, context.scene.pond_sixway)
        except (ValueError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已建立 {material.name}")
        return {"FINISHED"}


class POND_OT_swb_final_uv(bpy.types.Operator):
    """生成最终烘焙用的 UV（可沿用现有排布或重新智能展开）"""
    bl_idname = "pond.swb_final_uv"
    bl_label = "生成／重置最终 UV"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({"ERROR"}, "请先选择一个网格物体")
            return {"CANCELLED"}
        settings = context.scene.pond_sixway
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        source_uv = obj.data.uv_layers.active
        existing = obj.data.uv_layers.get(settings.final_uv_name)
        if existing:
            if source_uv is existing:
                source_uv = None
            obj.data.uv_layers.remove(existing)
        if settings.use_existing_uv and (source_uv or obj.data.uv_layers.active):
            src = source_uv or obj.data.uv_layers.active
            uv = obj.data.uv_layers.new(name=settings.final_uv_name)
            for i, loop_uv in enumerate(src.data):
                uv.data[i].uv = loop_uv.uv
            obj.data.uv_layers.active = uv
            self.report({"INFO"}, "已复制现有UV排布到 " + settings.final_uv_name)
            return {"FINISHED"}
        uv = obj.data.uv_layers.new(name=settings.final_uv_name)
        obj.data.uv_layers.active = uv
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=settings.margin / int(settings.resolution))
        bpy.ops.object.mode_set(mode="OBJECT")
        self.report({"INFO"}, f"已生成 {settings.final_uv_name}")
        return {"FINISHED"}


VIEW_AXIS_MAP = {
    (0, True): "RIGHT", (0, False): "LEFT",
    (1, True): "BACK", (1, False): "FRONT",
    (2, True): "TOP", (2, False): "BOTTOM",
}


class POND_OT_swb_view_face(bpy.types.Operator):
    """把视口转到这张贴图投射的那一面（正对屏幕的就是它）"""
    bl_idname = "pond.swb_view_face"
    bl_label = "看这一面"
    bl_options = {"REGISTER"}

    face_key: StringProperty()

    def execute(self, context):
        settings = context.scene.pond_sixway
        try:
            thickness, length, width = selected_axes(settings)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        directions = {
            "top": (thickness, True), "bottom": (thickness, False),
            "right": (width, True), "left": (width, False),
            "front": (length, True), "back": (length, False),
        }
        axis, positive = directions[self.face_key]
        view_type = VIEW_AXIS_MAP[(axis, positive)]
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with context.temp_override(area=area, region=region):
                    bpy.ops.view3d.view_axis(type=view_type, align_active=True)
                break
        self.report({"INFO"}, "现在正对着你的就是: " + dict(FACES)[self.face_key])
        return {"FINISHED"}


class POND_OT_swb_bake(bpy.types.Operator):
    """把六向投射烘成单张 Albedo，并自动搭好最终材质"""
    bl_idname = "pond.swb_bake"
    bl_label = "烘焙单张 Albedo"
    bl_options = {"REGISTER"}

    def execute(self, context):
        obj = active_mesh(context)
        settings = context.scene.pond_sixway
        if obj is None:
            self.report({"ERROR"}, "请先选择一个网格物体")
            return {"CANCELLED"}
        source_name = obj.get("sixway_source_material")
        source = bpy.data.materials.get(source_name) if source_name else None
        uv = obj.data.uv_layers.get(settings.final_uv_name)
        if source is None:
            self.report({"ERROR"}, "请先建立六向投射")
            return {"CANCELLED"}
        if uv is None:
            self.report({"ERROR"}, "请先生成最终 UV")
            return {"CANCELLED"}
        output_dir = bpy.path.abspath(settings.output_dir)
        if not output_dir:
            self.report({"ERROR"}, "请选择输出文件夹")
            return {"CANCELLED"}
        os.makedirs(output_dir, exist_ok=True)

        obj.data.uv_layers.active = uv
        obj.data.materials.clear()
        obj.data.materials.append(source)
        tree = source.node_tree
        target = tree.nodes.get("烘焙目标") or tree.nodes.new("ShaderNodeTexImage")
        target.name = "烘焙目标"
        target.label = "活动烘焙目标"
        size = int(settings.resolution)
        image = bpy.data.images.get(settings.output_name)
        if image and tuple(image.size) != (size, size):
            bpy.data.images.remove(image)
            image = None
        if image is None:
            image = bpy.data.images.new(settings.output_name, width=size, height=size, alpha=False)
        image.generated_color = (0.5, 0.1, 0.05, 1.0)
        target.image = image
        for node in tree.nodes:
            node.select = False
        target.select = True
        tree.nodes.active = target

        scene = context.scene
        prev_engine = scene.render.engine
        try:
            scene.render.engine = "CYCLES"
        except TypeError:
            self.report({"ERROR"}, "Cycles 不可用，请先启用 Cycles")
            return {"CANCELLED"}
        prev_samples = scene.cycles.samples
        scene.cycles.samples = 1
        scene.render.bake.use_selected_to_active = False
        scene.render.bake.use_clear = True
        scene.render.bake.margin = settings.margin
        try:
            bpy.ops.object.bake(type="EMIT", margin=settings.margin, use_clear=True)
        finally:
            scene.cycles.samples = prev_samples
            try:
                scene.render.engine = prev_engine
            except TypeError:
                pass

        path = os.path.join(output_dir, settings.output_name + ".png")
        image.filepath_raw = path
        image.file_format = "PNG"
        image.save()
        build_final_material(obj, image, settings)
        self.report({"INFO"}, f"烘焙完成：{path}")
        return {"FINISHED"}


class POND_OT_swb_show_source(bpy.types.Operator):
    """切回六向投射预览材质"""
    bl_idname = "pond.swb_show_source"
    bl_label = "切回投射预览"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_mesh(context)
        material = bpy.data.materials.get(obj.get("sixway_source_material", "")) if obj else None
        if material is None:
            self.report({"ERROR"}, "当前物体没有六向投射材质")
            return {"CANCELLED"}
        obj.data.materials.clear()
        obj.data.materials.append(material)
        return {"FINISHED"}


class POND_OT_swb_show_final(bpy.types.Operator):
    """切回烘焙后的最终材质"""
    bl_idname = "pond.swb_show_final"
    bl_label = "切回最终材质"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_mesh(context)
        material = bpy.data.materials.get(obj.get("sixway_final_material", "")) if obj else None
        if material is None:
            self.report({"ERROR"}, "当前物体还没有最终材质")
            return {"CANCELLED"}
        obj.data.materials.clear()
        obj.data.materials.append(material)
        return {"FINISHED"}


_classes = (
    POND_PG_sixway,
    POND_OT_swb_scan_folder,
    POND_OT_swb_setup,
    POND_OT_swb_final_uv,
    POND_OT_swb_view_face,
    POND_OT_swb_bake,
    POND_OT_swb_show_source,
    POND_OT_swb_show_final,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pond_sixway = PointerProperty(type=POND_PG_sixway)


def unregister():
    del bpy.types.Scene.pond_sixway
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
