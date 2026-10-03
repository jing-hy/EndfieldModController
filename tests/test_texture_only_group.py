"""钉住「贴图替换类」判据 —— 2026-10-03 用户要求的一个新分类。

**用户原话**（针对库里的「弭弗饮料罐690308」）：
「那个能不能**和皮肤 mod 做区分，算辅助 mod**，然后给个**其他 group（其他和壁纸那些并列）**」。

**那个 Mod 是什么**：把游戏里的饮料罐贴图换成真实品牌（红牛/怪兽/可乐…），按 `Alt+T`
轮换 12 种。它有 `Textures\\` 20 张 .dds，**没有 `Meshes\\`**。

**为什么以前判成了 `character`**：
`looks_like_assist` 的第一条是"没有换装资源"，而它**有 .dds** ⇒ 被判成"有换装资源" ⇒
落到 `kind=character`，group 还是按目录名 / 角色名生成的。

**判据的关键取舍**（实测踩过）：「弭弗」**真的是游戏里的角色**（别名 mifu / mi fu / 弥弗），
`match_character` 返回 high 置信 —— 但用户要的语义是「和皮肤 mod 做区分」，
所以判据必须是"**改了什么**"（贴图 or 模型），**不是**"属于哪个角色"。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import core


def _make_mod(root: Path, name: str, *, textures: bool, meshes: bool) -> Path:
    mod = root / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "mod.ini").write_text("[TextureOverride_Camera.x]\nhash = abcd\n", encoding="utf-8")
    if textures:
        tex = mod / "Textures"
        tex.mkdir(exist_ok=True)
        (tex / "a.dds").write_bytes(b"D" * 64)
    if meshes:
        mesh = mod / "Meshes"
        mesh.mkdir(exist_ok=True)
        (mesh / "b.buf").write_bytes(b"B" * 64)
    return mod


def test_texture_only_is_assist(tmp_path: Path) -> None:
    """★ 只有贴图、没有网格 ⇒ 辅助 Mod 的「贴图替换类」。"""
    mod = _make_mod(tmp_path, "弭弗饮料罐690308", textures=True, meshes=False)
    kind, group = core.infer_kind_and_group(["弭弗饮料罐690308"], {}, mod)
    assert kind == "assist", f"应当判成辅助，实际 {kind}"
    assert group == core.ASSIST_GROUP_TEXTURE, f"应当归到「贴图替换类」，实际 {group!r}"


def test_character_texture_pack_still_texture_class(tmp_path: Path) -> None:
    """★ **认得出角色也要算贴图替换类** —— 这正是用户要的"和皮肤 mod 做区分"。

    「弭弗」确实是角色（match_character 返回 high 置信），但它只是换饮料罐贴图、
    没换模型 ⇒ 按"改了什么"分类，归贴图替换类。
    """
    name = "弭弗饮料罐690308"
    mod = _make_mod(tmp_path, name, textures=True, meshes=False)
    matched = core.match_character(name.lower())
    assert matched, "这个样本必须能识别出角色，否则测不到这条取舍"
    kind, group = core.infer_kind_and_group([name], {}, mod)
    assert (kind, group) == ("assist", core.ASSIST_GROUP_TEXTURE), \
        f"认得出角色也应归贴图替换类，实际 {(kind, group)}"


def test_with_meshes_stays_character(tmp_path: Path) -> None:
    """有网格 = 在换模型 = 服装，**不能被**挪进贴图替换类。"""
    mod = _make_mod(tmp_path, "庄方宜水墨旗袍", textures=True, meshes=True)
    kind, _group = core.infer_kind_and_group(["庄方宜水墨旗袍"], {}, mod)
    assert kind == "character", f"有 Meshes 就应当留在角色库，实际 {kind}"


def test_texture_only_needs_textures(tmp_path: Path) -> None:
    """既没贴图也没网格的（纯 ini 小 Mod）不该被这个判据捞走。"""
    mod = _make_mod(tmp_path, "Hide UI UID", textures=False, meshes=False)
    assert core.looks_like_texture_only(mod, ["Hide UI UID"], {}, "") is False


def test_group_constant_exists_and_is_alongside_wallpaper() -> None:
    """新分组常量存在，且与壁纸组是**并列**的两个名字。"""
    assert core.ASSIST_GROUP_TEXTURE == "贴图替换类"
    assert core.WALLPAPER_GROUP == "加载页与壁纸"
    assert core.ASSIST_GROUP_TEXTURE != core.WALLPAPER_GROUP
