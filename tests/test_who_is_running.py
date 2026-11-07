# SPDX-License-Identifier: GPL-3.0-or-later
"""**实例判定**的回归：四条证据 + 陈旧锁不算"在跑"（2026-11-07）。

为什么要有它：我曾用
    Get-Process -Name EndfieldModController
判断"实例在不在"，两次坑都真实发生：
  * 源码方式启动（pythonw run.py）时进程名是 pythonw.exe ⇒ **明明在跑被判成没跑**；
  * 只看进程名、不看**exe 占用** ⇒ 真正决定"能不能替换 exe"的那件事根本没检查。
用户原话：「我现在实例都已经关了，你自己检查一下，不要下次再误识别实例」。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.who_is_running import judge  # noqa: E402
from endfieldmodcontroller import app as appmod  # noqa: E402


def _ev(**kwargs) -> dict:
    base = {"windows": [], "named_processes": [], "locks": [], "exe": []}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------- 四条证据
def test_window_means_running() -> None:
    running, reasons = judge(_ev(windows=["hwnd 1234"]))
    assert running and any("窗口" in r for r in reasons)


def test_named_process_means_running() -> None:
    running, reasons = judge(_ev(named_processes=[{"pid": 1, "image": "EndfieldModController.exe"}]))
    assert running and any("进程" in r for r in reasons)


def test_held_lock_means_running() -> None:
    running, _ = judge(_ev(locks=[{"path": "x", "state": "held", "pid": 42}]))
    assert running


def test_stale_lock_is_not_running_but_says_why() -> None:
    """陈旧锁（进程早退出）**不算在跑**，但要说明 —— 否则下次又被它吓住。"""
    running, reasons = judge(_ev(locks=[{"path": "L", "state": "stale", "pid": 9,
                                         "reason": "PID 已退出"}]))
    assert not running
    assert any("陈旧锁" in r for r in reasons)


def test_occupied_exe_without_process_is_a_warning_not_running() -> None:
    running, reasons = judge(_ev(exe=[{"path": "E", "exists": True, "replaceable": False}]))
    assert not running
    assert any("被占用" in r for r in reasons)


# ---------------------------------------------------------------- 锁文件判据
def test_lock_verdict_stale_pid(tmp_path: Path) -> None:
    from scripts.who_is_running import _lock_verdict

    lock = tmp_path / ".mc.lock"
    lock.write_text(json.dumps({"pid": 999999, "fp": "x|1"}), encoding="utf-8")
    assert _lock_verdict(lock)["state"] == "stale"


def test_lock_verdict_held_by_this_process(tmp_path: Path) -> None:
    from scripts.who_is_running import _lock_verdict

    lock = tmp_path / ".mc.lock"
    lock.write_text(json.dumps({"pid": os.getpid(),
                                "fp": appmod._process_fingerprint(os.getpid())}),
                    encoding="utf-8")
    assert _lock_verdict(lock)["state"] == "held"


def test_lock_verdict_pid_reused_when_fingerprint_is_foreign(tmp_path: Path) -> None:
    """PID 活着但指纹对不上（PID 被复用）⇒ 不能当成"在跑"。"""
    from scripts.who_is_running import _lock_verdict

    lock = tmp_path / ".mc.lock"
    lock.write_text(json.dumps({"pid": os.getpid(), "fp": "C:/somewhere/else.exe|123"}), encoding="utf-8")
    assert _lock_verdict(lock)["state"] == "pid-reused"
