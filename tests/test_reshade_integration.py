from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import launcher, reshade_integration
from endfieldmodcontroller.config import AppConfig


class ExistingReShadeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-reshade-")
        self.root = Path(self.tmp.name)
        self.game_dir = self.root / "Endfield Game"
        self.game_dir.mkdir(parents=True)
        (self.game_dir / "Endfield.exe").write_bytes(b"")
        (self.game_dir / "ReShade.ini").write_text("[ADDON]\n", encoding="utf-8")
        (self.game_dir / "dxgi.dll").write_bytes(b"reshade")
        (self.game_dir / "actions.tsv").write_text("original-actions\n", encoding="utf-8")

        self.addon = self.root / "endfieldmodcontroller.addon"
        self.addon.write_bytes(b"addon")
        self.controller = self.root / "controller"
        self.controller.mkdir(parents=True)
        (self.controller / "actions.tsv").write_text(
            "id\tlabel\tkind\tmod_name\tvalues\n1\tTest\tcommand\tMod\t1\n",
            encoding="utf-8",
        )
        self.runtime = self.root / "runtime"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.root / "staging"),
            game_exe=str(self.game_dir / "Endfield.exe"),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_detect_existing_reshade(self) -> None:
        info = reshade_integration.detect_existing_reshade(self.config)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(Path(info["game_dir"]).name, self.game_dir.name)
        self.assertIn((self.game_dir / "dxgi.dll").name, [Path(item).name for item in info["proxies"]])

    def test_deploy_backup_and_remove(self) -> None:
        with mock.patch("endfieldmodcontroller.reshade_integration.built_addon_path", return_value=self.addon):
            result = reshade_integration.deploy_existing_reshade(
                self.config, controller_dir=self.controller
            )
        self.assertTrue((self.game_dir / "endfieldmodcontroller.addon64").is_file())
        self.assertEqual(
            (self.game_dir / "actions.tsv").read_text(encoding="utf-8"),
            (self.controller / "actions.tsv").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (self.game_dir / "user_ini_path.txt").read_text(encoding="utf-8"),
            str(self.config.user_ini_path),
        )
        self.assertTrue(Path(result["manifest"]).is_file())
        backup = self.game_dir / "actions.tsv.endfieldmodcontroller.bak"
        self.assertTrue(backup.is_file())

        removals = reshade_integration.remove_existing_reshade(self.config)
        self.assertFalse((self.game_dir / "endfieldmodcontroller.addon64").exists())
        self.assertFalse((self.game_dir / "user_ini_path.txt").exists())
        self.assertEqual((self.game_dir / "actions.tsv").read_text(encoding="utf-8"), "original-actions\n")
        self.assertFalse(reshade_integration.manifest_path(self.config).exists())
        self.assertTrue(removals["removed"])
        self.assertTrue(removals["restored"])

    def test_adopt_disable_restore_proxies(self) -> None:
        (self.game_dir / "dxgi.dll").write_bytes(b"crosire ReShade 6.8.0")
        (self.game_dir / "d3d12.dll").write_bytes(b"crosire ReShade 6.8.0")
        adopted = reshade_integration.adopt_game_reshade_dll(self.config)
        target = Path(adopted["target"])
        self.assertTrue(target.is_file())
        self.assertIn(b"ReShade", target.read_bytes())

        disabled = reshade_integration.disable_game_reshade_proxies(self.config)
        self.assertEqual(len(disabled["disabled"]), 2)
        self.assertTrue((self.game_dir / "dxgi.dll.endfieldmodcontroller.disabled").is_file())
        self.assertTrue((self.game_dir / "d3d12.dll.endfieldmodcontroller.disabled").is_file())
        self.assertFalse((self.game_dir / "dxgi.dll").exists())
        self.assertIsNone(reshade_integration.detect_existing_reshade(self.config))

        restored = reshade_integration.restore_game_reshade_proxies(self.config)
        self.assertEqual(len(restored["restored"]), 2)
        self.assertTrue((self.game_dir / "dxgi.dll").is_file())
        self.assertTrue((self.game_dir / "d3d12.dll").is_file())

    def test_launcher_safe_mode_orchestration(self) -> None:
        xxmi_root = self.root / "xxmi"
        bin_dir = xxmi_root / "Resources" / "Bin"
        bin_dir.mkdir(parents=True)
        xxmi_exe = bin_dir / "XXMI Launcher.exe"
        xxmi_exe.write_bytes(b"")
        (xxmi_root / "XXMI Launcher Config.json").write_text(
            json.dumps({"Importers": {"EFMI": {"Importer": {}}}}), encoding="utf-8"
        )
        (self.game_dir / "dxgi.dll").write_bytes(b"crosire ReShade 6.8.0")
        (self.game_dir / "d3d12.dll").write_bytes(b"crosire ReShade 6.8.0")
        config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.root / "staging"),
            use_builtin_runtime=False,
            xxmi_launcher=str(xxmi_exe),
            game_exe=str(self.game_dir / "Endfield.exe"),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        config._config_path = str(self.root / "safe-config.json")
        result = launcher.enable_anti_cheat_safe_mode(config)
        self.assertTrue(result["safe_mode"])
        self.assertEqual(config.reshade_injection, "xxmi_extra")
        self.assertTrue((self.game_dir / "dxgi.dll.endfieldmodcontroller.disabled").is_file())
        self.assertTrue((self.runtime / "reshade" / "ReShade64.dll").is_file())
        data = json.loads((xxmi_root / "XXMI Launcher Config.json").read_text(encoding="utf-8"))
        importer = data["Importers"]["EFMI"]["Importer"]
        self.assertTrue(importer["extra_libraries_enabled"])
        self.assertIn("ReShade64.dll", importer["extra_libraries"])

        restored = launcher.restore_anti_cheat_safe_mode(config)
        self.assertTrue(restored["ok"] or restored["warnings"])
        self.assertTrue((self.game_dir / "dxgi.dll").is_file())
        self.assertTrue((self.game_dir / "d3d12.dll").is_file())

    def test_swap_dxgi_to_d3d12_and_restore(self) -> None:
        (self.game_dir / "dxgi.dll").write_bytes(b"crosire ReShade 6.8.0")
        (self.game_dir / "d3d12.dll").write_bytes(b"crosire ReShade 6.8.0")
        swapped = reshade_integration.swap_dxgi_to_d3d12(self.config)
        self.assertFalse((self.game_dir / "dxgi.dll").exists())
        self.assertTrue((self.game_dir / "dxgi.dll.endfieldmodcontroller.disabled").is_file())
        self.assertTrue((self.game_dir / "d3d12.dll").is_file())
        self.assertIsNotNone(reshade_integration.detect_existing_reshade(self.config))
        restored = reshade_integration.restore_dxgi_from_d3d12(self.config)
        self.assertTrue(restored["ok"])
        self.assertTrue((self.game_dir / "dxgi.dll").is_file())
        self.assertTrue((self.game_dir / "d3d12.dll").is_file())

    def test_manifest_is_valid_json(self) -> None:
        with mock.patch("endfieldmodcontroller.reshade_integration.built_addon_path", return_value=self.addon):
            reshade_integration.deploy_existing_reshade(self.config, controller_dir=self.controller)
        data = json.loads(reshade_integration.manifest_path(self.config).read_text(encoding="utf-8"))
        self.assertEqual(len(data["files"]), 3)


class GameDirInjectionAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-inject-")
        self.root = Path(self.tmp.name)
        self.game_dir = self.root / "Endfield Game"
        self.game_dir.mkdir(parents=True)
        (self.game_dir / "Endfield.exe").write_bytes(b"")
        self.runtime = self.root / "runtime"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.root / "staging"),
            game_exe=str(self.game_dir / "Endfield.exe"),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        self.config.ensure_dirs()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_loader_proxy(self, name: str) -> None:
        crash = bytes([13, 10])
        payload = b"[LOADER] started, base=x" + crash + b"no plugin dlls found" + crash
        (self.game_dir / name).write_bytes(payload)

    def test_audit_ignores_genuine_modules(self) -> None:
        (self.game_dir / "d3d12.dll").write_bytes(b"crosire ReShade 6.6.0 addon")
        (self.game_dir / "d3dcompiler_47.dll").write_bytes(b"Microsoft Direct3D HLSL Compiler")
        audit = reshade_integration.audit_game_dir_injections(self.config)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["suspicious"], [])

    def test_audit_detects_loader_proxy_and_plugin_payload(self) -> None:
        self._write_loader_proxy("d3dcompiler_47.dll")
        plugin_dir = self.game_dir / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "sbm.dll").write_bytes(b"mod payload")
        audit = reshade_integration.audit_game_dir_injections(self.config)
        self.assertFalse(audit["ok"])
        kinds = {item["kind"] for item in audit["suspicious"]}
        self.assertEqual(kinds, {"loader_proxy", "plugin_payload"})

    def test_clean_restores_backup_and_is_reversible(self) -> None:
        self._write_loader_proxy("d3dcompiler_47.dll")
        (self.game_dir / "d3dcompiler_47.dll.bak").write_bytes(b"GENUINE")
        plugin_dir = self.game_dir / "plugin"
        plugin_dir.mkdir()
        (plugin_dir / "sbm.dll").write_bytes(b"mod payload")

        result = reshade_integration.disable_game_dir_injections(self.config)
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.game_dir / "d3dcompiler_47.dll").read_bytes(), b"GENUINE")
        self.assertTrue((self.game_dir / "d3dcompiler_47.dll.loader.endfieldmodcontroller.disabled").is_file())
        self.assertTrue((plugin_dir / "sbm.dll.endfieldmodcontroller.disabled").is_file())
        self.assertTrue(reshade_integration.audit_game_dir_injections(self.config)["ok"])
        self.assertTrue(reshade_integration.game_injection_manifest_path(self.config).is_file())

        restored = reshade_integration.restore_game_dir_injections(self.config)
        self.assertTrue(restored["ok"], restored)
        self.assertFalse((self.game_dir / "d3dcompiler_47.dll").read_bytes().startswith(b"GENUINE"))
        self.assertTrue((plugin_dir / "sbm.dll").is_file())
        self.assertFalse(reshade_integration.game_injection_manifest_path(self.config).is_file())

    def test_clean_without_backup_removes_proxy(self) -> None:
        self._write_loader_proxy("vulkan-1.dll")
        result = reshade_integration.disable_game_dir_injections(self.config)
        self.assertTrue(result["ok"], result)
        self.assertFalse((self.game_dir / "vulkan-1.dll").exists())
        self.assertTrue((self.game_dir / "vulkan-1.dll.loader.endfieldmodcontroller.disabled").is_file())


if __name__ == "__main__":
    unittest.main()
