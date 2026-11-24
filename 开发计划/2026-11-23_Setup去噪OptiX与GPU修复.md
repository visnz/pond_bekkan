# Setup 去噪 OptiX 与 GPU 修复

## 目标与范围

修复「一键 setup 工作区」把已经配置好的视口 OptiX 改成 OpenImageDenoise、把 Use GPU 关闭的问题。按用户要求，渲染和视口都默认使用 OptiX，并开启 GPU 去噪。只修改 Bekkan 的工作区设置模块与相关测试、留档；不涉及 Mixed 文件、注册顺序或 Pond UI。

## 改动

- `core/workspace_setup.py`：`render_settings_plan()` 明确设置渲染/视口 `denoiser=OPTIX`、`denoising_use_gpu=True`，开启两端去噪，并保留 `device=GPU`。`_DENOISE_FIELDS` 仅同步渲染的通道、预过滤和质量，避免读取旧算法/GPU 值覆盖明确目标。`_SETTING_NAMES` 新增渲染去噪的中文比较标签。
- `tools/test_workspace_setup.py`：独立断言 OptiX/GPU/去噪开启，复现渲染端 OIDN/GPU 关闭、视口端 OptiX/GPU 开启的组合；检查准确报告、再次执行一致，以及失败时所有去噪参数恢复。
- `tools/test_workspace_setup_ui.py`：使用上述旧值组合验证真实操作器、报告、撤销和重做；场景快照包含去噪参数。
- `开发计划/模块归属标注.md`：追加本轮记录，模块归属不变，不新增共同维护模块。

## 调试与验证

- 修复前回归失败，证实旧 setup 未确保渲染去噪目标；源码检查确认其把渲染旧算法及 GPU 值直接同步到视口。
- Blender 5.2.4 LTS：完整后台 setup 回归通过，覆盖原始三件套识别、空场景、已有工程保护、缺失资源补建、重复执行、准确报告、失败恢复及本次 OptiX/GPU 回归。
- Blender 5.3.0：空场景、已有工程保护、缺失资源补建、失败恢复及本次 OptiX/GPU 后台回归通过。
- Blender 5.2.4 原生界面测试通过：三页报告、单次撤销/重做（包含去噪参数）、重复执行与报告重开。
- Blender 5.3 原生界面测试通过（隔离空场景夹具）：三页报告、单次撤销/重做（包含去噪参数）、重复执行与报告重开；实际截图确认渲染去噪从 OpenImageDenoise 改为 OptiX、GPU 从关闭改为开启。
- `python -m compileall -q core ui tools build.py __init__.py prefs.py`、`git diff --check` 通过。重新生成四个 zip，校验压缩包完整性，并确认含 setup 的三种包内源码与当前修复源码逐字节一致。
- 全部测试使用隔离 factory-startup 实例及独立配置目录，没有重载或保存用户当前工程。

## TODO 与边界

- 5.3 的默认 Principled BSDF 新增 `Transmission Dispersion Abbe Number=20`，已有 `scene_setup_mode()` 的默认材质比较表按 5.2 编写，因此原始三件套会判为已有工程。完整后台套件在该原有检查处停止；本轮仅验证相关空场景和已有工程分支，5.3 界面测试采用隔离空场景夹具。该识别兼容问题单独待修，不混入本次去噪修改。
- 本轮没有修改全局 Cycles 计算后端偏好，只修改 scene 的渲染设备与渲染/视口去噪设置；没有实测渲染耗时或性能提升比例。
- 未提交或推送，保留此前白膜与 Shader 面板的未提交改动。
