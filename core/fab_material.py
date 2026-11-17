# Fab / Megascans 材质导入：本地贴图识别、材质节点与猴头预览。
# 只在用户确认文件夹后读取图片；register() 不访问场景数据。
from collections import defaultdict
import json
from pathlib import Path
import re

import bpy
from bpy.props import BoolProperty, StringProperty

from .shader_tools import arrange_shader_tree


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


def create_material(name, maps, created_images):
    material = bpy.data.materials.new("Fab · " + name)
    try:
        tree = material.node_tree
        if tree is None and hasattr(material, "use_nodes"):
            material.use_nodes = True
            tree = material.node_tree
        if tree is None:
            raise ValueError("无法创建材质节点树")
        tree.nodes.clear()
        nodes, links = tree.nodes, tree.links
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        output = nodes.new("ShaderNodeOutputMaterial")
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        coordinate = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.vector_type = "POINT"
        value = nodes.new("ShaderNodeValue")
        value.name = "Fab Texture Scale"
        value.label = "统一贴图缩放"
        value.outputs[0].default_value = 1
        links.new(coordinate.outputs["UV"], mapping.inputs["Vector"])
        links.new(value.outputs[0], mapping.inputs["Scale"])
        for role in ROLES:
            if role not in maps:
                continue
            texture = nodes.new("ShaderNodeTexImage")
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
                normal = nodes.new("ShaderNodeNormalMap")
                normal.space = "TANGENT"
                if maps[role]["directx"]:
                    multiply = nodes.new("ShaderNodeVectorMath")
                    multiply.operation = "MULTIPLY"
                    multiply.label = "DirectX 法线 · 翻转绿色"
                    multiply.inputs[1].default_value = (1, -1, 1)
                    add = nodes.new("ShaderNodeVectorMath")
                    add.operation = "ADD"
                    add.inputs[1].default_value = (0, 1, 0)
                    links.new(color, multiply.inputs[0])
                    links.new(multiply.outputs["Vector"], add.inputs[0])
                    color = add.outputs["Vector"]
                links.new(color, normal.inputs["Color"])
                links.new(normal.outputs["Normal"], _socket(shader.inputs, "Normal"))
            elif role == "displacement":
                displacement = nodes.new("ShaderNodeDisplacement")
                links.new(color, displacement.inputs["Height"])
                links.new(displacement.outputs["Displacement"], output.inputs["Displacement"])
            # AO 只有 Vector 输入连接，颜色输出留空供用户自行使用。
        owner = material if hasattr(material, "displacement_method") else getattr(material, "cycles", None)
        if owner is None or not hasattr(owner, "displacement_method"):
            raise ValueError("当前 Blender 无法设置材质的 Bump Only 模式")
        owner.displacement_method = "BUMP"
        arrange_shader_tree(tree)
        for node in nodes:
            node.select = False
        shader.select = True
        nodes.active = shader
        return material
    except Exception:
        bpy.data.materials.remove(material)
        raise


class MATERIAL_OT_import_fab_visn(bpy.types.Operator):
    bl_idname = "material.import_fab_visn"
    bl_label = "导入 Fab 材质 · 创建猴头"
    bl_description = "选择 Fab 贴图文件夹，导入六种材质贴图并创建猴头预览"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(name="贴图文件夹", subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == "OBJECT"

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        images, material, monkey, mesh = [], None, None, None
        selection = list(context.selected_objects)
        active = context.view_layer.objects.active
        try:
            if not self.directory.strip():
                raise ValueError("请选择 Fab 贴图文件夹")
            folder, name, resolution, maps = discover_textures(bpy.path.abspath(self.directory))
            material = create_material(name, maps, images)
            material["fab_source_directory"] = str(folder)
            material["fab_texture_resolution"] = resolution
            result = bpy.ops.mesh.primitive_monkey_add(calc_uvs=True, enter_editmode=False,
                                                       location=context.scene.cursor.location)
            if result != {"FINISHED"}:
                raise ValueError("无法在当前场景创建猴头")
            monkey = context.object
            mesh = monkey.data
            monkey.name = "Fab · " + name
            mesh.materials.append(material)
            for polygon in mesh.polygons:
                polygon.use_smooth = True
            subdivision = monkey.modifiers.new("材质预览 · 细分", "SUBSURF")
            subdivision.levels = subdivision.render_levels = 2
        except (ValueError, RuntimeError, OSError, TypeError, AttributeError, KeyError) as exc:
            if monkey is not None:
                bpy.data.objects.remove(monkey, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            if material is not None:
                bpy.data.materials.remove(material)
            for image in images:
                if image.users == 0:
                    bpy.data.images.remove(image)
            for obj in selection:
                obj.select_set(True)
            context.view_layer.objects.active = active
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        missing = [LABELS[role].split(" ·")[0] for role in ROLES if role not in maps]
        summary = f"已导入 {name}，{len(maps)} 张贴图" + (f"（{resolution}K）" if resolution else "")
        if missing:
            self.report({"WARNING"}, summary + "；缺少：" + "、".join(missing))
        else:
            self.report({"INFO"}, summary)
        return {"FINISHED"}


def register():
    bpy.utils.register_class(MATERIAL_OT_import_fab_visn)


def unregister():
    bpy.utils.unregister_class(MATERIAL_OT_import_fab_visn)
