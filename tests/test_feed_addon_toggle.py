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
