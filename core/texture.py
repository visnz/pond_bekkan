# 贴图索引：建立 贴图→材质 索引、查材质、选中使用物体
# （合并自 Bekkan/STOOL_part/TextureOps.py，纯平移；面板在 ui/bekkan/panels.py）
import bpy  # type: ignore
from bpy.props import StringProperty, PointerProperty  # type: ignore
from bpy.types import Operator, PropertyGroup  # type: ignore


class TextureSearchProperties(PropertyGroup):
    texture_search_image: StringProperty(
        name="贴图", description="选择要查找的贴图", default="")  # type: ignore


# 全局变量存储索引结果
texture_material_index = {}


def _checked_image(op, context):
    """公共检查：返回贴图名，索引为空或未选贴图时报错返回 None"""
    if not texture_material_index:
        op.report({'WARNING'}, "请先建立贴图索引!")
        return None
    img = context.scene.texture_search_props.texture_search_image
    if not img:
        op.report({'WARNING'}, "请选择一张贴图!")
        return None
    return img


class INDEX_OT_build_texture_index(Operator):
    bl_idname = "index.build_texture_index"
    bl_label = "建立or刷新 贴图-材质 索引"
    bl_description = "扫描所有材质并建立贴图与材质的对应关系索引"

    def execute(self, context):
        global texture_material_index
        texture_material_index = {}
        for mat in bpy.data.materials:
            if not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    lst = texture_material_index.setdefault(node.image.name, [])
                    if mat.name not in lst:
                        lst.append(mat.name)
        self.report({'INFO'}, f"索引建立完成，共索引 {len(texture_material_index)} 张贴图")
        return {'FINISHED'}


class INDEX_OT_find_materials(Operator):
    bl_idname = "index.find_materials"
    bl_label = "查找使用贴图的材质"
    bl_description = "查找使用选定贴图的所有材质"

    def execute(self, context):
        img = _checked_image(self, context)
        if img is None:
            return {'CANCELLED'}
        mats = texture_material_index.get(img)
        if not mats:
            self.report({'INFO'}, f"贴图 '{img}' 未被任何材质使用")
            return {'FINISHED'}
        self.report({'INFO'}, f"贴图 '{img}' 被以下材质使用: {', '.join(mats)}")
        print(f"\n贴图 '{img}' 使用情况:")
        for mat in mats:
            print(f"- {mat}")
        return {'FINISHED'}


class INDEX_OT_select_objects_with_texture(Operator):
    bl_idname = "index.select_objects_with_texture"
    bl_label = "选中该贴图的材质对象"
    bl_description = "选中所有使用该贴图的物体"

    def execute(self, context):
        img = _checked_image(self, context)
        if img is None:
            return {'CANCELLED'}
        mats = texture_material_index.get(img)
        if not mats:
            self.report({'INFO'}, f"贴图 '{img}' 未被任何材质使用")
            return {'FINISHED'}

        bpy.ops.object.select_all(action='DESELECT')
        n = 0
        try:
            for obj in bpy.data.objects:
                if hasattr(obj.data, 'materials'):
                    for slot in obj.material_slots:
                        if slot.material and slot.material.name in mats:
                            obj.select_set(True)
                            n += 1
                            break  # 多材质物体匹配到一个即可
        except Exception as e:
            self.report({'ERROR'}, f"发生错误: 物体可能不在当前场景中 {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已选中 {n} 个使用该贴图的物体")
        return {'FINISHED'}


def _cycles_clay_group():
    for group in bpy.data.node_groups:
        if (group.bl_idname == 'ShaderNodeTree' and group.library is None
                and group.get('bekkan_cycles_clay') == 1
                and any(s.in_out == 'OUTPUT' and s.socket_type == 'NodeSocketShader'
                        for s in group.interface.items_tree if s.item_type == 'SOCKET')):
            return group
    group = bpy.data.node_groups.new('Cy白膜适配', 'ShaderNodeTree')
    group['bekkan_cycles_clay'] = 1
    group.interface.new_socket(name='BSDF', in_out='OUTPUT', socket_type='NodeSocketShader')
    shader = group.nodes.new('ShaderNodeBsdfDiffuse')
    output = group.nodes.new('NodeGroupOutput')
    output.location = (240, 0)
    group.links.new(shader.outputs['BSDF'], output.inputs['BSDF'])
    return group


def _is_default_cycles_clay(output):
    surface = output.inputs.get('Surface')
    if not surface or len(surface.links) != 1:
        return False
    if any(s.is_linked for s in output.inputs if s != surface):
        return False
    shader = surface.links[0].from_node
    if shader.type == 'GROUP' and shader.node_tree:
        group_outputs = [n for n in shader.node_tree.nodes
                         if n.type == 'GROUP_OUTPUT' and n.is_active_output]
        if not group_outputs:
            return False
        socket = group_outputs[0].inputs.get(surface.links[0].from_socket.name)
        if socket is None or len(socket.links) != 1:
            return False
        shader = socket.links[0].from_node
    if shader.bl_idname != 'ShaderNodeBsdfDiffuse' or any(s.is_linked for s in shader.inputs):
        return False
    color = shader.inputs.get('Color')
    roughness = shader.inputs.get('Roughness')
    weight = shader.inputs.get('Weight')
    normal = shader.inputs.get('Normal')
    return (color is not None and all(abs(a - b) < 1e-6 for a, b in zip(color.default_value, (0.8, 0.8, 0.8, 1.0)))
            and roughness is not None and abs(roughness.default_value) < 1e-6
            and (weight is None or abs(weight.default_value - 1.0) < 1e-6)
            and (normal is None or all(abs(v) < 1e-6 for v in normal.default_value)))


def adapt_cycles_clay(materials):
    """返回（适配后默认白膜材质数、本次补齐材质数、非默认材质数、跳过数）。"""
    default = added = custom = skipped = 0
    for mat in materials:
        tree = mat.node_tree
        if not tree or not mat.is_editable or not tree.is_editable:
            skipped += 1
            continue
        outputs = [n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL']
        if not any(n.target in {'ALL', 'EEVEE'} for n in outputs):
            skipped += 1
            continue
        cycles = [n for n in outputs if n.target == 'CYCLES']
        for output in outputs:
            if output.target == 'ALL':
                output.target = 'EEVEE'
        if not cycles:
            output = tree.nodes.new('ShaderNodeOutputMaterial')
            output.target = 'CYCLES'
            anchor = outputs[0]
            output.location = (anchor.location.x, anchor.location.y - 300)
            cycles = [output]
        changed = False
        for output in cycles:
            if any(s.is_linked for s in output.inputs):
                continue
            shader = tree.nodes.new('ShaderNodeGroup')
            shader.node_tree = _cycles_clay_group()
            shader.location = (output.location.x - 240, output.location.y)
            socket = next(s for s in shader.outputs if s.type == 'SHADER')
            tree.links.new(socket, output.inputs['Surface'])
            changed = True
        added += int(changed)
        if all(_is_default_cycles_clay(n) for n in cycles):
            default += 1
        else:
            custom += 1
    return default, added, custom, skipped


class MATERIAL_OT_cycles_clay(Operator):
    bl_idname = 'material.cycles_clay_visn'
    bl_label = '双引擎Cy白膜适配'
    bl_description = '将 All 输出改为 EEVEE，并为未连接的 Cycles 输出补齐共享白膜节点组；编辑组内材质可统一修改，已有连接与仅 Cycles 的材质保持原样'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        default, added, custom, skipped = adapt_cycles_clay(bpy.data.materials)
        self.report({'INFO'}, f'白膜适配 {default} 个材质；本次添加 {added} 个；非默认白膜 {custom} 个；跳过 {skipped} 个')
        return {'FINISHED'}


def _find_base_color(surface):
    """沿 Surface 的着色器链广度优先找最近的 BSDF，插口顺序决定同距离优先级。"""
    from collections import deque
    queue = deque(link.from_socket for link in surface.links)
    visited = set()
    while queue:
        socket = queue.popleft()
        node = socket.node
        if node.as_pointer() in visited:
            continue
        visited.add(node.as_pointer())
        if node.type.startswith('BSDF_'):
            color = node.inputs.get('Base Color') or node.inputs.get('Color')
            if color is not None:
                return color
        # 颜色已直出时不再追进贴图计算；节点组暂不展开，以免改动共享组。
        if node.type == 'REROUTE':
            inputs = node.inputs
        elif socket.type == 'SHADER' and node.type != 'GROUP':
            inputs = [s for s in node.inputs if s.type == 'SHADER']
        else:
            inputs = []
        for input_socket in inputs:
            queue.extend(link.from_socket for link in input_socket.links)
    return None


def base_color_direct(materials, engine):
    target = 'CYCLES' if engine == 'CYCLES' else 'EEVEE'
    linked = constant = skipped = 0
    for mat in materials:
        tree = mat.node_tree
        if not tree or not mat.is_editable or not tree.is_editable:
            skipped += 1
            continue
        output = tree.get_output_node(target)
        color = _find_base_color(output.inputs['Surface']) if output else None
        if color is None:
            skipped += 1
            continue
        if output.target == 'ALL':
            original = output
            output = tree.nodes.new('ShaderNodeOutputMaterial')
            output.target = target
            output.location = (original.location.x, original.location.y - 260)
            for source_input in original.inputs:
                dest = output.inputs.get(source_input.name)
                if dest is None:
                    continue
                if hasattr(source_input, 'default_value'):
                    dest.default_value = source_input.default_value
                for link in source_input.links:
                    tree.links.new(link.from_socket, dest)
        if color.is_linked:
            source = color.links[0].from_socket
            linked += 1
        else:
            rgb = tree.nodes.new('ShaderNodeRGB')
            rgb.label = 'Base Color 直出'
            rgb.location = (output.location.x - 220, output.location.y)
            rgb.outputs[0].default_value = color.default_value
            source = rgb.outputs[0]
            constant += 1
        tree.links.new(source, output.inputs['Surface'])
    return linked, constant, skipped


class MATERIAL_OT_base_color_direct(Operator):
    bl_idname = 'material.base_color_direct_visn'
    bl_label = 'Base Color 直出（MMD转BL）'
    bl_description = '将选中物体所用材质当前引擎输出上游最近 BSDF 的 Base Color 直连 Surface；共用该材质的其他物体也会受影响，支持撤销'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene and context.scene.render.engine in {'CYCLES', 'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'}

    def execute(self, context):
        materials = {slot.material for obj in context.selected_objects
                     for slot in obj.material_slots if slot.material is not None}
        if not materials:
            self.report({'INFO'}, '选中物体没有可处理的材质')
            return {'CANCELLED'}
        linked, constant, skipped = base_color_direct(materials, context.scene.render.engine)
        self.report({'INFO'}, f'Base Color 直出：上游连接 {linked} 个，纯色 {constant} 个，跳过 {skipped} 个材质')
        return {'FINISHED'}


_classes = (
    MATERIAL_OT_base_color_direct,
    MATERIAL_OT_cycles_clay,
    TextureSearchProperties,
    INDEX_OT_build_texture_index,
    INDEX_OT_find_materials,
    INDEX_OT_select_objects_with_texture,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.texture_search_props = PointerProperty(type=TextureSearchProperties)


def unregister():
    del bpy.types.Scene.texture_search_props
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
