"""工程分析：结果模型与评级定义
仅定义数据结构与常量，不含任何 Blender 注册逻辑。
"""
import bpy  # type: ignore

# ---- 影响程度 ----
IMPACT_SEVERE = "严重"
IMPACT_HIGH = "较高"
IMPACT_MED = "一般"
IMPACT_LOW = "轻微"

# ---- 操作便捷性 ----
EASE_ONE = "一键"
EASE_HALF = "半自动"
EASE_HARD = "复杂"

# ---- 类别 ----
CATEGORY_STRUCTURE = "场景结构"
CATEGORY_TRANSFORM = "变换"
CATEGORY_RENDER = "渲染设置"
CATEGORY_EEVEE = "EEVEE 专项"
CATEGORY_MATERIAL = "材质 / 贴图"
CATEGORY_DATA = "数据块"
CATEGORY_VISIBILITY = "视口 / 可见性"
CATEGORY_OTHER = "其它"

# 排序基准
_IMPACT_ORDER = {IMPACT_SEVERE: 0, IMPACT_HIGH: 1, IMPACT_MED: 2, IMPACT_LOW: 3}
_EASE_ORDER = {EASE_ONE: 0, EASE_HALF: 1, EASE_HARD: 2}


class Finding:
    """一条检测结果。

    key        稳定标识（用于 ✓/× 标记与展开定位），如 "TRANS.negative_scale"
    title      列表行标题
    count      涉及数量（0 表示无数量概念，如纯设置类）
    impact     影响程度
    ease       操作便捷性
    detail     问题详情（展开后显示）
    suggestion 处理手段（展开后显示，按当前版本给出可操作的选项）
    category   类别
    obj_names  可定位对象的名称列表（用于「选中相关对象」，可为空）
    """
    def __init__(self, key, title, count, impact, ease, detail,
                 suggestion, category, obj_names=None):
        self.key = key
        self.title = title
        self.count = count
        self.impact = impact
        self.ease = ease
        self.detail = detail
        self.suggestion = suggestion
        self.category = category
        self.obj_names = obj_names or []


def sort_results(results):
    """按 影响程度 → 便捷性 排序（易修的快修，排前面）"""
    return sorted(
        results,
        key=lambda f: (_IMPACT_ORDER.get(f.impact, 9), _EASE_ORDER.get(f.ease, 9)),
    )


# 最近一次扫描的缓存（面板只读缓存，不重扫）
LAST_RESULTS = []
LAST_MODE = "QUICK"
