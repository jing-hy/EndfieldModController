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
        # Endfield Poser（第四方插件，2026-10-01 起也在 ensure_all 的批次里）
        self.poser_zip = self.root / "poser.zip"
        with zipfile.ZipFile(self.poser_zip, "w") as zf:
            zf.writestr("plugin/poser.dll", b"dll")
        self.manifest_json.write_text('{"version": "v-test", "signatures": {}}', encoding="utf-8")
        self.config_path = self.root / "config.json"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.root / "runtime"),
            # 内置那份（绝对写法）—— 用户填了外部路径时 ensure_efmi 不该覆盖，
            # 那一半由 test_external_xxmi_is_not_hijacked 覆盖。
            staging_mods_dir=str(self.root / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods"),
            builtin_runtime_dir=str(self.root / "runtime" / "builtin"),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        self.config._config_path = str(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ensure_builtin_runtime(self) -> None:
        def fake_latest(repo, pattern, **kwargs):
            # 签名与 runtime_deps._latest_release_asset 一致：第 4 项是 Release 资产的 sha256 digest。
            # 2026-10-01 起多了 include_prerelease 关键字（Poser 上游只发预发布版，必须用它）。
            if repo == runtime_deps.XXMI_REPO:
                return self.xxmi_zip.as_uri(), "v-test", "xxmi.zip", ""
            if repo == runtime_deps.POSER_REPO:
                return self.poser_zip.as_uri(), "v-test", "poser.zip", ""
            return self.efmi_zip.as_uri(), "v-test", "efmi.zip", ""

        def fake_extract(url, asset_name, target, byte_progress=None, index=1, total=1,
                         key="builtin", expected_sha256=""):
            mapping = {
                "xxmi.zip": self.xxmi_zip,
                "XXMI-PACKAGE-v-test.zip": self.xxmi_libs_zip,
                "efmi.zip": self.efmi_zip,
                "poser.zip": self.poser_zip,
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
        self.assertEqual([r.key for r in results], ["XXMI", "XXMI-Libs", "EFMI", "Poser"])
        self.assertTrue(self.config.xxmi_launcher.endswith("XXMI Launcher.exe"))
        efmi_root = self.config.builtin_runtime_path / "XXMI" / "EFMI"
        self.assertTrue((efmi_root / "Core" / "EFMI" / "main.ini").is_file())
        self.assertEqual(self.config.staging_mods_path, efmi_root / "Mods")
        report = runtime_deps.builtin_report(self.config)
        self.assertTrue(report["XXMI"]["present"])
        self.assertTrue(report["XXMI-Libs"]["present"])
        self.assertTrue(report["EFMI"]["present"])
        # Poser：安装包下到 runtime\poser 之后 present 必须为真（供依赖页显示）
        self.assertTrue(report["Poser"]["present"])

    def _make_external_xxmi(self) -> Path:
        """造一份「用户自己那份 XXMI」（带 `EFMI\\d3d11.dll`，供 _external_efmi_mods 识别）。"""
        external = self.root / "my-xxmi"
        (external / "Resources" / "Bin").mkdir(parents=True, exist_ok=True)
        (external / "Resources" / "Bin" / "XXMI Launcher.exe").write_bytes(b"exe")
        (external / "EFMI").mkdir(parents=True, exist_ok=True)
        (external / "EFMI" / "d3d11.dll").write_bytes(b"dll")
        return external

    def test_external_xxmi_is_not_hijacked(self) -> None:
        """用户指定自己那份 XXMI 时，自动流程不许改他的路径（2026-09-30 issue #4）。"""
        external = self._make_external_xxmi()
        launcher = str(external / "Resources" / "Bin" / "XXMI Launcher.exe")
        self.config.xxmi_launcher = launcher
        self.config.staging_mods_dir = str(external / "EFMI" / "Mods")

        self.assertFalse(runtime_deps._points_at_builtin(self.config, launcher))
        self.assertFalse(runtime_deps._points_at_builtin(self.config, self.config.staging_mods_dir))
        self.assertTrue(runtime_deps._points_at_builtin(self.config, ""))
        self.assertTrue(runtime_deps._points_at_builtin(
            self.config, str(self.config.builtin_runtime_path / "XXMI" / "EFMI" / "Mods")))

        self.config.autofill(deep=False)
        self.assertEqual(self.config.xxmi_launcher, launcher)
        self.assertEqual(self.config.staging_mods_dir, str(external / "EFMI" / "Mods"))

    def test_staging_follows_external_xxmi(self) -> None:
        """用了外部 XXMI、但 staging 还是内置默认值时，自动跟到那份的 `EFMI\\Mods`。"""
        external = self._make_external_xxmi()
        self.config.xxmi_launcher = str(external / "Resources" / "Bin" / "XXMI Launcher.exe")
        self.config.staging_mods_dir = str(self.config.builtin_runtime_path / "XXMI" / "EFMI" / "Mods")

        filled = self.config.autofill(deep=False)
        self.assertIn("staging_mods_dir", filled)
        got = Path(self.config.staging_mods_dir)
        # 同一个目录在 Windows 下可能是长名/短名（ADMINI~1）、大小写也不同，比对结构
        self.assertEqual((got.name, got.parent.name, got.parent.parent.name), ("Mods", "EFMI", "my-xxmi"))


if __name__ == "__main__":
    unittest.main()
