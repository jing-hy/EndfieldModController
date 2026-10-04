"""钉住「香蕉网网站分类 → 管理器分类」这条链路（2026-10-04 接入）。

**用户原话**：「把 mod 在香蕉网中的分类接入管理器的分类」。

**为什么它可信**：分类是**作者投稿时自己挑的**；实测终末地全量 **695** 个 Mod
**100% 都带**，根只有 `Skins` / `UI` / `Other-Misc` 三个
（`Skins` 下面还有一层 `Operators` → 角色名）。

**定位：补充判据，不是覆盖判据。**
  * 角色：只在"名字/目录里认不出来"时拿分类里的英文角色名兜底；
  * 类型：`UI` 根分类 == `ASSIST_HINTS` 里的 `ui`/`hud`/`hide` 的同一方向，
    只是从"在名字里猜"升级成"按权威分类判"；
  * ⚠️ 两条**否决项照旧先生效**（有换装资源 / 能识别出角色 ⇒ 不是辅助），
    所以真皮肤不会被 `UI` 分类误伤成辅助。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import core


def _make_mod(root: Path, name: str, *, meta: dict | None = None,
              model: bool = False, textures: bool = False) -> Path:
    mod = root / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "mod.ini").write_text("[TextureOverride_Camera.x]\nhash = abcd\n", encoding="utf-8")
    if meta:
        import json

        (mod / "mod.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if model:
        mesh = mod / "Meshes"
        mesh.mkdir(exist_ok=True)
        (mesh / "b.buf").write_bytes(b"B" * 64)
    if textures or model:
        tex = mod / "Textures"
        tex.mkdir(exist_ok=True)
        (tex / "a.dds").write_bytes(b"D" * 64)
    return mod


SKIN_ARCANE = {"site_category": "Skins / Operators / Arcane", "site_category_root": "Skins"}
UI_MOD = {"site_category": "UI", "site_category_root": "UI"}


# ── 分类路径解析 ──────────────────────────────────────────────────────────────

def test_only_operators_path_yields_a_character() -> None:
    """★ 只在 `Skins / Operators / <角色>` 这一种形态下取角色名，其余一律不猜。"""
    assert core.site_category_character(SKIN_ARCANE) == "Arcane"
    # 武器/敌人/工厂这些同样是 Skins 的子类，但**不是角色**
    assert core.site_category_character({"site_category": "Skins / Weapons"}) == ""
    assert core.site_category_character({"site_category": "Skins / Operators / "}) == ""
    assert core.site_category_character(UI_MOD) == ""
    assert core.site_category_character({"site_category": "Other/Misc"}) == ""
    assert core.site_category_character({}) == ""
    assert core.site_category_character({"site_category": "Skins / Operators"}) == ""


# ── 角色兜底：只在认不出来时生效 ───────────────────────────────────────────────

def test_site_category_fills_in_the_character(tmp_path: Path) -> None:
    """★ 目录名看不出是谁时，用分类里的英文角色名兜底（Arcane → 别名表里的中文名）。"""
    expected = core.match_character("arcane")
    assert expected, "别名表里必须有 arcane，否则这条兜底测不到"
    mod = _make_mod(tmp_path, "some_random_pack", meta=SKIN_ARCANE, model=True)
    kind, group = core.infer_kind_and_group(["some_random_pack"], SKIN_ARCANE, mod)
    assert kind == "character", f"带模型的就是服装，实际 {kind}"
    assert group == expected, f"应当靠分类兜底认出「{expected}」，实际 {group!r}"


def test_local_evidence_wins_over_site_category(tmp_path: Path) -> None:
    """★ **本地证据优先**：名字里已经能认出角色时，分类不参与（更不覆盖）。"""
    mod = _make_mod(tmp_path, "gilberta_outfit", meta=SKIN_ARCANE, model=True)
    local = core.match_character("gilberta_outfit")
    assert local, "这个名字必须能本地识别出角色，否则测不到这条取舍"
    _kind, group = core.infer_kind_and_group(["gilberta_outfit"], SKIN_ARCANE, mod)
    assert group == local, f"应当用名字的结果「{local}」，实际 {group!r}"


def test_weapons_category_does_not_invent_a_character(tmp_path: Path) -> None:
    """`Skins / Weapons` 不该凭空造出一个角色，group 保持目录名。"""
    meta = {"site_category": "Skins / Weapons", "site_category_root": "Skins"}
    mod = _make_mod(tmp_path, "weapon_pack", meta=meta, model=True)
    kind, group = core.infer_kind_and_group(["weapon_pack"], meta, mod)
    assert kind == "character"
    assert group == "weapon_pack", f"不该给武器包编一个角色，实际 {group!r}"


# ── 类型：UI 分类 ⇒ 辅助（但两条否决项先生效）────────────────────────────────

def test_ui_category_marks_assist(tmp_path: Path) -> None:
    """★ 香蕉网归在 `UI` 底下、又没有换装资源 ⇒ 辅助 Mod。"""
    mod = _make_mod(tmp_path, "background_changer", meta=UI_MOD)
    kind, _group = core.infer_kind_and_group(["background_changer"], UI_MOD, mod)
    assert kind == "assist", f"UI 分类应当算辅助，实际 {kind}"


def test_ui_category_never_steals_a_real_skin(tmp_path: Path) -> None:
    """★★ **否决项优先**：有模型（换装资源）就永远是服装，`UI` 分类不能把它挪走。

    这是这条接入最容易出错的地方 —— 一旦误判，Mod 会从「服装 Mod」页消失、
    跑进辅助页，用户看到的就是"我的 mod 不见了"。
    """
    mod = _make_mod(tmp_path, "ui_named_but_skin", meta=UI_MOD, model=True)
    kind, _group = core.infer_kind_and_group(["ui_named_but_skin"], UI_MOD, mod)
    assert kind == "character", f"有换装资源的不能被 UI 分类判成辅助，实际 {kind}"


def test_ui_category_never_steals_a_recognized_character(tmp_path: Path) -> None:
    """★★ 同理：**能识别出角色**的也否决 —— 去掉某部件的小 Mod 结构上像辅助，
    但它属于那个角色，必须留在角色库里参与同角色互斥（2026-10-01 定的取舍）。"""
    name = "庄方宜水墨旗袍"
    assert core.match_character(name.lower()), "样本必须能识别出角色"
    mod = _make_mod(tmp_path, name, meta=UI_MOD)
    kind, _group = core.infer_kind_and_group([name], UI_MOD, mod)
    assert kind == "character", f"认得出角色就不算辅助，实际 {kind}"


def test_explicit_kind_still_wins(tmp_path: Path) -> None:
    """用户手动设过的 `kind`（sidecar 里有值）依旧最优先，分类不能翻它。"""
    meta = dict(UI_MOD, kind="character")
    mod = _make_mod(tmp_path, "manual_choice", meta=meta)
    kind, _group = core.infer_kind_and_group(["manual_choice"], meta, mod)
    assert kind == "character", f"显式 kind 必须最优先，实际 {kind}"
