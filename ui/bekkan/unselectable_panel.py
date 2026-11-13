# 别馆 · 与灯光台同级的不可选对象列表。
import bpy

from ...core.unselectable import managed_object


class BEKKAN_UL_unselectable(bpy.types.UIList):
    def draw_filter(self, context, layout):
        layout.prop(self, 'filter_name', text='', icon='VIEWZOOM')

    def filter_items(self, context, data, propname):
        self.use_filter_show = True
        objects = getattr(data, propname)
        name_filter = self.filter_name.casefold()
        flags = [self.bitflag_filter_item if managed_object(obj)
                 and name_filter in obj.name.casefold() else 0 for obj in objects]
        order = bpy.types.UI_UL_list.sort_items_by_name(objects, 'name')
        return flags, order

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index=0, flt_flag=0):
        obj = item
        row = layout.row(align=True)
        row.enabled = obj.is_editable
        name = row.row(align=True)
        name.operator_context = 'EXEC_DEFAULT'
        op = name.operator('object.manage_unselectable_visn', text=obj.name,
                           icon='OBJECT_DATA', depress=(obj == context.active_object))
        op.target_uid = str(obj.session_uid)
        op.action = 'EDIT'
        if not obj.hide_select:
            row.label(text='调整中')
        op = row.operator('object.manage_unselectable_visn', text='',
                          icon='RESTRICT_SELECT_ON' if obj.hide_select else 'RESTRICT_SELECT_OFF')
        op.target_uid = str(obj.session_uid)
        op.action = 'EDIT' if obj.hide_select else 'LOCK'
        if not obj.hide_select:
            op = row.operator('object.manage_unselectable_visn', text='', icon='X')
            op.target_uid = str(obj.session_uid)
            op.action = 'FORGET'


class BEKKAN_PT_unselectable(bpy.types.Panel):
    bl_label = '不可选对象'
    bl_idname = 'BEKKAN_PT_unselectable'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '别馆'
    bl_parent_id = ''
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        locked = adjusting = 0
        for obj in scene.objects:
            if obj.hide_select:
                locked += 1
            elif managed_object(obj):
                adjusting += 1
        layout.label(text=f'禁选 {locked} · 调整中 {adjusting}')
        if not locked and not adjusting:
            layout.label(text='关闭对象可选择性后会自动显示', icon='INFO')
            return
        layout.template_list(
            'BEKKAN_UL_unselectable', '', scene, 'objects',
            scene, 'bekkan_unselectable_index', rows=6, maxrows=10,
        )
        layout.label(text='点对象解锁并激活，调整后点右侧锁回')
        layout.label(text='禁选：Bounds · 激活：Textured')


_classes = (BEKKAN_UL_unselectable, BEKKAN_PT_unselectable)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
