# -*- coding: utf-8 -*-
"""初始化时把第一人称插件的界面语言配成中文 —— 回归测试。

用户要求：「我进去之后发现第一人称 mod 有个开关，跳了之后才能把语言变成中文，
你看一下配置在哪里，我要初始化的时候就配置成中文」。

数值映射由**用户手动切换后的文件**定案：`[endfield-enhancer] Language` 的
**1 = 中文、2 = 英文**（详见 initialize.py 里常量上方的证据链注释）。
"""
from endfieldmodcontroller.initialize import (
    FIRSTPERSON_LANGUAGE_EN,
    FIRSTPERSON_LANGUAGE_ZH,
    _ensure_chinese_language,
    _set_ini_key,
)

SAMPLE = "\r\n".join([
    "[endfield-enhancer]",
    "CameraFirstPerson=0",
    f"Language={FIRSTPERSON_LANGUAGE_EN}",
    "NPCCameraCulling=0",
    "",
    "[GENERAL]",
    r"EffectSearchPaths=D:\x\**",
    "",
    "[OVERLAY]",
    "AutoSavePreset=1",
    "Language=",
    "ShowClock=0",
    "",
])


def _lines(text: str) -> list[str]:
    return [line.rstrip("\r") for line in text.split("\n")]


def test_sets_firstperson_language_to_chinese() -> None:
    text, changed = _ensure_chinese_language(SAMPLE)
    assert changed is True
    lines = _lines(text)
    assert f"Language={FIRSTPERSON_LANGUAGE_ZH}" in lines
    # 中文值必须落在 [endfield-enhancer] 段内
    assert lines.index(f"Language={FIRSTPERSON_LANGUAGE_ZH}") < lines.index("[GENERAL]")


def test_does_not_touch_overlay_language() -> None:
    """ReShade 面板语言不是我们该动的东西（中文只需要 enhancer 那一个键）。"""
    text, _ = _ensure_chinese_language(SAMPLE)
    lines = _lines(text)
    assert lines[lines.index("[OVERLAY]") + 2] == "Language="   # 仍是空值，没被写成 zh-CN
    assert "Language=zh-CN" not in lines


def test_untouched_keys_and_sections_survive() -> None:
    text, _ = _ensure_chinese_language(SAMPLE)
    lines = _lines(text)
    for keep in ("[endfield-enhancer]", "CameraFirstPerson=0", "NPCCameraCulling=0",
                 "[GENERAL]", r"EffectSearchPaths=D:\x\**",
                 "[OVERLAY]", "AutoSavePreset=1", "ShowClock=0"):
        assert keep in lines, keep


def test_idempotent() -> None:
    once, changed = _ensure_chinese_language(SAMPLE)
    assert changed is True
    twice, changed_again = _ensure_chinese_language(once)
    assert changed_again is False
    assert twice == once          # 无改动时原样返回（不写盘）


def test_missing_section_is_appended() -> None:
    text, changed = _set_ini_key("[GENERAL]\nA=1\n", "OVERLAY", "Language", "zh-CN")
    assert changed is True
    lines = _lines(text)
    assert "[OVERLAY]" in lines
    assert "Language=zh-CN" in lines
    assert lines.index("Language=zh-CN") > lines.index("[OVERLAY]")
    assert "A=1" in lines


def test_key_only_touched_inside_target_section() -> None:
    """两个段都有 Language：改 enhancer 的不能碰到 OVERLAY 里那个。"""
    text, changed = _set_ini_key(SAMPLE, "endfield-enhancer", "Language", "1")
    assert changed is True
    lines = _lines(text)
    assert lines.count("Language=1") == 1
    assert lines.count("Language=") == 1        # OVERLAY 段仍是空


def test_key_inserted_when_absent_in_existing_section() -> None:
    sample = "[endfield-enhancer]\nCameraFirstPerson=0\n"
    text, changed = _set_ini_key(sample, "endfield-enhancer", "Language", "1")
    assert changed is True
    lines = _lines(text)
    assert lines[1] == "Language=1"
    assert lines[2] == "CameraFirstPerson=0"
