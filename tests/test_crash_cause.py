"""崩溃归因（Mod 冲突 vs 其它）与随包组件基线校验的离线单测。

都是 2026-09-30 那轮加的东西：
* 崩溃弹窗要能区分「确定是 Mod 冲突」与其它崩溃（用户要求：确定是 mod 冲突要区别于
  其他崩溃情况的弹窗）；
* 自检要能发现 `runtime\\dlss5` 里的随包组件被别的整合包换过（一个 issue 的教训）；
* 崩溃包/诊断包要收 DLSS5 现场（`dlss5-feed.log`），否则反馈里只能靠猜。

全部离线：不联网、不碰真实游戏目录，路径都指到 tmp_path。
"""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import crashwatch, diagnostics, runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: tmp_path / "dlss5"))
    (tmp_path / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    dlss5 = tmp_path / "dlss5"
    dlss5.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(tmp=tmp_path, config=config, dlss5=dlss5)


def _crashed() -> dict:
    """CrashSight 上传了崩溃转储 = 真崩溃（见 crashwatch.is_crash 的判据）。"""
    return {"crash_upload": ["uploadCrash"], "normal_exit": False}


# --------------------------------------------------------------- 崩溃归因
def test_mod_conflict_wins_over_generic_crash(env):
    diagnostics.record_mod_conflicts(
        env.config, ok=False,
        detail="「MC_A」与「MC_B」覆盖同一批资源（2 个独享标识: h:1, h:2…）",
        conflicts=["「MC_A」与「MC_B」覆盖同一批资源（2 个独享标识: h:1, h:2…）"],
    )
    cause = crashwatch.classify_cause(env.config, _crashed())
    assert cause["kind"] == "mod_conflict"
    assert "MC_A" in cause["detail"]
    assert cause["conflicts"] and cause["title"]
    assert cause["crashed"] is True


def test_crash_without_conflict_stays_generic(env):
    diagnostics.record_mod_conflicts(env.config, ok=True, detail="", conflicts=[])
    cause = crashwatch.classify_cause(env.config, _crashed())
    assert cause["kind"] == "crash"
    assert cause["title"] == "检测到终末地异常退出"
    assert cause["conflicts"] == []


def test_no_conflict_record_at_all_stays_generic(env):
    cause = crashwatch.classify_cause(env.config, _crashed())
    assert cause["kind"] == "crash"


def test_normal_exit_is_not_crash(env):
    diagnostics.record_mod_conflicts(env.config, ok=False, detail="x", conflicts=["x"])
    cause = crashwatch.classify_cause(env.config, {"normal_exit": True})
    assert cause["kind"] == "exit"
    assert cause["crashed"] is False


def test_stale_conflict_record_is_ignored(env):
    """很久以前的冲突记录不该给这次崩溃背锅（默认 6 小时窗口）。"""
    diagnostics.record_mod_conflicts(env.config, ok=False, detail="旧记录", conflicts=["旧记录"])
    path = diagnostics.mod_conflict_state_path(env.config)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["at"] = int(time.time() - 12 * 3600)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    cause = crashwatch.classify_cause(env.config, _crashed(), started_at=time.time())
    assert cause["kind"] == "crash"


def test_report_and_bundle_carry_the_cause(env, monkeypatch):
    monkeypatch.setattr(crashwatch, "collect_game_logs", lambda config, dest: [])
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: env.tmp / "no-crashes")
    monkeypatch.setattr(crashwatch, "_crash_sight_lines", lambda config, since=None, limit=4: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda config, since=None: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda config, limit=20: [])
    diagnostics.record_mod_conflicts(env.config, ok=False, detail="「MC_A」与「MC_B」冲突", conflicts=["「MC_A」与「MC_B」冲突"])

    evidence = crashwatch.collect_evidence(env.config)
    text = crashwatch._render_report(evidence)
    assert "归因" in text and "Mod 资源冲突" in text

    result = crashwatch.make_bundle(env.config, evidence)
    assert result["cause"]["kind"] == "mod_conflict"
    cause_file = Path(result["dir"]) / "cause.json"
    assert cause_file.is_file()
    assert json.loads(cause_file.read_text(encoding="utf-8"))["kind"] == "mod_conflict"


# --------------------------------------------------------------- 随包组件基线
def _sparse_files(directory: Path, sizes: dict[str, int]) -> None:
    """按给定大小造稀疏文件（不真写字节，快）。"""
    for name, size in sizes.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.truncate(size)


def _baseline_sizes(env) -> dict[str, int]:
    sizes = {name: int(entry.get("size") or 0)
             for _group, _root, name, entry in runtime_assets.manifest_entries(env.config)}
    sizes[runtime_assets.FEED_NAME] = runtime_assets.FEED_BASELINE_SIZE
    return sizes


def test_baseline_ok_when_sizes_match(env):
    _sparse_files(env.dlss5, _baseline_sizes(env))
    summary = runtime_assets.baseline_summary(env.config)
    assert summary["ok"] is True, summary["detail"]


def test_baseline_flags_missing_files(env):
    _sparse_files(env.dlss5, {runtime_assets.FEED_NAME: runtime_assets.FEED_BASELINE_SIZE})
    summary = runtime_assets.baseline_summary(env.config)
    assert summary["ok"] is False
    assert any(item["kind"] == "missing" for item in summary["mismatches"])


def test_baseline_flags_replaced_feed(env):
    """feed 与随包不同（大小 ≠ 76,800）时要被点名。

    ⚠ 只断言"被点名"，**不断言"不会出帧"** —— 2026-09-30 实测 0.1.0（76,800 B）与
    1.18.0-beta.1（332,800 B）在终末地上都能正常出帧，所以这条只是差异提示。
    """
    sizes = _baseline_sizes(env)
    sizes[runtime_assets.FEED_NAME] = 332_800
    _sparse_files(env.dlss5, sizes)
    summary = runtime_assets.baseline_summary(env.config)
    assert summary["ok"] is False
    assert any(item["name"] == runtime_assets.FEED_NAME for item in summary["mismatches"])
    assert "与随包的版本不同" in summary["detail"]


def test_baseline_flags_wrong_sized_addon(env):
    sizes = _baseline_sizes(env)
    target = "renodx-endfield-enhancer.addon64"
    sizes[target] = sizes[target] + 1024
    _sparse_files(env.dlss5, sizes)
    summary = runtime_assets.baseline_summary(env.config)
    assert summary["ok"] is False
    assert any(item["name"] == target and item["kind"] == "size" for item in summary["mismatches"])


# --------------------------------------------------------------- 诊断包
def test_diagnostic_bundle_includes_dlss5_scene(env, monkeypatch):
    monkeypatch.setattr(diagnostics, "_capture_windows_events", lambda config: None)
    (env.dlss5 / "dlss5-feed.log").write_text("feed: frame 1 delivered\n", encoding="utf-8")
    (env.dlss5 / "ReShade.ini").write_text("[GENERAL]\n", encoding="utf-8")
    (env.dlss5 / "dlss5-feed.cfg").write_text("k=v\n", encoding="utf-8")
    diagnostics.record_mod_conflicts(env.config, ok=False, detail="A 与 B 冲突", conflicts=["A 与 B 冲突"])

    out = diagnostics.create_diagnostic_bundle(env.config)
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
    assert "dlss5/dlss5-feed.log" in names
    assert "dlss5/ReShade.ini" in names
    assert "dlss5/dlss5-feed.cfg" in names
    assert "mod_conflicts.json" in names
