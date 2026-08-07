# 别馆模式 ·「✨ 灯光合成」独立面板
# 新操作脚本容器：目前两个脚本入口——「贴图强制压缩」（三步向导，见
# core/analyzer/ops.py 的 ANALYZER_OT_downscale）、「修复法线贴图色彩空间」
# （见 ANALYZER_OT_fix_normal_colorspace，同一套算法也用在工程分析的
# MAT.normal_map_colorspace 检查项，这里单独放一个按钮不用先跑分析）；
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
