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

MARKER_INI = """
namespace = MarkerDemo
[Constants]
global persist $coat = 0
global $creditinfo = 0
global $active1 = 0

[KeyCoatA]
key = vk_a
type = cycle
$coat = 0, 1

[KeyCoatB]
key = vk_b
$creditinfo = 0
$active1 = 1

[KeyCoatC]
key = vk_c
$creditinfo = 0
$active1 = 0

[KeyCoatD]
key = vk_d
$creditinfo = 0
$active1 = 1
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
        self.assertEqual(key_label("no_modifiers VK_F23"), "F23")

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

    def test_internal_markers_are_filtered_out(self) -> None:
        """「内部标记」变量不该出现在面板上（用户 2026-10-02：「creditinfo 要过滤掉」）。

        现场两种形态：
          * 某 Mod 在每个 `[Key*]` 段里都跟着一句 `$creditinfo = 0`（Mod 注释：
            ``; This acts as the "lock" for the UI notification``）；
          * 另一个 Mod 用 `$active1 = 0/1` 标记"这个部件这一帧画没画"（`[Present]` 里
            `post $active1 = 0` 每帧清零）。
        判据 = **非 persist** + 同文件里被赋值 **≥3 次** + **从不写成逗号列表**（真开关的写法）。
        """
        (self.mod / "marker.ini").write_text(MARKER_INI, encoding="utf-8")
        actions = core.parse_mod_actions(self.mod, self.mod)
        names = {a.var_name for a in actions}
        self.assertIn("coat", names)            # 真开关（persist + 逗号列表）保留
        self.assertNotIn("creditinfo", names)   # 内部标记：过滤
        self.assertNotIn("active1", names)

    def test_absolute_namespace_variables(self) -> None:
        (self.mod / "key.ini").write_text(ABS_VAR_INI, encoding="utf-8")
        actions = core.parse_mod_actions(self.mod, self.mod)
        names = {a.var_name for a in actions}
        self.assertIn("open", names)
        # `type = hold` 的瞬时状态不该变成开关
        self.assertNotIn("isMouseButtonDown", names)
        opened = next(a for a in actions if a.var_name == "open")
        # **原样大小写**（`FangyiVar` 不是笔误）：ini 层变量名大小写敏感；`d3dx_user.ini`
        # 里的小写只是持久化层的写法，别拿它当书写规范（2026-10-02 更正过一次误判）。
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
        # 面板用不了 → 绝不允许锁键（老红线不变：不能出现"锁了键却没面板"）
        self.config.hotkey_takeover = True
        self.config.reshade_injection = "none"
        self.assertFalse(launcher.resolve_hotkey_takeover(self.config, self.controller))
        # 2026-10-02 晚恢复「Mod 快捷键锁定」（默认开）：面板可用 + 开关开着 ⇒ 真的锁键
        self.config.reshade_injection = "xxmi_extra"
        self.assertTrue(launcher.resolve_hotkey_takeover(self.config, self.controller))
        self.assertTrue((self.dlss5 / reshade_integration.ADDON_NAME).is_file(),
                        "锁键的同时必须把面板铺进 ReShade")
        # 关掉开关 ⇒ 一个键都不改写（留后路：想手按就关掉）
        self.config.hotkey_takeover = False
        self.assertFalse(launcher.resolve_hotkey_takeover(self.config, self.controller))

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

        # 默认值现在是 True（用户要求默认开启），这条测的是"关掉时跳过"，显式关一下
        self.config.hotkey_takeover = False
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
        # 这条测的是"开关的往返"：默认值现在是 True（用户要求默认开启），
        # 所以从这里显式关掉、再从"关"开始走一遍开→关。
        self.api.config.hotkey_takeover = False
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

    def test_switch_deploys_panel_and_locks_mod_keys(self) -> None:
        """开关打开 = **铺面板 + 锁 Mod 按键**（2026-10-02 晚恢复的「Mod 快捷键锁定」）。

        锁键是为了治"多个 Mod 抢同一个真实键"：Mod 的 `key` 行被改写成
        `no_modifiers vk_f23`，手按原键失效，操作集中到游戏内面板。面板本身走
        **F13..F24 内部通道**（切档逻辑注入在 Mod 自己的 ini 里），与 `key` 段无关，
        所以锁键不影响面板 —— 这正是它今天能重新启用的原因。

        ⚠️ 2026-10-06：`set_hotkey_takeover` 里的重铺（`prepare()`）改成**后台执行**了
        （接口不许被秒级重活堵住，见 `api._run_background` 的说明）。这里把它换回
        **同步**执行，断言才能直接看到"锁键后 staging 的 key 被改写"这件事本身 ——
        异步只是执行方式，不改变这条语义。
        """
        self.api._run_background = lambda func, *args, **kwargs: func(*args, **kwargs)
        self.api.prepare()
        self.assertTrue(self._staged_keys())
        self.assertTrue(all("vk_left" in key for key in self._staged_keys()))

        opened = self.api.set_hotkey_takeover(True)
        self.assertTrue(opened["ready"])
        self.assertTrue((self.dlss5 / reshade_integration.ADDON_NAME).is_file())
        # 开关打开 ⇒ Mod 原键被锁定（防抢键）
        self.assertTrue(all("vk_f23" in key for key in self._staged_keys()), self._staged_keys())
        # `panel_info.txt` 的 takeover 含义：Mod 原键**是否真被锁住** ⇒ 这里应为 1
        self.assertIn("takeover=1", (self.dlss5 / "panel_info.txt").read_text(encoding="utf-8"))

        # 面板通道（2026-10-02 第二版）：**F13..F24，不带任何修饰键** ——
        # 用户原话「不要用 alt 这种辅助键」。红线依旧：绝不落在 F1..F12
        # （2026-10-01 实测 F6 = DLSS5 的 NR 开关、F7 = 第一人称切换）。
        controller_ini = self.staging / "MC_Controller" / "controller.ini"
        ini_text = controller_ini.read_text(encoding="utf-8")
        self.assertIn("key = VK_F13", ini_text)
        self.assertIn("key = VK_F24", ini_text)   # 面板协议的提交键（未变）
        key_lines = [line.strip().lower() for line in ini_text.splitlines()
                     if line.strip().lower().startswith("key =")]
        self.assertTrue(key_lines, "controller.ini 里应该有 key 行")
        for line in key_lines:
            for modifier in ("ctrl", "alt", "shift", "no_modifiers"):
                self.assertNotIn(modifier, line,
                                 f"面板通道不该带修饰键：{line}（用户：「不要用 alt 这种辅助键」）")
        self.assertNotRegex(ini_text, r"key = VK_F1\b")

        closed = self.api.set_hotkey_takeover(False)
        self.assertTrue(all("vk_left" in key for key in self._staged_keys()))
        self.assertIn("已关闭", closed["message"])


def _mini_pe64(import_name: str, dll_name: str = "FAKE.dll") -> bytes:
    """造一个最小可解析的 PE64（一节 `.rdata`，里面放一个导入表）。

    `initialize._pe_imports_name_bytes()` 的判据是 PE 结构本身（"这个 dll 有没有导入
    某个函数"），所以这里直接按结构拼一个出来，不依赖机器上恰好装着哪个 dll。
    """
    section_va = 0x1000
    raw_ptr = 0x200
    rdata = bytearray(0x200)
    desc = 0x00          # IMAGE_IMPORT_DESCRIPTOR（20 字节；后面紧跟全 0 结束项）
    thunk = 0x40         # INT / IAT 数组
    name_ref = 0x60      # 来源 dll 名
    hint_name = 0x80     # IMAGE_IMPORT_BY_NAME（hint(2) + 名字 + \0）

    def put(offset: int, value: int, size: int) -> None:
        rdata[offset:offset + size] = value.to_bytes(size, "little")

    put(desc + 0, section_va + thunk, 4)          # OriginalFirstThunk
    put(desc + 12, section_va + name_ref, 4)      # Name
    put(desc + 16, section_va + thunk + 16, 4)    # FirstThunk（IAT）
    put(thunk + 0, section_va + hint_name, 8)     # INT[0]
    put(thunk + 16, section_va + hint_name, 8)    # IAT[0]
    rdata[name_ref:name_ref + len(dll_name) + 1] = dll_name.encode("ascii") + b"\0"
    rdata[hint_name:hint_name + 2] = b"\0\0"
    payload = import_name.encode("ascii") + b"\0"
    rdata[hint_name + 2:hint_name + 2 + len(payload)] = payload

    headers = bytearray(raw_ptr)
    headers[0:2] = b"MZ"
    headers[0x3C:0x40] = (0x80).to_bytes(4, "little")     # e_lfanew
    headers[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    headers[coff:coff + 2] = (0x8664).to_bytes(2, "little")            # machine = x64
    headers[coff + 2:coff + 4] = (1).to_bytes(2, "little")             # NumberOfSections
    headers[coff + 16:coff + 18] = (240).to_bytes(2, "little")         # SizeOfOptionalHeader
    opt = coff + 20
    headers[opt:opt + 2] = (0x20B).to_bytes(2, "little")               # PE32+
    dd = opt + 112                                                     # DataDirectory 起点
    headers[dd + 8:dd + 12] = (section_va + desc).to_bytes(4, "little")   # [1] = 导入表 RVA
    section = dd + 16 * 8
    headers[section:section + 6] = b".rdata"
    headers[section + 8:section + 12] = (len(rdata)).to_bytes(4, "little")   # VirtualSize
    headers[section + 12:section + 16] = section_va.to_bytes(4, "little")    # VirtualAddress
    headers[section + 16:section + 20] = (len(rdata)).to_bytes(4, "little")  # SizeOfRawData
    headers[section + 20:section + 24] = raw_ptr.to_bytes(4, "little")       # PointerToRawData
    return bytes(headers) + bytes(rdata)


class PanelKeyLinkTests(unittest.TestCase):
    """面板按键链路体检：① EFMI 读键入口（2026-10-02 新判据）② 旧协议键位撞车（保留）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-keyconf-")
        self.root = Path(self.tmp.name)
        self.dlss5 = self.root / "runtime" / "dlss5"
        self.dlss5.mkdir(parents=True)
        self.efmi = self.root / "runtime" / "EFMI"
        self.staging = self.efmi / "Mods"
        self.staging.mkdir(parents=True)
        from endfieldmodcontroller.config import AppConfig

        self.config = AppConfig(
            runtime_dir=str(self.root / "runtime"),
            dlss5_dir=str(self.dlss5),
            staging_mods_dir=str(self.staging),
            hotkey_takeover=True,
        )
        self.ini = self.dlss5 / "ReShade.ini"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _check(self) -> dict:
        from endfieldmodcontroller import initialize

        report = initialize.Report()
        initialize._check_panel_hotkey_conflicts(self.config, report, None)
        return next(c for c in report.to_dict()["checks"] if c["key"] == "panel:hotkey_conflicts")

    def _write_efmi(self, import_name: str) -> None:
        (self.efmi / "d3d11.dll").write_bytes(_mini_pe64(import_name))

    def test_reports_when_efmi_is_not_installed(self) -> None:
        check = self._check()
        self.assertTrue(check["ok"])
        self.assertIn("还没装 EFMI", check["message"])

    def test_reports_broken_key_path(self) -> None:
        # EFMI 没有 `GetAsyncKeyState` 入口 = 面板所有按钮都会点了没反应
        self._write_efmi("SomethingElse")
        check = self._check()
        self.assertFalse(check["ok"])
        self.assertIn("没有 GetAsyncKeyState", check["message"])

    def test_ok_when_efmi_polls_getasynckeystate(self) -> None:
        self._write_efmi("GetAsyncKeyState")
        check = self._check()
        self.assertTrue(check["ok"], check["message"])
        self.assertIn("通路 OK", check["message"])

    def test_dlss5_and_firstperson_keys_do_not_conflict(self) -> None:
        # F6 = DLSS5 的 NR 开关、F7 = 第一人称切换 —— 旧协议正是撞在这两个键上
        self._write_efmi("GetAsyncKeyState")
        self.ini.write_text(
            "[INPUT]\nKeyOverlay=36,0,0,0\nKeyScreenshot=44,0,0,0\n"
            "[RenoDX.DLSS5]\nNRToggleKey=117\n",
            encoding="utf-8",
        )
        self.assertTrue(self._check()["ok"], self._check())

    def test_conflict_on_f13_plus_is_reported(self) -> None:
        self._write_efmi("GetAsyncKeyState")
        self.ini.write_text("[OTHER.ADDON]\nOtherToggleKey=124\nSomeShortcut=135\n", encoding="utf-8")
        check = self._check()
        self.assertFalse(check["ok"])
        self.assertIn("F13", check["message"])
        self.assertIn("F13", check["message"])   # 冲突检测针对面板协议键（未变）

    def test_legacy_staging_keys_are_flagged(self) -> None:
        self._write_efmi("GetAsyncKeyState")
        self.ini.write_text("[INPUT]\nKeyOverlay=36,0,0,0\n", encoding="utf-8")
        controller = self.staging / "MC_Controller"
        controller.mkdir(parents=True)
        (controller / "controller.ini").write_text("key = ctrl alt shift VK_F1\n", encoding="utf-8")
        check = self._check()
        self.assertTrue(check["ok"])              # 不是故障，是"下次启动会重写"
        self.assertIn("旧版", check["message"])

        (controller / "controller.ini").write_text("key = ctrl alt shift VK_F13\n", encoding="utf-8")
        self.assertNotIn("旧版", self._check()["message"])


class PeImportScanTests(unittest.TestCase):
    """`initialize._pe_imports_name_bytes()` —— 上面那条新判据的底层能力。"""

    def test_finds_function_in_import_table(self) -> None:
        from endfieldmodcontroller import initialize

        blob = _mini_pe64("GetAsyncKeyState")
        self.assertTrue(initialize._pe_imports_name_bytes(blob, "GetAsyncKeyState"))

    def test_reports_false_when_absent(self) -> None:
        from endfieldmodcontroller import initialize

        blob = _mini_pe64("GetAsyncKeyState")
        self.assertFalse(initialize._pe_imports_name_bytes(blob, "NopeNotHere"))

    def test_reports_none_for_non_pe(self) -> None:
        from endfieldmodcontroller import initialize

        self.assertIsNone(initialize._pe_imports_name_bytes(b"not a pe at all", "GetAsyncKeyState"))

    def test_real_efmi_dll_if_present(self) -> None:
        """本机真装着 EFMI 时顺手核一遍：**真 dll 里确实有这个入口**（判据的现实依据）。"""
        from endfieldmodcontroller import initialize

        candidate = Path(core.__file__).parents[1] / "runtime" / "builtin" / "XXMI" / "EFMI" / "d3d11.dll"
        if not candidate.is_file():
            self.skipTest("本机没有内置 EFMI 的 d3d11.dll")
        self.assertTrue(initialize._pe_imports_name(candidate, "GetAsyncKeyState"))


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

class ControllerIniSyntaxTests(unittest.TestCase):
    """生成的 `controller.ini` 必须是 **3DMigoto 认的条件语法**，而且 **if/endif 配平**。

    2026-10-01 现场铁证（两个坑，都会让"面板点了游戏没反应"）：
    ① **`elif` 不是 3DMigoto 的关键字**（只有 `if`/`else if`/`else`/`endif`）—— 那一行被丢弃后，
       **它下面的赋值语句会变成"无条件执行"**：面板点「外套」发 value=0、`$mc_state_N` 也正确
       记成 0，**但写进 Mod 变量的却是 1** → 点哪一档都没反应。
    ② 改成"每个档位一个独立 `if`"时，**每个 `if` 都必须有自己的 `endif`**（漏了会让整个
       `[Present]` 块结构错乱）。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-syntax-")
        self.root = Path(self.tmp.name)
        self.mod_dir = self.root / "DemoMod"
        self.mod_dir.mkdir(parents=True)
        (self.mod_dir / "mod.ini").write_text(MOD_INI, encoding="utf-8")
        self.controller = self.root / "MC_Controller"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _generate(self) -> str:
        from endfieldmodcontroller import core as mc_core

        staged = mc_core._make_mod_info(self.mod_dir, self.mod_dir, "演示", "character", {}, self.mod_dir.parent)
        mc_core.generate_controller_mod([staged], self.controller)
        return (self.controller / "controller.ini").read_text(encoding="utf-8")

    def test_no_elif(self) -> None:
        text = self._generate()
        self.assertNotIn("elif", text, "`elif` 不是 3DMigoto 的条件关键字 —— 会让它下面的赋值变成无条件执行")

    def test_if_endif_balanced(self) -> None:
        import re as _re

        text = self._generate()
        ifs = len(_re.findall(r"(?m)^\s*if\s", text))
        endifs = len(_re.findall(r"(?m)^\s*endif", text))
        self.assertEqual(ifs, endifs, f"if 与 endif 必须配平（if={ifs}, endif={endifs}）")
        self.assertGreater(ifs, 0)

    def test_each_value_gets_its_own_if_block(self) -> None:
        """「切到下一档」的分支写在**注入到 Mod ini 的那段**里，链式写法只用 `else if`。

        面板协议第三版：controller.ini 只负责 `run =` 呼叫，真正改变量的语句跑在 Mod 自己的
        命名空间里（带路径的跨命名空间赋值会被 3DMigoto 静默丢弃）。
        """
        self._generate()
        injected = (self.mod_dir / "mod.ini").read_text(encoding="utf-8")
        self.assertIn("[CommandListMC_Panel1]", injected)
        self.assertRegex(injected, r"(?m)^\s*if \$coat == 0\s*$")
        self.assertRegex(injected, r"(?m)^\s*else if \$coat == 1\s*$")
        self.assertRegex(injected, r"(?m)^\s*else\s*$")
        self.assertRegex(injected, r"(?m)^\s*endif\s*$")
        self.assertNotIn("elif", injected)

    def test_commit_reads_the_action_number_and_cycles(self) -> None:
        """提交段：读动作号 → `run =` 呼叫注入在 Mod ini 里的那段（本文件不改 Mod 变量）。"""
        text = self._generate()
        self.assertIn("$mc_last_wire = $mc_input", text)
        self.assertIn("if $mc_last_wire == 1", text)
        self.assertIn("run = CommandList\\mods\\demo.ini\\MC_Panel1", text)
        # 本文件里**不许**再出现跨命名空间的变量赋值（那条路已被实测证否）
        self.assertNotRegex(text, r"\$\\mods\\demo\.ini\\coat\s*=")

    def test_injected_lists_are_idempotent(self) -> None:
        """同一份 ini 被注入两次不该累积出两段（否则段名/变量会重复）。"""
        self._generate()
        self._generate()
        injected = (self.mod_dir / "mod.ini").read_text(encoding="utf-8")
        self.assertEqual(injected.count("[CommandListMC_Panel1]"), 1)
        self.assertEqual(injected.count("面板遥控（自动生成"), 1)

    def test_mod_variable_refs_keep_their_case(self) -> None:
        """本文件里**不许**再出现跨命名空间的变量赋值（实测会被静默丢弃）。

        改 Mod 变量这件事交给**注入在 Mod 自己 ini 里**的命令列表（用 Mod 声明时的原样
        大小写）；这里只用 `run =` 呼叫它。`d3dx_user.ini` 里的小写是**持久化层**的写法，
        不是 ini 的书写要求（2026-10-02 更正过一次误判）。
        """
        text = self._generate()
        # 只允许 `run = CommandList\<ns>\<name>` 这种跨命名空间**调用**
        self.assertIn("run = CommandList\\mods\\demo.ini\\MC_Panel1", text)
        # 变量赋值行里不许带命名空间路径（那种写法会被丢弃）
        self.assertNotRegex(text, r"(?m)^\s*\$\\[^\s=]+ *=")


class NextStepTests(unittest.TestCase):
    """`core.next_step_lines()` —— 「切到下一档」语句的生成器。"""

    def test_two_state_toggle(self) -> None:
        lines = core.next_step_lines("$\\Demo\\cape", ["0", "1"], indent="  ")
        text = "\n".join(lines)
        self.assertIn("  if $\\Demo\\cape == 0", text)
        self.assertIn("      $\\Demo\\cape = 1", text)
        self.assertIn("  else if $\\Demo\\cape == 1", text)
        self.assertIn("  else", text)
        self.assertTrue(lines[-1].strip() == "endif")
        self.assertNotIn("elif", text, "3DMigoto 不认 `elif`")

    def test_multi_state_wraps_around(self) -> None:
        text = "\n".join(core.next_step_lines("$x", ["0", "1", "2"]))
        # 最后一档要回到第一个值（面板只发"下一个"，不发具体档位）
        self.assertIn("if $x == 2\n    $x = 0", text)

    def test_single_value_is_a_reset(self) -> None:
        self.assertEqual(core.next_step_lines("$x", ["0"]), ["$x = 0"])

    def test_empty_values_generate_nothing(self) -> None:
        self.assertEqual(core.next_step_lines("$x", []), [])
