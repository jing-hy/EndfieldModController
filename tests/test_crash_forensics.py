"""崩溃取证判据（2026-10-06，用户原话：「**你加判据，多加一点**」）。

每一条都对应"数据现场本来就有、却要人肉翻"的问题：

* WER 的 `异常代码 + 异常数据` ⇒ 是空指针（读 `null+8`）还是别的（堆损坏 / 栈溢出 / fail-fast）；
* `故障模块 = StackHash_xxxx` ⇒ **Windows 根本没定位到模块**（不是有个文件叫 StackHash）；
* 面板 addon 有没有 `DllMain detach` ⇒ **自己退出**还是**被强杀**（2026-10-05 定的口径）；
* ReShade 日志"戛然而止" ⇒ 崩在 addon 加载之前还是之后（**且必须同时说明"也可能是日志缓冲没落盘"**，
  否则读的人会把"没有 addon 行"直接当成"跟 addon 无关"）；
* 当时的 NR 档位 ⇒ **只记录，不归因**（2026-10-02 已定案 `NRStyle` 不是本项目崩因）。

样本取自反馈包 `diagnostics-20261006-102527` 里的真实 WER 字段。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import crashwatch, diagnostics, nr_autostart
from endfieldmodcontroller.config import AppConfig

WER_REAL = """Version=1
EventType=APPCRASH
Sig[0].Name=应用程序名
Sig[0].Value=Endfield.exe
Sig[1].Name=应用程序版本
Sig[1].Value=2021.3.34.0
Sig[3].Name=故障模块名称
Sig[3].Value=StackHash_e7e9
Sig[7].Name=异常代码
Sig[7].Value=c0000005
Sig[8].Name=异常数据
Sig[8].Value=0000000000000008
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    runtime = root / "runtime"
    (runtime / "dlss5").mkdir(parents=True)
    (runtime / "reshade").mkdir(parents=True)
    config = AppConfig(runtime_dir=str(runtime), library_dir=str(root / "library"),
                       dlss5_dir=str(runtime / "dlss5"),
                       builtin_runtime_dir=str(runtime / "builtin"))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: runtime / "dlss5"))
    monkeypatch.setattr(AppConfig, "reshade_runtime_path",
                        property(lambda self: runtime / "reshade"))
    wer_dir = tmp_path / "wer"
    wer_dir.mkdir()
    return config, tmp_path, wer_dir


def _install_wer(monkeypatch, wer_dir, text: str):
    path = wer_dir / "AppCrash_Endfield.exe_abc_Report.wer"
    path.write_text(text, encoding="utf-16")          # 真实 WER 就是 UTF-16LE
    monkeypatch.setattr(diagnostics, "wer_report_paths", lambda: [path])
    return path


def test_null_dereference_is_named(env, monkeypatch):
    """`c0000005` + `异常数据=8` ⇒ 必须说成「读/写 null + 0x8」，而不是只说"崩了"。"""
    config, _tmp, wer_dir = env
    _install_wer(monkeypatch, wer_dir, WER_REAL)
    detail = crashwatch.wer_exception_detail()
    assert detail["exception_code"] == "c0000005"
    assert "null + 0x8" in detail["text"]
    assert "访问违例" in detail["text"]


def test_stackhash_means_module_not_located(env, monkeypatch):
    """`StackHash_*` ⇒ 明确写「没能定位到是哪个模块崩的」。"""
    config, _tmp, wer_dir = env
    _install_wer(monkeypatch, wer_dir, WER_REAL)
    text = crashwatch.wer_exception_detail()["text"]
    assert "StackHash" in text
    assert "没能定位到" in text


def test_real_fault_module_is_reported_verbatim(env, monkeypatch):
    config, _tmp, wer_dir = env
    _install_wer(monkeypatch, wer_dir, WER_REAL.replace("StackHash_e7e9", "nvgpucomp64.dll"))
    text = crashwatch.wer_exception_detail()["text"]
    assert "nvgpucomp64.dll" in text
    assert "没能定位到" not in text


def test_exit_kind_follows_dllmain_detach(env):
    """有 `DllMain detach` = 自己退；一条都没有 = 被强杀（2026-10-05 定口径）。"""
    config, _tmp, _wer = env
    log = config.reshade_runtime_path / crashwatch._ADDON_LOG_NAME
    log.write_text("[addon-early] DllMain attach: begin\n", encoding="utf-8")
    assert "被强杀" in crashwatch.addon_exit_kind(config)
    log.write_text("[addon-early] DllMain attach: begin\n[addon-early] DllMain detach: done\n",
                   encoding="utf-8")
    assert "自己退出" in crashwatch.addon_exit_kind(config)


def test_reshade_verdict_explains_both_meanings(env):
    """日志极短、没有 addon 注册行时，必须**两种含义一起说**（别让人误读成"与 addon 无关"）。"""
    config, _tmp, _wer = env
    log = nr_autostart.reshade_log_path(config)
    log.write_text(
        "20:57:26 | INFO | Initializing crosire's ReShade version '6.8.0'\n"
        "20:57:31 | INFO | Redirecting Direct3DCreate9(SDKVersion = 0x20) ...\n",
        encoding="utf-8")
    verdict = crashwatch.reshade_log_verdict(config)
    assert "没有一条 `Registered add-on`" in verdict
    assert "addon 加载之前" in verdict and "没落盘" in verdict
    assert "启动早期" in verdict


def test_reshade_verdict_counts_registered_addons(env):
    config, _tmp, _wer = env
    log = nr_autostart.reshade_log_path(config)
    log.write_text(
        "Initializing crosire's ReShade\n"
        + "Registered add-on \"DLSS 5 Neural Rendering\"\n" * 3
        + "x" * 9000,
        encoding="utf-8")
    verdict = crashwatch.reshade_log_verdict(config)
    assert "已注册 3 个 add-on" in verdict
    assert "崩在 addon 加载之后" in verdict


def test_nr_snapshot_is_recorded_without_attribution(env):
    """NR 档位只记录；`crash_forensics` 的文案里必须写明"不归因"。"""
    config, _tmp, _wer = env
    log = nr_autostart.reshade_log_path(config)
    log.write_text(
        "Initializing crosire's ReShade\n"
        "x | INFO | DLSS5 Generic: DLSS5 active settings: upscaling=OFF intensity=2.0 "
        "preset=2 style=2 enabled=OFF\n",
        encoding="utf-8")
    assert crashwatch.nr_settings_snapshot(config).startswith("upscaling=OFF")
    lines = crashwatch.crash_forensics(config)
    assert any("只记录、不归因" in line for line in lines)


def test_nr_toggle_flap_is_reported(env):
    """★「游戏内打不开 NR」：`ON` 后 0.6 秒被 `OFF` —— 这条必须被判出来并说人话。

    样本就是反馈者日志里的真实两行（`21:16:32.126 ON` / `21:16:32.760 OFF`）。
    """
    config, _tmp, _wer = env
    log = nr_autostart.reshade_log_path(config)
    log.write_text(
        "Initializing crosire's ReShade\n"
        "21:16:31:115 [1] | INFO | [RenoDX: Arknights Endfield Enhancer] "
        "Endfield enhancer: Camera controls installed.\n"
        "21:16:32:126 [2] | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: NR toggled ON via F6\n"
        "21:16:32:760 [2] | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: NR toggled OFF via F6\n",
        encoding="utf-8")
    verdict = crashwatch.nr_toggle_flap(config)
    assert "又被关掉" in verdict, verdict
    assert "0.6 秒" in verdict or "0.7 秒" in verdict, verdict
    assert any("NR 开关" in line for line in crashwatch.crash_forensics(config))


def test_nr_toggle_staying_on_is_not_flagged(env):
    """开了就是开着（例如随后建起 feature 18）⇒ 不报"开了又关"。"""
    config, _tmp, _wer = env
    log = nr_autostart.reshade_log_path(config)
    log.write_text(
        "Initializing crosire's ReShade\n"
        "21:16:32:126 | INFO | NR toggled ON via F6\n"
        "21:16:35:200 | INFO | feature 18 created after DLSS/DLAA\n"
        "21:20:00:000 | INFO | NR toggled OFF via F6\n",
        encoding="utf-8")
    assert crashwatch.nr_toggle_flap(config) == ""


def test_crt_runtime_error_dialog_is_detected(monkeypatch):
    """★ 卡在 CRT `Runtime Error!` 弹窗上（反馈截图那种）。

    这类失败**进程还活着**：事件日志、WER、退出码一条都拿不到，所以只能枚举窗口。
    """
    monkeypatch.setattr(crashwatch, "_visible_windows",
                        lambda: [(4321, "Microsoft Visual C++ Runtime Library", "#32770"),
                                 (9999, "Endfield", "UnityWndClass")])
    text = crashwatch.stuck_on_crt_dialog()
    assert "卡在 CRT 弹窗上" in text
    assert "4321" in text
    assert "进程还活着" in text


def test_unrelated_dialogs_are_ignored(monkeypatch):
    """别的对话框、或标题像但**不是对话框类**的窗口，都不算。"""
    monkeypatch.setattr(crashwatch, "_visible_windows",
                        lambda: [(1, "另存为", "#32770"),
                                 (2, "Runtime Error", "Notepad"),
                                 (3, "Endfield", "UnityWndClass")])
    assert crashwatch.stuck_on_crt_dialog() == ""


def test_forensics_includes_stuck_dialog_when_present(env, monkeypatch):
    config, _tmp, _wer = env
    monkeypatch.setattr(crashwatch, "_visible_windows",
                        lambda: [(777, "Microsoft Visual C++ Runtime Library", "#32770")])
    lines = crashwatch.crash_forensics(config)
    assert any("卡在 CRT 弹窗上" in line for line in lines)


def test_rival_nr_provider_conflict_is_reported(tmp_path, monkeypatch):
    """★ 两个 NR provider 同装（Chicken + RenoDX）⇒ **两者都不工作**。

    样本即反馈包现场：`deep-fried-chicken.addon64`（自己装的）与随包的
    `renodx-dlss5-4.7_汉化.addon64` 并存 —— 这是面板「未匹配NR功能 / 成功NR帧 0」的直接原因。
    """
    dlss5 = tmp_path / "dlss5"
    dlss5.mkdir()
    for name in ("deep-fried-chicken.addon64", "renodx-dlss5-4.7_汉化.addon64"):
        (dlss5 / name).write_bytes(b"x")
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    config = AppConfig()
    text = crashwatch.nr_provider_conflict(config)
    assert "两个 NR provider 同时在场" in text
    assert "deep-fried-chicken.addon64" in text
    assert "二选一" in text
    (dlss5 / "deep-fried-chicken.addon64").unlink()          # 只留 RenoDX ⇒ 不该再报
    assert crashwatch.nr_provider_conflict(config) == ""


def test_evaluate_crash_from_feed_log_is_reported(tmp_path, monkeypatch):
    """★ Feeder 记下的 evaluate 崩溃 —— **它带故障模块**，比 WER 的 `StackHash_*` 准得多。"""
    dlss5 = tmp_path / "dlss5"
    dlss5.mkdir()
    (dlss5 / "dlss5-feed.log").write_text(
        "11:17:39.112  ################ feed: opening D3D12 session ################\n"
        "11:17:43.717  [feed] evaluate raised 0xC0000005 (reading address FFFFFFFFFFFFFFFF)"
        " (caught; nothing submitted)\n"
        "11:17:43.717  [feed] evaluate fault stack, by module (innermost first):"
        " D3D12Core.dll <- nvngx_dlssnr.dll\n"
        "11:17:43.718  stopped: the DLSS evaluate crashed\n",
        encoding="utf-8")
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    config = AppConfig()
    text = crashwatch.nr_evaluate_crash(config)
    assert "evaluate 崩了" in text
    assert "FFFFFFFFFFFFFFFF" in text
    assert "nvngx_dlssnr.dll" in text
    assert "11:17" not in text, "时间戳不该混进故障栈里"


def test_forensics_lists_both_nr_findings(tmp_path, monkeypatch):
    dlss5 = tmp_path / "dlss5"
    dlss5.mkdir()
    for name in ("deep-fried-chicken.addon64", "renodx-dlss5-4.7.addon64"):
        (dlss5 / name).write_bytes(b"x")
    (dlss5 / "dlss5-feed.log").write_text(
        "################ feed: opening D3D12 session ################\n"
        "evaluate raised 0xC0000005 (reading address FFFFFFFFFFFFFFFF)\n"
        "evaluate fault stack, by module (innermost first): D3D12Core.dll <- nvngx_dlssnr.dll\n",
        encoding="utf-8")
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    monkeypatch.setattr(AppConfig, "reshade_runtime_path", property(lambda self: tmp_path / "reshade"))
    config = AppConfig()
    lines = crashwatch.crash_forensics(config)
    assert any(line.startswith("NR 冲突：") for line in lines)
    assert any(line.startswith("NR 运行库：") for line in lines)
