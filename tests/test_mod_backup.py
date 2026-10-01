"""Mod 备份仓（用户 2026-10-01 要求：「在根目录下放一个文件夹做 mod 备份，这个文件夹
**只增不减**，只要见到新 mod，就打包 zip 放进去」）。

要点：
* 备份目录默认 = 数据根下的 `mod-backup\\`；
* **只增不减** —— 没有任何删除/覆盖已有备份的路径；
* 已有备份的 Mod 直接跳过（幂等，第二次是毫秒级）；
* 备份目录与库/中转目录重叠时整体拒绝（否则 zip 会落进库里）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from endfieldmodcontroller import modbackup
from endfieldmodcontroller.config import AppConfig

MOD_INI = "namespace = Demo\n[Constants]\nglobal persist $cape = 0\n"


class ModBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-modbackup-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.config = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.runtime / "EFMI" / "Mods"),
        )
        self.config_path = self.root / "config.json"
        self.config.save(self.config_path)
        from endfieldmodcontroller.api import EndfieldModControllerApi

        self.api = EndfieldModControllerApi(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _add_mod(self, name: str, extra_bytes: int = 64) -> None:
        target = self.library / "佩丽卡" / name
        (target / "Textures").mkdir(parents=True, exist_ok=True)
        (target / "mod.ini").write_text(MOD_INI, encoding="utf-8")
        (target / "Textures" / "skin.dds").write_bytes(b"D" * extra_bytes)

    def test_new_mod_gets_zipped_into_backup_dir(self) -> None:
        self._add_mod("Alice")
        result = self.api._backup_new_mods()
        self.assertTrue(result["created"], result)
        target_dir = modbackup.backup_dir(self.config)
        # 路径比较要注意 Windows 8.3 短名（ADMINI~1 vs Administrator）→ 用 samefile
        self.assertTrue(target_dir.samefile(self.root / "mod-backup"), str(target_dir))
        zips = list(target_dir.glob("*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.startswith("Alice/") for name in names), names)
        self.assertIn("Alice/mod.ini", names)
        self.assertIn("Alice/Textures/skin.dds", names)

    def test_second_run_is_idempotent(self) -> None:
        self._add_mod("Alice")
        first = self.api._backup_new_mods()
        self.assertEqual(len(first["created"]), 1)
        self.api._invalidate_mods()
        second = self.api._backup_new_mods()
        self.assertEqual(second["created"], [])
        self.assertEqual(len(list(modbackup.backup_dir(self.config).glob("*.zip"))), 1)

    def test_zip_survives_source_removal_and_never_deleted(self) -> None:
        """只增不减：源 Mod 删了、库空跑很多次，备份 zip 也必须在。"""
        self._add_mod("Alice")
        self.api._backup_new_mods()
        zips = list(modbackup.backup_dir(self.config).glob("*.zip"))
        self.assertEqual(len(zips), 1)
        # 手动删掉源目录（模拟用户清理库）
        for child in sorted((self.library / "佩丽卡" / "Alice").rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        (self.library / "佩丽卡" / "Alice").rmdir()
        self.api._invalidate_mods()
        for _ in range(3):
            self.api._backup_new_mods()
        self.assertTrue(zips[0].is_file(), "备份 zip 被删了（违反只增不减）")
        self.assertEqual(len(list(modbackup.backup_dir(self.config).glob("*.zip"))), 1)

    def test_broken_index_does_not_rezip(self) -> None:
        self._add_mod("Alice")
        self.api._backup_new_mods()
        modbackup.index_path(self.config).write_text("{ 这不是 json", encoding="utf-8")
        self.api._invalidate_mods()
        result = self.api._backup_new_mods()
        self.assertEqual(result["created"], [], "索引坏掉后重打了 zip（覆盖已有备份）")
        self.assertEqual(len(list(modbackup.backup_dir(self.config).glob("*.zip"))), 1)

    def test_backup_dir_inside_library_is_refused(self) -> None:
        config = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.runtime / "EFMI" / "Mods"),
            mod_backup_dir=str(self.library / "mod-backup"),
        )
        config.save(self.config_path)
        from endfieldmodcontroller.api import EndfieldModControllerApi

        api = EndfieldModControllerApi(self.config_path)
        self._add_mod("Alice")
        result = api._backup_new_mods()
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("reason"), "backup_dir_overlaps_library")
        self.assertFalse((self.library / "mod-backup").exists())

    def test_status_reports_counts(self) -> None:
        self._add_mod("Alice")
        self._add_mod("Bob")
        self.api._backup_new_mods()
        state = self.api.mod_backup_status()
        self.assertEqual(state["count"], 2)
        self.assertGreater(state["bytes"], 0)
        self.assertFalse(state["overlaps_library"])
        self.assertEqual(state["pending"], 0)

    def test_bad_mod_does_not_block_others(self) -> None:
        """批量不要 fail-fast：一个 Mod 打包失败，其余照常备份。"""
        self._add_mod("Alice")
        self._add_mod("Bob")
        mods = self.api._mods()
        missing = mods[0]
        object.__setattr__(missing, "path", self.root / "does-not-exist")
        result = modbackup.backup_all(self.config, mods)
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertTrue((modbackup.backup_dir(self.config) / "Bob.zip").is_file()
                        or (modbackup.backup_dir(self.config) / "Alice.zip").is_file())


if __name__ == "__main__":
    unittest.main()
