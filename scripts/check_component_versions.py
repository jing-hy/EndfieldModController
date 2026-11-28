# SPDX-License-Identifier: AGPL-3.0-only
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

**2026-11-27 追加的第三道比对（表 vs 离线依赖包）**：
离线包 `dist/deps-bundle.zip`（不随 Release，QQ 群应急分发）里打包的是**某一时刻的各组件原文**。
它和随包资产一样会过气：v1.5.1 那次就出现过表已写 EFMI 1.5.1、离线包里还是 1.4.9，
而发版流程只核对“表 vs 上游”“表 vs 随包资产”两道，发现不了。
所以再比一次包内 `manifest.json` 的 `deps` 版本：
  * 包比表旧  → `stale`：先 `python scripts\\build_deps_bundle.py --all-editions` 重打，再发版；
  * 包比表新  → `ahead`：表漏更新；
  * 包在但缺组件 / 读不出 → `missing` / `unreadable`，同样报警；
  * 本机根本没有离线包 → `absent`，只提示、不阻断（从没打过离线包的机器不该被拦）。
只有两边都登记的组件参与（`OFFLINE_KEY_MAP`）；secondary_motion / rabbitfx 随
assets-bundle，不在这里。

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
import zipfile
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

# 第四道比对读的角色表（随包那份）。官网角色页=唯一可信来源，见 character_sync。
CHARACTERS_JSON = ROOT / "endfieldmodcontroller" / "characters.json"


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


# ---------------------------------------------------------------- 第三道：离线依赖包
#: 离线包（`dist/deps-bundle.zip`，**不随 Release**、QQ 群应急分发）的 manifest 键 → 版本表键。
#: 只登记两边都有的组件；secondary_motion / rabbitfx 随 assets-bundle，不在这里。
OFFLINE_BUNDLES: dict[str, Path] = {
    "full": ROOT / "dist" / "deps-bundle.zip",
    "lite": ROOT / "dist" / "deps-bundle-lite.zip",
}
#: 兼容旧引用（单包形态）。
OFFLINE_BUNDLE = OFFLINE_BUNDLES["full"]
#: Lite 包里本来就没有的东西（与 build_deps_bundle.RESHADE_DEPS 同一批）—— 核对时跳过，
#: 否则会把「Lite 不打 ReShade」误报成「离线包里缺这个组件」。
OFFLINE_LITE_SKIP: frozenset[str] = frozenset({"ReShade", "DLSS5-Feeder", "iMMERSE"})
OFFLINE_KEY_MAP: dict[str, str] = {
    "XXMI": "XXMI",
    "XXMI-Libs": "XXMI-Libs",
    "EFMI": "EFMI",
    "Poser": "Poser",
    "ReShade": "reshade",
    "EndfieldJiggle": "jiggle_efmi",
}


def _table_row(table: dict[str, Any], key: str) -> dict[str, Any] | None:
    """表里某个组件的行（先 builtin 后 external），没有就返回 None。"""
    for section in ("builtin", "external"):
        info = (table.get(section) or {}).get(key)
        if isinstance(info, dict):
            return info
    return None


def collect_offline_bundle(table: dict[str, Any], *, bundle_path: Path | None = None,
                           edition: str = "") -> dict[str, Any]:
    """逐项比对「离线包里打的组件版本」与「表里的 latest」。

    为什么需要这一道（2026-11-27）：离线包打包的是**某一时刻**的组件原文，
    表更新了、包没重打时，用户拿离线包装上的是旧版（v1.5.1 就出现过：表写 EFMI 1.5.1，
    包里还是 1.4.9）。只核对「表 vs 上游」「表 vs 随包资产」发现不了这种过气。

    本机**没有**离线包（从没打过）不阻断 —— 那是正常状态，只给一行提示。
    """
    path = Path(bundle_path) if bundle_path is not None else OFFLINE_BUNDLE
    if not path.is_file():
        return {"bundle": str(path), "built_at": "", "rows": [], "problems": [],
                "note": f"本机没有 {path.name}（从没打过离线包，跳过这道比对）"}
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        row = {
            "key": "", "display": path.name, "table": "", "bundle": "",
            "status": "unreadable",
            "reason": f"{path.name} 读不出 manifest.json（{type(exc).__name__}: {exc}）",
        }
        return {"bundle": str(path), "built_at": "", "rows": [row], "problems": [row]}
    deps = manifest.get("deps") if isinstance(manifest, dict) else None
    if not isinstance(deps, dict):
        deps = {}
    # 包自己声明了形态（build_deps_bundle 写进 manifest）；读不到就按调用方给的算。
    manifest_edition = str(manifest.get("edition") or edition or "full").strip().lower()
    rows: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for package_key, table_key in OFFLINE_KEY_MAP.items():
        if manifest_edition == "lite" and package_key in OFFLINE_LITE_SKIP:
            continue          # Lite 包本来就不打 ReShade 链路，别误报缺组件
        info = _table_row(table, table_key)
        if info is None:
            continue  # 表里没登记这个组件 ⇒ 不归这一道管
        table_version = str(info.get("latest") or "").strip()
        item = deps.get(package_key)
        bundle_version = (str(item.get("version") or "").strip()
                          if isinstance(item, dict) else "")
        if not bundle_version:
            status, reason = "missing", f"离线包里没有 {package_key}"
        elif not table_version:
            status, reason = "unknown", "表里没写版本"
        else:
            diff = _cmp_common(bundle_version, table_version)
            status, reason = ("stale" if diff < 0 else "ahead" if diff > 0 else "ok"), ""
        row = {
            "key": table_key,
            "display": str(info.get("display") or table_key),
            "table": table_version,
            "bundle": bundle_version,
            "status": status,
        }
        if reason:
            row["reason"] = reason
        rows.append(row)
        if status in ("stale", "ahead", "missing"):
            problems.append(row)
    built_at = str(manifest.get("built_at") or "") if isinstance(manifest, dict) else ""
    return {"bundle": str(path), "built_at": built_at, "edition": manifest_edition,
            "rows": rows, "problems": problems}


def collect_offline_bundles(table: dict[str, Any]) -> dict[str, Any]:
    """两版离线包各核一遍（2026-11-28 用户：「现在应该要构建两个离线包」）。

    返回 {"bundles": {edition: result}, "problems": [...]}；每条问题带上 edition
    与 bundle_name，打印/中止提示才能分清是哪个包过期。
    """
    bundles: dict[str, Any] = {}
    problems: list[dict[str, Any]] = []
    for edition, path in OFFLINE_BUNDLES.items():
        result = collect_offline_bundle(table, bundle_path=path, edition=edition)
        bundles[edition] = result
        for row in result.get("problems") or []:
            item = dict(row)
            item["edition"] = edition
            item["bundle_name"] = path.name
            problems.append(item)
    return {"bundles": bundles, "problems": problems}


def compare_characters(local_payload: dict[str, Any],
                       official_payload: dict[str, Any]) -> dict[str, Any]:
    """随包角色表 vs 官网角色页（纯比较，不联网 —— 便于单测）。

    判据：官网有、随包没有 = **缺角色**（发版前必须补），随包有、官网没有 = 下架/改名，
    保留不报错（老 Mod 还要能认）。管理员按 canonical 名拆成男/女两条。
    """
    from endfieldmodcontroller import character_sync

    official_names: set[str] = set()
    for item in (official_payload.get("characters") or []):
        if not isinstance(item, dict):
            continue
        name = character_sync.canonical_name(str(item.get("name") or ""),
                                             str(item.get("key") or ""))
        if name:
            official_names.add(name)
    local_names: set[str] = set()
    for item in (local_payload.get("characters") or []):
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            local_names.add(str(item["name"]).strip())
    missing = sorted(official_names - local_names)
    extra = sorted(local_names - official_names)
    return {
        "status": "ok" if not missing else "outdated",
        "official": len(official_names),
        "local": len(local_names),
        "missing": missing,
        "extra": extra,
        "problems": missing,
    }


def collect_characters() -> dict[str, Any]:
    """第四道：联网拉官网角色页，和随包 `characters.json` 比一遍。

    为什么要有（2026-11-28 用户：「把角色检查加进上游更新检查后面」）：
    角色表决定新导入的 Mod 能不能自动归类、同角色互斥会不会误判；随包表过期时
    用户的 Mod 会被归到「其他」或判错角色 —— v1.7 上线后随包表还停在 9 月的 32 位，
    小刻这类新角色直接缺失。发版前必须让它对上官网。
    """
    try:
        from endfieldmodcontroller import character_sync

        official = character_sync.fetch_official(timeout=25)
    except Exception as exc:  # noqa: BLE001 —— 网络/限流不算"表过期"
        return {"status": "unknown", "official": 0, "local": 0, "missing": [],
                "extra": [], "problems": [], "message": f"官网角色表拉取失败：{exc}"}
    try:
        local = json.loads(CHARACTERS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "missing", "official": 0, "local": 0, "missing": [],
                "extra": [], "problems": [], "message": f"随包角色表读不出：{exc}"}
    return compare_characters(local, official)


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
    offline_bundles = collect_offline_bundles(table)
    problems = [row for row in rows if row["status"] in ("outdated", "ahead")]
    asset_problems = [row for row in asset_rows if row["status"] in ("stale", "asset_ahead", "missing")]
    offline_problems = offline_bundles.get("problems") or []
    characters = collect_characters()
    character_problems = characters.get("problems") or []
    errors = [str(item) for item in (report.get("errors") or [])]
    return {
        "ok": not problems and not asset_problems and not offline_problems and not character_problems,
        "characters": characters,
        "character_problems": character_problems,
        "rows": rows,
        "assets": asset_rows,
        "offline": offline_bundles["bundles"].get("full") or {},
        "offline_bundles": offline_bundles["bundles"],
        "problems": problems,
        "asset_problems": asset_problems,
        "offline_problems": offline_problems,
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

    offline_bundles = data.get("offline_bundles") or {}
    if not offline_bundles:
        legacy = data.get("offline") or {}
        offline_bundles = {"full": legacy} if legacy else {}
    offline_marks = {"ok": "✓", "stale": "⚠ 离线包还是旧版", "ahead": "⚠ 离线包比表新",
                     "missing": "⚠ 离线包里缺这个组件", "unreadable": "⚠ 离线包读不出",
                     "unknown": "？ 缺版本号"}
    for edition, offline in offline_bundles.items():
        if offline.get("note"):
            print("")
            print(f"[组件版本表] {offline['note']}")
        offline_rows = offline.get("rows") or []
        if not offline_rows:
            continue
        print("")
        print(f"[组件版本表] 表里的版本 vs 离线依赖包（{edition}：{offline.get('bundle') or '?'}，"
              f"生成于 {offline.get('built_at') or '?'}）：")
        for row in offline_rows:
            print(f"  {offline_marks.get(row['status'], row['status']):<16} "
                  f"{row['display']:<12} 表={row['table'] or '(空)':<10} "
                  f"离线包={row['bundle'] or '(缺)'}")

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
    characters = data.get("characters") or {}
    if characters:
        print("")
        print("[角色表] 随包角色表 vs 官网角色页：")
        char_marks = {"ok": "✓", "outdated": "⚠ 角色表该更新", "unknown": "？ 没查到",
                      "missing": "⚠ 随包表读不出"}
        print(f"  {char_marks.get(characters.get('status'), characters.get('status')):<16} "
              f"随包 {characters.get('local', 0)} 位 / 官网 {characters.get('official', 0)} 位")
        if characters.get("missing"):
            print(f"    官网有、随包没有：{'、'.join(characters['missing'])}")
            print("    ⇒ 跑 `python scripts\\fetch_characters.py --update-bundled` 把随包表更新到官网最新")
        if characters.get("extra"):
            print(f"    随包有、官网没有（下架保留）：{'、'.join(characters['extra'])}")
        if characters.get("message"):
            print(f"    （{characters['message']}）")

    offline_problems = data.get("offline_problems") or []
    if offline_problems:
        print("")
        print(f"⚠ 有 {len(offline_problems)} 项「表与离线依赖包核对不上」—— 先处理再发版：")
        for row in offline_problems:
            if row["status"] == "stale":
                print(f"    {row['display']}：表写 {row['table']}，离线包只打了 {row['bundle']}"
                      f" ⇒ 跑 `python scripts\\build_deps_bundle.py --all-editions` 重打，或把表退回 {row['bundle']}")
            elif row["status"] == "ahead":
                print(f"    {row['display']}：离线包已是 {row['bundle']}，表还写 {row['table']}"
                      f" ⇒ 把表改成 {row['bundle']}")
            else:
                print(f"    {row['display']}：{row.get('reason') or row['status']}")
    character_problems = data.get("character_problems") or []
    if character_problems:
        print("")
        print(f"⚠ 随包角色表缺 {len(character_problems)} 位官网角色 —— 先更新再发版：")
        print(f"    {'、'.join(character_problems)}")

    if not problems and not asset_problems and not offline_problems and not character_problems:
        print("")
        print("✓ 表里所有组件都是上游最新；随包资产都在本机且与表一致；离线包（若有）与表一致；角色表与官网一致")
    for message in data.get("errors") or []:
        print(f"  （联网提示：{message}）")

    if args.strict and (problems or asset_problems or offline_problems or character_problems):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
