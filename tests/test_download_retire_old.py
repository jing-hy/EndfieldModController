"""入库时按**下载来源**移出旧版（用户 2026-10-03：「对于确认下载地址一致的，
要在入库的时候移出旧的」）。

背景：同一份 Mod 修好重下 / 换新版后，库里会**新旧两份并存**，用户得手动清
（他当天正是这样：`characterchange_131` 旧版还躺在库里）。

判据必须**"确认一致"**：只认 `download-info.json` 里记的
`来源网址` / `文件网址` **完全相等**；没记来源的一律**不猜**、不动它。
动作是移进 `runtime\backups\mod-trash`（**可找回**，不是删除）。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import api as api_mod
from endfieldmodcontroller.config import AppConfig

SAME = "https://gamebanana.com/mods/690864"
OTHER = "https://gamebanana.com/mods/999999"


class RetireSameSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mc-retire-")
        root = Path(self._tmp.name)
        (root / "library").mkdir(parents=True)
        (root / "runtime").mkdir(parents=True)
        cfg = AppConfig()
        cfg._config_path = str(root / "config.json")
        cfg.data_root = str(root)
        cfg.library_dir = "library"
        cfg.save(root / "config.json")
        self.root = root
        self.api = api_mod.EndfieldModControllerApi(str(root / "config.json"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make(self, name: str, source: str, file_url: str = "") -> Path:
        d = self.root / "library" / name
        d.mkdir()
        (d / "download-info.json").write_text(
            json.dumps({"来源网址": source, "文件网址": file_url}, ensure_ascii=False),
            encoding="utf-8")
        (d / "mod.ini").write_text("[Constants]\n", encoding="utf-8")
        return d

    def test_moves_only_same_source(self) -> None:
        """⭐ 核心：同来源的旧版移走；不同来源、以及刚入库的自己，都不动。"""
        self._make("old_same", SAME)
        new_dir = self._make("new_same", SAME)
        self._make("other", OTHER)
        retired = self.api._retire_same_source(new_dir, source_url=SAME, file_url="")
        self.assertEqual(retired, ["old_same"])
        left = sorted(p.name for p in (self.root / "library").iterdir())
        self.assertEqual(left, ["new_same", "other"])
        # 移出 = 进 mod-trash（可找回），不是删除
        self.assertTrue((self.root / "runtime" / "backups" / "mod-trash" / "old_same").is_dir())

    def test_unknown_source_is_never_touched(self) -> None:
        """没记来源的 Mod **绝不动**（不猜）。"""
        self._make("unknown", "")
        new_dir = self._make("new_same", SAME)
        retired = self.api._retire_same_source(new_dir, source_url=SAME, file_url="")
        self.assertEqual(retired, [])
        self.assertTrue((self.root / "library" / "unknown").is_dir())

    def test_matches_by_file_url_too(self) -> None:
        """`文件网址` 一致也算同来源（香蕉网页面地址会变、直链更稳）。"""
        self._make("old_by_file", "https://gamebanana.com/mods/111", "https://gamebanana.com/dl/1809776")
        new_dir = self._make("new_by_file", SAME, "https://gamebanana.com/dl/1809776")
        retired = self.api._retire_same_source(
            new_dir, source_url=SAME, file_url="https://gamebanana.com/dl/1809776")
        self.assertEqual(retired, ["old_by_file"])

    def test_no_criteria_returns_empty(self) -> None:
        """两个 URL 都空时直接返回空 —— 不能"没有判据就当全都一样"。"""
        self._make("a", SAME)
        new_dir = self._make("b", SAME)
        self.assertEqual(self.api._retire_same_source(new_dir, source_url="", file_url=""), [])
        self.assertTrue((self.root / "library" / "a").is_dir())


if __name__ == "__main__":
    unittest.main()
