# SPDX-License-Identifier: AGPL-3.0-only
"""版本形态：Universal（完整版）与 Lite（轻量版）。

Lite 版在**运行期彻底关掉 ReShade 链路**：不下载、不展开、不注入、不写任何
ReShade 文件，并把游戏目录里已有的 ReShade 痕迹当"总闸"强制清走（有备份、可还原）。
两版共用同一套数据根（config.json / runtime / library），因此**对 ReShade 相关配置只读** ——
切回 Universal 时用户原有的开关与能力原样恢复。

判定顺序（后者只在源码/开发时用得到）：
1. 环境变量 `MC_EDITION`（测试与源码启动 Lite 用）；
2. 资源根下的 `edition.json`（打包时由 build_exe.py 写入，内容 `{"edition": "lite"}`）；
3. 都没有 ⇒ `full`。

本模块**不 import config**（config 会 import 本模块做判据，避免循环）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

FULL = "full"
LITE = "lite"
VALID = (FULL, LITE)

_cache: str | None = None


def _resource_root() -> Path:
    """只读资源根：打包后是 PyInstaller 解压目录，源码方式就是仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    return Path(__file__).resolve().parents[1]


def _from_file() -> str:
    try:
        data = json.loads((_resource_root() / "edition.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = str((data or {}).get("edition") or "").strip().lower()
    return value if value in VALID else ""


def current() -> str:
    """当前版本的形态（`full` / `lite`），非法值一律按完整版处理。"""
    global _cache
    if _cache is not None:
        return _cache
    value = str(os.environ.get("MC_EDITION", "") or "").strip().lower()
    if value not in VALID:
        value = _from_file()
    _cache = value if value in VALID else FULL
    return _cache


def is_lite() -> bool:
    return current() == LITE


def has_reshade() -> bool:
    """本版本是否包含 ReShade 链路（Universal 才有）。"""
    return not is_lite()


def label() -> str:
    """给人看的形态名。"""
    return "轻量版" if is_lite() else "完整版"


def effective_reshade_disabled(config: Any) -> bool:
    """本次运行是否"禁用所有 ReShade 注入"。

    这是**唯一判据**：Lite 恒为 True（不落盘）；Universal 照旧读配置里的总闸。
    注入库、底座判定、启动前净化、锁键可用性都从这里取，避免各处各读一个字段。
    """
    if is_lite():
        return True
    return bool(getattr(config, "reshade_disabled", False))


def reset_cache() -> None:
    """测试用：清掉形态缓存（改环境变量 / edition.json 之后要重读）。"""
    global _cache
    _cache = None
