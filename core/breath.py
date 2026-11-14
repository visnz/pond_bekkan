# SPDX-License-Identifier: GPL-3.0-or-later
"""呼吸 · Mixamo体态与NLA（Blender 5.2/5.3）

别馆「绑定动画」面板中创建或更新呼吸。
确认前不修改骨架。「绑定动画」侧栏可开关、调强度、重新匹配或移除。

原骨骼不插关键帧，不改Rest Pose、父级、蒙皮、已有Action/NLA。
骨架自身的独立NLA只动画专用0..1呼吸参数，ADD混合，默认值为0。
局部胸廓缩放和世界Z起伏通过Offset约束叠加，原始姿势通道不插帧。
静音NLA或影响为0即恢复基础姿势；无需先把静态姿势保存为Action。
头肩额外起伏是在继承胸部运动之外的附加量，可设为0。
不依赖Python帧回调或自定义驱动函数；重开后数据仍可求值。
"""
import bpy
import math
import re
import uuid
from bpy.props import StringProperty, FloatProperty, EnumProperty
from bpy_extras import anim_utils

VERSION = '2.0.0'
RIG_ID = '_visn_breath_uuid'
OWNER = '_visn_breath_owner_uuid'
KIND = '_visn_breath_kind'
OLD_TRACK = '呼吸 · 独立参数层'
TRACK = '呼吸 · 缩放与体态叠加'
WAVE = '_visn_breath_wave'
LIFT_PREFIX = '呼吸起伏 · '
CONSTRAINT_PREFIX = '呼吸缩放 · '
AXES = [('X', 'X', '骨骼局部X轴'), ('Y', 'Y', '骨骼局部Y轴（通常沿骨长）'), ('Z', 'Z', '骨骼局部Z轴')]


def rig_from_context(context):
    ob = context.object
    if ob and ob.type == 'ARMATURE':
        return ob
    if ob and ob.type == 'MESH':
        return ob.find_armature()
    if ob and ob.get(OWNER):
        return next((r for r in bpy.data.objects if r.type == 'ARMATURE'
                     and r.get(RIG_ID) == ob.get(OWNER)), None)
    return next((o for o in context.selected_objects if o.type == 'ARMATURE'), None)


def controller_for(rig):
    ident = rig.get(RIG_ID) if rig else None
    if not ident:
        return None
    return next((o for o in bpy.data.objects
                 if o.get(OWNER) == ident and o.get(KIND) == 'CONTROL'), None)


def guess_bones(rig):
    """Mixamo first; never choose a root/hip as a guessed chest."""
    if not rig:
        return '', '', '请先选择骨架'
    def norm(name):
        short = re.split(r'[:|/]', name)[-1]
        return re.sub(r'^mixamorig\d*[:._-]*', '', short, flags=re.I).lower()
    by_short = {}
    for b in rig.data.bones:
        by_short.setdefault(norm(b.name), []).append(b.name)
    chest = next((by_short[n][0] for n in ['spine2', 'spine1', 'spine'] if n in by_short), '')
    abdomen = next((n for key in ['spine', 'spine1'] for n in by_short.get(key, []) if n != chest), '')
    if chest:
        return chest, abdomen, '已按Mixamo名称匹配，请核对骨骼与局部轴'
    # Convenient fallback for the Rigify characters already in this project.
    if 'tweak_spine.004' in rig.pose.bones:
        return 'tweak_spine.004', 'tweak_spine.003' if 'tweak_spine.003' in rig.pose.bones else '', '未发现Mixamo名称；已提供Rigify局部胸廓候选'
    active = rig.data.bones.active
    return (active.name if active else ''), '', '未发现Mixamo名称，请手动匹配胸腔骨'


def guess_motion_bones(rig):
    def norm(name):
        short=re.split(r'[:|/]',name)[-1]
        return re.sub(r'^mixamorig\d*[:._-]*','',short,flags=re.I).lower()
    names={norm(p.name):p.name for p in rig.pose.bones}
    if 'spine2' in names:
        return dict(lift_bone=names['spine2'], head_bone=names.get('head',names.get('neck','')),
                    shoulder_l=names.get('leftshoulder',''), shoulder_r=names.get('rightshoulder',''))
    return {key:name if name in rig.pose.bones else '' for key,name in
            [('lift_bone','chest'),('head_bone','head'),('shoulder_l','shoulder.L'),('shoulder_r','shoulder.R')]}

def rig_for_controller(ctrl):
    return next((o for o in bpy.data.objects if o.type=='ARMATURE' and o.get(RIG_ID)==ctrl.get(OWNER)),None)


def owned_objects(rig):
    ident = rig.get(RIG_ID)
    return [o for o in bpy.data.objects if ident and o.get(OWNER) == ident]


def layer_collection(scene):
    col = next((c for c in bpy.data.collections if c.get(KIND) == 'COLLECTION'), None)
    if col is None:
        col = bpy.data.collections.new('呼吸 · 独立辅助层')
        col[KIND] = 'COLLECTION'
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def new_helper(name, kind, ident, col):
    ob = bpy.data.objects.new(name, None)
    col.objects.link(ob)
    ob[KIND] = kind
    ob[OWNER] = ident
    ob.empty_display_type = 'PLAIN_AXES'
    ob.empty_display_size = .1
    ob.hide_render = True
    # Do not disable the object/collection in the dependency graph.
    ob.hide_set(True)
    return ob


def single_prop(driver, name, controller, prop):
    v = driver.variables.new()
    v.name = name
    v.type = 'SINGLE_PROP'
    v.targets[0].id = controller
    v.targets[0].data_path = '["' + prop + '"]'


def layer_gate(driver, rig):
    for name,path in [('tm','animation_data.nla_tracks["'+TRACK+'"].mute'),
                      ('sm','animation_data.nla_tracks["'+TRACK+'"].strips[0].mute'),
                      ('nla','animation_data.use_nla')]:
        v=driver.variables.new();v.name=name;v.type='SINGLE_PROP'
        v.targets[0].id=rig;v.targets[0].data_path=path


def remove_constraints(rig):
    ident = rig.get(RIG_ID)
    if not ident:
        return
    for bone in rig.pose.bones:
        for con in list(bone.constraints):
            if (con.name.startswith((CONSTRAINT_PREFIX,LIFT_PREFIX))
                    and con.target and con.target.get(OWNER)==ident):
                prefix=con.path_from_id()
                if rig.animation_data:
                    for fc in list(rig.animation_data.drivers):
                        if fc.data_path.startswith(prefix+'.'):
                            rig.animation_data.drivers.remove(fc)
                bone.constraints.remove(con)


def build_cycle(controller, scene):
    """Only rebuild our waveform strip, preserving user-keyed control knobs."""
    period = float(controller['period_seconds']) * scene.render.fps / scene.render.fps_base
    phase = float(controller['phase'])
    begin = float(scene.frame_start) - period * (1. + phase)
    repeats = math.ceil((scene.frame_end - begin + 1.) / period) + 2
    if repeats > bpy.types.NlaStrip.bl_rna.properties['repeat'].hard_max:
        raise ValueError('当前播放范围过长，请缩短播放范围或增加呼吸周期')
    rig=rig_for_controller(controller)
    if rig is None: raise ValueError('呼吸控制器找不到所属骨架')
    if WAVE not in rig: rig[WAVE]=0.0
    rig.id_properties_ui(WAVE).update(default=0.0,min=0.0,max=1.0,description='专用NLA呼吸参数；基础值保持0')
    ad = rig.animation_data_create()
    track = ad.nla_tracks.get(TRACK) or ad.nla_tracks.new()
    track.name = TRACK
    previous = dict(influence=1.,mute=False)
    if track.strips:
        previous=dict(influence=track.strips[0].influence,mute=track.strips[0].mute)
    old_actions = []
    for st in list(track.strips):
        if st.action:
            old_actions.append(st.action)
        track.strips.remove(st)
    action = bpy.data.actions.new('呼吸参数循环 · ' + controller.get('rig_label', controller.name))
    action[KIND] = 'WAVE_ACTION'
    slot = action.slots.new(id_type='OBJECT', name=rig.name)
    bag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
    curve = bag.fcurves.new(data_path='["'+WAVE+'"]', index=0)
    peak = 1. + 100. * float(controller['inhale_ratio'])
    for frame, value in [(1., 0.), (peak, 1.), (101., 0.)]:
        key = curve.keyframe_points.insert(frame, value)
        key.interpolation = 'BEZIER'
        key.handle_left_type = 'AUTO_CLAMPED'
        key.handle_right_type = 'AUTO_CLAMPED'
    curve.update()
    strip = track.strips.new('胸廓呼吸 · 独立参数循环', math.floor(begin), action)
    strip.action_slot = slot
    strip.action_frame_start = 1.
    strip.action_frame_end = 101.
    strip.scale = period / 100.
    strip.repeat = repeats
    strip.frame_start = begin
    strip.blend_type = 'ADD'  # Only a dedicated zero-default custom property.
    strip.extrapolation = 'NOTHING'
    strip.influence = previous['influence']
    strip.mute = previous['mute']
    strip.use_animated_influence = True
    # Blender adds a constant influence F-curve on enabling this flag.
    # Remove that automatic key so the visible Influence slider remains editable.
    for fc in list(strip.fcurves):
        if fc.data_path == 'influence':
            for frame in [k.co.x for k in fc.keyframe_points]:
                strip.keyframe_delete('influence',frame=frame)
    for old in old_actions:
        if old.users == 0 and old.get(KIND) == 'WAVE_ACTION':
            bpy.data.actions.remove(old)
    rig.update_tag()
    controller.update_tag()
    return strip


def create_or_update(rig, chest, abdomen='', width_axis='X', depth_axis='Z',
                     width_percent=1., depth_percent=1.8, length_percent=0.,
                     strength=1., period_seconds=4., phase=0., inhale_ratio=.4,
                     abdomen_ratio=.35, scene=None, lift_bone=None, head_bone=None,
                     shoulder_l=None, shoulder_r=None, chest_lift_mm=8.,
                     head_lift_mm=1.5, shoulder_lift_mm=2.):
    scene = scene or bpy.context.scene
    if not rig or rig.type != 'ARMATURE':
        raise ValueError('请选择骨架对象')
    if rig.mode == 'EDIT':
        raise ValueError('请先退出骨架编辑模式，使用物体模式或姿态模式')
    if rig.library and not rig.override_library:
        raise ValueError('该骨架为只读链接数据，请先建立可编辑覆盖')
    if chest not in rig.pose.bones:
        raise ValueError('胸腔骨不存在，请重新匹配')
    if abdomen and abdomen not in rig.pose.bones:
        raise ValueError('腹部骨不存在，请重新匹配或留空')
    if abdomen == chest:
        raise ValueError('胸腔和腹部不能是同一根骨骼；只用一根骨时请留空腹部')
    if width_axis == depth_axis:
        raise ValueError('宽度轴与厚度轴不能相同')
    if width_axis not in 'XYZ' or depth_axis not in 'XYZ':
        raise ValueError('无效局部轴')
    if period_seconds <= 0. or not .15 <= inhale_ratio <= .8:
        raise ValueError('请检查周期与吸气比例')
    if min(width_percent, depth_percent, length_percent, strength, abdomen_ratio) < 0.:
        raise ValueError('呼吸幅度不能为负')
    period_frames = period_seconds * scene.render.fps / scene.render.fps_base
    begin = scene.frame_start - period_frames * (1. + phase)
    repeats = math.ceil((scene.frame_end - begin + 1.) / period_frames) + 2
    if repeats > bpy.types.NlaStrip.bl_rna.properties['repeat'].hard_max:
        raise ValueError('当前播放范围过长，请缩短播放范围或增加呼吸周期')
    motion=guess_motion_bones(rig)
    supplied=dict(lift_bone=lift_bone,head_bone=head_bone,shoulder_l=shoulder_l,shoulder_r=shoulder_r)
    motion={k:motion[k] if v is None else v for k,v in supplied.items()}
    nonempty=[v for v in motion.values() if v]
    if len(set(nonempty))!=len(nonempty): raise ValueError('起伏角色请分别匹配不同骨骼，或留空')
    for name in nonempty:
        if name not in rig.pose.bones: raise ValueError('起伏骨不存在：'+name)
    if min(chest_lift_mm,head_lift_mm,shoulder_lift_mm)<0: raise ValueError('起伏幅度不能为负')
    # No pose transform channels are keyed or reassigned.
    ident = rig.get(RIG_ID)
    if not ident:
        ident = uuid.uuid4().hex
        rig[RIG_ID] = ident
    col = layer_collection(scene)
    ctrl = controller_for(rig) or new_helper('呼吸控制 · ' + rig.name, 'CONTROL', ident, col)
    if ctrl.name not in col.objects:
        col.objects.link(ctrl)
    defaults = {'enabled': True, 'wave': 0.}
    for k, v in defaults.items():
        if k not in ctrl:
            ctrl[k] = v
    values = dict(rig_label=rig.name, chest=chest, abdomen=abdomen,
                  width_axis=width_axis, depth_axis=depth_axis,
                  width_percent=width_percent, depth_percent=depth_percent,
                  length_percent=length_percent, strength=strength,
                  period_seconds=period_seconds, phase=phase, inhale_ratio=inhale_ratio,
                  abdomen_ratio=abdomen_ratio, tool_version=VERSION)
    for k, value in values.items():
        ctrl[k] = value
    labels = {'strength': (0., 5., '总幅度；允许大于1'),
              'width_percent': (0., 10., '胸廓宽度扩张百分比'),
              'depth_percent': (0., 10., '胸廓前后厚度扩张百分比'),
              'length_percent': (0., 5., '骨长方向扩张百分比；默认0'),
              'abdomen_ratio': (0., 1., '腹部相对于胸腔的幅度比例'),
              'period_seconds': (.5, 30., '周期秒数；修改后点击更新周期'),
              'phase': (-1., 1., '相位（一个周期为1）；修改后点击更新周期'),
              'inhale_ratio': (.15, .8, '吸气占周期的比例；修改后点击更新周期')}
    for k, (lo, hi, desc) in labels.items():
        ctrl.id_properties_ui(k).update(min=lo, max=hi, soft_min=lo, soft_max=hi, description=desc)
    for k,v in dict(**motion,chest_lift_mm=chest_lift_mm,head_lift_mm=head_lift_mm,shoulder_lift_mm=shoulder_lift_mm).items():
        ctrl[k]=v
    for k in ['chest_lift_mm','head_lift_mm','shoulder_lift_mm']:
        ctrl.id_properties_ui(k).update(min=0.,max=100.,soft_max=25.,description='世界空间毫米；头肩是在胸部继承量之外的附加起伏')
    # Migrate only the former tool-owned helper waveform.
    if ctrl.animation_data:
        old_track=ctrl.animation_data.nla_tracks.get(OLD_TRACK)
        if old_track:
            old_actions=[st.action for st in old_track.strips if st.action]
            ctrl.animation_data.nla_tracks.remove(old_track)
            for action in old_actions:
                if action.users==0 and action.get(KIND)=='WAVE_ACTION': bpy.data.actions.remove(action)
    build_cycle(ctrl, scene)
    remove_constraints(rig)
    axis_props = {width_axis: 'width_percent', depth_axis: 'depth_percent'}
    axis_props[next(a for a in 'XYZ' if a not in axis_props)] = 'length_percent'
    used = {'CONTROL'}
    for role, bone_name in [('CHEST', chest), ('ABDOMEN', abdomen)]:
        if not bone_name:
            continue
        used.add(role)
        helper = next((o for o in owned_objects(rig) if o.get(KIND) == role), None)
        if helper is None:
            helper = new_helper('呼吸倍率 · ' + role + ' · ' + rig.name, role, ident, col)
        if helper.name not in col.objects:
            col.objects.link(helper)
        for axis, axis_name in enumerate('XYZ'):
            helper.driver_remove('scale', axis)
            fc = helper.driver_add('scale', axis)
            d = fc.driver
            d.type = 'SCRIPTED'
            single_prop(d,'amp',ctrl,axis_props[axis_name])
            d.expression='1.0+amp/100.0'
        con = rig.pose.bones[bone_name].constraints.new('COPY_SCALE')
        con.name = CONSTRAINT_PREFIX + ('胸腔' if role == 'CHEST' else '腹部')
        con.target = helper
        con.target_space = 'LOCAL'
        con.owner_space = 'LOCAL'
        con.use_offset = True
        con.use_add = False
        con.use_make_uniform = False
        con.power = 1.
        d=con.driver_add('power').driver
        d.type='SCRIPTED'
        single_prop(d,'wave',rig,WAVE)
        single_prop(d,'st',ctrl,'strength')
        if role=='ABDOMEN': single_prop(d,'ratio',ctrl,'abdomen_ratio')
        d.expression='max(0.0,wave)*st'+('*ratio' if role=='ABDOMEN' else '')
        d=con.driver_add('influence').driver
        d.type='SCRIPTED'
        single_prop(d,'en',ctrl,'enabled'); single_prop(d,'st',ctrl,'strength');single_prop(d,'wave',rig,WAVE)
        layer_gate(d,rig)
        d.expression='(en>0.5)*(st>0.0)*(wave>0.0)*(tm<0.5)*(sm<0.5)*(nla>0.5)'
        helper.update_tag()
    for role,key,amp in [('LIFT','lift_bone','chest_lift_mm'),('HEAD','head_bone','head_lift_mm'),
                         ('SHOULDER_L','shoulder_l','shoulder_lift_mm'),('SHOULDER_R','shoulder_r','shoulder_lift_mm')]:
        name=motion[key]
        if not name: continue
        used.add(role)
        helper=next((o for o in owned_objects(rig) if o.get(KIND)==role),None)
        if helper is None: helper=new_helper('呼吸起伏量 · '+role+' · '+rig.name,role,ident,col)
        helper.location=(0.,0.,0.)
        helper.driver_remove('location',2)
        d=helper.driver_add('location',2).driver;d.type='SCRIPTED'
        single_prop(d,'amp',ctrl,amp);single_prop(d,'st',ctrl,'strength')
        d.expression='amp*st/'+repr(1000.*scene.unit_settings.scale_length)
        con=rig.pose.bones[name].constraints.new('COPY_LOCATION')
        con.name=LIFT_PREFIX+role
        con.target=helper;con.owner_space='WORLD';con.target_space='WORLD'
        con.use_offset=True;con.use_x=False;con.use_y=False;con.use_z=True
        d=con.driver_add('influence').driver;d.type='SCRIPTED'
        single_prop(d,'en',ctrl,'enabled');single_prop(d,'wave',rig,WAVE)
        layer_gate(d,rig)
        d.expression='(en>0.5)*min(1.0,max(0.0,wave))*(tm<0.5)*(sm<0.5)*(nla>0.5)'
        helper.update_tag()
    for old in owned_objects(rig):
        if old.get(KIND) not in used:
            bpy.data.objects.remove(old, do_unlink=True)
    rig.update_tag()
    ctrl.update_tag()
    bpy.context.view_layer.update()
    return ctrl


def remove_layer(rig):
    ctrl = controller_for(rig)
    if not ctrl:
        return False
    actions=[]
    if rig.animation_data:
        track=rig.animation_data.nla_tracks.get(TRACK)
        if track:
            actions=[st.action for st in track.strips if st.action]
            rig.animation_data.nla_tracks.remove(track)
    if WAVE in rig: del rig[WAVE]
    remove_constraints(rig)
    for ob in owned_objects(rig):
        bpy.data.objects.remove(ob, do_unlink=True)
    if RIG_ID in rig:
        del rig[RIG_ID]
    for act in actions:
        if act.users == 0 and act.get(KIND) == 'WAVE_ACTION':
            bpy.data.actions.remove(act)
    for col in list(bpy.data.collections):
        if col.get(KIND) == 'COLLECTION' and len(col.objects) == 0:
            bpy.data.collections.remove(col)
    rig.update_tag()
    return True


def load_dialog(self, context):
    rig = bpy.data.objects.get(self.rig_name)
    if not rig or rig.type != 'ARMATURE':
        return
    ctrl = controller_for(rig)
    if ctrl:
        for key,value in guess_motion_bones(rig).items():
            if key not in ctrl: setattr(self,key,value)
        for key in ['chest', 'abdomen', 'width_axis', 'depth_axis', 'width_percent',
                    'depth_percent', 'length_percent', 'strength', 'period_seconds',
                    'phase', 'inhale_ratio', 'abdomen_ratio', 'lift_bone','head_bone','shoulder_l','shoulder_r',
                    'chest_lift_mm','head_lift_mm','shoulder_lift_mm']:
            if key in ctrl:
                setattr(self, key, ctrl[key])
        self.match_info = '已载入该骨架的现有呼吸设置；确认后更新，不重复叠加'
    else:
        self.chest, self.abdomen, self.match_info = guess_bones(rig)
        for k,v in guess_motion_bones(rig).items(): setattr(self,k,v)


class VISN_BREATH_OT_setup(bpy.types.Operator):
    bl_idname = 'visn_breath.setup'
    bl_label = '呼吸 · 骨骼匹配与NLA层'
    bl_options = {'REGISTER', 'UNDO'}

    # Operators do not support ID PointerProperty. Resolve a searchable name
    # rather than storing a data-block reference on the operator.
    rig_name: StringProperty(name='骨架', update=load_dialog)
    lift_bone: StringProperty(name='胸部起伏骨（可留空）')
    head_bone: StringProperty(name='头部起伏骨（可留空）')
    shoulder_l: StringProperty(name='左肩骨（可留空）')
    shoulder_r: StringProperty(name='右肩骨（可留空）')
    chest_lift_mm: FloatProperty(name='胸部抬升（毫米）',default=8.,min=0.,max=100.)
    head_lift_mm: FloatProperty(name='头部额外抬升（毫米）',default=1.5,min=0.,max=100.)
    shoulder_lift_mm: FloatProperty(name='双肩额外抬升（毫米）',default=2.,min=0.,max=100.)
    chest: StringProperty(name='胸腔形变骨')
    abdomen: StringProperty(name='腹部骨（可留空）')
    match_info: StringProperty(options={'SKIP_SAVE'})
    width_axis: EnumProperty(name='宽度轴', items=AXES, default='X')
    depth_axis: EnumProperty(name='厚度轴', items=AXES, default='Z')
    width_percent: FloatProperty(name='宽度扩张（%）', default=1., min=0., max=10.)
    depth_percent: FloatProperty(name='厚度扩张（%）', default=1.8, min=0., max=10.)
    length_percent: FloatProperty(name='长度扩张（%）', default=0., min=0., max=5.)
    strength: FloatProperty(name='总幅度', default=1., min=0., max=5., soft_max=3.)
    period_seconds: FloatProperty(name='周期（秒）', default=4., min=.5, max=30.)
    phase: FloatProperty(name='相位（周期）', default=0., min=-1., max=1.)
    inhale_ratio: FloatProperty(name='吸气比例', default=.4, min=.15, max=.8)
    abdomen_ratio: FloatProperty(name='腹部幅度比例', default=.35, min=0., max=1.)

    def invoke(self, context, event):
        rig = rig_from_context(context)
        self.rig_name = rig.name if rig else ''
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        lay.prop_search(self, 'rig_name', bpy.data, 'objects', text='骨架')
        rig = bpy.data.objects.get(self.rig_name)
        if not rig or rig.type != 'ARMATURE':
            lay.label(text='选择骨架，默认按Mixamo名称匹配', icon='INFO')
            return
        lay.label(text=self.match_info, icon='INFO')
        lay.prop_search(self, 'chest', rig.data, 'bones')
        lay.prop_search(self, 'abdomen', rig.data, 'bones')
        for key in ['lift_bone','head_bone','shoulder_l','shoulder_r']:
            lay.prop_search(self,key,rig.data,'bones')
        for key in ['chest_lift_mm','head_lift_mm','shoulder_lift_mm']: lay.prop(self,key)
        box = lay.box()
        box.label(text='局部轴：骨骼Y轴通常沿骨长', icon='ORIENTATION_LOCAL')
        row = box.row(); row.prop(self, 'width_axis'); row.prop(self, 'depth_axis')
        for key in ['width_percent', 'depth_percent', 'length_percent', 'strength', 'abdomen_ratio']:
            box.prop(self, key)
        for key in ['period_seconds', 'phase', 'inhale_ratio']:
            lay.prop(self, key)
        lay.label(text='NLA只动画呼吸参数；保留手动姿势与已有动画', icon='CHECKMARK')
        lay.label(text='子骨可能继承缩放；默认小幅使用，优先局部胸廓骨', icon='INFO')

    def execute(self, context):
        try:
            create_or_update(rig=bpy.data.objects.get(self.rig_name), **{k: getattr(self, k) for k in [
                'chest', 'abdomen', 'width_axis', 'depth_axis', 'width_percent',
                'depth_percent', 'length_percent', 'strength', 'period_seconds',
                'phase', 'inhale_ratio', 'abdomen_ratio','lift_bone','head_bone','shoulder_l','shoulder_r',
                'chest_lift_mm','head_lift_mm','shoulder_lift_mm']}, scene=context.scene)
        except (ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已创建/更新体态呼吸NLA层；「绑定动画」面板可开关和调参')
        return {'FINISHED'}


class VISN_BREATH_OT_refresh(bpy.types.Operator):
    bl_idname = 'visn_breath.refresh'
    bl_label = '更新周期 / 相位'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ctrl = controller_for(rig_from_context(context))
        if ctrl is None:
            return {'CANCELLED'}
        build_cycle(ctrl, context.scene)
        context.view_layer.update()
        return {'FINISHED'}


class VISN_BREATH_OT_remove(bpy.types.Operator):
    bl_idname = 'visn_breath.remove'
    bl_label = '移除该骨架的呼吸层'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        remove_layer(rig_from_context(context))
        self.report({'INFO'}, '已移除本工具的呼吸层，原姿势和原动画保留')
        return {'FINISHED'}


class VISN_BREATH_OT_view_layer(bpy.types.Operator):
    bl_idname = 'visn_breath.view_layer'
    bl_label = '查看角色呼吸NLA'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = rig_from_context(context)
        ctrl = controller_for(rig)
        if ctrl is None:
            return {'CANCELLED'}
        destination = rig
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for ob in context.selected_objects:
            ob.select_set(False)
        destination.hide_set(False)
        destination.select_set(True)
        context.view_layer.objects.active = destination
        track=rig.animation_data.nla_tracks.get(TRACK)
        if track:
            rig.animation_data.nla_tracks.active=track
            track.select=True
            for strip in track.strips: strip.select=True
        for area in context.screen.areas:
            if area.type=='NLA_EDITOR':
                area.spaces.active.dopesheet.show_only_selected=True
                region=next((r for r in area.regions if r.type=='WINDOW'),None)
                if region:
                    with context.temp_override(area=area,region=region): bpy.ops.nla.view_selected()
        return {'FINISHED'}


CLASSES = (VISN_BREATH_OT_setup, VISN_BREATH_OT_refresh,
           VISN_BREATH_OT_remove, VISN_BREATH_OT_view_layer)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
