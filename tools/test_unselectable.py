"""隔离后台测试：blender -b --factory-startup --python-exit-code 1 -P 本文件。

包含测试工程保存/重开，不要在用户现场运行。
"""
import importlib
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
from pond_bekkan.core import unselectable as core
from pond_bekkan.ui.bekkan.unselectable_panel import BEKKAN_UL_unselectable


def shown(scene=None, search=''):
    scene = scene or bpy.context.scene
    mock = SimpleNamespace(filter_name=search, bitflag_filter_item=1)
    flags, order = BEKKAN_UL_unselectable.filter_items(mock, bpy.context, scene, 'objects')
    assert len(flags) == len(scene.objects)
    assert len(order) == len(scene.objects)
    return {o for o, flag in zip(scene.objects, flags) if flag}


def action(obj, value):
    return bpy.ops.object.manage_unselectable_visn(target_uid=str(obj.session_uid), action=value)


def new(name, collection=None):
    obj = bpy.data.objects.new(name, None)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


scene = bpy.context.scene
initial = new('InitiallyLocked')
initial.hide_select = True
ordinary = scene.objects['Cube']
ordinary.display_type = 'WIRE'
addon.register()
registered = True
try:
    assert bpy.app.timers.is_registered(core._initial_display_sync)
    assert core._initial_display_sync() is None  # 后台模式手动执行首次延迟同步。
    assert shown() == {initial}, '启用前已锁定的对象应自动进入列表'
    assert initial.display_type == 'BOUNDS', '启用前已有禁选对象应切为 Bounds'
    assert ordinary.display_type == 'WIRE', '普通可选对象的显示方式不得被覆盖'
    unlocked = new('Unlocked')
    assert unlocked not in shown()
    unlocked.hide_select = True
    bpy.context.view_layer.update()
    assert unlocked.display_type == 'BOUNDS', '外部脚本关闭可选择性也应同步 Bounds'
    assert shown() == {initial, unlocked}, '直接改原生可选择性，无需执行添加/刷新操作'
    unlocked.hide_select = False
    bpy.context.view_layer.update()
    assert unlocked.display_type == 'TEXTURED', '外部解锁应切回 Textured'
    assert shown() == {initial}

    bpy.context.view_layer.update()
    assert action(initial, 'EDIT') == {'FINISHED'}
    assert not initial.hide_select and initial.bekkan_selection_adjusting
    assert initial in shown() and bpy.context.active_object == initial
    assert set(bpy.context.selected_objects) == {initial}
    assert initial.display_type == 'TEXTURED'
    # 列表高亮使用原集合索引；点击列表行也要解锁并切换活跃对象。
    unlocked.hide_select = True
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'UI')
    index = list(scene.objects).index(unlocked)
    scene.bekkan_unselectable_index = index
    assert bpy.context.active_object == initial, '非侧边栏脚本修改索引不得扰动选择'
    assert unlocked.hide_select and not unlocked.bekkan_selection_adjusting
    with bpy.context.temp_override(area=area, region=region):
        scene.bekkan_unselectable_index = index
        assert bpy.context.active_object == unlocked
        assert set(bpy.context.selected_objects) == {unlocked}
        assert not unlocked.hide_select and unlocked.bekkan_selection_adjusting
        assert unlocked.display_type == 'TEXTURED'
        assert action(initial, 'EDIT') == {'FINISHED'}
        scene.bekkan_unselectable_index = index
        assert bpy.context.active_object == unlocked, '同一行再次点击也应激活'
    assert action(unlocked, 'FORGET') == {'FINISHED'}
    assert action(initial, 'EDIT') == {'FINISHED'}
    initial.name = 'RenamedDuringAdjustment'
    assert shown(search='renamed') == {initial}
    assert not shown(search='no-match')
    initial.location = (2, 3, 4)
    assert action(initial, 'LOCK') == {'FINISHED'}
    assert initial.hide_select and not initial.bekkan_selection_adjusting
    assert initial.display_type == 'BOUNDS', '面板锁回应立即显示为 Bounds'
    assert initial in shown() and not initial.select_get()
    assert tuple(initial.location) == (2, 3, 4)
    assert action(initial, 'EDIT') == {'FINISHED'}
    assert action(initial, 'FORGET') == {'FINISHED'}
    assert initial not in shown() and initial in scene.objects.values()
    assert not initial.hide_select
    assert initial.display_type == 'TEXTURED'

    # 隐藏/集合禁选时不解锁、不扰动当前选择；有其他未禁选集合路径时允许。
    blocked_collection = bpy.data.collections.new('SelectionBlockedCollection')
    scene.collection.children.link(blocked_collection)
    blocked_collection.hide_select = True
    blocked = new('CollectionBlockedObject', blocked_collection)
    blocked.hide_select = True
    bpy.context.view_layer.update()
    selected_before = set(bpy.context.selected_objects)
    display_before = blocked.display_type
    assert action(blocked, 'EDIT') == {'CANCELLED'}
    assert blocked.hide_select and not blocked.bekkan_selection_adjusting
    assert set(bpy.context.selected_objects) == selected_before
    assert blocked.display_type == display_before, '激活失败不得改变显示方式'
    scene.collection.objects.link(blocked)
    bpy.context.view_layer.update()
    assert action(blocked, 'EDIT') == {'FINISHED'}
    assert blocked_collection.hide_select, '不得解锁整个集合'
    assert action(blocked, 'LOCK') == {'FINISHED'}
    blocked.hide_set(True)
    assert action(blocked, 'EDIT') == {'CANCELLED'}
    assert blocked.hide_select and blocked.hide_get()
    blocked.hide_set(False)

    # 其他场景不会混入；移出、删除对象无需清理缓存或留下无效指针。
    second_scene = bpy.data.scenes.new('OtherScene')
    other = new('OtherSceneLocked')
    scene.collection.objects.unlink(other)
    second_scene.collection.objects.link(other)
    other.hide_select = True
    assert other not in shown() and shown(second_scene) == {other}
    removable = new('DeletedLocked')
    removable.hide_select = True
    uid = str(removable.session_uid)
    assert removable in shown()
    bpy.data.objects.remove(removable, do_unlink=True)
    assert bpy.ops.object.manage_unselectable_visn(target_uid=uid, action='EDIT') == {'CANCELLED'}
    assert {o.name for o in shown()} == {blocked.name}

    for mode in ('BEKKAN', 'POND', 'BEKKAN'):
        addon.ui.apply_mode(mode)
        panel = bpy.types.Panel.bl_rna_get_subclass_py('BEKKAN_PT_unselectable')
        assert (panel is not None) == (mode == 'BEKKAN')
        assert blocked in shown()
        if panel:
            assert panel.bl_parent_id == '' and panel.bl_order == 0

    assert action(blocked, 'EDIT') == {'FINISHED'}
    kept_name = blocked.name
    with tempfile.TemporaryDirectory(prefix='visn-unselectable-') as folder:
        path = str(Path(folder) / 'unselectable.blend')
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path, use_scripts=False)
        blocked = bpy.context.scene.objects[kept_name]
        assert blocked.bekkan_selection_adjusting and blocked in shown()
        assert not blocked.hide_select
        assert blocked.display_type == 'TEXTURED'
        assert core._on_load in bpy.app.handlers.load_post
        assert action(blocked, 'LOCK') == {'FINISHED'}
        assert blocked.display_type == 'BOUNDS'

    addon.unregister()
    registered = False
    assert core._on_load not in bpy.app.handlers.load_post
    assert core._on_history not in bpy.app.handlers.undo_post
    assert core._on_history not in bpy.app.handlers.redo_post
    assert core._on_depsgraph not in bpy.app.handlers.depsgraph_update_post
    assert not core._display_lock_states
    assert not bpy.app.timers.is_registered(core._initial_display_sync)
    assert not hasattr(bpy.types.Object, 'bekkan_selection_adjusting')
    addon.register()
    registered = True
    assert core._initial_display_sync() is None
    assert bpy.app.handlers.load_post.count(core._on_load) == 1
    assert bpy.app.handlers.undo_post.count(core._on_history) == 1
    assert bpy.app.handlers.depsgraph_update_post.count(core._on_depsgraph) == 1
    assert blocked in shown()
    assert blocked.display_type == 'BOUNDS'
    assert bpy.context.scene.objects['Cube'].display_type == 'WIRE'
    print('PASS_UNSELECTABLE: live filtering, display bounds/textured, search, edit/relock/forget, collections, hidden, scenes, deletion, mode switch, file reload, lifecycle')
finally:
    if registered:
        addon.unregister()
