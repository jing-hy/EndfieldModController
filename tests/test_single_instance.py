"""防多开的单实例锁（2026-10-03 反馈者实测的「关掉管理器就没反应」）。

**现象**（用户转来的反馈）：「关掉管理器，显示要管理员权限，然后就没反应了」。
诊断包里 `runtime\\logs` 连着四条：

    已有实例在运行 → 本次启动静默退出（防多开）

可他那个窗口**早就关了**。旧判据只看「锁里那个 PID 还活着吗」，而 Windows 会很快复用
PID，PyInstaller onefile 每次启动又都会创建**父子两个同名**的 `EndfieldModController.exe`
进程 ⇒ 旧 PID 被本次启动的进程复用 ⇒ 误判 ⇒ 静默退出 ⇒ 用户看到的就是
「双击 → 弹 UAC → 什么都没发生」。

现在的判据是**三件套**，本文件把它们钉住：
① 锁里那个 PID 活着，**并且**进程指纹（exe 路径 + 创建时间）与锁里记的一致 ⇒ 真的还有实例；
② 或者屏幕上**真有一个我们的窗口**（跨版本按标题前缀认）⇒ 真的还有实例；
③ 两者都不成立 ⇒ **陈旧锁 / PID 被复用 ⇒ 直接接管**，绝不静默退出。
另外：退出时要把锁还回去（`os._exit` 会跳过 finally，所以显式释放）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from endfieldmodcontroller import app


@pytest.fixture()
def lock_file(tmp_path, monkeypatch):
    """把数据根换成 tmp_path，并默认"屏幕上没有我们的窗口"。"""
    monkeypatch.setattr(app, "_instance_root", lambda: tmp_path)
    monkeypatch.setattr(app, "_our_windows", lambda: [])
    return tmp_path / "runtime" / app._LOCK_NAME


def _write_lock(lock: Path, payload) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")


def test_first_call_takes_the_lock(lock_file):
    assert app._already_running() is False
    assert lock_file.is_file()
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_same_process_is_not_treated_as_another_instance(lock_file):
    assert app._already_running() is False
    assert app._already_running() is False, "锁是本进程写的，不能再判成‘已有实例’"


def test_live_process_with_matching_fingerprint_counts_as_running(lock_file, monkeypatch):
    """指纹对得上 = 那个进程确实是"上一次的自己" ⇒ 判为已有实例。"""
    _write_lock(lock_file, {"pid": 4242, "fp": "c:\\mc.exe|111"})
    monkeypatch.setattr(app, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(app, "_process_fingerprint", lambda pid: "c:\\mc.exe|111")
    assert app._already_running() is True


def test_recycled_pid_is_taken_over(lock_file, monkeypatch):
    """★ 核心回归：PID 活着但**不是写这把锁的那个进程**（PID 被复用）⇒ 必须接管。"""
    _write_lock(lock_file, {"pid": 4242, "fp": "c:\\mc.exe|111"})
    monkeypatch.setattr(app, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(app, "_process_fingerprint", lambda pid: "c:\\mc.exe|999")  # 创建时间不同
    assert app._already_running() is False, "PID 复用绝不能被当成‘已有实例在运行’"
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_live_process_without_window_is_taken_over(lock_file, monkeypatch):
    """取不到指纹（旧格式锁）时，用"窗口还在不在"兜底：没窗口 ⇒ 接管。"""
    _write_lock(lock_file, "4242")                    # 老格式：纯 PID 文本
    monkeypatch.setattr(app, "_pid_alive", lambda pid: True)
    assert app._already_running() is False


def test_window_presence_alone_is_enough(lock_file, monkeypatch):
    """指纹取不到、但屏幕上真有我们的窗口 ⇒ 仍然是"已有实例"。"""
    _write_lock(lock_file, "4242")
    monkeypatch.setattr(app, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(app, "_process_fingerprint", lambda pid: "")
    monkeypatch.setattr(app, "_our_windows", lambda: [0x1234])
    assert app._already_running() is True


def test_dead_process_lock_is_taken_over(lock_file, monkeypatch):
    _write_lock(lock_file, {"pid": 4242, "fp": "c:\\mc.exe|111"})
    monkeypatch.setattr(app, "_pid_alive", lambda pid: False)
    assert app._already_running() is False
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_broken_lock_content_is_taken_over(lock_file):
    _write_lock(lock_file, "not-a-pid")
    assert app._already_running() is False


def test_release_only_removes_our_own_lock(lock_file):
    assert app._already_running() is False
    app._release_lock()
    assert not lock_file.exists(), "自己的锁要还回去（os._exit 前必须调用它）"

    _write_lock(lock_file, {"pid": 4242, "fp": "c:\\mc.exe|111"})
    app._release_lock()
    assert lock_file.is_file(), "别人（或接管者）的锁不能被误删"


def test_missing_dirs_do_not_break_the_check(tmp_path, monkeypatch):
    """数据根还不存在（首次运行）时也不能因此起不来。"""
    monkeypatch.setattr(app, "_instance_root", lambda: tmp_path / "brand-new")
    monkeypatch.setattr(app, "_our_windows", lambda: [])
    assert app._already_running() is False
