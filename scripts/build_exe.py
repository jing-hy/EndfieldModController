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
# 前端：有 Vite 产物（`web/dist/index.html`）就整目录带上，否则回退原生 `web/`。
# ⚠️ 判据与 `app.py:_index_html()` 必须一致（不要用额外的标记文件 —— `vite build` 的
# emptyOutDir 会把它清掉）。
_WEB_SRC = "web/dist" if (ROOT / "web" / "dist" / "index.html").is_file() else "web"
ADD_DATA = [
    (_WEB_SRC, "web"),
    ("endfieldmodcontroller/characters.json", "endfieldmodcontroller"),
    # 角色头像（34 张 PNG，约 3.8 MB）+ 索引 `index.json`：用户 2026-10-07 要求
    # 「角色表和图直接随包」「**是随 exe**」⇒ 离线也有头像，也不受官网改版（直链带 hash）影响。
    ("endfieldmodcontroller/characters", "endfieldmodcontroller/characters"),
    ("endfieldmodcontroller/hotkey_hints.json", "endfieldmodcontroller"),
    # ⚠️ **随包组件版本表**（2026-10-03 用户要求）：给"一键启动前的更新检查"用，
    # 读它是纯本地操作（微秒级），不像以前那样同步联网查 GitHub（实测 6.1 秒）。
    ("endfieldmodcontroller/component_versions.json", "endfieldmodcontroller"),
    ("assets/addon/endfieldmodcontroller.addon64", "assets/addon"),
    # ★★ **把"必须最新才能工作"的随包资产也打进 exe**（2026-10-06 定案）。
    #    为什么：资产清单是从 `<数据根>\assets\<组>\manifest.json` 读的，而数据根那份
    #    **优先于 exe 内嵌** ⇒ 用户机器上那句旧 `assets\` 会让"换 exe"完全拿不到新资产
    #    （实测：DLSS4 的 addon 条目不在旧清单里 ⇒ 永远展不出来 ⇒ ReShade 里没有
    #     `MFG Unlock` 页签；NR 引擎换代也变成"停用了旧的、又按旧清单装回旧的"）。
    #    这里只挑小的、且**不最新就会坏**的：清单本身 + 四个 addon 压缩包 + ReShade 模板
    #    （合计约 1.9 MB）；`shaders\`(0.85 MB) 与 `textures\`(10.5 MB) 属可选效果资产，
    #    仍走 assets-bundle.zip，不必塞进 exe。
    ("assets/dlss5/manifest.json", "assets/dlss5"),
    ("assets/dlss5/ReShade.ini.dlss5-template", "assets/dlss5"),
    ("assets/dlss5/renodx-dlss5.addon64.xz", "assets/dlss5"),
    ("assets/dlss5/renodx-endfield-enhancer.addon64.xz", "assets/dlss5"),
    ("assets/dlss5/renodx-mfgunlock.addon64.xz", "assets/dlss5"),
    ("assets/dlss5/trans-zh.addon64.xz", "assets/dlss5"),
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
