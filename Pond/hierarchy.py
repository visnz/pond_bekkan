# 父子级操作：C4D 手感的打组/拎出系列
import bpy

from . import prefs
from mathutils import Vector


def _keep_world(obj, new_parent):
    """改父级但保持世界变换不动"""
    mw = obj.matrix_world.copy()
    obj.parent = new_parent
    obj.matrix_world = mw


def _link_like(reference_obj, new_obj, context):
    """新对象放进参照对象所在的集合，找不到就丢进场景根"""
    cols = reference_obj.users_collection if reference_obj else ()
    (cols[0] if cols else context.scene.collection).objects.link(new_obj)


def _new_group_empty(name, context, reference_obj=None):
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 0.6
    _link_like(reference_obj, empty, context)
    return empty


class POND_OT_group_to_parent(bpy.types.Operator):
    """所选物体打组到一个父级空物体（C4D 的 Alt+G）"""
    bl_idname = "pond.group_to_parent"
    bl_label = "所选打组"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        sel = list(context.selected_objects)
        center = sum((o.matrix_world.translation for o in sel), Vector()) / len(sel)

        # 所有成员父级一致时，组挂回原层级位置
        parents = {o.parent for o in sel}
        shared = parents.pop() if len(parents) == 1 else None
        if shared in sel:
            shared = None

        empty = _new_group_empty("组", context, context.active_object or sel[0])
        if shared:
            _keep_world(empty, shared)
        empty.matrix_world.translation = center

        for o in sel:
            if o.parent in sel:
                continue  # 已跟着自己的父级走
            _keep_world(o, empty)

        context.view_layer.objects.active = empty
        empty.select_set(True)
        return {"FINISHED"}


class POND_OT_group_each(bpy.types.Operator):
    """每个所选物体单独包一个父级空物体（做分离动画用）"""
    bl_idname = "pond.group_each"
    bl_label = "单独每个打组"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        for o in list(context.selected_objects):
            empty = _new_group_empty(o.name + "_组", context, o)
            if o.parent:
                _keep_world(empty, o.parent)
            empty.matrix_world.translation = o.matrix_world.translation
            _keep_world(o, empty)
        return {"FINISHED"}


class POND_OT_select_parents(bpy.types.Operator):
    """把选择替换成所有所选物体的直接父级"""
    bl_idname = "pond.select_parents"
    bl_label = "选择所有父级"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        parents = {o.parent for o in context.selected_objects if o.parent}
        if not parents:
            self.report({"INFO"}, "所选物体都没有父级")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        for p in parents:
            p.select_set(True)
        context.view_layer.objects.active = next(iter(parents))
        return {"FINISHED"}


class POND_OT_release_up(bpy.types.Operator):
    """所选物体脱离当前父级，挂到上一级（保持位置）"""
    bl_idname = "pond.release_up"
    bl_label = "释放到上级"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        n = 0
        for o in context.selected_objects:
            if o.parent:
                _keep_world(o, o.parent.parent)
                n += 1
        self.report({"INFO"}, f"释放了 {n} 个物体")
        return {"FINISHED"}


def _extract(obj):
    """把 obj 从层级中间抽出来：孩子全部过继给它的父级"""
    for child in list(obj.children):
        _keep_world(child, obj.parent)
    _keep_world(obj, None)


class POND_OT_extract(bpy.types.Operator):
    """从多级层级中间单独拎出所选物体，孩子自动过继"""
    bl_idname = "pond.extract"
    bl_label = "拎出"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        for o in list(context.selected_objects):
            _extract(o)
        return {"FINISHED"}


class POND_OT_extract_delete(bpy.types.Operator):
    """拎出所选物体并删除，孩子过继给上级"""
    bl_idname = "pond.extract_delete"
    bl_label = "拎出并删除"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects

    def execute(self, context):
        for o in list(context.selected_objects):
            _extract(o)
            bpy.data.objects.remove(o)
        return {"FINISHED"}


class POND_PT_hierarchy(bpy.types.Panel):
    bl_label = "父子级"
    bl_idname = "POND_PT_hierarchy"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_tidy"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_hierarchy")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.group_to_parent", icon="OUTLINER_OB_EMPTY")
        col.operator("pond.group_each", icon="EMPTY_AXIS")
        col.operator("pond.select_parents", icon="SORT_DESC")
        col.operator("pond.release_up", icon="EXPORT")
        col.separator()
        col.operator("pond.extract", icon="UNLINKED")
        col.operator("pond.extract_delete", icon="TRASH")


_classes = (
    POND_OT_group_to_parent,
    POND_OT_group_each,
    POND_OT_select_parents,
    POND_OT_release_up,
    POND_OT_extract,
    POND_OT_extract_delete,
    POND_PT_hierarchy,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
