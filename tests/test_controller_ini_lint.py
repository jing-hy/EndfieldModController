"""生成的 `controller.ini` 必须通过 3DMigoto 语义体检（零"静默失败行"）。

**为什么要有这条测试**（2026-10-01 真实事故，整轮排查的根因）：
我为了诊断往 `controller.ini` 里加探针，后来又削掉一部分 —— **删了变量的声明、却漏删了赋值行**。
按 3DMigoto 源码（`CommandListOperand::parse`），左值变量的解析顺序是
「浮点 → ini param → **变量**」，**查不到变量 ⇒ 整行被当成非法命令**；而这类非法行
**足够让整个 `[CommandList]` / `[Present]` 段落的解析出问题** ⇒
`Commit` 段不再执行（`mc_last_wire` 不更新）、`[Present]` 读到的 `$controller_action` 恒为 0、
所有绑在 `run = CommandListMC_*` 上的按键全部失效 —— **而 ini 表面看完全正常**。

`py_compile`、常规单测、人工 review 都抓不到这种"ini 语法对、但 3DMigoto 不认"的问题，
所以这里把它做成**生成即体检**的硬卡点。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import ini_lint

MOD_INI = """[Constants]
global persist $cape = 0

[TextureOverrideDemo]
hash = deadbeef

[KeySwap_0]
key = vk_right
type = cycle
$cape = 0,1,
"""


class ControllerIniLintTests(unittest.TestCase):
    def test_generated_ini_has_no_silently_dropped_lines(self) -> None:
        from endfieldmodcontroller import core as mc_core

        with tempfile.TemporaryDirectory(prefix="mc-ini-lint-") as tmp:
            root = Path(tmp)
            mod_dir = root / "DemoMod"
            mod_dir.mkdir(parents=True)
            (mod_dir / "mod.ini").write_text(MOD_INI, encoding="utf-8")
            controller = root / "MC_Controller"

            staged = mc_core._make_mod_info(mod_dir, mod_dir, "演示", "character", {}, root)
            mc_core.generate_controller_mod([staged], controller)

            ini = controller / "controller.ini"
            self.assertTrue(ini.is_file())
            found = ini_lint.lint_file(ini)
            self.assertEqual(
                found, [],
                "生成的 controller.ini 里有会被 3DMigoto 静默丢弃 / 破坏段落的行：\n  "
                + "\n  ".join(found),
            )

    def test_linter_actually_catches_the_regression(self) -> None:
        """反向验证：体检器必须能抓住"赋值给未声明变量"（否则它是摆设）。"""
        bad = """[Constants]
global persist $known = 0

[CommandListMC_Commit]
$undefined_var = $known
"""
        found = ini_lint.lint_text(bad)
        self.assertTrue(any("undefined_var" in item for item in found), found)

    def test_linter_allows_expressions_and_namespaced_targets(self) -> None:
        """不许误报：右值表达式、跨命名空间左值都是合法的（初版误报了 25 处）。"""
        ok = """[Constants]
global persist $mc_input = 0
global persist $mc_last_wire = 0

[CommandListMC_Digit0]
$mc_input = $mc_input * 10

[CommandListMC_Commit]
$mc_last_wire = $mc_input

[Present]
$\\mods\\SomeMod\\0.ini\\coat = 0
"""
        self.assertEqual(ini_lint.lint_text(ok), [])
