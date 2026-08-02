# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **详细约定与注意事项见 [AGENTS.md](AGENTS.md)**（同样会被 AI 代理读取）。本文只记录跨文件才能看出的结构与日常操作要点，不重复 AGENTS.md 内容。

> ⚠️ **本插件仅支持 Blender 5.2**：全项目 `bpy.app.version` 版本判断已注释并锁定 5.2 分支，`bl_info` 最低版本已改为 `(5, 2, 0)`；其它 Blender 版本不再支持。

## 这是什么

Blender 插件 **Bekkan_visn**（作者 Kimi & visnz，GPL v3）：IPR 渲染快照对比工具 + 3D 视图「别馆」N 面板小工具箱（上下级操作、摄像机组、Wiggle 动画、渲染预设、贴图索引），并内嵌了说旧的第三方插件「颈椎拯救者」（AddonManager）。

**没有构建系统、没有 lint、没有 CI、没有自动化测试**。只依赖 Blender 内置 `bpy`/`gpu` API，无第三方 Python 依赖。工作目录就在 Blender 安装目录的 `scripts/addons_core/` 内，改动即生效。

## 开发与验证命令

所有验证都在 Blender 运行时内手动进行：

- **重载插件**：Blender 中按 `F8`；完全重载 = 偏好设置 → 插件 → 取消勾选再勾选 `Bekkan_visn`；注册状态残留就重启 Blender。
- **后台诊断脚本**（检查当前 Blender 版本的渲染 API 属性，新增/修改渲染同步功能前先跑）：
  ```bash
  blender --background --python "tools/check_render_attrs.py"
  ```
- **后台冒烟测试**（`tools/` 下以 `test_` 前缀的脚本，退出码 0 = 通过）：
  ```bash
  blender --background --python "tools/test_anim_migrate.py"   # P2E 动画迁移
  blender --background --python "tools/test_addon_manager_load.py"  # AddonManager 注册
  blender --background --python "tools/test_analyzer.py"   # 工程分析（构造全检查项 + 操作符）
  ```
- **单文件调试**：在 Blender 文本编辑器打开模块 → `Alt+P`（每个模块底部有 `if __name__ == "__main__": register()`）。

## 架构（需要读多个文件才能看到的部分）

- 入口 [__init__.py](__init__.py) 定义 `bl_info`；`register()` 按 **Snapshot → STOOL** 顺序无条件注册全部模块（无偏好设置开关），`unregister()` 逆序。新增模块：`register()` 末尾追加、`unregister()` 开头追加。
- [Snapshot.py](Snapshot.py) 是 IPR 快照：`GPUOffScreen.draw_view3d` 离屏重画到显存纹理 + GPU shader 叠加 A/B 对比（快照在线右侧、比例滑块 0-100 默认 50）。模块级 `IS_BLENDER5`/`_DRAW_DECODE_SRGB` 版本判断已注释并锁定 `True`（仅支持 5.2），旧版 GLSL 分支保留但不再执行。**三类崩溃硬教训**来自旧版「截图 + 隐藏面板」方案，已废弃、仅存档（详见 AGENTS.md）。
- [STOOL.py](STOOL.py) 是小工具箱的注册中心：`allClass` 列表统一注册全部 Operator/Panel/PropertyGroup，并向 `bpy.types.Scene` 挂两个 PointerProperty（`render_preset_settings`、`texture_search_props`，注销时删除）。**新增任何类必须同步加入 `allClass`**。UI 是 5 个面板类（继承 `BekkanPanelBase`，`bl_category = '别馆'`），注册顺序即侧边栏排列顺序，面板 `bl_label` 用 emoji 作前缀区分。
- [STOOL_part/](STOOL_part/) 按功能拆模块（`ParentsOps`/`StageOps`/`AnimeOps`/`RenderOps`/`TextureOps`），其 `__init__.py` 为空文件，本身不注册，全部由 `STOOL.py` 导入并纳入 `allClass`。
- [STOOL_part/AddonManager/](STOOL_part/AddonManager/) 是内嵌的独立插件「颈椎拯救者」（自带头部 `register()`/`unregister()`），由 `STOOL.py` 在 `allClass` 注册后/注销前调用，使其面板排在最下方；它会在 `register()` 时用 timer 延迟扫描/隐藏其他插件的面板。
- [STOOL_part/Analyzer/](STOOL_part/Analyzer/) 是「📋 工程分析」独立包（同 AddonManager，**自管注册、不加入 `allClass`**），由 `STOOL.py` 在 `register()` 开头调用，使其面板排在快照之后；简单/深度两模式（深度 = 简单 + 批 2：缩放统计/合并候选/面密度与相机占用/非流形，`run_deep` 运行较慢），只读报告 + 内置表格（UIList）UI：影响程度以 ★ 星级展示（严重★★★/较高★★/一般★/轻微无），操作便捷性暂不展示但保留数据供后续排序，行首是循环开关（未标记→已完成→不再提醒→未标记，状态存 `scene.analyzer_props.states_json` 随 .blend 保存），「不再提醒」由 `ANALYZER_UL_finding.filter_items` 排到最下面；结果行同步进 `analyzer_props.findings` CollectionProperty 随 .blend 保存。仅支持 Blender 5.2（原 4.2+ 版本门槛已注释）、只关注 EEVEE Next/Cycles；`checks.py` 每个检查函数用 `getattr`/`hasattr` 防御，深度几何检查有对象数/面数上限防卡死。
- 不属于插件代码、勿在其中查找/编写逻辑：`tools/`（诊断与冒烟脚本）、`blender_dev_env/`、`__pycache__/`、根目录 `package-lock.json` 与 `proxychains.conf`。

## 关键约定（易踩坑，详见 AGENTS.md）

- Operator 的 `bl_idname` 统一带 `_visn` 后缀；注释/UI/bl_info 均用中文；`bpy` 导入处 `# type: ignore`。
- **动画 API**：Blender 4.4 起 Action 改分层（slotted），5.0 移除 `action.fcurves`。仅支持 5.2，直接用 `action.fcurve_ensure_for_datablock(...)`（原 4.4 版本分支已注释，参照 `STOOL_part/AnimeOps.py`）。
- **RNA 属性**：仅 5.2 仍需注意个别属性随小版本调整（如 Cycles `pixel_size` 已移除）；批量同步优先 RNA 反射遍历（参照 `RenderOps.py` 的 `_copy_rna_props`），不要硬编码属性名列表。
- **GPU 相关必须延迟初始化**（首次使用时才建 shader，参照 `Snapshot.get_shader()`），否则 Vulkan 后端/上下文未就绪时崩溃。
- 选择类 Operator 先判空（`if not context.selected_objects: ... return {'CANCELLED'}`）。
- 中文本地化下约束名等数据名会被翻译，按英文字符串查找会 KeyError——用索引或按类型查找。
