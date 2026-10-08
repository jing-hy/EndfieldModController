"""把 PyInstaller onefile 留下的临时目录清干净（用户实测到弹窗
`Warning / Failed to remove temporary directory: …\\Temp\\_MEI0002b002`）。

`app._cleanup_stale_mei_dirs()` 的行为约定：
* **只认 `_MEI` 开头的目录**（PyInstaller 的命名），别的一律不碰；
* **跳过当前进程正在用的那个**（`sys._MEIPASS`）；
* **跳过不够老的**（2026-10-08 加）：太新的目录可能正是**另一个实例正在解压**的 ——
  删掉它，对方会在 import 标准库时报 `FileNotFoundError: …\\_MEIxxxxxx\\base_library.zip`
  （用户实测：连点两次 exe，第二个实例崩在 `Unhandled exception in script`）；
* 删不掉（正被别的进程占用）就静默跳过 —— 绝不报错、绝不打扰用户。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from endfieldmodcontroller.app import _cleanup_stale_mei_dirs


class StaleTempCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-mei-")
        self.root = Path(self.tmp.name)
        self.current = self.root / "_MEI000001"
        self.current.mkdir()
        self.old_a = self.root / "_MEI123456"
        self.old_a.mkdir()
        (self.old_a / "some.dll").write_bytes(b"x")
        self.old_b = self.root / "_MEI999999"
        self.old_b.mkdir()
        # ★ 另一个实例"刚解压到一半"的样子：目录很新、里面才落了几个 bootstrap 文件
        self.fresh = self.root / "_MEI777777"
        self.fresh.mkdir()
        (self.fresh / "python314.dll").write_bytes(b"x")
        (self.root / "别动我").mkdir()
        (self.root / "_MEIish.txt").write_text("x", encoding="utf-8")   # 文件，不是目录
        self._age(self.old_a, 3600 * 2)
        self._age(self.old_b, 3600 * 2)
        # 1 秒前：远小于 300 秒阈值（★ 回归要的正是这一点），但已明确"不是未来" ——
        # 否则 Windows 上 `time.time()` 的粗粒度会把"刚创建"的目录偶尔算成负年龄。
        self._age(self.fresh, 1)
        self._saved = getattr(sys, "_MEIPASS", None)
        sys._MEIPASS = str(self.current)

    @staticmethod
    def _age(path: Path, seconds: float) -> None:
        """把目录的 mtime 调老 —— 真正的残留都是"上一次运行"留下的。"""
        stamp = time.time() - seconds
        os.utime(path, (stamp, stamp))

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
        self.assertTrue(self.fresh.is_dir(), "太新的目录（可能是别的实例正在解压）绝不能删")
        self.assertTrue((self.root / "别动我").is_dir(), "不相干的目录绝不能碰")
        self.assertTrue((self.root / "_MEIish.txt").is_file(), "只删目录，不动同名文件")

    def test_fresh_dirs_are_never_removed(self) -> None:
        """★ 回归（2026-10-08）：连点两次 exe 时，先起来的实例**不许**删掉另一个实例
        正在解压的 `_MEIxxxxxx` —— 那会让对方 import 标准库时报
        `FileNotFoundError: …\\_MEIxxxxxx\\base_library.zip`（用户贴出来的那个崩溃）。
        """
        removed = _cleanup_stale_mei_dirs([str(self.root)])
        self.assertNotIn("_MEI777777", removed)
        self.assertTrue((self.fresh / "python314.dll").is_file(), "对方正在写的文件必须还在")

    def test_age_threshold_is_configurable(self) -> None:
        """阈值可调：给 0 就退回"不看年龄"的老行为（只给显式调用用）。"""
        removed = _cleanup_stale_mei_dirs([str(self.root)], min_age_seconds=0)
        self.assertIn("_MEI777777", removed)
        self.assertIn("_MEI123456", removed)

    def test_missing_base_is_harmless(self) -> None:
        removed = _cleanup_stale_mei_dirs([str(self.root / "不存在的目录"), ""])
        self.assertEqual(removed, [])

    def test_source_run_touches_nothing(self) -> None:
        """源码方式启动（没有 `sys._MEIPASS`）时**一个都不许动**：看不出谁在跑，
        删错会让正在运行的打包实例当场崩（比启动崩更糟）。"""
        saved = getattr(sys, "_MEIPASS", None)
        try:
            del sys._MEIPASS
        except AttributeError:
            pass
        try:
            removed = _cleanup_stale_mei_dirs([str(self.root)])
            self.assertEqual(removed, [])
            self.assertTrue(self.old_a.is_dir(), "没有自己的目录可比对时不许清理")
        finally:
            if saved is not None:
                sys._MEIPASS = saved


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

class EfmiExplicitIncludeTests(unittest.TestCase):
    """`[Key*]` 段必须通过**显式 include** 加载才会被注册。

    源码依据（`IniHandler.cpp` 初始化顺序）：`ParseConstantsSection()` →
    **`RegisterPresetKeyBindings()`** → `ParseCommandList(L"Present")`。
    `[Constants]`/`[Present]` 是命令列表，晚一点进也生效；而 `[Key*]` 只在
    `RegisterPresetKeyBindings()` **那一刻**从当时的 `ini_sections` 里取一次 ——
    经 `include_recursive = Mods` 递归进来的段赶不上，于是"Mod 外观生效、面板按键全无反应"。
    """

    def test_adds_explicit_include_before_recursive(self) -> None:
        from endfieldmodcontroller.launcher import ensure_efmi_early_includes

        with tempfile.TemporaryDirectory(prefix="mc-inc-") as tmp:
            ini = Path(tmp) / "d3dx.ini"
            ini.write_text(
                "[Include]\n"
                "include = Core\\EFMI\\main.ini\n"
                "include_recursive = Mods\n"
                "\n[System]\n"
                "skip_early_includes_load = 1\n"
                "config_initialization_delay = 0\n",
                encoding="utf-8")
            self.assertTrue(ensure_efmi_early_includes(ini))
            text = ini.read_text(encoding="utf-8")
            self.assertIn("include = Mods\\MC_Controller\\controller.ini", text)
            inc = text.index("include = Mods\\MC_Controller\\controller.ini")
            rec = text.index("include_recursive = Mods")
            self.assertLess(inc, rec, "显式 include 必须排在 include_recursive 之前")
            self.assertIn("skip_early_includes_load = 0", text)

    def test_idempotent_on_second_run(self) -> None:
        from endfieldmodcontroller.launcher import ensure_efmi_early_includes

        with tempfile.TemporaryDirectory(prefix="mc-inc2-") as tmp:
            ini = Path(tmp) / "d3dx.ini"
            ini.write_text("[Include]\ninclude_recursive = Mods\n\n[System]\n"
                           "skip_early_includes_load = 0\n"
                           "config_initialization_delay = -1\n", encoding="utf-8")
            ensure_efmi_early_includes(ini)
            before = ini.read_text(encoding="utf-8")
            self.assertFalse(ensure_efmi_early_includes(ini))
            self.assertEqual(before, ini.read_text(encoding="utf-8"))
            self.assertEqual(before.count("MC_Controller\\controller.ini"), 1)
