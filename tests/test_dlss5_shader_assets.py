# SPDX-License-Identifier: GPL-3.0-or-later
"""DLSS5 的 shader / 贴图资产必须是**内容级**检查（2026-10-13，用户现场反馈）。

用户原话：「这个软件注入的（贴图）文件夹有问题，但是在这个软件上却显示完整，
导致一直排查不出来，应该有个 bug」。ReShade 日志两行铁证：

    ERROR | Failed to compile '...\\reshade-shaders\\Shaders\\DLSS5_Feed.fx':
            DLSS5_Feed.fx(60, 1): preprocessor error: could not open included file 'ReShade.fxh'
    ERROR | Source 'AreaLUT.png' for texture 'v_areaLUT' was not found in any of the texture
            search paths!

而生效目录里 `Shaders\\` / `Textures\\` **目录都在**，只是少了具体文件（或内容不是随包
那份）—— 旧判据只问"目录在不在 / 有没有文件"，于是永远显示"就绪"。

这里钉住三件事：① 缺文件要补；② **大小不符要重铺并留备份**（"存在 ≠ 正确"）；
③「完整性检查」按钮要报得出来，而且**不许**因此拦死启动。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from endfieldmodcontroller import api as api_mod
from endfieldmodcontroller import initialize, integrity

SHADER_FILES = {
    "ReShade.fxh": "// reshade\n",
    "ReShadeUI.fxh": "// ui\n",
    "Blending.fxh": "// blending\n",
    "DrawText.fxh": "// drawtext\n",
    "Macros.fxh": "// macros\n",
    "TriDither.fxh": "// dither\n",
    "DLSS5_Feed.fx": "// feed\n" + "// padding\n" * 40,
    "iMMERSE/MartysMods_LAUNCHPAD.fx": "// launchpad\n",
}
TEXTURE_FILES = {
    "AreaLUT.png": b"\x89PNG\r\n\x1a\n" + b"A" * 128,
    "Stage.png": b"\x89PNG\r\n\x1a\n" + b"B" * 256,
}


class Dlss5ShaderAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="mc-shader-assets-")
        root = Path(self._tmp.name)
        (root / "runtime").mkdir(parents=True, exist_ok=True)
        (root / "library").mkdir(parents=True, exist_ok=True)
        # 随包基准：`<数据根>/assets/dlss5/{shaders,textures}`
        for name, text in SHADER_FILES.items():
            path = root / "assets" / "dlss5" / "shaders" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for name, data in TEXTURE_FILES.items():
            path = root / "assets" / "dlss5" / "textures" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        cfg = root / "config.json"
        cfg.write_text(json.dumps({"data_root": "", "runtime_dir": "runtime",
                                   "library_dir": "library",
                                   "dlss5_dir": "runtime/dlss5",
                                   "dlss5_injection": True}, ensure_ascii=False),
                       encoding="utf-8")
        self.api = api_mod.EndfieldModControllerApi(str(cfg))
        self.config = self.api.config
        self.shader_root = Path(self.config.dlss5_path) / "reshade-shaders"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------------------------------------------------------------- 工具
    def _repair(self):
        report = initialize.Report()
        initialize._check_dlss5_shaders(self.config, report, None)      # noqa: SLF001
        rows = [c for c in report.to_dict()["checks"] if c["key"] == "dlss5:shader_deps"]
        return report, (rows[0] if rows else {})

    def _seed(self) -> None:
        self._repair()                       # 首轮：从随包基准铺出完整一份

    def _integrity_row(self) -> dict:
        report = integrity.check_integrity(self.config)
        rows = [c for c in report["checks"] if c["key"] == "dlss5_shader_assets"]
        self.assertTrue(rows, "完整性检查里必须有 dlss5_shader_assets 这一项")
        return rows[0]

    # ---------------------------------------------------------------- 缺失
    def test_seed_makes_everything_present(self):
        self._seed()
        for name in SHADER_FILES:
            self.assertTrue((self.shader_root / "Shaders" / name).is_file(), name)
        for name in TEXTURE_FILES:
            self.assertTrue((self.shader_root / "Textures" / name).is_file(), name)

    def test_missing_texture_is_restored(self):
        """⭐ 用户现场：`AreaLUT.png` 缺失（目录里还有别的贴图）—— 必须补回来。"""
        self._seed()
        (self.shader_root / "Textures" / "AreaLUT.png").unlink()
        _, row = self._repair()
        self.assertTrue((self.shader_root / "Textures" / "AreaLUT.png").is_file())
        self.assertTrue(row["ok"], row)

    def test_missing_include_header_is_restored(self):
        """ReShade 标准头缺失 ⇒ DLSS5_Feed.fx 编译失败（日志里那条）。"""
        self._seed()
        (self.shader_root / "Shaders" / "ReShade.fxh").unlink()
        _, row = self._repair()
        self.assertTrue((self.shader_root / "Shaders" / "ReShade.fxh").is_file())
        self.assertTrue(row["ok"], row)

    # ---------------------------------------------------------------- 内容不符
    def test_texture_with_wrong_content_is_replaced_and_backed_up(self):
        """★ **存在 ≠ 正确**：被截断/换过的贴图要备份后重铺。"""
        self._seed()
        bad = self.shader_root / "Textures" / "Stage.png"
        bad.write_bytes(b"broken")
        _, row = self._repair()
        self.assertEqual(bad.stat().st_size, len(TEXTURE_FILES["Stage.png"]))
        self.assertTrue(list(bad.parent.glob("Stage.png.mc.bak-*")), "重铺前必须留备份")
        self.assertTrue(row["ok"], row)

    def test_shader_with_wrong_size_is_replaced_and_backed_up(self):
        """⭐ 本机现场：生效目录里的 `DLSS5_Feed.fx` 是 5,342 B 旧版，随包是 52,600 B。"""
        self._seed()
        fx = self.shader_root / "Shaders" / "DLSS5_Feed.fx"
        fx.write_text("// old\n", encoding="utf-8")
        _, row = self._repair()
        # ⚠️ 比的是**基准文件的大小**，不是字符串长度：Windows 文本写入会把 `\n` 折成 `\r\n`，
        #    用 `len(text.encode())` 当期望值会差出若干个字节（这里踩过一次）。
        base = Path(self.config.base_dir) / "assets" / "dlss5" / "shaders" / "DLSS5_Feed.fx"
        self.assertEqual(fx.stat().st_size, base.stat().st_size)
        self.assertTrue(list(fx.parent.glob("DLSS5_Feed.fx.mc.bak-*")))
        self.assertTrue(row["ok"], row)

    # ---------------------------------------------------------------- 完整性检查
    def test_integrity_reports_missing_asset(self):
        self._seed()
        (self.shader_root / "Textures" / "AreaLUT.png").unlink()
        row = self._integrity_row()
        self.assertFalse(row["ok"])
        self.assertIn("AreaLUT.png", row["message"])
        self.assertFalse(row["critical"], "缺贴图不该拦死启动")
        report = integrity.check_integrity(self.config)
        self.assertNotIn("dlss5_shader_assets", [item["key"] for item in report["failures"]])

    def test_integrity_reports_mismatched_content(self):
        self._seed()
        (self.shader_root / "Shaders" / "ReShade.fxh").unlink()
        row = self._integrity_row()
        self.assertFalse(row["ok"])
        self.assertIn("ReShade.fxh", row["message"])

    def test_integrity_is_green_after_repair(self):
        self._seed()
        (self.shader_root / "Textures" / "Stage.png").unlink()
        self._repair()
        row = self._integrity_row()
        self.assertTrue(row["ok"], row)

    def test_switch_off_skips_the_check(self):
        """DLSS5 关着 ⇒ 这项不该出现在完整性检查里（与其它 dlss5 项同一套规矩）。"""
        self.config.dlss5_injection = False
        report = integrity.check_integrity(self.config)
        self.assertFalse([c for c in report["checks"] if c["key"] == "dlss5_shader_assets"])


if __name__ == "__main__":
    unittest.main()
