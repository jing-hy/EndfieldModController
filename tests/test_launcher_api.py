from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import core, launcher, reshade_integration
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


class LauncherApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-launch-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "EFMI" / "Mods"
        self.config_path = self.root / "config.json"
        self._write("陈/夏日/mod.ini", """
namespace = ChenSummer
[Constants]
global persist $cape = 0
[KeyCape]
key = no_modifiers VK_9
type = cycle
$cape = 0,1
""")
        self.xxmi = self.root / "XXMI Launcher.exe"
        self.xxmi.write_bytes(b"")
        self.game = self.root / "Endfield.exe"
        self.game.write_bytes(b"")
        self.config = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            xxmi_launcher=str(self.xxmi),
            game_exe=str(self.game),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        self.config.save(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        path = self.library / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_config_roundtrip(self) -> None:
        loaded = AppConfig.load(self.config_path)
        self.assertEqual(loaded.library_dir, str(self.library))
        loaded.selected_mods = ["abc"]
        loaded.save(self.config_path)
        again = AppConfig.load(self.config_path)
        self.assertEqual(again.selected_mods, ["abc"])

    def test_prepare_reshade_runtime(self) -> None:
        controller = self.runtime / "EFMI" / "Mods" / "_controller"
        controller.mkdir(parents=True)
        (controller / "actions.tsv").write_text("id\tlabel\tkind\tmod_name\tvalues\n", encoding="utf-8")
        result = launcher.prepare_reshade_runtime(self.config, controller)
        reshade_dir = Path(result["reshade_dir"])
        self.assertTrue((reshade_dir / "ReShade.ini").is_file())
        # ⚠ 2026-10-01：统一面板**不再**写进 `runtime\reshade\Addons\`（ReShade 只搜
        #   d3d12.dll 所在目录，那份文件永远加载不了）—— 现在落在 dlss5 base 目录。
        panel_dir = Path(result["panel_dir"])
        self.assertEqual(panel_dir, self.config.dlss5_path)
        self.assertTrue((panel_dir / "actions.tsv").is_file())
        self.assertTrue((panel_dir / "user_ini_path.txt").is_file())
        if reshade_integration.built_addon_path() is not None:
            self.assertTrue((panel_dir / reshade_integration.ADDON_NAME).is_file())
            self.assertFalse((self.config.reshade_runtime_path / "Addons" / "endfieldmodcontroller.addon").is_file())

    def test_launch_preview_without_controller(self) -> None:
        result = launcher.launch(self.config, dry_run=True)
        self.assertEqual(result["command"], [str(self.config.xxmi_launcher_path)])
        self.assertNotIn("--xxmi", result["command"])
        self.assertNotIn("--nogui", result["command"])

    def test_launch_env_for_existing_reshade(self) -> None:
        env = launcher.build_launch_env(self.config, existing_reshade=True)
        self.assertNotIn("RESHADE_BASE_PATH_OVERRIDE", env)
        self.assertIn("ENDFIELDMODCONTROLLER_USER_INI", env)


    def test_configure_xxmi_extra_libraries(self) -> None:
        root = self.root / "xxmi"
        bin_dir = root / "Resources" / "Bin"
        bin_dir.mkdir(parents=True)
        launcher_exe = bin_dir / "XXMI Launcher.exe"
        launcher_exe.write_bytes(b"")
        config_json = root / "XXMI Launcher Config.json"
        config_json.write_text('{"Importers": {"EFMI": {"Importer": {}}}}', encoding="utf-8")
        reshade = self.root / "ReShade64.dll"
        reshade.write_bytes(b"")
        cfg = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            xxmi_launcher=str(launcher_exe),
            game_exe=str(self.game),
            reshade_dll=str(reshade),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        result = launcher.configure_xxmi_extra_libraries(cfg)
        self.assertTrue(Path(result["backup"]).is_file())
        data = json.loads(config_json.read_text(encoding="utf-8"))
        importer = data["Importers"]["EFMI"]["Importer"]
        self.assertTrue(importer["extra_libraries_enabled"])
        self.assertIn(str(reshade.resolve()), importer["extra_libraries"])

    def test_api_rollback(self) -> None:
        api = EndfieldModControllerApi(self.config_path)
        state = api.scan()
        mod_id = state["mods"][0]["id"]
        api.prepare([mod_id])
        self.assertTrue(api.config.managed_mods_path.exists())
        result = api.rollback()
        self.assertFalse(api.config.managed_mods_path.exists())
        self.assertIn("actions", result)

    def test_launch_log_read_and_clear(self) -> None:
        api = EndfieldModControllerApi(self.config_path)
        log_path = api.config.runtime_path / "launch.log"
        log_path.write_text("line1\nline2\n", encoding="utf-8")
        result = api.read_launch_log(10)
        self.assertIn("line1", result["text"])
        api.clear_launch_log()
        self.assertFalse(log_path.exists())

    def test_api_scan_prepare_and_preview(self) -> None:
        api = EndfieldModControllerApi(self.config_path)
        state = api.scan()
        self.assertEqual(len(state["mods"]), 1)
        mod_id = state["mods"][0]["id"]
        result = api.prepare([mod_id])
        self.assertGreaterEqual(result["action_count"], 1)
        preview = api.launch_preview()
        self.assertEqual(preview["command"], [str(api.config.xxmi_launcher_path)])
        self.assertNotIn("--xxmi", preview["command"])
        self.assertNotIn("--nogui", preview["command"])
        preview_game = api.launch_preview(start_game=True)
        self.assertNotIn("--nogui", preview_game["command"])
        self.assertIn("--xxmi", preview_game["command"])


if __name__ == "__main__":
    unittest.main()
