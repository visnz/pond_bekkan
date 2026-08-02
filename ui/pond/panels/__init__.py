# 蛙灾模式各模块子面板注册表（每个文件对应 core 同名模块的逻辑）。
from . import (cam_rig, sixproj, trace2solid, preset_lib, bakemap, splitter,
               hierarchy, organize, synccheck, lumen, snapshot, lightdesk,
               palette, c4d_bridge, version, renderlayers)

_MODULES = (
    cam_rig, sixproj, trace2solid, preset_lib, bakemap, splitter,
    hierarchy, organize, synccheck, lumen, snapshot, lightdesk,
    palette, c4d_bridge, version, renderlayers,
)


def register():
    for m in _MODULES:
        m.register()


def unregister():
    for m in reversed(_MODULES):
        m.unregister()
