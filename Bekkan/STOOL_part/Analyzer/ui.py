"""工程分析：面板 / 属性 / 内置表格
（AnalyzerProps + FindingItem + ANALYZER_UL_finding + VIEW3D_PT_analyze_visn）
"""
import bpy  # type: ignore
from bpy.props import (EnumProperty, StringProperty, BoolProperty, IntProperty,
                       CollectionProperty)

from . import model, state

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


class FindingItem(bpy.types.PropertyGroup):
    """列表行数据（每次运行后由分析结果同步而来，随 .blend 保存，
    会话恢复后不依赖模块级缓存也能直接渲染与选中）。"""
    key: StringProperty(name="建议标识")  # type: ignore
    title: StringProperty(name="标题")  # type: ignore
    impact: StringProperty(name="影响程度")  # type: ignore
    ease: StringProperty(name="操作便捷性")  # type: ignore
    category: StringProperty(name="类别")  # type: ignore
    count: IntProperty(name="涉及数量", default=0)  # type: ignore
    detail: StringProperty(name="问题详情", maxlen=4096)  # type: ignore
    suggestion: StringProperty(name="处理手段", maxlen=4096)  # type: ignore
    obj_names: StringProperty(name="相关对象", maxlen=16384)  # type: ignore


class AnalyzerProps(bpy.types.PropertyGroup):
    mode: EnumProperty(
        name="检查模式",
        items=[
            ('QUICK', "简单检查", "快速扫描常用项（推荐先用这个）"),
            ('DEEP', "深度检查", "含几何 / 合并 / 缩放统计等重计算（较慢）"),
        ],
        default='QUICK',
    )  # type: ignore
    has_run: BoolProperty(name="已运行", default=False)  # type: ignore
    findings: CollectionProperty(type=FindingItem)  # type: ignore
    active_index: IntProperty(name="选中项", default=0)  # type: ignore
    show_detail: BoolProperty(name="显示详情", default=False)  # type: ignore
    sort_by: EnumProperty(
        name="排序方式",
        items=[
            ('IMPACT', "影响程度", "按影响程度排序（严重在前）"),
            ('EASE', "操作难易", "按操作难易排序（一键在前）"),
        ],
        default='IMPACT',
    )  # type: ignore
    states_json: StringProperty(name="标记状态", default="")  # type: ignore


class ANALYZER_UL_finding(bpy.types.UIList):
    """内置表格：行内开关 + 标题 + 数量。
    「不再提醒」的条目始终排序到最下面。"""

    bl_idname = "ANALYZER_UL_finding"

    def filter_items(self, context, data, property):
        """排序：忽略项沉底，其余按当前 sort_by 排序。

        关闭 UIList 自带的字母/反向排序，避免覆盖自定义顺序。
        """
        # 禁用内置排序，确保「已忽略」沉底与 impact/ease 排序生效
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
        return [self.bitflag_filter_item] * n, order

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

    def draw(self, context):
        layout = self.layout
        props = context.scene.analyzer_props

        # 模式选择 + 运行
        row = layout.row(align=True)
        row.prop(props, "mode", expand=True)
        layout.operator("analyzer.run_visn", icon='TRIA_RIGHT', text="运行分析")

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
        box.label(text="问题详情：", icon='QUESTION')
        for line in _wrap(item.detail):
            box.label(text=line)

        box.separator()
        box.label(text="处理手段：", icon='TOOL_SETTINGS')
        for line in _wrap(item.suggestion):
            box.label(text=line)

        # 修复操作通道
        fix_box = box.box()
        fix_box.label(text="快速修复：")
        self._draw_fix_buttons(context, fix_box, item)

        if item.obj_names:
            box.separator()
            op = box.operator("analyzer.select_visn",
                              text=f"选中相关对象（{item.obj_names.count(chr(10)) + 1} 个）",
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
                box.label(text="Cycles 场景可设置视口纹理限制：")
                row = box.row(align=True)
                op = row.operator("analyzer.fix_visn", text="限制 4K", icon='IMAGE')
                op.key = item.key
                op.option = "4096"
                op = row.operator("analyzer.fix_visn", text="限制 2K", icon='IMAGE')
                op.key = item.key
                op.option = "2048"
                box.label(text="注：修改 scene.cycles.texture_limit，仅影响 Cycles 视口。",
                          icon='INFO')
            else:
                box.label(text="EEVEE 没有 scene.cycles.texture_limit，建议手动缩小图像尺寸。",
                          icon='ERROR')
        elif item.key == "MAT.texture_clamp":
            box = layout.column(align=True)
            row = box.row(align=True)
            op = row.operator("analyzer.fix_visn", text="限制 4K", icon='IMAGE')
            op.key = item.key
            op.option = "4096"
            op = row.operator("analyzer.fix_visn", text="限制 2K", icon='IMAGE')
            op.key = item.key
            op.option = "2048"
            box.label(text="设置 scene.cycles.texture_limit（仅 Cycles 有效）", icon='INFO')
        elif item.key == "VIS.viewport_only":
            row = layout.row(align=True)
            op = row.operator("analyzer.fix_visn", text="全部改为渲染可见", icon='RESTRICT_RENDER_OFF')
            op.key = item.key
            op.option = "render_visible"
            op = row.operator("analyzer.fix_visn", text="全部改为视图不可见", icon='RESTRICT_VIEW_ON')
            op.key = item.key
            op.option = "viewport_hidden"
        elif item.key in {"DATA.unused_materials", "DATA.orphans"}:
            op = layout.operator("analyzer.fix_visn",
                                 text="清理未使用数据（Purge）", icon='TRASH')
            op.key = item.key
            op.option = "purge"
        elif item.key == "MAT.duplicate_materials":
            op = layout.operator("analyzer.fix_visn",
                                 text="合并重复材质（保留每组第一个）", icon='CHECKMARK')
            op.key = item.key
            op.option = "merge"
        else:
            layout.label(text="暂无可用的自动修复", icon='BLANK1')
