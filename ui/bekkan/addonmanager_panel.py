# 别馆模式 · 颈椎拯救者面板 + 面板恢复/处理器逻辑
# （迁移自 Bekkan/STOOL_part/AddonManager/ui.py；
#   preferences.addon_show 的 module 改为动态根包名）
import bpy
from bpy.types import Panel, UIList
from bpy.app.handlers import persistent

from ...core.addonmanager import common
from .prefs import module_enabled

_ROOT_PKG = __package__.split(".")[0]


# --- UIList 实现 ---
class ADDONMANAGER_UL_category_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            split = layout.split(factor=0.9)
            split.label(text=item.name, icon='PLUGIN')

            icon_name = 'SOLO_ON' if item.is_favorite else 'SOLO_OFF'

            col_right = split.column(align=True)
            op = col_right.operator(
                "addonmanager.toggle_favorite",
                text="",
                icon=icon_name,
                emboss=False
            )
            op.item_index = index

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='PLUGIN')

    def filter_items(self, context, data, propname):
        """ Filter and order items in the list """
        items = getattr(data, propname)
        helper_funcs = bpy.types.UI_UL_list

        search_term = context.scene.addon_manager_search_term.lower()
        show_only_favs = context.scene.addon_manager_show_favorites_only
        filtered = [0] * len(items)
        ordered = []
        if search_term or show_only_favs:
            for i, item in enumerate(items):
                is_fav = item.is_favorite
                item_name = getattr(item, "name", "").lower()
                name_match = (not search_term or search_term in item_name)

                show_item = False
                if show_only_favs:
                    if is_fav and name_match:
                        show_item = True
                else:
                    if name_match:
                        show_item = True

                if show_item:
                    filtered[i] = self.bitflag_filter_item
        else:
            filtered = [self.bitflag_filter_item] * len(items)

        ordered = helper_funcs.sort_items_by_name(items, "name")

        return filtered, ordered


# --- 主管理面板 ---
class ADDONMANAGER_PT_main(Panel):
    bl_label = "颈椎拯救者 by 说旧"
    bl_idname = "OBJECT_PT_addon_manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = common.PANEL_CATEGORY
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if not module_enabled("show_addonmanager"):
            return False
        return context.space_data.type == 'VIEW_3D'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # --- 1. 搜索和刷新 ---
        row = layout.row(align=True)
        row.prop(scene, "addon_manager_search_term", text="", icon='VIEWZOOM')
        row.operator("addonmanager.refresh_categories", text="", icon='FILE_REFRESH')
        if scene.addon_manager_category_index != -1:
            row.label(text="", icon='INFO')
            layout.label(text="刷新来重置视图/释放插件", icon='INFO')
        show_favs_icon = 'SOLO_ON' if scene.addon_manager_show_favorites_only else 'SOLO_OFF'
        row.prop(
            scene,
            "addon_manager_show_favorites_only",
            text="",
            toggle=True,
            icon=show_favs_icon
        )
        props = row.operator("preferences.addon_show", text="", icon='PREFERENCES')
        props.module = _ROOT_PKG

        # --- 2. 插件类别列表 (UIList) ---
        list_box = layout.box()
        total_panels = len(scene.addon_manager_categories)

        row = list_box.row()
        row.label(text=f"共找到{total_panels} 个", icon='PLUGIN')

        list_box.template_list(
            "ADDONMANAGER_UL_category_list",
            "",
            scene,
            "addon_manager_categories",
            scene,
            "addon_manager_category_index",
            rows=4,
        )

        # --- 3. 信息区域 ---
        layout.separator()
        info_box = layout.box()
        selected_category_name = ""
        if 0 <= scene.addon_manager_category_index < len(scene.addon_manager_categories):
            selected_category_name = scene.addon_manager_categories[scene.addon_manager_category_index].name

        if selected_category_name:
            info_box.label(text=f"显示插件: '{selected_category_name}'", icon='INFO')
        else:
            info_box.label(text="在此处查看其面板_刷新按钮释放插件.", icon='INFO')


# 恢复面板函数 - 在注销插件前调用
def restore_panels(force=False):
    if not force and not common.should_auto_restore('exit'):
        return

    panels_to_restore = list(common.currently_managed_panels)
    restored_count = 0
    error_count = 0
    for panel_idname in panels_to_restore:
        try:
            if panel_idname in common.original_categories:
                panel_cls = common.original_categories[panel_idname]['class']
                original_cat = common.original_categories[panel_idname]['original_category']

                # 检查它是否真的在管理类别下
                if hasattr(panel_cls, 'bl_category') and panel_cls.bl_category == common.PANEL_CATEGORY:
                    try:
                        bpy.utils.unregister_class(panel_cls)
                        panel_cls.bl_category = original_cat
                        bpy.utils.register_class(panel_cls)
                        restored_count += 1
                    except Exception as e:
                        print(f"Error restoring panel {panel_idname}: {e}")
                        error_count += 1
        except Exception as e:
            print(f"Unexpected error processing panel {panel_idname}: {e}")
            error_count += 1
    common.currently_managed_panels.clear()

    print(f"Panel restoration complete: {restored_count} restored, {error_count} errors")


# 添加处理器函数
@persistent
def load_handler(dummy):
    """新文件加载时的处理器"""
    if common.should_auto_restore('new_file'):
        restore_panels(force=True)


@persistent
def save_handler(dummy):
    """文件保存时的处理器 - 可以用于保存状态"""
    pass


@persistent
def exit_handler(dummy=None):
    """Blender退出时的处理器"""
    restore_panels(force=True)  # 强制恢复，确保清理


# 注册类列表
_classes = (
    ADDONMANAGER_UL_category_list,
    ADDONMANAGER_PT_main,
)


def register():
    for cls in _classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            print(f"Warning: Could not register class {cls.__name__}: {e}")
    # 注册处理器
    bpy.app.handlers.load_post.append(load_handler)
    bpy.app.handlers.save_pre.append(save_handler)

    # 注册退出处理器
    try:
        import atexit
        atexit.register(exit_handler)
    except ImportError:
        print("Could not register exit handler")


def unregister():
    # 先恢复面板
    restore_panels(force=True)

    # 移除处理器
    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)
    if save_handler in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_handler)

    # 注销类
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

    # 尝试移除退出处理器
    try:
        import atexit
        atexit.unregister(exit_handler)
    except (ImportError, AttributeError):
        pass
