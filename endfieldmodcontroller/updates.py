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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def download_file(url: str, dest: Path, log: Callable[[str], None] | None = None, timeout: int = 300) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response, open(dest, "wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        step = 0
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total and done * 100 // total >= step + 25:
                step = done * 100 // total
                _log(log, f"下载中 {step}% ({done // 1048576}/{total // 1048576} MB)")
    _log(log, f"下载完成: {dest.name} ({dest.stat().st_size // 1048576} MB)")
    return dest


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
    }
    return versions


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
def check_updates(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """查询各组件的最新可用版本（联网）。"""
    report: dict[str, Any] = {"reshade": {}, "secondary_motion": {}, "errors": []}

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
        releases = _fetch_json(f"{GITHUB_API}/repos/{SBM_REPO}/releases?per_page=5")
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

    _log(log, "更新检查完成: " + json.dumps({
        "reshade": report["reshade"].get("latest"),
        "secondary_motion": report["secondary_motion"].get("latest"),
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


def _stamp() -> str:
    import time

    return time.strftime("%Y%m%d-%H%M%S")
