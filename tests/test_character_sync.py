"""角色表「跟官网同步」的离线单测（不触网）。

用户 2026-09-30 要求：「管理器要带最新角色名，可以固化拉最新角色名称的脚本，每次启动后
非阻塞检查」。这里测四件事：

* 官网 HTML 的解析（`OperatorItem_nameText` / `_codename` / `_index` + 图标里的美术 key）；
* 合并时**不丢本地 aliases**（社区简称是手工补的，官网没有），且官网没列的角色要保留；
* 24 小时节流（缓存命中时**一次网络都不发**）与失败静默；
* 写盘位置在**数据根**（`runtime\\_state\\characters.json`）并让 core 优先读它。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import character_sync, core
from endfieldmodcontroller.config import AppConfig

FAKE_HTML = """
<div class="OperatorItem_operatorItem__gPezu">
  <img src="https://web.hycdn.cn/endfield/official-v4/typhoea.87cfb4cd.png" />
  <div class="OperatorItem_contentBlock__I_0_3" data-rarity="6">
    <div class="OperatorItem_name__OvU8c"><span class="OperatorItem_nameText__ibYGO">提弗洛斯</span></div>
    <div class="OperatorItem_subTitle___c7GD">
      <div class="OperatorItem_codename__U3_VI">// Typhoeus</div>
      <div class="OperatorItem_index__ivv9h">01<!-- --> / <!-- -->34</div>
    </div>
  </div>
</div>
<div class="OperatorItem_operatorItem__gPezu">
  <img src="https://web.hycdn.cn/endfield/official-v4/newchar.abcdef12.png" />
  <div class="OperatorItem_contentBlock__I_0_3" data-rarity="6">
    <div class="OperatorItem_name__OvU8c"><span class="OperatorItem_nameText__ibYGO">新角色甲</span></div>
    <div class="OperatorItem_subTitle___c7GD">
      <div class="OperatorItem_codename__U3_VI">// Newchar</div>
      <div class="OperatorItem_index__ivv9h">34<!-- --> / <!-- -->34</div>
    </div>
  </div>
</div>
"""

LOCAL = {
    "schema_version": 2,
    "source": character_sync.SOURCE_URL,
    "fetched_at": "2026-09-27",
    "official_count": 33,
    "characters": [
        {"name": "提弗洛斯", "codename": "Typhoeus", "key": "typhoea",
         "aliases": ["提弗洛斯", "typhoeus", "typhoea", "提丰"]},   # 手工补的社区简称
        {"name": "已下架角色", "codename": "Gone", "key": "gone", "aliases": ["已下架角色"]},
    ],
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    # 两处都要用 monkeypatch 接管并在用例结束后还原：否则"临时表"的解析结果会留在
    # core 的模块级缓存里，把**别的测试**（test_core 的角色识别）带偏。
    monkeypatch.setattr(core, "CHARACTERS_OVERRIDE", None)
    monkeypatch.setattr(core, "_CHARACTER_ALIAS_CACHE", None)
    return SimpleNamespace(config=config, tmp=tmp_path)


# --------------------------------------------------------------- 解析
def test_parse_official_reads_name_codename_key_and_total():
    parsed = character_sync.parse_official(FAKE_HTML)
    assert parsed["total"] == 34
    assert [c["name"] for c in parsed["characters"]] == ["提弗洛斯", "新角色甲"]
    first = parsed["characters"][0]
    assert first["codename"] == "Typhoeus"
    assert first["key"] == "typhoea"
    assert first["index"] == 1


def test_parse_official_survives_empty_page():
    parsed = character_sync.parse_official("<html></html>")
    assert parsed["characters"] == []
    assert parsed["total"] == 0


# --------------------------------------------------------------- 合并
def test_merge_keeps_local_aliases_and_adds_new_character():
    parsed = character_sync.parse_official(FAKE_HTML)
    merged = character_sync.merge_payload(LOCAL, parsed)
    payload = merged["payload"]
    by_name = {item["name"]: item for item in payload["characters"]}

    assert merged["added"] == ["新角色甲"]
    # 已有角色的**手工别名不能丢**
    assert "提丰" in by_name["提弗洛斯"]["aliases"]
    # 新角色带上官网的三个名字
    assert set(by_name["新角色甲"]["aliases"]) == {"新角色甲", "Newchar", "newchar"}
    # 官网没列、本地有的要保留（否则用户已有 Mod 会突然识别不出来）
    assert "已下架角色" in by_name
    assert payload["official_count"] == 34


def test_merge_is_idempotent():
    parsed = character_sync.parse_official(FAKE_HTML)
    once = character_sync.merge_payload(LOCAL, parsed)["payload"]
    twice = character_sync.merge_payload(once, parsed)["payload"]
    assert [c["name"] for c in once["characters"]] == [c["name"] for c in twice["characters"]]
    assert character_sync.merge_payload(once, parsed)["added"] == []


def test_merge_aggregates_same_name_from_official():
    """官网把男女管理员列成两条（同名、key 不同）→ 合并后**只能有一条**，且两个 key 都进别名。

    这是实拉官网发现的真问题：不聚合就会在表里造出重复的「管理员」。
    """
    local = {"schema_version": 2, "characters": [
        {"name": "管理员", "codename": "Endministrator", "key": "endministrator",
         "aliases": ["管理员", "女管理员", "男管理员", "endmin"]},
    ]}
    official = {"total": 2, "characters": [
        {"name": "管理员", "codename": "Endministrator", "key": "endministrator",
         "aliases": ["管理员", "Endministrator", "endministrator"]},
        {"name": "管理员", "codename": "Endministrator", "key": "endministrator1",
         "aliases": ["管理员", "Endministrator", "endministrator1"]},
    ]}
    merged = character_sync.merge_payload(local, official)
    names = [c["name"] for c in merged["payload"]["characters"]]
    assert names == ["管理员"]                       # 没有重复条目
    assert merged["added"] == []
    aliases = merged["payload"]["characters"][0]["aliases"]
    assert "endministrator1" in aliases               # 官网第二条的 key 也没丢
    assert "男管理员" in aliases and "endmin" in aliases   # 本地手工别名保留


# --------------------------------------------------------------- 节流 / 失败静默
def test_sync_is_throttled_within_ttl(env, monkeypatch):
    calls: list[int] = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise AssertionError("节流命中时不该发网络请求")

    monkeypatch.setattr(character_sync, "fetch_official", boom)
    character_sync._write_json(character_sync.cache_path(env.config),
                               {"at": int(character_sync.time.time()), "ok": True, "total": 33})
    report = character_sync.sync(env.config)
    assert report["skipped"] is True
    assert calls == []


def test_sync_failure_is_silent(env, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("网络不通")

    monkeypatch.setattr(character_sync, "fetch_official", boom)
    logs: list[str] = []
    report = character_sync.sync(env.config, force=True, log=logs.append)
    assert report["ok"] is False and report["changed"] is False
    assert logs and "角色表检查失败" in logs[0]
    # 失败也要落缓存，避免每次启动都重试打网络
    cache = character_sync._read_json(character_sync.cache_path(env.config))
    assert cache.get("ok") is False


# --------------------------------------------------------------- 写盘 + core 生效
def test_write_latest_lands_in_data_root_and_core_picks_it_up(env):
    parsed = character_sync.parse_official(FAKE_HTML)
    payload = character_sync.merge_payload(LOCAL, parsed)["payload"]
    path = character_sync.write_latest(env.config, payload)

    assert path == env.tmp / "runtime" / "_state" / "characters.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["official_count"] == 34

    aliases = core.load_character_aliases()
    canonical = [name for name, _aliases in aliases]
    assert "新角色甲" in canonical           # 新角色立刻能被识别
    assert core.CHARACTERS_OVERRIDE == path
