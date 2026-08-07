# 2026-08-07 新面板「三渲二」：Fork OutlineHelper 并修 Blender 5.2 API bug

## 目标

把独立插件 `OutlineHelper`（反转法线壳描边工具，作者 Feline Entity，仓库外
`C:\Program Files (x86)\Steam\steamapps\common\Blender\5.2\scripts\addons_core\OutlineHelper`）
的功能 fork 进本仓库，做成别馆新面板「🎨 三渲二」，同时修两个用户点名的 Blender 5.2 bug：

1. `mat.shadow_method = "NONE"`——`Material.shadow_method` 在 EEVEE Next（4.2+）已被移除，
   原插件在 5.2 上创建描边材质时会直接抛异常。
2. `bpy.data.materials["OH_Outline_Material"].use_backface_culling_shadow` 没打开——
   材质只设了 `use_backface_culling`（视口/渲染背面剔除），阴影计算时背面没被剔除，
   反转法线壳在阴影里会露馅。

## 改动

### 1. 新建 `core/outline.py`（Bekkan）

平移 `OH_OT_Outline_Operator` / `OH_OT_Adjust_Operator` / `OH_OT_Remove_Operator`，
**保留原 idname**（`object.oh_outline` / `object.oh_adjust` / `object.oh_remove`），
延续本项目对独立插件"忠实平移，不改前缀"的惯例（对照 `core/anime.py` 的 `autosway.*`）。

- 删除 `mat.shadow_method = "NONE"`。
- 材质创建块里 `mat.use_backface_culling = True` 之后补一行
  `mat.use_backface_culling_shadow = True`。
- 顺手修了原插件三个操作符 `poll()` 里 `bpy.context.object` 为 `None` 时会崩溃的问题
  （改成先判断 `context.object is not None`）——这是原插件既有 bug，不在用户点名的两个
  之内，作为顺手带上的防御性修复。
- 节点树搭建（EEVEE 黑色 RGB 直出 + Cycles 背面透明混合的 3 层 MixShader）、Solidify
  修改器参数（负厚度、`use_flip_normals=True`、`use_rim=False`、`material_offset=999`）、
  顶点组权重逻辑（编辑模式下按选中顶点 `REPLACE` 权重）原样保留，未做其他改动。

### 2. 新建 `ui/bekkan/outline_panel.py`（New）

顶层面板 `VIEW3D_PT_outline_visn`，`bl_label = "🎨 三渲二"`，`bl_category = '别馆'`，
默认折叠（`DEFAULT_CLOSED`），`poll` 用 `module_enabled("show_toon_outline")`。
三行按钮布局照抄原插件 `oh_sidepanel.py`：Add/Set Outline（icon `ADD`）、
Adjust Outline（icon `ARROW_LEFTRIGHT`）、Remove Outline（icon `PANEL_CLOSE`）。

### 3. `ui/bekkan/prefs.py`：模块开关

`MODULES` 追加 `("show_toon_outline", "三渲二")`，插在 `show_render_preset` 和
`show_addonmanager` 之间（颈椎拯救者仍是最后一项）。根 `prefs.py` 的动态注解循环会
自动为这个 key 生成偏好开关，未改根 `prefs.py`。

### 4. `core/__init__.py`（Mixed）

`_MODULES` 元组末尾追加 `outline`（`analyzer` 之后），两模式都会常驻注册这三个操作符，
跟其它 Bekkan-only core 模块（`anime`/`render_preset` 等）的既有注册方式一致。

### 5. `ui/bekkan/__init__.py`（Mixed）

`outline_panel.register()` 插在 `panels.register()` 之后、`_am_core.register()`/
`addonmanager_panel.register()` 之前；`unregister()` 对称插在
`_am_core.unregister()` 之后、`panels.unregister()` 之前——维持「颈椎拯救者始终最后注册/
最先注销」的既有约束不被打破。

### 6. `开发计划/模块归属标注.md`

补充 `core/outline.py`（Bekkan）、`ui/bekkan/outline_panel.py`（New）两行，顺手回填了
一处此前遗漏的文档缺口：`ui/bekkan/prefs.py`（Bekkan，别馆模块开关唯一来源，此前从未
列入该文档，属于文档补漏而非本轮新引入的归属变更）。

## 已知风险 / 待验证

- **与独立版共存冲突**：如果 Blender 里还启用着独立的 `OutlineHelper` 插件，两边会注册
  同一批 `object.oh_*` idname 和同名的 `OH_Outline_Material`/`OH_OUTLINE`/
  `OH_Outline_VertexGroup`，后注册的覆盖前者，行为不确定。**建议整合完成后在 Blender
  偏好里禁用/卸载独立版**（同 `autosway.py` 先例），未跟用户当场确认，GUI 实测时留意。
- `use_backface_culling_shadow` 是否确实存在于当前 Blender 5.2 API：这是用户在实际项目里
  遇到并点名的属性，本次按用户描述直接采信设置；`WebSearch`/`WebFetch` 两条在线核实通道
  本次会话里均不可用（搜索返回训练数据免责声明、docs.blender.org 返回 403），未做进一步
  在线验证，只跑了 `python -m compileall -q .` 静态检查语法正确。
- 未跑 GUI 实测。需要 F8 重载后核对：
  - 别馆侧栏出现「🎨 三渲二」折叠面板；
  - 选中 mesh 点「Add/Set Outline」，确认 `OH_Outline_Material` 的
    `use_backface_culling_shadow` 已勾选，EEVEE/Cycles 渲染都只看到黑色描边，
    阴影里不露内部背面；
  - 「Adjust Outline」在物体模式（整体厚度）和编辑模式（选中顶点权重）分别测试；
  - 「Remove Outline」确认材质槽/修改器/顶点组三样都清干净；
  - 曲线对象（CURVE）路径也测一下（无顶点组分支，逻辑与原插件一致，未单独改动）。

## 测试结果

`python -m compileall -q .` 无报错。GUI 实测留给用户在 Blender 里验证。

## TODO

- 视用户 GUI 实测反馈，决定是否需要处理与独立版 `OutlineHelper` 共存的冲突提示。
