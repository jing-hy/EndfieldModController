# SPDX-License-Identifier: GPL-3.0-or-later
"""商城「进页面不自动刷新」「大图一直加载中」的两条回归（2026-11-07 实测报障）。

用户原话：
1. 「现在进入 mod 商城还是不会自动增量刷新索引」
2. 「点到 mod 详情里打开不是第一张的图片会一直加载不出来，显示大图加载中…（点任意处取消）」

根因：
1. 顶部增量刷新是 loadMore().finally(refreshHead) —— 列表读完才轮到它，慢；而且
   **界面上完全没有痕迹**（状态行的「多久以前」用的是全量索引的 fetched_at），
   busy/失败还被前端静默吞掉 ⇒ 看起来就是「根本没刷新」。
   后端同理：成功时 launch.log 一行都不写。
2. detail 的 images 只有 full/big/thumb 三档，**没有 thumb_big**；页面预取的是
   img.thumb_big || img.thumb ⇒ 预取的永远是缩略图，点开大图每次都要现下，
   而灯箱在没图时只会一直显示「大图加载中…」（没有兜底、也没有超时说明）。
"""
from __future__ import annotations

import re
from pathlib import Path

from endfieldmodcontroller import launcher, modstore
from endfieldmodcontroller.api import EndfieldModControllerApi

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "StorePage.vue"


def _text() -> str:
    return PAGE.read_text(encoding="utf-8")


# ---------------------------------------------------------------- ① 进页面就刷新顶部
def test_mount_refreshes_head_in_parallel() -> None:
    text = _text()
    mount = text.split("onMounted(", 1)[-1].split("onUnmounted", 1)[0]
    assert "refreshHead();" in mount, "进商城页必须触发一次顶部增量刷新"
    assert "loadMore().finally(() => refreshHead())" not in text, (
        "不要再用 loadMore().finally(refreshHead)：列表读完才刷、且看不出刷没刷"
    )


def test_head_refresh_busy_retries_and_failure_is_visible() -> None:
    text = _text()
    assert "if (result.busy)" in text, "全量索引正在跑时要自己排队重试，而不是干等 60 秒的定时器"
    assert "headRetries" in text, "busy 重试要有次数上限（别无限转）"
    assert "顶部刷新失败" in text, "失败必须写在界面上，不许静默吞掉"


def test_status_line_shows_head_check_time() -> None:
    text = _text()
    assert "headAgeText" in text and "head_age" in text, (
        "状态行要显示「顶部已检查（多久前）」，否则用户只能看到全量索引的时龄"
    )


def test_backend_logs_head_refresh_result(monkeypatch) -> None:
    """成功也要落一行 launch.log —— 否则事后完全查不出「到底刷没刷过」。"""
    lines: list[str] = []
    monkeypatch.setattr(launcher, "_append_log", lambda cfg, msg: lines.append(str(msg)))
    monkeypatch.setattr(
        modstore, "head_refresh",
        lambda config, log=None: {"ok": True, "added": 2, "items": [{"id": 1}], "total": 9},
    )
    monkeypatch.setattr(modstore, "category_counts", lambda items, nsfw="blur": {"total": 1})
    monkeypatch.setattr(modstore, "index_state", lambda index, now=None: {"items": 9, "age": 1})

    class _Fake:
        config = object()

    out = EndfieldModControllerApi.mod_store_head_refresh(_Fake(), "blur")
    assert out["ok"] is True and out["added"] == 2
    assert any("顶部增量刷新 +2" in line for line in lines), lines


# ---------------------------------------------------------------- ② 灯箱大图
def test_detail_prefetch_uses_big_not_thumb_big() -> None:
    code = _text()
    assert re.search(r"prepareImages\(\(result\.item\.images \|\| \[\]\)\.map\(\(img\) => img\.big", code), (
        "detail 的 images 没有 thumb_big，预取必须用 img.big（否则每次点大图都要现下）"
    )


def test_lightbox_has_fallback_and_timeout_message() -> None:
    text = _text()
    assert "lightboxFallback" in text, "大图没到时要先用缩略图顶着（点开立刻有画面）"
    assert "lightboxSrc" in text, "灯箱渲染要走 lightboxSrc（大图 → 缩略图 → 空）"
    assert "这张大图取不回来" in text, "等太久要给一句实话，不能永远转「加载中」"
    assert "openLightbox(img.big || img.full || img.thumb, img.thumb)" in text, (
        "点击时要把缩略图一并传进去当兜底"
    )
