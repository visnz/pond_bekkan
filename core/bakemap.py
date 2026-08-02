# 烘焙贴图：把物体上接好的程序化材质一键烘成贴图文件
# 基础色=DIFFUSE只取COLOR(无光照纯反照率) / 糙度=ROUGHNESS / 法线=NORMAL(切线空间)
# 凹凸=把接进凹凸节点Height口的源信号改道Emission烘成高度图,重建时凹凸节点读图
# 图落在工程旁 textures/，烘完自动搭一个「烘焙材质」，原材质原封不动可随时切回
# （合并自 Pond/bakemap.py：逻辑层；面板在 ui/pond/panels/bakemap.py）
import json
import os

import bpy

RES_ITEMS = (("512", "512", ""), ("1024", "1K", ""),
             ("2048", "2K", ""), ("4096", "4K", ""))


def _active_mesh(context):
    obj = context.active_object
    return obj if obj and obj.type == "MESH" else None


def _out_dir():
    if not bpy.data.filepath:
        return None
    d = os.path.join(os.path.dirname(bpy.data.filepath), "textures")
    os.makedirs(d, exist_ok=True)
    return d


def _bake_one(context, base, mats, suffix, size, margin, bake_kwargs, non_color):
    """建图→每个材质塞临时图片节点→烘→存盘→拆节点。返回 image
    烘的是当前选中的所有物体（多选=合烘进同一张图）"""
    name = f"烘焙_{base}_{suffix}"
    img = bpy.data.images.get(name)
    if img and tuple(img.size) != (size, size):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, size, size, alpha=False)
    if non_color:
        for cs in ("Non-Color", "Raw"):
            try:
                img.colorspace_settings.name = cs
                break
            except Exception:
                continue
    temp_nodes = []
    for mat in mats:
        tree = mat.node_tree
        node = tree.nodes.new("ShaderNodeTexImage")
        node.name = "池塘烘焙目标"
        node.image = img
        for n in tree.nodes:
            n.select = False
        node.select = True
        tree.nodes.active = node
        temp_nodes.append((tree, node))
    try:
        bpy.ops.object.bake(margin=margin, use_clear=True,
                            use_selected_to_active=False, **bake_kwargs)
    finally:
        for tree, node in temp_nodes:
            tree.nodes.remove(node)
    out = _out_dir()
    path = os.path.join(out, name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return img


def _bake_bump(context, base, mats, size, margin):
    """凹凸高度图：每个材质找第一个Height有连线的凹凸节点，把高度源
    临时接 Emission→材质输出 烘EMIT，烘完原样接回。
    返回 (image, 强度, 距离)；没有凹凸节点返回 (None, 0, 0)"""
    hooked = []   # (tree, emit节点, 输出节点, 原Surface源socket)
    strength = distance = None
    for mat in mats:
        tree = mat.node_tree
        bump = next((n for n in tree.nodes
                     if n.type == "BUMP" and n.inputs["Height"].is_linked), None)
        out = next((n for n in tree.nodes
                    if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if bump is None or out is None:
            continue
        if strength is None:
            strength = bump.inputs["Strength"].default_value
            distance = bump.inputs["Distance"].default_value
        src = bump.inputs["Height"].links[0].from_socket
        emit = tree.nodes.new("ShaderNodeEmission")
        emit.name = "池塘凹凸改道"
        orig = (out.inputs["Surface"].links[0].from_socket
                if out.inputs["Surface"].is_linked else None)
        tree.links.new(src, emit.inputs["Color"])
        tree.links.new(emit.outputs[0], out.inputs["Surface"])
        hooked.append((tree, emit, out, orig))
    if not hooked:
        return None, 0, 0
    try:
        img = _bake_one(context, base, mats, "凹凸", size, margin,
                        {"type": "EMIT"}, True)
    finally:
        for tree, emit, out, orig in hooked:
            tree.nodes.remove(emit)
            if orig is not None:
                tree.links.new(orig, out.inputs["Surface"])
    return img, strength, distance


def _grid_pack(objs):
    """打包的保底方案：每个物体的整套UV缩进棋盘格的一格(孤岛关系不变)"""
    import math
    n = len(objs)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    pad = 0.01
    seen_mesh = set()
    for idx, o in enumerate(objs):
        if o.data in seen_mesh:
            continue
        seen_mesh.add(o.data)
        lay = o.data.uv_layers.get("烘焙UV")
        if lay is None:
            continue
        cx, cy = idx % cols, idx // cols
        sx, sy = 1.0 / cols, 1.0 / rows
        for d in lay.data:
            u, v = d.uv
            d.uv = (cx * sx + (pad + u * (1 - 2 * pad)) * sx,
                    cy * sy + (pad + v * (1 - 2 * pad)) * sy)


def _pack_uv(context, objs):
    """保留孤岛打包：把各物体现有UV原样拷进「烘焙UV」层，
    不重新切岛、接缝不变，只把所有孤岛一起重新排进0~1。
    优先用官方Pack Islands，环境不允许时退化成棋盘格。"""
    for o in objs:
        me = o.data
        src = next((l for l in me.uv_layers if l.active_render), None)
        if src is None:
            return None, f"{o.name} 没有UV，打包模式要有原UV（不然改用智能展开）"
        lay = me.uv_layers.get("烘焙UV")
        if lay is None:
            if len(me.uv_layers) >= 8:
                return None, f"{o.name} 的UV层满8层了，删一层再来"
            me.uv_layers.active = src   # new(do_init)复制的是活动层
            lay = me.uv_layers.new(name="烘焙UV")
            if lay is None:
                return None, f"{o.name} 建不了新UV层"
        else:
            for i, d in enumerate(src.data):   # 已有就重新从原UV拷坐标
                lay.data[i].uv = d.uv
        me.uv_layers.active = lay
        src.active_render = True
    ts = context.scene.tool_settings
    prev_sync = ts.use_uv_select_sync
    ts.use_uv_select_sync = True   # 网格全选=UV全选,打包才认
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.uv.pack_islands(margin=0.02)
        packed = True
    except RuntimeError:
        packed = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        ts.use_uv_select_sync = prev_sync
    if not packed:
        _grid_pack(objs)
    return "烘焙UV", None


def _joint_uv(context, objs):
    """多物体合烘的UV准备：每个物体新建一层「烘焙UV」做烘焙目标，
    多物体编辑模式下一起智能展开(所有孤岛合排进同一个0~1)。
    原UV层一根手指不动，渲染采样层(active_render)保持原样。"""
    for o in objs:
        me = o.data
        orig_render = next((l for l in me.uv_layers if l.active_render), None)
        lay = me.uv_layers.get("烘焙UV")
        if lay is None:
            if len(me.uv_layers) >= 8:
                return None, f"{o.name} 的UV层满8层了，删一层再来"
            lay = me.uv_layers.new(name="烘焙UV")
            if lay is None:
                return None, f"{o.name} 建不了新UV层"
        me.uv_layers.active = lay
        if orig_render is not None and orig_render.name != "烘焙UV":
            orig_render.active_render = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    return "烘焙UV", None


def _bake_input(context, base, mats, suffix, socket, size, margin):
    """通用改道烘焙：把接进原理化BSDF某输入口(金属度/透明度…)的源信号
    改道 Emission 烘EMIT；没接线的烘常数值(多材质合烘各区域的值才都对)。
    返回 image；一个原理化BSDF都没有返回 None"""
    hooked = []
    for mat in mats:
        tree = mat.node_tree
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        out = next((n for n in tree.nodes
                    if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if bsdf is None or out is None:
            continue
        sock = bsdf.inputs[socket]
        emit = tree.nodes.new("ShaderNodeEmission")
        emit.name = f"池塘{suffix}改道"
        orig = (out.inputs["Surface"].links[0].from_socket
                if out.inputs["Surface"].is_linked else None)
        if sock.is_linked:
            tree.links.new(sock.links[0].from_socket, emit.inputs["Color"])
        else:
            v = sock.default_value
            emit.inputs["Color"].default_value = (v, v, v, 1.0)
        tree.links.new(emit.outputs[0], out.inputs["Surface"])
        hooked.append((tree, emit, out, orig))
    if not hooked:
        return None
    try:
        img = _bake_one(context, base, mats, suffix, size, margin,
                        {"type": "EMIT"}, True)
    finally:
        for tree, emit, out, orig in hooked:
            tree.nodes.remove(emit)
            if orig is not None:
                tree.links.new(orig, out.inputs["Surface"])
    return img


def _build_baked_mat(base, images, uv_name, bump_params=None):
    """基础色/糙度/法线/凹凸接进一个新原理化材质"""
    name = f"烘焙材质_{base}"
    mat = bpy.data.materials.get(name)
    if mat:
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    uv = None
    if uv_name:   # 不指定UV名=贴图跟各物体自己的渲染UV走
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = uv_name
        uv.location = (-620, 0)
    y = 260
    nm = bp = color_tex = ao_tex = None
    for key, img in images.items():
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.location = (-380, y)
        if uv:
            nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
        if key == "color":
            color_tex = tex
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        elif key == "rough":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])
        elif key == "metal":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Metallic"])
        elif key == "alpha":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Alpha"])
        elif key == "emit":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = 1.0
        elif key == "ao":
            ao_tex = tex
        elif key == "normal":
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.location = (-120, y - 40)
            nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        elif key == "bump":
            bp = nt.nodes.new("ShaderNodeBump")
            bp.location = (60, y - 40)
            if bump_params:
                bp.inputs["Strength"].default_value = bump_params[0]
                bp.inputs["Distance"].default_value = bump_params[1]
            nt.links.new(tex.outputs["Color"], bp.inputs["Height"])
        y -= 300
    # AO乘进基础色(有基础色图就乘,没有就直接当灰度结构用)
    if ao_tex and color_tex:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (-120, 260)
        mix.inputs["Factor"].default_value = 1.0
        # Mix节点同名口有Float/RGBA好几个,得挑RGBA的那对
        a_in = next(s for s in mix.inputs if s.name == "A" and s.type == "RGBA")
        b_in = next(s for s in mix.inputs if s.name == "B" and s.type == "RGBA")
        res = next(s for s in mix.outputs if s.name == "Result" and s.type == "RGBA")
        nt.links.new(color_tex.outputs["Color"], a_in)
        nt.links.new(ao_tex.outputs["Color"], b_in)
        nt.links.new(res, bsdf.inputs["Base Color"])
    elif ao_tex:
        nt.links.new(ao_tex.outputs["Color"], bsdf.inputs["Base Color"])
    # 法线/凹凸接进BSDF：都有就串起来(法线图垫底,凹凸叠上面)
    if nm and bp:
        nt.links.new(nm.outputs["Normal"], bp.inputs["Normal"])
        nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    elif bp:
        nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    elif nm:
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if "alpha" in images:
        # EEVEE 里透明要开混合方式(Cycles 不看这个)
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        try:
            mat.blend_method = "HASHED"
        except (AttributeError, TypeError):
            pass
    return mat


class POND_OT_bakemap(bpy.types.Operator):
    """把选中物体的程序化材质烘成贴图（原材质不动，烘完可两边切换）"""
    bl_idname = "pond.bakemap"
    bl_label = "烘焙选中物体"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        act = _active_mesh(context)
        wm = context.window_manager
        if not bpy.data.filepath:
            self.report({"ERROR"}, "先保存一下工程，贴图要落在工程旁的 textures/ 里")
            return {"CANCELLED"}
        objs = [o for o in context.selected_objects if o.type == "MESH"]
        if act not in objs:
            objs.insert(0, act)
        multi = len(objs) > 1
        base = f"{act.name}合{len(objs)}件" if multi else act.name
        mats = []
        for o in objs:
            for s in o.material_slots:
                if s.material and s.material.use_nodes and s.material not in mats:
                    mats.append(s.material)
        if not mats:
            self.report({"ERROR"}, "选中的物体没有节点材质，没东西可烘")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        for o in objs:
            o.select_set(True)
        context.view_layer.objects.active = act
        mode = wm.pond_bake_uvmode
        if mode == "SMART":
            # 新建「烘焙UV」层智能展开重排(多选=所有物体合排进一张图)
            # 原UV层和渲染采样层都不动,材质照旧从原UV读
            uv_name, err = _joint_uv(context, objs)
            if err:
                self.report({"ERROR"}, err)
                return {"CANCELLED"}
        elif mode == "PACK":
            # 保留原孤岛和接缝,只重新打包进一张图
            uv_name, err = _pack_uv(context, objs)
            if err:
                self.report({"ERROR"}, err)
                return {"CANCELLED"}
        elif multi:
            # 用各物体自己的UV做落点(共用一套UV或已手排不重叠的情况)
            # 烘焙材质不指定UV节点,贴图跟着各物体自己的渲染UV走
            for o in objs:
                if not o.data.uv_layers:
                    self.report({"ERROR"},
                                f"{o.name} 没有UV。排UV选「智能展开」,或先给它展一份")
                    return {"CANCELLED"}
            uv_name = None
        else:
            uv = act.data.uv_layers.active
            if uv is None:
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.uv.smart_project(island_margin=0.02)
                bpy.ops.object.mode_set(mode="OBJECT")
                uv = act.data.uv_layers.active
                self.report({"INFO"}, "物体没有UV，帮你智能展开了一份")
            uv_name = uv.name

        scene = context.scene
        prev_engine = scene.render.engine
        try:
            scene.render.engine = "CYCLES"
        except TypeError:
            self.report({"ERROR"}, "Cycles 不可用")
            return {"CANCELLED"}
        prev_samples = scene.cycles.samples
        scene.cycles.samples = 1
        size = int(wm.pond_bake_res)
        margin = wm.pond_bake_margin
        images = {}
        bump_params = None
        try:
            if wm.pond_bake_color:
                images["color"] = _bake_one(
                    context, base, mats, "基础色", size, margin,
                    {"type": "DIFFUSE", "pass_filter": {"COLOR"}}, False)
            if wm.pond_bake_rough:
                images["rough"] = _bake_one(
                    context, base, mats, "糙度", size, margin,
                    {"type": "ROUGHNESS"}, True)
            if wm.pond_bake_metal:
                img = _bake_input(context, base, mats, "金属度", "Metallic",
                                  size, margin)
                if img is None:
                    self.report({"WARNING"}, "材质里没有原理化BSDF，金属度图跳过")
                else:
                    images["metal"] = img
            if wm.pond_bake_alpha:
                img = _bake_input(context, base, mats, "透明度", "Alpha",
                                  size, margin)
                if img is None:
                    self.report({"WARNING"}, "材质里没有原理化BSDF，透明度图跳过")
                else:
                    images["alpha"] = img
            if wm.pond_bake_normal:
                # 凹凸单独烘时,法线烘焙先把原凹凸节点静音,不然凹凸会被烘进法线图再叠一遍
                muted = []
                if wm.pond_bake_bump:
                    for mat in mats:
                        for n in mat.node_tree.nodes:
                            if n.type == "BUMP" and not n.mute:
                                n.mute = True
                                muted.append(n)
                try:
                    images["normal"] = _bake_one(
                        context, base, mats, "法线", size, margin,
                        {"type": "NORMAL"}, True)
                finally:
                    for n in muted:
                        n.mute = False
            if wm.pond_bake_bump:
                img, st, di = _bake_bump(context, base, mats, size, margin)
                if img is None:
                    self.report({"WARNING"}, "材质里没有接了线的凹凸节点，凹凸图跳过")
                else:
                    images["bump"] = img
                    bump_params = (st, di)
            if wm.pond_bake_emit:
                images["emit"] = _bake_one(
                    context, base, mats, "自发光", size, margin,
                    {"type": "EMIT"}, False)
            if wm.pond_bake_ao:
                # AO要采样光线,1采样全是噪点,临时提到64
                scene.cycles.samples = 64
                try:
                    images["ao"] = _bake_one(
                        context, base, mats, "AO", size, margin,
                        {"type": "AO"}, True)
                finally:
                    scene.cycles.samples = 1
        except RuntimeError as e:
            self.report({"ERROR"}, f"烘焙失败: {str(e)[:120]}")
            return {"CANCELLED"}
        finally:
            scene.cycles.samples = prev_samples
            try:
                scene.render.engine = prev_engine
            except TypeError:
                pass
        if not images:
            self.report({"WARNING"}, "一个通道都没勾，啥也没烘")
            return {"CANCELLED"}
        mat = _build_baked_mat(base, images, uv_name, bump_params)
        for o in objs:
            o["pond_bake_orig"] = json.dumps(
                [s.material.name if s.material else "" for s in o.material_slots],
                ensure_ascii=False)
            o["pond_bake_mat"] = mat.name
        tip = "合烘 %d 件·" % len(objs) if multi else ""
        self.report({"INFO"},
                    tip + "烘好 %d 张 → textures/（原材质没动,想看效果点「切到烘焙材质」）"
                    % len(images))
        return {"FINISHED"}


def _baked_mat_for(obj):
    name = obj.get("pond_bake_mat") or f"烘焙材质_{obj.name}"
    return bpy.data.materials.get(name)


def _targets(context):
    """选中的网格们(活动物体保底)"""
    objs = [o for o in context.selected_objects if o.type == "MESH"]
    act = _active_mesh(context)
    if act and act not in objs:
        objs.insert(0, act)
    return objs


class POND_OT_bakemap_use_baked(bpy.types.Operator):
    """把选中物体换上烘焙出来的贴图材质（原材质记着，随时切回）"""
    bl_idname = "pond.bakemap_use_baked"
    bl_label = "切到烘焙材质"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(_baked_mat_for(o) for o in _targets(context))

    def execute(self, context):
        n = 0
        for obj in _targets(context):
            mat = _baked_mat_for(obj)
            if mat is None:
                continue
            if "pond_bake_orig" not in obj:
                obj["pond_bake_orig"] = json.dumps(
                    [s.material.name if s.material else ""
                     for s in obj.material_slots],
                    ensure_ascii=False)
            obj.data.materials.clear()
            obj.data.materials.append(mat)
            n += 1
        if n > 1:
            self.report({"INFO"}, f"{n} 件换上烘焙材质")
        return {"FINISHED"}


class POND_OT_bakemap_use_orig(bpy.types.Operator):
    """切回烘焙前的原材质"""
    bl_idname = "pond.bakemap_use_orig"
    bl_label = "切回原材质"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any("pond_bake_orig" in o for o in _targets(context))

    def execute(self, context):
        done = 0
        for obj in _targets(context):
            if "pond_bake_orig" not in obj:
                continue
            try:
                names = json.loads(obj["pond_bake_orig"])
            except Exception:
                self.report({"WARNING"}, f"{obj.name} 的原材质记录坏了，跳过")
                continue
            obj.data.materials.clear()
            for nm in names:
                obj.data.materials.append(bpy.data.materials.get(nm) if nm else None)
            done += 1
        self.report({"INFO"}, f"{done} 件切回原材质")
        return {"FINISHED"}


_classes = (
    POND_OT_bakemap,
    POND_OT_bakemap_use_baked,
    POND_OT_bakemap_use_orig,
)


def register():
    bpy.types.WindowManager.pond_bake_res = bpy.props.EnumProperty(
        name="分辨率", items=RES_ITEMS, default="2048")
    bpy.types.WindowManager.pond_bake_margin = bpy.props.IntProperty(
        name="扩边", default=16, min=2, max=64)
    bpy.types.WindowManager.pond_bake_color = bpy.props.BoolProperty(
        name="基础色", default=True)
    bpy.types.WindowManager.pond_bake_rough = bpy.props.BoolProperty(
        name="糙度", default=True)
    bpy.types.WindowManager.pond_bake_normal = bpy.props.BoolProperty(
        name="法线", default=False)
    bpy.types.WindowManager.pond_bake_metal = bpy.props.BoolProperty(
        name="金属度", default=False,
        description="把接进原理化BSDF金属度口的信号烘成一张图，"
                    "没接线的材质烘它的常数值")
    bpy.types.WindowManager.pond_bake_alpha = bpy.props.BoolProperty(
        name="透明度", default=False,
        description="把接进原理化BSDF透明度(Alpha)口的信号烘成一张图，"
                    "没接线的材质烘它的常数值；烘焙材质会自动开透明混合")
    bpy.types.WindowManager.pond_bake_emit = bpy.props.BoolProperty(
        name="自发光", default=False,
        description="把材质的自发光烘成一张图，烘焙材质里接进自发光颜色口"
                    "（注意：发光强度超过1的部分存PNG会被压到1）")
    bpy.types.WindowManager.pond_bake_ao = bpy.props.BoolProperty(
        name="AO", default=False,
        description="烘环境光遮蔽图（临时提到64采样，比别的通道慢一点）。"
                    "烘焙材质里自动乘进基础色当结构阴影")
    bpy.types.WindowManager.pond_bake_uvmode = bpy.props.EnumProperty(
        name="排UV", default="KEEP",
        items=[("KEEP", "用原UV",
                "直接用现有UV做烘焙落点——适合几件共用同一套UV、"
                "或已手动排好互不重叠的情况；多选且UV重叠的话后烘的会盖掉先烘的"),
               ("PACK", "打包原孤岛",
                "新建「烘焙UV」层，孤岛和接缝原样保留，"
                "只把所有物体的孤岛重新排进同一张图——已展好UV的模型合烘用这个"),
               ("SMART", "智能展开",
                "新建「烘焙UV」层按面朝向重新切岛合排——"
                "只适合没展过UV的硬表面，角色类会切得很碎")])
    bpy.types.WindowManager.pond_bake_bump = bpy.props.BoolProperty(
        name="凹凸", default=False,
        description="把接进凹凸节点的高度信号单独烘成一张图，"
                    "烘焙材质里用凹凸节点读图还原（跟法线可以同时勾，会自动串接不叠加）")
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.pond_bake_uvmode
    del bpy.types.WindowManager.pond_bake_ao
    del bpy.types.WindowManager.pond_bake_emit
    del bpy.types.WindowManager.pond_bake_alpha
    del bpy.types.WindowManager.pond_bake_metal
    del bpy.types.WindowManager.pond_bake_bump
    del bpy.types.WindowManager.pond_bake_normal
    del bpy.types.WindowManager.pond_bake_rough
    del bpy.types.WindowManager.pond_bake_color
    del bpy.types.WindowManager.pond_bake_margin
    del bpy.types.WindowManager.pond_bake_res
