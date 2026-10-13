# SPDX-License-Identifier: GPL-3.0-or-later
"""EndfieldJiggle（触摸形变 Mod）接入回归（2026-10-13）。

钉住四件事 —— 每一条都对应这套接入**踩过或差点踩到**的坑：

① **「关」必须把目录真的移出 `EFMI\\Mods`**：EFMI 的 `d3dx.ini` 是
   `include_recursive = Mods`（按递归扫 ini 加载），改名 / 挪进子目录**都挡不住加载**，
   所以"界面关了、游戏里还在"就是这么来的。
② **三份 staging 白名单必须认识它**（`activation.CONTROLLER_OWNED_NAMES` /
   `initialize.MOD_CONFLICT_IGNORE_NAMES` / `crashwatch._CONTROLLER_DIRS`）：少了任何一处，
   它要么被 `import_manual_mods` 当"用户手工放的 Mod"**收编进库再从 staging 搬走**
   （`api.prepare_launch` 点一次「生成控制器」就触发，**不受** `auto_adopt_manual_mods`
   开关保护），要么每次自检报一条"手动 Mod"红项。
③ **安装包解析不能按固定层级取**：上游纯 Mod 包是三段套法
   （`.../Mods/EndfieldJiggleEFMI/`），而拖放包 / 独立包的层级又不同。
④ **只挑纯 Mod 包**：同一个 Release 里还有 72 MB 拖放包与 149 MB 独立包。
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import activation, alerts, crashwatch, efmi_jiggle, initialize
from endfieldmodcontroller import api as api_mod

MOD_FILES = {
    "EndfieldJiggle.ini": "namespace = EndfieldJiggleEFMI\n",
    "Passes.ini": "namespace = EndfieldJiggleEFMI\n",
    "Outfits.ini": "namespace = EndfieldJiggleEFMI\n",
    "shaders/step_cs.hlsl": "// step\n",
    "shaders/input_controller.hlsl": "// input\n",
    "shaders/motion_model.hlsl": "// motion\n",
    "shaders/step_cs.cs_5_0.8000.bin": "bin",
}


def make_pack(path: Path, *, version: str = "0.2.2", layout: str = "", name: str = "") -> Path:
    """造一个**上游形状**的纯 Mod 包（默认用 v0.2.2 实测到的三段套法）。"""
    layout = layout or f"EndfieldJiggleEFMI-v{version}/Mods/EndfieldJiggleEFMI"
    path = path / (name or f"EndfieldJiggleEFMI-v{version}-win64.zip")
    with zipfile.ZipFile(path, "w") as bundle:
        for rel, text in MOD_FILES.items():
            bundle.writestr(f"{layout}/{rel}", text)
    return path


class JiggleEfmiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mc-jiggle-test-")
        root = Path(self._tmp.name)
        (root / "runtime").mkdir(parents=True, exist_ok=True)
        (root / "library").mkdir(parents=True, exist_ok=True)
        cfg = root / "config.json"
        cfg.write_text(json.dumps({"data_root": "", "runtime_dir": "runtime",
                                   "library_dir": "library"}, ensure_ascii=False),
                       encoding="utf-8")
        self.api = api_mod.EndfieldModControllerApi(str(cfg))
        self.config = self.api.config
        self.staging = Path(self.config.staging_mods_path)
        self.target = efmi_jiggle.mod_dir(self.config)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------------------------------------------------------------- 安装包
    def test_import_pack_finds_the_nested_mod_dir(self):
        """三段套法的 zip 也要能识别（`.../Mods/EndfieldJiggleEFMI/`）。"""
        archive = make_pack(Path(self._tmp.name))
        result = efmi_jiggle.import_pack(self.config, archive)
        self.assertTrue(result["ok"], result)
        self.assertTrue(efmi_jiggle.payload_ready(self.config))
        self.assertEqual(efmi_jiggle.installed_version(self.config), "0.2.2")
        self.assertTrue((efmi_jiggle.payload_dir(self.config) / "EndfieldJiggle.ini").is_file())
        # 上游原文也要留一份（离线重装 / 回滚要用）
        self.assertTrue(list((efmi_jiggle.component_root(self.config) / "_pack").glob("*.zip")))

    def test_import_pack_rejects_source_like_zip(self):
        """没有 `EndfieldJiggle.ini` 的包（例如 GitHub 自动生成的源码归档）要明确拒绝。"""
        archive = Path(self._tmp.name) / "source.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("repo-main/README.md", "no mod here\n")
        result = efmi_jiggle.import_pack(self.config, archive)
        self.assertFalse(result["ok"])
        self.assertIn("EndfieldJiggle.ini", result["message"])

    def test_pick_asset_only_takes_the_mod_pack(self):
        """同一 Release 里的 drop-in（72 MB）与 standalone（149 MB）都不许被选中。"""
        release = {"assets": [
            {"name": "EndfieldJiggleEFMI-v0.2.2-drop-in-win64.zip", "browser_download_url": "drop"},
            {"name": "EndfieldJiggleEFMI-v0.2.2-standalone-win64.zip", "browser_download_url": "stand"},
            {"name": "EndfieldJiggleEFMI-v0.2.1-win64.zip", "browser_download_url": "old"},
            {"name": "EndfieldJiggleEFMI-v0.2.2-win64.zip", "browser_download_url": "mod"},
            {"name": "SHA256SUMS-v0.2.2.txt", "browser_download_url": "sums"},
            {"name": "EndfieldJiggleEFMI-v0.2.2-source.zip", "browser_download_url": "src"},
        ]}
        picked = efmi_jiggle.pick_asset(release)
        self.assertIsNotNone(picked)
        version, asset = picked
        self.assertEqual(version, "0.2.2")
        self.assertEqual(asset["browser_download_url"], "mod")

    # ---------------------------------------------------------------- 开关 / 装卸
    def test_toggle_really_moves_the_dir_out_of_mods(self):
        """⭐ 核心：关闭 = 目录**真的离开** Mods（`include_recursive` 照加载，改名挡不住）。"""
        efmi_jiggle.import_pack(self.config, make_pack(Path(self._tmp.name)))

        on = efmi_jiggle.set_enabled(self.config, True)
        self.assertTrue(on["ok"] and on["changed"], on)
        self.assertTrue((self.target / "EndfieldJiggle.ini").is_file())
        self.assertTrue(efmi_jiggle.status(self.config)["enabled"])

        off = efmi_jiggle.set_enabled(self.config, False)
        self.assertTrue(off["ok"] and off["changed"], off)
        self.assertFalse(self.target.is_dir(),
                         "关闭后 Mods 里不许还留着它 —— EFMI 是 include_recursive，改名也会加载")
        self.assertFalse(list(self.staging.glob("EndfieldJiggleEFMI*")),
                         "连改名副本也不许留在 Mods 里（同样会被递归加载）")
        self.assertTrue(efmi_jiggle.park_dir(self.config).is_dir())
        self.assertFalse(efmi_jiggle.status(self.config)["enabled"])

        # 幂等 + 再打开能回来（停用副本是**移动**，不是复制）
        self.assertFalse(efmi_jiggle.set_enabled(self.config, False)["changed"])
        again = efmi_jiggle.set_enabled(self.config, True)
        self.assertTrue(again["ok"], again)
        self.assertTrue((self.target / "EndfieldJiggle.ini").is_file())
        self.assertFalse(efmi_jiggle.park_dir(self.config).is_dir())
        self.assertFalse((efmi_jiggle.component_root(self.config) / "_parked").exists())

    def test_install_reports_network_failure_without_deploying(self):
        """本地没载荷时会去上游取；取不到要给**可读原因**，并且不许把目录铺出来。"""
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                                 side_effect=RuntimeError("断网")):
            result = efmi_jiggle.install(self.config)
        self.assertFalse(result["ok"])
        self.assertIn("断网", result["message"])
        self.assertFalse(self.target.is_dir())

    def test_install_uses_local_payload_without_any_network(self):
        """⭐ 本地已在位 ⇒ **一个网络请求都不发**（CONTRIBUTING：别在流程里偷偷联网）。"""
        efmi_jiggle.import_pack(self.config, make_pack(Path(self._tmp.name)))
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                                 side_effect=AssertionError("本地已就位时不该联网")):
            result = efmi_jiggle.install(self.config)
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.target / "EndfieldJiggle.ini").is_file())

    def test_deploy_reports_when_payload_missing(self):
        result = efmi_jiggle.deploy(self.config)
        self.assertFalse(result["ok"])
        self.assertFalse(result["actions"])

    # ---------------------------------------------------------------- 三份白名单
    def test_staging_whitelists_know_the_component(self):
        self.assertIn("EndfieldJiggleEFMI", activation.CONTROLLER_OWNED_NAMES)
        self.assertIn("EndfieldJiggleEFMI", crashwatch._CONTROLLER_DIRS)          # noqa: SLF001
        self.assertIn("EndfieldJiggleEFMI", initialize.MOD_CONFLICT_IGNORE_NAMES)

    def test_find_manual_mods_skips_it_but_not_user_mods(self):
        """它不能被认成"用户手工放的 Mod"（否则会被收编、勾选、再搬出 staging）。"""
        self.target.mkdir(parents=True, exist_ok=True)
        (self.target / "EndfieldJiggle.ini").write_text("namespace = x\n", encoding="utf-8")
        (self.staging / "某人手放的皮肤").mkdir(parents=True, exist_ok=True)
        manual = [p.name for p in activation.find_manual_mods(self.staging)]
        self.assertNotIn("EndfieldJiggleEFMI", manual)
        self.assertIn("某人手放的皮肤", manual)

    def test_safe_mode_field_is_registered(self):
        """安全模式「还原配置」必须能关掉它（漏了它 = 以为退回原版其实还挂着一个 Mod）。"""
        self.assertIn("jiggle_efmi_injection", alerts.INJECTION_FIELDS)

    # ---------------------------------------------------------------- 启动自检
    def test_selfcheck_parks_when_switch_off(self):
        self.target.mkdir(parents=True, exist_ok=True)
        (self.target / "EndfieldJiggle.ini").write_text("namespace = x\n", encoding="utf-8")
        self.config.jiggle_efmi_injection = False
        report = initialize.Report()
        initialize._check_jiggle_efmi(self.config, report, None)                  # noqa: SLF001
        self.assertFalse(self.target.is_dir(), "开关关着时自检要把已经铺进去的移出来")

    def test_selfcheck_deploys_when_switch_on(self):
        efmi_jiggle.import_pack(self.config, make_pack(Path(self._tmp.name)))
        self.config.jiggle_efmi_injection = True
        report = initialize.Report()
        initialize._check_jiggle_efmi(self.config, report, None)                  # noqa: SLF001
        payload = report.to_dict()
        self.assertTrue((self.target / "EndfieldJiggle.ini").is_file())
        row = [c for c in payload["checks"] if c["key"] == "jiggle_efmi"]
        self.assertTrue(row and row[0]["ok"], payload["checks"])

    def test_selfcheck_reports_missing_pack_as_manual(self):
        self.config.jiggle_efmi_injection = True
        report = initialize.Report()
        initialize._check_jiggle_efmi(self.config, report, None)                  # noqa: SLF001
        payload = report.to_dict()
        row = [c for c in payload["checks"] if c["key"] == "jiggle_efmi"][0]
        self.assertFalse(row["ok"])
        self.assertFalse(self.target.is_dir())

    # ---------------------------------------------------------------- 接口 / 前端
    def test_api_entrypoints_exist(self):
        for name in ("jiggle_efmi_status", "jiggle_efmi_install", "jiggle_efmi_uninstall",
                     "open_jiggle_efmi_upstream"):
            self.assertTrue(callable(getattr(self.api, name, None)), name)
        state = self.api.jiggle_efmi_status()
        self.assertIn("enabled", state)
        self.assertIn("staging_root", state)

    def test_launch_page_has_the_switch(self):
        """启动页开关要真的绑到装卸接口上（前端漏改 = 界面上没有这个开关）。"""
        vue = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"
               / "LaunchPage.vue").read_text(encoding="utf-8")
        self.assertIn('k: "jiggle_efmi_injection"', vue)
        self.assertIn('"jiggle_efmi_install"', vue)
        self.assertIn('"jiggle_efmi_uninstall"', vue)
        # 依赖页是泛型渲染，条目由后端 manifest 提供 —— 这里钉住后端那一处
        api_py = (Path(api_mod.__file__)).read_text(encoding="utf-8")
        self.assertIn('report["manifest"]["jiggle_efmi"]', api_py)
        # 版本表与更新流程也各要有一处（漏了 = 依赖页永远说"已是最新"）
        self.assertIn("jiggle_efmi", (Path(initialize.__file__).parent
                                      / "component_versions.json").read_text(encoding="utf-8"))


class JiggleEfmiDamageTests(unittest.TestCase):
    """「文件在、内容不对」必须查得出来（用户 2026-10-13 反馈的缺口）。

    用户原话：「下载后的文件损坏**检测按钮和启动检查都查不出来**」——
    老逻辑只判 `is_file()`，所以半截下载、安全软件破坏、复制中断留下的
    "大小看着正常、内容不对"的文件，界面一路显示"完整"。
    这里钉住四层防线：装的时候记基线、平时能比对、启动自检能自愈、完整性检查能看到。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mc-jiggle-dmg-")
        root = Path(self._tmp.name)
        (root / "runtime").mkdir(parents=True, exist_ok=True)
        (root / "library").mkdir(parents=True, exist_ok=True)
        cfg = root / "config.json"
        cfg.write_text(json.dumps({"data_root": "", "runtime_dir": "runtime",
                                   "library_dir": "library"}, ensure_ascii=False),
                       encoding="utf-8")
        self.api = api_mod.EndfieldModControllerApi(str(cfg))
        self.config = self.api.config
        self.target = efmi_jiggle.mod_dir(self.config)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _install(self) -> None:
        efmi_jiggle.import_pack(self.config, make_pack(Path(self._tmp.name)))
        efmi_jiggle.deploy(self.config)

    def test_verify_catches_a_corrupted_file(self):
        """装完之后改坏一个文件 ⇒ 内容级校验必须报出来（而不是显示"完整"）。"""
        self._install()
        self.assertTrue(efmi_jiggle.verify(self.config)["ok"])
        (self.target / "Passes.ini").write_text("corrupted\n", encoding="utf-8")
        state = efmi_jiggle.status(self.config)
        self.assertFalse(state["verified"])
        self.assertIn("Passes.ini", state["corrupt"])
        self.assertFalse(efmi_jiggle.verify(self.config)["ok"])

    def test_verify_catches_a_dropped_file(self):
        self._install()
        (self.target / "shaders" / "motion_model.hlsl").unlink()
        verify = efmi_jiggle.verify(self.config)
        self.assertFalse(verify["ok"])
        self.assertIn("shaders/motion_model.hlsl", verify["missing"])

    def test_verify_without_baseline_never_false_alarms(self):
        """没记过基线（手工放进去的目录）不许被当成损坏 —— 读不到基线 ≠ 坏。"""
        for rel, text in MOD_FILES.items():
            path = self.target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        verify = efmi_jiggle.verify(self.config)
        self.assertTrue(verify["ok"])
        self.assertFalse(verify["known"])

    def test_import_pack_rejects_a_crc_broken_zip(self):
        """半截/损坏的 zip 当场拒绝，而不是铺一堆坏文件进 Mods。"""
        archive = make_pack(Path(self._tmp.name))
        raw = bytearray(archive.read_bytes())
        raw[-60:-20] = b"\x00" * 40
        archive.write_bytes(bytes(raw))
        result = efmi_jiggle.import_pack(self.config, archive)
        self.assertFalse(result["ok"])
        self.assertIn("损坏", result["message"])

    def test_deploy_does_not_trust_a_damaged_dir(self):
        """Mods 里那份内容不符基线时，`deploy` 不许说"已就位"（否则自愈是空转）。"""
        self._install()
        (self.target / "EndfieldJiggle.ini").write_text("broken\n", encoding="utf-8")
        result = efmi_jiggle.deploy(self.config)
        self.assertTrue(result["changed"], result)
        self.assertTrue(efmi_jiggle.verify(self.config)["ok"])

    def test_selfcheck_repairs_damage_from_local_pack(self):
        """启动自检要能自己修：本地留着原始包 ⇒ 重解重铺，**不联网**。"""
        self._install()
        (self.target / "Passes.ini").write_text("broken\n", encoding="utf-8")
        self.config.jiggle_efmi_injection = True
        report = initialize.Report()
        initialize._check_jiggle_efmi(self.config, report, None)                  # noqa: SLF001
        row = [c for c in report.to_dict()["checks"] if c["key"] == "jiggle_efmi"][0]
        self.assertTrue(row["ok"], row)
        self.assertTrue(efmi_jiggle.verify(self.config)["ok"])

    def test_integrity_button_surfaces_the_damage(self):
        """「完整性检查」按钮必须看得见它，而且**不许**因此拦死启动（critical=False）。"""
        from endfieldmodcontroller import integrity

        self._install()
        (self.target / "Passes.ini").write_text("broken\n", encoding="utf-8")
        self.config.jiggle_efmi_injection = True
        report = integrity.check_integrity(self.config)
        rows = [c for c in report["checks"] if c["key"] == "jiggle_efmi"]
        self.assertTrue(rows, "完整性检查里必须有这一项")
        self.assertFalse(rows[0]["ok"])
        self.assertFalse(rows[0]["critical"], "可选 Mod 损坏不该拦死启动")
        self.assertNotIn("jiggle_efmi", [item["key"] for item in report["failures"]])

    def test_switch_off_is_not_reported_by_integrity(self):
        """开关关着（默认）⇒ 完整性检查里**不该**出现这一项（不打扰）。"""
        from endfieldmodcontroller import integrity

        self.config.jiggle_efmi_injection = False
        report = integrity.check_integrity(self.config)
        self.assertFalse([c for c in report["checks"] if c["key"] == "jiggle_efmi"])


if __name__ == "__main__":
    unittest.main()
