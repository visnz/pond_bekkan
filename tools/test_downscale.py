"""贴图缩小工具诊断脚本

后台运行：blender --background --factory-startup --python tools/test_downscale.py
（本机 blender 不在 PATH，用全路径 "d:/SteamLibrary/steamapps/common/Blender/blender.exe"）。

自带头部把 core/ 加进 sys.path，直接 import analyzer 包，绕开现有 test_analyzer.py
相对 import 在 CLI 下解析不了的坏点。

覆盖：
  T1 前置拦截   未保存工程时拒绝运行并给 reason
  T2 pack_keep  缩小+打包+原图副本落在 .blend 旁
  T3 pack_delete 缩小+打包+删除磁盘源文件
  T4 幂等       已 ≤ 目标的图不被处理
  T5 计数        count_big_textures 的 >4K/>2K 口径
  T6 缓存        场景缓存 get/update_downscale_report 命中与失效
"""
import os
import shutil
import sys
import tempfile

_CORE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

import bpy  # noqa: E402

from analyzer import fixes  # noqa: E402
import analyzer as analyzer_mod  # noqa: E402


_TMP = tempfile.mkdtemp(prefix="analyzer_downscale_")


def _setup():
    """注册 analyzer core（拿 scene.analyzer_props）。"""
    if not hasattr(bpy.types.Scene, "analyzer_props"):
        analyzer_mod.register()


def _make_generated(name, size=4096):
    img = bpy.data.images.new(name, size, size)
    _ = img.pixels[:1]  # 强制物化缓冲
    return img


def _remove_img(img):
    if img.name in bpy.data.images:
        bpy.data.images.remove(img)


def test_mode_keep():
    print("\n[2] pack_keep：缩小+打包+原图副本在 .blend 旁")
    _setup()
    img = _make_generated("BigKeep")
    # bpy.data.filepath 在 5.2 是只读，用真实保存制造「已保存工程」
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(_TMP, "fake.blend"))
    try:
        fixed, skipped, info = fixes.fix_downscale_textures(bpy.context, 2048, 'pack_keep')
        dest = os.path.join(_TMP, "贴图备份", "BigKeep_原图.png")
        ok = (fixed == 1 and tuple(img.size) == (2048, 2048)
              and img.packed_file is not None and os.path.exists(dest))
        print(f"  fixed={fixed} skipped={skipped} size={tuple(img.size)} "
              f"packed={img.packed_file is not None} 副本={os.path.exists(dest)}")
        return ok
    except Exception:
        import traceback
        traceback.print_exc()
        return False
    finally:
        _remove_img(img)


def test_mode_delete():
    print("\n[3] pack_delete：缩小+打包+原地覆盖磁盘源文件")
    _setup()
    src = os.path.join(_TMP, "src_big.png")
    seed = _make_generated("SrcSeed")
    seed.file_format = 'PNG'
    seed.save_render(src)
    _remove_img(seed)
    img = bpy.data.images.load(src)
    try:
        fixed, skipped, info = fixes.fix_downscale_textures(bpy.context, 2048, 'pack_delete')
        ok = (fixed == 1 and os.path.exists(src) and img.packed_file is not None
              and info.get("overwritten") == 1)
        print(f"  fixed={fixed} overwritten={info.get('overwritten')} "
              f"源仍存在={os.path.exists(src)} packed={img.packed_file is not None}")
        return ok
    except Exception:
        import traceback
        traceback.print_exc()
        return False
    finally:
        _remove_img(img)


def test_gate_unsaved():
    print("\n[1] 未保存工程 → 拒绝并给 reason")
    _setup()
    try:
        fixed, skipped, info = fixes.fix_downscale_textures(bpy.context, 2048, 'pack_keep')
        ok = (fixed == 0 and skipped == 1 and info.get("reason"))
        print(f"  fixed={fixed} skipped={skipped} reason={'有' if info.get('reason') else '无'}")
        return ok
    except Exception:
        import traceback
        traceback.print_exc()
        return False


def test_idempotent_small():
    print("\n[4] 已达标小图不被处理（幂等）")
    _setup()
    img = _make_generated("BigSmall", size=1024)
    try:
        fixed, skipped, info = fixes.fix_downscale_textures(bpy.context, 2048, 'pack_keep')
        ok = (fixed == 0 and tuple(img.size) == (1024, 1024))
        print(f"  fixed={fixed} size={tuple(img.size)}")
        return ok
    finally:
        _remove_img(img)


def test_count():
    print("\n[5] count_big_textures 计数口径")
    _setup()
    imgs = []
    try:
        imgs.append(_make_generated("Cnt4096", 4096))   # 只 >2K
        imgs.append(_make_generated("Cnt8192", 8192))   # >4K
        imgs.append(_make_generated("Cnt3072", 3072))   # 只 >2K
        n4, n2 = fixes.count_big_textures()
        ok = (n4 == 1 and n2 == 3)
        print(f"  n4={n4} n2={n2}（期望 n4=1 n2=3）")
        return ok
    finally:
        for img in imgs:
            _remove_img(img)


def test_cache():
    print("\n[6] 场景缓存 get/update_downscale_report 命中与失效")
    _setup()
    props = bpy.context.scene.analyzer_props
    props.downscale_total = -1
    img = None
    try:
        r0 = fixes.get_downscale_report(props)      # 未计算 → None
        fixes.update_downscale_report(props, 1, 3)
        r1 = fixes.get_downscale_report(props)      # 图片数一致 → 命中
        img = _make_generated("CacheBig", 4096)
        r2 = fixes.get_downscale_report(props)      # 图片总数变了 → 失效
        ok = (r0 is None and r1 == (1, 3) and r2 is None)
        print(f"  未计算=None:{r0 is None} 命中={r1} 增图后失效:{r2 is None}")
        return ok
    finally:
        if img:
            _remove_img(img)
        props.downscale_total = -1


def run_all():
    print("=" * 60)
    print("贴图缩小工具诊断")
    print("=" * 60)
    results = [
        ("未保存工程前置拦截", test_gate_unsaved()),
        ("pack_keep 缩小+副本", test_mode_keep()),
        ("pack_delete 删源", test_mode_delete()),
        ("小图幂等跳过", test_idempotent_small()),
        ("计数口径", test_count()),
        ("场景缓存", test_cache()),
    ]
    print("\n" + "=" * 60)
    print("结果汇总")
    print("=" * 60)
    for name, ok in results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    shutil.rmtree(_TMP, ignore_errors=True)
    all_ok = all(ok for _, ok in results)
    print(f"\n总体: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
