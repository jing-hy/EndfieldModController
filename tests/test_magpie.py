"""Magpie Experimental（可选扩展）的接入测试。

用户 2026-10-01 要求：「做成拓展功能，在依赖上面加一个这个的开关，**默认关，关不下载**，
如果未下载，启动一栏这个就滑块变灰色，介绍加上需要在依赖页开启下载」。

**这里最要紧的一条**：开关关着时，任何链路都**不许**发起下载（主包约 467 MB）。
所以测试直接断言 `_latest_release_asset` / `_download_extract` **没有被调用过**。
"""
from __future__ import annotations

import json
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


class MagpieAutoConfigureTests(unittest.TestCase):
    """**一键启动时自动配置 Magpie**（用户：「我需要一键配置…是一键启动的时候自动配置」）。

    ⚠️ **这些测试必须把 `config_path` 打桩到临时文件** —— 本机 `%LOCALAPPDATA%/Magpie/config/v4e/config.json`
    是**用户的真实配置**，我第一版自测直接跑 `ensure_configured()` 就把它改掉了
    （把整数索引写成了字符串，等于没配）。教训见 lesson：测试碰真实环境 = 事故。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-magpie-cfg-")
        self.root = Path(self.tmp.name)
        self.config = _config(self.root, magpie_enabled=True)
        root = self.config.magpie_path
        root.mkdir(parents=True, exist_ok=True)
        (root / magpie.EXE_NAME).write_bytes(b"MZ")          # 假装已下载
        self.cfg_file = root / "config" / "v4e" / "config.json"
        self.cfg_file.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch(self, *, running: bool = False):
        return mock.patch.multiple(
            magpie,
            config_path=mock.Mock(return_value=self.cfg_file),
            running=mock.Mock(return_value=running),
        )

    def _write(self, data: dict) -> None:
        self.cfg_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_writes_integer_index_not_name(self) -> None:
        """**核心**：`scalingMode` 必须是 `scalingModes` 里的**整数索引**（源码 writer.Int/ReadInt）。"""
        self._write({
            "scalingModes": [{"name": "Lanczos"}, {"name": "FSR"}, {"name": "DLSSNR"}],
            "profiles": [{"scalingMode": 0}, {"name": "game", "pathRule": "Endfield.exe"}],
        })
        with self._patch():
            result = magpie.ensure_configured(self.config)
        self.assertTrue(result["changed"], result)
        saved = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["profiles"][0]["scalingMode"], 2, "要写整数索引，不是 'DLSSNR' 字符串")
        self.assertEqual(saved["profiles"][1]["name"], "game", "别的 profile 不许动")
        self.assertTrue((self.cfg_file.parent / (self.cfg_file.name + ".mc.bak")).is_file(), "写前要备份")

    def test_adds_mode_when_missing(self) -> None:
        self._write({"scalingModes": [{"name": "Lanczos"}], "profiles": [{"scalingMode": 0}]})
        with self._patch():
            result = magpie.ensure_configured(self.config)
        self.assertTrue(result["changed"], result)
        saved = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["profiles"][0]["scalingMode"], 1)
        self.assertEqual(saved["scalingModes"][1]["name"], "DLSSNR")
        self.assertIn("DLSSNR", saved["scalingModes"][1]["effects"][0]["name"])

    def test_idempotent(self) -> None:
        self._write({"scalingModes": [{"name": "DLSSNR"}], "profiles": [{"scalingMode": 0}]})
        with self._patch():
            result = magpie.ensure_configured(self.config)
        self.assertFalse(result["changed"])
        self.assertEqual(result["reason"], "already")

    def test_refuses_while_magpie_running(self) -> None:
        self._write({"scalingModes": [{"name": "DLSSNR"}], "profiles": [{"scalingMode": 1}]})
        with self._patch(running=True):
            result = magpie.ensure_configured(self.config)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "magpie_running")
        saved = json.loads(self.cfg_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["profiles"][0]["scalingMode"], 1, "在跑就不能改，否则会被它整份写回")

    def test_no_config_yet_is_not_an_error(self) -> None:
        """用户还没打开过 Magpie → **我们不凭空造整份配置**，只给引导。"""
        with mock.patch.multiple(magpie, config_path=mock.Mock(return_value=None),
                                 running=mock.Mock(return_value=False)):
            result = magpie.ensure_configured(self.config)
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["reason"], "no_config_yet")
        self.assertIn("先打开它一次", result["message"])

    def test_skips_when_disabled_or_not_installed(self) -> None:
        off = _config(self.root / "off")
        self.assertEqual(magpie.ensure_configured(off)["reason"], "disabled")
        not_installed = _config(self.root / "ni", magpie_enabled=True)
        self.assertEqual(magpie.ensure_configured(not_installed)["reason"], "not_installed")


class MagpieGameAttachTests(unittest.TestCase):
    """**随游戏自动开关**（用户：「接管它的开关，在终末地开始运行的时候打开，终末地退出的时候关闭」）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-magpie-attach-")
        self.root = Path(self.tmp.name)
        self.config = _config(self.root, magpie_enabled=True)
        self.config.magpie_path.mkdir(parents=True, exist_ok=True)
        (self.config.magpie_path / magpie.EXE_NAME).write_bytes(b"MZ")
        magpie._ATTACHED_BY_US["started"] = False      # 模块级状态，逐条清干净

    def tearDown(self) -> None:
        magpie._ATTACHED_BY_US["started"] = False
        self.tmp.cleanup()

    def test_attach_launches_and_detach_closes(self) -> None:
        with mock.patch.object(magpie, "running", return_value=False), \
                mock.patch.object(magpie, "launch", return_value={"ok": True}) as mock_launch:
            result = magpie.attach_to_game(self.config)
        self.assertTrue(result["ok"])
        mock_launch.assert_called_once()
        self.assertTrue(magpie._ATTACHED_BY_US["started"])
        with mock.patch.object(magpie.subprocess, "run") as mock_run:
            closed = magpie.detach_from_game(self.config)
        self.assertTrue(closed.get("closed"))
        self.assertEqual(mock_run.call_args.args[0][:2], ["taskkill", "/IM"])
        self.assertFalse(magpie._ATTACHED_BY_US["started"])

    def test_attach_leaves_user_started_instance_alone(self) -> None:
        """Magpie 本来就在跑（用户自己开的）→ 不重启、也不在退出时关它。"""
        with mock.patch.object(magpie, "running", return_value=True), \
                mock.patch.object(magpie, "launch") as mock_launch:
            result = magpie.attach_to_game(self.config)
        self.assertEqual(result["skipped"], "already_running")
        mock_launch.assert_not_called()
        with mock.patch.object(magpie.subprocess, "run") as mock_run:
            closed = magpie.detach_from_game(self.config)
        self.assertEqual(closed["skipped"], "not_started_by_us")
        mock_run.assert_not_called()

    def test_attach_skips_when_disabled_or_not_installed(self) -> None:
        off = _config(self.root / "off")
        self.assertEqual(magpie.attach_to_game(off)["skipped"], "disabled")
        ni = _config(self.root / "ni", magpie_enabled=True)
        self.assertEqual(magpie.attach_to_game(ni)["skipped"], "not_installed")

    def test_detach_without_attach_does_nothing(self) -> None:
        with mock.patch.object(magpie.subprocess, "run") as mock_run:
            result = magpie.detach_from_game(self.config)
        self.assertEqual(result["skipped"], "not_started_by_us")
        mock_run.assert_not_called()
