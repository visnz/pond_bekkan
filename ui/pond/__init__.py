# 蛙灾模式 UI：sections 四抽屉 + 各模块子面板。
from . import sections, panels


def register():
    sections.register()
    panels.register()


def unregister():
    panels.unregister()
    sections.unregister()
