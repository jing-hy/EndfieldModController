"""给角色表补**拼音别名**（固化脚本，用户 2026-10-01 要求「中文拼音也要自动识别」）。

为什么要有它：国内 Mod 作者常用拼音命名目录（`zhuangfangyi_泳装`、`ChenQianyu_v2`、
`luoxi_dress`），而随包表里的别名只有中文名 + 官网英文代号 —— 拼音写法一个都匹配不上，
于是新拖进来的 Mod 会被判成"角色不确定"。

做法：用 `pypinyin` 把每个角色的中文名转成全拼（连写 + 空格分词）写进 `aliases`。
`pypinyin` **只是本脚本的开发期依赖**，不进 `requirements.txt`、不随 exe 打包 ——
生成结果固化在 `characters.json` 里，运行时零依赖。

用法（在仓库根跑）：

    python scripts\\gen_character_pinyin.py            # 只看会补什么，不写盘
    python scripts\\gen_character_pinyin.py --write    # 写回随包表（先备份）+ 运行时表

发版前刷新过角色表（`fetch_characters.py --update-bundled`）之后跑一次 `--write`，
新角色的拼音就补齐了。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from endfieldmodcontroller.config import AppConfig  # noqa: E402
from endfieldmodcontroller import character_sync, core  # noqa: E402

# 多音字 / 社区习惯读法的人工补充（pypinyin 默认音与 Mod 圈常用音不一致时用）。
EXTRA_PINYIN: dict[str, list[str]] = {
    "洛茜": ["luoxi"],          # 「茜」默认 qiàn，社区念 luoxi（英文代号 Rossi）
    "卡缪": ["kamiao", "kamiu"],  # 「缪」默认 móu；卡缪（Camille）两种念法都有人用
    "赛希": ["saixi"],
    "弭弗": ["mifu"],
    "梨诺": ["linuo"],
    "阿列什": ["alieshi"],       # 「什」在人名里念 shí，pypinyin 默认给 shén
}

# 默认音**明显不对**的名字：丢掉 pypinyin 的结果，只用人工指定的那几种写法。
PINYIN_OVERRIDE: dict[str, list[str]] = {
    "阿列什": ["alieshi", "alesh"],
}


def pinyin_aliases(name: str) -> list[str]:
    """中文名的拼音别名（连写 + 空格分词），拿不到拼音时返回空表。"""
    try:
        from pypinyin import lazy_pinyin  # type: ignore
    except Exception:  # noqa: BLE001
        return []
    try:
        parts = [str(p).strip().lower() for p in lazy_pinyin(str(name)) if str(p).strip()]
    except Exception:  # noqa: BLE001
        return []
    if not parts:
        return []
    joined = "".join(parts)
    out = [joined, " ".join(parts)]
    out.extend(str(x).strip().lower() for x in EXTRA_PINYIN.get(str(name), []) if str(x).strip())
    override = PINYIN_OVERRIDE.get(str(name))
    if override:
        out = [str(x).strip().lower() for x in override]
    # 太短的拼音（如单字名「诀」→ jue 之外的两字母）容易误报，只保留 3 个字母以上
    return list(dict.fromkeys(a for a in out if len(a.replace(" ", "")) >= 3))


def add_aliases(payload: dict) -> tuple[dict, list[tuple[str, list[str]]]]:
    """把拼音别名并进 ``payload['characters']``（幂等），返回 (新 payload, 变更列表)。"""
    characters = payload.get("characters") or []
    # 先看看有哪些拼音会和**别的**角色撞车 —— 撞车的不能加（会造成误判）
    owner: dict[str, str] = {}
    conflicts: set[str] = set()
    for item in characters:
        name = str(item.get("name") or "").strip()
        for alias in pinyin_aliases(name):
            key = core.compact_text(alias)
            if key in owner and owner[key] != name:
                conflicts.add(key)
            owner.setdefault(key, name)

    changes: list[tuple[str, list[str]]] = []
    updated: list[dict] = []
    for item in characters:
        entry = dict(item)
        name = str(entry.get("name") or "").strip()
        aliases = [str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip()]
        existing = {core.compact_text(a) for a in aliases}
        added: list[str] = []
        for alias in pinyin_aliases(name):
            key = core.compact_text(alias)
            if key in existing or key in conflicts:
                continue
            aliases.append(alias)
            existing.add(key)
            added.append(alias)
        if added:
            entry["aliases"] = aliases
            changes.append((name, added))
        updated.append(entry)
    new_payload = dict(payload)
    new_payload["characters"] = updated
    new_payload["_pinyin"] = ("拼音别名由 scripts/gen_character_pinyin.py 用 pypinyin 生成；"
                              "运行时不依赖 pypinyin。")
    return new_payload, changes


def _write(path: Path, payload: dict, *, backup: bool = True) -> None:
    if backup and path.is_file():
        shutil.copy2(path, path.with_name(path.name + time.strftime(".bak-%Y%m%d-%H%M%S")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="给角色表补拼音别名")
    parser.add_argument("--write", action="store_true", help="写回随包表与运行时表（先备份）")
    parser.add_argument("--bundled-only", action="store_true", help="只写随包表，不碰运行时表")
    args = parser.parse_args()

    config = AppConfig.load()
    targets: list[Path] = [core.CHARACTERS_JSON]
    runtime_table = character_sync.latest_path(config)
    if runtime_table.is_file() and not args.bundled_only:
        targets.append(runtime_table)

    try:
        import pypinyin  # type: ignore  # noqa: F401
    except Exception:  # noqa: BLE001
        print("[失败] 没装 pypinyin（本脚本的开发期依赖）：python -m pip install pypinyin")
        return 2

    print(f"角色表     : {', '.join(str(t) for t in targets)}")
    total_changes = 0
    for path in targets:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[跳过] {path} 读不出来：{exc}")
            continue
        new_payload, changes = add_aliases(payload)
        total_changes += len(changes)
        print(f"\n{path.name}: {len(new_payload.get('characters') or [])} 位角色，"
              f"{len(changes)} 位需要补拼音")
        for name, added in changes:
            print(f"  - {name}: {' / '.join(added)}")
        if not changes:
            continue
        if args.write:
            _write(path, new_payload)
            print(f"  [写入] {path}")
        else:
            print("  （未指定 --write，只做了检查）")

    if not total_changes:
        print("\n拼音别名已齐，无需写盘。")
    elif not args.write:
        print("\n加 --write 才会真正写盘。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
