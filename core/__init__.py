# core 逻辑层注册中心：全部 Operator / PropertyGroup / 纯函数，无任何 Panel。
# 注意：core/addonmanager（颈椎拯救者）不在这里注册——它只随别馆模式 UI 激活
# （决策点 3，见 ui/bekkan/__init__.py）。core/analyzer 常驻（标记数据随 .blend 保存）。
from . import (snapshot, hierarchy, stage, anime, render_preset, texture,
               organize, lumen, synccheck, c4d_bridge, preset_lib, version,
               palette, trace2solid, sixproj, lightdesk, bakemap, splitter,
               renderlayers, analyzer)

_MODULES = (
    snapshot, hierarchy, stage, anime, render_preset, texture,
    organize, lumen, synccheck, c4d_bridge, preset_lib, version,
    palette, trace2solid, sixproj, lightdesk, bakemap, splitter,
    renderlayers, analyzer,
)


def register():
    for m in _MODULES:
        m.register()


def unregister():
    for m in reversed(_MODULES):
        m.unregister()
