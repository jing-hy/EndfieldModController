from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import core


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-core-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.staging = self.root / "staging"
        self._write("陈/夏日/mod.ini", """
namespace = ChenSummer
[Constants]
global persist $cape = 0
global persist $bag = 1
[KeyCape]
key = no_modifiers VK_9
type = cycle
$cape = 0,1
[KeyBag]
key = no_modifiers VK_8
run = CommandListToggleBag
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

    def test_scan_and_actions(self) -> None:
        mods = core.scan_library(self.library, self.staging)
        by_name = {m.name: m for m in mods}
        self.assertEqual(len(mods), 3)
        self.assertEqual(by_name["RabbitFX"].kind, "dependency")
        self.assertGreaterEqual(len(by_name["夏日"].actions), 2)
        kinds = {a.kind for a in by_name["夏日"].actions}
        self.assertIn("cycle", kinds)
        self.assertIn("command", kinds)

    def test_full_command_list_namespace(self) -> None:
        mods = core.scan_library(self.library, self.staging)
        summer = next(m for m in mods if m.name == "夏日")
        command = next(a for a in summer.actions if a.kind == "command")
        self.assertEqual(command.run_command_full, "CommandList\\ChenSummer\\ToggleBag")

    def test_patch_and_restore(self) -> None:
        mods = core.scan_library(self.library, self.staging)
        summer = next(m for m in mods if m.name == "夏日")
        original = (summer.path / "mod.ini").read_text(encoding="utf-8")
        records = core.patch_mod_hotkeys(summer.path, self.root / "backups", summer.id)
        patched = (summer.path / "mod.ini").read_text(encoding="utf-8")
        self.assertIn("key = no_modifiers vk_f23", patched.lower())
        self.assertIn("[key", patched.lower())
        core.restore_mod_hotkeys(summer.path, records)
        self.assertEqual((summer.path / "mod.ini").read_text(encoding="utf-8"), original)

    def test_user_ini_action_queue(self) -> None:
        user_ini = self.root / "EFMI" / "d3dx_user.ini"
        core.write_action_queue(user_ini, "123", "1")
        self.assertEqual(core.read_user_var(user_ini, "mc_controller", "controller_action"), "123")
        core.write_action_queue(user_ini, "456", "0")
        self.assertEqual(core.read_user_var(user_ini, "mc_controller", "controller_action"), "456")
        text = user_ini.read_text(encoding="utf-8")
        self.assertEqual(text.count("$\\mc_controller\\controller_action"), 1)

    def test_path_guard(self) -> None:
        game_dir = self.root / "game"
        game_dir.mkdir()
        guard = core.PathGuard()
        guard.add_allowed(self.root)
        guard.add_forbidden(game_dir)
        guard.assert_writable(self.root / "safe.txt")
        with self.assertRaises(core.PathGuardError):
            guard.assert_writable(game_dir / "d3dx.ini")

    def test_dependency_detection_from_ini_text(self) -> None:
        mods = core.scan_library(self.library, self.staging)
        summer = next(m for m in mods if m.name == "夏日")
        # ⚠️ 2026-10-02 改：引用必须写在**正文**里 —— 只写在**注释**里不算引用。
        # 旗袍那句「Draw-local isolation from optional RabbitFX bindings」就是在声明
        # "不依赖"，早期判据扫全文把它当成引用 ⇒ 误激活 RabbitFX ⇒ 游戏崩在着色器编译器
        # （用户移走 RabbitFX 后「现在可以进入了，确认生效」）。所以这条测试现在**同时**
        # 钉住两件事：注释不算、正文算。
        (summer.path / "README.ini").write_text(
            "; note: this mod deliberately does NOT use RabbitFX\n"
            "Resource\\RabbitFX\\FXMap = ref Resource-mask\n",
            encoding="utf-8",
        )
        names = core.collect_required_dependency_names([])
        self.assertEqual(names, [])
        mods = core.scan_library(self.library, self.staging)
        names = core.collect_required_dependency_names(mods)
        self.assertIn("RabbitFX", names)

    def test_flat_layout_and_cover(self) -> None:
        flat = self.root / "flat-library"
        mod = flat / "18+陈千语多服装切换"
        mod.mkdir(parents=True)
        (mod / "mod.ini").write_text("[Constants]\nglobal persist $x = 0\n", encoding="utf-8")
        (mod / "preview.png").write_bytes(b"\x89PNG\r\n")
        mods = core.scan_library(flat, self.staging)
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0].group, "陈千语")
        self.assertIsNotNone(mods[0].cover_path)
        self.assertEqual(mods[0].cover_path.name, "preview.png")

    def test_launch_helpers(self) -> None:
        cmd = core.build_xxmi_launch_command(Path("XXMI Launcher.exe"), Path("Endfield.exe"))
        self.assertEqual(cmd, ["XXMI Launcher.exe", "--nogui", "--xxmi", "EFMI", "Endfield.exe"])
        env = core.build_reshade_launch_env(self.root / "runtime")
        self.assertTrue(env["RESHADE_BASE_PATH_OVERRIDE"].endswith("reshade"))


if __name__ == "__main__":
    unittest.main()
