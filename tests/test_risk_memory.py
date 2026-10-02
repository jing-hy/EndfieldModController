"""崩溃记忆 + 「一键启动前风险确认」的离线单测。

用户 2026-09-30 的要求：**一键启动时检测 + 崩溃记忆，如果可能会崩就在启动前弹窗，
说明是什么冲突、让用户确认是否继续启动**。这里测的是后端那半：

* `crashwatch.staging_mods()` 扫当前 staging（排掉控制器自己的目录）；
* `remember_crash()` / `read_crash_memory()` 写读与去重；
* `prelaunch_risks()` 的两条判据（自检落盘的静态冲突 / 历史崩溃组合记忆）与
  "不相关组合不误报"；
* 崩溃包生成时自动写入记忆。

全部离线：路径都 patch 到 tmp_path，不碰真实游戏目录与真实 runtime。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import crashwatch, diagnostics
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    staging = tmp_path / "runtime" / "EFMI" / "Mods"
    staging.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "staging_mods_path", property(lambda self: staging))
    # `dlss5_path` 也要打桩：崩溃归因现在会读 `runtime\dlss5\dlss5-feed.log` 里插件自己写的
    # CRASH RECORDED，不打桩就会读到**开发机上真实的**那份日志（2026-10-02 实测踩到）。
    monkeypatch.setattr(AppConfig, "dlss5_path",
                        property(lambda self: tmp_path / "runtime" / "dlss5"))
    return SimpleNamespace(config=config, staging=staging, tmp=tmp_path)


def _mk(env, *names: str) -> None:
    for name in names:
        (env.staging / name).mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------- staging 扫描
def test_staging_mods_skips_controller_dirs(env):
    _mk(env, "MC_A", "MC_B", "MC_Controller", "DISABLED", "EndfieldModControllerManaged")
    (env.staging / "MC_Probe.ini").write_text("", encoding="utf-8")
    assert crashwatch.staging_mods(env.config) == ["MC_A", "MC_B"]


# --------------------------------------------------------------- 记忆读写
def test_remember_and_read(env):
    _mk(env, "MC_A", "MC_B")
    entry = crashwatch.remember_crash(env.config, kind="mod_conflict", detail="A 与 B 冲突")
    assert entry["mods"] == ["MC_A", "MC_B"]
    saved = crashwatch.read_crash_memory(env.config)
    assert len(saved) == 1
    assert saved[0]["kind"] == "mod_conflict"
    assert saved[0]["at_text"]


def test_same_combo_keeps_latest_only(env):
    _mk(env, "MC_A", "MC_B")
    crashwatch.remember_crash(env.config, kind="crash", detail="第一次")
    crashwatch.remember_crash(env.config, kind="mod_conflict", detail="第二次")
    saved = crashwatch.read_crash_memory(env.config)
    assert len(saved) == 1 and saved[0]["detail"] == "第二次"


def test_different_combos_both_kept(env):
    _mk(env, "MC_A", "MC_B")
    crashwatch.remember_crash(env.config, kind="crash", detail="组合一")
    crashwatch.remember_crash(env.config, kind="crash", detail="组合二", mods=["MC_X", "MC_Y"])
    assert len(crashwatch.read_crash_memory(env.config)) == 2


# --------------------------------------------------------------- 风险判定
def test_blocking_from_static_conflict(env):
    _mk(env, "MC_A", "MC_B")
    detail = "「MC_A」与「MC_B」覆盖同一批资源（31 个独享标识: g:1, h:2…）"
    diagnostics.record_mod_conflicts(env.config, ok=False, detail=detail, conflicts=[detail])
    risks = crashwatch.prelaunch_risks(env.config)
    assert risks["blocking"] is True
    assert risks["conflicts"] == [detail]
    assert risks["checked_at"]


def test_blocking_from_memory_superset(env):
    """崩过的组合是 {A,B}，现在 {A,B,C} —— 多勾一个照样提醒。"""
    _mk(env, "MC_A", "MC_B")
    crashwatch.remember_crash(env.config, kind="mod_conflict", detail="崩过")
    diagnostics.record_mod_conflicts(env.config, ok=True, detail="", conflicts=[])
    _mk(env, "MC_C")
    risks = crashwatch.prelaunch_risks(env.config)
    assert risks["blocking"] is True
    assert risks["memories"] and risks["memories"][0]["kind"] == "mod_conflict"


def test_blocking_from_memory_subset(env):
    """崩过的组合是 {A,B,C}，现在 {A,B} —— 少勾一个也提醒。"""
    _mk(env, "MC_A", "MC_B", "MC_C")
    crashwatch.remember_crash(env.config, kind="crash", detail="崩过")
    (env.staging / "MC_C").rmdir()
    assert crashwatch.prelaunch_risks(env.config)["blocking"] is True


def test_not_blocking_when_clean(env):
    _mk(env, "MC_A", "MC_B")
    diagnostics.record_mod_conflicts(env.config, ok=True, detail="", conflicts=[])
    crashwatch.remember_crash(env.config, kind="crash", detail="另一套崩过", mods=["MC_X", "MC_Y"])
    risks = crashwatch.prelaunch_risks(env.config)
    assert risks["blocking"] is False
    assert risks["conflicts"] == [] and risks["memories"] == []


def test_single_mod_combo_never_matches(env):
    """单 Mod 的组合不参与预警（一个 Mod 自己崩通常是别的原因，提示了是噪音）。"""
    _mk(env, "MC_A")
    crashwatch.remember_crash(env.config, kind="crash", detail="单 Mod 崩过", mods=["MC_A"])
    assert crashwatch.prelaunch_risks(env.config)["blocking"] is False


def test_staging_mods_excludes_dependencies_by_default(env):
    """**依赖不算"用户选的 Mod"**（用户 2026-10-02：「MC_RabbitFX 不属于 mod，应该算依赖」）。"""
    _mk(env, "MC_佩丽卡_佩丽卡-OL装", "MC_RabbitFX -ENDMI-_RabbitFX -ENDMI-")
    assert crashwatch.staging_mods(env.config) == ["MC_佩丽卡_佩丽卡-OL装"]
    assert crashwatch.staging_mods(env.config, include_dependencies=True) == [
        "MC_RabbitFX -ENDMI-_RabbitFX -ENDMI-",
        "MC_佩丽卡_佩丽卡-OL装",
    ]


def test_no_false_alarm_when_only_one_skin_with_a_dependency(env):
    """只勾一个皮肤时，不该因为"按需激活把 RabbitFX 带进了 staging"而命中旧的三件套记忆。"""
    _mk(env, "MC_佩丽卡_佩丽卡-OL装", "MC_RabbitFX -ENDMI-_RabbitFX -ENDMI-")
    crashwatch.remember_crash(
        env.config, kind="crash",
        mods=["MC_RabbitFX -ENDMI-_RabbitFX -ENDMI-", "MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍"],
    )
    risks = crashwatch.prelaunch_risks(env.config)
    assert risks["blocking"] is False, risks
    # 但真把三个都选上时，仍然要能命中那条记忆（别把功能一起修没了）
    _mk(env, "MC_庄方宜_旗袍")
    crashwatch.remember_crash(
        env.config, kind="crash",
        mods=["MC_RabbitFX -ENDMI-_RabbitFX -ENDMI-", "MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍"],
    )
    assert crashwatch.prelaunch_risks(env.config)["blocking"] is True


# --------------------------------------------------------------- 崩溃时自动记忆
def test_make_bundle_records_memory(env, monkeypatch):
    _mk(env, "MC_A", "MC_B")
    monkeypatch.setattr(crashwatch, "collect_game_logs", lambda config, dest: [])
    monkeypatch.setattr(crashwatch, "injection_snapshot", lambda config: {})
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: env.tmp / "no-crashes")
    monkeypatch.setattr(crashwatch, "_crash_sight_lines", lambda config, since=None, limit=4: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda config, since=None: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda config, limit=20: [])

    evidence = crashwatch.collect_evidence(env.config)
    bundle = crashwatch.make_bundle(env.config, evidence)
    assert (bundle.get("cause") or {}).get("kind") == "crash"
    saved = crashwatch.read_crash_memory(env.config)
    assert saved and saved[0]["mods"] == ["MC_A", "MC_B"]
    assert Path(crashwatch.crash_memory_path(env.config)).is_file()


def test_normal_exit_is_not_remembered(env, monkeypatch):
    """正常退出不该进崩溃记忆（否则用户每次正常退出都被下次启动警告）。"""
    _mk(env, "MC_A", "MC_B")
    monkeypatch.setattr(crashwatch, "collect_game_logs", lambda config, dest: [])
    monkeypatch.setattr(crashwatch, "injection_snapshot", lambda config: {})
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: env.tmp / "no-crashes")
    monkeypatch.setattr(crashwatch, "_crash_sight_lines", lambda config, since=None, limit=4: [])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda config, since=None: [])
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda config, limit=20: [])

    evidence = crashwatch.collect_evidence(env.config)
    evidence["normal_exit"] = True
    bundle = crashwatch.make_bundle(env.config, evidence)
    assert (bundle.get("cause") or {}).get("kind") == "exit"
    assert crashwatch.read_crash_memory(env.config) == []
