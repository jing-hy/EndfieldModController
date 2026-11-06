# SPDX-License-Identifier: GPL-3.0-or-later
"""钉住「启动 / 首屏绝不发网络请求」（2026-11-05 用户实测报的慢启动）。

**现象**：用户原话「启动这么慢，出加载页面和在加载页面都很久」。

实测拆出来的时间线（源码方式，本机）：

* `EndfieldModControllerApi()` 构造 0.01s；
* 桥可用 1.68s（WebView2 + 前端）；
* **首屏 `get_state()` 0.5~3.1s**，其中一大块是 `_app_dependency_entry()` 里的
  `selfupdate.check_update(use_cache=True)` —— 缓存（6 小时）一过期就**同步**去 GitHub
  拉两个页面（各 25 秒超时），而它跑在 GUI 线程上、又是加载页等待的对象。

修法：首屏只读缓存（`selfupdate.peek_cache`，纯本地），过期交给后台线程刷新。

这组测试钉两件事：

1. `peek_cache()` **永远不碰网络**（把网络函数换成"一调就炸"，它照样返回）；
2. `_app_dependency_entry()` 在网络**不通 / 极慢**时也立刻返回，刷新发生在后台线程。
"""
from __future__ import annotations

import json
import threading
import time
import types
from pathlib import Path

import pytest

from endfieldmodcontroller import selfupdate, startup_trace
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


def _config(root: Path):
    # `peek_cache` 只用 `config.runtime_path`，最小桩就够（与 test_app_update_cache 同口径）
    return types.SimpleNamespace(runtime_path=root)


def _write_cache(root: Path, payload: dict) -> Path:
    path = selfupdate._cache_path(_config(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_peek_cache_reads_disk_only(tmp_path, monkeypatch):
    """有缓存时不发网络，直接给结果（并且按当前版本重算 update_available）。"""
    def _boom(*_args, **_kwargs):
        raise AssertionError("peek_cache 绝不该发网络请求")

    monkeypatch.setattr(selfupdate, "_fetch_json", _boom)
    _write_cache(tmp_path, {
        "current": "0.0.1",
        "latest": "99.0.0",
        "checked_at": int(time.time()),
    })
    data = selfupdate.peek_cache(_config(tmp_path))
    assert data["latest"] == "99.0.0"
    assert data["cached"] is True
    assert data["stale"] is False
    assert data["update_available"] is True


def test_peek_cache_missing_marks_stale(tmp_path):
    """没有缓存 ⇒ stale=True（调用方据此起后台刷新），且不抛。"""
    data = selfupdate.peek_cache(_config(tmp_path))
    assert data["stale"] is True
    assert data["latest"] == ""
    assert data["update_available"] is False


@pytest.fixture
def env(tmp_path, monkeypatch):
    """离线桩：数据根落在 tmp_path，且**不起预热线程**（它会在 15 秒后碰网络）。"""
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: tmp_path / "library"))
    monkeypatch.setattr(EndfieldModControllerApi, "_start_warm_up", lambda self: None)
    return tmp_path


def test_app_dependency_entry_returns_without_network(env, monkeypatch):
    """缓存缺失 + 网络"很慢"：首屏那次调用必须**立刻**返回，网络动作在后台线程里。"""
    called: list[tuple[str, str]] = []
    done = threading.Event()

    def _slow_check_update(config, **_kwargs):
        called.append((threading.current_thread().name, "check_update"))
        time.sleep(0.05)
        done.set()
        return {}

    monkeypatch.setattr(selfupdate, "check_update", _slow_check_update)
    api = EndfieldModControllerApi(str(env / "config.json"))
    started = time.perf_counter()
    entry = api._app_dependency_entry()
    spent = time.perf_counter() - started
    assert spent < 0.5, f"首屏不该等网络（实测 {spent:.2f}s）"
    assert entry["is_app"] is True
    # 首屏连线程都不该起：只举手，联网交给预热收尾（预热=后台、不挡界面）
    assert called == [], "首屏不该同步联网"
    assert api._update_check_wanted is True, "缓存过期时应当举手，等预热去刷新"
    # 预热收尾时才真的拉，而且必须发生在后台线程（GUI 线程上一联网就是"点了没反应"）
    api._warm_done = True
    api._request_update_refresh()
    assert done.wait(2.0), "预热收尾时应当真的去刷新更新缓存"
    assert called and called[0][0] == "mc-update-check"


def test_startup_trace_report_line_never_raises():
    """打点缺项/取不到进程时间时也要能拼出一行，绝不因诊断把人挡在门外。"""
    line = startup_trace.report_line()
    assert line.startswith("启动时间线:")