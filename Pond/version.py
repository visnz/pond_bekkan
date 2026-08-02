# 版本另存：工程 v### 递增另存，渲染输出和合成器 File Output 路径同步打版本号
# 由来：2026-07-08 忘改文件名把渲染盖掉的那声「完蛋了」
import os
import re
import bpy

from . import prefs

_VER = re.compile(r"[_.]?v(\d{2,4})", re.IGNORECASE)


def _split_version(stem):
    """'安乐_v003' -> ('安乐', 3)；没有版本号 -> (原名, None)"""
    m = None
    for m in _VER.finditer(stem):
        pass  # 取最后一个匹配
    if m:
        return stem[:m.start()], int(m.group(1))
    return stem, None


def _next_free_version(directory, base, start):
    """从 start 起找同目录下没被占用的版本号"""
    v = start
    while os.path.exists(os.path.join(directory, f"{base}_v{v:03d}.blend")):
        v += 1
    return v


def _bump_path_version(path, ver):
    """把路径里的 v### 全部替换成指定版本；没有就在文件名/末级名后追加"""
    if not path:
        return path, False
    if _VER.search(path):
        return _VER.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + f"{ver:03d}", path), True
    root, ext = os.path.splitext(path)
    sep = "" if root.endswith(("/", "\\")) else None
    if sep == "":  # 以目录分隔符结尾的输出目录
        return root + f"v{ver:03d}" + ext, True
    return f"{root}_v{ver:03d}{ext}", True


def _iter_file_output_nodes(scene):
    tree = getattr(scene, "compositing_node_group", None) or getattr(scene, "node_tree", None)
    if not tree:
        return
    stack = [tree]
    seen = set()
    while stack:
        t = stack.pop()
        if t is None or t.name in seen:
            continue
        seen.add(t.name)
        for n in t.nodes:
            if n.type == "OUTPUT_FILE":
                yield n
            elif n.type == "GROUP" and n.node_tree:
                stack.append(n.node_tree)


class POND_OT_save_version(bpy.types.Operator):
    """另存为下一个版本，渲染输出路径和合成器 File Output 一起同步版本号"""
    bl_idname = "pond.save_version"
    bl_label = "另存下一版"

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath)

    def execute(self, context):
        directory = os.path.dirname(bpy.data.filepath)
        stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
        base, cur = _split_version(stem)
        base = base.rstrip("_.")
        ver = _next_free_version(directory, base, (cur or 0) + 1)
        newpath = os.path.join(directory, f"{base}_v{ver:03d}.blend")

        # 同步渲染输出与 File Output 节点
        synced = 0
        for scene in bpy.data.scenes:
            p, changed = _bump_path_version(scene.render.filepath, ver)
            if changed:
                scene.render.filepath = p
                synced += 1
            for node in _iter_file_output_nodes(scene):
                p, changed = _bump_path_version(node.base_path, ver)
                if changed:
                    node.base_path = p
                    synced += 1

        bpy.ops.wm.save_as_mainfile(filepath=newpath)
        self.report({"INFO"}, f"存为 v{ver:03d}，输出路径同步了 {synced} 处")
        return {"FINISHED"}


class POND_OT_sync_output_version(bpy.types.Operator):
    """不另存，只把渲染输出和 File Output 的版本号对齐到当前文件名"""
    bl_idname = "pond.sync_output_version"
    bl_label = "输出路径对齐版本"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath)

    def execute(self, context):
        stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
        _, cur = _split_version(stem)
        if cur is None:
            self.report({"WARNING"}, "当前文件名里没有 v 版本号，先用「另存下一版」")
            return {"CANCELLED"}
        synced = 0
        for scene in bpy.data.scenes:
            p, changed = _bump_path_version(scene.render.filepath, cur)
            if changed:
                scene.render.filepath = p
                synced += 1
            for node in _iter_file_output_nodes(scene):
                p, changed = _bump_path_version(node.base_path, cur)
                if changed:
                    node.base_path = p
                    synced += 1
        self.report({"INFO"}, f"输出路径对齐到 v{cur:03d}，共 {synced} 处")
        return {"FINISHED"}


class POND_PT_version(bpy.types.Panel):
    bl_label = "版本"
    bl_idname = "POND_PT_version"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_version")

    def draw(self, context):
        col = self.layout.column(align=True)
        if bpy.data.filepath:
            stem = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
            col.label(text=stem, icon="FILE_BLEND")
        col.operator("pond.save_version", icon="DUPLICATE")
        col.operator("pond.sync_output_version", icon="OUTPUT")


_classes = (
    POND_OT_save_version,
    POND_OT_sync_output_version,
    POND_PT_version,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
