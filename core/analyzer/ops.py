"""工程分析：操作符（运行 / 选中 / 标记切换 / 清除 / 快速修复）
（合并自 Bekkan/STOOL_part/Analyzer/ops.py，纯平移；仅支持 Blender 5.2，版本门槛已移除）
"""
import bpy  # type: ignore
from bpy.props import StringProperty, EnumProperty, IntProperty

from . import model, state, fixes
from .checks import run_quick, run_deep


def _log(msg):
    print(f"[Analyzer] {msg}")


def _tag_redraw_all(context):
    """强制刷新所有窗口的所有区域（做法同 core/addonmanager/common.py 的
    update_list_filter）。

    修复动作大多是直接对 scene.render/scene.cycles/scene.eevee 或对象可见性
    赋值，改动结果显示在属性编辑器的渲染/输出/对象标签页或大纲视图里——这些都
    不是按钮所在的 3D 视口 N 面板，Blender 不会自动重绘它们；不刷新的表现就是
    「明明改了但面板上看不出来，切一下别的标签页/引擎才更新」。
    """
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def _sync_findings(context, results):
    """把分析结果同步进列表集合（列表行数据随 .blend 保存）"""
    props = context.scene.analyzer_props
    props.findings.clear()
    for f in results:
        it = props.findings.add()
        it.key = f.key
        it.title = f.title
        it.impact = f.impact
        it.ease = f.ease
        it.category = f.category
        it.count = f.count
        it.detail = f.detail
        it.suggestion = f.suggestion
        it.obj_names = "\n".join(f.obj_names)
    props.active_index = 0
    _log(f"已同步 {len(results)} 条结果到列表")


def _rerun_analysis(context):
    """直接调用检查逻辑并同步结果，不经过 operator 层。

    ANALYZER_OT_fix 的部分修复分支（清理未使用数据/合并同材质等）修完数据后
    要刷新一遍建议列表；之前是嵌套调用 bpy.ops.analyzer.run_visn()——在一个
    还没执行完的、带 UNDO 的 operator 内部再触发另一个 operator（其内部还会
    强制刷一次 depsgraph），是 Ctrl+Z 反复撤销后容易把 undo 栈搞乱甚至崩溃的
    高风险写法，这里改成直接调函数，效果一样但不再嵌套 operator 调用。
    """
    props = context.scene.analyzer_props
    if props.mode == 'DEEP':
        results = run_deep(context)   # 深度 = 简单 + 批 2（几何/合并/缩放统计）
    else:
        results = run_quick(context)
    model.LAST_RESULTS = results
    model.LAST_MODE = props.mode
    _sync_findings(context, results)
    props.has_run = True
    return results


def _int_option(self, default):
    """从 self.option 安全读整数；空字符串 / 非数字回退默认值。

    MAT.big_textures / GEOM.subdivision_high 两个修复分支靠 option 传尺寸/级数，
    正常 GUI 按钮都会带 option，但防止某些入口（如重做面板手工调用）漏传时
    int('') 抛 ValueError 被外层 except 吞成「修复失败」。
    """
    try:
        return int(self.option) if self.option else default
    except (TypeError, ValueError):
        return default


class ANALYZER_OT_run(bpy.types.Operator):
    bl_idname = "analyzer.run_visn"
    bl_label = "运行工程分析"
    bl_description = "扫描当前工程，生成优化建议清单"
    bl_options = {'REGISTER'}

    def execute(self, context):
        _log(f"运行分析，模式={context.scene.analyzer_props.mode}")
        results = _rerun_analysis(context)
        self.report({'INFO'}, f"分析完成：共 {len(results)} 条建议")
        return {'FINISHED'}


class ANALYZER_OT_select(bpy.types.Operator):
    bl_idname = "analyzer.select_visn"
    bl_label = "选中相关对象"
    bl_description = "选中该建议涉及的对象"
    bl_options = {'REGISTER'}

    key: StringProperty(name="建议标识")  # type: ignore

    def execute(self, context):
        # 从列表集合读取（随 .blend 保存，不依赖本次会话的缓存）
        target = next((it for it in context.scene.analyzer_props.findings
                       if it.key == self.key), None)
        if target is None:
            self.report({'ERROR'}, "未找到对应建议，请重新运行分析")
            return {'CANCELLED'}
        names = [n for n in target.obj_names.split("\n") if n]
        if not names:
            self.report({'WARNING'}, "该建议没有可定位的对象")
            return {'CANCELLED'}
        found = [o for o in (bpy.data.objects.get(n) for n in names) if o is not None]
        if not found:
            self.report({'WARNING'}, "相关对象已不存在，请重新运行分析")
            return {'CANCELLED'}

        # 直接对视图层物体置 select=False，不调用 bpy.ops.object.select_all——
        # 该 operator 的 poll 要求处于 3D 视口上下文，从属性编辑器等其它区域触发
        # 会报 "context is incorrect" 直接抛异常，绕开 operator 层更稳妥。
        vl = context.view_layer
        for o in vl.objects:
            o.select_set(False)
        selected = 0
        active_obj = None
        for o in found:
            vl_obj = vl.objects.get(o.name)
            if vl_obj is None:
                continue
            vl_obj.select_set(True)
            selected += 1
            if active_obj is None:
                active_obj = vl_obj
        if selected == 0:
            self.report({'WARNING'}, "相关对象均不在当前视图层，无法选中")
            return {'CANCELLED'}
        vl.objects.active = active_obj
        self.report({'INFO'}, f"已选中 {selected}/{len(found)} 个对象")
        return {'FINISHED'}


class ANALYZER_OT_copy_names(bpy.types.Operator):
    bl_idname = "analyzer.copy_names_visn"
    bl_label = "复制名称到剪贴板"
    bl_description = "把该建议涉及的名称列表复制到系统剪贴板（可粘贴到大纲视图的搜索框里查找）"
    bl_options = {'REGISTER'}

    key: StringProperty(name="建议标识")  # type: ignore

    def execute(self, context):
        target = next((it for it in context.scene.analyzer_props.findings
                       if it.key == self.key), None)
        if target is None:
            self.report({'ERROR'}, "未找到对应建议，请重新运行分析")
            return {'CANCELLED'}
        names = [n for n in target.obj_names.split("\n") if n]
        if not names:
            self.report({'WARNING'}, "该建议没有可复制的名称")
            return {'CANCELLED'}
        context.window_manager.clipboard = "\n".join(names)
        self.report({'INFO'}, f"已复制 {len(names)} 个名称到剪贴板")
        return {'FINISHED'}


class ANALYZER_OT_toggle_mark(bpy.types.Operator):
    bl_idname = "analyzer.toggle_mark_visn"
    bl_label = "切换标记"
    bl_description = "循环切换：未标记 → 已完成 → 不再提醒 → 未标记（状态随 .blend 保存）"
    bl_options = {'REGISTER'}

    key: StringProperty(name="建议标识")  # type: ignore

    def execute(self, context):
        st = state.get_states(context.scene).get(self.key)
        if st == 'done':
            nxt = 'dismissed'
        elif st == 'dismissed':
            nxt = None
        else:
            nxt = 'done'
        state.set_state(context.scene, self.key, nxt)
        _log(f"标记 {self.key} -> {nxt}")
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()   # 让「不再提醒」立即重排到最下面
        return {'FINISHED'}


class ANALYZER_OT_clear_marks(bpy.types.Operator):
    bl_idname = "analyzer.clear_marks_visn"
    bl_label = "清除全部标记"
    bl_description = "清除所有「已完成 / 不再提醒」标记"
    bl_options = {'REGISTER'}

    def execute(self, context):
        state.clear_states(context.scene)
        _log("已清除全部标记")
        self.report({'INFO'}, "已清除全部标记")
        return {'FINISHED'}


class ANALYZER_OT_fix(bpy.types.Operator):
    bl_idname = "analyzer.fix_visn"
    bl_label = "快速修复"
    bl_description = "对该条建议执行自动修复（仅操作当前 View Layer 可访问的对象）"
    bl_options = {'REGISTER', 'UNDO'}

    key: StringProperty(name="建议标识")  # type: ignore
    option: StringProperty(name="修复选项", default="")  # type: ignore

    def execute(self, context):
        props = context.scene.analyzer_props
        item = next((it for it in props.findings if it.key == self.key), None)
        if item is None:
            self.report({'ERROR'}, "未找到对应建议，请重新运行分析")
            return {'CANCELLED'}

        _log(f"执行修复 key={self.key} option={self.option!r}")
        try:
            if item.key == "TRANS.negative_scale":
                fixed, skipped, info = fixes.fix_negative_scale(context, item)
                msg = f"已应用缩放 {fixed} 个，跳过 {skipped} 个"
                if info.get("made_single"):
                    msg += f"（其中 {info['made_single']} 个先复制为单用户）"
                self.report({'INFO'}, msg)
            elif item.key == "MAT.big_textures":
                max_size = _int_option(self, 2048)
                fixed, skipped, info = fixes.fix_clamp_textures(context, item, max_size)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'},
                           f"已设置 Cycles 视口+渲染纹理限制 {max_size} 并开启「简化」总开关"
                           f"（否则该限制不会生效），跳过 {skipped} 项")
            elif item.key == "MAT.normal_map_colorspace":
                fixed, skipped, info = fixes.fix_normal_map_colorspace(context, item)
                self.report({'INFO'}, f"已把 {fixed} 张贴图的色彩空间改成 Non-Color")
            elif item.key == "GEOM.subdivision_high":
                max_level = _int_option(self, 2)
                fixed, skipped, info = fixes.fix_cap_subdivision(context, item, max_level)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'},
                           f"已将「简化」细分级数上限设为 {max_level}（视口+渲染同时生效）")
            elif item.key == "VIS.viewport_only":
                if self.option == "render_visible":
                    fixed, skipped, _ = fixes.fix_viewport_to_render_visible(context, item)
                    self.report({'INFO'}, f"已设为渲染可见 {fixed} 个，跳过 {skipped} 个")
                elif self.option == "viewport_hidden":
                    fixed, skipped, _ = fixes.fix_viewport_to_hidden(context, item)
                    self.report({'INFO'}, f"已设为视图不可见 {fixed} 个，跳过 {skipped} 个")
                else:
                    self.report({'WARNING'}, "未知修复选项")
                    return {'CANCELLED'}
            elif item.key in {"DATA.unused_materials", "DATA.orphans", "DATA.unused_actions"}:
                fixed, skipped, info = fixes.fix_purge_unused(context, item)
                if skipped:
                    self.report({'ERROR'}, "清理未使用数据失败")
                    return {'CANCELLED'}
                self.report({'INFO'}, "已清理未使用的数据块")
                # 清理后建议重新分析，数据已经变化
                _rerun_analysis(context)
            elif item.key == "STRUCT.empty_objects":
                fixed, skipped, info = fixes.fix_empty_objects(context, item)
                self.report({'INFO'}, f"已删除 {fixed} 个无内容的空物体")
                if fixed:
                    _rerun_analysis(context)
            elif item.key == "STRUCT.orphan_objects":
                fixed, skipped, info = fixes.fix_link_orphans(context, item)
                self.report({'INFO'}, f"已移入专用集合 {fixed} 个，跳过 {skipped} 个")
                if fixed:
                    _rerun_analysis(context)
            elif item.key == "RENDER.persistent_data":
                fixed, skipped, info = fixes.fix_enable_persistent_data(context, item)
                if skipped:
                    self.report({'WARNING'}, "保留数据已是开启状态")
                    return {'CANCELLED'}
                self.report({'INFO'}, "已开启保留数据（Persistent Data）")
            elif item.key == "RENDER.motion_blur":
                fixed, skipped, info = fixes.fix_disable_motion_blur(context, item)
                self.report({'INFO'}, "已关闭运动模糊")
            elif item.key == "EEVEE.shadows":
                fixed, skipped, info = fixes.fix_shadow_pool(context, item)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'}, "已把阴影池限制到 2048")
            elif item.key == "RENDER.device":
                fixed, skipped, info = fixes.fix_device_gpu(context, item)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                backend = info.get("backend")
                msg = f"已把 Cycles 计算后端切到 {backend} 并将设备设为 GPU" if backend \
                    else "已把 Cycles 渲染设备切到 GPU"
                self.report({'INFO'}, msg)
            elif item.key == "RENDER.bounces":
                fixed, skipped, info = fixes.fix_cap_bounces(context, item)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'}, f"已调整 {fixed} 项反弹/光追/焦散设置")
            elif item.key == "RENDER.output_format":
                fixed, skipped, info = fixes.fix_output_compression(context, item)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'}, "已调整输出压缩设置")
            elif item.key == "RENDER.sampling":
                fixed, skipped, info = fixes.fix_adaptive_sampling(context, item)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'}, f"已调整 {fixed} 项采样设置")
            elif item.key == "RENDER.light_count":
                fixed, skipped, info = fixes.fix_light_perf_toggles(context, item)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'}, f"已开启 {fixed} 项灯光性能优化")
            elif item.key == "MAT.duplicate_materials":
                fixed, skipped, info = fixes.fix_duplicate_materials(context, item)
                self.report({'INFO'}, f"已合并 {fixed} 个重复材质，跳过 {skipped} 个")
                if fixed:
                    _rerun_analysis(context)
            elif item.key == "STRUCT.merge_same_material":
                fixed, skipped, info = fixes.fix_merge_same_material(context, item)
                msg = f"已合并 {fixed} 个同材质对象，跳过 {skipped} 个"
                if info.get("made_single"):
                    msg += f"（其中 {info['made_single']} 个先复制为单用户）"
                self.report({'INFO'}, msg)
                if fixed:
                    _rerun_analysis(context)
            elif item.key == "STRUCT.identical_duplicates":
                fixed, skipped, info = fixes.fix_identical_duplicates(context, item)
                msg = f"已关联复制 {fixed} 个对象，跳过 {skipped} 个"
                if info.get("orphan_meshes"):
                    msg += f"（{info['orphan_meshes']} 个旧网格待 Purge 清理）"
                self.report({'INFO'}, msg)
                if fixed:
                    _rerun_analysis(context)
            else:
                self.report({'WARNING'}, "该条建议暂无自动修复")
                return {'CANCELLED'}
        except Exception as e:
            _log(f"修复 {self.key} 失败：{e}")
            self.report({'ERROR'}, f"修复失败：{e}")
            return {'CANCELLED'}
        _tag_redraw_all(context)
        return {'FINISHED'}


class ANALYZER_OT_downscale(bpy.types.Operator):
    """贴图强制压缩：把大贴图数据等比缩小并打包进 .blend（EEVEE 也能用）。

    多步骤向导弹窗（灯光合成面板/工程分析共用同一入口）：
      0) 检测报告：N 张 >4K / M 张 >2K
      1) 保存提示（工程脏/未保存时）：先保存才能运行
      2) 选项：「覆盖原图 / 备份在文件旁边」+「钳制到 4K / 2K」（附耗时提示）
      3) 覆盖确认：不可逆，建议另存
    与 ANALYZER_OT_fix 独立，不依赖 findings 列表。
    """
    bl_idname = "analyzer.downscale_textures_visn"
    bl_label = "贴图强制压缩"
    bl_description = "把大贴图数据等比缩小并打包进 .blend（含保存/覆盖确认）"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="处理方式",
        items=[
            ('pack_keep', "备份在文件旁边",
             "缩小打包前把原图另存 PNG 到 .blend 旁（可恢复，推荐）"),
            ('pack_delete', "覆盖原图",
             "缩小打包后原地覆盖磁盘源文件为缩小后的版本（不可撤销）"),
        ],
        default='pack_keep',
    )  # type: ignore
    size: EnumProperty(
        name="目标尺寸",
        items=[
            ('4096', "钳制到 4K", "长边钳到 4096"),
            ('2048', "钳制到 2K", "长边钳到 2048"),
        ],
        default='2048',
    )  # type: ignore
    wizard_step: IntProperty(default=0)  # 0=检测 / 1=保存提示 / 2=选项 / 3=覆盖确认 / 99=执行

    def invoke(self, context, event):
        # 未保存到磁盘：脚本不负责选路径，直接报错中止（另存/覆盖都需要确定的目标文件夹）
        if not bpy.data.filepath:
            self.report({'ERROR'}, "工程尚未保存到磁盘，无法运行；请先保存 .blend 文件再运行。")
            return {'CANCELLED'}
        # 计数优先读场景缓存（后台预热已填）；失效才同步重扫一次
        props = context.scene.analyzer_props
        cached = fixes.get_downscale_report(props)
        if cached is None:
            self.n_gt4k, self.n_gt2k = fixes.count_big_textures()
            fixes.update_downscale_report(props, self.n_gt4k, self.n_gt2k)
        else:
            self.n_gt4k, self.n_gt2k = cached
        if self.n_gt4k + self.n_gt2k == 0:
            self.report({'INFO'}, "没有检测到大于 2K 的贴图，无需压缩。")
            return {'CANCELLED'}
        self.wizard_step = 0
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        if self.wizard_step == 0:
            layout.label(
                text=f"检测到 {self.n_gt4k} 张大于 4K 的贴图、"
                     f"{self.n_gt2k} 张大于 2K 的贴图。")
            layout.label(text="压缩会把这些大图等比缩小并嵌入 .blend。")
        elif self.wizard_step == 1:
            layout.label(text="需要保存文件之后才能运行，是否保存？")
        elif self.wizard_step == 2:
            layout.prop(self, "mode", expand=True)
            layout.prop(self, "size", expand=True)
            layout.label(text="转换过程可能需要几分钟，请耐心等待。", icon='INFO')
        elif self.wizard_step == 3:
            layout.label(text="覆盖原图不可逆：会用缩小后的版本原地覆盖磁盘源文件，无法用 Ctrl+Z 撤销。")
            layout.label(text="建议选「备份在文件旁边」；原图一旦被覆盖就找不回来了。")

    def execute(self, context):
        if self.wizard_step == 0:
            # 检测报告 → 保存检查（只有工程是脏的（带 *）才提示保存）
            self.wizard_step = 1 if bpy.data.is_dirty else 2
            return context.window_manager.invoke_props_dialog(self)
        if self.wizard_step == 1:
            # 保存提示 → 保存 → 选项
            try:
                bpy.ops.wm.save_mainfile()
            except Exception as e:
                self.report({'ERROR'}, f"保存工程失败：{e}")
                return {'CANCELLED'}
            self.wizard_step = 2
            return context.window_manager.invoke_props_dialog(self)
        if self.wizard_step == 2:
            if self.mode == 'pack_delete':
                self.wizard_step = 3
                return context.window_manager.invoke_props_dialog(self)
            self.wizard_step = 99
        elif self.wizard_step == 3:
            self.wizard_step = 99

        # ── 执行压缩 ──
        max_size = int(self.size)
        fixed, skipped, info = fixes.fix_downscale_textures(context, max_size, self.mode)
        if fixed == 0 and info.get("reason"):
            self.report({'WARNING'}, info["reason"])
            return {'CANCELLED'}
        # 尺寸变了：图片总数没变但计数已过时，置失效让后台预热/下次打开重扫
        context.scene.analyzer_props.downscale_total = -1
        tail = f"，已覆盖 {info['overwritten']} 个磁盘源文件" if info.get("overwritten") else ""
        if info.get("backup_dir"):
            tail += f"，备份于「{info['backup_dir']}」"
        self.report({'INFO'}, f"已压缩 {fixed} 张大图到长边 {max_size}，跳过 {skipped} 张{tail}")
        # 若工程分析已跑过，刷新建议列表（尺寸变了，大贴图条目可能消失）
        props = context.scene.analyzer_props
        if getattr(props, 'has_run', False):
            _rerun_analysis(context)
        return {'FINISHED'}


# ============================================================
# 报告导出
# ============================================================

def _build_markdown(context, props):
    """把当前分析结果渲染成 Markdown 文本。

    结构：标题 + 元信息（场景/时间/模式）+ 统计 + 按影响分组的 findings 清单。
    findings 已是 sort_results 后的顺序（影响→难易），按 impact 切分二级标题。
    标记状态：□ 待处理 / ✓ 已完成 / × 已忽略。
    """
    import time
    scene_path = bpy.data.filepath
    scene_name = bpy.path.basename(scene_path) if scene_path else "未保存场景"
    ts = time.strftime("%Y-%m-%d %H:%M")
    mode_label = "深度检查" if props.mode == 'DEEP' else "简单检查"
    states = state.get_states(context.scene)

    done_n = sum(1 for f in props.findings if states.get(f.key) == 'done')
    dismissed_n = sum(1 for f in props.findings if states.get(f.key) == 'dismissed')
    active_n = len(props.findings) - done_n - dismissed_n

    lines = [
        f"# 工程分析报告 — {scene_name}",
        "",
        f"- 生成时间：{ts}",
        f"- 检查模式：{mode_label}",
        f"- 共 {len(props.findings)} 条建议"
        f"（待处理 {active_n} · 已完成 {done_n} · 已忽略 {dismissed_n}）",
        "",
    ]

    cur_impact = None
    for f in props.findings:
        if f.impact != cur_impact:
            lines.append(f"\n## {f.impact}影响\n")
            cur_impact = f.impact
        st = states.get(f.key)
        mark = "✓" if st == 'done' else ("×" if st == 'dismissed' else "□")
        lines.append(f"### {mark} {f.title}")
        meta_bits = [f"`{f.key}`", f"数量 {f.count}", f"难易 {f.ease}"]
        if f.category:
            meta_bits.append(f"类别 {f.category}")
        lines.append(f"- {' · '.join(meta_bits)}")
        if f.detail:
            lines.append(f"- 详情：{f.detail}")
        if f.suggestion:
            lines.append(f"- 建议：{f.suggestion}")
        lines.append("")

    return "\n".join(lines)


class ANALYZER_OT_export_report(bpy.types.Operator):
    bl_idname = "analyzer.export_report_visn"
    bl_label = "导出分析报告"
    bl_description = "把当前分析结果导出为 Markdown 文件"
    bl_options = {'REGISTER'}

    filepath: StringProperty(  # type: ignore
        name="文件路径",
        subtype='FILE_PATH',
        description="导出的 .md 文件路径",
    )

    def execute(self, context):
        props = context.scene.analyzer_props
        if not props.has_run or not props.findings:
            self.report({'WARNING'}, "没有可导出的分析结果，请先运行分析")
            return {'CANCELLED'}
        path = self.filepath
        if not path:
            self.report({'WARNING'}, "未指定导出路径")
            return {'CANCELLED'}
        if not path.lower().endswith('.md'):
            path += '.md'
        try:
            md = _build_markdown(context, props)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(md)
        except Exception as e:
            self.report({'ERROR'}, f"导出失败：{e}")
            return {'CANCELLED'}
        _log(f"已导出报告 {len(props.findings)} 条到 {path}")
        self.report({'INFO'}, f"已导出 {len(props.findings)} 条到 {path}")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 弹文件保存对话框
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
