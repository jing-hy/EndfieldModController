# SPDX-License-Identifier: AGPL-3.0-only
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
        # 2026-11-28：`use_builtin_runtime` 现在会优先找内置 XXMI，而 `builtin_runtime_dir`
        # 是相对路径 ⇒ 不隔离会命中仓库里真实装好的内置 XXMI（并写它的配置）。
        from endfieldmodcontroller import config as config_mod
        self._builtin_patch = unittest.mock.patch.object(
            config_mod, "builtin_xxmi_launcher", lambda root: None)
        self._builtin_patch.start()
        self.addCleanup(self._builtin_patch.stop)
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
        """一键启动只开 XXMI 窗口（v1.6.5 回滚 v1.6.4 的无界面直启）。

        v1.6.4 曾改成 `--nogui --xxmi EFMI <game>`，用户实测**拉不起来终末地**，
        且无界面时没有任何可见反馈。恢复成开窗口、由用户点 Start 的方式。
        """
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

    def test_configure_xxmi_extra_libraries_drops_dead_paths(self) -> None:
        """注入库里**已经失效的旧路径要清掉**（2026-10-02）。

        背景：这里以前只追加、从不清理 —— 用户把程序目录改名/搬走后，注入库会一直带着
        旧位置的死路径（XXMI 会去加载一个不存在的 DLL），而「一键启动」的全量重写只在
        走那条链路时才覆盖它。现在写之前先剔掉不存在的路径。
        """
        root = self.root / "xxmi"
        bin_dir = root / "Resources" / "Bin"
        bin_dir.mkdir(parents=True)
        launcher_exe = bin_dir / "XXMI Launcher.exe"
        launcher_exe.write_bytes(b"")
        dead = str(self.root / "旧程序目录" / "runtime" / "dlss5" / "d3d12.dll")   # 不存在
        config_json = root / "XXMI Launcher Config.json"
        config_json.write_text(json.dumps({
            "Importers": {"EFMI": {"Importer": {
                "extra_libraries": dead,
                "extra_libraries_enabled": True,
            }}}
        }, ensure_ascii=False), encoding="utf-8")
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

        launcher.configure_xxmi_extra_libraries(cfg)

        importer = json.loads(config_json.read_text(encoding="utf-8"))["Importers"]["EFMI"]["Importer"]
        self.assertNotIn(dead, importer["extra_libraries"])
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

    def test_launch_aborts_when_builtin_components_missing(self) -> None:
        """缺内置组件时一键启动要**立刻停下并给出去下载的指引**（2026-11-28）。

        用户原话：「一键启动要是要安装应该调到下载安装，而不是卡在那」。
        后端这一道是兜底：`ensure_all` 现在只报 `update_available` 不下载，若启动流程继续
        往下走，只会撞上"找不到 XXMI Launcher"之类的半截失败 —— 所以这里必须中止。
        """
        from endfieldmodcontroller import runtime_deps

        original = runtime_deps.ensure_all
        runtime_deps.ensure_all = lambda *args, **kwargs: [
            runtime_deps.BuiltinResult("XXMI", "update_available", "本机还没有", "", str(self.root)),
            runtime_deps.BuiltinResult("EFMI", "up_to_date", "present", "", str(self.root)),
            runtime_deps.BuiltinResult("Poser", "update_available", "可选插件缺", "", str(self.root)),
        ]
        try:
            with self.assertRaises(launcher.LaunchError) as ctx:
                launcher.launch(self.config, dry_run=False)
        finally:
            runtime_deps.ensure_all = original
        message = str(ctx.exception)
        self.assertIn("XXMI", message)
        self.assertIn("下载", message)
        # Poser 是可选插件：缺它不许拦启动（否则关掉摆姿的人永远起不来）
        self.assertNotIn("Poser", message)

    def test_check_component_updates_rows(self) -> None:
        """依赖页「检查状态（不下载）」必须能返回列表（2026-11-28 用户实测报障）。

        原来内置段那行写的是 `_row(key, row, label=str(key))`，而 `_row` 的第三个形参叫
        `default` ⇒ 只要 `updates.check_updates` 返回了内置段就**每次都抛**
        `_row() got an unexpected keyword argument 'label'`（用户点一次就看到一次红字）。
        """
        from endfieldmodcontroller import dlss5_fetcher, updates

        original = updates.check_updates
        original_dlss5 = dlss5_fetcher.check_updates
        updates.check_updates = lambda config, log=None: {
            "builtin": {"XXMI": {"installed": True, "current": "v2.5.0"}}
        }
        dlss5_fetcher.check_updates = lambda config, log=None: {}
        try:
            api = EndfieldModControllerApi(self.config_path)
            result = api.check_component_updates()
        finally:
            updates.check_updates = original
            dlss5_fetcher.check_updates = original_dlss5
        rows = result.get("components") or []
        self.assertTrue(rows, "内置组件段必须能压成列表（前端按 components 渲染）")
        self.assertEqual(rows[0]["key"], "XXMI")
        self.assertEqual(rows[0]["display"], "XXMI")

    def test_stop_gryphlink_launcher(self) -> None:
        """官方启动器（`Games.exe`）要在拉起 XXMI 前被收掉（2026-11-28 用户实测报障）。

        XXMI 自己也会停它，停不掉就抛 `Failed to stop already running GRYPHLINK launcher
        process Games.exe` 并弹「EFMI 加载失败」。它停不掉、我们（提权进程）能停 ——
        所以提前收掉；真收不掉就在这里明确报错，别让用户对着 XXMI 的报错框干等。
        """
        original_names = launcher._running_process_names
        original_kill = launcher._taskkill_image
        killed: list = []
        launcher._taskkill_image = lambda name, **kwargs: killed.append(name)
        try:
            # ① 不在运行 ⇒ 一个 taskkill 都不发
            launcher._running_process_names = lambda names: []
            launcher._stop_gryphlink_launcher(self.config)
            self.assertEqual(killed, [])

            # ② 第一次在跑、收掉之后就没了 ⇒ 正常返回
            state = {"n": 0}

            def running_once(names):
                state["n"] += 1
                return ["Games.exe"] if state["n"] == 1 else []

            launcher._running_process_names = running_once
            killed.clear()
            launcher._stop_gryphlink_launcher(self.config)
            self.assertEqual(killed, ["Games.exe"])

            # ③ 一直停不掉 ⇒ 明确报错（而不是让 XXMI 去撞那个失败）
            launcher._running_process_names = lambda names: ["Games.exe"]
            with self.assertRaises(launcher.LaunchError) as ctx:
                launcher._stop_gryphlink_launcher(self.config)
            self.assertIn("Games.exe", str(ctx.exception))
        finally:
            launcher._running_process_names = original_names
            launcher._taskkill_image = original_kill

    def test_xxmi_shortcut_marked_deployed(self) -> None:
        """XXMI 的桌面快捷方式状态位要固定成"已部署"（2026-11-28 用户：老是在桌面创建）。

        XXMI 的 `ModelImporterPackage.create_shortcut` 按 `shortcut_deployed` 决定建不建，
        配置里没有别的开关（`shortcut_path` 只是它自己的记录）。我们的注入链路走 XXMI
        自己的启动按钮，那个快捷方式对用户没用 —— 所以统一置成 true，别再建。
        """
        root = self.root / "xxmi2"
        bin_dir = root / "Resources" / "Bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "XXMI Launcher.exe").write_bytes(b"")
        cfg_path = root / "XXMI Launcher Config.json"
        cfg_path.write_text(json.dumps({
            "Importers": {"EFMI": {"Importer": {"shortcut_deployed": False}}},
        }), encoding="utf-8")
        cfg = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            xxmi_launcher=str(bin_dir / "XXMI Launcher.exe"),
            game_exe=str(self.game),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        result = launcher.ensure_xxmi_game_folder(cfg)
        self.assertTrue(result.get("ok"), result)
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertIs(data["Importers"]["EFMI"]["Importer"]["shortcut_deployed"], True)


if __name__ == "__main__":
    unittest.main()
