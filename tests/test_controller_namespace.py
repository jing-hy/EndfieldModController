"""`controller.ini` 的**命名空间大小写**与条件语法（2026-10-01 现场两连击）。

两条都是"面板点了但游戏里没反应"的真凶，且都属于**生成的 ini 与 3DMigoto 语义不一致**：

1. **命名空间必须整体小写**：3DMigoto 内部把变量名规范化成小写（它自己往 `d3dx_user.ini`
   落盘的就是 `$\\mods\\mc_佩丽卡_佩丽卡-ol装_linyoude\\0.ini\\coat`）。我们照磁盘目录名原样拼
   （`MC_佩丽卡_佩丽卡-OL装_linyoude`）→ 写进去的是**另一个变量**，Mod 一点不动。
2. **条件分支不能用 `elif`**（Python 语法，3DMigoto 只认 `if` / `else if` / `else` / `endif`）。
3. **探针必须在 `if` 块内**：3DMigoto 会丢弃 `[Present]` 段里 `if` 块之外的裸语句
   （第一版探针放块外，`d3dx_user.ini` 里永远是 `-999`）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

MOD_INI = """[Constants]
global persist $coat = 0

[KeyCoat]
key = vk_right
type = cycle
$coat = 0,1,
"""


class ControllerNamespaceCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-panel-case-")
        self.root = Path(self.tmp.name)
        self.mod_dir = self.root / "MC_PeiliKa_MOD"          # 故意用大写目录名
        self.mod_dir.mkdir(parents=True)
        (self.mod_dir / "0.ini").write_text(MOD_INI, encoding="utf-8")
        self.controller = self.root / "MC_Controller"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_namespace_is_lowercased(self) -> None:
        from endfieldmodcontroller import core as mc_core

        staged = mc_core._make_mod_info(self.mod_dir, self.mod_dir, "演示", "character", {}, self.mod_dir.parent)
        mc_core.generate_controller_mod([staged], self.controller)
        text = (self.controller / "controller.ini").read_text(encoding="utf-8")
        self.assertNotIn("MC_PeiliKa_MOD", text, "命名空间必须小写（3DMigoto 内部就是这样规范化的）")
        self.assertIn(self.mod_dir.name.lower(), text)

    def test_probe_sits_inside_the_if_block(self) -> None:
        from endfieldmodcontroller import core as mc_core

        staged = mc_core._make_mod_info(self.mod_dir, self.mod_dir, "演示", "character", {}, self.mod_dir.parent)
        mc_core.generate_controller_mod([staged], self.controller)
        lines = (self.controller / "controller.ini").read_text(encoding="utf-8").splitlines()
        probe_lines = [i for i, l in enumerate(lines) if "$mc_probe_v" in l and "=" in l and "global" not in l]
        self.assertTrue(probe_lines, "应当生成探针行")
        for i in probe_lines:
            # 往上找最近的 if / endif，探针必须比最近的 `if` 更靠内（即位于某个块里）
            depth = 0
            for j in range(i - 1, -1, -1):
                s = lines[j].strip().lower()
                if s.startswith("if "):
                    depth = 1
                    break
            self.assertEqual(depth, 1, f"探针必须在 if 块内（第 {i+1} 行）")


if __name__ == "__main__":
    unittest.main()
