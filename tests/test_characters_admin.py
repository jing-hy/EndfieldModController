# SPDX-License-Identifier: AGPL-3.0-only
"""角色表：1.7 新角色（小刻）与管理员的男女拆分。

2026-11-28 用户：「现在角色是缺的，1.7 的小刻没有，现在管理员那里似乎只会识别男管理员，
这个要修一下」。根因两处：

* 随包表停在 2026-09-27（32 位），官网已有 37 位（含小刻）；
* 官网把男女管理员列成两条、都叫「管理员」，我们的表聚合成了一条、头像取的是男的那张。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from endfieldmodcontroller import character_avatars, character_sync, core
from endfieldmodcontroller.config import AppConfig


def _bundled() -> dict:
    return json.loads(Path(core.CHARACTERS_JSON).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _reset_override():
    core.set_characters_override(None)
    yield
    core.set_characters_override(None)


def test_bundled_table_has_the_17th_characters() -> None:
    names = [str(item.get("name") or "") for item in _bundled().get("characters") or []]
    assert "小刻" in names, "1.7 的小刻必须随包（否则新用户的 Mod 认不出角色）"
    assert len(names) >= 37
    assert "男管理员" in names and "女管理员" in names
    assert "管理员" not in names, "管理员应已拆成男/女两条，不再保留合并条目"


def test_new_character_is_matched() -> None:
    assert core.match_character("小刻") == "小刻"
    # 官网 key / codename 也要能认（作者常用英文命名）
    assert core.match_character("sweetpie") == "小刻"
    assert core.match_character("kay") == "小刻"


def test_administrator_sexes_are_matched_separately() -> None:
    assert core.match_character("女管理员") == "女管理员"
    assert core.match_character("男管理员") == "男管理员"
    # 裸名按默认外观归女管理员（官网第一条是男，但游戏默认女主）
    assert core.match_character("管理员") == "女管理员"


def test_administrator_avatars_are_indexed() -> None:
    index = json.loads((Path(core.CHARACTERS_JSON).parent / "characters" / "index.json")
                       .read_text(encoding="utf-8"))
    avatars = index.get("avatars") or {}
    assert avatars.get("女管理员") == "endministrator1.c391b13d.png"
    assert avatars.get("男管理员") == "endministrator2.5ccb44a8.png"
    folder = Path(core.CHARACTERS_JSON).parent / "characters"
    assert (folder / avatars["女管理员"]).is_file()
    assert (folder / avatars["男管理员"]).is_file()
    config = AppConfig()
    assert character_avatars.find_avatar(config, "女管理员") == "endministrator1.c391b13d.png"


def test_merge_keeps_administrators_apart() -> None:
    bundled = _bundled()
    official = {
        "total": 3,
        "characters": [
            {"name": "管理员", "codename": "Endministrator", "key": "endministrator2",
             "avatar": "https://x/male.png"},
            {"name": "管理员", "codename": "Endministrator", "key": "endministrator1",
             "avatar": "https://x/female.png"},
            {"name": "小刻", "codename": "Kay", "key": "sweetpie", "avatar": "https://x/kay.png"},
        ],
    }
    merged = character_sync.merge_payload(bundled, official)
    rows = merged["payload"]["characters"]
    names = [str(item.get("name") or "") for item in rows]

    assert names.count("管理员") == 0, "官网两条同名管理员不能再被聚合成一条"
    assert "男管理员" in names and "女管理员" in names
    male = next(item for item in rows if item["name"] == "男管理员")
    assert male["key"] == "endministrator2"
    assert "管理员" not in male["aliases"], "裸「管理员」不能进男条目，否则女管理员 Mod 会被判成男"


def test_legacy_merged_admin_row_is_absorbed() -> None:
    bundled = _bundled()
    legacy = {"characters": [{
        "name": "管理员", "codename": "Endministrator", "key": "endministrator",
        "aliases": ["管理员", "女管理员", "男管理员", "endministrator", "endmin"],
    }]}
    combined = character_sync.combine_tables(bundled, legacy)
    names = [str(item.get("name") or "") for item in combined["characters"]]

    assert "管理员" not in names, "旧运行时表里的合并条目应被吸收，而不是再单列一条"
    female = next(item for item in combined["characters"] if item["name"] == "女管理员")
    assert "男管理员" not in female["aliases"]


def test_conflict_group_merges_the_two_administrators() -> None:
    # 同一个游戏角色 ⇒ 同角色互斥必须归到一组，避免男女两套 Mod 能同时装
    assert core.CHARACTER_CONFLICT_MERGE == {"男管理员": "管理员", "女管理员": "管理员"}
