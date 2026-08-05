# 别馆模式 · 灯光台面板（引用蛙灾 Pond 的面板类，正文零副本）
# 逻辑（op / 属性）在 core/lightdesk.py 常驻，两模式共用同一份灯组/solo/隐藏数据；
# 这里只做一个皮肤壳：子类化 POND_PT_lightdesk，改 bl_idname / bl_category / bl_parent_id。
# poll 继承基类的 module_enabled("show_lightdesk")——与蛙灾共用同一个总开关
# （根 prefs.py 上的同一个 BoolProperty，一处关两处都关）。
import bpy

from ..pond.panels.lightdesk import POND_PT_lightdesk


class BEKKAN_PT_lightdesk(POND_PT_lightdesk):
    bl_idname = "BEKKAN_PT_lightdesk"
    bl_label = "灯光台"
    bl_category = "别馆"
    bl_parent_id = ""  # 顶层独立面板（Blender 5.2 的 bl_parent_id 不支持 None，空串 = 无父）
    # POND_PT_lightdesk 的 bl_order=3 是相对 POND_PT_sec_look 子面板排的，子类化会
    # 继承这个值；別馆顶层面板靠注册顺序排列（其它顶层面板都没设 bl_order，默认 0），
    # 继承来的 3 会把本面板排到所有默认值面板之后（连颈椎拯救者也排前面），必须清零。
    bl_order = 0


_classes = (
    BEKKAN_PT_lightdesk,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
