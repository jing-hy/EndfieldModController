"""「游戏自带 DLSS 时自动停用喂帧组件」的回归测试（2026-10-01 用户要求）。

用户原话：「**你把 2 做了，然后在设置留个这个开关，默认开启自动停用**」。
背景：`dlss5-feed` 组件自己在日志里写着 ——
`this game runs NVIDIA Streamline (sl.interposer.dll): it has DLSS of its own …
 This project is for games WITHOUT DLSS — use the game's own DLSS with OptiScaler,
 and remove dlss5-feed.addon64` —— 自带 DLSS 的游戏上它多余，还会与游戏自己的 DLSS
（以及 OptiScaler 这类第三方 NGX 注入器）抢同一条 NGX 链路。

要守住的性质：
* 判据 = 游戏目录里有 `sl.interposer.dll` 或 `nvngx_dlss.dll`（游戏**自带** DLSS）；
* 动作 = 只把 `dlss5-feed.addon64` 移进 `runtime\\dlss5\\_disabled\\`（**可逆**），
  **不许**连带停掉 `renodx-dlss5*.addon64` / 汉化 / preset / shader；
* 设置页那个开关（`auto_disable_feed_on_native_dlss`）关掉时**整项不动作**；
* 换成不带 DLSS 的游戏 / 关掉开关后，被停用的喂帧组件要能**自动放回**。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import initialize, launcher, reshade_integration
from endfieldmodcontroller.config import AppConfig


def _env(tmp_path: Path, *, native_dlss: bool = True, feed_present: bool = True,
         feed_enabled: bool = True) -> tuple[AppConfig, Path, Path]:
    game = tmp_path / "Endfield Game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    if native_dlss:
        (game / "sl.interposer.dll").write_bytes(b"MZ" + b"\x00" * 64)

    dlss5 = tmp_path / "dlss5"
    (dlss5 / "_disabled").mkdir(parents=True, exist_ok=True)
    if feed_present:
        target = dlss5 if feed_enabled else dlss5 / "_disabled"
        (target / "dlss5-feed.addon64").write_bytes(b"feed")
    # 对照物：DLSS5 本体与汉化**不该被动**
    (dlss5 / "renodx-dlss5-4.7_hanhua.addon64").write_bytes(b"dlss5")
    (dlss5 / "trans-zh.addon64").write_bytes(b"zh")

    config = AppConfig(runtime_dir=str(tmp_path / "runtime"), game_exe=str(game / "Endfield.exe"))
    config.dlss5_dir = str(dlss5)
    return config, game, dlss5


# --------------------------------------------------------------- 判据
def test_native_dlss_present_by_streamline(tmp_path):
    _, game, _ = _env(tmp_path, native_dlss=True)
    info = reshade_integration.native_dlss_present(game)
    assert info["present"] is True and "sl.interposer.dll" in info["files"]


def test_native_dlss_present_by_ngx_runtime(tmp_path):
    game = tmp_path / "g"
    game.mkdir()
    (game / "nvngx_dlss.dll").write_bytes(b"MZ")
    assert reshade_integration.native_dlss_present(game)["present"] is True


def test_native_dlss_absent(tmp_path):
    game = tmp_path / "g"
    game.mkdir()
    assert reshade_integration.native_dlss_present(game)["present"] is False
    assert reshade_integration.native_dlss_present(None)["present"] is False


# --------------------------------------------------------------- 单独启停（不动别的）
def test_set_feed_addon_enabled_only_touches_feed(tmp_path):
    config, _game, dlss5 = _env(tmp_path)

    off = launcher.set_feed_addon_enabled(config, False)
    assert off["ok"] is True and off["moved"] == ["dlss5-feed.addon64"], off
    assert (dlss5 / "_disabled" / "dlss5-feed.addon64").is_file()
    assert not (dlss5 / "dlss5-feed.addon64").exists()
    # 对照物必须原样在根目录（不能被连带停掉）
    assert (dlss5 / "renodx-dlss5-4.7_hanhua.addon64").is_file()
    assert (dlss5 / "trans-zh.addon64").is_file()
    assert launcher.feed_addon_status(config)["on"] is False

    on = launcher.set_feed_addon_enabled(config, True)
    assert on["ok"] is True and on["moved"] == ["dlss5-feed.addon64"]
    assert (dlss5 / "dlss5-feed.addon64").is_file()
    assert launcher.feed_addon_status(config)["on"] is True


# --------------------------------------------------------------- 自检行为
def test_initialize_auto_disables_feed_on_native_dlss(tmp_path, monkeypatch):
    config, _game, dlss5 = _env(tmp_path, native_dlss=True, feed_enabled=True)
    # 2026-10-03：判据改成「文件 + **运行时证据**」两条 —— 只有当游戏真的跑在 D3D12 上、
    # 用得上自己那套 DLSS 时，"喂帧组件多余"才成立。这里把运行时证据钉成 d3d12，
    # 否则测试会跟着跑测机器上的真实 Player.log 飘。
    monkeypatch.setattr("endfieldmodcontroller.reshade_integration.detect_render_api",
                        lambda game_dir: "d3d12")
    report = initialize.Report()
    logs: list[str] = []

    initialize._check_dlss5_feed_redundant(config, report, logs.append)

    checks = [c for c in report.checks if c["key"] == "dlss5:feed"]
    assert checks and checks[0]["ok"] is True and checks[0]["fixed"] is True, checks
    assert "已自动停用" in checks[0]["message"]
    assert (dlss5 / "_disabled" / "dlss5-feed.addon64").is_file()
    assert logs and "dlss5-feed" in logs[0]


def test_switch_off_means_no_action(tmp_path):
    """设置页把开关关掉 → 整项不动作，喂帧组件留在原地。"""
    config, _game, dlss5 = _env(tmp_path, native_dlss=True, feed_enabled=True)
    config.auto_disable_feed_on_native_dlss = False
    report = initialize.Report()

    initialize._check_dlss5_feed_redundant(config, report, None)

    checks = [c for c in report.checks if c["key"] == "dlss5:feed"]
    assert checks and "关闭" in checks[0]["message"]
    assert (dlss5 / "dlss5-feed.addon64").is_file(), "关掉开关后不该动文件"


def test_feed_is_restored_when_game_has_no_native_dlss(tmp_path):
    """换了不带 DLSS 的游戏 → 之前被停用的喂帧组件要自动放回。"""
    config, _game, dlss5 = _env(tmp_path, native_dlss=False, feed_enabled=False)
    report = initialize.Report()
    logs: list[str] = []

    initialize._check_dlss5_feed_redundant(config, report, logs.append)

    checks = [c for c in report.checks if c["key"] == "dlss5:feed"]
    assert checks and checks[0]["fixed"] is True and "放回" in checks[0]["message"], checks
    assert (dlss5 / "dlss5-feed.addon64").is_file()


def test_no_feed_component_at_all_is_skipped(tmp_path):
    config, _game, _ = _env(tmp_path, feed_present=False)
    report = initialize.Report()
    initialize._check_dlss5_feed_redundant(config, report, None)
    checks = [c for c in report.checks if c["key"] == "dlss5:feed"]
    assert checks and "不在位" in checks[0]["message"]
