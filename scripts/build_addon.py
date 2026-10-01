"""编译统一控制面板（ReShade addon）。

    python scripts\\build_addon.py            # 有 MSVC 就用 MSVC，否则 mingw
    python scripts\\build_addon.py --mingw    # 强制 mingw
    python scripts\\build_addon.py --msvc     # 强制 MSVC

产物：
* ``reshade_addon\\build\\endfieldmodcontroller.addon64`` —— 原始产物
* ``assets\\addon\\endfieldmodcontroller.addon64``        —— 打包用的那一份

`assets\\addon\\` 是 `build_exe.py` 的 `--add-data` 来源，也是源码方式运行时
`reshade_integration.built_addon_path()` 的**第一候选**（打包后则从 `_MEIPASS` 里读同名
文件）—— 一处产物、两种运行方式都能找到，避免再出现"发布版里 addon 恒为 None"。

编译失败直接非零退出：宁可不出包，也不要出一个"面板是旧版/缺失"的 exe。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "reshade_addon"
SOURCE = ADDON_DIR / "src" / "endfieldmodcontroller_addon.cpp"
BUILD_DIR = ADDON_DIR / "build"
ARTIFACT_NAME = "endfieldmodcontroller.addon64"
DIST_DIR = ROOT / "assets" / "addon"

VCVARS_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"),
    Path(r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"),
]
VCVARS_GLOBS = [
    r"C:\Program Files (x86)\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvarsall.bat",
    r"C:\Program Files\Microsoft Visual Studio\*\*\VC\Auxiliary\Build\vcvarsall.bat",
]


def _find_vcvars() -> Path | None:
    for candidate in VCVARS_CANDIDATES:
        if candidate.is_file():
            return candidate
    import glob

    for pattern in VCVARS_GLOBS:
        for hit in sorted(glob.glob(pattern)):
            return Path(hit)
    return None


def _run(command: list[str], *, shell_cmd: str | None = None) -> int:
    printable = shell_cmd or " ".join(command)
    print(f"$ {printable}")
    result = subprocess.run(
        command if shell_cmd is None else shell_cmd,
        shell=shell_cmd is not None,
        cwd=str(ADDON_DIR),
    )
    return result.returncode


def build_msvc() -> bool:
    vcvars = _find_vcvars()
    if vcvars is None:
        print("!! 找不到 vcvarsall.bat（没装 VS Build Tools）")
        return False
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    compile_line = (
        # /MT = 静态链接 MSVC 运行时：addon 会加载进游戏进程，不能指望那边已经装好了
        # vcruntime140/msvcp140（原来的 mingw 产物也是 -static 的道理）。
        # /Brepro = 可复现构建（PE 时间戳固定）：同一份源码两次编译出同一个 sha256，
        # 交付时"exe 里的面板"与"磁盘上那份"才能对得上。
        f'cl /nologo /std:c++17 /LD /MT /EHsc /W3 /O2 /utf-8 /Brepro '
        f'/DWIN32_LEAN_AND_MEAN /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS '
        f'/I"vendor\\reshade\\include" /I"vendor\\imgui" '
        f'src\\endfieldmodcontroller_addon.cpp '
        f'/Fe:build\\{ARTIFACT_NAME} /link user32.lib kernel32.lib /NOIMPLIB /Brepro'
    )
    command = f'cmd /c ""{vcvars}" x64 >nul && {compile_line}"'
    return _run([], shell_cmd=command) == 0


def build_mingw() -> bool:
    gxx = shutil.which("g++")
    if gxx is None:
        print("!! PATH 里没有 g++（没装 mingw）")
        return False
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    return _run([
        gxx, "-std=c++17", "-shared", "-O2",
        "-static", "-static-libgcc", "-static-libstdc++",
        "-finput-charset=UTF-8", "-fexec-charset=UTF-8",
        "-DWIN32_LEAN_AND_MEAN", "-DNOMINMAX", "-D_CRT_SECURE_NO_WARNINGS",
        "src/endfieldmodcontroller_addon.cpp",
        "-o", f"build/{ARTIFACT_NAME}",
        "-I", "vendor/reshade/include",
        "-I", "vendor/imgui",
        "-luser32", "-lkernel32",
        # 可复现：不写 PE 时间戳（与 MSVC 的 /Brepro 对应）
        "-Wl,--no-insert-timestamp",
    ]) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msvc", action="store_true", help="强制用 MSVC")
    parser.add_argument("--mingw", action="store_true", help="强制用 mingw")
    args = parser.parse_args()

    if not SOURCE.is_file():
        print(f"!! 源码不存在：{SOURCE}")
        return 1

    ok = False
    if args.msvc:
        ok = build_msvc()
    elif args.mingw:
        ok = build_mingw()
    else:
        ok = build_msvc()
        if not ok:
            print("MSVC 构建失败/不可用 → 回退 mingw")
            ok = build_mingw()
    if not ok:
        print("!! 面板编译失败")
        return 1

    produced = BUILD_DIR / ARTIFACT_NAME
    if not produced.is_file():
        print(f"!! 没找到产物 {produced}")
        return 1
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = DIST_DIR / ARTIFACT_NAME
    shutil.copy2(produced, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"\n[OK] {target}  {target.stat().st_size:,} B  sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
