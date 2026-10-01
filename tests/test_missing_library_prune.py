"""用户手动删掉 Mod 库里的文件之后，启动前不该再误报"崩溃风险"。

用户 2026-10-01 反馈：「如果手动删 mod 库中文件，会导致 mod 库选中 0 个，但是启动提示
崩溃风险」。根因两条：
① `selected_mods` 是上次的勾选快照，库文件被删后里面的 id 再也对不上 → 界面显示
   "选中 0 个"，但 staging 里还留着上一轮生成的 `MC_*`；
② `runtime\\_state\\mod_conflicts.json` 是**上次自检**的结论，没人作废它 —— 启动前的
   风险检查照样把它当"当前风险"。
修法：启动前先按"库里真实存在的 Mod"收敛勾选（只改勾选与控制器自己的 staging，绝不动
Mod 库），风险检查也改成"以这次真的会被加载的那批 Mod 为准"。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig, PROJECT_ROOT

MOD_TEMPLATE = """
namespace = {namespace}
[Constants]
global persist $cape = 0
[KeyCape]
key = no_modifiers vk_9
type = cycle
$cape = 0,1
"""


class MissingLibraryFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-prune-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "builtin" / "XXMI" / "EFMI" / "Mods"
        self.staging.mkdir(parents=True)
        self.config_path = self.root / "config.json"
        self.config = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            dependency_manifest=str(PROJECT_ROOT / "dependencies.json"),
        )
        self.config.save(self.config_path)

        # 库里的两个 Mod（用同一个角色名以避免被"同角色互斥"影响：显式打开放行）
        for name, namespace in (("Alice", "DemoAlice"), ("Bob", "DemoBob")):
            path = self.library / "佩丽卡" / name
            path.mkdir(parents=True)
            (path / "mod.ini").write_text(MOD_TEMPLATE.format(namespace=namespace), encoding="utf-8")
        self.config.allow_same_character_mods = True
        self.config.save(self.config_path)

        self.api = EndfieldModControllerApi(self.config_path)
        mods = self.api.scan()["mods"]
        self.ids = sorted(mod["id"] for mod in mods)
        self.api.config.selected_mods = list(self.ids)
        self.api.config.save()

        # 造出"上一轮"的产物：staging 里两个 MC_* + 一份冲突结论
        for name in ("MC_佩丽卡_Alice", "MC_佩丽卡_Bob"):
            (self.staging / name).mkdir()
        state_path = self.runtime / "_state" / "mod_conflicts.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "at": 1,
            "at_text": "2026-10-01 12:00:00",
            "ok": False,
            "detail": "两个 Mod 覆盖同一批资源",
            "conflicts": ["佩丽卡：Alice 与 Bob 覆盖同一批游戏资源"],
            "groups": [{"text": "佩丽卡：Alice 与 Bob", "names": ["MC_佩丽卡_Alice", "MC_佩丽卡_Bob"]}],
            "mods": ["MC_佩丽卡_Alice", "MC_佩丽卡_Bob"],
        }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _remove_library_mod(self, name: str) -> None:
        target = self.library / "佩丽卡" / name
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()

    def test_all_removed_no_more_risk(self) -> None:
        self._remove_library_mod("Alice")
        self._remove_library_mod("Bob")
        risks = self.api.prelaunch_risks()
        self.assertFalse(risks["blocking"], risks)
        self.assertEqual(risks["conflicts"], [])
        self.assertEqual(risks["mods"], [])
        self.assertNotIn("mod_conflicts", risks["note"] if "note" in risks else "")
        # 勾选也收敛成空，staging 里的旧产物被清掉；Mod 库目录本身还在（只是空的）
        self.assertEqual(self.api.config.selected_mods, [])
        leftovers = [p.name for p in self.staging.iterdir() if p.name.startswith("MC_") and p.name != "MC_Controller"]
        self.assertEqual(leftovers, [])
        self.assertTrue((self.library / "佩丽卡").is_dir())

    def test_partial_removal_keeps_only_existing(self) -> None:
        self._remove_library_mod("Bob")
        risks = self.api.prelaunch_risks()
        remaining = [mod["name"] for mod in self.api.scan()["mods"]]
        self.assertEqual(remaining, ["Alice"])
        self.assertEqual(len(self.api.config.selected_mods), 1)
        # 库里没有的那个 Mod 的 staging 产物也必须消失（否则游戏里照样加载它对撞）
        leftovers = sorted(
            p.name for p in self.staging.iterdir()
            if p.name.startswith("MC_") and p.name not in {"MC_Controller", "MC_Probe.ini"}
        )
        self.assertEqual(len(leftovers), 1, leftovers)
        self.assertIn("Alice", leftovers[0])
        self.assertFalse(risks["blocking"], risks)

    def test_stale_conflict_state_is_ignored(self) -> None:
        """结论是上一次对着别的 Mod 算的 → 不算当前风险。"""
        state_path = self.runtime / "_state" / "mod_conflicts.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["mods"] = ["MC_佩丽卡_Alice", "MC_佩丽卡_SomeOtherMod"]
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        risks = self.api.prelaunch_risks()
        self.assertFalse(risks["blocking"], risks)
        self.assertEqual(risks["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
