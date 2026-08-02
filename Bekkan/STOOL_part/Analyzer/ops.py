"""工程分析：操作符（运行 / 选中 / 标记切换 / 清除 / 快速修复）"""
import bpy  # type: ignore
from bpy.props import StringProperty

from . import model, state, fixes
from .checks import run_quick, run_deep

# MIN_VERSION = (4, 2, 0)  # 仅支持 Blender 5.2，版本门槛已注释


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
        # 仅支持 Blender 5.2：4.2+ 版本门槛判断已注释
        # if bpy.app.version < MIN_VERSION:
        #     self.report({'ERROR'}, "工程分析仅支持 Blender 4.2 及以上版本")
        #     return {'CANCELLED'}
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
            else:
                self.report({'WARNING'}, "该条建议暂无自动修复")
                return {'CANCELLED'}
        except Exception as e:
            _log(f"修复 {self.key} 失败：{e}")
            self.report({'ERROR'}, f"修复失败：{e}")
            return {'CANCELLED'}
        return {'FINISHED'}
