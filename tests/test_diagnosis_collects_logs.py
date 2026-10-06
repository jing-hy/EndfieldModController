"""★ 诊断包必须**一次抓齐**（用户定的规矩），而它此前漏了三样关键材料。

**2026-10-07 实测**（排查 issue16 时才发现）：
① **游戏自己的崩溃报告没收** —— 游戏把**带完整堆栈**的日志写在
   `%TEMP%\\Hypergryph\\Endfield\\Crashes\\Player.log`（还有 `crash.dmp`）。
   我们只收了 `LocalLow\\...\\Player.log`，而那份在**早退**时是被截断的
   （实测反馈者只有 48 行、止于 `MemoryPool::MMapMemoryBlock count:0`）⇒ 永远查不到崩溃原因。
② **我们自己的 `launch.log` 没收**（它在 `runtime\\` **根**，不在 `logs\\` 里）。
③ **`take()` 的静默失败**：`arcname` 带子目录（`logs/xxx`）时父目录不存在
   ⇒ `shutil.copy2` 抛 `OSError` 被"安静跳过"吞掉 ⇒ **整批 291 份日志一份都没进包**，
   而日志里连一句提示都没有。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import crashwatch
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "logs").mkdir(parents=True)
    # ① runtime 根下的主日志（以前完全没收）
    (runtime / "launch.log").write_text("主日志内容\n" * 100, encoding="utf-8")
    # ② logs\ 下的逐次日志
    (runtime / "logs" / "endfieldmodcontroller-20261007-000000.log").write_text(
        "会话日志\n" * 50, encoding="utf-8")
    (runtime / "logs" / "loader_debug.log").write_text("loader\n" * 20, encoding="utf-8")

    # ③ 假的"游戏崩溃报告目录"（用 TEMP 打桩，绝不碰真机）
    temp = tmp_path / "Temp"
    crashes = temp / "Hypergryph" / "Endfield" / "Crashes"
    crashes.mkdir(parents=True)
    (crashes / "Player.log").write_text(
        "========== OUTPUTTING STACK TRACE ==================\n"
        "0x00007FFA006B141B (nvgpucomp64) nvGetCompilerInterface\n",
        encoding="utf-8")
    (crashes / "crash.dmp").write_bytes(b"MINIDUMP" * 1000)

    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))

    config = AppConfig()
    config._config_path = str(tmp_path / "config.json")
    return config, tmp_path, crashes


def test_main_launch_log_is_collected(env):
    """★ `runtime\\launch.log`（主日志）必须进包 —— 它在 runtime 根、不在 logs\\ 里。"""
    config, tmp_path, _crashes = env
    dest = tmp_path / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)

    assert "logs/launch.log" in taken, f"主日志没收：{taken}"
    assert (dest / "logs" / "launch.log").is_file(), "子目录没被创建 ⇒ 文件其实没落盘"


def test_subdirectory_arcnames_do_not_get_silently_dropped(env):
    """★★ **带子目录的 arcname 不能静默丢**（这个坑让整批 291 份日志一份都没进包）。"""
    config, tmp_path, _crashes = env
    dest = tmp_path / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)

    log_files = [n for n in taken if n.startswith("logs/")]
    assert len(log_files) >= 3, f"logs/ 下只收到 {log_files}"
    for name in log_files:
        assert (dest / name).is_file(), f"{name} 记在清单里却没落盘"


def test_game_crash_reports_are_collected(env):
    """★ 游戏的崩溃报告（**带堆栈**那份）必须收 —— 这是 issue16 查不动的根因。"""
    config, tmp_path, crashes = env
    dest = tmp_path / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)

    crash_logs = [n for n in taken if n.startswith("game-crash-")]
    assert crash_logs, f"没收到游戏崩溃报告：{taken}"
    payload = (dest / crash_logs[0]).read_text(encoding="utf-8", errors="replace")
    assert "STACK TRACE" in payload, "收到的那份没有堆栈，等于没收"

    # `crash.dmp` 是 MB 级二进制 ⇒ **只记存在与大小**（不收本体）
    listing = (dest / "game-crash-reports.txt").read_text(encoding="utf-8", errors="replace")
    assert "crash.dmp" in listing, "清单里没有列出 dump"
    assert not any(n.endswith(".dmp") for n in taken), "dump 本体不该随包分发"


def test_player_prev_log_is_collected(env, tmp_path, monkeypatch):
    """★ 游戏 `Player-prev.log` 也要（崩溃那次常常只剩它完整）。"""
    home = tmp_path / "home"
    (home / "AppData" / "LocalLow" / "Hypergryph" / "Endfield").mkdir(parents=True)
    (home / "AppData" / "LocalLow" / "Hypergryph" / "Endfield" / "Player-prev.log").write_text(
        "上一份日志", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))

    config, tmp_path2, _crashes = env
    dest = tmp_path2 / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)
    assert "player-Player-prev.log" in taken, taken
