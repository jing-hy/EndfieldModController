# SPDX-License-Identifier: AGPL-3.0-only
"""切标签不销毁页面（2026-11-28 用户要求）。

用户原话：「如果没重启，mod 商城也不应该因为切页面就跳回主页，如果切其他标签时正在加载详情页，
详情页应当继续加载」—— 以前 `<component :is="currentPage">` 没有 KeepAlive，切走就销毁重建。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return ROOT.joinpath("frontend", "src", *parts).read_text(encoding="utf-8")


def test_tab_switch_keeps_the_page_alive() -> None:
    app = _read("App.vue")
    assert '<KeepAlive v-if="currentPage">' in app
    assert '<component :is="currentPage" />' in app
    # v-else 必须紧挨着 KeepAlive（拆开就会编译报错，历史踩过）
    assert '<div v-else class="card p-6 text-sm"' in app


def test_store_page_detail_survives_tab_switch() -> None:
    store = _read("pages", "StorePage.vue")
    # 详情/滚动状态是组件内 ref；保活后切走再回来不会重新 onMounted 拉列表
    assert "const detail = ref" in store
    assert "<KeepAlive" in _read("App.vue")


def test_store_nsfw_mode_is_remembered() -> None:
    """R18 三档要跨页面/重启记住（2026-11-28 用户要求）：config 是权威，localStorage 回填。"""
    store = _read("pages", "StorePage.vue")
    assert 'call("save_config", { mod_store_nsfw: mode })' in store
    assert "savedNsfw" in store
    assert "mod_store_nsfw" in store


def test_downloads_page_has_a_done_card() -> None:
    page = _read("pages", "DownloadsPage.vue")
    # 文案走 i18n（2026-11-28 起）：裸 `title="已下载"` 与 `:title="t('已下载')"` 都算对
    assert 'title="已下载"' in page or ":title=\"t('已下载')\"" in page, "没有「已下载」卡片"
    assert "const doneItems" in page and "const pendingItems" in page
    assert 'v-for="(item, index) in pendingItems"' in page, "进行中列表应只显示未入库的"
    assert "已入库" in page