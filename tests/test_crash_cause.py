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
import os
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
    # staging 也要打桩：崩溃记忆会读当前 staging 里的 Mod 名单，不打桩就会读到
    # **开发机上真实的** `runtime\builtin\XXMI\EFMI\Mods`（同一个坑第三次踩到）。
    monkeypatch.setattr(AppConfig, "staging_mods_path",
                        property(lambda self: tmp_path / "runtime" / "EFMI" / "Mods"))
    (tmp_path / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / "EFMI" / "Mods").mkdir(parents=True, exist_ok=True)
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


def test_baseline_accepts_both_known_feed_versions(env):
    """**两个已知可用的 feed 版本都不该报警**（2026-10-02 改成"已知可用集合"）。

    用户反馈这条每次自检都报、纯属噪音 —— 0.1.0（76,800 B）与 1.18.0-beta.1（332,800 B）
    在终末地上都能正常出帧，装哪个都不算异常。
    """
    for size in (76_800, 332_800):
        sizes = _baseline_sizes(env)
        sizes[runtime_assets.FEED_NAME] = size
        _sparse_files(env.dlss5, sizes)
        summary = runtime_assets.baseline_summary(env.config)
        assert summary["ok"] is True, f"{size} B 属于已知可用版本，不该报警: {summary['detail']}"


def test_baseline_flags_unknown_feed_version(env):
    """落在已知集合**之外**的 feed 才提醒。

    ⚠ 只断言"被点名"，**不断言"不会出帧"** —— 它是在线组件，允许用户换版本。
    """
    sizes = _baseline_sizes(env)
    sizes[runtime_assets.FEED_NAME] = 999_999
    _sparse_files(env.dlss5, sizes)
    summary = runtime_assets.baseline_summary(env.config)
    assert summary["ok"] is False
    assert any(item["name"] == runtime_assets.FEED_NAME for item in summary["mismatches"])
    assert "不在已知可用的版本" in summary["detail"]


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


def test_xxmi_summary_reads_launcher_section(env, monkeypatch):
    """诊断摘要里的 `active_importer` 在 **`Launcher`** 段，不是 `Config` 段。

    2026-10-02 反馈者诊断包定位：读错段会让这一行**永远**打印 `None` —— 本机正常环境
    （`Launcher.active_importer == 'EFMI'`）也一样，等于每次排查都被自己的摘要带偏，
    历史上还被当成"XXMI 没写进去"的证据用过。
    """
    launcher = env.tmp / "XXMI" / "Resources" / "Bin" / "XXMI Launcher.exe"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_bytes(b"MZ")
    config_path = env.tmp / "XXMI" / "XXMI Launcher Config.json"
    config_path.write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI", "enabled_importers": ["EFMI"]},
        "Importers": {"EFMI": {"Importer": {
            "extra_libraries_enabled": True,
            "extra_libraries": str(env.dlss5 / "d3d12.dll"),
            "extra_libraries_signature": "s" * 140,
        }}},
        "Security": {"user_signature": "u" * 140},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(AppConfig, "xxmi_launcher_path", property(lambda self: launcher))

    text = "\n".join(diagnostics._xxmi_summary(env.config))
    assert "active_importer   : 'EFMI'" in text, text
    assert "enabled_importers : ['EFMI']" in text, text
    assert "None" not in text, text


# --------------------------------------------------- 硬证据优先（2026-10-02 用户反馈后加的）
def test_dlss5_crash_record_beats_static_conflict(env):
    """插件自己记下的崩溃（**实测证据**）压过"自检发现资源相交"（静态推测）。

    2026-10-02 用户现场：用 NRStyle=2 崩的那次被归成了"Mod 资源冲突"，弹窗还催他去清理 Mod。
    """
    diagnostics.record_mod_conflicts(
        env.config, ok=False, detail="「MC_A」与「MC_B」覆盖同一批资源",
        conflicts=["「MC_A」与「MC_B」覆盖同一批资源（2 个独享标识: h:1, h:2…）"],
    )
    (env.dlss5 / "dlss5-feed.log").write_text(
        "11:47:05.434  ### CRASH RECORDED ###  exception 0xC0000005 (reading address 0000000000000020) "
        "at 00007FFC6E247EC5 in C:\\WINDOWS\\System32\\DriverStore\\FileRepository\\nv_dispi_x\\nvgpucomp64.dll; "
        "this add-on was last doing: D3D11 output blit complete (later faults in this process are not recorded)\n",
        encoding="utf-8",
    )
    (env.dlss5 / "ReShade.ini").write_text(
        "[GENERAL]\nA=1\n\n[RenoDX.DLSS5]\nNeuralUplift=1\nNRStyle=2\n", encoding="utf-8",
    )
    cause = crashwatch.classify_cause(env.config, _crashed())
    # ⚠ "是 NRStyle=2 引起这次崩溃"那条**因果断言已删除**（2026-10-02，实测 0 也崩；
    # 当天更晚定案的真因是 RabbitFX 进了 staging）→ 现在归到"崩在显卡着色器编译器"
    # 这个**事实陈述**上。
    assert cause["kind"] == "gpu_compiler"
    assert "nvgpucomp64" in cause["title"] and "不是 Mod 冲突" in cause["title"]
    assert cause["conflicts"], "静态检出的相交信息不该丢，只是不再当结论"


def test_nrstyle_never_produces_its_own_cause(env):
    """即使 NRStyle=2 且崩在 nvgpucomp64，也**不再**归因成 `dlss5_nr_style`。"""
    (env.dlss5 / "dlss5-feed.log").write_text(
        "11:47:05.434  ### CRASH RECORDED ###  exception 0xC0000005 (reading address 0000000000000020) "
        "at 00007FFC6E247EC5 in C:\\x\\nvgpucomp64.dll; this add-on was last doing: D3D11 output blit complete\n",
        encoding="utf-8",
    )
    (env.dlss5 / "ReShade.ini").write_text("[RenoDX.DLSS5]\nNRStyle=2\n", encoding="utf-8")
    cause = crashwatch.classify_cause(env.config, _crashed())
    assert cause["kind"] == "gpu_compiler"
    assert "NRStyle" not in cause["title"]


def test_gpu_compiler_crash_when_nrstyle_is_not_two(env):
    (env.dlss5 / "dlss5-feed.log").write_text(
        "12:00:00.000  ### CRASH RECORDED ###  exception 0xC0000005 (reading address 20) "
        "at 00007FFC6E247EC5 in C:\\x\\nvgpucomp64.dll; this add-on was last doing: D3D11 output blit complete\n",
        encoding="utf-8",
    )
    (env.dlss5 / "ReShade.ini").write_text("[RenoDX.DLSS5]\nNRStyle=0\n", encoding="utf-8")
    cause = crashwatch.classify_cause(env.config, _crashed())
    assert cause["kind"] == "gpu_compiler"
    assert "nvgpucomp64" in cause["title"]


def test_stale_crash_record_is_not_counted(env):
    """日志里那条记录是**上一次**崩溃留下的 → 不能算到这次头上。"""
    log = env.dlss5 / "dlss5-feed.log"
    log.write_text(
        "### CRASH RECORDED ###  exception 0xC0000005 at 0x1 in C:\\x\\nvgpucomp64.dll\n",
        encoding="utf-8",
    )
    old = time.time() - 3600
    os.utime(log, (old, old))
    cause = crashwatch.classify_cause(env.config, _crashed())
    assert cause["kind"] == "crash"


def test_dlss5_crash_record_helper_parses_module(env):
    (env.dlss5 / "dlss5-feed.log").write_text(
        "### CRASH RECORDED ###  exception 0xC0000005 (reading address 0000000000000020) "
        "at 00007FFC6E247EC5 in D:\\x\\nvgpucomp64.dll; this add-on was last doing: D3D11 output blit complete\n",
        encoding="utf-8",
    )
    record = crashwatch.dlss5_crash_record(env.config)
    assert record and record["module"].lower() == "nvgpucomp64.dll"
    assert record["gpu_compiler"] is True
    assert "D3D11 output blit" in record["doing"]


def test_gpu_compiler_crash_is_still_remembered(env, monkeypatch):
    """**归因类型不该决定"记不记"**：`gpu_compiler` 也要进崩溃记忆。

    2026-10-02 现场踩到：归因新增 `gpu_compiler` 后，那两类崩溃一条都没被记下来
    （`crash_memory.json` 里没有新条目），因为白名单还是 `{"crash", "mod_conflict"}`。
    """
    (env.tmp / "runtime" / "EFMI" / "Mods" / "MC_佩丽卡_皮肤").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(crashwatch, "collect_game_logs", lambda config, dest: [])
    monkeypatch.setattr(crashwatch, "injection_snapshot", lambda config: {})
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: env.tmp / "no-crashes")
    monkeypatch.setattr(crashwatch, "_crash_sight_lines", lambda config, since=None, limit=4: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda config, since=None: ["uploadCrash"])
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda config, limit=20: [])
    (env.dlss5 / "dlss5-feed.log").write_text(
        "### CRASH RECORDED ###  exception 0xC0000005 (reading address 20) "
        "at 0x7FF in C:\\x\\nvgpucomp64.dll; this add-on was last doing: D3D11 output blit complete\n",
        encoding="utf-8",
    )
    evidence = crashwatch.collect_evidence(env.config)
    bundle = crashwatch.make_bundle(env.config, evidence)
    assert (bundle.get("cause") or {}).get("kind") == "gpu_compiler"
    saved = crashwatch.read_crash_memory(env.config)
    assert saved, "gpu_compiler 这类崩溃也必须进崩溃记忆"
    assert saved[0]["mods"] == ["MC_佩丽卡_皮肤"]


# ------------------------------------------------- 崩溃判据一致性（2026-10-02）
def test_reportexception_alone_is_not_a_crash(env, monkeypatch):
    """CrashSight 里**只有 `reportException`**（游戏内被捕获的异常）不算崩溃。

    用户正常关窗口时它每次都打（实测 18:21 / 18:25 关窗口 → 6 条 reportException、
    没有 uploadCrash）。外部反馈 #11 的「崩溃判定: CrashSight 记录到异常」就是拿它误判的
    —— 而**同一份日志**里控制器写的是「未检测到崩溃（正常退出）」。
    """
    monkeypatch.setattr(crashwatch, "_crash_root", lambda: env.tmp / "no-crashes")
    monkeypatch.setattr(crashwatch, "injection_snapshot", lambda config: {})
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda config, limit=20: [])
    monkeypatch.setattr(crashwatch, "_crash_sight_lines",
                        lambda config, since=None, limit=4: ["reportException", "reportException"])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda config, since=None: [])

    evidence = crashwatch.collect_evidence(env.config)

    assert evidence["crash_sight"], "前提：CrashSight 确实留下了记录"
    assert crashwatch.is_crash(evidence) is False


def test_collect_crash_report_judges_by_uploadcrash_only():
    """`api.collect_crash_report` 的 `crashed` 不许再用 `crash_sight`（防回归）。

    它原本是 `bool(evidence.get("crash_sight"))` —— 于是"CrashSight 目录里有记录"就算崩溃，
    与包内报告、崩溃监控（两处都走 `is_crash`，只认 uploadCrash）判据不一致，
    会让用户在**根本没崩**的情况下被弹窗告知"崩溃 + Mod 资源冲突"。
    """
    root = Path(__file__).resolve().parents[1]
    source = (root / "endfieldmodcontroller" / "api.py").read_text(encoding="utf-8")
    start = source.index("def collect_crash_report")
    end = source.index("\n    def ", start + 10)
    block = "\n".join(line.split("#", 1)[0] for line in source[start:end].splitlines())

    assert "crashwatch.is_crash(" in block, "collect_crash_report 必须用 crashwatch.is_crash 判崩溃"
    assert "crash_sight" not in block, "不许再用 crash_sight 判崩溃（reportException 会被误判成崩溃）"
