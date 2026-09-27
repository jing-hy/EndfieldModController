"""Dependency inspection and update support.

The dependency manifest is a JSON file with entries such as:

{
  "RabbitFX": {
    "display": "RabbitFX",
    "kind": "dependency",
    "source": "gamebanana_mod",
    "gamebanana_id": 651557,
    "file_name_contains": "RabbitFX",
    "install_dir": "_deps/RabbitFX",
    "enabled": true
  },
  "MyLibrary": {
    "display": "MyLibrary",
    "source": "github_release",
    "repo": "owner/repo",
    "asset_pattern": ".zip",
    "install_dir": "_deps/MyLibrary"
  }
}

Only zip/tar archives are extracted with the standard library.  For rar/7z the
updater looks for a bundled or system 7-Zip executable and gives a clear error
if none is found.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from . import core


DEFAULT_TIMEOUT = 60
USER_AGENT = "EndfieldModController/0.1 (+https://github.com/)"


@dataclass
class DependencySpec:
    key: str
    display: str
    source: str
    install_dir: str
    version: str = ""
    enabled: bool = True
    gamebanana_id: int | None = None
    file_name_contains: str = ""
    repo: str = ""
    asset_pattern: str = ""
    url: str = ""
    extract: bool = True
    strip_root: bool = True
    required_file: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "DependencySpec":
        return cls(
            key=key,
            display=str(data.get("display") or key),
            source=str(data.get("source") or ""),
            install_dir=str(data.get("install_dir") or f"_deps/{key}"),
            version=str(data.get("version") or ""),
            enabled=bool(data.get("enabled", True)),
            gamebanana_id=int(data["gamebanana_id"]) if data.get("gamebanana_id") else None,
            file_name_contains=str(data.get("file_name_contains") or ""),
            repo=str(data.get("repo") or ""),
            asset_pattern=str(data.get("asset_pattern") or ""),
            url=str(data.get("url") or ""),
            extract=bool(data.get("extract", True)),
            strip_root=bool(data.get("strip_root", True)),
            required_file=str(data.get("required_file") or ""),
            notes=str(data.get("notes") or ""),
        )


@dataclass
class UpdateResult:
    key: str
    status: str                 # up_to_date | updated | downloaded | missing | error | skipped
    message: str = ""
    version: str = ""
    path: str = ""


def load_manifest(path: Path) -> dict[str, DependencySpec]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, DependencySpec] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            try:
                out[key] = DependencySpec.from_dict(key, value)
            except (TypeError, ValueError):
                continue
    return out


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _http_get(
    url: str,
    dest: Path | None = None,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    chunk_callback: Callable[[int, int], None] | None = None,
) -> bytes | Path:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if dest is None:
            return resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            expected = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            expected = 0
        received = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                received += len(chunk)
                if chunk_callback:
                    chunk_callback(received, expected)
        return dest


def _fetch_json(url: str) -> dict[str, Any]:
    """所有 GitHub（以及 GameBanana）的 JSON 查询都走这里。

    走 :mod:`github` 的好处：带上 `GH_TOKEN`/`GITHUB_TOKEN`（额度 60 → 5000 次/小时）、
    30 分钟磁盘缓存（同一地址不重复消耗额度）、以及把 403 限流翻成人话
    （否则用户只看到一个光秃秃的 403，不知道要等多久）。
    """
    from . import github

    return github.api_get(url)


def _cache_dir() -> Path:
    """依赖安装包的下载缓存目录（`<runtime>/_downloads`）。"""
    from .config import AppConfig

    try:
        return AppConfig.load().runtime_path / "_downloads"
    except Exception:  # noqa: BLE001
        return Path.cwd() / "runtime" / "_downloads"


def _download(url: str, dest: Path, chunk_callback: Callable[[int, int], None] | None = None) -> Path:
    """下载依赖包：走 fastnet（慢/抖时临时并发，直连不通时临时换镜像线路）。

    **同一 URL 已经下过就直接复用缓存** —— 以前下载目标是调用方给的临时目录
    （`tempfile.TemporaryDirectory`），用完即弃，于是"明明装过一次，再更新还要
    重新下载一遍"。缓存落在 `<runtime>/_downloads/<文件名>`，并配一份
    `<文件名>.url` 记录来源；只有 URL 完全一致才复用，避免误用旧包。
    """
    from . import fastnet

    target = _cache_dir() / dest.name if dest.name else dest
    meta = target.with_name(target.name + ".url")
    if target.is_file() and meta.is_file():
        try:
            if meta.read_text(encoding="utf-8").strip() == url and target.stat().st_size > 0:
                size = target.stat().st_size
                if chunk_callback:
                    chunk_callback(size, size)
                return target
        except OSError:
            pass

    def on_progress(done: int, total: int) -> None:
        if chunk_callback:
            chunk_callback(done, total)

    target.parent.mkdir(parents=True, exist_ok=True)
    report = fastnet.download(url, target, progress=on_progress, timeout=60)
    if not report.ok:
        raise RuntimeError(report.message)
    try:
        meta.write_text(url, encoding="utf-8")
    except OSError:
        pass
    return target


def _latest_gamebanana_file(profile: dict[str, Any], name_contains: str) -> dict[str, Any] | None:
    files = profile.get("_aFiles") or []
    if not files:
        return None
    if name_contains:
        lowered = name_contains.lower()
        matches = [f for f in files if lowered in str(f.get("_sFile", "")).lower()]
        if matches:
            files = matches
    files = sorted(files, key=lambda f: int(f.get("_tsDateAdded") or 0), reverse=True)
    return files[0] if files else None


def _download_for_spec(
    spec: DependencySpec,
    work_dir: Path,
    chunk_callback: Callable[[int, int], None] | None = None,
) -> tuple[Path, str]:
    """Return (downloaded_path, remote_version_or_timestamp)."""
    if spec.source == "gamebanana_mod" and spec.gamebanana_id:
        profile = _fetch_json(f"https://gamebanana.com/apiv11/Mod/{spec.gamebanana_id}/ProfilePage")
        file_info = _latest_gamebanana_file(profile, spec.file_name_contains)
        if not file_info:
            raise RuntimeError(f"GameBanana mod {spec.gamebanana_id} has no downloadable file")
        url = str(file_info.get("_sDownloadUrl") or "")
        if not url:
            raise RuntimeError("GameBanana file has no download URL")
        file_name = str(file_info.get("_sFile") or "dependency.bin")
        version = str(file_info.get("_tsDateAdded") or "")
        return _download(url, work_dir / file_name, chunk_callback), version  # type: ignore[return-value]

    if spec.source == "github_release" and spec.repo:
        from . import github

        release = github.releases_latest(spec.repo)
        assets = release.get("assets") or []
        pattern = spec.asset_pattern.lower()
        candidates = [a for a in assets if pattern in str(a.get("name", "")).lower()] if pattern else assets
        if not candidates:
            raise RuntimeError(f"no GitHub release asset matched {spec.asset_pattern!r}")
        asset = max(candidates, key=github.asset_sort_key)
        url = str(asset.get("browser_download_url") or "")
        return _download(url, work_dir / str(asset.get("name") or "dependency.bin"), chunk_callback), str(release.get("tag_name") or "")  # type: ignore[return-value]

    if spec.source == "url" and spec.url:
        target = work_dir / Path(spec.url).name
        downloaded = _download(spec.url, target, chunk_callback)
        assert isinstance(downloaded, Path)
        return downloaded, spec.version or _sha256_file(downloaded)  # type: ignore[return-value]

    raise RuntimeError(f"unsupported dependency source: {spec.source!r}")


def _find_7z() -> str | None:
    candidates = [
        Path(__file__).resolve().parents[1] / "tools" / "7zip" / "7z.exe",
        Path(__file__).resolve().parents[1] / "tools" / "7zip" / "7za.exe",
        shutil.which("7z"),
        shutil.which("7za"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def extract_archive(archive: Path, target: Path, *, strip_root: bool = True) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc-extract-") as tmp:
        tmp_path = Path(tmp)
        suffixes = "".join(archive.suffixes).lower()
        if suffixes.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp_path)
        elif suffixes.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
            with tarfile.open(archive) as tf:
                tf.extractall(tmp_path)
        elif suffixes.endswith((".7z", ".rar")):
            seven = _find_7z()
            if not seven:
                raise RuntimeError(f"{archive.name}: rar/7z needs 7z.exe in tools/7zip or on PATH")
            subprocess.run(
                [seven, "x", "-y", f"-o{tmp_path}", str(archive)],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            raise RuntimeError(f"unsupported archive format: {archive.name}")

        entries = list(tmp_path.iterdir())
        source = entries[0] if strip_root and len(entries) == 1 and entries[0].is_dir() else tmp_path
        for item in source.iterdir():
            dest = target / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)


def _install_dir_looks_valid(install_dir: Path, spec: DependencySpec) -> bool:
    """Return True when a previous install still contains its expected payload."""
    if not install_dir.is_dir():
        return False
    if spec.required_file:
        return (install_dir / spec.required_file).is_file()
    return True


def install_from_archive(archive: Path, install_dir: Path, spec: DependencySpec) -> None:
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)
    if spec.extract:
        extract_archive(archive, install_dir, strip_root=spec.strip_root)
    else:
        shutil.copy2(archive, install_dir / archive.name)


def update_dependency(
    spec: DependencySpec,
    library_root: Path,
    *,
    dry_run: bool = False,
    chunk_callback: Callable[[int, int], None] | None = None,
) -> UpdateResult:
    if not spec.enabled:
        return UpdateResult(key=spec.key, status="skipped", message="disabled in manifest")
    if spec.source not in {"gamebanana_mod", "github_release", "url"}:
        return UpdateResult(key=spec.key, status="skipped", message=f"unsupported source {spec.source!r}")

    install_dir = library_root / spec.install_dir
    marker = install_dir / ".endfieldmodcontroller_source.json"
    previous_version = ""
    if marker.is_file():
        try:
            previous_version = str(json.loads(marker.read_text(encoding="utf-8")).get("remote_version") or "")
        except Exception:
            previous_version = ""

    if dry_run:
        status = "missing" if not install_dir.exists() else "up_to_date"
        return UpdateResult(key=spec.key, status=status, message="dry run", version=previous_version, path=str(install_dir))

    with tempfile.TemporaryDirectory(prefix="mc-dep-") as tmp:
        archive, remote_version = _download_for_spec(spec, Path(tmp), chunk_callback=chunk_callback)
        if previous_version and remote_version and previous_version == remote_version and _install_dir_looks_valid(install_dir, spec):
            return UpdateResult(key=spec.key, status="up_to_date", message="already current", version=previous_version, path=str(install_dir))
        install_from_archive(archive, install_dir, spec)
        marker.write_text(json.dumps({
            "key": spec.key,
            "remote_version": remote_version,
            "updated_at": int(time.time()),
            "source": spec.source,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return UpdateResult(
            key=spec.key,
            status="updated" if previous_version else "downloaded",
            message="installed",
            version=remote_version,
            path=str(install_dir),
        )


def update_all(
    manifest: dict[str, DependencySpec],
    library_root: Path,
    *,
    dry_run: bool = False,
    enabled_only: bool = True,
    progress: Callable[[int, int, str, str], None] | None = None,
    byte_progress: Callable[[int, int, str, int, int], None] | None = None,
) -> list[UpdateResult]:
    specs = [spec for spec in manifest.values() if not (enabled_only and not spec.enabled)]
    total = len(specs)
    results: list[UpdateResult] = []
    for index, spec in enumerate(specs, start=1):
        if progress:
            progress(index - 1, total, spec.key, "start")

        def on_bytes(received: int, expected: int, *, _index: int = index, _spec: DependencySpec = spec) -> None:
            if byte_progress:
                byte_progress(_index, total, _spec.key, received, expected)

        try:
            result = update_dependency(spec, library_root, dry_run=dry_run, chunk_callback=on_bytes if byte_progress else None)
        except Exception as exc:  # noqa: BLE001
            result = UpdateResult(key=spec.key, status="error", message=str(exc))
        results.append(result)
        if progress:
            progress(index, total, spec.key, result.status)
    return results


def select_missing_dependencies(
    manifest: dict[str, DependencySpec],
    library_root: Path,
    required_names: Iterable[str],
) -> dict[str, DependencySpec]:
    required = {str(name).lower() for name in required_names}
    selected: dict[str, DependencySpec] = {}
    for key, spec in manifest.items():
        aliases = {key.lower(), spec.display.lower()}
        if not (aliases & required):
            continue
        if _install_dir_looks_valid(library_root / spec.install_dir, spec):
            continue
        selected[key] = replace(spec, enabled=True)
    return selected


def dependency_report(library_root: Path, mods: Iterable[core.ModInfo], manifest_path: Path) -> dict:
    manifest = load_manifest(manifest_path)
    required_names = set(core.collect_required_dependency_names(list(mods)))
    required_lower = {str(name).lower() for name in required_names}
    manifest_lower = {key.lower(): key for key in manifest}
    installed = {}
    for key, spec in manifest.items():
        path = library_root / spec.install_dir
        present = _install_dir_looks_valid(path, spec)
        required = key.lower() in required_lower or spec.display.lower() in required_lower
        needed = required or spec.enabled
        installed[key] = {
            "display": spec.display,
            "path": str(path),
            "install_dir": spec.install_dir,
            "present": present,
            "required": required,
            "needed": needed,
            "status": "已安装" if present else ("缺失" if needed else "无需"),
            "version": spec.version,
            "enabled": spec.enabled,
            "source": spec.source,
        }
    unknown = [name for name in sorted(required_names) if name.lower() not in manifest_lower]
    return {
        "required": sorted(required_names),
        "manifest": installed,
        "unknown": unknown,
    }
