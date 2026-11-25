"""隔离 GUI：真实调用 P2E、一次撤销/重做，检查原父逆矩阵与集合。"""
import importlib
import json
import math
import os
from pathlib import Path
import sys
import traceback

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
addon = importlib.import_module(ROOT.name)
OUT = ROOT / 'temp' / ('parent-to-empty-ui-' + str(bpy.app.version[1]))
OUT.mkdir(parents=True, exist_ok=True)
state = {'step': 0}

addon.register()
entry = bpy.context.preferences.addons.new()
entry.module = addon.__name__
addon.ui.apply_mode('BEKKAN')
if hasattr(bpy.context.preferences.view, 'show_splash'):
    bpy.context.preferences.view.show_splash = False
scene = bpy.data.scenes.new('P2E regression')
bpy.context.window.scene = scene
parent = bpy.data.objects.new('Original parent', None)
scene.collection.objects.link(parent)
parent.location = (15, 2, 0)
parent.rotation_euler.z = math.radians(30)
parent.scale = (2, 1.5, 1)
bpy.context.view_layer.update()
children = []
for i in range(3):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(4*i, 0, 0))
    child = bpy.context.object
    child.name = 'Child ' + str(i)
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()
    children.append(child)
extra = bpy.data.collections.new('Original extra collection')
scene.collection.children.link(extra)
extra.objects.link(children[0])
for selected in bpy.context.selected_objects:
    selected.select_set(False)
for child in children:
    child.select_set(True)
bpy.context.view_layer.objects.active = children[-1]
bpy.context.view_layer.update()
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.show_region_ui = True
area.spaces.active.region_3d.view_location = (4, 0, 0)
area.spaces.active.region_3d.view_distance = 20


def snapshot():
    bpy.context.view_layer.update()
    return {
        'objects': {obj.name: {
            'parent': obj.parent.name if obj.parent else None,
            'parent_type': obj.parent_type, 'bone': obj.parent_bone,
            'basis': tuple(x for row in obj.matrix_basis for x in row),
            'inverse': tuple(x for row in obj.matrix_parent_inverse for x in row),
            'world': tuple(x for row in obj.matrix_world for x in row),
            'collections': tuple(sorted(col.name for col in obj.users_collection)),
        } for obj in bpy.context.scene.objects},
        'selected': tuple(sorted(obj.name for obj in bpy.context.selected_objects)),
        'active': bpy.context.active_object.name if bpy.context.active_object else None,
    }


def finish(ok, error=None):
    (OUT / 'result.json').write_text(json.dumps({
        'ok': ok, 'error': error, 'blender': bpy.app.version_string,
        'step': state['step'], 'before': state.get('before'),
        'after': state.get('after'),
    }), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if ok else 1)


def advance():
    try:
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            if state['step'] == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                state['before'] = snapshot()
                bpy.ops.ed.undo_push(message='Before P2E')
            elif state['step'] == 1:
                assert bpy.ops.object.parent_to_empty_visn('INVOKE_DEFAULT', True) == {'FINISHED'}
                state['after'] = snapshot()
                empty = bpy.context.active_object
                assert empty.name not in state['before']['objects']
                assert empty.parent.name == 'Original parent'
                assert (empty.matrix_world.translation - Vector((4, 0, 0))).length < 1e-4
                for name, previous in state['before']['objects'].items():
                    current = state['after']['objects'][name]
                    assert current['basis'] == previous['basis'], name
                    assert all(abs(a-b) <= max(1e-5, abs(b)*1e-5)
                               for a, b in zip(current['world'], previous['world'])), name
                    if name.startswith('Child '):
                        assert current['parent'] == empty.name, name
                assert state['after']['selected'] == (empty.name,)
            elif state['step'] == 2:
                bpy.ops.screen.screenshot(filepath=str(OUT / 'grouped.png'))
                bpy.ops.ed.undo()
            elif state['step'] == 3:
                assert snapshot() == state['before'], (snapshot(), state['before'])
                bpy.ops.ed.redo()
            else:
                assert snapshot() == state['after'], (snapshot(), state['after'])
                finish(True)
        state['step'] += 1
        return 1
    except Exception:
        finish(False, traceback.format_exc())


bpy.app.timers.register(advance, first_interval=2)
