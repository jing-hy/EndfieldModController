# SPDX-License-Identifier: GPL-3.0-or-later
"""`scripts/check_component_versions.py` 的比对逻辑。

用户 2026-10-04 要求：「**另外每次 release 要检查内置的依赖版本表是否最新**」——
表是"随包快照"（一键启动前只读它、不联网），过期就会误导用户，所以发版时要联网核对。
这里只钉住比对规则本身（联网那一步在测试里被替换掉）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_component_versions.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_component_versions_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
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
    monkeypatch.setattr(module, "_bundled_version", lambda key: bundled)


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
    """PE 文件版本常带构建号（6.8.0.2155 vs 表里 6.8.0）—— 不能判成"随包比表新"。"""
    module = _load()
    _stub_both(monkeypatch, module,
               {"external": {"reshade": {"latest": "6.8.0"}}},
               {"reshade": {"latest": "6.8.0"}},
               "6.8.0.2155")

    data = module.collect()

    assert data["ok"] is True
    assert data["assets"][0]["status"] == "ok"


def test_component_without_bundled_asset_is_skipped(monkeypatch):
    """XXMI 是联网安装、没有"随包那份" ⇒ 探测不到就跳过，不误报。"""
    module = _load()
    _stub_both(monkeypatch, module,
               {"builtin": {"XXMI": {"latest": "v2.4.9"}}},
               {"builtin": {"XXMI": {"latest": "v2.4.9"}}},
               "")

    data = module.collect()

    assert data["ok"] is True
    assert data["assets"] == []


def test_rabbitfx_bundled_probe_reads_real_manifest():
    """探测本身要能真的读到随包资产（路径写错/文件被挪走时会红）。"""
    module = _load()
    assert module._bundled_version("rabbitfx"), "assets/rabbitfx/manifest.json 应当带 mod_version"

