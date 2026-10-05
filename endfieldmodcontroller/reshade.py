"""Download and extract the official ReShade Add-on build.

ReShade's website distributes a setup executable whose embedded **standard ZIP**
contains `ReShade64.dll`.  We download it to a temp directory, read it with the
standard library `zipfile`, and copy only the runtime files into the caller's
target directory.  Nothing is written into the game directory.

⚠️ 2026-10-05：原来这里写的是"extract with 7z"，而且**第一件事就是找 `7z.exe`** ——
用户机器上没有 7z 时，`_find_7z()` 直接抛 `ReShadeError`，"更新 ReShade 底座"
这个按钮**从来就没成功过**（诊断包原话：`后端异常 @ download_reshade() …
reshade.py line 46 ← line 36, in _find_7z`）。官方安装器是标准 ZIP，7z 不是必需品。
现在：**标准库优先、7z 只作兜底**（旧版本万一是 7z SFX 时才用）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_VERSION = "6.8.0"
USER_AGENT = "EndfieldModController/0.1"
# 安装器里我们真正要的文件（其它是 setup 自身的组件）。
_RUNTIME_MEMBERS = ("ReShade64.dll", "ReShade64.json", "ReShade64_XR.json")


class ReShadeError(RuntimeError):
    pass


def _find_7z() -> str:
    candidates = [
        shutil.which("7z"),
        shutil.which("7za"),
        shutil.which("7zr"),
        Path(__file__).resolve().parents[1] / "tools" / "7zip" / "7z.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ReShadeError("7z.exe was not found. Install 7-Zip or put 7z.exe in tools/7zip.")


def setup_url(version: str = DEFAULT_VERSION) -> str:
    return f"https://reshade.me/downloads/ReShade_Setup_{version}_Addon.exe"


def _download_setup(url: str, dest: Path, *, log=None) -> None:
    """走项目统一的下载通道（超时 / 重试 / 线路切换都在里面）。

    原来这里是裸 `urllib.request.urlopen` —— 慢网或被掐时只甩一个
    `WinError 10060`，既没有重试也没有兜底线路，而其它组件早就统一走 `fastnet` 了。
    """
    from . import dependencies

    dependencies._http_get(url, dest=dest, timeout=600, log=log)


def _read_setup_members(setup: Path) -> dict[str, bytes]:
    """从安装器里读出 `_RUNTIME_MEMBERS` —— **标准库 zipfile 优先，7z 只作兜底**。

    为什么要写死这个顺序：官方安装器就是标准 ZIP（`zipfile` 直接读，`dlss5_fetcher`
    里也是这么干的），而 `7z.exe` 在用户机器上**经常没有** —— 把它当前置条件，
    等于把"更新 ReShade 底座"整个功能押在一个可选工具上。
    """
    wanted: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(setup) as archive:
            lookup = {Path(name).name.lower(): name
                      for name in archive.namelist() if not name.endswith("/")}
            for member in _RUNTIME_MEMBERS:
                found = lookup.get(member.lower())
                if found:
                    wanted[member] = archive.read(found)
        return wanted
    except (zipfile.BadZipFile, OSError):
        pass
    # 兜底：老版本安装器可能是 7z SFX —— **到这里才需要 7z**。
    extract_dir = setup.parent / (setup.stem + ".extract")
    extract_dir.mkdir(parents=True, exist_ok=True)
    seven = _find_7z()
    result = subprocess.run(
        [seven, "x", "-y", f"-o{extract_dir}", str(setup)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise ReShadeError(f"7z extraction failed: {result.stderr or result.stdout}")
    for member in _RUNTIME_MEMBERS:
        candidate = extract_dir / member
        if candidate.is_file():
            wanted[member] = candidate.read_bytes()
    return wanted


def download_reshade(target_dir: Path, version: str = DEFAULT_VERSION, *, log=None) -> dict:
    """下载官方 ReShade Addon 安装器，把 `ReShade64.dll` 等铺到 *target_dir*。

    ⚠️ **2026-10-05 修（用户实测「reshade 下载又挂」）**：原实现**第一件事就是
    `_find_7z()`**，没有 7z 的机器上直接抛
    `ReShadeError: 7z.exe was not found. Install 7-Zip or put 7z.exe in tools/7zip.`
    ⇒ 反馈者那台**这个按钮从来就没成功过**（开发机装了 scoop 的 7z，所以本机复现不出来）。
    现在解包改成"标准库优先、7z 兜底"，下载改走统一通道。
    """
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    url = setup_url(version)

    with tempfile.TemporaryDirectory(prefix="mc-reshade-") as tmp:
        tmp_path = Path(tmp)
        setup = tmp_path / f"ReShade_Setup_{version}_Addon.exe"
        _download_setup(url, setup, log=log)

        wanted = _read_setup_members(setup)
        if "ReShade64.dll" not in wanted:
            raise ReShadeError("ReShade64.dll was not found in the official setup archive")

        copied: list[str] = []
        for member in _RUNTIME_MEMBERS:
            data = wanted.get(member)
            if data is None:
                continue
            target = target_dir / member
            target.write_bytes(data)
            copied.append(str(target))
        dll = target_dir / "ReShade64.dll"
        return {
            "version": version,
            "url": url,
            "dll": str(dll),
            "files": copied,
        }
