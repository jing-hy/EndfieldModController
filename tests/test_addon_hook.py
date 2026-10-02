"""面板按键注入链路的回归测试（离线）。

面板的按键注入最终作用在**游戏进程内的 EFMI** 上，但这条链路里属于我们自己的部分
—— 找目标模块 → 改它的导入表 → 伪造"按下" → 跨帧保持 → 到点自动释放 →
不影响别的调用者 —— 可以在离线环境里完整验证：`scripts/test_addon_hook.py` 造一个
"假 EFMI"（只通过导入表轮询 `GetAsyncKeyState`，与真 EFMI 读键的方式一致）让宿主加载它，
再逐条断言。

这里是它的 pytest 外壳；**编译器不在就 skip**（不能因为一台机器没装 MSVC 就把套件弄红）。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test_addon_hook.py"


class AddonHookTests(unittest.TestCase):
    def test_key_injection_link(self) -> None:
        if not SCRIPT.is_file():
            self.skipTest("自测脚本不存在")
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 2:
            self.skipTest(f"编译环境不可用（跳过）：{output[-300:]}")
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("0 项失败", output)


if __name__ == "__main__":
    unittest.main()
