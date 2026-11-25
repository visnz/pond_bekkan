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
        if current_material_tree(context) is not None:
            return True
        space = context.space_data
        tree = getattr(space, 'edit_tree', None)
        return (getattr(space, 'type', None) == 'NODE_EDITOR'
                and getattr(space, 'tree_type', None) == 'ShaderNodeTree'
                and getattr(space, 'shader_type', None) == 'WORLD'
                and isinstance(getattr(space, 'id', None), bpy.types.World)
                and tree is not None and tree.bl_idname == 'ShaderNodeTree')

    def draw(self, context):
        layout = self.layout.column(align=True)
        material_mode = current_material_tree(context) is not None
        if material_mode:
            layout.operator('material.import_fab_visn', text='导入Fab材质', icon='IMPORT')
            layout.operator('node.arrange_material_visn', text='整理', icon='NODETREE')
            layout.operator('node.selected_images_non_color_visn', text='图片转Non-Color', icon='IMAGE_DATA')
            layout.operator('analyzer.fix_normal_colorspace_visn', text='修复全局法线Non-Color', icon='NODE_MATERIAL')
            layout.operator('node.select_unrelated_shader_nodes_visn', text='选中无关输出节点', icon='RESTRICT_SELECT_OFF')
        layout.operator('material.cycles_clay_visn', text='Cy白膜适配', icon='NODE_MATERIAL')
        layout.operator('material.cancel_cycles_clay_visn', text='取消白膜适配', icon='NODE_MATERIAL')
        if not material_mode:
            layout.separator()
            layout.operator('wm.sky_angles_to_sun_coords_visn', text='Sky → Sun 位置')
            layout.operator('wm.sun_coords_to_sky_angles_visn', text='Sun 位置 → Sky')
            return
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
