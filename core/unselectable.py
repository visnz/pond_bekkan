# 别馆 · 不可选对象管理。列表直接读场景对象，只有临时解锁状态随工程保存。
import bpy
from bpy.app.handlers import persistent


_msgbus_owner = object()
_display_lock_states = {}


def managed_object(obj):
    return obj.hide_select or getattr(obj, 'bekkan_selection_adjusting', False)


def _tag_redraw(_self=None, _context=None):
    manager = getattr(bpy.context, 'window_manager', None)
    if manager:
        for window in manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


def _sync_object_display(obj):
    """只联动禁选对象和刚解锁对象，不覆盖普通可选对象的自定义显示。"""
    uid = obj.session_uid
    was_locked = _display_lock_states.get(uid, False)
    _display_lock_states[uid] = obj.hide_select
    target = 'BOUNDS' if obj.hide_select else (
        'TEXTURED' if was_locked or getattr(obj, 'bekkan_selection_adjusting', False) else None)
    if (target and obj.is_editable and hasattr(obj, 'display_type')
            and not obj.is_property_readonly('display_type') and obj.display_type != target):
        obj.display_type = target
        return True
    return False


def _sync_display_modes():
    objects = getattr(bpy.data, 'objects', None)
    if objects is None:
        return False  # addon_utils.enable 的 RestrictBlend 阶段不能读取工程。
    live_uids = set()
    for obj in objects:
        live_uids.add(obj.session_uid)
        _sync_object_display(obj)
    for uid in _display_lock_states.keys() - live_uids:
        del _display_lock_states[uid]
    _tag_redraw()
    return True


def _initial_display_sync():
    """注册结束后再同步已有对象；若暂时仍受限，下一次事件循环重试。"""
    return None if _sync_display_modes() else 0.1


@persistent
def _on_depsgraph(_scene, depsgraph):
    # 原生 UI 和脚本均可改 hide_select；只检查本次更新的对象，避免每帧全场景扫描。
    changed = False
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Object):
            changed = _sync_object_display(update.id.original) or changed
    if changed:
        _tag_redraw()


def _subscribe():
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    for prop, callback in (('hide_select', _sync_display_modes), ('name', _tag_redraw)):
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Object, prop), owner=_msgbus_owner,
            args=(), notify=callback,
        )


@persistent
def _on_load(_dummy):
    # 读文件会清空消息订阅；重新订阅后立即显示新场景已有的禁选对象。
    _display_lock_states.clear()
    _subscribe()
    _sync_display_modes()


@persistent
def _on_history(_dummy):
    _sync_display_modes()


def _has_selectable_collection_path(obj, view_layer):
    """同一对象可属于多个集合；任一可用路径未禁选即可，不擅自解锁整组。"""
    collections = set(obj.users_collection)
    pending = [view_layer.layer_collection]
    while pending:
        layer = pending.pop()
        collection = layer.collection
        if (layer.exclude or layer.hide_viewport or collection.hide_viewport
                or collection.hide_select):
            continue
        if collection in collections:
            return True
        pending.extend(layer.children)
    return False


def unlock_and_select(context, obj):
    """显式从面板解锁的对象保留在列表，用户可以调整完再锁回去。"""
    if obj.name not in context.view_layer.objects:
        raise ValueError('对象不在当前视图层，请先切换视图层或启用所在集合')
    viewport = context.space_data if context.space_data and context.space_data.type == 'VIEW_3D' else None
    if not obj.visible_get(view_layer=context.view_layer, viewport=viewport):
        raise ValueError('对象当前被隐藏或不在局部视图中，请先显示它')
    if not _has_selectable_collection_path(obj, context.view_layer):
        raise ValueError('对象所在集合被禁止选择，请先解除集合的禁选')

    was_locked = obj.hide_select
    was_adjusting = obj.bekkan_selection_adjusting
    was_display = obj.display_type
    selected = tuple(context.selected_objects)
    active = context.view_layer.objects.active
    try:
        obj.bekkan_selection_adjusting = True
        obj.hide_select = False
        for other in selected:
            other.select_set(False)
        obj.select_set(True)
        if not obj.select_get():
            raise ValueError('对象仍不可选择，请检查集合或视图层限制')
        context.view_layer.objects.active = obj
        _sync_object_display(obj)
    except Exception:
        obj.select_set(False)
        obj.hide_select = was_locked
        obj.bekkan_selection_adjusting = was_adjusting
        if obj.display_type != was_display:
            obj.display_type = was_display
        for other in selected:
            other.select_set(True)
        context.view_layer.objects.active = active
        raise


def _activate_list_item(scene, context):
    """原生列表行的高亮点击也要解锁并激活；非面板上下文不改变现场选择。"""
    space = context.space_data
    region = context.region
    if (context.scene != scene or context.mode != 'OBJECT' or not space
            or space.type != 'VIEW_3D' or not region or region.type != 'UI'):
        return
    index = scene.bekkan_unselectable_index
    if not 0 <= index < len(scene.objects):
        return
    obj = scene.objects[index]  # template_list 的索引对应原集合，不是过滤/排序后的行号。
    if managed_object(obj):
        bpy.ops.object.manage_unselectable_visn(
            'EXEC_DEFAULT', target_uid=str(obj.session_uid), action='EDIT')


class OBJECT_OT_manage_unselectable_visn(bpy.types.Operator):
    bl_idname = 'object.manage_unselectable_visn'
    bl_label = '管理不可选对象'
    bl_options = {'REGISTER', 'UNDO'}

    target_uid: bpy.props.StringProperty(options={'HIDDEN'})
    action: bpy.props.EnumProperty(
        items=[('EDIT', '解锁并激活', ''), ('LOCK', '重新锁定', ''),
               ('FORGET', '保持可选并移出列表', '')],
        options={'HIDDEN'},
    )

    @classmethod
    def description(cls, context, properties):
        return {
            'EDIT': '切回 Textured，解锁、选中并设为当前活跃对象，保留在列表中以便重新锁定',
            'LOCK': '重新禁止选择此对象并显示为 Bounds，结束临时调整',
            'FORGET': '保持对象可选，并将它从调整列表中移除；不会删除物体',
        }.get(properties.action, '管理不可选对象')

    @classmethod
    def poll(cls, context):
        if not context.scene or context.mode != 'OBJECT':
            cls.poll_message_set('请回到物体模式管理对象的可选择性')
            return False
        return True

    def execute(self, context):
        # session_uid 不随改名变化，也不会把同名链接对象认成另一个对象。
        obj = next((o for o in context.scene.objects if str(o.session_uid) == self.target_uid), None)
        if obj is None:
            self.report({'WARNING'}, '对象已删除或已移出当前场景')
            return {'CANCELLED'}
        if not obj.is_editable:
            self.report({'WARNING'}, '此对象为不可编辑的链接数据')
            return {'CANCELLED'}
        try:
            if self.action == 'EDIT':
                unlock_and_select(context, obj)
            elif self.action == 'LOCK':
                obj.hide_select = True
                obj.bekkan_selection_adjusting = False
                _sync_object_display(obj)
                if obj.name in context.view_layer.objects:
                    obj.select_set(False)
                    if context.view_layer.objects.active == obj:
                        context.view_layer.objects.active = None
            else:
                if obj.hide_select:
                    self.report({'WARNING'}, '禁选对象自动留在列表；请先解锁')
                    return {'CANCELLED'}
                obj.bekkan_selection_adjusting = False
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        _tag_redraw()
        return {'FINISHED'}


def register():
    bpy.types.Object.bekkan_selection_adjusting = bpy.props.BoolProperty(
        name='临时解锁调整中', default=False,
        description='从不可选对象面板解锁后继续保留，方便调整完重新锁定',
        update=_tag_redraw,
    )
    bpy.types.Scene.bekkan_unselectable_index = bpy.props.IntProperty(
        default=0, min=0, update=_activate_list_item)
    bpy.utils.register_class(OBJECT_OT_manage_unselectable_visn)
    _subscribe()
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.undo_post.append(_on_history)
    bpy.app.handlers.redo_post.append(_on_history)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.timers.register(_initial_display_sync, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_initial_display_sync):
        bpy.app.timers.unregister(_initial_display_sync)
    bpy.msgbus.clear_by_owner(_msgbus_owner)
    for handlers, callback in (
        (bpy.app.handlers.load_post, _on_load),
        (bpy.app.handlers.undo_post, _on_history),
        (bpy.app.handlers.redo_post, _on_history),
        (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
    ):
        if callback in handlers:
            handlers.remove(callback)
    bpy.utils.unregister_class(OBJECT_OT_manage_unselectable_visn)
    del bpy.types.Scene.bekkan_unselectable_index
    del bpy.types.Object.bekkan_selection_adjusting
    _display_lock_states.clear()
