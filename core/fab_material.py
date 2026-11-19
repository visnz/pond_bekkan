# Fab / Megascans 节点导入：向 Shader Editor 当前编辑层追加本地材质贴图。
# 只在用户确认文件夹后读取图片；register() 不访问场景数据。
from collections import defaultdict
import json
from pathlib import Path
import re

import bpy
from bpy.props import BoolProperty, StringProperty

from .shader_tools import current_material_tree, _layout_level, _node_size


ROLES = ("basecolor", "roughness", "specular", "normal", "displacement", "ao")
LABELS = {"basecolor": "Base Color", "roughness": "Roughness", "specular": "Specular",
          "normal": "Normal", "displacement": "Displacement", "ao": "AO · 未连接"}
EXTENSIONS = {".exr": 0, ".tif": 1, ".tiff": 1, ".png": 2, ".tga": 3, ".jpg": 4, ".jpeg": 4}
MAP_PATTERN = re.compile(
    r"(?:^|[_\-\s.])(base[_\-\s]?colou?r|albedo|diffuse|"
    r"normal(?:[_\-\s]?(?:opengl|directx|ogl|gl|dx))?|displacement|height|"
    r"specular|spec|roughness|rough|ambient[_\-\s]?occlusion|ao)(?=$|[_\-\s.])", re.I)
RESOLUTION_PATTERN = re.compile(r"(?:^|[_\-\s.])(\d+)k(?=$|[_\-\s.])", re.I)


def _parse_texture(path):
    if path.suffix.lower() not in EXTENSIONS:
        return None
    matches = list(MAP_PATTERN.finditer(path.stem))
    if not matches:
        return None
    match = matches[-1]
    token = re.sub(r"[_\-\s]", "", match.group(1).lower())
    if token.startswith("normal"):
        role = "normal"
    elif token in {"albedo", "diffuse", "basecolor", "basecolour"}:
        role = "basecolor"
    elif token in {"height", "displacement"}:
        role = "displacement"
    elif token in {"rough", "roughness"}:
        role = "roughness"
    elif token in {"spec", "specular"}:
        role = "specular"
    else:
        role = "ao"
    size_match = RESOLUTION_PATTERN.search(path.stem) or RESOLUTION_PATTERN.search(path.parent.name)
    resolution = int(size_match.group(1)) if size_match else 0
    # 类型前后可有分辨率后缀；同一材质不同分辨率分组，不混用其他资产的图。
    family = path.stem[:match.start()] + path.stem[match.end():]
    family = RESOLUTION_PATTERN.sub("", family).strip("_- .")
    family = re.sub(r"[_\-\s.]+", "_", family).lower() or path.parent.name.lower()
    directx = token in {"normaldx", "normaldirectx"}
    normal_priority = 0 if token in {"normalgl", "normalogl", "normalopengl"} else 2 if directx else 1
    return role, family, resolution, directx, normal_priority


def discover_textures(directory):
    folder = Path(directory).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("请选择已解压的 Fab 贴图文件夹")
    candidates = list(folder.iterdir())
    # 也接受仅包含 2K/4K 等子目录的父文件夹；不递归扫整个资产库。
    if not any(_parse_texture(p) for p in candidates if p.is_file()):
        candidates = [p for child in sorted(folder.iterdir()) if child.is_dir()
                      and not child.name.startswith(".") for p in child.iterdir()]
    groups = defaultdict(dict)
    for path in sorted(candidates):
        if not path.is_file():
            continue
        parsed = _parse_texture(path)
        if parsed is None:
            continue
        role, family, resolution, directx, normal_priority = parsed
        key = family, resolution
        score = (normal_priority if role == "normal" else 0, EXTENSIONS[path.suffix.lower()], str(path).lower())
        previous = groups[key].get(role)
        if previous is None or score < previous["score"]:
            groups[key][role] = {"path": path, "directx": directx, "score": score}
    usable = {key: maps for key, maps in groups.items() if "basecolor" in maps}
    if not usable:
        raise ValueError("未找到 BaseColor/Albedo 贴图，请选择一套材质的贴图文件夹")
    families = {key[0] for key in usable}
    if len(families) != 1:
        raise ValueError("文件夹包含多套材质，请选择其中一套的贴图文件夹")
    key = max(usable, key=lambda k: (k[1], len(usable[k])))
    maps = usable[key]
    name = key[0].replace("_", " ")
    # Fab 元数据只用于展示名称；maps 常描述 8K 源图，不能据此猜本地下载文件。
    for metadata in sorted(maps["basecolor"]["path"].parent.glob("*.json")):
        try:
            if metadata.stat().st_size > 1024 * 1024:
                continue
            data = json.loads(metadata.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("name"), str) and data["name"].strip():
                name = data["name"].strip()
                break
        except (OSError, UnicodeError, ValueError):
            continue
    return folder, name, key[1], maps


def _socket(sockets, *names):
    for name in names:
        found = next((s for s in sockets if s.name == name or s.identifier == name), None)
        if found is not None:
            return found
    raise ValueError("当前 Blender 缺少所需插座：" + "/".join(names))


def _load_image(path, color_space, created):
    # 可复用色彩空间已正确的图片；不改其他材质正在使用的图片数据。
    for image in bpy.data.images:
        if image.source == "FILE" and image.colorspace_settings.name == color_space:
            absolute = Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()
            if absolute == path:
                return image
    image = bpy.data.images.load(str(path), check_existing=False)
    created.append(image)
    image.colorspace_settings.name = color_space
    if image.size[0] < 1 or image.size[1] < 1:
        raise ValueError("图片无法读取：" + path.name)
    return image


def _arrange_imported_nodes(tree, imported, existing):
    # 只整理新增子图，不移动用户已有节点（含框架中的节点）。
    sizes = {node: _node_size(node, 1.0) for node in imported}
    edges = [(link.from_node, link.to_node, list(link.to_node.inputs).index(link.to_socket))
             for link in tree.links if link.from_node in sizes and link.to_node in sizes]
    positions, _size = _layout_level(imported, sizes, edges, 110.0, 65.0)
    left = max((node.location_absolute.x + _node_size(node, 1.0)[0]
                for node in existing), default=-160.0) + 160.0
    top = max((node.location_absolute.y for node in existing), default=0.0)
    for node, (x, y) in positions.items():
        node.location = (left + x, top + y)


def import_material_nodes(material, tree, name, maps):
    """追加一套节点；失败仅回滚本次节点/图片，原图和输出保持原样。"""
    existing = list(tree.nodes)
    selected = {node: node.select for node in existing}
    active = tree.nodes.active
    outputs = {node: node.is_active_output for node in existing if node.type == 'OUTPUT_MATERIAL'}
    created_images, imported = [], []
    owner = material if hasattr(material, "displacement_method") else getattr(material, "cycles", None)
    old_displacement = getattr(owner, "displacement_method", None)

    def new(type_name):
        node = tree.nodes.new(type_name)
        imported.append(node)
        return node

    def restore_outputs():
        if output is not None and outputs:
            output.is_active_output = False
            for node, was_active in outputs.items():
                node.is_active_output = was_active

    output = None
    try:
        nodes, links = tree.nodes, tree.links
        shader = new("ShaderNodeBsdfPrincipled")
        shader.label = "Fab · " + name
        # 组内只追加可供接入组接口的节点，不塞入无效的材质输出。
        if tree == material.node_tree:
            output = new("ShaderNodeOutputMaterial")
            output.label = "Fab · " + name
            links.new(shader.outputs["BSDF"], output.inputs["Surface"])
            restore_outputs()
        coordinate = new("ShaderNodeTexCoord")
        mapping = new("ShaderNodeMapping")
        mapping.vector_type = "POINT"
        value = new("ShaderNodeValue")
        value.name = "Fab Texture Scale"
        value.label = "统一贴图缩放"
        value.outputs[0].default_value = 1
        links.new(coordinate.outputs["UV"], mapping.inputs["Vector"])
        links.new(value.outputs[0], mapping.inputs["Scale"])
        for role in ROLES:
            if role not in maps:
                continue
            texture = new("ShaderNodeTexImage")
            texture.name = "Fab " + LABELS[role]
            texture.label = LABELS[role]
            texture.width = 280
            texture.image = _load_image(maps[role]["path"], "sRGB" if role == "basecolor" else "Non-Color", created_images)
            links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
            color = texture.outputs["Color"]
            if role == "basecolor":
                links.new(color, _socket(shader.inputs, "Base Color"))
            elif role == "roughness":
                links.new(color, _socket(shader.inputs, "Roughness"))
            elif role == "specular":
                links.new(color, _socket(shader.inputs, "Specular IOR Level", "Specular"))
            elif role == "normal":
                normal = new("ShaderNodeNormalMap")
                normal.space = "TANGENT"
                if maps[role]["directx"]:
                    multiply = new("ShaderNodeVectorMath")
                    multiply.operation = "MULTIPLY"
                    multiply.label = "DirectX 法线 · 翻转绿色"
                    multiply.inputs[1].default_value = (1, -1, 1)
                    add = new("ShaderNodeVectorMath")
                    add.operation = "ADD"
                    add.inputs[1].default_value = (0, 1, 0)
                    links.new(color, multiply.inputs[0])
                    links.new(multiply.outputs["Vector"], add.inputs[0])
                    color = add.outputs["Vector"]
                links.new(color, normal.inputs["Color"])
                links.new(normal.outputs["Normal"], _socket(shader.inputs, "Normal"))
            elif role == "displacement":
                displacement = new("ShaderNodeDisplacement")
                links.new(color, displacement.inputs["Height"])
                if output is not None:
                    links.new(displacement.outputs["Displacement"], output.inputs["Displacement"])
            # AO 只有 Vector 输入连接，颜色输出留空供用户自行使用。
        # 新输出首次接管空材质时保持 Bump Only；已有工程的模式不改。
        if output is not None and not outputs and old_displacement is not None:
            owner.displacement_method = "BUMP"
        _arrange_imported_nodes(tree, imported, existing)
        for node in nodes:
            node.select = node in imported
        nodes.active = shader
        return imported, output is not None and not outputs
    except Exception:
        for node in reversed(imported):
            tree.nodes.remove(node)
        for node, was_active in outputs.items():
            node.is_active_output = was_active
        if old_displacement is not None:
            owner.displacement_method = old_displacement
        for node, was_selected in selected.items():
            node.select = was_selected
        tree.nodes.active = active
        for image in created_images:
            if image.users == 0:
                bpy.data.images.remove(image)
        raise


class MATERIAL_OT_import_fab_visn(bpy.types.Operator):
    bl_idname = "material.import_fab_visn"
    bl_label = "导入 Fab / Megascans 节点"
    bl_description = "向当前编辑的材质节点树追加 Fab 贴图及连线，保留已有节点和材质输出"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(name="贴图文件夹", subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})
    # Operator 不支持 ID PointerProperty；session_uid 可跨文件选择器/重命名/撤销定位。
    target_material_uid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    target_tree_uid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        tree = current_material_tree(context)
        return tree is not None and tree.is_editable and context.space_data.id.is_editable

    def invoke(self, context, event):
        # 文件选择器可能改变当前 area，确认后仍写入发起导入时的材质编辑层。
        self.target_material_uid = str(context.space_data.id.session_uid)
        self.target_tree_uid = str(current_material_tree(context).session_uid)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            if self.target_material_uid:
                material = next((m for m in bpy.data.materials
                                 if str(m.session_uid) == self.target_material_uid), None)
                root = getattr(material, 'node_tree', None)
                tree = root if root and str(root.session_uid) == self.target_tree_uid else next(
                    (t for t in bpy.data.node_groups if str(t.session_uid) == self.target_tree_uid), None)
            else:
                tree = current_material_tree(context)
                material = getattr(context.space_data, 'id', None)
            if not isinstance(material, bpy.types.Material) or tree is None or tree.bl_idname != 'ShaderNodeTree':
                raise ValueError("请在当前材质的 Shader 编辑器中导入")
            if not tree.is_editable or not material.is_editable:
                raise ValueError("当前材质或节点组不可编辑")
            if not self.directory.strip():
                raise ValueError("请选择 Fab 贴图文件夹")
            folder, name, resolution, maps = discover_textures(bpy.path.abspath(self.directory))
            _imported, activated = import_material_nodes(material, tree, name, maps)
        except (ValueError, RuntimeError, OSError, TypeError, AttributeError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        missing = [LABELS[role].split(" ·")[0] for role in ROLES if role not in maps]
        summary = f"已追加 {name}，{len(maps)} 张贴图" + (f"（{resolution}K）" if resolution else "")
        if tree != material.node_tree:
            summary += "；请按需连接 BSDF / Displacement 到组接口"
        elif not activated:
            summary += "；保留当前输出，请按需连接或启用 Fab 输出"
        if missing:
            self.report({"WARNING"}, summary + "；缺少：" + "、".join(missing))
        else:
            self.report({"INFO"}, summary)
        return {"FINISHED"}


def register():
    bpy.utils.register_class(MATERIAL_OT_import_fab_visn)


def unregister():
    bpy.utils.unregister_class(MATERIAL_OT_import_fab_visn)
