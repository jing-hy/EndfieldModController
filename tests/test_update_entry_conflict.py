# SPDX-License-Identifier: GPL-3.0-or-later
"""「更新不了」的入口冲突回归（2026-10-16，反馈者诊断包 `diagnostics-20261015-233155`）。

**现象**：反馈者只说「更新不了」。诊断包里的事实是：

* `runtime\\_update\\` 里**只有** `last_check.json` —— 没有下载好的载荷、没有 `applied.json`；
* `logs\\launch.log` / 会话日志里**一句自更新的话都没有**（既没有"检查更新：…"，
  也没有"开始下载更新包 …"）；
* 缓存里 `current=1.4.0 / latest=1.4.2`，也就是界面上**一直亮着**"v1.4.0 → v1.4.2"。

⇒ 结论只能是"程序更新这条路径**一次都没真正跑起来**"，而界面却按"已下载"收过尾。

**根因**：三个入口（程序自更新 / 安装依赖 / 一键更新全部组件）开头都写着

    if self._dep_task and self._dep_task.get("running"):
        return self.get_dependency_progress()

—— 把**另一个任务**的进度静默当成自己的结果返回。于是"组件更新正在跑时点程序更新"
这一条链路会：① 徽章开始显示**别人的**进度；② 组件任务正常结束（消息正是"完成"）时，
前端按 `/已下载|完成/` 匹配 ⇒ 报「更新包已下载，等待你选择何时安装」；③ 其实什么都没下，
程序还是旧版、还提示有新版 ⇒ 用户看到的就是「更新不了」。

**修法**：入口如实拒绝（`ok=False` + `busy=True` + 一句人话）并落日志；前端只认
`app_update` 任务、且必须 `pending_apply` 才算"包已下载"（前端那份回归在
`tests/test_update_badge_frontend.py`）。
"""
from __future__ import annotations

import time

import pytest

from endfieldmodcontroller import launcher, selfupdate
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


@pytest.fixture
def env(tmp_path, monkeypatch):
    """离线桩：配置与数据根都落在 tmp_path 下，绝不碰真实工作区的 runtime / library。"""
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: tmp_path / "library"))
    return tmp_path


@pytest.fixture
def logs(monkeypatch):
    """把 `launcher._append_log` 换成内存列表 —— 日志断言不看文件、只看有没有写。"""
    lines: list[str] = []
    monkeypatch.setattr(launcher, "_append_log", lambda config, message: lines.append(str(message)))
    return lines


def _api(env):
    return EndfieldModControllerApi(str(env / "config.json"))


def _running_component_task() -> dict:
    """正在跑的**组件更新**任务（不是自更新）。"""
    return {
        "running": True, "current": 1, "total": 3, "percent": 42.0,
        "message": "XXMI: installed", "log": [], "results": [],
    }


def _running_app_task() -> dict:
    return {
        "running": True, "app_update": True, "current": 0, "total": 1, "percent": 10.0,
        "message": "正在下载 v1.4.3…", "log": [], "results": [],
    }


# ---------------------------------------------------------------------------
# ① 组件更新在跑时点「程序更新」⇒ 必须如实拒绝，而不是拿别人的进度冒充
# ---------------------------------------------------------------------------
def test_app_update_is_refused_while_component_update_runs(env, logs):
    api = _api(env)
    task = _running_component_task()
    api._dep_task = task

    result = api.start_app_update()

    assert result.get("ok") is False, "不得静默返回另一个任务的进度（那就是「点了没反应」的原形）"
    assert result.get("busy") is True
    assert result.get("app_update") is False
    assert "等它结束后再" in str(result.get("message") or "")
    # 关键：**不许**把任务替换成自更新任务（原来会走到下面的赋值，这里必须没走到）
    assert api._dep_task is task, "自更新任务被启动了 —— 用户会以为在下程序更新"
    assert not task.get("app_update")
    assert any("被拒绝" in line for line in logs), "拒绝必须落日志（诊断包里查不出就是这个原因）"


def test_dependency_update_is_refused_while_app_update_runs(env, logs):
    """反向：自更新在跑时点「安装依赖 / 一键更新全部组件」也要明确拒绝。"""
    api = _api(env)
    task = _running_app_task()
    api._dep_task = task

    for result in (api.start_dependency_update(), api.start_full_update()):
        assert result.get("ok") is False
        assert result.get("busy") is True
        assert result.get("app_update") is True
        assert "等它结束后再" in str(result.get("message") or "")
    assert api._dep_task is task, "自更新任务不许被组件任务顶掉"
    assert any("被拒绝" in line for line in logs)


# ---------------------------------------------------------------------------
# ② 重复点自己 / 跑的是同类任务 ⇒ 保持原行为：给进度（不能变成"被拒绝"）
# ---------------------------------------------------------------------------
def test_repeat_click_on_app_update_returns_progress(env, logs):
    api = _api(env)
    api._dep_task = _running_app_task()

    result = api.start_app_update()

    assert result.get("busy") is None or result.get("busy") is False
    assert result.get("running") is True
    assert result.get("app_update") is True
    assert result.get("percent") == 10.0
    assert not any("被拒绝" in line for line in logs), "重复点自己不算被别的任务挡住"


def test_repeat_click_on_component_update_returns_progress(env, logs):
    api = _api(env)
    api._dep_task = _running_component_task()

    result = api.start_full_update()

    assert result.get("running") is True
    assert result.get("percent") == 42.0
    assert not any("被拒绝" in line for line in logs)


# ---------------------------------------------------------------------------
# ③ 空闲时照旧能真的开始自更新（别把正常路径一起堵死）
# ---------------------------------------------------------------------------
def test_app_update_still_starts_when_idle(env, logs, monkeypatch):
    api = _api(env)
    monkeypatch.setattr(
        selfupdate, "check_update",
        lambda config, **kwargs: {"current": "1.4.0", "latest": "1.4.0",
                                  "update_available": False},
    )

    result = api.start_app_update()
    assert result.get("busy") is not True

    deadline = time.time() + 5.0
    while time.time() < deadline and (api._dep_task or {}).get("running"):
        time.sleep(0.05)

    assert api._dep_task is not None
    assert api._dep_task.get("app_update") is True
    assert api._dep_task.get("running") is False
    assert "已是最新" in str(api._dep_task.get("message") or "")
