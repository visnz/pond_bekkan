# 三渲二描边：反转法线壳描边工具（合并自独立插件 OutlineHelper，原作者 Feline Entity）
# 面板在 ui/bekkan/outline_panel.py
# 修复两处 Blender 5.2 (EEVEE Next) 上的 bug：
#   1. Material.shadow_method 已被移除，原代码 mat.shadow_method = "NONE" 会直接崩溃；
#   2. 描边材质只设了 use_backface_culling，没设 use_backface_culling_shadow，
#      导致反转法线壳在阴影里露出背面。
# 另外把三个操作符 poll() 里 bpy.context.object 为 None 时会崩的问题一并防御掉
# （原插件既有 bug，不在用户点名的两个之内，顺手带上）。
import bpy  # type: ignore
from bpy.props import FloatProperty, BoolProperty  # type: ignore


class OH_OT_Outline_Operator(bpy.types.Operator):
    bl_idname = "object.oh_outline"
    bl_label = "Set Outline"
    bl_description = "Add or adjust geometry outline of selected objects"
    bl_options = {"REGISTER", "UNDO"}

    outline_thickness: FloatProperty(
        name="Outline Thickness",
        description="Thickness of the applied outline",
        default=0.1, min=0, max=1000000)  # type: ignore
    apply_scale: BoolProperty(
        name="Apply Scale",
        description="Applies scale of objects to make outlines uniform",
        default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.mode != "EDIT"

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        col = box.column()
        col.label(text="Outline Thickness")
        colrow = col.row(align=True)
        colrow.prop(self, "outline_thickness", expand=True, text="")
        colrow = col.row(align=True)
        colrow.prop(self, "apply_scale", expand=True, text="Apply Scale")

    def invoke(self, context, event):
        active = bpy.context.view_layer.objects.active
        if active is not None:
            for mod in active.modifiers:
                if mod.name == "OH_OUTLINE":
                    self.outline_thickness = -(mod.thickness)

        mat = bpy.data.materials.get("OH_Outline_Material")

        if mat is None:
            mat = bpy.data.materials.new(name="OH_Outline_Material")
            mat.use_nodes = True
            mat.use_backface_culling = True
            mat.use_backface_culling_shadow = True
            nodes = mat.node_tree.nodes
            nodes.clear()
            links = mat.node_tree.links
            # Eevee Path
            node_color = nodes.new(type="ShaderNodeRGB")
            node_color.outputs[0].default_value = (0, 0, 0, 1)
            node_color.location = -700, -100
            node_output = nodes.new(type="ShaderNodeOutputMaterial")
            node_output.location = 100, -100
            node_output.target = "EEVEE"
            links.new(node_color.outputs[0], node_output.inputs[0])
            # Cycles Path
            node_geometry = nodes.new(type="ShaderNodeNewGeometry")
            node_geometry.location = -700, 400
            node_transparency = nodes.new(type="ShaderNodeBsdfTransparent")
            node_transparency.location = -700, 100
            node_lightpath = nodes.new(type="ShaderNodeLightPath")
            node_lightpath.location = -500, 500
            node_mix_1 = nodes.new(type="ShaderNodeMixShader")
            node_mix_1.location = -500, 100
            node_mix_2 = nodes.new(type="ShaderNodeMixShader")
            node_mix_2.location = -300, 100
            node_mix_3 = nodes.new(type="ShaderNodeMixShader")
            node_mix_3.location = -100, 100
            node_output_cycles = nodes.new(type="ShaderNodeOutputMaterial")
            node_output_cycles.location = 100, 100
            node_output_cycles.target = "CYCLES"

            links.new(node_geometry.outputs[6], node_mix_1.inputs[0])
            links.new(node_color.outputs[0], node_mix_1.inputs[1])
            links.new(node_transparency.outputs[0], node_mix_1.inputs[2])
            links.new(node_lightpath.outputs[0], node_mix_2.inputs[0])
            links.new(node_transparency.outputs[0], node_mix_2.inputs[1])
            links.new(node_mix_1.outputs[0], node_mix_2.inputs[2])
            links.new(node_lightpath.outputs[3], node_mix_3.inputs[0])
            links.new(node_mix_2.outputs[0], node_mix_3.inputs[1])
            links.new(node_mix_1.outputs[0], node_mix_3.inputs[2])
            links.new(node_mix_3.outputs[0], node_output_cycles.inputs[0])

            bpy.ops.ed.undo_push()

        return self.execute(context)

    def execute(self, context):
        sel = bpy.context.selected_objects

        for obj in sel:
            if obj.type in ("MESH", "CURVE"):
                bpy.context.view_layer.objects.active = obj

                if self.apply_scale:
                    bpy.ops.object.transform_apply(
                        location=False, rotation=False, scale=True, properties=False)

                mat_missing = True
                for slot in obj.data.materials:
                    if slot is not None and slot.name == "OH_Outline_Material":
                        mat_missing = False

                if mat_missing:
                    mat = bpy.data.materials.get("OH_Outline_Material")
                    obj.data.materials.append(mat)

                if obj.type == "MESH":
                    vg_missing = True
                    for vg in obj.vertex_groups:
                        if vg.name == "OH_Outline_VertexGroup":
                            vg_missing = False

                    if vg_missing:
                        vg_outline = obj.vertex_groups.new(name="OH_Outline_VertexGroup")
                        for vert in obj.data.vertices:
                            vg_outline.add([vert.index], 1.0, "ADD")

                exists = any(mod.name == "OH_OUTLINE" for mod in obj.modifiers)

                if exists:
                    mod = obj.modifiers["OH_OUTLINE"]
                    mod.thickness = -(self.outline_thickness)
                else:
                    mod = obj.modifiers.new("OH_OUTLINE", "SOLIDIFY")
                    mod.use_flip_normals = True
                    mod.use_rim = False
                    if obj.type == "MESH":
                        mod.vertex_group = "OH_Outline_VertexGroup"
                    mod.thickness = -(self.outline_thickness)
                    mod.material_offset = 999

        return {"FINISHED"}


class OH_OT_Adjust_Operator(bpy.types.Operator):
    bl_idname = "object.oh_adjust"
    bl_label = "Adjust Outline"
    bl_description = "Adjust geometry outline of selected objects"
    bl_options = {"REGISTER", "UNDO"}

    outline_thickness: FloatProperty(
        name="Outline Thickness",
        description="Thickness of the applied outline",
        default=0.1, min=0, max=1000000)  # type: ignore
    vertex_thickness: FloatProperty(
        name="Outline Thickness Vertex Weight",
        description="Thickness of the applied outline at vertex",
        default=1.0, min=0, max=1)  # type: ignore
    apply_scale: BoolProperty(
        name="Apply Scale",
        description="Applies scale of objects to make outlines uniform",
        default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        if context.object is None:
            return False
        if context.object.mode == "EDIT":
            return context.object.type == "MESH"
        return True

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        col = box.column()

        if context.object.mode != "EDIT":
            col.label(text="Outline Thickness")
            colrow = col.row(align=True)
            colrow.prop(self, "outline_thickness", expand=True, text="")
            colrow = col.row(align=True)
            colrow.prop(self, "apply_scale", expand=True, text="Apply Scale")
        else:
            col.label(text="Outline Thickness Vertex Weight")
            colrow = col.row(align=True)
            colrow.prop(self, "vertex_thickness", expand=True, text="")

    def invoke(self, context, event):
        active = bpy.context.view_layer.objects.active
        if active is not None:
            for mod in active.modifiers:
                if mod.name == "OH_OUTLINE":
                    self.outline_thickness = -(mod.thickness)

        return self.execute(context)

    def execute(self, context):
        sel = bpy.context.selected_objects

        for obj in sel:
            if obj.type in ("MESH", "CURVE"):
                if obj.mode != "EDIT":
                    bpy.context.view_layer.objects.active = obj

                    if self.apply_scale:
                        bpy.ops.object.transform_apply(
                            location=False, rotation=False, scale=True, properties=False)

                    exists = any(mod.name == "OH_OUTLINE" for mod in obj.modifiers)
                    if exists:
                        mod = obj.modifiers["OH_OUTLINE"]
                        mod.thickness = -(self.outline_thickness)
                else:
                    if obj.type == "MESH":
                        bpy.ops.object.mode_set(mode='OBJECT')
                        for vg in obj.vertex_groups:
                            if vg.name == "OH_Outline_VertexGroup":
                                for vert in obj.data.vertices:
                                    if vert.select:
                                        vg.add([vert.index], self.vertex_thickness, "REPLACE")
                        bpy.ops.object.mode_set(mode='EDIT')

        return {"FINISHED"}


class OH_OT_Remove_Operator(bpy.types.Operator):
    bl_idname = "object.oh_remove"
    bl_label = "Remove Outline"
    bl_description = "Remove the outline from selected objects."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.mode != "EDIT"

    def execute(self, context):
        sel = bpy.context.selected_objects

        for obj in sel:
            if obj.type in ("MESH", "CURVE"):
                bpy.context.view_layer.objects.active = obj

                matindex = obj.data.materials.find('OH_Outline_Material')
                if matindex != -1:
                    obj.data.materials.pop(index=matindex)

                exists = any(mod.name == "OH_OUTLINE" for mod in obj.modifiers)
                if exists:
                    obj.modifiers.remove(obj.modifiers["OH_OUTLINE"])

                for vg in obj.vertex_groups:
                    if vg.name == "OH_Outline_VertexGroup":
                        obj.vertex_groups.remove(vg)

        return {"FINISHED"}


_classes = (
    OH_OT_Outline_Operator,
    OH_OT_Adjust_Operator,
    OH_OT_Remove_Operator,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
