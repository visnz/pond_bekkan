# 灯光台：自建标签组管灯，solo 单灯/整组，发光材质面片自动归「发光面片」组
# solo 用隐藏实现（Eevee/Cycles 通吃），开 solo 前拍快照，退出原样恢复
import json
import bpy

from . import prefs

AUTO_EMIT = "发光面片"          # 自动组名，未分组的发光材质网格都归这里
_fold = set()                   # 收起的组（会话内记住）


# ── 识别 ──

def _is_emissive(obj):
    """网格挂了发光材质：有 Emission 节点，或原理化 BSDF 的发光强度 > 0"""
    if obj.type != "MESH":
        return False
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "EMISSION":
                return True
            if node.type == "BSDF_PRINCIPLED":
                sock = node.inputs.get("Emission Strength")
                if sock and (sock.is_linked or sock.default_value > 0):
                    return True
    return False


def _lightish(scene):
    """场景里所有该归灯光台管的对象：真灯 + 发光网格"""
    out = []
    for obj in scene.objects:
        if obj.type == "LIGHT" or _is_emissive(obj):
            out.append(obj)
    return out


def _groups(scene):
    try:
        g = json.loads(scene.pond_ld_groups or "[]")
        return [str(x) for x in g if str(x).strip()]
    except Exception:
        return []


def _set_groups(scene, names):
    scene.pond_ld_groups = json.dumps(names, ensure_ascii=False)


def _members(scene, gname):
    if gname == AUTO_EMIT:
        return [o for o in _lightish(scene)
                if o.type == "MESH" and not o.pond_ld_group]
    return [o for o in _lightish(scene) if o.pond_ld_group == gname]


def _hidden(obj):
    """开关灯图标看的是小眼睛(视口临时隐藏)"""
    try:
        return obj.hide_get()
    except RuntimeError:
        return obj.hide_viewport


# ── solo 快照 ──

def _solo_state(scene):
    try:
        return json.loads(scene.pond_ld_solo) if scene.pond_ld_solo else None
    except Exception:
        return None


def _solo_targets(scene):
    """当前 solo 里的目标 key 列表（obj:名字 / grp:组名），没在 solo 返回 []"""
    st = _solo_state(scene)
    if not st:
        return []
    if "targets" in st:
        return list(st["targets"])
    return [st["target"]] if st.get("target") else []


def _solo_restore(scene):
    st = _solo_state(scene)
    if not st:
        return
    for name, prev in st.get("states", {}).items():
        obj = scene.objects.get(name)
        if not obj:
            continue
        if isinstance(prev, list):      # 旧格式 [hv, hr, he] 兼容
            hv, hr, he = prev
            obj.hide_viewport = hv
            obj.hide_render = hr
        else:                            # 新格式: 只存小眼睛
            he = prev
        try:
            obj.hide_set(he)
        except Exception:
            pass
    scene.pond_ld_solo = ""


def _solo_write(context, targets):
    """按目标列表重铺 solo：目标成员亮、其余灭；快照只在进 solo 那一刻拍一次。
    targets 传空列表 = 恢复原样退出。"""
    scene = context.scene
    if not targets:
        _solo_restore(scene)
        return
    st = _solo_state(scene)
    states = (st or {}).get("states", {})
    keep = set()
    for key in targets:
        if key.startswith("obj:"):
            obj = scene.objects.get(key[4:])
            if obj:
                keep.add(obj.name)
        elif key.startswith("grp:"):
            keep.update(o.name for o in _members(scene, key[4:]))
    for obj in _lightish(scene):
        if obj.name not in states:      # 中途新出现的灯也补拍快照(只记小眼睛)
            try:
                states[obj.name] = obj.hide_get()
            except Exception:
                states[obj.name] = False
        try:
            obj.hide_set(obj.name not in keep)
        except Exception:
            pass
    scene.pond_ld_solo = json.dumps(
        {"targets": targets, "states": states}, ensure_ascii=False)


# ── 操作符 ──

class POND_OT_ld_group_new(bpy.types.Operator):
    """按上面输入的名字新建一个灯光组"""
    bl_idname = "pond.ld_group_new"
    bl_label = "建组"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        name = (scene.pond_ld_newname or "").strip()[:24]
        if not name:
            self.report({"WARNING"}, "先给组起个名字")
            return {"CANCELLED"}
        if name == AUTO_EMIT:
            self.report({"WARNING"}, "「%s」是自动组，换个名字" % AUTO_EMIT)
            return {"CANCELLED"}
        names = _groups(scene)
        if name in names:
            self.report({"WARNING"}, "已经有这个组了")
            return {"CANCELLED"}
        names.append(name)
        _set_groups(scene, names)
        scene.pond_ld_newname = ""
        return {"FINISHED"}


class POND_OT_ld_group_del(bpy.types.Operator):
    """解散这个组（灯还在场景里，只是不再属于这个组）"""
    bl_idname = "pond.ld_group_del"
    bl_label = "解散组"
    bl_options = {"REGISTER", "UNDO"}

    group: bpy.props.StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        for obj in scene.objects:
            if obj.pond_ld_group == self.group:
                obj.pond_ld_group = ""
        _set_groups(scene, [n for n in _groups(scene) if n != self.group])
        targets = _solo_targets(scene)
        if "grp:" + self.group in targets:
            targets.remove("grp:" + self.group)
            _solo_write(context, targets)
        return {"FINISHED"}


class POND_OT_ld_assign(bpy.types.Operator):
    """把视口里选中的灯/发光面片加进这个组"""
    bl_idname = "pond.ld_assign"
    bl_label = "把选中的加进组"
    bl_options = {"REGISTER", "UNDO"}

    group: bpy.props.StringProperty()

    def execute(self, context):
        n = 0
        skip = 0
        for obj in context.selected_objects:
            if obj.type == "LIGHT" or _is_emissive(obj):
                obj.pond_ld_group = self.group
                n += 1
            else:
                skip += 1
        if not n:
            self.report({"WARNING"}, "选中的里面没有灯，也没有发光材质的物体")
            return {"CANCELLED"}
        msg = "加进「%s」%d 个" % (self.group, n)
        if skip:
            msg += "（跳过 %d 个不发光的）" % skip
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class POND_OT_ld_unassign(bpy.types.Operator):
    """把这盏灯移出所在组"""
    bl_idname = "pond.ld_unassign"
    bl_label = "移出组"
    bl_options = {"REGISTER", "UNDO"}

    obj_name: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.scene.objects.get(self.obj_name)
        if obj:
            obj.pond_ld_group = ""
        return {"FINISHED"}


class POND_OT_ld_solo(bpy.types.Operator):
    """Solo（只动小眼睛,渲染开关不碰）。可叠加：点别的灯=一起亮；点已 solo 的=移出去"""
    bl_idname = "pond.ld_solo"
    bl_label = "Solo"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(items=[
        ("OBJ", "单灯", ""), ("GRP", "整组", ""), ("OFF", "退出", "")])
    target: bpy.props.StringProperty()

    def execute(self, context):
        scene = context.scene
        if self.mode == "OFF":
            _solo_write(context, [])
            return {"FINISHED"}
        key = ("obj:" if self.mode == "OBJ" else "grp:") + self.target
        if self.mode == "OBJ" and not scene.objects.get(self.target):
            self.report({"WARNING"}, "找不到这盏灯了")
            return {"CANCELLED"}
        if self.mode == "GRP" and not _members(scene, self.target):
            self.report({"WARNING"}, "这个组是空的")
            return {"CANCELLED"}
        targets = _solo_targets(scene)
        if key in targets:
            targets.remove(key)     # 已在 solo 里 → 移出去；空了自动恢复
        else:
            targets.append(key)     # 叠加进来一起亮
        _solo_write(context, targets)
        return {"FINISHED"}


class POND_OT_ld_fold(bpy.types.Operator):
    """收起/展开这个组的成员清单"""
    bl_idname = "pond.ld_fold"
    bl_label = "收展"

    group: bpy.props.StringProperty()

    def execute(self, context):
        if self.group in _fold:
            _fold.discard(self.group)
        else:
            _fold.add(self.group)
        return {"FINISHED"}


class POND_OT_ld_vis(bpy.types.Operator):
    """在视口中藏/显这盏灯（小眼睛，渲染开关不动）"""
    bl_idname = "pond.ld_vis"
    bl_label = "视口隐藏"
    bl_options = {"REGISTER", "UNDO"}

    obj_name: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.scene.objects.get(self.obj_name)
        if not obj:
            return {"CANCELLED"}
        try:
            obj.hide_set(not obj.hide_get())
        except RuntimeError:
            self.report({"WARNING"}, "这盏灯不在当前视图层")
            return {"CANCELLED"}
        return {"FINISHED"}


class POND_OT_ld_select(bpy.types.Operator):
    """点灯名选中这盏灯"""
    bl_idname = "pond.ld_select"
    bl_label = "选中这盏灯"

    obj_name: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.scene.objects.get(self.obj_name)
        if not obj:
            self.report({"WARNING"}, "找不到这盏灯了")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        try:
            obj.select_set(True)
            context.view_layer.objects.active = obj
        except RuntimeError:
            return {"CANCELLED"}
        return {"FINISHED"}


class POND_OT_ld_group_vis(bpy.types.Operator):
    """整组在视口中藏/显（小眼睛，渲染开关不动）"""
    bl_idname = "pond.ld_group_vis"
    bl_label = "整组视口隐藏"
    bl_options = {"REGISTER", "UNDO"}

    group: bpy.props.StringProperty()

    def execute(self, context):
        mem = _members(context.scene, self.group)
        if not mem:
            return {"CANCELLED"}
        to = any(not _hidden(o) for o in mem)
        for obj in mem:
            try:
                obj.hide_set(to)
            except RuntimeError:
                pass
        return {"FINISHED"}


# ── 面板 ──

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
    poll = prefs.module_enabled("show_lightdesk")

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
    POND_OT_ld_group_new,
    POND_OT_ld_group_del,
    POND_OT_ld_assign,
    POND_OT_ld_unassign,
    POND_OT_ld_solo,
    POND_OT_ld_fold,
    POND_OT_ld_select,
    POND_OT_ld_vis,
    POND_OT_ld_group_vis,
    POND_PT_lightdesk,
)


def register():
    bpy.types.Object.pond_ld_group = bpy.props.StringProperty(
        name="灯光组", default="")
    bpy.types.Scene.pond_ld_groups = bpy.props.StringProperty(default="[]")
    bpy.types.Scene.pond_ld_newname = bpy.props.StringProperty(
        name="新组名", default="", description="比如：主光 / 辅光 / 氛围")
    bpy.types.Scene.pond_ld_solo = bpy.props.StringProperty(default="")
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Object.pond_ld_group
    del bpy.types.Scene.pond_ld_groups
    del bpy.types.Scene.pond_ld_newname
    del bpy.types.Scene.pond_ld_solo
