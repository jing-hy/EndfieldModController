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


def _already_running() -> bool:
    """判断是否已经有控制器在跑。

    ⚠️ 2026-10-03 改成**锁文件 + PID 存活检查**。原先用命名互斥体
    （`CreateMutexW` + `GetLastError()==183`），实测**怎么都判不出来**：
    ctypes 的 `get_last_error()` 在这条调用链上取不到可靠值（哪怕用了
    `use_last_error=True` 并声明了 restype/argtypes），连续调用永远返回 False
    ⇒ 用户能开出两个实例、互相踩 `config.json`（他实测就是这个现象：
    `set_component_addon failed ... config.json.tmp-10116`，同时两个管理器在跑）。

    锁文件方案不依赖 ctypes 语义：用 `O_CREAT|O_EXCL` 抢占 `<数据根>/runtime/.mc.lock`，
    里面写自己的 PID；若文件已存在则读出来看那个 PID **是否还活着**，活着就是"已有实例"，
    否则视为陈旧锁并接管。

    ⚠️ **数据根不能用无参 `AppConfig.load()`**（2026-10-03 当天第二次踩到）：
    它读的是 `DEFAULT_CONFIG_PATH`（源码/插件所在位置），而用户实际运行的是**别处的 exe**
    （例如 modtest 下的那份 exe）。于是两个实例算出的锁位置不一致
    （一个写 modtest、一个写工作区），**互相看不见、谁都拦不住谁**，用户照样能开出两个、
    然后撞上 `WinError 5 拒绝访问 ... config.json.tmp-8668-4`。
    统一口径：**数据根 = exe 所在目录**（打包后取 `sys.executable`）。
    """
    try:
        root = _instance_root()
        lock_dir = root / "runtime"
        lock = lock_dir / ".mc.lock"
        lock_dir.mkdir(parents=True, exist_ok=True)
        if lock.is_file():
            try:
                pid = int(lock.read_text(encoding="utf-8").strip())
                if pid == os.getpid():
                    return False          # 锁就是本进程写的 ⇒ 本进程是持有者
                if _pid_alive(pid):
                    return True           # 别的活着的实例在持有
            except (OSError, ValueError):
                pass
            # 走到这里 = 陈旧锁（进程早没了 / 内容坏了）⇒ 删掉后重新抢
            try:
                lock.unlink()
            except OSError:
                pass
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
            return False
        except FileExistsError:
            # 竞态：刚好被别人抢到了
            return True
    except Exception:  # noqa: BLE001 - 判断失败一律当作"没有别的实例"，绝不因此起不来
        return False


def _pid_alive(pid: int) -> bool:
    """这个 PID 是不是还活着（并且确实是本程序）。"""
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # 声明类型：不声明的话 64 位下句柄会被截断（这个坑刚踩过）
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
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
    #
    # ⚠️⚠️ **2026-10-03 修「下载时关窗口会卡死、也没有弹窗」**：
    # 后端这条链路一直是完整的（`has_active_downloads` / `confirm_exit` 都在），
    # 但**前端从来没有定义 `window.mcAskExit`** —— 于是这里 `evaluate_js` 什么也没做、
    # 却仍然 `return False` 取消关闭：用户看到的是"点了关闭没反应（卡死）、也没弹窗"。
    # 两条都补上：
    #   ① 前端加 `window.mcAskExit`（App.vue），弹确认框 → 用户选"仍然退出"时调
    #      `api.confirm_exit()` 并再关一次窗；
    #   ② 这里加**超时放行**：万一前端没响应（页面卡住/JS 报错），
    #      也不能让窗口永远关不掉 —— 到点就放行，绝不把用户锁在里面。
    import time as _time

    _ask_at = {"t": 0.0}

    def _on_closing():
        try:
            if api.exit_confirmed:
                return True
            if not api.has_active_downloads():
                return True
        except Exception:  # noqa: BLE001 —— 判据出问题不该把程序卡住关不掉
            return True
        now = _time.monotonic()
        # 已经问过、且超过 25 秒还没等到回应 ⇒ 放行（用户已经被拦过一次，不能无限拦）
        if _ask_at["t"] and (now - _ask_at["t"]) > 25.0:
            try:
                api.exit_confirmed = True
            except Exception:  # noqa: BLE001
                pass
            return True
        _ask_at["t"] = now
        try:
            window.evaluate_js("window.mcAskExit && window.mcAskExit()")
        except Exception:  # noqa: BLE001
            return True          # 连脚本都发不出去 ⇒ 别再拦，直接放行
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
