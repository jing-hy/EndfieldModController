"""Minimal Windows DLL injector used as a ReShade fallback.

This is intentionally small and only used when the user selects external
injection.  It does not modify the game directory; it loads ReShade into the
already-running game process.

2026-10-01 修：所有 Win32 调用改为显式声明 argtypes/restype。此前一律用
`ctypes.windll.kernel32` 且不声明签名，ctypes 会按 `c_int` 解释返回值 —— 64 位下
`VirtualAllocEx` 的远程地址与 `GetProcAddress` 的模块地址通常远大于 2³¹，会被
截断成负数/0，随后 WriteProcessMemory / CreateRemoteThread 用错地址，
注入必然失败，而报错还会误导成 "timed out waiting for …"。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path


PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF
TH32CS_SNAPPROCESS = 0x00000002
MEM_RELEASE = 0x8000


class InjectorError(RuntimeError):
    pass


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


_KERNEL32 = None


def _kernel32():
    """带正确签名的 kernel32（不声明就会截断 64 位句柄与地址）。"""
    global _KERNEL32
    if _KERNEL32 is not None:
        return _KERNEL32
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    lib.CreateToolhelp32Snapshot.restype = wt.HANDLE
    lib.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    lib.Process32FirstW.restype = wt.BOOL
    lib.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    lib.Process32NextW.restype = wt.BOOL
    lib.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    lib.OpenProcess.restype = wt.HANDLE
    lib.CloseHandle.argtypes = [wt.HANDLE]
    lib.CloseHandle.restype = wt.BOOL
    lib.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
    lib.VirtualAllocEx.restype = ctypes.c_void_p
    lib.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
    lib.VirtualFreeEx.restype = wt.BOOL
    lib.WriteProcessMemory.argtypes = [
        wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.WriteProcessMemory.restype = wt.BOOL
    lib.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    lib.GetModuleHandleW.restype = wt.HMODULE
    lib.GetProcAddress.argtypes = [wt.HMODULE, wt.LPCSTR]
    lib.GetProcAddress.restype = ctypes.c_void_p
    lib.CreateRemoteThread.argtypes = [
        wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
    ]
    lib.CreateRemoteThread.restype = wt.HANDLE
    lib.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    lib.WaitForSingleObject.restype = wt.DWORD
    lib.GetExitCodeThread.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    lib.GetExitCodeThread.restype = wt.BOOL
    _KERNEL32 = lib
    return lib


def is_windows() -> bool:
    return hasattr(ctypes, "windll")


def find_process_id(process_name: str) -> int:
    if not is_windows():
        raise InjectorError("DLL injection is only supported on Windows")
    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or int(snapshot) == -1:
        raise InjectorError("CreateToolhelp32Snapshot failed")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return 0
        target = process_name.lower()
        while True:
            if entry.szExeFile.lower() == target:
                return int(entry.th32ProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return 0
    finally:
        kernel32.CloseHandle(snapshot)


def inject_dll(pid: int, dll_path: Path) -> None:
    if not is_windows():
        raise InjectorError("DLL injection is only supported on Windows")
    dll_path = dll_path.resolve()
    if not dll_path.is_file():
        raise InjectorError(f"ReShade DLL not found: {dll_path}")

    kernel32 = _kernel32()
    process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not process:
        raise InjectorError(f"OpenProcess failed for pid {pid} (try running as administrator)")

    try:
        path_bytes = (str(dll_path) + "\0").encode("utf-16-le")
        size = len(path_bytes)
        remote = kernel32.VirtualAllocEx(process, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote:
            raise InjectorError("VirtualAllocEx failed")
        try:
            written = ctypes.c_size_t(0)
            buffer = ctypes.create_string_buffer(path_bytes, size)
            if not kernel32.WriteProcessMemory(process, remote, buffer, size, ctypes.byref(written)):
                raise InjectorError("WriteProcessMemory failed")
            load_library = kernel32.GetProcAddress(
                kernel32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
            if not load_library:
                raise InjectorError("GetProcAddress(LoadLibraryW) failed")
            thread = kernel32.CreateRemoteThread(process, None, 0, load_library, remote, 0, None)
            if not thread:
                raise InjectorError("CreateRemoteThread failed")
            try:
                kernel32.WaitForSingleObject(thread, INFINITE)
                # LoadLibraryW 的返回值就是线程退出码：0 = 加载失败（位数不匹配 /
                # 依赖缺失 / 路径不可达）。原先从不检查，失败也报成功（2026-10-01 修）。
                exit_code = wt.DWORD(0)
                if kernel32.GetExitCodeThread(thread, ctypes.byref(exit_code)) and exit_code.value == 0:
                    raise InjectorError(
                        f"LoadLibraryW 在目标进程里返回 0（{dll_path.name} 加载失败："
                        "位数不匹配、依赖缺失或路径不可达）")
            finally:
                kernel32.CloseHandle(thread)
        finally:
            kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
    finally:
        kernel32.CloseHandle(process)


def wait_and_inject(process_name: str, dll_path: Path, timeout: float = 60.0, interval: float = 0.5) -> int:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            pid = find_process_id(process_name)
            if pid:
                inject_dll(pid, dll_path)
                return pid
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(interval)
    raise InjectorError(f"timed out waiting for {process_name}: {last_error}")
