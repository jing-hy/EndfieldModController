"""EndfieldModController desktop entry point."""
from __future__ import annotations

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

try:
    import webview  # type: ignore
except Exception:  # pragma: no cover
    webview = None

from .api import EndfieldModControllerApi
from .version import WINDOW_TITLE

def _resource_root() -> Path:
    """**只读资源**（web/ 等）的根目录。

    与 `config.PROJECT_ROOT`（用户数据根 = exe 所在目录）不同：打包后 `web/` 是被
    `--add-data` 解压到 PyInstaller 临时目录里的，所以这里要看 `sys._MEIPASS`。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    return Path(__file__).resolve().parents[1]


WEB_DIR = _resource_root() / "web"


def _already_running() -> bool:
    """Windows 命名互斥体：判断是否已经有控制器在跑。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, "Global\\EndfieldModController.SingleInstance")
        # ERROR_ALREADY_EXISTS = 183
        return bool(handle) and ctypes.windll.kernel32.GetLastError() == 183
    except Exception:  # noqa: BLE001
        return False


def _warn_already_running() -> None:
    """已有的实例在跑时，用系统对话框提示（不弹命令行黑窗）。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "EndfieldModController 已经在运行了。\n\n"
            "同时开两个控制器会同时改写 XXMI 注入库与 Mods staging，容易互相踩踏、"
            "界面上的 Mod 状态也会对不上。\n\n"
            "请直接用已经打开的那个窗口。\n"
            "（确实需要多开：把 config.json 里的 \"single_instance\" 改成 false）",
            WINDOW_TITLE,
            0x40,  # MB_ICONINFORMATION
        )
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 防多开：工具自身也只允许一个实例（用户要求「防多开」）
    try:
        from .config import AppConfig

        if getattr(AppConfig.load(), "single_instance", True) and _already_running():
            if "--cli" in argv:
                print(json.dumps({"ok": False, "message": "另一个 EndfieldModController 实例正在运行"},
                                 ensure_ascii=False))
            else:
                _warn_already_running()
            return 1
    except Exception:  # noqa: BLE001
        pass

    api = EndfieldModControllerApi()

    if "--cli" in argv:
        print(json.dumps(api.get_state(), ensure_ascii=False, indent=2))
        return 0

    if webview is None:
        print("pywebview is not installed. Run: pip install -r requirements.txt")
        return 1

    webview.create_window(
        WINDOW_TITLE,
        str(WEB_DIR / "index.html"),
        js_api=api,
        width=1180,
        height=800,
        min_size=(980, 680),
    )
    webview.start()
    # 关闭窗口后必须真的退出：后台还可能有下载/监控类工作线程，
    # 用 os._exit 兜底，避免 pythonw 变成关不掉的僵尸进程（占着端口）。
    try:
        api.shutdown()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
