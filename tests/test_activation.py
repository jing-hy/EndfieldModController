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
        self.assertIn("key = no_modifiers vk_f24", staged_text.lower())
        self.assertIn("[key", staged_text.lower())
        self.assertTrue((Path(result["reshade_dir"]) / "actions.tsv").is_file())
        self.assertTrue((Path(result["reshade_dir"]) / "user_ini_path.txt").is_file())

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
