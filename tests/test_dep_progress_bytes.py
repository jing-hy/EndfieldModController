"""依赖更新的**字节口径**回归（2026-10-07 用户报「88968.2 MB / 246303.5 MB 这下载又是啥 bug」）。

**判据**：字节回调是**每 256 KB 一次**（见 `dependencies._download` 的读取循环），而它传进来的
`received` / `expected` 是"**当前这一个文件**的累计已下值 / 总大小"。

⇒ 所以**同一个组件在一个文件内的上千次回调必须覆盖同一条账**，只有**换了组件**（新 key）
才把上一项的最终值并进总量。原来的写法是**无条件累加**，于是一个 240 MB 的包下完时，
进度分母会滚成 240 MB × ≈960 次 ≈ **230 GB**（用户界面上的 246303.5 MB，分子 88968.2 MB
对应的真实值是 86.9 MB —— 两者百分比一致，所以看着"进度是对的、数字疯了"）。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


@pytest.fixture
def env(tmp_path, monkeypatch):
    """离线桩：配置与数据根都落在 tmp_path 下，绝不碰真实工作区的 runtime / library。

    ⚠️ `EndfieldModControllerApi` 收的是**配置路径**（不是 AppConfig 对象）——
    拿对象当参数会立刻 `TypeError`（我第一次就这么写的）。
    """
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: tmp_path / "library"))
    return tmp_path


def _api(env):
    return EndfieldModControllerApi(str(env / "config.json"))


def _fresh_task(total_items: int = 1) -> dict:
    return {
        "running": True, "current": 0, "total": total_items,
        "percent": 0.0, "byte_percent": 0.0, "computed_bytes": 0, "expected_bytes": 0,
        "message": "", "log": [], "results": [],
    }


def test_repeated_callbacks_for_one_file_do_not_inflate_totals(env):
    """同一个文件回调近千次：分母必须还是文件真实大小，不是它的 ~960 倍。"""
    api = _api(env)
    api._dep_task = _fresh_task()
    _progress, byte_progress, _bump = api._make_dep_progress()

    size = 240 * 1024 * 1024          # 240 MB
    chunk = 256 * 1024                # 每块 256 KB ⇒ 约 960 次回调
    received = 0
    calls = 0
    while received < size:
        received = min(size, received + chunk)
        byte_progress(1, 1, "XXMI", received, size)
        calls += 1

    assert calls > 900, "前提变了：回调不再是一堆小块（这条测试的意义就在重复回调上）"
    assert api._dep_task["expected_bytes"] == size, (
        "总大小被重复累加 —— 用户看到的就是这个（246303.5 MB）")
    assert api._dep_task["computed_bytes"] == size, "已下字节被重复累加"
    assert 0 < api._dep_task["byte_percent"] <= 99.0


def test_switching_component_still_accumulates(env):
    """换组件（新 key）时**仍要**并入上一项的最终值 —— 跨组件累加本身是对的。"""
    api = _api(env)
    api._dep_task = _fresh_task(total_items=2)
    _progress, byte_progress, _bump = api._make_dep_progress()

    first, second = 100 * 1024 * 1024, 50 * 1024 * 1024
    byte_progress(0, 2, "A", first, first)
    byte_progress(1, 2, "B", second, second)

    assert api._dep_task["expected_bytes"] == first + second
    assert api._dep_task["computed_bytes"] == first + second


def test_missing_content_length_keeps_previous_total(env):
    """拿不到 `Content-Length`（expected=0）时**不许**把已有的分母抹掉。"""
    api = _api(env)
    api._dep_task = _fresh_task()
    _progress, byte_progress, _bump = api._make_dep_progress()

    size = 10 * 1024 * 1024
    byte_progress(1, 1, "K", 1024, size)          # 先知道总大小
    byte_progress(1, 1, "K", 2048, 0)             # 后续回调没带 expected

    assert api._dep_task["expected_bytes"] == size
    assert api._dep_task["computed_bytes"] == 2048
