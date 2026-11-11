# 别馆 Shader 脚本：只在当前材质的当前编辑层工作。
from collections import defaultdict, deque
import bpy


def current_material_tree(context):
    space = context.space_data
    if (not space or space.type != 'NODE_EDITOR'
            or space.tree_type != 'ShaderNodeTree'
            or getattr(space, 'shader_type', None) != 'OBJECT'
            or not isinstance(getattr(space, 'id', None), bpy.types.Material)):
        return None
    tree = getattr(space, 'edit_tree', None)
    return tree if tree and tree.bl_idname == 'ShaderNodeTree' else None


def _node_size(node, ui_scale):
    width = max(float(node.width), 32.0)
    dimensions = node.dimensions
    if dimensions.x > 1 and dimensions.y > 1:
        if node.hide:
            return max(dimensions.x / ui_scale, 32), max(dimensions.y / ui_scale, 32)
        # dimensions 含界面缩放，而 width 是节点坐标；用比例换回同一单位。
        return width, max(32, dimensions.y * width / dimensions.x)
    if node.type == 'REROUTE':
        return 32.0, 32.0
    if node.hide:
        return width, 40.0
    # 新建但尚未绘制的节点 dimensions 为 0；采用保守尺寸，不能只看默认 height=100。
    standard = {'TEX_IMAGE': 330, 'MAPPING': 390, 'TEX_COORD': 260,
                'BSDF_PRINCIPLED': 760, 'OUTPUT_MATERIAL': 180,
                'BUMP': 230, 'NORMAL_MAP': 200, 'VALTORGB': 240}
    sockets = sum(not socket.hide and socket.enabled for socket in (*node.inputs, *node.outputs))
    return width, max(float(node.height), standard.get(node.type, 110 + 24 * sockets))


def _owner_at_level(node, parent):
    while node is not None and node.parent != parent:
        node = node.parent
    return node


def _layout_level(nodes, sizes, links, horizontal_gap, vertical_gap):
    """按到末端的最长距离分列，按下游位置/输入插口顺序排列分支。"""
    outgoing = {node: set() for node in nodes}
    incoming = {node: set() for node in nodes}
    ports = defaultdict(list)
    for source, target, port in links:
        if source != target:
            outgoing[source].add(target)
            incoming[target].add(source)
            ports[source, target].append(port)

    # 先求完整布局，遇到环时取消；不能在半途挪动部分节点。
    degree = {node: len(outgoing[node]) for node in nodes}
    distance = {node: 0 for node in nodes}
    queue = deque(node for node in nodes if degree[node] == 0)
    processed = 0
    while queue:
        target = queue.popleft()
        processed += 1
        for source in incoming[target]:
            distance[source] = max(distance[source], distance[target] + 1)
            degree[source] -= 1
            if degree[source] == 0:
                queue.append(source)
    if processed != len(nodes):
        raise ValueError('存在循环连线或交叉回连的框架，请先检查连线或调整框架分组')

    # 各个互不相连的网络分开摆放，未连接的备用节点也会保留。
    remaining = set(nodes)
    components = []
    while remaining:
        seed = min(remaining, key=lambda n: n.name)
        connected, pending = set(), [seed]
        while pending:
            node = pending.pop()
            if node in connected:
                continue
            connected.add(node)
            pending.extend((incoming[node] | outgoing[node]) - connected)
        remaining.difference_update(connected)
        components.append(connected)
    components.sort(key=lambda group: (
        not any(n.type in {'OUTPUT_MATERIAL', 'GROUP_OUTPUT'} for n in group),
        -len(group), min(n.name for n in group),
    ))

    positions = {}
    total_width = total_height = 0.0
    for component in components:
        columns = defaultdict(list)
        maximum = max(distance[n] for n in component)
        for node in component:
            columns[maximum - distance[node]].append(node)
        xs, x = {}, 0.0
        for rank in sorted(columns):
            xs[rank] = x
            x += max(sizes[n][0] for n in columns[rank]) + horizontal_gap
        local = {}
        for rank in sorted(columns, reverse=True):
            desired = {}
            for node in columns[rank]:
                targets = outgoing[node]
                if targets:
                    # 插口索引使同接一个 BSDF 的颜色/粗糙度/法线等分支上下有序。
                    anchors = [local[t][1] - min(sizes[t][1] - 24,
                               40 + 22 * min(ports[node, t])) for t in targets]
                    desired[node] = sum(anchors) / len(anchors) + 40
                else:
                    desired[node] = 0.0
            ordered = sorted(columns[rank], key=lambda n: (-desired[n], n.name))
            tops = []
            for index, node in enumerate(ordered):
                top = desired[node]
                if index:
                    previous = ordered[index - 1]
                    top = min(top, tops[-1] - sizes[previous][1] - vertical_gap)
                tops.append(top)
            # 整列平移，均衡贴近下游；节点之间的间距始终保持。
            shift = sum(desired[n] - y for n, y in zip(ordered, tops)) / len(ordered)
            for node, top in zip(ordered, tops):
                local[node] = (xs[rank], top + shift)
        top = max(y for _, y in local.values())
        bottom = min(local[n][1] - sizes[n][1] for n in component)
        for node, (x_node, y_node) in local.items():
            positions[node] = (x_node, y_node - top - total_height)
        total_width = max(total_width, x - horizontal_gap)
        total_height += top - bottom + vertical_gap * 2
    return positions, (total_width, max(0, total_height - vertical_gap * 2))


def arrange_shader_tree(tree, horizontal_gap=110.0, vertical_gap=65.0, ui_scale=1.0):
    """只改变本层节点位置及框架尺寸，不进入引用的节点组，不改连线/参数。"""
    nodes = list(tree.nodes)
    if not nodes:
        return 0
    children = defaultdict(list)
    for node in nodes:
        children[node.parent].append(node)
    sizes = {n: _node_size(n, max(ui_scale, 0.01)) for n in nodes}
    planned = {}
    frame_sizes = {}
    links = [(link.from_node, link.to_node, list(link.to_node.inputs).index(link.to_socket))
             for link in tree.links]

    def plan(parent):
        siblings = children[parent]
        for node in siblings:
            if node.type == 'FRAME' and children[node]:
                size = plan(node)
                header = max(60, float(node.label_size) + 24)
                for child in children[node]:
                    x, y = planned[child]
                    planned[child] = (x + 40, y - header)
                size = (size[0] + 80, size[1] + header + 40)
                if not node.shrink:
                    size = (max(size[0], sizes[node][0]), max(size[1], sizes[node][1]))
                frame_sizes[node] = sizes[node] = size
        level_links = []
        for source, target, port in links:
            source = _owner_at_level(source, parent)
            target = _owner_at_level(target, parent)
            if source in siblings and target in siblings and source != target:
                level_links.append((source, target, port))
        positions, size = _layout_level(siblings, sizes, level_links, horizontal_gap, vertical_gap)
        planned.update(positions)
        return size

    plan(None)
    anchor = next((n for n in nodes if n.type in {'OUTPUT_MATERIAL', 'GROUP_OUTPUT'}
                   and getattr(n, 'is_active_output', False)), nodes[0])
    old_anchor = anchor.location_absolute.copy()
    new_anchor = [0.0, 0.0]
    parent = anchor
    while parent:
        x, y = planned[parent]
        new_anchor[0] += x
        new_anchor[1] += y
        parent = parent.parent
    shift = (old_anchor.x - new_anchor[0], old_anchor.y - new_anchor[1])
    before = {n: (n.location.copy(), n.width, n.height) for n in nodes}
    try:
        # parent/连线/节点宽度均保留；框架允许随整理后的内容扩展。
        for node in nodes:
            x, y = planned[node]
            node.location = (x + shift[0], y + shift[1]) if node.parent is None else (x, y)
        for frame, size in frame_sizes.items():
            frame.width, frame.height = size
    except Exception:
        for node, (location, width, height) in before.items():
            node.location = location
            if node.type == 'FRAME':
                node.width, node.height = width, height
        raise
    return len(nodes)


def selected_images_to_non_color(tree):
    images = {n.image for n in tree.nodes if n.select and n.type == 'TEX_IMAGE' and n.image}
    changed = already = skipped = 0
    for image in images:
        if image.colorspace_settings.name == 'Non-Color':
            already += 1
            continue
        if not image.is_editable:
            skipped += 1
            continue
        try:
            image.colorspace_settings.name = 'Non-Color'
            changed += 1
        except (TypeError, RuntimeError):
            skipped += 1
    return changed, already, skipped


def _driver_referenced_nodes(tree, nodes):
    """保护原生驱动变量引用的节点（含其他数据块上的驱动），不执行表达式。"""
    protected = set()
    paths = {node.path_from_id(): node for node in nodes}
    # all_ids 不包含材质等数据块内嵌的节点树，需补上。
    ids = set(bpy.data.all_ids)
    ids.update(getattr(owner, 'node_tree', None) for owner in tuple(ids))
    ids.add(tree)
    for owner in ids:
        animation = getattr(owner, 'animation_data', None)
        for curve in getattr(animation, 'drivers', ()):
            for variable in curve.driver.variables:
                for target in variable.targets:
                    target_id = getattr(target, 'id', None)
                    path = getattr(target, 'data_path', '')
                    if target_id != tree:
                        if (getattr(target_id, 'node_tree', None) != tree
                                or not path.startswith('node_tree.')):
                            continue
                        path = path[len('node_tree.'):]
                    if not path.startswith('nodes['):
                        continue
                    node = next((node for prefix, node in paths.items()
                                 if path == prefix or path.startswith(prefix + '.')
                                 or path.startswith(prefix + '[')), None)
                    if node is None:
                        # 数字下标会因删除别的节点而变化；未知节点路径同样保守保留全树。
                        return set(nodes)
                    protected.add(node)
    return protected


def select_nodes_unrelated_to_output(tree):
    """只选本层没有通向任何输出的节点；不分析常量、组内插口或任意 Python 引用。"""
    nodes = list(tree.nodes)
    outputs = {node for node in nodes
               if node.type.startswith('OUTPUT_') or node.type == 'GROUP_OUTPUT'}
    if not outputs:
        # 没有判断依据时保持原选择，不能把整棵树误当成废弃分支。
        raise ValueError('当前编辑层没有输出节点，已保持原选择')

    incoming = defaultdict(set)
    for link in tree.links:
        # 连线即保留：不根据 mute、is_valid、Mix 常量或当前渲染器做激进裁剪。
        incoming[link.to_node].add(link.from_node)
    required = set()
    pending = list(outputs | _driver_referenced_nodes(tree, nodes))
    while pending:
        node = pending.pop()
        if node in required:
            continue
        required.add(node)
        pending.extend(incoming[node] - required)

    unrelated = {node for node in nodes if node not in required and node.type != 'FRAME'}
    # 替换选择而非追加；零候选也清掉旧选择，避免误删此前选中的有效节点。
    active = tree.nodes.active
    for node in nodes:
        node.select = node in unrelated
    tree.nodes.active = active if active in unrelated else next(
        (node for node in nodes if node in unrelated), None)
    return len(unrelated)


class _MaterialShaderOperator:
    @classmethod
    def poll(cls, context):
        tree = current_material_tree(context)
        if tree is None:
            cls.poll_message_set('请在 Shader Editor 中打开一个材质')
            return False
        if not tree.is_editable:
            cls.poll_message_set('当前节点树为不可编辑的链接数据')
            return False
        return True


class NODE_OT_arrange_material_visn(_MaterialShaderOperator, bpy.types.Operator):
    bl_idname = 'node.arrange_material_visn'
    bl_label = '整理当前材质节点'
    bl_description = '按连线从左到右分列并错开分支，整理当前编辑层的全部节点；保留连线和参数，支持撤销'
    bl_options = {'REGISTER', 'UNDO'}

    horizontal_gap: bpy.props.FloatProperty(name='水平间距', default=110, min=30, max=1000)
    vertical_gap: bpy.props.FloatProperty(name='垂直间距', default=65, min=30, max=1000)

    def execute(self, context):
        tree = current_material_tree(context)
        try:
            count = arrange_shader_tree(tree, self.horizontal_gap, self.vertical_gap,
                                        max(context.preferences.system.ui_scale, 1.0))
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region:
            with context.temp_override(region=region):
                bpy.ops.node.view_all()
        context.area.tag_redraw()
        self.report({'INFO'}, f'已整理 {count} 个节点，连线和参数保持不变')
        return {'FINISHED'}


class NODE_OT_selected_images_non_color_visn(_MaterialShaderOperator, bpy.types.Operator):
    bl_idname = 'node.selected_images_non_color_visn'
    bl_label = '选中贴图设为 Non-Color'
    bl_description = '将选中的 Image Texture 节点所用图片设为 Non-Color；同一图片的其他材质引用也会同步变化'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        changed, already, skipped = selected_images_to_non_color(current_material_tree(context))
        if not (changed or already or skipped):
            self.report({'WARNING'}, '请先选中带有图片的 Image Texture 节点')
            return {'CANCELLED'}
        self.report({'INFO'}, f'已修改 {changed} 张图片，原本为 Non-Color {already} 张，跳过 {skipped} 张')
        context.area.tag_redraw()
        return {'FINISHED'}


class NODE_OT_select_unrelated_shader_nodes_visn(_MaterialShaderOperator, bpy.types.Operator):
    bl_idname = 'node.select_unrelated_shader_nodes_visn'
    bl_label = '选择与输出无关的节点'
    bl_description = ('选中当前编辑层中未通向任何输出的节点；保留框架及驱动变量引用，'
                      '只选择不删除，支持撤销')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            count = select_nodes_unrelated_to_output(current_material_tree(context))
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        context.area.tag_redraw()
        self.report({'INFO'}, f'已选中 {count} 个与输出无关的节点' if count
                    else '未发现与输出无关的节点，已清空选择')
        return {'FINISHED'}


_classes = (NODE_OT_arrange_material_visn, NODE_OT_selected_images_non_color_visn,
            NODE_OT_select_unrelated_shader_nodes_visn)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
