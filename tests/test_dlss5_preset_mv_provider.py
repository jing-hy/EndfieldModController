"""DLSS5 preset 的「运动矢量来源」判据（2026-10-06 从两份 40 系对照包定案）。

**事实链**：
* 两机 `dlss5-feed.log` 只差一处：
  能开 = `DLSS5_MV_PROVIDER=1 (Launchpad) -> MartysMods_Launchpad`；
  开不了 = `DLSS5_MV_PROVIDER=0 (texMotionVectors) -> none (not installed)`
  ⇒ `motion vectors will be zero (still images only)` ⇒ NGX 建不出 feature ⇒ `0xBAD00007`。
* `DLSS5_MV_PROVIDER=1` 是**编译预处理宏**，实测**只有写在 preset 里才生效**
  （`ReShade.ini` 的 `[GENERAL] PreprocessorDefinitions` 两边都写着，feed 仍按 0 编译）。
* 我们会增补这行，但会被 **ReShade 回写 preset** 抹掉（`AutoSavePreset=1`）。

要守住两条：
① 判据必须**单独检查**这一行 —— 光查 `Techniques` 是查不出它的（删掉这行，Techniques 照样完好）；
② 生成的 `ReShade.ini` 里 **`AutoSavePreset` 必须是 0**，否则增补的内容会被回写抹掉。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from endfieldmodcontroller import initialize as ini

GOOD_PRESET = """PreprocessorDefinitions=DLSS5_MV_PROVIDER=1
Techniques=MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx,DLSS5_Feed@DLSS5_Feed.fx
TechniqueSorting=MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx,DLSS5_Feed@DLSS5_Feed.fx
EffectSorting=MartysMods_LAUNCHPAD.fx,DLSS5_Feed.fx
"""

# 那位开不了的现场：Techniques 空、也没有 PreprocessorDefinitions 行
BAD_PRESET = """Techniques=
TechniqueSorting=DLSS5_Feed@DLSS5_Feed.fx,MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx

[DLSS5_Feed.fx]
DEBUG_VIEW=0
"""

# 更隐蔽的一种：Techniques 完好，但 `PreprocessorDefinitions` 被抹掉（回写的典型结果）
SUBTLY_BROKEN = """Techniques=MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx,DLSS5_Feed@DLSS5_Feed.fx
TechniqueSorting=MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx,DLSS5_Feed@DLSS5_Feed.fx
EffectSorting=MartysMods_LAUNCHPAD.fx,DLSS5_Feed.fx
"""


def _line(body: str, key: str) -> str:
    for line in body.splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1]
    return ""


def _mv_ok(body: str) -> bool:
    want = f"DLSS5_MV_PROVIDER={ini.DLSS5_MV_PROVIDER_LAUNCHPAD}"
    return want in _line(body, "PreprocessorDefinitions").replace(" ", "")


@pytest.mark.parametrize("body,expected", [
    (GOOD_PRESET, True),
    (BAD_PRESET, False),
    (SUBTLY_BROKEN, False),          # ★ 这条用旧判据查不出来
])
def test_mv_provider_judgement(body: str, expected: bool) -> None:
    """★ `DLSS5_MV_PROVIDER=1` 必须在 preset 里 —— 单独判，不能靠 `Techniques` 代偿。"""
    assert _mv_ok(body) is expected


def test_techniques_alone_cannot_detect_the_subtle_case() -> None:
    """★ 说明"为什么必须单独加这条判据"：`Techniques` 两项在、而 MV 行没了。"""
    launchpad, feed = ini.DLSS5_PRESET_TECHNIQUES
    tech = _line(SUBTLY_BROKEN, "Techniques")
    assert launchpad in tech and feed in tech, "这正是那条隐蔽的坏状态"
    assert _mv_ok(SUBTLY_BROKEN) is False, "它必须被判出来"


def test_autosave_preset_is_disabled_in_template() -> None:
    """★ 生成的 `ReShade.ini` 里 `AutoSavePreset` 必须是 0（否则回写会抹掉我们增补的行）。"""
    src = pathlib.Path(ini.__file__).read_text(encoding="utf-8")
    hits = re.findall(r'"AutoSavePreset=(\d)\\n"', src)
    assert hits, "模板里找不到 AutoSavePreset"
    assert set(hits) == {"0"}, (
        f"AutoSavePreset 必须是 0（现在是 {hits}）—— 否则 ReShade 退出时会把 preset 回写、"
        "抹掉 DLSS5_MV_PROVIDER=1，用户下次玩就是「成功NR帧 0」"
    )
