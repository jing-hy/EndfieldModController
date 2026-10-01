"""把 PyInstaller onefile 留下的临时目录清干净（用户实测到弹窗
`Warning / Failed to remove temporary directory: …\\Temp\\_MEI0002b002`）。

`app._cleanup_stale_mei_dirs()` 的行为约定：
* **只认 `_MEI` 开头的目录**（PyInstaller 的命名），别的一律不碰；
* **跳过当前进程正在用的那个**（`sys._MEIPASS`）；
* 删不掉（正被别的进程占用）就静默跳过 —— 绝不报错、绝不打扰用户。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller.app import _cleanup_stale_mei_dirs


class StaleTempCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-mei-")
        self.root = Path(self.tmp.name)
        self.current = self.root / "_MEI000001"
        self.current.mkdir()
        (self.root / "_MEI123456").mkdir()
        (self.root / "_MEI123456" / "some.dll").write_bytes(b"x")
        (self.root / "_MEI999999").mkdir()
        (self.root / "别动我").mkdir()
        (self.root / "_MEIish.txt").write_text("x", encoding="utf-8")   # 文件，不是目录
        self._saved = getattr(sys, "_MEIPASS", None)
        sys._MEIPASS = str(self.current)

    def tearDown(self) -> None:
        if self._saved is None:
            try:
                del sys._MEIPASS
            except AttributeError:
                pass
        else:
            sys._MEIPASS = self._saved
        self.tmp.cleanup()

    def test_removes_only_stale_mei_dirs(self) -> None:
        removed = _cleanup_stale_mei_dirs([str(self.root)])
        self.assertEqual(sorted(removed), ["_MEI123456", "_MEI999999"])
        self.assertTrue(self.current.is_dir(), "当前进程正在用的那个绝不能删")
        self.assertTrue((self.root / "别动我").is_dir(), "不相干的目录绝不能碰")
        self.assertTrue((self.root / "_MEIish.txt").is_file(), "只删目录，不动同名文件")

    def test_missing_base_is_harmless(self) -> None:
        removed = _cleanup_stale_mei_dirs([str(self.root / "不存在的目录"), ""])
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()

class EfmiEarlyIncludesTests(unittest.TestCase):
    """EFMI 的 `d3dx.ini` 必须被纠正成"初始化阶段就加载 Mods"。

    2026-10-01 根因：出厂默认 `skip_early_includes_load = 1`（配 `config_initialization_delay = 0`）
    会让 Mods/ 下的 ini **在 DLL 初始化之后**才加载，而 `[Key*]` 的**按键注册只在初始化阶段发生**
    ⇒ **所有按键一律不生效**（Mod 自己的键 + 面板发的合成键），可 `[Present]`/`[Constants]`
    照常工作，所以现象是"注入正常、变量能读能写、但按什么都没反应"。
    纠正函数原先挂在**已废弃**的 `launch_migoto_loader()` 上、从未执行 —— 这个测试防止它再脱钩。
    """

    def test_fixes_both_paired_switches(self) -> None:
        from endfieldmodcontroller.launcher import ensure_efmi_early_includes

        with tempfile.TemporaryDirectory(prefix="mc-efmi-early-") as tmp:
            ini = Path(tmp) / "d3dx.ini"
            ini.write_text(
                "[System]\n"
                "screen_width = 3840\n"
                "config_initialization_delay = 0\n"
                "skip_early_includes_load = 1\n"
                "\n[Logging]\ndebug = 0\n",
                encoding="utf-8",
            )
            self.assertTrue(ensure_efmi_early_includes(ini))
            text = ini.read_text(encoding="utf-8")
            self.assertIn("skip_early_includes_load = 0", text)
            self.assertIn("config_initialization_delay = -1", text)
            # 幂等：再跑一次不改动
            self.assertFalse(ensure_efmi_early_includes(ini))
            # 段落隔离：其它段里的同名键不该被动
            ini.write_text("[Logging]\nskip_early_includes_load = 1\n[System]\nskip_early_includes_load = 0\n"
                           "config_initialization_delay = -1\n", encoding="utf-8")
            self.assertFalse(ensure_efmi_early_includes(ini))
