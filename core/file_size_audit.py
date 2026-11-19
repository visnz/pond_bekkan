# 别馆搭建类：只读最后保存的 .blend，按实际序列化数据块统计体积。
# 压缩文件按解压后字节占比展示，不用显存/像素缓存推算工程大小。
from collections import defaultdict
from pathlib import Path
import re
import struct

import bpy


CATEGORIES = (
    ('IMAGE', '贴图 / 图片'),
    ('GEOMETRY', '几何 / 形态键'),
    ('SHADING', '材质 / 节点 / 世界'),
    ('ANIMATION', '动画 / 骨架'),
    ('SCENE', '场景 / 对象 / 集合'),
    ('OTHER', '其他 / 工作区 / 文件结构'),
)
_CODES = {
    'IMAGE': {b'IM'},
    'GEOMETRY': {b'ME', b'CU', b'CV', b'MB', b'KE', b'PT', b'GP', b'GD'},
    'SHADING': {b'MA', b'NT', b'TE', b'WO', b'LS'},
    'ANIMATION': {b'AC', b'AR'},
    'SCENE': {b'SC', b'OB', b'GR', b'CA', b'LA', b'LP'},
}
_LAST_REPORT = {}


def format_bytes(size):
    value = float(size)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.2f} {unit}' if unit != 'B' else f'{value:.0f} B'
        value /= 1024


def _id_name_layout(dna, endian, pointer_size):
    """从保存文件自己的 SDNA 读取 ID.name 的偏移，不硬编码版本布局。"""
    if dna[:8] != b'SDNANAME':
        raise ValueError('文件缺少有效的数据结构信息')
    u32 = struct.Struct(endian + 'I')
    u16pair = struct.Struct(endian + 'HH')

    def strings(offset, count):
        values = []
        for _ in range(count):
            end = dna.index(b'\0', offset)
            values.append(dna[offset:end].decode('utf-8'))
            offset = end + 1
        return values, (offset + 3) & ~3

    count = u32.unpack_from(dna, 8)[0]
    names, offset = strings(12, count)
    if dna[offset:offset + 4] != b'TYPE':
        raise ValueError('文件 TYPE 信息无效')
    count = u32.unpack_from(dna, offset + 4)[0]
    types, offset = strings(offset + 8, count)
    if dna[offset:offset + 4] != b'TLEN':
        raise ValueError('文件 TLEN 信息无效')
    lengths = struct.unpack_from(endian + 'H' * count, dna, offset + 4)
    offset = (offset + 4 + count * 2 + 3) & ~3
    if dna[offset:offset + 4] != b'STRC':
        raise ValueError('文件 STRC 信息无效')
    count = u32.unpack_from(dna, offset + 4)[0]
    offset += 8
    for _ in range(count):
        type_index, field_count = u16pair.unpack_from(dna, offset)
        offset += 4
        if types[type_index] != 'ID':
            offset += field_count * 4
            continue
        byte_offset = 0
        for _ in range(field_count):
            field_type, field_name = u16pair.unpack_from(dna, offset)
            offset += 4
            name = names[field_name]
            dimensions = [int(n) for n in re.findall(r'\[(\d+)\]', name)]
            elements = 1
            for dimension in dimensions:
                elements *= dimension
            if name.startswith('name['):
                return byte_offset, lengths[field_type] * elements
            # ID.name 前只有指针；如未来结构改变且包含对齐字段则拒绝猜测。
            if '*' not in name:
                raise ValueError('当前文件 ID 结构暂不支持精确名称读取')
            byte_offset += pointer_size * elements
    raise ValueError('文件缺少 ID 名称结构')


def inspect_file(filepath):
    """流式跳过大数据，只保留 ID 前缀和 SDNA；不保存、不加载用户工程。"""
    from _blendfile_header import BlendFileHeader, BlockHeader
    from blend_render_info import RawBlendFileReader

    path = Path(filepath)
    before = path.stat()
    entries = []
    owner = None
    dna = None
    with path.open('rb') as raw:
        magic = raw.read(4)
    compressed = magic[:2] == b'\x1f\x8b' or magic == b'\x28\xb5\x2f\xfd'
    with RawBlendFileReader(str(path)) as stream:
        header = BlendFileHeader(stream)
        block_struct = header.create_block_header_struct()
        overhead = stream.tell()
        while True:
            start = stream.tell()
            block = BlockHeader(stream, block_struct)
            size = stream.tell() - start + block.size
            if block.size < 0:
                raise ValueError('文件数据块大小无效')
            if block.code == b'ENDB':
                overhead += size
                break
            if block.code == b'DATA':
                if owner is None:
                    overhead += size
                else:
                    owner['bytes'] += size
                stream.seek(block.size, 1)
                continue
            owner = None
            if len(block.code) == 2:
                prefix = stream.read(min(block.size, 1024))
                if len(prefix) != min(block.size, 1024):
                    raise ValueError('文件数据块不完整')
                stream.seek(block.size - len(prefix), 1)
                category = next((key for key, codes in _CODES.items() if block.code in codes), 'OTHER')
                owner = {'code': block.code.decode('ascii', errors='replace'),
                         'category': category, 'bytes': size, '_prefix': prefix}
                entries.append(owner)
            elif block.code == b'DNA1':
                if block.size > 16 * 1024 * 1024:
                    raise ValueError('文件数据结构信息异常大')
                dna = stream.read(block.size)
                overhead += size
            else:
                overhead += size
                stream.seek(block.size, 1)
        # 合法文件通常在 ENDB 结束；任何尾部附加字节也纳入总量。
        while tail := stream.read(1024 * 1024):
            overhead += len(tail)
        total = stream.tell()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('文件在检查过程中被保存了，请重新检查')
    if dna is None:
        raise ValueError('文件缺少 DNA 信息，无法完成分类')
    name_offset, name_length = _id_name_layout(
        dna, '<' if header.is_little_endian else '>', header.pointer_size)
    for entry in entries:
        name = entry.pop('_prefix')[name_offset:name_offset + name_length].split(b'\0', 1)[0]
        entry['name'] = name[2:].decode('utf-8', errors='replace')
        entry['percent'] = 100 * entry['bytes'] / total if total else 0
    totals = defaultdict(int)
    totals['OTHER'] += overhead
    for entry in entries:
        totals[entry['category']] += entry['bytes']
    if sum(totals.values()) != total:
        raise ValueError('文件字节校验不一致，请重新检查')
    return {
        'filepath': str(path), 'disk_bytes': before.st_size, 'raw_bytes': total,
        'mtime_ns': before.st_mtime_ns, 'compressed': compressed,
        'categories': [{'key': key, 'label': label, 'bytes': totals[key],
                        'percent': 100 * totals[key] / total} for key, label in CATEGORIES],
        'entries': sorted(entries, key=lambda e: (-e['bytes'], e['name'])),
    }


def _real_users(data):
    return max(0, data.users - int(getattr(data, 'use_fake_user', False)))


def enrich_report(report):
    """附加当前数据引用/拓扑及外部图片说明，与保存文件的大小分开标注。"""
    report['dirty'] = bool(bpy.data.is_dirty)
    images_by_path = defaultdict(list)
    externals = {}
    mesh_instances = defaultdict(int)
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            mesh_instances[obj.data] += 1
    for image in bpy.data.images:
        if getattr(image, 'source', '') not in {'FILE', 'TILED', 'SEQUENCE', 'MOVIE'}:
            continue
        filepath = bpy.path.abspath(image.filepath, library=image.library)
        canonical = str(Path(filepath).resolve()).casefold() if filepath else ''
        if canonical:
            images_by_path[canonical].append(image.name)
        if getattr(image, 'packed_file', None) or len(getattr(image, 'packed_files', ())):
            continue
        # UDIM/序列/影片不能将单个路径大小误作整套总量。
        special = image.source != 'FILE'
        if canonical and canonical not in externals:
            try:
                size = Path(filepath).stat().st_size if not special else 0
                detail = '外部文件，不计入 .blend 占比' if not special else 'UDIM / 序列 / 影片：未统计整套大小'
            except OSError:
                size = 0
                detail = '外部图片缺失或路径无效'
            externals[canonical] = {'name': image.name, 'bytes': size, 'detail': detail,
                                    'filepath': filepath, 'category': 'EXTERNAL', 'code': 'IM', 'percent': 0}
    for entry in report['entries']:
        code, name = entry['code'], entry['name']
        data = None
        detail = []
        if code == 'IM':
            data = bpy.data.images.get(name)
            if data is not None and data.library is None:
                packed = list(getattr(data, 'packed_files', ()))
                packed_bytes = sum(item.packed_file.size for item in packed if item.packed_file)
                if not packed and getattr(data, 'packed_file', None):
                    packed_bytes = data.packed_file.size
                if packed_bytes:
                    detail.append(f'已打包 {format_bytes(packed_bytes)}')
                elif data.source == 'GENERATED':
                    detail.append('生成图片；按已保存内容计算')
                else:
                    detail.append('未打包；占用主要是图片记录')
                if data.has_data:
                    detail.append(f'{data.size[0]} × {data.size[1]}')
                else:
                    detail.append('分辨率信息暂不可用')
                filepath = bpy.path.abspath(data.filepath)
                canonical = str(Path(filepath).resolve()).casefold() if filepath else ''
                if len(images_by_path.get(canonical, ())) > 1:
                    detail.append('同路径存在多份图片数据，检查是否可合并')
        elif code == 'ME':
            data = bpy.data.meshes.get(name)
            if data is not None and data.library is None:
                detail.append(f'{len(data.vertices):,} 顶点 / {len(data.polygons):,} 面')
                detail.append(f'{len(data.uv_layers)} UV / {len(data.attributes)} 属性')
                instances = mesh_instances[data]
                detail.append(f'{instances} 个对象共用（只计一份）')
                if data.shape_keys:
                    detail.append(f'{len(data.shape_keys.key_blocks)} 个形态键（另列体积）')
        elif code == 'KE':
            data = bpy.data.shape_keys.get(name)
            if data is not None:
                detail.append(f'{len(data.key_blocks)} 个形态键；确认未使用的是否可清理')
        else:
            type_name = {'MA': '材质', 'NT': '节点组', 'AC': '动画动作', 'AR': '骨架',
                         'WO': '世界', 'TX': '文本', 'SO': '声音', 'VF': '字体',
                         'CU': '曲线', 'SC': '场景', 'OB': '对象', 'GR': '集合',
                         'CA': '摄像机', 'LA': '灯光', 'WS': '工作区', 'SN': '界面',
                         'WM': '窗口', 'LI': '链接库', 'ID': '链接引用'}.get(code, '工程')
            detail.append(f'{type_name}数据')
            collection_name = {'MA': 'materials', 'NT': 'node_groups', 'AC': 'actions',
                               'AR': 'armatures', 'WO': 'worlds', 'TX': 'texts',
                               'SO': 'sounds', 'VF': 'fonts', 'CU': 'curves',
                               'SC': 'scenes', 'OB': 'objects', 'GR': 'collections'}.get(code)
            collection = getattr(bpy.data, collection_name, None) if collection_name else None
            if collection is not None:
                data = collection.get(name)
        if data is not None and data.library is None:
            users = _real_users(data)
            detail.append(f'{users} 引用')
            if users == 0:
                detail.append('无实际引用，确认后可清理')
            if getattr(data, 'use_fake_user', False):
                detail.append('保留标记')
        entry['detail'] = '；'.join(detail) or '已保存数据；当前无同名本地数据'
    report['externals'] = sorted(externals.values(), key=lambda e: (-e['bytes'], e['name']))
    report['external_bytes'] = sum(e['bytes'] for e in report['externals'])
    return report


def last_report():
    return _LAST_REPORT.get('report')


class WM_OT_audit_file_size_visn(bpy.types.Operator):
    bl_idname = 'wm.audit_file_size_visn'
    bl_label = '检查文件体积占比'
    bl_description = '只读最后保存的 .blend，统计图片、几何等数据体积，列出较大的数据和清理参考'

    def execute(self, context):
        if not bpy.data.filepath:
            self.report({'INFO'}, '请先保存当前工程，再检查文件体积占比')
            return {'CANCELLED'}
        if context.window:
            context.window.cursor_modal_set('WAIT')
        try:
            report = enrich_report(inspect_file(bpy.data.filepath))
        except Exception as exc:
            self.report({'ERROR'}, f'无法检查文件体积：{exc}')
            return {'CANCELLED'}
        finally:
            if context.window:
                context.window.cursor_modal_restore()
        _LAST_REPORT['report'] = report
        if (not bpy.app.background and context.window
                and bpy.types.Operator.bl_rna_get_subclass_py('WM_OT_file_size_report_visn') is not None):
            bpy.ops.wm.file_size_report_visn('INVOKE_DEFAULT')
        else:
            self.report({'INFO'}, f'文件 {format_bytes(report["disk_bytes"])}；体积检查完成')
        return {'FINISHED'}


class WM_OT_select_size_mesh_visn(bpy.types.Operator):
    bl_idname = 'wm.select_size_mesh_visn'
    bl_label = '定位几何体'
    bl_description = '选择当前场景中使用这个网格的可见、可选对象；共用网格不重复计算文件体积'
    bl_options = {'INTERNAL'}

    mesh_name: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        mesh = bpy.data.meshes.get(self.mesh_name)
        objects = [obj for obj in context.view_layer.objects
                   if obj.type == 'MESH' and obj.data == mesh and mesh.library is None
                   and not obj.hide_select and obj.visible_get(view_layer=context.view_layer)] if mesh else []
        if not objects:
            self.report({'INFO'}, '当前视图层没有可见且可选的同名网格对象')
            return {'CANCELLED'}
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        context.view_layer.objects.active = objects[0]
        return {'FINISHED'}


def register():
    bpy.utils.register_class(WM_OT_audit_file_size_visn)
    bpy.utils.register_class(WM_OT_select_size_mesh_visn)


def unregister():
    _LAST_REPORT.clear()
    bpy.utils.unregister_class(WM_OT_select_size_mesh_visn)
    bpy.utils.unregister_class(WM_OT_audit_file_size_visn)
