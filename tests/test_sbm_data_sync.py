"""乳摇（SBM）角色参数「自行拉取」的离线单测（不触网）。

对应需求原话：「**在作者改之前，mod 管理器自行拉取新的参数文件**」（2026-10-01）。
要守住的性质：

* **只补缺失的角色**——本地已有角色（用户可能调过幅度/频率）必须原样保留；
* **只增不减**——上游条目比本地少时整条跳过（防回退/坏数据）；
* **绝不碰 `presets/User.json`**（那是用户自己的预设）；
* 24 小时节流、失败静默（不影响启动）。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import sbm_data_sync, secondary_motion
from endfieldmodcontroller.config import AppConfig

UPSTREAM_DATA = {
    "schema_version": 1,
    "characters": {
        "chr_0001_aurora": {"display_name": "Aurora", "tuned_by": "user"},
        "chr_0034_typhoea": {"display_name": "Typhoeus", "gait": {"walk": {"amplitude_deg": 12}}},
    },
}
LOCAL_DATA = {
    "schema_version": 1,
    "characters": {
        # 用户在管理器里调过：这个标记必须活下来
        "chr_0001_aurora": {"display_name": "Aurora", "tuned_by": "user", "user_tuned": True},
    },
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    game = tmp_path / "game"
    assets_root = tmp_path / "assets"
    runtime = tmp_path / "runtime"
    for base in (game / "SecondaryMotion" / "data", game / "SecondaryMotion" / "presets",
                 assets_root / "secondary_motion" / "data", assets_root / "secondary_motion" / "presets"):
        base.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(tmp_path / "library"),
        staging_mods_dir=str(tmp_path / "staging"),
    )
    # 把三个落点都指到临时目录（否则会写进真实的 assets/ 与游戏目录）
    monkeypatch.setattr(secondary_motion, "game_dir", lambda cfg: game)
    monkeypatch.setattr(secondary_motion, "_tool_dir", lambda cfg: None)
    monkeypatch.setattr(secondary_motion, "_assets_root", lambda cfg: assets_root)
    return SimpleNamespace(tmp=tmp_path, game=game, assets=assets_root / "secondary_motion",
                           runtime=runtime, config=config)


def _seed(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- 来源解析
def test_parse_source_defaults_and_override(env):
    assert sbm_data_sync.parse_source(env.config) == (sbm_data_sync.DEFAULT_REPO, "main")
    env.config.sbm_data_source = "jing-hy/Arknights-Endfield-Plugin-Secondary-bodyphysics@dev"
    assert sbm_data_sync.parse_source(env.config) == (
        "jing-hy/Arknights-Endfield-Plugin-Secondary-bodyphysics", "dev")
    env.config.sbm_data_source = "只有一段"
    assert sbm_data_sync.parse_source(env.config)[0] == sbm_data_sync.DEFAULT_REPO


# --------------------------------------------------------------- 合并规则
def test_merge_only_adds_missing_keeps_local_values():
    merged, added = sbm_data_sync.merge_characters(LOCAL_DATA, UPSTREAM_DATA)
    assert added == ["chr_0034_typhoea"]
    # 本地调过的角色原样保留
    assert merged["characters"]["chr_0001_aurora"].get("user_tuned") is True
    # 上游那条 tuning 标记不能被上游版本覆盖掉
    assert merged["characters"]["chr_0001_aurora"]["tuned_by"] == "user"
    assert "chr_0034_typhoea" in merged["characters"]


def test_merge_rejects_regression_and_empty():
    merged, added = sbm_data_sync.merge_characters(
        {"characters": {"a": {}, "b": {}}}, {"characters": {"a": {}}})
    assert added == [] and merged["characters"] == {"a": {}, "b": {}}
    merged2, added2 = sbm_data_sync.merge_characters(LOCAL_DATA, {"characters": {}})
    assert added2 == [] and merged2 is LOCAL_DATA


def test_user_preset_is_never_touched():
    files = {repo_path for repo_path, _local, _label in sbm_data_sync.FILES}
    assert files == {
        "SecondaryMotion/data/characters.default.json",
        "SecondaryMotion/presets/Default.json",
    }
    assert not any("User" in name for name in files)


# --------------------------------------------------------------- 整条链路
def test_sync_adds_to_game_dir_and_assets(env, monkeypatch):
    _seed(env.game / "SecondaryMotion" / "data" / "characters.default.json", LOCAL_DATA)
    _seed(env.assets / "data" / "characters.default.json", LOCAL_DATA)
    monkeypatch.setattr(sbm_data_sync, "fetch_text",
                        lambda repo, ref, rel, **kw: json.dumps(UPSTREAM_DATA, ensure_ascii=False))

    report = sbm_data_sync.sync(env.config, force=True)
    assert report["ok"] is True and report["changed"] is True, report
    # `added` 是"两个文件里新补进来的角色 key 合集"：data 那份本地已有 1 个角色，
    # 所以只多出提弗洛斯；presets 那份本地原本没有 → 整份落下来，它也计入 added。
    assert "chr_0034_typhoea" in report["added"]

    for path in (env.game / "SecondaryMotion" / "data" / "characters.default.json",
                 env.assets / "data" / "characters.default.json"):
        data = _read(path)
        assert "chr_0034_typhoea" in data["characters"]
        assert data["characters"]["chr_0001_aurora"].get("user_tuned") is True
        backups = list(path.parent.glob(path.name + ".mc.bak.*"))
        assert len(backups) == 1, "第一次改写要留一份备份"


def test_sync_is_throttled(env, monkeypatch):
    calls: list[int] = []

    def fake(repo, ref, rel, **kw):
        calls.append(1)
        return json.dumps(UPSTREAM_DATA, ensure_ascii=False)

    monkeypatch.setattr(sbm_data_sync, "fetch_text", fake)
    sbm_data_sync.sync(env.config, force=True)
    first_round = len(calls)
    report = sbm_data_sync.sync(env.config)          # 24 小时内第二次
    assert report["skipped"] is True
    assert len(calls) == first_round, "节流命中时不该再发请求"


def test_sync_failure_is_silent_and_keeps_files(env, monkeypatch):
    _seed(env.game / "SecondaryMotion" / "data" / "characters.default.json", LOCAL_DATA)
    before = (env.game / "SecondaryMotion" / "data" / "characters.default.json").read_bytes()

    def boom(repo, ref, rel, **kw):
        raise RuntimeError("网络不通")

    monkeypatch.setattr(sbm_data_sync, "fetch_text", boom)
    logs: list[str] = []
    report = sbm_data_sync.sync(env.config, force=True, log=logs.append)

    assert report["ok"] is False and report["changed"] is False
    assert report["errors"], "失败原因要带回给调用方"
    assert any("乳摇数据检查失败" in line for line in logs)
    assert (env.game / "SecondaryMotion" / "data" / "characters.default.json").read_bytes() == before
    # 失败也要写状态文件（否则每次启动都会重试打网络）
    state = _read(sbm_data_sync.state_path(env.config))
    assert state.get("ok") is False


def test_status_reports_typhoeus(env):
    _seed(env.game / "SecondaryMotion" / "data" / "characters.default.json", UPSTREAM_DATA)
    info = sbm_data_sync.status(env.config)
    assert info["local_characters"] == 2
    assert info["has_typhoeus"] is True
    assert info["repo"] == sbm_data_sync.DEFAULT_REPO
