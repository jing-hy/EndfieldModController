"""从 Mod 目录里扫出「开关变量名 → 中文含义」的候选，生成 `hotkey_hints.json`。

用户 2026-10-01 原话：「**要自动识别那个变量的名称，推测含义**，可能存在的变量名称
可以从 `D:\\zmdmod\\mod集合` 中找」——这个脚本就是"从 mod 集合里找"那一步，
开发期跑一次，把结果固化进随包的 `endfieldmodcontroller/hotkey_hints.json`。

    python scripts\\gen_hotkey_hints.py                 # 只报告（dry-run）
    python scripts\\gen_hotkey_hints.py --root <目录>   # 换扫描源
    python scripts\\gen_hotkey_hints.py --write         # 把新词条合并进 json

规则：**只写有中文含义的条目**。扫不出含义的变量（哈希部件名之类）留在报告里给人工看，
不写进 json —— 面板宁可显示 `$part_82254888_001` 也不要编一个假中文（用户最烦"表面功夫"）。
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from endfieldmodcontroller import hotkey_hints  # noqa: E402

DEFAULT_ROOT = Path(r"D:\zmdmod\mod集合")
HINTS_PATH = ROOT / "endfieldmodcontroller" / "hotkey_hints.json"

_VAR_RE = re.compile(r"^\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*=")


def scan(root: Path) -> dict[str, dict[str, object]]:
    """扫所有 ini 的 `[Key*]` 段，统计变量名 / 原键 / 上下文证据。"""
    stats: dict[str, dict[str, object]] = {}

    def entry(name: str) -> dict[str, object]:
        return stats.setdefault(name, {"count": 0, "keys": set(), "tokens": set(), "mods": set()})

    for ini in sorted(root.rglob("*.ini")):
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        section = ""
        current_key = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1]
                continue
            if not section.lower().startswith("key"):
                continue
            key_match = re.match(r"^\s*key\s*=\s*(.+)$", line, re.IGNORECASE)
            if key_match:
                current_key = key_match.group(1).strip()
            var_match = _VAR_RE.match(line)
            if not var_match:
                continue
            name = var_match.group(1)
            item = entry(name)
            item["count"] = int(item["count"]) + 1  # type: ignore[arg-type]
            if current_key:
                item["keys"].add(current_key)  # type: ignore[union-attr]
            item["mods"].add(ini.parent.name)  # type: ignore[union-attr]
        # 上下文证据要按整份文本找（变量的引用在别的段里）；只处理本文件真正出现过的
        # 变量，避免「每个 ini × 全部变量」的平方级扫描。
        for token in re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", text):
            name = token
            if name not in stats:
                continue
            for evidence in hotkey_hints.mesh_tokens(text, name):
                stats[name]["tokens"].add(evidence)  # type: ignore[union-attr]
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="扫描源目录")
    parser.add_argument("--write", action="store_true", help="把新词条合并进 hotkey_hints.json")
    parser.add_argument("--min-count", type=int, default=1, help="只报告出现次数 >= N 的变量")
    args = parser.parse_args()

    root: Path = args.root
    if not root.is_dir():
        print(f"!! 扫描源不存在：{root}")
        return 1

    stats = scan(root)
    table = hotkey_hints.hints()
    known = table["vars"]

    resolved: dict[str, str] = {}
    unresolved: list[tuple[str, int, list[str]]] = []

    print(f"扫描源：{root}")
    print(f"发现变量：{len(stats)} 个\n")
    for name, item in sorted(stats.items(), key=lambda kv: (-int(kv[1]["count"]), kv[0])):  # type: ignore[arg-type]
        count = int(item["count"])
        if count < args.min_count:
            continue
        tokens = sorted(item["tokens"])  # type: ignore[arg-type]
        hint = known.get(name.lower()) or hotkey_hints.hint_for(name, tokens=tokens[:12])
        keys = " ".join(sorted(item["keys"])[:4])  # type: ignore[arg-type]
        line = f"  {name:26} x{count:<3} 键[{keys}]"
        if hint:
            line += f"  → {hint}"
            if name.lower() not in known:
                resolved[name] = hint
        else:
            line += "  → (推测不出)"
            unresolved.append((name, count, tokens[:3]))
        print(line)

    print(f"\n可自动上词表的新条目：{len(resolved)}")
    for name, hint in sorted(resolved.items()):
        print(f"  {name} = {hint}")
    print(f"无法推测的变量：{len(unresolved)}（保持原样显示，不写进词表）")

    if not args.write:
        print("\n(dry-run；加 --write 才会写进 hotkey_hints.json)")
        return 0

    data: dict[str, object] = {}
    if HINTS_PATH.is_file():
        try:
            data = json.loads(HINTS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("_readme", "变量名 → 中文含义。由 scripts\\gen_hotkey_hints.py 生成，可手工增删。")
    data.setdefault("vars", {})
    data.setdefault("tokens", {})
    data.setdefault("sections", {})
    before = len(data["vars"])  # type: ignore[arg-type]
    for name, hint in resolved.items():
        data["vars"][name.lower()] = hint  # type: ignore[index]
    HINTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\n已写入 {HINTS_PATH}（vars {before} → {len(data['vars'])}）")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
