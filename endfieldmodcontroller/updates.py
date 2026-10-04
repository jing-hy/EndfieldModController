"""组件版本检查与更新。

覆盖两类组件：

* **DLSS5 / ReShade 底座** —— 本机是 ReShade 6.8.0 Addon 版（`runtime\\dlss5\\d3d12.dll`）。
  官方源 reshade.me 可下载最新 Addon 版；下载后改名成 `d3d12.dll` 并备份旧版。
* **乳摇插件 SecondaryMotion** —— GitHub 仓库
  `Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics` 的 release 里带
  `ShakingBreastManager-v*-ZH-win-x64.zip`，按版本号比较后可直接更新。

所有下载都写到临时目录，确认无误后再替换，旧文件一律备份。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

USER_AGENT = "EndfieldModController/0.1"
RESHADE_SETUP_URL = "https://reshade.me/downloads/ReShade_Setup_{version}_Addon.exe"
RESHADE_HOMEPAGE = "https://reshade.me/"
SBM_REPO = "Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics"
GITHUB_API = "https://api.github.com"


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def file_version(path: Path) -> str:
    """读 PE 文件版本资源（Windows）。失败返回空串。"""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD),
            ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD),
            ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD),
            ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (OSError, AttributeError):
        return ""


def _fetch_json(url: str, timeout: int = 25) -> Any:
    """GitHub 查询统一走 github 模块（token + 缓存 + 把 403 翻成人话）。"""
    from . import github

    return github.api_get(url, timeout=timeout)


def download_file(
    url: str,
    dest: Path,
    log: Callable[[str], None] | None = None,
    timeout: int = 300,
    *,
    expected_sha256: str = "",
) -> Path:
    """下载一个文件（走 fastnet：慢/抖时临时并发、直连不通时临时换镜像线路）。

    失败仍然抛 urllib.error.URLError，保持既有调用方的 except 兼容。
    """
    from . import fastnet

    # 命中缓存就跳过：同一 URL 下过一次就不再重下（用户网慢，重复下几百 MB 很痛）
    target, meta = _cache_target(dest)
    if target is not None and meta is not None and target.is_file() and meta.is_file():
        try:
            if meta.read_text(encoding="utf-8").strip() == url and target.stat().st_size > 0:
                if log:
                    log(f"命中下载缓存，跳过下载：{target.name}"
                        f"（{target.stat().st_size / 1048576:.1f} MB）")
                return target
        except OSError:
            pass

    final = target if target is not None else dest
    final.parent.mkdir(parents=True, exist_ok=True)
    report = fastnet.download(
        url, final, log=log, timeout=min(timeout, 60), expected_sha256=expected_sha256,
    )
    if not report.ok:
        raise urllib.error.URLError(report.message)
    if meta is not None:
        try:
            meta.write_text(url, encoding="utf-8")
        except OSError:
            pass
    return final


def _cache_dir() -> Path:
    """组件安装包的下载缓存目录（`<runtime>/_downloads`）。

    ⚠️ 实现收敛到 `fsutil.downloads_cache_dir()`（2026-10-04）：原先与
    `dependencies._cache_dir` 逐字节相同。
    """
    from . import fsutil

    return fsutil.downloads_cache_dir()


def _cache_target(dest: Path) -> tuple[Path | None, Path | None]:
    """把「临时下载目标」换成稳定缓存路径。

    返回 (目标文件, 记录来源 URL 的元数据文件)。**只有 URL 与上次完全一致才复用** ——
    这样"文件名不带版本"的包（如 `iMMERSE-main.zip`）在版本变化时 URL 也变了，
    会正常重新下载，不会误用旧包。
    """
    if not dest.name:
        return None, None
    target = _cache_dir() / dest.name
    return target, target.with_name(target.name + ".url")


def _find_7z() -> str | None:
    for candidate in (shutil.which("7z"), shutil.which("7za"), shutil.which("7zr")):
        if candidate:
            return candidate
    return None


# ---------------------------------------------------------------------------
# 版本汇总
# ---------------------------------------------------------------------------
def component_versions(config: AppConfig) -> dict[str, Any]:
    """当前各组件的版本 / 存在性，供 UI 显示。"""
    from . import secondary_motion

    dlss5_dir = config.dlss5_path
    dll = config.dlss5_dll_path
    versions: dict[str, Any] = {
        "reshade": {
            "name": "ReShade 底座 (d3d12.dll)",
            "path": str(dll),
            "version": file_version(dll) if dll.is_file() else "",
            "exists": dll.is_file(),
            "size": dll.stat().st_size if dll.is_file() else 0,
        },
        "dlss5_addon": {
            "name": "RenoDX DLSS5 插件",
            "version": _version_from_filename(dlss5_dir, "renodx-dlss5"),
            "exists": any(dlss5_dir.glob("renodx-dlss5*.addon64")),
        },
        "enhancer": {
            "name": "第一人称插件 (Enhancer)",
            "exists": config.dlss5_enhancer_addon_path.is_file(),
            "path": str(config.dlss5_enhancer_addon_path),
        },
        "feed": {
            "name": "DLSS5-Feeder",
            "exists": (dlss5_dir / "dlss5-feed.addon64").is_file(),
        },
        "shaders": {
            "name": "reshade-shaders",
            "exists": (dlss5_dir / "reshade-shaders" / "Shaders").is_dir(),
        },
        "nvngx": {
            "name": "DLSS 运行库 (nvngx)",
            "dlss": (dlss5_dir / "nvngx_dlss.dll").stat().st_size if (dlss5_dir / "nvngx_dlss.dll").is_file() else 0,
            "dlssnr": (dlss5_dir / "nvngx_dlssnr.dll").stat().st_size if (dlss5_dir / "nvngx_dlssnr.dll").is_file() else 0,
        },
        "xxmi": _xxmi_versions(config),
        "secondary_motion": {
            "name": "乳摇插件 (SecondaryMotion)",
            "version": _sbm_local_version(config),
            "path": str(config.secondary_motion_exe or ""),
            "exists": bool(config.secondary_motion_exe),
            "repository": f"https://github.com/{SBM_REPO}",
        },
        "poser": {
            "name": "Endfield Poser (摆姿 / MMD 播放)",
            "version": _poser_local_version(config),
            "path": str(config.poser_path),
            "exists": ((config.poser_path / "plugin" / "poser.dll").is_file()
                       or (config.poser_path / "poser.dll").is_file()),
            "repository": "https://github.com/OedoSoldier/Endfield-Poser",
            "license": "AGPL-3.0",
        },
    }
    return versions


def _poser_local_version(config: AppConfig) -> str:
    """Poser 安装包本地版本：读 runtime_deps 写的 marker（记录上游 tag）。"""
    from .runtime_deps import MARKER_NAME

    marker = config.poser_path / MARKER_NAME
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if isinstance(data, dict):
            return str(data.get("version") or "")
    return ""


def _version_from_filename(directory: Path, prefix: str) -> str:
    for item in directory.glob(f"{prefix}*"):
        match = re.search(r"(\d+(?:\.\d+)+)", item.name)
        if match:
            return match.group(1)
    return ""


def _xxmi_versions(config: AppConfig) -> dict[str, Any]:
    launcher = config.xxmi_launcher_path
    result: dict[str, Any] = {"name": "XXMI / EFMI", "launcher": str(launcher or ""), "packages": {}}
    if launcher is None:
        return result
    from . import reshade_integration

    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        return result
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        packages = (data.get("Packages") or {}).get("packages") or {}
        result["packages"] = {
            key: (value or {}).get("deployed_version", "") for key, value in packages.items()
        }
    except (OSError, json.JSONDecodeError):
        pass
    return result


def _sbm_local_version(config: AppConfig) -> str:
    root = config.secondary_motion_root
    if root is None:
        return ""
    for base in (root, root / "SecondaryMotion"):
        version_file = base / "version.txt"
        if version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8", errors="replace").strip().lstrip("vV")
            except OSError:
                text = ""
            if text:
                return text
    match = re.search(r"[vV](\d+(?:\.\d+)+)", root.name)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# 检查更新
# ---------------------------------------------------------------------------
def _builtin_local_version(config: AppConfig, key: str) -> str:
    """读内置组件**本地已装版本**（读 marker 文件；没有就返回空串 = 未安装）。"""
    try:
        from . import runtime_deps

        roots = {
            "XXMI": config.builtin_runtime_path / "XXMI",
            "XXMI-Libs": config.builtin_runtime_path / "XXMI",
            "EFMI": config.builtin_runtime_path / "XXMI",
        }
        root = roots.get(key)
        if root is None:
            return ""
        marker = runtime_deps._read_marker(root) or {}
        if key == "XXMI":
            return str(marker.get("version") or "")
        # ⚠️ **不要退回 XXMI 的 `version`**（2026-10-03 实测踩到）：三者在同一个 marker 文件里，
        # 图省事一律读 `version` 会让 Libs/EFMI 显示成 XXMI 的版本号（实测显示 v2.2.1），
        # "有没有更新"的判断随之整个错掉。找不到自己的键就**如实留空**。
        return str(marker.get(f"{key}_version") or "")
    except Exception:  # noqa: BLE001
        return ""


def check_updates(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """查询各组件的最新可用版本（联网）。"""
    report: dict[str, Any] = {"reshade": {}, "secondary_motion": {}, "poser": {},
                              # ⚠️ 内置组件（XXMI / XXMI-Libs / EFMI）单独一段：
                              # 用户要更新的往往就是它们（2026-10-03 补）。
                              "builtin": {}, "errors": []}

    # ReShade 官方最新版
    try:
        req = urllib.request.Request(RESHADE_HOMEPAGE, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=25) as response:
            html = response.read().decode("utf-8", errors="replace")
        matches = re.findall(r"ReShade_Setup_(\d+\.\d+\.\d+)_Addon\.exe", html)
        current = component_versions(config)["reshade"]["version"]
        latest = matches[0] if matches else ""
        report["reshade"] = {
            "current": current,
            "latest": latest,
            "update_available": bool(latest and current and latest != current.split(".")[0] + "." + ".".join(current.split(".")[1:3])),
            "download_url": RESHADE_SETUP_URL.format(version=latest) if latest else "",
            "note": "官方新版可能与 DLSS5 插件不兼容（本方案实测版本为 6.8.0），更新前会备份旧底座。",
        }
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"ReShade 检查失败: {exc}")

    # 乳摇插件 GitHub release
    try:
        from . import github

        # 优先走网页路线（不吃 API 额度、能借镜像线路）——没有 token 的用户也能用；
        # 万一网页不通再退回老的多版本列表接口。
        try:
            releases = [github.releases_latest(SBM_REPO)]
        except Exception:  # noqa: BLE001
            releases = _fetch_json(f"{GITHUB_API}/repos/{SBM_REPO}/releases?per_page=5") or []
        local = _sbm_local_version(config)
        best: dict[str, Any] | None = None
        for release in releases or []:
            for asset in release.get("assets") or []:
                name = asset.get("name") or ""
                if not name.lower().endswith(".zip") or "-zh-" not in name.lower():
                    continue
                match = re.search(r"[vV](\d+(?:\.\d+)+)", name)
                version = match.group(1) if match else ""
                if best is None or _version_tuple(version) > _version_tuple(best["version"]):
                    best = {
                        "version": version,
                        "asset": name,
                        "url": asset.get("browser_download_url", ""),
                        "size": asset.get("size", 0),
                        "tag": release.get("tag_name", ""),
                        "published": release.get("published_at", ""),
                        "notes": (release.get("name") or "").strip(),
                    }
        report["secondary_motion"] = {
            "current": local,
            "latest": (best or {}).get("version", ""),
            "update_available": bool(best and local and _version_tuple(best["version"]) > _version_tuple(local)),
            "download_url": (best or {}).get("url", ""),
            "asset": (best or {}).get("asset", ""),
            "size": (best or {}).get("size", 0),
            "tag": (best or {}).get("tag", ""),
            "published": (best or {}).get("published", ""),
            "notes": (best or {}).get("notes", ""),
        }
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"乳摇插件检查失败: {exc}")

    # Endfield Poser（摆姿 / MMD 播放插件）：上游**只发预发布版**，所以必须走
    # github.releases_list（/releases/latest 会跳过预发布，用它永远查不到 Poser）。
    try:
        from . import github, poser

        release = github.releases_list(poser.REPO, include_prerelease=True)
        assets = [asset for asset in (release.get("assets") or [])
                  if "win64.zip" in str(asset.get("name") or "").lower()]
        asset = max(assets, key=github.asset_sort_key) if assets else {}
        local = _poser_local_version(config)
        latest = str(release.get("tag_name") or "").lstrip("vV")
        report["poser"] = {
            "current": (local or "").lstrip("vV"),
            "latest": latest,
            "update_available": bool(latest and local and _version_tuple(latest) > _version_tuple(local)),
            "installed": not local,
            "download_url": str(asset.get("browser_download_url") or ""),
            "asset": str(asset.get("name") or ""),
            "size": int(asset.get("size") or 0),
            "tag": str(release.get("tag_name") or ""),
            "published": str(release.get("published_at") or ""),
            "prerelease": bool(release.get("prerelease")),
            "notes": str(release.get("name") or "").strip(),
            "license": "AGPL-3.0",
            "repository": f"https://github.com/{poser.REPO}",
        }
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"Poser 检查失败: {exc}")

    # ── 内置组件（XXMI / XXMI-Libs / EFMI）──────────────────────────────────
    # ⚠️ 2026-10-03 补：这三项以前**完全不在检查范围内**，而用户最常要更新的就是 XXMI。
    # 判定复用 `runtime_deps` 的"远端最新版"查询与本地 marker，不另造通道。
    try:
        from . import runtime_deps

        specs = [
            ("XXMI", runtime_deps.XXMI_REPO, runtime_deps.XXMI_ASSET_PATTERN, "XXMI"),
            ("XXMI-Libs", runtime_deps.XXMI_LIBS_REPO, runtime_deps.XXMI_LIBS_ASSET_PATTERN, "XXMI-Libs"),
            ("EFMI", runtime_deps.EFMI_REPO, runtime_deps.EFMI_ASSET_PATTERN, "EFMI"),
        ]
        for key, repo, pattern, label in specs:
            try:
                _url, latest, _asset, _digest = runtime_deps._latest_release_asset(repo, pattern)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"{label} 检查失败: {exc}")
                continue
            local = _builtin_local_version(config, key)
            report["builtin"][key] = {
                "display": label,
                "current": local or "",
                "latest": latest or "",
                # ⚠️ 没有本地版本时算"未安装"而不是"有更新"（由依赖页负责首次安装）
                "update_available": bool(local and latest and _version_tuple(latest) > _version_tuple(local)),
                "installed": bool(local),
                "kind": "builtin",
            }
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"内置组件检查失败: {exc}")

    _log(log, "更新检查完成: " + json.dumps({
        "reshade": report["reshade"].get("latest"),
        "secondary_motion": report["secondary_motion"].get("latest"),
        "poser": report["poser"].get("latest"),
    }, ensure_ascii=False))
    return report


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(p) for p in parts) or (0,)


# ---------------------------------------------------------------------------
# 执行更新
# ---------------------------------------------------------------------------
def update_reshade_base(config: AppConfig, version: str = "", log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """下载官方 ReShade Addon 并替换 DLSS5 目录里的 d3d12.dll（旧版备份）。"""
    seven = _find_7z()
    if not seven:
        return {"ok": False, "message": "需要 7z.exe 才能解包 ReShade 安装器"}
    version = version or "6.8.0"
    target_dir = config.dlss5_path
    target_dll = config.dlss5_dll_path
    if not target_dir.is_dir():
        return {"ok": False, "message": f"DLSS5 目录不存在: {target_dir}"}
    url = RESHADE_SETUP_URL.format(version=version)
    try:
        with tempfile.TemporaryDirectory(prefix="mc-reshade-") as tmp:
            tmp_path = Path(tmp)
            setup = download_file(url, tmp_path / f"ReShade_Setup_{version}_Addon.exe", log=log, timeout=600)
            extract = tmp_path / "extract"
            extract.mkdir()
            result = subprocess.run(
                [seven, "x", "-y", f"-o{extract}", str(setup)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return {"ok": False, "message": f"解包失败: {result.stderr or result.stdout}"}
            source = extract / "ReShade64.dll"
            if not source.is_file():
                return {"ok": False, "message": "安装器里没有 ReShade64.dll"}
            stamp = _stamp()
            if target_dll.is_file():
                shutil.copy2(target_dll, target_dll.with_suffix(f".dll.bak-{stamp}"))
            shutil.copy2(source, target_dll)
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "message": f"下载/替换失败: {exc}"}
    _log(log, f"ReShade 底座已更新到 {version}")
    return {
        "ok": True,
        "version": version,
        "target": str(target_dll),
        "note": "如 DLSS5 神经渲染失效，把 .dll.bak-* 备份改回 d3d12.dll 即可回退。",
    }


def update_secondary_motion(config: AppConfig, url: str = "", log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """下载乳摇插件最新 release 并替换工具目录（保留 logs/presets/data/settings）。"""
    from . import secondary_motion

    if not url:
        report = check_updates(config, log=log)
        url = (report.get("secondary_motion") or {}).get("download_url", "")
    if not url:
        return {"ok": False, "message": "没有拿到可用的下载地址"}
    try:
        with tempfile.TemporaryDirectory(prefix="mc-sbm-") as tmp:
            archive = download_file(url, Path(tmp) / "SecondaryMotion.zip", log=log, timeout=900)
            result = secondary_motion.import_pack(config, archive, log=log)
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "message": f"下载失败: {exc}"}
    if result.get("ok"):
        result["note"] = "日志/Presets/角色数据已保留，旧版整体备份在旁边 _backup_* 目录。"
    return result


def update_poser(config: AppConfig, url: str = "", log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """下载 Endfield Poser 安装包并更新到数据目录，再补齐游戏目录里的文件。

    分两步是刻意的：安装包只落在 `runtime\\poser`，**游戏目录一律交给它自己的安装
    向导**（`tools\\deploy.ps1`），我们不直接写 proxy / poser.dll。
    """
    from . import poser

    if url:
        try:
            with tempfile.TemporaryDirectory(prefix="mc-poser-") as tmp:
                archive = download_file(url, Path(tmp) / "Endfield-Poser.zip", log=log, timeout=900)
                result = poser.import_pack(config, archive, log=log)
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "message": f"下载失败: {exc}"}
    else:
        result = poser.ensure_pack(config, log=log, force=True)

    if result.get("ok"):
        injection = poser.ensure_injection(config, log=log)
        result["install"] = injection
        if not injection.get("ok"):
            result["note"] = injection.get("message") or "安装包已更新，但游戏目录里的文件没装好"
    return result


def _stamp() -> str:
    import time

    return time.strftime("%Y%m%d-%H%M%S")
