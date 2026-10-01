"""按显卡代次决定 DLSS5（用户 2026-10-01 要求：「**开启时检测机器，如果不是 50 系就默认关
dlss5，开启 dlss5 的时候弹窗说明拒绝**」）。

背景：DLSS5 神经渲染首发只支持 RTX 50 系；40 系及更早的机器上 NGX 会以 `0xBAD00001`
（FeatureNotSupported）拒掉 feature 18 —— 面板永远 `成功NR帧 0`。默认开着只会让人以为
装坏了，所以：非 50 系 → 默认关 + 手动开时**拒绝**并说明原因。

测试里**必须把显卡探测打桩**（`deviceinfo.collect`）—— 否则跑测试的人是什么卡，结论就
跟着变（开发机是 5080，CI/别人可能是 4060）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import deviceinfo
from endfieldmodcontroller.config import AppConfig


def _fake_adapter(name: str):
    def _collect(refresh: bool = False):
        return {"adapters": [{"name": name}]}

    return _collect


class _GpuCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-gpu-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def load_with_gpu(self, gpu: str, name: str = "config.json", **seed) -> AppConfig:
        path = self.root / name
        if seed or seed == {} and path.suffix:
            pass
        if seed:
            path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(deviceinfo, "collect", _fake_adapter(gpu)):
            deviceinfo.collect(refresh=True)
            return AppConfig.load(path)


class Dlss5GpuDefaultTests(_GpuCase):
    def test_non_50_series_defaults_dlss5_off(self) -> None:
        for gpu in ("NVIDIA GeForce RTX 4060 Laptop GPU", "NVIDIA GeForce RTX 4070 Laptop GPU",
                    "NVIDIA GeForce RTX 3080", "NVIDIA GeForce GTX 1660"):
            cfg = self.load_with_gpu(gpu, name=f"{gpu.split()[-1]}.json")
            self.assertFalse(cfg.dlss5_addon_enabled, gpu)
            self.assertTrue(cfg.dlss5_gpu_default_applied)

    def test_50_series_keeps_dlss5_on(self) -> None:
        cfg = self.load_with_gpu("NVIDIA GeForce RTX 5080")
        self.assertTrue(cfg.dlss5_addon_enabled)

    def test_user_choice_on_50_series_is_not_overridden(self) -> None:
        cfg = self.load_with_gpu(
            "NVIDIA GeForce RTX 5080", name="kept.json",
            dlss5_addon_enabled=False, hotkey_default_applied=True,
        )
        self.assertFalse(cfg.dlss5_addon_enabled, "用户自己关掉的开关不许被迁移改回来")

    def test_migration_turns_off_on_40_series(self) -> None:
        cfg = self.load_with_gpu(
            "NVIDIA GeForce RTX 4070 Laptop GPU", name="mig.json",
            dlss5_addon_enabled=True, hotkey_default_applied=True,
        )
        self.assertFalse(cfg.dlss5_addon_enabled)
        # 迁移结果要落盘，下次不再重复判断
        saved = json.loads((self.root / "mig.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["dlss5_addon_enabled"])
        self.assertTrue(saved["dlss5_gpu_default_applied"])

    def test_hotkey_takeover_defaults_on(self) -> None:
        """同批改动：用户还要求「把快捷键整合设为默认开启」。"""
        cfg = self.load_with_gpu("NVIDIA GeForce RTX 5080", name="hotkey.json")
        self.assertTrue(cfg.hotkey_takeover)


class Dlss5GpuGateTests(_GpuCase):
    """手动打开 DLSS5 时，非 50 系要被**拒绝**（不写配置、返回原因给前端弹窗）。"""

    def _api(self, gpu: str):
        from endfieldmodcontroller.api import EndfieldModControllerApi

        path = self.root / "config.json"
        with mock.patch.object(deviceinfo, "collect", _fake_adapter(gpu)):
            deviceinfo.collect(refresh=True)
            cfg = AppConfig(
                library_dir=str(self.root / "library"),
                runtime_dir=str(self.root / "runtime"),
                staging_mods_dir=str(self.root / "runtime" / "EFMI" / "Mods"),
                dlss5_addon_enabled=False,
            )
            cfg.save(path)
            api = EndfieldModControllerApi(path)
            api.config.dlss5_addon_enabled = False
            return api

    def test_enable_is_rejected_on_40_series(self) -> None:
        api = self._api("NVIDIA GeForce RTX 4060 Laptop GPU")
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU")):
            result = api.set_component_addon("dlss5", True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["rejected"], "dlss5_unsupported_gpu")
        self.assertIn("50 系", result["message"])
        self.assertFalse(api.config.dlss5_addon_enabled, "被拒绝时不许把开关写成开着")

    def test_enable_is_allowed_on_50_series(self) -> None:
        from endfieldmodcontroller import launcher

        api = self._api("NVIDIA GeForce RTX 5080")
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 5080")), \
                mock.patch.object(launcher, "set_component_addons", return_value={"moved": []}), \
                mock.patch.object(launcher, "configure_dlss5_injection", return_value={}):
            result = api.set_component_addon("dlss5", True)
        self.assertNotEqual(result.get("rejected"), "dlss5_unsupported_gpu")
        self.assertTrue(api.config.dlss5_addon_enabled)


class Dlss5GpuSelfCheckTests(_GpuCase):
    def test_self_check_turns_the_switch_off(self) -> None:
        from endfieldmodcontroller import initialize, launcher

        config = AppConfig(
            runtime_dir=str(self.root / "runtime"),
            staging_mods_dir=str(self.root / "runtime" / "EFMI" / "Mods"),
            dlss5_addon_enabled=True,
        )
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU")), \
                mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU")), \
                mock.patch.object(launcher, "set_component_addons", return_value={"moved": []}), \
                mock.patch.object(launcher, "configure_dlss5_injection", return_value={}):
            report = initialize.Report()
            initialize._check_dlss5_gpu_support(config, report, None)
        check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:gpu_support")
        self.assertTrue(check["ok"], "硬件支持范围问题不该报成待处理故障")
        self.assertIn("50 系", check["message"])
        self.assertFalse(config.dlss5_addon_enabled, "自检发现开关还开着时应顺手关掉")

    def test_self_check_passes_on_50_series(self) -> None:
        from endfieldmodcontroller import initialize

        config = AppConfig(runtime_dir=str(self.root / "runtime"))
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 5080")):
            report = initialize.Report()
            initialize._check_dlss5_gpu_support(config, report, None)
        check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:gpu_support")
        self.assertTrue(check["ok"])
        self.assertIn("5080", check["message"])


if __name__ == "__main__":
    unittest.main()
