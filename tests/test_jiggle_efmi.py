# SPDX-License-Identifier: GPL-3.0-or-later
"""EndfieldJiggle（触摸形变 Mod）迁进 Mod 库的回归（2026-10-19 用户要求）。

用户原话：「触摸 mod 移出自带，加入自动识别进辅助 mod」——
起因是反馈「触摸现在一键启动不行，需要手动移动进 mods 文件夹才行」。
旧实现只在初始化自检那条路部署它，而 `launcher.launch` 根本不跑 initialize。

现在它是一条**库里的普通辅助 Mod**：
  * 自动装进 Mod 库（首次一键启动 / 生成控制器 / 自检都会补），默认勾选；
  * 之后走 `stage_and_prepare`，一键启动自动铺进 `EFMI\\Mods\\MC_其它辅助_…`；
  * 开关 = 辅助 Mod 页上那个勾选；旧版直接铺在 Mods 顶层的目录会被自动收进库。

钉住这些判据：
① 识别（kind/group、不锁键、不进 ReShade 面板）；
② 装进库 + 写 sidecar + 默认勾选；已有则不动；用户移出后不再自动装回；
③ 旧 Mods 目录迁移（先复制成功再删来源）；失败节流；
④ 内容级校验（"文件在、内容不对"也查得出）；
⑤ 不再有启动页开关 / 依赖页条目 / 完整性检项。
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import activation, core, efmi_jiggle, initialize, integrity
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


def write_mod_dir(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for rel, text in MOD_FILES.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class JiggleLibraryTests(unittest.TestCase):
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
        self.library = Path(self.config.library_path)
        self.staging = Path(self.config.staging_mods_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _payload(self) -> dict:
        return efmi_jiggle.import_pack(self.config, make_pack(Path(self._tmp.name)))

    # ---------------------------------------------------------------- 安装包
    def test_import_pack_finds_the_nested_mod_dir(self):
        """三段套法的 zip 也要能识别（.../Mods/EndfieldJiggleEFMI/）。"""
        result = self._payload()
        self.assertTrue(result["ok"], result)
        self.assertTrue(efmi_jiggle.payload_ready(self.config))
        self.assertEqual(efmi_jiggle.installed_version(self.config), "0.2.2")
        self.assertTrue((efmi_jiggle.payload_dir(self.config) / "EndfieldJiggle.ini").is_file())
        self.assertTrue(list((efmi_jiggle.component_root(self.config) / "_pack").glob("*.zip")))

    def test_import_pack_rejects_source_like_zip(self):
        archive = Path(self._tmp.name) / "source.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("repo-main/README.md", "no mod here\n")
        result = efmi_jiggle.import_pack(self.config, archive)
        self.assertFalse(result["ok"])
        self.assertIn("EndfieldJiggle.ini", result["message"])

    def test_import_pack_rejects_a_crc_broken_zip(self):
        archive = make_pack(Path(self._tmp.name))
        raw = bytearray(archive.read_bytes())
        raw[-60:-20] = b"\x00" * 40
        archive.write_bytes(bytes(raw))
        result = efmi_jiggle.import_pack(self.config, archive)
        self.assertFalse(result["ok"])
        self.assertIn("损坏", result["message"])

    def test_pick_asset_only_takes_the_mod_pack(self):
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

    # ---------------------------------------------------------------- 装进库
    def test_install_to_library_places_mod_and_selects_it(self):
        self._payload()
        result = efmi_jiggle.install_to_library(self.config)
        self.assertTrue(result["ok"], result)
        target = efmi_jiggle.library_dir(self.config)
        self.assertTrue((target / "EndfieldJiggle.ini").is_file())
        meta = json.loads((target / "mod.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "assist")
        self.assertEqual(meta["group"], "其它辅助")
        self.assertEqual(meta["jiggle_version"], "0.2.2")
        self.assertIn(meta["id"], self.config.selected_mods, "装进来要默认启用")
        state = efmi_jiggle.status(self.config)
        self.assertTrue(state["in_library"])
        self.assertFalse(state["in_mods"])
        self.assertEqual(state["version"], "0.2.2")

    def test_install_uses_local_payload_without_any_network(self):
        self._payload()
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                        side_effect=AssertionError("本地载荷在位时不该联网")):
            result = efmi_jiggle.install_to_library(self.config)
        self.assertTrue(result["ok"], result)

    def test_install_reports_network_failure_without_writing_library(self):
        with mock.patch("endfieldmodcontroller.offline_deps.resolve_offline", return_value=None), \
                mock.patch("endfieldmodcontroller.github.releases_latest",
                           side_effect=RuntimeError("断网")):
            result = efmi_jiggle.install_to_library(self.config)
        self.assertFalse(result["ok"])
        self.assertIn("断网", result["message"])
        self.assertFalse(efmi_jiggle.library_dir(self.config).exists())

    def test_ensure_is_noop_when_already_in_library(self):
        self._payload()
        efmi_jiggle.install_to_library(self.config)
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                        side_effect=AssertionError("已在库里时不该联网")):
            result = efmi_jiggle.ensure_in_library(self.config)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["changed"])
        self.assertTrue(result["in_library"])

    def test_ensure_adopts_legacy_mods_dir(self):
        """旧版直接铺在 EFMI\\Mods 顶层的那份要**收进库**，然后在库里生效。"""
        legacy = efmi_jiggle.staging_legacy_dir(self.config)
        write_mod_dir(legacy)
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                        side_effect=AssertionError("迁移不该联网")):
            result = efmi_jiggle.ensure_in_library(self.config)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("adopted"))
        target = efmi_jiggle.library_dir(self.config)
        self.assertTrue((target / "EndfieldJiggle.ini").is_file())
        self.assertFalse(legacy.exists(), "收进库之后要把 Mods 里那份移走（两份同 namespace 会打架）")
        self.assertIn(json.loads((target / "mod.meta.json").read_text(encoding="utf-8"))["id"],
                      self.config.selected_mods)

    def test_ensure_respects_user_optout(self):
        efmi_jiggle.mark_optout(self.config, "用户移出 Mod 库")
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                        side_effect=AssertionError("用户已经移出，不该自动装回")):
            result = efmi_jiggle.ensure_in_library(self.config)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("skipped"))
        self.assertFalse(efmi_jiggle.library_dir(self.config).exists())

    def test_ensure_throttles_after_a_failed_attempt(self):
        with mock.patch("endfieldmodcontroller.offline_deps.resolve_offline", return_value=None), \
                mock.patch("endfieldmodcontroller.github.releases_latest",
                           side_effect=RuntimeError("断网")):
            first = efmi_jiggle.ensure_in_library(self.config)
        self.assertFalse(first["ok"])
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                        side_effect=AssertionError("6 小时内不该再重试")):
            second = efmi_jiggle.ensure_in_library(self.config)
        self.assertTrue(second["ok"])
        self.assertEqual(second.get("reason"), "retry-throttle")

    # ---------------------------------------------------------------- 内容校验
    def test_verify_catches_a_corrupted_file(self):
        self._payload()
        efmi_jiggle.install_to_library(self.config)
        self.assertTrue(efmi_jiggle.verify(self.config)["ok"])
        (efmi_jiggle.library_dir(self.config) / "Passes.ini").write_text("corrupted\n",
                                                                        encoding="utf-8")
        state = efmi_jiggle.status(self.config)
        self.assertFalse(state["verified"])
        self.assertIn("Passes.ini", state["corrupt"])

    def test_verify_catches_a_dropped_file(self):
        self._payload()
        efmi_jiggle.install_to_library(self.config)
        (efmi_jiggle.library_dir(self.config) / "shaders" / "motion_model.hlsl").unlink()
        verify = efmi_jiggle.verify(self.config)
        self.assertFalse(verify["ok"])
        self.assertIn("shaders/motion_model.hlsl", verify["missing"])

    def test_verify_without_baseline_never_false_alarms(self):
        """没记过基线（用户手工放进去的目录）不许被当成损坏 —— 读不到基线 ≠ 坏。"""
        write_mod_dir(efmi_jiggle.library_dir(self.config))
        verify = efmi_jiggle.verify(self.config)
        self.assertTrue(verify["ok"])
        self.assertFalse(verify["known"])

    def test_ensure_repairs_a_damaged_library_copy(self):
        self._payload()
        efmi_jiggle.install_to_library(self.config)
        (efmi_jiggle.library_dir(self.config) / "Passes.ini").write_text("broken\n",
                                                                        encoding="utf-8")
        result = efmi_jiggle.ensure_in_library(self.config)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("damaged"))
        self.assertTrue(efmi_jiggle.verify(self.config)["ok"])

    # ---------------------------------------------------------------- 识别
    def test_core_recognizes_touch_mod(self):
        target = efmi_jiggle.library_dir(self.config)
        write_mod_dir(target)
        self.assertTrue(core.is_touch_mod(target, (target.name,)))
        kind, group = core.infer_kind_and_group((target.name,), {}, target)
        self.assertEqual(kind, "assist")
        self.assertEqual(group, core.ASSIST_GROUP_OTHER)
        # 它自己处理输入 ⇒ 不锁键、也不把 Key* 塞进 ReShade 面板
        self.assertTrue(core.looks_like_ui_mod(target, ("其它辅助", "EndfieldJiggle（触摸形变）"), {}))
        mods = core.scan_library(self.library, self.staging)
        touch = [m for m in mods if m.kind == "assist"]
        self.assertTrue(touch, "库里那份必须被识别成辅助 Mod")
        self.assertTrue(touch[0].to_dict()["is_touch"])

    def test_old_dir_name_is_still_controller_owned(self):
        """旧版铺在 Mods 顶层的那份不能被当成"用户手放的 Mod"收编/搬走。"""
        self.assertIn("EndfieldJiggleEFMI", activation.CONTROLLER_OWNED_NAMES)
        self.assertIn("EndfieldJiggleEFMI", initialize.MOD_CONFLICT_IGNORE_NAMES)

    # ---------------------------------------------------------------- 自检 / 完整性
    def test_selfcheck_installs_into_library(self):
        self._payload()
        report = initialize.Report()
        initialize._check_jiggle_efmi(self.config, report, None)                  # noqa: SLF001
        self.assertTrue((efmi_jiggle.library_dir(self.config) / "EndfieldJiggle.ini").is_file())
        row = [c for c in report.to_dict()["checks"] if c["key"] == "jiggle_efmi"]
        self.assertTrue(row and row[0]["ok"], report.to_dict()["checks"])

    def test_selfcheck_without_pack_is_not_a_blocker(self):
        with mock.patch("endfieldmodcontroller.offline_deps.resolve_offline", return_value=None), \
                mock.patch("endfieldmodcontroller.github.releases_latest",
                           side_effect=RuntimeError("断网")):
            report = initialize.Report()
            initialize._check_jiggle_efmi(self.config, report, None)              # noqa: SLF001
        row = [c for c in report.to_dict()["checks"] if c["key"] == "jiggle_efmi"][0]
        self.assertTrue(row["ok"], "可选 Mod 没装上不该拦启动")

    def test_integrity_no_longer_checks_it(self):
        report = integrity.check_integrity(self.config)
        self.assertFalse([c for c in report["checks"] if c["key"] == "jiggle_efmi"])

    # ---------------------------------------------------------------- 接口 / 前端
    def test_api_entrypoints(self):
        self.assertTrue(callable(getattr(self.api, "jiggle_update", None)))
        self.assertTrue(callable(getattr(self.api, "jiggle_efmi_status", None)))
        self.assertFalse(hasattr(self.api, "jiggle_efmi_install"))
        self.assertFalse(hasattr(self.api, "jiggle_efmi_uninstall"))
        state = self.api.jiggle_efmi_status()
        self.assertIn("in_library", state)

    def test_launch_page_has_no_switch(self):
        """启动页不许再有这个组件的单独开关（用户：用和其他 Mod 一样的就行）。"""
        vue = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"
               / "LaunchPage.vue").read_text(encoding="utf-8")
        self.assertNotIn("jiggle_efmi", vue)

    def test_deps_page_has_no_entry(self):
        source = Path(api_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn('report["manifest"]["jiggle_efmi"]', source)
        self.assertNotIn("jiggle_efmi_injection", source)

    def test_pending_component_updates_excludes_it(self):
        """它已经不是组件 ⇒ 启动前那张"有新版本，去下载页更新"的清单里不该出现。"""
        result = self.api.pending_component_updates()
        self.assertNotIn("jiggle_efmi", result.get("installed") or {})

    def test_launcher_install_before_stage(self):
        """一键启动必须在 stage **之前**保证它在库里（否则还是会"必须手动移进 Mods"）。"""
        import inspect

        from endfieldmodcontroller import launcher

        source = inspect.getsource(launcher.launch)
        self.assertIn("ensure_in_library", source)
        stage_call = source.index("activation.stage_and_prepare(")
        self.assertLess(source.index("ensure_in_library"), stage_call)


class JigglePackageParseTests(unittest.TestCase):
    """（保留）上游包层级/CRC 的两个老判据 —— 它们是"铺一堆坏文件"的最后一道闸。"""

    def test_three_level_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = make_pack(root, layout="EndfieldJiggleEFMI-v0.9.9/Mods/EndfieldJiggleEFMI")
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
            self.assertTrue(any(name.endswith("EndfieldJiggleEFMI/EndfieldJiggle.ini")
                                for name in names))


if __name__ == "__main__":
    unittest.main()
