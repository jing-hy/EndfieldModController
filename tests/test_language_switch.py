# SPDX-License-Identifier: AGPL-3.0-only
"""界面语言（zh / en）：设置页切换 + 导航/设置浮窗接入 i18n（2026-11-28 用户要求）。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"


def test_i18n_module_exists_with_both_languages() -> None:
    text = (SRC / "lib" / "i18n.js").read_text(encoding="utf-8")
    assert "export function t(" in text
    assert "export async function setLang(" in text
    assert "import.meta.glob" in text, "英文字典应按 lib/i18n/en/*.js 片段合并"
    core = (SRC / "lib" / "i18n" / "en" / "core.js").read_text(encoding="utf-8")
    assert '"通用": "General"' in core
    assert '"设置": "Settings"' in core


def test_nav_and_settings_dialog_use_t() -> None:
    app = (SRC / "App.vue").read_text(encoding="utf-8")
    assert "{{ t(tab.name) }}" in app, "侧栏导航没有走 i18n"
    assert '{{ t("设置") }}' in app
    dialog = (SRC / "components" / "SettingsDialog.vue").read_text(encoding="utf-8")
    assert "{{ t(s.name) }}" in dialog
    assert '{{ t("说明") }}' in dialog


def test_nav_v_for_alias_does_not_shadow_i18n_t() -> None:
    """模板里 `v-for="t in tabs"` 会遮蔽 i18n 的 t() 函数 —— 2026-11-28 启动全白事故。"""
    app = (SRC / "App.vue").read_text(encoding="utf-8")
    assert 'v-for="t in tabs"' not in app, "v-for 别名 t 会遮蔽 i18n 的 t()"
    assert 'v-for="tab in tabs"' in app
    assert "{{ t(tab.name) }}" in app


def test_store_applies_language_from_config() -> None:
    store = (SRC / "store.js").read_text(encoding="utf-8")
    assert "applyLang(cfgLanguage)" in store
    assert 'import { applyLang } from "./lib/i18n.js"' in store