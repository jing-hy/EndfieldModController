"""按**显卡支持范围**决定 DLSS5 的默认开关与闸门。

**两次判据变更的历史（别把它们弄混）**：
* 2026-10-01（用户原话）：「开启时检测机器，如果不是 50 系就默认关 dlss5，开启 dlss5 的
  时候弹窗说明拒绝」—— 当时 DLSS5 首发只有 50 系运行库，40 系及更早会被 NGX 以
  `0xBAD00001`（FeatureNotSupported）拒掉，默认开着只会让人以为装坏了。
* **2026-10-05（用户原话）**：「去掉所有对非 50 系的锁，换成对 a 卡和 10 系及以下和核显」
  —— 实测发现那份随包运行库**只含 sm_120 内核**，而社区把它重定向到 sm_89/sm_86/sm_75
  之后 40/30/20 系都能跑（见 `runtime_assets` 的变体表）。于是判据变成
  **"有 tensor core 的 NVIDIA 卡"**，也就是 RTX 20 系及以上。

**因此本文件的语义变了**：以前"40 系要被关掉"，现在"40 系要被打开"。
不支持的是：A 卡 / Intel / 核显（没有可用的 NVIDIA 运行库）、GTX 10 系及以下、
以及 **GTX 16 系**（Turing sm_75 但**没有 tensor core**，上游实测跑不了）。

测试里**必须把显卡探测打桩**（`deviceinfo.collect`）—— 否则跑测试的人是什么卡，结论就
跟着变（开发机是 5080，别人可能是 4060）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import deviceinfo
from endfieldmodcontroller.config import AppConfig

# 「应该支持」的样本（有 tensor core 的 RTX）
SUPPORTED_GPUS = (
    "NVIDIA GeForce RTX 5080",
    "NVIDIA GeForce RTX 4070 Laptop GPU",
    "NVIDIA GeForce RTX 3080",
    "NVIDIA GeForce RTX 2060",
)
# 「不支持」的样本：无 N 卡 / 无 tensor core
UNSUPPORTED_GPUS = (
    "NVIDIA GeForce GTX 1660 SUPER",     # Turing sm_75，但**没有 tensor core**
    "NVIDIA GeForce GTX 1080 Ti",        # Pascal
    "AMD Radeon RX 7900 XTX",
    "Intel(R) Arc(TM) A770 Graphics",
    "Intel(R) UHD Graphics 630",         # 核显
)


def _fake_adapter(*names: str):
    """打桩显卡探测；**支持多张卡**（双显卡机器用，见 `DualGpuTests`）。

    ⚠️ 返回的结构要**跟真实 `collect()` 一致**（含 `dlss5_sm` / `dlss5_variant` 这些
    派生字段）：真实 `collect()` 会算好它们，若打桩只给 `adapters`，
    "读派生字段"的代码在测试里会 KeyError，而不是被测到。
    """
    def _collect(refresh: bool = False):
        adapters = [{"name": name} for name in names]
        cards = deviceinfo.rtx_cards(adapters)
        sm = cards[-1][1] if cards else None
        return {
            "adapters": adapters,
            "dlss5_cards": [{"name": name, "sm": card_sm} for name, card_sm in cards],
            "dlss5_sm": sm,
            "dlss5_variant": deviceinfo.dlss5_runtime_variant(sm),
        }

    return _collect


class _GpuCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-gpu-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def load_with_gpu(self, gpu: str, name: str = "config.json", **seed) -> AppConfig:
        path = self.root / name
        if seed:
            path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(deviceinfo, "collect", _fake_adapter(gpu)):
            deviceinfo.collect(refresh=True)
            return AppConfig.load(path)


class Dlss5GpuDefaultTests(_GpuCase):
    def test_supported_cards_default_dlss5_on(self) -> None:
        """⭐ 本轮核心：RTX 20/30/40/50 都该**默认开着**（旧判据会把 20/30/40 关掉）。"""
        for gpu in SUPPORTED_GPUS:
            cfg = self.load_with_gpu(gpu, name=f"{gpu.split()[-1]}.json")
            self.assertTrue(cfg.dlss5_addon_enabled, f"{gpu} 应该默认开启")
            self.assertTrue(cfg.dlss5_gpu_scope_applied)

    def test_unsupported_cards_default_dlss5_off(self) -> None:
        for gpu in UNSUPPORTED_GPUS:
            key = gpu.split()[-1].replace("(", "").replace(")", "")
            cfg = self.load_with_gpu(gpu, name=f"{key}.json")
            self.assertFalse(cfg.dlss5_addon_enabled, f"{gpu} 应该默认关闭")

    def test_migration_turns_40_series_back_on(self) -> None:
        """⭐ 老 40 系用户：配置里的 `False` 是**旧判据**写进去的，必须被重新打开。

        这正是"改判据但用户还是用不了"的坑：只改判据不动配置，40 系用户升级后依旧关着。
        """
        cfg = self.load_with_gpu(
            "NVIDIA GeForce RTX 4070 Laptop GPU", name="mig40.json",
            dlss5_addon_enabled=False, hotkey_default_applied=True,
            dlss5_gpu_default_applied=True,      # 旧迁移跑过（所以开关是旧的 False）
        )
        self.assertTrue(cfg.dlss5_addon_enabled, "旧判据关掉的 40 系必须被打开")
        saved = json.loads((self.root / "mig40.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["dlss5_addon_enabled"])
        self.assertTrue(saved["dlss5_gpu_scope_applied"])

    def test_user_choice_on_50_series_is_not_overridden(self) -> None:
        """50 系用户自己关掉的，迁移**不许**改回来（旧判据本来就支持 50 系 ⇒ 那个 False
        只可能是用户自己设的）。"""
        cfg = self.load_with_gpu(
            "NVIDIA GeForce RTX 5080", name="kept.json",
            dlss5_addon_enabled=False, hotkey_default_applied=True,
            dlss5_gpu_default_applied=True,
        )
        self.assertFalse(cfg.dlss5_addon_enabled, "用户自己关掉的开关不许被迁移改回来")

    def test_user_choice_on_40_series_after_scope_migration_is_kept(self) -> None:
        """已经跟过新范围的 40 系用户，之后自己关掉的不再被改回来。"""
        cfg = self.load_with_gpu(
            "NVIDIA GeForce RTX 4070 Laptop GPU", name="kept40.json",
            dlss5_addon_enabled=False, hotkey_default_applied=True,
            dlss5_gpu_default_applied=True, dlss5_gpu_scope_applied=True,
        )
        self.assertFalse(cfg.dlss5_addon_enabled)

    def test_hotkey_takeover_defaults_on(self) -> None:
        """同批改动：用户还要求「把快捷键整合设为默认开启」。"""
        cfg = self.load_with_gpu("NVIDIA GeForce RTX 5080", name="hotkey.json")
        self.assertTrue(cfg.hotkey_takeover)


class Dlss5GpuGateTests(_GpuCase):
    """手动打开 DLSS5 时的闸门：**只有真正不支持的机器**才被拒。"""

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

    def test_enable_is_allowed_on_40_series(self) -> None:
        """⭐ 40 系不再被拒（旧版本这里会返回 `dlss5_unsupported_gpu`）。"""
        from endfieldmodcontroller import launcher

        api = self._api("NVIDIA GeForce RTX 4060 Laptop GPU")
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU")), \
                mock.patch.object(launcher, "set_component_addons", return_value={"moved": []}), \
                mock.patch.object(launcher, "configure_dlss5_injection", return_value={}):
            result = api.set_component_addon("dlss5", True)
        self.assertNotEqual(result.get("rejected"), "dlss5_unsupported_gpu",
                            f"40 系不该再被拒：{result}")
        self.assertTrue(api.config.dlss5_addon_enabled)

    def test_enable_is_allowed_on_50_series(self) -> None:
        from endfieldmodcontroller import launcher

        api = self._api("NVIDIA GeForce RTX 5080")
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 5080")), \
                mock.patch.object(launcher, "set_component_addons", return_value={"moved": []}), \
                mock.patch.object(launcher, "configure_dlss5_injection", return_value={}):
            result = api.set_component_addon("dlss5", True)
        self.assertNotEqual(result.get("rejected"), "dlss5_unsupported_gpu")
        self.assertTrue(api.config.dlss5_addon_enabled)

    def test_enable_is_rejected_without_tensor_core(self) -> None:
        """GTX 16 系（sm_75 但无 tensor core）与核显都要被拒，且说明里写清是**硬件前提**。"""
        for gpu in ("NVIDIA GeForce GTX 1660 SUPER", "Intel(R) UHD Graphics 630"):
            api = self._api(gpu)
            with mock.patch.object(deviceinfo, "collect", _fake_adapter(gpu)):
                result = api.set_component_addon("dlss5", True)
            self.assertFalse(result["ok"], gpu)
            self.assertEqual(result["rejected"], "dlss5_unsupported_gpu", gpu)
            self.assertIn("tensor core", result["message"], gpu)
            self.assertFalse(api.config.dlss5_addon_enabled, "被拒绝时不许把开关写成开着")


class Dlss5GpuSelfCheckTests(_GpuCase):
    def test_self_check_turns_the_switch_off_for_unsupported(self) -> None:
        """不支持的机器（GTX 1660）：自检顺手关掉，且**不报成待处理故障**。"""
        from endfieldmodcontroller import initialize, launcher

        config = AppConfig(
            runtime_dir=str(self.root / "runtime"),
            staging_mods_dir=str(self.root / "runtime" / "EFMI" / "Mods"),
            dlss5_addon_enabled=True,
        )
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce GTX 1660 SUPER")), \
                mock.patch.object(launcher, "set_component_addons", return_value={"moved": []}), \
                mock.patch.object(launcher, "configure_dlss5_injection", return_value={}):
            report = initialize.Report()
            initialize._check_dlss5_gpu_support(config, report, None)
        check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:gpu_support")
        self.assertTrue(check["ok"], "硬件支持范围问题不该报成待处理故障")
        self.assertIn("tensor core", check["message"])
        self.assertFalse(config.dlss5_addon_enabled, "自检发现开关还开着时应顺手关掉")

    def test_self_check_keeps_40_series_on(self) -> None:
        """⭐ 40 系：自检**不再**关开关，并且报出该用哪个运行库变体。"""
        from endfieldmodcontroller import initialize

        config = AppConfig(
            runtime_dir=str(self.root / "runtime"),
            dlss5_addon_enabled=True,
        )
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU")):
            report = initialize.Report()
            initialize._check_dlss5_gpu_support(config, report, None)
        check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:gpu_support")
        self.assertTrue(check["ok"])
        self.assertTrue(config.dlss5_addon_enabled, "40 系不该被自检关掉")
        self.assertIn("rtx40", check["message"], "要告诉用户该用哪个变体")

    def test_self_check_passes_on_50_series(self) -> None:
        from endfieldmodcontroller import initialize

        config = AppConfig(runtime_dir=str(self.root / "runtime"))
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce RTX 5080")):
            report = initialize.Report()
            initialize._check_dlss5_gpu_support(config, report, None)
        check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:gpu_support")
        self.assertTrue(check["ok"])
        self.assertIn("5080", check["message"])


class DualGpuTests(_GpuCase):
    """⭐ 双显卡机器不能被判成"只支持 50 系"（2026-10-04 用户转来的反馈）。

    反馈原话：「双显卡（**一张 5080，一张 4060**）会被 dlss5 的开关挡住，显示只支持 50 显卡」。
    根因：`dlss5_supported()` 把**所有** NVIDIA 卡的名字拼成一串，再 `re.search` 第一个
    `rtx\\d{4}` —— 取到哪张**完全看适配器枚举顺序**，取到 4060 就把 5080 用户挡在门外。
    正确语义：**只要有一张够格就该放行**（用户当然会用那张跑游戏），并告诉他用哪张。
    """

    def test_5080_plus_4060_is_supported(self) -> None:
        with mock.patch.object(deviceinfo, "collect",
                               _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU",
                                             "NVIDIA GeForce RTX 5080")):
            supported, gpu, reason = deviceinfo.dlss5_supported(refresh=True)
        self.assertTrue(supported, f"有 5080 就该支持，实际：{reason}")
        self.assertIn("5080", reason, "要说清是哪张卡够格")
        self.assertIn("4060", gpu, "两张卡都要报出来")
        self.assertIn("多张显卡", reason)

    def test_order_does_not_matter(self) -> None:
        """枚举顺序反过来（5080 在前）结论必须一样 —— 这正是原来会翻车的地方。"""
        with mock.patch.object(deviceinfo, "collect",
                               _fake_adapter("NVIDIA GeForce RTX 5080",
                                             "NVIDIA GeForce RTX 4060 Laptop GPU")):
            supported, _gpu, reason = deviceinfo.dlss5_supported(refresh=True)
        self.assertTrue(supported, f"顺序不该影响结论，实际：{reason}")

    def test_two_supported_cards_pick_the_higher_arch(self) -> None:
        """两张都支持时**按架构最高的那张**准备运行库（4070 是 sm_89、3070 是 sm_86）。"""
        with mock.patch.object(deviceinfo, "collect",
                               _fake_adapter("NVIDIA GeForce RTX 4070 Laptop GPU",
                                             "NVIDIA GeForce RTX 3070")):
            info = deviceinfo.collect(refresh=True)
            sm = deviceinfo.best_rtx_sm(refresh=True)
        self.assertEqual(sm, 89, "要取架构最高的那张")
        self.assertEqual(deviceinfo.dlss5_runtime_variant(sm), "rtx40")
        self.assertEqual(info["dlss5_sm"], 89, "诊断包里的派生字段也要一致")

    def test_unsupported_plus_supported_is_supported(self) -> None:
        """一张 GTX + 一张 RTX：只要 RTX 那张够格就放行（同双卡语义）。"""
        with mock.patch.object(deviceinfo, "collect",
                               _fake_adapter("NVIDIA GeForce GTX 1660 SUPER",
                                             "NVIDIA GeForce RTX 3060")):
            supported, _gpu, reason = deviceinfo.dlss5_supported(refresh=True)
        self.assertTrue(supported, f"有 3060 就该支持，实际：{reason}")

    def test_switch_is_allowed_on_dual_gpu(self) -> None:
        """端到端：双显卡机器上手动打开 DLSS5 **不该被拒**。"""
        from endfieldmodcontroller import launcher
        from endfieldmodcontroller.api import EndfieldModControllerApi

        path = self.root / "dual.json"
        with mock.patch.object(deviceinfo, "collect",
                               _fake_adapter("NVIDIA GeForce RTX 4060 Laptop GPU",
                                             "NVIDIA GeForce RTX 5080")):
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
            with mock.patch.object(launcher, "set_component_addons", return_value={"moved": []}), \
                    mock.patch.object(launcher, "configure_dlss5_injection", return_value={}):
                result = api.set_component_addon("dlss5", True)
        self.assertNotEqual(result.get("rejected"), "dlss5_unsupported_gpu",
                            f"有 5080 却被拒了：{result}")

    def test_generations_lists_every_card(self) -> None:
        self.assertEqual(deviceinfo.nvidia_generations(
            "nvidia geforce rtx 5080 / nvidia geforce rtx 4060 laptop gpu"), [50, 40])
        self.assertEqual(deviceinfo.nvidia_generations("nvidia geforce rtx 4060"), [40])
        self.assertEqual(deviceinfo.nvidia_generations("intel arc a770"), [])
        # 单值接口保持原语义（只取第一个），别被多卡改动带偏
        self.assertEqual(deviceinfo.nvidia_generation("nvidia geforce rtx 5080"), 50)

    def test_verdict_uses_highest_arch(self) -> None:
        verdict = deviceinfo._verdict("nvidia geforce rtx 4060 / nvidia geforce rtx 5080")
        self.assertIn("50 系", verdict)
        self.assertIn("sm_120", verdict, "要报出按哪张卡的架构准备运行库")
        self.assertIn("按架构最高", verdict)


class NvidiaSmTests(_GpuCase):
    """卡名 → CUDA 架构的映射（"用哪份运行库"的唯一判据）。"""

    def test_generation_mapping(self) -> None:
        cases = {
            "nvidia geforce rtx 5080": 120,
            "nvidia geforce rtx 4090": 89,
            "nvidia geforce rtx 3080 ti": 86,
            "nvidia geforce rtx 2060": 75,
            "nvidia geforce rtx 4070 laptop gpu": 89,
        }
        for name, want in cases.items():
            self.assertEqual(deviceinfo.nvidia_sm(name), want, name)

    def test_workstation_cards_are_not_misread(self) -> None:
        # `RTX 2000 Ada` 是 Ada（sm_89），**不是** RTX 20 系；`RTX A4000` 是 Ampere
        self.assertEqual(deviceinfo.nvidia_sm("nvidia rtx 2000 ada"), 89)
        self.assertEqual(deviceinfo.nvidia_sm("nvidia rtx a4000"), 86)
        self.assertEqual(deviceinfo.nvidia_sm("nvidia titan rtx"), 75)

    def test_gtx16_is_turing_but_has_no_tensor_core(self) -> None:
        # 架构号是 75（Turing），但**没有 RTX 前缀** ⇒ 不能算支持
        self.assertEqual(deviceinfo.nvidia_sm("nvidia geforce gtx 1660 super"), 75)
        with mock.patch.object(deviceinfo, "collect", _fake_adapter("NVIDIA GeForce GTX 1660 SUPER")):
            supported, _gpu, reason = deviceinfo.dlss5_supported(refresh=True)
        self.assertFalse(supported)
        self.assertIn("tensor core", reason)

    def test_non_nvidia_and_old_cards(self) -> None:
        for name in ("amd radeon rx 7900 xtx", "intel(r) arc(tm) a770 graphics",
                     "intel(r) uhd graphics 630", "nvidia geforce gtx 1080 ti"):
            self.assertIsNone(deviceinfo.nvidia_sm(name), name)

    def test_variant_mapping(self) -> None:
        self.assertEqual(deviceinfo.dlss5_runtime_variant(120), "official")
        self.assertEqual(deviceinfo.dlss5_runtime_variant(89), "rtx40")
        self.assertEqual(deviceinfo.dlss5_runtime_variant(86), "sf")
        self.assertEqual(deviceinfo.dlss5_runtime_variant(75), "sf")
        self.assertEqual(deviceinfo.dlss5_runtime_variant(None), "")


if __name__ == "__main__":
    unittest.main()
