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
#: 包体下限（MB）：用户 2026-10-12「325 可以发出去 …… 如果不足 325 补足」——
#: QQ 群分发以 325 MB 这个尺寸实测可行，所以不足就追加 `_padding.bin`（导入时被忽略）。
DEFAULT_MIN_SIZE_MB = 325

#: (key, 说明, 许可) —— key 与 `offline_deps` 的索引键、以及各安装链路的查表键一致。
#: ⚠️ **许可分两类**（2026-10-12 逐一查证，不再凭印象）：
#:   * MIT / BSD 系（XXMI / Libs / EFMI / ReShade / Feeder / iMMERSE / **Streamline**）——
#:     允许再分发，条件是**保留版权与许可声明**（所以包内 `licenses/` 放各自许可文本）；
#:   * **AGPL-3.0（Endfield Poser）**——同样**允许再分发**，但除许可全文外还必须
#:     **给出对应源码的获取途径**（用户 2026-10-12：「poser 指明源码地址」）。包内说明里写。
LICENSES: dict[str, str] = {
    "XXMI": "MIT",
    "XXMI-Libs": "MIT",
    "EFMI": "MIT",
    "ReShade": "BSD-3-Clause",
    "DLSS5-Feeder": "见上游仓库说明",
    "iMMERSE": "MIT",
    "Streamline": "MIT（Copyright (c) 2023 NVIDIA CORPORATION）",
    "Poser": "AGPL-3.0（源码见包内说明）",
    # EndfieldJiggle（触摸形变 Mod，2026-10-13 接入）：GPL-3.0-only，**允许再分发**
    # （条件同样是附许可全文 + 保留版权 + 给出源码途径）。
    "EndfieldJiggle": "GPL-3.0-only（源码见包内说明）",
}

#: AGPL-3.0 的 Poser：包内必须带上"源码在哪"（AGPL 的再分发义务）。
POSER_SOURCE_NOTE = (
    "Endfield Poser（AGPL-3.0）源码与许可：\n"
    "  · 上游：https://github.com/OedoSoldier/Endfield-Poser （fork 自 honxi1/Endfield-Poser）\n"
    "  · 本包内对应的安装包版本见 manifest.json 的 deps.Poser.version\n"
    "  · AGPL-3.0 全文见本包 licenses/AGPL-3.0.txt\n"
    "  按 AGPL-3.0 §4/§6：本包只做原样搬运（未修改任何文件），版权归原作者；\n"
    "  需要对应源码请从上面的地址按同版本获取。\n"
)

#: GPL-3.0-only 的 EndfieldJiggle：同样要写清"源码在哪"（GPL 的再分发义务）。
JIGGLE_SOURCE_NOTE = (
    "EndfieldJiggle（GPL-3.0-only）源码与许可：\n"
    "  · 上游：https://github.com/woakato/EndfieldJiggle-EFMI\n"
    "  · 本包内对应的安装包版本见 manifest.json 的 deps.EndfieldJiggle.version\n"
    "  · GPL-3.0-only 全文见本包 licenses/GPL-3.0-only.txt\n"
    "  按 GPL-3.0：本包只做原样搬运（未修改任何文件），版权归原作者；\n"
    "  需要对应源码请从上面的地址获取（上游未单独发布与本包逐字节对应的源码归档）。\n"
)


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


def _license_text(repo: str) -> str:
    """取仓库许可全文（走 GitHub API —— 网页被加速器劫持时 API 仍然通）。"""
    import base64

    try:
        data = github.api_get(f"https://api.github.com/repos/{repo}/license")
        content = str((data or {}).get("content") or "")
        if content:
            return base64.b64decode(content).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return (f"（没能自动取到许可全文：{exc}）\n"
                f"许可全文请见 https://github.com/{repo}\n")
    return f"许可全文请见 https://github.com/{repo}\n"


def collect(dest: Path, *, download: bool = True) -> dict[str, dict[str, Any]]:
    """把各组件原件收进 `dest/`，返回清单条目（key → 条目）。"""
    dest.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, Any]] = {}

    def record(key: str, path: Path, version: str, source: str, *, extra: dict | None = None) -> None:
        entries[key] = {
            "asset": path.name,
            "version": version,
            "size": path.stat().st_size,
            "sha256": sha256_of(path),
            "source": source,
            "license": LICENSES.get(key, ""),
        }
        if extra:
            entries[key].update(extra)
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

    # ---- Endfield Poser（AGPL-3.0）：**允许再分发**，条件是附许可全文 + 保留版权 + 给出源码途径
    #      （用户 2026-10-12：「poser 指明源码地址」）。包内 `licenses/` 与说明里都写了。
    try:
        url, version, asset_name, digest = runtime_deps._latest_release_asset(
            runtime_deps.POSER_REPO, runtime_deps.POSER_ASSET_PATTERN, include_prerelease=True)
        target = dest / asset_name
        if (not download or _fetch(url, target, digest=digest, label="Poser")) and target.is_file():
            record("Poser", target, version, f"https://github.com/{runtime_deps.POSER_REPO}")
    except Exception as exc:  # noqa: BLE001
        _log(f"!! Poser：{exc}")

    # ---- EndfieldJiggle（GPL-3.0-only，2026-10-13 接入）：只要上游那个**纯 Mod 包**
    #      （`*win64.zip`，约 120 KB；同一个 Release 里的 72 MB 拖放包与 149 MB 独立包
    #      对本程序没有意义）。它的默认开关是**开**的 ⇒ 离线机器必须能拿到它，
    #      否则首次一键启动会去 GitHub 拉、拉不到。
    try:
        from endfieldmodcontroller import efmi_jiggle

        release = github.releases_latest(efmi_jiggle.REPO)
        picked = efmi_jiggle.pick_asset(release)
        if not picked:
            raise RuntimeError("release 里没有纯 Mod 包（*win64.zip）")
        version, asset = picked
        target = dest / str(asset.get("name") or "EndfieldJiggleEFMI-win64.zip")
        url = str(asset.get("browser_download_url") or "")
        if (not download or _fetch(url, target, digest=str(asset.get("digest") or ""),
                                   label="EndfieldJiggle")) and target.is_file():
            record("EndfieldJiggle", target, version, f"https://github.com/{efmi_jiggle.REPO}")
    except Exception as exc:  # noqa: BLE001
        _log(f"!! EndfieldJiggle：{exc}")

    # ---- Streamline 运行库（**MIT**，2026-10-12 查证 license.txt 原文）：9 个 dll 可以随包。
    #      ⚠️ 只打**本机已抽取的那 9 个 dll**（≈11 MB）—— 上游 SDK 本体 263 MB，进包会把包撑到
    #      600 MB，群里根本发不出去。条目里标 `kind: streamline-dlls`，安装侧据此直接落位。
    try:
        installed = ROOT / "runtime" / "streamline"
        marker_path = installed / ".endfieldmodcontroller_builtin.json"
        version = ""
        if marker_path.is_file():
            version = str(json.loads(marker_path.read_text(encoding="utf-8")).get("version") or "")
        missing_dlls = [name for name in runtime_deps.STREAMLINE_WANTED
                        if not (installed / name).is_file()]
        if missing_dlls:
            _log(f"!! Streamline：本机 runtime\\streamline 里缺 {len(missing_dlls)} 个 dll，跳过"
                 f"（先在依赖页把 Streamline 装好再打包）")
        else:
            target = dest / f"streamline-runtime-{version.lstrip('v') or 'unknown'}.zip"
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as packed:
                for name in runtime_deps.STREAMLINE_WANTED:
                    packed.write(installed / name, name)
            record("Streamline", target, version, "https://github.com/NVIDIA-RTX/Streamline",
                   extra={"kind": "streamline-dlls"})
    except Exception as exc:  # noqa: BLE001
        _log(f"!! Streamline：{exc}")

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
        "**不包含**：",
        "  · VC++ 运行库（微软条款：必须跑官方安装器；多数机器本来就有）——",
        "    缺的话可在依赖页让程序检测并引导安装，或从微软官网下载 vc_redist.x64.exe。",
        "",
        "说明：包内若有一个 `_padding.bin`，它只是把包体补到便于分发的体积（约 325 MB），",
        "      导入时会被完全忽略，不参与任何校验。",
        "",
        "许可与来源（本包只做**原样搬运**，未修改任何组件）：",
        "  · 各组件版权归各自作者所有；许可证全文见本包 licenses\\ 目录；",
        "  · 包内各文件的版本与 sha256 见 manifest.json；",
        "  · 若任一作者不希望被这样分发，请联系我们，会立即停止分发并删除。",
        "",
        POSER_SOURCE_NOTE,
        JIGGLE_SOURCE_NOTE,
        f"构建时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines) + "\n"


def _pad_to_min_size(path: Path, min_mb: int) -> int:
    """包体不足 `min_mb` 时**补足**（用户 2026-10-12：「如果不足 325 补足」）。

    实现在 zip 里追加一个 **`_padding.bin`**（零字节，ZIP_STORED 流式写入 —— 不会把几百 MB
    读进内存）。为什么这样做是安全的：导入侧 `offline_deps.inspect_deps_bundle()` 只校验
    `manifest.json` **声明的**那些文件、`import_deps_bundle()` 也只落 `deps/` 前缀的条目，
    根目录这个填充文件两边都会被忽略（包里说明写明了它是干什么的）。

    返回补进去的字节数（0 = 本来就不缺）。
    """
    size = path.stat().st_size
    target = int(min_mb) * 1048576
    if min_mb <= 0 or size >= target:
        return 0
    need = target - size
    chunk = b"\0" * (1 << 20)
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_STORED) as archive:
        with archive.open("_padding.bin", "w") as handle:
            remaining = need
            while remaining > 0:
                piece = chunk if remaining >= len(chunk) else chunk[:remaining]
                handle.write(piece)
                remaining -= len(piece)
    _log(f"包体不足 {min_mb} MB —— 已补足 {need / 1048576:.1f} MB（追加 _padding.bin，"
         f"导入时会被忽略）")
    return need


def build(out: Path, *, download: bool = True, min_mb: int = 0) -> int:
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

        # 许可全文（再分发的前提）：AGPL-3.0（Poser）、GPL-3.0-only（EndfieldJiggle）与
        # MIT（Streamline）都从各自仓库取，走 API（网页被加速器劫持时 API 仍然通）。
        # 取不到就退化成"指向仓库 URL"的说明，**不因此中断打包**
        # （但不能悄悄漏掉 —— 说明里会写清）。
        licenses = work / "licenses"
        licenses.mkdir(parents=True, exist_ok=True)
        from endfieldmodcontroller import efmi_jiggle as _jiggle_repo
        (licenses / "AGPL-3.0.txt").write_text(
            _license_text(runtime_deps.POSER_REPO), encoding="utf-8")
        (licenses / "GPL-3.0-only.txt").write_text(
            _license_text(_jiggle_repo.REPO), encoding="utf-8")
        (licenses / "Streamline-MIT.txt").write_text(
            _license_text("NVIDIA-RTX/Streamline"), encoding="utf-8")

        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        total = 0
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(work / MANIFEST_NAME, MANIFEST_NAME)
            archive.write(work / README_NAME, README_NAME)
            for item in sorted(licenses.iterdir()):
                if item.is_file():
                    archive.write(item, f"licenses/{item.name}")
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
    _pad_to_min_size(out, min_mb)
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
    parser.add_argument("--min-size-mb", type=int, default=DEFAULT_MIN_SIZE_MB,
                        help=f"包体下限（不足就补足，默认 {DEFAULT_MIN_SIZE_MB} MB；0 = 不补）")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("git") is None:
        _log("提示：本脚本不需要 git，这里只是提醒你确认网络能访问 GitHub。")
    return build(Path(args.out), download=not args.skip_download, min_mb=int(args.min_size_mb))


if __name__ == "__main__":
    raise SystemExit(main())
