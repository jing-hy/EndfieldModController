"""`NRStyle=2` 的处理：**不搞一刀切**，只在"上次就是这套 Mod 组合崩的"时才改。

用户 2026-10-02 原话：「nr风格2是不是电影啊，那个**我还要用，不要一刀切**，可以绑定进
mod，如果这种崩溃发生就记一下，**记过的 mod 被勾选时才改**」。

补充事实：`NRStyle=2` 是**预发布字段 `DLSSNR.Style` 选「神经渲染模型 C」**（0/1/2 =
模型 A/B/C，见 addon 自带汉化 `translations.txt`），**不是"电影风格"**；RenoDX 作者把它
标为"启动就崩（present 路径空指针）"。

所以规则是：
* 没有命中崩溃记忆 → **保留用户的 2**，一个字节都不动；
* 崩溃记忆里有"当时 NRStyle=2"、且**现在勾选的是同一套 Mod**（互为子集、两边都 ≥2 个）
  → 才备份后改回 0。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import crashwatch, initialize
from endfieldmodcontroller.config import AppConfig


class NrStyleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-nrstyle-")
        self.root = Path(self.tmp.name)
        staging = self.root / "runtime" / "EFMI" / "Mods"
        staging.mkdir(parents=True)
        self.staging = staging
        self.config = AppConfig(
            runtime_dir=str(self.root / "runtime"),
            dlss5_dir=str(self.root / "runtime" / "dlss5"),
            staging_mods_dir=str(staging),
        )
        # ⚠ 必须给 config 一个落盘路径：没加载过配置文件时 `base_dir` 会退回**项目根**，
        # 于是 dlss5_ini_path / crash_memory 都会指向工作区真实文件（2026-10-02 踩过）。
        self.config.save(self.root / "config.json")
        self.ini = self.config.dlss5_ini_path
        self.ini.parent.mkdir(parents=True, exist_ok=True)
        self.backup = self.ini.with_name(self.ini.name + ".bak-before-nrstyle")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- helpers -----------------------------------------------------
    def _write_ini(self, nrstyle: str | None = "2") -> None:
        body = "[GENERAL]\nA=1\n\n[RenoDX.DLSS5]\nNeuralUplift=1\n"
        if nrstyle is not None:
            body += f"NRStyle={nrstyle}\n"
        body += "NRIntensity=2\n\n[STYLE]\nB=2\n"
        self.ini.write_text(body, encoding="utf-8")

    def _stage(self, *names: str) -> None:
        for name in names:
            (self.staging / name).mkdir(parents=True, exist_ok=True)

    def _remember(self, mods: list[str], nrstyle: str = "2") -> None:
        path = crashwatch.crash_memory_path(self.config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"entries": [{"kind": "crash", "mods": mods, "nrstyle": nrstyle}]},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def _run(self) -> dict:
        report = initialize.Report()
        initialize._check_dlss5_nrstyle(self.config, report, None)
        return report.to_dict()

    def _check(self, payload: dict) -> dict:
        return next(c for c in payload["checks"] if c["key"] == "dlss5:nrstyle")

    # -- 测试 --------------------------------------------------------
    def test_nrstyle_2_is_KEPT_when_no_crash_memory(self) -> None:
        """没有崩溃记忆 → 保留用户的设置（这就是"不要一刀切"）。"""
        self._write_ini("2")
        self._stage("MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍")
        before = self.ini.read_text(encoding="utf-8")
        payload = self._run()
        self.assertEqual(self.ini.read_text(encoding="utf-8"), before, "不该动用户的 NRStyle")
        self.assertFalse(self.backup.exists())
        check = self._check(payload)
        self.assertTrue(check["ok"])
        self.assertFalse(check["fixed"])
        self.assertIn("保留不动", check["message"])

    def test_nrstyle_2_is_KEPT_even_when_the_same_combo_crashed_before(self) -> None:
        """**任何情况下都不改文件** —— 那套"命中崩溃记忆就改回 0"的自动修复已删除。

        用户 2026-10-02：「**先把之前那个 nr 风格的死代码删掉**」（它先前已被降级为死代码，
        现在整段移除）。依据：实测把 NRStyle 改成 0 之后**照样崩在同一处**；当天更晚定案的
        真正崩因是 **RabbitFX 进了 staging**，与 NRStyle 无关。
        """
        self._write_ini("2")
        self._stage("MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍")
        self._remember(["MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍"], nrstyle="2")
        before = self.ini.read_text(encoding="utf-8")
        payload = self._run()
        self.assertEqual(self.ini.read_text(encoding="utf-8"), before, "自检不该动用户的 NRStyle")
        self.assertFalse(self.backup.exists())
        check = self._check(payload)
        self.assertTrue(check["ok"])
        self.assertFalse(check["fixed"])
        self.assertIn("保留不动", check["message"])

    def test_nrstyle_2_kept_when_the_combo_differs(self) -> None:
        """崩过的是**另一套**组合 → 依旧保留（用户可能只是想在别的组合下用模型 C）。"""
        self._write_ini("2")
        self._stage("MC_别的角色_别的皮肤", "MC_另一个_皮肤")
        self._remember(["MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍"], nrstyle="2")
        before = self.ini.read_text(encoding="utf-8")
        payload = self._run()
        self.assertEqual(self.ini.read_text(encoding="utf-8"), before)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self._check(payload)["fixed"])

    def test_memory_without_nrstyle_2_does_not_trigger(self) -> None:
        """记忆里那次崩溃时 NRStyle 不是 2 → 与它无关，不动。"""
        self._write_ini("2")
        self._stage("MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍")
        self._remember(["MC_佩丽卡_佩丽卡-OL装", "MC_庄方宜_旗袍"], nrstyle="0")
        before = self.ini.read_text(encoding="utf-8")
        self._run()
        self.assertEqual(self.ini.read_text(encoding="utf-8"), before)

    def test_single_mod_combo_does_not_trigger(self) -> None:
        """只有 1 个 Mod 的组合不参与（一个 Mod 自己崩通常是别的原因）。"""
        self._write_ini("2")
        self._stage("MC_佩丽卡_佩丽卡-OL装")
        self._remember(["MC_佩丽卡_佩丽卡-OL装"], nrstyle="2")
        before = self.ini.read_text(encoding="utf-8")
        self._run()
        self.assertEqual(self.ini.read_text(encoding="utf-8"), before)

    def test_nrstyle_zero_or_absent_is_left_alone(self) -> None:
        self._write_ini("0")
        payload = self._run()
        self.assertTrue(self._check(payload)["ok"])
        self.assertFalse(self.backup.exists())
        self._write_ini(None)
        payload = self._run()
        self.assertTrue(self._check(payload)["ok"])

    def test_nrstyle_outside_the_section_is_ignored(self) -> None:
        self.ini.write_text("[SOMETHING]\nNRStyle=2\n", encoding="utf-8")
        payload = self._run()
        self.assertIn("NRStyle=2", self.ini.read_text(encoding="utf-8"))
        self.assertTrue(self._check(payload)["ok"])

    def test_remember_crash_records_the_current_nrstyle(self) -> None:
        """崩溃记忆里必须带上当时的 NRStyle —— 这是"记一下"的落点。"""
        self._write_ini("2")
        entry = crashwatch.remember_crash(self.config, kind="crash", mods=["a", "b"])
        self.assertEqual(entry["nrstyle"], "2")
        stored = crashwatch.read_crash_memory(self.config)
        self.assertEqual(stored[0]["nrstyle"], "2")


if __name__ == "__main__":
    unittest.main()
