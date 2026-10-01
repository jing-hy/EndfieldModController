"""设备信息（`deviceinfo`）的离线测试。

用户 2026-10-01 要求：「下一版本要在日志包中包含用户设备型号，判断是不是显卡不支持」。
这里只测"读得到、读不到都不炸"以及几条关键判词 —— 真机信息不参与断言。
"""
from __future__ import annotations

import unittest

from endfieldmodcontroller import deviceinfo


class DeviceInfoTests(unittest.TestCase):
    def test_collect_returns_expected_fields(self) -> None:
        info = deviceinfo.collect(refresh=True)
        for field in ("cpu", "cpu_cores", "memory_mb", "os", "adapters",
                      "has_nvidia", "has_rtx", "dlss_verdict"):
            self.assertIn(field, info)
        self.assertIsInstance(info["adapters"], list)
        self.assertIsInstance(info["dlss_verdict"], str)
        self.assertTrue(info["dlss_verdict"])

    def test_summary_lines_shape(self) -> None:
        lines = deviceinfo.summary_lines()
        self.assertTrue(any("设备与显卡" in line for line in lines), lines)
        self.assertTrue(any(line.startswith("CPU") for line in lines), lines)
        self.assertTrue(any(line.startswith("显示适配器") for line in lines), lines)
        self.assertTrue(any(line.startswith("DLSS5 前提") for line in lines), lines)

    def test_as_text_starts_without_blank_line(self) -> None:
        text = deviceinfo.as_text()
        self.assertFalse(text.startswith("\n"))
        self.assertIn("DLSS5 前提", text)

    def test_verdict_branches(self) -> None:
        self.assertIn("RTX", deviceinfo._verdict("nvidia geforce rtx 5080"))
        gtx = deviceinfo._verdict("nvidia geforce gtx 1660 super")
        self.assertIn("不是 RTX", gtx)
        other = deviceinfo._verdict("amd radeon(tm) graphics")
        self.assertIn("未检测到 NVIDIA", other)

    def test_os_text_corrects_windows_11_product_name(self) -> None:
        # 注册表在 Windows 11 上仍写 "Windows 10"，必须按 build 号纠正
        text = deviceinfo._os_text(
            {"os_name": "Windows 10 Pro", "os_version": "24H2", "os_build": "26100"})
        self.assertIn("Windows 11", text)
        self.assertIn("build 26100", text)

    def test_os_text_keeps_real_windows_10(self) -> None:
        text = deviceinfo._os_text(
            {"os_name": "Windows 10 Pro", "os_version": "22H2", "os_build": "19045"})
        self.assertIn("Windows 10", text)

    def test_reg_readers_never_raise(self) -> None:
        import winreg

        missing = r"SOFTWARE\EndfieldModControllerNoSuchKey"
        self.assertEqual(deviceinfo._reg_str(winreg.HKEY_LOCAL_MACHINE, missing, "x"), "")
        self.assertEqual(deviceinfo._reg_qword_mb(winreg.HKEY_LOCAL_MACHINE, missing, "x"), 0)


if __name__ == "__main__":
    unittest.main()
