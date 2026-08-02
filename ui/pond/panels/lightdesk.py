# 灯光台面板（逻辑在 core/lightdesk.py）
import bpy

from ..prefs import module_enabled
from ....core.lightdesk import (AUTO_EMIT, _fold, _lightish, _groups,
                                _members, _hidden, _solo_targets)


def context_active():
    return bpy.context.view_layer.objects.active


def _light_icon(obj):
    if obj.type == "LIGHT":
        return {"SUN": "LIGHT_SUN", "POINT": "LIGHT_POINT",
                "SPOT": "LIGHT_SPOT", "AREA": "LIGHT_AREA"}.get(
                    obj.data.type, "LIGHT")
    return "SHADING_RENDERED"


class POND_PT_lightdesk(bpy.types.Panel):
    bl_label = "灯光台"
    bl_idname = "POND_PT_lightdesk"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_look"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}
    poll = module_enabled("show_lightdesk")

    def _rows(self, box, scene, objs, solo_t):
        for obj in objs:
            row = box.row(align=True)
            sel = row.operator("pond.ld_select", text=obj.name,
                               icon=_light_icon(obj), emboss=(obj == context_active()))
            sel.obj_name = obj.name
            op = row.operator("pond.ld_solo", text="",
                              icon="SOLO_ON" if "obj:" + obj.name in solo_t
                              else "SOLO_OFF")
            op.mode = "OBJ"
            op.target = obj.name
            op = row.operator("pond.ld_vis", text="",
                              icon="HIDE_ON" if _hidden(obj) else "HIDE_OFF")
            op.obj_name = obj.name
            if obj.pond_ld_group:
                op = row.operator("pond.ld_unassign", text="", icon="REMOVE")
                op.obj_name = obj.name

    def draw(self, context):
        scene = context.scene
        layout = self.layout
        solo_t = set(_solo_targets(scene))

        row = layout.row(align=True)
        row.prop(scene, "pond_ld_newname", text="")
        row.operator("pond.ld_group_new", text="建组", icon="ADD")

        lights = _lightish(scene)
        assigned = set()

        for gname in _groups(scene):
            mem = _members(scene, gname)
            assigned.update(o.name for o in mem)
            box = layout.box()
            head = box.row(align=True)
            head.operator("pond.ld_fold", text="",
                          icon="TRIA_RIGHT" if gname in _fold else "TRIA_DOWN",
                          emboss=False).group = gname
            head.label(text="%s (%d)" % (gname, len(mem)), icon="OUTLINER_COLLECTION")
            op = head.operator("pond.ld_solo", text="",
                               icon="SOLO_ON" if "grp:" + gname in solo_t
                               else "SOLO_OFF")
            op.mode = "GRP"
            op.target = gname
            op = head.operator("pond.ld_group_vis", text="",
                               icon="HIDE_ON" if mem and all(_hidden(o) for o in mem)
                               else "HIDE_OFF")
            op.group = gname
            head.operator("pond.ld_group_del", text="",
                          icon="X").group = gname
            if gname in _fold:
                continue
            box.operator("pond.ld_assign", text="把选中的加进组",
                         icon="ADD").group = gname
            self._rows(box, scene, mem, solo_t)

        emit = _members(scene, AUTO_EMIT)
        if emit:
            assigned.update(o.name for o in emit)
            box = layout.box()
            head = box.row(align=True)
            head.operator("pond.ld_fold", text="",
                          icon="TRIA_RIGHT" if AUTO_EMIT in _fold else "TRIA_DOWN",
                          emboss=False).group = AUTO_EMIT
            head.label(text="%s (%d) 自动" % (AUTO_EMIT, len(emit)),
                       icon="SHADING_RENDERED")
            op = head.operator("pond.ld_solo", text="",
                               icon="SOLO_ON" if "grp:" + AUTO_EMIT in solo_t
                               else "SOLO_OFF")
            op.mode = "GRP"
            op.target = AUTO_EMIT
            op = head.operator("pond.ld_group_vis", text="",
                               icon="HIDE_ON" if all(_hidden(o) for o in emit)
                               else "HIDE_OFF")
            op.group = AUTO_EMIT
            if AUTO_EMIT not in _fold:
                self._rows(box, scene, emit, solo_t)

        rest = [o for o in lights if o.name not in assigned]
        if rest:
            box = layout.box()
            head = box.row(align=True)
            head.operator("pond.ld_fold", text="",
                          icon="TRIA_RIGHT" if "未分组" in _fold else "TRIA_DOWN",
                          emboss=False).group = "未分组"
            head.label(text="未分组 (%d)" % len(rest), icon="LIGHT")
            if "未分组" not in _fold:
                self._rows(box, scene, rest, solo_t)

        if solo_t:
            row = layout.row()
            row.alert = True
            row.operator("pond.ld_solo",
                         text="正在 Solo %d 个，点我恢复全部" % len(solo_t),
                         icon="LOOP_BACK").mode = "OFF"

        if not lights:
            layout.label(text="场景里还没有灯", icon="INFO")


_classes = (
    POND_PT_lightdesk,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
