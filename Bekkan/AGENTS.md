# AGENTS.md — Bekkan_visn

> 本文件面向 AI 编码代理，介绍项目结构、约定与注意事项。项目注释与文档以中文为主。

## 项目概述

> ⚠️ **仅支持 Blender 5.2**：全项目所有 `bpy.app.version` 版本判断代码已注释，直接锁定 5.2 分支；其它 Blender 版本不再支持（`bl_info` 已声明最低 `(5, 2, 0)`，旧版不会加载）。

这是一个 **Blender 插件（Addon）**，`bl_info` 名称为 `Bekkan_visn`，作者 Kimi & visnz，许可证 GPL v3（见 `LICENSE`）。**仅支持 Blender 5.2**；快照与动画功能的旧版分支（4.x 自定义 GLSL / 4.4 前 Action）已随版本判断一并注释、不再维护。

当前版本：1.3.0（`bl_info["version"]`）。

核心功能（功能详情见 `README.md`，以文字说明为主）：

1. **IPR 渲染快照**：对 3D 视图拍照并用 GPU 绘制叠加到窗口上做前后对比（类似 OctaneRender 的 store buffer）。`Ctrl+Alt+右键` 拍摄，`Alt+右键` 进视口拖动对比（左键确认）。捕获用 `GPUOffScreen.draw_view3d` 离屏重画到显存纹理（面板等 UI 天然不入镜），快照只存显存、会话级、不落盘、不随 .blend 保存；`📸 快照` 面板提供眼睛开关 / 拍摄 / 快照列表 / 对比比例滑块（0-100，默认 50）。
2. **小工具箱（STOOL）**：3D 视图 N 面板「别馆」页中的一组工具——上下级操作、摄像机组搭建、灯光约束、Wiggle 噪波动画、渲染预设（HD/Style/prev/demo）、贴图→材质引用索引与查找。

## 运行环境与构建

- **没有构建系统、没有 CI、没有依赖清单**。`package-lock.json` 是空壳（`"packages": {}`），项目与 Node.js 无关。`tools/` 下有少量后台冒烟测试（`test_*.py`），可在修改相关模块后运行，但不替代手动验证。
- 开发方式：把本目录作为 Blender 插件安装/软链接到 Blender 的 addons 目录，在 `编辑 - 偏好设置 - 插件` 中启用后交互式测试。当前工作目录位于 Blender 安装目录内（`.../Blender/5.2/scripts/addons_core/bekkan_visn`）。
- 代码只依赖 Blender 内置的 `bpy` / `gpu` API；无第三方 Python 依赖。`import bpy  # type: ignore` 是因为开发环境没有 bpy 类型存根。
- 每个模块都实现标准的 `register()` / `unregister()` 函数，并带 `if __name__ == "__main__": register()` 以便在 Blender 文本编辑器中单独运行调试。

## 代码结构与模块划分

入口 `__init__.py` 定义 `bl_info`，`register()` 中**无条件注册全部子模块**（无偏好设置开关，所有功能默认开启；注销按相反顺序）。

**注册顺序**（`__init__.py`）：`Snapshot` → `STOOL`
**注销顺序**（逆序）：`STOOL` → `Snapshot`
新增模块时在 `register()` 末尾追加、在 `unregister()` 开头追加。

| 模块 | 功能 |
|---|---|
| `Snapshot.py` | IPR 快照；`GPUOffScreen.draw_view3d` 离屏重画到显存纹理 + GPU shader 叠加 A/B 对比（快照在分割线右侧、比例滑块 0-100）；仅支持 5.2，`IS_BLENDER5`/`_DRAW_DECODE_SRGB` 的版本判断已注释并锁定 `True`，旧版 GLSL 分支保留但不再执行 |
| `STOOL.py` + `STOOL_part/` | 小工具箱面板 |
| `STOOL_part/Analyzer/` | 工程分析（只读报告：扫描 .blend 给出按影响程度/便捷性评级的优化建议；简单/深度两模式，✓/× 标记随 .blend 保存） |

注意：

- `Snapshot.py` 的版本常量 `IS_BLENDER5`、`_DRAW_DECODE_SRGB` 原为 `bpy.app.version` 判断，现仅支持 5.2 已注释并锁定 `True`；旧版 GLSL 分支代码保留但不再执行。shader 均延迟初始化（首次使用时创建）。**快照拍摄的三条硬教训来自旧版「截图 + 隐藏面板」方案**（5.2 实测 segfault 定位得出），已随离屏重画方案废弃，仅存档参考：
  1. op 返回时的 undo 推入会撤销 op 内对 `show_region_*` 的修改——隐藏面板须放独立 timer；
  2. 布局重排后旧 RNA 指针失效——禁止跨 timer 缓存 space/region 引用；
  3. 永不触碰 `show_region_hud`——5.2 下恢复它会 segfault。
- `STOOL.py` 是工具箱的注册中心：`allClass` 列表统一注册所有 Operator/Panel，并向 `bpy.types.Scene` 挂 `render_preset_settings` 和 `texture_search_props` 两个 PointerProperty。新增 Operator/Panel/PropertyGroup 类后必须同步加入 `allClass`，否则不会注册。注册顺序决定「别馆」页侧边栏排列：`STOOL.register()` 内先调用 `analyzer_register()`（工程分析），再循环注册 `allClass`（5 个主面板及对应 Operator/PropertyGroup），最后调用 `addonmanager_register()`（AddonManager 排在最下方）；`unregister()` 严格逆序。UI 按功能拆为 5 个面板类（均继承模块内的 `BekkanPanelBase`，`bl_category = '别馆'`），面板 `bl_label` 用 emoji 作前缀区分（如 `👪 上下级`）：
  - `VIEW3D_PT_parents_visn` — 上下级
  - `VIEW3D_PT_stage_visn` — 搭建类
  - `VIEW3D_PT_texture_visn` — 贴图索引
  - `VIEW3D_PT_anime_visn` — 动画类
  - `VIEW3D_PT_render_preset_visn` — 渲染预设
  - 另有 `Snapshot.py` 的 `SnapPanel`（快照，排在最上）、`Analyzer` 的 `VIEW3D_PT_analyze_visn`（工程分析，排在快照之后）和 `AddonManager` 的 `ADDONMANAGER_PT_main`（颈椎拯救者 by 说旧，排在最下），同属「别馆」页。
- `STOOL_part/` 按功能拆分（`STOOL_part/__init__.py` 为空文件）：
  - `ParentsOps.py` — 上下级操作（打组、单独打组、选择上级、释放到上级、拎出/拎出并删除、创建对焦物体、单选迁移动画：在锚点建上级空物体包裹并整体迁移物体动画到上级）
  - `StageOps.py` — 搭建类（C-P 摄像机组、C-SP-ZT 朝向摄像机组、中心约束灯光、打开工程文件夹、清理空物体）
  - `AnimeOps.py` — 动画类（Wiggle 噪波修改器动画、移除全部动画）
  - `RenderOps.py` — 渲染预设（创建 4 个预设、应用预设、从其他 Scene 同步渲染设置、打开输出文件夹 / 打开插件所在文件夹，支持绝对/相对路径切换）
  - `TextureOps.py` — 贴图索引与按贴图查找引用材质/选中相关对象
  - `AddonManager/` — 「颈椎拯救者 by 说旧」N 面板插件管理器，排在「别馆」页最下方；通过扫描、收藏、排除类别来管理其他插件面板的显示/隐藏
  - `Analyzer/` — 「📋 工程分析」**独立包（同 AddonManager，自管 register()/unregister()，不加入 allClass）**，由 `STOOL.py` 在 `register()` 开头调用注册，使其面板排在「别馆」页快照之后；简单 / 深度两模式：深度 = 简单 + 批 2（缩放统计、同材质合并、重复网格、高面数、相机占用、非流形），批 2 涉及 bmesh / 相机投影重计算、运行较慢，仅深度模式执行（`checks.run_deep` = `run_quick` + `_DEEP_CHECKS`）。**内置表格（UIList）UI**：影响程度以 ★ 星级展示（严重★★★/较高★★/一般★/轻微无），操作便捷性暂不展示但保留在数据里供后续排序用；每行行首是循环开关（未标记 → 已完成 → 不再提醒 → 未标记，状态存 `scene.analyzer_props.states_json` 随 .blend 保存），「不再提醒」的条目由 `ANALYZER_UL_finding.filter_items` 排序到最下面；点选行在下方显示问题详情 / 处理手段 / 选中相关对象（结果行数据同步进 `analyzer_props.findings` CollectionProperty，随 .blend 保存）。检测项仅针对 **Blender 4.2+**，只关注 EEVEE Next 与 Cycles；跨版本属性一律 `getattr`/`hasattr` 防御。**渲染类检查按当前引擎隔离**（`checks._engine(context)` 读 `scene.render.engine` 判断，EEVEE 场景不报 Cycles 专属项采样/反弹/设备/持久数据，反之亦然）——注意 `scene.cycles`/`scene.eevee` 是常驻 PointerProperty、**永不为 None**，判断引擎绝不能看这两个属性是否存在
- `blender_dev_env/` 是本地 Blender 运行时状态目录（`extensions/.cache/compat.dat`、`scripts/addons` 等），属于误提交的环境文件，不要在其中改代码。
- 仓库根目录的 `package-lock.json`（空壳、`"packages": {}`）与 `proxychains.conf`（代理配置，未被任何代码引用）同样**不是插件运行代码**，疑似误提交/环境文件，不要在其中编写或查找插件逻辑。`__pycache__/`、`blender_dev_env/` 同理，属运行时/环境产物，在其中改动无效。

## 代码约定

- 注释、UI 文本、`bl_info` 描述均用**中文**；新增代码沿用中文注释。
- Operator 的 `bl_idname` 普遍带 `_visn` 后缀（如 `object.parent_to_empty_visn`）；新 Operator 请保持 `_visn` 后缀以避免与其他插件冲突。
- 4 空格缩进；`bpy` 导入处习惯加 `# type: ignore`。
- 注册模式：模块级 `register()`/`unregister()`；多类模块用 `allClass` 列表循环注册，注销时同步删除挂在 `bpy.types.Scene` 上的 PointerProperty。
  - `STOOL.py` 向 Scene 挂载两个 PointerProperty：`render_preset_settings`（→ `RenderPresetSettings`）、`texture_search_props`（→ `TextureSearchProperties`），均在 `unregister()` 中删除。
  - `AnimeOps.py` 注册 `NoiseAnimSettings` PropertyGroup，同样需在注销时清理。
- GPU 相关代码必须**延迟初始化**（shader 在首次使用时创建，而非模块导入时），否则在 Blender 上下文未就绪或 Vulkan 后端下会崩溃——参见 `Snapshot.get_shader()` 的写法。
- 所有 UI 面板统一放在 N 面板的「别馆」页（`bl_category = '别馆'`），按钮尽量带图标。
- 动画 API：4.4 起 Action 改为分层（slotted）结构，5.0 已移除 `action.fcurves`。仅支持 5.2，直接用 `action.fcurve_ensure_for_datablock(datablock, data_path, index=...)`（自动创建 layer/strip/slot，原 4.4 版本判断已注释）——参见 `STOOL_part/AnimeOps.py`。
- 读取/写入 Blender RNA 属性时，必须做跨版本防御：用 `hasattr` 或 `try/except (AttributeError, TypeError)` 包裹，因为 4.0 ~ 5.x 间大量属性被移除、重命名或迁移到不同对象（如 `scene.view_settings` 在 Scene 上，`frame_start` 在 Scene 上，`pixel_size` 在 5.x Cycles 中已移除等）。批量同步类功能应优先使用 RNA 反射遍历（参见 `RenderOps.py` 的 `_copy_rna_props`），而非硬编码属性名列表。
- 选择类 Operator 必须先判空：`if not context.selected_objects: self.report({'WARNING'}, ...); return {'CANCELLED'}`，避免空选择时越界/除零。

## 测试说明

验证方式以手动为主：在 **Blender 5.2** 中启用插件（所有功能默认开启，无偏好设置开关）→ 在 3D 视图中实际操作确认。仅支持 5.2，无需跨版本验证。

另有少量后台冒烟测试（见「常用命令」），用于回归覆盖动画迁移、AddonManager 注册、工程分析检测项与面板图标合法性；退出码 0 = 通过。

## 常用命令

本项目无构建系统、无 lint，所有交互验证依赖 Blender 运行时；另有少量后台脚本用于诊断与冒烟回归。

- **重载插件**：在 Blender 中按 `F8`
- **完全重载插件**：偏好设置 → 插件 → 取消勾选再勾选 `Bekkan_visn`
- **重置注册状态**：重启 Blender
- **运行诊断脚本**（检查当前 Blender 版本的渲染 API 属性）：
  ```bash
  blender --background --python "tools/check_render_attrs.py"
  ```
- **诊断 ActionSlot API**（Blender 4.4+ / 5.x 的分层 Action 结构）：
  ```bash
  blender --background --python "tools/check_action_slot.py"
  ```
- **后台冒烟测试**（退出码 0 = 通过）：
  ```bash
  blender --background --python "tools/test_anim_migrate.py"          # P2E 动画迁移
  blender --background --python "tools/test_addon_manager_load.py"     # AddonManager 面板注册
  blender --background --python "tools/test_analyzer.py"               # 工程分析：检测项 + 操作符 + 面板图标合法性 mock
  ```
- **文本编辑器调试**：打开模块文件 → 按 `Alt+P` 运行（模块底部有 `if __name__ == "__main__": register()`）

## 开发工作流

没有自动构建/CI，主要验证靠手动；涉及相关模块时先跑对应后台冒烟测试。标准开发流程：

1. 编辑代码后，在 Blender 中按 `F8` 重新加载插件（或在偏好设置中禁用再启用）。
2. 若新增/修改了注册逻辑，建议重启 Blender 以清除残留的注册数据。
3. 可用 Blender 文本编辑器单独运行模块进行孤立调试（模块底部有 `if __name__ == "__main__": register()`）。
4. 仅支持 Blender 5.2，无需跨版本验证。

## 已知问题与注意事项

- 快照叠加为 5.2 色彩链路校准（离屏捕获 + sRGB 预解码画回）；Eevee 下需等采样完成再拍摄。
- `StageOps.py` / `RenderOps.py` 使用 `subprocess` + `platform` 做跨平台的"打开文件夹"操作，含 Windows 专属路径处理——修改时注意保持平台判断逻辑。
- 快照只存显存纹理（会话级），不落盘、不打包进 .blend；关闭 Blender 即清空。
- 中文界面下 Blender 会自动翻译约束名等数据名称，按英文名字符串查找（如 `constraints["Damped Track"]`）会 KeyError——用索引（`constraints[-1]`）或按类型查找。
- 采样数等引擎设置挂在 `scene.cycles` / `scene.eevee` 上，`scene.render`（RenderSettings）没有这些属性。
- 快照的句柄/图像清理统一走 `_free_res`/`_rm_handler`（吞 `ReferenceError`，防止 structRNA 失效报错）；`load_post` 时 `_reset_on_load` 清空全部快照记录，避免加载新文件后持有失效句柄。
- `tools/check_render_attrs.py` 用于诊断当前 Blender 版本的 `RenderSettings` / `CyclesRenderSettings` / `SceneEEVEE` 可用属性；`tools/check_action_slot.py` 用于诊断 `ActionSlot` API。新增/修改渲染设置同步类功能前可先运行前者，新增/修改动画曲线代码前可先运行后者。
- 修改模块的注册/注销逻辑时，务必同步检查 `__init__.py` 的 `register()`/`unregister()` 两处路径（注册与注销顺序相反）。
- README 中的「#3 pmatte 快速绑定」**仅为文档说明，并非插件代码实现**：它描述的是在合成器（Compositor）中手动将 PSR 绑定到面板的操作流程，并引用仓库外的 `example/pmatte example.blend` 资源（该 `example/` 目录不在本仓库内，也不随插件发布）。新增/查找代码时不要据此寻找 pmatte 相关模块——它不存在，本仓库所有功能即 AGENTS.md「核心功能」所列两项。
- README 中引用的 `src/img*.png` 截图资源未纳入本仓库（仅存在于作者本地），不影响代码运行，但无法在此工作目录中查看这些图片。
