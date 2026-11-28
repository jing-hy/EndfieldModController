# SPDX-License-Identifier: AGPL-3.0-only
r"""钉住 2026-11-28 的「驱动层 Vulkan 崩溃」归因。

现场（诊断包 diagnostics-20261128-225854，三次崩溃栈一字不差）：

    nvoglv64!vk_gr2608GetInstanceProcAddr
    NvPresent64!NVP_Init_Vulkan
    vulkan-1!vkResetEvent  →  unityplayer → 0xC0000005

游戏是 `-force-d3d11` 起来的（走 EFMI 必定 DX11），正常不该出现 Vulkan 初始化；
而 WER 把故障模块记成 `unityplayer.dll`，按模块名的旧判据完全不命中，弹窗给不出任何建议。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import crashwatch
from endfieldmodcontroller.config import AppConfig


CRASH_STACK = """
0x00007FFC98D2BFA0 (nvoglv64) vk_gr2608GetInstanceProcAddr
0x00007FFC761840D0 (NvPresent64) NVP_Init_Vulkan
0x00007FFCC6ED0F45 (vulkan-1) vkResetEvent
0x00007FFC76C1A1CE (unityplayer) (function-name not available)
"""


def _fake_crash_root(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "Crashes"
    sub = root / "Crash_2026-11-28_145553891"
    sub.mkdir(parents=True)
    (sub / "Player.log").write_text(body, encoding="utf-8")
    return root


def test_gpu_driver_vulkan_crash_detected(tmp_path: Path, monkeypatch) -> None:
    root = _fake_crash_root(tmp_path, CRASH_STACK)
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: root)
    monkeypatch.setattr("endfieldmodcontroller.diagnostics.player_log_candidates",
                        lambda limit=4: [])
    cfg = AppConfig()
    hint = crashwatch.gpu_driver_vulkan_crash(cfg)
    assert "nvoglv64" in hint and "NVP_Init_Vulkan" in hint, hint


def test_normal_player_log_is_not_driver_crash(tmp_path: Path, monkeypatch) -> None:
    root = _fake_crash_root(tmp_path, "Forcing GfxDevice: Direct3D 11\nGfxDevice: creating device client\n")
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: root)
    monkeypatch.setattr("endfieldmodcontroller.diagnostics.player_log_candidates",
                        lambda limit=4: [])
    assert crashwatch.gpu_driver_vulkan_crash(AppConfig()) == ""


def test_crash_advice_does_not_suggest_reinstall_for_driver_crash(monkeypatch) -> None:
    """驱动层崩溃**不许**给"清空依赖并重新下载"那种动作 —— 重装治不了驱动。"""
    monkeypatch.setattr(crashwatch, "is_crash", lambda evidence: True)
    monkeypatch.setattr(crashwatch, "gpu_driver_vulkan_crash",
                        lambda config: "崩溃栈命中 nvoglv64 / NVP_Init_Vulkan")
    advice = crashwatch.crash_advice(AppConfig(), {})
    assert advice.get("kind") == "gpu_driver_vulkan"
    assert advice.get("action") == ""
    text = str(advice.get("message") or "")
    assert "NVIDIA App" in text and "驱动" in text