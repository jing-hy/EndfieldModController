"""`prepare_reshade_runtime` 反复调用时，`ReShade.ini` **绝不能变大**。

2026-10-03 的真实事故（用户：「现在mod管理器未响应，关不掉」）：
`runtime\\reshade\\ReShade.ini` 一路膨胀到 **3 GB**（内容全是空行），读它的那一步
把内存吃到 23 GB、CPU 打满、界面卡死无法关闭 —— faulthandler 抓到的栈正是卡在
`ini_path.read_text(...)`。

**根因（最后定案）**：`write_text(..., encoding="utf-8")` 没给 `newline`，
默认 `newline=None` ⇒ Windows 文本模式会把 `\\n` **再转一次**成 `\\r\\n`；
而拼串用的是 `"\\r\\n".join(...)` ⇒ 叠加成 **`\\r\\r\\n`**。
`splitlines()` 把 `\\r\\r\\n` 当**两个**换行 ⇒ 凭空多一个空行 ⇒ 写回又多一个
⇒ **空行指数级翻倍**（6 → 11 → 20 → 40 → … 约 30 次到 3 GB）。

这里钉住两件事：
① 反复调用后**行数/大小不变**（曾经的翻倍）；
② 文件里**绝不出现 `\\r\\r\\n`**（那个组合就是膨胀的火种）。
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig


class ReshadeIniStabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mc-ini-test-")
        root = Path(self._tmp.name)
        (root / "runtime" / "reshade").mkdir(parents=True)
        (root / "runtime" / "dlss5").mkdir(parents=True)
        self.cfg = AppConfig()
        self.cfg._config_path = str(root / "config.json")
        self.cfg.data_root = str(root)
        # 源 ini（dlss5 那份，供 [STYLE]/[endfield-enhancer] 同步用）
        (self.cfg.dlss5_path / "ReShade.ini").write_text(
            "[ADDON]\nAddonPath=.\n\n[GENERAL]\nEffectSearchPaths=.\\x\n\n"
            "[STYLE]\nFont=C:\\WINDOWS\\Fonts\\msyh.ttc\n\n"
            "[endfield-enhancer]\nCameraEFMICompatibility=1\n",
            encoding="utf-8",
        )
        self.ini = self.cfg.reshade_runtime_path / "ReShade.ini"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _call(self) -> None:
        launcher.prepare_reshade_runtime(self.cfg, self.cfg.dlss5_path)

    def test_repeated_calls_do_not_grow(self) -> None:
        """⭐ 核心回归：反复调用 12 次，行数与字节数都必须稳定。"""
        self.ini.write_text("[ADDON]\nAddonPath=old\n\n[GENERAL]\nEffectSearchPaths=old\n",
                            encoding="utf-8", newline="")
        self._call()
        first_lines = len(self.ini.read_bytes().splitlines())
        first_size = self.ini.stat().st_size
        for _ in range(12):
            self._call()
        self.assertEqual(len(self.ini.read_bytes().splitlines()), first_lines,
                         "ReShade.ini 的行数又变了（曾经会指数级翻倍到 3 GB）")
        self.assertEqual(self.ini.stat().st_size, first_size, "ReShade.ini 的大小又变了")

    def test_never_writes_double_cr(self) -> None:
        """文件里绝不能出现 `\\r\\r\\n` —— 那个组合是膨胀的火种。"""
        self.ini.write_bytes(b"[ADDON]\r\r\nAddonPath=old\r\r\n\r\r\n[GENERAL]\r\r\nEffectSearchPaths=old\r\r\n")
        for _ in range(5):
            self._call()
            self.assertNotIn(b"\r\r\n", self.ini.read_bytes(),
                             "写出的 ini 里出现了 \\r\\r\\n（会引发空行指数膨胀）")

    def test_recovers_from_already_broken_ini(self) -> None:
        """已经坏掉的（带 `\\r\\r\\n`）文件也要能收敛，而不是继续翻倍。"""
        self.ini.write_bytes(b"[ADDON]\r\r\nAddonPath=old\r\r\n\r\r\n[GENERAL]\r\r\nEffectSearchPaths=old\r\r\n")
        self._call()
        n1 = len(self.ini.read_bytes().splitlines())
        for _ in range(8):
            self._call()
        n2 = len(self.ini.read_bytes().splitlines())
        self.assertEqual(n1, n2, f"坏文件没能收敛：{n1} → {n2}")


if __name__ == "__main__":
    unittest.main()
