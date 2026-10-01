"""统一控制面板（ReShade 内整合 Mod 快捷键）的测试。

覆盖三块：
① 变量识别与含义推测（`hotkey_hints`）；
② 面板部署位置与"面板不可用就不锁键"的保险（`reshade_integration` + `launcher`）；
③ actions.tsv 的新列（追加列、旧版兼容）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import core, launcher, reshade_integration
from endfieldmodcontroller.config import AppConfig
from endfieldmodcontroller.hotkey_hints import (
    hint_for,
    key_label,
    key_labels,
    mesh_tokens,
    var_phrase,
)

MOD_INI = """
namespace = \\mods\\demo.ini
[Constants]
global persist $ear = 0
global persist $coat = 0
[KeySwap_1]
condition = $active1 == 1
key = vk_left
type = cycle
$ear = 0,1,
[KeySwap_0]
key = vk_right
type = cycle
$coat = 0,1,
[TextureOverride_Head]
hash = 614a8c60
if $ear == 1
; [mesh:LOD0.614a8c60-45003-0.hair_ear_copy] [vertex_count:3170]
  drawindexedinstanced = 13098,INSTANCE_COUNT,35814,0,FIRST_INSTANCE
endif
"""

ABS_VAR_INI = """
namespace = FangyiKey
[KeyHelp]
condition = $\\Fangyi\\object_detected
key = alt 6
type = cycle
$\\FangyiVar\\open = 0,1
[KeyMouseClick]
key = VK_LBUTTON
type = hold
$\\FangyiVar\\isMouseButtonDown = 1
"""


class KeyLabelTests(unittest.TestCase):
    def test_common_keys(self) -> None:
        self.assertEqual(key_label("vk_left"), "←")
        self.assertEqual(key_label("VK_DOWN"), "↓")
        self.assertEqual(key_label("backspace"), "Backspace")
        self.assertEqual(key_label("VK_OEM_COMMA"), ",")
        self.assertEqual(key_label("VK_LBUTTON"), "鼠标左键")
        self.assertEqual(key_label("no_modifiers VK_F24"), "F24")

    def test_modifiers(self) -> None:
        self.assertEqual(key_label("ctrl alt shift VK_F1"), "Ctrl+Alt+Shift+F1")
        self.assertEqual(key_label("no_ctrl no_shift alt m"), "Alt+M")
        self.assertEqual(key_label("CTRL 0"), "Ctrl+0")

    def test_multiple_keys(self) -> None:
        self.assertEqual(key_labels(["vk_left", "vk_right"]), "← / →")
        self.assertEqual(key_labels(["vk_left;vk_left"]), "←")


class HintTests(unittest.TestCase):
    def test_variable_name_dictionary(self) -> None:
        self.assertEqual(hint_for("ear"), "耳羽")
        self.assertEqual(hint_for("Hair"), "头发")
        self.assertEqual(hint_for("hide_UI"), "隐藏界面")

    def test_variable_name_words(self) -> None:
        # 庄方宜那套 KatModular 的变量名本身就是英文描述
        self.assertEqual(hint_for("draw_component_0_zfy_tail"), "尾巴")
        self.assertIn(hint_for("draw_component_0_zfy_head_horns"), {"头部", "角"})

    def test_mesh_token_fallback(self) -> None:
        # 洛茜那种 $part_<hash>：名字看不出含义，只能靠 mesh 注释
        tokens = mesh_tokens(MOD_INI, "part_82254888_001", lines=MOD_INI.splitlines()) or []
        self.assertEqual(tokens, [])
        hint = hint_for("part_cb71c5cd", tokens=["Components-0-9 t=5715f140 BC7-Linear"])
        self.assertEqual(hint, "")

    def test_section_fallback_and_unknown(self) -> None:
        self.assertEqual(hint_for("swapkey3", section="KeySwap_3"), "部件切换")
        self.assertEqual(hint_for("totally_unknown_thing", section="Whatever"), "")

    def test_mesh_tokens_finds_mesh_comment(self) -> None:
        tokens = mesh_tokens(MOD_INI, "ear", lines=MOD_INI.splitlines())
        self.assertTrue(any("hair_ear_copy" in token for token in tokens))
        self.assertEqual(hint_for("part_x", tokens=tokens), "耳羽")

    def test_var_phrase(self) -> None:
        self.assertEqual(var_phrase("draw_component_0_zfy_head_horns"), "zfy head horns")
        self.assertEqual(var_phrase("swapkey12"), "")


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-parse-")
        self.mod = Path(self.tmp.name) / "DemoMod"
        self.mod.mkdir(parents=True)
        (self.mod / "mod.ini").write_text(MOD_INI, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_actions_carry_panel_fields(self) -> None:
        actions = core.parse_mod_actions(self.mod, self.mod)
        by_var = {a.var_name: a for a in actions}
        ear = by_var["ear"]
        self.assertEqual(ear.hint, "耳羽")
        self.assertEqual(ear.key_label, "←")
        self.assertEqual(ear.kind, "cycle")
        self.assertEqual(ear.condition, "$active1 == 1")
        self.assertEqual(ear.targets, ["$\\mods\\demo.ini\\ear"])

    def test_absolute_namespace_variables(self) -> None:
        (self.mod / "key.ini").write_text(ABS_VAR_INI, encoding="utf-8")
        actions = core.parse_mod_actions(self.mod, self.mod)
        names = {a.var_name for a in actions}
        self.assertIn("open", names)
        # `type = hold` 的瞬时状态不该变成开关
        self.assertNotIn("isMouseButtonDown", names)
        opened = next(a for a in actions if a.var_name == "open")
        self.assertEqual(opened.target_absolute, "$\\FangyiVar\\open")
        self.assertEqual(opened.key_label, "Alt+6")

    def test_no_false_match_on_comparison(self) -> None:
        (self.mod / "cmp.ini").write_text(
            "\n".join([
                "namespace = DemoCmp",
                "[KeyA]",
                "key = vk_9",
                "type = cycle",
                "$thing = 0,1",
                "[Constants]",
                "$thing = 0",
            ]),
            encoding="utf-8",
        )
        actions = [a for a in core.parse_mod_actions(self.mod, self.mod) if a.var_name == "thing"]
        self.assertEqual(len(actions), 1)
        # 值必须还解析成 0/1 两个档位，而不是把 "== 1" 这种比较当成赋值
        self.assertEqual(actions[0].values, ["0", "1"])


class TsvSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-tsv-")
        self.root = Path(self.tmp.name)
        self.mod_dir = self.root / "DemoMod"
        self.mod_dir.mkdir(parents=True)
        (self.mod_dir / "mod.ini").write_text(MOD_INI, encoding="utf-8")
        self.controller = self.root / "MC_Controller"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_new_columns_appended(self) -> None:
        from endfieldmodcontroller import core as mc_core

        staged = mc_core._make_mod_info(self.mod_dir, self.mod_dir, "佩丽卡", "character", {}, self.mod_dir.parent)
        manifest = mc_core.generate_controller_mod([staged], self.controller)
        lines = (self.controller / "actions.tsv").read_text(encoding="utf-8").splitlines()
        header = lines[0].split("\t")
        # 前 15 列保持原样（旧版 addon 靠列号读，追加列不破坏兼容）
        self.assertEqual(header[:15], [
            "id", "label", "kind", "mod_name", "values", "description",
            "current", "namespace", "var_name", "section", "run_command", "original_keys",
            "wire_id", "send_index", "merged",
        ])
        self.assertEqual(header[15:19], ["hint", "key_label", "char_group", "condition"])
        ear_row = next(line for line in lines[1:] if "\tear\t" in line)
        cells = ear_row.split("\t")
        self.assertEqual(len(cells), len(header))
        self.assertEqual(cells[15], "耳羽")
        self.assertEqual(cells[16], "←")
        self.assertEqual(cells[17], "佩丽卡")
        self.assertTrue(manifest["actions"])


class PanelDeployTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-deploy-")
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.dlss5 = self.runtime / "dlss5"
        self.dlss5.mkdir(parents=True)
        (self.dlss5 / "d3d12.dll").write_bytes(b"MZ" + b"\0" * 64)
        self.controller = self.runtime / "EFMI" / "Mods" / "MC_Controller"
        self.controller.mkdir(parents=True)
        (self.controller / "actions.tsv").write_text("id\tlabel\n1\tx\n2\ty\n", encoding="utf-8")
        self.addon = self.root / "endfieldmodcontroller.addon64"
        self.addon.write_bytes(b"MZ" + b"panel" * 100)
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.runtime / "EFMI" / "Mods"),
            dlss5_dir=str(self.dlss5),
            reshade_injection="xxmi_extra",
            reshade_dll=str(self.dlss5 / "d3d12.dll"),
        )
        self.patcher = mock.patch.object(reshade_integration, "built_addon_path", return_value=self.addon)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def test_deploy_goes_to_reshade_base_dir(self) -> None:
        result = reshade_integration.deploy_panel(self.config, self.controller)
        self.assertTrue((self.dlss5 / reshade_integration.ADDON_NAME).is_file())
        self.assertTrue((self.dlss5 / "actions.tsv").is_file())
        self.assertTrue((self.dlss5 / "user_ini_path.txt").is_file())
        info = (self.dlss5 / "panel_info.txt").read_text(encoding="utf-8")
        self.assertIn("actions=2", info)
        self.assertTrue(result["possible"])

    def test_legacy_panel_locations_are_cleaned(self) -> None:
        legacy_dir = self.config.reshade_runtime_path / "Addons"
        legacy_dir.mkdir(parents=True)
        legacy = legacy_dir / "endfieldmodcontroller.addon"
        legacy.write_bytes(b"old")
        reshade_integration.deploy_panel(self.config, self.controller)
        self.assertFalse(legacy.exists())
        self.assertTrue((self.dlss5 / reshade_integration.ADDON_NAME).is_file())

    def test_takeover_refused_when_reshade_disabled(self) -> None:
        self.config.reshade_injection = "none"
        possible, reason = reshade_integration.takeover_possible(self.config)
        self.assertFalse(possible)
        self.assertIn("ReShade", reason)

    def test_resolve_takeover_false_keeps_hotkeys(self) -> None:
        self.config.hotkey_takeover = True
        self.config.reshade_injection = "none"
        applied = launcher.resolve_hotkey_takeover(self.config, self.controller)
        self.assertFalse(applied)   # 面板用不了 → 绝不允许锁键
        self.config.reshade_injection = "xxmi_extra"
        applied = launcher.resolve_hotkey_takeover(self.config, self.controller)
        self.assertTrue(applied)

    def test_panel_status_reports_readiness(self) -> None:
        before = reshade_integration.panel_status(self.config)
        self.assertFalse(before["ready"])
        reshade_integration.deploy_panel(self.config, self.controller)
        after = reshade_integration.panel_status(self.config)
        self.assertTrue(after["ready"])
        self.assertTrue(after["addon_present"])
        self.assertTrue(after["actions_present"])

    def test_font_is_configured_once(self) -> None:
        (self.dlss5 / "ReShade.ini").write_text("[STYLE]\nFontSize=20\n", encoding="utf-8")
        result = reshade_integration.ensure_panel_font(self.config)
        if not result.get("changed"):
            self.skipTest(f"本机没有中文字体可测：{result.get('reason')}")
        text = (self.dlss5 / "ReShade.ini").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^Font=.*\.(ttc|ttf)$")
        self.assertTrue((self.dlss5 / "ReShade.ini.bak-before-panel-font").is_file())
        # 第二次不该再改（用户自己设过就尊重他）
        again = reshade_integration.ensure_panel_font(self.config)
        self.assertFalse(again.get("changed"))

    def test_missing_addon_is_reported_not_silent(self) -> None:
        with mock.patch.object(reshade_integration, "built_addon_path", return_value=None):
            result = reshade_integration.deploy_panel(self.config, self.controller)
        self.assertTrue(result["warnings"])
        self.assertFalse(result["possible"])


class InitializePanelCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-init-")
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.dlss5 = self.runtime / "dlss5"
        self.dlss5.mkdir(parents=True)
        (self.dlss5 / "d3d12.dll").write_bytes(b"MZ" + b"\0" * 64)
        self.controller = self.runtime / "EFMI" / "Mods" / "MC_Controller"
        self.controller.mkdir(parents=True)
        (self.controller / "actions.tsv").write_text("id\tlabel\n1\tx\n", encoding="utf-8")
        self.addon = self.root / "endfieldmodcontroller.addon64"
        self.addon.write_bytes(b"MZ")
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.runtime / "EFMI" / "Mods"),
            dlss5_dir=str(self.dlss5),
            reshade_injection="xxmi_extra",
            reshade_dll=str(self.dlss5 / "d3d12.dll"),
        )
        self.patcher = mock.patch.object(reshade_integration, "built_addon_path", return_value=self.addon)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    def test_check_skips_when_disabled(self) -> None:
        from endfieldmodcontroller import initialize

        report = initialize.Report()
        initialize._check_hotkey_panel(self.config, report, None)
        payload = report.to_dict()
        check = next(c for c in payload["checks"] if c["key"] == "hotkey_panel")
        self.assertTrue(check["ok"])
        self.assertIn("未开启", check["message"])

    def test_check_deploys_when_enabled(self) -> None:
        from endfieldmodcontroller import initialize

        self.config.hotkey_takeover = True
        report = initialize.Report()
        initialize._check_hotkey_panel(self.config, report, None)
        payload = report.to_dict()
        check = next(c for c in payload["checks"] if c["key"] == "hotkey_panel")
        self.assertTrue(check["ok"], check["message"])
        self.assertTrue((self.dlss5 / reshade_integration.ADDON_NAME).is_file())

    def test_check_marks_panel_unusable(self) -> None:
        from endfieldmodcontroller import initialize

        self.config.hotkey_takeover = True
        self.config.reshade_injection = "none"
        report = initialize.Report()
        initialize._check_hotkey_panel(self.config, report, None)
        payload = report.to_dict()
        check = next(c for c in payload["checks"] if c["key"] == "hotkey_panel")
        self.assertFalse(check["ok"])
        self.assertIn("面板用不了", check["message"])


class HotkeySwitchTests(unittest.TestCase):
    """开关一次要真的做完两件事：锁键 / 还键（不能只写配置）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-switch-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "builtin" / "XXMI" / "EFMI" / "Mods"
        self.staging.mkdir(parents=True)
        self.dlss5 = self.runtime / "dlss5"
        self.dlss5.mkdir(parents=True)
        (self.dlss5 / "d3d12.dll").write_bytes(b"MZ" + b"\0" * 64)
        for name in ("Alice", "Bob"):
            path = self.library / "佩丽卡" / name
            path.mkdir(parents=True)
            (path / "mod.ini").write_text(
                "namespace = Demo\n[Constants]\nglobal persist $cape = 0\n"
                "[KeyCape]\nkey = vk_left\ntype = cycle\n$cape = 0,1\n",
                encoding="utf-8",
            )
        self.config_path = self.root / "config.json"
        self.config = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            dlss5_dir=str(self.dlss5),
            reshade_injection="xxmi_extra",
            reshade_dll=str(self.dlss5 / "d3d12.dll"),
            allow_same_character_mods=True,
            dependency_manifest=str(Path(core.__file__).parents[1] / "dependencies.json"),
        )
        self.config.save(self.config_path)
        self.addon = self.root / "endfieldmodcontroller.addon64"
        self.addon.write_bytes(b"MZ")
        self.patcher = mock.patch.object(reshade_integration, "built_addon_path", return_value=self.addon)
        self.patcher.start()
        from endfieldmodcontroller.api import EndfieldModControllerApi

        # ⚠ 别依赖"本机到底有没有开游戏"：开发机上真开着 Endfield 时，切换开关会走
        #   "游戏在跑 → 先不重新生成控制器"那条分支（这是对的行为），测试却会假失败。
        self.running_patcher = mock.patch.object(
            EndfieldModControllerApi, "game_running", return_value={"running": False}
        )
        self.running_patcher.start()
        self.api = EndfieldModControllerApi(self.config_path)
        self.api.config.selected_mods = [mod["id"] for mod in self.api.scan()["mods"]]
        self.api.config.save()

    def tearDown(self) -> None:
        self.running_patcher.stop()
        self.patcher.stop()
        self.tmp.cleanup()

    def _staged_keys(self) -> list[str]:
        keys: list[str] = []
        for child in self.staging.iterdir():
            if not child.is_dir() or child.name == "MC_Controller":
                continue
            for ini in core.iter_ini_files(child):
                for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped.lower().startswith("key") and "=" in stripped:
                        keys.append(stripped.split("=", 1)[1].strip().lower())
        return keys

    def test_switch_locks_and_restores(self) -> None:
        self.api.prepare()
        self.assertTrue(self._staged_keys())
        self.assertTrue(all("vk_left" in key for key in self._staged_keys()))

        opened = self.api.set_hotkey_takeover(True)
        self.assertTrue(opened["ready"])
        self.assertTrue(all("vk_f24" in key for key in self._staged_keys()),
                        self._staged_keys())
        self.assertTrue((self.dlss5 / reshade_integration.ADDON_NAME).is_file())
        self.assertIn("takeover=1", (self.dlss5 / "panel_info.txt").read_text(encoding="utf-8"))
        # 控制器自己的合成键不受影响（否则面板点不动任何东西）
        controller_ini = self.staging / "MC_Controller" / "controller.ini"
        self.assertIn("ctrl alt shift VK_F11", controller_ini.read_text(encoding="utf-8"))

        closed = self.api.set_hotkey_takeover(False)
        self.assertNotIn("vk_f24", " ".join(self._staged_keys()))
        self.assertIn("还原", closed["message"])
        self.assertIn("takeover=0", (self.dlss5 / "panel_info.txt").read_text(encoding="utf-8"))


class HintsFileTests(unittest.TestCase):
    def test_shipped_table_is_valid(self) -> None:
        path = Path(core.__file__).with_name("hotkey_hints.json")
        self.assertTrue(path.is_file(), "hotkey_hints.json 必须随包（build_exe 的 ADD_DATA）")
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in ("vars", "tokens", "sections"):
            self.assertIn(section, data)
        self.assertEqual(hint_for("swapvar_neiku"), "内裤")


if __name__ == "__main__":
    unittest.main()
