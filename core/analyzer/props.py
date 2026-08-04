"""工程分析：属性组（FindingItem + AnalyzerProps）
合并自 Bekkan/STOOL_part/Analyzer/ui.py 的数据部分；UIList 与面板在 ui 层。
"""
import bpy  # type: ignore
from bpy.props import (EnumProperty, StringProperty, BoolProperty, IntProperty,
                       CollectionProperty)


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
            ('QUICK', "简单检查（几秒）", "快速扫描常用项（推荐先用这个）"),
            ('DEEP', "深度检查（几分钟）", "含几何 / 合并 / 缩放统计等重计算（较慢）"),
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
