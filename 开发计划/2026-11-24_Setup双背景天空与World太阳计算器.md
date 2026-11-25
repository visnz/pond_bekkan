# Setup 双背景天空与 World 太阳计算器

## 目标与范围

1. Setup 补建世界天空时按用户截图，用一张 Multiple Scattering 天空同时驱动 pow（照明强度 3）和 vib（相机背景强度 0.1），通过 Light Path / Is Camera Ray 混合输出。
2. World Shader 面板添加两项仅计算的脚本：Sky Elevation/Rotation 转 Sun 世界坐标，以及反向计算。用户自行填写结果，兼容多个不同 Sun/Sky 的使用习惯，不自动写回。

仅涉及 Bekkan 的新功能模块与 Shader 面板、New 核心注册表、测试及归属记录。无 Mixed/Pond 专属文件改动，无共同维护清单增减，无独立新面板；已有面板和注册顺序保留。

## 文件与实现

- `core/workspace_setup.py`：`_SKY_SETTINGS` 设置截图参数：Multiple Scattering、Sun Disc 开启、Sun Size 77.9°、Intensity 1、Elevation 0.7°、Rotation 60°、Altitude 100m、Air 3、Aerosols 1、Ozone 1。`create_sky_world()` 创建双 Background、pow/vib 框、Light Path 和 Mix Shader，相机射线选第二路强度 0.1，其余射线选第一路强度 3。压紧节点布局，只显示所需 Light Path 输出。简单 Background 复用为 pow；已有颜色/强度/自定义 Shader 连线保留，在副本追加完整天空分支，报告说明未自动覆盖。
- `core/world_sun_calc.py`：纯数学双向函数及两个计算弹窗操作器。角度以度输入；半径默认 1。Sky 初值仅从当前编辑节点树的活跃/单选天空读取，Sun 初值只从活跃 Sun 的求值后世界矩阵读取（兼容父级），均可手动改输入。显示 XYZ/角度和可复制文本，不改变场景，不加入撤销栈。原点无方向时提示；Z 轴上 Rotation 不唯一时提示并显示 0°。
- `core/__init__.py`：New 注册分发末尾追加 `world_sun_calc`，既有模块顺序保持。
- `ui/bekkan/shader_panel.py`：只在 World 模式追加「Sky 角度 → Sun 坐标」「Sun 坐标 → Sky 角度」；保留材质与 Foto 脚本。
- `tools/test_workspace_setup.py`：双背景拓扑/参数、已有环境保护、重复执行保留用户强度、节点创建后异常的 World 清理验证。
- `tools/test_setup_sky.py`：源 World 副本保护（纯色、强度驱动、自定义 Mix），Cycles 相机/照明路由实际渲染对比。
- `tools/test_world_sun_calc.py`、`tools/test_world_sun_calc_ui.py`：方向与往返、仅计算操作器、真实 World 界面与弹窗、父级 Sun 的世界坐标读取及数据不变验证。
- `tools/test_fab_material.py`：World 按钮列表同步新增计算器。
- `开发计划/模块归属标注.md`：同步上述归属与接口说明，均无 Mixed 增减。

## 公式核对与试错

用户提供的 DeepSeek 公式等价于：

```python
x = radius * cos(elevation) * sin(rotation)
y = radius * cos(elevation) * cos(rotation)
z = radius * sin(elevation)
```

内部三角函数采用弧度。逆向用 `atan2(z, hypot(x,y))` 与 `atan2(x,y)`，Rotation 归一化到 [0,360)。0°朝 +Y，90°朝 +X。30.9° / 220° / 半径1 得 `(-0.551553489706, -0.657315852865, 0.513541252058)`。

隔离 Cycles Multiple Scattering 四个方向的实际渲染核对：该方向阳光峰值约 1960043，X/Y 符号翻转三个方向约 1.52–1.70，确认实际太阳方位与公式一致（`temp/sky-direction-probe52.log`）。

初次后台测试切换节点编辑器后没有立即建立 edit_tree，修正测试夹具的 path.start；首次 GUI 捕获函数使用两个默认参数，RNA 要求 invoke 恰好三个参数，改为闭包工厂。生产 invoke 签名始终为三个参数。节点截图首次被隔离实例启动向导遮挡，关闭测试实例 splash 后重新检查；Light Path 仅隐藏无关插槽，保留「Is Camera Ray」文字。未改用户偏好。

## 测试结果

- Blender 5.2.4：完整 Setup 后台回归通过，包括初始三件套、已有工程保护、失败恢复。5.3：相关空场景/已有工程分支回归通过；原始三件套识别的旧兼容问题仍按 11-23 记录单独待修。
- 5.2.4/5.3 的 Setup 原生界面报告、一次撤销/重做、重复运行通过；双背景节点截图已检查。
- 5.2.4/5.3 的源环境保护与天空路由渲染通过：白色 Diffuse 受光结果两路对比均为 0.6000002，相机背景从直接照明 0.6000002 变为混合 0.0199999996，准确为 1/30。
- 5.2.4/5.3 的角度坐标已知值、四个水平轴向、30 组正反往返、Z轴/原点处理与只读操作器通过。
- 5.2.4/5.3 的真实 World 面板、选中 Sky 初值、父级+Track To Sun 世界坐标初值、半径改变后的计算刷新通过；前后天空值、Sun/父级矩阵、约束目标、节点/连线数及选择完全一致。
- 5.2.4/5.3 Shader/Fab 入口兼容测试通过，World 列表包含两个白膜按钮及两个计算按钮，材质侧原有短名及 Foto 入口保持。插件启用测试触发 Blender 扩展系统的宿主缓存/依赖清理尝试，被只读权限拒绝；测试断言仍全部通过，未对该外部路径申请写权限。
- 静态编译、`git diff --check` 通过；四种 zip 重新生成并校验完整性，三个完整插件包的核心注册表、Setup、新计算模块和 Shader 面板与工作区源码正文一致。初次逐字节比较因 build.py 对 `__init__.py` 使用文本写入统一换行而失败，统一 CRLF/LF 后比较全部通过。

全部 Blender 操作用隔离 factory-startup 实例和临时配置，未重载、保存或操作用户当前工程。临时结果位于 `temp/setup-sky-*`、`temp/world-sun-*`；无 Mixed 改动。

## TODO 与交付边界

- Setup 的已有 Sky（包括以前 Setup 创建的单背景天空）继续按既定保护规则保留；本次修改的是补建天空的默认结构，不迁移旧天空。
- 初版计算器按 Sun 朝向世界原点处理。用户后续授权直接同步，初版只计算/复制行为已由 `2026-11-24_World太阳天空直接同步.md` 中的实现替代；仍按世界原点计算方向。
- 本轮未 commit/push，未修改现场工程或自动保存用户偏好。
