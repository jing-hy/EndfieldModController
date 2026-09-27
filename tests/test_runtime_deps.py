from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from endfieldmodcontroller import dependencies, runtime_deps
from endfieldmodcontroller.config import AppConfig


class RuntimeDepsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-builtin-")
        self.root = Path(self.tmp.name)
        self.xxmi_zip = self.root / "xxmi.zip"
        self.xxmi_libs_zip = self.root / "xxmi-libs.zip"
        self.efmi_zip = self.root / "efmi.zip"
        self.manifest_json = self.root / "Manifest.json"
        with zipfile.ZipFile(self.xxmi_zip, "w") as zf:
            zf.writestr("XXMI/Resources/Bin/XXMI Launcher.exe", b"exe")
        with zipfile.ZipFile(self.xxmi_libs_zip, "w") as zf:
            zf.writestr("d3d11.dll", b"dll")
        with zipfile.ZipFile(self.efmi_zip, "w") as zf:
            zf.writestr("EFMI/Core/EFMI/main.ini", b"ini")
        self.manifest_json.write_text('{"version": "v-test", "signatures": {}}', encoding="utf-8")
        self.config_path = self.root / "config.json"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.root / "runtime"),
            staging_mods_dir=str(self.root / "runtime" / "EFMI" / "Mods"),
            builtin_runtime_dir=str(self.root / "runtime" / "builtin"),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        self.config._config_path = str(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ensure_builtin_runtime(self) -> None:
        def fake_latest(repo, pattern):
            if repo == runtime_deps.XXMI_REPO:
                return self.xxmi_zip.as_uri(), "v-test", "xxmi.zip"
            return self.efmi_zip.as_uri(), "v-test", "efmi.zip"

        def fake_extract(url, asset_name, target, byte_progress=None, index=1, total=1, key="builtin"):
            mapping = {
                "xxmi.zip": self.xxmi_zip,
                "XXMI-PACKAGE-v-test.zip": self.xxmi_libs_zip,
                "efmi.zip": self.efmi_zip,
            }
            dependencies.extract_archive(mapping[asset_name], target, strip_root=True)

        def fake_release_info(repo):
            return {
                "tag_name": "v-test",
                "assets": [
                    {"name": "XXMI-PACKAGE-v-test.zip", "browser_download_url": "local:xxmi-libs"},
                    {"name": "Manifest.json", "browser_download_url": self.manifest_json.as_uri()},
                ],
            }

        def fake_asset_url(release, name):
            for asset in release["assets"]:
                if asset["name"] == name:
                    return asset["browser_download_url"]
            raise AssertionError(name)

        original_latest = runtime_deps._latest_release_asset
        original_extract = runtime_deps._download_extract
        original_release = runtime_deps._release_info
        original_asset = runtime_deps._asset_url
        runtime_deps._latest_release_asset = fake_latest
        runtime_deps._download_extract = fake_extract
        runtime_deps._release_info = fake_release_info
        runtime_deps._asset_url = fake_asset_url
        try:
            results = runtime_deps.ensure_all(self.config)
        finally:
            runtime_deps._latest_release_asset = original_latest
            runtime_deps._download_extract = original_extract
            runtime_deps._release_info = original_release
            runtime_deps._asset_url = original_asset
        self.assertEqual([r.key for r in results], ["XXMI", "XXMI-Libs", "EFMI"])
        self.assertTrue(self.config.xxmi_launcher.endswith("XXMI Launcher.exe"))
        efmi_root = self.config.builtin_runtime_path / "XXMI" / "EFMI"
        self.assertTrue((efmi_root / "Core" / "EFMI" / "main.ini").is_file())
        self.assertEqual(self.config.staging_mods_path, efmi_root / "Mods")
        report = runtime_deps.builtin_report(self.config)
        self.assertTrue(report["XXMI"]["present"])
        self.assertTrue(report["XXMI-Libs"]["present"])
        self.assertTrue(report["EFMI"]["present"])


if __name__ == "__main__":
    unittest.main()
