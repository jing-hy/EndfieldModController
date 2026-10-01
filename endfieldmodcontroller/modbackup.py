"""Mod 备份仓：库里**每见到一个新 Mod**，就打包成 zip 放进数据根下的备份文件夹。

用户 2026-10-01 原话：「还有要在**根目录下放一个文件夹做 mod 备份**，这个文件夹
**只增不减**（原话"只删不减"），**只要见到新 mod，就打包 zip 放进去**」。

设计要点（都是照着用户的红线来的）：
* 备份目录默认 = **数据根下的 `mod-backup\\`**（与 `library\\` / `runtime\\` 平级，
  用户一眼能看到、能自己拷走）；config 字段 `mod_backup_dir` 可改。
* **只增不减**：这个模块**没有任何删除/覆盖已有备份的代码路径**；同名 zip 已存在就
  只登记进索引、绝不重打（也就不会把好备份覆盖成坏备份）。
* **失败不中断**：一个 Mod 打包失败只记一笔，继续下一个（rules：批量不要 fail-fast）。
* **绝不碰 Mod 库**：只读库、只写备份目录；备份目录若与库/中转目录重叠 → 整体拒绝
  执行（否则打包出来的 zip 会落在库里面，越滚越大）。
* 打包在**后台线程**里做（`api._warm_up` / 扫描之后触发），大库第一次会跑一会儿，
  但界面不会被卡住。
"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import core
from .config import AppConfig

INDEX_NAME = "_index.json"
# 打包时顺手跳过的垃圾（不影响 Mod 本体）
_SKIP_SUFFIXES = (".tmp", ".mc.tmp")
_SKIP_NAMES = {"desktop.ini", "thumbs.db"}


def backup_dir(config: AppConfig) -> Path:
    """备份仓目录（默认 `<数据根>\\mod-backup`）。"""
    value = str(getattr(config, "mod_backup_dir", "") or "").strip()
    return config.resolve_path(value) if value else (config.base_dir / "mod-backup")


def index_path(config: AppConfig) -> Path:
    return backup_dir(config) / INDEX_NAME


def _read_index(config: AppConfig) -> dict[str, Any]:
    path = index_path(config)
    if not path.is_file():
        return {"entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 索引坏了不是灾难：zip 还在，下面会按"同名 zip 已存在"重新登记
        return {"entries": []}
    if not isinstance(data, dict):
        return {"entries": []}
    entries = data.get("entries")
    data["entries"] = [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []
    return data


def _write_index(config: AppConfig, data: dict[str, Any]) -> None:
    try:
        from . import fsutil

        fsutil.write_text_atomic(
            index_path(config), json.dumps(data, ensure_ascii=False, indent=2), newline="\n"
        )
    except (OSError, ValueError):
        pass


def _overlaps_library(config: AppConfig, target: Path) -> bool:
    """备份目录落在库/中转目录里 → 不能往那儿打包（会越滚越大、还容易被当 Mod 扫到）。"""
    from . import fsutil

    for other in (config.library_path, config.staging_mods_path):
        try:
            if fsutil.library_conflict(other, target) or fsutil.library_conflict(target, other):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _zip_name(mod: Any) -> str:
    return f"{core.safe_name(str(mod.name))}.zip"


def pending(config: AppConfig, mods: Sequence[Any]) -> list[Any]:
    """还没备份过的 Mod（索引里没有、且同名 zip 也不存在）。"""
    known = {
        str(entry.get("id") or "")
        for entry in _read_index(config).get("entries", [])
        if entry.get("id")
    }
    target_dir = backup_dir(config)
    out: list[Any] = []
    for mod in mods:
        if str(getattr(mod, "id", "")) in known:
            continue
        if (target_dir / _zip_name(mod)).is_file():
            continue          # zip 已经在了（索引丢过也没关系）
        out.append(mod)
    return out


def backup_mod(config: AppConfig, mod: Any, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把一个 Mod 打包成 zip 放进备份仓；已有同名 zip 就只登记不重打。"""
    target_dir = backup_dir(config)
    if _overlaps_library(config, target_dir):
        return {"ok": False, "skipped": True,
                "message": f"备份目录与 Mod 库/中转目录重叠，已跳过：{target_dir}"}
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "skipped": True, "message": f"创建备份目录失败：{exc}"}

    source = Path(str(getattr(mod, "path", "")))
    zip_path = target_dir / _zip_name(mod)
    created = False
    if not zip_path.is_file():
        if not source.is_dir():
            return {"ok": False, "skipped": True, "message": f"Mod 目录不存在：{source}"}
        tmp = zip_path.with_name(zip_path.name + ".tmp")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for item in sorted(source.rglob("*")):
                    if not item.is_file():
                        continue
                    name = item.name.lower()
                    if name in _SKIP_NAMES or name.endswith(_SKIP_SUFFIXES):
                        continue
                    archive.write(item, arcname=f"{str(getattr(mod, 'name', source.name))}/{item.relative_to(source)}")
            tmp.replace(zip_path)          # 原子落盘：写一半失败不会留下半个 zip
            created = True
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            return {"ok": False, "skipped": False, "message": f"打包失败：{exc}"}

    size = zip_path.stat().st_size if zip_path.is_file() else 0
    data = _read_index(config)
    data["entries"] = [e for e in data.get("entries", []) if str(e.get("id") or "") != str(getattr(mod, "id", ""))]
    data["entries"].append({
        "id": str(getattr(mod, "id", "")),
        "name": str(getattr(mod, "name", "")),
        "zip": zip_path.name,
        "size": size,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_index(config, data)
    message = f"{'已备份' if created else '已有备份'} {getattr(mod, 'name', '')} → {zip_path.name}（{size / 1048576:.1f} MB）"
    if log is not None:
        log(message)
    return {"ok": True, "created": created, "zip": str(zip_path), "size": size, "message": message}


def backup_all(
    config: AppConfig,
    mods: Iterable[Any],
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把这一批里"新见到的"Mod 逐个打包（单项失败不中断，最后汇总）。"""
    todo = pending(config, list(mods))
    created: list[str] = []
    failed: list[str] = []
    for mod in todo:
        try:
            result = backup_mod(config, mod, log=log)
        except Exception as exc:  # noqa: BLE001 - 单项失败不能拖垮整批
            result = {"ok": False, "message": str(exc)}
        if result.get("ok"):
            if result.get("created"):
                created.append(str(result.get("zip")))
        else:
            failed.append(f"{getattr(mod, 'name', '')}: {result.get('message')}")
            if log is not None:
                log(f"WARN Mod 备份失败：{failed[-1]}")
    return {"checked": len(todo), "created": created, "failed": failed,
            "skipped": 0 if todo else 0, "dir": str(backup_dir(config))}


def status(config: AppConfig) -> dict[str, Any]:
    """备份仓现状（界面显示用）：数量、占用、最近一次。"""
    target = backup_dir(config)
    zips: list[Path] = []
    if target.is_dir():
        try:
            zips = sorted(p for p in target.glob("*.zip") if p.is_file())
        except OSError:
            zips = []
    total = 0
    for item in zips:
        try:
            total += item.stat().st_size
        except OSError:
            continue
    data = _read_index(config)
    return {
        "dir": str(target),
        "exists": target.is_dir(),
        "count": len(zips),
        "bytes": total,
        "updated": str(data.get("updated") or ""),
        "overlaps_library": _overlaps_library(config, target),
    }
