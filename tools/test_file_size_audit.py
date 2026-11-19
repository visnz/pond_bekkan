"""隔离后台：真实文件字节、压缩、打包/外部图、共享几何、形态键及只读行为。"""
import gzip
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
assert addon_utils.enable(ROOT.name, default_set=True) is not None
audit = importlib.import_module(ROOT.name + '.core.file_size_audit')
ui = importlib.import_module(ROOT.name + '.ui')
ui.apply_mode('POND')
assert bpy.ops.wm.audit_file_size_visn() == {'CANCELLED'}
directory = ROOT / 'temp' / f'file-size{bpy.app.version[0]}{bpy.app.version[1]}'
directory.mkdir(parents=True, exist_ok=True)

# 同路径两份已打包图是真正重复的数据；外部图的像素缓存不存进工程。
image = bpy.data.images.new('PackedNoise_贴图', width=256, height=256)
image.pixels.foreach_set(np.random.default_rng(5).random(256 * 256 * 4, dtype=np.float32))
image.filepath_raw = str(directory / 'noise.png')
image.file_format = 'PNG'
image.save()
image.pack()
image.use_fake_user = True
duplicate = bpy.data.images.load(image.filepath, check_existing=False)
duplicate.name = 'DuplicatePacked'
duplicate.pack()
duplicate.use_fake_user = True
external = bpy.data.images.load(image.filepath, check_existing=False)
external.name = 'ExternalNoise'
external.use_fake_user = True
missing = bpy.data.images.new('MissingExternal', width=2, height=2)
missing.source = 'FILE'
missing.filepath = str(directory / 'missing.png')
missing.use_fake_user = True

bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
obj = bpy.context.object
mesh = obj.data
mesh.name = '大网格_' + 'LongName_' * 15
obj.shape_key_add(name='Basis')
obj.shape_key_add(name='Extra')
shared = obj.copy()
bpy.context.scene.collection.objects.link(shared)
copy = mesh.copy()
copy.name = 'IndependentMesh'
copy.use_fake_user = True
unused = bpy.data.meshes.new('UnusedMesh')
unused.from_pydata([(i, 0, 0) for i in range(20)], [], [])
unused.use_fake_user = True
# 其他 Scene 的数据也在同一 .blend 内，不只当前可见对象。
other_scene = bpy.data.scenes.new('OtherScene')
other_obj = bpy.data.objects.new('OtherMeshObject', unused)
other_scene.collection.objects.link(other_obj)

raw_path = directory / 'raw.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(raw_path), compress=False)
raw = audit.inspect_file(str(raw_path))
assert raw['disk_bytes'] == raw_path.stat().st_size == raw['raw_bytes']
assert sum(c['bytes'] for c in raw['categories']) == raw['raw_bytes']
assert abs(sum(c['percent'] for c in raw['categories']) - 100) < 1e-6
entries = {(e['code'], e['name']): e for e in raw['entries']}
assert ('ME', mesh.name) in entries
assert len([e for e in raw['entries'] if e['code'] == 'ME' and e['name'] == mesh.name]) == 1
assert entries['ME', mesh.name]['bytes'] > len(mesh.vertices) * 12
assert entries['IM', image.name]['bytes'] >= image.packed_file.size
assert entries['IM', duplicate.name]['bytes'] >= duplicate.packed_file.size
assert entries['IM', external.name]['bytes'] < image.packed_file.size / 4
assert ('KE', mesh.shape_keys.name) in entries
assert ('ME', unused.name) in entries

compressed_path = directory / 'zst.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(compressed_path), compress=True)
compressed = audit.inspect_file(str(compressed_path))
assert compressed['compressed'] and compressed['disk_bytes'] < compressed['raw_bytes']
for category in ('IMAGE', 'GEOMETRY'):
    assert next(c['bytes'] for c in compressed['categories'] if c['key'] == category) == next(
        c['bytes'] for c in raw['categories'] if c['key'] == category)
gzip_path = directory / 'gzip.blend'
with raw_path.open('rb') as src, gzip.open(gzip_path, 'wb') as dest:
    while chunk := src.read(65536):
        dest.write(chunk)
gz = audit.inspect_file(str(gzip_path))
assert gz['compressed'] and gz['raw_bytes'] == raw['raw_bytes']
legacy = audit.inspect_file(str(ROOT / 'core/autoblend_assets/data.blend'))
assert legacy['disk_bytes'] == legacy['raw_bytes']

obj.location.x += 1
bpy.ops.ed.undo_push(message='Size audit dirty-state test')
selection = set(bpy.context.selected_objects)
active = bpy.context.view_layer.objects.active
before = compressed_path.stat()
assert bpy.ops.wm.audit_file_size_visn() == {'FINISHED'}
report = audit.last_report()
assert report['dirty']
assert selection == set(bpy.context.selected_objects)
assert active == bpy.context.view_layer.objects.active
assert before.st_size == compressed_path.stat().st_size and before.st_mtime_ns == compressed_path.stat().st_mtime_ns
detail = next(e['detail'] for e in report['entries'] if e['code'] == 'ME' and e['name'] == mesh.name)
assert '2 个对象共用' in detail and '2 个形态键' in detail
detail = next(e['detail'] for e in report['entries'] if e['name'] == image.name)
assert '同路径' in detail and '无实际引用' in detail
assert report['external_bytes'] == Path(bpy.path.abspath(image.filepath)).stat().st_size
assert len(report['externals']) == 2
assert any('缺失' in e['detail'] for e in report['externals'])
assert bpy.ops.wm.select_size_mesh_visn(mesh_name=mesh.name) == {'FINISHED'}
assert set(bpy.context.selected_objects) == {obj, shared}

bad_path = directory / 'bad.blend'
bad_path.write_bytes(raw_path.read_bytes()[:128])
try:
    audit.inspect_file(str(bad_path))
except Exception:
    pass
else:
    raise AssertionError('Truncated file accepted')

ui.apply_mode('BEKKAN')
assert bpy.types.Operator.bl_rna_get_subclass_py('WM_OT_file_size_report_visn') is not None
ui.apply_mode('POND')
assert bpy.types.Operator.bl_rna_get_subclass_py('WM_OT_file_size_report_visn') is None
addon_utils.disable(ROOT.name, default_set=True)
assert addon_utils.enable(ROOT.name, default_set=True) is not None
addon_utils.disable(ROOT.name, default_set=True)
print('FILE_SIZE_AUDIT_TEST_OK', bpy.app.version_string)
