# SPDX-License-Identifier: AGPL-3.0-only
"""发版前第四道检查：随包角色表 vs 官网角色页（2026-11-28 用户要求）。

用户原话：「另外要把角色检查加进上游更新检查后面」——「上游更新检查」指的是
`scripts/check_component_versions.py`（build_release --strict 会跑它）。
v1.7 上线后随包表还停在 9 月的 32 位，小刻这类新角色直接缺失，所以发版前必须能拦住。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_component_versions.py"


def _load():
    spec = importlib.util.spec_from_file_location("ccv_characters_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compare_detects_missing_characters_and_splits_administrators() -> None:
    module = _load()
    local = {"characters": [{"name": "小刻"}, {"name": "女管理员"}, {"name": "男管理员"}]}
    official = {"characters": [
        {"name": "小刻"},
        {"name": "沫沫"},
        {"name": "管理员", "key": "endministrator2"},
        {"name": "管理员", "key": "endministrator1"},
    ]}

    result = module.compare_characters(local, official)

    assert result["status"] == "outdated"
    assert "沫沫" in result["missing"]
    # 官网两条同名管理员按 key 拆成男/女，本地已有 ⇒ 不算缺
    assert "女管理员" not in result["missing"]
    assert "男管理员" not in result["missing"]
    assert result["problems"] == result["missing"]


def test_compare_is_ok_when_local_has_everything() -> None:
    module = _load()
    payload = {"characters": [{"name": "小刻"}, {"name": "女管理员"}]}
    result = module.compare_characters(payload, {"characters": [
        {"name": "小刻"}, {"name": "管理员", "key": "endministrator1"},
    ]})

    assert result["status"] == "ok"
    assert result["missing"] == []


def test_collect_characters_network_failure_is_unknown(monkeypatch) -> None:
    module = _load()
    from endfieldmodcontroller import character_sync

    def _boom(timeout=25):
        raise RuntimeError("offline")

    monkeypatch.setattr(character_sync, "fetch_official", _boom)

    result = module.collect_characters()

    assert result["status"] == "unknown", "网络失败不许当成“表过期”误拦发版"
    assert result["problems"] == []
    assert "拉取失败" in str(result.get("message") or "")


def test_collect_characters_reports_missing_against_bundled_file(monkeypatch, tmp_path) -> None:
    module = _load()
    from endfieldmodcontroller import character_sync

    monkeypatch.setattr(character_sync, "fetch_official",
                        lambda timeout=25: {"characters": [{"name": "小刻"}, {"name": "新角色"}]})
    local = tmp_path / "characters.json"
    local.write_text(json.dumps({"characters": [{"name": "小刻"}]}, ensure_ascii=False),
                     encoding="utf-8")
    monkeypatch.setattr(module, "CHARACTERS_JSON", local)

    result = module.collect_characters()

    assert result["status"] == "outdated"
    assert result["missing"] == ["新角色"]


def test_collect_characters_missing_file_is_missing(monkeypatch, tmp_path) -> None:
    module = _load()
    from endfieldmodcontroller import character_sync

    monkeypatch.setattr(character_sync, "fetch_official",
                        lambda timeout=25: {"characters": [{"name": "小刻"}]})
    monkeypatch.setattr(module, "CHARACTERS_JSON", tmp_path / "nope.json")

    result = module.collect_characters()

    assert result["status"] == "missing"