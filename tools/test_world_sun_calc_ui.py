"""一次性隔离 GUI：直接同步、父级 Sun、两种操作的一次撤销/重做。"""
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
calc = importlib.import_module(ROOT.name + '.core.world_sun_calc')
OUT = ROOT / 'temp' / ('world-sun-sync-ui-' + str(bpy.app.version[1]))
OUT.mkdir(parents=True, exist_ok=True)
state = {'step': 0}


addon.register()
entry = bpy.context.preferences.addons.new()
entry.module = addon.__name__
addon.ui.apply_mode('BEKKAN')
if hasattr(bpy.context.preferences.view, 'show_splash'):
    bpy.context.preferences.view.show_splash = False
scene = bpy.context.scene
sky = scene.world.node_tree.nodes.new('ShaderNodeTexSky')
sky.name = 'Sync Sky'
sky.location = (-600, 100)
sky.sky_type = 'MULTIPLE_SCATTERING'
sky.sun_elevation, sky.sun_rotation = math.radians(30.9), math.radians(220)
other_sky = scene.world.node_tree.nodes.new('ShaderNodeTexSky')
other_sky.name = 'Other Sky'
other_sky.location = (-600, -400)
scene.world.node_tree.nodes.active = sky
sky.select = True
other_sky.select = True
sun = scene.objects['Light']
sun.name = 'Sync Sun'
sun.data.type = 'SUN'
parent = bpy.data.objects.new('Offset parent', None)
scene.collection.objects.link(parent)
parent.location = (2, 3, 4)
sun.parent = parent
old_world_position = Vector((1, 2, 5))
expected = Vector(calc.sky_angles_to_position(30.9, 220, old_world_position.length))
sun.location = old_world_position - parent.location
target = bpy.data.objects.new('World origin', None)
scene.collection.objects.link(target)
constraint = sun.constraints.new('TRACK_TO')
constraint.target = target
constraint.track_axis = 'TRACK_NEGATIVE_Z'
constraint.up_axis = 'UP_Y'
other_sun = bpy.data.objects.new('Other Sun', bpy.data.lights.new('Other Sun', 'SUN'))
scene.collection.objects.link(other_sun)
other_sun.location = (6, 7, 8)
for obj in bpy.context.selected_objects:
    obj.select_set(False)
sun.select_set(True)
other_sun.select_set(True)
bpy.context.view_layer.objects.active = sun
bpy.context.view_layer.update()
area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
area.type = 'NODE_EDITOR'
area.spaces.active.tree_type = 'ShaderNodeTree'
area.spaces.active.shader_type = 'WORLD'
area.spaces.active.show_region_ui = True


def snapshot():
    scene = bpy.context.scene
    sky = scene.world.node_tree.nodes['Sync Sky']
    other_sky = scene.world.node_tree.nodes['Other Sky']
    sun = bpy.data.objects['Sync Sun']
    return {'sky': (sky.sun_elevation, sky.sun_rotation),
            'sun': tuple(v for row in sun.matrix_world for v in row),
            'sun_local': tuple(sun.location),
            'parent': tuple(v for row in bpy.data.objects['Offset parent'].matrix_world for v in row),
            'constraint_target': sun.constraints[0].target.name,
            'other_sky': (other_sky.sun_elevation, other_sky.sun_rotation),
            'other_sun': tuple(bpy.data.objects['Other Sun'].location),
            'nodes': len(scene.world.node_tree.nodes), 'links': len(scene.world.node_tree.links),
            'active': bpy.context.active_object.name,
            'selected': tuple(obj.name for obj in bpy.context.selected_objects),
            'active_sky': scene.world.node_tree.nodes.active.name}


def finish(ok, error=None):
    (OUT / 'result.json').write_text(json.dumps({'ok': ok, 'error': error,
        'blender': bpy.app.version_string, 'step': state['step']}), encoding='utf-8')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if ok else 1)


def advance():
    try:
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            if state['step'] == 0:
                next(r for r in area.regions if r.type == 'UI').active_panel_category = '别馆'
                state['before_sky'] = snapshot()
                bpy.ops.ed.undo_push(message='Before Sky to Sun sync')
            elif state['step'] == 1:
                assert bpy.ops.wm.sky_angles_to_sun_coords_visn('INVOKE_DEFAULT', True) == {'FINISHED'}
                sun = bpy.data.objects['Sync Sun']
                assert (calc._world_position(bpy.context, sun) - expected).length < 1e-4
                state['after_sky'] = snapshot()
                for field in ('sky', 'parent', 'constraint_target', 'other_sky', 'other_sun',
                              'nodes', 'links', 'active', 'selected', 'active_sky'):
                    assert state['after_sky'][field] == state['before_sky'][field], field
            elif state['step'] == 2:
                bpy.ops.screen.screenshot(filepath=str(OUT / 'sky-to-sun.png'))
                bpy.ops.ed.undo()
            elif state['step'] == 3:
                assert snapshot() == state['before_sky'], (snapshot(), state['before_sky'])
                bpy.ops.ed.redo()
            elif state['step'] == 4:
                assert snapshot() == state['after_sky']
                sun = bpy.data.objects['Sync Sun']
                matrix = sun.matrix_world.copy()
                matrix.translation = (-2, 3, 8)
                sun.matrix_world = matrix
                sky = bpy.context.scene.world.node_tree.nodes['Sync Sky']
                sky.sun_elevation, sky.sun_rotation = 0.12, 0.3
                bpy.context.view_layer.update()
                state['expected_angles'] = calc.position_to_sky_angles(calc._world_position(bpy.context, sun))[:2]
                state['before_sun'] = snapshot()
                bpy.ops.ed.undo_push(message='Before Sun to Sky sync')
            elif state['step'] == 5:
                assert bpy.ops.wm.sun_coords_to_sky_angles_visn('INVOKE_DEFAULT', True) == {'FINISHED'}
                state['after_sun'] = snapshot()
                assert all(math.isclose(math.degrees(a), b, abs_tol=1e-4) for a, b in
                           zip(state['after_sun']['sky'], state['expected_angles']))
                for field in state['before_sun']:
                    if field != 'sky':
                        assert state['after_sun'][field] == state['before_sun'][field], field
            elif state['step'] == 6:
                bpy.ops.screen.screenshot(filepath=str(OUT / 'sun-to-sky.png'))
                bpy.ops.ed.undo()
            elif state['step'] == 7:
                assert snapshot() == state['before_sun']
                bpy.ops.ed.redo()
            else:
                assert snapshot() == state['after_sun']
                finish(True)
        state['step'] += 1
        return 1
    except Exception:
        finish(False, traceback.format_exc())


bpy.app.timers.register(advance, first_interval=2)
