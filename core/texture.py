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


def _clay_group_users(group):
    owners = set(bpy.data.all_ids)
    owners.update(getattr(owner, 'node_tree', None) for owner in tuple(owners))
    return [node for owner in owners if isinstance(owner, bpy.types.NodeTree) and owner.is_editable
            for node in owner.nodes if node.type == 'GROUP' and node.node_tree == group]


def _extend_cycles_clay_group(group):
    """原位补齐旧共享组；保留 BSDF 接口标识、用户连线及已修改的颜色。"""
    if group.get('bekkan_cycles_clay_version', 1) >= 2:
        return False
    outputs = [node for node in group.nodes if node.type == 'GROUP_OUTPUT' and node.is_active_output]
    if not outputs:
        return False
    output = outputs[0]
    bsdf = output.inputs.get('BSDF')
    if not bsdf or len(bsdf.links) != 1:
        return False
    diffuse = bsdf.links[0].from_node
    if diffuse.bl_idname != 'ShaderNodeBsdfDiffuse':
        return False
    users = _clay_group_users(group)
    inputs = next((node for node in group.nodes if node.type == 'GROUP_INPUT'), None)
    if inputs is None:
        inputs = group.nodes.new('NodeGroupInput')
        inputs.location = (diffuse.location.x - 260, diffuse.location.y)

    def interface_socket(name, direction, socket_type):
        socket = next((item for item in group.interface.items_tree
                       if item.item_type == 'SOCKET' and item.in_out == direction
                       and item.name == name and item.socket_type == socket_type), None)
        if socket is not None:
            return socket, False
        return group.interface.new_socket(name=name, in_out=direction, socket_type=socket_type), True

    normal, new_normal = interface_socket('Normal', 'INPUT', 'NodeSocketVector')
    if new_normal:
        normal.from_socket(diffuse, diffuse.inputs['Normal'])
        normal.hide_value = True
    if not diffuse.inputs['Normal'].is_linked:
        group.links.new(inputs.outputs[normal.identifier], diffuse.inputs['Normal'])

    value, new_value = interface_socket('Value', 'INPUT', 'NodeSocketFloat')
    color = diffuse.inputs['Color']
    gray = (not color.is_linked and 0 <= color.default_value[0] <= 1
            and max(color.default_value[:3]) - min(color.default_value[:3]) < 1e-6
            and abs(color.default_value[3] - 1.0) < 1e-6)
    if new_value:
        value.min_value, value.max_value = 0.0, 1.0
        # 新组默认 0.8；旧组的自定义灰度保留，避免把已调好的共享白膜重置。
        value.default_value = color.default_value[0] if gray else 0.8
        value.description = 'Diffuse BSDF 灰度（0–1）'
        for node in users:
            node.inputs[value.identifier].default_value = value.default_value
    if gray:
        group.links.new(inputs.outputs[value.identifier], color)

    transparent_socket, new_transparent = interface_socket('Transparent BSDF', 'OUTPUT', 'NodeSocketShader')
    if new_transparent or not output.inputs[transparent_socket.identifier].is_linked:
        transparent = group.nodes.new('ShaderNodeBsdfTransparent')
        transparent.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        transparent.location = (diffuse.location.x, diffuse.location.y - 300)
        group.links.new(transparent.outputs['BSDF'], output.inputs[transparent_socket.identifier])
    group['bekkan_cycles_clay_version'] = 2
    return True


def _cycles_clay_group():
    for group in bpy.data.node_groups:
        if (group.bl_idname == 'ShaderNodeTree' and group.library is None
                and group.get('bekkan_cycles_clay') == 1
                and any(s.in_out == 'OUTPUT' and s.socket_type == 'NodeSocketShader'
                        for s in group.interface.items_tree if s.item_type == 'SOCKET')):
            _extend_cycles_clay_group(group)
            return group
    group = bpy.data.node_groups.new('Cy白膜适配', 'ShaderNodeTree')
    group['bekkan_cycles_clay'] = 1
    group.interface.new_socket(name='BSDF', in_out='OUTPUT', socket_type='NodeSocketShader')
    shader = group.nodes.new('ShaderNodeBsdfDiffuse')
    output = group.nodes.new('NodeGroupOutput')
    output.location = (240, 0)
    group.links.new(shader.outputs['BSDF'], output.inputs['BSDF'])
    _extend_cycles_clay_group(group)
    return group


def _is_default_cycles_clay(output):
    surface = output.inputs.get('Surface')
    if not surface or len(surface.links) != 1:
        return False
    if any(s.is_linked for s in output.inputs if s != surface):
        return False
    shader = surface.links[0].from_node
    instance = None
    if shader.type == 'GROUP' and shader.node_tree:
        instance = shader
        group_outputs = [n for n in shader.node_tree.nodes
                         if n.type == 'GROUP_OUTPUT' and n.is_active_output]
        if not group_outputs:
            return False
        socket = group_outputs[0].inputs.get(surface.links[0].from_socket.name)
        if socket is None or len(socket.links) != 1:
            return False
        shader = socket.links[0].from_node
    if shader.bl_idname != 'ShaderNodeBsdfDiffuse':
        return False
    color = shader.inputs.get('Color')
    roughness = shader.inputs.get('Roughness')
    weight = shader.inputs.get('Weight')
    normal = shader.inputs.get('Normal')
    if any(s.is_linked for s in shader.inputs if s not in (color, normal)):
        return False

    def exposed_input(socket):
        if instance is None or len(socket.links) != 1 or socket.links[0].from_node.type != 'GROUP_INPUT':
            return None
        identifier = socket.links[0].from_socket.identifier
        return next((s for s in instance.inputs if s.identifier == identifier and not s.is_linked), None)

    color_value = color.default_value if color is not None and not color.is_linked else None
    if color is not None and color.is_linked:
        exposed = exposed_input(color)
        if exposed is not None:
            color_value = exposed.default_value
            if isinstance(color_value, (float, int)):
                color_value = (color_value, color_value, color_value, 1.0)
    normal_default = normal is None or (not normal.is_linked and all(abs(v) < 1e-6 for v in normal.default_value))
    if normal is not None and normal.is_linked:
        exposed = exposed_input(normal)
        if exposed is not None:
            interface = next((s for s in instance.node_tree.interface.items_tree
                              if s.item_type == 'SOCKET' and s.identifier == exposed.identifier), None)
            normal_default = (getattr(interface, 'hide_value', False)
                              and all(abs(v) < 1e-6 for v in exposed.default_value))
    return (color_value is not None and len(color_value) == 4
            and all(abs(a - b) < 1e-6 for a, b in zip(color_value, (0.8, 0.8, 0.8, 1.0)))
            and roughness is not None and abs(roughness.default_value) < 1e-6
            and (weight is None or abs(weight.default_value - 1.0) < 1e-6)
            and normal_default)


def _restore_cancelled_cycles_outputs(outputs):
    for output in outputs:
        if output.get('bekkan_cancelled_cycles_output'):
            # 用户取消后手动接线/改归属的输出不再当成空白膜输出。
            if output.target == 'ALL' and not any(socket.is_linked for socket in output.inputs):
                output.target = 'CYCLES'
            del output['bekkan_cancelled_cycles_output']


def adapt_cycles_clay(materials):
    """返回（适配后默认白膜材质数、本次补齐材质数、非默认材质数、跳过数）。"""
    default = added = custom = skipped = 0
    # 仅在用户执行适配时升级，注册/热重载阶段不访问工程数据。
    for group in bpy.data.node_groups:
        if (group.bl_idname == 'ShaderNodeTree' and group.is_editable
                and group.get('bekkan_cycles_clay') == 1):
            _extend_cycles_clay_group(group)
    for mat in materials:
        tree = mat.node_tree
        if not tree or not mat.is_editable or not tree.is_editable:
            skipped += 1
            continue
        outputs = [n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL']
        _restore_cancelled_cycles_outputs(outputs)
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


def _is_default_cycles_world(output):
    surface = output.inputs.get('Surface')
    if not surface or len(surface.links) != 1 or any(s.is_linked for s in output.inputs if s != surface):
        return False
    background = surface.links[0].from_node
    if background.bl_idname != 'ShaderNodeBackground' or any(s.is_linked for s in background.inputs):
        return False
    color = background.inputs.get('Color')
    strength = background.inputs.get('Strength')
    weight = background.inputs.get('Weight')
    return (color is not None and all(abs(a-b) < 1e-6 for a, b in zip(color.default_value, (0.8, 0.8, 0.8, 1)))
            and strength is not None and abs(strength.default_value - 1) < 1e-6
            and (weight is None or abs(weight.default_value - 1) < 1e-6))


def adapt_cycles_worlds(worlds):
    """World 保留 EEVEE 天空，为空 Cycles 输出补灰度 0.8 / 强度 1 的 Background。"""
    default = added = custom = skipped = 0
    for world in worlds:
        tree = world.node_tree
        if not tree or not world.is_editable or not tree.is_editable:
            skipped += 1
            continue
        outputs = [node for node in tree.nodes if node.type == 'OUTPUT_WORLD']
        _restore_cancelled_cycles_outputs(outputs)
        if not any(node.target in {'ALL', 'EEVEE'} for node in outputs):
            skipped += 1
            continue
        cycles = [node for node in outputs if node.target == 'CYCLES']
        for output in outputs:
            if output.target == 'ALL':
                output.target = 'EEVEE'
        if not cycles:
            output = tree.nodes.new('ShaderNodeOutputWorld')
            output.target = 'CYCLES'
            output.location = (outputs[0].location.x, outputs[0].location.y - 300)
            cycles = [output]
        changed = False
        for output in cycles:
            if any(socket.is_linked for socket in output.inputs):
                continue
            background = tree.nodes.new('ShaderNodeBackground')
            background.label = 'Cy 世界白膜 · 灰度 0.8 / 强度 1'
            background.inputs['Color'].default_value = (0.8, 0.8, 0.8, 1)
            background.inputs['Strength'].default_value = 1
            background.location = (output.location.x - 260, output.location.y)
            tree.links.new(background.outputs['Background'], output.inputs['Surface'])
            changed = True
        added += int(changed)
        if all(_is_default_cycles_world(output) for output in cycles):
            default += 1
        else:
            custom += 1
    return default, added, custom, skipped


class MATERIAL_OT_cycles_clay(Operator):
    bl_idname = 'material.cycles_clay_visn'
    bl_label = '双引擎Cy白膜适配'
    bl_description = '物体白膜：Normal、0–1 灰度与纯白透明输出；World：灰度0.8/强度1的Background；保留EEVEE材质及已有Cycles输出连线'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        default, added, custom, skipped = adapt_cycles_clay(bpy.data.materials)
        world_default, world_added, world_custom, world_skipped = adapt_cycles_worlds(bpy.data.worlds)
        self.report({'INFO'}, f'材质：白膜 {default}，新增 {added}，自定义 {custom}，跳过 {skipped}；'
                    f'World：白膜 {world_default}，新增 {world_added}，自定义 {world_custom}，跳过 {world_skipped}')
        return {'FINISHED'}


def cancel_cycles_clay(owners, output_type):
    """返回（修改的数据块数、断开的连接数、改为 All 的输出数、跳过数）。"""
    changed = disconnected = restored = skipped = 0
    for owner in owners:
        tree = getattr(owner, 'node_tree', None)
        if not tree or not owner.is_editable or not tree.is_editable:
            skipped += 1
            continue
        outputs = [node for node in tree.nodes if node.type == output_type]
        if not outputs:
            skipped += 1
            continue
        cycles = [node for node in outputs if getattr(node, 'target', None) == 'CYCLES']
        eevee = [node for node in outputs if getattr(node, 'target', None) == 'EEVEE']
        # 多个输出时保留原 EEVEE 的实际选择，不由遍历顺序决定最后使用哪个。
        preferred = next((node for node in eevee if node.is_active_output), None)
        if preferred is None and eevee:
            preferred = eevee[0]
        touched = bool(eevee)
        for output in cycles:
            links = [link for socket in output.inputs for link in socket.links]
            touched |= bool(links) or output.is_active_output
            for link in links:
                tree.links.remove(link)
            disconnected += len(links)
            # 只关 is_active_output 仍会被专属 target 优先选中；转成非活跃 All 才能回退。
            output['bekkan_cancelled_cycles_output'] = True
            output.target = 'ALL'
            output.is_active_output = False
        for output in eevee:
            output.target = 'ALL'
        restored += len(eevee)
        if preferred is not None:
            preferred.is_active_output = True
        changed += int(touched)
    return changed, disconnected, restored, skipped


class MATERIAL_OT_cancel_cycles_clay(Operator):
    bl_idname = 'material.cancel_cycles_clay_visn'
    bl_label = '取消白膜适配'
    bl_description = '断开全部材质与World的Cycles专属输出，停用空输出并把EEVEE改回All；保留节点，支持撤销'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        changed, links, outputs, skipped = cancel_cycles_clay(bpy.data.materials, 'OUTPUT_MATERIAL')
        world_changed, world_links, world_outputs, world_skipped = cancel_cycles_clay(bpy.data.worlds, 'OUTPUT_WORLD')
        self.report({'INFO'}, f'材质：取消 {changed}，断线 {links}，恢复 All {outputs}，跳过 {skipped}；'
                    f'World：取消 {world_changed}，断线 {world_links}，恢复 All {world_outputs}，跳过 {world_skipped}')
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
    MATERIAL_OT_cancel_cycles_clay,
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
