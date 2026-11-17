# AutoBlend 内置节点资源

- 来源：AutoBlend 1.1，作者 **Shahzod Boyhonov (Specoolar)**，specoolar@gmail.com。
- 原插件说明：Easily blend objects in screen-space using compositor。
- 许可：**GPL-2.0-or-later**（源插件 `blender_manifest.toml` 声明）。完整条款见同目录 `COPYING`。
- `data.blend` 来自本机安装的 AutoBlend 1.1，原节点资源未经改写。
- SHA256：`D58D0A056EE9CCC813EA246CB2DDDD89E23BEFE325E6E259F1ABF876C0E404AC`。
- 主节点组 `_AUTOBLEND_1_1` 及依赖实现原作者的深度/Cryptomatte 画面空间融合算法。

PondBekkan 在 `core/autoblend.py` 中改编原操作逻辑，在别馆灯光合成面板提供中文入口；
适配 Blender 5.2+ 的 `Scene.compositing_node_group`、Group Output 及 Noise Factor 插座。
改编代码沿用 GPL-2.0-or-later。原 AutoBlend 安装目录不作修改。
