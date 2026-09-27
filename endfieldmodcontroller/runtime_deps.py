"""Built-in runtime management for XXMI Launcher and the EFMI package.

These are not regular 3DMigoto mods: they are the runtime that loads Mods.  The
functions here download the official GitHub release archives into the
EndfieldModController data directory, install them without touching the game folder,
and update config.json so the launcher can use them.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import dependencies
from .config import AppConfig


XXMI_REPO = "SpectrumQT/XXMI-Launcher"
XXMI_LIBS_REPO = "SpectrumQT/XXMI-Libs-Package"
EFMI_REPO = "SpectrumQT/EFMI-Package"
XXMI_ASSET_PATTERN = "Portable"
XXMI_LIBS_ASSET_PATTERN = "XXMI-PACKAGE"
EFMI_ASSET_PATTERN = "EFMI-PACKAGE"
MARKER_NAME = ".endfieldmodcontroller_builtin.json"


@dataclass
class BuiltinResult:
    key: str
    status: str
    message: str = ""
    version: str = ""
    path: str = ""


Progress = Callable[[int, int, str, str], None] | None
ByteProgress = Callable[[int, int, str, int, int], None] | None


def _find_xxmi_exe(root: Path) -> Path | None:
    candidates = [
        root / "Resources" / "Bin" / "XXMI Launcher.exe",
        root / "XXMI Launcher.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for candidate in root.rglob("XXMI Launcher.exe"):
        if candidate.is_file():
            return candidate
    return None


def _read_marker(root: Path) -> dict:
    marker = root / MARKER_NAME
    if not marker.is_file():
        return {}
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_marker(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER_NAME).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _latest_release_asset(repo: str, pattern: str) -> tuple[str, str, str]:
    release = dependencies._fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")
    assets = release.get("assets") or []
    lowered = pattern.lower()
    matches = [asset for asset in assets if lowered in str(asset.get("name", "")).lower()]
    if not matches:
        raise RuntimeError(f"{repo}: no release asset matched {pattern!r}")
    asset = sorted(matches, key=lambda item: int(item.get("size") or 0), reverse=True)[0]
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError(f"{repo}: release asset has no download URL")
    return url, str(release.get("tag_name") or ""), str(asset.get("name") or "asset.zip")


def _release_info(repo: str) -> dict:
    return dependencies._fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")


def _asset_url(release: dict, name: str) -> str:
    for asset in release.get("assets") or []:
        if str(asset.get("name") or "") == name:
            url = str(asset.get("browser_download_url") or "")
            if url:
                return url
    raise RuntimeError(f"release asset not found: {name}")


def _download_extract(
    url: str,
    asset_name: str,
    target: Path,
    byte_progress: ByteProgress = None,
    index: int = 1,
    total: int = 1,
    key: str = "builtin",
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc-builtin-") as tmp:
        archive = dependencies._http_get(
            url,
            Path(tmp) / asset_name,
            chunk_callback=(lambda received, expected: byte_progress(index, total, key, received, expected)) if byte_progress else None,
        )
        assert isinstance(archive, Path)
        dependencies.extract_archive(archive, target, strip_root=True)


def ensure_xxmi(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None) -> BuiltinResult:
    root = config.builtin_runtime_path / "XXMI"
    existing = _find_xxmi_exe(root)
    marker = _read_marker(root)
    if progress:
        progress(0, 3, "XXMI", "checking")
    url, version, asset_name = _latest_release_asset(XXMI_REPO, XXMI_ASSET_PATTERN)
    if existing and marker.get("version") == version:
        if progress:
            progress(1, 3, "XXMI", "up_to_date")
        return BuiltinResult("XXMI", "up_to_date", "already current", version, str(existing))
    _download_extract(url, asset_name, root, byte_progress, 1, 3, "XXMI")
    exe = _find_xxmi_exe(root)
    if exe is None:
        raise RuntimeError("XXMI Launcher.exe was not found after extraction")
    config.xxmi_launcher = str(exe)
    config.save()
    _write_marker(root, {"version": version, "asset": asset_name, "source": XXMI_REPO})
    if progress:
        progress(1, 3, "XXMI", "installed")
    return BuiltinResult("XXMI", "installed", "installed", version, str(exe))


def ensure_xxmi_libs(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None) -> BuiltinResult:
    root = config.builtin_runtime_path / "XXMI"
    target = root / "Resources" / "Packages" / "XXMI"
    d3d11 = target / "d3d11.dll"
    marker = _read_marker(target)
    if progress:
        progress(0, 3, "XXMI-Libs", "checking")
    release = _release_info(XXMI_LIBS_REPO)
    version = str(release.get("tag_name") or "")
    assets = {str(asset.get("name") or ""): asset for asset in (release.get("assets") or [])}
    zip_name = next((name for name in assets if XXMI_LIBS_ASSET_PATTERN.lower() in name.lower()), "")
    if not zip_name:
        raise RuntimeError(f"{XXMI_LIBS_REPO}: no asset matched {XXMI_LIBS_ASSET_PATTERN!r}")
    if d3d11.is_file() and marker.get("version") == version:
        if progress:
            progress(2, 3, "XXMI-Libs", "up_to_date")
        return BuiltinResult("XXMI-Libs", "up_to_date", "already current", version, str(target))
    archive_url = _asset_url(release, zip_name)
    target.mkdir(parents=True, exist_ok=True)
    _download_extract(archive_url, zip_name, target, byte_progress, 2, 3, "XXMI-Libs")
    manifest_url = _asset_url(release, "Manifest.json")
    manifest_data = dependencies._http_get(manifest_url)
    assert isinstance(manifest_data, bytes)
    (target / "Manifest.json").write_bytes(manifest_data)
    _write_marker(target, {"version": version, "asset": zip_name, "source": XXMI_LIBS_REPO})
    if progress:
        progress(2, 3, "XXMI-Libs", "installed")
    return BuiltinResult("XXMI-Libs", "installed", "installed", version, str(target))


def ensure_efmi(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None) -> BuiltinResult:
    xxmi_root = config.builtin_runtime_path / "XXMI"
    xxmi_exe = _find_xxmi_exe(xxmi_root)
    if xxmi_exe is None:
        ensure_xxmi(config, progress, byte_progress)
    target = xxmi_root / "EFMI"
    core_ini = target / "Core" / "EFMI" / "main.ini"
    marker = _read_marker(target)
    if progress:
        progress(0, 3, "EFMI", "checking")
    url, version, asset_name = _latest_release_asset(EFMI_REPO, EFMI_ASSET_PATTERN)
    if core_ini.is_file() and marker.get("version") == version:
        if progress:
            progress(3, 3, "EFMI", "up_to_date")
        return BuiltinResult("EFMI", "up_to_date", "already current", version, str(target))
    _download_extract(url, asset_name, target, byte_progress, 3, 3, "EFMI")
    _write_marker(target, {"version": version, "asset": asset_name, "source": EFMI_REPO})
    config.staging_mods_dir = str(target / "Mods")
    config.save()
    if progress:
        progress(3, 3, "EFMI", "installed")
    return BuiltinResult("EFMI", "installed", "installed", version, str(target))


def ensure_all(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None) -> list[BuiltinResult]:
    results: list[BuiltinResult] = []
    if progress:
        progress(0, 3, "builtin", "start")
    results.append(ensure_xxmi(config, progress, byte_progress))
    results.append(ensure_xxmi_libs(config, progress, byte_progress))
    results.append(ensure_efmi(config, progress, byte_progress))
    if progress:
        progress(3, 3, "builtin", "complete")
    return results


def dry_run_results(config: AppConfig) -> list[BuiltinResult]:
    report = builtin_report(config)
    results: list[BuiltinResult] = []
    for key, item in report.items():
        results.append(BuiltinResult(
            key=key,
            status="up_to_date" if item.get("present") else "missing",
            message="present" if item.get("present") else "not installed",
            version=str(item.get("version") or ""),
            path=str(item.get("install_dir") or ""),
        ))
    return results


def builtin_report(config: AppConfig) -> dict[str, dict]:
    xxmi_root = config.builtin_runtime_path / "XXMI"
    efmi_root = xxmi_root / "EFMI"
    xxmi_exe = _find_xxmi_exe(xxmi_root)
    xxmi_marker = _read_marker(xxmi_root)
    efmi_marker = _read_marker(efmi_root)
    return {
        "XXMI": {
            "display": "XXMI Launcher",
            "source": "builtin",
            "install_dir": str(xxmi_root),
            "present": xxmi_exe is not None,
            "required": bool(config.use_builtin_runtime),
            "needed": bool(config.use_builtin_runtime),
            "status": "已安装" if xxmi_exe is not None else ("缺失" if config.use_builtin_runtime else "无需"),
            "version": xxmi_marker.get("version", ""),
            "enabled": config.use_builtin_runtime,
        },
        "XXMI-Libs": {
            "display": "XXMI Libraries (d3d11.dll)",
            "source": "builtin",
            "install_dir": str(xxmi_root / "Resources" / "Packages" / "XXMI"),
            "present": (xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll").is_file(),
            "required": bool(config.use_builtin_runtime),
            "needed": bool(config.use_builtin_runtime),
            "status": "已安装" if (xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll").is_file() else ("缺失" if config.use_builtin_runtime else "无需"),
            "version": _read_marker(xxmi_root / "Resources" / "Packages" / "XXMI").get("version", ""),
            "enabled": config.use_builtin_runtime,
        },
        "EFMI": {
            "display": "EFMI Package",
            "source": "builtin",
            "install_dir": str(efmi_root),
            "present": (efmi_root / "Core" / "EFMI" / "main.ini").is_file(),
            "required": bool(config.use_builtin_runtime),
            "needed": bool(config.use_builtin_runtime),
            "status": "已安装" if (efmi_root / "Core" / "EFMI" / "main.ini").is_file() else ("缺失" if config.use_builtin_runtime else "无需"),
            "version": efmi_marker.get("version", ""),
            "enabled": config.use_builtin_runtime,
        },
    }
