# AutoBlend 合并与新版合成器适配

## 目标与范围

用户要求将当前 AutoBlend 插件适配 Blender 5.2 及以后并合并到别馆「灯光合成」。
基于干净的 `bekkanDEV` 分支开发，本轮不提交或推送。

已阅读项目 AGENTS.md、CLAUDE.md、合并对照清单、模块归属标注，以及个人技能库的
`blender/addon-development/SKILL.md`。只改 New 文件及新建逻辑、资源、测试文件；
不修改 Mixed 注册中心、Pond 专属代码、用户当前 Blender 工程或原 AutoBlend 安装。

## 来源与许可

源插件来自本机 Blender 5.3 用户扩展目录的 AutoBlend 1.1，作者
Shahzod Boyhonov (Specoolar)，manifest 声明 GPL-2.0-or-later。
`core/autoblend_assets/data.blend` 原样复制，SHA256 为
`D58D0A056EE9CCC813EA246CB2DDDD89E23BEFE325E6E259F1ABF876C0E404AC`。
同目录保存出处、作者与完整 GPL v2 条款；改编逻辑沿用 GPL-2.0-or-later。

## 改动

- `core/autoblend.py`：初始化、Noise/Voronoi 遮罩、选中物体材质加入/移除、旧节点组升级；
  operator 使用独立 `render.autoblend_*_visn`，逻辑中无 Panel/UIList。
- `core/__init__.py`：末尾追加 autoblend 常驻注册，原有顺序不变。
- `core/autoblend_assets/`：原 1.1 节点组及依赖；操作时惰性加载，启用时不接触受限场景数据。
- `ui/bekkan/light_compose_panel.py`：同文件添加并注册 AutoBlend 折叠子面板，包含中文融合参数、
  遮罩控制和材质名单。沿用父面板所在模块的注册入口，无需修改 Mixed 的 `ui/bekkan/__init__.py`。
- `build.py::_patched_content()`：非 `.py` 文件原样读取为 bytes，解决 `.blend` 被当 UTF-8 文本的问题。
- `tools/test_autoblend.py`、`tools/test_autoblend_render.py`、`tools/test_autoblend_ui.py`：隔离功能、渲染与图形交互测试。
- `开发计划/模块归属标注.md`：新增来源、资源与构建适配说明；未新增/移出 Mixed 模块。

保留原深度/Cryptomatte 融合算法及六项初始化选项。重复操作保留参数、材质名单及既有 Mask；
升级保留命名插座默认值、连线和连线的启用状态。合成器共享于其他场景时先复制当前场景的树。
现有 Render Image 下游经过 AutoBlend 再回到原色彩调整/Viewer/输出，不清空已有节点。
无法确认接入路径时报告错误并保留原输出连接，用户需在合成器中明确 Image 管线。

## 调试与试错

1. 实测 5.2.4 没有 `scene.node_tree` 和 `CompositorNodeComposite`，采用
   `Scene.compositing_node_group`、节点组 Image 输出和 `NodeGroupOutput`。
   `bpy.types.Scene` 上直接 `hasattr` 不反映该 RNA 属性，改为 RNA 表/场景实例检测。
2. 5.3 实测新增 `Scene.compositor_effects`，旧 `compositing_node_group` 将于 6.0 移除；
   优先原生效果栈，通过 `effect.node_group` 读写，不清除或重排已有效果。
   Group Input Image 可接收前一个效果的画面，Depth/ID 仍来自 Render Layers。
   在其他效果被设为活跃后仍能定位已有 AutoBlend。
3. Noise 显示名称由 Fac 变成 Factor，identifier 仍为 Fac，按名称和 identifier 兜底。
   `NodeLink.is_muted` 实测可写，保留原遮罩链接开关，无需额外门控节点。
4. 修正原 GPU 选项错误判断、失败却报告成功、空选择/材质空槽/名单重复等问题。
   Cryptomatte 原生名单按逗号切分且修剪首尾空格，不支持反斜线转义；核对 Blender 官方
   `source/blender/blenkernel/intern/cryptomatte.cc` 后，对含逗号等特殊名称使用原生浮点 ID，
   MurmurHash3_32 算法与 Blender 一致，普通名称保持可读。通过实际 Matte 渲染验证选中正确。
5. 从 Depth 连线识别实际源 View Layer，避免切换工作 View Layer 后重复生成渲染源；
   从 Matte/ID 连线定位 Crypto 节点，重命名后重复初始化也不产生循环。
6. 首轮后台测试仅 `--factory-startup` 未隔离扩展目录，Blender 刷新扩展缓存时出现权限失败；
   后续所有实例设置独立 `BLENDER_USER_RESOURCES`，不使用用户扩展/配置目录。
7. GUI 首轮因测试未创建临时插件偏好条目、在类型注册后才设置展开状态，未覆盖绘制；
   修正测试注册顺序后，两版本真实绘制、视图合成开关与一次撤销/重做通过。

## 验证

- Blender **5.2.4 LTS** 与 **5.3.0**：完整插件启用、初始化、重复运行、GPU 开关独立性、
  原参数与名单保留、Noise/Voronoi、Position pass、材质去重/空槽/加入移除、旧组升级、
  共享场景复制、既有多路下游保留、错误路径、模式切换、禁用与重载检查通过。
- 5.3：效果栈已有顺序及其他活跃效果保持，Group Input 管线接入通过。
- 两版本 GUI：原生侧边栏实际绘制，初始化启用当前视图合成器，单次撤销/重做通过，
  每个版本记录 9 次面板绘制且无 draw 异常。
- 两版本 Cycles 160×160 隔离渲染使用 **GPU 合成**，融合开/关存在实际像素差异；
  含逗号材质的 Crypto Matte 同时有正确的白色选中区域和黑色未选中区域。
- 四种 zip 打包成功；合体/Pond/Bekkan 内置资源 SHA256 与原资源一致，工程分析独立版不收 AutoBlend。
  三种完整构建在两版本均可独立启用与注销，独立包从自身资源路径加载节点组。
- Python 语法检查及 `git diff --check` 通过。

测试输出位于忽略目录 `temp/`，未保存或修改用户工程。复测前需将
`BLENDER_USER_RESOURCES` 设置为独立临时目录，再使用 `--factory-startup`；
后台测试同时加 `--python-exit-code 1`，GUI 测试在一次性实例中运行。

## 后续

当前实际覆盖 5.2.4 和 5.3.0；未来版本继续按原生属性能力检测，但需随 Blender 的 API 变化复测。
保留原材质作用范围：共用同一材质的物体一起参与融合。更多自定义连线在合成器中调整。
无本轮待完成功能；用户未要求本轮 commit/push。
