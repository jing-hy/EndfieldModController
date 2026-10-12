#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
"""打一个**离线依赖包**（`deps-bundle.zip`）—— 给连不上 GitHub 的机器应急用。

用户 2026-10-12 定的形态：

* **不进 Release**（不随附件发布，也不进 CI）—— 只在需要时本地构建一次；
* 分发渠道 = **QQ 群**（群号见 README / AGENTS.md），定位是"**无法使用 GitHub 时的应急方案**"；
* 包里**不含** AGPL / 受限组件（见下面"不打包的东西"），所以不存在"我们替别人再分发"的问题。

用法：

    python scripts/build_deps_bundle.py                 # 下载/收集 + 打包
    python scripts/build_deps_bundle.py --skip-download # 只用本地已有的原件（离线打包）
    python scripts/build_deps_bundle.py --out D:\\xx.zip

产出：`dist\\deps-bundle.zip`（+ `.sha256`）。包内结构见 `endfieldmodcontroller/offline_deps.py`
的模块说明；导入入口在依赖页「导入依赖包…」。

**不打包的东西（不是漏了，是许可上不能）**：

* `Endfield Poser` —— **AGPL-3.0**，README 与界面都明写"不随包分发，只从官方 Release 下载"；
* `Streamline SDK` —— NVIDIA SDK，条款限制再分发；
* `VC++ 运行库` —— 微软条款，必须跑官方安装器。

这三项在离线机器上仍需联网安装（界面会如实标出缺哪一项）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from endfieldmodcontroller import dependencies, dlss5_fetcher, github, runtime_deps, updates  # noqa: E402

DIST = ROOT / "dist"
ASSETS = ROOT / "assets"
BUNDLE_NAME = "deps-bundle.zip"
MANIFEST_NAME = "manifest.json"
README_NAME = "离线包说明.txt"

#: (key, 说明, 许可) —— key 与 `offline_deps` 的索引键、以及各安装链路的查表键一致。
LICENSES: dict[str, str] = {
    "XXMI": "MIT",
    "XXMI-Libs": "MIT",
    "EFMI": "MIT",
    "ReShade": "BSD-3-Clause",
    "DLSS5-Feeder": "见上游仓库说明",
    "iMMERSE": "MIT",
}


def _log(message: str) -> None:
    print(f"[deps] {message}", flush=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(url: str, target: Path, *, digest: str = "", label: str = "") -> bool:
    """下载一个原件（带 sha256 校验）；失败返回 False，不抛。"""
    if target.is_file() and target.stat().st_size:
        _log(f"{label or target.name}：本机已有，跳过下载")
        return True
    _log(f"{label or target.name}：下载 {url}")
    try:
        dependencies._http_get(url, target, expected_sha256=digest, log=_log)
    except Exception as exc:  # noqa: BLE001
        _log(f"!! 下载失败：{exc}")
        return False
    return target.is_file()


def collect(dest: Path, *, download: bool = True) -> dict[str, dict[str, Any]]:
    """把各组件原件收进 `dest/`，返回清单条目（key → 条目）。"""
    dest.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, Any]] = {}

    def record(key: str, path: Path, version: str, source: str) -> None:
        entries[key] = {
            "asset": path.name,
            "version": version,
            "size": path.stat().st_size,
            "sha256": sha256_of(path),
            "source": source,
            "license": LICENSES.get(key, ""),
        }
        _log(f"  ✓ {key}: {path.name}（{path.stat().st_size / 1048576:.1f} MB，{version}）")

    # ---- GitHub 上的三个内置组件（XXMI / XXMI-Libs / EFMI）
    plans = (
        ("XXMI", runtime_deps.XXMI_REPO, runtime_deps.XXMI_ASSET_PATTERN, False),
        ("XXMI-Libs", runtime_deps.XXMI_LIBS_REPO, runtime_deps.XXMI_LIBS_ASSET_PATTERN, False),
        ("EFMI", runtime_deps.EFMI_REPO, runtime_deps.EFMI_ASSET_PATTERN, False),
    )
    for key, repo, pattern, pre in plans:
        try:
            url, version, asset_name, digest = runtime_deps._latest_release_asset(
                repo, pattern, include_prerelease=pre)
        except Exception as exc:  # noqa: BLE001
            _log(f"!! {key}：查不到上游（{exc}）—— 若本机已有原件可加 --skip-download")
            continue
        target = dest / asset_name
        if download and not _fetch(url, target, digest=digest, label=key):
            continue
        if target.is_file():
            record(key, target, version, f"https://github.com/{repo}")
    # XXMI-Libs 还需要它自己的 Manifest.json（离线导入那条链路要用）
    try:
        release = runtime_deps._release_info(runtime_deps.XXMI_LIBS_REPO)
        manifest_url = runtime_deps._asset_url(release, "Manifest.json")
        _fetch(manifest_url, dest / "Manifest.json", label="XXMI-Libs Manifest.json")
    except Exception as exc:  # noqa: BLE001
        _log(f"!! XXMI-Libs 的 Manifest.json 没拿到：{exc}")

    # ---- ReShade 底座（reshade.me 的 Addon 安装器）
    try:
        version = dlss5_fetcher.reshade_latest_version(_log)
        name = f"ReShade_Setup_{version}_Addon.exe"
        target = dest / name
        url = dlss5_fetcher.RESHADE_ASSET_URL.format(version=version)
        if (not download or _fetch(url, target, label="ReShade")) and target.is_file():
            record("ReShade", target, version, dlss5_fetcher.RESHADE_HOMEPAGE)
    except Exception as exc:  # noqa: BLE001
        _log(f"!! ReShade：{exc}")

    # ---- DLSS5-Feeder
    try:
        release = github.releases_latest(dlss5_fetcher.FEEDER_REPO)
        tag = str(release.get("tag_name") or "")
        asset = dlss5_fetcher._pick_asset(release, "DLSS5-Feeder", ".zip")
        if not asset:
            raise RuntimeError("release 里没有 zip")
        name = str(asset.get("name") or "DLSS5-Feeder.zip")
        target = dest / name
        url = str(asset.get("browser_download_url") or "")
        if (not download or _fetch(url, target, digest=str(asset.get("digest") or ""),
                                   label="DLSS5-Feeder")) and target.is_file():
            record("DLSS5-Feeder", target, tag, f"https://github.com/{dlss5_fetcher.FEEDER_REPO}")
    except Exception as exc:  # noqa: BLE001
        _log(f"!! DLSS5-Feeder：{exc}")

    # ---- iMMERSE（无 release，走 codeload 分支 zip）
    try:
        revision = github.latest_commit(dlss5_fetcher.IMMERSE_REPO, dlss5_fetcher.IMMERSE_BRANCH)[:12]
        name = f"iMMERSE-{revision}.zip"
        target = dest / name
        url = (f"https://codeload.github.com/{dlss5_fetcher.IMMERSE_REPO}"
               f"/zip/refs/heads/{dlss5_fetcher.IMMERSE_BRANCH}")
        if (not download or _fetch(url, target, label="iMMERSE")) and target.is_file():
            record("iMMERSE", target, revision, f"https://github.com/{dlss5_fetcher.IMMERSE_REPO}")
    except Exception as exc:  # noqa: BLE001
        _log(f"!! iMMERSE：{exc}")

    return entries


def _readme(entries: dict[str, dict[str, Any]]) -> str:
    lines = [
        "EndfieldModController —— 离线依赖包（应急用）",
        "=" * 46,
        "",
        "用途：给**连不上 GitHub / reshade.me** 的机器一次性带上所有可再分发的依赖。",
        "用法：把它放进管理器「依赖」页 → 顶部「导入依赖包…」，导入后点一次「一键启动」即可自动配置。",
        "",
        "本包**不随 Release 发布**，只作应急搬运；组件版权与许可归各自作者所有。",
        "如各作者不希望被这样分发，请联系我们，会立即停止分发并删除。",
        "",
        "包含：",
    ]
    for key, entry in sorted(entries.items()):
        lines.append(f"  · {key} {entry.get('version') or ''}"
                     f"（{entry.get('asset')}，{(entry.get('size') or 0) / 1048576:.1f} MB，"
                     f"许可 {entry.get('license') or '见上游'}）")
    lines += [
        "",
        "**不包含**（许可上不能随包，请自行联网安装）：",
        "  · Endfield Poser（AGPL-3.0，本项目一直承诺不随包分发）",
        "  · Streamline SDK（NVIDIA，条款限制再分发）",
        "  · VC++ 运行库（微软，必须跑官方安装器）",
        "",
        f"构建时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines) + "\n"


def build(out: Path, *, download: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="mc-deps-") as tmp:
        work = Path(tmp)
        entries = collect(work / "deps", download=download)
        if not entries:
            _log("!! 一个组件都没收到（检查网络，或用 --skip-download 配合本机已有原件）")
            return 1
        manifest = {
            "format": offline_deps_format(),
            "kind": "deps-bundle",
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "离线依赖包（应急用，不随 Release 发布）。Endfield Poser / Streamline / VC++ "
                    "不在包内（许可原因）。",
            "deps": entries,
        }
        (work / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        (work / README_NAME).write_text(_readme(entries), encoding="utf-8")

        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        total = 0
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(work / MANIFEST_NAME, MANIFEST_NAME)
            archive.write(work / README_NAME, README_NAME)
            for item in sorted((work / "deps").iterdir()):
                if item.is_file():
                    archive.write(item, f"deps/{item.name}")
                    count += 1
                    total += item.stat().st_size
            if ASSETS.is_dir():
                for item in sorted(ASSETS.rglob("*")):
                    if item.is_file():
                        archive.write(item, str(item.relative_to(ROOT)).replace("\\", "/"))
                        count += 1
                        total += item.stat().st_size
            else:
                _log("!! 本机没有 assets\\ 目录 —— 包里不含随包资产（DLSS 运行库等）")
    digest = sha256_of(out)
    (out.with_name(out.name + ".sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    _log(f"完成：{out}")
    _log(f"      {count} 个文件 / 原始 {total / 1048576:.1f} MB / 包体 {out.stat().st_size / 1048576:.1f} MB")
    _log(f"      sha256 {digest}")
    _log("分发：**不进 Release**，只作无法访问 GitHub 时的应急搬运（QQ 群）。")
    return 0


def offline_deps_format() -> int:
    from endfieldmodcontroller import offline_deps

    return offline_deps.BUNDLE_FORMAT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建离线依赖包（应急用，不进 Release）")
    parser.add_argument("--out", default=str(DIST / BUNDLE_NAME), help="输出路径")
    parser.add_argument("--skip-download", action="store_true", help="只用本机已有原件，不联网")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("git") is None:
        _log("提示：本脚本不需要 git，这里只是提醒你确认网络能访问 GitHub。")
    return build(Path(args.out), download=not args.skip_download)


if __name__ == "__main__":
    raise SystemExit(main())
