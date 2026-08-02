# 颈椎拯救者（by 说旧）—— core 部分：属性 + 操作符 + 初始化刷新
# 合并自 Bekkan/STOOL_part/AddonManager。面板与恢复逻辑在 ui/bekkan/addonmanager_panel.py。
# 整个子包只在别馆模式激活时注册（决策点 3）。
import bpy
from . import common, properties, operators


def register():
    properties.register()
    operators.register()

    # 从偏好设置中加载额外排除的类别
    common.load_additional_excluded_from_preferences()

    # 延迟刷新
    def deferred_refresh():
        try:
            bpy.ops.addonmanager.scan_available_categories()
            bpy.ops.addonmanager.apply_excluded_categories()
            bpy.ops.addonmanager.refresh_categories()
        except Exception as e:
            print(f"Error during initial category refresh: {e}")
        return None

    bpy.app.timers.register(deferred_refresh, first_interval=0.1)


def unregister():
    # 面板的恢复（restore_panels）由 ui/bekkan/addonmanager_panel.unregister 先行处理
    operators.unregister()
    properties.unregister()
