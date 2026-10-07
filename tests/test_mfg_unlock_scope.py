"""「DLSS4 多帧生成」在本作上不可用 —— 用户选项 B：默认禁用 + 写明原因（2026-10-07）。

**为什么禁**（三条互相印证，见 `deviceinfo.MFG_UNLOCK_DISABLED_FOR_THIS_GAME` 的注释）：
  ① 终末地只有 DX11 启动模式（没有 DX12 模式）；
  ② 游戏内没有调倍率的接口 ⇒ 游戏从不提交帧生成请求；
  ③ addon 侧实测完全就绪，而 ReShade 日志里一次 `Game request observed` 都没有。
⇒ 开关"看起来能用、实际永远没效果"，正是最该避免的形态（用户：「那些滑块要真的有用，
  不要就做表面功夫」）⇒ 默认禁用并把原因写在界面上。

⚠️ 本文件同时**钉住"复活路径没腐烂"**：把常量翻回 False，原来那套按显卡的判据必须照旧可用。
"""
from __future__ import annotations

import pathlib

from endfieldmodcontroller import deviceinfo


def test_disabled_by_default_with_reason():
    """★ 默认必须判"不可用"，且给出一句能读懂的原因。"""
    ok, reason = deviceinfo.mfg_unlock_supported()
    assert ok is False, "本作上不该判可用"
    assert reason, "必须给出原因（界面那行靠它显示）"
    assert "帧生成" in reason, f"原因要说到点上：{reason!r}"


def test_reason_says_it_is_the_game_not_us():
    """★ 原因要讲清"是游戏不提供"，别让用户以为是我们/驱动坏了。"""
    _ok, reason = deviceinfo.mfg_unlock_supported()
    assert ("游戏" in reason) or ("本作" in reason), f"没说清责任方：{reason!r}"


def test_api_passes_it_through():
    """★ `api._mfg_available()` 必须透传（前端 `locked()` 读的就是它）。"""
    from endfieldmodcontroller import api as api_module

    ok, reason = api_module._mfg_available()
    assert ok is False and reason, (ok, reason)


def test_revival_path_still_works(monkeypatch):
    """★★ 复活路径不许腐烂：常量翻回 False，按显卡的判据照旧生效。

    50 系（sm_120）⇒ 可用（"提升不大"那句）；40 系（sm_89）⇒ 可用（"能提到 3x/4x"）。
    这里打桩 `rtx_cards`/`collect`，不碰真实设备。
    """
    monkeypatch.setattr(deviceinfo, "MFG_UNLOCK_DISABLED_FOR_THIS_GAME", False, raising=False)
    monkeypatch.setattr(deviceinfo, "collect", lambda refresh=False: {"adapters": ["fake"]})

    monkeypatch.setattr(deviceinfo, "rtx_cards", lambda adapters: [("RTX 5080", 120)])
    ok, reason = deviceinfo.mfg_unlock_supported()
    assert ok is True and "50 系" in reason, (ok, reason)

    monkeypatch.setattr(deviceinfo, "rtx_cards", lambda adapters: [("RTX 4070", 89)])
    ok, reason = deviceinfo.mfg_unlock_supported()
    assert ok is True and "40 系" in reason, (ok, reason)

    monkeypatch.setattr(deviceinfo, "rtx_cards", lambda adapters: [("RTX 3060", 86)])
    ok, reason = deviceinfo.mfg_unlock_supported()
    assert ok is False and "3060" not in reason, (ok, reason)


def test_reason_text_does_not_blame_the_user():
    """★ 文案口吻：不出现"你/您"，也别让人以为要自己动手改什么。"""
    _ok, reason = deviceinfo.mfg_unlock_supported()
    for bad in ("你", "您", "请自行", "手动改"):
        assert bad not in reason, f"文案里有 '{bad}'：{reason!r}"


def test_disabled_flag_is_documented():
    """★ 常量旁边必须写清"为什么禁"与"怎么复活"（否则下一个人只能猜）。"""
    src = pathlib.Path(deviceinfo.__file__).read_text(encoding="utf-8")
    head = src[: src.index("def mfg_unlock_supported")]
    assert "MFG_UNLOCK_DISABLED_FOR_THIS_GAME" in head
    assert "复活" in head or "False" in head, "没写怎么恢复"
    assert "Game request observed" in head, "没写关键证据（addon 没收到请求）"
