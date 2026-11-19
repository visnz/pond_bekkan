"""独立后台实例：隐藏继承、多重链接、排除、手动刷新、工程保存及注册。"""
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
audit = importlib.import_module(ROOT.name + '.core.visibility_audit')
light_probe = importlib.import_module(ROOT.name + '.core.light_probe')
ui = importlib.import_module(ROOT.name + '.ui')
scene = bpy.context.scene
layer = bpy.context.view_layer


def mesh(name, collection=None):
    obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    (collection or scene.collection).objects.link(obj)
    return obj


def collection(name, parent=None):
    col = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(col)
    return col


viewport_only = mesh('Viewport Only')
viewport_only.hide_render = True
render_only = mesh('Render Only')
render_only.hide_viewport = True
eye_hidden = mesh('Eye Hidden')
layer.update()
eye_hidden.hide_set(True, view_layer=layer)
both_hidden = mesh('Both Hidden')
both_hidden.hide_render = both_hidden.hide_viewport = True
ray_hidden = mesh('Camera Ray Disabled')
ray_hidden.visible_camera = False
render_collection = collection('Render Hidden Collection')
render_collection.hide_render = True
render_child = mesh('Render Collection Child', render_collection)
nested = collection('Nested', render_collection)
nested_child = mesh('Nested Child', nested)
view_collection = collection('Viewport Hidden Collection')
view_collection.hide_viewport = True
view_child = mesh('Viewport Collection Child', view_collection)
multi_linked = mesh('Multi Linked', render_collection)
scene.collection.objects.link(multi_linked)
shared_collection = collection('Shared Child Collection', render_collection)
scene.collection.children.link(shared_collection)
shared_child = mesh('Shared Collection Child', shared_collection)
layer_hidden_collection = collection('Layer Eye Hidden Collection')
layer_hidden_child = mesh('Layer Eye Hidden Child', layer_hidden_collection)
excluded_collection = collection('Excluded Collection')
excluded_child = mesh('Excluded Child', excluded_collection)
excluded_child.hide_render = True
layer.update()
layer.layer_collection.children[layer_hidden_collection.name].hide_viewport = True
layer.layer_collection.children[excluded_collection.name].exclude = True

absorber = light_probe.create_ev_absorber(bpy.context)
absorber.name = 'Renamed Automatic Absorber'
legacy_absorber = mesh('EV吸光体_99')
legacy_absorber.hide_render = True
keyword_obj = mesh('AAA_helper')
keyword_obj.hide_render = True
keyword_collection = collection('BBB Helpers')
keyword_collection.hide_render = True
keyword_nested = collection('Helper Descendant', keyword_collection)
keyword_child = mesh('Keyword Collection Child', keyword_nested)
other_scene = bpy.data.scenes.new('Separate Project Settings')
other_mesh = bpy.data.objects.new('Other Scene Mismatch', bpy.data.meshes.new('Other Scene Mismatch'))
other_scene.collection.objects.link(other_mesh)
other_mesh.hide_render = True
scene.visibility_audit.exclusions = ' aaa, BBB ,aaa， '
other_scene.visibility_audit.exclusions = 'ccc'

expected = {viewport_only, render_only, eye_hidden, render_child, nested_child,
            view_child, layer_hidden_child}
layer.update()
before = {o: (o.hide_viewport, o.hide_render, o.hide_select) for o in scene.objects}
selection = set(bpy.context.selected_objects)
active = layer.objects.active
assert bpy.ops.view3d.check_visibility_visn() == {'FINISHED'}
props = scene.visibility_audit
assert {i.object for i in props.results} == expected, [(i.object.name, i.reason) for i in props.results]
assert props.ignored_absorbers == 2 and props.ignored_keywords == 2
assert {o: (o.hide_viewport, o.hide_render, o.hide_select) for o in scene.objects} == before
assert set(bpy.context.selected_objects) == selection and layer.objects.active == active
for item in props.results:
    assert item.viewport_visible != item.render_visible
    assert item.viewport_visible == item.object.visible_get(view_layer=layer)
    assert item.reason
assert 'Render Hidden Collection' in next(i.reason for i in props.results if i.object == nested_child)

# 结果保持上次快照，排除项及对象状态修改不会触发自动扫描。
count = len(props.results)
viewport_only.hide_render = False
props.exclusions = 'aaa,bbb,Eye Hidden'
layer.update()
assert len(props.results) == count
assert next(i for i in props.results if i.object == viewport_only).render_visible is False
assert bpy.ops.view3d.check_visibility_visn() == {'FINISHED'}
assert viewport_only not in {i.object for i in props.results}
assert eye_hidden not in {i.object for i in props.results}
assert props.scanned_exclusions == props.exclusions

# 多条可用路径均可见，不误报；另一个视图层的 exclude 独立。
other_layer = scene.view_layers.new('Alternative Layer')
layer.update()
other_results, _ = audit.collect_mismatches(scene, other_layer, 'aaa,bbb')
assert excluded_child in {i['object'] for i in other_results}
assert eye_hidden not in {i['object'] for i in other_results}  # hide_set 只属于原视图层。
assert multi_linked not in {i['object'] for i in other_results}
assert shared_child not in {i['object'] for i in other_results}

# 定位隐藏对象不会改变其视图/渲染/禁选状态。
assert bpy.ops.view3d.activate_visibility_result_visn(object_name=render_only.name) == {'FINISHED'}
assert layer.objects.active == render_only
assert (render_only.hide_viewport, render_only.hide_render, render_only.hide_select) == before[render_only]

# 不同 Scene 的字段分别随 .blend 保存，读取后无需再次手填。
directory = ROOT / 'temp' / f'visibility-audit{bpy.app.version[0]}{bpy.app.version[1]}'
directory.mkdir(parents=True, exist_ok=True)
main_name = scene.name
saved = scene.visibility_audit.exclusions
filepath = directory / 'exclusions.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(filepath))
bpy.ops.wm.open_mainfile(filepath=str(filepath))
assert bpy.data.scenes[main_name].visibility_audit.exclusions == saved
assert bpy.data.scenes['Separate Project Settings'].visibility_audit.exclusions == 'ccc'
assert audit.exclusion_keywords(' aa, AA，bb,, ') == ('aa', 'bb')

icons = bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys()
assert all(icon in icons for icon in ('VIEWZOOM', 'HIDE_ON', 'HIDE_OFF', 'RESTRICT_RENDER_ON', 'RESTRICT_RENDER_OFF'))
ui.apply_mode('BEKKAN')
assert hasattr(bpy.types, 'BEKKAN_UL_visibility_audit')
ui.apply_mode('POND')
assert not hasattr(bpy.types, 'BEKKAN_UL_visibility_audit')
addon_utils.disable(ROOT.name, default_set=True)
assert not hasattr(bpy.types.Scene, 'visibility_audit')
assert addon_utils.enable(ROOT.name, default_set=True) is not None
assert bpy.data.scenes[main_name].visibility_audit.exclusions == saved
addon_utils.disable(ROOT.name, default_set=True)
print('VISIBILITY_AUDIT_TEST_OK', bpy.app.version_string)
