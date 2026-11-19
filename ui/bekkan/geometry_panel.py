# Geometry Nodes 专用脚本面板；后续几何节点脚本在此追加。
import bpy

from ...core.geometry_tools import current_geometry_tree


class BEKKAN_PT_geometry_scripts(bpy.types.Panel):
    bl_label = '几何节点脚本'
    bl_idname = 'BEKKAN_PT_geometry_scripts'
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = '别馆'

    @classmethod
    def poll(cls, context):
        return current_geometry_tree(context) is not None

    def draw(self, context):
        self.layout.operator('node.expose_group_inputs_visn', icon='NODETREE')


def register():
    bpy.utils.register_class(BEKKAN_PT_geometry_scripts)


def unregister():
    bpy.utils.unregister_class(BEKKAN_PT_geometry_scripts)
