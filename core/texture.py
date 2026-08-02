# 贴图索引：建立 贴图→材质 索引、查材质、选中使用物体
# （合并自 Bekkan/STOOL_part/TextureOps.py，纯平移；面板在 ui/bekkan/panels.py）
import bpy  # type: ignore
from bpy.props import StringProperty, PointerProperty  # type: ignore
from bpy.types import Operator, PropertyGroup  # type: ignore


class TextureSearchProperties(PropertyGroup):
    texture_search_image: StringProperty(
        name="贴图", description="选择要查找的贴图", default="")  # type: ignore


# 全局变量存储索引结果
texture_material_index = {}


def _checked_image(op, context):
    """公共检查：返回贴图名，索引为空或未选贴图时报错返回 None"""
    if not texture_material_index:
        op.report({'WARNING'}, "请先建立贴图索引!")
        return None
    img = context.scene.texture_search_props.texture_search_image
    if not img:
        op.report({'WARNING'}, "请选择一张贴图!")
        return None
    return img


class INDEX_OT_build_texture_index(Operator):
    bl_idname = "index.build_texture_index"
    bl_label = "建立or刷新 贴图-材质 索引"
    bl_description = "扫描所有材质并建立贴图与材质的对应关系索引"

    def execute(self, context):
        global texture_material_index
        texture_material_index = {}
        for mat in bpy.data.materials:
            if not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    lst = texture_material_index.setdefault(node.image.name, [])
                    if mat.name not in lst:
                        lst.append(mat.name)
        self.report({'INFO'}, f"索引建立完成，共索引 {len(texture_material_index)} 张贴图")
        return {'FINISHED'}


class INDEX_OT_find_materials(Operator):
    bl_idname = "index.find_materials"
    bl_label = "查找使用贴图的材质"
    bl_description = "查找使用选定贴图的所有材质"

    def execute(self, context):
        img = _checked_image(self, context)
        if img is None:
            return {'CANCELLED'}
        mats = texture_material_index.get(img)
        if not mats:
            self.report({'INFO'}, f"贴图 '{img}' 未被任何材质使用")
            return {'FINISHED'}
        self.report({'INFO'}, f"贴图 '{img}' 被以下材质使用: {', '.join(mats)}")
        print(f"\n贴图 '{img}' 使用情况:")
        for mat in mats:
            print(f"- {mat}")
        return {'FINISHED'}


class INDEX_OT_select_objects_with_texture(Operator):
    bl_idname = "index.select_objects_with_texture"
    bl_label = "选中该贴图的材质对象"
    bl_description = "选中所有使用该贴图的物体"

    def execute(self, context):
        img = _checked_image(self, context)
        if img is None:
            return {'CANCELLED'}
        mats = texture_material_index.get(img)
        if not mats:
            self.report({'INFO'}, f"贴图 '{img}' 未被任何材质使用")
            return {'FINISHED'}

        bpy.ops.object.select_all(action='DESELECT')
        n = 0
        try:
            for obj in bpy.data.objects:
                if hasattr(obj.data, 'materials'):
                    for slot in obj.material_slots:
                        if slot.material and slot.material.name in mats:
                            obj.select_set(True)
                            n += 1
                            break  # 多材质物体匹配到一个即可
        except Exception as e:
            self.report({'ERROR'}, f"发生错误: 物体可能不在当前场景中 {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已选中 {n} 个使用该贴图的物体")
        return {'FINISHED'}


_classes = (
    TextureSearchProperties,
    INDEX_OT_build_texture_index,
    INDEX_OT_find_materials,
    INDEX_OT_select_objects_with_texture,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.texture_search_props = PointerProperty(type=TextureSearchProperties)


def unregister():
    del bpy.types.Scene.texture_search_props
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
