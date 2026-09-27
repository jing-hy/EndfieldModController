"""手动放进 Mods 的 Mod 同步进库的测试。

对应需求原话：「手动放进去的和库里的进行比对，如果库里已有，就在 UI 中显示那个开启，
库里没有就把它放到库里，然后显示开启」。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import activation
from endfieldmodcontroller.config import AppConfig


def _write_mod(root: Path, rel: str, namespace: str) -> Path:
    path = root / rel
    path.mkdir(parents=True, exist_ok=True)
    (path / "mod.ini").write_text(
        f"namespace = {namespace}\n[Constants]\nglobal persist $on = 0\n",
        encoding="utf-8",
    )
    return path


class ImportManualModsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-import-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "EFMI" / "Mods"
        self.library.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

        self.cfg = AppConfig()
        self.cfg.library_dir = str(self.library)
        self.cfg.runtime_dir = str(self.runtime)
        self.cfg.staging_mods_dir = str(self.staging)
        # 给一个可写的配置路径：AppConfig.save() 在没有 load 过时会主动拒绝保存
        # （防止误写真实配置），而 import_manual_mods 需要把"已勾选"写回配置。
        self.cfg.save(self.root / "config.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_find_manual_mods_skips_controller_artifacts(self) -> None:
        """控制器自己的产物不能被当成"用户手动放的 Mod"。"""
        for name in ("MC_Controller", "MC_Probe.ini", "EndfieldModControllerManaged",
                     "_endfieldmodcontroller_managed", "DISABLED", "MC_埃特拉_埃特拉变肥美"):
            (self.staging / name).mkdir(exist_ok=True)
        (self.staging / "手动放的Mod").mkdir()
        found = [p.name for p in activation.find_manual_mods(self.staging)]
        self.assertEqual(found, ["手动放的Mod"])

    def test_import_not_in_library(self) -> None:
        """库里没有 → 复制进库 + 标记选中 + 从 Mods 移除。"""
        _write_mod(self.staging, "手动放的Mod", "ManualOne")
        result = activation.import_manual_mods(self.cfg, None)

        self.assertIn("手动放的Mod", result["imported"])
        self.assertTrue((self.library / "手动放的Mod" / "mod.ini").is_file())
        self.assertFalse((self.staging / "手动放的Mod").exists())   # 已移走，避免同角色成对
        self.assertEqual(result["selected_added"], ["手动放的Mod"])
        self.assertTrue(self.cfg.selected_mods)
        self.assertTrue(result["ok"])

    def test_import_already_in_library(self) -> None:
        """库里已有（同名）→ 不重复复制，只标记选中。"""
        _write_mod(self.library, "已有Mod", "Existing")
        _write_mod(self.staging, "已有Mod", "Existing")
        result = activation.import_manual_mods(self.cfg, None)

        self.assertEqual(result["imported"], [])
        self.assertEqual(result["matched"], ["已有Mod"])
        self.assertEqual(result["selected_added"], ["已有Mod"])
        self.assertFalse((self.staging / "已有Mod").exists())

    def test_import_renamed_mod_matched_by_namespace(self) -> None:
        """目录名不同但 namespace 相同 → 认作同一个 Mod，不重复入库。"""
        _write_mod(self.library, "原名", "SameNamespace")
        _write_mod(self.staging, "改过名的", "SameNamespace")
        result = activation.import_manual_mods(self.cfg, None)

        self.assertEqual(result["imported"], [])
        self.assertEqual(result["matched"], ["原名"])
        self.assertEqual(len(list(self.library.iterdir())), 1)   # 没有多出一份

    def test_idempotent(self) -> None:
        """重复调用不应重复入库或重复勾选。"""
        _write_mod(self.staging, "一次性", "Once")
        activation.import_manual_mods(self.cfg, None)
        second = activation.import_manual_mods(self.cfg, None)
        self.assertEqual(second["found"], 0)
        self.assertEqual(second["selected_added"], [])

    def test_no_manual_mods_is_noop(self) -> None:
        result = activation.import_manual_mods(self.cfg, None)
        self.assertEqual(result["found"], 0)
        self.assertEqual(result["actions"], [])


if __name__ == "__main__":
    unittest.main()
