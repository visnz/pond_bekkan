# 父子级：打组/拎出/释放/选择父级（合并核心）
#
# 重要更正（合并核查发现，已更新进 合并对照清单.md 第 4 节）：
# 两项目的「父子级」工具大部分**语义不同**，并非同一功能的两种实现：
#   - Pond「所选打组」= 直接挂到激活物体下；Bekkan「到上级」= 新建空物体包裹
#   - Pond「拎出」= 保子树摘自己；Bekkan「拎出」= 孩子先释放给上级、再摘自己
#   - Pond「拎出并删除」= 删原父级链；Bekkan「拎出并删除」= 删所选物体自己
# 因此除「选择父级」（语义等价，采用 Pond 实现）外，两边 op 全部保留、忠实移植。
# Bekkan 独有 op 保留原 bl_idname（_visn / camera.*），Pond op 保留 pond.*。
# （合并自 Pond/hierarchy.py + Bekkan/STOOL_part/ParentsOps.py；
#   面板在 ui/pond/panels/hierarchy.py 与 ui/bekkan/panels.py）
import bpy


# ── 共享助手（源自 Bekkan/ParentsOps.py，core/stage.py 也引用） ──

def centro(sel):
    """所选物体的局部坐标中心"""
    return tuple(sum(o.location[i] for o in sel) / len(sel) for i in range(3))


def centro_global(sel):
    """所选物体的世界坐标中心"""
    return tuple(sum(o.matrix_world.translation[i] for o in sel) / len(sel) for i in range(3))


def get_children(obj):
    return [ob for ob in bpy.data.objects if ob.parent == obj]


def _checked_objs(op, context):
    """公共检查：无选中则报错返回 None，并尝试切回物体模式"""
    objs = context.selected_objects
    if not objs:
        op.report({'WARNING'}, "没有选中的物体")
        return None
    try:
        bpy.ops.object.mode_set()
    except Exception:
        pass
    return objs


def _release_children(obj):
    """释放 obj 的下级：有上级则转给上级，否则放到世界层级"""
    for ch in get_children(obj):
        ch.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        if obj.parent:
            bpy.context.view_layer.objects.active = obj.parent
            bpy.ops.object.parent_no_inverse_set(keep_transform=True)
        ch.select_set(False)


class _Ctx:
    """改父级时保持世界矩阵不变：with _Ctx(obj): obj.parent = xxx（源自 Pond）"""

    def __init__(self, obj):
        self._obj = obj
        self._m = None

    def __enter__(self):
        self._m = self._obj.matrix_world.copy()
        return self._obj

    def __exit__(self, *a):
        self._obj.matrix_world = self._m


def _active_parent(context):
    parent = context.active_object
    children = [o for o in context.selected_objects if o != parent]
    if not parent or not children:
        return None, None
    return parent, children


# ══════════════════════════════════════════════════════════
# Pond 原版 op（忠实平移）
# ══════════════════════════════════════════════════════════

class POND_OT_group_to_parent(bpy.types.Operator):
    """把其他所选物体挂到激活物体下面（世界变换不变）"""
    bl_idname = "pond.group_to_parent"
    bl_label = "所选打组"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        p, c = _active_parent(context)
        return p is not None

    def execute(self, context):
        parent, children = _active_parent(context)
        for child in children:
            with _Ctx(child):
                child.parent = parent
        self.report({"INFO"}, f"{len(children)} 个 → 「{parent.name}」")
        return {"FINISHED"}


class POND_OT_group_each(bpy.types.Operator):
    """每个被选物体带上它自己的子树，各自挂到激活物体下面"""
    bl_idname = "pond.group_each"
    bl_label = "单独每个打组"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        p, c = _active_parent(context)
        return p is not None

    def execute(self, context):
        parent, children = _active_parent(context)
        for child in children:
            with _Ctx(child):
                child.parent = parent
        return {"FINISHED"}


class POND_OT_select_parents(bpy.types.Operator):
    """选中所有所选物体的直接父级（语义与 Bekkan SelectParent 等价，采用本实现）"""
    bl_idname = "pond.select_parents"
    bl_label = "选择所有父级"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        parents = {o.parent for o in context.selected_objects if o.parent}
        if not parents:
            self.report({"WARNING"}, "所选都没有父级")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        for p in parents:
            p.select_set(True)
        context.view_layer.objects.active = next(iter(parents))
        return {"FINISHED"}


class POND_OT_release_up(bpy.types.Operator):
    """把所选物体从父级里提出来，挂到祖父级（没祖父就回场景根）"""
    bl_idname = "pond.release_up"
    bl_label = "释放到上级（自身上移）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.parent for o in context.selected_objects)

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.parent:
                with _Ctx(obj):
                    obj.parent = obj.parent.parent
        return {"FINISHED"}


class POND_OT_extract(bpy.types.Operator):
    """把所选物体连同子树整体拎出所有层级，回到场景根"""
    bl_idname = "pond.extract"
    bl_label = "拎出(带全家)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.parent for o in context.selected_objects)

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.parent:
                with _Ctx(obj):
                    obj.parent = None
        return {"FINISHED"}


class POND_OT_extract_delete(bpy.types.Operator):
    """拎出所选物体，把它原来的整个父级链删掉"""
    bl_idname = "pond.extract_delete"
    bl_label = "拎出并删除原层级"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.parent for o in context.selected_objects)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        doomed = set()
        for obj in context.selected_objects:
            p = obj.parent
            while p:
                doomed.add(p)
                p = p.parent
        for obj in context.selected_objects:
            if obj.parent:
                with _Ctx(obj):
                    obj.parent = None
        doomed -= set(context.selected_objects)
        for d in doomed:
            bpy.data.objects.remove(d, do_unlink=True)
        return {"FINISHED"}


# ══════════════════════════════════════════════════════════
# Bekkan 原版 op（忠实平移，保留原 bl_idname）
# ══════════════════════════════════════════════════════════

class CAMERA_OT_create_focus_object(bpy.types.Operator):
    """创建对焦对象+黑框"""
    bl_idname = "camera.create_focus_object"
    bl_label = "创建对焦对象"
    bl_description = "为当前摄像机生成一个子空物体作为景深对焦对象，并开启景深与外围遮黑"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        cam = context.scene.camera
        if not cam:
            self.report({"ERROR"}, "当前场景没有设置活跃摄像机。请先设置一个摄像机为场景相机。")
            return {"CANCELLED"}
        if cam.type != 'CAMERA':
            self.report({"ERROR"}, f"当前活跃物体 '{cam.name}' 不是摄像机类型。")
            return {"CANCELLED"}
        focus = bpy.data.objects.new("Focus_Object", None)
        focus.parent = cam
        focus.location = (0, 0, -5)
        # 创建在摄像机所在的集合
        linked = False
        for coll in cam.users_collection:
            coll.objects.link(focus)
            linked = True
            break
        if not linked:
            context.collection.objects.link(focus)
        cam.data.dof.use_dof = True
        cam.data.dof.focus_object = focus
        cam.data.show_passepartout = True
        cam.data.passepartout_alpha = 1.0
        focus.select_set(True)
        bpy.ops.object.parent_no_inverse_set(keep_transform=True)
        focus.select_set(False)
        self.report({"INFO"}, f"已为摄像机 '{cam.name}' 创建对焦空物体 '{focus.name}'，并开启景深与外围遮黑。")
        return {"FINISHED"}


class SoloPick(bpy.types.Operator):
    # 断开所选物体的所有上下级关系，捡出来放在世界层级，下级归更上一层上级管。
    bl_idname = "object.solo_pick_visn"
    bl_label = "拎出"
    bl_description = "断开所有选择物体的上下级"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _checked_objs(self, context)
        if objs is None:
            return {'CANCELLED'}
        for obj in objs:
            obj.select_set(False)
        for obj in objs:
            _release_children(obj)
        for obj in objs:
            obj.select_set(True)
            bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            obj.select_set(False)
        for obj in objs:
            obj.select_set(True)
        return {'FINISHED'}


class SoloPick_delete(bpy.types.Operator):
    bl_idname = "object.solo_pick_delete_visn"
    bl_label = "拎出并删除"
    bl_description = "删除选中物体（不含上下级）"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _checked_objs(self, context)
        if objs is None:
            return {'CANCELLED'}
        for obj in objs:
            obj.select_set(False)
        for obj in objs:
            _release_children(obj)
        for obj in objs:
            obj.select_set(True)
            bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
            obj.select_set(False)
        for obj in objs:
            obj.select_set(True)
        bpy.ops.object.delete(use_global=False)
        return {'FINISHED'}


class RAQtoSubparent(bpy.types.Operator):
    bl_idname = "object.release_all_children_to_subparent_visn"
    bl_label = "释放到上级"
    bl_description = "释放子对象（到上级）"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _checked_objs(self, context)
        if objs is None:
            return {'CANCELLED'}
        no_parent = False
        for obj in objs:
            obj.select_set(False)
        for obj in objs:
            if not obj.parent:
                no_parent = True
            _release_children(obj)
        if not no_parent:
            for obj in objs:
                bpy.context.view_layer.objects.active = obj.parent
                obj.parent.select_set(True)
        return {'FINISHED'}


class P2E_individual(bpy.types.Operator):
    bl_idname = "object.parent_to_empty_visn_individual"
    bl_label = "所选物体 单独每个到上级"
    bl_description = "所有所选物体，每个对象都创建一个保护上级"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _checked_objs(self, context)
        if objs is None:
            return {'CANCELLED'}
        act = context.view_layer.objects.active  # 最后选中的活跃对象

        # 为每个选中的物体创建一个独立的上级空物体
        for obj in objs:
            bpy.ops.object.add(type='EMPTY', location=obj.location.copy(),
                               rotation=obj.rotation_euler)
            empty = context.object

            # 把空物体移到物体所在集合
            try:
                for col in obj.users_collection:
                    col.objects.link(empty)
                context.collection.objects.unlink(empty)
            except Exception:
                pass

            empty.parent = obj.parent  # 继承原始物体的上级
            obj.select_set(True)
            context.view_layer.objects.active = empty
            bpy.ops.object.parent_no_inverse_set(keep_transform=True)
            obj.select_set(False)

        # 恢复原始选择状态
        for obj in objs:
            obj.select_set(True)
        if act:
            context.view_layer.objects.active = act
        return {'FINISHED'}


class P2E(bpy.types.Operator):
    bl_idname = "object.parent_to_empty_visn"
    bl_label = "所选物体 到上级"
    bl_description = "所有所选物体到上级"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _checked_objs(self, context)
        if objs is None:
            return {'CANCELLED'}
        act = context.view_layer.objects.active  # 最后选中的活跃对象
        same_parent = all(o.parent == objs[0].parent for o in objs)

        if len(objs) == 1:
            bpy.ops.object.add(type='EMPTY', location=centro(objs),
                               rotation=objs[0].rotation_euler)
        else:
            bpy.ops.object.add(type='EMPTY', location=centro(objs))
        empty = context.object

        # 把空物体和子对象都移到活跃对象所在集合
        if act is not None:
            cols = act.users_collection
            try:
                for col in cols:
                    col.objects.link(empty)
                context.collection.objects.unlink(empty)
            except Exception:
                pass
            for o in objs:
                for col in o.users_collection:
                    col.objects.unlink(o)
                for col in cols:
                    col.objects.link(o)

        if same_parent:
            empty.parent = objs[0].parent

        for o in objs:
            o.select_set(True)
            bpy.ops.object.parent_no_inverse_set(keep_transform=True)
            o.select_set(False)
        return {'FINISHED'}


class P2E_anim_migrate(bpy.types.Operator):
    """单选物体：在锚点创建上级空物体包裹，并把动画迁移到上级"""
    bl_idname = "object.parent_to_empty_anim_visn"
    bl_label = "单体迁移动画 到上级"
    bl_description = "单选一个物体：在其锚点创建上级空物体包裹它，并把该物体的动画迁移到上级空物体上"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # 只能单选一个物体使用
        return len(context.selected_objects) == 1

    def execute(self, context):
        obj = context.selected_objects[0]
        P = obj.parent
        M = obj.matrix_world.copy()

        # 1) 在物体锚点创建上级空物体（逻辑与基础功能一致）
        empty = bpy.data.objects.new(f"{obj.name}_上级", None)
        empty.empty_display_type = 'ARROWS'
        empty.rotation_mode = obj.rotation_mode

        if P is not None:
            # 继承原上级：空物体与原物体处在同一上级空间，局部变换直接对齐即可
            empty.parent = P
            empty.location = obj.location.copy()
            if obj.rotation_mode == 'QUATERNION':
                empty.rotation_quaternion = obj.rotation_quaternion.copy()
            elif obj.rotation_mode == 'AXIS_ANGLE':
                empty.rotation_axis_angle = obj.rotation_axis_angle
            else:
                empty.rotation_euler = obj.rotation_euler.copy()
            empty.scale = obj.scale.copy()
        else:
            # 无上级：空物体直接放到物体的世界锚点
            empty.location = M.translation.copy()
            if obj.rotation_mode == 'QUATERNION':
                empty.rotation_quaternion = M.to_quaternion()
            elif obj.rotation_mode == 'AXIS_ANGLE':
                axis, angle = M.to_quaternion().to_axis_angle()
                empty.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
            else:
                empty.rotation_euler = M.to_euler()
            empty.scale = M.to_scale()

        # 把空物体放入物体所在集合，并确保它位于当前视图层（否则无法被选中）
        for col in obj.users_collection:
            try:
                col.objects.link(empty)
            except Exception:
                pass
        vl_col = context.view_layer.active_layer_collection.collection
        try:
            vl_col.objects.link(empty)
        except Exception:
            pass

        # 2) 把物体的动画迁移到上级空物体：为每个 fcurve 创建对应曲线并复制关键帧，
        #    避免依赖 NLA 或 slotted action 的绑定行为差异。
        migrated = 0
        ad = obj.animation_data
        if ad and ad.action:
            src_action = ad.action
            dst_action = bpy.data.actions.new(name=f"{obj.name}_上级")

            # 复制 fcurve（关键帧 + 插值 + handle + 修饰器）
            for src_fc in src_action.fcurves:
                try:
                    dst_fc = dst_action.fcurves.new(
                        data_path=src_fc.data_path,
                        index=src_fc.array_index,
                        action_group=src_fc.group.name if src_fc.group else ""
                    )
                except Exception:
                    # 空物体没有的属性（如 shape key、modifier 属性）跳过
                    continue

                # 复制关键帧
                n = len(src_fc.keyframe_points)
                dst_fc.keyframe_points.add(n)
                for src_kp, dst_kp in zip(src_fc.keyframe_points, dst_fc.keyframe_points):
                    dst_kp.co = src_kp.co
                    dst_kp.handle_left = src_kp.handle_left
                    dst_kp.handle_right = src_kp.handle_right
                    dst_kp.handle_left_type = src_kp.handle_left_type
                    dst_kp.handle_right_type = src_kp.handle_right_type
                    dst_kp.interpolation = src_kp.interpolation
                    dst_kp.type = src_kp.type

                # 复制 fcurve 修饰器
                for src_mod in src_fc.modifiers:
                    try:
                        dst_mod = dst_fc.modifiers.new(type=src_mod.type)
                        for attr in dir(src_mod):
                            if attr.startswith('_') or attr in {'type', 'name', 'bl_rna', 'rna_type'}:
                                continue
                            try:
                                setattr(dst_mod, attr, getattr(src_mod, attr))
                            except (AttributeError, TypeError):
                                pass
                    except Exception:
                        pass

                migrated += len(dst_fc.keyframe_points)

            # 清除原物体动画数据，空物体接管新 action
            obj.animation_data_clear()
            empty.animation_data_create()
            empty.animation_data.action = dst_action

        # 3) 把物体包进上级空物体：上级=空物体，物体自身变换归零（局部单位化），
        #    这样物体世界变换完全由上级空物体的动画驱动，视觉上与原动画一致。
        obj.parent = empty
        obj.matrix_parent_inverse.identity()
        obj.location = (0.0, 0.0, 0.0)
        if obj.rotation_mode == 'QUATERNION':
            obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        elif obj.rotation_mode == 'AXIS_ANGLE':
            obj.rotation_axis_angle = (0.0, 0.0, 0.0, 1.0)
        else:
            obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)

        obj.select_set(True)
        empty.select_set(True)
        context.view_layer.objects.active = empty

        if migrated:
            self.report({'INFO'}, f"已在锚点创建上级空物体 '{empty.name}'，并迁移 {migrated} 条动画曲线到上级")
        else:
            self.report({'INFO'}, f"已在锚点创建上级空物体 '{empty.name}' 包裹 '{obj.name}'（无动画可迁移）")
        return {'FINISHED'}


_classes = (
    # Pond
    POND_OT_group_to_parent,
    POND_OT_group_each,
    POND_OT_select_parents,
    POND_OT_release_up,
    POND_OT_extract,
    POND_OT_extract_delete,
    # Bekkan
    CAMERA_OT_create_focus_object,
    SoloPick,
    SoloPick_delete,
    RAQtoSubparent,
    P2E,
    P2E_individual,
    P2E_anim_migrate,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
