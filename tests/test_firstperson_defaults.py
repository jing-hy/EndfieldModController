"""第一人称默认项要写进 **ReShade 实际读的那份 ini**。

2026-10-03 用户反馈「第一人称视角不会自动配置」：`core.py` 给游戏进程设了
`RESHADE_BASE_PATH_OVERRIDE` = `runtime\\reshade`，ReShade 读的是**那一份**
`ReShade.ini`；而初始化只维护 `dlss5\\ReShade.ini`。于是 addon 首次运行把**出厂值
（全 0）**写进生效的那份后，`CameraEFMICompatibility` / `ShortcutFirstPerson` 等
在生效文件里全是 0 —— 表现为"面板里点按钮也没反应"。

`launcher._sync_enhancer_section` 负责把关键项从源同步到目标，这里钉住它。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import launcher

SOURCE = """[endfield-enhancer]
CameraEFMICompatibility=1
CameraFirstPersonDialogue=1
CameraFirstPersonMovement=0
Language=1
ShortcutFirstPerson=112
Uncensor=0

[OVERLAY]
Window=
"""

TARGET = """[endfield-enhancer]
CameraEFMICompatibility=0
CameraFirstPersonDialogue=0
CameraFirstPersonMovement=0
Language=1
ShortcutFirstPerson=0
Uncensor=0

[OVERLAY]
Window=
"""


def _v(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return "<missing>"


def test_syncs_only_the_keys_that_differ(tmp_path):
    src = tmp_path / "src.ini"
    dst = tmp_path / "dst.ini"
    src.write_text(SOURCE, encoding="utf-8")
    dst.write_text(TARGET, encoding="utf-8")

    # CameraEFMICompatibility / CameraFirstPersonDialogue / ShortcutFirstPerson 三项不同
    assert launcher._sync_enhancer_section(src, dst) == 3
    assert _v(dst, "CameraEFMICompatibility") == "1"
    assert _v(dst, "CameraFirstPersonDialogue") == "1"
    assert _v(dst, "ShortcutFirstPerson") == "112"
    # 源里本来就是 0、目标也是 0 的项不该被动；也不该越界改别的段
    assert _v(dst, "Uncensor") == "0"


def test_no_change_is_reported_as_zero(tmp_path):
    src = tmp_path / "src.ini"
    dst = tmp_path / "dst.ini"
    src.write_text(SOURCE, encoding="utf-8")
    dst.write_text(SOURCE, encoding="utf-8")
    assert launcher._sync_enhancer_section(src, dst) == 0


def test_missing_files_are_ignored(tmp_path):
    """任何一份不存在都不该抛异常（首次运行时那份 ini 可能还没生成）。"""
    existing = tmp_path / "a.ini"
    existing.write_text(SOURCE, encoding="utf-8")
    assert launcher._sync_enhancer_section(existing, tmp_path / "nope.ini") == 0
    assert launcher._sync_enhancer_section(tmp_path / "nope.ini", existing) == 0
