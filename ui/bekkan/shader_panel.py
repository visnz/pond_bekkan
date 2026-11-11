# Shader Editor 专用脚本面板；后续材质脚本继续在此追加入口。
import bpy

from ...core.shader_tools import current_material_tree


class BEKKAN_PT_shader_scripts(bpy.types.Panel):
    bl_label = 'Shader 脚本'
    bl_idname = 'BEKKAN_PT_shader_scripts'
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = '别馆'

    @classmethod
    def poll(cls, context):
        return current_material_tree(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.operator('node.arrange_material_visn', icon='NODETREE')
        layout.operator('node.selected_images_non_color_visn', icon='IMAGE_DATA')


def register():
    bpy.utils.register_class(BEKKAN_PT_shader_scripts)


def unregister():
    bpy.utils.unregister_class(BEKKAN_PT_shader_scripts)
