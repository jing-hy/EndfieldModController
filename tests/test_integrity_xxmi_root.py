# SPDX-License-Identifier: AGPL-3.0-only
"""完整性检查必须看「运行期真正在用的那份 XXMI」。

2026-11-28 反馈（诊断包 diagnostics-20261128-175808）：
    用户配了外部 XXMI（D:/XXMI）与外部 EFMI（D:/EFMI），但 use_builtin_runtime 还开着。
    旧实现第一句就是 if use_builtin_runtime: return builtin_runtime_path / "XXMI"，
    于是检查去看**内置那份副本**（这台机器从来没用过它）⇒

        launch failed: 完整性检查失败: XXMI Libraries / 3dmloader.dll;
        XXMI Libraries / d3d11.dll; XXMI Libraries / d3dcompiler_47.dll;
        EFMI Core / main.ini; EFMI d3dx.ini

    ⇒ **一键启动被彻底拦死**，而运行期（launcher.*）用的明明是那个外部 XXMI。

钉两件事：① 根目录按 launcher 推导；② EFMI 用 config.efmi_dir（importer 可以把它指到别处）。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import integrity
from endfieldmodcontroller.config import AppConfig


def _external_setup(tmp_path: Path) -> AppConfig:
    external = tmp_path / "XXMI"
    (external / "Resources" / "Bin").mkdir(parents=True)
    launcher = external / "Resources" / "Bin" / "XXMI Launcher.exe"
    launcher.write_bytes(b"exe")
    packages = external / "Resources" / "Packages" / "XXMI"
    packages.mkdir(parents=True)
    for name in ("3dmloader.dll", "d3d11.dll", "d3dcompiler_47.dll"):
        (packages / name).write_bytes(b"dll")

    efmi = tmp_path / "EFMI"          # 注意：**不在** XXMI 目录下（importer 指到别处）
    (efmi / "Core" / "EFMI").mkdir(parents=True)
    (efmi / "Core" / "EFMI" / "main.ini").write_text("x", encoding="utf-8")
    (efmi / "d3dx.ini").write_text("x", encoding="utf-8")
    (efmi / "Mods").mkdir()
    (efmi / "d3d11.dll").write_bytes(b"dll")

    return AppConfig(
        library_dir=str(tmp_path / "library"),
        runtime_dir=str(tmp_path / "runtime"),
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
        use_builtin_runtime=True,          # 关键：内置开关开着，但实际用的是外部那份
        xxmi_launcher=str(launcher),
        staging_mods_dir=str(efmi / "Mods"),
        dlss5_injection=False,
        efmi_injection=True,
        reshade_disabled=True,
    )


def test_xxmi_root_follows_the_configured_launcher(tmp_path: Path) -> None:
    config = _external_setup(tmp_path)
    assert integrity.xxmi_root(config) == tmp_path / "XXMI", (
        "内置开关开着时仍要按 launcher 推导 —— 否则检查的是没人用的那份副本")


def test_check_integrity_passes_on_a_valid_external_setup(tmp_path: Path) -> None:
    config = _external_setup(tmp_path)
    report = integrity.check_integrity(config)
    failing = {str(item.get("key") or "") for item in report["failures"]}
    # 只看这次修复涉及的几项；控制器 ini/actions 等与本次无关，测试环境里本来就没有
    assert not any(key.startswith("xxmi_libs_") for key in failing), failing
    assert "efmi_main" not in failing, failing
    assert "efmi_d3dx" not in failing, failing
