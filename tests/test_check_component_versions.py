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
