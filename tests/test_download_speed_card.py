"""**「速度卡一直横线」的根因与修法**（2026-10-04，用户实测报障）。

用户原话：「进度条只是刷新慢，**但速度卡是一直横线**」——两件事同一个原因：

速度原先只在 `api._make_dep_progress().byte_progress` 里算，而**一键启动**那条路
（`launcher.launch` → `runtime_deps.ensure_all(progress=lambda …: 写日志)`）
**根本没传 `byte_progress`** ⇒ `_dep_task` 里既没有字节进度、也没有速度
⇒ 依赖页 `speed_bps` 恒为 0（横线）、进度只能靠"一项完成跳一下"（看着刷新慢）。

**修法**：速度改由 `fastnet` **内部全局采样**（任何下载路径都经过它），
UI 用 `fastnet.global_speed()` 取；`get_dependency_progress()` 在"没有依赖任务"
或"本任务还没采到"时都用它兜底。本文件钉住这条链。
"""
from __future__ import annotations

from endfieldmodcontroller import fastnet


# ---------------------------------------------------------------- 采样
def test_global_speed_is_zero_before_any_sample() -> None:
    with fastnet._STATE_LOCK:
        fastnet._STATE.pop("speed_bps", None)
        fastnet._STATE.pop("speed_at", None)
        fastnet._STATE.pop("speed_sample", None)
    assert fastnet.global_speed() == 0.0


def test_note_speed_produces_a_positive_speed(monkeypatch) -> None:
    """★ 两次采样（间隔够长、字节在增长）⇒ 全局速度有值 —— 这就是横线的解药。"""
    fake_now = {"t": 1000.0}
    monkeypatch.setattr(fastnet.time, "time", lambda: fake_now["t"])
    with fastnet._STATE_LOCK:
        fastnet._STATE.pop("speed_bps", None)
        fastnet._STATE.pop("speed_at", None)
        fastnet._STATE.pop("speed_sample", None)

    fastnet._note_speed(0, 1_000_000)
    fake_now["t"] += 1.0                       # 一秒后下了 500 KB
    fastnet._note_speed(500 * 1024, 1_000_000)

    speed = fastnet.global_speed()
    assert speed > 0, "采样后必须给出速度，否则界面永远横线"
    assert abs(speed - 500 * 1024) < 1024, f"速度算错：{speed}"


def test_global_speed_decays_to_zero_when_stale(monkeypatch) -> None:
    """★ 超过 3 秒没有新数据 ⇒ 归零（否则卡片会挂着一个早就不动的数字）。"""
    fake_now = {"t": 2000.0}
    monkeypatch.setattr(fastnet.time, "time", lambda: fake_now["t"])
    with fastnet._STATE_LOCK:
        fastnet._STATE["speed_bps"] = 1234.0
        fastnet._STATE["speed_at"] = fake_now["t"]
    assert fastnet.global_speed() > 0
    fake_now["t"] += 5.0
    assert fastnet.global_speed() == 0.0


def test_backwards_progress_does_not_produce_negative_speed(monkeypatch) -> None:
    """换了文件 / 进度回退时（done 变小）不许算出负速度。"""
    fake_now = {"t": 3000.0}
    monkeypatch.setattr(fastnet.time, "time", lambda: fake_now["t"])
    with fastnet._STATE_LOCK:
        fastnet._STATE["speed_bps"] = 100.0
        fastnet._STATE["speed_at"] = fake_now["t"]
        fastnet._STATE.pop("speed_sample", None)
    fastnet._note_speed(900, 1000)
    fake_now["t"] += 1.0
    fastnet._note_speed(10, 1000)               # 回退
    assert fastnet.global_speed() >= 0


# ---------------------------------------------------------------- 接线
def test_download_tracks_speed_even_without_caller_progress() -> None:
    """★ 调用方**不传** progress 时也要采样（一键启动那条路就是这样）。"""
    import inspect

    src = inspect.getsource(fastnet.download)
    assert "def _tracked(done: int, total: int)" in src, "download 里要有速度采样的包装"
    assert "_note_speed(done, total)" in src, "包装里必须调用 _note_speed"
    assert "progress=_tracked" in src, "传给 _attempt_line 的应当是包装后的回调"


def test_dependency_progress_falls_back_to_global_speed() -> None:
    """★ `get_dependency_progress` 在两种情况下都要用全局速度兜底。"""
    import inspect

    from endfieldmodcontroller import api

    src = inspect.getsource(api.EndfieldModControllerApi.get_dependency_progress)
    assert src.count("global_speed()") >= 2, \
        "「没有依赖任务」和「本任务还没采到」两种情况都该用全局速度兜底"
    assert "speed_bps" in src
