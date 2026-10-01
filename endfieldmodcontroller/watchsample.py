"""游戏进程的**运行时定期采样** —— 给"跑了几十秒就闪退"这类问题留下时间线。

**为什么要它**（2026-10-01 用户要求「**你最好能让日志包一次抓全所有数据，不要搞好几轮**」）：
用户反馈的形态是「**游戏跑四十多秒就闪退**」，而他补充「**四十多秒闪退是开发初期我也经常遇到的问题**」
—— 说明这是个**有历史的老问题**。但此前的诊断包只收"崩溃那一刻的静态快照"，
**看不到这 40 秒里发生了什么**：

* 是**某个 DLL 在某一秒才被加载**然后立刻出事？（典型：`nvgpucomp64.dll` 在着色器编译时才加载）
* 还是**内存/句柄一路涨到某个点**？
* 还是**某个 addon 在某一秒开始报错**？

所以这里在游戏运行期间**每 5 秒**采一次样，**增量落盘**（`runtime/_state/watch-samples.jsonl`），
崩溃时随包带走。采的内容刻意保持"轻、稳、不干扰游戏"：

* `modules` —— 进程里已加载的**非系统目录**模块（去重排序）；
* `new_modules` —— **相对上一次采样新出现的模块**（这一项最能定位"崩前那一刻发生了什么"）；
* `working_set` / `handles` / `threads` —— 资源曲线；
* `feed_lines` / `reshade_lines` —— 两个关键日志的行数（能看出它们是否还在推进）。

实现用 `psapi` + `kernel32` 的 ctypes 调用（纯读取，不注入、不改动游戏进程）。
"""
from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

_SAMPLES_NAME = "watch-samples.jsonl"

# 视为"系统自带、与 mod 生态无关"的目录 —— 采样时跳过，避免噪音
_SYSTEM_HINTS = (
    "\\windows\\system32", "\\windows\\syswow64", "\\windows\\winsxs",
    "\\windows\\assembly", "\\windows\\microsoft.net", "\\program files\\windowsapps",
    "\\windows\\systemapps",
)

_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010
_LIST_MODULES_ALL = 0x08
_TH32CS_SNAPMODULE = 0x00000008
_TH32CS_SNAPMODULE32 = 0x00000010
_MAX_PATH = 32768

# ⚠️ **必须显式声明 argtypes/restype**（2026-10-01 实测踩坑）：ctypes 默认把返回值当 `c_int`，
# 64 位下**句柄会被截断**，`OpenProcess`/`CreateToolhelp32Snapshot` 拿回来的句柄不可用，
# 表现就是"模块枚举永远返回 0"。这条在本项目已犯过一次（见 diagnostics/injector 的同类修复）。
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

_psapi.EnumProcessModulesEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD)
_psapi.EnumProcessModulesEx.restype = wintypes.BOOL
_psapi.GetModuleFileNameExW.argtypes = (wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
_psapi.GetModuleFileNameExW.restype = wintypes.DWORD


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE,
                                        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS),
                                        wintypes.DWORD)
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
_kernel32.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
_kernel32.GetProcessHandleCount.restype = wintypes.BOOL

_TH32CS_SNAPTHREAD = 0x00000004


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD),
    ]


def samples_path(config: Any) -> Path:
    """采样文件落点（放在 `_state` 下，与其它运行时状态一起）。"""
    return Path(config.runtime_path) / "_state" / _SAMPLES_NAME


def _open_process(pid: int) -> int | None:
    """先要"能枚举模块"的权限，拿不到再退回最小权限（那样模块为空，但内存/句柄/线程照采）。

    ⚠️ 实测（2026-10-01）：只用 `PROCESS_QUERY_LIMITED_INFORMATION` 时 `EnumProcessModulesEx`
    返回空 —— 那正是最需要的那一项。所以这里带权限降级。
    """
    for access in (_PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ,
                   _PROCESS_QUERY_LIMITED_INFORMATION):
        handle = _kernel32.OpenProcess(access, False, pid)
        if handle:
            return handle
    return None


class _MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
        # ⚠️ `szExePath` 必须是 **MAX_PATH(260)**：写成 32768 会让 `dwSize` 远超真实结构体，
        # `Module32FirstW` 直接返回 `ERROR_BAD_LENGTH(24)`（2026-10-01 实测踩到）。
        ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260),
    ]


_kernel32.Module32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MODULEENTRY32W))
_kernel32.Module32FirstW.restype = wintypes.BOOL
_kernel32.Module32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MODULEENTRY32W))
_kernel32.Module32NextW.restype = wintypes.BOOL
_kernel32.Thread32First.argtypes = (wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32))
_kernel32.Thread32First.restype = wintypes.BOOL
_kernel32.Thread32Next.argtypes = (wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32))
_kernel32.Thread32Next.restype = wintypes.BOOL


def _module_paths_toolhelp(pid: int) -> list[str]:
    """备选路线：Toolhelp32 快照枚举模块（权限要求比 psapi 宽松，实测更稳）。"""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPMODULE | _TH32CS_SNAPMODULE32, pid)
    if snapshot in (0, -1):
        return []
    try:
        entry = _MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(_MODULEENTRY32W)
        ok = _kernel32.Module32FirstW(snapshot, ctypes.byref(entry))
        out: list[str] = []
        while ok:
            if entry.szExePath:
                out.append(entry.szExePath)
            ok = _kernel32.Module32NextW(snapshot, ctypes.byref(entry))
        return out
    finally:
        _kernel32.CloseHandle(snapshot)


def _is_system_module(path_lower: str) -> bool:
    lowered = path_lower.replace("/", "\\")
    return any(hint in lowered for hint in _SYSTEM_HINTS)


def _module_paths(handle: int) -> list[str]:
    needed = wintypes.DWORD()
    # 先问需要多大缓冲（⚠️ 传一个真实的小数组，而不是 None —— 有些实现不接受空指针）
    probe = (wintypes.HMODULE * 1)()
    _psapi.EnumProcessModulesEx(handle, probe, ctypes.sizeof(probe), ctypes.byref(needed),
                                _LIST_MODULES_ALL)
    count = max(1, needed.value // ctypes.sizeof(wintypes.HMODULE))
    buf = (wintypes.HMODULE * (count + 64))()
    if not _psapi.EnumProcessModulesEx(handle, buf, ctypes.sizeof(buf),
                                       ctypes.byref(needed), _LIST_MODULES_ALL):
        return []
    real = needed.value // ctypes.sizeof(wintypes.HMODULE)
    name_buf = ctypes.create_unicode_buffer(_MAX_PATH)
    out: list[str] = []
    for i in range(real):
        if _psapi.GetModuleFileNameExW(handle, buf[i], name_buf, _MAX_PATH):
            out.append(name_buf.value)
    return out


def _thread_count(pid: int) -> int:
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot in (0, -1):
        return 0
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        ok = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        total = 0
        while ok:
            if entry.th32OwnerProcessID == pid:
                total += 1
            ok = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        return total
    finally:
        _kernel32.CloseHandle(snapshot)


def sample(pid: int, *, known_modules: set[str] | None = None,
           feed_log: Path | None = None, reshade_log: Path | None = None) -> dict[str, Any] | None:
    """采一次样。进程已退出/打不开时返回 None。"""
    handle = _open_process(pid)
    if not handle:
        return None
    try:
        # Toolhelp32 优先（实测在这台机器上比 psapi 稳），psapi 兜底
        all_paths = _module_paths_toolhelp(pid) or _module_paths(handle)
        third_party = sorted(p for p in all_paths if not _is_system_module(p.lower()))
        known = known_modules if known_modules is not None else set()
        new = [p for p in third_party if os.path.basename(p).lower() not in known]

        mem = _PROCESS_MEMORY_COUNTERS()
        mem.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        working_set = 0
        if _psapi.GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb):
            working_set = int(mem.WorkingSetSize)

        handles = wintypes.DWORD()
        handle_count = int(handles.value) if _kernel32.GetProcessHandleCount(handle, ctypes.byref(handles)) else 0

        def _lines(path: Path | None) -> int:
            if not path or not path.is_file():
                return 0
            try:
                with path.open("rb") as fh:
                    return sum(1 for _ in fh)
            except OSError:
                return 0

        return {
            "t": round(time.time(), 1),
            "at": time.strftime("%H:%M:%S"),
            "module_count": len(all_paths),
            "modules_ok": bool(all_paths),
            "third_party_count": len(third_party),
            "modules": third_party,
            "new_modules": new,
            "working_set_mb": round(working_set / 1048576, 1),
            "handles": handle_count,
            "threads": _thread_count(pid),
            "feed_lines": _lines(feed_log),
            "reshade_lines": _lines(reshade_log),
        }
    finally:
        _kernel32.CloseHandle(handle)


def append(config: Any, entry: dict[str, Any]) -> None:
    """把一次采样**增量**写盘（追加一行 JSON）—— 崩了也不丢已经采到的数据。"""
    path = samples_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def reset(config: Any) -> None:
    """开一次新的跟踪前清掉旧采样。"""
    try:
        samples_path(config).unlink()
    except OSError:
        pass


def read_all(config: Any) -> list[dict[str, Any]]:
    path = samples_path(config)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def summarise(entries: list[dict[str, Any]]) -> str:
    """把采样渲染成一段人能读的表格（进崩溃报告正文）。"""
    if not entries:
        return "（没有采到样本 —— 游戏可能没起来，或跟踪启动得太晚）\n"
    lines = [
        "  时间      模块数  第三方  工作集MB  句柄  线程  feed行  ReShade行  新加载的模块",
        "  " + "-" * 100,
    ]
    for e in entries:
        new = ", ".join(os.path.basename(p) for p in (e.get("new_modules") or [])) or "-"
        lines.append(
            f"  {e.get('at','?'):>8}  {e.get('module_count',0):>6}  {e.get('third_party_count',0):>6}  "
            f"{e.get('working_set_mb',0):>8}  {e.get('handles',0):>4}  {e.get('threads',0):>4}  "
            f"{e.get('feed_lines',0):>6}  {e.get('reshade_lines',0):>9}  {new[:70]}"
        )
    return "\n".join(lines) + "\n"
