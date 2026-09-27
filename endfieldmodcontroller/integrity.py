"""Runtime integrity checks and repair for the launch flow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import activation, reshade_integration, runtime_deps
from .config import AppConfig


@dataclass
class Check:
    key: str
    ok: bool
    path: str
    message: str
    critical: bool = True


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def xxmi_root(config: AppConfig) -> Path | None:
    if config.use_builtin_runtime:
        return config.builtin_runtime_path / "XXMI"
    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        return None
    candidates = [
        launcher.parent.parent.parent,
        launcher.parent.parent,
        launcher.parent,
    ]
    for candidate in candidates:
        if (candidate / "Resources" / "Bin").is_dir() or (candidate / "EFMI").is_dir():
            return candidate
    return None


def check_integrity(config: AppConfig) -> dict:
    checks: list[Check] = []

    def add(key: str, path: Path, ok: bool, message: str, critical: bool = True) -> None:
        checks.append(Check(key, bool(ok), str(path), message, critical))

    launcher = config.xxmi_launcher_path
    add("xxmi_launcher", launcher or Path("<unset>"), launcher is not None and launcher.is_file(), "XXMI Launcher.exe")

    root = xxmi_root(config)
    if root is None:
        checks.append(Check("xxmi_root", False, "<unknown>", "无法定位 XXMI 根目录"))
    else:
        for name in ("3dmloader.dll", "d3d11.dll", "d3dcompiler_47.dll"):
            path = root / "Resources" / "Packages" / "XXMI" / name
            add(f"xxmi_libs_{name}", path, path.is_file(), f"XXMI Libraries / {name}")
        efmi_root = root / "EFMI"
        add("efmi_main", efmi_root / "Core" / "EFMI" / "main.ini", (efmi_root / "Core" / "EFMI" / "main.ini").is_file(), "EFMI Core / main.ini")
        add("efmi_d3dx", efmi_root / "d3dx.ini", (efmi_root / "d3dx.ini").is_file(), "EFMI d3dx.ini")
        add("efmi_mods", efmi_root / "Mods", (efmi_root / "Mods").is_dir(), "EFMI Mods directory")

    existing_reshade = reshade_integration.detect_existing_reshade(config)
    if existing_reshade is not None:
        # 本方案不使用游戏目录 ReShade（唯一底座由 XXMI 注入），只提示，不算失败。
        add(
            "game_reshade_present",
            Path(str(existing_reshade.get("ini") or existing_reshade.get("game_dir"))),
            False,
            "游戏目录仍有 ReShade —— 建议用「清理游戏目录注入」停放，避免两个 ReShade 抢 hook",
            critical=False,
        )

    if config.dlss5_injection:
        dlss5_dll = config.dlss5_dll_path
        add("dlss5_dll", dlss5_dll, dlss5_dll.is_file(), "DLSS5 ReShade 底座 d3d12.dll")
        dlss5_ini = config.dlss5_ini_path
        add("dlss5_ini", dlss5_ini, dlss5_ini.is_file(), "DLSS5 ReShade.ini（含 [endfield-enhancer] 段）")
        enhancer = config.dlss5_enhancer_addon_path
        add("dlss5_enhancer_addon", enhancer, enhancer.is_file(), "第一人称插件 renodx-endfield-enhancer.addon64")
        efmi_dll = config.efmi_dll_path
        add("efmi_dll", efmi_dll or Path("<unset>"), efmi_dll is not None and efmi_dll.is_file(), "EFMI d3d11.dll（注入用）")

    add("controller_ini", config.controller_dir / "controller.ini", (config.controller_dir / "controller.ini").is_file(), "controller.ini")
    add("controller_actions", config.controller_dir / "actions.tsv", (config.controller_dir / "actions.tsv").is_file(), "controller actions.tsv")

    critical_failures = [check for check in checks if check.critical and not check.ok]
    return {
        "ok": not critical_failures,
        "checks": [check.__dict__ for check in checks],
        "failures": [check.__dict__ for check in critical_failures],
        "existing_reshade": existing_reshade,
    }


def repair_integrity(config: AppConfig, log: Callable[[str], None] | None = None) -> dict:
    messages: list[str] = []

    def note(message: str) -> None:
        messages.append(message)
        if log:
            log(message)

    if config.use_builtin_runtime:
        note("重新检查/安装内置 XXMI + XXMI Libraries + EFMI")
        for result in runtime_deps.ensure_all(config):
            note(f"{result.key}: {result.status} {result.message}")
    else:
        note("当前使用外部 XXMI，缺失的 XXMI Libraries/EFMI 需要重新安装或切换为内置运行环境")

    note("重新生成控制器和 staging")
    activation.stage_and_prepare(
        config.library_path,
        config.staging_mods_path,
        config.runtime_path,
        selected_ids=config.selected_mods,
    )
    if config.dlss5_injection:
        note("重新写入 XXMI 注入库（DLSS5 d3d12.dll + EFMI d3d11.dll）")
        try:
            from . import launcher as launcher_mod

            result = launcher_mod.configure_dlss5_injection(config, enabled=True)
            note("注入库: " + " + ".join(result.get("extra_libraries", [])))
        except Exception as exc:  # noqa: BLE001
            note(f"写入 XXMI 注入库失败: {exc}")
    return {"messages": messages, "integrity": check_integrity(config)}
