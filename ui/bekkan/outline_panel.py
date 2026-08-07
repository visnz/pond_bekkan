# 三渲二描边面板（合并自独立插件 OutlineHelper 的 oh_sidepanel.py，布局照抄）
# 按钮转发到 core/outline.py
import bpy

from .prefs import module_enabled


class VIEW3D_PT_outline_visn(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_outline_visn"
    bl_label = "🎨 三渲二"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '别馆'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return module_enabled("show_toon_outline")

    def draw(self, context):
        col = self.layout.column()
        col.operator("object.oh_outline", icon='ADD', text="Add/Set Outline")
        col.operator("object.oh_adjust", icon='ARROW_LEFTRIGHT', text="Adjust Outline")
        col.operator("object.oh_remove", icon='PANEL_CLOSE', text="Remove Outline")


_classes = (
    VIEW3D_PT_outline_visn,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
