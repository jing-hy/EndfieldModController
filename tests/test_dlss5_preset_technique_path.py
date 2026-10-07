"""DLSS5 preset 的 **technique 全名必须带 effect 相对路径**（2026-10-07 用户实测定案）。

**现场**：用户「注入进去了，但是 reshade 还是报错」「DLSS5 和第一人称没加载」。日志里
插件自己写着

    [feed] effects: DLSS5_Feed.fx technique found, ColorInput found, DLSS5_MV found ...
    [feed] motion-vector provider MartysMods_Launchpad is installed but DISABLED:
           enable it above DLSS 5 Feed.
    NR-VERDICT v3 state=UNAVAILABLE

而 preset 里明明写着 `MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx=1`。

**两个叠加的缺陷（都必须钉住）**：
1. technique 全名少了 effect 的目录 —— 那个 shader 在 `iMMERSE\\` 子目录里，
   ReShade 认的全名是 `MartysMods_Launchpad@iMMERSE\\MartysMods_LAUNCHPAD.fx`
   （`DLSS5_Feed.fx` 在根目录，所以它不带前缀是对的）；
2. `_merge_preset_line` 按 `@` 前面那段去重 ⇒ 旧的短名字被当作"已经存在"⇒
   **修了等于没修**（自检报 `fixed=True`、文件纹丝不动）。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import initialize
from endfieldmodcontroller.config import AppConfig

LAUNCHPAD_SHORT = "MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx"
LAUNCHPAD_FULL = "MartysMods_Launchpad@iMMERSE\\MartysMods_LAUNCHPAD.fx"
FEED = "DLSS5_Feed@DLSS5_Feed.fx"

BROKEN_PRESET = (
    "PreprocessorDefinitions=DLSS5_MV_PROVIDER=1\n"
    f"Techniques={LAUNCHPAD_SHORT}=1,{FEED}=1\n"
    f"TechniqueSorting={LAUNCHPAD_SHORT},{FEED}\n"
    "EffectSorting=MartysMods_LAUNCHPAD.fx,DLSS5_Feed.fx\n"
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """造一个最小可判的 DLSS5 环境：ReShade.ini + preset + `iMMERSE\\` 下的 provider shader。"""
    dlss5 = tmp_path / "dlss5"
    shaders = dlss5 / "reshade-shaders" / "Shaders"
    (shaders / "iMMERSE").mkdir(parents=True)
    (shaders / "iMMERSE" / "MartysMods_LAUNCHPAD.fx").write_text("// provider\n", encoding="utf-8")
    (shaders / "DLSS5_Feed.fx").write_text("// feed\n", encoding="utf-8")
    preset = dlss5 / "ReShadePreset.ini"
    preset.write_text(BROKEN_PRESET, encoding="utf-8")
    (dlss5 / "ReShade.ini").write_text(
        f"PresetPath={preset}\n", encoding="utf-8")

    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    monkeypatch.setattr(AppConfig, "dlss5_ini_path", property(lambda self: dlss5 / "ReShade.ini"))
    monkeypatch.setattr(AppConfig, "dlss5_addon_enabled", True, raising=False)
    return dlss5


def _lines(preset):
    return {line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in preset.read_text(encoding="utf-8").splitlines() if "=" in line}


def test_effect_relative_path_uses_real_location(env):
    """相对路径按磁盘实际位置算（provider 在 iMMERSE\\ 下）。"""
    shaders = env / "reshade-shaders" / "Shaders"
    assert initialize._effect_relative_path(shaders, "MartysMods_LAUNCHPAD.fx") == \
        "iMMERSE\\MartysMods_LAUNCHPAD.fx"
    assert initialize._effect_relative_path(shaders, "DLSS5_Feed.fx") == "DLSS5_Feed.fx"


def test_broken_short_name_is_recognised_and_replaced(env):
    """**核心**：无前缀的旧写法要被判成"需要修复"，并**真的**换成带路径的全名。

    这两条缺一不可 —— 只修判据不改合并逻辑，就是"报 fixed=True、文件没变"；
    只改合并逻辑不修判据，就是"永远不会去修"。
    """
    report = initialize.Report()
    initialize._check_dlss5_preset(AppConfig(), report, None)

    assert report.checks, "自检没有产出结论"
    assert report.checks[0]["fixed"] is True, "带错误路径的 technique 没被修"

    written = _lines(env / "ReShadePreset.ini")
    assert LAUNCHPAD_FULL in written["Techniques"], "没有写进 ReShade 真正认的全名"
    assert LAUNCHPAD_SHORT not in written["Techniques"], "旧的短名字还在（修了等于没修）"
    assert LAUNCHPAD_FULL in written["TechniqueSorting"], "排序表里的名字也要一起换"


def test_second_run_is_idempotent(env):
    """修完再跑必须**不再动它**（否则每轮一键启动都改一遍 preset）。"""
    first = initialize.Report()
    initialize._check_dlss5_preset(AppConfig(), first, None)
    after_first = (env / "ReShadePreset.ini").read_text(encoding="utf-8")

    second = initialize.Report()
    initialize._check_dlss5_preset(AppConfig(), second, None)

    assert second.checks[0]["ok"] is True
    assert second.checks[0]["fixed"] is not True, "第二次又修了一遍 —— 判据仍然认不出全名"
    assert (env / "ReShadePreset.ini").read_text(encoding="utf-8") == after_first


def test_mainline_preset_is_left_alone(env):
    """本来就是正确全名的 preset，不许被改（保留 ReShade 自己写的内容）。"""
    preset = env / "ReShadePreset.ini"
    good = BROKEN_PRESET.replace(LAUNCHPAD_SHORT, LAUNCHPAD_FULL)
    preset.write_text(good, encoding="utf-8")

    report = initialize.Report()
    initialize._check_dlss5_preset(AppConfig(), report, None)

    assert report.checks[0]["ok"] is True
    assert report.checks[0]["fixed"] is not True
    assert preset.read_text(encoding="utf-8") == good
