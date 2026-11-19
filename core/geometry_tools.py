# 几何节点脚本：在当前编辑层封装选中节点组的未连接输入。
# 同步接口 Panel 和当前参数；只添加入口，不重组原节点或已有连线。
import bpy


_ENTRY_TAG = 'pond_bekkan_geometry_entry'
_SOCKET_SETTINGS = ('description', 'structure_type', 'hide_value', 'hide_in_modifier',
                    'force_non_field', 'attribute_domain', 'default_attribute_name',
                    'default_input', 'layer_selection_field', 'menu_expanded',
                    'optional_label', 'is_panel_toggle')


def current_geometry_tree(context):
    space = context.space_data
    if not space or space.type != 'NODE_EDITOR' or space.tree_type != 'GeometryNodeTree':
        return None
    tree = getattr(space, 'edit_tree', None)
    return tree if tree and tree.bl_idname == 'GeometryNodeTree' else None


def _animation_paths(tree):
    animation = getattr(tree, 'animation_data', None)
    if animation is None:
        return set()
    paths = {curve.data_path for curve in animation.drivers}
    actions = [animation.action] if animation.action else []
    actions.extend(strip.action for track in animation.nla_tracks for strip in track.strips if strip.action)
    for action in actions:
        for layer in getattr(action, 'layers', ()):
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', ()):
                    paths.update(curve.data_path for curve in bag.fcurves)
        paths.update(curve.data_path for curve in getattr(action, 'fcurves', ()))
    return paths


def _value(socket):
    value = getattr(socket, 'default_value', None)
    if socket.bl_idname == 'NodeSocketMenu' and value == '':
        return None
    if hasattr(value, 'copy') and not isinstance(value, bpy.types.ID):
        return value.copy()
    return value


def _modifier_inputs(modifier):
    properties = getattr(modifier, 'properties', None)
    return properties.inputs if properties is not None else modifier


def _set_modifier_value(modifier, identifier, value):
    inputs = _modifier_inputs(modifier)
    if inputs is modifier:
        inputs[identifier] = tuple(value) if hasattr(value, '__len__') and not isinstance(value, str) else value
    else:
        prop = getattr(inputs, identifier, None)
        if prop is not None and hasattr(prop, 'value'):
            prop.value = value


def _absolute_location(node):
    location = node.location.copy()
    parent = node.parent
    while parent:
        location += parent.location
        parent = parent.parent
    return location


def _new_entry(tree, selected, count):
    entry = tree.nodes.new('NodeGroupInput')
    entry.name = '封装入口'
    entry.label = '封装入口'
    entry.width = 240
    entry[_ENTRY_TAG] = True
    positions = [_absolute_location(node) for node in selected]
    x = min(p.x for p in positions) - 340
    y = max(p.y for p in positions) - 140
    height = 70 + 24 * count
    # 保留原节点位置；新增入口遇到已有节点时向下避让。
    for _ in range(len(tree.nodes) + 1):
        collisions = []
        for node in tree.nodes:
            if node == entry or node.type == 'FRAME':
                continue
            pos = _absolute_location(node)
            width = max(node.width, 120)
            node_height = max(node.dimensions.y, 100)
            if x < pos.x + width + 30 and x + entry.width + 30 > pos.x:
                if y > pos.y - node_height - 30 and y - height < pos.y + 30:
                    collisions.append(pos.y - node_height - 60)
        if not collisions:
            break
        y = min(collisions)
    entry.location = (x, y)
    entry.select = False
    return entry


def expose_group_inputs(tree, selected):
    if tree is None or tree.bl_idname != 'GeometryNodeTree':
        raise ValueError('请在几何节点编辑器中操作')
    if not getattr(tree, 'is_editable', tree.library is None):
        raise ValueError('当前节点树不可编辑，请先制作本地副本')
    selected = [node for node in selected if node.id_data == tree
                and node.bl_idname == 'GeometryNodeGroup' and node.node_tree]
    if not selected:
        raise ValueError('请选中至少一个几何节点组节点')
    selected.sort(key=lambda node: (-_absolute_location(node).y, _absolute_location(node).x, node.name))
    animated = _animation_paths(tree)
    candidates = []
    skipped = 0
    for node in selected:
        for item in node.node_tree.interface.items_tree:
            if item.item_type != 'SOCKET' or item.in_out != 'INPUT':
                continue
            socket = node.inputs.get(item.identifier)
            if socket is None or socket.is_linked:
                continue
            if (not socket.enabled or socket.bl_idname == 'NodeSocketVirtual'
                    or (hasattr(socket, 'default_value') and socket.path_from_id('default_value') in animated)):
                skipped += 1
                continue
            candidates.append((node, item.identifier, item, _value(socket)))
    if not candidates:
        return {'sockets': 0, 'panels': 0, 'skipped': skipped, 'entry': None}

    # 新接口默认值不会自动同步到已有外层组节点/修改器；只初始化本次新增的接口。
    users = [node for group in bpy.data.node_groups for node in group.nodes
             if getattr(node, 'node_tree', None) == tree]
    modifiers = [mod for obj in bpy.data.objects for mod in obj.modifiers
                 if mod.type == 'NODES' and mod.node_group == tree]
    modifier_keys = [(mod, set(_modifier_inputs(mod).keys())) for mod in modifiers]
    old_selection = [(node, node.select) for node in tree.nodes]
    old_active = tree.nodes.active
    active_index = getattr(tree.interface, 'active_index', None)
    entry = next((node for node in tree.nodes if node.bl_idname == 'NodeGroupInput'
                  and node.get(_ENTRY_TAG, False)), None)
    created_entry = entry is None
    created = []
    added_sockets = []
    added_links = []
    panels = {}
    group_panels = {}
    used_names = {item.name for item in tree.interface.items_tree
                  if item.item_type == 'SOCKET' and item.in_out == 'INPUT'}

    def parent_panel(node, source):
        if source is None or source.parent is None:
            if len(selected) == 1:
                return None
            if node not in group_panels:
                panel = tree.interface.new_panel(name=node.label or node.name)
                created.append(panel)
                group_panels[node] = panel
            return group_panels[node]
        key = (node.as_pointer(), source.as_pointer())
        if key not in panels:
            parent = parent_panel(node, source.parent)
            panel = tree.interface.new_panel(name=source.name,
                description=getattr(source, 'description', ''), default_closed=source.default_closed)
            created.append(panel)
            if parent is not None:
                tree.interface.move_to_parent(panel, parent, len(parent.interface_items))
            panels[key] = panel
        return panels[key]

    try:
        if entry is None:
            entry = _new_entry(tree, selected, len(candidates))
        for node, identifier, source, value in candidates:
            socket = node.inputs[identifier]
            parent = parent_panel(node, source.parent)
            name = source.name
            suffix = 2
            while name in used_names:
                name = f'{source.name} ({suffix})'
                suffix += 1
            target = tree.interface.new_socket(name=name, in_out='INPUT',
                                              socket_type=source.socket_type, parent=parent)
            created.append(target)
            used_names.add(target.name)
            target.from_socket(node, socket)
            for setting in _SOCKET_SETTINGS:
                if hasattr(source, setting) and hasattr(target, setting):
                    setattr(target, setting, getattr(source, setting))
            link = tree.links.new(entry.outputs[target.identifier], node.inputs[identifier])
            added_links.append(link)
            # Menu 的选项由下游连接传播，连接完成后才可写默认项。
            if value is not None and hasattr(target, 'default_value'):
                target.default_value = value
            for user in users:
                user_socket = user.inputs.get(target.identifier)
                if value is not None and user_socket is not None and hasattr(user_socket, 'default_value'):
                    user_socket.default_value = value
            for mod in modifiers:
                if value is not None and hasattr(target, 'default_value'):
                    _set_modifier_value(mod, target.identifier, value)
            added_sockets.append(target)
        for socket in entry.outputs:
            socket.hide = not socket.is_linked
    except Exception:
        for link in reversed(added_links):
            tree.links.remove(link)
        for item in reversed(created):
            tree.interface.remove(item)
        for mod, keys in modifier_keys:
            inputs = _modifier_inputs(mod)
            for key in list(inputs.keys()):
                if key not in keys:
                    del inputs[key]
        if created_entry and entry is not None:
            tree.nodes.remove(entry)
        raise
    finally:
        for node, select in old_selection:
            node.select = select
        tree.nodes.active = old_active
        if active_index is not None:
            tree.interface.active_index = active_index
    return {'sockets': len(added_sockets), 'panels': len(panels) + len(group_panels),
            'skipped': skipped, 'entry': entry}


class NODE_OT_expose_group_inputs_visn(bpy.types.Operator):
    bl_idname = 'node.expose_group_inputs_visn'
    bl_label = '封装当前节点入口'
    bl_description = '把选中节点组未连接的输入接到一个独立入口，同步参数值及 Panel 分组；跳过已有连接和动画输入'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return current_geometry_tree(context) is not None

    def execute(self, context):
        tree = current_geometry_tree(context)
        try:
            result = expose_group_inputs(tree, [node for node in tree.nodes if node.select])
        except Exception as exc:
            self.report({'ERROR'}, f'无法封装入口：{exc}')
            return {'CANCELLED'}
        context.area.tag_redraw()
        text = (f'已封装 {result["sockets"]} 个输入，同步 {result["panels"]} 个 Panel'
                if result['sockets'] else '没有需要封装的未连接输入')
        if result['skipped']:
            text += f'；跳过 {result["skipped"]} 个不可连接或带动画/驱动的输入'
        self.report({'INFO'}, text)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(NODE_OT_expose_group_inputs_visn)


def unregister():
    bpy.utils.unregister_class(NODE_OT_expose_group_inputs_visn)
