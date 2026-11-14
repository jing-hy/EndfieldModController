# SPDX-License-Identifier: GPL-3.0-or-later
"""详情页「预览图糊」与「下载键灰掉」的两条回归（2026-11-08 实测报障）。

用户原话：
  「mod商城里详情页的图片除了第一张图以外其他图片都很模糊，但点开又清晰」
  「而且详情页下载键都是灰的，点不了」

根因（都出在详情接口的字段上，不是前端样式）：
1. `Mod/ProfilePage`（以及带 csvProperties 的 `Mod/<id>`）里，很多截图**只有 100px 那一档**
   （`100-90_xxx.jpg`）。详情那一排原先用 `thumb`（530→220→100），于是 100px 被放大到
   200px 宽 ⇒ 糊；而灯箱用 `big/full`（原图）⇒ 清晰。
2. 详情**不返回 `_bHasFiles`**（实测 raw._bHasFiles = None），而 `normalize()` 的 has_files
   只读这个字段 ⇒ 详情页恒为 False ⇒ 前端 `:disabled="… || !detail.has_files"` 永远禁用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from endfieldmodcontroller import modstore

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "StorePage.vue"


def _fake_detail(**extra: Any) -> dict:
    base = "https://images.gamebanana.com/img/ss/mods"
    return {
        "_idRow": 7,
        "_sName": "Demo",
        "_sProfileUrl": "https://gamebanana.com/mods/7",
        "_aFiles": [
            {"_sFile": "demo.zip", "_sDownloadUrl": "https://gamebanana.com/dl/1",
             "_tsDateAdded": 100, "_nFilesize": 10},
        ],
        "_aPreviewMedia": {"_aImages": [
            {"_sBaseUrl": base, "_sFile": "a.jpg", "_sFile530": "530-90_a.jpg", "_sFile100": "100-90_a.jpg"},
            # 只有 100px 那一档（正是用户看到"糊"的那种）
            {"_sBaseUrl": base, "_sFile": "b.jpg", "_sFile100": "100-90_b.jpg"},
        ]},
    }


def test_detail_has_files_when_profile_page_omits_flag(monkeypatch) -> None:
    """详情不返回 _bHasFiles 时，必须按 _aFiles 重新判 —— 否则下载键永远是灰的。"""
    payload = _fake_detail()
    payload.pop("_bHasFiles", None)
    monkeypatch.setattr(modstore, "_get", lambda url, **kw: payload)
    out = modstore.detail(7)
    assert out["files"], "详情应当解析出可下载文件"
    assert out["has_files"] is True, "有 _aFiles 就必须认为 has_files=True"


def test_detail_has_files_false_when_no_files(monkeypatch) -> None:
    payload = _fake_detail()
    payload["_aFiles"] = []
    monkeypatch.setattr(modstore, "_get", lambda url, **kw: payload)
    assert modstore.detail(7)["has_files"] is False


def test_detail_preview_never_uses_the_100px_tier(monkeypatch) -> None:
    monkeypatch.setattr(modstore, "_get", lambda url, **kw: _fake_detail())
    images = modstore.detail(7)["images"]
    assert images[0]["preview"].endswith("530-90_a.jpg"), "有 530 就该用 530"
    # 只有 100px + 原图时：preview 用原图（清晰），thumb 才落到 100px（列表卡片够用）
    assert images[1]["thumb"].endswith("100-90_b.jpg")
    assert images[1]["preview"].endswith("b.jpg")
    for img in images:
        assert "100-90_" not in img["preview"], f"详情预览不许用 100px 档：{img['preview']}"


# ---------------------------------------------------------------- 前端：详情那一排用 preview
def test_detail_row_uses_preview_tier() -> None:
    text = PAGE.read_text(encoding="utf-8")
    # ⚠️ 2026-11-14：详情那一排的显示源收进了 detailImgSrc() —— preview **优先**，
    # thumb 只是"本地缓存里已经有就先顶着"的兜底（不许反过来，否则又变成 100px 撑大图）。
    assert "detailImgSrc(img)" in text, "详情那一排必须用 preview（而不是可能只有 100px 的 thumb）"
    assert "return imageSrc(img.preview) || imageSrc(img.thumb);" in text, (
        "detailImgSrc 必须 preview 优先，thumb 只在本地已有时兜底"
    )
    # 详情那一排以前写的是 `imageSrc(img.thumb_big || img.thumb)` —— detail.images 里没有 thumb_big，
    # 等于永远退到 thumb。断言它已经不在（只允许出现在列表卡片的 listSrc 那条路上）。
    assert "imageSrc(img.thumb_big || img.thumb)" not in text
    assert "openLightbox(img.full || img.big || img.preview, img.preview || img.thumb)" in text


def test_detail_prefetch_uses_preview() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert "img.preview || img.big || img.full || img.thumb" in text, (
        "打开详情时要先预取 preview（530 档），点开灯箱才有缓存可用"
    )
