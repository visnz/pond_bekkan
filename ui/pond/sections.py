# 蛙灾模式 · 四个抽屉父面板（迁移自 Pond/sections.py，纯平移）
import bpy


class _SecBase:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"


class POND_PT_sec_tidy(_SecBase, bpy.types.Panel):
    bl_label = "🧹 整理"
    bl_idname = "POND_PT_sec_tidy"
    bl_order = 0

    def draw(self, context):
        pass


class POND_PT_sec_look(_SecBase, bpy.types.Panel):
    bl_label = "👁 观察"
    bl_idname = "POND_PT_sec_look"
    bl_order = 1

    def draw(self, context):
        pass


class POND_PT_sec_make(_SecBase, bpy.types.Panel):
    bl_label = "🔨 制作"
    bl_idname = "POND_PT_sec_make"
    bl_order = 2

    def draw(self, context):
        pass


class POND_PT_sec_ship(_SecBase, bpy.types.Panel):
    bl_label = "📦 交付"
    bl_idname = "POND_PT_sec_ship"
    bl_order = 3

    def draw(self, context):
        pass


_classes = (
    POND_PT_sec_tidy,
    POND_PT_sec_look,
    POND_PT_sec_make,
    POND_PT_sec_ship,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
