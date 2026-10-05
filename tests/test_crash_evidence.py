"""崩溃取证的回归测试（v1.0.11 补的 WER 判据 + 「崩溃后给出下一步」）。

**为什么要单独一组**：2026-10-05 的一份诊断包里 **8 次真实崩溃全被判成"未发现崩溃迹象"** ——
因为终末地的崩溃处理器会把异常吞掉、CrashSight 只留 `reportException`，而我们原来只认
`uploadCrash`。同时按用户要求，崩溃之后**不许卸功能**，只能给出"清空依赖并重新下载"这条
可点的下一步。四条判据都要钉住：

1. WER 报告（`Sig[3]` = 故障模块）算**真崩溃**；
2. 但**有正常退出卸载统计时优先判正常**（别把"手动关窗口"说成崩溃）；
3. 建议**只在崩溃点落在图形 / 注入链**（dxgi / d3d11 / d3d12 / nvngx…）时给 —— 崩在
   `unityplayer` 这类游戏自己的模块上，重装依赖是白折腾；
4. 建议要**真的进崩溃包与崩溃报告**（前端弹窗与事后翻日志都靠它）。

全部离线：不联网、不碰真实游戏目录 / 真实 WER 目录，路径都指到 tmp_path。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import crashwatch, diagnostics
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: tmp_path / "dlss5"))
    monkeypatch.setattr(AppConfig, "staging_mods_path",
                        property(lambda self: tmp_path / "runtime" / "EFMI" / "Mods"))
    for path in (tmp_path / "runtime" / "logs", tmp_path / "dlss5",
                 tmp_path / "runtime" / "EFMI" / "Mods"):
        path.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(tmp=tmp_path, config=config, dlss5=tmp_path / "dlss5")


def _wer_file(directory: Path, *, module: str, mtime: float, name: str = "AppCrash_x.wer") -> Path:
    """造一份真的 WER 报告（UTF-16LE，与 Windows 写出来的编码一致）。"""
    path = directory / name
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Version=1\n"
        "EventType=APPCRASH\n"
        "Sig[0].Name=应用程序名\nSig[0].Value=Endfield.exe\n"
        "Sig[3].Name=故障模块名称\n"
        f"Sig[3].Value={module}\n"
        "Sig[6].Value=c0000005\n",
        encoding="utf-16",
    )
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def wer_dir(tmp_path, monkeypatch):
    """把 WER 报告目录换成 tmp（绝不读这台机器真实的 WER 归档）。"""
    directory = tmp_path / "wer"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(diagnostics, "wer_report_paths", lambda limit=8: sorted(directory.glob("*.wer")))
    return directory


# ---------------------------------------------------------------------------
# ① WER 判据
# ---------------------------------------------------------------------------
def test_wer_report_counts_as_crash():
    evidence = {"crash_upload": [], "normal_exit": False, "wer_crash": True}
    assert crashwatch.is_crash(evidence) is True


def test_normal_exit_beats_wer():
    """有卸载统计 ⇒ 正常退出，哪怕同一次运行里出现过 WER 记录。"""
    evidence = {"crash_upload": [], "normal_exit": True, "wer_crash": True}
    assert crashwatch.is_crash(evidence) is False


def test_wer_modules_parsed_and_time_filtered(env, monkeypatch, wer_dir):
    started = time.time()
    _wer_file(wer_dir, module=r"D:\Game\dxgi.dll", mtime=started + 1)          # 本次运行期间
    _wer_file(wer_dir, module="nvgpucomp64.dll", mtime=started - 3600, name="AppCrash_old.wer")

    assert crashwatch.wer_crash_modules(started) == ["dxgi.dll"], "只认本次运行时段的报告，且取 basename"


def test_wer_modules_empty_without_reports(env, wer_dir):
    assert crashwatch.wer_crash_modules(time.time()) == []


# ---------------------------------------------------------------------------
# ② 故障模块归并（DLSS5 插件自己的记录 + WER）
# ---------------------------------------------------------------------------
def test_fault_modules_merges_and_dedupes(env):
    evidence = {"dlss5_crash": {"module": "dxgi.dll"}, "wer_modules": ["DXGI.DLL", "d3d11.dll"]}
    assert crashwatch.fault_modules(env.config, evidence) == ["dxgi.dll", "d3d11.dll"]


def test_fault_modules_reads_dlss5_log_when_evidence_missing(env):
    """`evidence` 里没有时回落到读 `dlss5-feed.log` 的 CRASH RECORDED（真实格式就是一整行）。"""
    (env.dlss5 / "dlss5-feed.log").write_text(
        "11:47:05.434  ### CRASH RECORDED ###  exception 0xC0000005 (reading address FFFFFFFFFFFFFFFF)"
        " at 00007FFACD5BA816 in D:\\Game\\dxgi.dll; this add-on was last doing: nothing yet\n",
        encoding="utf-8")
    modules = crashwatch.fault_modules(env.config, {"_started_at": time.time()})
    assert modules and modules[0] == "dxgi.dll"


# ---------------------------------------------------------------------------
# ③ 建议：只在图形 / 注入链那层给
# ---------------------------------------------------------------------------
def _crashed_on(module: str, *, alive: float = 67.0) -> dict:
    return {
        "crash_upload": [], "normal_exit": False, "wer_crash": True,
        "wer_modules": [module], "dlss5_crash": {}, "process": {"alive_seconds": alive},
    }


def test_crash_advice_offered_for_graphics_layer(env):
    advice = crashwatch.crash_advice(env.config, _crashed_on("dxgi.dll"))
    assert advice["action"] == "reset_dependencies_and_redownload"
    assert advice["fault_modules"] == ["dxgi.dll"]
    assert "清空依赖" in advice["message"] and "Mod 库" in advice["message"]


def test_crash_advice_not_offered_for_game_modules(env):
    """崩在游戏自己的模块上 ⇒ 不给重装建议（那是白折腾，且会让用户以为能修好）。"""
    assert crashwatch.crash_advice(env.config, _crashed_on("unityplayer.dll")) == {}


def test_crash_advice_not_offered_for_normal_exit(env):
    evidence = dict(_crashed_on("dxgi.dll"), normal_exit=True)
    assert crashwatch.crash_advice(env.config, evidence) == {}


def test_crash_advice_does_not_touch_function_switches(env):
    """**不卸功能**：给建议的过程不许改任何插件开关（用户明确要求的红线）。"""
    before = (env.config.dlss5_addon_enabled, env.config.firstperson_addon_enabled)
    crashwatch.crash_advice(env.config, _crashed_on("dxgi.dll"))
    after = (env.config.dlss5_addon_enabled, env.config.firstperson_addon_enabled)
    assert before == after
    assert not hasattr(crashwatch, "apply_addon_guard"), "自动停用插件那条路必须已经撤掉"


# ---------------------------------------------------------------------------
# ④ 建议要真的进崩溃包与报告
# ---------------------------------------------------------------------------
def test_make_bundle_puts_advice_into_result_and_report(env, monkeypatch, wer_dir):
    started = time.time()
    _wer_file(wer_dir, module="dxgi.dll", mtime=started + 1)
    # 打桩掉所有"读这台机器真实环境"的收集步骤（本测试只关心 advice 有没有落地）
    for name in ("_collect_event_log", "_collect_mods_tree", "_collect_crash_dumps",
                 "_collect_full_game_logs", "_collect_xxmi_log",
                 "_collect_extra_evidence", "_collect_game_config"):
        monkeypatch.setattr(crashwatch, name, lambda *a, **k: None, raising=False)
    monkeypatch.setattr(crashwatch, "collect_game_logs", lambda *a, **k: [])   # 返回值要参与 len()
    monkeypatch.setattr(crashwatch, "_crash_sight_lines", lambda *a, **k: [])
    monkeypatch.setattr(crashwatch, "_crash_sight_upload_lines", lambda *a, **k: [])
    monkeypatch.setattr(crashwatch, "_normal_exit_marker", lambda: False)
    monkeypatch.setattr(crashwatch, "_extract_game_errors", lambda *a, **k: [])

    evidence = crashwatch.collect_evidence(env.config, started_at=started,
                                          exit_time=started + 67, alive_seconds=67)
    assert evidence["wer_crash"] is True and evidence["wer_modules"] == ["dxgi.dll"]

    bundle = crashwatch.make_bundle(env.config, evidence)

    assert bundle["crashed"] is True
    assert bundle["advice"]["action"] == "reset_dependencies_and_redownload"
    report = Path(bundle["bundle"]) / "controller-crash-report.log"
    assert "崩溃后的建议" in report.read_text(encoding="utf-8")

    # 前端拿的是 `take_bundle()` 那一份 —— 它必须带着同一条建议
    crashwatch._WATCH["bundle"] = bundle
    assert (crashwatch.take_bundle() or {}).get("advice", {}).get("action") \
        == "reset_dependencies_and_redownload"
