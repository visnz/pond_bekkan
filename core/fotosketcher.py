"""调用经典版 FotoSketcher 处理 Shader Editor 选中的图片节点。"""
from pathlib import Path
import json
import re
import subprocess
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from .shader_tools import current_material_tree


# 经典版静默命令编号：油漆4/7/9/10/11 为 12/25/17/26/21（按实际出图与用户选择核对）。
PRESETS = {
    'PAINT4': ('Foto大块笔刷', 'Foto大块笔刷', '12', (20, 80, 25, 0, 30),
               ('最小笔刷', '最大笔刷', '笔触数量', '混合强度', '精密笔刷')),
    'PAINT7': ('Foto细条笔刷', 'Foto细条笔刷', '25', (100, 200, 20, 15, 50),
               ('最小笔刷', '最大笔刷', '笔触数量', '边缘强度', '精密笔刷')),
    'WATERCOLOR9': ('Foto点画色块', 'Foto点画色块', '17', (9, 255, 13, 59, 10),
                    ('迭代次数', '笔刷大小', '精细笔刷', '边缘强度', '变暗/变亮')),
    'PAINT10': ('Foto毛躁笔刷', 'Foto毛躁笔刷', '26', (50, 50, 50, 130, 130),
                ('最小笔刷', '迭代次数', '抽象强度', '效果强度', '饱和度')),
    'PAINT11': ('Foto混合笔刷', 'Foto混合笔刷', '21', (50, 300, 30, 5, 200),
                ('最小笔刷', '最大笔刷', '笔触数量', '混合强度', '抽象强度')),
}
_OLD_PRESET_NAMES = {
    'PAINT4': '油漆效果4（笔触）',
    'PAINT7': '油漆效果7（笔触）',
    'WATERCOLOR9': '油漆效果9（水彩）',
    'PAINT10': '油漆效果10（笔触）',
    'PAINT11': '油漆效果11（笔触）',
}
_REFERENCE_SIZE = 2048
_SIZE_SCALED_FIELDS = {'PAINT11': (0, 1)}
_JOBS = {}
_STATUS = {}
_BATCHES = {}
_TREE_STATUS = {}


def _key(tree, node):
    return (tree.name, node.name)


def status_for(context):
    tree, nodes = _selected_image_nodes(context)
    if tree is None:
        return None
    batch = _BATCHES.get(tree.name)
    if batch:
        index = batch['total'] - len(batch['remaining'])
        elapsed = int(time.monotonic() - batch['started'])
        return ('RUNNING', f'处理中 {index}/{batch["total"]} · {elapsed} 秒')
    if tree.name in _TREE_STATUS:
        return _TREE_STATUS[tree.name]
    key = _key(tree, nodes[0]) if len(nodes) == 1 else None
    if key in _STATUS:
        return _STATUS[key]
    return next((value for (tree_name, _), value in reversed(tuple(_STATUS.items()))
                 if tree_name == tree.name), None)


def _redraw_nodes():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()


def _notify_finished(success):
    if bpy.app.background:
        return
    try:
        import winsound
        sound = 'SystemAsterisk' if success else 'SystemExclamation'
        winsound.PlaySound(sound, winsound.SND_ALIAS | winsound.SND_ASYNC)
    except (ImportError, OSError, RuntimeError) as exc:
        print('[pond_bekkan] FotoSketcher 提示音不可用：', exc)


def _executable(folder):
    path = Path(bpy.path.abspath(folder)) / 'FotoSketcher.exe' if folder else None
    return path if path and path.is_file() else None


def _selected_image_nodes(context):
    tree = current_material_tree(context)
    if tree is None or not tree.is_editable:
        return None, []
    nodes = [node for node in tree.nodes if node.select and node.type == 'TEX_IMAGE' and node.image]
    return tree, nodes


def _comment_parameters(comment, preset):
    if comment is None or comment.bl_idname != 'NodeComment':
        return None
    saved_preset = comment.get('_visn_fotosketcher_preset')
    if saved_preset and saved_preset != preset:
        return None
    lines = getattr(comment, 'text', '').splitlines()
    if (not saved_preset and lines
            and not any(name in lines[0] for name in (PRESETS[preset][0], _OLD_PRESET_NAMES[preset]))):
        return None
    for key in ('_visn_fotosketcher_base_parameters', '_visn_fotosketcher_parameters'):
        stored = comment.get(key)
        if stored is not None:
            try:
                values = tuple(int(value) for value in stored)
                if len(values) == 5:
                    return values
            except (TypeError, ValueError):
                pass
    values = []
    for label in PRESETS[preset][4]:
        match = next((re.fullmatch(r'\s*-\s*' + re.escape(label) + r'\s*[：:]\s*(\d+)\s*', line)
                      for line in lines if label in line), None)
        if match is None:
            break
        values.append(int(match.group(1)))
    if len(values) == 5:
        return tuple(values)
    return None


def _effective_parameters(preset, base_parameters, image_size, extra_multiplier):
    if preset not in _SIZE_SCALED_FIELDS:
        return base_parameters, 1.0
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError('无法读取贴图尺寸，请先在 Blender 中载入图片')
    multiplier = max(width, height) / _REFERENCE_SIZE * extra_multiplier
    parameters = list(base_parameters)
    for index in _SIZE_SCALED_FIELDS[preset]:
        value = base_parameters[index]
        parameters[index] = max(1, int(value * multiplier + 0.5)) if value else 0
    return tuple(parameters), multiplier


def _output_path(image, preset, parameters):
    source = Path(bpy.path.abspath(image.filepath)) if image.filepath else None
    if source and source.parent.is_dir() and image.source == 'FILE':
        folder, stem = source.parent, source.stem
    else:
        blend = Path(bpy.data.filepath) if bpy.data.filepath else None
        folder = blend.parent if blend else Path(bpy.app.tempdir)
        stem = Path(image.name).stem
    values = '-'.join(map(str, parameters))
    base = folder / f'{stem}_FotoSketcher_{PRESETS[preset][1]}_{values}'
    # 经典版静默输出始终是 JPEG；传 .png 会写成 .png.jpg。
    output = base.with_suffix('.jpg')
    count = 2
    while output.exists():
        output = folder / f'{base.name}_{count:02d}.jpg'
        count += 1
    return source, output


def _source_path(image, source, output, _scene):
    if source and source.is_file() and image.source == 'FILE' and not image.is_dirty:
        return source, None
    if image.source not in {'FILE', 'GENERATED'}:
        raise ValueError('仅支持普通或打包的单张图片；序列、影片与 UDIM 请先转成单张图片')
    exported = output.with_name(output.stem + '_source.png')
    number = 2
    while exported.exists():
        exported = output.with_name(f'{output.stem}_source_{number:02d}.png')
        number += 1
    copy = image.copy()
    try:
        copy.file_format = 'PNG'
        copy.filepath_raw = str(exported)
        copy.save()
    finally:
        bpy.data.images.remove(copy)
    return exported, exported


def _prepare_1k_image(image):
    if image.source not in {'FILE', 'GENERATED'}:
        raise ValueError('仅支持普通、打包或生成的单张图片')
    width, height = map(int, image.size)
    if width <= 0 or height <= 0:
        raise ValueError('无法读取贴图尺寸')
    if max(width, height) <= 1024:
        return None
    ratio = 1024 / max(width, height)
    new_size = (max(1, round(width * ratio)), max(1, round(height * ratio)))
    source = Path(bpy.path.abspath(image.filepath)) if image.filepath else None
    if source and source.parent.is_dir() and image.source == 'FILE':
        folder, stem = source.parent, source.stem
    else:
        blend = Path(bpy.data.filepath) if bpy.data.filepath else None
        folder = blend.parent if blend else Path(bpy.app.tempdir)
        stem = Path(image.name).stem
    stem = re.sub(r'[\\/:*?"<>|]', '_', stem)
    output = folder / f'{stem}_Foto_1K.png'
    suffix = 2
    while output.exists():
        output = folder / f'{stem}_Foto_1K_{suffix:02d}.png'
        suffix += 1
    copy = image.copy()
    try:
        copy.scale(*new_size)
        if tuple(image.size) != (width, height):
            raise RuntimeError('原图尺寸发生变化，已停止处理')
        copy.file_format = 'PNG'
        copy.filepath_raw = str(output)
        copy.save()
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError('1K 副本没有成功写出')
    finally:
        bpy.data.images.remove(copy)
    result = bpy.data.images.load(str(output), check_existing=False)
    result.colorspace_settings.name = image.colorspace_settings.name
    return result, output, new_size


def _attach_1k_node(tree, source, image):
    outgoing = [(link.from_socket, link.to_socket) for link in tree.links
                if link.from_node == source]
    node = None
    try:
        node = tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        node.label = f'Foto 1K · {image.size[0]}×{image.size[1]}'
        node.parent = source.parent
        node.location = (source.location.x + source.width + 70, source.location.y)
        node.width = source.width
        for attr in ('interpolation', 'projection', 'extension', 'projection_blend'):
            if hasattr(source, attr) and hasattr(node, attr):
                setattr(node, attr, getattr(source, attr))
        vector = source.inputs.get('Vector')
        if vector:
            for link in list(vector.links):
                tree.links.new(link.from_socket, node.inputs['Vector'])
        for from_socket, to_socket in outgoing:
            socket = node.outputs.get(from_socket.name)
            if socket is None:
                raise RuntimeError(f'1K 节点缺少输出插口：{from_socket.name}')
            tree.links.new(socket, to_socket)
    except Exception:
        if node is not None:
            tree.nodes.remove(node)
        for from_socket, to_socket in outgoing:
            tree.links.new(from_socket, to_socket)
        raise
    return node


def _find_tree(material_name, tree_name):
    material = bpy.data.materials.get(material_name)
    if material and material.node_tree and material.node_tree.name == tree_name:
        return material.node_tree
    return bpy.data.node_groups.get(tree_name)


def _finish(job):
    tree = _find_tree(job['material'], job['tree'])
    source = tree.nodes.get(job['node']) if tree else None
    if source is None or source.type != 'TEX_IMAGE':
        raise RuntimeError(f'源图片节点已不存在；结果仍在 {job["output"]}')
    image = bpy.data.images.load(str(job['output']), check_existing=False)
    node = None
    comment = None
    outgoing = [(link.from_socket, link.to_socket) for link in tree.links
                if link.from_node == source]
    try:
        image.colorspace_settings.name = source.image.colorspace_settings.name
        node = tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        node.label = f'FotoSketcher · {job["label"]} · {job["duration"]:.1f} 秒'
        node['_visn_fotosketcher_duration_seconds'] = round(job['duration'], 2)
        node.parent = source.parent
        node.location = (source.location.x + source.width + 70, source.location.y)
        node.width = source.width
        for attr in ('interpolation', 'projection', 'extension', 'projection_blend'):
            if hasattr(source, attr) and hasattr(node, attr):
                setattr(node, attr, getattr(source, attr))
        # 原图保留 Vector，新增节点接相同来源；输出全部转给新增节点。
        vector = source.inputs.get('Vector')
        if vector:
            for link in list(vector.links):
                tree.links.new(link.from_socket, node.inputs['Vector'])
        for from_socket, to_socket in outgoing:
            socket = node.outputs.get(from_socket.name)
            if socket is None:
                raise RuntimeError(f'新贴图缺少输出插口：{from_socket.name}')
            tree.links.new(socket, to_socket)
        if bpy.app.version >= (5, 3, 0):
            try:
                comment = tree.nodes.new('NodeComment')
                comment['_visn_fotosketcher_image'] = image.name
                comment['_visn_fotosketcher_preset'] = job['preset']
                comment['_visn_fotosketcher_parameters'] = list(job['parameters'])
                comment['_visn_fotosketcher_base_parameters'] = list(job['base_parameters'])
                comment['_visn_fotosketcher_extra_multiplier'] = job['extra_multiplier']
                comment['_visn_fotosketcher_duration_seconds'] = round(job['duration'], 2)
                comment.parent = source.parent
                comment.location = (node.location.x, node.location.y + 180)
                comment.width = max(node.width, 260)
                labels = PRESETS[job['preset']][4]
                values = job['parameters']
                comment.text = ('## FotoSketcher · ' + job['label'] + '\n'
                                + f'- 生成耗时：{job["duration"]:.1f} 秒\n'
                                + f'- 贴图尺寸：{job["image_size"][0]} × {job["image_size"][1]}\n'
                                + (f'- 笔刷倍率：{job["size_multiplier"]:.3f}（以 2K 为基准）\n'
                                   if job['preset'] in _SIZE_SCALED_FIELDS else '')
                                + '\n'.join(f'- {label}：{value}'
                                            for label, value in zip(labels, values)))
            except RuntimeError:
                # 5.3 早期构建无 Comment 时，文件名仍保留全部参数。
                comment = None
    except Exception:
        if comment is not None:
            tree.nodes.remove(comment)
        if node is not None:
            tree.nodes.remove(node)
        for from_socket, to_socket in outgoing:
            tree.links.new(from_socket, to_socket)
        if image.users == 0:
            bpy.data.images.remove(image)
        raise
    for item in tree.nodes:
        item.select = item == node
    tree.nodes.active = node
    if job['exported'] and job['exported'].is_file():
        job['exported'].unlink()
    print('[pond_bekkan] FotoSketcher 图片已导入：', job['output'])
    return len(outgoing)


def _stop(job, state, message):
    _JOBS.pop(job['key'], None)
    batch = job['batch']
    batch['done'] += state == 'DONE'
    batch['failed'] += state != 'DONE'
    if state != 'DONE':
        batch['errors'].append(f'{job["node"]}：{message}')
    exported = job.get('exported')
    if exported and exported.is_file():
        try:
            exported.unlink()
        except OSError:
            pass
    _redraw_nodes()
    print('[pond_bekkan] FotoSketcher', state, message)
    _start_next(batch)


def _start_next(batch):
    while batch['remaining']:
        node_name = batch['remaining'].pop(0)
        tree = _find_tree(batch['material'], batch['tree'])
        node = tree.nodes.get(node_name) if tree else None
        scene = bpy.data.scenes.get(batch['scene'])
        try:
            if node is None or node.type != 'TEX_IMAGE' or node.image is None or scene is None:
                raise RuntimeError('图片节点或场景已不存在')
            image_size = tuple(int(value) for value in node.image.size)
            parameters, size_multiplier = _effective_parameters(
                batch['preset'], batch['parameters'], image_size, batch['extra_multiplier'])
            source, output = _output_path(node.image, batch['preset'], parameters)
            source, exported = _source_path(node.image, source, output, scene)
            command = [PRESETS[batch['preset']][2], *map(str, parameters), 'n', 'n', 'n']
            try:
                process = subprocess.Popen([str(batch['exe']), '-silent', str(source), str(output), *command],
                                           cwd=str(batch['exe'].parent))
            except OSError:
                if exported and exported.is_file():
                    exported.unlink()
                raise
        except (OSError, ValueError, RuntimeError) as exc:
            batch['failed'] += 1
            batch['errors'].append(f'{node_name}：{exc}')
            print('[pond_bekkan] FotoSketcher ERROR', batch['errors'][-1])
            continue
        job = {'key': (batch['tree'], node_name), 'batch': batch,
               'process': process, 'output': output,
               'material': batch['material'], 'tree': batch['tree'], 'node': node_name,
               'label': PRESETS[batch['preset']][0], 'preset': batch['preset'],
               'parameters': parameters, 'base_parameters': batch['parameters'],
               'extra_multiplier': batch['extra_multiplier'],
               'image_size': image_size, 'size_multiplier': size_multiplier,
               'exported': exported,
               'started': time.monotonic(), 'stable': 0, 'signature': None}
        _JOBS[job['key']] = job
        bpy.app.timers.register(lambda item=job: _watch(item), first_interval=0.5)
        _redraw_nodes()
        return
    _BATCHES.pop(batch['tree'], None)
    summary = (f'{batch["label"]}：完成 {batch["done"]}/{batch["total"]}'
               f'，总耗时 {time.monotonic() - batch["started"]:.1f} 秒')
    if batch['failed']:
        summary += f'，失败 {batch["failed"]}；{batch["errors"][0]}'
    state = 'ERROR' if batch['failed'] else 'DONE'
    result = (state, summary)
    _TREE_STATUS[batch['tree']] = result
    for name in batch['targets']:
        _STATUS[(batch['tree'], name)] = result
    _redraw_nodes()
    print('[pond_bekkan] FotoSketcher', state, summary)
    _notify_finished(state == 'DONE')


def _watch(job):
    output = job['output']
    try:
        if output.is_file() and output.stat().st_size > 0:
            signature = (output.stat().st_size, output.stat().st_mtime_ns)
            job['stable'] = job['stable'] + 1 if job['signature'] == signature else 0
            job['signature'] = signature
            if job['stable'] >= 3:
                job['duration'] = time.monotonic() - job['started']
                count = _finish(job)
                _stop(job, 'DONE', f'{job["label"]}完成，接管 {count} 条输出连线')
                return None
        exit_code = job['process'].poll()
        elapsed = time.monotonic() - job['started']
        # 经典版可能把任务交给已打开的 FotoSketcher 窗口，启动进程先退出。
        if (exit_code is not None and not output.is_file()
                and elapsed > (5 if exit_code else 60)):
            _stop(job, 'ERROR', f'程序退出但没有生成图片（代码 {job["process"].returncode}）；可重新点击')
            return None
        if time.monotonic() - job['started'] > 900:
            _stop(job, 'ERROR', f'等待超过 15 分钟，未得到完整图片：{output}')
            return None
    except Exception as exc:
        _stop(job, 'ERROR', f'处理或导入失败：{exc}')
        return None
    _redraw_nodes()
    return 0.5


class NODE_OT_fotosketcher_prepare_1k_visn(bpy.types.Operator):
    bl_idname = 'node.fotosketcher_prepare_1k_visn'
    bl_label = '选中贴图生成 1K 副本'
    bl_description = '等比缩小到最长边 1024；原图保留，新节点接管原有连线并自动选中'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        tree, nodes = _selected_image_nodes(context)
        if not nodes:
            cls.poll_message_set('请至少选择一张 Image Texture 节点')
        return bool(nodes)

    def execute(self, context):
        if _BATCHES:
            self.report({'WARNING'}, 'FotoSketcher 正在处理图片，请等待完成')
            return {'CANCELLED'}
        tree, selected = _selected_image_nodes(context)
        if tree is None or not selected:
            self.report({'WARNING'}, '请至少选择一张图片节点')
            return {'CANCELLED'}
        cache = {}
        created = []
        skipped = 0
        errors = []
        for source in selected:
            original = source.image
            try:
                if max(map(int, original.size)) <= 1024:
                    skipped += 1
                    continue
                key = original.as_pointer()
                if key not in cache:
                    cache[key] = _prepare_1k_image(original)
                image, output, _ = cache[key]
                node = _attach_1k_node(tree, source, image)
                node['_visn_fotosketcher_1k_source'] = original.name
                node['_visn_fotosketcher_1k_file'] = str(output)
                created.append(node)
            except Exception as exc:
                errors.append(f'{source.name}：{exc}')
        if created:
            for node in tree.nodes:
                node.select = node in created
            tree.nodes.active = created[-1]
        message = f'已生成 {len(created)} 个 1K 节点，跳过 {skipped} 个'
        if errors:
            message += f'，失败 {len(errors)} 个：{errors[0]}'
        self.report({'WARNING'} if errors else {'INFO'}, message)
        return {'FINISHED'} if created else {'CANCELLED'}


class NODE_OT_fotosketcher_paint11_visn(bpy.types.Operator):
    bl_idname = 'node.fotosketcher_paint11_visn'
    bl_label = 'FotoSketcher 风格化贴图'
    bl_description = '处理所选图片节点；活动备注节点可作为参数起点'
    bl_options = {'REGISTER'}

    directory: StringProperty(name='FotoSketcher 所在文件夹', subtype='DIR_PATH', options={'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})
    preset: EnumProperty(name='效果', items=[
        ('PAINT4', 'Foto大块笔刷', '油漆效果4'),
        ('PAINT7', 'Foto细条笔刷', '油漆效果7'),
        ('WATERCOLOR9', 'Foto点画色块', '油漆效果9'),
        ('PAINT10', 'Foto毛躁笔刷', '油漆效果10'),
        ('PAINT11', 'Foto混合笔刷', '油漆效果11'),
    ], default='PAINT11', options={'SKIP_SAVE'})
    param1: IntProperty(name='参数1', default=10, min=0, max=999, options={'SKIP_SAVE'})
    param2: IntProperty(name='参数2', default=100, min=0, max=999, options={'SKIP_SAVE'})
    param3: IntProperty(name='参数3', default=20, min=0, max=999, options={'SKIP_SAVE'})
    param4: IntProperty(name='参数4', default=0, min=0, max=999, options={'SKIP_SAVE'})
    param5: IntProperty(name='参数5', default=127, min=0, max=999, options={'SKIP_SAVE'})
    extra_multiplier: FloatProperty(name='额外笔刷倍率', default=1.0, min=0.1, max=10.0,
                                    precision=2, options={'SKIP_SAVE'})
    show_parameters: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})
    selected_node_names: StringProperty(default='', options={'HIDDEN', 'SKIP_SAVE'})
    selected_tree_name: StringProperty(default='', options={'HIDDEN', 'SKIP_SAVE'})
    source_note: StringProperty(default='', options={'HIDDEN', 'SKIP_SAVE'})

    def _set_defaults(self):
        for index, value in enumerate(PRESETS[self.preset][3], start=1):
            setattr(self, f'param{index}', value)
        self.extra_multiplier = 1.0

    def draw(self, context):
        layout = self.layout
        layout.label(text=PRESETS[self.preset][0])
        if self.selected_node_names:
            layout.label(text=f'将处理 {len(json.loads(self.selected_node_names))} 张图片节点')
        if self.source_note:
            layout.label(text=self.source_note, icon='INFO')
        for index, label in enumerate(PRESETS[self.preset][4], start=1):
            layout.prop(self, f'param{index}', text=label)
        if self.preset == 'PAINT11':
            layout.separator()
            layout.label(text='以上为 2K 参数；前两项按最长边自动缩放')
            layout.prop(self, 'extra_multiplier')
            tree, _ = _selected_image_nodes(context)
            names = json.loads(self.selected_node_names) if self.selected_node_names else []
            if tree and len(names) == 1:
                node = tree.nodes.get(names[0])
                if node and node.type == 'TEX_IMAGE' and node.image:
                    base = tuple(getattr(self, f'param{index}') for index in range(1, 6))
                    try:
                        applied, multiplier = _effective_parameters(
                            self.preset, base, node.image.size, self.extra_multiplier)
                        layout.label(text=(f'本图 {node.image.size[0]}×{node.image.size[1]} '
                                           f'→ 笔刷 {applied[0]}/{applied[1]}（{multiplier:.2f} 倍）'))
                    except ValueError:
                        pass
            elif len(names) > 1:
                layout.label(text='多图会按各自尺寸分别换算', icon='INFO')

    @classmethod
    def poll(cls, context):
        tree, nodes = _selected_image_nodes(context)
        if not nodes:
            cls.poll_message_set('请至少选择一张 Image Texture 节点')
        return bool(nodes)

    def invoke(self, context, event):
        self._set_defaults()
        tree, nodes = _selected_image_nodes(context)
        self.selected_tree_name = tree.name if tree else ''
        self.selected_node_names = json.dumps([node.name for node in nodes], ensure_ascii=False)
        active = tree.nodes.active if tree else None
        self.source_note = ''
        if active and active.select and active.bl_idname == 'NodeComment':
            values = _comment_parameters(active, self.preset)
            if values is not None:
                for index, value in enumerate(values, start=1):
                    setattr(self, f'param{index}', value)
                if self.preset == 'PAINT11':
                    self.extra_multiplier = float(
                        active.get('_visn_fotosketcher_extra_multiplier', 1.0))
                self.source_note = f'已读取活动备注：{active.name}'
            else:
                self.source_note = '活动备注效果或格式不匹配，使用默认参数'
        prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        if _executable(prefs.fotosketcher_folder):
            self.show_parameters = True
            return context.window_manager.invoke_props_dialog(self, width=380)
        self.directory = prefs.fotosketcher_folder or ''
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        folder = self.directory or prefs.fotosketcher_folder
        exe = _executable(folder)
        if exe is None:
            prefs.fotosketcher_folder = ''
            self.report({'ERROR'}, '所选文件夹没有 FotoSketcher.exe；请重新选择程序所在文件夹')
            return {'CANCELLED'}
        if not self.show_parameters:
            self.show_parameters = True
            return context.window_manager.invoke_props_dialog(self, width=380)
        tree, nodes = _selected_image_nodes(context)
        if tree is None or (self.selected_tree_name and tree.name != self.selected_tree_name):
            self.report({'ERROR'}, '材质节点树已切换，请重新选择后运行')
            return {'CANCELLED'}
        names = json.loads(self.selected_node_names) if self.selected_node_names else [node.name for node in nodes]
        if not names:
            self.report({'WARNING'}, '请至少选择一张图片节点')
            return {'CANCELLED'}
        if _BATCHES:
            self.report({'WARNING'}, '已有 FotoSketcher 任务在处理中，请等待完成')
            return {'CANCELLED'}
        parameters = tuple(getattr(self, f'param{index}') for index in range(1, 6))
        if self.preset in {'PAINT4', 'PAINT7', 'PAINT11'} and parameters[0] > parameters[1]:
            self.report({'ERROR'}, '最小笔刷不能大于最大笔刷')
            return {'CANCELLED'}
        if prefs.fotosketcher_folder != str(exe.parent):
            prefs.fotosketcher_folder = str(exe.parent)
            try:
                bpy.ops.wm.save_userpref()
            except RuntimeError as exc:
                print('[pond_bekkan] FotoSketcher 路径暂未写入偏好文件：', exc)
        batch = {'exe': exe, 'material': context.space_data.id.name,
                 'tree': tree.name, 'scene': context.scene.name,
                 'preset': self.preset, 'parameters': parameters,
                 'extra_multiplier': self.extra_multiplier,
                 'label': PRESETS[self.preset][0], 'targets': names,
                 'remaining': names.copy(), 'total': len(names),
                 'done': 0, 'failed': 0, 'errors': [], 'started': time.monotonic()}
        _TREE_STATUS.pop(tree.name, None)
        for name in names:
            _STATUS.pop((tree.name, name), None)
        _BATCHES[tree.name] = batch
        _start_next(batch)
        if tree.name not in _BATCHES:
            self.report({'ERROR'}, _TREE_STATUS[tree.name][1])
            return {'CANCELLED'}
        self.report({'INFO'}, f'FotoSketcher 已开始处理 {len(names)} 张图片；完成后逐张导入')
        return {'FINISHED'}


def register():
    bpy.utils.register_class(NODE_OT_fotosketcher_prepare_1k_visn)
    bpy.utils.register_class(NODE_OT_fotosketcher_paint11_visn)


def unregister():
    bpy.utils.unregister_class(NODE_OT_fotosketcher_paint11_visn)
    bpy.utils.unregister_class(NODE_OT_fotosketcher_prepare_1k_visn)
