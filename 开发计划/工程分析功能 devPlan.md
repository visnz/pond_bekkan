# Bekkan_visn · 📋 工程分析（Analyzer）开发报告

> 文档更新：2026-08-01。本文跟踪「工程分析」功能的**开发计划、完成进度与调试记录**，随迭代更新。
> 代码：`STOOL_part/Analyzer/`（model / state / checks / ops / ui + 自管注册 `__init__.py`）。
> 测试：`tools/test_analyzer.py`。

---

## 1. 功能定位

对当前 `.blend` 做扫描，输出一份按「影响程度」与「操作难易度」评级的优化建议清单，供用户逐条查看、标记完成/忽略、按需执行自动修复。

- **检查只读**：所有检查函数只读取场景/数据块，不修改数据。
- **修复按需**：检查是只读的，但部分建议提供「快速修复」操作通道，仅在用户点击时执行，且只操作当前 View Layer 可访问的对象/数据。
- **双模式**：简单检查（批 1，快） / 深度检查（= 简单 + 批 2，含几何/合并/缩放重计算，慢）。
- **适用范围**：仅 Blender 4.2+，只关注 EEVEE Next 与 Cycles 两个渲染引擎。
- **评级**：影响程度（严重/较高/一般/轻微）+ 操作便捷性（一键/小半/繁琐）。两者均在详情面板展示，列表支持按任一维度排序。

## 2. 架构

| 文件 | 职责 |
|---|---|
| `model.py` | `Finding` 数据结构、评级常量、`sort_results`、模块级 `LAST_RESULTS` 缓存 |
| `state.py` | ✓/× 标记状态持久化（JSON 存 `scene.analyzer_props.states_json`，随 .blend 保存） |
| `checks.py` | 全部检查函数；`run_quick` / `run_deep` 入口；`_engine()` 引擎判断；跨版本属性 `getattr`/`hasattr` 防御；调试日志 |
| `ops.py` | 操作符：运行 / 选中相关对象 / 行内循环开关 / 清除标记 / 快速修复 |
| `fixes.py` | 快速修复实现库（负缩放应用、贴图钳制等）；只处理当前 View Layer 可访问的对象 |
| `ui.py` | `AnalyzerProps` + `FindingItem`(行数据) + `ANALYZER_UL_finding`(内置表格 UIList) + `VIEW3D_PT_analyze_visn`(面板) |
| `__init__.py` | 自管注册（同 AddonManager，**不加入 allClass**）；`STOOL.py` 在 `register()` 开头调用，面板排在「别馆」页快照之后 |

**UI（v3，内置表格）**：
- `template_list` 表格：行 = 行首循环开关 + 标题 + 涉及数量（列表不再显示星级，改在详情展示）。
- 文字靠左；已完成 / 已忽略项置灰显示；已忽略项默认排序到最底部。
- 行内开关循环：未标记 □ → 已完成 ☑ → 不再提醒 × → 未标记；「不再提醒」由 `filter_items` **排到最下面**。
- 运行按钮下方提供「按影响程度排序 / 按操作难易排序」切换。
- 点选行 → 折叠详情面板（默认隐藏）：问题详情 / 处理手段 / 影响程度 / 操作难易度 / 快速修复按钮 / 「选中相关对象（N 个）」。
- 结果行同步进 `analyzer_props.findings`（CollectionProperty），随 .blend 保存，会话恢复后不依赖模块级缓存。

## 3. 检查项清单

### 3.1 简单检查（批 1，`_QUICK_CHECKS`，25 项）

| 类别 | key | 内容（要点） |
|---|---|---|
| 场景结构 | `STRUCT.object_count` | 对象总数过多 |
| | `STRUCT.empty_objects` | 大量无下级空物体 |
| | `STRUCT.orphan_objects` | 孤立对象（不在任何集合） |
| 变换 | `TRANS.negative_scale` | 负缩放对象 |
| | `TRANS.tiny_scale` / `TRANS.big_scale` | 缩放过大/过小 |
| 数据块 | `DATA.unused_shapekeys` | 无动画的形态键 |
| | `DATA.unused_materials` / `DATA.orphans` / `DATA.unused_actions` | 未使用数据块 |
| 视口/可见性 | `VIS.viewport_only` | 视图可见但渲染隐藏 |
| 渲染设置 | `RENDER.light_count` | 灯光数量偏多 |
| | `RENDER.sampling` | Cycles 采样 >2048 / 自适应未开 / 阈值过低；EEVEE 渲染采样 >64 |
| | `RENDER.bounces` | Cycles 反弹/焦散；EEVEE 光追分辨率 |
| | `RENDER.persistent_data` | 保留数据开关（Cycles 专属） |
| | `RENDER.motion_blur` | 运动模糊开启 |
| | `RENDER.output_format` | 输出格式/压缩可优化 |
| | `RENDER.device` | 未用 GPU（Cycles 专属） |
| | `RENDER.resolution` | 分辨率偏高（>16M / >33M 像素） |
| EEVEE 专项 | `EEVEE.shadows` | 阴影池 >2048（EEVEE 专属） |
| | `EEVEE.world_volume` | 世界体积雾 |
| 材质/贴图 | `MAT.duplicate_materials` | 节点树相同的重复材质 |
| | `MAT.images_per_material` | 单材质贴图数量过多 |
| | `MAT.big_textures` | 大尺寸贴图（≥4096） |
| | `MAT.texture_clamp` | Cycles 未开启 `scene.cycles.texture_limit`（仅 Cycles） |

### 3.2 深度检查（批 2，`_DEEP_CHECKS`，7 项，仅在「深度检查」模式跑）

| key | 内容 | 影响/便捷性 | 防卡死上限 |
|---|---|---|---|
| `TRANS.scale_range` | 场景缩放跨度过大（比值≥1000） | 一般/复杂 | — |
| `TRANS.non_uniform_scale` | 非等比缩放对象 | 轻微/复杂 | — |
| `STRUCT.merge_same_material` | 同材质对象≥10（可合并） | 较高/半自动 | — |
| `STRUCT.identical_duplicates` | 几何完全相同的网格（可关联复制） | 一般/复杂 | 跳过 >5 万顶点 / 带形态键 |
| `GEOM.high_poly_count` | 单对象面数>10 万 | 较高/半自动 | — |
| `GEOM.camera_occupancy` | 高面数对象在相机画面占比<2%（需场景有相机） | 较高/复杂 | 仅 ≥5 万面对象 |
| `GEOM.non_manifold` | 非流形边/点/零面积面（bmesh） | 较高/复杂 | 前 100 个网格 / 跳过 >10 万顶点 |

## 4. 开发阶段与进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| **P0** 批 1 检查 | 25 项简单检查 + `run_quick` 单检查 try/except 不中断 | ✅ 完成 |
| **P1** 评级 UI v1 | 影响/便捷性评级、展开详情、✓/× 标记、选中相关对象、简单/深度两模式（深度为占位降级） | ✅ 完成 |
| **P2** 批 2 深度检查 | 7 项几何/合并/缩放统计检查 + `run_deep` = 简单 + 批 2 | ✅ 完成 |
| **P3** 内置表格 UI v2 | template_list 表格、★星级、隐藏便捷性、行内循环开关、「不再提醒」排最下、结果持久化 | ✅ 完成 |
| **P4** 引擎隔离 + 稳定性 | `_engine()` 引擎判断；渲染类检查按 CYCLES/EEVEE 隔离；预运行空态提示 | ✅ 完成 |
| **P5** 快速修复扩展 | 负缩放、视口可见性、未使用数据清理、重复材质合并、Cycles 贴图限制 | ✅ 完成 |

## 5. Debug 汇报（问题 → 根因 → 修复）

### D1. 面板 draw 崩溃：`enum "WARNING" not found`（用户手动点击暴露）
- **现象**：渲染面板时 `TypeError: UILayout.label(): error with keyword argument "icon" - enum "WARNING" not found`。
- **根因**：影响程度图标用了 `'WARNING'`，Blender 5.2 已把该图标移除（合法的是 `STATUS_WARNING`）；图标枚举随版本增减。
- **修复**：改用 `STATUS_WARNING`；新增 `_icon()` 跨版本防御——首次绘制时读当前版本的合法图标枚举，无效图标一律回退 `'NONE'`。
- **教训**：测试只点 operator 不渲染面板，draw 层的错误漏掉了。→ 补 D6。

### D2. 面板 draw 崩溃：`'NoneType' object has no attribute 'active'`（用户反馈）
- **现象**：标记「已完成」后渲染，`title_lbl = title_row.label(...)` 返回 `None`，随后 `title_lbl.active = False` 崩溃。
- **根因**：不能依赖 `UILayout.label()` 的返回值（5.2 下可能返回 `None`）。
- **修复**：不再使用 label() 返回值——改为独立的行容器 `title_row.active = (st != 'done')`（对 `row()` 生效，稳定）。新版 UI 全部规避此模式。

### D3. 深度测试：`GEOM.non_manifold` 不触发
- **根因**：对象上限用 `enumerate(_objects())` 的下标，而 `_objects()` 含 3000+ 空物体，网格对象下标全部超出 100 上限。
- **修复**：先把网格对象过滤成列表再 `meshes[:_NONMANIFOLD_MAX_OBJS]` 切片。
- **教训**：防卡死上限应对**该类型的对象**计数，不能对全部对象计数。

### D4. EEVEE 场景误报「采样 4096」（用户反馈）
- **现象**：用户用 EEVEE、16 采样，分析却报「采样数高达 4096」。
- **根因**：`check_sampling`（及 `check_bounces`/`check_device`）按 `scene.cycles is not None` 分支——但 `scene.cycles`/`scene.eevee` 是**常驻 PointerProperty，任何引擎下永不为 None**，于是 EEVEE 工程也走 Cycles 分支，读到了遗留的 `scene.cycles.samples=4096`；EEVEE 分支是死代码。
- **修复**：新增 `checks._engine()`（读 `scene.render.engine` 判断 CYCLES/EEVEE/其它），把 6 个渲染类检查全部引擎隔离。
- **回归测试**：EEVEE + 16 采样 → `RENDER.sampling` 不出现、Cycles 专属项不出现、`EEVEE.world_volume` 仍报；Cycles 场景不报 `EEVEE.shadows`。

### D5. 打开列表「没东西」
- **现象**：面板首次展开时列表区域看起来是空的。
- **根因**：运行前的提示只有两行小字，视觉上像空；运行后结果本就在（`findings` 随 .blend 保存）。
- **修复**：把预运行态改成醒目的提示块（「尚未运行分析 · 点击上方「运行分析」…」）。

### D6. 测试覆盖缺口：GUI draw 路径
- **根因**：后台模式没有真实 UILayout，原测试只调 operator，draw 层错误（D1/D2）漏网。
- **修复**：`invoke_panel_draw()` 用递归 mock UILayout 直接调用面板 `draw()`，逐条校验 `icon=` 是否合法；`invoke_uilist()` 直接调用 UIList 的 `draw_item`/`filter_items`，校验行内图标与「不再提醒排最下」排序。

### D7. 列表窗口实际仍为空（运行分析后行不渲染）
- **现象**：用户实测：点击「运行分析」后，列表区域没有任何行显示（D5 的预运行提示已消失，确认 `has_run=True`）。
- **根因**：`ANALYZER_UL_finding.draw_item()` 方法签名缺少 Blender UIList 规范中的 `flt_flag` 参数。真实 Blender 5.2 调用 `draw_item` 时传入 `flt_flag`，Python 因参数数量不匹配抛出 `TypeError`，UI 绘制被静默吞掉，导致所有行空白。
- **修复**：`draw_item(self, ..., index, flt_flag=0)`；显式声明 `bl_idname = "ANALYZER_UL_finding"`；测试调用同步更新。

### D8. UI/修复/稳定性改进（用户反馈集中批）
- **修复**：UI v3；`select_visn` 跨 View Layer 容错；新增 `ANALYZER_OT_fix`；`fixes.py` 初始修复库；`_as_int()` 字符串兼容；调试日志；换行优化。

### D9. 修复第二批实测反馈
- **修复**：多用户网格负缩放修复、未使用/孤儿数据列名、视口可见性批量修复、PNG 压缩建议修正、贴图限制改为设置 `gl_texture_limit`、遗漏的 `max_bounces` 字符串兼容。

### D10. 内部图像过滤 + 快速修复扩展 + 排序修正（本次迭代）

#### D10.1 Viewer Node / Render Result 不应被视为贴图或孤儿数据
- **现象**：用户反馈 Viewer Node 不是贴图，也不是孤儿数据块，应像 Render Result 一样视为内部中间件。
- **根因**：`check_unused_materials`、`check_orphan_data`、`check_big_textures` 直接遍历 `bpy.data.images`，把 `source == 'VIEWER'` 的 Viewer Node 图像、以及 `type == 'RENDER_RESULT'` / 名称以 `Render Result` 开头的内部图像都纳入了统计。
- **修复**：
  - `checks.py` 新增 `_is_real_image(img)` 帮助函数，过滤 `source == 'VIEWER'`、`type in {'RENDER_RESULT','COMPOSITING'}`、名称以 `Render Result` 开头的图像。
  - 在 `check_big_textures`、`check_unused_materials`、`check_orphan_data` 中统一调用该过滤。
- **相关提交**：`STOOL_part/Analyzer/checks.py`

#### D10.2 一键清理未使用 / 孤儿数据
- **现象**：存在未使用的贴图或孤儿数据块时，应能直接调用 Blender 操作清除。
- **修复**：
  - `fixes.py` 新增 `fix_purge_unused(context, item)`，调用 `bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)`，并做参数兼容性回退（某些版本参数名不同则回退到最简调用）。
  - `ops.py` 为 `DATA.unused_materials`、`DATA.orphans` 分发到 `fix_purge_unused`；修复成功后自动调用 `analyzer.run_visn` 重新扫描。
  - `ui.py` 为这两个 key 在详情面板显示「清理未使用数据（Purge）」按钮。
- **相关提交**：`STOOL_part/Analyzer/fixes.py`、`ops.py`、`ui.py`

#### D10.3 重复材质自动合并替换
- **现象**：节点树对比分析出的重复材质，应能自动替换为每组第一个，确保参数一致。
- **修复**：
  - `checks.py` 把重复材质分组逻辑提取为公共函数 `collect_duplicate_material_groups(limit=3000)`，返回 `[[keep_mat, dup_mat, ...], ...]`。
  - `checks.py` 的 `check_duplicate_materials` 复用该函数，并在详情中列出「保留 XXX，合并 YYY」方案。
  - `fixes.py` 新增 `fix_duplicate_materials(context, item)`：遍历每组，把所有引用 `dup` 材质的对象的 `material_slots` 改为引用 `keep`，然后 `bpy.data.materials.remove(dup)`。
  - `ops.py` 为 `MAT.duplicate_materials` 分发到该修复，修复成功后自动重新扫描。
  - `ui.py` 显示「合并重复材质（保留每组第一个）」按钮。
- **相关提交**：`STOOL_part/Analyzer/checks.py`、`fixes.py`、`ops.py`、`ui.py`

#### D10.4 过大贴图按尺寸排序并列出名字
- **现象**：用户要求把过大贴图的数据都列出来，并按大小排序显示名字。
- **修复**：
  - `check_big_textures` 先过滤内部图像，再按 `size[0] * size[1]` 从大到小排序。
  - 详情 / 处理手段中列出 `名字 (宽×高)`，超过 20 条自动截断并提示剩余数量。
- **相关提交**：`STOOL_part/Analyzer/checks.py`

#### D10.5 Cycles 贴图钳制改为 `scene.cycles.texture_limit`，EEVEE 提示不可用
- **现象**：EEVEE 环境下没有可做贴图钳制的地方；Cycles 下钳制也没成功，正确属性路径是 `scene.cycles.texture_limit`。
- **根因**：旧实现设置的是全局偏好 `preferences.system.gl_texture_limit`，既非 Cycles 专属，也不影响渲染；EEVEE 没有对应属性。
- **修复**：
  - `checks.py` 新增 `check_texture_clamp(context)`：仅 `_engine(context) == 'CYCLES'` 时检查；若 `scene.cycles.texture_limit` 与 `texture_limit_render` 均为 `'OFF'` 则报告。
  - 将该检查加入 `_QUICK_CHECKS`。
  - `fixes.py` 的 `fix_clamp_textures(context, item, max_size)` 改为设置 `scene.cycles.texture_limit`（仅视口限制；渲染限制保留用户决定）；EEVEE 下返回 `(0, 1, {"reason": "..."})`。
  - `ops.py` 在修复返回 `reason` 时以 `WARNING` 报告并返回 `{'CANCELLED'}`。
  - `ui.py` 中 `MAT.big_textures` 按当前引擎显示不同提示：Cycles 显示「限制 4K / 2K」按钮；EEVEE 显示「没有 scene.cycles.texture_limit，建议手动缩小图像尺寸」。`MAT.texture_clamp` 始终显示 Cycles 限制按钮（因为该检查只在 Cycles 下出现）。
- **相关提交**：`STOOL_part/Analyzer/checks.py`、`fixes.py`、`ops.py`、`ui.py`

#### D10.6 「已忽略」排序不沉底
- **现象**：用户标记「不再提醒」的条目仍排在列表中间，期望永远在最下面。
- **根因**：`ANALYZER_UL_finding.filter_items` 已按 `dismissed` 作为第一排序键，但 UIList 自带的 `use_filter_sort_alpha` / `use_filter_sort_reverse` 可能覆盖自定义顺序。
- **修复**：在 `filter_items` 中强制关闭 `self.use_filter_sort_alpha = False` 与 `self.use_filter_sort_reverse = False`（用 `hasattr` 防御版本差异）。
- **相关提交**：`STOOL_part/Analyzer/ui.py`

#### D10.7 `NameError: name 'context' is not defined`
- **现象**：本次迭代中为 `_draw_fix_buttons` 新增 `context` 参数后，`VIEW3D_PT_analyze_visn._draw_detail` 调用它时未传入 `context`，导致绘制详情时崩溃。
- **修复**：
  - `_draw_detail(self, layout, item)` 改为 `_draw_detail(self, context, layout, item)`。
  - `draw` 中调用 `self._draw_detail(context, layout, findings[idx])`。
  - `_draw_fix_buttons(self, layout, item)` 改为 `_draw_fix_buttons(self, context, layout, item)`。
  - `tools/test_analyzer.py` 的面板 mock 同步更新：`_draw_detail` lambda 改为接收 `ctx` 并转发。
- **相关提交**：`STOOL_part/Analyzer/ui.py`、`tools/test_analyzer.py`

## 6. 测试与验证

```bash
blender --background --python "tools/test_analyzer.py"           # 工程分析
blender --background --python "tools/test_anim_migrate.py"       # 回归：ALL PASS
blender --background --python "tools/test_addon_manager_load.py" # 回归：PASS
```

- 本次新增测试覆盖：
  - Viewer Node 不被视为未使用贴图 / 孤儿数据。
  - 过大贴图按尺寸从大到小排序，且详情中列出名字与分辨率。
  - Cycles 下 `fix 贴图` 正确设置 `scene.cycles.texture_limit='4096'`。
  - EEVEE 下 `fix 贴图` 返回 `{'CANCELLED'}` 并给出原因。
  - `fix 合并重复材质` 后重复材质被移除。
  - `fix 清理未使用数据（Purge）` 不崩溃。
  - 面板 mock 的 `_draw_detail` 签名与新实现一致。
- GUI 验证：Blender 中 `F8` 重载 → 「别馆」页 → 📋 工程分析 → 运行分析；确认列表行正常显示；测试排序按钮、折叠详情、修复按钮（负缩放 / 视口可见性 / 贴图限制 / Purge / 合并重复材质）；切「深度检查」验证批 2。

## 7. 当前待办 / 后续方向

- [x] D7：修复 UIList `draw_item` 缺少 `flt_flag` 导致真实 GUI 列表为空。
- [x] D8：UI v3、快速修复基础设施、select 跨 View Layer 容错、`check_bounces` 字符串兼容。
- [x] D9：多用户网格负缩放修复、未使用/孤儿数据列名、视口可见性批量修复、PNG 压缩建议修正、贴图限制修正。
- [x] D10：内部图像过滤、Purge 清理、重复材质合并、大图排序列名、Cycles `texture_limit`、忽略项沉底排序、`context` NameError 修复。
- [ ] GUI 实测：重载插件后运行「简单检查」与「深度检查」，确认列表行正常渲染、排序按钮、折叠详情、所有修复按钮可交互。
- [ ] 扩展快速修复：同材质合并（`STRUCT.merge_same_material`）、重复网格关联复制（`STRUCT.identical_duplicates`）等。
- [ ] 批 2 检查项的阈值是否按项目体量自适应（目前为固定经验值）。
- [ ] 本轮所有改动尚未提交 git，确认后整理提交。

## 8. 已知问题 / 备注

- 退出 Blender 时偶尔出现 `unregister_class(...) missing bl_rna attribute` / `ModuleNotFoundError: bgl`：来自用户机器上的**其他**插件 `Snapshot_3d_viewer`（AppData 目录），与本插件无关，未处理。
- 深度检查在真实大工程上比简单检查慢（几何哈希 + bmesh 扫描），属预期；防卡死上限见 3.2。
- 判断渲染引擎**只能看 `scene.render.engine`**，不能看 `scene.cycles`/`scene.eevee` 是否存在（常驻属性永不为 None）。
- Cycles 的 `scene.cycles.texture_limit` 仅控制 3D 视口纹理分辨率上限，渲染输出如需完整精度请保持 `texture_limit_render='OFF'`。
- EEVEE 没有与 Cycles `texture_limit` 对应的 per-scene 贴图钳制，大图优化需手动缩小图像数据尺寸。
