"""Persistent diagnostics, process monitoring and crash log bundles."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
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
# 「请停下」信号：`stop_process_monitor()` 置位，`_monitor_process` 每轮检查一次。
# 没有它的话，关窗口时那个最长 1800 秒的监视线程根本没法早点收工（见 stop_process_monitor）。
_MONITOR_STOP = threading.Event()


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
    from . import reshade_integration

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
            loader_dir / "Addons" / reshade_integration.ADDON_NAME,
            runtime / "reshade" / "ReShade64.dll",
            runtime / "reshade" / "actions.tsv",
            runtime / "reshade" / "Addons" / "endfieldmodcontroller.addon",
            # ⚠ 统一面板**真正生效**的位置 = ReShade 的 base 目录（d3d12.dll 所在处）：
            #   诊断包必须带上它，才能回答"面板到底装了没有、ReShade 加载了没有"。
            config.dlss5_path / reshade_integration.ADDON_NAME,
            config.dlss5_path / "actions.tsv",
            config.dlss5_path / "user_ini_path.txt",
            config.dlss5_path / "modecontroller.addon.log",
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
    """取某个进程的完整命令行（崩溃报告用）。

    ⚠️ **删掉了 `wmic` 兜底**（2026-10-04）：`wmic` 自 Windows 11 24H2 起默认不再随系统提供，
    那条兜底在新系统上必然失败且**没有任何记录**（这里连日志都不写），留着只会让人以为
    "命令行读不到是权限问题"。现在只有 PowerShell 一条路径，失败就在报告里写明原因。
    """
    if os.name != "nt":
        return ""
    global _LAST_COMMAND_LINE_ERROR
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=creationflags,
        )
    except Exception as exc:  # noqa: BLE001
        _LAST_COMMAND_LINE_ERROR = f"读取命令行失败: {exc}"
        return ""
    text = (ps.stdout or "").strip()
    if not text:
        _LAST_COMMAND_LINE_ERROR = (ps.stderr or "").strip()[:200] or "PowerShell 没有返回命令行"
        return ""
    _LAST_COMMAND_LINE_ERROR = ""
    return text.splitlines()[-1].strip()


# 最近一次读命令行失败的原因（写进崩溃报告，免得"读不到"变成一个谜）
_LAST_COMMAND_LINE_ERROR = ""


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


# ---------------------------------------------------------------------------
# 采集留痕（2026-10-04）
# ---------------------------------------------------------------------------
# 为什么要有（用户 2026-10-04 原话：「日志包尽量多塞东西，**不要老是判据不够**」，
# 以及 issue #13 反馈者指出的原话：「采集失败连一条日志都不会留」）：
#   * 原来的 `_capture_tail` 在源文件不存在时**静默 return** —— 包里那条目直接消失，
#     看包的人分不清"这份日志不存在"和"这份日志是空的"（2026-10-04 那份包里
#     `ReShade.log` 就是这样整条不见的，把排查方向带偏了一整轮）。
#   * 现在每条采集项都记一行结果（ok / missing / error）+ 来源路径 + 大小 + mtime +
#     **是不是本次游戏运行写过的**（`fresh`）。清单本身作为一个文件进包。
# 判据（三问）："没有现场"和"没去抓"必须能一眼分开 —— 这就是这份清单的唯一目的。

# 最近一次游戏进程被发现的时间（`_monitor_process` 里记）——用来判断抓到的日志
# 是"本次现场"还是"上一次的旧文件"。旧日志当现场用比没有更危险（2026-10-04：
# 那份 `d3d11_log.txt` 12,667,256 字节跨 10:34→11:04 一字未变，却在包里被当成现场）。
_LAST_GAME_START = 0.0


def _new_capture_manifest() -> list[dict[str, Any]]:
    return []


def _manifest_add(
    manifest: list[dict[str, Any]] | None,
    *,
    arcname: str,
    source: Path | str,
    status: str,
    note: str = "",
    size: int | None = None,
    mtime: float | None = None,
    fresh: bool | None = None,
) -> None:
    if manifest is None:
        return
    manifest.append({
        "arcname": str(arcname),
        "source": str(source),
        "status": status,
        "note": note,
        "size": size,
        "mtime": mtime,
        "fresh": fresh,
    })


def _is_fresh(mtime: float | None) -> bool | None:
    """这份文件是不是**本次游戏运行**（进程被发现之后）写过的。"""
    if mtime is None:
        return None
    if not _LAST_GAME_START:
        return None
    return mtime >= (_LAST_GAME_START - 5.0)


def capture_manifest_text(manifest: list[dict[str, Any]]) -> str:
    """把人读的采集清单渲染出来（进包的一个纯文本文件）。"""
    counts: dict[str, int] = {}
    for item in manifest:
        counts[item.get("status", "?")] = counts.get(item.get("status", "?"), 0) + 1
    lines = [
        "诊断包采集清单（每一行 = 一个「本该有」的条目；missing/error 是采集不到，不是「没有内容」）",
        "status: ok=收进包了｜missing=源文件/目录不存在｜error=读取失败｜note 里有原因",
        f"合计 {len(manifest)} 项：" + "，".join(f"{key} {value}" for key, value in sorted(counts.items())),
        "",
    ]
    for item in manifest:
        extra = []
        if item.get("size") is not None:
            extra.append(f"{int(item['size']):,} B")
        if item.get("mtime"):
            extra.append("mtime=" + datetime.fromtimestamp(float(item["mtime"])).isoformat(timespec="seconds"))
        if item.get("fresh") is True:
            extra.append("**本次运行写过**")
        elif item.get("fresh") is False:
            extra.append("⚠ 上次运行留下的旧文件")
        if item.get("note"):
            extra.append(str(item["note"]))
        suffix = ("  " + "  ".join(extra)) if extra else ""
        lines.append(f"[{item.get('status')}] {item.get('arcname')}{suffix}")
        lines.append(f"        来源: {item.get('source')}")
    return "\n".join(lines) + "\n"


def _capture_tail(
    source: Path,
    target: Path,
    *,
    lines: int = 300,
    manifest: list[dict[str, Any]] | None = None,
    arcname: str | None = None,
    required: bool = False,
) -> bool:
    """把 `source` 的尾部写进 `target`。**采集不到也要留痕**（见上面那段的说明）。

    `required=True` 表示"这个源本该存在"（比如 EFMI 的 d3dx_user.ini）——
    仍不会抛异常，但会在包内的占位文件里写成明确的警告，而不是一句 "missing"。
    """
    arc = arcname or target.name
    try:
        if not source.is_file():
            _manifest_add(manifest, arcname=arc, source=source, status="missing",
                          note=("本该存在却找不到" if required else "源文件不存在"))
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    f"[诊断包] 这个条目采集不到：源文件不存在\n源: {source}\n"
                    f"（{'这条链本该有这个文件 —— 请把这条一并反馈' if required else '按当前配置它不存在，属正常'})\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            return False
        content = source.read_text(encoding="utf-8", errors="replace").splitlines()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(content[-lines:]) + "\n", encoding="utf-8", errors="replace")
        try:
            stat = source.stat()
            size, mtime = stat.st_size, stat.st_mtime
        except OSError:
            size, mtime = None, None
        _manifest_add(manifest, arcname=arc, source=source, status="ok",
                      note=f"取最后 {lines} 行（原文件 {len(content)} 行）",
                      size=size, mtime=mtime, fresh=_is_fresh(mtime))
        return True
    except OSError as exc:
        _manifest_add(manifest, arcname=arc, source=source, status="error", note=str(exc))
        return False


# ---------------------------------------------------------------------------
# 游戏侧现场：日志候选位置 / Player.log / WER / 反作弊 / 游戏目录清单
# ---------------------------------------------------------------------------
# 2026-10-04 建立（用户原话：「日志包尽量多塞东西，**不要老是判据不够**」）。
# 这一组函数回答的是"游戏那一侧到底发生了什么"，全部**只读**、且**永远不抛异常**
# —— 取证代码自己失败比不取证更糟（issue #13 的教训：`log_efmi_state` 整段包在一个
# try 里，一处 `iterdir()` 抛错就把后面所有采集全吞了）。


def reshade_log_candidates(config: Any, game_dir: Path | None) -> list[tuple[str, Path]]:
    """ReShade 日志的候选位置（带来源标签，全部返回、由采集层逐个记结果）。

    ⚠️ 为什么不能只看游戏目录（**issue #13 缺陷三**，2026-10-04 实测再次复现）：
    `launcher.py` 会给游戏进程设 `RESHADE_BASE_PATH_OVERRIDE` = `runtime\\reshade`，
    **ReShade 就以此为基准目录** —— `ReShade.log` 落在 `runtime\\reshade\\`，
    游戏目录里一个 ReShade 产物都没有。原代码只抓 `game_dir / "ReShade.log"`，
    于是那份真实日志整条没进包（`_capture_tail` 又是静默 return，包里连占位都没有）。
    """
    items: list[tuple[str, Path]] = []
    if game_dir is not None:
        items.append(("game", Path(game_dir) / "ReShade.log"))
    for label, value in (
        ("runtime", getattr(config, "reshade_runtime_path", None)),
        ("dlss5", getattr(config, "dlss5_path", None)),
    ):
        if value:
            items.append((label, Path(value) / "ReShade.log"))
    dll = getattr(config, "reshade_dll_path", None)
    if dll:
        items.append(("reshade-dll", Path(dll).parent / "ReShade.log"))
    loader = getattr(config, "migoto_loader_path", None)
    if loader:
        items.append(("loader", Path(loader).parent / "ReShade.log"))
    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for label, path in items:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((label, path))
    return unique


def efmi_probe_paths(config: Any) -> dict[str, Any]:
    """EFMI / 3DMigoto 侧的探测路径：**以 config 解析结果为准，loader 推导只作兜底**。

    ⚠️ **issue #13 缺陷一** + 2026-10-04 实测（反馈者 AST）：
    原代码把 `migoto_loader` 的父目录当成 EFMI 目录。那位反馈者把 `migoto_loader`
    指向了 `D:\\d3dxSkinManage\\home\\Arknights Endfield\\work`（**另一套 3DMigoto**），
    于是日志里报出一串 `…\\work\\Mods\\MC_Probe.ini exists=False`，
    而真正的 staging 在 `…\\XXMI Launcher\\EFMI\\Mods` —— 同一份日志的「应用配置」行里
    就明明白白写着。差点把结论带成"控制器铺的 Mod 一个都没进游戏"。
    现在**两个位置都探**、各自标明来源（不静默切换，也不再把"目录不存在"当异常）。
    """
    result: dict[str, Any] = {
        "staging": [], "user_ini": [], "loader_dir": None, "efmi_dir": None, "notes": [],
    }
    staging: list[tuple[str, Path]] = []
    user_ini: list[tuple[str, Path]] = []
    try:
        staging.append(("config", Path(config.staging_mods_path)))
    except Exception as exc:  # noqa: BLE001
        result["notes"].append(f"config.staging_mods_path 读不到: {exc}")
    try:
        user_ini.append(("config", Path(config.user_ini_path)))
    except Exception as exc:  # noqa: BLE001
        result["notes"].append(f"config.user_ini_path 读不到: {exc}")
    try:
        efmi_dir = config.efmi_dir
    except Exception as exc:  # noqa: BLE001
        efmi_dir = None
        result["notes"].append(f"config.efmi_dir 读不到: {exc}")
    if efmi_dir is not None:
        efmi = Path(efmi_dir)
        result["efmi_dir"] = efmi
        staging.append(("efmi", efmi / "Mods"))
        for name in ("d3dx_user.ini", "Core/d3dx_user.ini"):
            user_ini.append(("efmi", efmi / name))
    loader = getattr(config, "migoto_loader_path", None)
    if loader is not None:
        loader_dir = Path(loader).parent
        result["loader_dir"] = loader_dir
        staging.append(("loader", loader_dir / "Mods"))
        user_ini.append(("loader", loader_dir / "d3dx_user.ini"))

    def _unique(items: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
        seen: set[str] = set()
        out: list[tuple[str, Path]] = []
        for label, path in items:
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((label, path))
        return out

    result["staging"] = _unique(staging)
    result["user_ini"] = _unique(user_ini)
    return result


def efmi_log_candidates(config: Any) -> list[tuple[str, Path]]:
    """EFMI / 3DMigoto 侧的运行日志候选（`d3d11_log.txt` / `loader_debug.log` / …）。

    ⚠️ 为什么两个目录都要（2026-10-04 实测）：反馈者机器上 `d3dxSkinManage` 的
    `work\\d3d11_log.txt`（12.6 MB）**跨半小时一字未变** —— 那是**上一次运行**留下的
    旧文件，而包里把它当成"本次现场"用了。真正的 EFMI 日志在 `EFMI\\` 目录里、
    根本没被采集。现在两侧都抓，并在清单里标 `fresh`（是不是本次运行写过的）。
    """
    items: list[tuple[str, Path]] = []
    probes = efmi_probe_paths(config)
    for label, root in (("efmi", probes.get("efmi_dir")), ("loader", probes.get("loader_dir"))):
        if not root:
            continue
        root = Path(root)
        for name in ("d3d11_log.txt", "loader_debug.log", "d3dx.ini", "d3dx_user.ini", "ReShade.ini"):
            items.append((label, root / name))
    seen: set[str] = set()
    out: list[tuple[str, Path]] = []
    for label, path in items:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((label, path))
    return out


def _user_dirs() -> dict[str, Path | None]:
    profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA")
    return {
        "profile": Path(profile) if profile else None,
        "local": Path(local) if local else None,
        "locallow": (Path(profile) / "AppData" / "LocalLow") if profile else None,
        "programdata": Path(os.environ.get("ProgramData") or r"C:\ProgramData"),
    }


def _find_named_files(root: Path | None, names: tuple[str, ...], *, depth: int = 3,
                      limit: int = 8, prefer: tuple[str, ...] = ()) -> list[Path]:
    """在 `root` 下限定深度找指定文件名（只读、失败返回空表）。

    `prefer` 里的关键词命中时会**排前面**（例如 `endfield` / `hypergryph`）——
    同一台机器上常有别的 Unity 游戏，先给最可能是这个游戏的。
    """
    if root is None or not root.is_dir():
        return []
    found: list[tuple[int, float, Path]] = []
    try:
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            current, level = stack.pop()
            if level >= depth:
                continue
            try:
                children = list(current.iterdir())
            except OSError:
                continue
            for child in children:
                try:
                    if child.is_dir():
                        stack.append((child, level + 1))
                        continue
                except OSError:
                    continue
                if child.name.lower() in names:
                    lowered = str(child).lower()
                    rank = 0 if any(token in lowered for token in prefer) else 1
                    try:
                        mtime = child.stat().st_mtime
                    except OSError:
                        mtime = 0.0
                    found.append((rank, -mtime, child))
    except Exception:  # noqa: BLE001
        return []
    found.sort()
    return [path for _rank, _mtime, path in found[:limit]]


def _prefer_only(found: list[Path], tokens: tuple[str, ...], limit: int) -> list[Path]:
    """优先只留"名字像这个游戏"的那些；一个都没有时才退回全部（限 `limit` 条）。"""
    preferred = [path for path in found if any(token in str(path).lower() for token in tokens)]
    return (preferred or found)[:limit]


def player_log_candidates(limit: int = 4) -> list[Path]:
    """Unity 的 `Player.log` / `Player-prev.log`（终末地在 `%USERPROFILE%\\AppData\\LocalLow\\<厂商>\\Endfield`）。

    ⚠️ 为什么必须收它（2026-10-04）：这是**游戏自己**写的最后几句话 ——
    "真崩溃" / "被外部结束" / "走到了正常卸载" 三种情况的结尾完全不同。
    issue #13 的反馈者就是靠它（`Player.log` 停在 `MemoryPool::MMapMemoryBlock count:0`、
    没有任何 Unity 关闭信息）才判出"不是崩溃，而是被外部结束"。以前包里根本没有这一项。

    ⚠️ 但**别把别的 Unity 游戏的日志也收进来**（2026-10-04 实测：搜索 `LocalLow` 时
    顺手收了《城市天际线》《Subnautica》的 `Player.log`）：那对排查没用，还会把无关的
    隐私内容带进一个要往外发的包。所以命中"像终末地"的那些优先、且**只留它们**。
    """
    dirs = _user_dirs()
    tokens = ("endfield", "hypergryph", "gryphline")
    pool = _find_named_files(
        dirs.get("locallow"), ("player.log", "player-prev.log"),
        depth=3, limit=max(limit * 4, 12), prefer=tokens,
    )
    return _prefer_only(pool, tokens, limit)


def unity_crash_logs(limit: int = 8) -> list[Path]:
    """Unity / 游戏自己写的崩溃报告（`Crashes\\*.log` / `error.log`），只读文本、不收 dmp。"""
    dirs = _user_dirs()
    out: list[Path] = []
    for key in ("local", "profile"):
        root = dirs.get(key)
        if root is None:
            continue
        out.extend(_find_named_files(
            root / "AppData" / "Local" / "Temp" if key == "profile" else root / "Temp",
            ("error.log", "crash.log", "crashreport.log"),
            depth=5, limit=limit, prefer=("endfield", "hypergryph", "gryphline", "unity"),
        ))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    # 与 `player_log_candidates` 同一套取舍：先留"像终末地"的，别把别的程序的崩溃日志
    # 一并塞进要外发的包（"unity" 这个 token 只是兜底，命中终末地时不会用到）。
    return _prefer_only(unique, ("endfield", "hypergryph", "gryphline"), limit)


def wer_report_paths(limit: int = 8) -> list[Path]:
    """Windows 错误报告（WER）里与游戏有关的 `Report.wer`。

    为什么要有（issue #13 反馈者也提过这条判据）：**有没有 WER 记录**直接区分
    "进程自己崩了"和"进程被外部结束了" —— 崩了会有 Application Error 事件 + WER 报告，
    被 `TerminateProcess` 结束则两者都没有。以前包里完全没有这一项。
    """
    dirs = _user_dirs()
    root = dirs.get("programdata")
    if root is None:
        return []
    out: list[Path] = []
    for sub in ("Microsoft/Windows/WER/ReportArchive", "Microsoft/Windows/WER/ReportQueue"):
        base = root / sub
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for entry in entries[:120]:
            if "endfield" not in entry.name.lower():
                continue
            report = entry / "Report.wer"
            if report.is_file():
                out.append(report)
            if len(out) >= limit:
                return out
    return out


def crash_dump_candidates(limit: int = 10) -> list[tuple[Path, int, float]]:
    """崩溃转储清单（`%LOCALAPPDATA%\\CrashDumps`）—— **只列不塞**（dmp 动辄几百 MB）。"""
    dirs = _user_dirs()
    local = dirs.get("local")
    if local is None:
        return []
    base = local / "CrashDumps"
    if not base.is_dir():
        return []
    out: list[tuple[Path, int, float]] = []
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not entry.is_file() or entry.suffix.lower() != ".dmp":
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            out.append((entry, stat.st_size, stat.st_mtime))
            if len(out) >= limit:
                break
    except OSError:
        return out
    return out


_ENV_REPORT_CACHE: tuple[float, str] | None = None
_ENV_REPORT_TTL = 45.0


def _powershell(script: str, *, timeout: float = 25.0) -> tuple[str, str]:
    """跑一段 PowerShell，返回 (stdout, 错误说明)。**永远不抛异常**。

    ⚠️ 命令前必须先把 `[Console]::OutputEncoding` 设成 UTF-8：PowerShell 5.1 默认按
    系统 ANSI（中文机 = GBK）往管道写字，而我们按 UTF-8 解码 —— 于是
    `信息: 没有运行的任务匹配指定标准` 变成一串乱码进了日志（2026-10-04 那份包里
    到处是 `��Ϣ: û�����е�����ƥ��ָ����׼��`）。反过来也一样：这里把编码统一到 UTF-8，
    中文事件描述、服务名、Mod 名才不会变成问号。
    """
    if os.name != "nt":
        return "", "非 Windows 平台，跳过"
    prefix = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$OutputEncoding=[System.Text.Encoding]::UTF8;"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return "", f"超时（>{timeout:g}s）"
    except Exception as exc:  # noqa: BLE001
        return "", f"调用失败: {exc}"
    text = (result.stdout or "").strip()
    if not text and (result.stderr or "").strip():
        return "", f"stderr: {(result.stderr or '').strip()[:300]}"
    return text, ""


def collect_environment_report(config: Any, game_dir: Path | None = None) -> tuple[str, str]:
    """一次 PowerShell 调用把"游戏之外"的现场抓齐：事件日志 / 反作弊服务 / 转储 / 版本。

    返回 `(文本, 失败原因)`；**失败也会返回一行说明**（"抓不到"本身是判据：
    比如"没有 WER 记录"能证明进程不是自己崩的，而"采集失败"什么也证明不了）。

    结果按 45 秒缓存 —— 一次崩溃会连着走 `_capture_postmortem` 与
    `create_diagnostic_bundle` 两条路，不能为此跑两遍 PowerShell（那是几十秒的等待）。
    """
    global _ENV_REPORT_CACHE
    now = time.time()
    if _ENV_REPORT_CACHE is not None and now - _ENV_REPORT_CACHE[0] < _ENV_REPORT_TTL:
        return _ENV_REPORT_CACHE[1], ""

    lines: list[str] = []
    notes: list[str] = []
    lines.append("-- Windows 事件（Application：错误/挂起/WER，近 60 分钟；含任何提到 Endfield 的事件）--")
    events, err = _powershell(
        "Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=(Get-Date).AddMinutes(-60)} "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.ProviderName -in @('Application Error','Application Hang','Windows Error Reporting') "
        "-or $_.Message -match 'Endfield' } | Select-Object -First 12 | "
        "Format-List TimeCreated,Id,ProviderName,LevelDisplayName,Message"
    )
    if err:
        notes.append(f"事件日志抓取失败：{err}")
        lines.append(f"（抓取失败：{err}）")
    elif not events:
        lines.append("（近 60 分钟内没有任何 Application Error / Hang / WER 事件。**⚠️ 这条判据"
                     "不完整**：① 被 TerminateProcess 结束不会留事件；② **CRT 的「Runtime Error!」"
                     "对话框会把进程卡在弹窗上 —— 既不写事件、也不退出**，所以「没有事件」≠「没出过事」。"
                     "要分清请看游戏进程退出码（0xC0000409 / 0x40000015 = CRT fail-fast / abort）"
                     "以及面板 addon 自己的日志（见 summary 的 addon 段））")
    else:
        lines.append(events)

    # ── "有 DLL 没加载起来"的**直接记录点**（2026-10-04 加）────────────────────
    # 为什么单开一段：反馈者报的 `0xC0000135 STATUS_DLL_NOT_FOUND` 直译就是"某个 DLL 没加载
    # 起来"，而这类失败**不一定**进 Application 日志 —— 它常只落在 SideBySide（WinSxS
    # 激活失败）与 AppModel-Runtime 里。原来只看 Application Error/Hang/WER，
    # 等于把这条线上唯一的直接证据漏掉了。
    lines.append("")
    lines.append("-- DLL 加载 / 映像相关性（**STATUS_DLL_NOT_FOUND 的经典记录点**）--")
    sxs, err = _powershell(
        "Get-WinEvent -FilterHashtable @{LogName='Application';ProviderName='SideBySide';"
        "StartTime=(Get-Date).AddDays(-2)} -ErrorAction SilentlyContinue | "
        "Select-Object -First 10 | Format-List TimeCreated,Id,LevelDisplayName,Message"
    )
    if err:
        lines.append(f"SideBySide：（抓取失败：{err}）")
    else:
        lines.append("SideBySide：" + (sxs.strip() or "（近 2 天没有事件）"))
    appmodel, err2 = _powershell(
        "Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-AppModel-Runtime/Admin';"
        "StartTime=(Get-Date).AddDays(-2)} -ErrorAction SilentlyContinue | "
        "Select-Object -First 10 | Format-List TimeCreated,Id,LevelDisplayName,Message"
    )
    if not err2:
        lines.append("AppModel-Runtime/Admin：")
        lines.append(appmodel.strip() or "（近 2 天没有事件）")

    # ── 近 60 分钟 Application 里的**全部**错误（不限那几个 Provider）────────────
    # 原来是白名单式筛选（Application Error / Hang / WER + 提到 Endfield），
    # 于是"游戏自己注册的事件源报的错"永远看不到。用户要的是"尽量多塞、别老是判据不够"。
    lines.append("")
    lines.append("-- 近 60 分钟 Application 日志里的全部错误/严重（不限 Provider）--")
    all_errors, err3 = _powershell(
        "Get-WinEvent -FilterHashtable @{LogName='Application';Level=@(1,2);"
        "StartTime=(Get-Date).AddMinutes(-60)} -ErrorAction SilentlyContinue | "
        "Select-Object -First 20 | "
        "Format-List TimeCreated,Id,ProviderName,LevelDisplayName,Message"
    )
    if err3:
        lines.append(f"（抓取失败：{err3}）")
    else:
        lines.append(all_errors.strip() or "（近 60 分钟一条错误都没有）")

    lines.append("")
    lines.append("-- 反作弊 / 安全相关服务（判断「是不是被反作弊结束」看这里）--")
    # ⚠️ 2026-10-04 扩正则：`PassGuard` 是 `EisPassGuardXInputService`（反馈者机器上 Running、
    # 本机没有）—— 它靠 `SGuard` 这条**误打误撞**匹配进来的（`PassGuard` 里含 `sGuard`），
    # 说明原来的正则既漏（Eis / Defender / 国产杀毒全不在）又歪（靠子串撞进来）。
    # 这里按"反作弊 + 安全软件"两类补齐，并**保留 XInput**：那个服务名带 XInput，
    # 而反馈者的 Player.log 恰好断在 `Using XInput` 之后，需要它出现在同一份报告里。
    services, err = _powershell(
        "Get-Service -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Name -match 'AntiCheat|ACE|SGuard|PassGuard|XInput|TenSafe|Hypergryph|Gryphline|BEDaisy|EasyAntiCheat|WinDefend|WdNisSvc|Sense|MBAMService|Avast|Avira|ekrn|Kaspersky|ESET|Huorong|火绒|QQPCMgr|Kingsoft|ZhuDongFangYu|360' } | "
        "Format-Table -AutoSize Name,DisplayName,Status,StartType"
    )
    if err:
        notes.append(f"服务查询失败：{err}")
        lines.append(f"（抓取失败：{err}）")
    else:
        lines.append(services or "（没有匹配到反作弊/官方服务）")

    # ── 安全软件与它的"吃文件"记录（2026-10-04 加）─────────────────────────────
    # 为什么：反馈者报的退出码是 `0xC0000135 STATUS_DLL_NOT_FOUND` —— "某个 DLL 加载失败"。
    # 而用户早就要过同一条防线（原话：「如果某一文件老是被删掉，要在启动的时候出个弹窗
    # 提醒用户，建议把某个文件夹加入杀毒软件白名单」）⇒ **杀毒隔离文件是这个项目已知的问题类**，
    # 排查"缺哪个 DLL"必须先看一眼安全软件最近干了什么，而不是靠猜。
    lines.append("")
    lines.append("-- 已注册的安全软件（判断「这台机器上谁在拦文件」）--")
    av, err = _powershell(
        "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct "
        "-ErrorAction SilentlyContinue | "
        "Select-Object displayName,productState,pathToSignedProductExe | Format-List"
    )
    if err:
        notes.append(f"杀毒产品查询失败：{err}")
        lines.append(f"（抓取失败：{err}）")
    else:
        lines.append(av.strip() or
                     "（SecurityCenter2 里没有注册任何杀毒产品 —— 要么真没装，"
                     "要么系统把这块裁剪掉了；本机就是这种空结果）")
    excludes, err = _powershell(
        "(Get-MpPreference -ErrorAction SilentlyContinue).ExclusionPath -join ', '"
    )
    if not err:
        lines.append("Defender 排除项：" + (excludes.strip() or "（无 —— 游戏/运行目录都没加白名单）"))

    lines.append("")
    lines.append("-- 安全软件的检测/隔离记录（近 7 天；**怀疑文件被吃掉时先看这里**）--")
    defender, err = _powershell(
        "Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Windows Defender/Operational';"
        "StartTime=(Get-Date).AddDays(-7)} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Id -in 1006,1007,1008,1009,1010,1011,1012,1013,1015,1116,1117,1118,1119 } | "
        "Select-Object -First 15 | Format-List TimeCreated,Id,Message"
    )
    if err:
        notes.append(f"Defender 事件抓取失败：{err}")
        lines.append(f"（抓取失败：{err}）")
    else:
        lines.append(defender.strip() or
                     "（近 7 天没有 Defender 的检测/处置事件 —— 至少 Defender 没动过手）")
    # **最直接的一条**：Defender 到底动过哪些文件（`Resources` 里就是被隔离/删除的路径）。
    # 原来只能靠翻事件日志的 `Message` 去猜，而这条直接给出路径 ——
    # "某个 DLL 加载失败"的答案常常就在这份清单里。
    threats, err = _powershell(
        "Get-MpThreatDetection -ErrorAction SilentlyContinue | "
        "Sort-Object InitialDetectionTime -Descending | Select-Object -First 10 | "
        "Format-List InitialDetectionTime,ThreatID,ActionSuccess,Resources"
    )
    if err:
        lines.append(f"（Defender 威胁清单抓取失败：{err}）")
    else:
        lines.append("Defender 处理过的文件（Recent detections）：")
        lines.append(threats.strip() or
                     "（没有 —— Defender 没隔离/删过任何文件；注意这一项需要管理员权限）")

    lines.append("")
    lines.append("-- 崩溃转储（%LOCALAPPDATA%\\CrashDumps，只列清单不收本体）--")
    dumps = crash_dump_candidates()
    if not dumps:
        lines.append("（目录不存在或没有 .dmp —— 没有本地转储）")
    for path, size, mtime in dumps:
        lines.append(f"{datetime.fromtimestamp(mtime).isoformat(timespec='seconds')}  "
                     f"{size:>14,} B  {path.name}")

    lines.append("")
    lines.append("-- 游戏与启动器文件版本 --")
    targets = []
    if game_dir is not None:
        targets.append(Path(game_dir) / "Endfield.exe")
    exe = getattr(config, "game_exe_path", None)
    if exe:
        targets.append(Path(exe))
    seen: set[str] = set()
    for target in targets:
        key = str(target).lower()
        if key in seen or not target.is_file():
            continue
        seen.add(key)
        info, err = _powershell(
            f"(Get-Item -LiteralPath '{str(target).replace("'", "''")}').VersionInfo | "
            "Format-List FileVersion,ProductVersion,FileDescription,CompanyName"
        )
        lines.append(f"{target}")
        lines.append(info if not err else f"（读取失败：{err}）")

    # ── 关键运行时模块的**存在性**（2026-10-04 加）─────────────────────────────
    # `0xC0000135` 直译就是"某个 DLL 没加载起来"。而我们的 loader proxy 是**转发到
    # System32** 的（字符串表里写死 `C:\Windows\System32\d3dcompiler_47.D3DCompile`
    # 这种"路径.导出名"），所以 **System32 里那几个文件在不在**直接决定 proxy 能不能把
    # 调用转出去。以前整份包里没有这份清单 —— 真出这种事时，连"文件是不是被杀毒吃掉"
    # 都答不上来（本机对照：vulkan-1.dll 1,730,096 B / d3dcompiler_47.dll 4,669,440 B）。
    lines.append("")
    lines.append("-- 关键运行时模块（System32：proxy 的转发目标 + VC 运行库）--")
    modules, err = _powershell(
        "$names = @('vulkan-1.dll','d3dcompiler_47.dll','nvngx_dlss.dll','nvngx_dlssg.dll',"
        "'nvngx_dlssd.dll','dxgi.dll','d3d11.dll','d3d12.dll','msvcp140.dll','vcruntime140.dll',"
        "'vcruntime140_1.dll','nvapi64.dll');"
        "foreach ($n in $names) { $p = Join-Path $env:SystemRoot ('System32\\' + $n);"
        " if (Test-Path -LiteralPath $p) { $i = Get-Item -LiteralPath $p;"
        " '{0,-22} {1,12:N0} B  {2:yyyy-MM-dd HH:mm}  v{3}' -f $n, $i.Length, $i.LastWriteTime, $i.VersionInfo.FileVersion }"
        " else { '{0,-22} **缺失**' -f $n } }"
    )
    lines.append(modules if not err else f"（抓取失败：{err}）")

    lines.append("")
    lines.append("-- 相关进程（注入框架 / 插件 / 启动器，判断谁在同时跑）--")
    # ⚠️ 2026-10-04 扩正则：原来的清单只看我们自己的组件与注入框架，于是**覆盖层 /
    # 加速 / 远程桌面**这类"会改渲染与输入行为"的常驻软件一律看不见。反馈者机器上就
    # 有 `Todesk Virtual Display Adapter`（虚拟显示器），而它的 Player.log 恰好断在
    # `Using XInput` 之后 —— 这类软件必须出现在同一份报告里才可能被关联上。
    procs, err = _powershell(
        "Get-Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.ProcessName -match 'XXMI|loader|migoto|d3dx|Endfield|SecondaryMotion|Poser|webview|EndfieldModController|OptiScaler|Lossless|SpecialK|RTSS|RivaTuner|Afterburner|Nahimic|Todesk|Sunlogin|AnyDesk|TeamViewer|Fraps|Bandicam|obs' } | "
        "Select-Object Id,ProcessName,@{n='StartTime';e={try{$_.StartTime}catch{''}}} | Format-Table -AutoSize"
    )
    lines.append(procs if not err else f"（抓取失败：{err}）")

    # ── 系统级注入点（2026-10-04 加）─────────────────────────────────────────────
    # 为什么："游戏进程里多了一个不认识的东西"是闪退的常见成因，而它**不一定**来自游戏
    # 目录 —— `AppInit_DLLs`（全局注入）与 IFEO（映像劫持 / 调试器、`VerifierDlls`）
    # 都能在游戏启动瞬间把 DLL 塞进去。两处都很短，值得常备在包里。
    lines.append("")
    lines.append("-- 系统级注入点（全局注入 / 映像劫持）--")
    injections, err = _powershell(
        "$k = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Windows';"
        "$v = Get-ItemProperty -Path $k -ErrorAction SilentlyContinue;"
        "'AppInit_DLLs     = ' + [string]$v.AppInit_DLLs;"
        "'LoadAppInit_DLLs = ' + [string]$v.LoadAppInit_DLLs;"
        "$ifeo = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options';"
        "Get-ChildItem $ifeo -ErrorAction SilentlyContinue | ForEach-Object {"
        " $p = Get-ItemProperty -Path $_.PSPath -ErrorAction SilentlyContinue;"
        " foreach ($n in @('Debugger','AppInit_DLLs','VerifierDlls')) {"
        "  if ($p.$n) { '{0} -> {1} = {2}' -f $_.PSChildName, $n, $p.$n } } }"
    )
    lines.append(injections.strip() if not err else f"（抓取失败：{err}）")

    text = "\n".join(lines) + "\n"
    reason = "；".join(notes)
    if not reason:
        _ENV_REPORT_CACHE = (now, text)
    return text, reason


def game_dir_inventory_text(config: Any, game_dir: Path | None, *, limit: int = 400) -> str:
    """游戏目录清单 + 注入归属（哪套 proxy、原版备份在不在、plugin 里都有什么）。

    为什么要有（2026-10-04）：那份包里只有一句 `kind=loader_proxy … backup=None`，
    看不出"这份 proxy 是谁铺的、能不能还原"。而这些正好决定"游戏起不起得来"
    （game_clean 的注释就写过：proxy 移走却没补回系统原版 ⇒ 游戏直接起不来）。
    """
    from . import reshade_integration

    lines = ["-- 游戏目录清单 --"]
    if game_dir is None or not Path(game_dir).is_dir():
        lines.append(f"（没有游戏目录：{game_dir}）")
        return "\n".join(lines) + "\n"
    game = Path(game_dir)
    lines.append(f"游戏目录: {game}")
    lines.append("")
    lines.append("== 注入 proxy（决定游戏能否加载 plugin\\*.dll）==")
    # ⚠️ 只有这两个是**我们真的会借它注入**的 loader 底座。`LOADER_PROXY_MODULES` 里
    # 其余那些（`dxgi.dll` / `d3d11.dll` / `d3d12.dll` / `nvapi64.dll` / `winmm.dll`）
    # 是"别的注入器可能占用的位置"，**正常游戏目录本来就没有** —— 对它们报"缺失"纯属噪音，
    # 会把真正要看的那两行淹掉（本机实测：一次刷出 5 行假警报）。
    required_loaders = {"d3dcompiler_47.dll", "vulkan-1.dll"}
    for name in reshade_integration.LOADER_PROXY_MODULES:
        path = game / name
        parked = path.with_name(name + reshade_integration.LOADER_PROXY_DISABLED_SUFFIX)
        backup = path.with_name(name + ".bak")
        # ⚠️⚠️ **不存在的也要列出来**（2026-10-04 改）。原来这一句是
        # `if not path.is_file() and not parked.is_file(): continue` —— 于是
        # "**proxy 和 .bak 都不在**"这种最危险的状态（游戏可能因为缺这个模块直接起不来，
        # 而且没有任何可还原的原版）在清单里**一个字都不出现**，恰恰是最该被看见的情况
        # 被静默跳过了。反馈者这次的退出码正是 `STATUS_DLL_NOT_FOUND`，这一行必须永远可见。
        if not path.is_file() and not parked.is_file() and not backup.is_file():
            if name.lower() in required_loaders:
                lines.append(f"{name}: **缺失（proxy 与原版备份都不在）** —— "
                             "游戏若依赖它会直接起不来，而且没有可还原的原版")
            continue
        try:
            is_proxy = reshade_integration.looks_like_loader_proxy(path) if path.is_file() else False
            kind = reshade_integration.loader_kind(path) if path.is_file() else ""
        except Exception as exc:  # noqa: BLE001
            is_proxy, kind = False, f"判定失败: {exc}"
        size = path.stat().st_size if path.is_file() else 0
        # 「与 System32 原版一模一样的副本」要**点名**（2026-10-05）：它不是第三方注入，
        # 所以净化**不会动它**（搬走还可能让启动器 `verify_files.json` 校验失败），
        # 但它会让进程里出现**同名不同路径的两份模块**（d3d11 按 exe 目录优先命中它，
        # 而 ReShade 用完整路径 hook System32 那份）⇒ 图形 hook 打偏、注入链错位。
        # 这类文件以前在这里只显示"（不是 proxy）归属=未知"，等于什么也没说。
        note = ""
        if path.is_file() and not is_proxy:
            try:
                if reshade_integration.duplicate_of_system_module(path):
                    note = ("  ⚠️ **与 System32 原版内容完全一致（系统模块副本）**："
                            "净化不会动它（不是第三方注入、搬走可能让启动器校验失败），"
                            "但它会让进程里出现同名不同路径的两份模块，注入链的 hook 可能打偏")
            except Exception:  # noqa: BLE001 —— 判不出来就别乱说
                note = ""
        lines.append(
            f"{name}: {'**loader proxy**' if is_proxy else '（不是 proxy）'} "
            f"归属={kind or '未知'} size={size:,} B "
            f"原版备份={backup.name + '（在）' if backup.is_file() else '**缺失（无法安全还原）**'}"
            + (f" 另有停用副本 {parked.name}" if parked.is_file() else "")
            + note
        )
    lines.append("")
    lines.append("== plugin 目录（会被 proxy 全部加载）==")
    plugin = game / reshade_integration.PLUGIN_DIR_NAME
    if plugin.is_dir():
        try:
            entries = sorted(plugin.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            entries = []
        for entry in entries[:80]:
            try:
                size = entry.stat().st_size if entry.is_file() else 0
            except OSError:
                size = 0
            lines.append(f"    {size:>12,} B  {entry.name}")
    else:
        lines.append("    （没有 plugin 目录）")
    lines.append("")
    lines.append("== 游戏目录文件（顶层，按修改时间倒序；只列关键后缀）==")
    interesting = (".dll", ".exe", ".ini", ".log", ".addon64", ".json", ".txt", ".bak", ".disabled")
    try:
        files = [p for p in game.iterdir() if p.is_file() and p.suffix.lower() in interesting]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        files = []
    for path in files[:limit]:
        try:
            stat = path.stat()
        except OSError:
            continue
        lines.append(
            f"    {stat.st_size:>12,} B  {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}  {path.name}"
        )
    if len(files) > limit:
        lines.append(f"    …（还有 {len(files) - limit} 个未列出）")
    lines.append("")
    lines.append("== 游戏目录子目录（一层）==")
    try:
        for child in sorted(game.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir():
                try:
                    count = sum(1 for _ in child.iterdir())
                except OSError:
                    count = -1
                lines.append(f"    {child.name}\\  （{count} 项）")
    except OSError:
        pass
    # ── 值得看的子目录**内容**（2026-10-04 加）─────────────────────────────────
    # 上面那一段只列子目录名与项数 —— 而"游戏为什么没起来"的答案往往就在其中某几个里：
    # `CrashSightLog\` 是**游戏自己的崩溃日志**（`0xC0000135` 那次唯一可能指名道姓的地方）、
    # `_DLSS5_Backup\` 是我们动过 DLSS5 相关文件的备份、`sdklogs\` 是官方 SDK 的日志。
    # 只列名字等于知道"那儿有东西"却看不到是什么。
    lines.append("")
    lines.append("== 值得看的子目录内容（最新 8 个）==")
    wanted = ["_DLSS5_Backup", "CrashSightLog", "sdklogs", "launcher_tmp", "U8Data",
              "HGEventLog_Encrypted"]
    try:
        wanted += [p.name for p in game.glob("_nvngx_before_dlss5*") if p.is_dir()]
    except OSError:
        pass
    for sub in wanted:
        folder = game / sub
        if not folder.is_dir():
            continue
        try:
            items = sorted((p for p in folder.rglob("*") if p.is_file()),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            items = []
        if not items:
            lines.append(f"    {sub}\\  （空）")
            continue
        lines.append(f"    {sub}\\  （{len(items)} 个文件）")
        for entry in items[:8]:
            try:
                stat = entry.stat()
            except OSError:
                continue
            try:
                rel = entry.relative_to(folder).as_posix()
            except ValueError:
                rel = entry.name
            lines.append(f"        {stat.st_size:>12,} B  "
                         f"{datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}  {rel}")
    return "\n".join(lines) + "\n"


def sanitized_xxmi_config(config: Any) -> tuple[str, str]:
    """XXMI 的 `Config.json` **脱敏副本**（签名值只留长度）。

    为什么要塞整份：`_xxmi_summary` 只给几个字段，而"注入库到底列了什么、顺序如何、
    有没有多出别的库"全在原文里。签名字段是用户自己的 ECDSA 签名（私钥不在其中），
    但**没必要把它带走** —— 一律替换成 `<已省略，长度 N>`。
    """
    from . import reshade_integration

    launcher = config.xxmi_launcher_path
    if launcher is None:
        return "", "没有定位到 XXMI Launcher"
    path = reshade_integration.xxmi_config_path(launcher)
    if not path or not Path(path).is_file():
        return "", f"XXMI 配置不存在: {path}"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "", f"读取 XXMI 配置失败: {exc}"

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if isinstance(value, str) and ("signature" in key.lower() or "private" in key.lower()):
                    out[key] = f"<已省略，长度 {len(value)}>"
                else:
                    out[key] = _walk(value)
            return out
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    try:
        return json.dumps(_walk(data), ensure_ascii=False, indent=2), ""
    except (TypeError, ValueError) as exc:
        return "", f"序列化失败: {exc}"


def _try_capture(config: Any, what: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    """跑一段采集；**失败只记一条日志，绝不让它中断其余采集**。

    issue #13 的核心教训：`log_efmi_state` 整个函数体包在一个 `try` 里，
    `staging_root.iterdir()` 一处抛 `FileNotFoundError` ⇒ 后面 `loader_debug.log` /
    `d3d11_log.txt` 的采集**一行都没执行**，而在最需要现场的那一次崩溃包里，
    取证代码自己整段放弃了。
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log_exception(config, f"采集失败: {what}", exc, category="diag")
        return None


def _capture_postmortem(config: Any, game_dir: Path | None, reason: str) -> None:
    """游戏退出后收集现场。

    ⚠️ **正常退出不打完整诊断包**（2026-10-04 修）：原来无论什么原因都会走到
    `create_diagnostic_bundle()` —— 于是"每次正常退出游戏"都在 logs 目录留下一个几十 MB 的
    `diagnostics-<stamp>.zip`（而 `crashwatch` 在真崩溃时还会再打一个 `crash-*.zip`，
    一次崩溃两个大包、正常退出也堆包）。现在：只有**异常退出/超时**才打包，
    正常退出（`exit_code=0` 且没有崩溃特征）只写日志与尾巴文件。

    ⚠️ **2026-10-04 扩充**（用户原话：「日志包尽量多塞东西，**不要老是判据不够**」）：
      * 每条采集都进 `capture-manifest.txt`（"没有现场" vs "没去抓"必须能分开）；
      * `ReShade.log` **多候选**：它按 `RESHADE_BASE_PATH_OVERRIDE` 落在 `runtime\\reshade\\`，
        只抓游戏目录等于整条丢失（issue #13 缺陷三，2026-10-04 实测再次复现）；
      * 补 `Player.log`（Unity 侧最后几句话 —— 区分"崩了"与"被外部结束"的关键）；
      * EFMI 与 3DMigoto **两侧**日志都抓，并标出"是不是本次运行写过的"（旧日志
        被当现场用比没有更危险：那份 12.6 MB 的 `d3d11_log.txt` 半小时没变过）。
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = logs_dir(config)
    manifest = _new_capture_manifest()

    # ① ReShade 日志（多候选，文件名带来源标签，谁也不覆盖谁）
    for label, source in _try_capture(config, "ReShade 候选路径", reshade_log_candidates, config, game_dir) or []:
        arc = f"logs/ReShade-{label}-{stamp}.log"
        _try_capture(config, arc, _capture_tail, source, target_dir / f"ReShade-{label}-{stamp}.log",
                     lines=800, manifest=manifest, arcname=arc)
    # 兼容旧名字 `ReShade-<stamp>.log`（issue #13 的反馈者按这个找过），仅在游戏目录那份存在时
    game_reshade = (Path(game_dir) / "ReShade.log") if game_dir else None
    if game_reshade is not None and game_reshade.is_file():
        _try_capture(config, "ReShade-<stamp>", _capture_tail, game_reshade,
                     target_dir / f"ReShade-{stamp}.log", lines=800,
                     manifest=manifest, arcname=f"logs/ReShade-{stamp}.log")

    # ② EFMI / 3DMigoto 两侧的日志与 ini
    for label, source in _try_capture(config, "EFMI 日志候选", efmi_log_candidates, config) or []:
        arc = f"logs/{source.stem}-{label}-{stamp}{source.suffix}"
        _try_capture(config, arc, _capture_tail, source,
                     target_dir / f"{source.stem}-{label}-{stamp}{source.suffix}",
                     lines=500, manifest=manifest, arcname=arc)

    # ③ Unity 的 Player.log / Player-prev.log（游戏自己写的最后几句话）
    for path in _try_capture(config, "Player.log 候选", player_log_candidates) or []:
        arc = f"player/{path.parent.name}-{path.name}"
        _try_capture(config, arc, _capture_tail, path,
                     target_dir / f"player-{path.parent.name}-{path.name}",
                     lines=400, manifest=manifest, arcname=arc)

    # ④ 游戏目录里的 loader 残留（System32 那份 loader_debug.log 也看一眼）
    probes = _try_capture(config, "EFMI 路径", efmi_probe_paths, config) or {}
    loader_dir = probes.get("loader_dir")
    if loader_dir is not None:
        for name in ("loader_debug.log", "mc_bootstrap.log", "inject_order.txt"):
            arc = f"logs/{name}-{stamp}"
            _try_capture(config, arc, _capture_tail, Path(loader_dir) / name,
                         target_dir / f"{name}-{stamp}", lines=500,
                         manifest=manifest, arcname=arc)
    _try_capture(config, "loader_debug(System32)", _capture_tail,
                 Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "loader_debug.log",
                 target_dir / f"loader_debug-system32-{stamp}.log", lines=500,
                 manifest=manifest, arcname=f"logs/loader_debug-system32-{stamp}.log")

    # ⑤ EFMI 状态（路径以 config 为准；内部三路各自独立兜底）
    _try_capture(config, "EFMI 状态", log_efmi_state, config)

    if _is_normal_exit_reason(reason):
        # 正常退出不打包，但**采集清单仍然落盘**（下次排查能看出"当时抓了什么"）
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"capture-{stamp}.txt").write_text(
                capture_manifest_text(manifest), encoding="utf-8", errors="replace")
        except OSError:
            pass
        log_event(config, "游戏正常退出（不生成诊断包）", category="monitor", reason=reason)
        return
    _capture_windows_events(config)
    bundle = create_diagnostic_bundle(config, game_dir=game_dir,
                                      note=f"auto-postmortem: {_describe_reason(reason)}",
                                      manifest=manifest)
    log_event(config, "已生成诊断包", category="crash", path=bundle, reason=reason)


# ── 退出码 → 人话（2026-10-04 加）─────────────────────────────────────────────
# 为什么需要：反馈者机器上抓到 `exit_code=3221225781`，而当时包里**只有裸数字** ——
# 事后得靠人工把它折成 `0xC0000135` 再去查表，才知道是 `STATUS_DLL_NOT_FOUND`。
# 这个码本身是最强的判据之一（"有 DLL 没加载起来"），必须一抓下来就写成能直接读的形态。
# 取值：Windows NTSTATUS 常量（ntstatus.h）+ 常见 CRT/运行时退出码。
_EXIT_CODE_NAMES: dict[int, tuple[str, str]] = {
    0xC0000005: ("STATUS_ACCESS_VIOLATION", "访问了非法内存 —— 典型的内存/兼容性问题"),
    0xC0000017: ("STATUS_NO_MEMORY", "内存不足"),
    0xC000001D: ("STATUS_ILLEGAL_INSTRUCTION",
                 "执行了非法指令（CPU 指令集不匹配，或注入器写坏了指令流）"),
    0xC0000022: ("STATUS_ACCESS_DENIED", "权限被拒绝"),
    0xC000007B: ("STATUS_INVALID_IMAGE_FORMAT", "32/64 位混用或映像损坏"),
    0xC0000094: ("STATUS_INTEGER_DIVIDE_BY_ZERO", "整数除零"),
    0xC0000096: ("STATUS_PRIVILEGED_INSTRUCTION", "执行了特权指令"),
    0xC00000FD: ("STATUS_STACK_OVERFLOW", "栈溢出"),
    0xC000013A: ("STATUS_CONTROL_C_EXIT",
                 "进程被结束（Ctrl+C / 被别的程序 TerminateProcess）—— **不是自己崩的**"),
    0xC0000135: ("STATUS_DLL_NOT_FOUND",
                 "**有 DLL 加载失败** —— 被杀毒隔离 / 缺 VC 运行库 / 注入的 proxy 没有转发成功"),
    0xC0000139: ("STATUS_ENTRYPOINT_NOT_FOUND",
                 "DLL 里找不到入口点 —— 典型的**版本不匹配**（放错了另一版的 dll）"),
    0xC0000142: ("STATUS_DLL_INIT_FAILED", "DLL 找到了、但初始化失败"),
    0xC0000374: ("STATUS_HEAP_CORRUPTION", "堆被写坏"),
    0xC0000409: ("STATUS_STACK_BUFFER_OVERRUN",
                 "栈保护触发（/GS），或 **CRT 的 fail-fast**：C++ 异常逃出 DllMain / "
                 "std::terminate() 也走这里 —— 现场常常是游戏里弹一个"
                 "「Microsoft Visual C++ Runtime Library / Runtime Error!」对话框"),
    0xC0000417: ("STATUS_INVALID_CRUNTIME_PARAMETER", "传给 CRT 的参数非法"),
    0xC0000602: ("STATUS_FAIL_FAST_EXCEPTION", "主动 fail-fast（断言/完整性检查没过）"),
    0x40000015: ("FATAL_APP_EXIT",
                 "CRT 致命退出（abort() 被调用 —— 同样会弹 Runtime Error 对话框）"),
}


def describe_exit_code(code: Any) -> str:
    """把退出码写成人能读的一行；**认不出就如实说认不出，不猜**。

    退出码在 Windows 上是 32 位无符号，但 `ctypes` 有时给回带符号整数 —— 这里统一
    折成无符号再查表（否则 `0xC0000135` 会显示成 `-1073741515`，没人认得出）。
    """
    if code is None:
        return "（拿不到退出码 —— 进程句柄没打开，或进程已被 TerminateProcess 结束）"
    try:
        value = int(code)
    except (TypeError, ValueError):
        return f"（退出码不是整数：{code!r}）"
    unsigned = value & 0xFFFFFFFF
    if unsigned == 0:
        return "0x00000000 正常退出"
    text = f"0x{unsigned:08X}（{unsigned}）"
    known = _EXIT_CODE_NAMES.get(unsigned)
    if known:
        return f"{text} {known[0]} —— {known[1]}"
    if unsigned <= 0xFF:
        return f"{text} 普通非零退出码，含义由程序自己决定"
    return f"{text} 不是已知的 NTSTATUS —— 需要对照该程序自己的文档"


def _describe_reason(reason: str) -> str:
    """给 `exit_code=…` 这类内部 reason 补上人能读的解释。

    ⚠️ 只用于写进诊断包（`note`），**绝不参与 `_is_normal_exit_reason` 的判据** ——
    那个函数按精确字符串比对（`exit_code=0`），改格式会把判据弄坏。
    """
    text = str(reason or "").strip()
    match = re.fullmatch(r"exit_code=(-?\d+)", text)
    if not match:
        return text
    return f"{text} → {describe_exit_code(int(match.group(1)))}"


def _is_normal_exit_reason(reason: str) -> bool:
    """这次退出算"正常"吗（只有 `exit_code=0` 才算；超时/进程消失一律按异常处理）。

    为什么不看 Player.log 的卸载统计：那个判据属于"崩溃归因"（`crashwatch`），
    而这里只是决定**要不要打一个几十 MB 的包**——保守一点，只认明确的退出码 0。
    """
    return str(reason or "").strip() in ("exit_code=0", "exit_code=None")


def _monitor_process(config: Any, game_dir: Path | None, image_name: str, timeout: float) -> None:
    global _LAST_GAME_START

    log_event(config, "进程监视启动", category="monitor", image=image_name, timeout=timeout)
    found_pid: int | None = None
    handle: int | None = None
    started = time.monotonic()
    # ⚠️ 句柄打不开时的降级判据（2026-10-04 修，见下面 `handle is None` 分支的说明）
    degraded_logged = False
    try:
        while time.monotonic() - started < timeout:
            if _MONITOR_STOP.is_set():
                log_event(config, "进程监视被请求停止", category="monitor", image=image_name)
                _close_handle(handle)
                return
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
                    # 记下"这次游戏是什么时候起来的" —— 采集层用它判断抓到的日志
                    # 是**本次现场**还是上一次留下的旧文件（2026-10-04 加）。
                    _LAST_GAME_START = time.time()
                    log_event(config, "检测到游戏进程", category="monitor", image=image_name, pid=pid,
                              # 读不到就把原因写出来（否则"命令行是空的"永远是个谜 ——
                              # 原来那条 wmic 兜底在新系统上必然失败且不留痕迹）
                              command_line=command_line or (_LAST_COMMAND_LINE_ERROR or "（读不到命令行）"))
                if handle is None and found_pid is not None and not degraded_logged:
                    # ⚠️⚠️ **`OpenProcess` 拿不到句柄时必须降级**（2026-10-04 修）。
                    # 游戏以管理员运行时，非提权的我们 `OpenProcess` 会 Access denied
                    # ⇒ `handle = None` ⇒ 下面 `if handle and ...` **永远不成立**，
                    # 而 `ids` 又一直非空（进程还在）⇒ 连 `elif found_pid is not None` 也走不到
                    # ⇒ 这个线程**空转到超时**（默认 1800 秒），最后按 `monitor_timeout`
                    # 调 `_capture_postmortem` 再生成一个大诊断包 —— 崩溃取证白白晚 30 分钟。
                    # 降级为"按进程名消失"判据（下面那个 elif 分支），行为与句柄可用时等价。
                    degraded_logged = True
                    log_event(config, "拿不到游戏进程句柄（多半是它以管理员运行）——"
                                     "改用进程名消失作为退出判据", category="monitor",
                              level="WARN", pid=found_pid)
                if handle is not None and _process_exited(handle):
                    code = _process_exit_code(handle)
                    # 退出码必须**连同人话一起落盘**（2026-10-04）：光一个 3221225781，
                    # 事后要靠人工折成 0xC0000135 再查表才知道是"有 DLL 没加载起来"。
                    log_event(config, "游戏进程已退出", category="crash", image=image_name, pid=pid,
                              exit_code=code, exit_text=describe_exit_code(code))
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


def stop_process_monitor() -> bool:
    """请求停掉进程监视线程（**关窗口时调**）。

    ⚠️ 这个函数曾经**不存在**，而 `api.shutdown()` 用
    `getattr(diagnostics, "stop_process_monitor", None)` 期望它存在 —— 于是那个
    "停掉后台任务"的动作是**空操作**：监视线程是 daemon、最长跑 1800 秒，
    用户关窗后若进程没真正退出，它还会继续跑完并生成诊断包（2026-10-04 审计发现）。
    """
    _MONITOR_STOP.set()
    thread = _MONITOR_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    return True


def start_process_monitor(config: Any, *, game_dir: Path | None = None, image_name: str = "Endfield.exe", timeout: float = 1800.0) -> bool:
    global _MONITOR_THREAD
    if os.name != "nt":
        log_event(config, "非 Windows 平台，跳过进程监视", category="monitor")
        return False
    with _MONITOR_LOCK:
        if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
            log_event(config, "进程监视已在运行，跳过重复启动", category="monitor")
            return False
        _MONITOR_STOP.clear()      # 上一轮可能被 stop_process_monitor() 置过位
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
                         groups: list[dict[str, Any]] | None = None,
                         mods: list[str] | None = None) -> None:
    """把**本次自检**的 Mod 冲突结论落盘。

    为什么要落盘（2026-09-30）：崩溃监视跑在另一个线程（且常在用户下次开程序时才
    收集现场），它要判断"这次崩溃是不是 Mod 冲突造成的"，只能靠这份留痕 —— 否则
    弹窗只能笼统地说"异常退出"，用户不知道该先去清 Mod 还是去查注入。

    `groups`（2026-10-01 新增）：**结构化**冲突组（每组含涉及的 Mod 名 + 库内 id）——
    前端「选择要保留的 Mod」弹窗用它渲染"每组一个下拉框"，选完调
    `api.resolve_mod_conflicts()` 自动取消勾选其余的那些。`conflicts`（字符串）保留，
    是为了兼容既有文案与诊断包。

    `mods`（2026-10-01 修 bug 时新增）：**这份结论是对着哪一批 staged Mod 算出来的**。
    "启动前风险确认"要靠它判断结论是否过期 —— 用户手动删了库里的文件后，选择会变成
    空的，可这份 json 还留着上一次的冲突，于是"明明没选中任何 Mod 却提示崩溃风险"。
    """
    payload = {
        "at": int(time.time()),
        "at_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": bool(ok),
        "detail": str(detail or ""),
        "conflicts": [str(item) for item in (conflicts or [])],
        "groups": [dict(item) for item in (groups or []) if isinstance(item, dict)],
        "mods": sorted({str(item) for item in (mods or [])}),
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
    """把一个文件写进诊断包；**超大时只收尾部 `max_bytes`，并在包内注明被截断**。

    ⚠️ 原来超限就 `return`（**静默丢弃**）：`log_event` 把同一行同时写进 daily/session/launch
    三个日志且**没有轮转**，跑久了很容易超过 8 MB ⇒ 用户交上来的包里**最关键的日志整份缺失**，
    而包内没有任何提示（排查的人只会以为"日志是空的"）。
    现在改成尾部截断 + 带一行 `（已截断，仅保留最后 N MB）` 的说明——"一次抓齐"的前提是
    拿到的数据本身要能看出它被裁过。
    """
    try:
        if not path.is_file():
            return
        size = path.stat().st_size
        if size <= max_bytes:
            archive.write(path, arcname)
            return
        with open(path, "rb") as handle:
            handle.seek(size - max_bytes)
            tail = handle.read(max_bytes)
        header = (f"[诊断包提示] 原文件 {size:,} 字节，超过单文件上限 {max_bytes:,} 字节，"
                  f"这里只保留**尾部** {max_bytes:,} 字节（崩溃现场通常在末尾）。\n").encode("utf-8")
        archive.writestr(arcname, header + tail)
        archive.writestr(arcname + ".truncated.txt",
                         f"{path}: 原 {size} 字节，已截断为 {max_bytes} 字节\n")
    except (OSError, zipfile.BadZipFile):
        return


def _zip_tracked(
    archive: zipfile.ZipFile,
    source: Path,
    arcname: str,
    manifest: list[dict[str, Any]] | None,
    *,
    max_bytes: int = 8 * 1024 * 1024,
    required: bool = False,
) -> None:
    """把 `source` 收进包 **并在采集清单里记一行结果**（找不到也记）。

    `required=True` = "这个文件本该在"（例如 `Player.log`、`sbm_log.txt`）——
    找不到时清单里会写明"本该存在却找不到"，而不是含糊的 missing。
    """
    source = Path(source)
    if not source.is_file():
        _manifest_add(manifest, arcname=arcname, source=source, status="missing",
                      note=("本该存在却找不到（这条请一并反馈）" if required else "按当前配置不存在"))
        return
    try:
        stat = source.stat()
    except OSError as exc:
        _manifest_add(manifest, arcname=arcname, source=source, status="error", note=str(exc))
        return
    _safe_zip_write(archive, source, arcname, max_bytes=max_bytes)
    note = "" if stat.st_size <= max_bytes else f"超过 {max_bytes:,} 字节，只收了尾部"
    _manifest_add(manifest, arcname=arcname, source=source, status="ok", note=note,
                  size=stat.st_size, mtime=stat.st_mtime, fresh=_is_fresh(stat.st_mtime))


def _game_injection_summary(config: Any, game_dir: Path | None) -> list[str]:
    """summary 里那段"游戏目录注入了什么"的精简版（完整清单在 `game-inventory.txt`）。"""
    lines = ["", "-- 游戏目录注入（游戏起不来 / 缺 DLL 时先看这里）--"]
    from . import reshade_integration

    if game_dir is None or not Path(game_dir).is_dir():
        lines.append(f"（没有游戏目录：{game_dir}）")
        return lines
    game = Path(game_dir)
    for name in reshade_integration.LOADER_PROXY_MODULES:
        path = game / name
        if not path.is_file():
            continue
        try:
            if not reshade_integration.looks_like_loader_proxy(path):
                continue
            kind = reshade_integration.loader_kind(path) or "未知"
            size = path.stat().st_size
        except (OSError, AttributeError):
            continue
        backup = path.with_name(name + ".bak")
        lines.append(f"{name}: loader proxy（归属={kind}）{size:,} B；"
                     f"原版备份 {backup.name}：{'在' if backup.is_file() else '**缺失 —— 无法安全还原**'}")
    plugin = game / reshade_integration.PLUGIN_DIR_NAME
    if plugin.is_dir():
        try:
            for entry in sorted(plugin.iterdir(), key=lambda p: p.name.lower()):
                if entry.is_file():
                    lines.append(f"plugin\\{entry.name}: {entry.stat().st_size:,} B")
        except OSError:
            pass
    if len(lines) == 2:
        lines.append("（游戏目录里没有检测到第三方注入 proxy）")
    return lines


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
    # ⚠️ 段名是 **`Launcher`**（XXMI 的 `config_version` 2.2.x 实测），不是 `Config`。
    #    2026-10-02 由反馈者诊断包定位：读错段会让这一行**永远**打印 `active_importer: None`
    #    / `enabled_importers: None` —— 本机正常环境（`Launcher.active_importer == 'EFMI'`）
    #    也一样是 None，等于每次排查都被自己的摘要带偏。（`Config` 只作为老版兜底。）
    section = data.get("Launcher") or data.get("Config") or {}
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


_XXMI_EXE_PATH = re.compile(r"exe_path=WindowsPath\('([^']+)'\)")
_XXMI_WORK_DIR = re.compile(r"work_dir=WindowsPath\('([^']*)'\)")
_XXMI_INJECTED = re.compile(r"Successfully injected DLL to process (\S+) \(PID: (\d+)\): (.+)")
_XXMI_INJECT_FAILED = re.compile(r"注入额外库 (.+?) 失败")
_XXMI_STOPPED = re.compile(r"Stopping process:")


def _xxmi_injection_summary(config: Any, *, tail_lines: int = 4000, keep: int = 6) -> list[str]:
    """XXMI 自己的注入现场（**解析成字段**，不是把 200 KB 日志原样塞进包）。

    为什么要有（2026-10-04 反馈者现场）：他报"ReShade 没注入"，而 XXMI 的日志里明明白白写着
    `Successfully injected DLL to process Endfield.exe (PID: 2632): E:\\新建文件夹\\d3d12.dll`
    —— 注入**确实发生了**，只是注入的是"另一个目录的那份 d3d12.dll"；同一份日志还记了
    `work_dir=E:/新建文件夹/Arknights Endfield`（游戏目录的真相）和一连串 `Stopping process`
    （"游戏被反复结束"）。这几条以前全靠人肉翻 208 KB 原始日志，等于没有判据。
    """
    lines = ["", "-- XXMI 注入现场（它才是真正启动游戏、注入 dll 的那一环）--"]
    launcher = config.xxmi_launcher_path
    if launcher is None:
        lines.append("（未配置 XXMI Launcher）")
        return lines
    root = Path(launcher).parent.parent.parent
    log = root / "XXMI Launcher Log.txt"
    if not log.is_file():
        lines.append(f"（没有 {log}）")
        return lines
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        lines.append(f"读取失败 {log}: {exc}")
        return lines
    rows = text.splitlines()[-tail_lines:]
    starts: list[tuple[str, str]] = []
    injected: list[str] = []
    failures: list[str] = []
    stops = 0
    errors: list[str] = []
    for row in rows:
        if "Starting process:" in row:
            exe = _XXMI_EXE_PATH.search(row)
            work = _XXMI_WORK_DIR.search(row)
            starts.append((exe.group(1) if exe else "?", work.group(1) if work else "?"))
        match = _XXMI_INJECTED.search(row)
        if match:
            injected.append(f"{match.group(1)} (PID {match.group(2)}) ← {match.group(3).strip()}")
            continue
        if _XXMI_STOPPED.search(row):
            stops += 1
        failed = _XXMI_INJECT_FAILED.search(row)
        if failed:
            failures.append(failed.group(1).strip())
        if " ERROR " in row:
            message = row.split(" ERROR ", 1)[1].strip()
            if message and message not in errors:
                errors.append(message[:200])
    lines.append(f"日志: {log}（解析尾部 {len(rows)} 行）")
    lines.append(f"窗口内统计：启动 {len(starts)} 次 / 成功注入 {len(injected)} 次 / "
                 f"Stopping process {stops} 次 / 注入失败 {len(failures)} 次")
    for exe, work in starts[-keep:]:
        lines.append(f"    启动 : exe={exe}  work_dir={work}")
    for row in injected[-keep * 2:]:
        lines.append(f"    注入 : {row}")
    for row in failures[-keep:]:
        lines.append(f"    !! 注入失败: {row}")
    if errors:
        lines.append("    XXMI 自己报的错（去重，最多 5 条）:")
        for row in errors[:5]:
            lines.append(f"      {row}")
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


# ---------------------------------------------------------------------------
# 2026-10-04：反馈者「ReShade 没注入」那次暴露的判据缺口（用户原话：「为什么你修了这么多轮，
# 还是判据不够，你能不能一次加完」）。这一批全部是"数据其实已经在现场、只是没人解析/没人列"。
# ---------------------------------------------------------------------------

# 面板 addon 自己写的日志名（**不是** `endfieldmodcontroller.addon.log`，见 addon 的 addon_log_path()）
ADDON_LOG_NAME = "modecontroller.addon.log"
ADDON_LOG_LEGACY_NAMES = ("endfieldmodcontroller.addon.log",)
# ReShade 扫描 add-on 的两个后缀（同名同时存在 ⇒ 第二次注册必失败）
ADDON_SCAN_SUFFIXES = (".addon", ".addon64")
_ADDON_SCAN_DIR = re.compile(r"Searching for add-ons \(\*\.addon, \*\.addon64\) in '([^']+)'")
_ADDON_REGISTERED = re.compile(
    r'Registered add-on "([^"]+)"[^ ]* ?([^ ]*) using ReShade API version (\d+)')
_ADDON_LOAD_FAILED = re.compile(r"Failed to load add-on from '([^']+)' with error code (\d+)")
_ADDON_DUPLICATE = re.compile(
    r'Failed to register add-on, because another one with the same name \("([^"]+)"\)')
_RESHADE_HOST = re.compile(r"loaded from '([^']+)' into '([^']+)'")


def addon_log_candidates(config: Any, game_dir: Path | None = None) -> list[tuple[str, Path]]:
    """面板 addon 自己写的那份日志可能落在哪几处。

    ⚠️ **2026-10-04 修**：这里以前只有 `endfieldmodcontroller.addon.log` —— **文件名根本不对**。
    addon 真实写的是 **`modecontroller.addon.log`**（`reshade_addon/src/endfieldmodcontroller_addon.cpp`
    的 `addon_log_path()`），于是每次诊断包里那两条都是 missing。而这次"面板为什么没加载"的
    一手证据恰恰只在这份文件里：addon 从 DllMain 第一行就开始写，**加载失败也会留下"走到哪一步"**
    （2026-10-04 起还会写 `register_addon FAILED (api=… last_error=…)`）。
    老名字保留是为了还能读懂以前导出的包。
    """
    bases: list[tuple[str, Path]] = [
        ("dlss5", Path(config.dlss5_path)),
        ("reshade", Path(config.reshade_runtime_path)),
    ]
    if game_dir is not None:
        bases.append(("game", Path(game_dir)))
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp:
        bases.append(("temp", Path(temp)))

    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for name in (ADDON_LOG_NAME, *ADDON_LOG_LEGACY_NAMES):
        for label, base in bases:
            path = base / name
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((label if name == ADDON_LOG_NAME else f"{label}-{name}", path))
    return out


def _reshade_addon_summary(config: Any, game_dir: Path | None) -> list[str]:
    """把每份 ReShade.log 里的**插件加载结果**提炼成几行。

    为什么单列（2026-10-04 反馈者现场）：他报"ReShade 没注入"，而包里其实躺着决定性的一行
    —— `ERROR Failed to load add-on from '…\\endfieldmodcontroller.addon64' with error code 4551!`
    —— 但**没有任何代码解析它**，于是"面板没加载"这件事在摘要里完全看不见，只能靠人肉翻
    36 KB 的日志（还得先知道该翻哪一份）。

    判据本身很直白：
      * `Registered add-on "X" …` = 加载成功；
      * `Failed to load add-on from 'P' with error code N` = **DLL 加载失败**（**不是**"文件不存在"，
        文件在不在由文件快照/目录清单回答）；
      * `Failed to register add-on … same name` = 被 ReShade 拒（同名重复，通常是 `.addon` 与
        `.addon64` 同时存在）。
    ⚠️ 这里**故意不翻译 error code 的含义** —— 它不是标准 Win32 码时乱给结论只会误导
    （同族教训：「下结论之前先找对照」）。
    """
    lines = ["", "-- ReShade 插件（add-on）加载结果（面板没出来 / DLSS5 菜单缺失时先看这里）--"]
    candidates = _try_capture(config, "ReShade 候选", reshade_log_candidates, config, game_dir) or []
    if not candidates:
        lines.append("（没有可读的 ReShade.log —— 采集失败，或 ReShade 从未在本机加载过）")
        return lines
    parsed_any = False
    for label, path in candidates:
        path = Path(path)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            lines.append(f"[{label}] 读取失败: {exc}")
            continue
        host = _RESHADE_HOST.findall(text)
        scan_dirs = sorted(set(_ADDON_SCAN_DIR.findall(text)))
        registered = _ADDON_REGISTERED.findall(text)
        failed = _ADDON_LOAD_FAILED.findall(text)
        duplicate = sorted(set(_ADDON_DUPLICATE.findall(text)))
        lines.append(f"[{label}] {path}")
        if host:
            lines.append(f"    ReShade 底座 : {host[0][0]}")
            lines.append(f"    注入进进程   : {host[0][1]}")
        for base in scan_dirs:
            lines.append(f"    扫描插件目录 : {base}")
        for name, _version, api in registered:
            parsed_any = True
            lines.append(f"    OK  已注册   : {name}（API {api}）")
        for target, code in failed:
            parsed_any = True
            lines.append(f"    !! **加载失败**: {target}  （error code {code}）")
        for name in duplicate:
            parsed_any = True
            lines.append(f"    !! 同名重复  : {name}（`.addon` 与 `.addon64` 同时存在会被拒）")
    if not parsed_any:
        lines.append("（日志里没有任何 add-on 加载记录：ReShade 多半还没走到扫描插件那一步）")
    return lines


def dir_listing(config: Any, root: Path, *, limit: int = 120, subdirs: int = 10) -> list[str]:
    """一个目录的顶层清单（名字/字节/时间）+ 子目录一层摘要。

    为什么要有（2026-10-04）：包里对 `dlss5_dir` 只有 8 条固定文件名的探测，**没有目录枚举**，
    于是"这个目录里到底有什么、有几份同名 addon、ReShade.ini 在不在"全都回答不了 ——
    而反馈者正是把 `dlss5_dir` 填成了游戏目录，目录内容就是判据本身。
    """
    root = Path(root)
    if not root.is_dir():
        return [f"**目录不存在**  {root}"]
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    except OSError as exc:
        return [f"读取失败 {root}: {exc}"]
    files = [p for p in entries if p.is_file()]
    dirs = [p for p in entries if p.is_dir()]
    lines = [f"{root}  （{len(files)} 个文件 / {len(dirs)} 个子目录）"]
    for path in files[:limit]:
        try:
            info = path.stat()
        except OSError:
            lines.append(f"    ?  {path.name}")
            continue
        stamp = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"    {info.st_size:>12,} B  {stamp}  {path.name}")
    if len(files) > limit:
        lines.append(f"    …另有 {len(files) - limit} 个文件")
    for path in dirs[:subdirs]:
        try:
            count = sum(1 for _ in path.iterdir())
        except OSError:
            count = -1
        lines.append(f"    [目录] {path.name}/  （{count if count >= 0 else '?'} 项）")
    if len(dirs) > subdirs:
        lines.append(f"    …另有 {len(dirs) - subdirs} 个子目录")
    return lines


def addon_duplicate_report(bases: list[Path]) -> list[str]:
    """同名 `.addon` 与 `.addon64` 同时存在 = 必有一次注册失败（ReShade 两种后缀都扫）。"""
    lines: list[str] = []
    for base in bases:
        base = Path(base)
        if not base.is_dir():
            continue
        try:
            names = {p.name.lower() for p in base.iterdir() if p.is_file()}
        except OSError:
            continue
        for name in sorted(names):
            if not name.endswith(".addon64"):
                continue
            twin = name[: -len(".addon64")] + ".addon"
            if twin in names:
                lines.append(f"    !! {base} 里 {name} 与 {twin} **同时存在**"
                             "（会被加载两次，第二次注册必失败）")
    return lines


def _xxmi_importer_fields(config: Any) -> dict[str, Any]:
    """XXMI 配置里 EFMI 段的**关键字段**（`game_folder` 一族决定"XXMI 认为游戏在哪"）。"""
    from . import reshade_integration

    launcher = config.xxmi_launcher_path
    if launcher is None:
        return {}
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None or not Path(config_path).is_file():
        return {}
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    importer = ((data.get("Importers") or {}).get("EFMI") or {}).get("Importer") or {}
    return dict(importer)


def _game_dir_reality_summary(config: Any, game_dir: Path | None) -> list[str]:
    """把"我们以为的游戏目录"与"实际跑的那个"摆在一起。

    2026-10-04 反馈者现场：`config.game_exe` 指向官方启动器推断出来的
    `D:\\Hypergryph Launcher\\games\\Arknights Endfield`，而游戏实际跑在
    `E:\\新建文件夹\\Arknights Endfield`（XXMI 的 `EFMI.Importer.game_folder == "E:/"`，
    进程命令行也是 E 盘）。于是 `game-inventory.txt`、proxy 归属、`plugin\\` 清单**整段都在看一个
    他根本不玩的安装**，真目录一份清单都没有 —— 这类"目录错位"会让后面每一条结论都失效，
    所以必须并列摆出来，而不是默认 `game_exe` 就是游戏。
    """
    lines = ["", "-- 游戏目录：我们以为的 vs 实际跑的（错位时下面所有“游戏目录”结论都失效）--"]
    lines.append(f"config.game_exe         : {config.game_exe or '(未配置)'}")
    lines.append(f"config.official_launcher: {config.official_launcher or '(未配置)'}")
    lines.append(f"本次采集用的 game_dir   : {game_dir or '(没有)'}")
    fields = _try_capture(config, "XXMI importer 字段", _xxmi_importer_fields, config) or {}
    if fields:
        lines.append(f"XXMI EFMI.game_folder   : {fields.get('game_folder')!r}")
        lines.append(f"XXMI game_folder_names  : {fields.get('game_folder_names')!r}")
        lines.append(f"XXMI game_folder_children: {fields.get('game_folder_children')!r}")
        for lib in [x.strip() for x in str(fields.get("extra_libraries") or "").splitlines() if x.strip()]:
            lines.append(f"XXMI 注入库             : {lib}")
    else:
        lines.append("XXMI EFMI 段            : （读不到 —— 没配 XXMI 或配置还没生成）")
    try:
        ids = _find_process_ids("Endfield.exe")
    except Exception:  # noqa: BLE001
        ids = []
    if ids:
        for pid in ids[:3]:
            lines.append(f"正在运行的 Endfield.exe : pid={pid} 命令行={_process_command_line(pid)}")
    else:
        lines.append("正在运行的 Endfield.exe : （当前没有在跑）")
    lines.append("注：`game_exe` 只是“我们按官方启动器推断出来的”一个候选；真正在跑的那个以上面的"
                 "XXMI game_folder / 进程命令行为准。")
    return lines


def _dlss5_dir_summary(config: Any, game_dir: Path | None) -> list[str]:
    """`dlss5_dir`（DLSS5 / 第一人称目录）+ ReShade 底座所在目录的**完整清单**与重名检查。

    这是 2026-10-04 那次最直接的判据：反馈者把设置页的「DLSS5 / 第一人称目录」填成了**游戏目录**
    （`E:\\新建文件夹\\Arknights Endfield`），而底座 `d3d12.dll` 在**上一级** `E:\\新建文件夹` ——
    两边各有什么文件，包内原本一个字都没有，只能靠猜。
    """
    lines = ["", "-- DLSS5 目录 / ReShade 底座目录的内容（“填错目录”只能靠这里看）--"]
    bases: list[Path] = [Path(config.dlss5_path)]
    dll = config.reshade_dll_path
    if dll is not None:
        bases.append(Path(dll).parent)
    bases.append(Path(config.reshade_runtime_path))
    if game_dir is not None:
        bases.append(Path(game_dir))
    seen: set[str] = set()
    for base in bases:
        key = str(base).lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append("")
        lines.extend(_try_capture(config, f"目录清单 {base}", dir_listing, config, base) or [])
        dll_marker = base / "d3d12.dll"
        lines.append(f"    → d3d12.dll（ReShade 底座）: "
                     + ("在" if dll_marker.is_file() else "**不在**"))
    dupes = _try_capture(config, "同名 addon 检查", addon_duplicate_report, bases) or []
    lines.append("")
    if dupes:
        lines.append("同名 addon 重复检查：")
        lines.extend(dupes)
    else:
        lines.append("同名 addon 重复检查：没有发现 `.addon` / `.addon64` 同名并存")
    return lines


def _addon_log_summary(config: Any, game_dir: Path | None) -> list[str]:
    """面板 addon 自己的日志（`modecontroller.addon.log`）最后若干行 + 落点候选。

    加载失败时它就是唯一的"走到哪一步"记录（DllMain 第一行就开始写），所以**平铺所有候选路径**，
    包括"哪里没有"，并明确说明"没有"意味着什么。
    """
    lines = ["", "-- 面板 addon 自己的日志（加载失败时唯一能回答“走到哪一步”的东西）--"]
    found = 0
    for label, path in addon_log_candidates(config, game_dir):
        path = Path(path)
        if not path.is_file():
            continue
        found += 1
        try:
            info = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            lines.append(f"[{label}] 读取失败 {path}: {exc}")
            continue
        stamp = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        rows = [row for row in text.splitlines() if row.strip()]
        lines.append(f"[{label}] {path}  （{info.st_size:,} B，最后写于 {stamp}，{len(rows)} 行）")
        for row in rows[-12:]:
            lines.append(f"    {row[:200]}")
    if not found:
        lines.append(f"（一条都没找到：{ADDON_LOG_NAME} 在这些候选路径里都不存在 —— "
                     "要么 addon 从未被加载过，要么它的 base path 在别处）")
    return lines



def create_diagnostic_bundle(
    config: Any,
    *,
    game_dir: Path | None = None,
    note: str = "manual",
    manifest: list[dict[str, Any]] | None = None,
) -> Path:
    """打一个诊断包（zip）：日志 + 上下文 + **采集清单**（不含游戏二进制）。

    ⚠️ **2026-10-04 大幅扩充**（用户原话：「日志包尽量多塞东西，**不要老是判据不够**」）。
    这次进来的是之前反复缺的判据：
      * `ReShade.log` —— **多候选**（它按 `RESHADE_BASE_PATH_OVERRIDE` 落在
        `runtime\\reshade\\`，只抓游戏目录等于整份丢失；issue #13 缺陷三）；
      * `Player.log` / `Player-prev.log` —— Unity 侧最后几句话（整份，不截尾）；
      * WER 报告（`Report.wer`）与 Unity / 官方崩溃目录里的文本日志；
      * `game-inventory.txt` —— 游戏目录清单 + **proxy 归属 / 原版备份在不在** + plugin 清单；
      * `environment.txt` —— 事件日志 / 反作弊服务 / 崩溃转储 / 游戏版本 / 相关进程；
      * `xxmi/Config.json`（**脱敏**）+ `XXMI Launcher Log.txt`（注入参数的一手记录）；
      * `plugin/` 下的文本（`sbm_log.txt`、`poser-install.json`…）与 `SecondaryMotion/**/*.json`；
      * **`capture-manifest.txt`** —— 每项"抓到没有、为什么没抓到、是不是本次运行写过的"。
    """
    _capture_windows_events(config)
    runtime = Path(config.runtime_path)
    target_dir = logs_dir(config)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # ⚠️ 同秒两次导出的包不能互相覆盖（2026-10-04）：名字是秒级时间戳，
    # `zipfile` 打开同名文件会**合并/覆盖**上一次的内容。收敛到 fsutil.unique_sibling。
    from . import fsutil

    out = fsutil.unique_sibling(target_dir / f"diagnostics-{stamp}.zip")
    if manifest is None:
        manifest = _new_capture_manifest()
    probes = _try_capture(config, "EFMI 路径", efmi_probe_paths, config) or {}
    loader_dir = Path(probes["loader_dir"]) if probes.get("loader_dir") else runtime / "migoto"
    config_path = Path(getattr(config, "_config_path", "") or "")
    game_path = Path(game_dir) if game_dir is not None else None

    summary = [
        "EndfieldModController diagnostic bundle",
        f"created={datetime.now().isoformat(timespec='seconds')}",
        f"note={note}",
        f"session_log={session_log_path(config)}",
        f"runtime={runtime}",
        f"loader={loader_dir}",
        f"game_dir={game_dir}",
    ]
    summary.extend(_game_injection_summary(config, game_path))
    summary.extend(_nvngx_fingerprint(config))
    summary.extend(_xxmi_summary(config))
    # XXMI 自己的注入现场（启动参数 / work_dir / 每个 dll 的注入结果 / 它报的错）—— 2026-10-04 加
    summary.extend(_xxmi_injection_summary(config))
    summary.extend(_ngx_consumer_summary(game_path))
    summary.extend(_shader_summary(config))
    # ⚠️ 2026-10-04 补的四段（用户原话：「你能不能一次加完」）。
    #    这四段全是"数据本来就在现场、只是没人解析/没人列"，不是新采集：
    #      * `_reshade_addon_summary` —— ReShade.log 里的 add-on 成功/失败行（本次事故的直接答案）；
    #      * `_addon_log_summary`     —— 面板 addon 自己的日志（加载失败时的"走到哪一步"）；
    #      * `_game_dir_reality_summary` —— "我们以为的游戏目录 vs 实际跑的"；
    #      * `_dlss5_dir_summary`     —— DLSS5/base 目录里到底有什么 + 同名 addon 重复检查。
    summary.extend(_reshade_addon_summary(config, game_path))
    summary.extend(_addon_log_summary(config, game_path))
    summary.extend(_game_dir_reality_summary(config, game_path))
    summary.extend(_dlss5_dir_summary(config, game_path))
    # 运行时组件清单（2026-10-02 加）：文件名 / 字节 / sha256 / 是否偏离随包基线。
    # 那天用户遇到"配套损坏 ⇒ 游戏启动几十秒后崩"，包里却没有这份清单，
    # 事后连"装的是哪一版组件"都回答不了（详见 runtime_assets.inventory_text）。
    try:
        from . import runtime_assets

        inventory = runtime_assets.inventory_text(config)
    except Exception as exc:  # noqa: BLE001
        inventory = f"（收集运行时清单失败：{exc}）"
    summary.append("")
    summary.append("-- 运行时组件清单（runtime\\dlss5）--")
    summary.extend(inventory.splitlines())
    # 设备型号 / 显卡与驱动（用户 2026-10-01 要求）：判断"是不是显卡不支持"就靠这段。
    try:
        from . import deviceinfo

        summary.extend(deviceinfo.summary_lines())
    except Exception as exc:  # noqa: BLE001
        summary.append(f"（设备信息读取失败: {exc}）")

    # 游戏之外的现场（事件日志 / 反作弊服务 / 转储 / 版本 / 进程）——**一次 PowerShell 拿全**；
    # 拿不到也把原因写进 environment.txt 与采集清单（"抓不到"本身是判据：
    # 比如"没有 WER 记录"能说明进程不是自己崩的，而"采集失败"什么也说明不了）。
    env_text, env_error = collect_environment_report(config, game_path)
    inventory_text = game_dir_inventory_text(config, game_path)

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(target_dir.glob("*.log")):
            _safe_zip_write(archive, path, f"logs/{path.name}")
        _safe_zip_write(archive, launch_log_path(config), "logs/launch.log")
        for path in sorted(target_dir.glob("*.txt")):
            _safe_zip_write(archive, path, f"logs/{path.name}")
        # ① 游戏目录里的文本类产物（不收 dll/exe 本体）
        if game_path is not None:
            from . import reshade_integration

            for name in ("ReShade.ini", "ReShade.log", "actions.tsv", "user_ini_path.txt",
                         "loader_debug.log", "d3d11_log.txt", "endfieldmodcontroller.addon.log",
                         # ⚠️ `modecontroller.addon.log` 才是面板 addon **真实**写的名字；
                         #    `panel_info.txt` 是它读的面板状态（2026-10-04 补：以前只找错名那个，
                         #    于是"面板为什么没加载"的一手证据每次都整份 missing）
                         ADDON_LOG_NAME, "panel_info.txt",
                         "d3dx.ini", "d3dx_user.ini", "inject_order.txt", "version.txt", "app.info"):
                _zip_tracked(archive, game_path / name, f"game/{name}", manifest,
                             required=name in ("d3dx.ini", "d3dx_user.ini"))
            # ①a ReShade 日志的其它候选位置（**这就是 issue #13 缺陷三**：
            #     它按 `RESHADE_BASE_PATH_OVERRIDE` 落在 `runtime\reshade\`）
            for label, source in _try_capture(config, "ReShade 候选", reshade_log_candidates,
                                              config, game_path) or []:
                if label == "game":
                    continue                      # 上面那条已按原名收过
                _zip_tracked(archive, source, f"reshade/{label}-ReShade.log", manifest)

            # ①b plugin 目录下的文本（`sbm_log.txt` 是"插件到底起没起来"的一手材料）
            plugin = game_path / reshade_integration.PLUGIN_DIR_NAME
            if plugin.is_dir():
                try:
                    entries = sorted(plugin.iterdir(), key=lambda p: p.name.lower())
                except OSError:
                    entries = []
                for entry in entries:
                    if not entry.is_file():
                        continue
                    if entry.suffix.lower() not in (".log", ".txt", ".json", ".ini", ".tsv"):
                        continue
                    _zip_tracked(archive, entry, f"plugin/{entry.name}", manifest,
                                 required=entry.name.lower() == "sbm_log.txt")
            # ①c SecondaryMotion 的 json（插件运行状态 / 角色数据 / 预设）
            secondary = game_path / "SecondaryMotion"
            if secondary.is_dir():
                try:
                    payloads = [p for p in secondary.rglob("*.json") if p.is_file()]
                    payloads.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                except OSError:
                    payloads = []
                for entry in payloads[:80]:
                    arc = "game/SecondaryMotion/" + entry.relative_to(secondary).as_posix()
                    _zip_tracked(archive, entry, arc, manifest, max_bytes=2 * 1024 * 1024)
            # ①d **游戏自己的崩溃日志**（2026-10-04 加，反馈者 AST 那次暴露的缺口）。
            #     那次游戏退出码是 `0xC0000135 STATUS_DLL_NOT_FOUND`（"有 DLL 没加载起来"），
            #     而 Windows 侧**一条 WER 都没有**（被 TerminateProcess / 显式退出码结束不留事件）。
            #     游戏自带的 CrashSight（崩溃上报 SDK）是**唯一**可能指名道姓写出"崩在哪、
            #     缺什么"的现场 —— 而整份诊断包以前完全没采集它，判据因此断在这里。
            crashsight = game_path / "CrashSightLog"
            if crashsight.is_dir():
                try:
                    cs_logs = sorted((p for p in crashsight.rglob("*") if p.is_file()),
                                     key=lambda p: p.stat().st_mtime, reverse=True)
                except OSError:
                    cs_logs = []
                for entry in cs_logs[:12]:
                    arc = "game/CrashSightLog/" + entry.relative_to(crashsight).as_posix()
                    _zip_tracked(archive, entry, arc, manifest, max_bytes=2 * 1024 * 1024)
            # ①e 反作弊目录里的文本（ACE 的日志/配置）—— 判断"是不是被反作弊结束"的一手材料。
            anticheat = game_path / "AntiCheatExpert"
            if anticheat.is_dir():
                try:
                    ac_files = [p for p in anticheat.rglob("*") if p.is_file()
                                and p.suffix.lower() in (".log", ".txt", ".json", ".ini", ".dat")]
                    ac_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                except OSError:
                    ac_files = []
                for entry in ac_files[:20]:
                    arc = "game/AntiCheatExpert/" + entry.relative_to(anticheat).as_posix()
                    _zip_tracked(archive, entry, arc, manifest, max_bytes=1024 * 1024)

        # ①g 面板 addon 自己的日志（**多候选**：dlss5 目录 / runtime\reshade / 游戏目录 / %TEMP%）
        #     与**目录枚举**。两者都是 2026-10-04「ReShade 没注入」那次最缺的判据：
        #     addon 的日志文件名原本写错（永远 missing），而"那个目录里到底有什么"从来没人列过。
        #     ⚠️ 刻意放在 `game_path is not None` 之外 —— 这两件事与"有没有配游戏目录"无关。
        for label, source in _try_capture(config, "addon 日志候选", addon_log_candidates,
                                          config, game_path) or []:
            source = Path(source)
            if source.is_file():
                _zip_tracked(archive, source, f"addon-log/{label}-{ADDON_LOG_NAME}", manifest)
        listings: list[str] = []
        for title, root in (
            ("dlss5_dir（设置里的「DLSS5 / 第一人称目录」）", Path(config.dlss5_path)),
            ("reshade_runtime（我们设的 RESHADE_BASE_PATH_OVERRIDE 目录）",
             Path(config.reshade_runtime_path)),
        ):
            listings.append(f"===== {title} =====")
            listings.extend(_try_capture(config, f"目录清单 {title}", dir_listing, config, root) or [])
            listings.append("")
        if game_path is not None:
            listings.append("===== game_dir（我们以为的游戏目录）=====")
            listings.extend(_try_capture(config, "目录清单 game_dir", dir_listing,
                                         config, game_path) or [])
            listings.append("")
        listings.append("===== 同名 addon 重复检查（`.addon` 与 `.addon64` 并存会被加载两次）=====")
        dupes = _try_capture(config, "同名 addon 检查", addon_duplicate_report,
                             [Path(config.dlss5_path), Path(config.reshade_runtime_path)]) or []
        listings.extend(dupes or ["（没有发现同名并存）"])
        archive.writestr("dir-listings.txt", "\n".join(listings) + "\n")
        _manifest_add(manifest, arcname="dir-listings.txt",
                      source="(目录枚举：dlss5 目录 / ReShade override 目录 / 游戏目录)",
                      status="ok", note=f"{len(listings)} 行")

        # ② EFMI / 3DMigoto 两侧的 ini 与日志（**两侧都收**，谁是谁写清楚）
        for label, source in _try_capture(config, "EFMI 日志候选", efmi_log_candidates, config) or []:
            if source.is_file():
                _zip_tracked(archive, source, f"loader/{label}-{source.name}", manifest)
        # ②a loader 目录里的其它产物（自造的 loader / bootstrap 残留）
        for name in ("mc_bootstrap.log", "mc_bootstrap.dll", "inject_order.txt", "actions.tsv",
                     "user_ini_path.txt", "endfieldmodcontroller.addon.log"):
            _zip_tracked(archive, loader_dir / name, f"loader/{name}", manifest)

        # ③ Unity 的 Player.log（整份；这是"崩了 vs 被外部结束"的关键判据）
        for path in _try_capture(config, "Player.log 候选", player_log_candidates) or []:
            _zip_tracked(archive, path, f"player/{path.parent.name}-{path.name}", manifest,
                         max_bytes=32 * 1024 * 1024,
                         required=path.name.lower() == "player.log")

        # ④ WER 报告 + Unity / 官方崩溃目录里的文本日志
        #    ⚠️ **“没有”也必须留一条**（2026-10-04 补）：以前空结果不留任何 manifest 条目，
        #    于是"没有 WER 记录"这个判据**无法与"根本没去抓"区分** —— 正是"判据不够"的典型。
        wer_reports = _try_capture(config, "WER 报告", wer_report_paths) or []
        for path in wer_reports:
            _zip_tracked(archive, path, f"wer/{path.parent.name}-{path.name}", manifest)
        if not wer_reports:
            _manifest_add(manifest, arcname="wer/", source="WER ReportArchive/ReportQueue",
                          status="missing",
                          note="没有本机 WER 报告（**已查过**）。注意：CRT 的 abort 对话框会把进程"
                               "卡住且不产生事件 ⇒「没有 WER」≠「没出过事」")
        unity_crashes = _try_capture(config, "Unity 崩溃日志", unity_crash_logs) or []
        for path in unity_crashes:
            _zip_tracked(archive, path, f"unity-crash/{path.parent.name}-{path.name}", manifest)
        if not unity_crashes:
            _manifest_add(manifest, arcname="unity-crash/", source="Unity 崩溃目录",
                          status="missing", note="没有 Unity 崩溃日志（**已查过**）")

        # ⑤ XXMI 侧：脱敏配置 + 它自己的日志（注入参数与注入结果的一手记录）
        xxmi_text, xxmi_note = sanitized_xxmi_config(config)
        if xxmi_text:
            archive.writestr("xxmi/Config.json", xxmi_text)
            _manifest_add(manifest, arcname="xxmi/Config.json", source="(XXMI 配置，签名值已脱敏)",
                          status="ok", note="signature 字段只保留长度")
        else:
            _manifest_add(manifest, arcname="xxmi/Config.json", source="(XXMI 配置)",
                          status="missing", note=xxmi_note)
        launcher = config.xxmi_launcher_path
        if launcher is not None:
            xxmi_root = Path(launcher).parent.parent.parent
            for name in ("XXMI Launcher Log.txt", "XXMI Launcher Log.old.txt"):
                _zip_tracked(archive, xxmi_root / name, f"xxmi/{name}", manifest,
                             required=name == "XXMI Launcher Log.txt")
        # DLSS5 现场：`dlss5-feed.log` 是判断"神经渲染有没有出帧、卡在哪一步"的关键证据。
        # 2026-09-30 有一个 issue 就因为它没被收进包里，导致只能靠猜（那条反馈最终是
        # 靠 dlss5-feed.addon64 的 fileVersion 才对上线索）。
        dlss5_dir = Path(config.dlss5_path)
        for name in ("dlss5-feed.log", "dlss5-feed.cfg", "ReShade.ini", "ReShadePreset.ini", "ReShade.log",
                     "panel_info.txt", "actions.tsv", "user_ini_path.txt"):
            _zip_tracked(archive, dlss5_dir / name, f"dlss5/{name}", manifest,
                         required=name in ("dlss5-feed.log", "ReShade.ini"))
        state = mod_conflict_state(config)
        if state:
            try:
                archive.writestr("mod_conflicts.json", json.dumps(state, ensure_ascii=False, indent=2))
            except (OSError, ValueError):
                pass
        # ⚠️⚠️ **把各状态 json 一起收进包**（2026-10-04 用户拍板）。
        #
        # 原来这里只单独塞了 `mod_conflicts.json`，而"注入 / 还原 / 安全模式**现在到底是什么
        # 状态**"全写在这些 json 里：安全模式改了哪些文件、停用了哪些注入、采纳过哪份 ReShade、
        # 全局 Apps 打算怎么还、崩溃记忆与"跑通过"的台账、文件守护计数、上次更新检查结果。
        # 少了它们，用户报"还原没生效 / 游戏起不来"时只能**凭日志反推**，往往要再来一轮
        # —— 与用户定的"日志包一次抓齐所有数据，不要搞好几轮"冲突。
        # 单个上限 256 KB（超了 `_safe_zip_write` 会收尾部并在包内注明被截断）。
        # 2026-10-04 再扩：`.jsonl`（运行时采样曲线）与 `logs\*.json` 也一并收。
        for path in sorted(runtime.glob("*.json")):
            _safe_zip_write(archive, path, f"runtime-state/{path.name}", max_bytes=256 * 1024)
        for folder, arc in ((runtime / "_state", "runtime-state/_state"),
                            (runtime / "_update", "runtime-state/_update"),
                            (runtime / "_net", "runtime-state/_net"),
                            (runtime / "_sample", "runtime-state/_sample")):
            if not folder.is_dir():
                continue
            for pattern in ("*.json", "*.jsonl"):
                for path in sorted(folder.glob(pattern)):
                    _safe_zip_write(archive, path, f"{arc}/{path.name}", max_bytes=256 * 1024)
        if config_path.is_file():
            _safe_zip_write(archive, config_path, "config.json")
        archive.writestr("runtime-inventory.txt", inventory + "\n")
        archive.writestr("game-inventory.txt", inventory_text)
        archive.writestr("environment.txt",
                         env_text + (f"\n[采集提示] {env_error}\n" if env_error else ""))
        _manifest_add(manifest, arcname="environment.txt", source="(事件日志/服务/转储/版本/进程)",
                      status="error" if env_error else "ok", note=env_error)
        manifest_text = capture_manifest_text(manifest)
        archive.writestr("capture-manifest.txt", manifest_text)
        overview = manifest_text.splitlines()[2] if len(manifest_text.splitlines()) > 2 else ""
        summary[1:1] = ["-- 采集清单（完整清单见 capture-manifest.txt）--",
                        overview,
                        "missing/error 表示**没抓到**（不是没有内容）；带「⚠ 上次运行留下的旧文件」的日志不能当本次现场用。"]
        archive.writestr("summary.txt", "\n".join(summary) + "\n")

    log_event(config, "诊断包已创建", category="diag", path=out, note=note,
              items=len(manifest),
              missing=sum(1 for item in manifest if item.get("status") == "missing"))
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
    """把"游戏之外"的现场落一份到 `logs\\windows-events-<stamp>.log`。

    ⚠️ **2026-10-04 改**：原实现是"抓到内容才写文件、抓不到就静默 return" ——
    于是包里既没有事件文件、也没有任何说明，看包的人分不清"这台机器没有崩溃事件"
    和"我们没抓成功"。这两者在归因上完全相反（没有 WER/Application Error 事件
    恰恰能说明**进程不是自己崩的，而是被外部结束的**）。
    现在**永远写文件**：抓到就写事件，抓不到就写明原因或"近 60 分钟内没有相关事件"。
    """
    if os.name != "nt":
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    text, error = collect_environment_report(config, None)
    target = logs_dir(config) / f"windows-events-{stamp}.log"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + (f"\n[采集提示] {error}\n" if error else ""),
                          encoding="utf-8", errors="replace")
        log_event(config, "已捕获 Windows 现场（事件/服务/转储）", category="crash",
                  path=target, error=error or "")
    except OSError:
        return


def log_efmi_state(config: Any, *, user_ini_path: Path | None = None, staging_root: Path | None = None) -> None:
    """记录 EFMI / 3DMigoto 到底有没有把 staged 的 Mods / controller / probe 读进去。

    ⚠️ **2026-10-04 重写**（issue #13 缺陷一 + 二；同一天另一位反馈者的包里原地复现）：
      * **路径以 config 解析结果为准**，`loader` 推导只作兜底；调用方传进来的路径算
        **额外候选**，不再覆盖 config 的结论 —— 原来 `_capture_postmortem` 传的是
        `loader_dir/Mods`，而那位反馈者的 `migoto_loader` 指向的是**另一套 3DMigoto**
        （`D:\\d3dxSkinManage\\…\\work`），于是包里报出一串 `exists=False` 误报，
        真实 staging 在 `…\\XXMI Launcher\\EFMI\\Mods` —— 同一份日志的「应用配置」行里写着。
      * **两侧都探**：EFMI 侧与 loader 侧各报一条（谁在、谁不在，一眼看清）。
      * **三路独立兜底**：user ini / staging / loader 日志互不牵连；任何一路抛异常都不会
        吃掉另外两路（原来整个函数体一个 `try`，一处 `iterdir()` 就把后面的采集全吞了）。
      * **目录不存在不是异常，而是一条结论**（"这条链本来就没部署"）。
    """
    probes = _try_capture(config, "EFMI 路径", efmi_probe_paths, config) or {}

    def _dedupe(items: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
        seen: set[str] = set()
        out: list[tuple[str, Path]] = []
        for label, path in items:
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((label, path))
        return out

    ini_candidates = [("caller", Path(user_ini_path))] if user_ini_path is not None else []
    ini_candidates += list(probes.get("user_ini") or [])
    staging_candidates = [("caller", Path(staging_root))] if staging_root is not None else []
    staging_candidates += list(probes.get("staging") or [])

    def _step(name: str, func: Any) -> None:
        try:
            func()
        except Exception as exc:  # noqa: BLE001
            log_exception(config, f"EFMI 状态采集失败: {name}", exc, category="efmi")

    # ---- ① user ini（谁写进去了什么：面板状态、probe、controller 标记）----
    for label, path in _dedupe(ini_candidates):
        def _read_ini(path: Path = path, label: str = label) -> None:
            if not path.is_file():
                log_event(config, "EFMI user ini missing", category="efmi", source=label, path=path,
                          note="这条路径没有这个文件（见同批其它候选行，不要据此判定 EFMI 没部署）")
                return
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log_event(config, "EFMI user ini 读取失败", level="WARN", category="efmi",
                          source=label, path=path, error=str(exc))
                return
            log_event(config, "EFMI user ini 命中", category="efmi", source=label, path=path,
                      size=path.stat().st_size)
            wanted = ("mc_probe", "mc_controller_loaded", "mc_last_wire", "mc_last_value", "mc_state_")
            hits = 0
            for line in text.splitlines():
                lowered = line.lower()
                if any(token in lowered for token in wanted):
                    log_event(config, "EFMI user ini state", category="efmi", source=label, line=line)
                    hits += 1
                    if hits >= 60:
                        break
            if not hits:
                log_event(config, "EFMI user ini 里没有任何 mc_* 状态",
                          level="WARN", category="efmi", source=label, path=path,
                          note="面板/控制器没往这份 ini 写过东西 —— 要么游戏里没按过面板，"
                               "要么游戏读的是**另一份** ini")

        _step(f"user ini {label}", _read_ini)

    # ---- ② staging（staged 的 Mods / probe / controller 到底在不在）----
    for label, root in _dedupe(staging_candidates):
        def _read_staging(root: Path = root, label: str = label) -> None:
            if not root.is_dir():
                log_event(config, "staged Mods 目录不存在（不是报错，是这条链本来就没部署）",
                          level="WARN", category="efmi", source=label, path=root)
                return
            managed = root / "EndfieldModControllerManaged"
            probe = root / "MC_Probe.ini"
            controller = root / "MC_Controller" / "controller.ini"
            log_event(config, "staged metadata root", category="efmi", source=label, path=managed,
                      exists=managed.is_dir())
            log_event(config, "staged probe", category="efmi", source=label, path=probe,
                      exists=probe.is_file())
            log_event(config, "staged controller", category="efmi", source=label, path=controller,
                      exists=controller.is_file())
            active_dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("MC_")]
            ini_count = sum(1 for _ in root.rglob("*.ini"))
            log_event(config, "staged inventory", category="efmi", source=label,
                      mod_dirs=len(active_dirs), ini_files=ini_count,
                      sample=", ".join(sorted(p.name for p in active_dirs)[:12]))

        _step(f"staging {label}", _read_staging)

    # ---- ③ loader 侧日志（含"这份日志是不是本次运行写的"）----
    loader_dir = probes.get("loader_dir")
    if loader_dir is not None:
        def _read_loader_debug() -> None:
            debug = Path(loader_dir) / "loader_debug.log"
            if not debug.is_file():
                return
            lines = debug.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-120:]:
                log_event(config, "loader debug", category="efmi", line=line)

        def _read_loader_d3d11() -> None:
            log = Path(loader_dir) / "d3d11_log.txt"
            if not log.is_file():
                return
            stat = log.stat()
            log_event(config, "loader d3d11_log", category="efmi", path=log, size=stat.st_size,
                      mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                      fresh=_is_fresh(stat.st_mtime))
            # 只读尾部 2 MB：这份日志常有十几 MB，而"我们关心的 Mod 有没有被加载"
            # 在最近的记录里就能看出来（顺带避免崩溃时卡在这一步）。
            try:
                with open(log, "rb") as handle:
                    handle.seek(max(0, stat.st_size - 2 * 1024 * 1024))
                    text = handle.read().decode("utf-8", errors="replace")
            except OSError:
                return
            for token in ("MC_Probe", "mc_probe", "mc_controller", "EndfieldModControllerManaged", "MC_Controller"):
                count = text.count(token)
                if count:
                    log_event(config, "loader d3d11_log token", category="efmi", token=token, count=count)
            shown = 0
            for line in text.splitlines():
                if any(token in line for token in ("mc_probe", "mc_controller", "MC_Probe", "MC_Controller",
                                                   "EndfieldModControllerManaged")):
                    log_event(config, "loader d3d11_log line", category="efmi", line=line[:500])
                    shown += 1
                    if shown >= 40:
                        break
            if not shown:
                log_event(config, "loader d3d11_log 里没有控制器铺的 Mod 的任何痕迹",
                          level="WARN", category="efmi", path=log,
                          note="要么游戏读的不是这个 loader 的 Mods，要么控制器铺的 Mod 没进游戏")

        _step("loader_debug", _read_loader_debug)
        _step("loader d3d11_log", _read_loader_d3d11)
