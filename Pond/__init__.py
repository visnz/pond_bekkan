# 池塘 —— 岁岁的 Blender 工具总集
# 模块：父子级操作 / 一键整理 / 明度检查 / 同步体检 / C4D互导 / 节点预设库
#       版本另存 / 快照对比 / 摄像机组 / 色卡调色板

bl_info = {
    "name": "池塘 Pond",
    "author": "屿 & 岁岁",
    "version": (0, 22, 1),
    "blender": (4, 2, 0),
    "location": "3D视图 > N面板 > 池塘",
    "description": "岁岁自己习惯用的功能总集",
    "category": "3D View",
}

import importlib

from . import (prefs, sections, hierarchy, organize, lumen, synccheck,
               c4d_bridge, preset_lib, version, snapshot, cam_rig, palette,
               trace2solid, sixproj, lightdesk, bakemap, splitter,
               renderlayers)

# sections(四个抽屉)必须先于各模块注册，子面板才认得到父面板
_modules = (prefs, sections, hierarchy, organize, lumen, synccheck,
            c4d_bridge, preset_lib, version, snapshot, cam_rig, palette,
            trace2solid, sixproj, lightdesk, bakemap, splitter,
            renderlayers)

# 开发期热重载：重复启用插件时刷新子模块
if "bpy" in locals():
    for _m in _modules:
        importlib.reload(_m)

import bpy


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
