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
    """已有实例在跑时**静默退出**（用户要求「重复启动不要弹窗，直接不启动就行」）。

    只往日志写一行，方便以后排查"为什么双击了没反应"。
    """
    try:
        from . import launcher
        from .config import AppConfig

        launcher._append_log(AppConfig.load(), "已有实例在运行 → 本次启动静默退出（防多开）")
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

    # 窗口的初始背景色：WebView2 初始化那 1~2 秒里窗口内容是空的，默认白色在深色
    # 主题下很刺眼，看起来也像"卡住了"（2026-10-01 实测：从零启动窗口先白屏，
    # 加载页因此几乎看不到）。按主题给底色，白屏期直接就是主题色。
    theme = str(getattr(api.config, "theme", "light") or "light")
    window_bg = "#eef2f7" if theme == "light" else "#0a0e13"

    webview.create_window(
        WINDOW_TITLE,
        str(WEB_DIR / "index.html"),
        js_api=api,
        width=1180,
        height=800,
        min_size=(980, 680),
        background_color=window_bg,
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
