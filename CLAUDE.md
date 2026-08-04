# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

PondBekkan（池塘 × 别馆）—— Blender 5.2 插件。**一套核心，两套界面**：
蛙灾的「池塘」（四抽屉 + 16 模块开关）与桶桶的「别馆」（快照 + 工程分析 + 工具箱）共用
`core/` 逻辑层，各自有 `ui/pond/` 与 `ui/bekkan/` 皮肤。**仓库根目录即插件包根目录**
（包名 = 文件夹名 = `pond_bekkan`），开发时把整个文件夹复制/链接进 `scripts/addons/` 即可。

**读这份之前必读 [AGENTS.md](AGENTS.md)** —— 架构总览、三版本构建、注册流程、代码约定、
**协作开发规则**（模块所有权与修改边界）全在那里。改代码前还要对照
`开发计划/合并对照清单.md`（决策记录、已知问题）。

## 常用命令

```bash
python build.py                      # 打包 dist/ 下四个 zip（合体/蛙灾/别馆/工程分析独立版）
python -m compileall -q .             # 静态自检（无 Blender 也能跑，只查语法）
blender --background --python tools/test_snapshot.py   # 快照回归（需 Blender）
blender --background --python tools/test_analyzer.py   # 工程分析回归（需 Blender）
```

- 热重载：Blender 里禁用/启用插件或 `F8`，根 [__init__.py](__init__.py) 会倒序 reload 全部子模块。
- GUI 实测清单见 AGENTS.md「开发工作流」末尾。
- `tools/check_render_attrs.py` 是 Blender 脚本编辑器内运行的诊断脚本（非 CLI）。

## 架构要点（读多文件才能拼出的全貌）

### 三层结构与分层纪律
- `core/` — **逻辑层**：Operator / PropertyGroup / 纯函数。**禁止出现 Panel/UIList**。
  蛙灾侧每个模块一文件（`core/bakemap.py` ↔ `ui/pond/panels/bakemap.py` 同名对应）。
- `ui/pond/` — 蛙灾皮肤：[prefs.py](ui/pond/prefs.py) 的 `MODULES` 是 16 模块开关的唯一来源，
  通过 `__annotations__` 动态挂载偏好字段；面板 `poll` 用 `module_enabled(key)` 查询。
- `ui/bekkan/` — 别馆皮肤：工具箱集中在 [panels.py](ui/bekkan/panels.py)，加
  `snapshot_panel.py` / `analyzer_panel.py` / `addonmanager_panel.py`。

### 注册顺序（[__init__.py](__init__.py)）
`register()` = `prefs.register()` → `core.register()` → `ui.register(mode)`；`unregister` 倒序。
- **core 常驻**：两模式下全部 op/props 都注册（含快照快捷键、`scene.analyzer_props` 持久化数据）。
  **唯一例外**：`core/addonmanager`（颈椎拯救者）**不在 core 注册表**，由
  [ui/bekkan/__init__.py](ui/bekkan/__init__.py) 随别馆模式注册/注销。
- **ui 按模式**：[ui/__init__.py](ui/__init__.py) 的 `register(mode)` 注销旧模式、注册新模式；
  合体版偏好切换走同一条 `apply_mode()` 路径。模式注销别馆 UI 时，
  `addonmanager_panel.unregister()` 会先把被移动的第三方面板恢复原类别——**切换顺序不能乱**。
- 初始模式：独立版锁死（`_build_mode.BUILD_MODE`），合体版读偏好（默认蛙灾）。

### 包名动态化（硬约束）
所有需要包名处一律用 `__package__.split(".")[0]`（见 [ui/pond/prefs.py](ui/pond/prefs.py)、
[core/addonmanager/prefs_access.py](core/addonmanager/prefs_access.py)）。独立版包名沿用
`Pond` / `bekkan_visn`，使旧偏好（模块开关、颈椎拯救者收藏）可直接继承。**禁止硬编码包名。**

### 三版本构建（[build.py](build.py)）
同一份源码打四个 zip，差异仅两处：`_build_mode.py` 内容、`bl_info` 的 name。
| 版本 | 包名 | BUILD_MODE | UI |
|---|---|---|---|
| 合体版 | `pond_bekkan` | combined | prefs 里有模式开关，默认蛙灾 |
| 蛙灾独立 | `Pond` | pond | 只有池塘 UI |
| 别馆独立 | `bekkan_visn` | bekkan | 只有别馆 UI |
| 工程分析独立 | `analyzer_tool` | analyzer | 只含 `core/analyzer` + 生成面板 |

**analyzer 独立版的特殊性**：面板 [ui/bekkan/analyzer_panel.py](ui/bekkan/analyzer_panel.py)
是唯一源，build.py 在打包 analyzer 变体时用 `_generate_analyzer_panel()` 做基于锚点的文本改写
（改 `bl_category`、删 `poll`、删 `module_enabled` import、`from ...core.analyzer`→`from ..core.analyzer`
修命名空间包 import 深度、删 `DEFAULT_CLOSED`）生成独立版面板写进 zip。
`build_assets/analyzer/` 只留 `__init__.py` + `prefs.py`，**没有面板副本**——改 UI 只动合并版一处。

## 工程分析（analyzer）模块地图

- `core/analyzer/` 在 [core/__init__.py](core/__init__.py) 的 `_MODULES` 里**常驻注册**
  （`scene.analyzer_props` 的标记数据随 .blend 保存，模式切换不能丢）。注意它的面板
  [ui/bekkan/analyzer_panel.py](ui/bekkan/analyzer_panel.py) 只随别馆模式注册。
- 架构：[model.py](core/analyzer/model.py) 数据结构/评级常量 →
  [state.py](core/analyzer/state.py) ✓/× 标记 JSON 持久化 →
  [checks.py](core/analyzer/checks.py) 25 简单检查 + 7 深度检查（`run_quick`/`run_deep`）→
  [fixes.py](core/analyzer/fixes.py) 快速修复 → [ops.py](core/analyzer/ops.py) 操作符 →
  [props.py](core/analyzer/props.py) PropertyGroup。
- 关键防御：判断渲染引擎**只看 `scene.render.engine`**（`checks._engine()`），
  不能看 `scene.cycles`/`scene.eevee` 是否存在（常驻 PointerProperty 永不为 None，见
  `开发计划/工程分析功能 devPlan.md` D4）。图标用前查合法枚举（[analyzer_panel.py](ui/bekkan/analyzer_panel.py) `_icon()`）。
- UIList `draw_item` 签名必须含 `flt_flag=0`，否则真实 GUI 列表为空（devPlan D7）。

## 开发约定（精要，详见 AGENTS.md）

- **idname 前缀**：Pond 系用 `pond.*`；Bekkan 系保留 `_visn` / `camera.*` / `analyzer.*` / `addonmanager.*` 等。
- **跨版本防御**：属性访问用 `getattr/hasattr`；GPU/惰性初始化资源放模块级 dict，
  `blender --background` 下 import 也必须安全（参考 [core/snapshot.py](core/snapshot.py) 文件头）。
- **忠实平移**：合并进来的模块保持原作者注释风格（蛙灾的口语化注释是项目文化，不要「润色」）。
  修 bug 走单独 PR，不混进结构调整。
- **每次开发必须留档**：在 `开发计划/` 下新增或追加 `YYYY-MM-DD_开发主题.md`，
  记录目标/改动/调试过程/测试结果/TODO。

## 协作规则（AI 必须遵守，详见 AGENTS.md §1-§2）

项目由蛙灾（Pond）与桶桶（Bekkan）共同维护。模块分三类：
- **Pond 专属**（`core/bakemap.py` 等 13 个 + `ui/pond/` 全部）——改前优先由蛙灾确认。
- **Bekkan 专属**（`core/anime.py`、`core/render_preset.py`、`core/texture.py`、
  `core/addonmanager/`、`core/analyzer/` + 对应 `ui/bekkan/` 面板）——改前优先由桶桶确认。
- **共同维护 Mixed**（`core/hierarchy.py`、`core/stage.py`、`core/snapshot.py`、`__init__.py`、
  `prefs.py`、`ui/__init__.py`、`ui/bekkan/__init__.py`）——任何改动必须先说明影响范围并获当前用户同意。

**改对方专属或共同模块前**：必须向当前用户说明（1）改哪个文件/函数（2）原归属
（3）理由（4）是否影响另一模式 UI/行为（5）是否需更新 `开发计划/模块归属标注.md` 共同维护清单。
**未获明确同意不得改对方专属模块。** 共同维护模块索引见 AGENTS.md §4。
