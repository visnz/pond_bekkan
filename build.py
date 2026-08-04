# build.py — PondBekkan 打包脚本
# 用法：python build.py
# 本仓库根目录即插件包根目录（开发时整体复制/链接进 addons 即可），
# 打包时按白名单只收插件本体文件，产出 dist/ 下四个 zip
# （同一份源码，仅 _build_mode.py 与 bl_info 名称不同）：
#   pond_bekkan_combined.zip   根目录 pond_bekkan   合体版（偏好设置里切蛙灾/别馆，默认蛙灾）
#   Pond_standalone.zip        根目录 Pond          蛙灾独立版（打开即池塘 UI，继承她旧偏好）
#   bekkan_visn_standalone.zip 根目录 bekkan_visn   别馆独立版（打开即别馆 UI，替换旧安装）
#   analyzer_standalone.zip    根目录 analyzer_tool 工程分析独立版（仅含 analyzer 模块）
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT
DIST = ROOT / "dist"
ASSETS = ROOT / "build_assets"

# 插件本体白名单：只有这些会进 zip（仓库其余内容——本脚本/文档/tools/开发计划/dist 等——不收）
PACKAGE_MEMBERS = ("__init__.py", "_build_mode.py", "prefs.py", "core", "ui")

VARIANTS = (
    # (zip文件名, zip内根目录名=包名, bl_info名称, BUILD_MODE)
    ("pond_bekkan_combined.zip", "pond_bekkan", "PondBekkan", "combined"),
    ("Pond_standalone.zip", "Pond", "池塘 Pond", "pond"),
    ("bekkan_visn_standalone.zip", "bekkan_visn", "Bekkan_visn", "bekkan"),
    ("analyzer_standalone.zip", "analyzer_tool", "工程分析", "analyzer"),
)

IGNORE = {"__pycache__", ".git", ".DS_Store"}


def _iter_source_files():
    for name in PACKAGE_MEMBERS:
        p = SRC / name
        if p.is_file():
            # _build_mode.py 由 build_variant() 手动写入，避免重复
            if p.name == "_build_mode.py":
                continue
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_dir():
                    continue
                if any(part in IGNORE for part in f.parts):
                    continue
                if f.suffix == ".pyc":
                    continue
                yield f


def _iter_analyzer_source_files():
    """analyzer 独立版：只取 core/analyzer/ 下的源码"""
    base = SRC / "core" / "analyzer"
    for f in sorted(base.rglob("*")):
        if f.is_dir():
            continue
        if any(part in IGNORE for part in f.parts):
            continue
        if f.suffix == ".pyc":
            continue
        yield f


def _iter_analyzer_asset_files():
    """analyzer 独立版：取 build_assets/analyzer/ 下的最小根文件。

    注意：面板 ui/analyzer_panel.py 不在这里，由 _generate_analyzer_panel()
    从合并版源 ui/bekkan/analyzer_panel.py 在打包时生成，避免正文双副本漂移。
    """
    base = ASSETS / "analyzer"
    for f in sorted(base.rglob("*")):
        if f.is_dir():
            continue
        if any(part in IGNORE for part in f.parts):
            continue
        if f.suffix == ".pyc":
            continue
        yield f


def _generate_analyzer_panel():
    """从合并版源 ui/bekkan/analyzer_panel.py 生成独立版面板文本。

    独立版差异只有 5 处确定文本（基于锚点替换，非正则）：
      - 头注释 → 独立版说明
      - 删 from .prefs import module_enabled（独立版无模块开关）
      - bl_category '别馆' → '工程分析'
      - 删 bl_options = {'DEFAULT_CLOSED'}（独立版默认展开）
      - 删 poll 类方法整块
      - from ...core.analyzer → from ..core.analyzer（独立版 ui/ 是命名空间包、depth=2，3 点会跳过包根）
    正文（draw_item / filter_items / _draw_detail / _draw_fix_buttons / _wrap / _icon）
    保持与合并版完全一致，改 UI 只动合并版一处即可。
    """
    src = (SRC / "ui" / "bekkan" / "analyzer_panel.py").read_text(encoding="utf-8")

    # 1) 头注释：替换开头两行注释块
    old_header = ("# 别馆模式 · 工程分析面板 + 内置表格（迁移自 Bekkan/STOOL_part/Analyzer/ui.py）\n"
                  "# 属性组与操作符在 core/analyzer/。\n")
    new_header = ("# 独立工程分析插件 · 面板（由 build.py 从合并版 ui/bekkan/analyzer_panel.py 生成，勿手改）\n"
                  "# 与合并版的差异：bl_category='工程分析'、无模块开关 poll、默认展开、import 深度 2 点。\n")
    if old_header not in src:
        raise SystemExit("analyzer 面板生成失败：找不到合并版头注释锚点，源文件结构是否变了？")
    src = src.replace(old_header, new_header, 1)

    # 2) 删 module_enabled 导入行（独立版没有模块开关）
    src = src.replace("from .prefs import module_enabled\n", "", 1)

    # 3) bl_category：别馆 → 工程分析
    src = src.replace("bl_category = '别馆'", "bl_category = '工程分析'", 1)

    # 4) 删 bl_options = {'DEFAULT_CLOSED'} 行（独立版默认展开）
    src = src.replace("    bl_options = {'DEFAULT_CLOSED'}\n", "", 1)

    # 5) 删 poll 类方法整块（@classmethod + def poll + return 行）
    poll_block = ("    @classmethod\n"
                 "    def poll(cls, context):\n"
                 "        return module_enabled(\"show_analyzer\")\n")
    if poll_block not in src:
        raise SystemExit("analyzer 面板生成失败：找不到 poll 方法块锚点")
    src = src.replace(poll_block, "", 1)

    # 6) 修 import 深度：独立版 ui/ 是命名空间包（无 __init__.py），位于包根下第 2 层，
    #    3 点会「attempted relative import beyond top-level package」，必须改 2 点。
    src = src.replace("from ...core.analyzer import model, state",
                      "from ..core.analyzer import model, state", 1)

    return src


def _patched_content(path, variant_name, build_mode):
    text = path.read_text(encoding="utf-8")
    if path.name == "_build_mode.py":
        return (f'# 构建标记：本包由 build.py 生成\n'
                f'BUILD_MODE = "{build_mode}"\n')
    if path.name == "__init__.py" and path.parent == SRC:
        # 补丁 bl_info 名称（仅根 __init__.py）
        text = text.replace('"name": "PondBekkan",', f'"name": "{variant_name}",', 1)
    return text


def build_variant(zip_name, pkg_dir, variant_name, build_mode):
    zip_path = DIST / zip_name
    if zip_path.exists():
        zip_path.unlink()
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 写 _build_mode.py
        build_mode_content = (
            f'# 构建标记：本包由 build.py 生成\n'
            f'BUILD_MODE = "{build_mode}"\n'
        )
        zf.writestr(f"{pkg_dir}/_build_mode.py", build_mode_content)
        n += 1

        if build_mode == "analyzer":
            # analyzer 独立版：最小根文件 + core/analyzer + 生成的面板
            for src_file in _iter_analyzer_asset_files():
                rel = src_file.relative_to(ASSETS / "analyzer")
                arc = Path(pkg_dir) / rel
                zf.writestr(str(arc).replace("\\", "/"), src_file.read_text(encoding="utf-8"))
                n += 1
            for src_file in _iter_analyzer_source_files():
                rel = src_file.relative_to(SRC)
                arc = Path(pkg_dir) / rel
                zf.writestr(str(arc).replace("\\", "/"), src_file.read_text(encoding="utf-8"))
                n += 1
            # 面板由合并版源生成（避免正文双副本 + 修独立版 import 深度）
            panel_arc = f"{pkg_dir}/ui/analyzer_panel.py"
            zf.writestr(panel_arc, _generate_analyzer_panel())
            n += 1
        else:
            for src_file in _iter_source_files():
                rel = src_file.relative_to(SRC)
                arc = Path(pkg_dir) / rel
                content = _patched_content(src_file, variant_name, build_mode)
                zf.writestr(str(arc).replace("\\", "/"), content)
                n += 1
    print(f"[ok] {zip_name:<28} 根目录={pkg_dir:<12} 模式={build_mode:<9} 文件数={n}")


def main():
    if not SRC.is_dir():
        raise SystemExit(f"找不到源码目录: {SRC}")
    DIST.mkdir(exist_ok=True)
    for zip_name, pkg_dir, variant_name, build_mode in VARIANTS:
        build_variant(zip_name, pkg_dir, variant_name, build_mode)
    print(f"\n四个版本已产出到 {DIST}")


if __name__ == "__main__":
    main()
