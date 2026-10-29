# 搭建类：摄像机组 / 约束灯光 / 清理空物体 / 打开文件夹（合并核心）
# 合并自 Bekkan/STOOL_part/StageOps.py + Pond/cam_rig.py。
# Bekkan 两套机组（C-P / C-SP-ZT）与 Pond 的简洁机组是不同设计，双双保留；
# Bekkan 原版 op 保留原 bl_idname。
# （面板在 ui/bekkan/panels.py 与 ui/pond/panels/cam_rig.py）
import math
import os
import platform
import subprocess
import bpy

from mathutils import Vector

from .hierarchy import centro_global


class DeleteEmptyNull(bpy.types.Operator):
    bl_idname = "object.delete_empty_null_visn"
    bl_label = "删除无内容的Empty"
    bl_description = "删除场景中所有没有下级且没有数据的空物体，保护集合实例"
    bl_options = {"REGISTER", "UNDO"}

    @staticmethod
    def is_coll_instance(obj):
        return getattr(obj, 'instance_type', None) == 'COLLECTION'

    def execute(self, context):
        empties = [o for o in bpy.data.objects if o.type == 'EMPTY']
        # 集合实例保留，其余默认待删
        keep = {o: self.is_coll_instance(o) for o in empties}
        # 直接含非空下级的保留
        for o in empties:
            if not keep[o]:
                keep[o] = any(c.type != 'EMPTY' or self.is_coll_instance(c)
                              for c in o.children)
        # 计算空物体层级深度，自底向上：下级保留则上级也保留
        depth = {}
        for o in empties:
            d, cur = 0, o
            while cur.parent in empties:
                cur = cur.parent
                d += 1
            depth[o] = d
        for o in sorted(empties, key=depth.get, reverse=True):
            if not keep[o]:
                keep[o] = any(keep.get(c) for c in o.children)

        doomed = [o for o in empties if not keep[o]]
        for o in doomed:  # 先解除下级父子关系
            for c in list(o.children):
                c.parent = None
        n = 0
        for o in doomed:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
                n += 1
            except ReferenceError:  # 对象可能已被删除
                pass

        self.report({'INFO'}, f"删除了 {n} 个无内容的空对象" if n else "没有找到需要删除的空对象")
        return {'FINISHED'}


class FastCentreCamera(bpy.types.Operator):
    bl_idname = "object.fast_camera_visn"
    bl_label = "C-P摄像机组"
    bl_description = "创建一个以选择物体为目标点的，中心点+PSR锁定的的摄像机"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = context.selected_objects
        loc = centro_global(objs) if objs else (0, 0, 0)

        # 创建摄像机并对齐当前视图
        bpy.ops.object.camera_add(align='VIEW')
        cam = context.active_object
        cam.name = 'Camera'
        context.space_data.camera = cam
        bpy.ops.view3d.camera_to_view()

        # 创建 Protection 空物体，摄像机挂到其下并锁定 PSR
        bpy.ops.object.add(type='EMPTY', location=cam.location,
                           rotation=cam.rotation_euler)
        camP = context.active_object
        camP.name = 'Camera Protection'
        bpy.ops.object.constraint_add(type='DAMPED_TRACK')
        cam.select_set(True)
        bpy.ops.object.parent_no_inverse_set(keep_transform=True)
        cam.lock_location[:] = cam.lock_rotation[:] = [True] * 3

        # 创建原点的 Central 空物体，Protection 挂到其下
        bpy.ops.object.add(type='EMPTY', location=loc)
        camC = context.active_object
        camC.name = 'Camera Central'
        camP.select_set(True)
        bpy.ops.object.parent_no_inverse_set(keep_transform=True)
        camP.select_set(False)
        cam.select_set(False)
        # 按索引取新建的约束（中文界面下约束名会被翻译，不能按英文名查找）
        track = camP.constraints[-1]
        track.target = camC
        track.track_axis = 'TRACK_NEGATIVE_Z'
        return {'FINISHED'}


class CSPZT_Camera(bpy.types.Operator):
    bl_idname = "object.cspzt_camera_visn"
    bl_label = "C-SP-ZT朝向摄像机组"
    bl_description = "创建包含Central、Stare、Protection、Target和Zup的复杂摄像机组"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = context.selected_objects
        loc = centro_global(objs) if objs else (0, 0, 0)
        # 当前视图的位置和旋转
        view = context.space_data.region_3d.view_matrix
        cam_loc = view.inverted().translation
        cam_rot = view.to_3x3().inverted().to_euler()

        def new_empty(name, location=(0, 0, 0)):
            bpy.ops.object.add(type='EMPTY', location=location)
            o = context.active_object
            o.name = name
            return o

        central = new_empty('Cam_Central--↑（向上添加目标点运动）', loc)
        central.rotation_euler = cam_rot
        zup = new_empty('Cam_Zup', (0, 0, 100000))  # 世界空间，不设上级

        stare = new_empty('Cam_Stare--↑（向上添加摄像机运动）', cam_loc)
        stare.parent = central
        # Damped Track 指向 Central（-Z），Locked Track 指向 Zup（跟踪Y锁Z）
        dt = stare.constraints.new('DAMPED_TRACK')
        dt.target = central
        dt.track_axis = 'TRACK_NEGATIVE_Z'
        lt = stare.constraints.new('LOCKED_TRACK')
        lt.target = zup
        lt.track_axis = 'TRACK_Y'
        lt.lock_axis = 'LOCK_Z'

        protection = new_empty('Cam_Protection--↑（向上添加局部空间运动）')
        protection.parent = stare

        dof_target = new_empty('Cam_DOFTarget', (0, 0, -1))
        dof_target.parent = protection
        dof_target.lock_location = (True, True, False)  # 仅Z轴可动
        dof_target.lock_rotation = dof_target.lock_scale = (True,) * 3

        bpy.ops.object.camera_add()
        cam = context.active_object
        cam.name = 'Cam'
        cam.parent = protection
        cam.location = cam.rotation_euler = (0,) * 3
        cam.lock_location = cam.lock_rotation = cam.lock_scale = (True,) * 3
        cam.data.dof.use_dof = True
        cam.data.dof.focus_object = dof_target

        # 设为当前视图相机并进入摄像机视图
        context.space_data.camera = cam
        bpy.ops.view3d.view_camera()
        return {'FINISHED'}


class OpenProjectFolderOperator(bpy.types.Operator):
    bl_idname = "wm.open_project_folder_visn"
    bl_label = "打开工程所在文件夹"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({'ERROR'}, "当前没有打开的工程文件")
            return {'CANCELLED'}
        folder = os.path.dirname(bpy.data.filepath)
        if platform.system() == 'Windows':
            subprocess.Popen(['explorer', folder])
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
        return {'FINISHED'}


class AddLightWithConstraint(bpy.types.Operator):
    bl_idname = "object.add_light_with_constraint"
    bl_label = "中心约束灯光"
    bl_description = "在所选物体的位置创建一个空对象，并在其下级创建一个灯光，设置 Damped Track 约束"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = context.selected_objects
        if not objs:
            self.report({'WARNING'}, "没有选中的物体")
            return {'CANCELLED'}
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception as e:
            self.report({'WARNING'}, f"无法切换模式: {e}")

        # 临时切换活跃集合到场景根集合，在其下创建约束组
        orig_coll = context.view_layer.active_layer_collection
        context.view_layer.active_layer_collection = context.view_layer.layer_collection

        bpy.ops.object.add(type='EMPTY', location=centro_global(objs))
        empty = context.object
        empty.name = "约束灯光组"

        bpy.ops.object.light_add(type='SPOT', location=empty.location)
        light = context.object
        light.parent = empty
        light.name = "约束灯光"
        light.location = (0, 0, 0)
        dt = light.constraints.new(type='DAMPED_TRACK')
        dt.target = empty
        dt.track_axis = 'TRACK_NEGATIVE_Z'

        context.view_layer.active_layer_collection = orig_coll
        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = light
        light.select_set(True)
        self.report({'INFO'}, "灯光和约束已成功创建")
        return {'FINISHED'}


class POND_OT_cam_rig_build(bpy.types.Operator):
    """以激活物体为中心搭 Root>Orbit>Cam 三级摄像机组"""
    bl_idname = "pond.cam_rig_build"
    bl_label = "搭建摄像机组"
    bl_options = {"REGISTER", "UNDO"}

    height_offset: bpy.props.FloatProperty(name="高度偏移", default=3.0)
    back_offset: bpy.props.FloatProperty(name="后退距离", default=8.0)
    focal: bpy.props.FloatProperty(name="焦距 mm", default=50.0, min=1.0)
    constraint_name: bpy.props.StringProperty(
        name="对准约束名", default="对准目标",
        description="想在别处认出这个约束就靠这个名字")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        target = context.active_object
        center = target.matrix_world.translation.copy()

        root = bpy.data.objects.new("镜头Root", None)
        context.scene.collection.objects.link(root)
        root.location = center

        orbit = bpy.data.objects.new("Orbit", None)
        context.scene.collection.objects.link(orbit)
        orbit.parent = root

        cam_data = bpy.data.cameras.new("镜头Cam")
        cam = bpy.data.objects.new("镜头Cam", cam_data)
        context.scene.collection.objects.link(cam)
        cam.parent = orbit
        cam.location = Vector((0, -self.back_offset, self.height_offset))
        cam_data.lens = self.focal

        point = cam.constraints.new("TRACK_TO")
        point.name = self.constraint_name
        point.target = target
        point.track_axis = "TRACK_NEGATIVE_Z"
        point.up_axis = "UP_Y"

        cam_data.dof.use_dof = True
        cam_data.dof.focus_object = target

        context.scene.camera = cam
        context.view_layer.objects.active = cam
        cam.select_set(True)
        self.report({"INFO"}, f"摄像机组就位：{root.name} > {orbit.name} > {cam.name}")
        return {"FINISHED"}


class StageLegacyFbxImport(bpy.types.Operator):
    """呼出 Blender 内置 FBX 导入器自己的文件选择/选项窗口（骨骼定向等老选项都在
    那个窗口里），不额外包任何自定义参数或逻辑——单纯图个面板里顺手点的入口。"""
    bl_idname = "object.legacy_fbx_import_visn"
    bl_label = "旧版FBX导入器（骨骼定向）"
    bl_description = "呼出 Blender 内置 FBX 导入器的选项窗口，用于需要骨骼定向等老选项的场景"
    bl_options = {"REGISTER"}

    def execute(self, context):
        bpy.ops.import_scene.fbx("INVOKE_DEFAULT")
        return {"FINISHED"}


_ANCHOR_TYPES = {"MESH", "CURVE"}


def _world_points(obj):
    """物体在世界空间下的真实控制点：mesh 顶点 / 曲线控制点+贝塞尔手柄。
    用于算一个贴合实际形状的世界空间包围盒——不能用局部包围盒的 8 个角点
    整体乘 matrix_world：局部 AABB 本身就比圆柱/不规则 mesh 等非箱形状宽松，
    物体旋转后再整体转这个盒子，只会比真实形状的世界空间范围更大（盒子套
    盒子的误差），导致算出来的顶/底偏出视觉边界。贝塞尔曲线段必然落在四个
    控制点（两端点+两手柄）的凸包内，所以手柄也要算进去，否则会漏算手柄
    拉出去的那部分曲线。"""
    mw = obj.matrix_world
    pts = []
    if obj.type == "MESH":
        for v in obj.data.vertices:
            pts.append(mw @ v.co)
    elif obj.type == "CURVE":
        for spline in obj.data.splines:
            if spline.type == "BEZIER":
                for bp in spline.bezier_points:
                    pts.append(mw @ bp.co)
                    pts.append(mw @ bp.handle_left)
                    pts.append(mw @ bp.handle_right)
            else:
                for p in spline.points:
                    pts.append(mw @ Vector(p.co[:3]))
    return pts


def _anchor_to_bbox(context, objs, pick_z):
    """把每个物体的原点移到自身世界空间包围盒的「顶部中心」或「底部中心」
    （pick_z 从世界 Z 坐标列表里选 min 或 max）。XY 取世界空间范围的中点
    （包围盒中心，不是顶点均值——均值会被顶点密度带偏）。
    做法与 core/organize.py 的 POND_OT_origin_bottom 一致：挪 3D 游标到
    目标点、调用 origin_set(ORIGIN_CURSOR)，再把游标和选中状态还原。"""
    sel = [o for o in objs if o.type in _ANCHOR_TYPES]
    if not sel:
        return 0

    cursor = context.scene.cursor
    cursor_backup = cursor.location.copy()
    active_backup = context.view_layer.objects.active
    selected_backup = list(context.selected_objects)
    processed = 0

    try:
        for o in sel:
            pts = _world_points(o)
            if not pts:
                continue
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            zs = [p.z for p in pts]
            target = Vector((
                (min(xs) + max(xs)) / 2.0,
                (min(ys) + max(ys)) / 2.0,
                pick_z(zs),
            ))
            bpy.ops.object.select_all(action="DESELECT")
            o.select_set(True)
            context.view_layer.objects.active = o
            cursor.location = target
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            processed += 1
    finally:
        cursor.location = cursor_backup
        bpy.ops.object.select_all(action="DESELECT")
        for o in selected_backup:
            o.select_set(True)
        context.view_layer.objects.active = active_backup
    return processed


class StageAnchorTop(bpy.types.Operator):
    """所选物体原点批量设到（世界空间）包围盒顶部中心"""
    bl_idname = "object.anchor_to_top_visn"
    bl_label = "锚点到顶部中心"
    bl_description = "把所选物体的原点移到各自包围盒的顶部中心（按物体当前实际的旋转/缩放表现计算）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects) and context.mode == "OBJECT"

    def execute(self, context):
        n = _anchor_to_bbox(context, context.selected_objects, max)
        if n == 0:
            self.report({"WARNING"}, "所选里没有带几何的物体")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已将 {n} 个物体的原点设到包围盒顶部中心")
        return {"FINISHED"}


class StageAnchorBottom(bpy.types.Operator):
    """所选物体原点批量设到（世界空间）包围盒底部中心"""
    bl_idname = "object.anchor_to_bottom_visn"
    bl_label = "锚点到底部中心"
    bl_description = "把所选物体的原点移到各自包围盒的底部中心（按物体当前实际的旋转/缩放表现计算）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects) and context.mode == "OBJECT"

    def execute(self, context):
        n = _anchor_to_bbox(context, context.selected_objects, min)
        if n == 0:
            self.report({"WARNING"}, "所选里没有带几何的物体")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已将 {n} 个物体的原点设到包围盒底部中心")
        return {"FINISHED"}


def _world_bbox(obj):
    """物体世界空间包围盒角点，返回 (max_span, bottom_z)：
    max_span 取 XYZ 三轴跨度里最大的一个作为该物体的"体量"代表值；
    bottom_z 取世界空间最低点，用于落地对齐。无网格数据的物体（空物体等）
    bound_box 退化为 8 个重合的原点，自然得到 max_span=0。"""
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    max_span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    return max_span, min(zs)


def _checkerboard_warnings(objs):
    """返回警告文案列表：物体数超 100 / 尺寸最大最小比超 100 倍。"""
    warnings = []
    if len(objs) > 100:
        warnings.append(f"选中了 {len(objs)} 个物体（超过 100 个），陈列范围会很大，请确认是否需要全部摆开。")
    spans = [s for s, _ in (_world_bbox(o) for o in objs) if s > 1e-6]
    if spans and (max(spans) / min(spans)) > 100:
        warnings.append(
            f"所选物体尺寸差距超过 100 倍（最大 {max(spans):.3g} / 最小 {min(spans):.3g}），"
            "网格会被最大的物体撑开，很小的物体可能变得肉眼难以察觉，建议先手动排查。")
    return warnings


class StageCheckerboardLayout(bpy.types.Operator):
    """把所选物体以激活物体为中心，按棋盘格网格重新摆开，方便逐个查看"""
    bl_idname = "object.checkerboard_layout_visn"
    bl_label = "棋盘格陈列"
    bl_description = "以激活物体为中心，把所选物体按棋盘格网格摊开摆放，整理查看用"
    bl_options = {"REGISTER", "UNDO"}

    margin: bpy.props.FloatProperty(
        name="格子间距系数", default=1.2, min=1.0,
        description="格子边长 = 所选物体中最大的包围盒尺寸 × 这个系数")

    _warnings = None

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects) and context.active_object is not None

    def invoke(self, context, event):
        objs = context.selected_objects
        if context.active_object not in objs:
            self.report({'ERROR'}, "激活物体必须在选中范围内")
            return {'CANCELLED'}
        self._warnings = _checkerboard_warnings(objs)
        if self._warnings:
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        if not self._warnings:
            return
        col = self.layout.column()
        for w in self._warnings:
            col.label(text=w, icon='ERROR')
        col.label(text="点击「确定」继续陈列，取消则不做任何改动。", icon='INFO')

    def execute(self, context):
        objs = context.selected_objects
        active = context.active_object
        if active not in objs:
            self.report({'ERROR'}, "激活物体必须在选中范围内")
            return {'CANCELLED'}

        bbox = {o: _world_bbox(o) for o in objs}
        spans = [s for s, _ in bbox.values()]
        cell_size = (max(spans) if max(spans) > 1e-6 else 1.0) * self.margin

        n = len(objs)
        grid = max(1, math.ceil(math.sqrt(n)))
        r0 = grid // 2
        c0 = grid // 2

        # 以到中心格的切比雪夫距离（环层）排序，环内再按欧式距离、行列号兜底，
        # 保证每次运行结果一致、可复现
        cells = [(r, c) for r in range(grid) for c in range(grid)]
        cells.sort(key=lambda rc: (
            max(abs(rc[0] - r0), abs(rc[1] - c0)),
            (rc[0] - r0) ** 2 + (rc[1] - c0) ** 2,
            rc[0], rc[1],
        ))
        cells.remove((r0, c0))

        others = sorted((o for o in objs if o is not active), key=lambda o: o.name)

        active_x = active.matrix_world.translation.x
        active_y = active.matrix_world.translation.y
        ground_z = bbox[active][1]

        for obj, (r, c) in zip(others, cells):
            dx = (c - c0) * cell_size
            dy = (r0 - r) * cell_size
            _, bottom_z = bbox[obj]
            local_offset_z = obj.matrix_world.translation.z - bottom_z
            obj.matrix_world.translation = Vector((
                active_x + dx, active_y + dy, ground_z + local_offset_z,
            ))

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region:
                    with context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_selected()
                break

        self.report({'INFO'}, f"已将 {n} 个物体陈列为 {grid}×{grid} 棋盘格")
        return {'FINISHED'}


_classes = (
    DeleteEmptyNull,
    FastCentreCamera,
    CSPZT_Camera,
    OpenProjectFolderOperator,
    AddLightWithConstraint,
    POND_OT_cam_rig_build,
    StageCheckerboardLayout,
    StageLegacyFbxImport,
    StageAnchorTop,
    StageAnchorBottom,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
