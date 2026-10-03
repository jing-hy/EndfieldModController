"""EndfieldModController desktop entry point."""
from __future__ import annotations

import atexit
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
    """窗口要加载的页面：有 Vite 产物就用它，否则回退原生页面。

    ⚠️ 判据**不能**用额外的"接管标记"文件：`vite build` 的 `emptyOutDir` 会把 `web/dist/`
    整个清掉重建，标记文件每次构建都会消失（2026-10-02 踩到：程序静默退回旧界面，
    而旧前端里恰好有个我漏声明的变量，于是日志里报 `modDownloadFinished is not defined`）。
    现在只看产物在不在：构建失败 → dist 不存在 → 自动回退旧页面，依然是安全的。
    """
    dist = WEB_DIR / "dist" / "index.html"
    return dist if dist.is_file() else WEB_DIR / "index.html"


def _instance_root() -> Path:
    """本进程该用的**数据根**（防多开的锁就放它下面）。

    打包后 = `sys.executable` 所在目录（与全局口径一致：**数据根 = exe 旁边**）；
    源码运行时退回模块所在目录（保持开发/测试时的原行为）。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# ⚠️ PID 存活检查本身**不足以**判断"是不是我们的实例" —— Windows 会很快复用 PID，
# 而 PyInstaller onefile 每次启动都会创建**父子两个同名的** `EndfieldModController.exe`
# 进程，于是"锁里那个早就退出的 PID"极容易被本次启动的父/子进程复用 ⇒ 误判成
# 「已有实例在运行」⇒ 静默退出 ⇒ 用户看到的就是**双击、弹完 UAC、什么都没发生**。
# 2026-10-03 反馈者诊断包实证：`runtime\logs` 里连续四条
# 「已有实例在运行 → 本次启动静默退出（防多开）」，而他那个窗口其实早关了。
# 现在的判据是**三件套**：PID 活着 + 进程指纹（exe 路径 + 创建时间）对得上 +（或）屏幕上
# 真的有一个我们的窗口；三者都不成立才算陈旧锁，**直接接管**。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_LOCK_NAME = ".mc.lock"
_TITLE_PREFIX = "EndfieldModController"


def _lock_path() -> Path:
    """防多开的锁文件：`<数据根>/runtime/.mc.lock`。

    ⚠️ **数据根不能用无参 `AppConfig.load()`**（2026-10-03 踩到）：
    它读的是 `DEFAULT_CONFIG_PATH`（源码/插件所在位置），而用户实际运行的是**别处的 exe**
    （例如 modtest 下的那份 exe）。于是两个实例算出的锁位置不一致
    （一个写 modtest、一个写工作区），**互相看不见、谁都拦不住谁**，用户照样能开出两个、
    然后撞上 `WinError 5 拒绝访问 ... config.json.tmp-8668-4`。
    统一口径：**数据根 = exe 所在目录**（打包后取 `sys.executable`）。
    """
    lock_dir = _instance_root() / "runtime"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / _LOCK_NAME


def _process_fingerprint(pid: int) -> str:
    """进程指纹 = `<exe 全路径小写>|<创建时间>`；取不到返回空串。

    **创建时间那一半是必须的**：光比 exe 路径挡不住"旧锁里的 PID 被复用给同一个 exe 的
    新进程"（onefile 的父/子进程都叫这个名字），一比创建时间就露馅了。
    """
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        try:
            size = ctypes.c_uint32(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
            kernel32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32),
            ]
            ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            path = buf.value.lower() if ok else ""

            creation = wintypes.FILETIME()
            exit_t = wintypes.FILETIME()
            kernel_t = wintypes.FILETIME()
            user_t = wintypes.FILETIME()
            kernel32.GetProcessTimes.restype = ctypes.c_bool
            kernel32.GetProcessTimes.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ]
            has_time = bool(kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_t),
                ctypes.byref(kernel_t), ctypes.byref(user_t),
            ))
            started = ((creation.dwHighDateTime << 32) | creation.dwLowDateTime) if has_time else 0
            if not path and not started:
                return ""
            return f"{path}|{started}"
        finally:
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001
        return ""


def _pid_alive(pid: int) -> bool:
    """这个 PID 是不是还活着。"""
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # 声明类型：不声明的话 64 位下句柄会被截断（这个坑刚踩过）
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
            handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(handle)
            return True
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _our_windows() -> list[int]:
    """屏幕上属于本程序的**可见窗口**（标题以 `EndfieldModController` 开头）。

    按标题前缀找而不是精确标题：标题里带版本号（`EndfieldModController v1.0.4`），
    前缀匹配连"旧版本实例"也能认出来 —— 这正是双击图标时该被拉到前面的那个窗口。
    """
    if os.name != "nt":
        return []
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        found: list[int] = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _visit(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = int(user32.GetWindowTextLengthW(hwnd) or 0)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value.startswith(_TITLE_PREFIX):
                    found.append(int(hwnd or 0))
            except Exception:  # noqa: BLE001
                pass
            return True

        callback = proto(_visit)
        user32.EnumWindows.argtypes = [proto, ctypes.c_void_p]
        user32.EnumWindows(callback, None)
        return found
    except Exception:  # noqa: BLE001
        return []


def _focus_our_window() -> bool:
    """把已经开着的那个窗口拉到最前面（双击图标 = 想看到它，而不是"没反应"）。"""
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        for hwnd in _our_windows():
            try:
                user32.ShowWindow(ctypes.c_void_p(hwnd), 9)          # SW_RESTORE
                user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
                return True
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return False


def _read_lock(lock: Path) -> dict:
    """读锁内容。兼容老格式（纯 PID 文本）—— 那种锁没有指纹，只能靠窗口兜底。"""
    try:
        raw = lock.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    try:
        return {"pid": int(raw), "legacy": True}
    except ValueError:
        return {}


def _release_lock() -> None:
    """退出前把锁还回去（**内容还是自己的 PID 才删**，别误删别人接管后的锁）。"""
    try:
        lock = _lock_path()
        if int(_read_lock(lock).get("pid") or 0) == os.getpid():
            lock.unlink()
    except Exception:  # noqa: BLE001
        pass


def _already_running() -> bool:
    """判断是否已经有控制器在跑（真的在跑：进程还是那个进程，或窗口还在）。

    ⚠️ 历史：2026-10-03 之前用命名互斥体（`CreateMutexW`），实测怎么都判不出来
    （ctypes 的 `get_last_error()` 在这条调用链上取不到可靠值），于是换成锁文件 + PID。
    现在在 PID 之上再补两道：**进程指纹**（exe 路径 + 创建时间，挡 PID 复用）与
    **窗口存在性**（挡"锁残留但进程早没了"），见文件上方那段注释。
    """
    try:
        lock = _lock_path()
        if lock.is_file():
            info = _read_lock(lock)
            pid = int(info.get("pid") or 0)
            if pid and pid == os.getpid():
                return False                  # 锁就是本进程写的 ⇒ 本进程是持有者
            if pid and _pid_alive(pid):
                recorded = str(info.get("fp") or "")
                current = _process_fingerprint(pid)
                same_process = bool(recorded and current and recorded == current)
                if same_process or _our_windows():
                    return True               # 真的还有一个实例（进程对得上，或窗口就在屏幕上）
                # 落到这里 = PID 活着，但**不是写这把锁的那个进程**（PID 被系统复用了），
                # 而且屏幕上也没有我们的窗口 ⇒ 陈旧锁，接管（"关掉再打开没反应"的根因）
            # 陈旧锁（进程早没了 / 内容坏了 / PID 被复用）⇒ 删掉后重新抢
            try:
                lock.unlink()
            except OSError:
                pass
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return True                       # 竞态：刚好被别人抢到了
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "pid": os.getpid(),
                "fp": _process_fingerprint(os.getpid()),
            }, ensure_ascii=False))
        return False
    except Exception:  # noqa: BLE001 - 判断失败一律当作"没有别的实例"，绝不因此起不来
        return False


def _warn_already_running() -> None:
    """已有实例在跑：**先把那个窗口拉到前台**，再写一行日志，然后安静退出。

    用户 2026-09-29 要求「重复启动不要弹窗，直接不启动就行」——这条不变；
    但**完全没有反馈**会让人以为程序坏了（2026-10-03 反馈：「关掉管理器，显示要管理员
    权限，然后就没反应了」）。现在能叫醒就叫醒（窗口跳到最前面），叫不醒才安静退出。
    """
    try:
        from . import launcher
        from .config import AppConfig

        focused = _focus_our_window()
        launcher._append_log(
            AppConfig.load(),
            "已有实例在运行 → 本次启动退出（防多开）"
            + ("，已把那个窗口调到最前面" if focused else "") ,
        )
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

    # 抢到锁之后的任何正常退出都要还锁（`os._exit` 那条路已在下面显式调用）
    atexit.register(_release_lock)

    api = EndfieldModControllerApi()

    if "--cli" in argv:
        print(json.dumps(api.get_state(), ensure_ascii=False, indent=2))
        _release_lock()
        return 0

    if webview is None:
        print("pywebview is not installed. Run: pip install -r requirements.txt")
        _release_lock()
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

    # ⚠️⚠️ **关窗口不再做任何拦截**（2026-10-03 用户拍板：「**如果难搞就直接不要那个弹窗了**」）。
    #
    # 这个功能前后试了两版，**两版都会卡死**，所以按用户的话直接砍掉：
    #   ① 第一版：`closing` 返回 False 取消关闭 + `evaluate_js("window.mcAskExit()")`
    #      让前端弹确认框。实测「点了关闭没反应、也没弹窗」——因为前端当时**根本没定义**
    #      `window.mcAskExit`（后端一直在等一个不存在的回调）。
    #   ② 第二版：补上前端弹窗 + 后端超时放行。实测**仍然卡死** ——
    #      `closing` 一旦返回 False，pywebview 就进入收尾流程，此刻前端再
    #      `await call("confirm_exit")`，桥可能已经断了、永远等不到返回，
    #      而窗口又处在"被拒绝关闭"的状态。
    # 结论：**在 pywebview 的 `closing` 里做异步交互本身就不稳**。
    # 代价说明：下载中关窗口**不再提示**（已下载的部分会保留，下次从断点继续），
    # 换来的是**任何时候都关得掉**——这个取舍是用户定的。
    #
    # （保留 `active_download_count` / `confirm_exit` 等能力，将来若要用原生
    #  `MessageBoxW` 同步弹框可以接上；本次不接，见 app.py 里的 `_ask_native` 注释。）
    def _on_closing():
        return True

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
    # **先把防多开的锁还回去**：`os._exit` 会跳过 atexit/finally，锁就成了"残留锁"，
    # 下一次启动只能靠 PID/指纹去猜（2026-10-03 反馈者那四条"已有实例在运行"就是这么来的）。
    _release_lock()
    os._exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
