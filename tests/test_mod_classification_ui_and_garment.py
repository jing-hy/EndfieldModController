"""两个归错的类（2026-10-06 用户指名，两个 mod 本地都有）。

**①「AI generated)Background Image Alteration」→ 界面功能类（UI）**
  * sidecar 铁证：`download-info.json` 的 `网站分类 = "UI"`、`mod.meta.json` 的
    `site_category_root = "UI"`，原始文件名 `changescreens_182.zip`；
  * 却因**名字含 `background`** 被 `looks_like_wallpaper()` 判成「加载页与壁纸」。
  * 已有的"site_category_root == ui"判据在 `looks_like_assist()` 里，**管不到带 .dds 的包**
    （那个函数第一关"有换装资源 ⇒ 不是辅助"就先返回了）。
  ⇒ 修法：**作者填的网站分类压过"按名字猜"**。

**②「萤石去紧身衣+…」→ 皮肤**
  * 内容只有 `Diffuse.dds` / `MaterialMap.dds` / `NormalMap.dds` + `Test.ini` ⇒ 有贴图无网格
    ⇒ `looks_like_texture_only()` 判 True ⇒ 被归进辅助；
  * 那条函数本有"命中服装关键词就排除"的规则，但 `GARMENT_HINTS` **漏了「紧身衣」**。
  ⇒ 修法：补上紧身衣 / 连体衣 / 打底这一族词。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import core


def _dds_only_mod(root: pathlib.Path, name: str) -> pathlib.Path:
    """造一个「只有贴图、没有网格」的 Mod 目录（复现这类包的形态）。"""
    folder = root / name
    folder.mkdir(parents=True)
    for fname in ("Diffuse.dds", "MaterialMap.dds", "NormalMap.dds"):
        (folder / fname).write_bytes(b"DDS ")
    (folder / "Test.ini").write_text("[TextureOverrideShade]\nhash = bf266dfc\n",
                                     encoding="utf-8")
    return folder


def test_ui_site_category_beats_background_in_name(tmp_path, monkeypatch):
    """★ 网站分类 = UI ⇒ 界面功能类；**不能**因为名字含 `background` 就归到「加载页与壁纸」。"""
    name = "AI_generated_Background_Image_Alteration"
    folder = _dds_only_mod(tmp_path, name)
    # 它就是这样的 sidecar（真实包里的字段）
    meta = {"name": "AI generated)Background Image Alteration", "site_category": "UI",
            "site_category_root": "UI"}
    kind, group = core.infer_kind_and_group([name], meta, folder)
    assert kind == "assist"
    assert group == core.ASSIST_GROUP_HIDE, f"应归界面功能类，实际 {group!r}"


def test_wallpaper_without_ui_category_still_goes_to_wallpaper(tmp_path):
    """对照：**没有** UI 分类的壁纸包照旧归「加载页与壁纸」（别把正常路径关掉）。"""
    name = "female_images_dark_mode_a12a6"
    folder = _dds_only_mod(tmp_path, name)
    kind, group = core.infer_kind_and_group([name], {"name": name}, folder)
    assert kind == "assist"
    assert group == core.WALLPAPER_GROUP, f"壁纸包应归加载页与壁纸，实际 {group!r}"


@pytest.mark.parametrize("name", [
    "萤石去紧身衣+z键尾巴萤石去除紧身衣去尾巴（会和黎风、伊冯等角色有贴图错误）",
    "萤石去紧身衣_z键尾巴萤石去除紧身衣去尾巴_会和黎风_伊冯等角色有贴图错误",
])
def test_texture_only_with_garment_word_stays_skin(tmp_path, name):
    """★ 只有贴图、没有网格，但名字里是**服装**词 ⇒ 必须留在角色库（是那个角色的衣服）。"""
    folder = _dds_only_mod(tmp_path, name)
    kind, group = core.infer_kind_and_group([name], {"name": name}, folder)
    assert kind == "character", f"「紧身衣」是服装词，不该被当成辅助：{kind!r}/{group!r}"
    assert group == "萤石"


def test_plain_texture_only_still_assist(tmp_path):
    """对照：**不含**服装词的纯贴图包照旧归辅助（原语义不变）。"""
    name = "饮料罐贴图替换690308"
    folder = _dds_only_mod(tmp_path, name)
    kind, group = core.infer_kind_and_group([name], {"name": name}, folder)
    assert kind == "assist", f"不含服装词的纯贴图包应仍是辅助：{kind!r}"
