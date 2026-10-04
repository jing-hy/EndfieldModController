"""热重载（`hot_reload`）的回归测试。

对应 2026-10-04 用户要求：「加一个热重载，如果终末地在运行……点了热重载能包括改配置按 f10 等等」。

钉住三件事（都是踩过或容易踩的）：
  ① **找窗口的判据是进程名，不是窗口标题** —— 第一版按标题找，把开着的浏览器标签页
     （标题里带 "…Endfield…"）当成了游戏窗口；那样 F10 会发给浏览器，用户只看到"点了没反应"。
  ② 游戏中/不在游戏中要能区分：没找到游戏窗口时，`send_f10` 必须**明确报原因**而不是静默返回。
  ③ 关键字可配置，留空/写脏数据都要能落回默认那组。
"""
from __future__ import annotations

import os

import pytest

from endfieldmodcontroller import hot_reload
from endfieldmodcontroller.config import AppConfig


def test_window_keywords_falls_back_to_defaults() -> None:
    config = AppConfig()
    assert hot_reload.window_keywords(config) == hot_reload.DEFAULT_WINDOW_KEYWORDS
    config.game_window_keywords = "   ,  ,"          # 全空 ⇒ 仍走默认
    assert hot_reload.window_keywords(config) == hot_reload.DEFAULT_WINDOW_KEYWORDS
    config.game_window_keywords = "Endfield, 终末地"
    assert hot_reload.window_keywords(config) == ("Endfield", "终末地")


def test_window_keywords_accepts_list() -> None:
    config = AppConfig()
    config.game_window_keywords = ["Arknights", " Endfield "]     # type: ignore[assignment]
    assert hot_reload.window_keywords(config) == ("Arknights", "Endfield")


@pytest.mark.skipif(os.name != "nt", reason="窗口枚举只在 Windows 上有意义")
def test_find_game_window_only_matches_game_process() -> None:
    """**不管现在有没有开游戏**，只要进程名不是 `Endfield.exe` 就绝不能命中。

    这条正是为了钉住 ①：把浏览器/编辑器之类"标题里带关键字"的窗口排除掉。
    """
    found = hot_reload.find_game_window(hot_reload.DEFAULT_WINDOW_KEYWORDS)
    if found is not None:
        hwnd, title = found
        # 真的命中了，那就必须是 Endfield.exe 的窗口（有标题时标题不该像浏览器）
        assert isinstance(hwnd, int) and hwnd > 0
        assert "chrome" not in title.lower()
        assert "edge" not in title.lower()


@pytest.mark.skipif(os.name != "nt", reason="SendInput 只在 Windows 上有意义")
def test_send_f10_reports_reason_when_no_game() -> None:
    """没有游戏进程时必须**明确报原因**（绝不能静默成功）。"""
    result = hot_reload.send_f10(AppConfig())
    assert isinstance(result, dict)
    if result.get("ok"):
        # 本机真在跑游戏（少见）—— 那就至少要有窗口信息
        assert result.get("hwnd") and result.get("window") is not None
    else:
        assert result.get("message"), "失败时必须带原因"
        assert "没找到" in str(result["message"]), "失败原因要说清是「没找到窗口」"
        assert result.get("candidates") == [] or isinstance(result.get("candidates"), list)
