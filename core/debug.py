# 插件开发调试：延迟注销并从磁盘重新导入本插件。
import bpy


def _reload_addon_from_disk():
    """在 UI 操作结束后调用；先注销旧类，再重新导入整个插件包。"""
    import addon_utils
    import importlib
    import sys
    package = __package__.rpartition('.')[0]
    old = sys.modules.get(package)
    persistent = getattr(old, '__addon_persistent__', False)
    errors = []
    def on_error(exc=None):
        import traceback
        errors.append(''.join(traceback.format_exception(exc)) if exc is not None
                      else traceback.format_exc())
    addon_utils.disable(package, default_set=False, refresh_handled=True, handle_error=on_error)
    if errors:
        raise RuntimeError('注销插件失败：' + '\n'.join(errors))
    for name in tuple(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]
    importlib.invalidate_caches()
    module = addon_utils.enable(package, default_set=False, persistent=persistent, refresh_handled=True,
                                handle_error=on_error)
    if module is None or errors:
        raise RuntimeError('重新加载失败：' + '\n'.join(errors))
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    print('[PondBekkan] 已从磁盘重载插件')


_reload_pending = False


class WM_OT_reload_pond_bekkan(bpy.types.Operator):
    bl_idname = 'wm.reload_pond_bekkan_visn'
    bl_label = '重载插件'
    bl_description = '从磁盘重新加载池塘/别馆代码，保留偏好设置；快照等临时状态会清空'

    @classmethod
    def poll(cls, context):
        return not _reload_pending

    def execute(self, context):
        global _reload_pending
        _reload_pending = True
        def reload_later():
            global _reload_pending
            try:
                _reload_addon_from_disk()
            except Exception:
                import traceback
                traceback.print_exc()
                def draw_error(menu, context):
                    menu.layout.label(text='插件重载失败，请查看系统控制台；修复后重新启用插件。')
                bpy.context.window_manager.popup_menu(draw_error, title='重载失败', icon='ERROR')
            finally:
                _reload_pending = False
            return None
        bpy.app.timers.register(reload_later, first_interval=0.2)
        self.report({'INFO'}, '正在从磁盘重载池塘/别馆插件…')
        return {'FINISHED'}


def register():
    bpy.utils.register_class(WM_OT_reload_pond_bekkan)


def unregister():
    bpy.utils.unregister_class(WM_OT_reload_pond_bekkan)
