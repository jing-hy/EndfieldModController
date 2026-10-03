from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import activation, integrity, runtime_deps
from endfieldmodcontroller.config import AppConfig


class IntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-integrity-")
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.builtin = self.runtime / "builtin"
        self.xxmi_root = self.builtin / "XXMI"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            builtin_runtime_dir=str(self.builtin),
            staging_mods_dir=str(self.xxmi_root / "EFMI" / "Mods"),
            xxmi_launcher=str(self.xxmi_root / "Resources" / "Bin" / "XXMI Launcher.exe"),
            reshade_injection="none",
        )
        self.config._config_path = str(self.root / "config.json")
        # dlss5 走相对路径后指向临时 runtime，必须在 fixture 里造出来，
        # 否则 dlss5_dll / dlss5_ini / dlss5_enhancer_addon 三项会失败
        self.config.dlss5_dir = str(self.runtime / "dlss5")
        self.config.reshade_dll = str(self.runtime / "dlss5" / "d3d12.dll")
        self._make_files()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _touch(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def _make_files(self) -> None:
        self._touch(Path(self.config.xxmi_launcher))
        package = self.xxmi_root / "Resources" / "Packages" / "XXMI"
        for name in ("3dmloader.dll", "d3d11.dll", "d3dcompiler_47.dll"):
            self._touch(package / name)
        self._touch(self.xxmi_root / "EFMI" / "Core" / "EFMI" / "main.ini")
        self._touch(self.xxmi_root / "EFMI" / "d3dx.ini")
        self._touch(self.xxmi_root / "EFMI" / "d3d11.dll")
        (self.xxmi_root / "EFMI" / "Mods").mkdir(parents=True, exist_ok=True)
        self._touch(self.config.reshade_runtime_path / "ReShade.ini")
        self._touch(self.config.reshade_runtime_path / "Addons" / "endfieldmodcontroller.addon")
        self._touch(self.config.reshade_runtime_path / "actions.tsv")
        self._touch(self.config.controller_dir / "controller.ini")
        self._touch(self.config.controller_dir / "actions.tsv")
        # DLSS5 底座三件套
        self._touch(self.config.dlss5_path / "d3d12.dll")
        self._touch(self.config.dlss5_path / "renodx-endfield-enhancer.addon64")
        ini = self.config.dlss5_ini_path
        ini.parent.mkdir(parents=True, exist_ok=True)
        ini.write_text("[endfield-enhancer]\nCameraFirstPerson=1\n", encoding="utf-8")

    def test_integrity_ok(self) -> None:
        report = integrity.check_integrity(self.config)
        self.assertTrue(report["ok"], report)

    def test_missing_d3d11_is_detected(self) -> None:
        (self.xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll").unlink()
        report = integrity.check_integrity(self.config)
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["key"] == "xxmi_libs_d3d11.dll" for item in report["failures"]))

    def test_efmi_dll_falls_back_to_package_dir(self) -> None:
        """EFMI 的 `d3d11.dll` 还没被 XXMI 部署到 `EFMI\\` 时，也要算就位。

        2026-10-02 反馈者截图：每次启动都弹「发现缺失文件：EFMI d3d11.dll（注入用）
        是否自动修复?」，点"继续"也修不好 —— 因为 `efmi_dir` 以前要求
        `<XXMI>\\EFMI\\d3d11.dll` **已经存在**才算找到 EFMI，于是 `efmi_dll_path` 里
        "回退到 `Resources\\Packages\\XXMI\\`"那段**永远走不到**（判据是死结：修复链里
        没有任何一步能把它变成"存在"），EFMI 的 dll 也永远进不了注入库。
        """
        (self.xxmi_root / "EFMI" / "d3d11.dll").unlink()
        efmi_dll = self.config.efmi_dll_path
        expected = self.xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll"
        # 用 samefile：tempfile 给的可能是 8.3 短路径（ADMINI~1），字符串比对会假失败
        self.assertTrue(efmi_dll is not None and os.path.samefile(efmi_dll, expected),
                        f"{efmi_dll} != {expected}")
        report = integrity.check_integrity(self.config)
        self.assertTrue(report["ok"], report)
        self.assertFalse(any(item["key"] == "efmi_dll" for item in report["failures"]))

    def test_efmi_dll_is_not_listed_in_extra_libraries(self) -> None:
        """⚠️ 行为已改（2026-10-03 实测）：**EFMI 的 d3d11.dll 不能出现在 extra_libraries 里**。

        原断言是"必须包含它"，前提是"XXMI 不会自己注入"。实测证明**它会**：
        XXMI 日志里的注入请求是

            Inject(library_name='d3d11.dll, d3d12.dll, d3d11.dll')

        —— 第一个 `d3d11.dll` 就是 XXMI 自带的 EFMI 注入。我们再在 extra_libraries 里列一遍
        （内容相同、路径不同），第二次注入必然失败，用户看到
        「注入额外库 …\Packages\XXMI\d3d11.dll 失败：DLL 注入失败！」并且**启动直接中断**。

        EFMI 的注入本身**没有丢**：XXMI 那条照旧执行（用户实测「efmi 关了直接终末地拉不起来」，
        说明它确实是必需品 —— 但归 XXMI 管）。
        """
        (self.xxmi_root / "EFMI" / "d3d11.dll").unlink()
        from endfieldmodcontroller import launcher

        targets = launcher.dlss5_injection_targets(self.config)
        self.assertFalse(any("d3d11.dll" in t for t in targets),
                         f"extra_libraries 里又混进了 d3d11.dll（会与 XXMI 自带注入重复）: {targets}")

    def test_repair_reuses_the_launch_chain(self) -> None:
        """「修复」必须和一键启动一样能自愈（2026-10-01 issue #6 的回归测试）。

        那条 issue 里用户反复点「修复」，每次只拿到
        「写入 XXMI 注入库失败: 找不到 XXMI Launcher Config.json」，界面停在
        「修复后仍有缺失」—— 因为修复链路**既不做 bootstrap_xxmi_config（XXMI 配置是它
        首次运行时才生成的），也不调 initialize.ensure_all（随包资产、ReShade.ini 都补不了）**。
        这里把三条链路的调用顺序钉住。
        """
        calls: list[str] = []

        def fake_bootstrap(config, **kwargs):
            calls.append("bootstrap")
            return {"ok": True, "created": True, "message": "已生成"}

        def fake_initialize(config, **kwargs):
            calls.append("initialize")
            return {"actions": ["补齐 DLSS5 运行库"], "warnings": []}

        def fake_configure(config, enabled=True):
            calls.append("injection")
            return {"extra_libraries": ["d3d12.dll"]}

        from endfieldmodcontroller import initialize, launcher

        with mock.patch.object(runtime_deps, "ensure_all", lambda config: []), \
                mock.patch.object(activation, "stage_and_prepare", lambda *a, **k: None), \
                mock.patch.object(launcher, "bootstrap_xxmi_config", fake_bootstrap), \
                mock.patch.object(launcher, "configure_dlss5_injection", fake_configure), \
                mock.patch.object(initialize, "ensure_all", fake_initialize):
            result = integrity.repair_integrity(self.config)

        self.assertIn("bootstrap", calls)
        self.assertIn("initialize", calls)
        self.assertIn("injection", calls)
        self.assertLess(calls.index("bootstrap"), calls.index("injection"),
                        "写注入库之前必须先让 XXMI 生成配置文件")
        self.assertTrue(any("XXMI" in message for message in result["messages"]))

    def test_repair_prepares_xxmi_signing_key_before_writing(self) -> None:
        """「修复」必须和一键启动一样**先补 XXMI 签名密钥**（2026-10-02 反馈者诊断包定位）。

        反馈者机器上 `Security.user_signature` 长度是 **0**（正常环境 140）：`bootstrap_xxmi_config`
        拉起 XXMI 生成配置后是**强杀**它的 —— 密钥对落了盘、`user_signature` 没落盘；而
        `sign_xxmi_setting()` 只在**私钥文件缺失**时才补这一对，私钥已存在 → 永远补不上。
        后果：修复写进去的 `extra_libraries_signature` 会在 XXMI 下次启动时被它自己重新
        生成的密钥作废 → 弹「Failed to validate unsecure settings!」→ 点 Reset 注入列表清空
        → 用户看到「点多少次修复都还是不行」。所以这一步必须排在**任何配置写入之前**。
        """
        calls: list[str] = []
        config_path = self.xxmi_root / "XXMI Launcher Config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("{}", encoding="utf-8")

        from endfieldmodcontroller import initialize, launcher, reshade_integration

        def fake_key(path):
            calls.append("signing_key")
            return {"ok": True, "generated": True, "message": "已生成 XXMI 签名密钥并写入 user_signature"}

        def fake_configure(config, enabled=True):
            calls.append("injection")
            return {"extra_libraries": ["d3d12.dll"]}

        with mock.patch.object(runtime_deps, "ensure_all", lambda config: []), \
                mock.patch.object(activation, "stage_and_prepare", lambda *a, **k: None), \
                mock.patch.object(launcher, "bootstrap_xxmi_config",
                                  lambda config, **k: {"ok": True, "created": False, "message": ""}), \
                mock.patch.object(reshade_integration, "xxmi_config_path",
                                  lambda launcher_path: config_path), \
                mock.patch.object(launcher, "ensure_xxmi_signing_key", fake_key), \
                mock.patch.object(launcher, "configure_dlss5_injection", fake_configure), \
                mock.patch.object(initialize, "ensure_all",
                                  lambda config, **k: {"actions": [], "warnings": []}):
            result = integrity.repair_integrity(self.config)

        self.assertIn("signing_key", calls, result["messages"])
        self.assertLess(calls.index("signing_key"), calls.index("injection"),
                        "签名密钥必须在写注入库之前就位")
        self.assertTrue(any("签名密钥" in message for message in result["messages"]),
                        result["messages"])

    def test_repair_failure_of_injection_is_reported_not_swallowed(self) -> None:
        """注入库写不进去时必须留在消息里（用户要能在界面上看到是哪一步失败）。"""
        from endfieldmodcontroller import initialize, launcher

        def boom(config, enabled=True):
            raise RuntimeError("找不到 XXMI Launcher Config.json")

        with mock.patch.object(runtime_deps, "ensure_all", lambda config: []), \
                mock.patch.object(activation, "stage_and_prepare", lambda *a, **k: None), \
                mock.patch.object(launcher, "bootstrap_xxmi_config",
                                  lambda config, **k: {"ok": True, "created": False, "message": ""}), \
                mock.patch.object(launcher, "configure_dlss5_injection", boom), \
                mock.patch.object(initialize, "ensure_all",
                                  lambda config, **k: {"actions": [], "warnings": []}):
            result = integrity.repair_integrity(self.config)

        self.assertTrue(any("找不到 XXMI Launcher Config.json" in message
                            for message in result["messages"]), result["messages"])


if __name__ == "__main__":
    unittest.main()
