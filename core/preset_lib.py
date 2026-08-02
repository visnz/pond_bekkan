# 节点预设库：几何节点 / 材质双分页，自己养预设
# 每个预设单独存一个 .blend，index.json 记名字和备注，改名删除都是文件操作
# （合并自 Pond/preset_lib.py：逻辑层；面板和 UIList 在 ui/pond/panels/preset_lib.py）
import json
import os
import re
import time
import bpy

# TODO(合并清单): 库根路径硬编码，后续宜改为偏好设置可配
LIB_ROOT = r"I:\Blender资产\预设库"
KINDS = {"GEO": "geo", "SHADER": "shader"}


def _dir(kind):
    path = os.path.join(LIB_ROOT, KINDS[kind])
    os.makedirs(path, exist_ok=True)
    return path


def _index_path(kind):
    return os.path.join(_dir(kind), "index.json")


def _load_index(kind):
    try:
        with open(_index_path(kind), encoding="utf-8") as f:
            return json.load(f).get("presets", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_index(kind, presets):
    with open(_index_path(kind), "w", encoding="utf-8") as f:
        json.dump({"presets": presets}, f, ensure_ascii=False, indent=2)


def _refresh_items(wm):
    kind = wm.pond_lib_tab
    wm.pond_lib_items.clear()
    for p in _load_index(kind):
        it = wm.pond_lib_items.add()
        it.label = p.get("label", "")
        it.name = it.label   # 列表自带搜索只认name,不填搜不到
        it.desc = p.get("desc", "")
        it.file = p.get("file", "")
        it.datablock = p.get("datablock", "")
    wm.pond_lib_index = min(wm.pond_lib_index, max(0, len(wm.pond_lib_items) - 1))


def _on_tab_change(self, context):
    _refresh_items(context.window_manager)


class PondLibItem(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()
    desc: bpy.props.StringProperty()
    file: bpy.props.StringProperty()
    datablock: bpy.props.StringProperty()


class POND_OT_lib_refresh(bpy.types.Operator):
    """重新读取预设库列表"""
    bl_idname = "pond.lib_refresh"
    bl_label = "刷新"

    def execute(self, context):
        _refresh_items(context.window_manager)
        return {"FINISHED"}


class POND_OT_lib_save(bpy.types.Operator):
    """把当前激活的节点组/材质存进预设库"""
    bl_idname = "pond.lib_save"
    bl_label = "存入预设库"

    label: bpy.props.StringProperty(name="名字")
    desc: bpy.props.StringProperty(name="备注")

    def _pick_datablock(self, context):
        kind = context.window_manager.pond_lib_tab
        obj = context.active_object
        if kind == "GEO":
            if obj:
                mod = obj.modifiers.active
                if mod and mod.type == "NODES" and mod.node_group:
                    return mod.node_group
                for m in obj.modifiers:
                    if m.type == "NODES" and m.node_group:
                        return m.node_group
            return None
        return obj.active_material if obj else None

    def invoke(self, context, event):
        db = self._pick_datablock(context)
        if db is None:
            kind = context.window_manager.pond_lib_tab
            what = "几何节点修改器" if kind == "GEO" else "材质"
            self.report({"WARNING"}, f"激活物体上没有可存的{what}")
            return {"CANCELLED"}
        self.label = db.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        wm = context.window_manager
        kind = wm.pond_lib_tab
        db = self._pick_datablock(context)
        if db is None:
            return {"CANCELLED"}
        label = self.label.strip() or db.name

        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", label)[:40]
        filename = f"{int(time.time())}_{safe}.blend"
        filepath = os.path.join(_dir(kind), filename)
        try:
            bpy.data.libraries.write(filepath, {db}, fake_user=True,
                                     path_remap="ABSOLUTE")
        except Exception as e:
            self.report({"ERROR"}, f"写库失败：{e}")
            return {"CANCELLED"}

        presets = _load_index(kind)
        presets.append({
            "label": label,
            "desc": self.desc.strip(),
            "file": filename,
            "datablock": db.name,
            "created": time.strftime("%Y-%m-%d %H:%M"),
        })
        _save_index(kind, presets)
        _refresh_items(wm)
        wm.pond_lib_index = len(wm.pond_lib_items) - 1
        self.report({"INFO"}, f"「{label}」进库了")
        return {"FINISHED"}


class POND_OT_lib_apply(bpy.types.Operator):
    """把选中的预设挂到所选物体上"""
    bl_idname = "pond.lib_apply"
    bl_label = "挂载到所选"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return context.selected_objects and 0 <= wm.pond_lib_index < len(wm.pond_lib_items)

    def execute(self, context):
        wm = context.window_manager
        kind = wm.pond_lib_tab
        it = wm.pond_lib_items[wm.pond_lib_index]
        filepath = os.path.join(_dir(kind), it.file)
        if not os.path.isfile(filepath):
            self.report({"ERROR"}, "库文件不见了，刷新看看")
            return {"CANCELLED"}

        try:
            with bpy.data.libraries.load(filepath, link=False) as (src, dst):
                if kind == "GEO":
                    dst.node_groups = [it.datablock]
                else:
                    dst.materials = [it.datablock]
            loaded = (dst.node_groups if kind == "GEO" else dst.materials)[0]
        except Exception as e:
            self.report({"ERROR"}, f"读库失败：{e}")
            return {"CANCELLED"}
        if loaded is None:
            self.report({"ERROR"}, "库文件里找不到这个数据块")
            return {"CANCELLED"}

        n = 0
        if kind == "GEO":
            for obj in context.selected_objects:
                if obj.type in {"MESH", "CURVE", "CURVES", "POINTCLOUD", "VOLUME"}:
                    mod = obj.modifiers.new(name=it.label, type="NODES")
                    mod.node_group = loaded
                    n += 1
        else:
            for obj in context.selected_objects:
                data = getattr(obj, "data", None)
                if data is None or not hasattr(data, "materials"):
                    continue
                if obj.material_slots:
                    obj.material_slots[obj.active_material_index].material = loaded
                else:
                    data.materials.append(loaded)
                n += 1

        self.report({"INFO"}, f"挂到了 {n} 个物体上")
        return {"FINISHED"}


class POND_OT_lib_rename(bpy.types.Operator):
    """改预设的显示名和备注"""
    bl_idname = "pond.lib_rename"
    bl_label = "重命名 / 改备注"

    label: bpy.props.StringProperty(name="名字")
    desc: bpy.props.StringProperty(name="备注")

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return 0 <= wm.pond_lib_index < len(wm.pond_lib_items)

    def invoke(self, context, event):
        wm = context.window_manager
        it = wm.pond_lib_items[wm.pond_lib_index]
        self.label, self.desc = it.label, it.desc
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        wm = context.window_manager
        kind = wm.pond_lib_tab
        it = wm.pond_lib_items[wm.pond_lib_index]
        presets = _load_index(kind)
        for p in presets:
            if p.get("file") == it.file:
                p["label"] = self.label.strip() or p["label"]
                p["desc"] = self.desc.strip()
        _save_index(kind, presets)
        _refresh_items(wm)
        return {"FINISHED"}


class POND_OT_lib_delete(bpy.types.Operator):
    """把选中的预设从库里删掉（会删文件）"""
    bl_idname = "pond.lib_delete"
    bl_label = "删除预设"

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return 0 <= wm.pond_lib_index < len(wm.pond_lib_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        wm = context.window_manager
        kind = wm.pond_lib_tab
        it = wm.pond_lib_items[wm.pond_lib_index]
        filepath = os.path.join(_dir(kind), it.file)
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
        except OSError as e:
            self.report({"ERROR"}, f"删不掉文件：{e}")
            return {"CANCELLED"}
        _save_index(kind, [p for p in _load_index(kind) if p.get("file") != it.file])
        _refresh_items(wm)
        return {"FINISHED"}


_classes = (
    PondLibItem,
    POND_OT_lib_refresh,
    POND_OT_lib_save,
    POND_OT_lib_apply,
    POND_OT_lib_rename,
    POND_OT_lib_delete,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.pond_lib_tab = bpy.props.EnumProperty(
        items=[("GEO", "几何节点", "几何节点组预设"),
               ("SHADER", "材质", "材质预设")],
        default="GEO", update=_on_tab_change)
    bpy.types.WindowManager.pond_lib_items = bpy.props.CollectionProperty(type=PondLibItem)
    bpy.types.WindowManager.pond_lib_index = bpy.props.IntProperty(default=0)


def unregister():
    del bpy.types.WindowManager.pond_lib_index
    del bpy.types.WindowManager.pond_lib_items
    del bpy.types.WindowManager.pond_lib_tab
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
