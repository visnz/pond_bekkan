# Shader Editor 专用脚本面板；后续材质脚本继续在此追加入口。
import bpy

from ...core.shader_tools import current_material_tree
from ...core.fotosketcher import status_for


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
        layout = self.layout.column(align=True)
        layout.operator('material.import_fab_visn', icon='IMPORT')
        layout.operator('node.arrange_material_visn', icon='NODETREE')
        layout.operator('node.selected_images_non_color_visn', icon='IMAGE_DATA')
        layout.operator('analyzer.fix_normal_colorspace_visn', icon='NODE_MATERIAL')
        layout.operator('node.select_unrelated_shader_nodes_visn', icon='RESTRICT_SELECT_OFF')
        layout.separator()
        status = status_for(context)
        if status and status[0] == 'RUNNING':
            layout.label(text=status[1], icon='TIME')
        prepare = layout.row()
        prepare.enabled = not (status and status[0] == 'RUNNING')
        prepare.operator('node.fotosketcher_prepare_1k_visn',
                         text='选中贴图生成 1K 副本', icon='IMAGE_DATA')
        buttons = layout.column(align=True)
        buttons.enabled = not (status and status[0] == 'RUNNING')
        for preset, label in (
            ('PAINT4', 'Foto大块笔刷'),
            ('PAINT7', 'Foto细条笔刷'),
            ('WATERCOLOR9', 'Foto点画色块'),
            ('PAINT10', 'Foto毛躁笔刷'),
            ('PAINT11', 'Foto混合笔刷'),
        ):
            buttons.operator('node.fotosketcher_paint11_visn', text=label,
                             icon='IMAGE_DATA').preset = preset
        layout.label(text='多选图片，最后选备注可复用参数', icon='INFO')
        if status and status[0] != 'RUNNING':
            layout.label(text=status[1], icon='CHECKMARK' if status[0] == 'DONE' else 'ERROR')


def register():
    bpy.utils.register_class(BEKKAN_PT_shader_scripts)


def unregister():
    bpy.utils.unregister_class(BEKKAN_PT_shader_scripts)
