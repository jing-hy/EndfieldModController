# SPDX-License-Identifier: AGPL-3.0-only
"""文件守护的开关感知 + 一键启动的无界面开关（2026-11-29）。

两条都是实测过的冤案/需求：

1. 用户主动关掉 Poser 后，启动前净化会把 plugin/poser.dll 搬走（备份在
   game_backup）。旧的文件守护只判"文件在不在"，连着几次就把这件事记成
   「被杀毒软件删了」，还弹窗让用户加白名单 —— 冤枉，而且那个弹窗会挡在
   「一键启动」前面（要等用户点掉才继续）。
2. --nogui 直启（v1.6.4）实测拉不起来终末地：无界面时 XXMI 仍会弹
   「性能提示」模态框，用户看不见也点不到，流程就卡在启动之前。所以改成开关
   （launch_nogui，默认关 = 开窗口让你自己点 Start）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import filewatch, launcher
from endfieldmodcontroller.config import AppConfig

POSER = "game/plugin/poser.dll"
SBM = "game/plugin/sbm.dll"


def _item(key: str) -> filewatch.WatchedFile:
    return next(item for item in filewatch.WATCHED if item.key == key)


class FilewatchSwitchAwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-fw-switch-")
        self.root = Path(self.tmp.name)
        self.game = self.root / "game"
        (self.game / "plugin").mkdir(parents=True)
        self.runtime = self.root / "runtime"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            builtin_runtime_dir=str(self.runtime / "builtin"),
            game_exe=str(self.game / "Endfield.exe"),
        )
        self.config._config_path = str(self.root / "config.json")
        self._patch = mock.patch(
            "endfieldmodcontroller.reshade_integration.detect_game_dir",
            lambda *_a, **_k: self.game,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self.tmp.cleanup()

    def _boot(self, name: str) -> dict:
        with mock.patch.object(filewatch, "_SESSION", name):
            return filewatch.scan(self.config)

    def test_switch_off_item_is_skipped(self) -> None:
        """Poser 开关关着 ⇒ 这一项不监听、不算缺失。"""
        self.config.poser_injection = False
        item = _item(POSER)
        self.assertTrue(filewatch._skipped(self.config, item))
        self.assertIsNone(filewatch._path_for(self.config, item))

    def test_switch_off_does_not_alert(self) -> None:
        """关掉 Poser 后连着几次"文件不在"，也不能报「被杀毒删了」。"""
        self.config.poser_injection = False
        for session in ("s1", "s2", "s3", "s4"):
            self._boot(session)
        state = filewatch.load_state(self.config)
        self.assertNotIn(POSER, state["files"])
        self.assertIsNone(filewatch.pending(self.config))

    def test_switch_off_clears_history(self) -> None:
        """先装好并被盯上，再关开关 + 文件消失 ⇒ 历史计数被清掉（不留后患）。"""
        poser = self.game / "plugin" / "poser.dll"
        poser.write_bytes(b"x")
        self._boot("s1")
        self.config.poser_injection = False
        poser.unlink()
        self._boot("s2")
        state = filewatch.load_state(self.config)
        self.assertNotIn(POSER, state["files"])

    def test_switch_on_still_alerts(self) -> None:
        """开关还开着时照常盯（别把真缺失也放过）。"""
        poser = self.game / "plugin" / "poser.dll"
        poser.write_bytes(b"x")
        self._boot("s1")
        poser.unlink()
        self._boot("s2")
        self._boot("s3")
        state = filewatch.load_state(self.config)
        entry = state["files"].get(POSER) or {}
        self.assertGreaterEqual(int(entry.get("missing") or 0), 2)

    def test_sbm_follows_its_own_switch(self) -> None:
        """乳摇开关关着 ⇒ 游戏里的 sbm.dll 也不盯。"""
        self.config.secondary_motion_injection = False
        self.assertTrue(filewatch._skipped(self.config, _item(SBM)))
        self.config.secondary_motion_injection = True
        self.assertFalse(filewatch._skipped(self.config, _item(SBM)))


class LaunchNoguiSwitchTests(unittest.TestCase):
    """launch_nogui 开关：默认开窗口，开了才用 --nogui 直启。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-nogui-")
        self.root = Path(self.tmp.name)
        bin_dir = self.root / "XXMI" / "Resources" / "Bin"
        bin_dir.mkdir(parents=True)
        self.xxmi = bin_dir / "XXMI Launcher.exe"
        self.xxmi.write_bytes(b"")
        self.game_exe = self.root / "Endfield.exe"
        self.game_exe.write_bytes(b"")
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.root / "runtime"),
            xxmi_launcher=str(self.xxmi),
            game_exe=str(self.game_exe),
        )
        self.config._config_path = str(self.root / "config.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_opens_window_only(self) -> None:
        """默认（开关关）：只开窗口 —— 看得见界面，也看得见 XXMI 的确认框。"""
        self.assertFalse(self.config.launch_nogui)
        cmd = launcher.build_launch_command(self.config)
        # 短路径（ADMINI~1）与长路径指的是同一个文件 —— 按 resolve 比较
        self.assertEqual([Path(p).resolve() for p in cmd], [self.xxmi.resolve()])

    def test_switch_on_uses_nogui(self) -> None:
        self.config.launch_nogui = True
        cmd = launcher.build_launch_command(self.config)
        self.assertIn("--nogui", cmd)
        self.assertIn("--xxmi", cmd)
        self.assertIn("EFMI", cmd)

    def test_start_game_never_nogui_when_switch_off(self) -> None:
        """start_game=True 且开关关：带窗口 + --xxmi（不是 --nogui）。"""
        cmd = launcher.build_launch_command(self.config, start_game=True)
        self.assertIn("--xxmi", cmd)
        self.assertNotIn("--nogui", cmd)


if __name__ == "__main__":
    unittest.main()
