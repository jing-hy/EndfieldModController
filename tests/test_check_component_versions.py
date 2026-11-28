# SPDX-License-Identifier: AGPL-3.0-only
"""`scripts/check_component_versions.py` 的比对逻辑。

用户 2026-10-04 要求：「**另外每次 release 要检查内置的依赖版本表是否最新**」——
表是"随包快照"（一键启动前只读它、不联网），过期就会误导用户，所以发版时要联网核对。
这里只钉住比对规则本身（联网那一步在测试里被替换掉）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_component_versions.py"
#: 默认指到不存在的路径：本文件的历史用例只测「表 vs 上游」「表 vs 随包资产」，
#: 不该被本机 dist 里那份真实的离线包（可能本身已过期）牵动。第三道比对自己显式传路径。
_NO_BUNDLE = SCRIPT.parent.parent / "_no_such_deps_bundle.zip"


def _load(*, offline_bundle: Path | None = None):
    spec = importlib.util.spec_from_file_location("check_component_versions_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.OFFLINE_BUNDLE = offline_bundle or _NO_BUNDLE
    # 第四道（角色表 vs 官网）会联网：这些用例只测版本比对，统一打成"没查到"，
    # 免得测试依赖网络与时延。角色表自己的用例在 test_check_component_versions_characters.py。
    module.collect_characters = lambda: {
        "status": "unknown", "official": 0, "local": 0,
        "missing": [], "extra": [], "problems": [], "message": "测试不联网",
    }
    return module


def test_upstream_newer_is_reported_as_outdated(monkeypatch):
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"builtin": {"XXMI": {"latest": "v2.3.8"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"builtin": {"XXMI": {"latest": "v2.4.1"}}, "errors": []})

    data = module.collect()

    assert data["ok"] is False
    assert data["rows"][0]["status"] == "outdated"
    assert data["rows"][0]["upstream"] == "v2.4.1"


def test_table_newer_than_upstream_is_flagged_too(monkeypatch):
    """表里比上游还新 = 多半写错或上游撤包，也要报出来（安静地留着更危险）。"""
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"external": {"reshade": {"latest": "6.9.0"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"reshade": {"latest": "6.8.0"}, "errors": []})

    data = module.collect()

    assert data["ok"] is False
    assert data["rows"][0]["status"] == "ahead"


def test_matching_version_is_ok(monkeypatch):
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"builtin": {"EFMI": {"latest": "v1.4.8"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"builtin": {"EFMI": {"latest": "v1.4.8"}}, "errors": []})
    # 与 _stub_both 同一理由：离线包那一道读本机 dist/，不该影响这条"表对上就算过"的用例
    monkeypatch.setattr(module, "collect_offline_bundles",
                        lambda table: {"bundles": {}, "problems": []})

    data = module.collect()

    assert data["ok"] is True
    assert data["rows"][0]["status"] == "ok"


def test_poser_is_read_from_its_own_section(monkeypatch):
    """Poser 上游只发预发布版，`check_updates()` 把它单独放在 `poser` 段里。"""
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"builtin": {"Poser": {"latest": "0.5.2"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"poser": {"latest": "0.5.18"}, "errors": []})

    data = module.collect()

    assert data["rows"][0]["status"] == "outdated"
    assert data["rows"][0]["upstream"] == "0.5.18"


def test_unknown_upstream_is_not_treated_as_outdated(monkeypatch):
    """查不到（网络/限流）**不算**表过期 —— 否则离线构建会一直被误报。"""
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"external": {"reshade": {"latest": "6.8.0"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"reshade": {}, "errors": ["boom"]})

    data = module.collect()

    assert data["ok"] is True
    assert data["rows"][0]["status"] == "unknown"


def test_missing_table_skips(monkeypatch):
    module = _load()
    monkeypatch.setattr(module.component_versions, "load", lambda: {})

    data = module.collect()

    assert data["ok"] is True
    assert data.get("skipped")

# ── 第二道比对：表 vs 随包资产（2026-10-26 补）──────────────────────────────
# 起因（真实事故）：表里乳摇写 3.2.1、上游也是 3.2.1，一切"正常"；
# 可仓库随包的 assets/secondary_motion/plugin/sbm.dll 还是 3.1.2 ——
# 用户装完管理器，随包铺进去的是旧版，一键启动立刻提示"该更新"。
# 第一道比对（表 vs 上游）永远发现不了这种"表对、货没换"。
def _stub_both(monkeypatch, module, table, report, bundled):
    monkeypatch.setattr(module.component_versions, "load", lambda: table)
    monkeypatch.setattr(module.updates, "check_updates", lambda *a, **k: {**report, "errors": []})
    monkeypatch.setattr(module, "_probe_bundled", lambda key: (bundled, "" if bundled else "探测不到"))
    # 2026-11-28：离线包那一道读的是**本机 dist/**，开发机上留着一个旧包就会让这些用例变红；
    # 它们考的是"版本表比对"，与真实包无关 ⇒ 隔离掉（两版都算没有包）。
    monkeypatch.setattr(module, "collect_offline_bundles",
                        lambda table: {"bundles": {}, "problems": []})


def test_bundled_asset_older_than_table_blocks_release(monkeypatch):
    module = _load()
    _stub_both(monkeypatch, module,
               {"external": {"secondary_motion": {"latest": "3.2.1"}}},
               {"secondary_motion": {"latest": "3.2.1"}},
               "3.1.2.0")

    data = module.collect()

    assert data["ok"] is False, "随包比表旧时整轮检查必须判为不通过（发版闸要拦住）"
    assert data["assets"][0]["status"] == "stale"
    assert data["assets"][0]["bundled"] == "3.1.2.0"
    assert data["assets"][0]["table"] == "3.2.1"


def test_bundled_asset_newer_than_table_is_flagged(monkeypatch):
    """随包已经比表新 = 发版时忘了更新表，也要报出来。"""
    module = _load()
    _stub_both(monkeypatch, module,
               {"external": {"rabbitfx": {"latest": "2.6"}}},
               {"rabbitfx": {"latest": "2.6"}},
               "2.8")

    data = module.collect()

    assert data["ok"] is False
    assert data["assets"][0]["status"] == "asset_ahead"


def test_build_suffix_in_bundled_version_is_not_a_mismatch(monkeypatch):
    """PE 文件版本常带构建号（3.2.1.0 vs 表里 3.2.1）—— 不能判成"随包比表新"。"""
    module = _load()
    _stub_both(monkeypatch, module,
               {"external": {"secondary_motion": {"latest": "3.2.1"}}},
               {"secondary_motion": {"latest": "3.2.1"}},
               "3.2.1.0")

    data = module.collect()

    assert data["ok"] is True
    assert data["assets"][0]["status"] == "ok"


def test_component_without_bundled_asset_is_skipped(monkeypatch):
    """XXMI 是联网安装、没有"随包那份"（不在探测表里）⇒ 不参与这一道，也不报警。"""
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"builtin": {"XXMI": {"latest": "v2.4.9"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"builtin": {"XXMI": {"latest": "v2.4.9"}}, "errors": []})
    monkeypatch.setattr(module, "collect_offline_bundles",
                        lambda table: {"bundles": {}, "problems": []})

    data = module.collect()

    assert data["ok"] is True
    assert data["assets"] == []


def test_missing_bundled_asset_is_reported(monkeypatch):
    """★ 2026-10-26 用户要求：「你改检测，让他会报警就行」。

    仓库里没有随包二进制（*.dll 不进 git，新克隆就是这种状态）时必须出声，
    不能因为"探测不到"就静默通过 —— 否则同一个事故在别的机器上永远发现不了。
    """
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"external": {"secondary_motion": {"latest": "3.2.1"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"secondary_motion": {"latest": "3.2.1"}, "errors": []})
    monkeypatch.setattr(module, "_probe_bundled",
                        lambda key: ("", "仓库里没有 assets/secondary_motion/plugin/sbm.dll"))

    data = module.collect()

    assert data["ok"] is False, "缺随包资产时必须判为不通过（会报警）"
    assert data["assets"][0]["status"] == "missing"
    assert "sbm.dll" in data["assets"][0]["reason"]


def test_missing_bundled_asset_can_be_allowed(monkeypatch):
    """没有资产的机器（只研究源码）可以显式放过：--allow-missing-assets。"""
    module = _load()
    monkeypatch.setattr(module.component_versions, "load",
                        lambda: {"external": {"secondary_motion": {"latest": "3.2.1"}}})
    monkeypatch.setattr(module.updates, "check_updates",
                        lambda *a, **k: {"secondary_motion": {"latest": "3.2.1"}, "errors": []})
    monkeypatch.setattr(module, "_probe_bundled", lambda key: ("", "没有"))

    data = module.collect(allow_missing_assets=True)

    assert data["ok"] is True
    assert data["assets"][0]["status"] == "absent"


def test_rabbitfx_bundled_probe_reads_real_manifest():
    """探测本身要能真的读到随包资产（路径写错/文件被挪走时会红）。"""
    module = _load()
    assert module._bundled_version("rabbitfx"), "assets/rabbitfx/manifest.json 应当带 mod_version"

# ── 第三道比对：表 vs 离线依赖包（2026-11-27 补）────────────────────────────
# 起因（真实事故）：表已写 EFMI v1.5.1，而 dist/deps-bundle.zip 还是 11-14 打的、里面是 1.4.9。
# 前两道（表 vs 上游、表 vs 随包资产）都发现不了 —— 离线包不随 Release，之前没人核它。
OFFLINE_TABLE = {
    "builtin": {
        "XXMI": {"latest": "v2.5.0"},
        "XXMI-Libs": {"latest": "v1.3.3"},
        "EFMI": {"latest": "v1.5.1"},
        "Poser": {"latest": "0.5.115"},
    },
    "external": {
        "reshade": {"latest": "6.8.0"},
        "jiggle_efmi": {"latest": "0.2.7"},
    },
}
OFFLINE_DEPS_OK = {
    "XXMI": {"version": "2.5.0"},
    "XXMI-Libs": {"version": "1.3.3"},
    "EFMI": {"version": "1.5.1"},
    "Poser": {"version": "0.5.115"},
    "ReShade": {"version": "6.8.0"},
    "EndfieldJiggle": {"version": "0.2.7"},
}


def _make_bundle(tmp_path, deps):
    import json
    import zipfile

    path = tmp_path / "deps-bundle.zip"
    manifest = {"built_at": "2026-11-27T00:00:00", "deps": deps}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    return path


def test_offline_bundle_matching_table_is_ok(tmp_path):
    module = _load()
    bundle = _make_bundle(tmp_path, OFFLINE_DEPS_OK)

    data = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=bundle)

    assert data["problems"] == []
    assert {row["status"] for row in data["rows"]} == {"ok"}
    assert len(data["rows"]) == 6, "六个登记的组件都该参与比对"


def test_offline_bundle_older_than_table_is_stale(tmp_path):
    """离线包是旧版 ⇒ 必须拦住发版（v1.5.1 那次的真实事故）。"""
    deps = dict(OFFLINE_DEPS_OK, EFMI={"version": "1.4.9"})
    module = _load()
    bundle = _make_bundle(tmp_path, deps)

    data = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=bundle)

    assert len(data["problems"]) == 1
    row = data["problems"][0]
    assert row["key"] == "EFMI" and row["status"] == "stale"
    assert row["table"] == "v1.5.1" and row["bundle"] == "1.4.9"


def test_offline_bundle_newer_than_table_is_flagged(tmp_path):
    """包里比表新 = 表漏更新，同样要报（不能安静地留着）。"""
    deps = dict(OFFLINE_DEPS_OK, Poser={"version": "0.5.120"})
    module = _load()
    bundle = _make_bundle(tmp_path, deps)

    data = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=bundle)

    assert data["problems"][0]["status"] == "ahead"
    assert data["problems"][0]["key"] == "Poser"


def test_offline_bundle_missing_component_is_reported(tmp_path):
    deps = {k: v for k, v in OFFLINE_DEPS_OK.items() if k != "ReShade"}
    module = _load()
    bundle = _make_bundle(tmp_path, deps)

    data = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=bundle)

    assert data["problems"][0]["status"] == "missing"
    assert data["problems"][0]["key"] == "reshade"


def test_absent_offline_bundle_is_not_an_error(tmp_path):
    """从没打过离线包的机器不该被这道拦下。"""
    module = _load()

    data = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=tmp_path / "none.zip")

    assert data["problems"] == [] and data["rows"] == []
    assert "从没打过离线包" in data["note"]


def test_broken_offline_bundle_is_reported(tmp_path):
    """坏包 / 读不出 manifest 要报警，不许静默通过。"""
    path = tmp_path / "deps-bundle.zip"
    path.write_bytes(b"not a zip")
    module = _load()

    data = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=path)

    assert data["problems"][0]["status"] == "unreadable"
    assert "读不出 manifest.json" in data["problems"][0]["reason"]


def test_strict_fails_when_offline_bundle_is_stale(tmp_path, monkeypatch):
    """发版闸：collect() 判不通过时，--strict 必须返回 1。"""
    module = _load()
    bundle = _make_bundle(tmp_path, dict(OFFLINE_DEPS_OK, EFMI={"version": "1.4.9"}))
    offline = module.collect_offline_bundle(OFFLINE_TABLE, bundle_path=bundle)
    monkeypatch.setattr(module, "collect", lambda **kwargs: {
        "rows": [], "assets": [], "problems": [], "asset_problems": [],
        "offline": offline, "offline_problems": offline["problems"], "errors": [],
        "ok": bool(not offline["problems"]),
    })

    assert module.main(["--strict"]) == 1
    assert module.main([]) == 0

