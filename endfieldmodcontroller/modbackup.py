"""Mod 备份仓：库里**每见到一个新 Mod**，就整份复制进数据根下的备份文件夹。

用户 2026-10-01 原话（两次）：
① 「在**根目录下放一个文件夹做 mod 备份**，这个文件夹**只增不减**，只要见到新 mod，
   就**打包 zip** 放进去」；
② 随后改主意：「**改成不要打包，纯备份**」—— 所以现在是**纯复制**（不压缩、不打包），
   一个 Mod 一个文件夹，原样躺在备份仓里。

设计要点（都是照着用户的红线来的）：
* 备份目录默认 = **数据根下的 `mod-backup\\`**（与 `library\\` / `runtime\\` 平级，
  用户一眼能看到、能自己拷走）；config 字段 `mod_backup_dir` 可改。
* **只增不减**：这个模块**没有任何删除/覆盖已有备份的代码路径**；同名目录已存在就
  只登记进索引、绝不重拷（也就不会把好备份覆盖成坏备份）。以前打过的 zip 也**留着不动**。
* **失败不中断**：一个 Mod 复制失败只记一笔，继续下一个（rules：批量不要 fail-fast）。
* **绝不碰 Mod 库**：只读库、只写备份目录；备份目录若与库/中转目录重叠 → 整体拒绝
  执行（否则备份会落进库里，越滚越大）。
* 复制在**后台线程**里做（`api._warm_up` / 扫描之后触发），大库第一次会跑一会儿，
  但界面不会被卡住。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import core
from .config import AppConfig

INDEX_NAME = "_index.json"
# 备份仓的默认名字（数据根下）；设置页留空就是它
DEFAULT_DIR_NAME = "mod-backup"
# 复制时顺手跳过的垃圾（不影响 Mod 本体）
_SKIP_SUFFIXES = (".tmp", ".mc.tmp")
_SKIP_NAMES = {"desktop.ini", "thumbs.db"}
# 复制中途用的临时前缀（写完 rename 成正式名字，避免留下半份备份）
_TMP_PREFIX = "_copying_"


def configured_dir(config: AppConfig) -> str:
    """config 里写的备份目录（空串 = 用默认）。设置页输入框回填用这个。"""
    return str(getattr(config, "mod_backup_dir", "") or "").strip()


def enabled(config: AppConfig) -> bool:
    """**Mod 备份总开关**（默认开）。

    用户 2026-10-02 原话：「**给 mod 备份做一个开关，默认开，关了就不备份**」。
    关掉 = 一个字节都不复制、连备份目录都不创建；**已有的备份一个都不动**
    （"只增不减"是这条功能的红线，开关不改变它）。
    """
    return bool(getattr(config, "mod_backup_enabled", True))


def backup_dir(config: AppConfig) -> Path:
    """备份仓目录（默认 `<数据根>\\mod-backup`）。"""
    value = configured_dir(config)
    return config.resolve_path(value) if value else (config.base_dir / DEFAULT_DIR_NAME)


def index_path(config: AppConfig) -> Path:
    return backup_dir(config) / INDEX_NAME


def _read_index(config: AppConfig) -> dict[str, Any]:
    path = index_path(config)
    if not path.is_file():
        return {"entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 索引坏了不是灾难：备份目录还在，下面会按"同名目录已存在"重新登记
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
    """备份目录落在库/中转目录里 → 不能往那儿备份（会越滚越大、还容易被当 Mod 扫到）。"""
    from . import fsutil

    for other in (config.library_path, config.staging_mods_path):
        try:
            if fsutil.library_conflict(other, target) or fsutil.library_conflict(target, other):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _safe_folder_name(mod: Any) -> str:
    return core.safe_name(str(getattr(mod, "name", "") or "mod"))


def _zip_name(mod: Any) -> str:
    """以前打包时代留下的文件名（只用来判断"这个 Mod 备份过没有"）。"""
    return f"{_safe_folder_name(mod)}.zip"


def _dir_bytes(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def pending(config: AppConfig, mods: Sequence[Any]) -> list[Any]:
    """还没备份过的 Mod（索引里没有，且备份目录/旧 zip 也都不存在）。

    总开关关着时一律返回空 —— 这时"待备份"没有意义，界面也不该显示"还有 N 个待打包"。
    """
    if not enabled(config):
        return []
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
        if (target_dir / _safe_folder_name(mod)).is_dir():
            continue          # 已经备份过（索引丢过也没关系）
        if (target_dir / _zip_name(mod)).is_file():
            continue          # 早先打包时代留下的 zip：也算备份过，不重复
        out.append(mod)
    return out


def backup_mod(config: AppConfig, mod: Any, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把一个 Mod **整份复制**进备份仓；已有同名目录/旧 zip 就只登记不重拷。"""
    if not enabled(config):
        # 关掉总开关：连备份目录都不建（否则"关了还凭空多个空目录"）。
        return {"ok": True, "skipped": True, "disabled": True,
                "message": "Mod 备份已关闭（设置页「Mod 备份」滑块可打开）"}
    target_dir = backup_dir(config)
    if _overlaps_library(config, target_dir):
        return {"ok": False, "skipped": True,
                "message": f"备份目录与 Mod 库/中转目录重叠，已跳过：{target_dir}"}
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "skipped": True, "message": f"创建备份目录失败：{exc}"}

    source = Path(str(getattr(mod, "path", "")))
    folder_name = _safe_folder_name(mod)
    target = target_dir / folder_name
    created = False
    if not target.is_dir() and not (target_dir / _zip_name(mod)).is_file():
        if not source.is_dir():
            return {"ok": False, "skipped": True, "message": f"Mod 目录不存在：{source}"}
        # 先复制到临时目录、成功后再改名 —— 中途失败不会在备份仓里留下"看起来备份了、
        # 实际半拉子"的目录（用户对"备份是假的"很敏感）。
        tmp = target_dir / f"{_TMP_PREFIX}{folder_name}"
        try:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(
                source,
                tmp,
                ignore=shutil.ignore_patterns(*_SKIP_NAMES, *_SKIP_SUFFIXES),
            )
            tmp.replace(target)
            created = True
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            return {"ok": False, "skipped": False, "message": f"复制失败：{exc}"}

    size = _dir_bytes(target) if target.is_dir() else 0
    data = _read_index(config)
    data["entries"] = [e for e in data.get("entries", []) if str(e.get("id") or "") != str(getattr(mod, "id", ""))]
    data["entries"].append({
        "id": str(getattr(mod, "id", "")),
        "name": str(getattr(mod, "name", "")),
        "folder": target.name,
        "size": size,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_index(config, data)
    message = (f"{'已备份' if created else '已有备份'} {getattr(mod, 'name', '')} → {target.name}\\"
               f"（{size / 1048576:.1f} MB）")
    if log is not None:
        log(message)
    return {"ok": True, "created": created, "path": str(target), "size": size, "message": message}


def backup_all(
    config: AppConfig,
    mods: Iterable[Any],
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把这一批里"新见到的"Mod 逐个备份（单项失败不中断，最后汇总）。"""
    if not enabled(config):
        return {"checked": 0, "created": [], "failed": [], "disabled": True,
                "dir": str(backup_dir(config))}
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
                created.append(str(result.get("path")))
        else:
            failed.append(f"{getattr(mod, 'name', '')}: {result.get('message')}")
            if log is not None:
                log(f"WARN Mod 备份失败：{failed[-1]}")
    return {"checked": len(todo), "created": created, "failed": failed,
            "dir": str(backup_dir(config))}


def status(config: AppConfig) -> dict[str, Any]:
    """备份仓现状（界面显示用）：数量、占用、最近一次。"""
    target = backup_dir(config)
    data = _read_index(config)
    folders: list[Path] = []
    zips: list[Path] = []
    if target.is_dir():
        try:
            for item in sorted(target.iterdir()):
                if item.is_dir() and not item.name.startswith(_TMP_PREFIX) and item.name != "__pycache__":
                    folders.append(item)
                elif item.is_file() and item.suffix.lower() == ".zip":
                    zips.append(item)
        except OSError:
            pass
    # 占用优先用索引里记的值（快），没有记录的再实算
    recorded = {
        str(entry.get("folder") or ""): int(entry.get("size") or 0)
        for entry in data.get("entries", [])
        if entry.get("folder")
    }
    total = 0
    for item in folders:
        total += recorded.get(item.name) or _dir_bytes(item)
    for item in zips:
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return {
        "dir": str(target),
        "exists": target.is_dir(),
        "enabled": enabled(config),
        "count": len(folders) + len(zips),
        "folders": len(folders),
        "legacy_zips": len(zips),
        "bytes": total,
        "updated": str(data.get("updated") or ""),
        "overlaps_library": _overlaps_library(config, target),
    }


def set_backup_dir(config: AppConfig, value: str | Path | None) -> dict[str, Any]:
    """改 Mod 备份目录（设置页输入框与「选择文件夹」都走这一个入口）。

    用户 2026-10-02 原话：「**需要加个那个 mod 备份在设置里能自行选择备份目录**」。
    规则：
    * **留空 = 回到默认**（数据根下的 `mod-backup\\`）；相对路径照旧按数据根解析；
    * **先按新位置做重叠校验**：落在 Mod 库 / 中转目录里一律**拒绝并保持原值**
      （否则备份会滚进库里，既占地方又会被当 Mod 扫到）；
    * **只改这一个字段**：旧目录里已有的备份**原地不动**（"只增不减"是这条功能的红线），
      新目录里还是空的，下一次扫描会重新整份复制一份过去 —— 所以返回值里带 `changed`，
      界面据此把"会重新备份一次"说清楚。
    """
    previous_value = configured_dir(config)
    previous_dir = backup_dir(config)
    text = "" if value is None else str(value).strip()
    # 落在数据根里的位置存相对路径（搬家后天然跟随）；外部位置原样保留
    config.mod_backup_dir = config.store_path(text) or DEFAULT_DIR_NAME
    target = backup_dir(config)
    changed = str(target) != str(previous_dir)

    if _overlaps_library(config, target):
        config.mod_backup_dir = previous_value
        return {"ok": False, "changed": False, "reason": "backup_dir_overlaps_library",
                "dir": str(previous_dir), "target": str(target),
                "message": f"这个位置在 Mod 库/中转目录里面，不能拿来放备份：{target}"}
    try:
        config.save()
    except OSError as exc:
        config.mod_backup_dir = previous_value
        return {"ok": False, "changed": False, "dir": str(previous_dir),
                "message": f"保存配置失败：{exc}"}
    state = status(config)
    state.update({"ok": True, "changed": changed, "previous": str(previous_dir),
                  "configured": configured_dir(config)})
    return state


def set_enabled(config: AppConfig, value: bool) -> dict[str, Any]:
    """开/关 **Mod 备份总开关**（设置页滑块，默认开）。

    用户 2026-10-02 原话：「给 mod 备份做一个开关，默认开，关了就不备份」。
    规则：
    * 关掉 = **不再复制任何东西**（`backup_mod`/`backup_all` 直接跳过、连备份目录都不建）；
    * **已有的备份一个都不动、目录也不删**（"只增不减"是这条功能的红线，开关不改变它）；
    * 重新打开后，库里"还没备份过"的 Mod 会在下次扫描/一键启动时照旧补上（索引没丢）。
    """
    previous = enabled(config)
    config.mod_backup_enabled = bool(value)
    try:
        config.save()
    except OSError as exc:
        config.mod_backup_enabled = previous
        return {"ok": False, "changed": False, "enabled": previous,
                "message": f"保存配置失败：{exc}"}
    state = status(config)
    state.update({"ok": True, "changed": previous != bool(value), "enabled": bool(value)})
    return state


