# SPDX-License-Identifier: GPL-3.0-or-later
"""「详情页第一张图能看，后面的图不点进去就一直加载中，点进去又有了」（2026-11-14 修）。

用户原话：「商城的详情页还是有点问题，会出现第一张图能正常加载，后面的图如果不点进去
会一直显示在加载，但点进去就有了，修一下」。

实测复现（本机直接跑后端）：同一个 Mod 的 4 张预览图，第一张 80 KB 约 10 秒到位，
其余三张是站点只给原图的截图（**0.5~1 MB**），前台怎么等都不出现 —— 而后端**不管前端
还在不在问**都继续下，脚本退出后再跑一次就全在本地了。两条根因各钉一条：

① **前端轮询固定 60 轮（约 36 秒）一刀切**：到点 clear() 走人，慢网下大图根本来不及，
   前端从此**再也不会问第二次** ⇒ 界面永远停在「加载中」；等用户点开灯箱时才又调一次
   prepare_images，那会儿后端早下好了 ⇒ 表现成「点进去就有了」。
   修法：改成**按进展**判 —— 只要还有新图到位就继续问，连续 PENDING_STALL_MS 无进展才停，
   停了也要在详情页给一句实话 + 重试入口（不许永远转圈）。

② **后端并发上限是"每个批次各 6 路"**：列表页的后台批次还在跑时打开详情就是 6+6=12 路，
   而那台机器三次实测的结论是「12 路会让整批**全部失败**」（站点按同 IP 并发连接数限制）。
   修法：进程内**全局**闸门 IMAGE_CONCURRENCY，所有批次的真正下载都从这里领名额。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "frontend" / "src" / "pages" / "StorePage.vue"
MODSTORE = ROOT / "endfieldmodcontroller" / "modstore.py"


def _store() -> str:
    return STORE.read_text(encoding="utf-8")


def test_pending_poll_gives_up_by_progress_not_by_a_fixed_round_count():
    """轮询不许再按固定轮数放弃（36 秒一刀切就是本次的根因）。"""
    text = _store()
    assert "rounds > 60" not in text, "轮询又变回「固定 60 轮就放弃」—— 慢网下大图必然来不及"
    assert "rounds += 1" not in text, "轮询又数起轮数来了"
    assert "PENDING_STALL_MS" in text, "没有「连续多久没有进展才放弃」的判据"
    assert "lastProgressAt" in text, "轮询没有跟踪「上次有进展的时间」"


def test_pending_poll_survives_slow_images_and_keeps_asking():
    """有进展就继续问：每轮都要把「还没到位的」重新问一遍（不是问一次就撒手）。"""
    text = _store()
    assert "await prepareBatch([...pendingImages2]);" in text, "轮询里没有继续向后端要图"
    # 放弃时**不许**把待问清单一并清空 —— 否则「重试」手里没东西可问
    assert "pendingImages2.clear()" not in text, "放弃时把待问清单清空了，重试将无从下手"


def test_detail_images_have_a_visible_failure_exit_with_retry():
    """详情那排图：取不回来时要说实话 + 给重试入口（不许永远显示「加载中」）。"""
    text = _store()
    assert "imagesStalled" in text, "没有「图取不回来」的状态"
    assert "retryDetailImages" in text, "没有重试入口"
    assert "图没取回来" in text, "占位文案里没有一句实话（仍是永远转圈）"
    assert '@click.stop="retryDetailImages"' in text, "重试没接到点击上（会顺手触发灯箱）"


def test_detail_thumbnails_join_the_lazy_loading_channel():
    """详情那排图也要被 observer 盯上：每次进详情都是一次新的机会。"""
    text = _store()
    assert ':data-thumb="img.preview || img.thumb"' in text, "详情预览图没有 data-thumb，永远不会被懒加载通道捡起"
    assert "observeThumbs();" in text, "详情渲染后没有 observeThumbs（第三张之后没人盯）"
    assert "detailImgSrc(img)" in text, "详情图没有「preview 优先、thumb 已在缓存就先用」的回退"


def test_backend_image_concurrency_is_global_not_per_batch():
    """后端：并发闸门必须是**进程级**的，不能每个批次各开 6 路（叠上去就是 12 路全失败）。"""
    text = MODSTORE.read_text(encoding="utf-8")
    assert "IMAGE_CONCURRENCY = 6" in text, "没有全局并发上限"
    assert "_IMAGE_SLOTS = threading.BoundedSemaphore(IMAGE_CONCURRENCY)" in text, "没有全局信号量"
    fetch = text.split("def _fetch_image(", 1)[1].split("def _drain_images(", 1)[0]
    assert "with _IMAGE_SLOTS:" in fetch, "_fetch_image 没走全局闸门（并发上限形同虚设）"
