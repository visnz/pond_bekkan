# build.py — PondBekkan 打包脚本
# 用法：python build.py
# 本仓库根目录即插件包根目录（开发时整体复制/链接进 addons 即可），
# 打包时按白名单只收插件本体文件，产出 dist/ 下三个 zip
# （同一份源码，仅 _build_mode.py 与 bl_info 名称不同）：
#   pond_bekkan_combined.zip  根目录 pond_bekkan  合体版（偏好设置里切蛙灾/别馆，默认蛙灾）
#   Pond_standalone.zip       根目录 Pond         蛙灾独立版（打开即池塘 UI，继承她旧偏好）
#   bekkan_visn_standalone.zip 根目录 bekkan_visn 别馆独立版（打开即别馆 UI，替换旧安装）
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT
DIST = ROOT / "dist"

# 插件本体白名单：只有这些会进 zip（仓库其余内容——本脚本/文档/tools/开发计划/dist 等——不收）
PACKAGE_MEMBERS = ("__init__.py", "_build_mode.py", "prefs.py", "core", "ui")

VARIANTS = (
    # (zip文件名, zip内根目录名=包名, bl_info名称, BUILD_MODE)
    ("pond_bekkan_combined.zip", "pond_bekkan", "PondBekkan", "combined"),
    ("Pond_standalone.zip", "Pond", "池塘 Pond", "pond"),
    ("bekkan_visn_standalone.zip", "bekkan_visn", "Bekkan_visn", "bekkan"),
)

IGNORE = {"__pycache__", ".git", ".DS_Store"}


def _iter_source_files():
    for name in PACKAGE_MEMBERS:
        p = SRC / name
        if p.is_file():
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
    print(f"\n三个版本已产出到 {DIST}")


if __name__ == "__main__":
    main()
