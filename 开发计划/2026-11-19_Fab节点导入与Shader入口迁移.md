# Fab 节点导入与 Shader 入口迁移

## 目标与范围

按用户要求，Fab/Megascans 导入取消猴头预览，改为向当前 Shader 编辑层追加节点；
Fab 和「修复法线贴图色彩空间」从灯光合成移到 Shader Editor 的「别馆 → Shader 脚本」。

已读取个人插件开发技能、项目 AGENTS.md、合并对照清单及模块归属标注。
只修改现有 New/Bekkan 文件；现有 Shader 面板已接入，无需改 Mixed 注册中心。
池塘界面和 addonmanager 恢复顺序不变。本轮更新模块归属说明，无共同维护清单新增项。
保留此前尚未提交的文件体积检查和几何节点入口封装改动。

## 修改文件与行为

- core/fab_material.py：用 import_material_nodes() 替换新材质/猴头创建，保留材质导入操作器 idname。
- ui/bekkan/shader_panel.py：加入 Fab 导入、原有法线色彩空间修复按钮，使用紧凑列。
- ui/bekkan/light_compose_panel.py：移除对应按钮、Fab 子面板及其本文件注册项。
- tools/test_fab_material.py、tools/test_fab_material_ui.py、tools/test_fab_material_render.py：更新隔离验证。
- 本日志和模块归属标注。

当前材质需已存在且可编辑。导入不创建任何对象、网格或新材质，不修改物体选择。
保留旧节点、连线、位置及原材质输出；新节点单独排列在旧图右侧，全部选中便于移动。
已有材质输出时，新增 Fab 输出保持非活跃；由用户按需连接或启用。
没有材质输出时，新输出直接启用并保持 Bump Only；已有工程的置换模式保留。
在嵌套 Shader 组内导入时保留组接口，新增 BSDF 和 Displacement 输出由用户手动接入，
不创建组内无效的 Material Output。

原贴图规则保持：同一资产优选整套最高分辨率；
BaseColor sRGB，其余 Non-Color；BaseColor、Roughness、Specular、Normal Map、Displacement 连线；
AO 的颜色输出不连，共用 UV → Mapping 和 Value → Scale。
OpenGL 法线优先，明确 DirectX 时翻转绿色通道。
导入失败只清理本次新增节点/图片，恢复节点选择、活动节点、输出状态及置换设置。

文件选择器打开前捕获材质和当前编辑树的 session_uid。
即使选择器期间退出组或重命名节点组，仍导入最初目标；目标已删除则取消。
法线修复仅迁移 UI 入口，沿用原有全工程修复算法与可选名称复核，不改范围。

## 调试过程

1. 原方案用 Operator 的 ID PointerProperty 捕获目标，真实注册发现该类型不支持数据块属性。
   改用隐藏 StringProperty 保存 session_uid；两个版本的文件夹确认和撤销重做验证通过。
2. 测试中 SpaceNodeEditor.id 是只读，改用真实对象材质槽与编辑器 path 初始化上下文。
3. 重跑测试时旧贴图夹具带入其他资产文件；每次使用独立临时夹具子目录，避免污染识别结果。

## 验证结果

Blender 5.2.4 LTS / 5.3.0 隔离后台均通过：

- 真实 Fab 4K 六张图、2K、缺图、多资产错误、损坏图片、GL/DX 选择、正确色彩图片复用。
- 不增加对象/网格/材质，不改变物体选择；旧节点位置、框架关系、连线和活跃输出保留。
- 新增子图排列不重叠，重复导入复用正确图片。
- 空材质输出启用并保持 Bump Only；原 BOTH 置换设置保留。
- 组内接口保留；注入布局错误后节点、图片、选择、活动节点、输出完整回退。
- 法线色彩修复从 Shader 上下文运行，世界着色器模式不显示/不可调用 Fab 导入。
- 两按钮仅出现在 Shader，Fab 3D 子面板已注销；别馆/池塘切换和禁用/启用正常。

两个版本真实 GUI 均通过：

- Shader 面板实际绘制、原生文件夹选择器确认、一次撤销/重做。
- 用绘制后的真实尺寸验证新节点避让，并检查截图。
- 嵌套组中打开选择器，退出组并重命名后确认，仍向原组追加节点。
- Shader 中调用法线修复，原节点/接口不变。

两个版本 Cycles 实际渲染通过；Value 从 1 改为 2 时，前景 11447 像素中
分别 7374 / 7372 像素发生明显变化，统一缩放生效。
猴头仅由渲染测试脚本创建为测试夹具，插件实现已无猴头创建。

日志在 temp/fab-material52.log、temp/fab-material53.log；
GUI 结果/截图在 temp/fab-ui52/、temp/fab-ui53/；
渲染结果在 temp/fab-render52/、temp/fab-render53/。
所有测试均使用独立 factory-startup 实例，未重载、保存或修改用户当前工程。

静态语法与 git diff --check 通过。四种发行 zip 重新生成并校验，
三个完整包包含最新 Fab/Shader UI，工程分析独立版保持原范围。

## 后续

本轮功能完成；未执行 commit/push。
