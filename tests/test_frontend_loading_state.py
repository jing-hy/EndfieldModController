"""「还没读到」不许显示成「库里没有」：首屏与 Mod 库页必须给加载态。

用户 2026-10-07 原话：「**我要一进去就能出，要是要等待，就显示加载页面**」。

现场问题：窗口一出现就渲染了侧栏与页面骨架，而 Mod 列表要等**第一次 `get_state()`
回来**才有（首次启动要扫库 + 逐个 Mod 补"修复/可回滚"状态，实测本机首次 0.8 秒、
大库更久）。在那之前 `ModLibraryPage` 显示的是空态「还没有发现 Mod」——
用户读成"库是空的 / 界面坏了"，过一会儿列表又自己冒出来。

判据（静态钉住，构建不会替我们报错）：
* `App.vue` 有覆盖整块界面的首屏加载层，判据是 `store.ready`；
* 而且**有兜底**：12 秒还没就绪就给出「先进界面」（桥/后端出问题时不许把人锁在加载页）；
* 两个列表页（服装 Mod / 辅助 Mod）在 `store.ready` 之前显示"正在读取"，**不是**空态；
* 「已发现 N 个 Mod」这类计数在状态没到之前**不许显示 0**（0 会被读成"库是空的"）。
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_app_has_a_boot_overlay_gated_on_store_ready():
    text = _read("App.vue")
    assert 'v-if="!store.ready"' in text, "App.vue 里没有以 store.ready 为判据的首屏加载层"
    assert "正在读取 Mod 库与配置" in text, "加载层上没写清在读什么"
    # 兜底：不许把人永久锁在加载页上
    assert "bootStuck" in text and "先进界面" in text, "加载层没有超时兜底（桥坏了就进不去界面）"
    assert "12000" in text and "bootStuck.value = true" in text, "加载层的兜底计时器不见了"


def test_mod_library_page_shows_loading_instead_of_empty_state():
    text = _read("pages/ModLibraryPage.vue")
    assert 'v-if="!store.ready"' in text, "服装 Mod 页没有『还没读到』的分支"
    assert "正在读取 Mod 库" in text
    # 空态必须退成"另一个分支"，不能与加载态并列（否则两个会同时命中）
    assert 'v-else-if="!groups.length"' in text, "空态没有退成 v-else-if，会与加载态同时显示"
    first_ready = text.index('v-if="!store.ready"')
    first_empty = text.index('v-else-if="!groups.length"')
    assert first_ready < first_empty, "加载态必须排在空态之前"


def test_mod_library_page_hides_the_zero_count_before_state():
    text = _read("pages/ModLibraryPage.vue")
    assert "v-else>正在读取 Mod 库…</template>" in text, (
        "状态没到之前仍会显示『已发现 0 个 Mod』—— 0 会被读成『库是空的』"
    )


def test_assist_page_shows_loading_instead_of_empty_state():
    text = _read("pages/AssistPage.vue")
    assert 'v-if="!store.ready"' in text, "辅助 Mod 页没有『还没读到』的分支"
    assert "正在读取 Mod 库" in text
    assert 'v-else-if="!list.length"' in text, "空态没有退成 v-else-if"
