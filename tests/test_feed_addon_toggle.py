"""喂帧组件（dlss5-feed）启停。

2026-10-02 反馈者 31002 的现场：`runtime\\dlss5\\` 与 `_disabled\\` 里**各有一份**
`dlss5-feed.addon64` ⇒ 状态判据说"启用中"、停用函数说"无需停用"，互相矛盾、什么都没做 ⇒
ReShade 一直加载着 feed，与 `renodx-dlss5` 抢同一条 NGX 链路 ⇒ 游戏 42 秒静默退出。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig


class FeedAddonToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.base = Path(self.tmp.name) / "dlss5"
        self.base.mkdir(parents=True)
        self.disabled = self.base / launcher.ADDON_DISABLED_DIR
        self.config = AppConfig(dlss5_dir=str(self.base))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _status(self) -> dict:
        return launcher.feed_addon_status(self.config)

    def test_disable_removes_the_duplicate_copy(self) -> None:
        """两处各有一份时，停用必须**真的把根目录那份清掉**（而不是"无需停用"）。"""
        (self.base / "dlss5-feed.addon64").write_bytes(b"x")
        self.disabled.mkdir(parents=True, exist_ok=True)
        (self.disabled / "dlss5-feed.addon64").write_bytes(b"x")
        self.assertTrue(self._status()["on"], "前提：根目录那份在位 ⇒ 状态判据认为启用中")

        result = launcher.set_feed_addon_enabled(self.config, False)

        self.assertTrue(result["ok"], result)
        self.assertIn("dlss5-feed.addon64", result.get("removed") or [])
        self.assertFalse((self.base / "dlss5-feed.addon64").exists(), "根目录那份要被清掉")
        self.assertTrue((self.disabled / "dlss5-feed.addon64").is_file(), "_disabled 那份留着，可还原")
        self.assertFalse(self._status()["on"], "清完之后状态判据必须一致地说：已停用")

    def test_disable_then_enable_round_trip(self) -> None:
        """正常的一次搬运（只有一份）仍旧要能来回。"""
        (self.base / "dlss5-feed.addon64").write_bytes(b"x")
        off = launcher.set_feed_addon_enabled(self.config, False)
        self.assertTrue(off["ok"] and off.get("moved"), off)
        self.assertFalse((self.base / "dlss5-feed.addon64").exists())
        on = launcher.set_feed_addon_enabled(self.config, True)
        self.assertTrue(on["ok"] and on.get("moved"), on)
        self.assertTrue((self.base / "dlss5-feed.addon64").is_file())
        self.assertTrue(self._status()["on"])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# 2026-10-03：判据必须是「文件 + 运行时证据」两条，不能只看文件
# （用户转来的反馈：XXMI/EFMI 强制 -force_d3d11 时游戏建不出 DLSS 特性，
#   停用 feeder 等于把 DLSS5 关掉 —— v0.9.5 就是这么坏的。）
# ---------------------------------------------------------------------------

def _feed_check(monkeypatch, tmp_path, *, present, enabled, render_api):
    """跑一次 _check_dlss5_feed_redundant，返回 (report, 是否调用了停用/启用)。"""
    from endfieldmodcontroller import initialize, launcher, reshade_integration
    from endfieldmodcontroller.config import AppConfig

    config = AppConfig()
    config.auto_disable_feed_on_native_dlss = True
    calls = []

    monkeypatch.setattr(launcher, "feed_addon_status",
                        lambda cfg: {"present": present, "on": enabled})
    monkeypatch.setattr(launcher, "set_feed_addon_enabled",
                        lambda cfg, on, log=None: (calls.append(on), {"ok": True, "moved": True})[1])
    monkeypatch.setattr(reshade_integration, "detect_game_dir", lambda cfg, allow_scan=True: tmp_path)
    monkeypatch.setattr(reshade_integration, "native_dlss_present",
                        lambda game_dir: {"present": present, "files": ["nvngx_dlss.dll"] if present else []})
    monkeypatch.setattr(reshade_integration, "detect_render_api", lambda game_dir: render_api)

    report = initialize.Report()
    initialize._check_dlss5_feed_redundant(config, report, None)
    entries = [e for e in report.checks if e.get("key") == "dlss5:feed"]
    return (entries[0] if entries else None), calls


def test_feed_kept_when_running_d3d11(monkeypatch, tmp_path):
    """★ 核心回归：游戏目录里有 DLSS 文件，但运行时是 d3d11 ⇒ **绝不能停用** feeder。"""
    entry, calls = _feed_check(monkeypatch, tmp_path, present=True, enabled=True, render_api="d3d11")
    assert calls == [], f"d3d11 下不许停用喂帧组件，却调用了 {calls}"
    assert entry is not None and "保持启用" in entry["message"]


def test_feed_kept_when_render_api_unknown(monkeypatch, tmp_path):
    """证据不足时保守：不确定就留着 feeder（停错等于 DLSS5 全废）。"""
    entry, calls = _feed_check(monkeypatch, tmp_path, present=True, enabled=True, render_api="unknown")
    assert calls == []


def test_feed_disabled_only_on_d3d12(monkeypatch, tmp_path):
    """真的跑 D3D12、用得上游戏自己的 DLSS 时，才停用。"""
    entry, calls = _feed_check(monkeypatch, tmp_path, present=True, enabled=True, render_api="d3d12")
    assert calls == [False]
    assert entry is not None and "已自动停用" in entry["message"]


def test_feed_restored_when_misdisabled_on_d3d11(monkeypatch, tmp_path):
    """★ 自愈：被 v0.9.5 那个只看文件的判据误停用的机器，自检要把它放回来。"""
    entry, calls = _feed_check(monkeypatch, tmp_path, present=True, enabled=False, render_api="d3d11")
    assert calls == [True], "d3d11 下被停用的 feeder 必须自动放回"
    assert entry is not None and "放回" in entry["message"]
