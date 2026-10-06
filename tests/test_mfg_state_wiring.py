"""链路测试：DLSS4 可用性字段必须落在**前端真正会读的那一层**（2026-10-06）。

**现场**：40 系用户反馈「**40 系也开不了 dlss4 的按钮**」——那一行对所有人都灰。

**链路**（读代码确认）：
  * `store.state = get_state()`（原样存）；
  * `loadSettings()` 把 **`store.state.config`** 灌进 `settings`；
  * `get_state()["config"] = self.config.to_dict()` ⇒ **只装 AppConfig 的配置字段**。
⇒ 我第一版把 `mfg_unlock_available` 加进了 `component_addon_status()["config"]`（**另一个 dict**），
  前端却用 `settings.mfg_unlock_available` 去读 ⇒ 恒为 `undefined` ⇒ `locked()` 恒真 ⇒ 全灰。
**本机是 RTX 5080（50 系）本来就该灰，所以表现一样、把这个 bug 掩盖了** ——
这类"只对特定硬件显形"的判据，只能靠测试钉住落点。
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from endfieldmodcontroller import api

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCH_PAGE = ROOT / "frontend" / "src" / "pages" / "LaunchPage.vue"


def test_get_state_really_exposes_the_field() -> None:
    """★★ **真调 `get_state()`**，确认字段真的在前端唯一能读到的那一层。

    ⚠️ **为什么必须真调、不能看源码**：2026-10-06 我连着改错两次 ——
    字段加进了 `api.component_addon_status()`（一个**同名但前端不读**的方法），
    而前端读的是 `get_state()` 里**另一个**名叫 `component_addon_status` 的字典
    （那里以前是**硬编码两个键**的）⇒ 那一行对 40 系**仍然是灰的**，
    而"看源码"的测试居然是通过的。**字段落在哪一层，只有真实调用能证明。**
    """
    inst = api.EndfieldModControllerApi()
    state = inst.get_state()
    config = (state.get("component_addon_status") or {}).get("config")
    assert isinstance(config, dict), "get_state 里没有 component_addon_status.config"
    assert "mfg_unlock_available" in config, (
        "字段不在 get_state() 的 component_addon_status.config 里 ⇒ "
        "前端读不到 ⇒ 那一行永远灰（40 系也打不开）"
    )
    assert "mfg_unlock_reason" in config


def test_frontend_reads_from_the_same_place() -> None:
    """★ 前端：必须从 `store.state.component_addon_status.config` 读，**不能**用 `settings`。"""
    lines = LAUNCH_PAGE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines, 1) if "mfg_unlock_enabled" in line)
    # 只看**代码行**：注释里会把 `settings.mfg_unlock_available` 当反面例子写着，不能算数
    body = "\n".join(
        line for line in lines[start - 1:start + 9]
        if not line.strip().startswith("//")
    )
    assert "component_addon_status" in body, (
        "前端没从 component_addon_status 读可用性 ⇒ 会恒为 undefined ⇒ 那一行永远灰"
    )
    assert "settings.mfg_unlock_available" not in body, (
        "又用 settings 读了 —— settings 只装 AppConfig 的字段，这里读不到"
    )


def test_api_helper_is_safe_on_any_machine(monkeypatch) -> None:
    """判据探不到设备时**不许抛**，按"不能用"处理（这是可选增强，宁可不开）。"""
    from endfieldmodcontroller import deviceinfo

    def boom(refresh=False):        # noqa: ARG001
        raise RuntimeError("探测炸了")

    monkeypatch.setattr(deviceinfo, "mfg_unlock_supported", boom)
    ok, reason = api._mfg_available()
    assert ok is False
    assert reason
