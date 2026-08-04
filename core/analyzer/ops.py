"""工程分析：操作符（运行 / 选中 / 标记切换 / 清除 / 快速修复）
（合并自 Bekkan/STOOL_part/Analyzer/ops.py，纯平移；仅支持 Blender 5.2，版本门槛已移除）
"""
import bpy  # type: ignore
from bpy.props import StringProperty

from . import model, state, fixes
from .checks import run_quick, run_deep


def _log(msg):
    print(f"[Analyzer] {msg}")


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


class ANALYZER_OT_run(bpy.types.Operator):
    bl_idname = "analyzer.run_visn"
    bl_label = "运行工程分析"
    bl_description = "扫描当前工程，生成优化建议清单"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.analyzer_props
        _log(f"运行分析，模式={props.mode}")
        if props.mode == 'DEEP':
            results = run_deep(context)   # 深度 = 简单 + 批 2（几何/合并/缩放统计）
        else:
            results = run_quick(context)
        model.LAST_RESULTS = results
        model.LAST_MODE = props.mode
        _sync_findings(context, results)
        props.has_run = True
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

        bpy.ops.object.select_all(action='DESELECT')
        vl = context.view_layer
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
            elif item.key in {"MAT.big_textures", "MAT.texture_clamp"}:
                max_size = int(self.option)
                fixed, skipped, info = fixes.fix_clamp_textures(context, item, max_size)
                if skipped and info.get("reason"):
                    self.report({'WARNING'}, info["reason"])
                    return {'CANCELLED'}
                self.report({'INFO'}, f"已设置 Cycles 视口纹理限制 {max_size}，跳过 {skipped} 项")
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
            elif item.key in {"DATA.unused_materials", "DATA.orphans"}:
                fixed, skipped, info = fixes.fix_purge_unused(context, item)
                if skipped:
                    self.report({'ERROR'}, "清理未使用数据失败")
                    return {'CANCELLED'}
                self.report({'INFO'}, "已清理未使用的数据块")
                # 清理后建议重新分析，数据已经变化
                bpy.ops.analyzer.run_visn()
            elif item.key == "MAT.duplicate_materials":
                fixed, skipped, info = fixes.fix_duplicate_materials(context, item)
                self.report({'INFO'}, f"已合并 {fixed} 个重复材质，跳过 {skipped} 个")
                if fixed:
                    bpy.ops.analyzer.run_visn()
            elif item.key == "STRUCT.merge_same_material":
                fixed, skipped, info = fixes.fix_merge_same_material(context, item)
                msg = f"已合并 {fixed} 个同材质对象，跳过 {skipped} 个"
                if info.get("made_single"):
                    msg += f"（其中 {info['made_single']} 个先复制为单用户）"
                self.report({'INFO'}, msg)
                if fixed:
                    bpy.ops.analyzer.run_visn()
            elif item.key == "STRUCT.identical_duplicates":
                fixed, skipped, info = fixes.fix_identical_duplicates(context, item)
                msg = f"已关联复制 {fixed} 个对象，跳过 {skipped} 个"
                if info.get("orphan_meshes"):
                    msg += f"（{info['orphan_meshes']} 个旧网格待 Purge 清理）"
                self.report({'INFO'}, msg)
                if fixed:
                    bpy.ops.analyzer.run_visn()
            else:
                self.report({'WARNING'}, "该条建议暂无自动修复")
                return {'CANCELLED'}
        except Exception as e:
            _log(f"修复 {self.key} 失败：{e}")
            self.report({'ERROR'}, f"修复失败：{e}")
            return {'CANCELLED'}
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
