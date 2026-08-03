# AGENTS.md — PondBekkan 开发指南

面向维护者（人类或 AI）的架构与约定说明。修改代码前请先读
`开发计划/合并对照清单.md`（决策记录、模块处置、语义差异、已知问题）。

## 架构总览

**一套核心，两套界面。** 逻辑层与 UI 层严格分离。
**仓库根目录即插件包根目录**（包名 = 文件夹名 = `pond_bekkan`），
开发时把整个仓库文件夹复制/链接进 `scripts/addons/` 即可。

```
pond_bekkan/            # 仓库根 = 插件包根
├── __init__.py         # bl_info + 注册中心 + 热重载
├── _build_mode.py      # 构建标记：combined / pond / bekkan（build.py 改写）
├── prefs.py            # 唯一 AddonPreferences（详见下文「偏好设置」）
├── core/               # 逻辑层：Operator / PropertyGroup / 纯函数。**禁止出现 Panel/UIList**
│   ├── <module>.py     #   每个功能模块一个文件，自管 register()/unregister()
│   ├── analyzer/       #   工程分析子包（core 常驻注册）
│   └── addonmanager/   #   颈椎拯救者子包（只随别馆模式注册！）
└── ui/
    ├── __init__.py     # 模式分发：register(mode) / apply_mode(mode)
    ├── bekkan/         # 别馆 UI（category='别馆'）
    └── pond/           # 蛙灾 UI（category='池塘'，prefs.py 模块开关视图 +
                        #   sections.py 四抽屉 + panels/ 16 个子面板）
```

对应关系：`core/xxx.py` ↔ `ui/pond/panels/xxx.py`（同名）；别馆侧面板集中在
`ui/bekkan/panels.py`（工具箱）+ `snapshot_panel.py` + `analyzer_panel.py` +
`addonmanager_panel.py`。

## 注册流程

`__init__.register()`：`prefs.register()` → `core.register()` → `ui.register()`。

- **core 常驻**：两个模式下全部 op/props 都注册（含快照快捷键、`scene.analyzer_props`
  持久化数据）。**例外：`core/addonmanager` 不在 core 注册表**，它由
  `ui/bekkan/__init__.py` 随别馆模式注册/注销（决策点 3）。
- **ui 按模式**：`ui.register(mode)` 注销旧模式 UI、注册新模式 UI。
  合体版用户在偏好设置切换时走同一条 `apply_mode()` 路径。
- 模式注销别馆 UI 时，`addonmanager_panel.unregister()` 会先把被移动的
  第三方面板恢复原类别（`restore_panels(force=True)`）——**切换顺序不能乱**。

## 三版本构建

`build.py` 把同一份源码打成三个 zip，差异只有两处：`_build_mode.py` 的内容、
bl_info 的 name。

| 版本 | 包名（zip 根目录） | BUILD_MODE | UI |
|---|---|---|---|
| 合体版 | `pond_bekkan` | combined | prefs 里有模式开关，默认蛙灾 |
| 蛙灾独立版 | `Pond` | pond | 只有池塘 UI |
| 别馆独立版 | `bekkan_visn` | bekkan | 只有别馆 UI |

**包名动态化是本架构的硬约束**：所有需要包名的地方一律用
`__package__.split(".")[0]`（见 `ui/pond/prefs.py`、`core/addonmanager/prefs_access.py`、
`ui/bekkan/addonmanager_panel.py`）。独立版包名沿用 `Pond` / `bekkan_visn`，
使用户的旧偏好设置（模块开关、颈椎拯救者收藏）可以直接继承。**禁止再出现
硬编码包名**（原 `AddonManager/preferences.py` 的 `bl_idname="bekkan_visn"` 已被消灭）。

## 偏好设置（prefs.py）

一个插件包只能有一个 AddonPreferences。合并后的 `PondBekkanPreferences`
（`bl_idname = __package__`）包含三组字段：

1. `mode`：界面模式枚举（合体版显示；独立版字段闲置不画）
2. 蛙灾 16 个模块开关：名单唯一来源是 `ui/pond/prefs.py` 的 `MODULES`，
   通过 `__annotations__` 动态挂载；面板的 `poll` 用 `module_enabled(key)` 查询
3. 颈椎拯救者设置（收藏/排除类别/自动恢复等，原 AddonManager 偏好字段）

新增蛙灾模块时：在 `MODULES` 加一行 → 偏好自动出现开关 → 面板加
`poll = module_enabled("show_xxx")`。

## 代码约定

- **idname 前缀**：Pond 系 op 用 `pond.*`；Bekkan 系 op 保留原 `_visn` / `camera.*` /
  `wm.*` / `index.*` / `render.*` / `analyzer.*` / `addonmanager.*`。新增 op 按归属选前缀。
  已废弃 idname 仅 `object.select_parent_visn`（由 `pond.select_parents` 取代）。
- **分层纪律**：core 不 import ui；ui 可以 import core。蛙灾 core 模块**不再**
  `from . import prefs`（面板 poll 才关心开关，逻辑不关心）。
- **GPU/惰性初始化**：GPU 资源（offscreen/shader/handler）只放模块级 dict，
  首次用到时现建，`blender --background --python` 下 import 也必须安全
  （参考 `core/snapshot.py` 的文件头注释，含 5.2 色彩链路标定记录）。
- **跨版本防御**：属性访问用 `getattr/hasattr` 兜底；图标用前先查合法枚举
  （参考 `ui/bekkan/analyzer_panel.py` 的 `_icon()`）。目标版本只有 5.2，
  但防御性写法是两项目的共同传统，保留。
- **忠实平移**：合并进来的模块保持原实现与原作者的注释风格（蛙灾的口语化
  注释是她的项目文化，不要「润色」掉）。修 bug 走单独 PR，不混进结构调整。
- **快照交互**：当前统一 Bekkan 行为（快照在线左、Alt+右键拖）；Pond 的
  点线拖交互以注释形式保留在 `core/snapshot.py` 末尾（决策点 5），
  改动前先对照清单确认是否要做双模式双交互。

## 开发工作流

- 热重载：Blender 里禁用/启用插件或 F8，根 `__init__.py` 会倒序 reload 全部子模块。
- 打包：`python build.py` → `dist/` 三个 zip。
- 静态自检：`python -m compileall -q pond_bekkan`。
- 诊断脚本：`tools/check_render_attrs.py`（Blender 脚本编辑器内运行）。
- Blender 实测清单：合体版切换模式后两侧 UI 完整、快照拍/拖/清/导出、
  别馆侧颈椎拯救者移动面板后切走能恢复、独立版各自打开即是原 UI。

## 已知问题与 TODO

以 `开发计划/合并对照清单.md` 第 5 节为准（快照交互待议、四元数迁移、
窗口缩放跟随、预设库路径可配化等）。**合并重组阶段不修 bug**；
之后的修复请按清单逐条销号。

---

## 协作开发规则（AI 必须遵守）

> 本项目由「蛙灾（Pond）」与「桶桶（Bekkan）」共同维护。
> 原则是：**底层核心共用，顶层 UI 各自独立；能不碰对方模块就不碰，必须碰时先说明、获同意。**

### 1. 模块所有权与修改边界

- **Pond 专属**：`core/bakemap.py`、`core/c4d_bridge.py`、`core/lightdesk.py`、
  `core/lumen.py`、`core/organize.py`、`core/palette.py`、`core/preset_lib.py`、
  `core/renderlayers.py`、`core/sixproj.py`、`core/splitter.py`、
  `core/synccheck.py`、`core/trace2solid.py`、`core/version.py`，以及
  `ui/pond/` 下全部文件。**修改前原则上应优先由蛙灾确认。**
- **Bekkan 专属**：`core/anime.py`、`core/render_preset.py`、`core/texture.py`、
  `core/addonmanager/`、`core/analyzer/`，以及 `ui/bekkan/panels.py`、
  `ui/bekkan/analyzer_panel.py`、`ui/bekkan/addonmanager_panel.py`。
  **修改前原则上应优先由桶桶确认。**
- **共同维护（Mixed）**：`core/hierarchy.py`、`core/stage.py`、`core/snapshot.py`、
  `__init__.py`、`prefs.py`、`ui/__init__.py`、`ui/bekkan/__init__.py`。
  这些文件同时包含双方代码或已被重写为共同资产，**任何改动都必须在方案阶段讲清楚影响范围，并获得当前用户明确同意。**

### 2. AI 修改前必须做的方案说明

当 AI 计划修改**对方专属模块**或**共同维护模块**时，必须在动手前向当前用户说明：

1. 要改哪个文件/函数；
2. 这个模块原来的归属（Pond / Bekkan / Mixed）；
3. 修改理由；
4. 是否会影响另一模式的 UI 或行为；
5. 是否需要同步更新 `开发计划/模块归属标注.md` 中的共同维护清单。

**未获得当前用户明确同意前，不得直接修改对方专属模块。**

### 3. 每次开发必须留档

每次 AI vibecoding 后，必须在 `开发计划/` 下新增或追加开发日志，记录：

- 本次目标与范围；
- 修改了哪些文件/函数；
- 调试与试错过程；
- 测试结果；
- 未完成的 TODO。

日志命名建议：`开发计划/YYYY-MM-DD_开发主题.md`。
已有 `snapshot_debug_report.md` 即此类文档的示例。

### 4. 共同维护模块索引

以下模块为双方共用，修改后必须同步更新 `开发计划/模块归属标注.md` 中的「共同维护清单」：

| 文件 | 涉及双方内容 | 主要维护者 | 关键注意点 |
|---|---|---|---|
| `core/hierarchy.py` | Pond 6 op + Bekkan 7 op + 共享助手 | 蛙灾/桶桶共同 | Pond 侧 6 op 多数概念 fork 自 Bekkan，但实现已改（详见 `开发计划/模块归属标注.md`） |
| `core/stage.py` | Bekkan 摄像机组/开文件夹 + Pond 简洁机组 | 蛙灾/桶桶共同 | 中心约束灯光、C-P/C-SP-ZT 机组来自 Bekkan；Pond 侧 `POND_OT_cam_rig_build` 为独立实现 |
| `core/snapshot.py` | Bekkan 核心 + Pond 删除/导出/清理逻辑 | **桶桶** | 蛙灾已放权修改；改 GPU/交互前先读调试报告 |
| `__init__.py` | 注册中心 | 共同 | 注册顺序影响模式切换与面板恢复 |
| `prefs.py` | 唯一 AddonPreferences | 共同 | 同时影响模式开关、模块开关、颈椎拯救者设置 |
| `ui/__init__.py` | 模式分发 | 共同 | 改切换逻辑需实测合体版与独立版 |
| `ui/bekkan/__init__.py` | 别馆注册/注销 | 共同 | addonmanager 注册与面板恢复顺序不能乱 |

> 注：`core/hierarchy.py` 与 `core/stage.py` 中部分 Pond op 在概念上源自 Bekkan（如 `P2E`、`SoloPick`、`RAQtoSubparent`、中心约束灯光、摄像机组），但实现已被蛙灾改写。若后续发现功能可被 Bekkan 原版覆盖，需在开发计划中记录评估结果后再合并。

新增或移出共同维护模块时，必须同时更新本索引和 `开发计划/模块归属标注.md`。

### 5. 原始归属速查

完整模块归属与函数级标注见 `开发计划/模块归属标注.md`，
自动生成相似度报告见 `tools/analyze_origin_report.md`。
