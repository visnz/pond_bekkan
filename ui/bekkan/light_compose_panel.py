# 别馆模式 ·「✨ 灯光合成」独立面板
# 新操作脚本容器：「贴图强制压缩」（三步向导，见
# core/analyzer/ops.py 的 ANALYZER_OT_downscale）、「修复法线贴图色彩空间」
# （见 ANALYZER_OT_fix_normal_colorspace，同一套算法也用在工程分析的
# MAT.normal_map_colorspace 检查项，这里单独放一个按钮不用先跑分析）；
# 双引擎 Cy 白膜适配：core/texture.py，共用一个白膜节点组。
# 中心约束灯光：core/stage.py；隐形遮光板、探针、EV 吸光体及烘焙：core/light_probe.py。
# 后续脚本以按钮追加。
import bpy


class BEKKAN_PT_light_compose(bpy.types.Panel):
    bl_label = "✨ 灯光合成"
    bl_idname = "BEKKAN_PT_light_compose"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "别馆"
    bl_parent_id = ""  # 顶层独立面板（bl_parent_id 空串 = 无父）
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.operator('object.add_light_with_constraint', icon='LIGHT_SPOT')
        layout.operator('object.create_invisible_blocker_visn', icon='MESH_PLANE')
        layout.separator()
        layout.operator('camera.create_volume_probe_visn', icon='LIGHTPROBE_VOLUME')
        layout.operator('object.create_ev_absorber_visn', icon='CUBE')
        layout.operator('object.bake_ev_absorbers_visn', icon='LIGHTPROBE_VOLUME')
        layout.operator('material.cycles_clay_visn', icon='NODE_MATERIAL')
        layout.operator('material.base_color_direct_visn', icon='NODE_MATERIAL')
        layout.operator("analyzer.downscale_textures_visn",
                        text="贴图强制压缩", icon="IMAGE")
        layout.operator("analyzer.fix_normal_colorspace_visn",
                        text="修复法线贴图色彩空间", icon="NODE_MATERIAL")


_classes = (
    BEKKAN_PT_light_compose,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
