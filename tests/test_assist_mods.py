"""「辅助 mod」通道的测试（2026-10-01 用户要求④：自动识别 + 手动标记 + 独立页签）。

背景：用户问「这种辅助 mod 要怎么塞进去，能不能在 mod 管理器中增加一个辅助 mod 页，
给这种非皮肤小 mod 留加载通道」。典型样本 = 群友包里的 **Hide UI＆UID**（`alt 1` 隐藏
UI/UID），它只有 `.ini + .json + .bitmap`，ini 全是 `[TextureOverride_*] + handling = skip`。

要守住的性质：
* **自动识别**：没有换装资源 + 跳过绘制型/关键词 + **归不到任何角色** → `kind == "assist"`；
* **不误伤**：「去面具 / 去圆环」这类"去掉某个部件"的 Mod 结构与隐藏 UI **一模一样**，
  但它们能归到角色 → 必须仍是 `character`（留在角色库、参与同角色互斥）；
* **不互斥**：辅助 mod 之间、以及辅助 mod 与角色 mod 之间都不互相挤掉；
* **不打扰**：辅助 mod 的 `char_confidence == "high"`（不会被要求"确认角色归属"）。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import activation, core

# 典型的"隐藏 UI/UID"型：没有资源，只有跳过绘制 + 一个开关变量
SKIP_INI = """
[Constants]
global $hide_UI = 1
[TextureOverride_UID]
hash = bc9b5f4c
match_first_index = 18
match_index_count = 126
handling = skip
[KeyHideUI]
key = alt 1
type = cycle
$hide_UI = 0,1
"""

# 典型的换装型：带 Textures 资源
SKIN_INI = """
[TextureOverride_Body]
hash = 1234abcd
[ResourceBodyTexture]
filename = Textures/body.dds
[KeySwap0]
key = no_modifiers VK_1
run = CommandListSwap
"""


def _make_mod(root: Path, name: str, ini: str, *, textures: bool = False) -> Path:
    target = root / name
    target.mkdir(parents=True)
    (target / f"{name}.ini").write_text(ini, encoding="utf-8")
    if textures:
        (target / "Textures").mkdir()
        (target / "Textures" / "body.dds").write_bytes(b"DDS ")
    return target


# --------------------------------------------------------------- 判据
def test_ui_hider_is_assist(tmp_path):
    mod = _make_mod(tmp_path, "Hide UI＆UID", SKIP_INI)
    assert core.has_mod_resources(mod) is False
    assert core.looks_like_assist(mod, ["Hide UI＆UID"], {}) is True


def test_part_removal_with_character_is_not_assist(tmp_path):
    """「去面具 / 去圆环」也得算角色 Mod —— 结构与隐藏 UI 一样，但它归得到角色。"""
    mod = _make_mod(tmp_path, "莱万汀去除背后圆环", SKIP_INI)
    assert core.looks_like_assist(mod, ["莱万汀去除背后圆环"], {}, character="莱万汀") is False
    kind, group = core.infer_kind_and_group(["莱万汀去除背后圆环"], {}, mod)
    assert (kind, group) == ("character", "莱万汀")


def test_skin_mod_with_resources_is_never_assist(tmp_path):
    mod = _make_mod(tmp_path, "隐藏UI皮肤", SKIN_INI, textures=True)
    assert core.has_mod_resources(mod) is True
    assert core.looks_like_assist(mod, ["隐藏UI皮肤"], {}) is False


def test_explicit_meta_kind_wins(tmp_path):
    """用户手动标记（mod.meta.json 写 kind）优先于自动识别。"""
    mod = _make_mod(tmp_path, "Hide UI＆UID", SKIP_INI)
    assert core.infer_kind_and_group(["Hide UI＆UID"], {"kind": "character"}, mod)[0] == "character"
    skin = _make_mod(tmp_path / "x", "某皮肤", SKIN_INI, textures=True)
    assert core.infer_kind_and_group(["某皮肤"], {"kind": "assist"}, skin)[0] == "assist"


# --------------------------------------------------------------- 扫描 + 互斥
def test_scan_classifies_assist_and_keeps_parts_mods_as_characters(tmp_path):
    library = tmp_path / "library"
    _make_mod(library, "Hide UI＆UID", SKIP_INI)
    _make_mod(library, "莱万汀去除背后圆环", SKIP_INI)
    _make_mod(library, "莱万汀泳装", SKIN_INI, textures=True)

    mods = {m.name: m for m in core.scan_library(library, tmp_path / "staging")}
    assert mods["Hide UI＆UID"].kind == "assist"
    assert mods["Hide UI＆UID"].char_confidence == "high", "辅助 mod 不该被要求确认角色"
    assert mods["莱万汀去除背后圆环"].kind == "character"
    assert mods["莱万汀泳装"].kind == "character"


def test_assist_mods_never_conflict(tmp_path):
    """两个辅助 mod 之间、辅助与角色 mod 之间都不互相挤掉。"""
    library = tmp_path / "library"
    _make_mod(library, "Hide UI＆UID", SKIP_INI)
    _make_mod(library, "辅助-隐藏水印", SKIP_INI)
    _make_mod(library, "莱万汀泳装", SKIN_INI, textures=True)

    mods = core.scan_library(library, tmp_path / "staging")
    active, report = activation.resolve_active_set(mods, [m.id for m in mods])
    names = {m.name for m in active}
    assert names == {"Hide UI＆UID", "辅助-隐藏水印", "莱万汀泳装"}, f"不该有东西被挤掉: {report.dropped}"
    assert not report.dropped


def test_two_skin_of_same_character_still_conflict(tmp_path):
    """对照组：同角色两个皮肤仍然互斥（辅助通道没有放松这条）。"""
    library = tmp_path / "library"
    _make_mod(library, "莱万汀泳装", SKIN_INI, textures=True)
    _make_mod(library, "莱万汀内衣", SKIN_INI, textures=True)

    mods = core.scan_library(library, tmp_path / "staging")
    active, report = activation.resolve_active_set(mods, [m.id for m in mods])
    assert len(active) == 1 and len(report.dropped) == 1
