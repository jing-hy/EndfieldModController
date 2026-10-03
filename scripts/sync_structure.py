#!/usr/bin/env python
"""把 normify 结构树同步进仓库：`docs/structure/`。

**用户要求（2026-10-03）**：「还有结构树也一起上传」。
结构数据原本只落在 dsh 的 profile 目录里（`~/.dsh/profiles/desktop/normify-modecontroller`，
刻意不进 git、不污染仓库）；现在**每次推送都整份同步到仓库**，别人 clone 下来就能直接用
normify 工具打开看架构图，也能跟着源码一起 diff。

同步内容：`modules/**`、`renders/**`、`policy.yml`、编译产物
（`tree.json` / `outline.md` / `api-index.json` / `receipt.json`）与渲染出来的 `normify.html`。

用法：
    python scripts/sync_structure.py                # 同步（默认源见下）
    python scripts/sync_structure.py --dry-run      # 只看会同步多少个文件
    python scripts/sync_structure.py --src <目录>   # 换结构树目录
环境变量 `MC_STRUCTURE_DIR` 也能指定源目录。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = Path(os.environ.get("MC_STRUCTURE_DIR")
                   or Path(os.environ.get("USERPROFILE", str(Path.home())))
                   / ".dsh" / "profiles" / "desktop" / "normify-modecontroller")
DEFAULT_DST = ROOT / "docs" / "structure"
# 只搬"结构数据 + 产物"，不搬别的东西（dsh 的 profile 目录里可能有别的文件）
PATTERNS = ("modules", "renders", "policy.yml", "tree.json", "outline.md",
            "api-index.json", "receipt.json", "normify.html")


def sync(src: Path, dst: Path, *, dry_run: bool = False) -> tuple[int, int]:
    """整份同步，返回（文件数, 字节数）。目标目录先清空，避免删掉的模块留在仓库里。"""
    if not (src / "modules").is_dir():
        raise FileNotFoundError(f"不是结构数据目录（没有 modules/）：{src}")
    files = 0
    size = 0
    plan: list[tuple[Path, Path]] = []
    for name in PATTERNS:
        item = src / name
        if not item.exists():
            continue
        if item.is_dir():
            for path in sorted(item.rglob("*")):
                if path.is_file():
                    plan.append((path, dst / name / path.relative_to(item)))
        else:
            plan.append((item, dst / name))
    for path, _target in plan:
        files += 1
        size += path.stat().st_size
    if dry_run:
        return files, size

    if dst.exists():
        shutil.rmtree(dst)
    for path, target in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return files, size


def main() -> int:
    parser = argparse.ArgumentParser(description="把 normify 结构树同步进 docs/structure/")
    parser.add_argument("--src", default=str(DEFAULT_SRC))
    parser.add_argument("--dst", default=str(DEFAULT_DST))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not (src / "modules").is_dir():
        # 结构树不在（别人 clone 下来跑）⇒ 静默跳过，绝不阻断 push
        print(f"[structure] 没有结构树 {src}，跳过（不影响推送）")
        return 0
    files, size = sync(src, dst, dry_run=args.dry_run)
    verb = "将同步" if args.dry_run else "已同步"
    print(f"[structure] {verb} {files} 个文件 / {size / 1024:.0f} KB → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
