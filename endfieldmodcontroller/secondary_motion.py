"""SecondaryMotion（乳摇 / 次级运动管理器）集成。

这个第三方工具靠替换游戏目录里的两个 proxy DLL 注入自己的 loader，再由 loader
加载 ``plugin\\sbm.dll``：

    d3dcompiler_47.dll  (proxy, 十几 KB)  +  d3dcompiler_47.dll.bak  (原版)
    vulkan-1.dll        (proxy, 几十 KB)  +  vulkan-1.dll.bak        (原版)
    plugin\\sbm.dll     (插件本体, 由 loader 加载)

本模块只做四件事：报状态、缺了就补齐、一键卸掉、启动它自己的 Manager.exe。
所有写入都是可回滚的（原版一律留 ``.bak``）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

PROXY_NAMES = ("d3dcompiler_47.dll", "vulkan-1.dll")
# 正版系统 DLL 都是几 MB，proxy 只有十几~几十 KB
PROXY_MAX_SIZE = 200_000
PLUGIN_NAME = "sbm.dll"


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def game_dir(config: AppConfig) -> Path | None:
    from . import reshade_integration

    return reshade_integration.detect_game_dir(config)


def _tool_dir(config: AppConfig) -> Path | None:
    return config.secondary_motion_tool_dir


def _is_proxy(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size < PROXY_MAX_SIZE
    except OSError:
        return False


def status(config: AppConfig) -> dict[str, Any]:
    """工具 / 注入 / 运行时的当前状态，供 UI 显示。"""
    root = config.secondary_motion_root
    tool = _tool_dir(config)
    exe = config.secondary_motion_exe
    result: dict[str, Any] = {
        "tool_root": str(root) if root else "",
        "tool_dir": str(tool) if tool else "",
        "manager_exe": str(exe) if exe else "",
        "manager_exists": bool(exe and exe.is_file()),
        "tool_version": _tool_version(root) if root else "",
        "pack_version": _pack_version(tool) if tool else "",
        "game_dir": "",
        "proxies": {},
        "injected": False,
        "plugin_exists": False,
        "backup_ok": False,
        "runtime": {},
        "log_tail": [],
    }
    game = game_dir(config)
    if game is None:
        return result
    result["game_dir"] = str(game)

    for name in PROXY_NAMES:
        target = game / name
        backup = game / f"{name}.bak"
        installed = _is_proxy(target)
        result["proxies"][name] = {
            "installed": installed,
            "size": target.stat().st_size if target.is_file() else 0,
            "backup": backup.is_file(),
        }
    result["injected"] = all(item["installed"] for item in result["proxies"].values())
    result["backup_ok"] = all(item["backup"] for item in result["proxies"].values())

    plugin = game / "plugin" / PLUGIN_NAME
    result["plugin_exists"] = plugin.is_file()

    data_dir = game / "SecondaryMotion"
    status_file = data_dir / "runtime" / "runtime_status.json"
    if status_file.is_file():
        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
            payload["age_s"] = round(time.time() - status_file.stat().st_mtime, 1)
            result["runtime"] = payload
        except (OSError, json.JSONDecodeError):
            result["runtime"] = {}
    log_file = game / "plugin" / "sbm_log.txt"
    if log_file.is_file():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            result["log_tail"] = lines[-6:]
        except OSError:
            pass
    return result


def _version_from_name(name: str) -> str:
    """从 ShakingBreastManager-v2.3.5-ZH-win-x64 这种目录名里抠版本号。"""
    import re

    match = re.search(r"[vV](\d+(?:\.\d+)+)", name or "")
    return match.group(0) if match else ""


def _tool_version(root: Path | None) -> str:
    """版本优先读目录里的 version.txt（内嵌副本靠它记住发布版本号），再退回目录名。"""
    if root is None:
        return ""
    for base in (root, root / "SecondaryMotion"):
        version_file = base / "version.txt"
        if version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                text = ""
            if text:
                return text
    return _version_from_name(root.name)


def _pack_version(tool_dir: Path | None) -> str:
    if tool_dir is None:
        return ""
    exe = tool_dir / "SecondaryMotion.Manager.exe"
    if not exe.is_file():
        return ""
    version_file = tool_dir / "version.txt"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def ensure_injection(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """补齐乳摇注入：两个 proxy + plugin\\sbm.dll。已装的不动，缺失才补。"""
    actions: list[str] = []
    warnings: list[str] = []
    tool = _tool_dir(config)
    game = game_dir(config)
    if tool is None:
        return {"ok": False, "message": "未找到 SecondaryMotion 工具目录", "actions": [], "warnings": []}
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录", "actions": [], "warnings": []}

    source_dir = tool / "plugin"
    for name in PROXY_NAMES:
        target = game / name
        source = source_dir / name
        if not source.is_file():
            warnings.append(f"工具包缺少 {name}，跳过")
            continue
        if _is_proxy(target):
            continue
        if target.is_file():
            backup = game / f"{name}.bak"
            if not backup.is_file():
                shutil.copy2(target, backup)
                actions.append(f"备份原版 {name} -> {name}.bak")
        elif (game / f"{name}.bak").is_file():
            # 原版已在 .bak，直接放 proxy
            pass
        try:
            shutil.copy2(source, target)
            actions.append(f"安装注入 {name}")
        except OSError as exc:
            warnings.append(f"写入 {name} 失败: {exc}")

    plugin_target = game / "plugin" / PLUGIN_NAME
    plugin_source = source_dir / PLUGIN_NAME
    if not plugin_target.is_file() and plugin_source.is_file():
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plugin_source, plugin_target)
        actions.append(f"安装插件 plugin\\{PLUGIN_NAME}")

    for action in actions:
        _log(log, action)
    for warning in warnings:
        _log(log, f"WARN {warning}")
    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "injected": status(config)["injected"],
    }


def remove_injection(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """卸掉注入：删除 proxy、把 .bak 还原成正式 DLL、移除 plugin\\sbm.dll。"""
    actions: list[str] = []
    warnings: list[str] = []
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录", "actions": [], "warnings": []}

    for name in PROXY_NAMES:
        target = game / name
        backup = game / f"{name}.bak"
        try:
            if _is_proxy(target):
                target.unlink()
                actions.append(f"移除注入 {name}")
            if backup.is_file():
                if target.exists():
                    target.unlink()
                shutil.copy2(backup, target)
                actions.append(f"还原原版 {name}")
        except OSError as exc:
            warnings.append(f"处理 {name} 失败: {exc}")

    plugin_target = game / "plugin" / PLUGIN_NAME
    if plugin_target.is_file():
        try:
            disabled = plugin_target.with_suffix(".dll.mc_disabled")
            shutil.move(str(plugin_target), str(disabled))
            actions.append(f"停用 plugin\\{PLUGIN_NAME}")
        except OSError as exc:
            warnings.append(f"停用插件失败: {exc}")

    for action in actions:
        _log(log, action)
    for warning in warnings:
        _log(log, f"WARN {warning}")
    return {"ok": not warnings, "actions": actions, "warnings": warnings}


def launch_manager(config: AppConfig) -> dict[str, Any]:
    """启动它原生的 Manager.exe（保持工具自身界面不变）。"""
    exe = config.secondary_motion_exe
    if exe is None or not exe.is_file():
        return {"ok": False, "message": "未找到 SecondaryMotion.Manager.exe，请在设置页配置工具目录"}
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=creationflags)
    except OSError as exc:
        return {"ok": False, "message": f"启动失败: {exc}"}
    return {"ok": True, "exe": str(exe)}


def import_pack(config: AppConfig, archive: Path, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """用新的发布包（zip）更新工具本体，保留 logs / presets / data / settings.json。

    新包解压后如果顶层只有一层目录，会自动下钻到含 SecondaryMotion.Manager.exe 的那层。
    """
    import tempfile
    import zipfile

    archive = Path(archive)
    if not archive.is_file():
        return {"ok": False, "message": f"压缩包不存在: {archive}"}
    tool = _tool_dir(config)
    if tool is None:
        return {"ok": False, "message": "请先在设置页配置 SecondaryMotion 工具目录"}

    keep = ("logs", "presets", "data", "runtime")
    keep_files = ("settings.json", "default_lang.txt")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = tool.parent / f"_backup_{stamp}"

    try:
        with tempfile.TemporaryDirectory(prefix="mc-sbm-") as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp_path)
            # 下钻到含 exe 的目录
            root = tmp_path
            for _ in range(3):
                if (root / "SecondaryMotion.Manager.exe").is_file():
                    break
                children = [c for c in root.iterdir() if c.is_dir()]
                if len(children) == 1:
                    root = children[0]
                else:
                    break
            if not (root / "SecondaryMotion.Manager.exe").is_file():
                return {"ok": False, "message": "压缩包里没找到 SecondaryMotion.Manager.exe"}

            shutil.copytree(tool, backup)  # 先整体备份旧版
            for child in list(tool.iterdir()):
                if child.name in keep or child.name in keep_files:
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            shutil.copytree(root, tool, dirs_exist_ok=True)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "message": f"更新失败: {exc}"}

    _log(log, f"SecondaryMotion 已更新，旧版备份在 {backup}")
    return {"ok": True, "backup": str(backup), "tool_dir": str(tool), "archive": str(archive)}
