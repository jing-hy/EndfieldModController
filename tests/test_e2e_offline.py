from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import core
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


class OfflineEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-e2e-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "EFMI" / "Mods"
        self._write("陈/夏日/mod.ini", """
namespace = ChenSummer
[Constants]
global persist $cape = 0
[KeyCape]
key = no_modifiers VK_9
type = cycle
$cape = 0,1
""")
        self._write("陈/万圣/mod.ini", """
namespace = ChenHalloween
[Constants]
global persist $hat = 0
[KeyHat]
key = no_modifiers VK_7
type = cycle
$hat = 0,1
""")
        self._write("_deps/RabbitFX/mod.ini", "[Constants]\nglobal persist $enabled = 1\n")
        self.xxmi = self.root / "Resources" / "Bin" / "XXMI Launcher.exe"
        self.xxmi.parent.mkdir(parents=True)
        self.xxmi.write_bytes(b"")
        self.game = self.root / "Endfield.exe"
        self.game.write_bytes(b"")
        self.config_path = self.root / "config.json"
        AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            xxmi_launcher=str(self.xxmi),
            game_exe=str(self.game),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        ).save(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        path = self.library / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_full_offline_pipeline(self) -> None:
        api = EndfieldModControllerApi(self.config_path)
        state = api.scan()
        self.assertEqual(len(state["mods"]), 3)
        summer = next(m for m in state["mods"] if m["name"] == "夏日")
        prepare = api.prepare([summer["id"]])
        self.assertGreaterEqual(prepare["action_count"], 1)

        # Original library still has active key lines.
        original = (self.library / "陈" / "夏日" / "mod.ini").read_text(encoding="utf-8")
        self.assertIn("key = no_modifiers VK_9", original)

        # Managed staging is patched and contains controller files.
        managed = api.config.managed_mods_path
        self.assertTrue(managed.is_dir())
        self.assertTrue((api.config.controller_dir / "controller.ini").is_file())
        staged_text = "\n".join(p.read_text(encoding="utf-8") for p in api.config.staging_mods_path.rglob("mod.ini"))
        self.assertIn("key = no_modifiers vk_f24", staged_text.lower())
        self.assertIn("[key", staged_text.lower())

        # ReShade add-on and action list are deployed outside the game dir.
        self.assertTrue((api.config.reshade_runtime_path / "Addons" / "endfieldmodcontroller.addon").is_file())
        self.assertTrue((api.config.reshade_runtime_path / "actions.tsv").is_file())
        self.assertTrue((api.config.reshade_runtime_path / "user_ini_path.txt").is_file())

        # Action queue can be written and read back.
        first = prepare and json.loads((api.config.controller_dir / "actions.json").read_text(encoding="utf-8"))["actions"][0]
        core.write_action_queue(api.config.user_ini_path, str(first["id"]), "1")
        self.assertEqual(core.read_user_var(api.config.user_ini_path, "mc_controller", "controller_action"), str(first["id"]))

        # Launch preview is built without executing anything.
        preview = api.launch_preview()
        self.assertEqual(preview["command"], [str(api.config.xxmi_launcher_path)])
        self.assertNotIn("--xxmi", preview["command"])
        self.assertNotIn("--nogui", preview["command"])

        # Rollback removes only the managed staging directory.
        rollback = api.rollback()
        self.assertFalse(managed.exists())
        self.assertIn("actions", rollback)
        self.assertTrue((self.library / "陈" / "夏日" / "mod.ini").is_file())


if __name__ == "__main__":
    unittest.main()
