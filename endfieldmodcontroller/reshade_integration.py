"""Integration helpers for a ReShade installation that already lives in the game folder.

The game folder must stay untouched by the generic staging flow, but when ReShade is
already installed next to the game executable there is no reliable way to make its
add-on UI visible from an external runtime directory.  In that specific case
EndfieldModController deploys only three small integration files into the game folder and
keeps a manifest so the operation is fully reversible:

* ``endfieldmodcontroller.addon64``
* ``actions.tsv``
* ``user_ini_path.txt``

Existing files with the same names are backed up first.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

MANIFEST_NAME = "existing_reshade_files.json"
ADDON_NAME = "endfieldmodcontroller.addon64"

CONFLICTING_ADDON_NAMES = ("renodx-dlss.addon64", "renodx-dlss.addon", "renodx-dlss.addon64.disabled")



def built_addon_path() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dist" / "endfieldmodcontroller.addon",
        root / "reshade_addon" / "build" / "endfieldmodcontroller.addon",
        root / "reshade_addon" / "cmake-build" / "endfieldmodcontroller.addon",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def xxmi_config_path(launcher: Path) -> Path | None:
    candidates = [
        launcher.parent.parent.parent / "XXMI Launcher Config.json",
        launcher.parent.parent / "XXMI Launcher Config.json",
        launcher.parent / "XXMI Launcher Config.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def disable_conflicting_addons(game_dir: Path, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Physically hide add-ons known to conflict with the EFMI/ReShade mix.

    ``ReShade.ini`` ``DisabledAddons`` is not reliably honoured by every
    ReShade build, so the conflicting add-on file is renamed instead.  The
    original file is kept next to the game executable and can be restored by
    renaming it back.
    """
    disabled: list[str] = []
    warnings: list[str] = []
    for name in ("renodx-dlss.addon64", "renodx-dlss.addon"):
        source = game_dir / name
        if not source.is_file():
            continue
        target = source.with_name(source.name + ".endfieldmodcontroller.disabled")
        try:
            if target.exists():
                target.unlink()
            source.rename(target)
            disabled.append(f"{source} -> {target}")
            if log is not None:
                log(f"已物理禁用冲突 addon: {source.name} -> {target.name}")
        except OSError as exc:
            warnings.append(f"禁用 {source.name} 失败: {exc}")
    return {"disabled": disabled, "warnings": warnings}


def restore_conflicting_addons(game_dir: Path, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Restore add-ons renamed by :func:`disable_conflicting_addons`."""
    restored: list[str] = []
    warnings: list[str] = []
    for name in ("renodx-dlss.addon64.endfieldmodcontroller.disabled", "renodx-dlss.addon.endfieldmodcontroller.disabled"):
        source = game_dir / name
        if not source.is_file():
            continue
        target_name = name.replace(".endfieldmodcontroller.disabled", "")
        target = game_dir / target_name
        try:
            if target.exists():
                target.unlink()
            source.rename(target)
            restored.append(f"{source} -> {target}")
            if log is not None:
                log(f"已恢复冲突 addon: {target.name}")
        except OSError as exc:
            warnings.append(f"恢复 {target_name} 失败: {exc}")
    return {"restored": restored, "warnings": warnings}


def detect_game_dir(config: AppConfig) -> Path | None:
    game_exe = config.game_exe_path
    if game_exe is not None and game_exe.is_file():
        return game_exe.parent

    launcher = config.xxmi_launcher_path
    if launcher is None:
        return None
    config_path = xxmi_config_path(launcher)
    if config_path is None:
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    folder = data.get("Importers", {}).get("EFMI", {}).get("Importer", {}).get("game_folder")
    if folder:
        path = Path(folder)
        if path.is_dir():
            return path
    # ③ 兜底：自动搜索游戏本体（不硬编码任何盘符/目录）
    from .config import auto_detect_game_dir

    guess = auto_detect_game_dir()
    return Path(guess) if guess else None


def detect_render_api(game_dir: Path) -> str:
    """Heuristically detect the main graphics API from the latest ReShade.log entries."""
    player_log = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "Hypergryph" / "Endfield" / "Player.log"
    if player_log.is_file():
        try:
            player_text = player_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            player_text = ""
        # Endfield may initialize auxiliary Vulkan/DLSS subsystems even when the
        # launcher is told to use DX11.  The explicit "Forcing GfxDevice" line is
        # the API actually selected for the render device, so it must win over the
        # later auxiliary Vulkan lines.
        if "Forcing GfxDevice: Direct3D 11" in player_text or "Forcing GfxDevice: Direct3D11" in player_text:
            return "d3d11"
        if "Forcing GfxDevice: Direct3D 12" in player_text or "Forcing GfxDevice: Direct3D12" in player_text:
            return "d3d12"
        if "Forcing GfxDevice: Vulkan" in player_text:
            return "vulkan"
        if "Vulkan init" in player_text or "VK_LAYER" in player_text:
            return "vulkan"
        if "DirectX 11" in player_text or "D3D11" in player_text:
            return "d3d11"
        if "D3D12" in player_text or "DirectX 12" in player_text:
            return "d3d12"
    log_path = Path(game_dir) / "ReShade.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown"
    if not text:
        return "unknown"
    swap = max(text.rfind("CreateSwapChainForHwnd"), text.rfind("CreateSwapChain"))
    if swap < 0:
        swap = len(text)
    pos11 = text.rfind("D3D11CreateDeviceAndSwapChain", 0, swap + 1)
    pos12 = text.rfind("D3D12CreateDevice", 0, swap + 1)
    if pos12 > pos11:
        return "d3d12"
    if pos11 > pos12:
        return "d3d11"
    overall12 = text.rfind("D3D12CreateDevice")
    overall11 = text.rfind("D3D11CreateDeviceAndSwapChain")
    if overall12 > overall11:
        return "d3d12"
    if overall11 >= 0:
        return "d3d11"
    return "unknown"


def detect_existing_reshade(config: AppConfig) -> dict[str, Any] | None:
    game_dir = detect_game_dir(config)
    if game_dir is None:
        return None
    ini = game_dir / "ReShade.ini"
    proxies = [game_dir / name for name in ("dxgi.dll", "d3d12.dll") if (game_dir / name).is_file()]
    if ini.is_file() and proxies:
        return {
            "game_dir": str(game_dir),
            "ini": str(ini),
            "proxies": [str(path) for path in proxies],
        }
    return None


def manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / MANIFEST_NAME


def _read_manifest(config: AppConfig) -> dict[str, Any]:
    path = manifest_path(config)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _backup_name(path: Path) -> Path:
    return path.with_name(path.name + ".endfieldmodcontroller.bak")


def _install_file(
    target: Path,
    source: Path | None,
    content: str | None = None,
    *,
    owned: bool = False,
    previous_backup: str | None = None,
) -> dict[str, str | None]:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.is_file():
        if owned:
            if previous_backup:
                candidate = Path(previous_backup)
                if candidate.is_file():
                    backup = candidate
        else:
            candidate = _backup_name(target)
            if not candidate.exists():
                shutil.copy2(target, candidate)
            backup = candidate
    if source is not None:
        shutil.copy2(source, target)
    elif content is not None:
        target.write_text(content, encoding="utf-8")
    else:  # pragma: no cover - defensive, callers always pass one
        raise ValueError("source or content is required")
    return {"path": str(target), "backup": str(backup) if backup else None}


def deploy_existing_reshade(
    config: AppConfig,
    info: dict[str, Any] | None = None,
    *,
    controller_dir: Path | None = None,
) -> dict[str, Any]:
    info = info or detect_existing_reshade(config)
    if info is None:
        raise RuntimeError("no existing ReShade installation was detected")
    game_dir = Path(info["game_dir"])
    addon = built_addon_path()
    if addon is None:
        raise RuntimeError("EndfieldModController ReShade add-on is missing")

    actions_source: Path | None = None
    if controller_dir is not None:
        candidate = controller_dir / "actions.tsv"
        if candidate.is_file():
            actions_source = candidate
    if actions_source is None:
        candidate = config.reshade_runtime_path / "actions.tsv"
        if candidate.is_file():
            actions_source = candidate
    if actions_source is None:
        raise RuntimeError("actions.tsv is missing; run prepare before launching")

    previous: dict[str, dict[str, str | None]] = {}
    for entry in _read_manifest(config).get("files", []):
        if isinstance(entry, dict) and entry.get("path"):
            previous[str(entry["path"])] = entry

    def install(target: Path, source: Path | None, content: str | None = None) -> dict[str, str | None]:
        old = previous.get(str(target))
        return _install_file(
            target,
            source,
            content,
            owned=old is not None,
            previous_backup=(old or {}).get("backup"),
        )

    entries: list[dict[str, str | None]] = []
    entries.append(install(game_dir / ADDON_NAME, addon))
    entries.append(install(game_dir / "actions.tsv", actions_source))
    entries.append(install(game_dir / "user_ini_path.txt", None, str(config.user_ini_path)))

    data = {
        "game_dir": str(game_dir),
        "files": entries,
    }
    path = manifest_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return {"manifest": str(path), "game_dir": str(game_dir), "files": entries}


def remove_existing_reshade(config: AppConfig) -> dict[str, Any]:
    path = manifest_path(config)
    if not path.is_file():
        return {"ok": True, "removed": [], "restored": []}
    data = _read_manifest(config)
    removed: list[str] = []
    restored: list[str] = []
    for entry in data.get("files", []):
        if not isinstance(entry, dict):
            continue
        target = Path(str(entry.get("path") or ""))
        backup = Path(str(entry.get("backup") or "")) if entry.get("backup") else None
        if target.is_file():
            try:
                target.unlink()
                removed.append(str(target))
            except OSError:
                continue
        if backup is not None and backup.is_file():
            try:
                shutil.copy2(backup, target)
                backup.unlink()
                restored.append(str(target))
            except OSError:
                pass
    try:
        path.unlink()
    except OSError:
        pass
    return {"ok": True, "removed": removed, "restored": restored}


SAFE_MODE_MANIFEST_NAME = "anti_cheat_safe_mode.json"


def safe_mode_manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / SAFE_MODE_MANIFEST_NAME


def _read_safe_mode_manifest(config: AppConfig) -> dict[str, Any]:
    path = safe_mode_manifest_path(config)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_safe_mode_manifest(config: AppConfig, data: dict[str, Any]) -> None:
    path = safe_mode_manifest_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_mode_active(config: AppConfig) -> bool:
    return safe_mode_manifest_path(config).is_file()


def _looks_like_reshade_dll(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return b"ReShade" in data or b"reshade" in data or b"crosire" in data


def _game_reshade_dll_candidates(config: AppConfig, info: dict[str, Any] | None = None) -> list[Path]:
    info = info or detect_existing_reshade(config)
    if info is None:
        return []
    game_dir = Path(info["game_dir"])
    preferred = [game_dir / "dxgi.dll", game_dir / "d3d12.dll"]
    existing = [Path(item) for item in info.get("proxies", [])]
    result: list[Path] = []
    for path in preferred + existing:
        if path.is_file() and path not in result:
            result.append(path)
    return result


def adopt_game_reshade_dll(config: AppConfig, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copy the game-directory ReShade DLL into runtime/reshade for XXMI injection.

    The existing game-directory ReShade is known to match the installed game and
    supports the same add-on API as the EndfieldModController add-on, so it is safer
    than downloading a different ReShade version.
    """
    candidates = _game_reshade_dll_candidates(config, info)
    source = next((path for path in candidates if _looks_like_reshade_dll(path)), None)
    if source is None:
        raise RuntimeError("no ReShade DLL was found in the game directory")
    target = config.reshade_runtime_path / "ReShade64.dll"
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.is_file():
        candidate = _backup_name(target)
        if not candidate.exists():
            shutil.copy2(target, candidate)
        backup = candidate
    shutil.copy2(source, target)
    data = _read_safe_mode_manifest(config)
    data["adopted_reshade_dll"] = str(target)
    data["adopted_from"] = str(source)
    data["reshade_dll_backup"] = str(backup) if backup else None
    _write_safe_mode_manifest(config, data)
    return {
        "source": str(source),
        "target": str(target),
        "backup": str(backup) if backup else None,
    }


def disable_game_reshade_proxies(config: AppConfig, info: dict[str, Any] | None = None) -> dict[str, Any]:
    info = info or detect_existing_reshade(config)
    if info is None:
        return {"ok": True, "disabled": []}
    game_dir = Path(info["game_dir"])
    entries: list[dict[str, str]] = []
    for proxy in [Path(item) for item in info.get("proxies", [])]:
        if not proxy.is_file():
            continue
        disabled = proxy.with_name(proxy.name + ".endfieldmodcontroller.disabled")
        if disabled.exists():
            disabled.unlink()
        proxy.rename(disabled)
        entries.append({"original": str(proxy), "disabled": str(disabled)})
    data = _read_safe_mode_manifest(config)
    data["game_dir"] = str(game_dir)
    data["disabled_proxies"] = entries
    _write_safe_mode_manifest(config, data)
    return {"ok": True, "game_dir": str(game_dir), "disabled": entries}


def restore_game_reshade_proxies(config: AppConfig) -> dict[str, Any]:
    data = _read_safe_mode_manifest(config)
    restored: list[str] = []
    errors: list[str] = []
    for entry in data.get("disabled_proxies", []):
        if not isinstance(entry, dict):
            continue
        original = Path(str(entry.get("original") or ""))
        disabled = Path(str(entry.get("disabled") or ""))
        if disabled.is_file() and not original.exists():
            try:
                disabled.rename(original)
                restored.append(str(original))
            except OSError as exc:
                errors.append(f"{disabled}: {exc}")
    return {"ok": not errors, "restored": restored, "errors": errors}


def clear_safe_mode_manifest(config: AppConfig) -> None:
    try:
        safe_mode_manifest_path(config).unlink()
    except OSError:
        pass


D3D12_SWAP_MANIFEST_NAME = "dxgi_to_d3d12.json"


def d3d12_swap_manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / D3D12_SWAP_MANIFEST_NAME


def _read_d3d12_swap_manifest(config: AppConfig) -> dict[str, Any]:
    path = d3d12_swap_manifest_path(config)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_d3d12_swap_manifest(config: AppConfig, data: dict[str, Any]) -> None:
    path = d3d12_swap_manifest_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def swap_dxgi_to_d3d12(config: AppConfig, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rename only ``dxgi.dll`` away, leaving a ReShade ``d3d12.dll`` proxy in place.

    Endfield dynamically loads ``d3d12.dll`` even in its DX11 path, so this is a
    common workaround when the anti-cheat rejects the ``dxgi.dll`` module name.
    """
    info = info or detect_existing_reshade(config)
    if info is None:
        raise RuntimeError("no existing ReShade installation was detected")
    game_dir = Path(info["game_dir"])
    dxgi = game_dir / "dxgi.dll"
    d3d12 = game_dir / "d3d12.dll"
    old_data = _read_d3d12_swap_manifest(config)

    disabled: Path | None = None
    if dxgi.is_file():
        disabled = dxgi.with_name("dxgi.dll.endfieldmodcontroller.disabled")
        if disabled.exists():
            disabled.unlink()
        dxgi.rename(disabled)
    elif old_data.get("disabled_dxgi"):
        candidate = Path(str(old_data["disabled_dxgi"]))
        if candidate.is_file():
            disabled = candidate

    marker = game_dir / "dxgi.dll.dlss5oneclick"
    disabled_marker: Path | None = None
    if marker.is_file():
        disabled_marker = marker.with_name("dxgi.dll.dlss5oneclick.endfieldmodcontroller.disabled")
        if disabled_marker.exists():
            disabled_marker.unlink()
        marker.rename(disabled_marker)
    elif old_data.get("disabled_marker"):
        candidate = Path(str(old_data["disabled_marker"]))
        if candidate.is_file():
            disabled_marker = candidate

    created_d3d12 = bool(old_data.get("created_d3d12"))
    if not d3d12.is_file():
        source = disabled
        if source is None:
            source = next((Path(item) for item in info.get("proxies", []) if Path(item).name == "dxgi.dll"), None)
        if source is None or not source.is_file():
            raise RuntimeError("no ReShade DLL is available to use as d3d12.dll")
        shutil.copy2(source, d3d12)
        created_d3d12 = True
    data = {
        "game_dir": str(game_dir),
        "disabled_dxgi": str(disabled) if disabled else None,
        "disabled_marker": str(disabled_marker) if disabled_marker else None,
        "created_d3d12": created_d3d12,
    }
    _write_d3d12_swap_manifest(config, data)
    return {
        "game_dir": str(game_dir),
        "disabled_dxgi": data["disabled_dxgi"],
        "disabled_marker": data["disabled_marker"],
        "d3d12": str(d3d12),
        "created_d3d12": created_d3d12,
    }


def restore_dxgi_from_d3d12(config: AppConfig) -> dict[str, Any]:
    data = _read_d3d12_swap_manifest(config)
    actions: list[str] = []
    errors: list[str] = []
    game_dir = Path(str(data.get("game_dir") or ""))
    disabled = Path(str(data.get("disabled_dxgi"))) if data.get("disabled_dxgi") else None
    if disabled is not None and disabled.is_file():
        original = game_dir / "dxgi.dll"
        if not original.exists():
            try:
                disabled.rename(original)
                actions.append(str(original))
            except OSError as exc:
                errors.append(f"{disabled}: {exc}")
    disabled_marker = Path(str(data.get("disabled_marker"))) if data.get("disabled_marker") else None
    if disabled_marker is not None and disabled_marker.is_file():
        original_marker = game_dir / "dxgi.dll.dlss5oneclick"
        if not original_marker.exists():
            try:
                disabled_marker.rename(original_marker)
                actions.append(str(original_marker))
            except OSError as exc:
                errors.append(f"{disabled_marker}: {exc}")
    if data.get("created_d3d12"):
        d3d12 = game_dir / "d3d12.dll"
        if d3d12.is_file():
            try:
                d3d12.unlink()
                actions.append(f"removed {d3d12}")
            except OSError as exc:
                errors.append(f"{d3d12}: {exc}")
    try:
        d3d12_swap_manifest_path(config).unlink()
    except OSError:
        pass
    return {"ok": not errors, "actions": actions, "errors": errors}


GLOBAL_RESHADE_MANIFEST_NAME = "global_reshade_apps.json"


def global_reshade_apps_path() -> Path:
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    return Path(program_data) / "ReShade" / "ReShadeApps.ini"


def global_reshade_manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / GLOBAL_RESHADE_MANIFEST_NAME


def _parse_global_reshade_apps(text: str) -> list[str]:
    apps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("apps="):
            continue
        value = stripped[5:].strip()
        if not value:
            continue
        for part in value.replace(",", ";").split(";"):
            part = part.strip()
            if part:
                apps.append(part)
    return apps


def disable_global_reshade_for_game(config: AppConfig) -> dict[str, Any]:
    """Remove Endfield.exe from ReShade's global injection list, reversibly.

    A global ReShade install (``C:/ProgramData/ReShade/ReShadeApps.ini``)
    loads ReShade before 3DMigoto and conflicts with it, even if the game
    directory has no dxgi.dll/d3d12.dll proxy.
    """
    path = global_reshade_apps_path()
    if not path.is_file():
        return {"ok": True, "path": str(path), "changed": False, "removed": []}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return {"ok": False, "path": str(path), "message": str(exc)}
    apps = _parse_global_reshade_apps(text)
    game_exe = config.game_exe_path
    game_names = {"endfield.exe"}
    if game_exe is not None:
        game_names.add(game_exe.name.lower())
    removed = [app for app in apps if Path(app).name.lower() in game_names]
    kept = [app for app in apps if Path(app).name.lower() not in game_names]
    if not removed and apps == kept:
        return {"ok": True, "path": str(path), "changed": False, "removed": []}
    backup = path.with_name(path.name + ".endfieldmodcontroller.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    if not kept:
        # An empty Apps= is treated by ReShade as "all applications" by some
        # global installs, so use an explicit non-matching path instead.
        kept = [str(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ReShade" / "disabled.exe")]
    payload = "Apps=" + ";".join(kept) + chr(13) + chr(10)

    path.write_text(payload, encoding="utf-8-sig")
    manifest = {
        "path": str(path),
        "backup": str(backup),
        "original_apps": apps,
        "kept_apps": kept,
        "removed_apps": removed,
    }
    manifest_path = global_reshade_manifest_path(config)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(path), "changed": True, "removed": removed, "kept": kept, "backup": str(backup)}


def restore_global_reshade_apps(config: AppConfig) -> dict[str, Any]:
    manifest_path = global_reshade_manifest_path(config)
    if not manifest_path.is_file():
        return {"ok": True, "restored": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "message": "global_reshade_apps.json is invalid"}
    backup = Path(str(manifest.get("backup") or ""))
    target = Path(str(manifest.get("path") or ""))
    if backup.is_file() and target.parts:
        shutil.copy2(backup, target)
        try:
            backup.unlink()
        except OSError:
            pass
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return {"ok": True, "restored": [str(target)]}


def integration_state(config: AppConfig) -> dict[str, Any]:
    info = detect_existing_reshade(config)
    if info is None:
        return {"detected": False}
    game_dir = Path(info["game_dir"])
    return {
        "detected": True,
        "game_dir": str(game_dir),
        "addon": (game_dir / ADDON_NAME).is_file(),
        "actions": (game_dir / "actions.tsv").is_file(),
        "user_ini": (game_dir / "user_ini_path.txt").is_file(),
        "manifest": manifest_path(config).is_file(),
    }


# ---------------------------------------------------------------------------
# Game directory injection audit
# ---------------------------------------------------------------------------
# Third-party loaders (older EndfieldModController builds, unrelated mod installers)
# drop a small proxy DLL next to the game executable.  Windows then loads that
# proxy instead of the real system module, the proxy forwards the exports *and*
# silently loads everything found in ``<game>/plugin/*.dll``.  That hides the
# genuine DLL and injects arbitrary code into the game process, so it must be
# detected and removed before any crash report can be trusted.
LOADER_PROXY_MODULES = (
    "dxgi.dll",
    "d3d12.dll",
    "d3d11.dll",
    "d3dcompiler_47.dll",
    "vulkan-1.dll",
    "nvapi64.dll",
    "winmm.dll",
    "version.dll",
)

LOADER_PROXY_DISABLED_SUFFIX = ".loader.endfieldmodcontroller.disabled"
PLUGIN_DISABLED_SUFFIX = ".endfieldmodcontroller.disabled"
GAME_INJECTION_MANIFEST = "game_dir_injections.json"
PLUGIN_DIR_NAME = "plugin"
_BOOTSTRAP_MARKERS = (b"[LOADER] started", b"no plugin dlls found", b"[LOADER] loading")


def game_injection_manifest_path(config: AppConfig) -> Path:
    return Path(config.runtime_path) / GAME_INJECTION_MANIFEST


def looks_like_loader_proxy(path: Path) -> bool:
    """Return True when *path* is a loader proxy rather than a genuine module.

    The check is marker based on purpose: a real ReShade ``d3d12.dll`` or the
    original Microsoft ``d3dcompiler_47.dll`` must never be reported.
    """
    try:
        with path.open("rb") as handle:
            blob = handle.read(512 * 1024)
    except OSError:
        return False
    return any(marker in blob for marker in _BOOTSTRAP_MARKERS)


def _resolve_game_dir(config: AppConfig, game_dir: Path | None = None) -> Path | None:
    if game_dir is not None:
        return Path(game_dir)
    return detect_game_dir(config)


def audit_game_dir_injections(config: AppConfig, game_dir: Path | None = None) -> dict[str, Any]:
    """Report foreign injection artifacts that live in the game directory."""
    target = _resolve_game_dir(config, game_dir)
    if target is None:
        return {"ok": False, "message": "没有找到游戏目录", "suspicious": [], "disabled": []}

    suspicious: list[dict[str, Any]] = []
    disabled: list[dict[str, Any]] = []
    for name in LOADER_PROXY_MODULES:
        path = target / name
        if path.is_file() and looks_like_loader_proxy(path):
            backup = path.with_name(name + ".bak")
            suspicious.append({
                "kind": "loader_proxy",
                "name": name,
                "path": str(path),
                "size": path.stat().st_size,
                "backup": str(backup) if backup.is_file() else None,
                "detail": "第三方加载器 DLL：转发系统导出并注入 plugin/*.dll",
            })
        parked = path.with_name(name + LOADER_PROXY_DISABLED_SUFFIX)
        if parked.is_file():
            backup = path.with_name(name + ".bak")
            disabled.append({
                "kind": "loader_proxy",
                "name": name,
                "disabled": str(parked),
                "original_present": path.is_file(),
                "backup": str(backup) if backup.is_file() else None,
            })

    plugin_dir = target / PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        for payload in sorted(plugin_dir.glob("*.dll")):
            suspicious.append({
                "kind": "plugin_payload",
                "name": payload.name,
                "path": str(payload),
                "size": payload.stat().st_size,
                "backup": None,
                "detail": "会被加载器代理注入游戏进程的插件 DLL",
            })
        for parked in sorted(plugin_dir.glob("*" + PLUGIN_DISABLED_SUFFIX)):
            original = plugin_dir / parked.name[: -len(PLUGIN_DISABLED_SUFFIX)]
            disabled.append({
                "kind": "plugin_payload",
                "name": original.name,
                "disabled": str(parked),
                "original_present": original.is_file(),
                "backup": None,
            })

    return {
        "ok": not suspicious,
        "game_dir": str(target),
        "suspicious": suspicious,
        "disabled": disabled,
    }



def disable_game_dir_injections(config: AppConfig, game_dir: Path | None = None) -> dict[str, Any]:
    """Park loader proxies (and their ``plugin`` payloads) next to the game.

    The genuine module is restored from ``<name>.bak`` when such a backup
    exists, so the game directory returns to a state the official launcher can
    verify.  Everything is recorded in ``runtime/game_dir_injections.json`` so
    :func:`restore_game_dir_injections` can undo it.
    """
    target = _resolve_game_dir(config, game_dir)
    if target is None:
        return {"ok": False, "message": "没有找到游戏目录", "disabled": [], "restored": [], "plugins": [], "warnings": []}

    disabled: list[str] = []
    restored: list[str] = []
    plugins: list[str] = []
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []

    for name in LOADER_PROXY_MODULES:
        path = target / name
        if not path.is_file() or not looks_like_loader_proxy(path):
            continue
        parked = path.with_name(name + LOADER_PROXY_DISABLED_SUFFIX)
        try:
            if parked.exists():
                parked.unlink()
            path.rename(parked)
            disabled.append(str(parked))
        except OSError as exc:
            warnings.append(f"{name}: 无法重命名代理 DLL: {exc}")
            continue
        restored_from: str | None = None
        backup = path.with_name(name + ".bak")
        if backup.is_file():
            try:
                shutil.copy2(backup, path)
                restored.append(str(path))
                restored_from = str(backup)
            except OSError as exc:
                warnings.append(f"{name}: 恢复原文件失败: {exc}")
        entries.append({
            "name": name,
            "disabled": str(parked),
            "restored_from": restored_from,
        })

    plugin_dir = target / PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        for payload in sorted(plugin_dir.glob("*.dll")):
            parked = payload.with_name(payload.name + PLUGIN_DISABLED_SUFFIX)
            try:
                if parked.exists():
                    parked.unlink()
                payload.rename(parked)
                plugins.append(str(parked))
            except OSError as exc:
                warnings.append(f"{payload.name}: 无法重命名插件 DLL: {exc}")

    if entries or plugins:
        data = {
            "game_dir": str(target),
            "entries": entries,
            "plugins": plugins,
        }
        manifest_path = game_injection_manifest_path(config)
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            warnings.append(f"写入清单失败: {exc}")

    return {
        "ok": not warnings,
        "game_dir": str(target),
        "disabled": disabled,
        "restored": restored,
        "plugins": plugins,
        "warnings": warnings,
    }


def restore_game_dir_injections(config: AppConfig) -> dict[str, Any]:
    """Undo :func:`disable_game_dir_injections` using its manifest."""
    manifest_path = game_injection_manifest_path(config)
    if not manifest_path.is_file():
        return {"ok": False, "message": "没有找到注入清理记录", "restored": [], "warnings": []}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": f"读取清单失败: {exc}", "restored": [], "warnings": []}

    restored: list[str] = []
    warnings: list[str] = []
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        parked = Path(str(entry.get("disabled") or ""))
        if not parked.is_file():
            continue
        name = parked.name[: -len(LOADER_PROXY_DISABLED_SUFFIX)]
        target = parked.with_name(name)
        restored_from = entry.get("restored_from")
        try:
            if target.is_file() and restored_from:
                backup = Path(str(restored_from))
                if backup.is_file() and target.stat().st_size == backup.stat().st_size:
                    target.unlink()
            if target.exists():
                target.unlink()
            parked.rename(target)
            restored.append(str(target))
        except OSError as exc:
            warnings.append(f"{name}: {exc}")
    for item in data.get("plugins", []):
        parked = Path(str(item))
        if not parked.is_file():
            continue
        target = parked.with_name(parked.name[: -len(PLUGIN_DISABLED_SUFFIX)])
        try:
            if target.exists():
                target.unlink()
            parked.rename(target)
            restored.append(str(target))
        except OSError as exc:
            warnings.append(f"{target.name}: {exc}")

    if not warnings:
        try:
            manifest_path.unlink()
        except OSError:
            pass
    return {"ok": not warnings, "restored": restored, "warnings": warnings}
