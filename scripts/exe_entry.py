"""PyInstaller 打包入口 —— 把桌面 UI 打成单个 exe。

用法（见 scripts\\build_exe.py）：
    python -m PyInstaller ... scripts/exe_entry.py

注意两个根目录的区别（打包后必须分开）：
  * 用户数据根 = **exe 所在目录**（config.json / runtime / library 落在这里）,
    由 `config._detect_project_root()` 处理；
  * 只读资源根 = PyInstaller 的解压目录 `sys._MEIPASS`（web/ 等打进来的资源），
    由 `app._resource_root()` 处理。
"""
from endfieldmodcontroller.app import main

if __name__ == "__main__":
    raise SystemExit(main())
