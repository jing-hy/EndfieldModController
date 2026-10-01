"""OptiScaler 共存的三件事（2026-10-01 用户拍板：「一键还原游戏本体要全部移走，1 和 2 可以做」）。

背景（一份真实诊断包）：反馈者机器装着 **OptiScaler DLSS-NR**（以 `WINHTTP.dll` 形式注入、
接管 NGX 调用），于是 `ReShade.log` 报 `Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C`、
面板 `NGX Hook 创建: 0`，他据此认为「未启动 DLSS5」—— 而日志证明它**一直在出帧**
（`feature ready: 2560x1440 DLAA`、`OptiScaler DLSS-NR … neural model (feature 18) loaded`）。

三件事：
* **① 自检** `dlss5:ngx_consumer`：认出 OptiScaler 就说明"面板 hook 计数为 0 属正常、该看什么"；
* **② 诊断包** 的 `summary.txt` 加「NGX 消费者」段（以后看包的人不再被那两条误导）；
* **③ 净化**（一键还原游戏本体）：`LOADER_PROXY_MODULES` 补 `winhttp.dll` 等常见 proxy 名，
  判定放宽为"内容标记 / OptiScaler 特征 / **与 System32 原版不同**"—— 用户明确要求**全部移走**。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import diagnostics, game_clean, initialize, reshade_integration
from endfieldmodcontroller.config import AppConfig

OPTISCALER_FAKE = b"MZ" + b"\x00" * 64 + b"OptiScaler DLSS-NR direct-runtime build" + b"\x00" * 32
PLAIN_FAKE = b"MZ" + b"\x00" * 200          # 内容里没有我们的标记，也不是真系统模块


def _game(tmp_path: Path, *, winhttp: bytes | None = None, ini: bool = False) -> Path:
    game = tmp_path / "Endfield Game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    if winhttp is not None:
        (game / "winhttp.dll").write_bytes(winhttp)
    if ini:
        (game / "OptiScaler.ini").write_text("[DlssNr]\nEnabled=auto\n", encoding="utf-8")
    return game


def _config(tmp_path: Path, game: Path) -> AppConfig:
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                       game_exe=str(game / "Endfield.exe"))
    return config


# --------------------------------------------------------------- 判定层
def test_replaced_system_module_is_third_party(tmp_path):
    """`winhttp.dll` 与 System32 原版不同 → 判定为第三方（OptiScaler 正是这么注入的）。"""
    game = _game(tmp_path, winhttp=PLAIN_FAKE)
    assert reshade_integration.is_third_party_proxy(game / "winhttp.dll") == "third-party"


def test_optiscaler_marker_wins_over_size_heuristic(tmp_path):
    """内容带 OptiScaler 特征 → 血统直接标成 optiscaler（便于在界面/日志里说清是什么）。"""
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE)
    assert reshade_integration.is_third_party_proxy(game / "winhttp.dll") == "optiscaler"


def test_winhttp_is_in_the_proxy_list():
    assert "winhttp.dll" in reshade_integration.LOADER_PROXY_MODULES
    assert "wininet.dll" in reshade_integration.LOADER_PROXY_MODULES


def test_optiscaler_present_detects_ini_and_proxy(tmp_path):
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)
    info = reshade_integration.optiscaler_present(game)
    assert info["present"] is True
    assert any("winhttp.dll" in item for item in info["files"])
    assert info["ini"] is True

    clean_game = _game(tmp_path / "clean")
    assert reshade_integration.optiscaler_present(clean_game)["present"] is False


# --------------------------------------------------------------- ③ 净化：全部移走
def test_audit_reports_optiscaler_proxy(tmp_path):
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)
    report = game_clean.audit(_config(tmp_path, game))
    proxies = [f for f in report["findings"] if f["category"] == "loader_proxy"]
    assert [p["relative"] for p in proxies] == ["winhttp.dll"]
    assert "OptiScaler" in proxies[0]["detail"]


def test_backup_and_clean_moves_optiscaler_proxy_and_backs_it_up(tmp_path):
    """用户要求「一键还原游戏本体要全部移走」：proxy 要**备份后移走**，并补回系统原版。"""
    game = _game(tmp_path, winhttp=PLAIN_FAKE, ini=True)
    config = _config(tmp_path, game)

    result = game_clean.backup_and_clean(config)

    moved = [item["relative"] for item in result["moved"]]
    assert "winhttp.dll" in moved, result
    assert any("OptiScaler" in m for m in moved), result
    # 备份区里必须留着原件（可还原）
    backup_dir = Path(result["backup_dir"])
    assert backup_dir.is_dir()
    assert (backup_dir / "files" / "winhttp.dll").is_file()
    # 系统原版会被补回（本机 System32 里有 winhttp.dll）——补不回也不许假报 ok
    assert result["ok"] is True, result.get("errors")


def test_untouched_when_module_matches_system(tmp_path, monkeypatch):
    """与 System32 完全一致的文件**不算**第三方（避免误伤游戏自带/正版模块）。"""
    game = _game(tmp_path, winhttp=PLAIN_FAKE)
    monkeypatch.setattr(reshade_integration, "system_module_differs", lambda _n, _p: False)
    assert reshade_integration.is_third_party_proxy(game / "winhttp.dll") == ""
    report = game_clean.audit(_config(tmp_path, game))
    assert not [f for f in report["findings"] if f["category"] == "loader_proxy"]


# --------------------------------------------------------------- ① 自检：检测到就**自动处理**
def test_initialize_auto_quarantines_optiscaler(tmp_path):
    """用户 2026-10-01：「不是提示的问题，正常用户不会看日志，需要自动检测处理」。

    所以自检发现 OptiScaler 时**不能只写一句说明** —— 要把它备份移走，并报成 `fixed=True`。
    """
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)
    config = _config(tmp_path, game)
    report = initialize.Report()
    logs: list[str] = []

    initialize._check_dlss5_ngx_consumer(config, report, logs.append)

    checks = [c for c in report.checks if c["key"] == "dlss5:ngx_conflict"]
    assert checks, report.checks
    assert checks[0]["ok"] is True and checks[0]["fixed"] is True, checks[0]
    assert "已自动备份并移走" in checks[0]["message"]
    # 真的动手了：OptiScaler 的配置被移走（proxy 会被系统原版补回，所以断言目录里没有 ini）
    assert not (game / "OptiScaler.ini").is_file()
    backups = list((tmp_path / "runtime" / "game_backup").glob("ngx-conflict-*/files/"))
    assert backups, "必须有备份区（可还原）"
    assert (backups[0] / "OptiScaler.ini").is_file()
    assert logs and any("OptiScaler" in line for line in logs)


def test_quarantine_injector_is_idempotent(tmp_path):
    """第二次调用应当报"没有需要处理的文件"（不重复备份、不报错）。"""
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)
    config = _config(tmp_path, game)
    first = game_clean.quarantine_injector(config)
    assert first["changed"] is True and first["ok"] is True, first

    monkeypatch_game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)   # 再造一份干净现场
    second = game_clean.quarantine_injector(_config(tmp_path, monkeypatch_game))
    assert second["changed"] is True
    third = game_clean.quarantine_injector(_config(tmp_path, monkeypatch_game))
    assert third["changed"] is False and third["ok"] is True, third


def test_quarantine_injector_dry_run_touches_nothing(tmp_path):
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)
    result = game_clean.quarantine_injector(_config(tmp_path, game), dry_run=True)
    assert result["changed"] is True
    assert (game / "OptiScaler.ini").is_file() and (game / "winhttp.dll").is_file()


def test_initialize_says_no_third_party_consumer(tmp_path):
    game = _game(tmp_path)
    report = initialize.Report()
    initialize._check_dlss5_ngx_consumer(_config(tmp_path, game), report, None)
    checks = [c for c in report.checks if c["key"] == "dlss5:ngx_consumer"]
    assert checks and checks[0]["ok"] is True
    assert "未检测到" in checks[0]["message"]


# --------------------------------------------------------------- ② 诊断包
def test_diagnostics_summary_has_ngx_consumer_section(tmp_path):
    game = _game(tmp_path, winhttp=OPTISCALER_FAKE, ini=True)
    lines = diagnostics._ngx_consumer_summary(game)
    text = "\n".join(lines)
    assert "NGX 消费者" in text and "OptiScaler" in text
    assert "EvaluateFeature_C" in text and "feature ready" in text

    clean_lines = diagnostics._ngx_consumer_summary(_game(tmp_path / "clean2"))
    assert "未检测到第三方 NGX 接管" in "\n".join(clean_lines)
