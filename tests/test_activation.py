from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import activation, core


class ActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-act-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "EFMI" / "Mods"
        self._write("陈/夏日/mod.ini", """
namespace = ChenSummer
[Constants]
global persist $cape = 0
[KeyCape]
key = no_modifiers VK_9
type = cycle
$cape = 0,1
""")
        self._write("陈/万圣/mod.ini", """
namespace = ChenHalloween
[Constants]
global persist $hat = 0
[KeyHat]
key = no_modifiers VK_7
type = cycle
$hat = 0,1
""")
        self._write("_deps/RabbitFX/mod.ini", """
[Constants]
global persist $enabled = 1
""")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> Path:
        path = self.library / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_conflict_resolution(self) -> None:
        mods = core.scan_library(self.library, self.staging)
        chars = [m for m in mods if m.kind == "character"]
        active, report = activation.resolve_active_set(mods, [m.id for m in chars])
        self.assertEqual(len([m for m in active if m.kind == "character"]), 1)
        self.assertEqual(len(report.dropped), 1)

    def test_dependency_activated_only_when_required(self) -> None:
        """依赖按需激活：没有被 requires 引用到的依赖不进 active 集合。

        2026-09-27 修正 —— 原先 `resolve_active_set` 无条件取 `_deps` 下全部依赖，
        与用户选了什么无关。于是只选一个不需要依赖的 Mod，也会被动背上会改写游戏
        shader 的库（RabbitFX 的 [ShaderRegex*] 段），游戏直接闪退；而手动把 Mod
        放进 Mods 目录时这些依赖并不存在，所以不崩 —— 用户正是这么发现的。
        """
        mods = core.scan_library(self.library, self.staging)
        chars = [m for m in mods if m.kind == "character"]
        active, report = activation.resolve_active_set(mods, [m.id for m in chars])
        self.assertFalse(any(m.kind == "dependency" for m in active))
        self.assertEqual(report.dependencies, [])

    def test_dependency_activated_when_required(self) -> None:
        """被 requires 真正引用到的依赖仍必须激活（含传递依赖）。"""
        mods = core.scan_library(self.library, self.staging)
        char = next(m for m in mods if m.kind == "character")
        dep = next(m for m in mods if m.kind == "dependency")
        char.requires = [dep.name]
        active, report = activation.resolve_active_set(mods, [char.id])
        self.assertIn(dep.id, [m.id for m in active])
        self.assertEqual(report.dependencies, [dep.id])

    def test_stage_does_not_touch_library(self) -> None:
        self.staging.mkdir(parents=True, exist_ok=True)
        keep = self.staging / "keep_me.txt"
        keep.write_text("unmanaged", encoding="utf-8")
        mods = core.scan_library(self.library, self.staging)
        summer = next(m for m in mods if m.name == "夏日")
        original = (summer.path / "mod.ini").read_bytes()
        result = activation.stage_and_prepare(self.library, self.staging, self.runtime, selected_ids=[summer.id])
        self.assertTrue(keep.is_file())
        self.assertGreaterEqual(len(result["actions_manifest"]["actions"]), 1)
        self.assertEqual((summer.path / "mod.ini").read_bytes(), original)
        staged_text = "\n".join(p.read_text(encoding="utf-8") for p in self.staging.rglob("mod.ini"))
        self.assertIn("[key", staged_text.lower())
        self.assertTrue((Path(result["reshade_dir"]) / "actions.tsv").is_file())
        self.assertTrue((Path(result["reshade_dir"]) / "user_ini_path.txt").is_file())

    def test_stage_keeps_original_hotkeys_by_default(self) -> None:
        """**默认不再改写 Mod 热键**（2026-10-01 用户拍板：「那个控制面板还没做好，
        在此之前先恢复快捷键」）。

        以前 staging 会把每个 Mod 的 `[Key*]` 一律改成 `no_modifiers VK_F24` —— 本意是
        把操作权交给控制器面板，但那个面板（自研 ReShade addon）既没随包、也没装进
        ReShade 真正读取的目录，于是"键被改死了、面板却不存在"，Mod 自带的快捷键与
        `CTRL 0`／`ALT 1` 那类控制菜单全都用不了。
        """
        self.staging.mkdir(parents=True, exist_ok=True)
        mods = core.scan_library(self.library, self.staging)
        summer = next(m for m in mods if m.name == "夏日")
        result = activation.stage_and_prepare(self.library, self.staging, self.runtime, selected_ids=[summer.id])

        self.assertEqual(result["patch_count"], 0)
        staged = [p for p in self.staging.rglob("mod.ini")]
        self.assertTrue(staged)
        for path in staged:
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("vk_f24", text, f"{path} 的热键不该被改写")
            self.assertIn("no_modifiers vk_9", text)      # 测试 Mod 自带的键保持原样

    def test_hotkey_takeover_still_available_when_asked(self) -> None:
        """显式打开接管时，行为与以前一致（等控制面板做好后要用这条路）。"""
        self.staging.mkdir(parents=True, exist_ok=True)
        mods = core.scan_library(self.library, self.staging)
        summer = next(m for m in mods if m.name == "夏日")
        result = activation.stage_and_prepare(
            self.library, self.staging, self.runtime,
            selected_ids=[summer.id], hotkey_takeover=True,
        )
        self.assertGreaterEqual(result["patch_count"], 1)
        staged_text = "\n".join(p.read_text(encoding="utf-8") for p in self.staging.rglob("mod.ini"))
        self.assertIn("key = no_modifiers vk_f24", staged_text.lower())
        self.assertEqual((summer.path / "mod.ini").read_bytes().decode("utf-8").lower().count("vk_f24"), 0)

    def test_allow_same_character_keeps_all(self) -> None:
        """**强行关闭角色 Mod 互斥**后，同角色的 Mod 全部保留（用户 2026-10-01 要求：
        「mod 库上面加一个拨钮，强行关闭角色 mod 互斥…便于部分同角色但不冲突的 mod」）。"""
        mods = core.scan_library(self.library, self.staging)
        chars = [m for m in mods if m.kind == "character"]
        self.assertEqual(len(chars), 2)          # 陈/夏日 + 陈/万圣（同角色）

        # 默认：互斥生效，只留一个
        active_default, report_default = activation.resolve_active_set(mods, [m.id for m in chars])
        self.assertEqual(len([m for m in active_default if m.kind == "character"]), 1)
        self.assertEqual(len(report_default.dropped), 1)

        # 关闭互斥：两个都留下，且不报 dropped
        active, report = activation.resolve_active_set(
            mods, [m.id for m in chars], allow_same_character=True
        )
        self.assertEqual(len([m for m in active if m.kind == "character"]), 2)
        self.assertEqual(report.dropped, [])

    def test_stage_and_prepare_respects_same_character_switch(self) -> None:
        """开关要一路传到 staging：打开后 Mods 目录里真的会出现两个同角色 MC_ 产物。"""
        self.staging.mkdir(parents=True, exist_ok=True)
        mods = core.scan_library(self.library, self.staging)
        ids = [m.id for m in mods if m.kind == "character"]

        activation.stage_and_prepare(self.library, self.staging, self.runtime, selected_ids=ids)
        self.assertEqual(len([d for d in self.staging.glob("MC_*") if d.is_dir() and d.name != "MC_Controller"]), 1)

        activation.stage_and_prepare(
            self.library, self.staging, self.runtime,
            selected_ids=ids, allow_same_character=True,
        )
        self.assertEqual(len([d for d in self.staging.glob("MC_*") if d.is_dir() and d.name != "MC_Controller"]), 2)

    def test_user_ini_follows_builtin_staging_layout(self) -> None:
        """Regression: user_ini_path must track the staging root, not runtime_dir.

        With the built-in runtime the staging root is
        <runtime>/builtin/XXMI/EFMI/Mods, so a runtime_dir-based default wrote
        the action queue to <runtime>/EFMI/d3dx_user.ini and the ReShade add-on
        silently lost every click.  This failed before the fix.
        """
        builtin_staging = self.runtime / "builtin" / "XXMI" / "EFMI" / "Mods"
        builtin_staging.mkdir(parents=True, exist_ok=True)
        mods = core.scan_library(self.library, builtin_staging)
        summer = next(m for m in mods if m.name == "夏日")
        result = activation.stage_and_prepare(
            self.library, builtin_staging, self.runtime, selected_ids=[summer.id]
        )
        user_ini = Path(result["user_ini_path"]).resolve()
        self.assertEqual(user_ini.parent, builtin_staging.parent.resolve())
        self.assertEqual(user_ini.name, "d3dx_user.ini")
        advertised = (Path(result["reshade_dir"]) / "user_ini_path.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(Path(advertised).resolve(), user_ini)


if __name__ == "__main__":
    unittest.main()
