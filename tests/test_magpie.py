"""Magpie Experimental（可选扩展）的接入测试。

用户 2026-10-01 要求：「做成拓展功能，在依赖上面加一个这个的开关，**默认关，关不下载**，
如果未下载，启动一栏这个就滑块变灰色，介绍加上需要在依赖页开启下载」。

**这里最要紧的一条**：开关关着时，任何链路都**不许**发起下载（主包约 467 MB）。
所以测试直接断言 `_latest_release_asset` / `_download_extract` **没有被调用过**。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import magpie, runtime_deps
from endfieldmodcontroller.config import AppConfig


def _config(root: Path, **kw) -> AppConfig:
    return AppConfig(
        library_dir=str(root / "library"),
        runtime_dir=str(root / "runtime"),
        staging_mods_dir=str(root / "runtime" / "EFMI" / "Mods"),
        magpie_dir=str(root / "runtime" / "magpie"),
        **kw,
    )


class MagpieDisabledTests(unittest.TestCase):
    """默认关 —— 绝不下载。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-magpie-")
        self.root = Path(self.tmp.name)
        self.config = _config(self.root)
        self.assertEqual(self.config.magpie_enabled, False, "Magpie 必须默认关闭")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_disabled_never_downloads(self) -> None:
        with mock.patch.object(runtime_deps, "_latest_release_asset") as mock_release, \
                mock.patch.object(runtime_deps, "_download_extract") as mock_download:
            result = runtime_deps.ensure_magpie(self.config)
        self.assertEqual(result.status, "skipped")
        mock_release.assert_not_called()
        mock_download.assert_not_called()
        self.assertFalse((self.root / "runtime" / "magpie").exists(), "关着时不该建目录")

    def test_ensure_all_skips_magpie_when_disabled(self) -> None:
        """一键启动那条链路（ensure_all）也不能偷偷下 467 MB。"""
        with mock.patch.object(runtime_deps, "ensure_xxmi") as m1, \
                mock.patch.object(runtime_deps, "ensure_xxmi_libs") as m2, \
                mock.patch.object(runtime_deps, "ensure_efmi") as m3, \
                mock.patch.object(runtime_deps, "ensure_poser") as m4, \
                mock.patch.object(runtime_deps, "_download_extract") as mock_download:
            for m in (m1, m2, m3, m4):
                m.return_value = runtime_deps.BuiltinResult("x", "up_to_date", "ok")
            results = runtime_deps.ensure_all(self.config)
        by_key = {r.key: r for r in results}
        self.assertIn("Magpie", by_key)
        self.assertEqual(by_key["Magpie"].status, "skipped")
        mock_download.assert_not_called()

    def test_report_marks_it_optional(self) -> None:
        report = runtime_deps.builtin_report(self.config)
        self.assertIn("Magpie", report)
        item = report["Magpie"]
        self.assertFalse(item["required"], "可选扩展绝不能算必需项")
        self.assertFalse(item["needed"], "默认关着时不该被一键启动当成待补项")
        self.assertIn("未启用", item["status"])

    def test_status_says_cannot_toggle_before_download(self) -> None:
        status = magpie.status(self.config)
        self.assertFalse(status["installed"])
        self.assertFalse(status["can_toggle"], "未下载时启动页滑块要灰掉")
        self.assertEqual(status["enabled"], False)
        self.assertGreater(status["approx_bytes"], 400 * 1024 * 1024, "要如实报告 467 MB 量级")
        self.assertIn("不如游戏内 DLSS5", status["effect_note"])

    def test_launch_without_download_is_refused_with_hint(self) -> None:
        result = magpie.launch(self.config)
        self.assertFalse(result["ok"])
        self.assertIn("依赖页", result["message"])


class MagpieEnabledTests(unittest.TestCase):
    """打开开关 → 才下载；下完 → 启动页滑块可用。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-magpie-")
        self.root = Path(self.tmp.name)
        self.config = _config(self.root, magpie_enabled=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enabled_downloads_and_marks_installed(self) -> None:
        def fake_extract(_url, _asset, root, *_args, **_kw):
            (Path(root)).mkdir(parents=True, exist_ok=True)
            (Path(root) / magpie.EXE_NAME).write_bytes(b"MZ")

        with mock.patch.object(runtime_deps, "_latest_release_asset",
                               return_value=("https://example.invalid/m.zip", "v0.6.8-experimental.1",
                                             "Magpie-Experimental-x64.zip", "sha256:deadbeef")) as mock_release, \
                mock.patch.object(runtime_deps, "_download_extract", side_effect=fake_extract) as mock_download:
            result = runtime_deps.ensure_magpie(self.config)
        mock_release.assert_called_once()
        self.assertEqual(mock_release.call_args.kwargs.get("include_prerelease"), True,
                         "Magpie 只发预发布，必须走列表接口")
        mock_download.assert_called_once()
        self.assertEqual(result.status, "installed")
        self.assertEqual(result.version, "v0.6.8-experimental.1")
        self.assertTrue(magpie.installed(self.config))
        self.assertEqual(magpie.version(self.config), "v0.6.8-experimental.1")
        status = magpie.status(self.config)
        self.assertTrue(status["can_toggle"], "下载完成后启动页滑块要能用")
        report = runtime_deps.builtin_report(self.config)
        self.assertEqual(report["Magpie"]["status"], "已安装")
        self.assertTrue(report["Magpie"]["enabled"])

    def test_up_to_date_does_not_redownload(self) -> None:
        root = self.config.magpie_path
        root.mkdir(parents=True, exist_ok=True)
        (root / magpie.EXE_NAME).write_bytes(b"MZ")
        magpie.write_marker(self.config, {"version": "v0.6.8-experimental.1"})
        with mock.patch.object(runtime_deps, "_latest_release_asset",
                               return_value=("u", "v0.6.8-experimental.1", "a", "")), \
                mock.patch.object(runtime_deps, "_download_extract") as mock_download:
            result = runtime_deps.ensure_magpie(self.config)
        self.assertEqual(result.status, "up_to_date")
        mock_download.assert_not_called()


class MagpieApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-magpie-api-")
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "config.json"
        _config(self.root).save(self.config_path)
        from endfieldmodcontroller.api import EndfieldModControllerApi

        self.api = EndfieldModControllerApi(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_turning_off_keeps_files_and_does_not_download(self) -> None:
        self.api.config.magpie_enabled = True
        with mock.patch.object(runtime_deps, "ensure_magpie") as mock_ensure:
            result = self.api.set_magpie_enabled(False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["downloading"])
        self.assertFalse(self.api.config.magpie_enabled)
        mock_ensure.assert_not_called()

    def test_turning_on_starts_a_download_task(self) -> None:
        with mock.patch.object(runtime_deps, "ensure_magpie",
                               return_value=runtime_deps.BuiltinResult("Magpie", "installed", "ok")) as mock_ensure:
            result = self.api.set_magpie_enabled(True)
            self.assertTrue(result["downloading"])
            # 等后台线程跑完（它只做一次 mock 调用，很快）
            for _ in range(100):
                task = self.api.get_dependency_progress()
                if not task.get("running"):
                    break
                import time

                time.sleep(0.02)
        mock_ensure.assert_called_once()
        self.assertTrue(self.api.config.magpie_enabled)

    def test_state_carries_magpie_status(self) -> None:
        state = self.api.get_state()
        self.assertIn("magpie", state)
        self.assertIn("can_toggle", state["magpie"])


if __name__ == "__main__":
    unittest.main()
