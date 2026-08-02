# 一键整理：清孤立数据、合并重复材质、批量原点
# （合并自 Pond/organize.py：逻辑层；面板在 ui/pond/panels/organize.py）
import re
import bpy

from mathutils import Vector


class POND_OT_purge_orphans(bpy.types.Operator):
    """递归清理所有没被使用的孤立数据块"""
    bl_idname = "pond.purge_orphans"
    bl_label = "清理孤立数据"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
        self.report({"INFO"}, f"清掉了 {n} 个孤立数据块")
        return {"FINISHED"}


class POND_OT_merge_dup_materials(bpy.types.Operator):
    """把 材质.001 这类重复材质合并回本体（本体存在时）"""
    bl_idname = "pond.merge_dup_materials"
    bl_label = "合并重复材质"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        pat = re.compile(r"^(.+)\.\d{3}$")
        merged = 0
        for mat in list(bpy.data.materials):
            m = pat.match(mat.name)
            if not m:
                continue
            base = bpy.data.materials.get(m.group(1))
            if base and base is not mat and not base.library:
                mat.user_remap(base)
                merged += 1
        if merged:
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
        self.report({"INFO"}, f"合并了 {merged} 个重复材质")
        return {"FINISHED"}


class POND_OT_origin_center(bpy.types.Operator):
    """所选物体原点批量设到几何中心"""
    bl_idname = "pond.origin_center"
    bl_label = "原点→几何中心"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.mode == "OBJECT"

    def execute(self, context):
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")
        return {"FINISHED"}


class POND_OT_origin_bottom(bpy.types.Operator):
    """所选物体原点批量设到包围盒底部中心（落地摆放用）"""
    bl_idname = "pond.origin_bottom"
    bl_label = "原点→底部"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and context.mode == "OBJECT"

    def execute(self, context):
        sel = [o for o in context.selected_objects if o.type in
               {"MESH", "CURVE", "SURFACE", "META", "FONT"}]
        if not sel:
            self.report({"WARNING"}, "所选里没有带几何的物体")
            return {"CANCELLED"}

        cursor = context.scene.cursor
        cursor_backup = cursor.location.copy()
        active_backup = context.view_layer.objects.active
        selected_backup = list(context.selected_objects)

        try:
            for o in sel:
                corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
                target = Vector((
                    sum(c.x for c in corners) / 8.0,
                    sum(c.y for c in corners) / 8.0,
                    min(c.z for c in corners),
                ))
                bpy.ops.object.select_all(action="DESELECT")
                o.select_set(True)
                context.view_layer.objects.active = o
                cursor.location = target
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        finally:
            cursor.location = cursor_backup
            bpy.ops.object.select_all(action="DESELECT")
            for o in selected_backup:
                o.select_set(True)
            context.view_layer.objects.active = active_backup
        return {"FINISHED"}


_classes = (
    POND_OT_purge_orphans,
    POND_OT_merge_dup_materials,
    POND_OT_origin_center,
    POND_OT_origin_bottom,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
