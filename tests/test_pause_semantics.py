"""「暂停保留断点 / 终止清半成品」必须在**取消那一刻**判定（2026-10-06）。

用户实测原话：「**我按的是暂停，弹窗告诉我终止了，而且清除半成品**」。

根因：`api` 传的是 `keep_partial=bool(self._mod_dl.get("pause"))` —— 一个**值**，
在"进入 `moddl.download()`"那一刻就定死了；而用户是在下载**已经跑起来之后**才点暂停的
⇒ 那个快照永远是 `False` ⇒ **点暂停也走「终止」分支**：清掉半成品、日志写「下载已终止」、
弹窗说「已终止（半成品已清理）」。
日志现场：`10:43:29 Mod 下载: 用户点了暂停（保留断点）` → `10:44:02 下载已终止：…`。

要守住的性质：
* 取消那一刻 `pause=True` ⇒ 报「已暂停」、**保留**半成品（下次能续传）；
* 取消那一刻 `pause=False` ⇒ 报「已终止」；
* 传**值**仍然兼容（老写法），但只有传**函数**才能读到"运行中"的状态 —— 这条钉住它；
* `fastnet._adaptive_read_size`：慢线路读小块（决定"点暂停后多久真的停"），快线路照旧满块。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import dependencies, fastnet, moddl


def _drive_download(tmp_path: Path, monkeypatch, *, keep_partial, pause_at_cancel: bool):
    """让 `dependencies._http_get` 在"下载跑起来之后"抛 `Cancelled`，模拟用户此时点按钮。"""
    state = {"pause": False}

    def fake_http_get(url, dest=None, **kwargs):  # noqa: ANN001, ANN003
        state["pause"] = pause_at_cancel       # 关键：取消**那一刻**的状态
        raise fastnet.Cancelled("用户暂停/终止")

    monkeypatch.setattr(dependencies, "_http_get", fake_http_get)
    kwargs = {"cancel": lambda: True}
    if callable(keep_partial):
        kwargs["keep_partial"] = lambda: state["pause"]
    else:
        kwargs["keep_partial"] = keep_partial
    return moddl.download("https://example.com/mod.zip", tmp_path, **kwargs)


def test_pause_state_is_read_at_cancel_time(tmp_path, monkeypatch):
    """**传函数**（现在的写法）：取消那一刻 pause=True ⇒ 报「已暂停」，不能报「已终止」。"""
    _path, error, _slow = _drive_download(
        tmp_path, monkeypatch, keep_partial=lambda: True, pause_at_cancel=True)
    assert error == "已暂停", f"点暂停被当成了终止：{error}"


def test_terminate_state_is_read_at_cancel_time(tmp_path, monkeypatch):
    """取消那一刻 pause=False ⇒ 报「已终止」、清半成品。"""
    _path, error, _slow = _drive_download(
        tmp_path, monkeypatch, keep_partial=lambda: False, pause_at_cancel=False)
    assert error == "已终止", error


def test_value_form_is_snapshot_and_would_misreport(tmp_path, monkeypatch):
    """**传值**（老写法）即使运行中改成暂停，读到的仍是进入时的快照 —— 这正是那个 bug。

    这条测试的意义：把"传值 ⇒ 读不到运行中状态"钉成**已知事实**，
    将来谁改回传值，这里立刻会说话。
    """
    _path, error, _slow = _drive_download(
        tmp_path, monkeypatch, keep_partial=False, pause_at_cancel=True)
    assert error == "已终止", "传值的语义就是「进入时快照」，与运行中的状态无关"


@pytest.mark.parametrize("mbps,expected_max", [(10.0, fastnet.READ_CHUNK), (0.008, fastnet.MIN_READ_CHUNK)])
def test_adaptive_read_size(mbps, expected_max):
    """慢线路读小块（暂停才秒级生效）；快线路照旧用满 `READ_CHUNK`。"""
    size = fastnet._adaptive_read_size(mbps)
    assert fastnet.MIN_READ_CHUNK <= size <= fastnet.READ_CHUNK
    assert size == expected_max


def test_adaptive_read_size_unknown_speed_falls_back():
    assert fastnet._adaptive_read_size(0) == fastnet.READ_CHUNK
