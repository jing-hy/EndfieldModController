# SPDX-License-Identifier: AGPL-3.0-only
"""商城从详情返回要回到进入前的位置（2026-11-28 用户要求）。

用户原话：「从详情页出来应该回到进去时的位置而不是到顶」。

成因：列表与详情是 v-if 切换，详情比列表矮时浏览器会把 scrollY 截断，
返回列表后不会自己回到原处。做法是进详情前记下 window.scrollY，返回时恢复
（列表卡片是 nextTick 之后才渲染的，所以恢复要重试几帧）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _store_page() -> str:
    return ROOT.joinpath("frontend", "src", "pages", "StorePage.vue").read_text(encoding="utf-8")


def test_store_remembers_and_restores_the_list_scroll() -> None:
    page = _store_page()
    assert "let listScrollY = 0" in page, "没有记住进入详情前的列表位置"
    assert "function restoreListScroll" in page
    # 进详情要回到顶部看，否则从列表中部点进去会看到详情中间
    assert "window.scrollTo(0, 0)" in page, "进详情没有回到顶部"
    # 恢复必须发生在返回商城那一步
    close_part = page.split("function closeDetail")[1][:400]
    assert "restoreListScroll()" in close_part, "返回商城时没有恢复列表位置"
