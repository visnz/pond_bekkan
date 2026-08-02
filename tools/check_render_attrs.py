"""诊断脚本：检查当前 Blender 版本的渲染 API 属性
在 Blender 脚本编辑器中运行，或 `python -m tools.check_render_attrs`
列出 RenderSettings / CyclesRenderSettings / SceneEEVEE 的可用属性，
可与 core/render_preset.py 中 _copy_rna_props 的复制范围比对，发现缺失属性。
（随迁自 Bekkan/test_tools/tools/check_render_attrs.py）
"""
import bpy  # type: ignore


def _safe_attrs(obj):
    """获取对象上所有可读属性名"""
    return [a for a in dir(obj) if not a.startswith('_')]


def _check_list(label, src, attrs):
    missing = []
    for a in attrs:
        if not hasattr(src, a):
            missing.append(a)
    print(f"\n--- {label} ---")
    if missing:
        print(f"  缺失 ({len(missing)}): {missing}")
    else:
        print(f"  全部 {len(attrs)} 个属性均存在")


def main():
    s = bpy.context.scene

    render_attrs = [
        'engine',
        'resolution_x', 'resolution_y', 'resolution_percentage',
        'pixel_aspect_x', 'pixel_aspect_y',
        'fps', 'fps_base',
        'frame_map_old', 'frame_map_new',
        'use_motion_blur', 'motion_blur_shutter', 'motion_blur_position',
        'use_border', 'use_crop_to_border',
        'film_transparent',
        'use_persistent_data', 'dither_intensity',
        'views_format',
        'filepath',
        'use_single_layer', 'use_lock_interface',
        'use_overwrite', 'use_file_extension', 'use_render_cache',
        'use_compositing', 'use_sequencer', 'use_stamp',
    ]
    _check_list("RenderSettings", s.render, render_attrs)

    img_attrs = ['file_format', 'color_mode', 'color_depth', 'compression', 'quality']
    _check_list("ImageFormatSettings", s.render.image_settings, img_attrs)

    view_attrs = ['view_transform', 'look', 'exposure', 'gamma']
    _check_list("ColorManagedViewSettings", s.view_settings, view_attrs)

    if hasattr(s, 'cycles'):
        cycles_attrs = [
            'samples',
            'use_denoising', 'denoiser',
            'use_preview_denoising', 'preview_denoiser',
            'use_adaptive_sampling', 'adaptive_threshold', 'adaptive_min_samples',
            'sampling_pattern',
            'use_light_tree',
            'max_bounces',
            'diffuse_bounces', 'glossy_bounces',
            'transmission_bounces', 'volume_bounces',
            'transparent_max_bounces',
            'caustics_reflective', 'caustics_refractive',
            'use_fast_gi',
            'film_exposure',
            'film_transparent_glass', 'film_transparent_roughness',
            'seed', 'use_animated_seed',
            'time_limit', 'pixel_size',
            'preview_samples', 'preview_adaptive_threshold',
            'preview_denoising',
        ]
        _check_list("CyclesRenderSettings", s.cycles, cycles_attrs)
    else:
        print("\n--- Cycles 不可用 ---")

    if hasattr(s, 'eevee'):
        eevee_attrs = [
            'taa_render_samples',
            'use_taa_reprojection',
            'use_raytracing',
            'ray_tracing_method',
            'use_shadows',
            'use_motion_blur',
            'gi_diffuse_bounces', 'gi_cubemap_resolution',
            'use_volumetric_shadows', 'use_volumetric_lights',
            'volumetric_tile_size', 'volumetric_samples',
            'volumetric_start', 'volumetric_end',
            'use_gtao',
            'bokeh_max_size', 'bokeh_threshold',
            'use_ssr', 'use_ssr_halfres',
        ]
        _check_list("SceneEEVEE", s.eevee, eevee_attrs)
        ray_attrs = ['resolution_scale']
        if hasattr(s.eevee, 'ray_tracing_options'):
            _check_list("RaytraceEEVEE", s.eevee.ray_tracing_options, ray_attrs)
        else:
            print("\n--- Eevee 光追不可用 ---")
    else:
        print("\n--- Eevee 不可用 ---")

    print("\n=== 完成 ===\n")


if __name__ == "__main__":
    main()
