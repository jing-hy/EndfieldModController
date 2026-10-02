#!/usr/bin/env python
"""结构树行号重定位：代码改完之后，把 normify 模块 `source` 里的行号按 git diff 平移。

**为什么需要它**：结构树的每个叶子模块都用**精确行号**指向代码（`source: [{path, line,
end_line}]`），而任何一次改动都会让后面所有行号漂移 —— 手工改 100+ 个模块不现实，于是
「改完一个 bug 就更新一次结构树」这件事会一直拖着不做（用户 2026-10-02 明确要求每次都更新）。

**它做什么**：`git diff -U0 <结构树所基于的快照>` → 建一张"旧行号 → 新行号"的映射表 →
把每个模块 `source` 里落在**改动文件**上的行号平移过去。不碰 description / apis / 布局。

**之后还要做**（本脚本只负责行号）：
  1. `normify_module_refresh(all=true, repoRoot=...)` —— 重算 fingerprint 与 revision；
  2. 内容真的变了的模块，手工改 `description` / `apis`；
  3. `normify_validate` → `normify_build` → `normify_render`。

用法：
    python scripts/normify_realign.py                     # 只报告（默认）
    python scripts/normify_realign.py --apply             # 真的写回
    python scripts/normify_realign.py --since <git ref>   # 指定结构树所基于的快照
    python scripts/normify_realign.py --tree <结构数据目录>
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TREE = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".dsh" / "profiles" / "desktop" / "normify-modecontroller"

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout


def _tree_revision(tree: Path) -> str:
    """结构树所基于的 git 快照 = 模块 frontmatter 里出现最多的那个 revision。"""
    seen: dict[str, int] = {}
    for path in tree.glob("modules/**/*.md"):
        try:
            head = path.read_text(encoding="utf-8").split("---", 2)[1]
        except (OSError, IndexError):
            continue
        match = re.search(r"^revision:\s*([0-9a-f]{7,40})\s*$", head, re.MULTILINE)
        if match:
            seen[match.group(1)] = seen.get(match.group(1), 0) + 1
    if not seen:
        raise SystemExit("在结构树里找不到 revision，请用 --since 指定快照")
    return max(seen.items(), key=lambda item: item[1])[0]


def _hunks(since: str) -> dict[str, list[tuple[int, int, int, int]]]:
    """{仓库相对路径: [(old_start, old_count, new_start, new_count), ...]}"""
    out = _git(["diff", "-U0", since, "--", "."])
    table: dict[str, list[tuple[int, int, int, int]]] = {}
    current: str | None = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            table.setdefault(current, [])
            continue
        match = HUNK_RE.match(line)
        if match and current:
            old_start = int(match.group(1))
            old_count = int(match.group(2) or 1)
            new_start = int(match.group(3))
            new_count = int(match.group(4) or 1)
            table[current].append((old_start, old_count, new_start, new_count))
    return {path: hunks for path, hunks in table.items() if hunks}


def _mapper(hunks: list[tuple[int, int, int, int]]):
    ordered = sorted(hunks)

    def map_line(line: int) -> int:
        offset = 0
        for old_start, old_count, new_start, new_count in ordered:
            if old_count == 0:                       # 纯插入：插在 old_start 之后
                if line > old_start:
                    offset += new_count
                continue
            if line >= old_start + old_count:        # 在被改动的行块之后
                offset += new_count - old_count
            elif line >= old_start:                  # 落在被改动的行块里
                return new_start + min(line - old_start, max(new_count - 1, 0))
        return line + offset

    return map_line


SOURCE_ITEM_RE = re.compile(
    r'(?P<indent>^[ \t]*)- path:\s*(?P<q>["\']?)(?P<path>[^"\'\n]+)(?P=q)\s*\n'
    r'(?P<body>(?:^[ \t]+[a-z_]+:.*\n?)*)',
    re.MULTILINE,
)


def realign_file(text: str, table: dict[str, list[tuple[int, int, int, int]]]) -> tuple[str, int]:
    """把 frontmatter 里 source 项的行号平移，返回（新文本, 改动项数）。"""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text, 0
    head = parts[1]
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        path = match.group("path").strip()
        hunks = table.get(path)
        if not hunks:
            return match.group(0)
        body = match.group("body")
        if "line:" not in body:
            return match.group(0)
        map_line = _mapper(hunks)

        def fix(inner: re.Match[str]) -> str:
            nonlocal changed
            key, value = inner.group(1), int(inner.group(2))
            new_value = map_line(value)
            if new_value != value:
                changed += 1
            return f"{key}{new_value}"

        body = re.sub(r"(line:\s*)(\d+)", fix, body)
        body = re.sub(r"(end_line:\s*)(\d+)", fix, body)
        return f'{match.group("indent")}- path: "{path}"\n{body}'

    head = SOURCE_ITEM_RE.sub(repl, head)
    return "---".join([parts[0], head, parts[2]]), changed


def main() -> int:
    parser = argparse.ArgumentParser(description="按 git diff 平移结构树模块 source 的行号")
    parser.add_argument("--tree", default=str(DEFAULT_TREE), help="结构数据目录（normify-<slug>）")
    parser.add_argument("--since", default="", help="结构树所基于的 git 快照（默认自动取）")
    parser.add_argument("--apply", action="store_true", help="真的写回（默认只报告）")
    args = parser.parse_args()

    tree = Path(args.tree)
    if not (tree / "modules").is_dir():
        raise SystemExit(f"不是结构数据目录：{tree}")

    since = args.since or _tree_revision(tree)
    table = _hunks(since)
    if not table:
        print(f"自 {since} 起没有代码改动，无需重定位。")
        return 0
    print(f"结构树快照 = {since}；改动文件 {len(table)} 个，hunk {sum(len(v) for v in table.values())} 个。")

    touched_files = 0
    touched_ranges = 0
    for path in sorted(tree.glob("modules/**/*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        updated, changed = realign_file(text, table)
        if not changed:
            continue
        touched_files += 1
        touched_ranges += changed
        rel = path.relative_to(tree / "modules").as_posix()
        if args.apply:
            path.write_text(updated, encoding="utf-8")
            print(f"  已更新 {rel}（{changed} 个行号）")
        else:
            print(f"  待更新 {rel}（{changed} 个行号）")

    verb = "已更新" if args.apply else "待更新"
    print(f"{verb} {touched_files} 个模块 / {touched_ranges} 个行号。")
    if not args.apply and touched_files:
        print("确认无误后加 --apply 写回，接着跑 normify_module_refresh(all=true) 重算指纹。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
