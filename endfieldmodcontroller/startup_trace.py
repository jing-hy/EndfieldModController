# SPDX-License-Identifier: GPL-3.0-or-later
"""启动时间线打点（2026-11-05）。

为什么有这个东西：用户报「启动这么慢，出加载页面和在加载页面都很久」。光看代码只能猜，
而启动链上每一段的归属完全不同 ——
  * **PyInstaller onefile 解压**（发生在 Python 代码之前，只能用进程创建时间量）；
  * 后端 `EndfieldModControllerApi()` 构造；
  * 创建窗口 + WebView2 初始化 + 前端 JS 起来（到桥可用）；
  * 首屏那次 `get_state()`（加载页就是等它）。
所以这里只做一件事：在几个关键点记下「距本模块导入多少秒」，最后拼成一行人话写进
`runtime\\logs\\<日期>.log`。以后再有人说慢，先看这一行就知道该修哪一段。

设计约束：
  * **不新增依赖**、打点本身不做 IO（只往 list 里 append）；
  * 写日志那一下可能抛（没权限/磁盘满）—— 调用方全部吞掉，绝不影响启动；
  * 只在**首屏那一路**打点，不挂在每个 API 调用上（那是热路径）。
"""
from __future__ import annotations

import os
import time
from typing import Any

_T0 = time.perf_counter()
_MARKS: dict[str, float] = {}


def mark(name: str) -> float:
    """记一个时间点，返回它距本模块导入的秒数（后面的段都用它做差）。"""
    at = time.perf_counter() - _T0
    _MARKS[str(name)] = at
    return at


def mark_once(name: str) -> float:
    """只在第一次记（同一个点有两条路径会走到时用它，别让后来的覆盖先来的）。"""
    if str(name) in _MARKS:
        return _MARKS[str(name)]
    return mark(name)


def process_uptime_seconds() -> float | None:
    """从**进程创建**到现在（秒）。onefile 的解压就发生在进程创建之后、Python 之前。

    取不到（非 Windows / 权限受限）返回 None —— 调用方如实写「未知」，不要编一个数。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessTimes.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = ctypes.c_bool
        created = wintypes.FILETIME()
        exit_t = wintypes.FILETIME()
        kernel_t = wintypes.FILETIME()
        user_t = wintypes.FILETIME()
        handle = kernel32.GetCurrentProcess()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exit_t),
            ctypes.byref(kernel_t), ctypes.byref(user_t),
        ):
            return None
        started = ((created.dwHighDateTime << 32) | created.dwLowDateTime) / 1e7   # 100ns → 秒
        # 11644473600 = 1601-01-01 → 1970-01-01 的秒数（FILETIME 纪元换算，固定值）
        return max(0.0, time.time() - (started - 11644473600.0))
    except Exception:  # noqa: BLE001 —— 量不出来就当"未知"，别让它把启动弄坏
        return None


def _fmt(value: float | None) -> str:
    return "未知" if value is None else f"{float(value):.2f}s"


def summary() -> dict[str, Any]:
    """各段的**绝对时刻**（距本模块导入，秒）。缺的点是 None。"""
    return {
        "uptime": process_uptime_seconds(),
        "entry": _MARKS.get("entry"),
        "api": _MARKS.get("api"),
        "window": _MARKS.get("window"),
        "frontend_ready": _MARKS.get("frontend_ready"),
        "first_state": _MARKS.get("first_state"),
    }


def report_line(extra: dict[str, float] | None = None) -> str:
    """拼成一行人话（写进日志用）。各段写的都是「这一段花了多久」。"""
    marks = summary()
    entry, api_ready, window = marks["entry"], marks["api"], marks["window"]
    frontend, first_state = marks["frontend_ready"], marks["first_state"]
    uptime = marks["uptime"]

    parts: list[str] = []
    if uptime is not None and entry is not None:
        # 进程创建 → 进入 main()：含 onefile 解压 + PyInstaller bootstrap
        parts.append("进程创建→入口 " + _fmt(max(0.0, uptime - entry)))
    elif entry is not None:
        parts.append("进程创建→入口 未知")
    if entry is not None and api_ready is not None:
        parts.append("入口→API " + _fmt(api_ready - entry))
    if api_ready is not None and window is not None:
        parts.append("API→窗口 " + _fmt(window - api_ready))
    if window is not None and frontend is not None:
        parts.append("窗口→前端就绪 " + _fmt(frontend - window))
    if frontend is not None and first_state is not None:
        parts.append("前端就绪→首屏状态 " + _fmt(first_state - frontend))
    if uptime is not None and entry is not None and first_state is not None:
        # 进程创建时刻在本模块导入之后 uptime-entry 秒处
        parts.append("合计(进程创建→首屏) " + _fmt(uptime - entry + first_state))
    if extra:
        for key, value in extra.items():
            parts.append(f"{key} {_fmt(value)}")
    return "启动时间线: " + " | ".join(parts or ["（无数据）"])