"""Persistent diagnostics, process monitoring and crash log bundles."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

_SESSION_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
_LOCK = threading.RLock()
_MONITOR_LOCK = threading.Lock()
_MONITOR_THREAD: threading.Thread | None = None


def open_path(config: Any, path: Path) -> dict[str, Any]:
    """在资源管理器里定位到指定文件/目录。

    ⚠️ 这个函数**曾经缺失**：`api.open_path_in_explorer()` 与 `api.open_logs_dir()` 一直在调
    `diagnostics.open_path(...)`，但模块里根本没有它 —— 于是崩溃弹窗上点"打开路径"必然报
    `AttributeError: module 'endfieldmodcontroller.diagnostics' has no attribute 'open_path'`
    （用户 2026-09-29 实测报的）。

    安全约束与 `api.open_path` 保持一致（那条路径 2026-10-01 加固过）：
      * 只允许打开本程序自己的目录（runtime / 配置目录 / Mod 库）与游戏目录；
      * **不直接运行可执行文件** —— Windows 上 `os.startfile` 对 exe/bat/lnk 是"执行"，
        页面一旦被注入脚本就是任意代码执行；这里一律用 `explorer /select,` 定位。
    """
    import subprocess

    target = Path(path).expanduser()
    try:
        target = target.resolve()
    except OSError as exc:
        return {"ok": False, "message": f"路径无法解析: {exc}"}
    if not target.exists():
        return {"ok": False, "message": f"路径不存在: {target}"}

    def _under(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            return False

    allowed = [config.runtime_path, config.base_dir, config.library_path]
    try:
        from . import reshade_integration

        game_dir = reshade_integration.detect_game_dir(config)
    except Exception:  # noqa: BLE001
        game_dir = None
    if game_dir is not None:
        allowed.append(game_dir)
    if not any(_under(target, root) for root in allowed):
        return {"ok": False, "message": f"拒绝打开程序目录之外的路径: {target}"}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        # 目录用 /select 也能定位（父目录里高亮该项）；文件则高亮文件本身
        subprocess.Popen(["explorer", f"/select,{target}"], creationflags=creationflags)
    except OSError as exc:
        return {"ok": False, "message": f"打开失败: {exc}"}
    return {"ok": True, "path": str(target)}


def logs_dir(config: Any) -> Path:
    return Path(config.runtime_path) / "logs"


def session_log_path(config: Any) -> Path:
    return logs_dir(config) / f"endfieldmodcontroller-{_SESSION_ID}.log"


def daily_log_path(config: Any) -> Path:
    return logs_dir(config) / f"endfieldmodcontroller-{datetime.now().strftime('%Y%m%d')}.log"


def launch_log_path(config: Any) -> Path:
    return Path(config.runtime_path) / "launch.log"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", errors="replace") as handle:
        handle.write(line.rstrip() + "\n")


def log_event(config: Any, message: str, *, level: str = "INFO", category: str = "app", **fields: Any) -> None:
    """Append one diagnostic line to session/daily/legacy launch logs."""
    try:
        suffix = " | " + " ".join(f"{key}={value}" for key, value in fields.items()) if fields else ""
        line = f"{_stamp()} [{level.upper():<5}] [{category}] {message}{suffix}"
        with _LOCK:
            _append_line(logs_dir(config) / f"endfieldmodcontroller-{datetime.now().strftime('%Y%m%d')}.log", line)
            _append_line(session_log_path(config), line)
            _append_line(launch_log_path(config), line)
    except Exception:  # noqa: BLE001 - diagnostics must never break launch
        return


def log_exception(config: Any, message: str, exc: BaseException, *, category: str = "error") -> None:
    log_event(config, message, level="ERROR", category=category, error=repr(exc))
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_event(config, "traceback:\n" + tb, level="ERROR", category=category)
    except Exception:  # noqa: BLE001
        pass


def _file_info(path: Path, *, hash_limit: int = 8 * 1024 * 1024) -> str:
    try:
        if not path.is_file():
            return "missing"
        stat = path.stat()
        info = f"{stat.st_size} bytes mtime={datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}"
        if stat.st_size <= hash_limit:
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            info += f" sha256={digest.hexdigest()}"
        return info
    except OSError as exc:
        return f"unreadable: {exc}"


def _read_text(path: Path, limit: int = 8192) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _log_ini_section(config: Any, path: Path, section: str, *, max_lines: int = 80) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    current = ""
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].lower()
            continue
        if current == section.lower():
            kept.append(stripped)
            if len(kept) >= max_lines:
                break
    if kept:
        log_event(config, f"{path.name} [{section}]", category="snapshot", content="; ".join(kept))


def log_system_info(config: Any) -> None:
    try:
        import ctypes
        is_admin = bool(os.name == "nt" and ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        is_admin = False
    log_event(
        config,
        "系统信息",
        category="diag",
        platform=platform.platform(),
        python=sys.version.replace("\n", " "),
        executable=sys.executable,
        admin=is_admin,
        pid=os.getpid(),
    )


def log_environment(config: Any) -> None:
    for key, value in sorted(os.environ.items()):
        if key.upper().startswith(("RESHADE", "ENDFIELDMODCONTROLLER", "XXMI", "EFMI")):
            log_event(config, "环境变量", category="diag", key=key, value=value)
    try:
        log_event(
            config,
            "应用配置",
            category="diag",
            library=config.library_path,
            staging=config.staging_mods_path,
            runtime=config.runtime_path,
            controller=config.controller_dir,
            user_ini=config.user_ini_path,
            migoto_loader=config.migoto_loader_path,
            reshade_dll=config.reshade_dll_path,
            selected=",".join(str(item) for item in (config.selected_mods or [])),
        )
    except Exception as exc:  # noqa: BLE001
        log_exception(config, "读取应用配置失败", exc, category="diag")


def _process_lines(image_name: str, timeout: float = 4.0) -> list[str]:
    if os.name != "nt":
        return []
    command = ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
    except Exception:  # noqa: BLE001
        return []
    return result.stdout.splitlines()


def log_runtime_snapshot(config: Any, game_dir: Path | None = None) -> None:
    """Log the files that commonly decide whether injection works."""
    try:
        runtime = Path(config.runtime_path)
        loader = config.migoto_loader_path
        loader_dir = Path(loader).parent if loader else runtime / "migoto"
        log_event(config, "运行时快照开始", category="snapshot")
        candidate_files = [
            runtime / "launch.log",
            loader_dir / "loader.exe",
            loader_dir / "migoto_loader2.exe",
            loader_dir / "loader_debug.log",
            loader_dir / "mc_bootstrap.dll",
            loader_dir / "mc_bootstrap.log",
            loader_dir / "d3d11.dll",
            loader_dir / "d3dcompiler_47.dll",
            loader_dir / "d3dx.ini",
            loader_dir / "d3dx_user.ini",
            loader_dir / "inject_order.txt",
            loader_dir / "actions.tsv",
            loader_dir / "user_ini_path.txt",
            loader_dir / "ReShade.ini",
            loader_dir / "endfieldmodcontroller.addon.log",
            loader_dir / "Addons" / "endfieldmodcontroller.addon",
            runtime / "reshade" / "ReShade64.dll",
            runtime / "reshade" / "actions.tsv",
            runtime / "reshade" / "Addons" / "endfieldmodcontroller.addon",
        ]
        if game_dir is not None:
            candidate_files.extend([
                game_dir / "Endfield.exe",
                game_dir / "d3d12.dll",
                game_dir / "dxgi.dll",
                game_dir / "d3d11.dll",
                game_dir / "ReShade.ini",
                game_dir / "ReShade.log",
                game_dir / "actions.tsv",
                game_dir / "user_ini_path.txt",
                game_dir / "endfieldmodcontroller.addon",
                game_dir / "endfieldmodcontroller.addon64",
                game_dir / "endfieldmodcontroller.addon.log",
                game_dir / "终末地EE.addon64",
                game_dir / "renodx-dlss.addon64",
                game_dir / "renodx-dlss.addon64.endfieldmodcontroller.disabled",
            ])
        seen: set[str] = set()
        for path in candidate_files:
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            if path.exists():
                log_event(config, "文件快照", category="snapshot", path=path, info=_file_info(path))
        if game_dir is not None:
            try:
                from . import reshade_integration

                audit = reshade_integration.audit_game_dir_injections(config, game_dir)
            except Exception as exc:  # noqa: BLE001
                log_event(config, "游戏目录注入审计失败", level="WARN", category="snapshot", error=str(exc))
            else:
                for item in audit.get("suspicious", []):
                    log_event(
                        config,
                        "游戏目录存在第三方注入 DLL（会污染所有崩溃报告）",
                        level="WARN",
                        category="snapshot",
                        kind=item.get("kind"),
                        path=item.get("path"),
                        size=item.get("size"),
                        backup=item.get("backup"),
                    )
                for item in audit.get("disabled", []):
                    log_event(
                        config,
                        "游戏目录注入 DLL 已禁用",
                        category="snapshot",
                        kind=item.get("kind"),
                        disabled=item.get("disabled"),
                        original_present=item.get("original_present"),
                        backup=item.get("backup"),
                    )
        if game_dir is not None and (game_dir / "ReShade.ini").is_file():
            _log_ini_section(config, game_dir / "ReShade.ini", "ADDON")
        if (loader_dir / "ReShade.ini").is_file():
            _log_ini_section(config, loader_dir / "ReShade.ini", "ADDON")
        if game_dir is not None and (game_dir / "user_ini_path.txt").is_file():
            log_event(config, "游戏目录 user_ini_path.txt", category="snapshot", value=_read_text(game_dir / "user_ini_path.txt", 512).strip())
        if (loader_dir / "user_ini_path.txt").is_file():
            log_event(config, "loader user_ini_path.txt", category="snapshot", value=_read_text(loader_dir / "user_ini_path.txt", 512).strip())
        if (loader_dir / "inject_order.txt").is_file():
            log_event(config, "inject_order.txt", category="snapshot", value=_read_text(loader_dir / "inject_order.txt", 512).strip())
        for image in ("Endfield.exe", "migoto_loader2.exe", "loader.exe", "XXMI Launcher.exe"):
            rows = _process_lines(image)
            if rows:
                log_event(config, "进程", category="snapshot", image=image, lines=" | ".join(rows[:5]))
        log_event(config, "运行时快照完成", category="snapshot")
    except Exception as exc:  # noqa: BLE001
        log_exception(config, "生成运行时快照失败", exc, category="snapshot")


def begin_launch(config: Any, mode: str, game_dir: Path | None = None) -> None:
    log_event(config, "=" * 20 + f" 启动流程开始 ({mode}) " + "=" * 20, category="launch")
    log_system_info(config)
    log_environment(config)
    log_runtime_snapshot(config, game_dir=game_dir)


def _find_process_ids(image_name: str) -> list[int]:
    ids: list[int] = []
    for line in _process_lines(image_name):
        try:
            row = next(csv.reader([line]))
            if len(row) >= 2 and row[1].strip().isdigit():
                ids.append(int(row[1].strip()))
        except Exception:  # noqa: BLE001
            continue
    return ids


def _process_command_line(pid: int) -> str:
    if os.name != "nt":
        return ""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=creationflags,
        )
        text = (ps.stdout or "").strip()
        if text:
            return text.splitlines()[-1].strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        result = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={int(pid)}", "get", "CommandLine", "/value"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=creationflags,
        )
    except Exception:  # noqa: BLE001
        return ""
    for line in (result.stdout or "").splitlines():
        if line.lower().startswith("commandline="):
            return line.split("=", 1)[1].strip()
    return ""


_KERNEL32 = None


def _kernel32():
    """带正确 argtypes/restype 的 kernel32。

    2026-10-01 修：原先直接用 `ctypes.windll.kernel32` 且不声明签名，ctypes 会按
    `c_int` 解释返回值 —— 64 位下进程句柄往往远大于 2³¹，被截断成负数/0 之后
    `WaitForSingleObject` 永远判不出"进程已退出"，进程监视只能空转到超时，
    崩溃取证整条链静默失效（界面只留一行"进程监视异常"）。
    """
    global _KERNEL32
    if _KERNEL32 is not None:
        return _KERNEL32
    import ctypes
    from ctypes import wintypes

    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    lib.OpenProcess.restype = wintypes.HANDLE
    lib.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    lib.WaitForSingleObject.restype = wintypes.DWORD
    lib.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    lib.GetExitCodeProcess.restype = wintypes.BOOL
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    lib.CloseHandle.restype = wintypes.BOOL
    _KERNEL32 = lib
    return lib


def _open_process_handle(pid: int) -> int | None:
    if os.name != "nt":
        return None
    handle = _kernel32().OpenProcess(0x1000 | 0x00100000, False, int(pid))
    return int(handle) if handle else None


def _process_exited(handle: int) -> bool:
    if os.name != "nt":
        return True
    return _kernel32().WaitForSingleObject(handle, 0) == 0


def _process_exit_code(handle: int) -> int | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    code = wintypes.DWORD(0)
    if _kernel32().GetExitCodeProcess(handle, ctypes.byref(code)):
        return int(code.value)
    return None


def _close_handle(handle: int | None) -> None:
    if handle and os.name == "nt":
        _kernel32().CloseHandle(handle)


def _capture_tail(source: Path, target: Path, *, lines: int = 300) -> None:
    try:
        if not source.is_file():
            return
        content = source.read_text(encoding="utf-8", errors="replace").splitlines()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(content[-lines:]) + "\n", encoding="utf-8", errors="replace")
    except OSError:
        return


def _capture_postmortem(config: Any, game_dir: Path | None, reason: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = logs_dir(config)
    loader = config.migoto_loader_path
    loader_dir = Path(loader).parent if loader else Path(config.runtime_path) / "migoto"
    _capture_tail(game_dir / "ReShade.log" if game_dir else Path("__missing__"), target_dir / f"ReShade-{stamp}.log", lines=500)
    _capture_tail(loader_dir / "loader_debug.log", target_dir / f"loader_debug-{stamp}.log", lines=500)
    _capture_tail(loader_dir / "mc_bootstrap.log", target_dir / f"mc_bootstrap-{stamp}.log", lines=500)
    _capture_tail(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "loader_debug.log", target_dir / f"loader_debug-system32-{stamp}.log", lines=500)
    _capture_tail(loader_dir / "d3d11_log.txt", target_dir / f"d3d11_log-{stamp}.log", lines=500)
    _capture_windows_events(config)
    log_efmi_state(config, user_ini_path=loader_dir / "d3dx_user.ini", staging_root=loader_dir / "Mods")
    bundle = create_diagnostic_bundle(config, game_dir=game_dir, note=f"auto-postmortem: {reason}")
    log_event(config, "已生成诊断包", category="crash", path=bundle, reason=reason)


def _monitor_process(config: Any, game_dir: Path | None, image_name: str, timeout: float) -> None:
    log_event(config, "进程监视启动", category="monitor", image=image_name, timeout=timeout)
    found_pid: int | None = None
    handle: int | None = None
    started = time.monotonic()
    try:
        while time.monotonic() - started < timeout:
            ids = _find_process_ids(image_name)
            if ids:
                pid = ids[0]
                if found_pid != pid:
                    # 换了 PID（游戏退出后又被启动器拉起）：先把上一个进程句柄关掉再开新的，
                    # 否则每次重启都泄漏一个句柄（2026-10-01 修）。
                    _close_handle(handle)
                    found_pid = pid
                    handle = _open_process_handle(pid)
                    command_line = _process_command_line(pid)
                    log_event(config, "检测到游戏进程", category="monitor", image=image_name, pid=pid, command_line=command_line)
                if handle and _process_exited(handle):
                    code = _process_exit_code(handle)
                    log_event(config, "游戏进程已退出", category="crash", image=image_name, pid=pid, exit_code=code)
                    _close_handle(handle)
                    _capture_postmortem(config, game_dir, f"exit_code={code}")
                    return
            elif found_pid is not None:
                log_event(config, "游戏进程已结束", category="crash", image=image_name, pid=found_pid)
                _close_handle(handle)
                _capture_postmortem(config, game_dir, "process_disappeared")
                return
            time.sleep(0.5 if time.monotonic() - started < 60 else 1.0)
        log_event(config, "进程监视超时", category="monitor", image=image_name, timeout=timeout)
        _capture_postmortem(config, game_dir, "monitor_timeout")
    except Exception as exc:  # noqa: BLE001
        log_exception(config, "进程监视异常", exc, category="monitor")


def start_process_monitor(config: Any, *, game_dir: Path | None = None, image_name: str = "Endfield.exe", timeout: float = 1800.0) -> bool:
    global _MONITOR_THREAD
    if os.name != "nt":
        log_event(config, "非 Windows 平台，跳过进程监视", category="monitor")
        return False
    with _MONITOR_LOCK:
        if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
            log_event(config, "进程监视已在运行，跳过重复启动", category="monitor")
            return False
        thread = threading.Thread(
            target=_monitor_process,
            args=(config, game_dir, image_name, timeout),
            name="endfieldmodcontroller-process-monitor",
            daemon=True,
        )
        _MONITOR_THREAD = thread
        thread.start()
        return True


# ---------------------------------------------------------------------------
# 自检结论留痕：Mod 资源冲突（崩溃归因要用它）
# ---------------------------------------------------------------------------
MOD_CONFLICT_STATE_NAME = Path("_state") / "mod_conflicts.json"


def mod_conflict_state_path(config: Any) -> Path:
    return Path(config.runtime_path) / MOD_CONFLICT_STATE_NAME


def record_mod_conflicts(config: Any, *, ok: bool, detail: str = "",
                         conflicts: list[str] | None = None,
                         groups: list[dict[str, Any]] | None = None) -> None:
    """把**本次自检**的 Mod 冲突结论落盘。

    为什么要落盘（2026-09-30）：崩溃监视跑在另一个线程（且常在用户下次开程序时才
    收集现场），它要判断"这次崩溃是不是 Mod 冲突造成的"，只能靠这份留痕 —— 否则
    弹窗只能笼统地说"异常退出"，用户不知道该先去清 Mod 还是去查注入。

    `groups`（2026-10-01 新增）：**结构化**冲突组（每组含涉及的 Mod 名 + 库内 id）——
    前端「选择要保留的 Mod」弹窗用它渲染"每组一个下拉框"，选完调
    `api.resolve_mod_conflicts()` 自动取消勾选其余的那些。`conflicts`（字符串）保留，
    是为了兼容既有文案与诊断包。
    """
    payload = {
        "at": int(time.time()),
        "at_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": bool(ok),
        "detail": str(detail or ""),
        "conflicts": [str(item) for item in (conflicts or [])],
        "groups": [dict(item) for item in (groups or []) if isinstance(item, dict)],
    }
    path = mod_conflict_state_path(config)
    try:
        from . import fsutil

        path.parent.mkdir(parents=True, exist_ok=True)
        fsutil.write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2), newline="\n")
    except (OSError, ValueError):
        pass


def mod_conflict_state(config: Any) -> dict[str, Any]:
    """读回最近一次自检的 Mod 冲突结论（没写过就返回 {}）。"""
    try:
        data = json.loads(mod_conflict_state_path(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_zip_write(archive: zipfile.ZipFile, path: Path, arcname: str, *, max_bytes: int = 8 * 1024 * 1024) -> None:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return
        archive.write(path, arcname)
    except OSError:
        return


def _nvngx_fingerprint(config: Any) -> list[str]:
    """把 DLSS5 那两个运行库的「指纹」写进诊断包 summary。

    为什么要有（2026-09-30 issue #3）：用户只报"dlss5 开不了"，而我们能拿到的
    `runtime\\dlss5` 证据只有日志里的展开记录 —— 文件到底在不在、是不是随包那份，
    以前全靠猜。这两个数（精确字节 + 与基线的 sha256 是否一致）一眼就能判定。
    """
    from . import runtime_assets

    lines = ["", "-- DLSS5 运行库指纹（出不出帧先看这里）--"]
    dlss5 = Path(config.dlss5_path)
    try:
        entries = {name: dict(entry) for _g, _root, name, entry in runtime_assets.manifest_entries(config)}
    except Exception as exc:  # noqa: BLE001
        lines.append(f"（读取随包清单失败: {exc}）")
        return lines
    for name in ("nvngx_dlss.dll", "nvngx_dlssnr.dll"):
        entry = entries.get(name) or {}
        expected = int(entry.get("size") or 0)
        want_sha = str(entry.get("sha256") or "")
        path = dlss5 / name
        if not path.is_file():
            lines.append(f"{name}: **缺失**（随包基线 {expected:,} 字节）—— DLSS5 的 NR 一定起不来")
            continue
        try:
            actual = path.stat().st_size
            got = runtime_assets.sha256_file(path) if want_sha else ""
        except OSError as exc:
            lines.append(f"{name}: 读取失败 {exc}")
            continue
        verdict = "n/a"
        if want_sha:
            verdict = "是" if got.lower() == want_sha.lower() else "**否（内容被换过）**"
        lines.append(
            f"{name}: size={actual:,}（基线 {expected:,}）与随包基线 sha256 一致={verdict} "
            f"sha256={got[:16]}…"
        )
    return lines


def _ngx_consumer_summary(game_dir: Path | None) -> list[str]:
    """「NGX 消费者」是谁 —— 决定"面板的 NGX Hook 计数算不算数"（2026-10-01 加）。

    为什么必须有这一段：一份真实诊断包里 `ReShade.log` 报
    `Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C`、面板 `NGX Hook 创建: 0`，
    看包的人（包括我）第一反应都是"DLSS5 没起来" —— 而它其实一直出帧，因为那台机器用
    **OptiScaler DLSS-NR（`WINHTTP.dll`）** 当神经消费者，NGX 调用被接管、不走 ReShade 的 hook。
    这段把"是不是这种共存方式"直接写在包的开头部分，避免同类误判再发生。
    """
    lines = ["", "-- NGX 消费者（判断面板「NGX Hook 创建: 0」算不算问题先看这里）--"]
    try:
        from . import reshade_integration

        info = reshade_integration.optiscaler_present(game_dir)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"（检查失败: {exc}）")
        return lines
    if not info.get("present"):
        lines.append("未检测到第三方 NGX 接管 → DLSS5 走 ReShade 自己的 NGX hook 路线，"
                     "面板的「NGX Hook 创建」应当 > 0；若为 0 才需要按 NGX/运行库方向排查。")
        return lines
    files = "、".join(info.get("files") or [])
    lines.append(f"检测到 **OptiScaler**（{files}）在接管 NGX —— 这是一种正常共存方式：")
    lines.append("  · 面板「NGX Hook 创建」**必然是 0**、ReShade.log 会报 "
                 "`Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C`，**均属正常**；")
    lines.append("  · 判断 DLSS5 是否生效请看：面板的「成功 NR 帧」是否增长，以及本包里 "
                 "`dlss5\\dlss5-feed.log` 是否出现 `feature ready` 与持续的帧统计。")
    return lines


def _xxmi_summary(config: Any) -> list[str]:
    """XXMI 注入链摘要（**不含任何密钥内容**，只看配置写没写对、签名在不在）。

    为什么要有（2026-09-30）：反馈者用**外部 XXMI** 时报"DLSS5 / 第一人称没注入进去"，
    而诊断包里没有任何 XXMI 信息 —— 只能来回问他、没法定位。这里把关键字段一次收齐：
    `active_importer` 是不是 EFMI（写错 importer 等于白写）、`extra_libraries` 里实际列了
    哪些 DLL、文件在不在、`extra_libraries_signature` 与 `Security.user_signature` 的**长度**
    （签名无效时 XXMI 会弹 Reset 并把注入列表清空 —— 这是"看着配好了却没注入"最常见的原因）。
    """
    lines = ["", "-- XXMI 注入链摘要（DLSS5 / ReShade 没生效时先看这里）--"]
    from . import reshade_integration

    launcher_path = config.xxmi_launcher_path
    lines.append(f"XXMI Launcher  : {launcher_path or '(未配置)'}")
    if launcher_path is None:
        return lines
    config_path = reshade_integration.xxmi_config_path(launcher_path)
    lines.append(f"Config.json    : {config_path or '(找不到 —— XXMI 还没首次运行过？)'}")
    if config_path is None or not Path(config_path).is_file():
        return lines
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        lines.append(f"读取失败       : {exc}")
        return lines
    section = data.get("Config") or {}
    lines.append(f"active_importer   : {section.get('active_importer')!r}")
    lines.append(f"enabled_importers : {section.get('enabled_importers')!r}")
    importers = data.get("Importers") or {}
    lines.append(f"Importers 段      : {sorted(importers.keys())}")
    importer = ((importers.get("EFMI") or {}).get("Importer") or {})
    libs = [item.strip() for item in str(importer.get("extra_libraries") or "").splitlines() if item.strip()]
    lines.append(f"EFMI.extra_libraries_enabled = {importer.get('extra_libraries_enabled')!r}")
    lines.append(f"EFMI.extra_libraries（{len(libs)} 条）:")
    for lib in libs:
        lines.append(f"    {'存在' if Path(lib).is_file() else '**文件不存在**'}  {lib}")
    lines.append(f"extra_libraries_signature 长度 = {len(str(importer.get('extra_libraries_signature') or ''))}")
    lines.append(f"Security.user_signature 长度   = {len(str((data.get('Security') or {}).get('user_signature') or ''))}")
    security_dir = Path(config_path).parent / "Resources" / "Security"
    for name in ("private_key.der", "public_key.der"):
        lines.append(f"{name}: {'存在' if (security_dir / name).is_file() else '缺失'}")
    return lines


def _shader_summary(config: Any) -> list[str]:
    """DLSS5 shader 文件清单（关键几个）+ ReShade 的搜索路径与 preset 启用状态。

    为什么要有（2026-09-30）：反馈者说"ReShade 面板里没有 DLSS5 / 第一人称的菜单"，
    而他历史截图报过 `DLSS5_Feed.fx(60): could not open included file 'ReShade.fxh'`
    —— 这类问题**只能靠"文件在不在、是不是 0 字节/被截断"来判**，日志里看不出来
    （addon 那句 `technique MISSING` 在**能用的环境**里启动头几秒也会出现，不是判据）。
    **只看存在与字节数**，不读内容。
    """
    from .initialize import DLSS5_SHADER_FILES

    lines = ["", "-- DLSS5 shader 文件清单（面板里没有 DLSS5 / 第一人称菜单时看这里）--"]
    root = config.dlss5_path / "reshade-shaders"
    for relative in DLSS5_SHADER_FILES:
        # ⚠ relative 自带 "Shaders" / "iMMERSE" 前缀，root 只到 reshade-shaders，所以要用全量
        # （第一版写成 relative[1:] 少了一层，8 个文件全被误报"缺失" —— 靠导包读回才发现）
        path = root.joinpath(*relative)
        if path.is_file():
            size = path.stat().st_size
            flag = "**0 字节！**" if size == 0 else "存在"
            lines.append(f"{flag}  {size:>8,} B  {'/'.join(relative)}")
        else:
            lines.append(f"**缺失**  {'/'.join(relative)}")
    immer = root / "Shaders" / "iMMERSE"
    try:
        files = sorted(p for p in immer.iterdir() if p.suffix.lower() == ".fx")
    except OSError:
        files = []
    lines.append(f"iMMERSE 目录: {len(files)} 个 .fx" + ("（目录不存在）" if not files else ""))
    for path in files:
        lines.append(f"    {path.stat().st_size:>8,} B  {path.name}")
    textures = root / "Textures"
    try:
        count = sum(1 for p in textures.iterdir() if p.is_file())
    except OSError:
        count = 0
    lines.append(f"Textures 目录: {count} 个文件")
    ini = root.parent / "ReShade.ini"
    if ini.is_file():
        for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("EffectSearchPaths=", "TextureSearchPaths=", "PresetPath=")):
                lines.append(f"ReShade.ini {line}")
    preset = root.parent / "ReShadePreset.ini"
    if preset.is_file():
        for line in preset.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("Techniques=", "TechniqueSorting=", "EffectSorting=")):
                lines.append(f"Preset {line[:180]}")
    return lines


def create_diagnostic_bundle(config: Any, *, game_dir: Path | None = None, note: str = "manual") -> Path:
    """Create a zip with logs and lightweight context files (no game binaries)."""
    _capture_windows_events(config)
    runtime = Path(config.runtime_path)
    target_dir = logs_dir(config)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = target_dir / f"diagnostics-{stamp}.zip"
    loader = config.migoto_loader_path
    loader_dir = Path(loader).parent if loader else runtime / "migoto"
    config_path = Path(getattr(config, "_config_path", "") or "")

    summary = [
        "EndfieldModController diagnostic bundle",
        f"created={datetime.now().isoformat(timespec='seconds')}",
        f"note={note}",
        f"session_log={session_log_path(config)}",
        f"runtime={runtime}",
        f"loader={loader_dir}",
        f"game_dir={game_dir}",
    ]
    summary.extend(_nvngx_fingerprint(config))
    summary.extend(_xxmi_summary(config))
    summary.extend(_ngx_consumer_summary(game_dir))
    summary.extend(_shader_summary(config))
    # 设备型号 / 显卡与驱动（用户 2026-10-01 要求）：判断"是不是显卡不支持"就靠这段。
    try:
        from . import deviceinfo

        summary.extend(deviceinfo.summary_lines())
    except Exception as exc:  # noqa: BLE001
        summary.append(f"（设备信息读取失败: {exc}）")

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(target_dir.glob("*.log")):
            _safe_zip_write(archive, path, f"logs/{path.name}")
        _safe_zip_write(archive, launch_log_path(config), "logs/launch.log")
        for path in sorted(target_dir.glob("*.txt")):
            _safe_zip_write(archive, path, f"logs/{path.name}")
        if game_dir is not None:
            for name in ("ReShade.ini", "ReShade.log", "actions.tsv", "user_ini_path.txt", "loader_debug.log", "d3d11_log.txt", "endfieldmodcontroller.addon.log"):
                _safe_zip_write(archive, game_dir / name, f"game/{name}")
        for name in ("ReShade.ini", "d3dx.ini", "d3dx_user.ini", "inject_order.txt", "actions.tsv", "user_ini_path.txt", "loader_debug.log", "mc_bootstrap.log", "mc_bootstrap.dll", "d3d11_log.txt", "endfieldmodcontroller.addon.log"):
            _safe_zip_write(archive, loader_dir / name, f"loader/{name}")
        # DLSS5 现场：`dlss5-feed.log` 是判断"神经渲染有没有出帧、卡在哪一步"的关键证据。
        # 2026-09-30 有一个 issue 就因为它没被收进包里，导致只能靠猜（那条反馈最终是
        # 靠 dlss5-feed.addon64 的 fileVersion 才对上线索）。
        dlss5_dir = Path(config.dlss5_path)
        for name in ("dlss5-feed.log", "dlss5-feed.cfg", "ReShade.ini", "ReShadePreset.ini", "ReShade.log"):
            _safe_zip_write(archive, dlss5_dir / name, f"dlss5/{name}")
        state = mod_conflict_state(config)
        if state:
            try:
                archive.writestr("mod_conflicts.json", json.dumps(state, ensure_ascii=False, indent=2))
            except (OSError, ValueError):
                pass
        if config_path.is_file():
            _safe_zip_write(archive, config_path, "config.json")
        archive.writestr("summary.txt", "\n".join(summary) + "\n")

    log_event(config, "诊断包已创建", category="diag", path=out, note=note)
    return out


def read_diagnostic_log(config: Any, tail: int = 800) -> str:
    """Return the newest diagnostic lines for the UI log viewer."""
    candidates = [session_log_path(config), daily_log_path(config), launch_log_path(config)]
    lines: list[str] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        lines.extend(content[-max(1, int(tail)):])
    return "\n".join(lines[-max(1, int(tail)):])


def clear_logs(config: Any) -> list[str]:
    removed: list[str] = []
    targets = [launch_log_path(config)]
    targets.extend(sorted(logs_dir(config).glob("*.log")))
    for path in targets:
        try:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
        except OSError:
            continue
    return removed


def _capture_windows_events(config: Any) -> None:
    """Append the newest Application Error / Hang entries when available."""
    if os.name != "nt":
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error','Application Hang'; StartTime=(Get-Date).AddMinutes(-15)} -ErrorAction SilentlyContinue | Select-Object -First 8 | Format-List TimeCreated,Id,ProviderName,Message",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=creationflags,
        )
    except Exception:  # noqa: BLE001
        return
    text = (result.stdout or "").strip()
    if not text:
        return
    target = logs_dir(config) / f"windows-events-{stamp}.log"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8", errors="replace")
        log_event(config, "已捕获 Windows 应用错误事件", category="crash", path=target)
    except OSError:
        return


def log_efmi_state(config: Any, *, user_ini_path: Path | None = None, staging_root: Path | None = None) -> None:
    """Log whether EFMI actually loaded the staged Mods/controller/probe files."""
    try:
        if user_ini_path is not None:
            user_ini = Path(user_ini_path)
            if user_ini.is_file():
                text = user_ini.read_text(encoding="utf-8", errors="replace")
                wanted = ("mc_probe", "mc_controller_loaded", "mc_last_wire", "mc_last_value", "mc_state_")
                for line in text.splitlines():
                    lowered = line.lower()
                    if any(token in lowered for token in wanted):
                        log_event(config, "EFMI user ini state", category="efmi", line=line)
            else:
                log_event(config, "EFMI user ini missing", category="efmi", path=user_ini)
        if staging_root is not None:
            root = Path(staging_root)
            managed = root / "EndfieldModControllerManaged"
            probe = root / "MC_Probe.ini"
            controller = root / "MC_Controller" / "controller.ini"
            log_event(config, "staged metadata root", category="efmi", path=managed, exists=managed.is_dir())
            log_event(config, "staged probe", category="efmi", path=probe, exists=probe.is_file())
            log_event(config, "staged controller", category="efmi", path=controller, exists=controller.is_file())
            active_dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("MC_")]
            ini_count = sum(1 for _ in root.rglob("*.ini"))
            log_event(config, "staged inventory", category="efmi", mod_dirs=len(active_dirs), ini_files=ini_count)
        loader = getattr(config, "migoto_loader_path", None)
        if loader is not None:
            loader_dir = Path(loader).parent
            debug = loader_dir / "loader_debug.log"
            if debug.is_file():
                lines = debug.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-120:]:
                    log_event(config, "loader debug", category="efmi", line=line)
            efmi_log = loader_dir / "d3d11_log.txt"
            if efmi_log.is_file():
                try:
                    log_event(config, "EFMI d3d11_log", category="efmi", path=efmi_log, size=efmi_log.stat().st_size)
                    text = efmi_log.read_text(encoding="utf-8", errors="replace")
                    for token in ("MC_Probe", "mc_probe", "mc_controller", "EndfieldModControllerManaged", "MC_Controller"):
                        count = text.count(token)
                        if count:
                            log_event(config, "EFMI d3d11_log token", category="efmi", token=token, count=count)
                    shown = 0
                    for line in text.splitlines():
                        if any(token in line for token in ("mc_probe", "mc_controller", "MC_Probe", "MC_Controller", "EndfieldModControllerManaged")):
                            log_event(config, "EFMI d3d11_log line", category="efmi", line=line[:500])
                            shown += 1
                            if shown >= 40:
                                break
                except OSError:
                    pass
    except Exception as exc:  # noqa: BLE001
        log_exception(config, "EFMI state logging failed", exc, category="efmi")
