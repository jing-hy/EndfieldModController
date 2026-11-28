# SPDX-License-Identifier: AGPL-3.0-only
"""Mod 商城「一键更新」：按钮不能再因为“还没扫描”而一直不可点。

2026-11-28 用户反馈：「mod 商城的一键更新是按不了的，也要修」。
现场：按钮绑的是 disabled=!updateCount，而 updateCount 来自上次扫描结果
（runtime/_state/modstore_updates.json）；没扫过 = 按钮永久禁用，点了没反应。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "src" / "pages" / "StorePage.vue"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_update_button_is_not_disabled_without_scan_result() -> None:
    page = _page()
    assert ':disabled="!updateCount"' not in page, "一键更新又被绑成了没有扫描结果就禁用"
    assert 'variant="primary" :disabled="scan.running" @click="updateAll()"' in page


def test_update_all_starts_a_scan_when_there_is_no_saved_result() -> None:
    page = _page()
    assert "pendingUpdateAll" in page, "没有先扫描、扫完自动更新这条路径"
    assert "await scanUpdates()" in page
    assert "updateAll(true)" in page, "扫描结束后没有自动接着执行更新"


def test_index_button_refreshes_the_index() -> None:
    """「扫描更新」改名「索引更新」，点了就是重建索引（2026-11-28 用户更正语义）。"""
    page = _page()
    assert "索引更新" in page
    assert '@click="refreshIndex"' in page
    assert ': "扫描更新"' not in page, "旧按钮文案还在（它其实是索引刷新，名字误导）"


def test_update_button_scans_before_downloading() -> None:
    """「一键更新」= 检查已下载 Mod 有没有新版本，有就加入下载 —— 每次点都先扫。"""
    page = _page()
    assert "if (!auto) {" in page
    assert "pendingUpdateAll = true" in page
    assert "正在检查已下载 Mod 的新版本" in page
    assert "已下载的 Mod 都是最新版本" in page


def test_detail_request_cannot_pull_the_page_back() -> None:
    """详情加载期间离开 ⇒ 结果作废，不许把页面又拉回详情（2026-11-28 用户）。"""
    page = _page()
    assert "detailSeq" in page
    assert "seq !== detailSeq" in page, "详情回调没有检查请求是否还有效"
    assert "detailSeq++" in page, "关闭详情时没有作废在途请求"


def test_backend_still_reports_a_readable_reason() -> None:
    text = (ROOT / "endfieldmodcontroller" / "api.py").read_text(encoding="utf-8")
    assert "还没有可用的扫描结果 —— 先点「扫描更新」" in text