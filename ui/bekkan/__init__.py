# 别馆模式 UI：📸快照 → 📋工程分析 → ✨灯光合成 → 灯光台 → 工具箱五面板 → 颈椎拯救者
# （保持原排列顺序）
# 颈椎拯救者的 core（属性/操作符）只随别馆模式注册（决策点 3）；
# 工程分析的 core 常驻，这里只注册它的面板。
# 灯光台面板引用蛙灾 Pond 的面板类（ui/pond/panels/lightdesk.py），正文零副本。
import bpy

from . import (snapshot_panel, analyzer_panel, light_compose_panel,
               lightdesk_panel, panels, outline_panel, addonmanager_panel)
from ...core import addonmanager as _am_core


def register():
    snapshot_panel.register()
    analyzer_panel.register()
    light_compose_panel.register()
    lightdesk_panel.register()
    panels.register()
    outline_panel.register()
    _am_core.register()
    addonmanager_panel.register()


def unregister():
    # 先恢复被管理器移动过的面板，再注销本模式 UI
    addonmanager_panel.unregister()
    _am_core.unregister()
    outline_panel.unregister()
    panels.unregister()
    lightdesk_panel.unregister()
    light_compose_panel.unregister()
    analyzer_panel.unregister()
    snapshot_panel.unregister()
