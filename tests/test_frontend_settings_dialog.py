# SPDX-License-Identifier: AGPL-3.0-only
"""设置浮窗化（2026-11-28 用户要求）的静态回归。

用户原话（节选）：「把左边导航栏的设置和说明页改掉……设置放到下面，说明去掉，
设置按了之后应该像 dsh 一样在中间浮出一个稍小一点的应用内窗口，背景虚化，
然后小窗内左边有设置的导航栏……主题色和说明也像 maaend 一样放进设置里，
说明可以在最下面留个打开的按钮」。

「vite build 不会报」的一类错，只能静态钉住：
* 设置/说明**不能**再出现在侧栏页面列表里（否则点进去还是一片空白页）；
* 侧栏底部要有设置入口，且浮层必须真正挂载；
* 浮层层级必须低于 DialogHost（z-50）—— 否则「还原游戏本体」的确认框被盖住，
  用户会以为按钮没反应；
* 4 个分类与「说明」入口都得存在（新手引导第 4 步会打开「维护」分类并高亮还原按钮）。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_nav_no_longer_has_settings_or_about_pages() -> None:
    app = _read("App.vue")
    assert 'id: "settings"' not in app, "侧栏里还有 settings 页签 —— 它已经不是页面了"
    assert 'id: "about"' not in app, "侧栏里还有 about 页签 —— 说明已经搬进设置浮窗"
    for page in ("服装 Mod", "辅助 Mod", "Mod 商城", "下载", "依赖", "启动"):
        assert page in app, f"侧栏少了「{page}」"


def test_sidebar_has_settings_entry_and_dialog_is_mounted() -> None:
    app = _read("App.vue")
    assert 'data-mc-id="settings:open"' in app, "侧栏底部没有设置入口（AI 自动化也靠这个 id）"
    assert 'id="settings-btn"' in app, "设置按钮没有稳定 id（焦点/回归要用）"
    assert "<SettingsDialog />" in app, "App.vue 没有挂载设置浮窗"
    assert 'import SettingsDialog from "./components/SettingsDialog.vue"' in app, (
        "SettingsDialog 没有 import —— Vue 会把它当未知元素，点了什么都不出"
    )


def test_store_keeps_six_pages_and_settings_state() -> None:
    store = _read("store.js")
    match = re.search(r"export const PAGE_IDS = \[([^\]]+)\]", store)
    assert match, "store.js 里找不到 PAGE_IDS"
    ids = [item.strip().strip('"') for item in match.group(1).split(",") if item.strip()]
    assert ids == ["library", "assist", "store", "downloads", "dependencies", "launch"], (
        f"页面列表应当收成 6 项（设置/说明不是页面），现在是 {ids}"
    )
    for key in ("settingsOpen", "settingsSection", "settingsMode"):
        assert key in store, f"store 里缺少浮窗状态 {key}"
    for fn in ("openSettings", "closeSettings", "showAbout", "backToSettings"):
        assert f"export function {fn}" in store, f"store 里缺少 {fn}()"


def test_dialog_has_four_sections_about_button_and_safe_z_index() -> None:
    dialog = _read("components/SettingsDialog.vue")
    assert "settings:section:" in dialog, "分类按钮没有 data-mc-id（自动化与回归都要靠它）"
    assert 'data-mc-id="settings:about"' in dialog, "浮窗底部没有「说明」入口"
    assert 'data-mc-id="settings:close"' in dialog, "浮窗没有关闭按钮"
    assert "backdrop-filter" in dialog and "blur(" in dialog, "背景没有虚化"
    assert re.search(r"z-index:\s*40\b", dialog), (
        "设置浮层的 z-index 必须是 40 —— 必须低于 DialogHost(z-50)，否则确认框会被盖住"
    )
    for section in ("general", "paths", "downloads", "maintenance"):
        assert f'id: "{section}"' in dialog, f"缺少分类 {section}"


def test_settings_panel_is_one_scrollable_page_with_anchors() -> None:
    """设置内容必须是**一页连续滚动**（左栏只做锚点），不再按标签切换。

    2026-11-28 用户明确：「设置页要能直接滑到底，不要还需要在标签那里切」。
    """
    page = _read("pages/SettingsPage.vue")
    for section in ("general", "appearance", "paths", "downloads",
                    "webserver", "maintenance", "debug", "about"):
        assert f'id="settings-section-{section}"' in page, (
            f"设置分组 {section} 没有锚点 id（左栏点击靠它滚动定位）"
        )
    assert "store.settingsSection ===" not in page, (
        "设置内容仍在按分类切换渲染 —— 应该是一页连续滚动、左栏只负责滚动定位"
    )
    assert 'id="game-restore-btn"' in page, "引导第 4 步的落点（还原游戏本体）不见了"
    assert "THEME_BASE_OPTIONS" in page and "THEME_ACCENT_OPTIONS" in page, "主题没有拆成底色+强调色"
    assert "changeThemeBase" in page and "changeThemeAccent" in page
    assert "setThemeAccent" in page, "强调色没有接到 store 的唯一入口"
    assert "强调色" in page and "界面" in page, "背景色与强调色没有分开选"
    # 语言切换（2026-11-28 用户要求英文版 + 设置页语言切换，默认中文）
    assert "LANG_OPTIONS" in page and "changeLang" in page
    assert "language:' + opt.value" in page, "语言按钮没有可识别的 data-mc-id"
    # 模板/formatResult 用了 humanSize，就必须真的 import（历史 bug：整张卡渲染失败）
    assert 'import { humanSize } from "../lib/util.js"' in page, "SettingsPage 没有 import humanSize"
    assert "humanSize(" in page, "humanSize 的调用点被删了？请同步更新这条回归"


def test_settings_has_the_maend_sections() -> None:
    """MaaEnd 那几项设置都要有：背景图 / 自动清理日志 / Web 服务 / 调试 / 关于。"""
    page = _read("pages/SettingsPage.vue")
    for keyword in ("背景图片", "背景不透明度", "自动清理运行日志", "保留天数",
                    "本机 Web 服务（UI 自动化 API）", "运行环境", "关于 终末地 Mod 管理器",
                    "许可与致谢"):
        assert keyword in page, f"设置里缺少「{keyword}」这一项"
    assert "ui_api_enabled" in page and "choose_background_image" in page, (
        "Web 服务/背景图没有接到后端接口上"
    )

def test_lite_hides_reshade_entries() -> None:
    page = _read("pages/SettingsPage.vue")
    assert "isLite" in page and 'edition) || "full"' in page, "SettingsPage 没有按 edition 分支"
    launch = _read("pages/LaunchPage.vue")
    assert "RESHADE_ONLY_SWITCHES" in launch and "visibleSwitches" in launch, (
        "启动页没有按 edition 过滤 ReShade 开关"
    )
    about = _read("pages/AboutPage.vue")
    assert "isLite" in about, "说明页没有按 edition 分支"
    assert "完整版与轻量版怎么切换" in about, "说明里缺少两版切换的说明"


def test_shell_no_longer_renders_theme_menu() -> None:
    app = _read("App.vue")
    for leftover in ("themeOpen", "themeLabel", "pickTheme", "THEME_LABELS"):
        assert leftover not in app, f"App.vue 里还有主题菜单残留：{leftover}（主题已搬进设置）"