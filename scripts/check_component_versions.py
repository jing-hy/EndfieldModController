# SPDX-License-Identifier: GPL-3.0-or-later
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

**2026-10-26 追加的第二道比对（表 vs 随包资产）**：
第一道只回答"表对不对上游"，回答不了"表说的那个版本，我们真的随包带上了吗"。
真出过事：表写乳摇 3.2.1，而 `assets/secondary_motion/plugin/sbm.dll` 还是 3.1.2 ——
表对、上游也对，但用户装完随包拿到的是旧版，一键启动立刻提示"该更新"。
所以再比一次**仓库里随包资产自己的版本号**：
  * 随包比表旧 → `stale`：不许发版（先换随包资产，或把表退回）；
  * 随包比表新 → `asset_ahead`：表漏更新。
只有**真的随包分发**的组件参与这一道（`BUNDLED_ASSET_PROBES` 里登记）；
XXMI / XXMI-Libs / EFMI / Poser / reshade 是联网安装（或由 exe 内嵌），不登记就完全不参与。

**探测不到资产要报警，不许静默通过**（用户 2026-10-26：「你改检测，让他会报警就行」）：
`*.dll` 不进 git，新克隆的仓库本来就没有 sbm.dll —— 那时"查不了"本身就是要人知道的事，
记成 `missing` 并中止构建；确实只想研究源码、手上没有资产包的机器可以显式加
`--allow-missing-assets` 放过（状态记成 `absent`，仍会打印出来）。

用法：
    python scripts\\check_component_versions.py            # 只检查，永远 return 0
    python scripts\\check_component_versions.py --strict    # 有差异时 return 1（发版流程用）
    python scripts\\check_component_versions.py --skip      # 明确跳过（离线构建）
    python scripts\\check_component_versions.py --allow-missing-assets   # 本机没有随包二进制时放过
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

# 随包资产自己的版本号从哪读（相对仓库根）。
#   "pe"       —— 读 PE 文件版本资源（`updates.file_version`）
#   "manifest" —— 读 JSON 清单里的 `mod_version`
# 新增一个"随包分发"的组件时在这里登记一条，第二道比对自动覆盖它。
BUNDLED_ASSET_PROBES: dict[str, tuple[tuple[str, ...], str]] = {
    "secondary_motion": (("assets", "secondary_motion", "plugin", "sbm.dll"), "pe"),
    "rabbitfx": (("assets", "rabbitfx", "manifest.json"), "manifest"),
}


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


def _cmp_common(left: str, right: str) -> int:
    """按**共同段数**比较两个版本串（返回 -1 / 0 / 1）。

    为什么要截到共同段：PE 文件版本常带构建号（`6.8.0.2155` vs 表里的 `6.8.0`），
    直接按段比会把**同一个版本**判成"随包比表新"，那样每次发版都被误拦。
    """
    a, b = _ver(left), _ver(right)
    size = min(len(a), len(b))
    if not size:
        return 0
    a, b = a[:size], b[:size]
    return (a > b) - (a < b)


def _probe_bundled(key: str) -> tuple[str, str]:
    """读随包资产自己的版本号；返回 `(版本, 读不到的原因)`。

    第二个值是**报警用的**（用户 2026-10-26：「你改检测，让他会报警就行」）：
    文件不在 / 读不出时要把原因如实交还给调用方，而不是当成"这不归我管"静默跳过。
    典型场景：`*.dll` 不进 git，新克隆的仓库里没有 sbm.dll —— 那时必须出声，
    否则「表对、货没换」这种事故在别的机器上永远发现不了。
    """
    probe = BUNDLED_ASSET_PROBES.get(str(key))
    if not probe:
        return ("", "")
    parts, how = probe
    rel = "/".join(parts)
    path = ROOT.joinpath(*parts)
    try:
        if not path.is_file():
            return ("", f"仓库里没有 {rel}（随包二进制不进 git：从 assets-bundle.zip 解开，或按上游重放一次）")
        if how == "pe":
            version = str(updates.file_version(path) or "").strip()
            return (version, "" if version else f"{rel} 读不出 PE 版本资源")
        data = json.loads(path.read_text(encoding="utf-8"))
        version = str((data or {}).get("mod_version") or "").strip()
        return (version, "" if version else f"{rel} 里没有 mod_version")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ("", f"{rel} 读不动（{exc}）")


def _bundled_version(key: str) -> str:
    """仓库里随包资产自己的版本号；没有随包那份（联网安装的组件）返回空串。"""
    return _probe_bundled(key)[0]


def collect_assets(table: dict[str, Any], *, allow_missing: bool = False) -> list[dict[str, Any]]:
    """逐项比对「表里的 latest」与「随包资产自己的版本号」。

    ★ 探测不到资产**不再静默跳过**（用户 2026-10-26：「你改检测，让他会报警就行」）：
    记成 missing 并参与报警 —— `*.dll` 不进 git，新克隆的仓库本来就没有它，
    这时"查不了"本身就是一条要人知道的事；只有显式 --allow-missing-assets 才放过。
    """
    rows: list[dict[str, Any]] = []
    for section in ("builtin", "external"):
        for key, info in (table.get(section) or {}).items():
            if not isinstance(info, dict):
                continue
            probe = BUNDLED_ASSET_PROBES.get(str(key))
            if not probe:
                continue  # 不随包分发（联网安装）⇒ 这一道不适用
            bundled, why = _probe_bundled(key)
            display = str(info.get("display") or key)
            table_version = str(info.get("latest") or "").strip()
            if not bundled:
                rows.append({
                    "section": section,
                    "key": key,
                    "display": display,
                    "table": table_version,
                    "bundled": "",
                    "status": "absent" if allow_missing else "missing",
                    "source": "/".join(probe[0]),
                    "reason": why,
                })
                continue
            if not table_version:
                status = "unknown"
            else:
                diff = _cmp_common(table_version, bundled)
                status = "stale" if diff > 0 else ("asset_ahead" if diff < 0 else "ok")
            rows.append({
                "section": section,
                "key": key,
                "display": display,
                "table": table_version,
                "bundled": bundled,
                "status": status,
                "source": "/".join(probe[0]),
            })
    return rows


def collect(*, allow_missing_assets: bool = False) -> dict[str, Any]:
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
    asset_rows = collect_assets(table, allow_missing=allow_missing_assets)
    problems = [row for row in rows if row["status"] in ("outdated", "ahead")]
    asset_problems = [row for row in asset_rows if row["status"] in ("stale", "asset_ahead", "missing")]
    errors = [str(item) for item in (report.get("errors") or [])]
    return {
        "ok": not problems and not asset_problems,
        "rows": rows,
        "assets": asset_rows,
        "problems": problems,
        "asset_problems": asset_problems,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    parser = argparse.ArgumentParser(description="检查随包组件版本表是否最新（联网）")
    parser.add_argument("--strict", action="store_true", help="有差异时返回非零（发版流程用）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--skip", action="store_true", help="跳过检查（离线构建）")
    parser.add_argument("--allow-missing-assets", action="store_true",
                        help="本机没有随包二进制时不算问题（默认会报警）")
    args = parser.parse_args(argv)

    if args.skip:
        print("[组件版本表] 已按 --skip 跳过检查")
        return 0

    data = collect(allow_missing_assets=args.allow_missing_assets)
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

    asset_rows = data.get("assets") or []
    if asset_rows:
        print("")
        print("[组件版本表] 表里的版本 vs 随包资产自己的版本：")
        asset_marks = {"ok": "✓", "stale": "⚠ 随包还是旧版", "asset_ahead": "⚠ 表漏更新",
                       "unknown": "？ 表里没版本", "missing": "⚠ 随包资产缺失",
                       "absent": "？ 不在本机（已放过）"}
        for row in asset_rows:
            print(f"  {asset_marks.get(row['status'], row['status']):<16} {row['display']:<12} "
                  f"表={row['table'] or '(空)':<10} 随包={row['bundled']}")

    problems = data.get("problems") or []
    if problems:
        print("")
        print(f"⚠ 有 {len(problems)} 项对不上上游 —— 发版前请更新 "
              "`endfieldmodcontroller/component_versions.json`：")
        for row in problems:
            print(f'    "{row["key"]}": {{"latest": "{row["upstream"]}"}}   '
                  f'（原 {row["table"]}）')
    asset_problems = data.get("asset_problems") or []
    if asset_problems:
        print("")
        print(f"⚠ 有 {len(asset_problems)} 项「表与随包资产核对不上」—— 先处理再发版：")
        for row in asset_problems:
            if row["status"] == "missing":
                print(f'    {row["display"]}：查不了随包资产 —— {row["reason"]}')
            elif row["status"] == "stale":
                print(f'    {row["display"]}：表写 {row["table"]}，随包只带了 {row["bundled"]}'
                      f'（{row["source"]}）⇒ 把随包资产换成 {row["table"]}，'
                      f'或把表退回 {row["bundled"]}')
            else:
                print(f'    {row["display"]}：随包已是 {row["bundled"]}，表还写 {row["table"]}'
                      f'（{row["source"]}）⇒ 把表改成 {row["bundled"]}')
    if not problems and not asset_problems:
        print("")
        print("✓ 表里所有组件都是上游最新；随包资产都在本机且与表一致（或有查不到的项，见上）")
    for message in data.get("errors") or []:
        print(f"  （联网提示：{message}）")

    if args.strict and (problems or asset_problems):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
