# 四个大抽屉：把 13 个模块按干活动作归组，N 面板平时只露四行
# 整理(父子级/一键整理/同步体检) 观察(明度/快照/灯光台/色卡)
# 制作(摄像机组/六面投射/图转立体/预设库) 交付(C4D互导/版本)
import bpy


def _make(idname, label, order):
    return type(idname, (bpy.types.Panel,), {
        "bl_label": label,
        "bl_idname": idname,
        "bl_space_type": "VIEW_3D",
        "bl_region_type": "UI",
        "bl_category": "池塘",
        "bl_order": order,
        "bl_options": {"DEFAULT_CLOSED"},
        "draw": lambda self, context: None,
    })


POND_PT_sec_tidy = _make("POND_PT_sec_tidy", "整理", 1)
POND_PT_sec_look = _make("POND_PT_sec_look", "观察", 2)
POND_PT_sec_make = _make("POND_PT_sec_make", "制作", 3)
POND_PT_sec_ship = _make("POND_PT_sec_ship", "交付", 4)

_classes = (POND_PT_sec_tidy, POND_PT_sec_look, POND_PT_sec_make, POND_PT_sec_ship)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
