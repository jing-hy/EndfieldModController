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
    from . import fsutil

    root.mkdir(parents=True, exist_ok=True)
    fsutil.write_text_atomic(
        root / MARKER_NAME,
        json.dumps(data, ensure_ascii=False, indent=2),
        newline="\n",
    )


def _latest_release_asset(repo: str, pattern: str) -> tuple[str, str, str, str]:
    """返回 (下载地址, 版本, 资产名, sha256 digest)。"""
    from . import github

    # 先走网页路线（不消耗 API 额度、能借镜像），普通用户没有 token 也能用
    release = github.releases_latest(repo)
    assets = release.get("assets") or []
    lowered = pattern.lower()
    matches = [asset for asset in assets if lowered in str(asset.get("name", "")).lower()]
    if not matches:
        raise RuntimeError(f"{repo}: no release asset matched {pattern!r}")
    asset = max(matches, key=github.asset_sort_key)
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError(f"{repo}: release asset has no download URL")
    return (url, str(release.get("tag_name") or ""), str(asset.get("name") or "asset.zip"),
            str(asset.get("digest") or ""))


def _release_info(repo: str) -> dict:
    from . import github

    return github.releases_latest(repo)


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
    expected_sha256: str = "",
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc-builtin-") as tmp:
        archive = dependencies._http_get(
            url,
            Path(tmp) / asset_name,
            chunk_callback=(lambda received, expected: byte_progress(index, total, key, received, expected)) if byte_progress else None,
            expected_sha256=expected_sha256,
        )
        assert isinstance(archive, Path)
        # 2026-10-01 修（⑧）：原先直接解压进 target（copytree 合并语义）—— 更新时
        # 旧版本文件不会被清掉，`_find_xxmi_exe` 的 rglob 兜底可能命中旧版 Launcher
        # 并写进配置；中途失败还会留下"半新半旧"且无从回滚。
        # 现在：先解压到临时目录 → 校验非空 → **逐文件原子替换**合并进 target。
        # 刻意**不删除新包里没有的文件**：target 里还有 EFMI / Mods / 用户配置，
        # 整目录替换会把它们一起弄丢。
        from . import fsutil

        staging = Path(tmp) / "unpacked"
        dependencies.extract_archive(archive, staging, strip_root=True)
        entries = [item for item in staging.rglob("*") if item.is_file()]
        if not entries:
            raise RuntimeError(f"{asset_name}: 解压结果为空")
        for item in entries:
            destination = target / item.relative_to(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fsutil.write_bytes_atomic(destination, item.read_bytes())


def ensure_xxmi(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None) -> BuiltinResult:
    root = config.builtin_runtime_path / "XXMI"
    existing = _find_xxmi_exe(root)
    marker = _read_marker(root)
    if progress:
        progress(0, 3, "XXMI", "checking")
    url, version, asset_name, digest = _latest_release_asset(XXMI_REPO, XXMI_ASSET_PATTERN)
    if existing and marker.get("version") == version:
        if progress:
            progress(1, 3, "XXMI", "up_to_date")
        return BuiltinResult("XXMI", "up_to_date", "already current", version, str(existing))
    _download_extract(url, asset_name, root, byte_progress, 1, 3, "XXMI", expected_sha256=digest)
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
    _download_extract(archive_url, zip_name, target, byte_progress, 2, 3, "XXMI-Libs",
                      expected_sha256=str((assets.get(zip_name) or {}).get("digest") or ""))
    manifest_url = _asset_url(release, "Manifest.json")
    manifest_data = dependencies._http_get(
        manifest_url,
        expected_sha256=str((assets.get("Manifest.json") or {}).get("digest") or ""),
    )
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
    url, version, asset_name, digest = _latest_release_asset(EFMI_REPO, EFMI_ASSET_PATTERN)
    if core_ini.is_file() and marker.get("version") == version:
        if progress:
            progress(3, 3, "EFMI", "up_to_date")
        return BuiltinResult("EFMI", "up_to_date", "already current", version, str(target))
    _download_extract(url, asset_name, target, byte_progress, 3, 3, "EFMI", expected_sha256=digest)
    _write_marker(target, {"version": version, "asset": asset_name, "source": EFMI_REPO})
    config.staging_mods_dir = str(target / "Mods")
    config.save()
    if progress:
        progress(3, 3, "EFMI", "installed")
    return BuiltinResult("EFMI", "installed", "installed", version, str(target))


def ensure_all(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None) -> list[BuiltinResult]:
    """安装三个内置组件（XXMI / XXMI-Libs / EFMI）。

    **单项失败不中断其它项，跑完后再对失败项重试（最多 3 次）。**
    用户 2026-10-01 要求：「下载一旦失败就停了，改成全部下载完之后如果有失败项，
    就重试，3 次截止」——以前 `ensure_xxmi` 抛异常会让后面两个组件连试都不试。
    """
    steps: list[tuple[str, Callable[..., BuiltinResult], int]] = [
        ("XXMI", ensure_xxmi, 0),
        ("XXMI-Libs", ensure_xxmi_libs, 1),
        ("EFMI", ensure_efmi, 2),
    ]
    total = len(steps)
    ok_status = {"installed", "up_to_date", "skipped", "present"}
    if progress:
        progress(0, total, "builtin", "start")

    def worker(step: tuple[str, Callable[..., BuiltinResult], int], attempt: int) -> BuiltinResult:
        key, function, index = step
        if progress:
            progress(index, total, key, "start" if attempt == 0 else f"重试第 {attempt} 次")
        result = function(config, progress, byte_progress)
        if not isinstance(result, BuiltinResult):
            raise RuntimeError(f"{key}: 安装没有返回结果")
        if str(result.status) not in ok_status:
            raise RuntimeError(result.message or f"{key}: 安装失败（{result.status}）")
        if progress:
            progress(index + 1, total, key, result.status)
        return result

    def on_retry(attempt: int, pending: list[tuple[str, Callable[..., BuiltinResult], int]]) -> None:
        if progress:
            for key, _function, index in pending:
                progress(index, total, key, f"重试第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次")

    outcomes, _pending = dependencies.run_batch_with_retry(steps, worker, on_retry=on_retry)
    results: list[BuiltinResult] = []
    for index, (key, _function, _i) in enumerate(steps):
        kind, payload = outcomes[index]
        if kind == "ok":
            results.append(payload)
        else:
            results.append(BuiltinResult(key=key, status="error", message=str(payload)))
    if progress:
        progress(total, total, "builtin", "complete")
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
