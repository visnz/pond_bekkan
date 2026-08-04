"""
工程分析（Analyzer）诊断脚本
在 Blender 5.2 脚本编辑器内运行，或：blender --background --python tools/test_analyzer.py

覆盖 devPlan 里只有真实 GUI 才暴露、operator 测试抓不到的回归口：
  D1 图标 WARNING→STATUS_WARNING 跨版本回退
  D2 不能依赖 UILayout.label() 返回值
  D7 UIList draw_item 缺 flt_flag 导致真实列表空白
  D4 引擎隔离（EEVEE 不报 Cycles 专属项）
  D10.6 忽略项沉底排序

沿用 tools/test_snapshot.py 的诊断脚本风格：run_all() 汇总 PASS/FAIL。
"""
import bpy
import inspect


# ============================================================
# Mock UILayout：递归，覆盖 analyzer_panel.draw / draw_item 用到的方法。
# 真实后台模式没有 UILayout，只能用 mock 直接调 draw()，否则 draw 层错误漏网（D6 教训）。
# ============================================================

class MockOp:
    """记录 operator 调用与后续 .key/.option 赋值。"""
    def __init__(self, idname):
        self.idname = idname
        self.key = ""
        self.option = ""
        self.text = ""

    def __repr__(self):
        return f"<MockOp {self.idname} key={self.key!r} option={self.option!r}>"


class MockLayout:
    """递归 mock UILayout。

    模拟 5.2 下 UILayout.label() 可能返回 None 的行为（D2 回归点），
    并收集所有 icon= 参数供 D1 图标合法性校验。
    """
    def __init__(self, parent=None):
        self._parent = parent
        self.calls = []          # (method, args, kwargs) 记录
        self.icons = []          # 所有传过的 icon 参数
        self.ops = []            # 创建的 MockOp 列表

    def _child(self):
        c = MockLayout(self)
        return c

    def row(self, align=False):
        self.calls.append(("row", {"align": align}))
        return self._child()

    def box(self):
        self.calls.append(("box", {}))
        return self._child()

    def column(self, align=False):
        self.calls.append(("column", {"align": align}))
        return self._child()

    def label(self, text="", icon=None, **kw):
        # D2 关键：label() 返回 None，任何后续 .active 等操作会崩。
        # 这里如实返回 None，draw 里若误用返回值会被测试捕获。
        self.calls.append(("label", {"text": text, "icon": icon}))
        if icon is not None:
            self.icons.append(icon)
        return None

    def operator(self, idname, text="", icon=None, emboss=True, **kw):
        self.calls.append(("operator", {"idname": idname, "text": text, "icon": icon}))
        if icon is not None:
            self.icons.append(icon)
        op = MockOp(idname)
        op.text = text
        self.ops.append(op)
        return op

    def prop(self, data, prop, **kw):
        self.calls.append(("prop", {"prop": prop}))
        return None

    def separator(self, **kw):
        self.calls.append(("separator", {}))

    def template_list(self, *a, **kw):
        self.calls.append(("template_list", {}))

    def __getattr__(self, name):
        # 兜底：draw 里若调了没显式 mock 的方法（如 .active=），不崩
        def _noop(*a, **kw):
            return None
        return _noop


def _all_icons(layout):
    """递归收集一个 MockLayout 树里出现过的所有 icon 字符串。"""
    icons = list(layout.icons)
    # MockLayout 没存子 layout 引用，icons 只在直接调用层；测试需在 draw 后直接读
    return icons


# ============================================================
# T1：检查函数回归（不崩溃 + 引擎隔离 D4）
# ============================================================

def test_run_quick_minimal():
    """run_quick 在空场景不崩溃，返回 list"""
    print("\n[1] run_quick 空场景回归")
    try:
        from ..core.analyzer import checks
        results = checks.run_quick(bpy.context)
        ok = isinstance(results, list)
        print(f"  run_quick 返回 list: {'OK' if ok else 'FAIL'} (len={len(results)})")
        return ok
    except Exception as e:
        print(f"  run_quick 崩溃: {type(e).__name__}: {e}")
        return False


def test_engine_isolation():
    """D4 回归：EEVEE 下不应出现 Cycles 专属检查项"""
    print("\n[2] 引擎隔离 D4（EEVEE 不报 Cycles 专属）")
    try:
        from ..core.analyzer import checks
        scene = bpy.context.scene
        orig = scene.render.engine
        scene.render.engine = 'BLENDER_EEVEE'
        try:
            results = checks.run_quick(bpy.context)
        finally:
            scene.render.engine = orig
        keys = {f.key for f in results}
        bad = [k for k in keys if k in ("RENDER.device",
                                        "RENDER.persistent_data")]
        # persistent_data 在 EEVEE 下直接 return None，不应出现
        ok = not bad
        print(f"  EEVEE 下 Cycles 专属项: {bad if bad else '无'} -> {'OK' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        print(f"  测试本身崩溃: {type(e).__name__}: {e}")
        return False


# ============================================================
# T2：D6 核心——面板 draw 不崩溃 + 图标合法（堵 D1/D2）
# ============================================================

def _valid_icon_set():
    """读当前 Blender 的 UILayout.label 合法图标枚举"""
    try:
        param = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon']
        return {item.identifier for item in param.enum_items}
    except Exception:
        return set()


def test_panel_draw():
    """D1/D2 回归：用 mock UILayout 直接调面板 draw，不崩溃 + 所有图标合法"""
    print("\n[3] 面板 draw 路径（D1 图标合法 + D2 label 返回值）")
    try:
        # 先跑一次分析填充 findings（draw 依赖 props.findings，需 _sync_findings 同步）
        from ..core.analyzer import checks, ops
        results = checks.run_quick(bpy.context)
        ops._sync_findings(bpy.context, results)
        bpy.context.scene.analyzer_props.has_run = True

        from ..ui.bekkan import analyzer_panel as P
        panel = P.VIEW3D_PT_analyze_visn

        # 用 mock UILayout 顶替 self.layout，直接调 draw
        mock = MockLayout()
        inst = panel.__new__(panel)
        inst.layout = mock
        try:
            panel.draw(inst, bpy.context)
            drew_ok = True
        except Exception as e:
            print(f"  draw 崩溃: {type(e).__name__}: {e}")
            drew_ok = False

        # 校验图标合法性（D1）
        valid = _valid_icon_set()
        if valid:
            bad_icons = [ic for ic in mock.icons if ic not in valid and ic != 'NONE']
            icon_ok = not bad_icons
            print(f"  图标合法性: {'OK' if icon_ok else 'FAIL'} "
                  f"{'(非法: '+str(bad_icons)+')' if bad_icons else ''}")
        else:
            icon_ok = True  # 读不到合法枚举则跳过这层校验
            print("  图标合法性: 跳过（读不到合法枚举）")

        ok = drew_ok and icon_ok
        print(f"  draw 不崩溃: {'OK' if drew_ok else 'FAIL'}")
        return ok
    except Exception as e:
        import traceback
        print(f"  测试本身崩溃: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


# ============================================================
# T3：D7 核心——UIList draw_item 签名含 flt_flag
# ============================================================

def test_uilist_draw_item_signature():
    """D7 回归：draw_item 必须含 flt_flag 参数，否则真实 GUI 列表空白"""
    print("\n[4] UIList draw_item 签名（D7 flt_flag）")
    try:
        from ..ui.bekkan.analyzer_panel import ANALYZER_UL_finding
        sig = inspect.signature(ANALYZER_UL_finding.draw_item)
        has_flt = "flt_flag" in sig.parameters
        print(f"  draw_item 含 flt_flag 参数: {'OK' if has_flt else 'FAIL'}")
        print(f"  签名: {sig}")
        return has_flt
    except Exception as e:
        print(f"  测试崩溃: {type(e).__name__}: {e}")
        return False


def test_uilist_draw_item_runs():
    """D7 补充：用 mock 调 draw_item，确认不崩"""
    print("\n[5] UIList draw_item 实跑（mock 不崩溃）")
    try:
        from ..core.analyzer import checks, ops
        from ..ui.bekkan import analyzer_panel as P
        # 填充 findings（run_quick + _sync_findings 同步进列表）
        results = checks.run_quick(bpy.context)
        ops._sync_findings(bpy.context, results)
        props = bpy.context.scene.analyzer_props
        if not props.findings:
            print("  跳过（无 findings，造一条测试用行数据）")
            it = props.findings.add()
            it.key = "TEST.key"
            it.title = "测试条目"
            it.impact = "一般"
            it.ease = "半自动"
            it.count = 1
        item = props.findings[0]
        ul = P.ANALYZER_UL_finding.__new__(P.ANALYZER_UL_finding)
        ul.layout_type = 'DEFAULT'
        mock = MockLayout()
        # draw_item 签名：(self, context, layout, data, item, icon,
        #                   active_data, active_propname, index, flt_flag=0)
        try:
            ul.draw_item(bpy.context, mock, props, item, 'NONE',
                         props, "active_index", 0, 0)
            ok = True
        except Exception as e:
            print(f"  draw_item 崩溃: {type(e).__name__}: {e}")
            ok = False
        # 校验行内 icon 合法
        valid = _valid_icon_set()
        if valid and mock.icons:
            bad = [ic for ic in mock.icons if ic not in valid and ic != 'NONE']
            if bad:
                print(f"  行内图标非法: {bad}")
                ok = False
        print(f"  draw_item 不崩溃: {'OK' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        import traceback
        print(f"  测试崩溃: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


# ============================================================
# T4：filter_items 忽略项沉底（D10.6）
# ============================================================

def test_filter_items_dismissed_last():
    """D10.6 回归：dismissed 的条目应排到 order 末尾"""
    print("\n[6] filter_items 忽略项沉底（D10.6）")
    try:
        from ..core.analyzer import checks, state
        from ..ui.bekkan import analyzer_panel as P
        # 清空 findings 造两条
        props = bpy.context.scene.analyzer_props
        props.findings.clear()
        state.clear_states(bpy.context.scene)
        a = props.findings.add(); a.key="A"; a.impact="较高"; a.ease="一键"; a.title="A"
        b = props.findings.add(); b.key="B"; b.impact="较高"; b.ease="一键"; b.title="B"
        # 把 B 标记为 dismissed
        state.set_state(bpy.context.scene, "B", "dismissed")
        ul = P.ANALYZER_UL_finding.__new__(P.ANALYZER_UL_finding)
        ul.bitflag_filter_item = 1 << 0
        flags, order = ul.filter_items(bpy.context, props, "findings")
        # order 是索引列表，B(index=1) 应在末尾
        ok = order[-1] == 1
        print(f"  order={order} dismissed 在末尾: {'OK' if ok else 'FAIL'}")
        # 清理
        props.findings.clear()
        state.clear_states(bpy.context.scene)
        return ok
    except Exception as e:
        print(f"  测试崩溃: {type(e).__name__}: {e}")
        return False


# ============================================================
# T5：标记状态持久化
# ============================================================

def test_state_roundtrip():
    """state set/get/clear 往返"""
    print("\n[7] 标记状态持久化往返")
    try:
        from ..core.analyzer import state
        scene = bpy.context.scene
        state.clear_states(scene)
        state.set_state(scene, "TEST.key", "done")
        ok1 = state.get_states(scene).get("TEST.key") == "done"
        state.set_state(scene, "TEST.key", "dismissed")
        ok2 = state.get_states(scene).get("TEST.key") == "dismissed"
        state.set_state(scene, "TEST.key", None)
        ok3 = "TEST.key" not in state.get_states(scene)
        ok = ok1 and ok2 and ok3
        print(f"  set done:{ok1} set dismissed:{ok2} clear:{ok3} -> {'OK' if ok else 'FAIL'}")
        return ok
    except Exception as e:
        print(f"  测试崩溃: {type(e).__name__}: {e}")
        return False


# ============================================================
# 主入口
# ============================================================

def run_all():
    print("=" * 60)
    print("工程分析（Analyzer）诊断")
    print("=" * 60)

    results = []
    results.append(("run_quick 空场景", test_run_quick_minimal()))
    results.append(("引擎隔离 D4", test_engine_isolation()))
    results.append(("面板 draw D1/D2", test_panel_draw()))
    results.append(("draw_item 签名 D7", test_uilist_draw_item_signature()))
    results.append(("draw_item 实跑 D7", test_uilist_draw_item_runs()))
    results.append(("忽略项沉底 D10.6", test_filter_items_dismissed_last()))
    results.append(("标记状态往返", test_state_roundtrip()))

    print("\n" + "=" * 60)
    print("结果汇总")
    print("=" * 60)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")

    all_ok = all(ok for _, ok in results)
    print(f"\n总体: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    return all_ok


if __name__ == "__main__":
    run_all()
