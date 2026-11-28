# SPDX-License-Identifier: AGPL-3.0-only
r"""钉住「路径 + 日志字段尾巴」被当成路径的问题（2026-11-28 用户现场）。

现象：用户点「打开文件夹」，弹 `路径不存在: D:\…\runtime\launch.log info=365719 bytes
mtime=2026-11-28T22:00:18 sha256=57c070…` —— 而 launch.log 其实就在那儿。

原因有两层：
  ① 前端弹窗的 `firstPath` 用了贪婪正则，把整行（含 ` info=… sha256=…`）当路径；
  ② 后端`open_path` 拿这串去 `exists()` 必然为假。
前后端各收一道：前端按 `PATH_RE` 同一口径截断，后端再把已知日志字段尾巴切掉。
"""
from __future__ import annotations

from endfieldmodcontroller import diagnostics


def test_truncates_log_field_tail() -> None:
    """`…launch.log info=… sha256=…` → 只留 `…launch.log`。"""
    raw = (r"D:\EndfieldModController\runtime\launch.log info=365719 bytes"
           r" mtime=2026-11-28T22:00:18 sha256=57c070d09cb2615daa515fb7d73a8dfa582c61db")
    assert diagnostics._normalize_open_target(raw) == r"D:\EndfieldModController\runtime\launch.log"


def test_keeps_real_paths_with_spaces() -> None:
    """含空格的正常路径不许被误截（只认已知字段名 + 等号）。"""
    raw = r"C:\Program Files\Hypergryph Launcher\Launcher.exe"
    assert diagnostics._normalize_open_target(raw) == raw


def test_keeps_plain_path() -> None:
    raw = r"D:\zmdmod\modtest\runtime\launch.log"
    assert diagnostics._normalize_open_target(raw) == raw