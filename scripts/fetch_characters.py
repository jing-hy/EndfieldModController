"""从官网拉最新角色名表（固化脚本，用户 2026-09-30 要求）。

用法（在仓库根跑）：

    python scripts\\fetch_characters.py                  # 只看差异，不写盘
    python scripts\\fetch_characters.py --write          # 有新角色就写到数据根（程序会读它）
    python scripts\\fetch_characters.py --write --force  # 忽略 24 小时节流缓存
    python scripts\\fetch_characters.py --update-bundled # 同时更新随包那份（发版前用）

程序每次启动后也会在后台做同一件事（`api._warm_up` → `character_sync.sync`），
所以平时**不需要**手工跑；这个脚本用于核对、以及发版前把随包表刷新到最新。

只认官网 `https://endfield.hypergryph.com/operator`（用户准则：一手来源优先 ——
第三方聚合站的译名有硬错误）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from endfieldmodcontroller import character_sync  # noqa: E402
from endfieldmodcontroller.config import AppConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="从官网同步《终末地》角色名表")
    parser.add_argument("--write", action="store_true",
                        help="把结果写到 <数据根>/runtime/_state/characters.json（程序优先读它）")
    parser.add_argument("--update-bundled", action="store_true",
                        help="同时写回随包那份 endfieldmodcontroller/characters.json（会先备份）")
    parser.add_argument("--force", action="store_true", help="忽略 24 小时节流缓存")
    parser.add_argument("--timeout", type=int, default=25, help="官网请求超时（秒）")
    args = parser.parse_args()

    config = AppConfig.load()
    print(f"数据根     : {config.runtime_path.parent}")
    print(f"官网来源   : {character_sync.SOURCE_URL}")

    try:
        official = character_sync.fetch_official(timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"[失败] 拉官网失败：{exc}")
        print("       （这不影响程序使用：启动时的检查失败是静默的，会继续用随包表）")
        return 2

    local = character_sync.load_local(config)
    merged = character_sync.merge_payload(local, official)
    payload = merged["payload"]

    print(f"官网       : {official['total']} 位")
    print(f"本地现有   : {len(local.get('characters') or [])} 位"
          f"（fetched_at={local.get('fetched_at') or '随包'}）")
    print(f"合并后     : {len(payload['characters'])} 位")
    print(f"新增       : {len(merged['added'])} 位"
          + (f" → {', '.join(merged['added'])}" if merged["added"] else ""))
    print(f"字段更新   : {merged['updated']} 位（codename / key 变化）")

    if not merged["added"] and not merged["updated"]:
        print("\n已是最新，无需写盘。")
        return 0

    if args.write:
        path = character_sync.write_latest(config, payload)
        print(f"\n[写入] 运行时表 → {path}")
    elif args.update_bundled:
        path = character_sync.write_bundled(payload)
        print(f"\n[写入] 随包表 → {path}")
    else:
        print("\n（未指定 --write / --update-bundled，只做了检查；"
              "要看完整合并结果可加 --write）")

    if args.update_bundled and args.write:
        path = character_sync.write_bundled(payload)
        print(f"[写入] 随包表 → {path}")

    print("\n新增角色的 aliases 只含官网给的名字/代号/美术 key ——")
    print("社区简称（如「小羊」「塞希」）需要手工补进 characters.json 的 aliases。")
    print(json.dumps({k: v for k, v in merged.items() if k != "payload"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
