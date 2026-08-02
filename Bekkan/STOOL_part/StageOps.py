import bpy  # type: ignore
import os
import subprocess
import platform
from .ParentsOps import centro_global  # type: ignore


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
