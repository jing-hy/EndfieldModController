"""Mod 备份仓（用户 2026-10-01 要求）。

用户原话先是「在根目录下放一个文件夹做 mod 备份，这个文件夹**只增不减**，只要见到新
mod，就**打包 zip** 放进去」，随后改成「**改成不要打包，纯备份**」——所以现在是
**纯复制**：一个 Mod 一个文件夹，原样躺进备份仓。

要点：默认 = 数据根下的 `mod-backup\\`；**只增不减**（没有任何删除/覆盖备份的路径）；
已有备份直接跳过（幂等）；备份目录与库/中转目录重叠时整体拒绝。
"""
from __future__ import annotations

import tempfile
import unittest
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

    def _add_mod(self, name: str, extra_bytes: int = 64) -> Path:
        target = self.library / "佩丽卡" / name
        (target / "Textures").mkdir(parents=True, exist_ok=True)
        (target / "mod.ini").write_text(MOD_INI, encoding="utf-8")
        (target / "Textures" / "skin.dds").write_bytes(b"D" * extra_bytes)
        return target

    def test_new_mod_is_copied_into_backup_dir(self) -> None:
        source = self._add_mod("Alice")
        result = self.api._backup_new_mods()
        self.assertTrue(result["created"], result)
        target_dir = modbackup.backup_dir(self.config)
        # 路径比较要注意 Windows 8.3 短名（ADMINI~1 vs Administrator）→ 用 samefile
        self.assertTrue(target_dir.samefile(self.root / "mod-backup"), str(target_dir))
        backup = target_dir / "Alice"
        self.assertTrue(backup.is_dir(), "备份应该是一个目录（不打包）")
        self.assertEqual(
            (backup / "mod.ini").read_text(encoding="utf-8"),
            (source / "mod.ini").read_text(encoding="utf-8"),
        )
        self.assertEqual((backup / "Textures" / "skin.dds").stat().st_size, 64)
        # 不打包 = 备份仓里不该出现 zip
        self.assertEqual(list(target_dir.glob("*.zip")), [])
        # 复制中途的临时目录不能留下
        self.assertEqual([p.name for p in target_dir.iterdir() if p.name.startswith("_copying_")], [])

    def test_second_run_is_idempotent(self) -> None:
        self._add_mod("Alice")
        first = self.api._backup_new_mods()
        self.assertEqual(len(first["created"]), 1)
        self.api._invalidate_mods()
        second = self.api._backup_new_mods()
        self.assertEqual(second["created"], [])
        target_dir = modbackup.backup_dir(self.config)
        self.assertEqual(len([p for p in target_dir.iterdir() if p.is_dir()]), 1)

    # ------------------------------------------------- 总开关（用户 2026-10-02 要求）
    def test_switch_defaults_to_on(self) -> None:
        """默认开：连"没有这个字段"的老配置读进来也必须是开着的。"""
        self.assertTrue(modbackup.enabled(self.config))
        self.assertTrue(modbackup.status(self.config)["enabled"])

    def test_switch_off_stops_backup_entirely(self) -> None:
        """关了就不备份：**一个字节都不复制**，连备份目录都不建。

        用户 2026-10-02 原话：「给 mod 备份做一个开关，默认开，关了就不备份」。
        """
        self._add_mod("Alice")
        state = self.api.set_mod_backup_enabled(False)
        self.assertTrue(state["ok"] and state["changed"], state)
        self.assertFalse(state["enabled"])
        target_dir = modbackup.backup_dir(self.config)
        self.assertFalse(target_dir.exists(), "关掉后不该凭空多出一个空备份目录")

        self.api._invalidate_mods()
        result = self.api._backup_new_mods()
        self.assertTrue(result.get("skipped"), result)
        self.assertEqual(result.get("reason"), "disabled")
        self.assertFalse(target_dir.exists(), "关掉后不该创建备份目录")
        self.assertFalse((self.root / "mod-backup").exists())

    def test_switch_off_keeps_existing_backups_and_resumes(self) -> None:
        """只增不减优先于开关：关掉不删已有备份；重新打开后照旧补上没备份过的。"""
        self._add_mod("Alice")
        self.api._backup_new_mods()
        target_dir = modbackup.backup_dir(self.config)
        self.assertTrue((target_dir / "Alice" / "mod.ini").is_file())

        self.api.set_mod_backup_enabled(False)
        self._add_mod("Bob")
        self.api._invalidate_mods()
        self.api._backup_new_mods()
        self.assertFalse((target_dir / "Bob").exists(), "关着的时候不该备份")
        self.assertTrue((target_dir / "Alice" / "mod.ini").is_file(), "关掉开关绝不能删已有备份")

        opened = self.api.set_mod_backup_enabled(True)
        self.assertTrue(opened["ok"] and opened["changed"], opened)
        self.api._invalidate_mods()
        result = self.api._backup_new_mods()
        self.assertEqual(len(result["created"]), 1, result)          # Bob 补上
        self.assertTrue((target_dir / "Bob").is_dir())
        self.assertTrue((target_dir / "Alice" / "mod.ini").is_file())

    def test_backup_survives_source_removal_and_is_never_deleted(self) -> None:
        """只增不减：源 Mod 删了、库空跑很多次，备份也必须在。"""
        source = self._add_mod("Alice")
        self.api._backup_new_mods()
        backup = modbackup.backup_dir(self.config) / "Alice"
        self.assertTrue(backup.is_dir())
        for child in sorted(source.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        source.rmdir()
        self.api._invalidate_mods()
        for _ in range(3):
            self.api._backup_new_mods()
        self.assertTrue((backup / "mod.ini").is_file(), "备份被删了（违反只增不减）")
        self.assertEqual(len([p for p in modbackup.backup_dir(self.config).iterdir() if p.is_dir()]), 1)

    def test_broken_index_does_not_recopy(self) -> None:
        self._add_mod("Alice")
        self.api._backup_new_mods()
        modbackup.index_path(self.config).write_text("{ 这不是 json", encoding="utf-8")
        self.api._invalidate_mods()
        result = self.api._backup_new_mods()
        self.assertEqual(result["created"], [], "索引坏掉后重拷了（浪费磁盘、还可能覆盖）")

    def test_legacy_zip_counts_as_backed_up(self) -> None:
        """以前打包时代留下的 zip 也算"备份过"，不会再复制一份目录出来。"""
        self._add_mod("Alice")
        target_dir = modbackup.backup_dir(self.config)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "Alice.zip").write_bytes(b"PK\x03\x04old")
        self.api._invalidate_mods()
        result = self.api._backup_new_mods()
        self.assertEqual(result["created"], [])
        self.assertTrue((target_dir / "Alice.zip").is_file(), "旧 zip 不该被动")
        self.assertFalse((target_dir / "Alice").is_dir())

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
        self.assertEqual(state["folders"], 2)
        self.assertGreater(state["bytes"], 0)
        self.assertFalse(state["overlaps_library"])
        self.assertEqual(state["pending"], 0)

    def test_bad_mod_does_not_block_others(self) -> None:
        """批量不要 fail-fast：一个 Mod 复制失败，其余照常备份。"""
        self._add_mod("Alice")
        self._add_mod("Bob")
        mods = self.api._mods()
        object.__setattr__(mods[0], "path", self.root / "does-not-exist")
        result = modbackup.backup_all(self.config, mods)
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(result["failed"]), 1)
        folders = [p.name for p in modbackup.backup_dir(self.config).iterdir() if p.is_dir()]
        self.assertEqual(len(folders), 1)

    # ------------------------------------------------------------------
    # 设置页「自行选择备份目录」（用户 2026-10-02 要求）
    # ------------------------------------------------------------------
    def test_custom_backup_dir_is_used_and_persisted(self) -> None:
        elsewhere = self.root / "other-drive" / "mc-backup"
        source = self._add_mod("Alice")
        result = self.api.set_mod_backup_dir(str(elsewhere))
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["changed"], result)
        elsewhere.mkdir(parents=True, exist_ok=True)
        # 注意：api 内部持有**自己加载的那份 config**（与 self.config 不是同一个对象），
        # 判断生效要看 self.api.config。
        self.assertTrue(modbackup.backup_dir(self.api.config).samefile(elsewhere), result["dir"])
        # 落盘了：重新加载配置也指向新目录
        reloaded = AppConfig.load(self.config_path)
        self.assertTrue(modbackup.backup_dir(reloaded).samefile(elsewhere))
        # 备份真的进了新目录，内容与源一致
        self.api._invalidate_mods()
        again = self.api._backup_new_mods()
        self.assertTrue(again["created"], again)
        self.assertTrue((elsewhere / "Alice" / "mod.ini").is_file())
        self.assertEqual(
            (elsewhere / "Alice" / "mod.ini").read_text(encoding="utf-8"),
            (source / "mod.ini").read_text(encoding="utf-8"),
        )

    def test_blank_value_restores_default_dir(self) -> None:
        """留空 = 回到默认（数据根下的 mod-backup）。"""
        self.api.set_mod_backup_dir(str(self.root / "custom"))
        result = self.api.set_mod_backup_dir("")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["changed"], result)
        default_dir = self.root / "mod-backup"
        default_dir.mkdir(parents=True, exist_ok=True)
        self.assertTrue(modbackup.backup_dir(self.api.config).samefile(default_dir), result["dir"])

    def test_unchanged_value_reports_not_changed(self) -> None:
        """填的还是原值 → changed=False（界面据此不提示"会重新备份一次"）。"""
        result = self.api.set_mod_backup_dir("mod-backup")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["changed"], result)

    def test_backup_dir_change_is_refused_when_inside_library(self) -> None:
        """落进 Mod 库/中转目录 → 拒绝并保持原值（否则备份会滚进库里）。"""
        before = modbackup.configured_dir(self.api.config)
        result = self.api.set_mod_backup_dir(str(self.library / "backup"))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "backup_dir_overlaps_library")
        self.assertEqual(modbackup.configured_dir(self.api.config), before, "被拒绝的值不该留在配置里")
        self.assertFalse((self.library / "backup").exists())

    def test_choose_dir_without_window_reports_failure(self) -> None:
        """单测环境没有窗口：如实报失败，且绝不偷偷改配置。"""
        before = modbackup.configured_dir(self.api.config)
        result = self.api.choose_mod_backup_dir()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("message"), result)
        self.assertEqual(modbackup.configured_dir(self.api.config), before)


if __name__ == "__main__":
    unittest.main()
