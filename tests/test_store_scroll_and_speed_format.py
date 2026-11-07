# SPDX-License-Identifier: GPL-3.0-or-later
"""三件「用户看得见却不该发生」的事，各自钉住（2026-11-07 实测报障）。

用户原话：
1. 「mod 商城在全部里往下滑滑到最下会显示往下滑自动加载，**然后就划不动了**」
2. 「为什么最开始一下这么慢，**在干什么**」（点了「下载并补齐组件」，前面 41 秒日志一片空白）
3. 「会显示 **9.513806651037655 B/s**」

根因（都不是"玄学卡顿"）：
1. `StorePage.vue` 的列表长度 watcher 用了 **默认的 flush='pre'** —— 回调在 DOM 更新**之前**跑，
   而哨兵节点是 `v-if="items.length"`，首屏那一刻 `sentinel.value` 还是 null，
   `watchSentinel()` 于是只执行了 `disconnect()`、**没 observe 任何节点**；
   只要首屏一页就铺满视口（`fillIfNeeded` 不需要补第二页），就再没人盯哨兵 ⇒ 滚到底不再加载。
2. `runtime_deps._resolve_builtin_asset` 里查上游 release（网页路线 + 自动换镜像 + 探测）
   是整个更新里最慢的一步，**原来前面一行日志都不写** ⇒ 界面看起来像卡死。
3. `lib/util.js` 的 `humanSize()` 对 <1 KB 直接 `n + " B"` —— 速度是浮点 EMA，
   于是把 `9.513806651037655` 原样印到界面上（与 2026-10-03「23.76781745624384%」同类）。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


# ---------------------------------------------------------------- ① 商城无限滚动
def test_store_sentinel_watch_is_post_flush() -> None:
    """列表长度 watcher 必须 post-flush —— 否则首屏哨兵还没渲染就去 observe 了。"""
    text = (SRC / "pages" / "StorePage.vue").read_text(encoding="utf-8")
    block = re.search(
        r"watch\(\s*\(\)\s*=>\s*items\.value\.length(.{0,400})",
        text, re.S,
    )
    assert block, "StorePage.vue 里找不到「items.length」的 watcher（结构变了就更新本测试）"
    window = block.group(0)
    assert 'flush: "post"' in window or "flush: 'post'" in window, (
        "watcher 必须 { flush: \"post\" }：默认 pre 会在 DOM 落地前跑，"
        "哨兵（v-if=items.length）那一刻还不存在 ⇒ observer 盯不上 ⇒ 滚到底不再加载"
    )
    assert "nextTick" in window, "post-flush 之后仍要 await nextTick() 再 observe 更稳"


def test_load_more_rearms_sentinel_observer() -> None:
    """每加载完一页都要兜底重新盯哨兵（首屏/换页/从详情返回都可能换掉节点）。"""
    text = (SRC / "pages" / "StorePage.vue").read_text(encoding="utf-8")
    tail = text.split("async function loadMore", 1)[-1].split("function reload", 1)[0]
    assert "watchSentinel()" in tail, (
        "loadMore 的收尾里必须重新 watchSentinel()：只靠 watcher 会漏，"
        "漏了的表现就是「往下滑自动加载」永远不动"
    )


# ---------------------------------------------------------------- ② 速度格式化
def test_human_size_never_prints_raw_float() -> None:
    """<1 KB 的数值必须格式化 —— 否则会出现 9.513806651037655 B/s。"""
    text = (SRC / "lib" / "util.js").read_text(encoding="utf-8")
    body = text.split("export function humanSize", 1)[-1].split("export function", 1)[0]
    assert 'toFixed(1) + " B"' in body, "小于 1 KB 的分支必须取整（否则浮点速度原样上屏）"
    assert not re.search(r"return\s+n\s*\+\s*[\"']\s*B", body), (
        "不要直接把 n 拼成 \"B\"：n 是浮点（EMA 速度），会印出一长串小数"
    )


# ---------------------------------------------------------------- ③ 更新依赖的可观测性
def test_release_lookup_reports_progress(monkeypatch) -> None:
    """查上游最新版这一步必须**先报开始**、慢的时候再报用时（之前 41 秒零日志）。"""
    from endfieldmodcontroller import offline_deps, runtime_deps

    notes: list[str] = []
    monkeypatch.setattr(runtime_deps, "_note", lambda cfg, msg: notes.append(str(msg)))
    monkeypatch.setattr(offline_deps, "resolve_offline", lambda cfg, key: None)
    monkeypatch.setattr(
        runtime_deps, "_latest_release_asset",
        lambda repo, pattern, include_prerelease=False: (
            "https://example.invalid/x.zip", "v9.9.9", "x.zip", ""),
    )
    clock = {"t": 1000.0}
    monkeypatch.setattr(runtime_deps.time, "time", lambda: clock["t"])

    def slow(*args, **kwargs):
        clock["t"] += 12.5
        return ("https://example.invalid/x.zip", "v9.9.9", "x.zip", "")

    monkeypatch.setattr(runtime_deps, "_latest_release_asset", slow)

    out = runtime_deps._resolve_builtin_asset(None, "XXMI", "SpectrumQT/XXMI-Launcher", "xxmi")
    assert out[1] == "v9.9.9"
    assert any("正在读取上游最新版本" in n for n in notes), "查版本前必须先写一行「正在读取…」"
    assert any("查最新版本用了" in n for n in notes), "超过 2 秒必须回报实际用时"
