# 别馆模式 · 工程分析面板 + 内置表格（迁移自 Bekkan/STOOL_part/Analyzer/ui.py）
# 属性组与操作符在 core/analyzer/。
import bpy

from ...core.analyzer import model, state
from .prefs import module_enabled

# 影响程度 → 排序基准（严重在前）
_IMPACT_RANK = {model.IMPACT_SEVERE: 0, model.IMPACT_HIGH: 1,
                model.IMPACT_MED: 2, model.IMPACT_LOW: 3}
# 便捷性 → 排序基准（一键在前）
_EASE_RANK = {model.EASE_ONE: 0, model.EASE_HALF: 1, model.EASE_HARD: 2}
# 标记状态 → 行内开关图标
_MARK_ICON = {None: 'CHECKBOX_DEHLT', 'done': 'CHECKBOX_HLT', 'dismissed': 'CANCEL'}

_VALID_ICONS = None


def _valid_icon_set():
    """读取当前 Blender 的 UILayout.label 合法图标枚举；失败则空集合（全部回退 NONE）"""
    try:
        param = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon']
        return {item.identifier for item in param.enum_items}
    except Exception:
        return set()


def _icon(name):
    """跨版本防御：图标枚举随 Blender 版本增减（如 WARNING→STATUS_WARNING），
    无效图标会让 draw 抛 TypeError，这里回退 'NONE' 保底。"""
    global _VALID_ICONS
    if _VALID_ICONS is None:
        _VALID_ICONS = _valid_icon_set()
    return name if name in _VALID_ICONS else 'NONE'


def _mark_icon(st):
    return _icon(_MARK_ICON.get(st, 'CHECKBOX_DEHLT'))


def _wrap(text, width=36):
    """按字符宽度折行，优先在中文标点或空格处断开，避免切断单词；
    保留原始换行，并对每段分别折行。"""
    text = text or ""
    all_lines = []
    for para in text.split("\n"):
        while para:
            if len(para) <= width:
                all_lines.append(para)
                break
            chunk = para[:width]
            # 优先在靠右的标点/空格处断开，保留阅读节奏
            break_at = width
            for p in ('。', '；', '，', '、', '！', '？'):
                pos = chunk.rfind(p)
                if pos > width // 3:
                    break_at = pos + len(p)
                    break
            else:
                # 没有中文标点时，找空格
                pos = chunk.rfind(' ')
                if pos > width // 3:
                    break_at = pos + 1
            all_lines.append(para[:break_at])
            para = para[break_at:]
    return all_lines or [""]


class ANALYZER_UL_finding(bpy.types.UIList):
    """内置表格：行内开关 + 标题 + 数量。
    「不再提醒」的条目始终排序到最下面。"""

    bl_idname = "ANALYZER_UL_finding"

    def filter_items(self, context, data, property):
        """排序：忽略项沉底，其余按当前 sort_by 排序。

        关闭 UIList 自带的字母/反向排序，避免覆盖自定义顺序。
        """
        if hasattr(self, "use_filter_sort_alpha"):
            self.use_filter_sort_alpha = False
        if hasattr(self, "use_filter_sort_reverse"):
            self.use_filter_sort_reverse = False

        items = getattr(data, property)
        n = len(items)
        states = state.get_states(context.scene)
        sort_by = data.sort_by

        def _key(i):
            f = items[i]
            dismissed = 1 if states.get(f.key) == 'dismissed' else 0
            if sort_by == 'EASE':
                return (dismissed, _EASE_RANK.get(f.ease, 9), _IMPACT_RANK.get(f.impact, 9), i)
            return (dismissed, _IMPACT_RANK.get(f.impact, 9), _EASE_RANK.get(f.ease, 9), i)

        order = sorted(range(n), key=_key)
        # flt_neworder 要求的是「原索引 -> 新位置」的反向映射，不是排好序的索引列表本身
        # ——直接把 order 传回去会让显示顺序整体错位（这正是"难易排序方向反了"的根因）。
        neworder = [0] * n
        for new_pos, orig_idx in enumerate(order):
            neworder[orig_idx] = new_pos
        return [self.bitflag_filter_item] * n, neworder

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index, flt_flag=0):
        if self.layout_type not in {'DEFAULT', 'COMPACT'}:
            return
        st = state.get_states(context.scene).get(item.key)

        row = layout.row(align=True)
        # 行内开关：未标记 → 已完成 → 不再提醒 → 未标记（循环）
        op = row.operator("analyzer.toggle_mark_visn", text="", emboss=False,
                          icon=_mark_icon(st))
        op.key = item.key

        # 标题容器（已完成的置灰；忽略项也置灰，但保留可操作）
        title_row = row.row()
        if st in ('done', 'dismissed'):
            title_row.active = False
        title_row.label(text=item.title)

        # 涉及数量靠右
        if item.count:
            row.label(text=f"×{item.count}")


class VIEW3D_PT_analyze_visn(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '别馆'
    bl_idname = "VIEW3D_PT_analyze_visn"
    bl_label = "📋 工程分析"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return module_enabled("show_analyzer")

    def draw(self, context):
        layout = self.layout
        props = context.scene.analyzer_props

        # 模式选择 + 运行 + 导出
        row = layout.row(align=True)
        row.prop(props, "mode", expand=True)
        run_row = layout.row(align=True)
        run_row.operator("analyzer.run_visn", icon='TRIA_RIGHT', text="运行分析")
        run_row.operator("analyzer.export_report_visn", text="", icon='EXPORT',
                         emboss=False)

        if not props.has_run:
            box = layout.box()
            box.label(text="尚未运行分析", icon='INFO')
            box.label(text="点击上方「运行分析」扫描当前工程", icon='TRIA_RIGHT')
            return

        findings = props.findings
        if not findings:
            layout.label(text="未发现问题 ✓", icon='CHECKMARK')
            return

        states = state.get_states(context.scene)
        done_n = sum(1 for f in findings if states.get(f.key) == 'done')
        dismissed_n = sum(1 for f in findings if states.get(f.key) == 'dismissed')
        active_n = len(findings) - done_n - dismissed_n

        # 排序按钮
        sort_row = layout.row(align=True)
        sort_row.label(text="排序：")
        sort_row.prop(props, "sort_by", expand=True)
        layout.separator()

        # 统计行 + 清除标记
        row = layout.row(align=True)
        row.label(text=f"{active_n} 待处理 · {done_n} 已完成 · {dismissed_n} 已忽略",
                  icon='FILE_TICK')
        if done_n or dismissed_n:
            row.operator("analyzer.clear_marks_visn", text="", icon='X', emboss=False)
        layout.separator()

        # 内置表格
        layout.template_list("ANALYZER_UL_finding", "",
                             props, "findings", props, "active_index", rows=6)

        # 选中项详情（默认折叠）
        idx = props.active_index
        if 0 <= idx < len(findings):
            row = layout.row(align=True)
            row.prop(props, "show_detail", toggle=True,
                     text="显示选中项详情", icon='DOWNARROW_HLT' if props.show_detail else 'RIGHTARROW')
            if props.show_detail:
                self._draw_detail(context, layout, findings[idx])
        layout.separator()

    def _draw_detail(self, context, layout, item):
        box = layout.box()
        head = box.row(align=True)
        head.label(text=item.title, icon='INFO')
        if item.count:
            head.label(text=f"× {item.count}")

        # 影响程度 / 操作难易 / 类别
        meta = box.row(align=True)
        meta.label(text=f"影响：{item.impact}")
        meta.label(text=f"难易：{item.ease}")
        if item.category:
            meta.label(text=f"类别：{item.category}")

        box.separator()
        detail_box = box.box()
        detail_box.label(text="问题详情：", icon='QUESTION')
        for line in _wrap(item.detail):
            detail_box.label(text=line)

        box.separator()
        sug_box = box.box()
        sug_box.label(text="处理手段：", icon='TOOL_SETTINGS')
        for line in _wrap(item.suggestion):
            sug_box.label(text=line)

        box.separator()
        fix_box = box.box()
        fix_box.label(text="快速修复：")
        self._draw_fix_buttons(context, fix_box, item)

        self._draw_locator_buttons(context, box, item)

    def _draw_locator_buttons(self, context, layout, item):
        """按建议类型决定「相关对象/集合」的定位方式，避免对超大集合直接全选卡死。

        「问题详情」里的名称是 UILayout.label 渲染的纯文本，Blender 的 N 面板里
        label 文本本身无法像文本编辑器那样框选复制（平台限制，插件无法绕过）；
        这里始终提供一个「复制名称到剪贴板」按钮作为变通方案，方便粘贴进大纲的
        搜索框按名字过滤查找。
        """
        if not item.obj_names:
            return
        names = [n for n in item.obj_names.split("\n") if n]
        if not names:
            return

        layout.separator()
        op = layout.operator("analyzer.copy_names_visn",
                             text=f"复制名称到剪贴板（{len(names)} 个）",
                             icon=_icon('COPYDOWN'))
        op.key = item.key

        if item.key in {"STRUCT.object_count", "MAT.big_textures", "MAT.images_per_material"}:
            # obj_names 在这些 key 下存的不是可安全选中的对象名（集合名/贴图名），
            # 或者材质类问题本身要处理的是材质而不是「使用该材质的对象」——
            # 选中对象对定位材质问题没有实际帮助，只保留复制名称按钮
            return

        op = layout.operator("analyzer.select_visn",
                             text=f"选中相关对象（{len(names)} 个）",
                             icon='RESTRICT_SELECT_OFF')
        op.key = item.key

    def _draw_fix_buttons(self, context, layout, item):
        if item.key == "TRANS.negative_scale":
            op = layout.operator("analyzer.fix_visn",
                                 text="应用缩放（修正负缩放）", icon='CHECKMARK')
            op.key = item.key
            op.option = "apply_scale"
        elif item.key == "MAT.big_textures":
            box = layout.column(align=True)
            engine = context.scene.render.engine
            if engine.endswith('CYCLES'):
                box.label(text="推荐：非破坏性钳制（视口+渲染纹理上限）：",
                          icon=_icon('INFO'))
                row = box.row(align=True)
                op = row.operator("analyzer.fix_visn", text="限制 4K", icon=_icon('IMAGE'))
                op.key = item.key
                op.option = "4096"
                op = row.operator("analyzer.fix_visn", text="限制 2K", icon=_icon('IMAGE'))
                op.key = item.key
                op.option = "2048"
                box.separator()
            # 破坏性缩小走统一的「贴图强制压缩」向导（EEVEE 没有钳制时唯一出路）
            box.label(text="直接压缩贴图数据（破坏性，含保存/覆盖确认）：",
                      icon=_icon('INFO'))
            box.operator("analyzer.downscale_textures_visn",
                         text="贴图强制压缩…", icon=_icon('IMAGE'))
        elif item.key == "MAT.normal_map_colorspace":
            op = layout.operator("analyzer.fix_visn",
                                 text="全部改成 Non-Color", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "GEOM.subdivision_high":
            box = layout.column(align=True)
            box.label(text="用「简化」总开关统一钳制全场景细分级数上限：")
            row = box.row(align=True)
            op = row.operator("analyzer.fix_visn", text="限制到 2 级", icon=_icon('MOD_SUBSURF'))
            op.key = item.key
            op.option = "2"
            op = row.operator("analyzer.fix_visn", text="限制到 1 级", icon=_icon('MOD_SUBSURF'))
            op.key = item.key
            op.option = "1"
            box.label(text="注：不修改各修改器自身级数，只设置运行时上限（视口+渲染同时生效）。",
                      icon='INFO')
        elif item.key == "VIS.viewport_only":
            row = layout.row(align=True)
            op = row.operator("analyzer.fix_visn", text="全部改为渲染可见", icon='RESTRICT_RENDER_OFF')
            op.key = item.key
            op.option = "render_visible"
            op = row.operator("analyzer.fix_visn", text="全部改为视图不可见", icon='RESTRICT_VIEW_ON')
            op.key = item.key
            op.option = "viewport_hidden"
        elif item.key in {"DATA.unused_materials", "DATA.orphans", "DATA.unused_actions"}:
            op = layout.operator("analyzer.fix_visn",
                                 text="清理未使用数据（Purge）", icon='TRASH')
            op.key = item.key
            op.option = "purge"
        elif item.key == "STRUCT.empty_objects":
            op = layout.operator("analyzer.fix_visn",
                                 text="删除无内容的空物体", icon='TRASH')
            op.key = item.key
        elif item.key == "STRUCT.orphan_objects":
            op = layout.operator("analyzer.fix_visn",
                                 text="移入「_未分类孤立对象」集合", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "RENDER.persistent_data":
            op = layout.operator("analyzer.fix_visn",
                                 text="开启保留数据（Persistent Data）", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "RENDER.motion_blur":
            op = layout.operator("analyzer.fix_visn",
                                 text="关闭运动模糊", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "EEVEE.shadows":
            op = layout.operator("analyzer.fix_visn",
                                 text="阴影池限制到 2048", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "RENDER.device":
            op = layout.operator("analyzer.fix_visn",
                                 text="切到 GPU 渲染", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "RENDER.bounces":
            op = layout.operator("analyzer.fix_visn",
                                 text="限制反弹/光追/焦散到建议值", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "RENDER.output_format":
            op = layout.operator("analyzer.fix_visn",
                                 text="按建议压缩输出格式", icon='CHECKMARK')
            op.key = item.key
        elif item.key == "RENDER.sampling":
            box = layout.column(align=True)
            engine = context.scene.render.engine
            if engine.endswith('CYCLES'):
                op = box.operator("analyzer.fix_visn",
                                  text="自动调整（视口 0.1 / 渲染 0.03）", icon='CHECKMARK')
                op.key = item.key
            else:
                box.label(text="EEVEE 采样数需按画面手动权衡，暂不自动修复", icon='ERROR')
        elif item.key == "RENDER.light_count":
            box = layout.column(align=True)
            engine = context.scene.render.engine
            if engine.endswith('CYCLES'):
                op = box.operator("analyzer.fix_visn",
                                  text="开启 Light Tree + 阴影剔除", icon='CHECKMARK')
                op.key = item.key
            else:
                box.label(text="该优化仅适用于 Cycles", icon='ERROR')
        elif item.key == "MAT.duplicate_materials":
            op = layout.operator("analyzer.fix_visn",
                                 text="合并重复材质（保留每组第一个）", icon='CHECKMARK')
            op.key = item.key
            op.option = "merge"
        elif item.key == "STRUCT.merge_same_material":
            op = layout.operator("analyzer.fix_visn",
                                 text="合并同材质对象（Ctrl+J）", icon=_icon('JOIN'))
            op.key = item.key
            op.option = "merge_objs"
        elif item.key == "STRUCT.identical_duplicates":
            op = layout.operator("analyzer.fix_visn",
                                 text="关联复制（共享网格数据）", icon='LINKED')
            op.key = item.key
            op.option = "link"
        else:
            layout.label(text="暂无可用的自动修复", icon='BLANK1')


_classes = (
    ANALYZER_UL_finding,    # 先于面板（template_list 按类名查找）
    VIEW3D_PT_analyze_visn,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
