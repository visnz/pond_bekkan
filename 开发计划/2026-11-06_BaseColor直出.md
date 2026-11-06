# Base Color 直出（MMD 转 BL）

## 目标与改动

桶桶要求 MMD 转 BL 后，一键把当前引擎输出链中 BSDF 的 Base Color 上游直接接到 Material Output。修改 Bekkan 的 `core/texture.py`，新增 `base_color_direct` 和 `material.base_color_direct_visn`；在 `ui/bekkan/light_compose_panel.py` 灯光合成面板增加按钮。

## 行为

- 仅遍历当前选中物体材质槽中的材质，按数据块去重并忽略空槽，用 `get_output_node` 选择当前 EEVEE/Cycles 有效输出。未选中物体独有的材质不处理；若与选中物体共用材质，同一数据块的修改仍会共同生效。
- 从 Surface 广度优先沿着色器连接寻找最近的 BSDF，读取 Base Color 或 Color。支持重定向、Mix/Add Shader，同距离按输入插口顺序选取。
- 有连接时把原来源插口（贴图、Mix 等）直接接到 Surface；无连接时创建 RGB 节点，保留原颜色值。
- All 输出时为当前引擎新建独立输出，保留原 All 输出及另一引擎着色，同时保留 Volume/Displacement 等其他输入。
- 不删除原 BSDF 或上游节点；支持撤销。底部报告上游连接直出数、纯色数、跳过数。
- 无可用 BSDF、已直出、只读材质跳过。此版不展开节点组内部 BSDF。绕过 BSDF 同时绕过其 Alpha、粗糙度等着色属性，功能仅直出 Base Color。

## 简单验证

Blender 5.2.3 独立后台验证通过：Mix 上游直连、RGB 常量精度、All 与当前引擎输出隔离、已存在另一引擎输出保持、重复执行不新增、Cycles 路径与操作符注册执行。没有在用户工程中执行或重载插件；前台视觉效果由用户亲测。

尚未提交或推送，保留此前白膜与骨架同步的未提交改动。

## 选择范围调整

按用户反馈将操作符入口从全工程材质改为所选物体的材质槽；空选择或无材质时提示并取消。范围逻辑经静态检查，无需重复运行已通过的节点转换测试。
