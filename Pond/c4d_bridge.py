# C4D 互导：集合转 Empty 组长导 FBX（C4D 只认父子层级不认集合）
# 导出全程在当前数据上临时打组、导完还原，不动工程本身
# 材质清单：Principled 槽位 → JSON + 贴图包，给 C4D 侧重建 Octane 材质用
# Alembic 顶点缓存：绑骨角色动画去 C4D 渲染用，逐帧网格所见即所得
import json
import os
import shutil
import time
import bpy

from . import prefs
from bpy_extras.io_utils import ExportHelper


def _build_group_empties(scene):
    """集合结构 → 临时 Empty 组长（C4D 只认父子层级不认集合）。
    返回 (created, moved) 给 _restore_group_empties 还原"""
    created = []   # 临时组长 Empty
    moved = []     # (obj, 原parent, 原世界矩阵)

    def build(col, parent_empty):
        empty = bpy.data.objects.new(col.name, None)
        scene.collection.objects.link(empty)
        created.append(empty)
        if parent_empty:
            empty.parent = parent_empty
        for o in col.objects:
            if o.parent is None:  # 有父级的跟着父级走，不重复挂
                moved.append((o, o.parent, o.matrix_world.copy()))
                o.parent = empty
                o.matrix_world = moved[-1][2]
        for sub in col.children:
            build(sub, empty)

    for col in scene.collection.children:
        build(col, None)
    return created, moved


def _restore_group_empties(created, moved):
    """还原现场：先还对象，再删临时组长"""
    for o, parent, mw in moved:
        o.parent = parent
        o.matrix_world = mw
    for e in created:
        bpy.data.objects.remove(e)


class POND_OT_export_c4d(bpy.types.Operator, ExportHelper):
    """按集合结构打组导出 FBX 给 C4D（贴图一并打包）"""
    bl_idname = "pond.export_c4d"
    bl_label = "导出 C4D 分组 FBX"
    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(default="*.fbx", options={"HIDDEN"})

    def invoke(self, context, event):
        blend = bpy.path.basename(bpy.data.filepath)
        stem = os.path.splitext(blend)[0] if blend else "未命名"
        self.filepath = f"{stem}_分组.fbx"
        return super().invoke(context, event)

    def execute(self, context):
        scene = context.scene
        created, moved = [], []
        try:
            created, moved = _build_group_empties(scene)
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=False,
                object_types={"EMPTY", "MESH", "ARMATURE", "LIGHT", "CAMERA", "OTHER"},
                path_mode="COPY",
                embed_textures=False,
            )
        except Exception as e:
            self.report({"ERROR"}, f"导出失败：{e}")
            return {"CANCELLED"}
        finally:
            _restore_group_empties(created, moved)

        self.report({"INFO"}, f"导出完成：{self.filepath}")
        return {"FINISHED"}


# abc 里有意义的类型：能出几何的 + 摄像机；其余（灯光/骨架/空物体…）只会变成空 Null
_ABC_KEEP_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT",
                   "CURVES", "POINTCLOUD", "VOLUME", "CAMERA"}


class POND_OT_export_c4d_abc(bpy.types.Operator, ExportHelper):
    """导出 Alembic 顶点缓存给 C4D 渲染：绑骨/约束/物理全烘成逐帧网格，摄像机一起走。
到那边不可再编辑，要继续调动作的角色别走这条"""
    bl_idname = "pond.export_c4d_abc"
    bl_label = "导出 Alembic 顶点缓存"
    filename_ext = ".abc"
    filter_glob: bpy.props.StringProperty(default="*.abc", options={"HIDDEN"})

    only_selected: bpy.props.BoolProperty(name="仅选中物体", default=False)
    flatten: bpy.props.BoolProperty(
        name="压平层级（不要任何组）", default=False,
        description="默认保留分组：集合和父级会变成 C4D 里的组长 Null。"
                    "勾上则全部平铺，一个空节点都不留")
    frame_start: bpy.props.IntProperty(name="起始帧", default=1)
    frame_end: bpy.props.IntProperty(name="结束帧", default=250)
    samples: bpy.props.IntProperty(
        name="每帧采样数", default=1, min=1, max=8,
        description="C4D/Octane 里要运动模糊就开 2 以上")
    apply_subdiv: bpy.props.BoolProperty(
        name="烘进细分", default=True,
        description="按渲染设置把细分烘进网格，所见即所得；嫌文件大就关掉，去 C4D 再细分")
    global_scale: bpy.props.FloatProperty(
        name="缩放", default=100.0,
        description="C4D 按厘米读数值，100 = 米转厘米，和分组 FBX 的尺寸一致")

    def invoke(self, context, event):
        blend = bpy.path.basename(bpy.data.filepath)
        stem = os.path.splitext(blend)[0] if blend else "未命名"
        self.filepath = f"{stem}_顶点缓存.abc"
        self.frame_start = context.scene.frame_start
        self.frame_end = context.scene.frame_end
        return super().invoke(context, event)

    def execute(self, context):
        scene = context.scene
        # 所见即所得：几何只导视图里看得见的；摄像机 = 可见的 + 当前激活相机（藏着也带）
        pool = context.selected_objects if self.only_selected else list(scene.objects)

        def vis(o):
            try:
                return o.visible_get()
            except RuntimeError:
                return False

        targets = []
        for o in pool:
            if o.type not in _ABC_KEEP_TYPES:
                continue
            if o.type == "CAMERA":
                if vis(o) or o == scene.camera:
                    targets.append(o)
            elif vis(o):
                targets.append(o)
        if not targets:
            self.report({"ERROR"}, "没有可导出的几何或摄像机")
            return {"CANCELLED"}

        kwargs = dict(
            filepath=self.filepath,
            start=self.frame_start,
            end=self.frame_end,
            xsamples=self.samples,
            gsamples=self.samples,
            selected=True,
            visible_objects_only=False,
            flatten=self.flatten,
            uvs=True,
            normals=True,
            face_sets=True,   # 材质分面组带过去，C4D 里按材质名对回
            apply_subdiv=self.apply_subdiv,
            use_instancing=True,
            global_scale=self.global_scale,
            evaluation_mode="RENDER",
        )
        # 跨版本保险：参数名有变动就丢弃不识别的，别整个导出挂掉
        avail = bpy.ops.wm.alembic_export.get_rna_type().properties.keys()
        kwargs = {k: v for k, v in kwargs.items() if k in avail}

        prev_sel = list(context.selected_objects)
        prev_active = context.view_layer.objects.active

        # 目标必须可见可选、且渲染评估里能逐帧采样：
        # 视图/渲染/集合的隐藏全部临时解除，导完还原
        obj_restore = []
        for o in targets:
            try:
                hidden = o.hide_get()
            except RuntimeError:
                hidden = False
            obj_restore.append((o, hidden, o.hide_viewport, o.hide_render))
            try:
                o.hide_set(False)
            except RuntimeError:
                pass
            o.hide_viewport = False
            o.hide_render = False
        col_restore = [(c, c.hide_viewport, c.hide_render) for c in bpy.data.collections]
        for c, _, _ in col_restore:
            c.hide_viewport = False
            c.hide_render = False
        context.view_layer.update()

        # 保留分组时：集合转临时 Empty 组长（导出器会把父链写成组节点）
        created, moved = [], []
        bridged = []   # 父链被骨架等不可导类型卡断的对象，临时桥到组长
        if not self.flatten:
            created, moved = _build_group_empties(scene)
            # 绑骨角色的 mesh 挂在 armature 下，armature 会被 abc 导出器
            # 整个吞掉，父链在它那里断，mesh 平铺到根级。
            # Empty 父链是安全的（导出器必写 xform），只有骨架这类才算断点。
            # 断链对象桥到断点上方最近的安全祖先（Empty/组长/其他导出对象），
            # 世界矩阵不动；abc 逐帧采样相对变换，对象级动画不丢。
            created_set = set(created)
            target_set = set(targets)
            boned = 0
            for o in targets:
                # 骨骼挂载的对象(相机摇臂等)运动全在父级骨骼上——
                # 桥接会把它的世界矩阵冻在当前帧,动画就没了。
                # 不桥,让它平铺到根级:导出器对无父级对象逐帧写世界矩阵,动画不丢
                if o.parent_type == "BONE":
                    boned += 1
                    continue
                anc = o.parent
                crossed_bad = False
                dest = None
                while anc is not None:
                    if anc in created_set or anc in target_set or anc.type == "EMPTY":
                        dest = anc
                        break
                    crossed_bad = True   # armature/lattice 等会被导出器吞的
                    anc = anc.parent
                if crossed_bad and dest is not None:
                    bridged.append((o, o.parent, o.matrix_world.copy()))
                    o.parent = dest
                    o.matrix_world = bridged[-1][2]
            self._boned = boned

        selected_ok = []
        unreachable = 0
        try:
            for o in context.view_layer.objects:
                try:
                    o.select_set(False)
                except RuntimeError:
                    pass
            for o in targets:
                try:
                    o.select_set(True)
                    selected_ok.append(o)
                except RuntimeError:
                    unreachable += 1  # 不在视图层里（被排除的集合），选不中
            bpy.ops.wm.alembic_export(**kwargs)
        except Exception as e:
            self.report({"ERROR"}, f"导出失败：{e}")
            return {"CANCELLED"}
        finally:
            for o in context.view_layer.objects:
                try:
                    o.select_set(False)
                except RuntimeError:
                    pass
            for o in prev_sel:
                try:
                    o.select_set(True)
                except RuntimeError:
                    pass
            context.view_layer.objects.active = prev_active
            for o, parent, mw in bridged:   # 先拆桥，再还组长
                o.parent = parent
                o.matrix_world = mw
            _restore_group_empties(created, moved)
            for c, hv, hr in col_restore:
                c.hide_viewport = hv
                c.hide_render = hr
            for o, hs, hv, hr in obj_restore:
                try:
                    o.hide_set(hs)
                except RuntimeError:
                    pass
                o.hide_viewport = hv
                o.hide_render = hr

        n_cam = sum(1 for o in selected_ok if o.type == "CAMERA")
        n_geo = len(selected_ok) - n_cam
        # abc7 是版本印记：提示里看不到它 = Blender 加载的还是旧代码
        msg = f"[abc7] 导出完成：几何 {n_geo}、摄像机 {n_cam}，{self.frame_start}-{self.frame_end} 帧"
        if bridged:
            msg += f"；{len(bridged)} 个对象的断链父级已桥到组长"
        if getattr(self, "_boned", 0):
            msg += f"；{self._boned} 个骨骼挂载对象平铺到根级(保动画)"
        warn = False
        if n_cam == 0 and any(o.type == "CAMERA" for o in scene.objects):
            msg += "；场景里有摄像机但没导上（看看它是否在被排除的集合里）"
            warn = True
        if unreachable:
            msg += f"；{unreachable} 个对象在被排除的集合里没导上"
            warn = True
        self.report({"WARNING" if warn else "INFO"}, msg)
        return {"FINISHED"}


class POND_OT_import_c4d_restore(bpy.types.Operator):
    """把选中的 Empty 组长还原成 Collection：只转选中的这一层，
里面的子 Empty 组保持原样（想一起转就把它们也选上）"""
    bl_idname = "pond.import_c4d_restore"
    bl_label = "Empty 组还原成集合"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.type == "EMPTY" and o.children for o in context.selected_objects)

    def execute(self, context):
        roots = [o for o in context.selected_objects if o.type == "EMPTY" and o.children]
        # 外层的先转，一起选中的子组随后自然嵌进外层新集合
        def depth(o):
            d = 0
            p = o.parent
            while p:
                d += 1
                p = p.parent
            return d
        roots.sort(key=depth)
        n = 0

        def move_subtree(o, col):
            for uc in list(o.users_collection):
                uc.objects.unlink(o)
            col.objects.link(o)
            for c in o.children:
                move_subtree(c, col)

        for root in roots:
            parent_col = root.users_collection[0] if root.users_collection \
                else context.scene.collection
            col = bpy.data.collections.new(root.name)
            parent_col.children.link(col)
            n += 1
            for child in list(root.children):
                mw = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = mw
                move_subtree(child, col)
            bpy.data.objects.remove(root)

        self.report({"INFO"}, f"还原了 {n} 个集合")
        return {"FINISHED"}


# ── 材质清单导出（Blender Principled → Octane 翻译层的 B 侧） ──

# 清单键 → Principled 输入名（兼容 4.x 前后的改名）
_SLOTS = (
    ("base_color", ("Base Color",)),
    ("metallic", ("Metallic",)),
    ("roughness", ("Roughness",)),
    ("ior", ("IOR",)),
    ("alpha", ("Alpha",)),
    ("transmission", ("Transmission Weight", "Transmission")),
    ("emission_color", ("Emission Color", "Emission")),
    ("emission_strength", ("Emission Strength",)),
    ("normal", ("Normal",)),
)
# 允许穿透的颜色处理节点：往上游继续找贴图
_PASSTHROUGH = {"NORMAL_MAP", "MIX", "MIX_RGB", "HUE_SAT", "BRIGHTCONTRAST",
                "CURVE_RGB", "GAMMA", "INVERT", "SEPARATE_COLOR", "SEPCOLOR"}


def _upstream_image(socket, depth=0):
    """顺着链接往上找图像纹理，穿过常见的颜色处理节点"""
    if not socket or not socket.links or depth > 5:
        return None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE":
        return node.image
    if node.type in _PASSTHROUGH:
        for inp in node.inputs:
            img = _upstream_image(inp, depth + 1)
            if img:
                return img
    return None


def _slot_entry(inp, textures):
    """一个槽位 → {'tex': 相对路径} / {'value': ...} / {'procedural': 节点类型}"""
    if inp.links:
        img = _upstream_image(inp)
        if img is not None:
            return {"tex": textures.claim(img)}
        return {"procedural": inp.links[0].from_node.type}
    v = inp.default_value
    try:
        return {"value": [round(x, 5) for x in v]}
    except TypeError:
        return {"value": round(float(v), 5)}


class _TextureBag:
    """把用到的贴图收进 textures/，同名去重"""

    def __init__(self, outdir):
        self.dir = os.path.join(outdir, "textures")
        self.claimed = {}   # image.name -> 相对路径
        self.jobs = {}      # 目标绝对路径 -> image
        self.taken = set()

    def claim(self, img):
        if img.name in self.claimed:
            return self.claimed[img.name]
        src = bpy.path.abspath(img.filepath) if img.filepath else ""
        base = os.path.basename(src) if src else img.name + ".png"
        name = base
        n = 1
        while name in self.taken:
            name = f"{os.path.splitext(base)[0]}_{n}{os.path.splitext(base)[1]}"
            n += 1
        self.taken.add(name)
        rel = "textures/" + name
        self.claimed[img.name] = rel
        self.jobs[os.path.join(self.dir, name)] = (img, src)
        return rel

    def flush(self):
        copied, baked, missing = 0, 0, []
        if self.jobs:
            os.makedirs(self.dir, exist_ok=True)
        for dest, (img, src) in self.jobs.items():
            if src and os.path.isfile(src):
                shutil.copy2(src, dest)
                copied += 1
            elif img.packed_file or img.has_data:
                try:  # 打包/生成的图落一份盘
                    img.save_render(dest)
                    baked += 1
                except Exception:
                    missing.append(img.name)
            else:
                missing.append(img.name)
        return copied, baked, missing


class POND_OT_export_mat_manifest(bpy.types.Operator, ExportHelper):
    """导出材质槽位清单 JSON + 贴图包，给 C4D 侧重建 Octane 材质"""
    bl_idname = "pond.export_mat_manifest"
    bl_label = "导出材质清单"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})
    only_selected: bpy.props.BoolProperty(name="仅选中物体", default=False)

    def invoke(self, context, event):
        blend = bpy.path.basename(bpy.data.filepath)
        stem = os.path.splitext(blend)[0] if blend else "未命名"
        self.filepath = f"{stem}_材质清单.json"
        return super().invoke(context, event)

    def execute(self, context):
        objs = context.selected_objects if self.only_selected else context.scene.objects
        outdir = os.path.dirname(self.filepath)
        textures = _TextureBag(outdir)
        materials, objects, procedural = {}, {}, {}

        for obj in objs:
            mats = [s.material for s in getattr(obj, "material_slots", []) if s.material]
            if mats:
                objects[obj.name] = [m.name for m in mats]
            for mat in mats:
                if mat.name in materials:
                    continue
                entry = {}
                bsdf = None
                if mat.use_nodes:
                    bsdf = next((n for n in mat.node_tree.nodes
                                 if n.type == "BSDF_PRINCIPLED"), None)
                if bsdf is None:
                    entry["note"] = "无Principled节点,只给了漫射色"
                    entry["base_color"] = {"value": list(mat.diffuse_color)}
                else:
                    for key, names in _SLOTS:
                        inp = next((bsdf.inputs[n] for n in names if n in bsdf.inputs), None)
                        if inp is None:
                            continue
                        if key == "normal" and not inp.links:
                            continue  # 法线没接东西就不记
                        entry[key] = _slot_entry(inp, textures)
                    # 置换走材质输出节点
                    out_node = next((n for n in mat.node_tree.nodes
                                     if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
                    if out_node and out_node.inputs["Displacement"].links:
                        img = _upstream_image(out_node.inputs["Displacement"])
                        if img:
                            entry["displacement"] = {"tex": textures.claim(img)}
                bad = [k for k, v in entry.items()
                       if isinstance(v, dict) and "procedural" in v]
                if bad:
                    procedural[mat.name] = bad
                materials[mat.name] = entry

        copied, baked, missing = textures.flush()
        manifest = {
            "source": bpy.path.basename(bpy.data.filepath) or "未保存",
            "exported": time.strftime("%Y-%m-%d %H:%M"),
            "materials": materials,
            "objects": objects,
            "procedural_slots": procedural,
            "missing_images": missing,
        }
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)

        msg = f"{len(materials)} 材质 / 贴图复制{copied} 落盘{baked}"
        if procedural:
            msg += f" / {len(procedural)} 个材质有程序化槽位待烘焙"
        if missing:
            msg += f" / {len(missing)} 张图丢失"
        self.report({"WARNING" if (procedural or missing) else "INFO"}, msg)
        return {"FINISHED"}


class POND_PT_c4d(bpy.types.Panel):
    bl_label = "C4D 互导"
    bl_idname = "POND_PT_c4d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "池塘"
    bl_parent_id = "POND_PT_sec_ship"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}
    poll = prefs.module_enabled("show_c4d")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("pond.export_c4d", icon="EXPORT")
        col.operator("pond.export_c4d_abc", icon="RENDER_ANIMATION")
        col.operator("pond.import_c4d_restore", icon="IMPORT")
        col.separator()
        col.operator("pond.export_mat_manifest", icon="MATERIAL")


_classes = (
    POND_OT_export_c4d,
    POND_OT_export_c4d_abc,
    POND_OT_import_c4d_restore,
    POND_OT_export_mat_manifest,
    POND_PT_c4d,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
