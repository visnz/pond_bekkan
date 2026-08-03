# 独立工程分析插件的占位偏好设置（无实际选项）
import bpy
from bpy.types import AddonPreferences


class AnalyzerPreferences(AddonPreferences):
    bl_idname = __package__


def register():
    bpy.utils.register_class(AnalyzerPreferences)


def unregister():
    bpy.utils.unregister_class(AnalyzerPreferences)
