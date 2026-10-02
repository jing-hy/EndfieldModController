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
    实现已收敛到 `config.resource_root()`（ReShade addon 的定位也用它）。
    """
    from .config import resource_root

    return resource_root()


WEB_DIR = _resource_root() / "web"


def _index_html() -> Path:
    """窗口要加载的页面。

    **默认继续用原生页面**；只有 Vite 产物就绪、**并且**放了接管标记（`web/dist/.ready`）时才切过去。
    这样 Phase 1 做到一半也不会让人看到半成品界面，切换与回退都只是删/加一个标记文件的事。
    """
    dist = WEB_DIR / "dist"
    if (dist / ".ready").is_file() and (dist / "index.html").is_file():
        return dist / "index.html"
    return WEB_DIR / "index.html"


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


def _cleanup_stale_mei_dirs(bases: list[str] | None = None) -> list[str]:
    """删掉 `%TEMP%` 下**上次没删掉**的 `_MEI*` 目录，返回被删掉的目录名。

    PyInstaller onefile 退出时会删自己的 `_MEIxxxxxx`；删不掉（子进程继承、杀软扫描等）
    就弹 `Failed to remove temporary directory` 并把目录留在 `%TEMP%` 里越积越多。
    这里在**下次启动时**补删：
    * 只认 `_MEI` 开头的目录（PyInstaller 的命名），别的一律不碰；
    * **跳过当前进程正在用的那个**（`sys._MEIPASS`）；
    * 删不掉（正被别的进程用着）就**静默跳过**，下次启动再试 —— 绝不报错、绝不打扰用户。
    """
    import shutil
    import tempfile

    current = str(getattr(sys, "_MEIPASS", "") or "")
    roots = bases if bases is not None else [
        tempfile.gettempdir(), os.environ.get("TEMP", ""), os.environ.get("TMP", ""),
    ]
    removed: list[str] = []
    for root in {r for r in roots if r}:
        try:
            entries = list(Path(root).glob("_MEI*"))
        except OSError:
            continue
        for item in entries:
            try:
                if not item.is_dir() or str(item) == current:
                    continue
                shutil.rmtree(item)
                removed.append(item.name)
            except OSError:
                continue
    return removed


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

    # **清理 onefile 的环境变量残留**（2026-10-01 用户实测到弹窗
    # `Warning / Failed to remove temporary directory: …\Temp\_MEI0002b002`）：
    # onefile 的启动器会把 `_MEIxxxx` / `_PYI_*` 塞进环境，**我们启动的所有子进程都会继承**；
    # 子进程只要引用过那个临时目录，主进程退出时就删不掉它 —— 于是弹出上面那个 Warning。
    # 两件事一起做：
    # ① **从本进程环境里删掉这些键** → 之后启动的子进程不再继承（**一处修全部**，
    #    25 个 subprocess 调用点不用逐个改；自更新脚本另有一份显式 `env=` 清理做双保险）。
    #    Python 层找资源用的是 `sys._MEIPASS`，不依赖这两个环境变量，删除是安全的。
    # ② **清掉以前没删掉、堆在 %TEMP% 里的 `_MEI*` 目录**（不是当前进程在用的那个；删不掉就跳过）。
    try:
        from . import launcher as _launcher

        leaked = sorted(k for k in os.environ if k.upper().startswith(("_MEI", "_PYI")))
        for key in leaked:
            os.environ.pop(key, None)
        if leaked:
            _launcher._append_log(api.config, f"启动自检: 已清理 onefile 环境变量残留 {leaked}")
        stale = _cleanup_stale_mei_dirs()
        if stale:
            _launcher._append_log(
                api.config,
                f"启动自检: 清理了 {len(stale)} 个上次没删掉的 PyInstaller 临时目录（{', '.join(stale[:4])}…）",
            )
    except Exception:  # noqa: BLE001
        pass

    # 窗口的初始背景色：WebView2 初始化那 1~2 秒里窗口内容是空的，默认白色在深色
    # 主题下很刺眼，看起来也像"卡住了"（2026-10-01 实测：从零启动窗口先白屏，
    # 加载页因此几乎看不到）。按主题给底色，白屏期直接就是主题色。
    theme = str(getattr(api.config, "theme", "light") or "light")
    window_bg = "#eef2f7" if theme == "light" else "#0a0e13"

    window = webview.create_window(
        WINDOW_TITLE,
        str(_index_html()),
        js_api=api,
        width=1180,
        height=800,
        min_size=(980, 680),
        background_color=window_bg,
        # 允许选中/复制文字（用户 2026-10-01 要求「日志框要允许复制」）。
        # pywebview 默认 text_select=False，会在 WebView2 层禁掉选择，CSS 压不住。
        text_select=True,
    )

    # **下载中关窗口要拦一下**（用户 2026-10-02：「如果在下载的时候关闭 mod 管理器，
    # 要弹窗提示」）：`closing` 返回 False 就取消关闭，同时让界面弹一个确认框；
    # 用户在框里选"仍然退出"时前端会调 `api.confirm_exit()`，那时这里就放行。
    def _on_closing():
        try:
            if api.exit_confirmed:
                return True
            if not api.has_active_downloads():
                return True
        except Exception:  # noqa: BLE001 —— 判据出问题不该把程序卡住关不掉
            return True
        try:
            window.evaluate_js("window.mcAskExit && window.mcAskExit()")
        except Exception:  # noqa: BLE001
            pass
        return False

    try:
        events = getattr(window, "events", None)
        if events is not None and hasattr(events, "closing"):
            events.closing += _on_closing
    except Exception:  # noqa: BLE001
        pass
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
