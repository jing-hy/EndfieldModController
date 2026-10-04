"""发版前检查「随包组件版本表」是不是最新（用户 2026-10-04 要求）。

用户原话：「**另外每次 release 要检查内置的依赖版本表是否最新**」。

表 = `endfieldmodcontroller/component_versions.json`（随 exe 走，一键启动前用它做
**本地**比对，避免联网干等 6 秒 —— 用户 2026-10-03 定的）。正因为它是"随包快照"，
**发版时必须联网核对一遍**：表里写着"上游最新版"，过期就会误导用户
（提示了并不存在的新版，或者漏掉真正的新版）。

做法：复用现成的联网链路 `updates.check_updates()`（GitHub / reshade.me / 乳摇 / Poser /
XXMI···），把它的 `latest` 与表里的 `latest` 逐项比对：
  * 一致      → ✓
  * 上游更新  → ⚠「表该更新了」，并给出可直接粘贴进表的 JSON 片段
  * 上游更旧  → ⚠「表里的版本比上游还新」（多半写错或上游撤包）
  * 查不到    → ？ 网络/限流，**不算**表过期（不误报）

用法：
    python scripts\\check_component_versions.py            # 只检查，永远 return 0
    python scripts\\check_component_versions.py --strict    # 有差异时 return 1（发版流程用）
    python scripts\\check_component_versions.py --skip      # 明确跳过（离线构建）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from endfieldmodcontroller import component_versions, updates  # noqa: E402
from endfieldmodcontroller.config import AppConfig  # noqa: E402


def _fix_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def _latest_from_report(report: dict[str, Any], section: str, key: str) -> tuple[str, str]:
    """从 `check_updates()` 的结果里取某个组件的最新版；返回 `(版本, 取不到的原因)`。"""
    if section == "builtin" and key == "Poser":
        value = str((report.get("poser") or {}).get("latest") or "").strip()
        return (value, "") if value else ("", "查询失败或无数据")
    if section == "builtin":
        row = (report.get("builtin") or {}).get(key) or {}
        value = str(row.get("latest") or "").strip()
        return (value, "") if value else ("", "查询失败或无数据")
    row = report.get(key) or {}
    value = str(row.get("latest") or "").strip()
    return (value, "") if value else ("", "查询失败或无数据")


def _ver(text: str) -> tuple[int, ...]:
    return component_versions._ver_tuple(text)


def collect() -> dict[str, Any]:
    table = component_versions.load()
    if not table:
        return {"ok": True, "skipped": "没有 component_versions.json（旧版本/未随包）", "rows": []}
    report = updates.check_updates(AppConfig(), log=None)
    rows: list[dict[str, Any]] = []
    for section in ("builtin", "external"):
        for key, info in (table.get(section) or {}).items():
            if not isinstance(info, dict):
                continue
            current = str(info.get("latest") or "").strip()
            latest, reason = _latest_from_report(report, section, key)
            if not latest:
                status = "unknown"
            elif _ver(latest) > _ver(current):
                status = "outdated"
            elif _ver(latest) < _ver(current):
                status = "ahead"
            else:
                status = "ok"
            rows.append({
                "section": section,
                "key": key,
                "display": str(info.get("display") or key),
                "table": current,
                "upstream": latest,
                "status": status,
                "reason": reason,
            })
    problems = [row for row in rows if row["status"] in ("outdated", "ahead")]
    errors = [str(item) for item in (report.get("errors") or [])]
    return {"ok": not problems, "rows": rows, "problems": problems, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    parser = argparse.ArgumentParser(description="检查随包组件版本表是否最新（联网）")
    parser.add_argument("--strict", action="store_true", help="有差异时返回非零（发版流程用）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--skip", action="store_true", help="跳过检查（离线构建）")
    args = parser.parse_args(argv)

    if args.skip:
        print("[组件版本表] 已按 --skip 跳过检查")
        return 0

    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if (data.get("ok") or not args.strict) else 1

    if data.get("skipped"):
        print(f"[组件版本表] {data['skipped']}")
        return 0

    print("[组件版本表] 随包快照 vs 上游最新：")
    marks = {"ok": "✓", "outdated": "⚠ 表该更新", "ahead": "⚠ 表里比上游还新", "unknown": "？ 没查到"}
    for row in data["rows"]:
        line = (f"  {marks.get(row['status'], row['status']):<16} {row['display']:<12} "
                f"表={row['table'] or '(空)':<10} 上游={row['upstream'] or '(没查到)'}")
        if row["status"] == "unknown" and row["reason"]:
            line += f"  （{row['reason']}）"
        print(line)

    problems = data.get("problems") or []
    if problems:
        print("")
        print(f"⚠ 有 {len(problems)} 项对不上 —— 发版前请更新 "
              f"`endfieldmodcontroller/component_versions.json`：")
        for row in problems:
            print(f'    "{row["key"]}": {{"latest": "{row["upstream"]}"}}   '
                  f'（原 {row["table"]}）')
    else:
        print("")
        print("✓ 表里所有组件都是上游最新（或有查不到的项，见上）")
    for message in data.get("errors") or []:
        print(f"  （联网提示：{message}）")

    if args.strict and problems:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
