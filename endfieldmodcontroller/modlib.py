# SPDX-License-Identifier: AGPL-3.0-only
"""Mod 库操作：把 Mod 移出库（移进回收区，可手动找回）。

2026-11-27：原先这里的「损坏 Mod 修复（ps-t+1）/ 回滚」整套功能已按用户要求**完全移除**
（连同备份索引与 sidecar 修复记录）。现只保留用户在卡片菜单里主动点的「移出 Mod 库」——
它同样是数据安全的关键动作：**删除 ≠ 真删**，只移到
`runtime\\backups\\mod-trash\\<时间戳>\\`，用户随时能在资源管理器里找回。
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def trash_root(config: AppConfig) -> Path:
    return Path(config.runtime_path) / "backups" / "mod-trash"


def _unique_dir(parent: Path, prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = parent / f"{prefix}{stamp}"
    index = 1
    while candidate.exists():
        candidate = parent / f"{prefix}{stamp}-{index}"
        index += 1
    return candidate


def delete_mod(config: AppConfig, mod_dir: Path, *, log: Log = None) -> dict[str, Any]:
    """把 Mod 从库里**移走**（移到 `runtime\\backups\\mod-trash\\<时间戳>\\`，可找回）。"""
    mod_dir = Path(mod_dir)
    if not mod_dir.is_dir():
        return {"ok": False, "message": f"Mod 目录不存在: {mod_dir}"}
    target = _unique_dir(trash_root(config), "") / mod_dir.name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mod_dir), str(target))
    except (OSError, shutil.Error) as exc:
        return {"ok": False, "message": f"移动失败: {exc}"}
    _log(log, f"已移出 Mod 库: {mod_dir.name} → {target}")
    return {"ok": True, "moved_to": str(target), "name": mod_dir.name,
            "message": "已移出 Mod 库（放在 runtime\\backups\\mod-trash 下，可手动找回）"}
