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


def test_availability_lives_in_component_addon_status_config() -> None:
    """★ 后端：可用性字段必须在 `component_addon_status()` 的 `config` 里（前端从那里读）。"""
    source = inspect.getsource(api.EndfieldModControllerApi.component_addon_status)
    assert "mfg_unlock_available" in source, "字段不在 component_addon_status 里"
    assert "mfg_unlock_reason" in source
    # 反例：它**不该**被塞进 `get_state()["config"]`（那是 AppConfig.to_dict()，会污染配置）
    state_source = inspect.getsource(api.EndfieldModControllerApi.get_state)
    assert '"config": self.config.to_dict()' in state_source, "get_state 的 config 来源变了，需复核本测试"


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
