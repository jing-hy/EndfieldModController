"""Minimal Windows DLL injector used as a ReShade fallback.

This is intentionally small and only used when the user selects external
injection.  It does not modify the game directory; it loads ReShade into the
already-running game process.
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


def is_windows() -> bool:
    return hasattr(ctypes, "windll")


def find_process_id(process_name: str) -> int:
    if not is_windows():
        raise InjectorError("DLL injection is only supported on Windows")
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == -1:
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

    kernel32 = ctypes.windll.kernel32
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
            if not kernel32.WriteProcessMemory(process, remote, path_bytes, size, ctypes.byref(written)):
                raise InjectorError("WriteProcessMemory failed")
            load_library = kernel32.GetProcAddress(kernel32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
            if not load_library:
                raise InjectorError("GetProcAddress(LoadLibraryW) failed")
            thread = kernel32.CreateRemoteThread(process, None, 0, load_library, remote, 0, None)
            if not thread:
                raise InjectorError("CreateRemoteThread failed")
            try:
                kernel32.WaitForSingleObject(thread, INFINITE)
            finally:
                kernel32.CloseHandle(thread)
        finally:
            kernel32.VirtualFreeEx(process, remote, 0, 0x8000)
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
