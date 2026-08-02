# 短片摄像机组：Root(位置) > 环绕层(转它做环绕) > 摄像机
# 外加 注视目标(Track To) 和 对焦目标(景深)，两个都能单独拖着走
import bpy

from . import prefs
from mathutils import Vector


def _link(obj, context):
    context.scene.collection.objects.link(obj)


class POND_OT_make_cam_rig(bpy.types.Operator):
    """围绕选中物体（没有就在原点）搭一套短片摄像机组"""
    bl_idname = "pond.make_cam_rig"
    bl_label = "搭摄像机组"
    bl_options = {"REGISTER", "UNDO"}

    use_black_frame: bpy.props.BoolProperty(
        name="黑框区域", default=True,
        description="相机视图外全黑，构图不被场外抢戏")
    use_dof: bpy.props.BoolProperty(name="开景深", default=True)
    use_motion_blur: bpy.props.BoolProperty(name="开动态模糊", default=True)

    def execute(self, context):
        sel = context.selected_objects
        if sel:
            center = sum((o.matrix_world.translation for o in sel), Vector()) / len(sel)
        else:
            center = Vector((0, 0, 0))

        root = bpy.data.objects.new("CAM_根", None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 1.2
        _link(root, context)
        root.location = center

        orbit = bpy.data.objects.new("CAM_环绕层", None)
        orbit.empty_display_type = "CIRCLE"
        orbit.empty_display_size = 4.0
        _link(orbit, context)
        orbit.parent = root

        cam_data = bpy.data.cameras.new("短片摄像机")
        cam = bpy.data.objects.new("短片摄像机", cam_data)
        _link(cam, context)
        cam.parent = orbit
        cam.location = (0, -6, 2)

        target = bpy.data.objects.new("CAM_注视目标", None)
        target.empty_display_type = "SPHERE"
        target.empty_display_size = 0.3
        _link(target, context)
        target.parent = root

        dof_target = bpy.data.objects.new("CAM_对焦目标", None)
        dof_target.empty_display_type = "CUBE"
        dof_target.empty_display_size = 0.18
        _link(dof_target, context)
        dof_target.parent = root

        con = cam.constraints.new("TRACK_TO")
        con.target = target
        con.track_axis = "TRACK_NEGATIVE_Z"
        con.up_axis = "UP_Y"

        cam_data.dof.use_dof = self.use_dof
        cam_data.dof.focus_object = dof_target

        if self.use_black_frame:
            cam_data.show_passepartout = True
            cam_data.passepartout_alpha = 1.0
        if self.use_motion_blur:
            context.scene.render.use_motion_blur = True
            eevee = getattr(context.scene, "eevee", None)
            if eevee and hasattr(eevee, "use_motion_blur"):
                eevee.use_motion_blur = True

        context.scene.camera = cam
        bpy.ops.object.select_all(action="DESELECT")
        cam.select_set(True)
        context.view_layer.objects.active = cam
        extras = [s for s, on in (("黑框", self.use_black_frame),
                                  ("景深", self.use_dof),
                                  ("动态模糊", self.use_motion_blur)) if on]
        self.report({"INFO"}, "摄像机组搭好了" + ("，已开：" + "/".join(extras) if extras else ""))
        return {"FINISHED"}


class POND_PT_cam_rig(bpy.types.Panel):
    bl_label = "摄像机组"
    bl_idname = "POND_PT_cam_rig"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_make"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_cam_rig")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.make_cam_rig", icon="CAMERA_DATA")
        col.label(text="根管位置 环绕层管转", icon="INFO")
        col.label(text="注视球管朝向 对焦块管景深")


_classes = (
    POND_OT_make_cam_rig,
    POND_PT_cam_rig,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
