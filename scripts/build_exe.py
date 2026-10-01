"""把 EndfieldModController 打包成单个 exe（PyInstaller）。

    python scripts/build_exe.py             # 单文件 exe（默认）
    python scripts/build_exe.py --onedir    # 目录模式：启动更快，但不是单个文件
    python scripts/build_exe.py --console   # 保留控制台（调试 --cli 用）

产出：``dist/EndfieldModController.exe``

⚠ 两个「根目录」必须分清，改代码时别搞混（细节见 config._detect_project_root
与 app._resource_root）：

* **用户数据根 = exe 所在目录** —— ``config.json`` / ``runtime/`` / ``library/``
  都落在这里，用户看得到、能备份，不会随进程消失；
* **只读资源根 = PyInstaller 解压目录**（``sys._MEIPASS``）—— ``web/`` 等被打进
  exe 的资源在这里。

之前 `PROJECT_ROOT` 只写了 ``Path(__file__).resolve().parents[1]``，打包后
``__file__`` 指向临时解压目录，用户的配置和 Mod 库会被写进临时目录、一退出就没了。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "exe_entry.py"
APP_NAME = "EndfieldModController"

# 只读资源：web 前端整目录 + 角色名表（含拼音别名）+ 面板词表 + 自研 ReShade 面板。
# ⚠ 这些 .json / .addon64 都是数据文件，PyInstaller 只自动收 .py —— 少一个，发布版就会
# 悄悄退化成"内置兜底数据"（角色表踩过一次：exe 里没有 characters.json，33 位角色全没了）。
# 面板也一样：没有它，「整合 Mod 快捷键」会因为"面板不存在"而拒绝锁键（这是对的，
# 但用户会以为是开关坏了），所以它必须进包。
ADD_DATA = [
    ("web", "web"),
    ("endfieldmodcontroller/characters.json", "endfieldmodcontroller"),
    ("endfieldmodcontroller/hotkey_hints.json", "endfieldmodcontroller"),
    ("assets/addon/endfieldmodcontroller.addon64", "assets/addon"),
]

# 应用图标（多尺寸 ico，含 16/24/32/48/64/128/256）。放进 exe 后，
# 资源管理器、任务栏、窗口标题栏都会用它。
ICON = ROOT / "assets" / "app.ico"


def main() -> int:
    args = list(sys.argv[1:])
    onefile = "--onedir" not in args
    keep_console = "--console" in args

    # 面板必须在打之前就编好 —— 缺了它 exe 里就没有统一面板。
    # （默认自动编；`--skip-addon` 只给"刚编过、确认没改源码"的场合用。）
    if "--skip-addon" not in args:
        addon_script = ROOT / "scripts" / "build_addon.py"
        result = subprocess.run([sys.executable, str(addon_script)], cwd=str(ROOT))
        if result.returncode != 0:
            print("\n!! ReShade 面板编译失败（可加 --skip-addon 沿用上次产物）")
            return result.returncode
    for src, _dest in ADD_DATA:
        if not (ROOT / src).exists():
            print(f"!! 缺少随包资源：{src}")
            return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--onefile" if onefile else "--onedir",
        "--console" if keep_console else "--noconsole",
    ]
    for src, dest in ADD_DATA:
        cmd += ["--add-data", f"{src}{';' if sys.platform == 'win32' else ':'}{dest}"]
    if ICON.is_file():
        cmd += ["--icon", str(ICON)]
    else:
        print(f"!! 没找到图标 {ICON}，将使用 PyInstaller 默认图标")
    if os.name == "nt":
        # 让 exe 的 manifest 自己要求管理员：**双击即弹 UAC 提权，用户零配置**。
        # 需要它的原因：XXMI Launcher 的 exe 要求管理员权限，非管理员启动会直接报
        # WinError 740（2026-09-29 实测）。
        cmd += ["--uac-admin"]
    # pywebview 在 Windows 上走 WebView2，经 pythonnet/clr 调用，必须显式带上
    cmd += ["--collect-all", "webview"]
    for hidden in ("clr", "pythonnet", "PIL", "cryptography", "webview.platforms.edgechromium"):
        cmd += ["--hidden-import", hidden]
    for skip in ("tkinter", "matplotlib", "numpy", "pandas", "scipy"):
        cmd += ["--exclude-module", skip]
    cmd.append(str(ENTRY))

    print("打包命令：\n  " + " ".join(cmd) + "\n")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("\n!! 打包失败")
        return result.returncode

    target = ROOT / "dist" / (f"{APP_NAME}.exe" if onefile else APP_NAME)
    if target.exists():
        if target.is_file():
            size = target.stat().st_size / 1024 / 1024
            print(f"\n[OK] 产出 {target}  ({size:.1f} MB)")
        else:
            print(f"\n[OK] 产出目录 {target}")
        print("提示：exe 旁边的目录就是「用户数据根」—— config.json / runtime / library 都会生在那里。")
    else:
        print(f"\n!! 没找到产出：{target}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
