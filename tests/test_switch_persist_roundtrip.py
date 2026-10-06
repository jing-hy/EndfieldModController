"""开关"关掉之后过一会又自己打开"（2026-10-06 用户反馈）。

**机制**：前端 `toggleSwitch()` 是「**乐观更新 + 后台刷新**」——
它先按点击把界面画好，再 `refreshState() + loadSettings()` 整份重灌；
判断"后端到底存了什么"的**唯一依据**是返回值里的 `config`
（`persisted = !!(r && r.config && sw.k in r.config)`）。

⚠️ `set_component_addon()` 以前**不回传 `config`** ⇒ 前端只能信自己记的值 ⇒
后台刷新一旦读到旧值，界面就被弹回原样 = 用户说的「关了，过一会又开了」。
`set_minimal_injection()` 一直是回传的，所以那个开关没有这个毛病。

这几条钉住：**凡是改动插件开关的入口，都必须回传落盘后的配置**（含互斥时一起改掉的键）。
"""
from __future__ import annotations

import inspect

import pytest

from endfieldmodcontroller import api as apimod

CLS = next(o for _n, o in vars(apimod).items()
           if inspect.isclass(o) and hasattr(o, "get_state"))

SWITCH_KEYS = {"dlss5_addon_enabled", "firstperson_addon_enabled", "mfg_unlock_enabled"}


@pytest.fixture(scope="module")
def inst():
    return CLS()


def test_set_component_addon_returns_persisted_config(inst):
    """★ 返回值里必须有 `config`，且含本次改的那个键 —— 否则前端只能靠猜。"""
    for component, key in (("dlss5", "dlss5_addon_enabled"),
                           ("firstperson", "firstperson_addon_enabled")):
        result = inst.set_component_addon(component, True)
        assert "config" in result, f"{component} 的返回值没有 config ⇒ 前端会弹回"
        assert key in result["config"], f"{component} 的 config 里缺 {key}"
        assert result["config"][key] is True
        result = inst.set_component_addon(component, False)
        assert result["config"][key] is False, (
            f"{component} 关掉后回传的仍是 {result['config'][key]!r} ⇒ 界面会弹回"
        )


def test_returned_config_covers_every_switch_key(inst):
    """★ 三个键都要在 —— 互斥时另一个键会被一起改掉，前端要能同步显示。"""
    result = inst.set_component_addon("dlss5", True)
    missing = SWITCH_KEYS - set(result.get("config") or {})
    assert not missing, f"回传的 config 缺这些键 ⇒ 互斥后的界面不同步：{missing}"


def test_frontend_reads_the_returned_config():
    """★ 前端确实按 `sw.k in r.config` 判断"后端存了什么"（这条链路别被改掉）。"""
    page = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "frontend" / "src" / "pages" / "LaunchPage.vue")
    text = page.read_text(encoding="utf-8")
    assert "sw.k in r.config" in text, (
        "前端判断 persisted 的判据变了 —— 后端回传 config 的约定要一起复核"
    )
