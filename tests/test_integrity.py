from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import integrity
from endfieldmodcontroller.config import AppConfig


class IntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-integrity-")
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.builtin = self.runtime / "builtin"
        self.xxmi_root = self.builtin / "XXMI"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            builtin_runtime_dir=str(self.builtin),
            staging_mods_dir=str(self.xxmi_root / "EFMI" / "Mods"),
            xxmi_launcher=str(self.xxmi_root / "Resources" / "Bin" / "XXMI Launcher.exe"),
            reshade_injection="none",
        )
        self.config._config_path = str(self.root / "config.json")
        # dlss5 走相对路径后指向临时 runtime，必须在 fixture 里造出来，
        # 否则 dlss5_dll / dlss5_ini / dlss5_enhancer_addon 三项会失败
        self.config.dlss5_dir = str(self.runtime / "dlss5")
        self.config.reshade_dll = str(self.runtime / "dlss5" / "d3d12.dll")
        self._make_files()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _touch(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def _make_files(self) -> None:
        self._touch(Path(self.config.xxmi_launcher))
        package = self.xxmi_root / "Resources" / "Packages" / "XXMI"
        for name in ("3dmloader.dll", "d3d11.dll", "d3dcompiler_47.dll"):
            self._touch(package / name)
        self._touch(self.xxmi_root / "EFMI" / "Core" / "EFMI" / "main.ini")
        self._touch(self.xxmi_root / "EFMI" / "d3dx.ini")
        self._touch(self.xxmi_root / "EFMI" / "d3d11.dll")
        (self.xxmi_root / "EFMI" / "Mods").mkdir(parents=True, exist_ok=True)
        self._touch(self.config.reshade_runtime_path / "ReShade.ini")
        self._touch(self.config.reshade_runtime_path / "Addons" / "endfieldmodcontroller.addon")
        self._touch(self.config.reshade_runtime_path / "actions.tsv")
        self._touch(self.config.controller_dir / "controller.ini")
        self._touch(self.config.controller_dir / "actions.tsv")
        # DLSS5 底座三件套
        self._touch(self.config.dlss5_path / "d3d12.dll")
        self._touch(self.config.dlss5_path / "renodx-endfield-enhancer.addon64")
        ini = self.config.dlss5_ini_path
        ini.parent.mkdir(parents=True, exist_ok=True)
        ini.write_text("[endfield-enhancer]\nCameraFirstPerson=1\n", encoding="utf-8")

    def test_integrity_ok(self) -> None:
        report = integrity.check_integrity(self.config)
        self.assertTrue(report["ok"], report)

    def test_missing_d3d11_is_detected(self) -> None:
        (self.xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll").unlink()
        report = integrity.check_integrity(self.config)
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["key"] == "xxmi_libs_d3d11.dll" for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
