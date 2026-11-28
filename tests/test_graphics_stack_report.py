# SPDX-License-Identifier: AGPL-3.0-only
r"""诊断包里的「图形栈事实」采集（2026-11-28 加）。

触发场景：一台机器崩溃栈固定落在 `nvoglv64!vk_gr2608GetInstanceProcAddr`
→ `NvPresent64!NVP_Init_Vulkan` → `vulkan-1!vkResetEvent`，而游戏是 `-force-d3d11`
（走 EFMI 必定 DX11）。判"是显卡驱动问题还是我们的文件问题"要三样数据，
以前包里一样都没有，只能反复问用户。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import diagnostics


def test_graphics_stack_lists_modules_and_compares_with_original(tmp_path: Path, monkeypatch) -> None:
    game = tmp_path / "game"
    game.mkdir()
    # 一台"被顶替"的机器：vulkan-1.dll 是 1,730,096（System32 版），不是游戏原版 831,488
    (game / "vulkan-1.dll").write_bytes(b"\0" * 1024)
    (game / "d3dcompiler_47.dll").write_bytes(b"\0" * 2048)
    monkeypatch.setattr(diagnostics, "_running_process_modules", lambda images, limit=40: [])
    from endfieldmodcontroller import reshade_integration

    monkeypatch.setattr(reshade_integration, "detect_game_dir", lambda config, **kw: game)

    lines = diagnostics.graphics_stack_report(object())
    text = "\n".join(lines)
    assert "d3dcompiler_47.dll" in text and "vulkan-1.dll" in text
    assert "游戏原版" in text, text
    # 这两个文件都不是游戏原版大小 ⇒ 必须标出来
    assert "与游戏原版不同" in text, text
    # 驱动侧那几项也要在（哪怕本机没装 NVIDIA，也得留一条"没找到"）
    assert "NvPresent64.dll" in text and "nvoglv64.dll" in text