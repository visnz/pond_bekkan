# 别馆搭建类：手动对比当前视图层的视图/渲染可见性。
# 不订阅消息或依赖图，不自动修改可见性；排除关键词按 Scene 随工程保存。
from collections import defaultdict
import re

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty

from .light_probe import _absorbers


def exclusion_keywords(text):
    return tuple(dict.fromkeys(part.strip().casefold() for part in re.split(r'[,，]', text)
                               if part.strip()))


def collect_mismatches(scene, view_layer, exclusions=''):
    keywords = exclusion_keywords(exclusions)
    routes = defaultdict(list)
    excluded_by_name = set()

    def matches(name):
        return any(word in name.casefold() for word in keywords)

    def visit(layer_collection, excluded=False, viewport_cause='', render_cause='', ignored=False):
        collection = layer_collection.collection
        excluded = excluded or layer_collection.exclude
        ignored = ignored or matches(collection.name)
        if not viewport_cause:
            if collection.hide_viewport:
                viewport_cause = f'集合「{collection.name}」禁用视图'
            elif layer_collection.hide_viewport:
                viewport_cause = f'视图层集合「{collection.name}」临时隐藏'
        if not render_cause and collection.hide_render:
            render_cause = f'集合「{collection.name}」禁用渲染'
        for obj in collection.objects:
            if ignored:
                excluded_by_name.add(obj)
            if not excluded:
                routes[obj].append((viewport_cause, render_cause))
        for child in layer_collection.children:
            visit(child, excluded, viewport_cause, render_cause, ignored)

    visit(view_layer.layer_collection)
    absorbers = set(_absorbers())
    results = []
    counts = {'checked': 0, 'absorbers': 0, 'keywords': 0}
    for obj in sorted(scene.objects, key=lambda o: o.name.casefold()):
        if obj in absorbers:
            counts['absorbers'] += 1
            continue
        if obj in excluded_by_name or matches(obj.name):
            counts['keywords'] += 1
            continue
        counts['checked'] += 1
        paths = routes[obj]
        # 多重集合链接按任一可用路径判断；排除视图层的路径不参与任何一种可见性。
        view_path = any(not view_cause for view_cause, _ in paths)
        render_path = any(not render_cause for _, render_cause in paths)
        temporary_hidden = bool(obj.hide_get(view_layer=view_layer)) if view_path else False
        viewport_visible = view_path and not obj.hide_viewport and not temporary_hidden
        render_visible = render_path and not obj.hide_render
        if viewport_visible == render_visible:
            continue
        reasons = []
        if not viewport_visible:
            if obj.hide_viewport:
                reasons.append('对象禁用视图（显示器）')
            if temporary_hidden:
                reasons.append('对象临时隐藏（眼睛）')
            if not view_path:
                reasons.extend(view_cause for view_cause, _ in paths if view_cause)
        if not render_visible:
            if obj.hide_render:
                reasons.append('对象禁用渲染（相机）')
            if not render_path:
                reasons.extend(render_cause for _, render_cause in paths if render_cause)
        results.append({'object': obj, 'viewport_visible': viewport_visible,
                        'render_visible': render_visible,
                        'reason': '；'.join(dict.fromkeys(reasons))})
    return results, counts


class VisibilityAuditItem(bpy.types.PropertyGroup):
    object: PointerProperty(type=bpy.types.Object)
    viewport_visible: BoolProperty()
    render_visible: BoolProperty()
    reason: StringProperty()


class VisibilityAuditProperties(bpy.types.PropertyGroup):
    exclusions: StringProperty(
        name='排除关键词',
        description='逗号分隔名称关键词，例如 aaa,bbb,ccc；匹配对象或所属集合名称，随当前工程保存')
    results: CollectionProperty(type=VisibilityAuditItem, options={'SKIP_SAVE'})
    index: IntProperty(default=0, options={'SKIP_SAVE'})
    has_scan: BoolProperty(default=False, options={'SKIP_SAVE'})
    scanned_exclusions: StringProperty(options={'SKIP_SAVE'})
    scanned_layer: StringProperty(options={'SKIP_SAVE'})
    checked: IntProperty(options={'SKIP_SAVE'})
    ignored_absorbers: IntProperty(options={'SKIP_SAVE'})
    ignored_keywords: IntProperty(options={'SKIP_SAVE'})


class VIEW3D_OT_check_visibility_visn(bpy.types.Operator):
    bl_idname = 'view3d.check_visibility_visn'
    bl_label = '检查视图 / 渲染可见性'
    bl_description = '手动检查当前视图层的对象、集合继承及临时隐藏状态，排除吸光体和指定名称'

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.view_layer is not None

    def execute(self, context):
        context.view_layer.update()
        props = context.scene.visibility_audit
        results, counts = collect_mismatches(context.scene, context.view_layer, props.exclusions)
        props.results.clear()
        for result in results:
            item = props.results.add()
            for key, value in result.items():
                setattr(item, key, value)
        props.index = 0
        props.checked = counts['checked']
        props.ignored_absorbers = counts['absorbers']
        props.ignored_keywords = counts['keywords']
        props.scanned_exclusions = props.exclusions
        props.scanned_layer = context.view_layer.name
        props.has_scan = True
        self.report({'WARNING'} if results else {'INFO'},
                    f'发现 {len(results)} 个视图/渲染可见性不一致对象；'
                    f'已排除 {counts["absorbers"]} 个吸光体、{counts["keywords"]} 个关键词匹配对象')
        return {'FINISHED'}


class VIEW3D_OT_activate_visibility_result_visn(bpy.types.Operator):
    bl_idname = 'view3d.activate_visibility_result_visn'
    bl_label = '定位检查对象'
    bl_description = '设为活跃对象并在大纲视图中定位，便于调整可见性'
    bl_options = {'INTERNAL'}

    object_name: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    @classmethod
    def description(cls, context, properties):
        props = context.scene.visibility_audit
        result = next((item for item in props.results if item.object
                       and item.object.name == properties.object_name), None)
        return (result.reason + '。点击定位对象，方便调整。') if result else cls.bl_description

    def execute(self, context):
        obj = context.view_layer.objects.get(self.object_name)
        if obj is None or obj.name not in context.scene.objects:
            self.report({'INFO'}, '对象已删除或不在当前视图层，请重新检查')
            return {'CANCELLED'}
        for selected in context.selected_objects:
            selected.select_set(False)
        context.view_layer.objects.active = obj
        if not obj.hide_select and obj.visible_get(view_layer=context.view_layer):
            obj.select_set(True)
        for area in context.screen.areas:
            if area.type == 'OUTLINER':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region:
                    with context.temp_override(area=area, region=region):
                        if bpy.ops.outliner.show_active.poll():
                            bpy.ops.outliner.show_active()
        return {'FINISHED'}


_CLASSES = (VisibilityAuditItem, VisibilityAuditProperties,
            VIEW3D_OT_check_visibility_visn, VIEW3D_OT_activate_visibility_result_visn)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.visibility_audit = PointerProperty(type=VisibilityAuditProperties)


def unregister():
    del bpy.types.Scene.visibility_audit
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
