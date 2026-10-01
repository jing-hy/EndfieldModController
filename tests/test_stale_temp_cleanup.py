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
