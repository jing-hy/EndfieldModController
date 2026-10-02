"""面板按键注入（vkey_inject）的离线自测。

    python scripts\\test_addon_hook.py

为什么要有它：面板的按键注入是在**游戏进程里**改 EFMI 的读键路径，
天然只能进游戏才能看到最终效果。但这个机制里**属于我们自己的那部分**
（找模块 → 改导入表 → 伪造按下 → 跨帧保持 → 自动释放 → 不影响别的调用者）
可以完全离线验证：造一个"假 EFMI"（只通过导入表轮询 `GetAsyncKeyState`，
与真 EFMI 的读键方式一致）让宿主加载它，再逐条断言。

被验证的链路一旦坏掉（例如某个 Windows 版本改了导入表形态、或谁把
`press` 的窗口语义改成"每帧都置低位"导致 toggle 连跳），这里会立刻红。

退出码：0 = 全过，1 = 有用例失败，2 = 环境/编译不可用。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "reshade_addon"
TESTS_DIR = ADDON_DIR / "tests"
BUILD_DIR = TESTS_DIR / "build"

sys.path.insert(0, str(ROOT / "scripts"))
from build_addon import _find_vcvars  # noqa: E402  （同一套 MSVC 定位逻辑）


def _run_vcvars(compile_line: str, timeout: int = 300) -> int:
    vcvars = _find_vcvars()
    if vcvars is None:
        print("!! 找不到 vcvarsall.bat（没装 VS Build Tools）")
        return 2
    command = f'cmd /c ""{vcvars}" x64 >nul && {compile_line}"'
    print(f"$ {compile_line}")
    result = subprocess.run(command, shell=True, cwd=str(ADDON_DIR))
    return result.returncode


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    common = "/nologo /std:c++17 /MT /EHsc /W3 /O2 /utf-8 /DWIN32_LEAN_AND_MEAN /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS"

    fake_dll = BUILD_DIR / "fake_efmi_d3d11.dll"
    host_exe = BUILD_DIR / "hook_host.exe"
    # cl 的工作目录是 addon 根，`/Fe:` 要写相对它的路径
    fake_out = f"tests\\build\\{fake_dll.name}"
    host_out = f"tests\\build\\{host_exe.name}"

    code = _run_vcvars(
        f"cl {common} /LD tests\\fake_efmi_d3d11.cpp "
        f"/Fe:{fake_out} /link user32.lib /NOIMPLIB"
    )
    if code != 0:
        print("!! 假 EFMI 编译失败")
        return 2

    code = _run_vcvars(
        f"cl {common} tests\\hook_host.cpp "
        f"/Fe:{host_out} /link user32.lib"
    )
    if code != 0:
        print("!! 测试宿主编译失败")
        return 2

    env = dict(os.environ)
    # vkey::pick_module 的测试通道（正式链路不设它）
    env["MODECONTROLLER_HOOK_MODULE"] = str(fake_dll)

    print(f"\n$ {host_exe} {fake_dll}")
    result = subprocess.run([str(host_exe), str(fake_dll)], env=env, cwd=str(ADDON_DIR))
    if result.returncode == 0:
        print("\n[OK] 面板按键注入链路自测通过")
    else:
        print(f"\n!! 自测失败（退出码 {result.returncode}）")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
