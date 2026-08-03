import os
import re
import subprocess
import difflib
from pathlib import Path

ROOT = Path(__file__).parent.parent
CURRENT_DIRS = ["core", "ui"]
OLD_COMMIT = "a3283fa"


def git_show(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{OLD_COMMIT}:{path}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def normalize(text: str) -> list:
    """忽略空行和行首缩进/注释，提取可比较的逻辑行。"""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def similarity(a: list, b: list) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def list_old_files():
    out = subprocess.run(
        ["git", "ls-tree", "-r", OLD_COMMIT, "--name-only"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout.splitlines()
    pond = [p for p in out if p.startswith("Pond/") and p.endswith(".py")]
    bekkan = [p for p in out if p.startswith("Bekkan/") and p.endswith(".py")]
    return pond, bekkan


def main():
    pond_files, bekkan_files = list_old_files()
    all_old = [("Pond", p) for p in pond_files] + [("Bekkan", p) for p in bekkan_files]

    print("# PondBekkan 模块来源分析报告\n")
    print("基于 commit `a3283fa`（初版本合并预备）与当前工作区文件逐行相似度计算。\n")
    print("| 当前文件 | 最相似原始文件 | 来源 | 当前行数 | 原始行数 | 逻辑相似度 | 结论 |")
    print("|---|---|---|---|---|---|---|")

    rows = []
    for cur_dir in CURRENT_DIRS:
        for cur_path in sorted((ROOT / cur_dir).rglob("*.py")):
            rel = cur_path.relative_to(ROOT).as_posix()
            cur_text = cur_path.read_text(encoding="utf-8", errors="replace")
            cur_norm = normalize(cur_text)

            best_src, best_old, best_ratio = None, None, 0.0
            for src, old in all_old:
                old_text = git_show(old)
                if not old_text:
                    continue
                old_norm = normalize(old_text)
                r = similarity(cur_norm, old_norm)
                if r > best_ratio:
                    best_ratio = r
                    best_src = src
                    best_old = old

            conclusion = "—"
            if best_ratio >= 0.85:
                conclusion = f"忠实平移自 {best_src}"
            elif best_ratio >= 0.50:
                conclusion = f"基于 {best_src} 改写/合并"
            elif best_ratio >= 0.25:
                conclusion = f"参考 {best_src} 重写"
            else:
                conclusion = "合并新增"

            old_lines = len(git_show(best_old).splitlines()) if best_old else 0
            rows.append((
                rel,
                best_old or "—",
                best_src or "—",
                len(cur_text.splitlines()),
                old_lines,
                f"{best_ratio*100:.1f}%",
                conclusion,
            ))

    for r in rows:
        print("| " + " | ".join(str(x) for x in r) + " |")


if __name__ == "__main__":
    main()
