"""随仓库分发的二进制资产（DLSS 运行库 + 无上游的 DLSS5 组件）——首次启动自动展开。

两类资产都放在 `assets/` 下、**压缩 + 按需分卷**，由本模块在启动自检时自动
解压回 `dlss5_dir`，让用户拿到仓库/便携包就能开箱即用：

* `assets/nvngx/` —— `nvngx_dlss.dll` / `nvngx_dlssnr.dll`。后者压缩后 103 MB，
  超过 GitHub 单文件 100 MiB 上限，所以切成 `.part1` / `.part2`；
  NVIDIA 官方 SDK 也**没有** `nvngx_dlssnr.dll` 的直链，只能随包。
* `assets/dlss5/` —— DLSS5 底座里**查不到公开上游**的三个 addon
  （Endfield Enhancer 第一人称、ReShade 面板汉化、RenoDX-DLSS5 汉化版）。

有公开上游的组件（ReShade 底座、DLSS5-Feeder、iMMERSE shader、XXMI/EFMI）
不在这里，走 `dlss5_fetcher` 的在线自动安装。

设计要点（都对应用户踩过的坑）：

* **流式**：按分卷顺序喂 `LZMADecompressor`，全程不把 165 MB 读进内存；
* **先校验后落盘**：解压到同目录的 `.mc-tmp`，比对大小与 sha256 通过后
  `os.replace` 原子改名——中途断电/磁盘满不会留下半截的 DLL；
* **幂等**：目标文件大小与清单一致就直接跳过，不重复解压（每次重解 5~15 秒
  会让"一键启动"变慢）；
* **有进度**：解压是慢操作，必须给 UI/日志可见的进度，不能黑着。

资产由 `scripts/pack_nvngx_assets.py` 生成，清单见各目录下的 `manifest.json`。
"""
from __future__ import annotations

import hashlib
import json
import lzma
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import PROJECT_ROOT, AppConfig

# 资产组：目录名 → 说明（都解压到 dlss5_dir）
ASSET_GROUPS: dict[str, str] = {
    "nvngx": "NVIDIA DLSS 运行库（随包，压缩分卷）",
    "dlss5": "DLSS5 组件包（无公开上游，随包内置）",
}
MANIFEST_NAME = "manifest.json"
CHUNK = 1 << 22
TMP_SUFFIX = ".mc-tmp"

Progress = Callable[[str, int, int], None] | None


@dataclass
class AssetResult:
    name: str
    status: str          # present | extracted | missing_source | error
    message: str = ""
    size: int = 0
    sha256: str = ""
    path: str = ""
    group: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in {"present", "extracted"}


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def group_root(config: AppConfig, group: str) -> Path | None:
    """某组资产目录（第一个含 manifest.json 的候选）。"""
    subdir = Path("assets") / group
    candidates: list[Path] = []
    # 允许用配置项覆盖根目录（个别用户会把 assets 挪到别处）
    configured = getattr(config, "nvngx_assets_dir", "") or ""
    if configured and group == "nvngx":
        candidates.append(config.resolve_path(configured))
        candidates.append(config.resolve_path(configured).parent / "dlss5")
    candidates.append(PROJECT_ROOT / subdir)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / subdir)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / subdir)
    candidates.append(Path(__file__).resolve().parents[1] / subdir)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if (candidate / MANIFEST_NAME).is_file():
                return candidate
        except OSError:
            continue
    return None


def load_manifest(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def iter_assets(config: AppConfig) -> Iterator[tuple[str, Path, str, dict[str, Any]]]:
    """依次产出 (组名, 资产目录, 文件名, 清单条目)。"""
    for group in ASSET_GROUPS:
        root = group_root(config, group)
        if root is None:
            continue
        entries = load_manifest(root).get("files") or {}
        for name, entry in entries.items():
            if isinstance(entry, dict):
                yield group, root, str(name), dict(entry)


def manifest_entries(config: AppConfig) -> list[tuple[str, Path, str, dict[str, Any]]]:
    return list(iter_assets(config))


def sha256_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    digest = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, size)
    return digest.hexdigest()


def _decompress_parts(parts: list[Path], dest: Path, *, progress: Progress, name: str) -> int:
    """按序拼接分卷并流式解压到 dest，返回写出的字节数。"""
    total = sum(part.stat().st_size for part in parts)
    written = 0
    done = 0
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    with open(dest, "wb") as out:
        for part in parts:
            with open(part, "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    data = decompressor.decompress(chunk)
                    if data:
                        out.write(data)
                        written += len(data)
                    if progress:
                        progress(name, done, total)
            if decompressor.eof:
                break
        if not decompressor.eof:
            raise lzma.LZMAError("压缩流不完整（分卷缺失或被截断）")
    return written


def ensure_file(
    config: AppConfig,
    name: str,
    entry: dict[str, Any],
    root: Path,
    *,
    group: str = "",
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
) -> AssetResult:
    """确保 `dlss5_dir\\<name>` 在位（缺失/损坏时从内置资产展开）。"""
    target = config.dlss5_path / name
    expected_size = int(entry.get("size") or 0)
    expected_sha = str(entry.get("sha256") or "")

    if target.is_file() and not force:
        size = target.stat().st_size
        if not expected_size or size == expected_size:
            if verify and expected_sha:
                actual = sha256_file(target)
                if actual == expected_sha:
                    return AssetResult(name, "present", f"{size:,} B（已校验）", size, actual, str(target), group)
                _log(log, f"{name}: 内容校验不符，将从内置资产修复")
            else:
                return AssetResult(name, "present", f"{size:,} B 已就位", size, "", str(target), group)
        else:
            _log(log, f"{name}: 现有文件 {size:,} B 与内置版本 {expected_size:,} B 不符，重新展开")

    part_names = [str(p) for p in (entry.get("parts") or [])]
    if not part_names:
        return AssetResult(name, "missing_source", "清单里没有分卷记录", 0, "", str(target), group)
    parts = [root / part for part in part_names]
    missing = [part.name for part in parts if not part.is_file()]
    if missing:
        return AssetResult(
            name, "missing_source",
            f"内置资产缺分卷 {missing}（重新运行 scripts\\pack_nvngx_assets.py）",
            0, "", str(target), group,
        )

    packed_bytes = sum(part.stat().st_size for part in parts)
    try:
        config.dlss5_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return AssetResult(name, "error", f"无法创建 {config.dlss5_path}: {exc}", 0, "", str(target), group)

    try:
        free = shutil.disk_usage(config.dlss5_path).free
        if expected_size and free < expected_size + (16 << 20):
            return AssetResult(
                name, "error",
                f"磁盘空间不足：需要约 {expected_size // 1048576} MB，可用 {free // 1048576} MB",
                0, "", str(target), group,
            )
    except OSError:
        pass

    tmp = target.with_name(target.name + TMP_SUFFIX)
    started = time.time()
    _log(log, f"展开内置资产 {name}（{packed_bytes / 1048576:.1f} MB 压缩包 → {expected_size / 1048576:.1f} MB）")
    actual_sha = ""
    try:
        written = _decompress_parts(parts, tmp, progress=progress, name=name)
        if expected_size and written != expected_size:
            raise lzma.LZMAError(f"解压大小不符：得到 {written:,} B，清单要求 {expected_size:,} B")
        actual_sha = sha256_file(tmp)
        if expected_sha and actual_sha != expected_sha:
            raise lzma.LZMAError(f"sha256 校验失败（得到 {actual_sha[:16]}…，期望 {expected_sha[:16]}…）")
        os.replace(tmp, target)
    except (OSError, lzma.LZMAError, EOFError) as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return AssetResult(name, "error", f"展开失败: {exc}", 0, "", str(target), group)
    elapsed = time.time() - started
    return AssetResult(
        name, "extracted",
        f"已从内置资产展开（{target.stat().st_size:,} B，{elapsed:.1f}s）",
        target.stat().st_size, actual_sha, str(target), group, elapsed,
    )


def ensure_all(
    config: AppConfig,
    *,
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
    allow_fetch: bool = True,
) -> list[AssetResult]:
    """展开所有随包资产里缺失的文件。已就位的直接跳过。

    本地没有 `assets\\`（典型情况：用户只下了单文件 exe，没下资产包）时，
    会尝试从本仓库 Release 拉一次 `assets-bundle.zip` 再展开。
    """
    found = manifest_entries(config)
    if not found and allow_fetch:
        fetched = fetch_bundle(config, log=log)
        if fetched.get("changed"):
            found = manifest_entries(config)
        elif fetched.get("message"):
            _log(log, f"未能获取资产包：{fetched['message']}")
    if not found:
        return [AssetResult(
            "*", "missing_source",
            "找不到随包资产目录 assets\\nvngx、(assets\\dlss5)"
            "（源码/便携包不完整，或用的是旧版 Release）",
        )]
    results: list[AssetResult] = []
    for group, root, name, entry in found:
        results.append(ensure_file(
            config, name, entry, root,
            group=group, progress=progress, log=log, force=force, verify=verify,
        ))
    return results


# ---------------------------------------------------------------------------
# 资产包：单文件 exe 用户没有本地 assets 时，从 Release 拉一次
# ---------------------------------------------------------------------------
BUNDLE_PATTERN = "assets-bundle"
BUNDLE_STALE_SECONDS = 24 * 3600


def _extract_bundle(archive: Path, dest_root: Path) -> int:
    """只接受压缩包里 `assets/...` 下的条目（防目录穿越 / 防乱写）。"""
    import zipfile

    written = 0
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
            if "assets" not in parts or ".." in parts:
                continue
            relative = parts[parts.index("assets"):]
            target = dest_root.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            written += 1
    return written


def fetch_bundle(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """从本仓库 Release 下载 `assets-bundle.zip` 并解到工作区（得到 assets\\）。"""
    if not force and any(
        (PROJECT_ROOT / "assets" / group / MANIFEST_NAME).is_file() for group in ASSET_GROUPS
    ):
        return {"ok": True, "changed": False, "message": "本地已有 assets"}

    import urllib.error
    import urllib.request

    from .version import LATEST_API, USER_AGENT

    stamp = PROJECT_ROOT / "runtime" / "_update" / "bundle-fetch.json"
    if not force and stamp.is_file():
        try:
            last = json.loads(stamp.read_text(encoding="utf-8"))
            if time.time() - float(last.get("at") or 0) < BUNDLE_STALE_SECONDS:
                return {"ok": False, "changed": False,
                        "message": last.get("message") or "24 小时内已尝试过，跳过"}
        except (OSError, json.JSONDecodeError):
            pass

    def remember(message: str) -> None:
        try:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(json.dumps({"at": int(time.time()), "message": message},
                                        ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    try:
        request = urllib.request.Request(LATEST_API, headers={
            "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=25) as response:
            release = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        message = f"查询 Release 失败：{exc}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    candidates = [
        asset for asset in (release.get("assets") or [])
        if BUNDLE_PATTERN in str(asset.get("name", "")).lower()
        and str(asset.get("name", "")).lower().endswith(".zip")
    ]
    if not candidates:
        message = (f"Release {release.get('tag_name') or ''} 里没有 {BUNDLE_PATTERN}.zip"
                   "（发布时需把 assets 目录压成该附件一起上传）")
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    asset = sorted(candidates, key=lambda a: int(a.get("size") or 0), reverse=True)[0]
    url = str(asset.get("browser_download_url") or "")
    size_mb = int(asset.get("size") or 0) / 1048576
    _log(log, f"本地没有 assets\\，从 Release 下载资产包 {asset.get('name')}（{size_mb:.0f} MB）")
    target = PROJECT_ROOT / "runtime" / "_update" / str(asset.get("name") or "assets-bundle.zip")
    # 资产包走 fastnet（慢/抖时临时并发、直连不通时临时换镜像）：
    # digest 由 GitHub API 给出，用来防止第三方镜像中转时被替换。
    from . import fastnet

    report = fastnet.download(
        url, target, log=log, expected_sha256=str(asset.get("digest") or ""),
    )
    if not report.ok:
        message = f"下载资产包失败：{report.message}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}
    try:
        written = _extract_bundle(target, PROJECT_ROOT)
    except Exception as exc:  # noqa: BLE001
        message = f"解包资产包失败：{exc}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    if not written:
        message = "资产包里没有 assets\\ 内容，已忽略"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    remember(f"ok:{written}")
    _log(log, f"资产包已解出 {written} 个文件")
    return {"ok": True, "changed": True, "files": written, "message": f"已下载并解出 {written} 个文件"}


def asset_report(config: AppConfig) -> dict[str, dict[str, Any]]:
    """给依赖页用的状态：内置包是否可用、本地是否已展开。"""
    report: dict[str, dict[str, Any]] = {}
    for group, root, name, entry in manifest_entries(config):
        target = config.dlss5_path / name
        parts = list(entry.get("parts") or [])
        parts_ok = all((root / part).is_file() for part in parts)
        expected_size = int(entry.get("size") or 0)
        present = target.is_file() and (not expected_size or target.stat().st_size == expected_size)
        packed_bytes = int(entry.get("packed_bytes") or 0)
        report[f"{group}:{name}"] = {
            "display": f"{ASSET_GROUPS.get(group, group)} · {name}",
            "source": f"仓库内置 assets/{group}",
            "install_dir": str(config.dlss5_path),
            "present": bool(present),
            "required": True,
            "needed": not present,
            "status": "已就位" if present else ("待展开" if parts_ok else "内置资产缺失"),
            "enabled": True,
            "version": f"{expected_size / 1048576:.1f} MB",
            "packed": f"{packed_bytes / 1048576:.2f} MB / {len(parts)} 卷" if packed_bytes else "",
            "asset_dir": str(root),
        }
    return report


def stage_report(config: AppConfig) -> dict[str, Any]:
    """资产整体可用性（供"完整性检查"用）。"""
    present = extracted = 0
    problems: list[str] = []
    for group, root, name, entry in manifest_entries(config):
        target = config.dlss5_path / name
        if target.is_file() and target.stat().st_size == int(entry.get("size") or 0):
            extracted += 1
        else:
            missing = [p for p in (entry.get("parts") or []) if not (root / p).is_file()]
            if missing:
                problems.append(f"{name}: 内置资产缺 {missing}")
        present += 1
    return {"total": present, "extracted": extracted, "problems": problems}
