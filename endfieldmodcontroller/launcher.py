"""Launch orchestration and ReShade runtime preparation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import activation
from . import core
from . import dependencies
from . import diagnostics
from . import integrity
from . import runtime_deps
from .config import AppConfig
from . import injector
from . import reshade_integration


class LaunchError(RuntimeError):
    pass


def _copy_if_changed(src: Path, dst: Path) -> bool:
    """Copy a runtime file only when content differs.

    This avoids unnecessary writes/locks when the destination is already the
    current version, which is the common case on repeated launches.
    """
    if not src.is_file():
        return False
    if dst.is_file():
        try:
            if src.stat().st_size == dst.stat().st_size:
                src_digest = hashlib.sha256(src.read_bytes()).hexdigest()
                dst_digest = hashlib.sha256(dst.read_bytes()).hexdigest()
                if src_digest == dst_digest:
                    return False
        except OSError:
            pass
    shutil.copy2(src, dst)
    return True


def _built_addon_path() -> Path | None:
    return reshade_integration.built_addon_path()


def _multi_loader_path() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dist" / "migoto_loader.exe",
        root / "scripts" / "migoto_multi_loader.exe",
        root / "runtime" / "migoto" / "loader_new.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _legacy_migoto_source() -> Path | None:
    """Locate the known-working Endfield 3DMigoto v1.4.x package.

    The first working installation used a standalone 3DMigoto package whose
    d3dx.ini contains the original ``$costume_mods`` / ShaderOverrideCharacter
    logic.  EFMI v1.3.x from a newer XXMI package parses the mods but does not
    apply the same costume override path, so prefer the legacy framework when
    it is present.
    """
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "runtime" / "builtin" / "XXMI" / "EFMI",
        root / "runtime" / "migoto",
    ]
    for candidate in candidates:
        if not (candidate / "d3d11.dll").is_file() or not (candidate / "d3dx.ini").is_file():
            continue
        try:
            text = (candidate / "d3dx.ini").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "$costume_mods" in text and "[ShaderOverrideCharacter]" in text:
            return candidate
    return None


def _has_legacy_migoto_config(d3dx_ini: Path) -> bool:
    try:
        text = d3dx_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "$costume_mods" in text and "[ShaderOverrideCharacter]" in text


def _is_legacy_framework_config(d3dx_ini: Path) -> bool:
    try:
        text = d3dx_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    lower = text.lower()
    return (
        "$costume_mods" in text
        and "[shaderoverridecharacter]" in lower
        and not ("core" in lower and "efmi" in lower and "main.ini" in lower)
    )


def _has_efmi_core_config(d3dx_ini: Path) -> bool:
    try:
        text = d3dx_ini.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return ("core" in text and "efmi" in text and "main.ini" in text) or ("core/efmi/main.ini" in text)


def _bootstrap_path() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dist" / "mc_bootstrap.dll",
        root / "scripts" / "mc_bootstrap.dll",
        root / "runtime" / "builtin" / "XXMI" / "EFMI" / "mc_bootstrap.dll",
        root / "runtime" / "migoto" / "mc_bootstrap.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _running_process_names(names: list[str]) -> list[str]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
        )
    except Exception:
        return []
    running: list[str] = []
    lower_names = {name.lower(): name for name in names}
    for line in result.stdout.splitlines():
        stripped = line.strip().strip('"').lower()
        for low, original in lower_names.items():
            if stripped.startswith(low):
                running.append(original)
                break
    return running


def _stop_locked_files_processes(config: AppConfig) -> list[str]:
    """Kill stale loader/game processes before touching runtime files.

    Windows keeps loaded DLLs/EXEs locked, so replacing runtime/migoto files or
    deleting the old Mods staging while a previous loader/game is still running
    raises WinError 32.  Try non-elevated taskkill first; if the processes are
    elevated, request a single elevated cleanup and wait for it to finish.
    """
    names = [
        "migoto_loader2.exe",
        "migoto_loader.exe",
        "loader.exe",
        "loader_new.exe",
        "3dmloader.exe",
        "3DMigoto Loader.exe",
        "3DMigotoLoader.exe",
        "Endfield.exe",
    ]
    running = _running_process_names(names)
    if not running:
        return []
    _append_log(config, f"检测到残留进程，先结束: {', '.join(running)}")
    # Best effort without UAC.
    for name in running:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        except Exception:
            pass
    time.sleep(0.5)
    running = _running_process_names(names)
    if not running:
        return []

    runtime = config.runtime_path
    runtime.mkdir(parents=True, exist_ok=True)
    script = runtime / "stop_migoto_processes.cmd"
    marker = runtime / "stop_migoto_processes.done"
    try:
        if marker.exists():
            marker.unlink()
    except OSError:
        pass
    lines = [
        "@echo off",
        "taskkill /F /IM migoto_loader2.exe >nul 2>&1",
        "taskkill /F /IM migoto_loader.exe >nul 2>&1",
        "taskkill /F /IM loader.exe >nul 2>&1",
        "taskkill /F /IM loader_new.exe >nul 2>&1",
        "taskkill /F /IM Endfield.exe >nul 2>&1",
        f'> "{marker}" echo done',
    ]
    script.write_text(chr(10).join(lines) + chr(10), encoding="utf-8", newline=chr(10))
    _spawn_elevated(config, str(script), str(script.parent), show_window=0)

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if marker.is_file():
            break
        if not _running_process_names(names):
            break
        time.sleep(0.5)
    running = _running_process_names(names)
    try:
        if marker.exists():
            marker.unlink()
    except OSError:
        pass
    if running:
        raise LaunchError(
            "旧游戏或 loader 进程仍占用 runtime 文件（WinError 32）。"
            "请手动关闭 Endfield.exe / migoto_loader2.exe 后重试。"
        )
    return running


def _ensure_reshade_disabled_addons(game_dir: Path) -> None:
    """Disable only RenoDX/DLSS add-on while keeping Endfield Enhancer enabled.

    EndfieldModController and the user's ``终末地EE.addon64`` are expected to coexist.
    RenoDX/DLSS is the known conflicting add-on in the current mixed setup, so
    only that one is listed in DisabledAddons.  Files are never deleted.
    """
    disabled_value = "renodx-dlss.addon64"
    ini_path = game_dir / "ReShade.ini"
    if not ini_path.is_file():
        ini_path.write_text("[ADDON]" + chr(10) + "DisabledAddons=" + disabled_value + chr(10), encoding="utf-8")
        return
    lines = ini_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: list[str] = []
    in_addon = False
    inserted = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_addon and not inserted:
                out.append("DisabledAddons=" + disabled_value)
                inserted = True
            in_addon = stripped.lower() == "[addon]"
            out.append(line)
            continue
        if in_addon and stripped.lower().startswith("loadfromdllmain"):
            continue
        if in_addon and stripped.lower().startswith("disabledaddons"):
            out.append("DisabledAddons=" + disabled_value)
            inserted = True
            continue
        out.append(line)
    if in_addon and not inserted:
        out.append("DisabledAddons=" + disabled_value)
    ini_path.write_text(chr(10).join(out) + chr(10), encoding="utf-8")


def prepare_reshade_runtime(config: AppConfig, controller_dir: Path) -> dict[str, Any]:
    """Prepare runtime/reshade without writing anything into the game dir."""
    reshade_dir = config.reshade_runtime_path
    addons_dir = reshade_dir / "Addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    (reshade_dir / "reshade-shaders" / "Shaders").mkdir(parents=True, exist_ok=True)
    (reshade_dir / "reshade-shaders" / "Textures").mkdir(parents=True, exist_ok=True)

    built_addon = _built_addon_path()
    installed_addon = addons_dir / "endfieldmodcontroller.addon"
    if getattr(config, "inject_reshade_ui", True):
        if built_addon and built_addon.resolve() != installed_addon.resolve():
            shutil.copy2(built_addon, installed_addon)
    else:
        disabled_addon = installed_addon.with_name(installed_addon.name + ".disabled")
        if installed_addon.is_file():
            if disabled_addon.exists():
                disabled_addon.unlink()
            installed_addon.rename(disabled_addon)

    actions_tsv = controller_dir / "actions.tsv"
    if actions_tsv.is_file():
        shutil.copy2(actions_tsv, reshade_dir / "actions.tsv")
    (reshade_dir / "user_ini_path.txt").write_text(str(config.user_ini_path), encoding="utf-8", newline="\n")

    ini_text = "\n".join([
        "[ADDON]",
        "AddonPath=Addons",
        "",
        "[GENERAL]",
        "EffectSearchPaths=reshade-shaders\\Shaders\\**",
        "TextureSearchPaths=reshade-shaders\\Textures\\**",
        "PresetPath=ReShadePreset.ini",
        "",
    ])
    (reshade_dir / "ReShade.ini").write_text(ini_text, encoding="utf-8", newline="\n")
    return {
        "reshade_dir": str(reshade_dir),
        "addon": str(installed_addon) if installed_addon.is_file() else "",
        "actions_tsv": str(reshade_dir / "actions.tsv"),
        "user_ini_path": str(config.user_ini_path),
    }


def sign_xxmi_setting(config_path: Path, value: str) -> str:
    """用 XXMI 自己的私钥给「危险设置」的值签名。

    XXMI 把 ``extra_libraries`` / ``unsafe_mode`` / ``custom_launch`` 等标为
    *unsecure settings*：值本身 + 一个 ``*_signature``。校验不过时 XXMI 会弹
    「Failed to validate unsecure settings! [Reset] [Keep]」——点 Reset 会**清空设置**
    （注入列表没了 → ReShade 不注入 → 游戏闪退），所以程序改写后必须自己补签名。

    实测算法：ECDSA(P-384, SHA-256)，待签内容 = 字段值原样，签名 = base64(DER)。
    密钥文件 ``Resources\\Security\\private_key.der`` 是 **base64 文本包装的 DER**。
    """
    try:
        import base64

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:  # pragma: no cover
        raise LaunchError("缺少 cryptography，无法为 XXMI 设置签名（pip install cryptography）") from exc
    key_file = config_path.parent / "Resources" / "Security" / "private_key.der"
    if not key_file.is_file():
        raise LaunchError(f"找不到 XXMI 私钥: {key_file}")
    der = base64.b64decode(key_file.read_bytes().strip())
    key = serialization.load_der_private_key(der, None)
    signature = key.sign(value.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


# 同一个 ReShade 底座（d3d12.dll）下挂的两组 addon。
# 一个进程只能有一个 ReShade 底座，所以两者无法用两个 dll 分开注入；
# 正确的"拆开"方式是各自启停 addon 文件——ReShade 只加载底座**根目录**里的
# *.addon64，把文件移进 _disabled 子目录就等于停用。
DLSS5_ADDON_GLOBS = ("renodx-dlss5*.addon64", "dlss5-feed.addon64", "trans-zh.addon64", "translations.txt")
FIRSTPERSON_ADDON_GLOBS = ("renodx-endfield-enhancer.addon64",)
ADDON_DISABLED_DIR = "_disabled"


def set_component_addons(config: AppConfig, component: str, enabled: bool) -> dict[str, Any]:
    """单独启停 DLSS5 或第一人称插件（移动 addon 文件，可逆）。

    component: "dlss5" | "firstperson"
    """
    globs = DLSS5_ADDON_GLOBS if component == "dlss5" else FIRSTPERSON_ADDON_GLOBS
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR
    disabled.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    if enabled:
        for pattern in globs:
            for path in sorted(disabled.glob(pattern)):
                target = base / path.name
                if target.exists():
                    continue
                shutil.move(str(path), str(target))
                moved.append(path.name)
    else:
        for pattern in globs:
            for path in sorted(base.glob(pattern)):
                target = disabled / path.name
                if target.exists():
                    continue
                shutil.move(str(path), str(target))
                moved.append(path.name)
    return {"ok": True, "component": component, "enabled": enabled, "moved": moved}


def component_addon_status(config: AppConfig) -> dict[str, Any]:
    """两个插件的 addon 是否在位。"""
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR

    def probe(globs: tuple[str, ...]) -> dict[str, Any]:
        active: list[str] = []
        inactive: list[str] = []
        for pattern in globs:
            active.extend(p.name for p in base.glob(pattern))
            inactive.extend(p.name for p in disabled.glob(pattern))
        return {"active": sorted(active), "disabled": sorted(inactive), "on": bool(active)}

    return {"dlss5": probe(DLSS5_ADDON_GLOBS), "firstperson": probe(FIRSTPERSON_ADDON_GLOBS)}


def dlss5_injection_targets(config: AppConfig) -> list[str]:
    """本方案写进 XXMI 注入库的内容：DLSS5 的 d3d12.dll + EFMI 的 d3d11.dll。

    视频方案（BV1XMh76UEA5）实测有效的最小集合就是这两条：XXMI 启动游戏时把
    它们注入进程，于是唯一一个 ReShade 底座（DLSS5 的 d3d12.dll）同时带上
    RenoDX-DLSS5 与 Endfield Enhancer 两个插件，EFMI 负责服装 Mod，互不抢 hook。
    """
    targets: list[str] = []
    dll = config.dlss5_dll_path
    if not dll.is_file():
        raise LaunchError(f"DLSS5 ReShade 底座不存在: {dll}")
    # 两个插件（DLSS5 / 第一人称）都关掉时就不必注入底座了
    want_base = bool(getattr(config, "dlss5_addon_enabled", True)
                    or getattr(config, "firstperson_addon_enabled", True))
    if want_base:
        targets.append(str(dll))
    if getattr(config, "efmi_injection", True):
        efmi = config.efmi_dll_path
        if efmi is not None and efmi.is_file():
            targets.append(str(efmi))
    # 乳摇：可选用「注入 sbm.dll」的方式（config.secondary_motion_dll 指向短路径下的
    # sbm.dll）。这样游戏目录不用替换 d3dcompiler_47.dll / vulkan-1.dll，
    # 避免和 ReShade/EFMI 抢 D3D 调用链（proxy 方式实测 65 秒崩）。
    sbm_setting = str(getattr(config, "secondary_motion_dll", "") or "").strip()
    if sbm_setting and getattr(config, "secondary_motion_injection", False):
        sbm = config.resolve_path(sbm_setting)
        if sbm.is_file():
            targets.append(str(sbm))
    return targets


def configure_dlss5_injection(config: AppConfig, enabled: bool = True) -> dict[str, Any]:
    """开/关 DLSS5 注入：改写 XXMI 的 EFMI extra_libraries（可回滚）。

    开 = 注入 d3d12.dll（DLSS5 + 第一人称 + 服装 Mod 三件套齐活）
    关 = 清空注入库（只跑服装 Mod，ReShade/DLSS5 不加载）
    """
    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        raise LaunchError("XXMI Launcher 路径未配置")
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        raise LaunchError("找不到 XXMI Launcher Config.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    importer = data.setdefault("Importers", {}).setdefault("EFMI", {}).setdefault("Importer", {})
    backup = config_path.with_suffix(config_path.suffix + ".mc.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    if enabled:
        targets = dlss5_injection_targets(config)
        importer["extra_libraries_enabled"] = True
        importer["extra_libraries"] = "\n".join(targets)
    else:
        targets = []
        importer["extra_libraries_enabled"] = False
        importer["extra_libraries"] = ""
    # 同步签名：不然 XXMI 判定为 unsecure setting 会弹 Reset/Keep，点 Reset 就清空注入列表
    importer["extra_libraries_signature"] = sign_xxmi_setting(config_path, importer["extra_libraries"])
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    config.dlss5_injection = enabled
    config.reshade_injection = "xxmi_extra" if enabled else "none"
    config.save()
    _append_log(config, f"DLSS5 注入 {'开启' if enabled else '关闭'}: {targets or '(注入库已清空)'}")
    return {
        "ok": True,
        "enabled": enabled,
        "config_path": str(config_path),
        "backup": str(backup),
        "extra_libraries": targets,
    }


def dlss5_injection_status(config: AppConfig) -> dict[str, Any]:
    """当前 DLSS5/第一人称注入状态，供 UI 与自检使用。"""
    launcher = config.xxmi_launcher_path
    status: dict[str, Any] = {
        "xxmi_launcher": str(launcher) if launcher else "",
        "dlss5_dir": str(config.dlss5_path),
        "dlss5_dll": str(config.dlss5_dll_path),
        "dlss5_dll_exists": config.dlss5_dll_path.is_file(),
        "enhancer_addon_exists": config.dlss5_enhancer_addon_path.is_file(),
        "efmi_dll": str(config.efmi_dll_path or ""),
        "config_path": "",
        "extra_libraries": "",
        "enabled": False,
        "has_dlss5": False,
    }
    if launcher is None:
        return status
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        return status
    status["config_path"] = str(config_path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        importer = data.get("Importers", {}).get("EFMI", {}).get("Importer", {})
        libs = str(importer.get("extra_libraries") or "")
        status["extra_libraries"] = libs
        status["enabled"] = bool(importer.get("extra_libraries_enabled")) and bool(libs.strip())
        status["has_dlss5"] = str(config.dlss5_dll_path).lower() in libs.lower()
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)
    return status


def ensure_injections(config: AppConfig) -> dict[str, Any]:
    """一键启动前的完整自检。

    分工：
      * **XXMI 负责的注入**（进程启动时把 d3d12.dll / d3d11.dll 注进游戏）不在检查范围内，
        这里只保证「XXMI 注入库」这个配置写对了。
      * **文件层面的初始化**全部交给 ``initialize.ensure_all``：DLSS5 目录内容、
        ReShade.ini 与 [endfield-enhancer] 段、游戏目录 nvngx 运行库、控制器文件、
        Mod staging、乳摇注入 —— 缺什么补什么。
    """
    actions: list[str] = []
    warnings: list[str] = []

    # 先按两个开关同步 addon 的启停（同一底座下的 DLSS5 / 第一人称各自独立）
    status = component_addon_status(config)
    for component, key, label in (
        ("dlss5", "dlss5_addon_enabled", "DLSS5 神经渲染"),
        ("firstperson", "firstperson_addon_enabled", "第一人称 Endfield Enhancer"),
    ):
        want = bool(getattr(config, key, True))
        if bool(status[component]["on"]) != want:
            try:
                moved = set_component_addons(config, component, want)
                detail = ", ".join(moved["moved"]) or "(已一致)"
                actions.append(f"{label} {'启用' if want else '停用'}: {detail}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"切换 {label} 失败: {exc}")

    if config.dlss5_injection:
        try:
            injection = configure_dlss5_injection(config, enabled=True)
            actions.append("XXMI 注入库: " + " + ".join(injection["extra_libraries"]))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"写入 XXMI 注入库失败: {exc}")
    else:
        # 关闭时必须主动清空，否则会保留上一次写进去的 DLL（滑块看着关了、实际还在注入）
        try:
            configure_dlss5_injection(config, enabled=False)
            actions.append("XXMI 注入库已清空（DLSS5 注入关闭）")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"清空 XXMI 注入库失败: {exc}")

    from . import initialize

    report = initialize.ensure_all(config, log=lambda message: _append_log(config, message))
    actions.extend(report.get("actions", []))
    warnings.extend(report.get("warnings", []))

    for action in actions:
        _append_log(config, f"注入自检: {action}")
    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "initialize": report,
    }


def configure_xxmi_extra_libraries(config: AppConfig) -> dict[str, Any]:
    """Add the ReShade DLL to XXMI's EFMI extra_libraries list.

    XXMI validates this setting with a local signature.  The function writes the
    JSON and creates a backup; the first launch may show XXMI's own
    "unsecure setting" prompt where the user can choose Keep once.
    """
    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        raise LaunchError("XXMI Launcher path is not configured")
    reshade_dll = config.reshade_dll_path
    if reshade_dll is None or not reshade_dll.is_file():
        raise LaunchError("ReShade DLL path is not configured")
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        raise LaunchError("XXMI Launcher Config.json was not found next to XXMI Launcher")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    importer = data.setdefault("Importers", {}).setdefault("EFMI", {}).setdefault("Importer", {})
    existing = [line.strip() for line in str(importer.get("extra_libraries") or "").splitlines() if line.strip()]
    reshade_path = str(reshade_dll)
    if reshade_path not in existing:
        existing.append(reshade_path)
    importer["extra_libraries_enabled"] = True
    importer["extra_libraries"] = "\n".join(existing)
    backup = config_path.with_suffix(config_path.suffix + ".mc.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    return {
        "config_path": str(config_path),
        "backup": str(backup),
        "extra_libraries": reshade_path,
    }



def restore_xxmi_extra_libraries(config: AppConfig) -> dict[str, Any]:
    launcher_path = config.xxmi_launcher_path
    if launcher_path is None:
        return {"ok": False, "message": "XXMI Launcher path is not configured"}
    config_path = reshade_integration.xxmi_config_path(launcher_path)
    if config_path is None:
        return {"ok": False, "message": "XXMI Launcher Config.json was not found"}
    backup = config_path.with_suffix(config_path.suffix + ".mc.bak")
    if not backup.is_file():
        return {"ok": False, "message": "no XXMI config backup found"}
    shutil.copy2(backup, config_path)
    return {"ok": True, "config_path": str(config_path), "backup": str(backup)}

def enable_anti_cheat_safe_mode(config: AppConfig) -> dict[str, Any]:
    """Move ReShade out of the game directory and inject it through XXMI instead.

    This is intentionally explicit and reversible.  It removes only
    EndfieldModController's integration files, renames the game-directory ReShade
    proxies to ``*.endfieldmodcontroller.disabled``, copies the existing ReShade DLL to
    ``runtime/reshade/ReShade64.dll`` when possible, and switches the launch mode
    to ``xxmi_extra`` so XXMI injects ReShade at process start.
    """
    actions: list[str] = []
    warnings: list[str] = []

    removed = reshade_integration.remove_existing_reshade(config)
    actions.extend(f"removed {item}" for item in removed.get("removed", []))
    actions.extend(f"restored {item}" for item in removed.get("restored", []))

    info = reshade_integration.detect_existing_reshade(config)
    adopted_ok = False
    if info is not None:
        try:
            adopted = reshade_integration.adopt_game_reshade_dll(config, info)
            config.reshade_dll = adopted["target"]
            config.save()
            adopted_ok = True
            actions.append(f"adopted ReShade 6.x from {adopted['source']}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"复制游戏目录 ReShade 失败: {exc}")
        if adopted_ok:
            try:
                disabled = reshade_integration.disable_game_reshade_proxies(config, info)
                for entry in disabled.get("disabled", []):
                    actions.append(f"disabled {entry['original']} -> {entry['disabled']}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"重命名游戏目录 ReShade 代理失败: {exc}")
        else:
            warnings.append("未能从游戏目录复制 ReShade，已保留 dxgi.dll / d3d12.dll 原样。请手动准备 ReShade 6.8 Addon 后再试。")
    else:
        warnings.append("未检测到游戏目录 ReShade，跳过复制和代理重命名。")

    if not config.reshade_dll_path or not config.reshade_dll_path.is_file():
        try:
            from . import reshade
            downloaded = reshade.download_reshade(config.reshade_runtime_path)
            config.reshade_dll = downloaded["dll"]
            config.save()
            actions.append(f"downloaded ReShade {downloaded['version']}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"下载 ReShade 6.8 Addon 失败: {exc}")

    config.reshade_injection = "xxmi_extra"
    config.save()
    try:
        extra = configure_xxmi_extra_libraries(config)
        actions.append(f"XXMI extra_libraries -> {extra.get('extra_libraries')}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"配置 XXMI extra_libraries 失败: {exc}")

    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "safe_mode": True,
        "reshade_injection": config.reshade_injection,
        "reshade_dll": str(config.reshade_dll_path or ""),
    }


def restore_global_reshade_elevated(config: AppConfig) -> dict[str, Any]:
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    apps = Path(program_data) / "ReShade" / "ReShadeApps.ini"
    backup = Path(str(apps) + ".endfieldmodcontroller.bak")
    if not backup.is_file():
        return {"ok": True, "restored": []}
    script = config.runtime_path / "restore_global_reshade.cmd"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "@echo off" + chr(10)
        + "setlocal" + chr(10)
        + "set \"APPS=%ProgramData%\\ReShade\\ReShadeApps.ini\"" + chr(10)
        + "if exist \"%APPS%.endfieldmodcontroller.bak\" copy /Y \"%APPS%.endfieldmodcontroller.bak\" \"%APPS%\" >nul" + chr(10)
        + "endlocal" + chr(10),
        encoding="utf-8",
    )
    _spawn_elevated(config, str(script), str(script.parent), show_window=0)
    return {"ok": True, "restored": [str(apps)]}


def restore_anti_cheat_safe_mode(config: AppConfig) -> dict[str, Any]:
    actions: list[str] = []
    warnings: list[str] = []
    restored = reshade_integration.restore_game_reshade_proxies(config)
    actions.extend(f"restored {item}" for item in restored.get("restored", []))
    warnings.extend(restored.get("errors", []))
    xxmi = restore_xxmi_extra_libraries(config)
    if xxmi.get("ok"):
        actions.append(f"restored {xxmi.get('config_path')}")
    else:
        warnings.append(str(xxmi.get("message")))
    reshade_integration.clear_safe_mode_manifest(config)
    global_restore = restore_global_reshade_elevated(config)
    actions.extend(f"restored global ReShade apps: {item}" for item in global_restore.get("restored", []))
    if not global_restore.get("ok", True):
        warnings.append(str(global_restore.get("message") or "restore global ReShade apps failed"))
    config.reshade_injection = "external"
    config.save()
    return {"ok": not warnings, "actions": actions, "warnings": warnings}


def enable_d3d12_proxy_mode(config: AppConfig) -> dict[str, Any]:
    """Use the game-directory ReShade as ``d3d12.dll`` and hide ``dxgi.dll``.

    This matches the common Endfield workaround: the game dynamically loads
    ``d3d12.dll`` even in its DX11 mode, while the anti-cheat message specifically
    complains about the ``dxgi`` module name.
    """
    actions: list[str] = []
    warnings: list[str] = []

    if reshade_integration.safe_mode_active(config):
        restored = restore_anti_cheat_safe_mode(config)
        actions.extend(restored.get("actions", []))
        warnings.extend(restored.get("warnings", []))

    info = reshade_integration.detect_existing_reshade(config)
    if info is None:
        raise LaunchError("没有检测到游戏目录 ReShade，无法切换 dxgi→d3d12 模式。")
    try:
        swapped = reshade_integration.swap_dxgi_to_d3d12(config, info)
        actions.append(f"disabled {swapped.get('disabled_dxgi')}")
        actions.append(f"kept ReShade d3d12 proxy: {swapped.get('d3d12')}")
    except Exception as exc:  # noqa: BLE001
        raise LaunchError(f"切换 dxgi→d3d12 失败: {exc}") from exc

    config.reshade_injection = "none"
    config.save()

    try:
        integration = reshade_integration.deploy_existing_reshade(config, controller_dir=config.controller_dir)
        actions.extend(f"deployed {entry['path']}" for entry in integration.get("files", []))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"写入游戏目录 ReShade 集成文件失败: {exc}")

    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "d3d12_proxy_mode": True,
        "reshade_injection": config.reshade_injection,
    }


def restore_d3d12_proxy_mode(config: AppConfig) -> dict[str, Any]:
    actions: list[str] = []
    warnings: list[str] = []
    restored = reshade_integration.restore_dxgi_from_d3d12(config)
    actions.extend(restored.get("actions", []))
    warnings.extend(restored.get("errors", []))
    removed = reshade_integration.remove_existing_reshade(config)
    actions.extend(f"removed {item}" for item in removed.get("removed", []))
    actions.extend(f"restored {item}" for item in removed.get("restored", []))
    xxmi = restore_xxmi_extra_libraries(config)
    if xxmi.get("ok"):
        actions.append(f"restored {xxmi.get('config_path')}")
    else:
        warnings.append(str(xxmi.get("message")))
    global_restore = restore_global_reshade_elevated(config)
    actions.extend(f"restored global ReShade apps: {item}" for item in global_restore.get("restored", []))
    if not global_restore.get("ok", True):
        warnings.append(str(global_restore.get("message") or "restore global ReShade apps failed"))
    config.reshade_injection = "external"
    config.save()
    return {"ok": not warnings, "actions": actions, "warnings": warnings}


def _set_d3dx_loader_target(d3dx_ini: Path, target: str) -> bool:
    """Keep [Loader] target pointing at the real Endfield executable.

    The injected EFMI d3d11.dll validates this value against the process it was
    loaded into.  Updating it outside the loader hot path avoids the old
    QueryFullProcessImageName stall while still making moved installations work.
    """
    if not d3dx_ini.is_file() or not target:
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    in_loader = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_loader = stripped.lower() == "[loader]"
        if in_loader and stripped.lower().startswith("target") and "=" in stripped and not replaced:
            out.append(f"target = {target}")
            replaced = True
            continue
        out.append(line)
    if not replaced:
        try:
            index = next(i for i, line in enumerate(out) if line.strip().lower() == "[loader]")
        except StopIteration:
            return False
        out.insert(index + 1, f"target = {target}")
    d3dx_ini.write_text(chr(10).join(out) + chr(10), encoding="utf-8", newline=chr(10))
    return True


def build_launch_env(config: AppConfig, *, existing_reshade: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    if existing_reshade:
        # Let the existing game-directory ReShade keep its own base path.
        env.pop("RESHADE_BASE_PATH_OVERRIDE", None)
        env.pop("RESHADE_DISABLE_LOADING_CHECK", None)
    else:
        env["RESHADE_BASE_PATH_OVERRIDE"] = str(config.reshade_runtime_path)
        env["RESHADE_DISABLE_LOADING_CHECK"] = "1"
    env["ENDFIELDMODCONTROLLER_USER_INI"] = str(config.user_ini_path)
    return env


def build_launch_command(config: AppConfig, *, start_game: bool = False) -> list[str]:
    launcher = config.xxmi_launcher_path
    if launcher is None:
        raise LaunchError("XXMI Launcher path is not configured")
    if not start_game:
        # Opening XXMI without --xxmi only shows the launcher window.  Passing
        # --xxmi EFMI makes XXMI start the game immediately, which is not what
        # the one-click preparation flow promises.
        return [str(launcher)]
    game_exe = config.game_exe_path
    # Explicit "start game" keeps the normal XXMI window visible.  The
    # headless --nogui form is still available through core.build_xxmi_launch_command.
    return core.build_xxmi_launch_command(launcher, game_exe, nogui=False)


def launch_official_gui(config: AppConfig) -> dict[str, Any]:
    """Open the official XXMI Launcher GUI with the EFMI package selected.

    This deliberately avoids EndfieldModController's custom 3DMigoto loader,
    bootstrap DLL, ReShade proxy deployment and game-directory edits.  It only
    stages the selected mods into the official XXMI/EFMI ``Mods`` folder and
    starts the official XXMI Launcher window; the user then uses XXMI's own
    EFMI interface to start the game.
    """
    config.ensure_dirs()
    # Prevent an old custom loader from injecting a second 3DMigoto proxy.
    try:
        _stop_locked_files_processes(config)
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"清理旧 loader 失败（继续启动官方 XXMI）: {exc}")

    # 先把「手动放进 Mods 目录的 Mod」收编进来，再做 staging。
    #
    # 用户需求（原话）：「手动放进去的和库里的进行比对，如果库里已有，就在 UI 中显示
    # 那个开启，库里没有就把它放到库里，然后显示开启」。
    # 时机很关键：必须在下面对 Mods 的整目录清空**之前**执行，否则手动放的 Mod 会被
    # 直接清掉。收编后它们进入 selected_mods，本次 staging 就会正常生成 MC_* 产物。
    try:
        synced = activation.import_manual_mods(config, log=lambda m: _append_log(config, m))
        if synced.get("found"):
            detail = (f"手动 Mod 同步: 收进库 {len(synced['imported'])} 个、"
                      f"库中已有 {len(synced['matched'])} 个")
            if synced.get("selected_added"):
                detail += f"；已在界面勾选: {', '.join(synced['selected_added'])}"
            _append_log(config, detail)
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"同步手动 Mod 失败（已跳过，继续启动）: {exc}")

    # Mods 目录由控制器全权管理：最终只放"用户在 Mod 库勾选的那些"。
    # stage_and_prepare 会先清空整个 Mods（含手动放进去的），再按 selected_mods 生成
    # MC_* 产物 —— 这样绝不会出现同角色成对（踩过两次，见 activation.stage_and_prepare）。
    # 注意 selected_mods 为空时不能调用：resolve_active_set 里「空列表」= 全部激活。
    if config.selected_mods and getattr(config, "efmi_injection", True):
        try:
            activation.stage_and_prepare(
                config.library_path,
                config.staging_mods_path,
                config.runtime_path,
                selected_ids=config.selected_mods,
            )
        except Exception as exc:  # noqa: BLE001
            _append_log(config, f"暂存所选 mod 失败: {exc}")
    else:
        _append_log(config, "未选择任何 Mod，跳过 staging（Mods 目录保持原样）")

    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        raise LaunchError("没有配置可用的 XXMI Launcher 路径")

    # 用 os.startfile 启动 = **字面意义上的"双击"**：Windows 走 shell 关联，
    # 工作目录 / 权限 / 环境变量全部按系统默认来，不再受本 Python 进程影响。
    # 之前用 subprocess / ShellExecuteW 时，cwd、CREATE_NO_WINDOW、
    # os.environ.copy() 都会把控制器的进程属性带过去，实测会让游戏起不来。
    _append_log(config, f"以系统默认方式启动 XXMI: {launcher}")
    try:
        os.startfile(str(launcher))  # type: ignore[attr-defined]
        process = None
    except OSError as exc:  # noqa: PERF203
        if getattr(exc, "winerror", None) == 740:
            raise LaunchError(
                "XXMI Launcher 需要管理员权限。请关闭本控制器，右键 run.vbs / run.bat 选"
                "「以管理员身份运行」后重试。"
            ) from exc
        raise
    # 启动崩溃监控：游戏是 XXMI 拉起来的，这里起个后台线程等进程出现、跟踪到退出，
    # 自动把崩溃现场（CrashSight / 崩溃栈 / 模块清单 / 注入快照）写成报告。
    try:
        from . import crashwatch

        crashwatch.start_watch(config, log=lambda msg: _append_log(config, msg))
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"启动崩溃监控失败: {exc}")
    return {
        "mode": "official_xxmi_gui",
        "command": [str(launcher)],
        "pid": None,
        "elevated": False,
        "message": "已以系统默认方式（等同双击）打开 XXMI Launcher；请在它的 EFMI 界面里启动游戏。",
    }



def install_missing_dependencies(config: AppConfig) -> list[dict[str, Any]]:
    """Install dependencies required by the current selection but not present locally."""
    mods = core.scan_library(config.library_path, config.staging_mods_path)
    selected = set(config.selected_mods or [])
    if selected:
        mods = [mod for mod in mods if mod.id in selected or mod.is_dependency]
    required = core.collect_required_dependency_names(mods)
    manifest = dependencies.load_manifest(config.dependency_manifest_path)
    missing = dependencies.select_missing_dependencies(manifest, config.library_path, required)
    if not missing:
        return []
    return [result.__dict__ for result in dependencies.update_all(missing, config.library_path, dry_run=False, enabled_only=False)]


def _append_log(config: AppConfig, message: str) -> None:
    diagnostics.log_event(config, message, category="launch")


_ENV_KEEP = {
    "PATH", "SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT",
    "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramData",
    "ProgramFiles", "ProgramFiles(x86)", "CommonProgramFiles", "CommonProgramFiles(x86)",
    "CommonProgramW6432", "ProgramW6432", "PUBLIC", "ALLUSERSPROFILE",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "OS", "COMPUTERNAME",
    "USERNAME", "USERDOMAIN", "USERDOMAIN_ROAMINGPROFILE",
    "HOMEDRIVE", "HOMEPATH", "LOGONSERVER", "SESSIONNAME",
}
# 不该出现在游戏进程 PATH 里的开发/工具链目录
_ENV_PATH_BLOCK = (
    "windowsapps", "powershell", "\\python", "python3", "scoop", "\\git",
    "nodejs", "vmware", "\\java", "dotnet", "sql server", "msys", "cygwin",
)
# Windows 环境变量名大小写不敏感，比较前统一小写（否则会误剔 ComSpec/ProgramData 等）
_ENV_KEEP_LOWER = {k.lower() for k in _ENV_KEEP}


def clean_launch_env() -> dict[str, str]:
    """给「启动启动器/游戏」用的最小环境。

    控制器自己是从 Python（甚至从别的 shell）启动的，它继承的一堆变量
    （PYTHON*、DSH_*、GIT_*、各种专业软件变量，以及在 PATH 最前面的
    PowerShell/工具链目录）会被 XXMI 继承、再传给游戏进程，可能干扰游戏的
    DLL 查找与初始化。这里只保留系统必需变量，并把工具链目录从 PATH 剔除。
    """
    env = {k: v for k, v in os.environ.items() if k.lower() in _ENV_KEEP_LOWER}
    raw_path = os.environ.get("PATH", "")
    parts = [
        p for p in raw_path.split(os.pathsep)
        if p and not any(bad in p.lower() for bad in _ENV_PATH_BLOCK)
    ]
    if parts:
        env["PATH"] = os.pathsep.join(parts)
    return env


def _spawn_command(config: AppConfig, command: list[str], cwd: str, env: dict[str, str], show_window: int = 1):
    """Start a command, requesting UAC when WinError 740 occurs.

    **不要给 GUI 启动器（XXMI / 官方启动器）加 CREATE_NO_WINDOW**：
    它们随后会用 CreateProcess 拉起游戏，而"无控制台"的父进程会让游戏继承
    异常的标准句柄（stdout/stderr 无效），Unity 游戏在这种环境下可能直接
    进不去（2026-09-27 实测：同一份 XXMI2，双击能进、被本函数加了这个标志
    启动就崩）。只在启动纯控制台工具时才隐藏窗口。
    """
    creationflags = 0
    try:
        name = Path(command[0]).name.lower()
    except Exception:  # noqa: BLE001
        name = ""
    console_tools = ("taskkill", "where", "cmd.exe", "7z.exe", "7za.exe", "tar.exe")
    if os.name == "nt" and name in console_tools:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 740:
            # 不要在这里自动 runas 提权：UAC 提升后的进程工作目录常被重置为
            # C:\Windows\System32（ShellExecuteW 的 lpDirectory 经常不生效），
            # 而 XXMI 按自身工作目录找资源，cwd 一错游戏就进不去。
            # 正确做法是让用户「以管理员身份」启动本控制器，这样 XXMI 由普通
            # CreateProcess 启动，cwd 正确。
            raise LaunchError(
                "XXMI Launcher 需要管理员权限。请关闭本控制器，右键 run.vbs / run.bat 选"
                "「以管理员身份运行」后重试 —— 自动提权会让它丢失工作目录，导致游戏进不去。"
            ) from exc
        raise

def _spawn_elevated(config: AppConfig, exe: str, cwd: str, show_window: int = 0) -> None:
    """Run an executable elevated without a console window via ShellExecuteW."""
    if os.name != "nt":
        subprocess.Popen([exe], cwd=cwd)
        return
    import ctypes
    _append_log(config, f"正在以管理员权限启动: {exe}")
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, None, cwd, show_window)
    if result <= 32:
        raise LaunchError(f"请求管理员权限失败，ShellExecuteW 返回 {result}")


def launch(
    config: AppConfig,
    *,
    dry_run: bool = True,
    start_game: bool = False,
    inject_timeout: float = 60.0,
) -> dict[str, Any]:
    config.ensure_dirs()
    game_dir = reshade_integration.detect_game_dir(config)
    if not dry_run:
        diagnostics.begin_launch(config, "xxmi", game_dir=game_dir)
    if config.use_builtin_runtime and not dry_run:
        try:
            runtime_deps.ensure_all(
                config,
                progress=lambda current, total, key, status: _append_log(config, f"builtin {key}: {status}"),
            )
        except Exception as exc:  # noqa: BLE001
            _append_log(config, f"builtin runtime install failed: {exc}")

    dependency_updates: list[dict[str, Any]] = []
    if not dry_run:
        # Install dependencies before staging so newly installed libraries are
        # copied into the active Mods directory in the same launch.
        try:
            dependency_updates = install_missing_dependencies(config)
        except Exception as exc:  # noqa: BLE001
            _append_log(config, f"missing dependency install failed: {exc}")

    if not dry_run:
        activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.selected_mods,
        )

    problems = config.validate()
    if problems:
        raise LaunchError("; ".join(problems))

    controller_dir = config.controller_dir
    if not dry_run and not (controller_dir / "actions.tsv").is_file():
        raise LaunchError("Controller files are missing. Run prepare first.")

    if config.auto_update_dependencies and not dry_run:
        manifest = dependencies.load_manifest(Path(config.dependency_manifest))
        dependency_updates += [r.__dict__ for r in dependencies.update_all(manifest, config.library_path, dry_run=False)]

    reshade = prepare_reshade_runtime(config, controller_dir)
    existing_reshade = reshade_integration.detect_existing_reshade(config)
    if not dry_run and game_dir is not None:
        diagnostics.log_runtime_snapshot(config, game_dir=game_dir)

    # —— 本方案唯一的注入路径 ——
    # 由 XXMI 在进程启动时把 DLSS5 的 d3d12.dll（唯一 ReShade 底座：DLSS5 +
    # 第一人称两个插件）和 EFMI 的 d3d11.dll（服装 Mod）一起注入。
    # 因此不再往游戏目录写任何文件，也不接管游戏目录里可能残留的旧 ReShade。
    integration: dict[str, Any] | None = None
    if existing_reshade is not None:
        _append_log(
            config,
            "检测到游戏目录仍有 ReShade（"
            + str(existing_reshade.get("ini"))
            + "）——本方案不使用它，唯一底座由 XXMI 注入；"
            "建议用「清理游戏目录注入」把它停放，避免两个 ReShade 抢 hook。",
        )

    if not dry_run:
        injection_report = ensure_injections(config)
        reshade["injection_report"] = injection_report
        for warning in injection_report.get("warnings", []):
            _append_log(config, f"WARN 注入自检: {warning}")

    integrity_report = {"ok": True, "failures": []}
    if not dry_run:
        integrity_report = integrity.check_integrity(config)
        if not integrity_report["ok"]:
            for failure in integrity_report["failures"]:
                _append_log(config, f"integrity missing: {failure['key']} -> {failure['path']}")
            integrity.repair_integrity(config, log=lambda message: _append_log(config, f"repair: {message}"))
            controller_dir = config.controller_dir
            reshade = prepare_reshade_runtime(config, controller_dir)
            if config.dlss5_injection:
                configure_dlss5_injection(config, enabled=True)
            integrity_report = integrity.check_integrity(config)
        if not integrity_report["ok"]:
            raise LaunchError("完整性检查失败: " + "; ".join(item["message"] for item in integrity_report["failures"]))
        _append_log(config, "完整性检查通过")

    command = build_launch_command(config, start_game=start_game)
    env = build_launch_env(config, existing_reshade=existing_reshade is not None)
    result: dict[str, Any] = {
        "command": command,
        "env": {k: v for k, v in env.items() if k.startswith(("RESHADE", "ENDFIELDMODCONTROLLER"))},
        "reshade": reshade,
        "existing_reshade": integration if integration is not None else existing_reshade,
        "dependency_updates": dependency_updates,
        "start_game": start_game,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    _append_log(config, f"launch command: {command}")
    _append_log(config, f"RESHADE_BASE_PATH_OVERRIDE={env.get('RESHADE_BASE_PATH_OVERRIDE')}")
    if not start_game:
        _append_log(config, "游戏未由 EndfieldModController 启动；请从 XXMI Launcher 手动启动游戏。")

    if config.require_admin and hasattr(os, "geteuid") and os.geteuid() != 0:  # pragma: no cover
        raise LaunchError("Administrator privileges are required for launch")

    launcher_path = config.xxmi_launcher_path
    assert launcher_path is not None
    process = _spawn_command(config, command, str(launcher_path.parent), env)
    if process is not None:
        result["pid"] = process.pid
    else:
        result["elevated"] = True

    _append_log(config, "ReShade/DLSS5 与第一人称插件由 XXMI 注入库在进程启动时加载，无外部注入。")
    diagnostics.start_process_monitor(config, game_dir=game_dir, timeout=1800.0)
    return result


def ensure_migoto_runtime(config: AppConfig, source_dir: Path | None = None) -> dict[str, Any]:
    """Copy the framework files of a working 3DMigoto package into runtime/migoto.

    User Mods and d3dx_user.ini are deliberately not copied; EndfieldModController owns
    its own Mods/_endfieldmodcontroller_managed staging area there.
    """
    source = source_dir or (config.migoto_loader_path.parent if config.migoto_loader_path else None)
    if source is None or not source.is_dir():
        raise LaunchError("没有找到可用的 3DMigoto 包目录")
    target = config.runtime_path / "migoto"
    target.mkdir(parents=True, exist_ok=True)
    (target / "Mods").mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    framework_source = source
    if source.resolve() != target.resolve():
        # Prefer the EFMI core: it supports EFMIv1 / Pool mod sections.
        # The legacy v1.4.x framework is only a fallback.
        legacy = _legacy_migoto_source()
        efmi_dir = config.builtin_runtime_path / "XXMI" / "EFMI"
        if (efmi_dir / "d3d11.dll").is_file() and (efmi_dir / "d3dx.ini").is_file() and (efmi_dir / "Core").is_dir():
            framework_source = efmi_dir
        elif legacy is not None:
            framework_source = legacy
        for name in ("loader.exe",):
            src = source / name
            if src.is_file():
                _copy_if_changed(src, target / name)
                copied.append(name)
        for name in ("d3d11.dll", "d3dcompiler_47.dll", "d3dx.ini", "nvapi64.dll"):
            src = framework_source / name
            if src.is_file():
                _copy_if_changed(src, target / name)
                copied.append(name)
        for dirname in ("Core", "ShaderFixes"):
            src_dir = framework_source / dirname
            if src_dir.is_dir():
                shutil.copytree(src_dir, target / dirname, dirs_exist_ok=True)
                copied.append(dirname)
    bootstrap_src = _bootstrap_path()
    if bootstrap_src is not None:
        bootstrap_dst = target / "mc_bootstrap.dll"
        if bootstrap_src.resolve() != bootstrap_dst.resolve():
            _copy_if_changed(bootstrap_src, bootstrap_dst)
        copied.append("mc_bootstrap.dll")
    config.migoto_loader = str(target / "loader.exe")
    config.save()
    return {"source": str(source), "framework_source": str(framework_source), "target": str(target), "loader": str(target / "loader.exe"), "copied": copied}


def _efmi_core_global_keys(core_dir: Path | None) -> set[str]:
    keys: set[str] = set()
    if core_dir is None or not core_dir.is_dir():
        return keys
    try:
        files = list(core_dir.rglob("*.ini"))
    except OSError:
        return keys
    for candidate in files:
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("global "):
                match = re.search(r"\$[^=\s]+", stripped)
                keys.add(match.group(0).lower() if match else stripped.lower())
    return keys


def ensure_efmi_library_globals(d3dx_ini: Path, library_root: Path, core_dir: Path | None = None) -> bool:
    """Copy global variable definitions from library-level d3dx.ini files.

    Some Endfield mod packs ship a base d3dx.ini that defines globals such as
    ``$costume_mods``.  Their mod ini files assume those globals exist, but
    EndfieldModController deliberately does not copy per-mod d3dx.ini files into Mods.
    Pull the declarations into the active d3dx.ini [Constants] section so the
    dependency works without replacing the whole EFMI config.

    Globals already owned by EFMI core (for example its own ``$version``) are
    deliberately skipped to avoid breaking EFMI's compatibility checks.
    """
    if not d3dx_ini.is_file() or not library_root.is_dir():
        return False
    declarations: dict[str, str] = {}
    try:
        candidates = list(library_root.rglob("d3dx.ini"))
    except OSError:
        candidates = []
    for candidate in candidates:
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped.lower().startswith("global "):
                continue
            match = re.search(r"\$[^=\s]+", stripped)
            key = match.group(0).lower() if match else stripped.lower()
            declarations.setdefault(key, stripped)
    reserved = _efmi_core_global_keys(core_dir)
    declarations = {key: value for key, value in declarations.items() if key not in reserved}
    if not declarations:
        # Still remove an old generated block if it exists.
        pass

    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        marker = line.strip().lower()
        if marker == "; endfieldmodcontroller library globals begin":
            skipping = True
            continue
        if marker == "; endfieldmodcontroller library globals end":
            skipping = False
            continue
        if not skipping:
            out.append(line)

    try:
        index = next(i for i, line in enumerate(out) if line.strip().lower() == "[constants]")
    except StopIteration:
        return False

    existing = set()
    for line in out:
        stripped = line.strip()
        if stripped.lower().startswith("global "):
            match = re.search(r"\$[^=\s]+", stripped)
            existing.add(match.group(0).lower() if match else stripped.lower())
    missing = [value for key, value in declarations.items() if key not in existing]
    if not missing:
        d3dx_ini.write_text(chr(10).join(out) + chr(10), encoding="utf-8", newline=chr(10))
        return bool(not skipping or out)
    block = ["; EndfieldModController library globals begin", *missing, "; EndfieldModController library globals end"]
    out[index + 1:index + 1] = block
    d3dx_ini.write_text(chr(10).join(out) + chr(10), encoding="utf-8", newline=chr(10))
    return True


def ensure_legacy_costume_sections(d3dx_ini: Path) -> bool:
    """Append the legacy ShaderOverrideCharacter/CommandListSkin block.

    The EFMI core handles Pool/EFMIv1 mods, but many costume mods in this pack
    still depend on the original Endfield 3DMigoto v1.4.x overrides:
    ``[ShaderOverrideCharacter]`` runs ``[CommandListSkin]`` and enables the
    per-slot ``checktextureoverride`` entries used by ``VSCheck.ini``.
    """
    if not d3dx_ini.is_file():
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    begin = "; EndfieldModController legacy costume override begin"
    end = "; EndfieldModController legacy costume override end"
    out: list[str] = []
    skipping = False
    for line in lines:
        marker = line.strip().lower()
        if marker == begin.lower():
            skipping = True
            continue
        if marker == end.lower():
            skipping = False
            continue
        if not skipping:
            out.append(line)
    text = chr(10).join(out)
    if "[ShaderOverrideCharacter]" in text and "[CommandListSkin]" in text:
        d3dx_ini.write_text(chr(10).join(out) + chr(10), encoding="utf-8", newline=chr(10))
        return False
    block = [
        begin,
        "[ShaderOverrideCharacter]",
        "hash = 653c63ba4a73ca8b",
        "run = CommandListSkin",
        "",
        "[CommandListSkin]",
        "if $costume_mods",
        "    checktextureoverride = ps-t0",
        "    checktextureoverride = ps-t1",
        "    checktextureoverride = ps-t2",
        "    checktextureoverride = ps-t3",
        "    checktextureoverride = vb0",
        "    checktextureoverride = vb1",
        "    checktextureoverride = vb2",
        "    checktextureoverride = ib",
        "    checktextureoverride = ps-t13",
        "    checktextureoverride = ps-t14",
        "    checktextureoverride = ps-t15",
        "    checktextureoverride = ps-t16",
        "    checktextureoverride = ps-t17",
        "    x140 = 0",
        "endif",
        end,
    ]
    out.extend(["", *block])
    d3dx_ini.write_text(chr(10).join(out) + chr(10), encoding="utf-8", newline=chr(10))
    return True


def ensure_efmi_early_includes(d3dx_ini: Path) -> bool:
    """Load [Include]/Mods during EFMI init instead of waiting for the first frame.

    EFMI 1.3.x defaults to ``skip_early_includes_load=1`` with a zero-second
    delayed reload.  In Endfield that delayed reload may not fire before the
    player checks the character, so mods appear "not loaded" even though EFMI
    initialized.  Force the original 3DMigoto behavior instead.
    """
    if not d3dx_ini.is_file():
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    in_system = False
    found_skip = False
    found_delay = False
    changed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_system = stripped.lower() == "[system]"
        if in_system and stripped.lower().startswith("skip_early_includes_load") and "=" in stripped:
            if stripped != "skip_early_includes_load = 0":
                out.append("skip_early_includes_load = 0")
                changed = True
            else:
                out.append(line)
            found_skip = True
            continue
        if in_system and stripped.lower().startswith("config_initialization_delay") and "=" in stripped:
            if stripped != "config_initialization_delay = -1":
                out.append("config_initialization_delay = -1")
                changed = True
            else:
                out.append(line)
            found_delay = True
            continue
        out.append(line)
    if not found_skip or not found_delay:
        try:
            index = next(i for i, line in enumerate(out) if line.strip().lower() == "[system]")
        except StopIteration:
            return changed
        insert_at = index + 1
        if not found_delay:
            out.insert(insert_at, "config_initialization_delay = -1")
            changed = True
        if not found_skip:
            out.insert(insert_at, "skip_early_includes_load = 0")
            changed = True
    if changed:
        d3dx_ini.write_text(chr(10).join(out) + chr(10), encoding="utf-8", newline=chr(10))
    return changed


def enable_efmi_debug_logging(d3dx_ini: Path) -> bool:
    """Set a light EFMI/3DMigoto log profile: calls on, per-frame debug off.

    ``debug=1`` logs every API call and is frequently unbuffered, which can
    drop Endfield to single-digit FPS.  Keep only calls/input logging so the
    log stays useful without throttling the game.
    """
    if not d3dx_ini.is_file():
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    in_logging = False
    changed = False
    wanted = {"calls": "1", "input": "1", "debug": "0", "unbuffered": "0"}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_logging = stripped.lower() == "[logging]"
            out.append(line)
            continue
        if in_logging and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().lower()
            if key in wanted:
                out.append(f"{key} = {wanted[key]}")
                changed = True
                continue
        out.append(line)
    if changed:
        # Drop the run of empty continuation lines that some older packaging
        # steps inserted; the parser ignores them, but they make d3dx.ini huge.
        cleaned = [line for line in out if line.strip()]
        d3dx_ini.write_text(chr(10).join(cleaned) + chr(10), encoding="utf-8", newline=chr(10))
    return changed


def launch_migoto_loader(
    config: AppConfig,
    *,
    open_official_launcher: bool = True,
) -> dict[str, Any]:
    """Stage controller mods into a working 3DMigoto package and start its loader.exe.

    The loader waits for Endfield.exe, updates d3dx.ini's target, and injects the
    package's own d3d11.dll.  This mirrors the workflow that already worked for
    the user and avoids XXMI/EFMI and ReShade proxy DLLs.
    """
    actions: list[str] = []
    warnings: list[str] = []

    _stop_locked_files_processes(config)
    loader = config.migoto_loader_path
    if loader is None or not loader.is_file():
        raise LaunchError("3DMigoto loader path is not configured")
    target_runtime = (config.runtime_path / "migoto").resolve()
    legacy_source = _legacy_migoto_source()
    efmi_dir = config.builtin_runtime_path / "XXMI" / "EFMI"
    current_ini = target_runtime / "d3dx.ini"
    if not (_is_legacy_framework_config(current_ini) or _has_efmi_core_config(current_ini)):
        if (
            (efmi_dir / "d3d11.dll").is_file()
            and (efmi_dir / "d3dx.ini").is_file()
            and (efmi_dir / "Core").is_dir()
        ):
            ensured = ensure_migoto_runtime(config, efmi_dir)
            loader = Path(ensured["loader"])
        elif legacy_source is not None:
            ensured = ensure_migoto_runtime(config, legacy_source)
            loader = Path(ensured["loader"])
    if loader.parent.resolve() != target_runtime or not (target_runtime / "loader.exe").is_file():
        ensured = ensure_migoto_runtime(config, loader.parent)
        loader = Path(ensured["loader"])
    loader_dir = loader.parent
    legacy_mode = _is_legacy_framework_config(loader_dir / "d3dx.ini")

    if not legacy_mode:
        bootstrap_src = _bootstrap_path()
        if bootstrap_src is None:
            raise LaunchError("未找到 mc_bootstrap.dll，无法启动 EFMI 注入桥")
        _copy_if_changed(bootstrap_src, loader_dir / "mc_bootstrap.dll")

    try:
        d3dx_ini = loader_dir / "d3dx.ini"
        if _has_efmi_core_config(d3dx_ini):
            ensure_efmi_library_globals(d3dx_ini, config.library_path, loader_dir / "Core")
            ensure_efmi_early_includes(d3dx_ini)
        enable_efmi_debug_logging(d3dx_ini)
        old_log = loader_dir / "d3d11_log.txt"
        if old_log.is_file():
            backup_log = loader_dir / "d3d11_log.prev.txt"
            if backup_log.exists():
                backup_log.unlink()
            old_log.rename(backup_log)
    except OSError:
        pass
    game_dir = reshade_integration.detect_game_dir(config)
    diagnostics.begin_launch(config, "migoto_loader", game_dir=game_dir)
    required_files = ["d3d11.dll", "d3dx.ini"]
    if not legacy_mode:
        required_files.append("mc_bootstrap.dll")
    for required in required_files:
        if not (loader_dir / required).is_file():
            raise LaunchError(f"3DMigoto package is missing {required}: {loader_dir}")

    # Reuse the simple loader executable, but use our multi-injector build so
    # ReShade64.dll can be injected before the EFMI d3d11.dll.
    multi_loader = _multi_loader_path()
    if not legacy_mode and multi_loader is not None:
        _copy_if_changed(multi_loader, loader_dir / "migoto_loader2.exe")

    mods_dir = loader_dir / "Mods"
    user_ini = loader_dir / "d3dx_user.ini"
    if not user_ini.is_file():
        user_ini.write_text("; EndfieldModController generated" + chr(10) + "[Constants]" + chr(10), encoding="utf-8")
    result = activation.stage_and_prepare(
        config.library_path,
        mods_dir,
        config.runtime_path,
        selected_ids=config.selected_mods,
        user_ini_path=user_ini,
    )
    controller_dir = Path(result["controller_dir"])

    # Prepare ReShade beside the injected EFMI d3d11.dll.  ReShade uses its own
    # module directory as base path, so actions.tsv and user_ini_path.txt must
    # live here rather than in the game directory.
    built_addon = _built_addon_path()
    addons_dir = loader_dir / "Addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    installed_addon = addons_dir / "endfieldmodcontroller.addon"
    if getattr(config, "inject_reshade_ui", True):
        if built_addon is not None:
            shutil.copy2(built_addon, installed_addon)
    else:
        disabled_addon = installed_addon.with_name(installed_addon.name + ".disabled")
        if installed_addon.is_file():
            if disabled_addon.exists():
                disabled_addon.unlink()
            installed_addon.rename(disabled_addon)
    actions_tsv = controller_dir / "actions.tsv"
    if actions_tsv.is_file():
        shutil.copy2(actions_tsv, loader_dir / "actions.tsv")
    (loader_dir / "user_ini_path.txt").write_text(str(user_ini), encoding="utf-8")
    (loader_dir / "inject_order.txt").write_text("mc_bootstrap.dll" + chr(10), encoding="utf-8")
    reshade_ini = loader_dir / "ReShade.ini"
    if not reshade_ini.is_file():
        ini_lines = [
            "[ADDON]",
            "AddonPath=Addons",
            "",
            "[GENERAL]",
            "EffectSearchPaths=reshade-shaders/Shaders/**",
            "TextureSearchPaths=reshade-shaders/Textures/**",
            "PresetPath=ReShadePreset.ini",
            "",
            "[INPUT]",
            "KeyOverlay=36,0,0,0",
            "",
        ]
        reshade_ini.write_text(chr(10).join(ini_lines), encoding="utf-8")

    # ReShade + EFMI coexistence: put ReShade in the game folder as d3d12.dll
    # (the name Endfield dynamically probes under DX11), and let the EFMI loader
    # inject only d3d11.dll.  Do not inject ReShade64.dll into the same process.
    if game_dir is None:
        game_dir = reshade_integration.detect_game_dir(config)
    reshade_enabled = config.reshade_injection in {"external", "xxmi_extra"}
    if game_dir is not None and not reshade_enabled:
        # Explicitly disable ReShade when the user selects "不注入 ReShade".
        # The previous run may have left a proxying d3d12.dll in the game dir.
        for proxy_name in ("d3d12.dll",):
            proxy = game_dir / proxy_name
            if proxy.is_file():
                disabled = game_dir / (proxy_name + ".endfieldmodcontroller.disabled")
                if disabled.exists():
                    disabled.unlink()
                proxy.rename(disabled)
                actions.append(f"已禁用 ReShade 代理: {proxy_name}")
    if game_dir is not None and reshade_enabled:
        for conflict_name in ("dxgi.dll", "d3d11.dll"):
            conflict = game_dir / conflict_name
            if conflict.is_file():
                backup = conflict.with_name(conflict.name + ".endfieldmodcontroller.disabled")
                if backup.exists():
                    backup.unlink()
                conflict.rename(backup)
        reshade_dll = config.reshade_dll_path
        if reshade_dll is not None and reshade_dll.is_file():
            shutil.copy2(reshade_dll, game_dir / "d3d12.dll")
            _ensure_reshade_disabled_addons(game_dir)
            try:
                disabled_addons = reshade_integration.disable_conflicting_addons(
                    game_dir,
                    log=lambda message: _append_log(config, message),
                )
                actions.extend(f"disabled {item}" for item in disabled_addons.get("disabled", []))
                warnings.extend(disabled_addons.get("warnings", []))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"物理禁用冲突 addon 失败: {exc}")
            built_addon = _built_addon_path()
            game_addon = game_dir / "endfieldmodcontroller.addon"
            if getattr(config, "inject_reshade_ui", True):
                if built_addon is not None:
                    shutil.copy2(built_addon, game_addon)
            else:
                disabled_game_addon = game_addon.with_name(game_addon.name + ".disabled")
                if game_addon.is_file():
                    if disabled_game_addon.exists():
                        disabled_game_addon.unlink()
                    game_addon.rename(disabled_game_addon)
            if actions_tsv.is_file():
                shutil.copy2(actions_tsv, game_dir / "actions.tsv")
            (game_dir / "user_ini_path.txt").write_text(str(user_ini), encoding="utf-8")
            if not (game_dir / "ReShade.ini").is_file():
                ini_lines = [
                    "[ADDON]",
                    "",
                    "[GENERAL]",
                    "PresetPath=ReShadePreset.ini",
                    "",
                    "[INPUT]",
                    "KeyOverlay=36,0,0,0",
                    "",
                ]
                (game_dir / "ReShade.ini").write_text(chr(10).join(ini_lines), encoding="utf-8")
            actions.append("deployed ReShade as game-directory d3d12.dll")

    game_exe = config.game_exe_path
    game_path = ""
    if game_exe is not None and game_exe.is_file():
        game_path = str(game_exe)
    else:
        game_dir = reshade_integration.detect_game_dir(config)
        if game_dir is not None:
            candidate = game_dir / "Endfield.exe"
            if candidate.is_file():
                game_path = str(candidate)
    if not game_path:
        game_path = r"%ProgramData%\ReShade\Endfield.exe"

    if game_path and not game_path.startswith("%"):
        try:
            if _set_d3dx_loader_target(loader_dir / "d3dx.ini", game_path):
                actions.append("已同步 EFMI 的 [Loader] target")
        except OSError as exc:
            warnings.append(f"更新 d3dx.ini target 失败: {exc}")

    env = os.environ.copy()
    run_script = loader_dir / "_run_loader.cmd"
    batch_template = r'''@echo off
setlocal
set "GAME=__GAME__"
set "APPS=%ProgramData%\ReShade\ReShadeApps.ini"
if exist "%APPS%" (
  > "%APPS%.endfieldmodcontroller.bak" echo Apps=%GAME%
  > "%APPS%" echo Apps=%ProgramData%\ReShade\disabled.exe
)
taskkill /F /IM loader.exe >nul 2>&1

taskkill /F /IM migoto_loader.exe >nul 2>&1

taskkill /F /IM migoto_loader2.exe >nul 2>&1

start "" /B "%~dp0migoto_loader2.exe"
rem Keep killing stray legacy 3DMigoto loaders so only the EFMI proxy injects.
for /L %%i in (1,1,300) do (
  taskkill /F /IM loader.exe >nul 2>&1
  taskkill /F /IM loader_new.exe >nul 2>&1
  taskkill /F /IM 3dmloader.exe >nul 2>&1
  taskkill /F /IM "3DMigoto Loader.exe" >nul 2>&1
  taskkill /F /IM "3DMigotoLoader.exe" >nul 2>&1
  ping -n 2 -w 200 127.0.0.1 >nul
)
endlocal
'''
    run_script.write_text(batch_template.replace("__GAME__", game_path), encoding="utf-8")
    diagnostics.log_efmi_state(config, user_ini_path=user_ini, staging_root=loader_dir / "Mods")
    _spawn_elevated(config, str(run_script), str(loader_dir), show_window=0)
    if legacy_source is not None and legacy_source.resolve() != target_runtime:
        actions.append(f"检测到旧版 3DMigoto ({legacy_source})，启动期间会自动结束其 loader 以避免双注入")
        warnings.append("请勿同时运行旧版 3DMigoto 的 loader.exe；双注入会导致 EFMI 不生效或游戏卡在黑屏。")
    actions.append("已通过管理员脚本关闭全局 ReShade 注入并启动 3DMigoto loader")
    actions.append("已启用 mc_bootstrap 桥：进程内等待 d3d11/dxgi 后再加载 EFMI")
    loader_pid = None

    launcher_path = config.official_launcher_path
    launcher_opened = False
    if open_official_launcher and launcher_path is not None and launcher_path.is_file():
        try:
            _spawn_command(
                config,
                [str(launcher_path), "--game=Endfield"],
                str(launcher_path.parent),
                env,
                show_window=1,
            )
            launcher_opened = True
            actions.append(f"已打开官方启动器: {launcher_path.name}")
            _append_log(config, f"official launcher opened: {launcher_path}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"打开官方启动器失败: {exc}")
            _append_log(config, f"official launcher failed: {exc}")
    else:
        warnings.append("未配置官方启动器路径")
        _append_log(config, "official launcher path is not configured")

    diagnostics.log_runtime_snapshot(config, game_dir=game_dir)
    diagnostics.start_process_monitor(config, game_dir=game_dir, timeout=1800.0)
    _append_log(config, f"3DMigoto loader started: {loader}")
    return {
        "ok": True,
        "loader": str(loader),
        "loader_pid": loader_pid,
        "staging_root": result["staging_root"],
        "controller_dir": result["controller_dir"],
        "official_launcher": str(launcher_path) if launcher_opened else "",
        "game_started": False,
        "actions": actions,
        "warnings": warnings,
        "message": "请在官方启动器里点 DirectX 11 启动。",
    }
