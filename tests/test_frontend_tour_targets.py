# SPDX-License-Identifier: GPL-3.0-or-later
"""新手引导的落点必须真实存在（2026-11-05 用户要求改第 2 步时补上的回归）。

**为什么钉这条**：0.9.5 踩过一次 —— 引导第 2 步指向 `#mod-download-box`，而那代前端里
根本没这个 id ⇒ `getElementById` 返回 null ⇒ 聚光框宽高 0、卡片只能居中，用户看不出该点哪。
`vite build` 不会报这种错（字符串对不上不是语法错误），只能静态检查。

2026-11-05 用户原话：「改一下新手引导，添加 mod 那步改成展示 mod 商城，文案也微调一下，
三种方式添加都说明」。于是第 2 步从「下载」页的 `#mod-download-box` 挪到商城的
`#store-browse-box`，正文把「拖进来 / 商城 / 粘贴网址」三条路都写清。这组测试钉住两件事：

1. 每一步的 `target` 在前端源码里**真的有个元素带这个 id**（否则聚光退化成不可见）；
2. 第 2 步就是商城那一页，且正文把三种添加方式都提到（下次改文案漏一种会立刻红）。
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"


def _tour_steps() -> list[dict[str, str]]:
    """从 App.vue 里抠出 TOUR_STEPS 的每一步（tab / target / title / body 原文）。"""
    src = (FRONTEND / "App.vue").read_text(encoding="utf-8")
    start = src.index("const TOUR_STEPS")
    end = src.index("];", start)
    block = src[start:end]
    steps: list[dict[str, str]] = []
    for chunk in block.split("\n  {")[1:]:
        fields: dict[str, str] = {}
        for key in ("tab", "target", "title"):
            match = re.search(key + r':\s*"([^"]+)"', chunk)
            if match:
                fields[key] = match.group(1)
        body = chunk.split("body:", 1)[1] if "body:" in chunk else ""
        fields["body"] = "".join(re.findall(r'"(?:[^"\\]|\\.)*"', body))
        steps.append(fields)
    return steps


def _sources_with_id(element_id: str) -> list[str]:
    """哪些前端源码里出现了 id="…"（只找 .vue）。"""
    needle = 'id="' + element_id + '"'
    hits: list[str] = []
    for path in FRONTEND.rglob("*.vue"):
        try:
            if needle in path.read_text(encoding="utf-8"):
                hits.append(str(path.relative_to(FRONTEND)))
        except OSError:
            continue
    return hits


def test_every_tour_target_exists() -> None:
    """每一步的高亮目标都必须能在前端源码里找到对应 id。"""
    steps = _tour_steps()
    assert len(steps) >= 4, "TOUR_STEPS 解析失败（只拿到 %d 步）" % len(steps)
    missing = [step.get("target") for step in steps
               if step.get("target") and not _sources_with_id(step["target"])]
    targets = [step.get("target") for step in steps]
    assert not missing, (
        "这些引导落点在前端源码里找不到对应元素 id，聚光会退化成不可见：%s（全部落点：%s）"
        % (missing, targets)
    )


def test_second_step_shows_the_store_and_three_ways() -> None:
    """第 2 步 = Mod 商城，且正文讲清「拖进来 / 商城 / 粘贴网址」三种方式。"""
    step = _tour_steps()[1]
    assert step.get("tab") == "store", "第 2 步应当在商城页，现在是 %r" % step.get("tab")
    assert step.get("target") == "store-browse-box", (
        "第 2 步应当高亮商城的「Mod 商城」卡片，现在是 %r" % step.get("target")
    )
    body = step.get("body", "")
    for keyword in ("拖", "商城", "网址"):
        assert keyword in body, "第 2 步正文没提到「%s」这条添加方式：%r" % (keyword, body)


def test_store_page_keeps_the_tour_anchor() -> None:
    """商城那张卡片上的 id 是引导的落点，别在改商城时顺手删掉。"""
    page = (FRONTEND / "pages" / "StorePage.vue").read_text(encoding="utf-8")
    assert 'id="store-browse-box"' in page, (
        "StorePage.vue 里的 store-browse-box 没了 —— 新手引导第 2 步会变成没有高亮"
    )