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


# ------------------------------------------------- 成功跑通就移出崩溃记忆（2026-10-02 用户要求）
def _mem_setup(env, monkeypatch) -> None:
    """打桩掉那些要读真实游戏目录的东西（与上面几个用例同一套）。"""
    monkeypatch.setattr(crashwatch, "collect_game_logs", lambda config, dest: [])
    monkeypatch.setattr(crashwatch, "injection_snapshot", lambda config: {})
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: env.tmp / "no-crashes")
    monkeypatch.setattr(crashwatch, "_crash_sight_lines", lambda config, since=None, limit=4: [])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda config, since=None: [])
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda config, limit=20: [])


def test_combo_succeeded_judgement(env):
    """判据本身：有崩溃转储 ⇒ 不算成功；静默退出（无卸载统计 + 只活一小会儿）也不算。

    用户要求的是「**成功启动没崩**就从记忆里移出」—— 所以"没检测到崩溃"不够，
    「无卸载统计、无 uploadCrash」那档可能是一次闪退，不能拿它当成功。
    """
    assert crashwatch.combo_succeeded({"crash_upload": ["uploadCrash"], "normal_exit": False}) is False
    assert crashwatch.combo_succeeded({"crash_upload": [], "normal_exit": True}) is True
    assert crashwatch.combo_succeeded({"crash_upload": [], "normal_exit": False,
                                       "process": {"alive_seconds": 30}}) is False
    # 没卸载统计也算成功：很多人玩完直接 Alt+F4（实测那些"必崩"的组合都是几十秒内就崩）
    assert crashwatch.combo_succeeded({"crash_upload": [], "normal_exit": False,
                                       "process": {"alive_seconds": 200}}) is True


def test_successful_run_clears_matching_memory(env, monkeypatch):
    """用户原话：「**某一组之前报崩溃的，后面终末地成功启动没崩就从记忆里移出**」。"""
    _mk(env, "MC_A", "MC_B")
    crashwatch.remember_crash(env.config, kind="crash", mods=["MC_A", "MC_B"])
    assert crashwatch.read_crash_memory(env.config), "前提：记忆里本来有一条"

    _mem_setup(env, monkeypatch)
    evidence = crashwatch.collect_evidence(env.config)
    evidence["normal_exit"] = True
    crashwatch.make_bundle(env.config, evidence)

    assert crashwatch.read_crash_memory(env.config) == [], "这套组合跑通了，旧记忆该被移出"
    assert crashwatch.prelaunch_risks(env.config)["blocking"] is False, "移出后不该再提前预警"


def test_unrelated_combo_memory_is_kept(env, monkeypatch):
    """只移出**匹配这套组合**的那条；别的组合的记录必须留着。"""
    _mk(env, "MC_A", "MC_B")
    crashwatch.remember_crash(env.config, kind="crash", mods=["MC_X", "MC_Y"])
    crashwatch.remember_crash(env.config, kind="crash", mods=["MC_A", "MC_B"])

    _mem_setup(env, monkeypatch)
    evidence = crashwatch.collect_evidence(env.config)
    evidence["normal_exit"] = True
    crashwatch.make_bundle(env.config, evidence)

    left = [e["mods"] for e in crashwatch.read_crash_memory(env.config)]
    assert left == [["MC_X", "MC_Y"]], left


def test_failed_run_keeps_memory(env, monkeypatch):
    """这次又崩了 ⇒ 记忆照旧留着（这条路径不能被新逻辑弄坏）。"""
    _mk(env, "MC_A", "MC_B")
    _mem_setup(env, monkeypatch)
    monkeypatch.setattr(crashwatch, "_crash_sight_lines",
                        lambda config, since=None, limit=4: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines",
                        lambda config, since=None: ["uploadCrash"])

    evidence = crashwatch.collect_evidence(env.config)
    crashwatch.make_bundle(env.config, evidence)

    saved = crashwatch.read_crash_memory(env.config)
    assert saved and saved[0]["mods"] == ["MC_A", "MC_B"]


def test_silent_exit_keeps_memory(env, monkeypatch):
    """静默退出（没崩、也没卸载统计、只活 30 秒）⇒ **留着**记忆，别急着当成功清掉。"""
    _mk(env, "MC_A", "MC_B")
    crashwatch.remember_crash(env.config, kind="crash", mods=["MC_A", "MC_B"])
    _mem_setup(env, monkeypatch)

    evidence = crashwatch.collect_evidence(env.config)
    evidence["normal_exit"] = False
    evidence["process"] = {"alive_seconds": 30}
    crashwatch.make_bundle(env.config, evidence)

    assert crashwatch.read_crash_memory(env.config), "静默退出不算成功，记忆要留着"


# --------------------------- 跑通过的组合：静态冲突不再报（2026-10-02 用户要求）
def _conflict_pair(env, monkeypatch, names=("MC_A", "MC_B"),
                   h1: str = "aaaaaaaa", h2: str = "bbbbbbbb") -> None:
    """造一对**真会报冲突**的 staging Mod：两者的 ini 覆盖同样两个资源 hash（只有它们用到）。

    ⚠️ 必须**两个不同的** hash —— 判据要求"至少 2 个独享标识同时相交"（单个相交可能只是巧合）。
    """
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: env.tmp / "library"))
    (env.tmp / "library").mkdir(parents=True, exist_ok=True)
    body = f"[TextureOverride_{h1}_0]\nhash = {h1}\n[TextureOverride_{h2}_1]\nhash = {h2}\n"
    for name in names:
        d = env.staging / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "0.ini").write_text("namespace = T\n" + body, encoding="utf-8")


def test_proven_combo_silences_static_conflict(env, monkeypatch):
    """用户原话：「报了独享标识可能冲突的，**只要能进，都记忆不再报**」。"""
    from endfieldmodcontroller import initialize

    _conflict_pair(env, monkeypatch)

    # ① 常规检测：先如实报出来
    report = initialize.Report()
    initialize._check_mod_conflicts(env.config, report, None)
    first = report.checks[-1]
    assert first["ok"] is False and "覆盖同一批资源" in first["message"], first

    # ② 这套组合**跑通过了**（等价于一次成功启动后的记账）
    assert crashwatch.record_proven_combo(env.config) == ["MC_A", "MC_B"]
    assert crashwatch.conflict_pair_proven(env.config, "MC_A", "MC_B") is True

    # ③ 再检测 —— 这一对不再报，而且如实说明"忽略了 N 条"
    report2 = initialize.Report()
    initialize._check_mod_conflicts(env.config, report2, None)
    second = report2.checks[-1]
    assert second["ok"] is True, second["message"]
    assert "已忽略" in second["message"], second["message"]


def test_pair_never_proven_is_still_reported(env, monkeypatch):
    """只有跑通过的那一对不再报；换一对没跑通过的，照样要报（别把功能一起修没）。"""
    from endfieldmodcontroller import initialize

    _conflict_pair(env, monkeypatch, ("MC_A", "MC_B"), "aaaaaaaa", "bbbbbbbb")
    crashwatch.record_proven_combo(env.config, ["MC_A", "MC_B"])
    _conflict_pair(env, monkeypatch, ("MC_C", "MC_D"), "cccccccc", "dddddddd")   # 从没一起跑通过

    report = initialize.Report()
    initialize._check_mod_conflicts(env.config, report, None)
    msg = report.checks[-1]["message"]

    assert "MC_C" in msg and "MC_D" in msg, msg
    assert "MC_A" not in msg and "MC_B" not in msg, "跑通过的那一对不该再出现"


def test_proven_combo_roundtrip(env):
    """台账本身的读写、排序与去重。"""
    assert crashwatch.proven_combos(env.config) == []
    crashwatch.record_proven_combo(env.config, ["B", "A"])
    crashwatch.record_proven_combo(env.config, ["A", "B"])      # 同一套只留一条
    assert crashwatch.proven_combos(env.config) == [["A", "B"]]
    assert crashwatch.conflict_pair_proven(env.config, "A", "B") is True
    assert crashwatch.conflict_pair_proven(env.config, "A", "C") is False
    assert crashwatch.record_proven_combo(env.config, ["A"]) == [], "单 Mod 不成组合"
