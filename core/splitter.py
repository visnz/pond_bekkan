# 拆分物体：把一个物体一键拆成多个独立物体
# 按松散块(不相连的部分各自成体) / 按材质；拆完每块原点各自居中
# （合并自 Pond/splitter.py：逻辑层；面板在 ui/pond/panels/splitter.py）
import bpy


def _active_mesh(context):
    obj = context.active_object
    return obj if obj and obj.type == "MESH" else None


class POND_OT_split(bpy.types.Operator):
    """把选中物体拆成多个独立物体"""
    bl_idname = "pond.split"
    bl_label = "拆分"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        wm = context.window_manager
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        # 网格被多个物体共用时先断开,免得拆坏别人
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj

        before = set(context.scene.objects)
        v_before = len(obj.data.vertices)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        # 拆之前先按距离焊点：重合没焊上的顶点会让一块被误拆成碎渣
        merged = 0
        if wm.pond_split_merge > 0:
            bpy.ops.mesh.remove_doubles(threshold=wm.pond_split_merge)
            bpy.ops.object.mode_set(mode="OBJECT")
            merged = v_before - len(obj.data.vertices)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.mesh.separate(type="LOOSE")
        except RuntimeError as e:
            bpy.ops.object.mode_set(mode="OBJECT")
            self.report({"ERROR"}, f"拆不开: {str(e)[:100]}")
            return {"CANCELLED"}
        bpy.ops.object.mode_set(mode="OBJECT")

        pieces = [o for o in context.scene.objects if o not in before] + [obj]
        # 原物体可能被拆空(全分出去了),清掉空壳
        alive = []
        for o in pieces:
            if o.type == "MESH" and len(o.data.vertices) == 0:
                bpy.data.objects.remove(o, do_unlink=True)
            else:
                alive.append(o)
        if wm.pond_split_center:
            bpy.ops.object.select_all(action="DESELECT")
            for o in alive:
                o.select_set(True)
            if alive:
                context.view_layer.objects.active = alive[0]
                bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")
        n = len(alive)
        msg = ("先焊了 %d 个重合点，" % merged) if merged else ""
        if n <= 1:
            self.report({"INFO"}, msg + "本来就是一整块，没什么可拆的")
        else:
            self.report({"INFO"}, msg + f"拆成 {n} 个物体" +
                        ("，原点各自居中" if wm.pond_split_center else ""))
        return {"FINISHED"}


_classes = (
    POND_OT_split,
)


def register():
    bpy.types.WindowManager.pond_split_center = bpy.props.BoolProperty(
        name="拆完原点各自居中", default=True)
    bpy.types.WindowManager.pond_split_merge = bpy.props.FloatProperty(
        name="先按距离焊点", default=0.0001, min=0.0, soft_max=0.01,
        precision=5, description="拆之前先把这个距离内的重合顶点焊上;填0=不焊")
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.pond_split_merge
    del bpy.types.WindowManager.pond_split_center
