# SPDX-License-Identifier: AGPL-3.0-only
"""主题拆成「底色 + 强调色」两维（2026-11-28 用户：「背景色应该和强调色应该分开能选择」）。

约束：`config.py` 的 THEME_BASES / THEME_ACCENTS 必须与 `frontend/src/store.js` 完全一致，
否则用户选的存不住（2026-10-04 踩过：两边不一致 ⇒ 选琥珀后下次启动被静默改回 light）。
旧配置（theme=amber/...）必须迁移成 dark + 对应强调色，不能直接变浅色。
"""
from __future__ import annotations

import json
from pathlib import Path

from endfieldmodcontroller.config import AppConfig, THEME_ACCENTS, THEME_BASES

ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_legacy_six_way_theme_migrates_to_dark_plus_accent(tmp_path: Path) -> None:
    cfg = AppConfig.load(_write(tmp_path, {"theme": "amber"}))
    assert cfg.theme == "dark"
    assert cfg.theme_accent == "amber"


def test_new_dimensions_are_kept(tmp_path: Path) -> None:
    cfg = AppConfig.load(_write(tmp_path, {"theme": "dark", "theme_accent": "emerald"}))
    assert cfg.theme == "dark"
    assert cfg.theme_accent == "emerald"


def test_invalid_values_fall_back(tmp_path: Path) -> None:
    cfg = AppConfig.load(_write(tmp_path, {"theme": "neon", "theme_accent": "rainbow"}))
    assert cfg.theme == "light"
    assert cfg.theme_accent == "blue"


def test_whitelists_match_frontend() -> None:
    store = (ROOT / "frontend" / "src" / "store.js").read_text(encoding="utf-8")
    assert 'export const THEME_BASES = ["light", "dark"];' in store
    assert 'export const THEME_ACCENTS = ["blue", "amber", "cyan", "violet", "emerald"];' in store
    assert THEME_BASES == ("light", "dark")
    assert THEME_ACCENTS == ("blue", "amber", "cyan", "violet", "emerald")


def test_tokens_define_accent_and_soft_by_base() -> None:
    css = (ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")
    for accent in ("amber", "cyan", "violet", "emerald"):
        assert f'[data-theme-accent="{accent}"]' in css, f"缺少强调色 {accent} 的定义"
    for base in ("light", "dark"):
        assert f'[data-theme="{base}"][data-theme-accent="amber"]' in css


def test_first_paint_script_sets_both_attributes() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'setAttribute("data-theme", t)' in html
    assert 'setAttribute("data-theme-accent", a)' in html
    assert "legacy[t]" in html, "首屏脚本没有迁移旧的六套主题值"