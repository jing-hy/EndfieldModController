"""游戏崩溃取证：跟踪 Endfield.exe 的生命周期，崩了就自动收集现场并写进日志。

日志写到 `runtime/logs/crash-<时间戳>.log`，同时把摘要投进控制器主日志。
现场内容包括：
  * 进程时间线（启动 / 退出 / 存活秒数）
  * 崩溃判定（CrashSight 的 reportException / uploadCrash 时间点）
  * 启动时的注入快照（XXMI 注入库、游戏目录各 dll、乳摇状态）
  * XXMI Launcher Log 里最近的注入记录
  * 游戏自己的崩溃栈（`%LOCALAPPDATA%\\Temp\\Hypergryph\\Endfield\\Crashes\\Crash_*\\Player.log`
    里 `Crash!!!` 前后那一段，以及模块清单中的第三方 DLL）
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

GAME_PROCESS = "Endfield.exe"
_THIRD_PARTY_HINT = re.compile(
    r"(zmdmod|EFMI|sbm\.dll|plugin\\|d3dcompiler_47|vulkan-1|reshade|renodx|nvngx|sl\.|EndfieldBase)",
    re.I,
)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _log(config: AppConfig, message: str, category: str = "crash") -> None:
    try:
        from . import diagnostics

        diagnostics.log_event(config, message, category=category)
    except Exception:  # noqa: BLE001
        pass


def _process_ids(name: str = GAME_PROCESS) -> list[int]:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def _endfield_local_low() -> Path:
    """游戏自己的 LocalLow 目录（`...\\LocalLow\\<厂商>\\Endfield`）。

    ⚠️⚠️ **两家厂商都要认**（2026-10-07 从两个反馈者的包对照查出）：国服是 `Hypergryph`，
    **国际服/其它渠道是 `Gryphline`**（他们的游戏目录叫 `Arknights Endfield`）。这里原先
    **写死 `Hypergryph`** ⇒ 国际服那台**永远读不到 `Player.log`** ⇒ 建立在它上面的判据
    （`streamline_manifest_broken()` 等）**一次都不会命中** —— 表现就是"说好的自动处理
    从来没触发过"：issue #16 换上 v1.1.1 之后，包里**仍然是 10 条 `parseServerManifest`
    报错**（本该被自动换掉的新版 Streamline 一直没装）。

    两个目录都不在时，仍返回国服那个路径（让调用方能拼出路径，只是文件不存在）。
    """
    from . import fsutil

    return fsutil.endfield_local_low_dirs()[0]

def _crash_root() -> Path:
    """游戏的崩溃报告目录（`%TEMP%\\<厂商>\\Endfield\\Crashes`）—— 同样**两家都要认**。"""
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("TEMP", "")):
        if not base:
            continue
        for vendor in ("Hypergryph", "Gryphline"):
            root = Path(base) / "Temp" / vendor / "Endfield" / "Crashes"
            if root.is_dir():
                return root
    return (Path(os.environ.get("LOCALAPPDATA", "")) / "Temp"
            / "Hypergryph" / "Endfield" / "Crashes")


# ---------------------------------------------------------------------------
# 现场快照
# ---------------------------------------------------------------------------
def injection_snapshot(config: AppConfig) -> dict[str, Any]:
    """当前注入物快照（游戏目录 dll、XXMI 注入库、乳摇状态）。"""
    from . import launcher, reshade_integration, secondary_motion

    snap: dict[str, Any] = {"game_dir": None, "files": {}, "extra_libraries": "", "sbm": {}}
    game_dir = reshade_integration.detect_game_dir(config)
    if game_dir is not None:
        snap["game_dir"] = str(game_dir)
        for name in ("nvngx_dlss.dll", "nvngx_dlssnr.dll", "d3dcompiler_47.dll", "vulkan-1.dll", "d3d12.dll", "dxgi.dll"):
            path = game_dir / name
            snap["files"][name] = path.stat().st_size if path.is_file() else 0
        plugin = game_dir / "plugin" / "sbm.dll"
        snap["files"]["plugin\\sbm.dll"] = plugin.stat().st_size if plugin.is_file() else 0
    try:
        status = launcher.dlss5_injection_status(config)
        snap["extra_libraries"] = status.get("extra_libraries") or ""
        snap["injection_enabled"] = status.get("enabled")
    except Exception as exc:  # noqa: BLE001
        snap["extra_libraries"] = f"(读取失败: {exc})"
    try:
        sbm = secondary_motion.status(config)
        snap["sbm"] = {"injected": sbm.get("injected"), "plugin": sbm.get("plugin_exists"),
                       "version": sbm.get("tool_version")}
    except Exception as exc:  # noqa: BLE001
        snap["sbm"] = {"error": str(exc)}
    return snap


def _xxmi_inject_lines(config: AppConfig, limit: int = 6) -> list[str]:
    launcher_path = config.xxmi_launcher_path
    if launcher_path is None:
        return []
    log_path = launcher_path.parent.parent.parent / "XXMI Launcher Log.txt"
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    hits = [ln.strip() for ln in lines if "ApplicationEvents.Inject(" in ln or "Successfully injected DLL" in ln
            or "StartAndInject(" in ln]
    return hits[-limit:]


def is_crash(evidence: dict[str, Any]) -> bool:
    """判定这次游戏退出算不算崩溃。

    判据（2026-09-27 第二次修订，依据用户实测反馈「刚才是我直接关了终末地的窗口」）：
      * **`reportException` 不等于崩溃。** 用户手动关窗口的正常退出，CrashSight 里
        同样留下 5~6 条 reportException —— 因为游戏自己在反复打
        `[Error] [Scope] Failed to fallback to main scope : [ItemBag] Main` 这类
        **被捕获、并不致命**的异常，CrashSight 把它们也上报了。拿它当崩溃信号，
        就是"正常退出也弹异常退出"的根因。
      * **`uploadCrash` 才是崩溃证据**（会上传崩溃转储）。实测：真崩溃 18:13/18:16
        有 uploadCrash，用户关窗口 18:21/18:25 没有。
      * **WER 报告也是崩溃证据**（2026-10-05 补）：进程真崩时 Windows 会在
        `%LOCALAPPDATA%\\Microsoft\\Windows\\WER\\ReportArchive\\AppCrash_*` 留一份报告，
        里面直接写着"故障模块 + 异常代码"。这条补上的直接原因：2026-10-05 那份诊断包里
        8 次真崩（`dxgi.dll` + `0xA816`，WER 齐全）却**每次都被判成"未发现崩溃迹象"** ——
        因为终末地的崩溃处理器把异常吞了、CrashSight 没上传转储，而我们只看 uploadCrash。

    判定顺序：uploadCrash → 正常退出统计 → WER 报告 → Player.log 崩溃标记。
    （"有正常退出统计"排在 WER 之前：真崩不会有卸载统计，反过来能挡住时间窗没卡准的旧报告。）
    """
    # ① 真正上传了崩溃转储 —— 最可靠的崩溃证据
    if evidence.get("crash_upload"):
        return True
    # ② 有正常退出卸载统计 —— 正常退出
    if evidence.get("normal_exit"):
        return False
    # ③ 本次运行时段里留下了 WER 应用程序错误报告
    if evidence.get("wer_crash"):
        return True
    # ④ 都没有时，再看 Player.log 里有没有崩溃标记
    return bool(evidence.get("player_log_crash"))


# ---------------------------------------------------------------------------
# WER 报告：Windows 自己写的崩溃记录（"故障模块 + 异常代码"最硬的一手材料）
# ---------------------------------------------------------------------------
def _wer_text(path: Path) -> str:
    """WER 报告是 UTF-16LE（带 BOM）；读不出来时退回 utf-8，别让编码问题吃掉证据。"""
    for encoding in ("utf-16", "utf-8"):
        try:
            return path.read_text(encoding=encoding, errors="replace")
        except (OSError, UnicodeError):
            continue
    return ""


def wer_crash_modules(since: float | None = None) -> list[str]:
    """本次运行时段内 WER 报告里的**故障模块名**（小写，去重）。

    `since` = 游戏进程启动时刻；只认 `mtime >= since - 5s` 的报告，
    否则会把上一次崩溃的报告算到这一次头上（同 `dlss5_crash_record` 的口径）。
    """
    out: list[str] = []
    try:
        from . import diagnostics

        paths = diagnostics.wer_report_paths()
    except Exception:  # noqa: BLE001 —— 拿不到就当没有，绝不影响主流程
        return out
    for path in paths:
        try:
            if since is not None and path.stat().st_mtime < float(since) - 5:
                continue
        except OSError:
            continue
        text = _wer_text(path)
        name = ""
        for line in text.splitlines():
            # Sig[3] = 故障模块名称；Sig[0..2] 是应用程序名/版本/时间戳
            if line.startswith("Sig[3].Value="):
                name = line.split("=", 1)[1].strip()
                break
        if not name:
            continue
        name = Path(name).name.lower()
        if name and name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# 崩溃归因：Mod 冲突 vs 其它（用户要求弹窗要区分）
# ---------------------------------------------------------------------------
_CRASH_RECORD_RE = re.compile(r"###\s*CRASH RECORDED\s*###\s*(?P<rest>.+?)\s*$", re.I | re.M)
# DLSS5 的 NR 风格档里被作者标记"启动就崩"的那个值（预发布字段 DLSSNR.Style 选「模型 C」）。
# 现在**只用于记录**（崩溃记忆里会带上"当时 NRStyle 是多少"），**不再用于任何归因或改动** ——
# 2026-10-02 定案：它既不是本项目的崩因（真正原因是 RabbitFX 进了 staging），
# "NRStyle=2 引起这次崩溃"那条因果归因已按用户要求**整段删除**。
_NRSTYLE_BAD_VALUE = "2"


# ---------------------------------------------------------------------------
# 崩溃取证：把"怎么崩的 / 崩在哪一层"解析成能读的结论（2026-10-06 加）
# ---------------------------------------------------------------------------
# 用户原话：「**你加判据，多加一点**」。起因是那份反馈包（勾选 DLSS5 神经渲染就闪退）：
# 手里明明有 WER 的"异常代码 + 异常数据"和一份**戛然而止**的 ReShade 日志，要回答的问题却
# 全靠人肉翻 —— ① 是不是空指针？② 自己退还是被强杀？③ 崩在 addon 加载之前还是之后？
# ④ 故障模块到底有没有被定位到？这些数据现场都有，这里一次解析成结论。
#
# ⚠️ 本段**只如实陈述证据，不做任何因果归因** —— 尤其不碰 `NRStyle`
#    （2026-10-02 已定案它不是本项目的崩因，见上面 `_NRSTYLE_BAD_VALUE` 的说明）。
# 面板 addon 日志的文件名（与 `diagnostics.ADDON_LOG_NAME` 同一个值）
_ADDON_LOG_NAME = "modecontroller.addon.log"
_EXCEPTION_NAMES = {
    "c0000005": "访问违例（ACCESS_VIOLATION）—— 读写了非法地址",
    "c0000409": "栈保护 / CRT fail-fast（STATUS_STACK_BUFFER_OVERRUN）",
    "c000001d": "非法指令（ILLEGAL_INSTRUCTION）",
    "c00000fd": "栈溢出（STACK_OVERFLOW）",
    "c0000374": "堆损坏（HEAP_CORRUPTION）",
    "c0000135": "找不到依赖 DLL（STATUS_DLL_NOT_FOUND）",
    "80000003": "断点（BREAKPOINT）",
}
_WER_PAIR_RE = re.compile(r"^(?:Dynamic)?Sig\[(\d+)\]\.(Name|Value)=(.*)$")


def _wer_named_fields(text: str) -> dict[str, str]:
    """把 WER 的 `Sig[n].Name=…` / `Sig[n].Value=…` **配对**成 `{名字: 值}`。

    为什么不直接按 `Sig[7]` 取：不同 Windows 版本的编号会漂，而名字是稳定的。
    """
    names: dict[str, str] = {}
    values: dict[str, str] = {}
    for raw in text.splitlines():
        match = _WER_PAIR_RE.match(raw.strip())
        if not match:
            continue
        index, kind, value = match.group(1), match.group(2), match.group(3).strip()
        (names if kind == "Name" else values)[index] = value
    return {names[key]: value for key, value in values.items() if names.get(key)}


def _recent_wer_texts(since: float | None) -> list[tuple[Path, str]]:
    """`since` 之后的 WER 报告（(路径, 文本)），**新的在前**。"""
    try:
        from . import diagnostics

        paths = list(diagnostics.wer_report_paths())
    except Exception:  # noqa: BLE001 —— 拿不到就当没有，绝不影响主流程
        return []
    out: list[tuple[Path, str]] = []
    for path in paths:
        try:
            if since is not None and path.stat().st_mtime < float(since) - 5:
                continue
        except OSError:
            continue
        out.append((path, _wer_text(path)))
    out.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
    return out


def wer_exception_detail(since: float | None = None) -> dict[str, str]:
    """最近一次 WER 的**异常代码 / 异常数据 / 故障模块**，并翻成人话。

    为什么需要（2026-10-06 实测）：反馈包里 WER 写着 `异常代码=c0000005`、
    `异常数据=0000000000000008` —— 那是"读 **null + 8**"（典型空指针访问对象成员）；
    只说"崩了"是分不出"空指针 / 野指针 / 堆损坏 / 栈溢出"的。
    另外 `故障模块 = StackHash_xxxx` 表示**Windows 连是哪个模块崩的都没定位到**
    （栈上没有可用模块信息）—— 这本身就是一条判据，别当成"模块就叫 StackHash"。
    """
    for _path, text in _recent_wer_texts(since):
        fields = _wer_named_fields(text)
        if not fields:
            continue
        code = (fields.get("异常代码") or "").strip().lower()
        data = (fields.get("异常数据") or "").strip().lower()
        module = (fields.get("故障模块名称") or fields.get("故障模块") or "").strip()
        parts: list[str] = []
        if code:
            known = _EXCEPTION_NAMES.get(code)
            parts.append(f"异常代码 `{code}`" + (f" = {known}" if known else ""))
        try:
            address = int(data, 16) if data else -1
        except ValueError:
            address = -1
        if address > 0:
            if code == "c0000005" and address <= 0x1000:
                parts.append(f"异常数据 `0x{address:x}` ⇒ **读/写 null + 0x{address:x}**"
                             f"（空指针访问对象成员）")
            else:
                parts.append(f"异常数据 `0x{address:x}`（读写地址）")
        if module:
            if module.lower().startswith("stackhash"):
                parts.append(f"故障模块 `{module}` ⇒ **没能定位到是哪个模块崩的**"
                             f"（栈上没有可用模块信息）")
            else:
                parts.append(f"故障模块 `{module}`")
        return {"exception_code": code, "exception_data": data, "fault_module": module,
                "text": "；".join(parts)}
    return {}


def _addon_log_paths(config: AppConfig) -> list[Path]:
    """面板 addon 日志的候选位置（`DllMain` 第一行就写它 ⇒ 能回答"走到哪一步"）。

    ⚠️ **候选必须给全**（2026-10-06 实测教训）：第一版只列了 `reshade\\` 与 `dlss5\\`，
    而反馈包里那份实际是从**游戏目录**收上来的 ⇒ 判据当场"判不出"（**等于没做这条判据**）。
    这里与 `diagnostics._addon_log_summary` 的多候选口径对齐。
    """
    bases: list[Path] = []
    for name in ("reshade_runtime_path", "dlss5_path", "runtime_path"):
        base = getattr(config, name, None)
        if base:
            bases.append(Path(base))
    game_exe = str(getattr(config, "game_exe", "") or "").strip()
    if game_exe:
        bases.append(Path(game_exe).parent)
    candidates: list[Path] = []
    for base in bases:
        for path in (base / _ADDON_LOG_NAME, base / "Addons" / _ADDON_LOG_NAME):
            if path not in candidates:
                candidates.append(path)
    return candidates


def addon_exit_kind(config: AppConfig) -> str:
    """"自己退出"还是"被强杀"—— 判据是**面板 addon 有没有收到 `DllMain detach`**。

    2026-10-05 定的口径：收到 detach = 走了 `ExitProcess`（卸载流程跑到了）；
    一条都没有 = 被 `TerminateProcess` 强杀（崩了，或被别的程序结束）。
    """
    seen_any = False
    for path in _addon_log_paths(config):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen_any = True
        if "DllMain detach" in text:
            return "自己退出（面板 addon 收到了 `DllMain detach` ⇒ 走到了正常卸载）"
    if not seen_any:
        return "判不出（没找到面板 addon 的日志）"
    return "被强杀 / 中途消失（面板 addon **没有** `DllMain detach` ⇒ 不是正常退出）"


def reshade_log_verdict(config: AppConfig, *, small_bytes: int = 8192) -> str:
    """生效那份 `ReShade.log` 的"戛然而止"判据：崩在 addon 加载**之前**还是之后。

    为什么要它（2026-10-06）：反馈者那三份崩掉的日志都只有 **2,775 B**、最后一行停在
    `Redirecting Direct3DCreate9(…)`，**连一条 `Registered add-on` 都没有** —— 这既可能是
    "崩在 addon 加载之前"，也可能是"崩溃时日志缓冲没落盘"。**两种含义必须一起说清楚**，
    否则读的人会直接把"没有 addon 行"当成"跟 addon 无关"。
    """
    from . import nr_autostart

    path = nr_autostart.reshade_log_path(config)
    if not path.is_file():
        legacy = Path(config.dlss5_path) / "ReShade.log"
        path = legacy if legacy.is_file() else None
    if path is None:
        return "没有 ReShade 日志（没进过游戏？）"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        size = path.stat().st_size
    except OSError as exc:
        return f"读不到 ReShade 日志：{exc}"
    marker = "Initializing crosire's ReShade"
    last = text.rfind(marker)
    recent = text[last:] if last >= 0 else text
    lines = [line for line in recent.splitlines() if line.strip()]
    tail = lines[-1].strip() if lines else ""
    registered = recent.count("Registered add-on")
    verdict = f"{size:,} B / 本次运行 {len(lines)} 行"
    if tail:
        verdict += f"；最后一行：`{tail[:120]}`"
    if registered == 0:
        verdict += ("；**没有一条 `Registered add-on`** ⇒ 要么崩在 addon 加载之前，"
                    "要么崩溃时日志缓冲还没落盘（这两者要靠转储区分）")
    else:
        verdict += f"；已注册 {registered} 个 add-on（崩在 addon 加载之后）"
    if size < small_bytes:
        verdict += "；日志极短（疑似启动早期就中断）"
    return verdict


def nr_settings_snapshot(config: AppConfig) -> str:
    """崩溃当时 NR 的档位（`DLSS5 active settings:`，取最后一次运行的那行）。

    ⚠️ **只记录、不归因** —— 见本段开头的说明。
    """
    from . import nr_autostart

    path = nr_autostart.reshade_log_path(config)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    marker = "Initializing crosire's ReShade"
    recent = text[text.rfind(marker):] if text.rfind(marker) >= 0 else text
    hits = [line.strip() for line in recent.splitlines() if "DLSS5 active settings:" in line]
    if not hits:
        return ""
    return hits[-1].split("DLSS5 active settings:", 1)[1].strip()


# Windows 标准对话框的窗口类名（`#32770` = Dialog）
_DIALOG_CLASS = "#32770"
_CRT_DIALOG_HINTS = ("microsoft visual c++ runtime library", "runtime error")


def _visible_windows() -> list[tuple[int, str, str]]:
    """枚举**可见的顶层窗口**：`[(pid, 标题, 类名)]`（非 Windows 返回空）。"""
    import os

    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    out: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):  # noqa: ANN001
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = int(user32.GetWindowTextLengthW(hwnd) or 0)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            klass = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, klass, 256)
            out.append((int(pid.value), title.value.strip(), klass.value.strip()))
        except Exception:  # noqa: BLE001 —— 单个窗口出问题不该影响其它
            pass
        return True

    try:
        user32.EnumWindows(_callback, 0)
    except Exception:  # noqa: BLE001
        return []
    return out


def stuck_on_crt_dialog() -> str:
    """进程是不是**卡在 CRT 的 `Runtime Error!` 弹窗**上（没退出、也没有崩溃事件）。

    为什么要它（2026-10-06 反馈给的截图）：那是典型的
    「Microsoft Visual C++ Runtime Library / `Runtime Error!` / This application has requested
    the Runtime to terminate it in an unusual way.」—— `abort()`（未捕获 C++ 异常 /
    `std::terminate`）弹出的**模态对话框**。

    ⚠️ 关键：按我们自己记过的坑，**它会把进程卡在弹窗上 —— 既不写事件、也不退出**。
    于是事件日志 / WER / 退出码**一条都拿不到**（`diagnostics` 里解析的那两个退出码
    `0xC0000409` / `0x40000015` 此时根本不会出现），"闪退"这个词也就对不上现场
    （进程其实还活着）。所以只能**直接枚举窗口**。
    """
    for pid, title, klass in _visible_windows():
        low = title.lower()
        if klass == _DIALOG_CLASS and any(hint in low for hint in _CRT_DIALOG_HINTS):
            return (f"**卡在 CRT 弹窗上**：窗口「{title}」（PID {pid}，类 {klass}）"
                    f"—— 这是 `abort()` / 未捕获 C++ 异常弹的模态框。**进程还活着**，"
                    f"事件日志与 WER 都不会有记录，所以别按「闪退」去找；先关掉这个弹窗。")
    return ""


# 已知的"**替代 NR provider**"addon：与 `renodx-dlss5*.addon64` 抢同一个 provider 位。
# 来源 = DLSS5-Feeder 自己的警告（2026-10-06 反馈包实测原文）：
#   "Deep Fried Chicken 1.4.8-alpha and renodx-dlss5.addon64 are BOTH next to this add-on.
#    Chicken replaces the RenoDX neural provider and stays inert for the whole process while
#    both are loaded, so neural rendering will come from RenoDX or from nothing."
_RIVAL_NR_PROVIDERS = {
    "deep-fried-chicken.addon64":
        "Deep Fried Chicken（自带 neural provider，与 RenoDX 抢同一个位置）",
}


# NR 引擎 × 驱动的**已知坏组合**（DLSS5-Feeder 官方矩阵 / issue #54，2026-10-06）。
# 官方矩阵：renodx-dlss5 v4.70 在 616.56 上 300/300，但 616.64 与 617.14 上 **0/300**；
# v6.1.0 / v7.0.0-rc8 / v8.0.1 在 617.14 上 300/300。
_NR_ENGINE_BAD_MAX = (4, 70)
_NR_DRIVER_BAD_MIN = (616, 64)


def _driver_branch(version: str) -> tuple[int, int] | None:
    """把 Windows 的驱动版本 `32.0.16.1714` 换算成 NVIDIA 的 `617.14`。

    规则：取最后两段数字拼起来（`16` + `1714` = `161714`），**后 5 位**再拆成 `617` / `14`。
    """
    parts = [part for part in str(version).split(".") if part.isdigit()]
    if len(parts) < 2:
        return None
    digits = "".join(parts[-2:])
    if len(digits) < 5:
        return None
    tail = digits[-5:]
    return (int(tail[:3]), int(tail[3:]))


def current_driver_branch() -> tuple[int, int] | None:
    """本机 NVIDIA 驱动分支（如 `(617, 14)`）；拿不到返回 None。"""
    try:
        from . import deviceinfo

        for adapter in deviceinfo._adapters():
            # ⚠️ **只认 NVIDIA 那张卡**（2026-10-06）：本机/很多机器是"核显 + 独显"，
            #    取第一个会读到 AMD/Intel 的驱动号（实测得到 199.49 这种值）。
            if "nvidia" not in str(adapter.get("name") or "").lower():
                continue
            branch = _driver_branch(str(adapter.get("driver") or ""))
            if branch:
                return branch
    except Exception:  # noqa: BLE001 —— 拿不到就不判
        return None
    return None


def nr_engine_version(config: AppConfig) -> tuple[int, int] | None:
    """日志里报出的 NR 引擎版本（`RenoDX DLSS5 Generic v4.7 (build …)`）。"""
    from . import nr_autostart

    for path in (nr_autostart.reshade_log_path(config),
                 Path(config.dlss5_path) / "ReShade.log"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # ⚠️ **只看本次运行那段**（2026-10-06）：日志是追加写的，直接取最后一条会读到
        #    上一次运行留下的旧版本行（换版之后尤其容易看错）。
        marker = "Initializing crosire's ReShade"
        recent = text[text.rfind(marker):] if text.rfind(marker) >= 0 else text
        found = re.findall(r"RenoDX DLSS5 Generic v(\d+)\.(\d+)", recent)
        if found:
            major, minor = found[-1]
            return (int(major), int(minor))
    return None


def nr_ran_ok(config: AppConfig) -> bool:
    """本次运行 NR 有没有**真的出帧**（`evaluation succeeded (count=N)` 且 N > 1）。

    ⚠️ `count=1` 不算成功：首帧建起来之后就没下文，正是"建了但没跑起来"的形态。
    """
    from . import nr_autostart

    for path in (nr_autostart.reshade_log_path(config),
                 Path(config.dlss5_path) / "ReShade.log"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        marker = "Initializing crosire's ReShade"
        recent = text[text.rfind(marker):] if text.rfind(marker) >= 0 else text
        counts = [int(value) for value in
                  re.findall(r"inline feature 18 evaluation succeeded \(count=(\d+)", recent)]
        if counts and max(counts) > 1:
            return True
    return False


def nr_engine_driver_mismatch(config: AppConfig) -> str:
    """NR 引擎 × 驱动落在官方矩阵的**坏格子**里、**且这次确实没出帧**时给一句线索。

    ⚠️ **不要只看矩阵**（2026-10-06 自我纠正）：本机同驱动（617.14）实测 v4.7 出帧
    `count=60` 正常 ⇒ 矩阵那格不能当根因；所以这里先用 `nr_ran_ok()` 卡一道
    —— **出帧正常就一个字都不说**（判据要等于被观测事实）。
    """
    if nr_ran_ok(config):
        return ""
    engine = nr_engine_version(config)
    driver = current_driver_branch()
    if not engine or not driver:
        return ""
    if engine > _NR_ENGINE_BAD_MAX or driver < _NR_DRIVER_BAD_MIN:
        return ""
    return (f"**NR 引擎 {engine[0]}.{engine[1]} × 驱动 {driver[0]}.{driver[1]} 是已知会崩的组合**"
            f"—— DLSS5-Feeder 官方矩阵里该组合为 **0/300**，失败形态是 evaluate 崩在 "
            f"`nvngx_dlssnr.dll`（issue #54）。请把随包的 NR 引擎换成 **7.0.0-rc8 或更新**"
            f"（v6.1+ 起在 617.14 上是 300/300）")


def nr_provider_conflict(config: AppConfig) -> str:
    r"""`runtime\dlss5\` 里是不是**同时装了两个互相顶替的 NR provider**。

    为什么要它（2026-10-06 反馈）：那位机器上 `deep-fried-chicken.addon64`（自己装的）
    与随包的 `renodx-dlss5-4.7_汉化.addon64` 并存 ⇒ 日志里 Feeder 明确 WARN
    「两者同装时**两个都不工作**，neural rendering will come from RenoDX **or from nothing**」
    ⇒ 面板停在「未匹配NR功能 成功NR帧 0」，紧接着 NR 的 evaluate 还**崩在运行库里**。
    这条冲突 Feeder 检测得到、我们一直没检测 ⇒ 补上。
    """
    base = Path(getattr(config, "dlss5_path", "") or "")
    if not base.is_dir():
        return ""
    try:
        names = {path.name.lower(): path.name for path in base.glob("*.addon64")}
    except OSError:
        return ""
    reno = sorted(name for low, name in names.items() if low.startswith("renodx-dlss5"))
    rivals = sorted(names[low] for low in names if low in _RIVAL_NR_PROVIDERS)
    if not (reno and rivals):
        return ""
    detail = "；".join(_RIVAL_NR_PROVIDERS[name.lower()] for name in rivals)
    return (f"**两个 NR provider 同时在场**：{'、'.join(rivals)} 与 {'、'.join(reno)}"
            f"（{detail}）—— 二者互相顶替，**同装时两个都不工作**（Feeder 的原话："
            f"neural rendering will come from RenoDX or from nothing）⇒ NR 会停在"
            f"「未匹配NR功能 / 成功NR帧 0」，evaluate 还可能直接崩在 `nvngx_dlssnr.dll` 里。"
            f"处理：**二选一**（只留一个），然后完全重启游戏。")


def nr_evaluate_crash(config: AppConfig) -> str:
    """DLSS5-Feeder 有没有记下「**NR 的 evaluate 崩了**」——它带**故障模块**，比 WER 准。

    实测现场（2026-10-06 反馈包 `dlss5-feed.log`）：

        11:17:43.717 [feed] evaluate raised 0xC0000005 (reading address FFFFFFFFFFFFFFFF)
                            (caught; nothing submitted)
        11:17:43.717 [feed] evaluate fault stack, by module (innermost first):
                            D3D12Core.dll <- nvngx_dlssnr.dll
        11:17:43.718 stopped: the DLSS evaluate crashed

    ⇒ 崩在 **`nvngx_dlssnr.dll`**（NR 运行库）里。WER 那边只给出 `StackHash_*`（定位不到模块），
    所以这条是"崩在 NR 运行库"**唯一**的一手证据。
    """
    path = Path(getattr(config, "dlss5_path", "") or "") / "dlss5-feed.log"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    marker = "feed: opening D3D12 session"
    recent = text[text.rfind(marker):] if text.rfind(marker) >= 0 else text
    address = ""
    stack = ""
    for line in recent.splitlines():
        if "evaluate raised" in line and "0xC0000005" in line and not address:
            found = re.search(r"reading address ([0-9A-Fa-f]+)", line)
            address = found.group(1) if found else ""
        if "evaluate fault stack" in line and not stack:
            stack = line.split("innermost first)", 1)[-1].lstrip(": ").strip()
    if not (address or stack):
        return ""
    parts = ["**NR 的 evaluate 崩了**（DLSS5-Feeder 在进程内捕获，带故障模块）"]
    if address:
        parts.append(f"读地址 `0x{address}`")
    if stack:
        parts.append(f"故障栈（内→外）`{stack}`")
    parts.append("⇒ 这是 NR 运行库里的崩溃，不是游戏自身逻辑")
    return "；".join(parts)


def nr_toggle_flap(config: AppConfig, *, window: float = 3.0) -> str:
    """NR 有没有"**刚打开就被关掉**"（`toggled ON` 之后几秒内又 `toggled OFF`）。

    为什么要它（2026-10-06，反馈者原话「**游戏内无法打开 dlss5 的神经渲染**」）——
    他的日志长这样：

        21:16:31 Endfield enhancer: Camera controls installed.
        21:16:32.126 NR toggled ON via F6
        21:16:32.760 NR toggled OFF via F6      ← 0.6 秒后

    旧版（1.0.10）那条"等相机 hook 装好后**自动按一次 NR 键**"用的正是同一颗 **F6**
    ⇒ "开"和"关"被连着触发 ⇒ 用户看到的就是"打不开"（1.0.16 起改成"启动即开"、
    自动按键整条停用，这一类就不再发生）。

    ⚠️ 本判据**只说"被开了又关"**，不猜是谁按的 —— 谁按的要靠当时的配置与日志对照。
    """
    from . import nr_autostart

    path = nr_autostart.reshade_log_path(config)
    if not path.is_file():
        legacy = Path(config.dlss5_path) / "ReShade.log"
        path = legacy if legacy.is_file() else None
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    marker = "Initializing crosire's ReShade"
    recent = text[text.rfind(marker):] if text.rfind(marker) >= 0 else text
    stamp_re = re.compile(r"^(\d\d:\d\d:\d\d)[:.](\d\d\d)\s.*NR toggled (ON|OFF)")
    last_on: float | None = None
    for raw in recent.splitlines():
        match = stamp_re.search(raw.strip())
        if not match:
            continue
        clock = match.group(1).split(":")
        seconds = int(clock[0]) * 3600 + int(clock[1]) * 60 + int(clock[2]) + int(match.group(2)) / 1000
        if match.group(3) == "ON":
            last_on = seconds
            continue
        if last_on is not None and 0 <= seconds - last_on <= window:
            return (f"**NR 被打开后 {seconds - last_on:.1f} 秒又被关掉**"
                    f"（`NR toggled ON via …` 紧跟 `NR toggled OFF via …`）"
                    f"—— 用户感受就是「打不开」。看当时是不是有自动按键/重复触发（旧版的"
                    f"`auto_enable_nr_after_camera_hook` 会替用户按一次 NR 键）")
        last_on = None
    return ""


# ── Streamline / NGX 的 server manifest 损坏（2026-10-06）───────────────────────
# 现场：游戏启动后 15 毫秒连打 10 条
#   `[streamline][error] ota.cpp:329 [parseServerManifest] Unexpected line in manifest file: <乱码>`
# 随后内存从 627 MB 涨到 1694 MB、进程自己退出（无 WER、ReShade 卸载都没走完）。
# 包内 `%LOCALAPPDATA%\NVIDIA\NGX\models\config\versions\2\files\nvngx_server_config.txt`
# **是 0 字节** —— 与报错的 `parseServerManifest` 直接对应。
_STREAMLINE_MANIFEST_MARKERS = (
    "parseServerManifest",
    "Unexpected line in manifest file",
    "[streamline][error]",
)


def _player_log_candidates(config: AppConfig) -> list[Path]:
    """可能藏着"**游戏自己写的** Player.log"的位置（按可信度排序）。

    ⚠️ **必须把 `_endfield_local_low()` 放第一位**（那才是游戏真正落盘的地方）。
    2026-10-06 的教训：我一开始只拼了 `runtime\\logs\\player\\Player.log` ——
    **该路径根本不存在** ⇒ 判据一次都没命中 ⇒ v1.0.22 的自动修复从未执行
    （反馈者升级到 v1.0.22 后仍带同样的 `parseServerManifest` 报错）。
    `runtime\\player\\*` 那几份是我们自己归档出来的副本，只作兜底。
    """
    out: list[Path] = []
    low = _endfield_local_low()
    if low is not None:
        out += [low / "Player.log", low / "Player-prev.log"]
    runtime = Path(config.runtime_path)
    for sub in ("player", "logs"):
        out += [
            runtime / sub / "Player.log",
            runtime / sub / "Endfield-Player.log",
            runtime / sub / "Endfield-Player-prev.log",
            runtime / sub / "player-Player.log",
        ]
    return out


def nvidia_config_roots() -> list[Path]:
    r"""NVIDIA 落"清单 / 配置"的那几个根（**采集与清理共用的唯一入口**）。

    ⚠️ **为什么必须是共用入口**（2026-10-06 第二次踩坑）：诊断包由这里列出 6 个候选根
    （`%LOCALAPPDATA%\NVIDIA\NGX`、`%LOCALAPPDATA%\NVIDIA Corporation\NGX`、
    `%PROGRAMDATA%` 下三个…），而"清理损坏配置"那边一度**只写了一个**
    `%LOCALAPPDATA%\NVIDIA\NGX` ⇒ 反馈者那台的文件在别的根里 ⇒ 日志报
    "判据命中、但没找到可清理的缓存文件"，**修复实际没做**。
    凡是"发现的路径"与"动手的路径"，只能有一处定义。
    """
    home = Path(os.environ.get("USERPROFILE") or "")
    local = home / "AppData" / "Local"
    programdata = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    return [
        local / "NVIDIA" / "Streamline",
        local / "NVIDIA" / "NGX",
        local / "NVIDIA Corporation" / "NGX",
        programdata / "NVIDIA" / "Streamline",
        programdata / "NVIDIA Corporation" / "NGX",
        programdata / "NVIDIA" / "NGX",
    ]


def _broken_config_file(path: Path) -> str:
    r"""这份 NGX / Streamline 配置是不是**坏到读不了**（返回原因，正常则空串）。

    为什么按内容判而不是按文件名（2026-10-06 两位反馈者对照，报的是同一条
    `parseServerManifest` 错，但坏的文件不同）：
      * 一位 `nvngx_server_config.txt` = **0 字节**，`nvngx_mapping.json` = 700 B（正常）；
      * 另一位 `nvngx_server_config.txt` = 5,296 B（正常），**`nvngx_mapping.json` = 0 字节**。
    判据只认三种**确定**的坏：空文件 / `.json` 解析失败 / 含 NUL 或大量不可打印字节。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size == 0:
        return "空文件"
    if size > 4 * 1024 * 1024:                       # 大文件不动（那不是"读不懂的清单"）
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in raw:
        return "含 NUL 字节（不是文本清单）"
    if path.suffix.lower() == ".json":
        import json as _json

        try:
            _json.loads(raw.decode("utf-8", errors="strict"))
        except Exception as exc:  # noqa: BLE001
            return f"JSON 解析失败（{type(exc).__name__}）"
    else:
        printable = sum(1 for b in raw if 9 <= b <= 13 or 32 <= b < 127 or b >= 128)
        if printable < len(raw) * 0.9:
            return "大量不可打印字节（不是文本清单）"
    return ""


def streamline_manifest_broken(config: AppConfig) -> str:
    """游戏 `Player.log` 里有没有"Streamline 读不懂它的 server manifest"。

    为什么要它：这类失败**不是崩溃**（没有 WER、面板 addon 也正常 detach），
    表现是"游戏启动后很快就自己退出"，光看崩溃取证什么都抓不到。
    """
    for path in _player_log_candidates(config):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = sum(1 for line in text.splitlines()
                   if any(mark in line for mark in _STREAMLINE_MANIFEST_MARKERS))
        if hits:
            return (f"**Streamline 的 server manifest 读不懂**（`Player.log` 里 {hits} 条 "
                    f"`parseServerManifest Unexpected line in manifest file`）—— "
                    f"这类失败表现为**内存暴涨 + 启动后很快自己退出**，没有 WER、也不像崩溃")
    return ""


def streamline_ota_files(config: AppConfig) -> list[Path]:
    r"""要清理的 NGX / Streamline 缓存文件（server manifest 与 OTA 缓存）。

    只列**确定的目标**：NGX 的 `models\config\versions\*\files\nvngx_server_config.txt`
    与 Streamline 用户目录下的小文件。**不碰** `nvngx_config.txt` / `sl_sdk_*` 这些
    内容正常、驱动需要的表。
    """
    out: list[Path] = []
    # ⚠️ **必须遍历 `nvidia_config_roots()` 的全部候选根**（2026-10-06 第二次踩坑）：
    #   采集列出了 6 个根，而这里一度只写 `%LOCALAPPDATA%\NVIDIA\NGX` 一个 ⇒
    #   反馈者的坏配置在别的根里 ⇒ 判据命中但"没找到可清理的缓存文件"，修复没做。
    for root in nvidia_config_roots():
        if not root.is_dir():
            continue
        if root.name.lower() == "ngx":
            # ① **按内容判坏**：两位反馈者坏的文件不同（一位空的是 `nvngx_server_config.txt`、
            #    另一位空的是 `nvngx_mapping.json`），报的却是同一条 `parseServerManifest` 错
            #    ⇒ 只按文件名挑会漏掉一半。
            for item in sorted(root.glob("models/config/versions/*/files/*")):
                if item.is_file() and _broken_config_file(item):
                    out.append(item)
            # ② 名字直接对应报错函数的那份（server manifest）——内容看着正常也一并搬走
            out.extend(sorted(root.glob("models/config/versions/*/files/nvngx_server_config.txt")))
            # ③ ★★ **`nvngx_deny_list.txt` 才是 `ota.cpp` 真正读的那个清单**（2026-10-06 定案）。
            #    它的内容就是 `[streamline-ota]` 段（正常机器上 33 B：`[streamline-ota]` +
            #    `app_xxx = 1`），而反馈者那台 **是 0 字节** ⇒
            #    `[streamline][error] ota.cpp:329[parseServerManifest] Unexpected line in
            #    manifest file` ⇒ 内存暴涨后进程自己退出。
            #    ⚠️ **必须与上面那份成组一起清**：v1.0.24 只清了 `server_config`，
            #    结果驱动重建 OTA 时把 `deny_list` 写坏（那时它还不是 0 字节，按内容判不到）
            #    ⇒ 症状照旧。成组清掉、让驱动整套重建才有效。
            out.extend(sorted(root.glob("models/config/versions/*/files/nvngx_deny_list.txt")))
        else:
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                # **只取与 manifest / OTA 缓存有关的**（更保守：别把整个目录内容都搬走）
                name = item.name.lower()
                if any(key in name for key in ("manifest", "server", "ota", "cache")):
                    out.append(item)
    # 去重（①② 可能命中同一个文件）
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def repair_streamline_manifest(config: AppConfig, *,
                               log: Callable[[str], None] | None = None) -> list[str]:
    """把坏的 server manifest / OTA 缓存**备份移走**（只搬不删，驱动下次启动会重建）。

    返回被移走的文件名。**只有在判据命中时才会被调用**（见 `initialize` 的自检项）。
    """
    moved: list[str] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for path in streamline_ota_files(config):
        try:
            dest = path.with_name(path.name + f".mc-backup-{stamp}")
            shutil.move(str(path), str(dest))
        except OSError:
            continue
        moved.append(path.name)
    if moved and log:
        log("Streamline/NGX 的 server manifest 缓存已备份移走（驱动下次启动会自动重建）："
            + "、".join(moved[:6]) + ("…" if len(moved) > 6 else ""))
    return moved


def crash_forensics(config: AppConfig, evidence: dict[str, Any] | None = None) -> list[str]:
    """一次崩溃的**一页结论**（每条都只有一个问题、一个答案，且只陈述证据）。

    用户 2026-10-06：「你加判据，**多加一点**」。这几条正好各回答一个原本要人肉翻的问题：
    空指针还是别的？自己退还是被强杀？崩在 addon 之前还是之后？故障模块定位到了吗？
    以及（连着"打不开 NR"那类反馈一起看）NR 有没有被开了又关掉？
    """
    evidence = evidence or {}
    started = evidence.get("_started_at")
    lines: list[str] = []
    detail = wer_exception_detail(started)
    if detail.get("text"):
        lines.append(f"异常：{detail['text']}")
    else:
        lines.append("异常：本次时段内没有 WER 报告"
                     "（被 TerminateProcess 结束不会留事件，见 `environment.txt` 的说明）")
    lines.append(f"退出方式：{addon_exit_kind(config)}")
    lines.append(f"ReShade 日志：{reshade_log_verdict(config)}")
    snapshot = nr_settings_snapshot(config)
    if snapshot:
        lines.append(f"当时的 NR 档位（**只记录、不归因**）：{snapshot}")
    mismatch = nr_engine_driver_mismatch(config)
    if mismatch:
        lines.append(f"NR 版本：{mismatch}")
    conflict = nr_provider_conflict(config)
    if conflict:
        lines.append(f"NR 冲突：{conflict}")
    crashed = nr_evaluate_crash(config)
    if crashed:
        lines.append(f"NR 运行库：{crashed}")
    flap = nr_toggle_flap(config)
    if flap:
        lines.append(f"NR 开关：{flap}")
    stuck = stuck_on_crt_dialog()
    if stuck:
        lines.append(f"当前状态：{stuck}")
    streamline = streamline_manifest_broken(config)
    if streamline:
        lines.append(f"Streamline：{streamline}")
    return lines


def dlss5_crash_record(config: AppConfig, started_at: float | None = None) -> dict[str, Any] | None:
    """读 `runtime\\dlss5\\dlss5-feed.log` 里 **DLSS5 插件自己写的**崩溃记录。

    ```text
    11:47:05.434  ### CRASH RECORDED ###  exception 0xC0000005 (reading address 0000000000000020)
                  at 00007FFC6E247EC5 in C:\\…\\nvgpucomp64.dll; this add-on was last doing:
                  D3D11 output blit complete
    ```

    为什么把它放在归因的**第一顺位**（2026-10-02 用户反馈）：这是**实测证据** —— 插件就在
    游戏进程里，它记下了 faulting module、异常码与"自己最后在做什么"；而"自检发现两个 Mod
    覆盖同一批资源"只是**静态推测**。那天用户的 NRStyle 崩溃就被归成了"Mod 资源冲突"，
    弹窗还让他去清理 Mod，白折腾。**有硬证据时，硬证据说了算。**

    只认**本次运行**写下的那条（用日志文件 mtime 与 `started_at` 比），否则会把上一次崩溃
    的记录算到这一次头上。
    """
    log = Path(str(getattr(config, "dlss5_path", ""))) / "dlss5-feed.log"
    if not log.is_file():
        return None
    try:
        stat = log.stat()
    except OSError:
        return None
    if started_at:
        if stat.st_mtime < float(started_at) - 5:
            return None
    elif stat.st_mtime < time.time() - 900:
        # 没有时间基准时（少数调用点不传 started_at）只认"最近 15 分钟内"的日志 ——
        # 否则会把**上一次**崩溃留下的 CRASH RECORDED 算到这一次头上。
        return None
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    hits = list(_CRASH_RECORD_RE.finditer(text))
    if not hits:
        return None
    line = " ".join(hits[-1].group("rest").split())
    module = ""
    found = re.search(r"\bin\s+([^;]+?\.dll)\b", line, re.I)
    if found:
        module = Path(found.group(1).strip()).name
    doing = ""
    found = re.search(r"last doing:\s*([^;(]+)", line, re.I)
    if found:
        doing = found.group(1).strip()
    return {
        "line": line,
        "module": module,
        "doing": doing,
        "gpu_compiler": "nvgpucomp64" in module.lower(),
    }


def classify_cause(config: AppConfig, evidence: dict[str, Any], *,
                   started_at: float | None = None) -> dict[str, Any]:
    """给这次退出定性：``mod_conflict`` / ``crash`` / ``exit``。

    「确定是 Mod 冲突」的判据：**自检明确记录过** Mods 资源冲突
    （`initialize._check_mod_conflicts` 落盘到 `runtime\\_state\\mod_conflicts.json`），
    而且这次确实崩了 —— 结论来自自检，不是我们猜的；只有"这次游戏启动前后不久"的
    那份记录才算数（默认 6 小时窗口，够覆盖一轮玩）。
    """
    from . import diagnostics

    crashed = is_crash(evidence)
    state = diagnostics.mod_conflict_state(config)
    conflicts = [str(item) for item in (state.get("conflicts") or [])] if state else []
    has_conflict = bool(state) and state.get("ok") is False
    fresh = True
    if started_at and state.get("at"):
        try:
            fresh = float(state["at"]) >= float(started_at) - 6 * 3600
        except (TypeError, ValueError):
            fresh = True

    # ── 硬证据优先（2026-10-02 用户反馈后加的）：DLSS5 插件**自己记下的**崩溃是实测证据
    #    （它就在进程里，记下了 faulting module 与"最后在做什么"），而"自检发现两个 Mod
    #    覆盖同一批资源"只是**静态推测**。那天用 NRStyle=2 崩的那次被归成了"Mod 资源冲突"，
    #    弹窗还催用户去清理 Mod —— 白折腾。所以：**有硬证据时，硬证据说了算**；
    #    静态冲突照旧列出来（可能同时成立），只是不再自动当结论。
    record = dlss5_crash_record(config, started_at)
    if crashed and record and record.get("gpu_compiler"):
        detail = f"DLSS5 插件记录的崩溃：{record.get('line') or ''}"
        if conflicts:
            detail += f"（另外自检还检出过 {len(conflicts)} 组资源相交，但那只是静态推测）"
        return {
            "kind": "gpu_compiler",
            "title": "这次崩溃发生在显卡着色器编译器（nvgpucomp64），不是 Mod 冲突",
            "detail": detail,
            "conflicts": conflicts,
            "checked_at": str(state.get("at_text") or "") if state else "",
            "crashed": True,
        }

    if crashed and has_conflict and fresh:
        return {
            "kind": "mod_conflict",
            "title": "这次崩溃很可能由 Mod 资源冲突引起",
            "detail": str(state.get("detail") or ""),
            "conflicts": conflicts,
            "checked_at": str(state.get("at_text") or ""),
            "crashed": True,
        }
    if crashed:
        return {
            "kind": "crash",
            "title": "检测到终末地异常退出",
            "detail": "",
            "conflicts": [],
            "checked_at": str(state.get("at_text") or "") if state else "",
            "crashed": True,
        }
    return {
        "kind": "exit",
        "title": "终末地已退出（未检测到崩溃）",
        "detail": "",
        "conflicts": [],
        "checked_at": "",
        "crashed": False,
    }


# ---------------------------------------------------------------------------
# 崩溃记忆：记住"哪套 Mod 组合崩过"，供一键启动前预警（用户 2026-09-30 要求）
# ---------------------------------------------------------------------------
CRASH_MEMORY_NAME = Path("_state") / "crash_memory.json"
CRASH_MEMORY_LIMIT = 20
_CONTROLLER_DIRS = frozenset({
    "MC_Controller", "MC_Probe.ini", "DISABLED",
    "EndfieldModControllerManaged", "ModeControllerManaged",
})


def crash_memory_path(config: AppConfig) -> Path:
    return Path(config.runtime_path) / CRASH_MEMORY_NAME


def _is_dependency_dir(item: Path) -> bool:
    """这个 staging 目录是**依赖**（RabbitFX / Orfix / SlotFix 那类）吗？

    判据统一走 `core.is_dependency_package`（**名字像依赖 且 自己不带换装资源**）。

    ⚠️ **不能只看名字**（2026-10-02 定案）：作者的皮肤包常把前置名写进包名 ——
    `MC_莱万汀_laevatain_..._rabbitfx_da62a` 会被旧的 `dependency_key_of` 命中，
    于是被当成依赖排除出"当前加载的 Mod 清单" ⇒ 崩溃归因的组合比对**漏掉真正的 Mod**。
    """
    try:
        from . import core

        return core.is_dependency_package(item.name, item)
    except Exception:  # noqa: BLE001
        return False


def staging_mods(config: AppConfig, *, include_dependencies: bool = False) -> list[str]:
    """当前 staging（EFMI\\Mods）里"**用户选的**"那些 Mod 名字（排序，排掉控制器自己的东西）。

    ⚠️ **默认排除依赖**（RabbitFX / Orfix / SlotFix 这类）：它们是被"按需激活"自动带进来的，
    **不是用户的选择** —— 拿它们参与"崩溃记忆"的组合比对会**误报**。用户 2026-10-02 实测：
    只勾了佩丽卡一个皮肤，启动前却弹出"佩丽卡 + 旗袍 + RabbitFX"那套旧记录 —— 因为依赖
    修复之后 RabbitFX 真的会进 staging，两家一凑就满足了 `_same_combo` 的"互为子集"判据。
    用户原话：「**MC_RabbitFX 不属于 mod，应该算依赖**」。

    需要把依赖也算进去时显式传 `include_dependencies=True`。
    """
    root = Path(config.staging_mods_path)
    try:
        items = sorted(root.iterdir())
    except OSError:
        return []
    out: list[str] = []
    for item in items:
        if not item.is_dir() or item.name in _CONTROLLER_DIRS:
            continue
        if item.name.startswith("MC_Controller") or item.name.startswith("MC_Probe"):
            continue
        if not include_dependencies and _is_dependency_dir(item):
            continue
        out.append(item.name)
    return out


def read_crash_memory(config: AppConfig) -> list[dict[str, Any]]:
    import json

    try:
        data = json.loads(crash_memory_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else data
    return [e for e in (entries or []) if isinstance(e, dict)]


def _current_nrstyle(config: AppConfig) -> str:
    """崩溃那一刻 `ReShade.ini` 里的 `NRStyle`（读不到就返回空串）。

    为什么要记它（用户 2026-10-02 要求）：`NRStyle=2` = 预发布字段 `DLSSNR.Style` 选的
    「神经渲染模型 C」，**它会在这个人的机器上让启动崩掉**，但用户说"那个我还要用、
    不要一刀切" —— 所以只在**崩溃记忆命中的那套 Mod 组合**被再次勾选时才自动改回 0。
    崩溃时把当时的值记下来，是这条链路唯一的判据来源。
    """
    ini = Path(str(getattr(config, "dlss5_ini_path", "")))
    if not ini.is_file():
        return ""
    try:
        text = ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    block = re.search(r"\[RenoDX\.DLSS5\](.*?)(?=\n\s*\[|\Z)", text, re.S | re.I)
    if not block:
        return ""
    found = re.search(r"^\s*NRStyle\s*=\s*(\S+)\s*$", block.group(1), re.M | re.I)
    return found.group(1).strip() if found else ""


def remember_crash(config: AppConfig, *, kind: str, detail: str = "",
                   mods: list[str] | None = None, at: float | None = None) -> dict[str, Any]:
    """把"这次崩溃时跑的是哪套 Mod"记下来（只记崩溃，正常退出不记）。

    同一套组合只留最近一次 —— 否则反复崩会把列表刷满、把别的组合挤掉。
    另外记下**崩溃那一刻的 `NRStyle`**（用户 2026-10-02 要求：那种崩溃要能"记一下"，
    之后只在同一套 Mod 被勾选时才自动改回 0）。
    """
    import json

    stamp = float(at or time.time())
    entry = {
        "at": int(stamp),
        "at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp)),
        "kind": str(kind or "crash"),
        "detail": str(detail or "")[:400],
        "mods": sorted({str(m) for m in (staging_mods(config) if mods is None else mods)}),
        "nrstyle": _current_nrstyle(config),
    }
    entries = [e for e in read_crash_memory(config)
               if sorted(str(x) for x in (e.get("mods") or [])) != entry["mods"]]
    entries.insert(0, entry)
    entries = entries[:CRASH_MEMORY_LIMIT]
    path = crash_memory_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass
    return entry


def _same_combo(history: list[str], now: list[str]) -> bool:
    """历史那套 Mod 与现在这套算不算"同一套"：互为子集，且两边都至少 2 个。

    用子集而不是完全相等：用户常常只是多勾/少勾一个 —— 少一个照样会崩、
    多一个也逃不掉那对冲突，所以两个方向都算命中；单 Mod 的组合不参与
    （一个 Mod 自己崩通常是别的原因，提示了反而是噪音）。
    """
    a, b = {str(x) for x in history}, {str(x) for x in now}
    if len(a) < 2 or len(b) < 2:
        return False
    return a <= b or b <= a


# 公开别名：`initialize._check_dlss5_nrstyle` 要拿它判断"现在这套 Mod 崩过没有"
# （决定要不要动用户的 NRStyle，见那边的注释）。
same_combo = _same_combo


# 「这套组合这次**真的跑通了**」的判据（用户 2026-10-02 要求：成功启动没崩就从崩溃记忆里移出）。
#
# 两条任一满足即可，**共同前提都是"没有崩溃转储"**（`is_crash` 为假）：
#   ① `normal_exit`：Player.log 里有卸载统计 = 走了正常退出流程；
#   ② **存活 ≥ 120 秒**：很多人玩完直接 Alt+F4，Player.log 不会留下卸载统计，
#      但"跑满两分钟还没崩"已足够说明这套组合没问题 —— 实测里那些"必崩"的组合
#      （删了 `endif` 的 RabbitFX / 湿润效果修复、庄方宜旗袍）都是启动后几十秒内就崩。
# ⚠️ 不能拿"没检测到崩溃"直接当成功：「无卸载统计、无 uploadCrash」那档也可能是一次静默闪退。
COMBO_SUCCESS_ALIVE_SECONDS = 120


def combo_succeeded(evidence: dict[str, Any]) -> bool:
    """这次这套 Mod 到底有没有跑通（见上面两条判据）。"""
    if is_crash(evidence):
        return False
    if evidence.get("normal_exit"):
        return True
    try:
        alive = float((evidence.get("process") or {}).get("alive_seconds") or 0)
    except (TypeError, ValueError):
        return False
    return alive >= COMBO_SUCCESS_ALIVE_SECONDS


# ── 「连续启动失败」计数 → 界面弹「强力修复」（2026-10-05 用户要求）──────────────
# 用户原话：「**如果连续启动三次失败，加个弹窗，做个强力修复功能，一键还原终末地，
#            然后清空依赖并重新下载**，注意：**还原终末地需要把其他第三方的也还原掉**」。
#
# 判据刻意与 `combo_succeeded` **共用同一套**（`record_launch_result` 直接调它）：
# **崩了**、或**没活过 120 秒且没有正常退出卸载统计**（静默闪退）都算一次失败 ——
# 这样"启动即退"和"真崩溃"能累加到同一个计数里。这一条很关键：2026-10-05 那位反馈者
# 就是典型的"静默闪退"（每次活 20 秒、一条 WER 都没有），只数崩溃的话他永远等不到弹窗。
LAUNCH_FAILURE_NAME = Path("_state") / "launch_failures.json"
STRONG_REPAIR_THRESHOLD = 3
_LAUNCH_FAILURE_HISTORY = 10


def launch_failure_path(config: AppConfig) -> Path:
    return Path(config.runtime_path) / LAUNCH_FAILURE_NAME


def read_launch_failures(config: AppConfig) -> dict[str, Any]:
    """读计数（文件缺失/写坏一律当"没有记录" —— 绝不因为读不出来影响启动）。"""
    import json

    blank = {"streak": 0, "prompted_streak": 0, "history": []}
    path = launch_failure_path(config)
    if not path.is_file():
        return dict(blank)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(blank)
    if not isinstance(data, dict):
        return dict(blank)
    try:
        streak = int(data.get("streak") or 0)
        prompted = int(data.get("prompted_streak") or 0)
    except (TypeError, ValueError):
        streak, prompted = 0, 0
    return {
        "streak": max(0, streak),
        "prompted_streak": max(0, prompted),
        "history": list(data.get("history") or [])[-_LAUNCH_FAILURE_HISTORY:],
    }


def _write_launch_failures(config: AppConfig, state: dict[str, Any]) -> bool:
    import json

    path = launch_failure_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
        return True
    except OSError:
        return False


def record_launch_result(config: AppConfig, evidence: dict[str, Any], *,
                         log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """游戏退出后记一笔：**跑通就清零、失败就 +1**。

    ⚠️ 成功判据必须用 `combo_succeeded`，**不能**拿"没检测到崩溃"当成功 ——
    那一档也可能是静默闪退（本函数存在的理由就是这个）。
    """
    state = read_launch_failures(config)
    if combo_succeeded(evidence):
        if state["streak"]:
            _log(config, f"启动结果: 这次跑通了 → 连续失败计数清零（原为 {state['streak']} 次）")
        cleared = {"streak": 0, "prompted_streak": 0, "history": state["history"]}
        _write_launch_failures(config, cleared)
        return {**cleared, "ok": True, "failed": False}

    try:
        alive = int(float((evidence.get("process") or {}).get("alive_seconds") or 0))
    except (TypeError, ValueError):
        alive = 0
    streak = int(state.get("streak") or 0) + 1
    history = (list(state.get("history") or []) + [{
        "at": int(time.time()),
        "alive_seconds": alive,
        "crash": bool(is_crash(evidence)),
        "modules": [str(m) for m in (evidence.get("wer_modules") or [])][:3],
    }])[-_LAUNCH_FAILURE_HISTORY:]
    state = {"streak": streak, "prompted_streak": int(state.get("prompted_streak") or 0),
             "history": history}
    _write_launch_failures(config, state)
    _log(config, f"启动结果: 第 {streak} 次连续失败（存活 {alive} 秒）"
                 + ("—— 已达阈值，界面会提示「强力修复」" if streak >= STRONG_REPAIR_THRESHOLD else ""))
    return {**state, "ok": True, "failed": True}


def strong_repair_status(config: AppConfig) -> dict[str, Any]:
    """前端轮询用：连续失败够阈值、且**这一档还没提示过**时 `ready=True`。

    为什么要有 `prompted_streak`：这是防骚扰判据 —— 弹过一次之后同一档不再弹；
    等用户修好、计数清零，**再**攒到 3 次才会重新提示（而不是每次启动都弹）。
    """
    state = read_launch_failures(config)
    streak = int(state.get("streak") or 0)
    prompted = int(state.get("prompted_streak") or 0)
    return {
        "streak": streak,
        "threshold": STRONG_REPAIR_THRESHOLD,
        "ready": streak >= STRONG_REPAIR_THRESHOLD and streak > prompted,
        "prompted_streak": prompted,
        "history": state.get("history") or [],
    }


def mark_strong_repair_prompted(config: AppConfig) -> dict[str, Any]:
    """把"已提示过"钉在当前这一档上（前端弹窗后立刻调，保证只弹一次）。"""
    state = read_launch_failures(config)
    state["prompted_streak"] = int(state.get("streak") or 0)
    _write_launch_failures(config, state)
    return state


def reset_launch_failures(config: AppConfig) -> dict[str, Any]:
    """清零（"强力修复"成功后调：已经重头来过了，旧的失败计数不该继续压着用户）。"""
    cleared = {"streak": 0, "prompted_streak": 0,
               "history": (read_launch_failures(config).get("history") or [])}
    _write_launch_failures(config, cleared)
    return cleared


def forget_crashes_for_combo(config: AppConfig, mods: list[str] | None = None) -> list[dict[str, Any]]:
    """这套 Mod **这次成功跑通、没崩** ⇒ 把记忆里匹配它的条目移出（返回被移出的那些）。

    用户 2026-10-02 要求原话：「**如果某一组之前报崩溃的，后面终末地成功启动没崩就从记忆里移出**」。

    为什么必须要有：崩溃记忆的用途是"下次一键启动前提醒"，可一旦同一套组合后来真的跑通了，
    那条记忆就成了**噪音** —— 它会一直弹"这套组合以前崩过"，而那条记录反映的往往还是**旧版本**
    的行为（例如 0.9.2 之前那个把 shader 汇编 `endif` 删掉的 bug，害得 RabbitFX 被冤枉了一整天）。
    留着只会让人白紧张、还可能把人引去删 Mod。

    ⚠️ 调用方必须先用 `combo_succeeded(evidence)` 确认"确实成功"，别拿"没检测到崩溃"当成功。
    """
    import json

    current = sorted({str(m) for m in (staging_mods(config) if mods is None else mods)})
    entries = read_crash_memory(config)
    if not entries or len(current) < 2:      # 单 Mod 的组合不参与（与 `_same_combo` 同一口径）
        return []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for entry in entries:
        history = sorted(str(x) for x in (entry.get("mods") or []))
        if history and _same_combo(history, current):
            dropped.append(entry)
        else:
            kept.append(entry)
    if not dropped:
        return []
    path = crash_memory_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": kept}, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        return []
    return dropped


# 「这套组合已经**成功跑通过**」的台账（用户 2026-10-02 的两条要求，一体两面）：
#   ① 「**如果某一组之前报崩溃的，后面终末地成功启动没崩就从记忆里移出**」
#      → 清 `crash_memory.json` 里匹配的条目（见 `forget_crashes_for_combo`）；
#   ② 「**报了独享标识可能冲突的，只要能进，都记忆不再报**」
#      → 靠这个台账：**整套组合一起跑通过 ⇒ 这套里任何"独享标识相交"的静态推测都不再报到界面上**
#        （静态推测本来就只是"可能冲突"；用户实测能进，就等于把那一条否掉了）。
PROVEN_COMBOS_NAME = Path("_state") / "proven_combos.json"
PROVEN_COMBOS_LIMIT = 50


def proven_combos_path(config: AppConfig) -> Path:
    return Path(config.runtime_path) / PROVEN_COMBOS_NAME


def proven_combos(config: AppConfig) -> list[list[str]]:
    """已经成功跑通过的 Mod 组合（每条是一套 staged Mod 名，已排序去重）。"""
    import json

    try:
        data = json.loads(proven_combos_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    combos = data.get("combos") if isinstance(data, dict) else data
    out: list[list[str]] = []
    for item in combos or []:
        if isinstance(item, list) and item:
            out.append(sorted({str(x) for x in item}))
    return out


def record_proven_combo(config: AppConfig, mods: list[str] | None = None) -> list[str]:
    """这套组合跑通了 ⇒ 记进"已证实无害"台账（返回记下的那套名字）。"""
    import json

    current = sorted({str(m) for m in (staging_mods(config) if mods is None else mods)})
    if len(current) < 2:          # 单 Mod 不成"组合"（与 `_same_combo` 同一口径）
        return []
    combos = [c for c in proven_combos(config) if c != current]
    combos.insert(0, current)
    combos = combos[:PROVEN_COMBOS_LIMIT]
    path = proven_combos_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"combos": combos}, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        return []
    return current


def conflict_pair_proven(config: AppConfig, a: str, b: str) -> bool:
    """`a` 与 `b` 是否**同处某个已跑通过的组合**里。

    是 ⇒ 它们之间那条"独享标识相交"的静态推测已经被实测否掉，不该再报（用户原话：
    「报了独享标识可能冲突的，**只要能进，都记忆不再报**」）。
    """
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    for combo in proven_combos(config):
        if a in combo and b in combo:
            return True
    return False


# ---------------------------------------------------------------------------
# 崩溃后的**下一步建议**（只给建议，绝不擅自改用户的功能开关）
# ---------------------------------------------------------------------------
# 用户 2026-10-05 定调（先说"我需要能自动处理，不像就直接不加载"，随即纠正为）：
# 「**崩溃不要卸掉功能，应该弹窗建议清空依赖并重新下载重试**」。
# ⇒ 崩溃之后我们**不动任何插件开关**，只做两件事：
#   ① 把"这次崩在哪一层"用实测证据说清楚（WER 故障模块 / DLSS5 插件自己的 CRASH RECORDED）；
#   ② 判据指向"图形/注入链"时，在弹窗里给出**「清空依赖并重新下载」**这个现成动作
#      （`api.reset_dependencies_and_redownload`，设置页那个红按钮同一条路），由用户点。
# 为什么不自动关插件：那是**卸功能** —— 用户少了一样他本来要用的东西，而且多半治不到根因
# （组件配套坏了的时候，关掉插件游戏照样起不来，只是白白少了个功能）。
GRAPHICS_FAULT_MODULES = frozenset({
    "dxgi.dll", "d3d11.dll", "d3d12.dll", "d3d12core.dll", "d3dcompiler_47.dll",
    "vulkan-1.dll", "nvngx.dll", "nvngx_dlss.dll", "nvngx_dlssnr.dll",
    "nvngx_dlssd.dll", "nvngx_dlssg.dll", "nvngx_deepdvc.dll", "nvapi64.dll",
    "sl.interposer.dll", "sl.common.dll", "nvgpucomp64.dll",
})


def fault_modules(config: AppConfig, evidence: dict[str, Any]) -> list[str]:
    """这次崩溃的故障模块（小写 basename，去重）—— 只用实测证据，不猜。

    两个来源：① DLSS5 插件自己写在 `dlss5-feed.log` 里的 `### CRASH RECORDED ###`
    （它就在游戏进程里，记下了 faulting module）；② Windows 的 WER 报告
    （`Sig[3]` = 故障模块名称）。都没有就返回空 —— 空 ≠ 没崩，只是**没拿到是谁崩的**。
    """
    out: list[str] = []
    record = evidence.get("dlss5_crash")
    if not isinstance(record, dict):
        record = dlss5_crash_record(config, evidence.get("_started_at")) or {}
    module = str(record.get("module") or "").strip()
    if module:
        out.append(Path(module).name.lower())
    for name in (evidence.get("wer_modules") or []):
        name = Path(str(name)).name.lower()
        if name and name not in out:
            out.append(name)
    return out


def crash_advice(config: AppConfig, evidence: dict[str, Any]) -> dict[str, Any]:
    """崩溃后给用户的下一步建议（**空 dict = 这次给不出具体建议**）。

    只在"真崩了 + 崩在图形/注入链那层"时给：这两条都是实测判据，够格让人去重装组件；
    崩在游戏自己模块（unityplayer / GameAssembly）上时不建议重装依赖 —— 那是白折腾，
    老实让他把诊断包发出去。
    """
    if not is_crash(evidence):
        return {}
    hit = [m for m in fault_modules(config, evidence) if m in GRAPHICS_FAULT_MODULES]
    if not hit:
        return {}
    return {
        "kind": "rebuild_dependencies",
        "title": "建议：清空依赖并重新下载",
        "action": "reset_dependencies_and_redownload",
        "fault_modules": hit,
        "message": (
            "这次是崩在 **" + "、".join(hit) + "**（图形 / 注入链那一层），不是游戏自己的逻辑。\n\n"
            "这种情况最常见的原因是组件配套坏了、或者注入链被别的工具改过一遍。"
            "建议**清空依赖并重新下载**之后重试："
            "它会重装整套组件、重新展开随包资产，**你的 Mod 库、Mod 备份与路径设置都会保留**。"
        ),
    }


def prelaunch_risks(config: AppConfig) -> dict[str, Any]:
    """一键启动前的风险检查：这套 Mod 会不会崩（静态冲突 + 崩溃记忆）。

    两个数据来源都是**已经算好的事实**，不是猜：
      * 静态冲突 = 本次自检落盘的 `runtime\\_state\\mod_conflicts.json`（initialize 写）；
      * 崩溃记忆 = 过去真的崩过的 Mod 组合（`crash_memory.json`）。

    ⚠ 判据必须以**这次真的会被加载的那批 Mod** 为准（2026-10-01 修 bug）：
    用户手动删掉库里的文件后，界面上已经是"选中 0 个"，可那份冲突 json 还留着上一次的
    结论，于是启动时照样弹"崩溃风险"。所以这里两处收紧：
      ① 当前 staging 里一个 Mod 都没有 → 直接没有风险（没有任何东西会被加载）；
      ② 落盘结论**不是对着现在这批 staged Mod 算的** → 视为过期，不报。
    """
    from . import diagnostics

    mods = staging_mods(config)
    if not mods:
        return {
            "blocking": False,
            "conflicts": [],
            "groups": [],
            "memories": [],
            "mods": [],
            "checked_at": "",
            "note": "当前没有生效的 Mod（staging 为空），跳过冲突检查",
        }

    state = diagnostics.mod_conflict_state(config)
    fresh = state.get("ok") is False
    recorded_mods = state.get("mods")
    if fresh and isinstance(recorded_mods, list) and recorded_mods:
        if sorted(str(x) for x in recorded_mods) != sorted(mods):
            # 结论过期：那批 Mod 和现在这批不一样了（多半是库里的文件被删/换了）
            fresh = False
    conflicts = [str(x) for x in (state.get("conflicts") or [])] if fresh else []
    # 结构化冲突组（2026-10-01）：前端「选择要保留的 Mod」弹窗按"每组一个下拉框"渲染，
    # 选完调 `api.resolve_mod_conflicts()` 自动取消勾选其余的那些。
    groups = [g for g in (state.get("groups") or []) if isinstance(g, dict)] if fresh else []
    memories = [e for e in read_crash_memory(config)
                if _same_combo(list(e.get("mods") or []), mods)]
    return {
        "blocking": bool(conflicts or memories),
        # ⚠️ 别名（2026-10-04 修前后端不匹配）：前端 `LaunchPage.riskGate()` 读的是
        # `risks.risky` / `risks.crashed`，而后端给的是 `blocking` / `memories` ——
        # `!risks.risky` 恒为真 ⇒ **启动前风险弹窗一条都不再提示**（连同"以前崩过"
        # 的提示与那条自动撤回通道的用户可见效果一起失效）。
        # 按"以补齐为主"补别名，原字段保留（自检报告与测试都在用）。
        "risky": bool(conflicts or memories),
        "crashed": memories[:3],
        "conflicts": conflicts,
        "groups": groups,
        "memories": memories[:3],
        "mods": mods,
        "checked_at": str(state.get("at_text") or "") if fresh else "",
    }


def _normal_exit_marker() -> bool:
    """Player.log 尾部是否有 Unity 的正常退出统计。

    Unity 正常退出会写 `UnloadTime: ...` 与 `Total: ... ms (FindLiveObjects...)` 这类
    卸载统计；崩溃时日志会在栈回溯处戛然而止。用户反馈过"正常退出也弹异常弹窗"，
    这个判据用来区分「真的崩」和「正常退出」。
    """
    path = _endfield_local_low() / "Player.log"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # 必须**全量**扫描：卸载统计不一定在文件末尾。实测 458 行的 Player.log 里
    # `UnloadTime` 在第 40 行、`unused Assets...` 在第 44 行，而原先只取尾部 40 行
    # （419~458）正好把它们全漏掉 —— 这是个纯粹的下标 bug，已修。
    return ("UnloadTime" in text) or ("unused Assets to reduce memory usage" in text)


def _crash_sight_lines(config: AppConfig, since: float | None = None, limit: int = 4) -> list[str]:
    """最近的 CrashSight 记录。

    `since`（游戏启动时间）用于**只统计本次运行期间**产生的记录 —— 否则历史崩溃
    记录会被算到本次头上，导致"正常退出也报异常"。
    """
    game_dir = None
    from . import reshade_integration

    game_dir = reshade_integration.detect_game_dir(config)
    if game_dir is None:
        return []
    root = game_dir / "CrashSightLog"
    if not root.is_dir():
        return []
    files = sorted(root.glob("CrashSight.*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[str] = []
    for path in files:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if since is not None and mtime < since:
            continue          # 本次游戏启动之前的记录，不算
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        interesting = [ln.strip() for ln in text.splitlines()
                       if "reportException" in ln or "uploadCrash" in ln or "Begin get access info" in ln]
        if interesting:
            out.append(f"{path.name}: " + " | ".join(interesting[:6]))
        if len(out) >= limit:
            break
    return out


def _crash_sight_upload_lines(config: AppConfig, since: float | None = None) -> list[str]:
    """本次运行期间真正**上传了崩溃转储**（`uploadCrash`）的 CrashSight 记录。

    这是「游戏到底崩没崩」的可靠判据（2026-09-27 实测确立）：

      * `reportException` —— 上报**被游戏捕获的异常**。终末地自己会反复打
        `[Error] [Scope] Failed to fallback to main scope : [ItemBag] Main`，
        CrashSight 把这些并不致命的异常一并上报，所以**每次运行都会出现**；
        拿它当崩溃信号，就会得出"每次正常退出都是异常退出"。
      * `uploadCrash` —— 真正**上传崩溃转储**，只有进程真的崩了才会有。

    实测对照（同一天同一个游戏）：
        真崩溃 18:13 / 18:16 → reportException ×6 **且** 有 uploadCrash；
        用户自己关窗口 18:21 / 18:25 → 只有 reportException，**没有** uploadCrash。
    """
    from . import reshade_integration

    game_dir = reshade_integration.detect_game_dir(config)
    if game_dir is None:
        return []
    root = game_dir / "CrashSightLog"
    if not root.is_dir():
        return []
    out: list[str] = []
    for path in sorted(root.glob("CrashSight.*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            if since is not None and path.stat().st_mtime < since:
                continue      # 本次游戏启动之前的上传，不算
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = [ln.strip() for ln in text.splitlines() if "uploadCrash" in ln]
        if hits:
            out.append(f"{path.name}: " + " | ".join(hits[:3]))
    return out


def _player_log_crash_section(crash_dir: Path, context: int = 28) -> dict[str, Any]:
    """从崩溃报告的 Player.log 里提取 Crash!!! 前后段落与第三方模块。"""
    player = crash_dir / "Player.log"
    if not player.is_file():
        return {}
    try:
        lines = player.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    idx = next((i for i, ln in enumerate(lines) if "Crash!!!" in ln), None)
    result: dict[str, Any] = {"report_dir": str(crash_dir), "lines": len(lines)}
    if idx is not None:
        start = max(0, idx - context)
        result["before"] = [ln.strip() for ln in lines[start:idx] if ln.strip()]
        result["at"] = idx
    tail = [ln.strip() for ln in lines if _THIRD_PARTY_HINT.search(ln) and ".dll" in ln]
    seen: list[str] = []
    for line in tail[-24:]:
        if line not in seen:
            seen.append(line)
    result["modules"] = seen
    return result


_GAME_ERR_RE = re.compile(r"^\s*\[(Error|Exception|Warning)\]\s*(.*)$", re.I)


def _error_signature(text: str) -> str:
    """把错误行归一化成签名（抹掉时间戳/tid/微秒/数字），用于同类聚合。"""
    s = re.sub(
        r"\[\d{2}-\d{2}-\d{2}\]"      # [16-59-28]
        r"|\[tid:\d+\]"               # [tid:43844]
        r"|\[[0-9a-z:]*us\]"          # [0s:008ms:096us]
        r"|\b\d+\b",                  # 其它数字
        "#", text,
    )
    return s[:140]


def _extract_game_errors(config: AppConfig, limit: int = 20) -> list[str]:
    """从终末地 Player.log 里挑出它自己的 [Error]/[Exception] 行。

    这类行通常埋在十几万行日志里（例如
    `[Error] [Scope] [F:418][DLog]Failed to fallback to main scope : [ItemBag] Main`）。
    处理方式：① 按签名聚合同类（Streamline 那种会刷上百条）；② **按最后一次出现的位置
    降序排列** —— 越接近崩溃时刻的错误越可能是原因。
    """
    path = _endfield_local_low() / "Player.log"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    stats: dict[str, dict[str, Any]] = {}
    for idx, line in enumerate(lines):
        m = _GAME_ERR_RE.match(line)
        if not m:
            continue
        text = line.strip()[:200]
        sig = _error_signature(text)
        entry = stats.setdefault(sig, {"text": text, "count": 0, "first": idx + 1, "last": idx + 1})
        entry["count"] += 1
        entry["last"] = idx + 1
    ordered = sorted(stats.values(), key=lambda e: e["last"], reverse=True)[:limit]
    out: list[str] = []
    for e in ordered:
        times = f"（×{e['count']}，行{e['first']}~{e['last']}）" if e["count"] > 1 else f"（行{e['first']}）"
        out.append(f"{e['text']} {times}")
    return out


def collect_evidence(config: AppConfig, *, started_at: float | None = None,
                     exit_time: float | None = None,
                     alive_seconds: float | None = None) -> dict[str, Any]:
    """收集一次完整的崩溃现场。"""
    # WER 故障模块要取两次（`wer_crash` 判"崩没崩"、`wer_modules` 给归因/自动降级用），
    # 算一次共享（读的是同一批文件，别重复 IO）。
    wer_modules = wer_crash_modules(started_at)
    evidence: dict[str, Any] = {
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "process": {"name": GAME_PROCESS, "started_at": None, "exit_time": None, "alive_seconds": alive_seconds},
        "injections": injection_snapshot(config),
        "xxmi_inject": _xxmi_inject_lines(config),
        "crash_sight": _crash_sight_lines(config, since=started_at),
        "crash_upload": _crash_sight_upload_lines(config, since=started_at),
        "normal_exit": _normal_exit_marker(),
        # 两张"是谁崩的"硬证据（2026-10-05 加）：DLSS5 插件自己写的崩溃记录，
        # 以及 Windows 的 WER 报告。`is_crash` 与"注入链自动降级"都要用。
        "dlss5_crash": dlss5_crash_record(config, started_at),
        "wer_modules": wer_modules,
        "wer_crash": bool(wer_modules),
        "crashes": [],
        "player_log_tail": [],
        "game_errors": _extract_game_errors(config),
    }
    evidence["_started_at"] = started_at
    evidence["cause"] = classify_cause(config, evidence, started_at=started_at)
    if started_at:
        evidence["process"]["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at))
    if exit_time:
        evidence["process"]["exit_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exit_time))

    root = _crash_root()
    if root.is_dir():
        dirs = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)[:2]
        for d in dirs:
            section = _player_log_crash_section(d)
            if section:
                evidence["crashes"].append(section)

    # 运行时采样时间线（每 5 秒一次）—— "跑几十秒就闪退"最需要的证据
    try:
        from . import watchsample

        evidence["watch_samples"] = watchsample.read_all(config)
    except Exception:  # noqa: BLE001
        evidence["watch_samples"] = []

    # 注入现场时间线（五个时机各一张照片）—— 2026-10-05 用户要求：
    # 「在一键启动最开始和 xxmi 拉起后和终末地启动后和终末地关闭和崩溃后都要收注入列表」。
    # 与上面那条的分工：那条只有**进程层**（每 5 秒的模块/内存/句柄），这条多了
    # **配置层**（注入库逐条内容 + 游戏目录注入物 + `runtime\dlss5` 文件状态），
    # 而且**贴着关键时刻**。两条一起看，才能回答"注入库是何时被改的、
    # 进程里到底进了哪几个 DLL"。
    try:
        from . import injecttrace

        evidence["injection_trace"] = injecttrace.read_all(config)
    except Exception:  # noqa: BLE001
        evidence["injection_trace"] = []

    low = _endfield_local_low() / "Player.log"
    if low.is_file():
        try:
            evidence["player_log_tail"] = [ln.strip() for ln in low.read_text(encoding="utf-8", errors="replace").splitlines()[-15:] if ln.strip()]
        except OSError:
            pass
    return evidence


# ---------------------------------------------------------------------------
# 写日志
# ---------------------------------------------------------------------------
def write_report(config: AppConfig, evidence: dict[str, Any]) -> Path:
    logs = config.runtime_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"crash-{time.strftime('%Y%m%d-%H%M%S')}.log"
    path.write_text(_render_report(evidence), encoding="utf-8")
    _log(config, f"已写出崩溃/退出报告: {path.name}")
    return path


# ---------------------------------------------------------------------------
# 崩溃包：把终末地自己的日志也拉进来，整包打成 zip
# ---------------------------------------------------------------------------
BUNDLE_DIR_NAME = "bundles"


def bundles_root(config: AppConfig) -> Path:
    return config.runtime_path / "logs" / BUNDLE_DIR_NAME


def collect_game_logs(config: AppConfig, dest: Path) -> list[str]:
    """把**终末地自己的日志**复制到 dest（Player.log / CrashSight / 崩溃转储）。"""
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    low = _endfield_local_low()
    for name in ("Player.log", "Player-prev.log"):
        src = low / name
        if src.is_file():
            try:
                shutil.copy2(src, dest / f"Endfield-{name}")
                copied.append(f"Endfield-{name}")
            except OSError:
                pass
    # Hypergryph 启动器/游戏日志（体积大，只取最近一个的尾部）
    for extra in (low.parent / "33a0a6296a20400d503c59ac0fd6341e" / "logs" / "games.log",):
        if extra.is_file():
            try:
                lines = extra.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
                (dest / "launcher-games-tail.log").write_text("\n".join(lines), encoding="utf-8")
                copied.append("launcher-games-tail.log")
            except OSError:
                pass
    from . import reshade_integration

    game_dir = reshade_integration.detect_game_dir(config)
    if game_dir is not None:
        cs = game_dir / "CrashSightLog"
        if cs.is_dir():
            files = sorted(cs.glob("CrashSight.*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]
            for f in files:
                try:
                    shutil.copy2(f, dest / f"CrashSight-{f.name}")
                    copied.append(f"CrashSight-{f.name}")
                except OSError:
                    pass
    root = _crash_root()
    if root.is_dir():
        dirs = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)[:2]
        for d in dirs:
            target = dest / f"Endfield-{d.name}"
            try:
                shutil.copytree(d, target, dirs_exist_ok=True)
                copied.append(f"Endfield-{d.name}/")
            except OSError:
                pass
    return copied


def _environment_text(config: AppConfig) -> str:
    import platform
    import sys

    lines = [
        f"生成时间   : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"程序       : EndfieldModController",
        f"Python     : {sys.version.split()[0]} / {platform.platform()}",
    ]
    # 设备型号 / 显卡与驱动（用户 2026-10-01 要求：日志包里要带上，好一眼判断
    # "DLSS5 出不来"到底是机器不支持还是我们配错了）。读注册表，毫秒级、无子进程。
    try:
        from . import deviceinfo

        lines.extend(line for line in deviceinfo.summary_lines() if line)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"设备信息读取失败: {exc}")
    try:
        from . import updates

        versions = updates.component_versions(config)
        for key, info in versions.items():
            lines.append(f"组件 {key:<16}: {info.get('version')}  {info.get('path')}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"组件版本读取失败: {exc}")
    try:
        snap = injection_snapshot(config)
        lines.append(f"游戏目录   : {snap.get('game_dir')}")
        for name, size in (snap.get("files") or {}).items():
            lines.append(f"  {name:<22} {size} B")
        lines.append("XXMI 注入库:")
        for line in (snap.get("extra_libraries") or "").split("\n"):
            lines.append(f"  {line}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"注入快照失败: {exc}")
    return "\n".join(lines) + "\n"


def _collect_extra_evidence(config: AppConfig, bundle_dir: Path) -> None:
    """崩溃包里那几样"以前总是缺"的判据（2026-10-04 加，用户要求"尽量多塞东西"）。

    * **`ReShade.log` 多候选** —— 它按 `RESHADE_BASE_PATH_OVERRIDE` 落在
      `runtime\\reshade\\`，原来只从 `dlss5_path` 取 ⇒ 反馈者的包里整份丢失
      （issue #13 缺陷三）。这是判断"游戏是自己退出还是被外部结束"的一手材料：
      最后一段是 `Unregistered add-on …` = 走到了正常卸载。
    * **EFMI / 3DMigoto 两侧的 `d3d11_log.txt`** —— 判断"控制器铺的 Mod 到底进没进游戏"。
    * **`game-inventory.txt`** —— proxy 归属 / 原版备份在不在 / plugin 清单。
    * **WER 报告** —— 有记录 = 真崩溃；没有 = 多半是被外部结束（两者归因相反）。
    """
    from . import diagnostics

    def _copy(src: Path, arcname: str, *, limit: int = 32 * 1024 * 1024) -> None:
        try:
            if not src.is_file() or src.stat().st_size > limit:
                return
            dest = bundle_dir / arcname
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        except OSError:
            return

    for label, source in diagnostics.reshade_log_candidates(config, None):
        _copy(source, f"ReShade-{label}.log")
    for label, source in diagnostics.efmi_log_candidates(config):
        if source.is_file():
            _copy(source, f"loader/{label}-{source.name}")
    try:
        (bundle_dir / "game-inventory.txt").write_text(
            diagnostics.game_dir_inventory_text(config, diagnostics_game_dir(config)), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    for path in diagnostics.wer_report_paths():
        _copy(path, f"wer/{path.parent.name}-{path.name}", limit=4 * 1024 * 1024)


def diagnostics_game_dir(config: AppConfig) -> Path | None:
    """游戏目录（崩溃包要用；失败返回 None，不抛异常）。"""
    try:
        from . import reshade_integration

        return reshade_integration.detect_game_dir(config)
    except Exception:  # noqa: BLE001
        return None


def _collect_full_game_logs(config: AppConfig, bundle_dir: Path) -> None:
    """**完整的** `Player.log`（含 `-prev`）—— 不再只取尾部 15 行。

    "跑四十多秒就闪退"的关键信息在**退出前最后几十行**，而此前的包只收尾部，
    且夹在报告正文里；现在整份收进来。
    """
    low = _endfield_local_low()
    for name in ("Player.log", "Player-prev.log"):
        src = low / name
        if src.is_file() and src.stat().st_size <= 32 * 1024 * 1024:
            try:
                shutil.copy2(src, bundle_dir / f"Endfield-{name}")
            except OSError:
                pass


def _collect_crash_dumps(config: AppConfig, bundle_dir: Path) -> int:
    """官方崩溃转储目录 `Crashes/Crash_*`（含 crash.dmp / error.log / output_log.txt）。

    这是判断"到底崩没崩、崩在哪个模块"的一手材料；此前完全没进包。
    """
    root = _crash_root()
    if not root.is_dir():
        return 0
    taken = 0
    try:
        dirs = sorted((d for d in root.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime, reverse=True)[:3]
    except OSError:
        return 0
    for d in dirs:
        dest = bundle_dir / "official-crash" / d.name
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for src in sorted(d.rglob("*")):
            if not src.is_file():
                continue
            try:
                if src.stat().st_size > 64 * 1024 * 1024:   # 单个 dmp 一般几十 MB，过大的跳过
                    continue
                shutil.copy2(src, dest / src.name)
                taken += 1
            except OSError:
                continue
    return taken


def _collect_game_config(config: AppConfig, bundle_dir: Path) -> None:
    """EFMI 侧的配置与 Mod 清单 —— 判断"按键/Mod 状态"必须的两份文件。"""
    try:
        from .config import auto_detect_migoto_loader  # 延迟导入避免循环依赖
        loader = auto_detect_migoto_loader()
        if loader:
            root = Path(loader)
            for name in ("d3dx.ini", "d3dx_user.ini"):
                src = root / name
                if src.is_file() and src.stat().st_size <= 8 * 1024 * 1024:
                    shutil.copy2(src, bundle_dir / f"efmi-{name}")
            mods = root / "Mods"
            if mods.is_dir():
                listing = []
                for item in sorted(mods.iterdir()):
                    try:
                        kind = "dir" if item.is_dir() else f"{item.stat().st_size} B"
                    except OSError:
                        kind = "?"
                    listing.append(f"{item.name}\t{kind}")
                (bundle_dir / "efmi-mods-listing.txt").write_text(
                    "EFMI Mods 目录清单\n" + "\n".join(listing) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _collect_injection_files(config: AppConfig, bundle_dir: Path) -> None:
    """收**注入链上的文件本体**（2026-10-05 用户批准：「加一下」）。

    收三样，都是"光有哈希查不了、必须有本体"的东西：

    * **`ReShade.ini` 正文**（2 KB 级）—— 诊断包以前只收它的哈希，于是**看不到里面写了什么**。
      而 DLSS5 / 第一人称的钩子开关、`[RenoDX.DLSS5]` 段（含已知会破坏第一人称相机 hook 的
      `NeuralUplift`）全在那里面。实测反馈者那份只有 **2,259 B**、开发机是 **6,708 B**，
      差三倍却无从比对 —— 2 KB 的东西收不到纯亏。两份都收：部署源 + **生效那份**
      （`RESHADE_BASE_PATH_OVERRIDE` 指向 `runtime\\reshade`）。
    * **游戏目录里的 proxy 本体**（`d3dcompiler_47.dll` / `vulkan-1.dll` / `plugin\\*.dll`）：
      各几十 KB。反馈者那份 `d3dcompiler_47.dll` 是 **35,840 B**，开发机是 **14,336 B**，
      **不是同一个版本** —— 只有拿到本体，才能对他的文件跑依赖检查（`pedeps`）。
    """
    # ① 两份 ReShade.ini 的正文
    try:
        candidates: list[tuple[str, Path]] = [("dlss5", Path(config.dlss5_path) / "ReShade.ini")]
        runtime_ini = Path(config.reshade_runtime_path) / "ReShade.ini"
        candidates.append(("effective", runtime_ini))
        for tag, src in candidates:
            if src.is_file() and src.stat().st_size <= 2 * 1024 * 1024:
                shutil.copy2(src, bundle_dir / f"reshade-{tag}-ReShade.ini")
    except Exception:  # noqa: BLE001
        pass
    # ② 游戏目录里的 proxy 本体（含 plugin\ 下的 DLL）
    try:
        from . import reshade_integration

        game_dir = reshade_integration.detect_game_dir(config, prefer_actual=True)
        if game_dir is not None:
            for name in reshade_integration.LOADER_PROXY_MODULES:
                src = game_dir / name
                try:
                    if src.is_file() and src.stat().st_size <= 8 * 1024 * 1024:
                        shutil.copy2(src, bundle_dir / f"game-{name}")
                except OSError:
                    continue
            plugin_dir = game_dir / reshade_integration.PLUGIN_DIR_NAME
            if plugin_dir.is_dir():
                for item in sorted(plugin_dir.glob("*.dll")):
                    try:
                        if item.is_file() and item.stat().st_size <= 32 * 1024 * 1024:
                            shutil.copy2(item, bundle_dir / f"game-plugin-{item.name}")
                    except OSError:
                        continue
    except Exception:  # noqa: BLE001
        pass


def collect_diagnosis_files(config: AppConfig, dest: Path, *,
                            log: Callable[[str], None] | None = None) -> list[str]:
    """把**排查真正要用到的那些文件**一次性收进包里。

    用户 2026-10-05 要求：「**你自己怎么查的，就把那些文件全收进日志包**」。

    所以这一批不是拍脑袋列的 —— 它们是这次定位「`0xC0000135` / NR 不自动开 / 资产展开失败」
    时**实际打开过的**那份清单：ReShade 生效日志（判 `Camera controls installed.` 有没有出现
    全靠它）、面板 addon 日志、feed 日志、运行库变体 marker、游戏自己的 `Player.log`、
    XXMI 配置与日志、**各 addon 的身份（名 + 大小 + sha256）**、随包资产清单 ……

    以前它们里有些**只收了一半**（addon 只有清单没有身份、变体 marker 完全没收、
    `ReShade.ini` 只有哈希没有正文）⇒ 每次排查都要回头再要一轮，与用户定的
    「日志包一次抓齐所有数据，不要搞好几轮」冲突。现在统一收齐。

    返回收进去的相对名（便于在报告里逐条列出来）。
    """
    emit: Callable[[str], None] = log or (lambda message: None)
    taken: list[str] = []

    def take(src: Path | None, arcname: str, *, limit: int = 8 * 1024 * 1024) -> None:
        """收一个文件（超限/读不到就安静跳过 —— 取证不能反噬打包）。

        ⚠️ **arcname 可以是子目录**（例如 `logs/launch.log`）⇒ 必须先建父目录：
        否则 `shutil.copy2` 抛 `FileNotFoundError`（属 `OSError`）被这里静默吞掉
        ⇒ **整批文件一个都进不了包**（2026-10-07 实测栽在这：291 份日志全丢，而日志里
        没有任何提示 —— 因为"安静跳过"是故意的）。静默失败的前提是"目标父目录一定在"，
        这一点以前不成立。
        """
        if src is None:
            return
        try:
            if not src.is_file() or src.stat().st_size > limit:
                return
            target = dest / arcname
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            taken.append(arcname)
        except OSError:
            return

    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        emit(f"排查素材: 建目录失败 {exc}")
        return taken

    reshade = Path(config.reshade_runtime_path)
    dlss5 = Path(config.dlss5_path)

    # ① ReShade 那一侧（**生效那份**的日志与 ini、面板 addon 日志、按键表）
    take(reshade / "ReShade.log", "reshade-effective-ReShade.log")
    take(reshade / "ReShade.ini", "reshade-effective-ReShade.ini")
    take(reshade / "modecontroller.addon.log", "reshade-modecontroller.addon.log")
    take(reshade / "actions.tsv", "reshade-actions.tsv")
    take(reshade / "user_ini_path.txt", "reshade-user_ini_path.txt")
    for extra in ("renodx-dlss5.log", "dlss5.log", "ReShade.log.old"):
        take(reshade / extra, f"reshade-{extra}")

    # ② DLSS5 那一侧（部署源的 ini、feed 的日志与配置、**运行库变体 marker**）
    take(dlss5 / "ReShade.ini", "dlss5-ReShade.ini")
    take(dlss5 / "ReShade.log", "dlss5-ReShade.log")
    take(dlss5 / "dlss5-feed.log", "dlss5-feed.log")
    take(dlss5 / "dlss5-feed.cfg", "dlss5-feed.cfg")
    take(dlss5 / ".dlssnr_variant.json", "dlss5-variant.json")
    take(dlss5 / "panel_info.txt", "dlss5-panel_info.txt")

    # ★★★ 2026-10-07 补采（用户定的规矩：「**你查过啥，啥就要加进诊断包，没加的你不允许看**」）：
    #     排查「DLSS5 不出帧」时我实际看的就是下面这三样，而它们**当时都不在包里** ——
    #     我只能去读本机文件，那等于绕开诊断包、对反馈者的机器完全无效。
    # ① preset 本体：technique 的**全名与启用状态**都写在它里面。
    #    `dlss5-ReShade.ini` 只给 `PresetPath`（一个路径），`dlss5-ReShade.log` 只给
    #    "认没认出来"的后果 —— **判据本身在这份文件里**，缺了它就没法定案。
    take(dlss5 / "ReShadePreset.ini", "dlss5-ReShadePreset.ini")
    # ② addon 的**位置**（根目录 vs `_disabled\`）：上面 `dlss5-addons.txt` 只列根目录，
    #    于是"那个插件是被停用了、还是根本没铺进来"分不清 —— 两边各有一份时结论正好相反。
    try:
        rows = ["dlss5 里的 addon 位置（根目录 = 启用中；_disabled = 已停用）"]
        for item in sorted(dlss5.glob("*.addon64")):
            try:
                rows.append(f"根目录\t{item.name}\t{item.stat().st_size} B")
            except OSError:
                rows.append(f"根目录\t{item.name}\t(读不到)")
        disabled_dir = dlss5 / "_disabled"     # 与 `launcher.ADDON_DISABLED_DIR` 同一个名字
        if disabled_dir.is_dir():
            for item in sorted(disabled_dir.glob("*")):
                try:
                    rows.append(f"_disabled\t{item.name}\t{item.stat().st_size} B")
                except OSError:
                    rows.append(f"_disabled\t{item.name}\t(读不到)")
        else:
            rows.append("_disabled\t（目录不存在）")
        (dest / "dlss5-addon-placement.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        taken.append("dlss5-addon-placement.txt")
    except Exception as exc:  # noqa: BLE001 —— 采集失败绝不影响诊断包生成
        emit(f"排查素材: addon 位置清单失败（忽略）: {exc}")
    # ③ shader 的**相对路径清单**：ReShade 的 technique 全名是
    #    `<Technique>@<effect 相对路径>` ⇒ "`MartysMods_LAUNCHPAD.fx` 在根目录还是 `iMMERSE\` 下"
    #    直接决定全名对不对。这正是 2026-10-07 那台 `provider is installed but DISABLED`
    #    的根因，而它**推不出来** —— 已收的任何一份文件里都没有这个信息。
    try:
        shaders_root = dlss5 / "reshade-shaders" / "Shaders"
        rows = [f"shaders 根目录: {shaders_root}"]
        if shaders_root.is_dir():
            for item in sorted(shaders_root.rglob("*.fx")):
                try:
                    rows.append(item.relative_to(shaders_root).as_posix())
                except ValueError:
                    rows.append(item.name)
        else:
            rows.append("（目录不存在）")
        (dest / "dlss5-shaders-tree.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        taken.append("dlss5-shaders-tree.txt")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: shader 清单失败（忽略）: {exc}")

    # ③ 各 addon 的**身份**（只收清单：名 + 字节 + sha256 前 16 —— 判"对方用的是不是我们随包那份"
    #    靠它；4 MB 的本体不收，包会太大）
    try:
        from . import runtime_assets

        rows = ["runtime\\dlss5 里的 addon（名 / 字节 / sha256 前 16）"]
        for item in sorted(dlss5.glob("*.addon64")):
            try:
                rows.append(f"{item.name}\t{item.stat().st_size} B\t{runtime_assets.sha256_file(item)[:16]}")
            except OSError:
                rows.append(f"{item.name}\t(读不到)")
        (dest / "dlss5-addons.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        taken.append("dlss5-addons.txt")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: addon 清单失败（忽略）: {exc}")

    # ④ 游戏自己的日志（判"走到哪一步"必看）
    #    ⚠️ **厂商目录不能写死**（2026-10-07 修）：国服 `Hypergryph`、国际服/其它渠道
    #    `Gryphline` —— 原来只试 `Hypergryph`，国际服那台一条都收不到。
    try:
        home = Path(os.environ.get("USERPROFILE") or "")
        if home.is_dir():
            for vendor in ("Hypergryph", "Gryphline"):
                for sub in ("Endfield", "Arknights Endfield"):
                    base = home / "AppData" / "LocalLow" / vendor / sub
                    take(base / "Player.log", "player-Player.log")
                    # ⚠️ 上一份也要（崩溃那次常常只剩 prev 是完整的）
                    take(base / "Player-prev.log", "player-Player-prev.log")
    except Exception:  # noqa: BLE001
        pass

    # ④b ★★★ **游戏自己的崩溃报告**（2026-10-07 补 —— 这是 issue16 一直查不动的根因）
    #
    #     游戏崩溃时会把**带完整堆栈**的日志写到这里：
    #       `%TEMP%\Hypergryph\Endfield\Crashes\Player.log`（几十~一百多 KB，含 `OUTPUTTING STACK TRACE`）
    #       `%TEMP%\Hypergryph\Endfield\Crashes\crash.dmp`（1.5~2 MB 的 minidump）
    #     **我们从来没收集过这个目录** ⇒ 每次拿到手的都只是 `LocalLow` 那份**被截断**的日志
    #     （实测：反馈者的只有 48 行、止于 `MemoryPool::MMapMemoryBlock count:0`，
    #       而崩溃原因恰恰在堆栈里）。
    #     ⚠️ 用户定的规矩是「**第一轮排查只允许看收进日志包的**」⇒ 日志必须全收，
    #        只有真正的大二进制才节选 ⇒ 这里 `Player.log` **全收**，`crash.dmp` **只记存在与大小**
    #        （2 MB 的 dump 收进去会让包变大，而堆栈已经在 `Player.log` 里了）。
    try:
        import glob as _glob

        from . import fsutil

        # ⚠️ 厂商段同样**不能写死**（2026-10-07）：国际服的崩溃报告在 `Gryphline` 下，
        #    只扫 `Hypergryph` 会让那台永远收不到游戏自己的崩溃堆栈。
        _temp = Path(os.environ.get("TEMP") or tempfile.gettempdir())
        crashes = _temp / fsutil.ENDFIELD_VENDORS[0] / "Endfield" / "Crashes"
        _found: list[Path] = []
        for _vendor in fsutil.ENDFIELD_VENDORS:
            _dir = _temp / _vendor / "Endfield" / "Crashes"
            if _dir.is_dir():
                if not _found:
                    crashes = _dir
                _found.extend(p for p in _dir.rglob("Player.log") if p.is_file())
        if _found:
            reports = sorted(_found, key=lambda p: p.stat().st_mtime, reverse=True)
            for index, report in enumerate(reports[:3]):          # 只取最近 3 次
                take(report, f"game-crash-{index + 1}-Player.log")
            rows = ["# 游戏崩溃报告目录（%TEMP%\\Hypergryph\\Endfield\\Crashes）",
                    "# crash.dmp 是 minidump（MB 级二进制，**不随包分发**，此处只记存在与大小）", ""]
            for item in sorted(crashes.rglob("*")):
                if item.is_file():
                    rows.append(f"{item.stat().st_size:>12,} B  {item.stat().st_mtime:.0f}  "
                                f"{item.relative_to(crashes)}")
            (dest / "game-crash-reports.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
            taken.append("game-crash-reports.txt")
            emit(f"排查素材: 游戏崩溃报告目录收到 {min(len(reports), 3)} 份 Player.log")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: 游戏崩溃报告目录失败（忽略）: {exc}")

    # ④c ★ **我们自己的日志全量收**（`launch.log` 与逐次会话日志 —— 判"走到哪一步"的第一手材料）
    #
    #   ⚠️ 以前只零散收 ReShade / addon 那几份，**主日志 `launch.log` 根本没进包** ——
    #      而"一键启动卡在哪一步、注入库写成什么、清理搬走了什么"全在里面。
    #      实测排查 issue16 时要靠用户截图才看到它。
    #   体积：单份几十 KB ~ 几 MB；**日志全收**（用户 2026-10-05：「你自己怎么查的，就把那些文件全收进日志包」）。
    try:
        rt = Path(config.runtime_path)
        # ⚠️ `launch.log` 在 **runtime 根**（不在 `logs\` 里）—— 实测漏过一次
        roots = [rt, rt / "logs"]
        budget = 64 * 1024 * 1024          # 日志总量上限，正常情况远用不到
        used = 0
        patterns = ("launch.log", "endfieldmodcontroller-*.log", "windows-events-*.log",
                    "loader_debug*.log", "d3d11_log*.txt", "ReShade-*.log", "*.dmp.txt")
        collected: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            for pattern in patterns:
                collected.extend(p for p in root.glob(pattern) if p.is_file())
        # 最新的优先（排查看的就是最近那次）
        collected.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for item in collected:
            size = item.stat().st_size
            if used + size > budget:
                continue
            take(item, f"logs/{item.name}")
            used += size
        if collected:
            emit(f"排查素材: 运行时日志收到 {sum(1 for t in taken if t.startswith('logs/'))} 份"
                 f"（约 {used / 1048576:.1f} MB）")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: 运行时日志收集失败（忽略）: {exc}")

    # ⑤ XXMI 那一侧（配置 + 它自己的日志）
    try:
        from . import reshade_integration

        launcher_path = config.xxmi_launcher_path
        if launcher_path:
            take(reshade_integration.xxmi_config_path(launcher_path), "xxmi-Launcher-Config.json")
            take(Path(launcher_path).parent.parent.parent / "XXMI Launcher Log.txt",
                 "xxmi-Launcher-Log.txt")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: XXMI 侧失败（忽略）: {exc}")

    # ⑥ 随包资产清单（每个组一份 manifest.json —— 判"资产齐不齐、分卷对不对"全靠它）
    try:
        from . import runtime_assets

        seen: set[str] = set()
        for _group, root, _name, _entry in runtime_assets.manifest_entries(config):
            key = f"assets-{Path(root).name}-manifest.json"
            if key in seen:
                continue
            seen.add(key)
            take(Path(root) / "manifest.json", key, limit=1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: 资产清单失败（忽略）: {exc}")

    # ⑦ 游戏目录里的 proxy 本体（依赖检查要用本体，光有哈希查不了）
    _collect_injection_files(config, dest)

    # ⑧ **大日志的关键行摘录**（用户 2026-10-05 定的规矩：「**特别大文件可以节选你要的**」）。
    #    `ReShade.log` 动辄几十上百 KB，而排查真正要看的就那么几类行 ——
    #    相机 hook 装没装、NR 有没有建帧、addon 注册了哪些、有没有 hook 失败与报错。
    #    全量那份照收（超限时 `_safe_zip_write` 会截尾并注明），这里再给一份"只看这几类"的，
    #    让**第一轮排查不必再回头要文件**（这正是这条纪律的目的）。
    try:
        src = reshade / "ReShade.log"
        if src.is_file():
            keys = ("Camera controls installed", "camera hook installation failed",
                    "feature 18 created", "evaluation succeeded", "Registered add-on",
                    "Loading add-on", "installing delayed hooks", "hotkeys:", "| ERROR | ",
                    # 2026-10-06 加：NR「建了特征却一帧不出」的现场就在这三行里 ——
                    # 以前它们**不在采集范围内**，于是"池耗尽"这条关键判据只能在
                    # 我这边翻全量 ReShade.log 才看得到（第一轮排查又得回头要文件）。
                    "workset pool exhausted",
                    "NR workset completion fence could not be signaled",
                    "failed to install native D3D12 queue submission tracker")
            picked: list[str] = []
            with src.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if any(key in line for key in keys):
                        picked.append(line.rstrip("\n"))
            (dest / "reshade-keylines.txt").write_text(
                "ReShade.log 关键行摘录（相机 hook / NR 建帧 / addon 注册 / hook 失败 / 报错）\n"
                f"源: {src}（{src.stat().st_size:,} B）· 共命中 {len(picked)} 行"
                f"（只保留最后 {min(len(picked), 400)} 行）\n\n"
                + "\n".join(picked[-400:]) + "\n", encoding="utf-8")
            taken.append("reshade-keylines.txt")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: ReShade 关键行摘录失败（忽略）: {exc}")

    # ⑪ **自更新现场**（2026-10-06 加）。起因：反馈者报「自更新下载完就没了，没提示重启，
    #     手动按重启也没用」，而当时包里**一条相关证据都没有** —— 看不到已下载的载荷还在不在、
    #     exe 旁边有没有 `.old` / `.new` / `update-failed.txt`，更看不到**当前这个 exe 自己**
    #     的大小与 sha256（这是"他现在跑的是哪一版"的**唯一直接判据**）。
    try:
        from . import fsutil, selfupdate

        def _fmt_time(value: float) -> str:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))

        lines: list[str] = []
        exe = selfupdate.executable_path()
        if exe is not None and exe.is_file():
            stat = exe.stat()
            lines.append(f"当前程序（正在跑的就是它）：{exe}")
            lines.append(f"  大小={stat.st_size:,} B · 修改时间={_fmt_time(stat.st_mtime)}"
                         f" · sha256={fsutil.sha256_file(exe)}")
            lines.append("  （与 Release 附件比对 sha256 即可确认它到底是哪一版）")
            for suffix in (".old", ".new"):
                sibling = exe.with_name(exe.name + suffix)
                if sibling.is_file():
                    lines.append(f"  残留 {sibling.name}：{sibling.stat().st_size:,} B"
                                 f" · {_fmt_time(sibling.stat().st_mtime)}")
            notice = exe.with_name("update-failed.txt")
            if notice.is_file():
                lines.append("  **存在 update-failed.txt（上次替换失败的通知）**：")
                lines.extend("    " + row for row in
                             notice.read_text(encoding="utf-8", errors="replace").splitlines()[:8])
        update_dir = Path(config.runtime_path) / "_update"
        if update_dir.is_dir():
            lines.append(f"更新目录 {update_dir}：")
            for item in sorted(update_dir.iterdir()):
                try:
                    lines.append(f"  {item.name}  {item.stat().st_size:,} B"
                                 f" · {_fmt_time(item.stat().st_mtime)}")
                except OSError:
                    continue
            pending = selfupdate.pending_payload(config)
            lines.append(f"待安装判定：{pending}")
        else:
            lines.append("更新目录不存在（从没检查过更新？）")
        if lines:
            (dest / "self-update-forensics.txt").write_text(
                "自更新现场（当前 exe 指纹 / 残留 / 载荷清单 / 待安装判定）\n\n"
                + "\n".join(lines) + "\n", encoding="utf-8")
            taken.append("self-update-forensics.txt")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: 自更新现场失败（忽略）: {exc}")

    # ⑩ **staging（EFMI Mods）的清单与 `key =` 行**（2026-10-06 加）。
    #    起因：反馈者报「**皮肤打不进去**」，而当时包里能回答这个问题的东西**一个都没收** ——
    #    `staged inventory` 只是控制器日志里的一行
    #    `staged inventory | mod_dirs=3 ini_files=6 sample=MC_Controller, …`（只列 3 个名字），
    #    看不到：每个 Mod 目录里到底有几个 ini、那些 `[Key*]` 的 `key =` 现在是什么
    #    （**锁键会把它们改写成 `VK_F24`**）、有没有依赖包混在 staging 里。
    #    于是第一轮只能靠控制器日志推断 —— 这就是「判据不够」。这里只收**清单与 key 行**，
    #    Mod 本体（几百 MB）不收。
    try:
        # ⚠️ **必须走 `config.staging_mods_path`**（按数据根解析过的）—— 直接拿
        #    `staging_mods_dir` 那个相对字符串去找，会相对**当前工作目录**解析，
        #    换个 cwd 就指错地方（实测：测试里差点指到开发机真实的 staging 上）。
        staging = Path(config.staging_mods_path)
        if staging.is_dir():
            lines = [
                f"staging 目录: {staging}",
                "说明：逐目录列出 ini 与其 `key =` 行 —— 锁键（Mod 快捷键锁定）会把 Mod 的键"
                "改写成 `VK_F24`，所以这里能直接看出「键盘到底有没有被锁」。",
                "",
            ]
            folders = sorted(path for path in staging.iterdir() if path.is_dir())
            lines.append(f"共 {len(folders)} 个 Mod 目录：")
            for folder in folders:
                inis = sorted(folder.rglob("*.ini"))
                lines.append(f"  {folder.name}/  （{len(inis)} 个 ini）")
                for ini in inis[:12]:
                    key_lines: list[str] = []
                    try:
                        for raw_line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
                            stripped = raw_line.strip()
                            if stripped.lower().startswith("key") and "=" in stripped:
                                key_lines.append(stripped)
                            if len(key_lines) >= 12:
                                break
                    except OSError:
                        continue
                    try:
                        shown = ini.relative_to(folder)
                    except ValueError:
                        shown = ini.name
                    lines.append(f"      {shown}")
                    lines.extend(f"          {item}" for item in key_lines)
            loose = sorted(path.name for path in staging.iterdir() if path.is_file())
            if loose:
                lines.append(f"散落文件（{len(loose)}）：" + "、".join(loose[:20]))
            (dest / "staging-inventory.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            taken.append("staging-inventory.txt")
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: staging 清单失败（忽略）: {exc}")

    # ⑨ **Streamline / NGX 的清单与配置**（2026-10-06 加 —— 反馈者 #16 的现场指到了这里）。
    #    他的 `Player.log` 里连着 10 次
    #    `[streamline][error] ota.cpp:329 [parseServerManifest] Unexpected line in manifest
    #    file: …`，随后进程内存在 28 秒里从 36 MB 涨到 1.2 GB 然后退出。而那些 manifest
    #    **以前一个都没收** ⇒「到底哪个文件坏了」只能靠猜。
    #    按用户定的规矩：**要看没被收的东西，先把收包范围改掉**。这里只收**小清单/配置**
    #    （json/ini/txt/cfg/dat/xml/log 且 ≤512 KB），大缓存一律跳过（节选原则）。
    try:
        # 根列表由 `nvidia_config_roots()` 统一给出 —— **与"清理损坏配置"用的是同一份**，
        # 否则会出现"包里收得到、清理时却找不到"这种自相矛盾（2026-10-06 实测踩到）。
        for root in nvidia_config_roots():
            if not root.is_dir():
                continue
            for item in sorted(root.rglob("*")):
                try:
                    if not item.is_file() or item.stat().st_size > 512 * 1024:
                        continue
                except OSError:
                    continue
                if item.suffix.lower() not in (".json", ".ini", ".txt", ".cfg", ".dat", ".xml", ".log"):
                    continue
                rel = str(item.relative_to(root)).replace(os.sep, "_")
                take(item, f"nvidia-{root.parent.name}-{root.name}-{rel}"[:118])
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: Streamline/NGX 清单失败（忽略）: {exc}")

    # ⑩ **游戏目录下的小清单**（`Player.log` 说 manifest 内容乱码，先确认游戏侧有没有这类文件）
    try:
        from . import reshade_integration

        game_dir = reshade_integration.detect_game_dir(config, prefer_actual=True)
        if game_dir:
            folder = Path(game_dir)
            for pattern in ("*.json", "*.ini", "sl_*.txt", "nvngx*.json"):
                for item in sorted(folder.glob(pattern)):
                    take(item, f"game-{item.name}"[:118], limit=512 * 1024)
    except Exception as exc:  # noqa: BLE001
        emit(f"排查素材: 游戏侧清单失败（忽略）: {exc}")
    return taken


def _collect_event_log(config: AppConfig, bundle_dir: Path, started_at: float | None) -> None:
    """把该时段的 Windows 事件日志导出来 —— 应用崩溃/挂起事件会写**出错模块名**。"""
    import subprocess

    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((started_at or time.time()) - 300))
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"Get-WinEvent -FilterHashtable @{{LogName='Application','System';StartTime='{since}'}} "
        "-MaxEvents 400 | Select-Object TimeCreated,Id,LevelDisplayName,ProviderName,Message | Format-List"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=60, creationflags=flags)
        text = (out.stdout or "") + (out.stderr or "")
        if text.strip():
            (bundle_dir / "windows-events.txt").write_text(text, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _collect_xxmi_log(config: AppConfig, bundle_dir: Path) -> None:
    """XXMI 自己的日志（注入记录、dll_paths、错误都在里面）。"""
    try:
        from .config import auto_detect_xxmi
        root = auto_detect_xxmi()
        if not root:
            return
        for candidate in (Path(root) / "XXMI Launcher Log.txt",):
            if candidate.is_file() and candidate.stat().st_size <= 16 * 1024 * 1024:
                shutil.copy2(candidate, bundle_dir / "xxmi-launcher-log.txt")
        # 配置也带上：active_importer / extra_libraries / 签名长度都在这
        cfg = Path(root) / "XXMI Launcher Config.json"
        if cfg.is_file() and cfg.stat().st_size <= 2 * 1024 * 1024:
            shutil.copy2(cfg, bundle_dir / "xxmi-config.json")
    except Exception:  # noqa: BLE001
        pass


def _collect_mods_tree(config: AppConfig, bundle_dir: Path) -> int:
    """**把整个 EFMI `Mods` 目录的文件收进包**（2026-10-01 用户要求：
    「上传包加一项，增加整个 mod 目录中的文件」）。

    取舍：**诊断价值高的小文本（`.ini`/`.json`/`.txt`/`.cfg`/`.tsv` 等）一律收**；
    大资源（`.dds`/`.buf`/`.mesh`）**只登记进清单**（含大小与 sha256），因为它们对定位问题
    没有信息量、却能把包撑到几百 MB。**清单永远完整列出所有文件**，并在表头写明收了多少、
    合计多大、上限多少。总量上限 200 MB、单文件 64 MB。
    """
    import hashlib

    try:
        from .config import auto_detect_migoto_loader

        loader = auto_detect_migoto_loader()
        mods = Path(loader) / "Mods" if loader else None
        if not mods or not mods.is_dir():
            return 0
    except Exception:  # noqa: BLE001
        return 0

    TEXT_EXT = {".ini", ".json", ".txt", ".cfg", ".md", ".xml", ".yaml", ".yml",
                ".log", ".tsv", ".csv"}
    LIMIT_TOTAL = 200 * 1024 * 1024
    LIMIT_FILE = 64 * 1024 * 1024

    def digest(path: Path) -> str:
        try:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return "?"

    listing: list[str] = []
    taken = 0
    total = 0
    for src in sorted(mods.rglob("*")):
        if not src.is_file():
            continue
        try:
            size = src.stat().st_size
        except OSError:
            continue
        rel = src.relative_to(mods)
        is_text = src.suffix.lower() in TEXT_EXT
        copy_it = (total + size <= LIMIT_TOTAL and size <= LIMIT_FILE
                   and (is_text or size <= 2 * 1024 * 1024))
        if copy_it:
            try:
                dest = bundle_dir / "efmi-mods" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                taken += 1
                total += size
                listing.append(f"{rel}\t{size} B\t已收入包")
            except OSError as exc:
                listing.append(f"{rel}\t{size} B\t复制失败: {exc}")
        else:
            listing.append(f"{rel}\t{size} B\t仅登记（sha256={digest(src)}）")

    header = (f"EFMI Mods 目录完整清单：共 {len(listing)} 个文件；"
              f"已收入包 {taken} 个、合计 {total / 1048576:.1f} MB"
              f"（上限 {LIMIT_TOTAL // 1048576} MB，单文件 {LIMIT_FILE // 1048576} MB）\n"
              f"目录: {mods}\n\n")
    (bundle_dir / "efmi-mods-tree.txt").write_text(header + "\n".join(listing) + "\n",
                                                   encoding="utf-8")
    return taken


def make_bundle(config: AppConfig, evidence: dict[str, Any] | None = None,
                *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把崩溃现场 + 控制器日志 + 终末地日志打成 zip，返回路径信息。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    from . import fsutil

    # ⚠️ 同秒两次崩溃包不能互相覆盖（2026-10-04）：`mkdir(exist_ok=True)` + `make_archive`
    # 在同一个秒级名字上会**合并进上一次的目录/覆盖上一份 zip**（"验收发现两套实现同族
    # 只修一处"里的另一处 —— `game_clean.backup_and_clean` 早就防了这个）。
    bundle_dir = fsutil.unique_sibling(bundles_root(config) / f"crash-{ts}")
    bundle_dir.mkdir(parents=True, exist_ok=True)

    if evidence is None:
        evidence = collect_evidence(config)

    # 崩溃后的建议（算一次，报告正文与前端弹窗共用）—— 见 `crash_advice`。
    advice = crash_advice(config, evidence)

    # ① 崩溃报告正文
    try:
        report_text = _render_report(evidence)
        if advice:
            # 建议也要落在报告里：用户把 zip 发出去、或自己翻日志时，
            # 一眼就该看到"下一步该做什么"，而不是只有一堆现场数据。
            report_text += ("\n" + "=" * 72 + "\n崩溃后的建议\n" + "=" * 72 + "\n"
                            + str(advice.get("title") or "") + "\n\n"
                            + str(advice.get("message") or "") + "\n")
        (bundle_dir / "controller-crash-report.log").write_text(report_text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        (bundle_dir / "controller-crash-report.log").write_text(f"报告生成失败: {exc}\n", encoding="utf-8")

    # ② 控制器自己的日志
    for path in sorted((config.runtime_path / "logs").glob("EndfieldModController-*.log")):
        try:
            shutil.copy2(path, bundle_dir / path.name)
        except OSError:
            pass

    # ③ 终末地自己的日志（关键：用户崩溃时最需要的）
    game_logs = collect_game_logs(config, bundle_dir)

    # ④ 环境信息
    (bundle_dir / "environment.txt").write_text(_environment_text(config), encoding="utf-8")
    # 运行时组件清单（用户 2026-10-02 要求「一次抓全」）：文件名 / 字节 / sha256 / 是否偏离基线。
    # 之前缺了它，"崩溃那一刻装的是哪一版组件"根本无从回答 —— 2026-10-02 那天用户把 runtime
    # 整个删掉重下，旧现场连清单都没留下，崩因只能停在"配套损坏"这个类别上。
    try:
        from . import runtime_assets

        (bundle_dir / "runtime-inventory.txt").write_text(
            runtime_assets.inventory_text(config), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        (bundle_dir / "runtime-inventory.txt").write_text(
            f"（收集运行时清单失败：{exc}）", encoding="utf-8"
        )

    # ④-b DLSS5 现场 + 崩溃归因
    #   * `dlss5-feed.log` 是"神经渲染到底有没有出帧、卡在哪一步"的直接证据；
    #     2026-09-30 一个反馈的包里缺它，只能靠 addon 的 fileVersion 反推，绕了一大圈。
    #   * `cause.json` 让前端弹窗知道该走"Mod 冲突"那套文案，还是普通崩溃文案。
    import json as _json

    try:
        dlss5_dir = Path(config.dlss5_path)
        for name in ("dlss5-feed.log", "dlss5-feed.cfg", "ReShade.ini", "ReShadePreset.ini"):
            src = dlss5_dir / name
            if src.is_file() and src.stat().st_size <= 8 * 1024 * 1024:
                shutil.copy2(src, bundle_dir / name)
    except OSError:
        pass
    cause = evidence.get("cause") or classify_cause(config, evidence)
    try:
        (bundle_dir / "cause.json").write_text(
            _json.dumps(cause, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass
    # ④-c **全量现场**（2026-10-01 用户要求「让日志包一次抓全所有数据，不要搞好几轮」）
    #   针对的正是反馈里那个"跑四十多秒就闪退"的形态 —— 以前只收静态快照 + Player.log 尾部，
    #   看不出这 40 秒里发生了什么。现在一次性收：运行时采样时间线、完整 Player.log、
    #   官方崩溃转储、Windows 事件、EFMI 配置与 Mod 清单、XXMI 日志与配置、ReShade.log。
    try:
        from . import watchsample

        samples = watchsample.read_all(config)
        if samples:
            (bundle_dir / "watch-samples.jsonl").write_text(
                "\n".join(_json.dumps(s, ensure_ascii=False) for s in samples) + "\n", encoding="utf-8")
            (bundle_dir / "watch-samples.txt").write_text(
                "游戏进程运行时采样（每 5 秒一次）\n" + watchsample.summarise(samples), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _collect_full_game_logs(config, bundle_dir)
    _collect_crash_dumps(config, bundle_dir)
    _collect_game_config(config, bundle_dir)
    # ④-d **注入现场时间线**（2026-10-05 用户要求「在一键启动最开始和 xxmi 拉起后和
    #     终末地启动后和终末地关闭和崩溃后都要收注入列表」）：五张照片连同
    #     "**进程里到底进了哪几个 DLL**"一起带走。只抓崩溃那一刻的话，"本来是对的、
    #     中途被改坏"和"一直都是这样"分不开 —— 而 `0xC0000135` 恰好有这两种来源。
    try:
        from . import injecttrace

        entries = injecttrace.read_all(config)
        if entries:
            (bundle_dir / "injection-trace.jsonl").write_text(
                "\n".join(_json.dumps(item, ensure_ascii=False) for item in entries) + "\n",
                encoding="utf-8")
            (bundle_dir / "injection-trace.txt").write_text(
                injecttrace.render(entries), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    collect_diagnosis_files(config, bundle_dir, log=log)
    _collect_mods_tree(config, bundle_dir)
    _collect_event_log(config, bundle_dir, evidence.get("_started_at"))
    _collect_xxmi_log(config, bundle_dir)
    _collect_extra_evidence(config, bundle_dir)

    # 崩溃记忆：记下"这次崩的时候跑的是哪套 Mod"，一键启动前就能预警（用户 2026-09-30 要求）
    #
    # ⚠️ 判据改成看 `crashed`（2026-10-02 修）：以前是 `kind in {"crash", "mod_conflict"}`，
    #    而归因后来新增了 `gpu_compiler`（以及当时还有、现已删除的 `dlss5_nr_style`）——
    #    于是那两类崩溃**一条都没被记下来**（用户现场：12:53 那次崩完，
    #    `crash_memory.json` 里没有新条目）。
    #    "算不算一次崩溃"与"崩因是哪一类"是两件事，不该用后者当前者的开关。
    if cause.get("crashed") or str(cause.get("kind")) in {"crash", "mod_conflict"}:
        try:
            remember_crash(config, kind=str(cause.get("kind")),
                           detail=str(cause.get("detail") or ""), mods=staging_mods(config))
        except Exception:  # noqa: BLE001 —— 记忆写失败不该影响崩溃包本身
            pass
    elif combo_succeeded(evidence):
        # 这次**确实跑通**了（没有崩溃转储，且正常退出或跑够久）⇒ 把记忆里匹配这套组合的旧记录移出。
        # 用户 2026-10-02 要求：「某一组之前报崩溃的，后面终末地成功启动没崩就从记忆里移出」——
        # 组合既然已经跑通，留着那条记忆只会让下次启动白弹一次"这套以前崩过"。
        try:
            cleared = forget_crashes_for_combo(config)
            proven = record_proven_combo(config)
            if cleared or proven:
                detail = f"已移出 {len(cleared)} 条旧崩溃记忆" if cleared else ""
                if proven:
                    detail += ("；" if detail else "") + "这套组合已记为『能进』（以后不再报它的静态冲突）"
                _log(config, f"崩溃记忆: 这套组合这次跑通了 —— {detail}")
                if log:
                    log(f"崩溃记忆: 这套组合跑通了 —— {detail}")
        except Exception:  # noqa: BLE001 —— 清记忆/记台账失败不该影响崩溃包本身
            pass

    # ⑤ 打包
    # 名字直接取目录名（可能带 `-1` 之类去重后缀），别再用 `crash-{ts}` 拼一遍
    # （那会变成 `crash-crash-…`）。
    zip_path = bundles_root(config) / f"{bundle_dir.name}.zip"
    try:
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", bundle_dir)
        ok_zip = zip_path.is_file()
    except Exception as exc:  # noqa: BLE001
        ok_zip = False
        zip_path = Path(f"(打包失败: {exc})")

    result = {
        "ok": True,
        "dir": str(bundle_dir),
        "zip": str(zip_path) if ok_zip else "",
        # ⚠️ 下面四个是**给前端弹窗补的别名**（2026-10-04 修前后端不匹配）：
        # `App.vue` 的崩溃弹窗读 `fresh.path / fresh.bundle / fresh.reason / fresh.mods`，
        # 而后端原先只给 `zip / dir / crashed / cause` ⇒ 弹窗里路径**恒显示
        # 「（路径读取失败）」**、点「打开诊断包」**什么都不打开**（违反"必须给出文件在哪"
        # 的准则），也看不到崩溃时启用了哪些 Mod。`reason` 用归因 kind（可能是
        # `exit_code=0` 的正常退出），前端不再无脑写死 `process_disappeared`。
        "path": str(zip_path) if ok_zip else str(bundle_dir),
        "bundle": str(bundle_dir),
        "reason": str((cause or {}).get("kind") or ""),
        "mods": staging_mods(config),
        "game_logs": game_logs,
        "crashed": is_crash(evidence),
        "cause": cause,
        # 崩溃后的**下一步建议**（2026-10-05）：崩在图形/注入链那层时给
        # 「清空依赖并重新下载」这条路（前端弹窗据此多一个按钮）。空 dict = 这次没有具体建议。
        "advice": advice,
        "fault_modules": fault_modules(config, evidence),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _log(config, f"崩溃包已生成: {zip_path.name if ok_zip else bundle_dir.name}（含终末地日志 {len(game_logs)} 份）")
    if log:
        try:
            log(f"崩溃包: {result['zip'] or result['dir']}")
        except Exception:  # noqa: BLE001
            pass
    return result


def latest_bundle(config: AppConfig) -> dict[str, Any]:
    """最近一个崩溃包（供前端弹窗）。"""
    root = bundles_root(config)
    if not root.is_dir():
        return {}
    zips = sorted(root.glob("crash-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        return {}
    latest = zips[0]
    cause: dict[str, Any] = {}
    cause_file = latest.with_suffix("") / "cause.json"
    if cause_file.is_file():
        import json as _json

        try:
            loaded = _json.loads(cause_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cause = loaded
        except (OSError, ValueError):
            cause = {}
    return {
        "zip": str(latest),
        "dir": str(latest.with_suffix("")),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest.stat().st_mtime)),
        "size_mb": round(latest.stat().st_size / 1048576, 2),
        "cause": cause,
    }


def _render_report(evidence: dict[str, Any]) -> str:
    """把 evidence 渲染成文本（write_report 与崩溃包共用）。"""
    e = evidence
    p = e.get("process", {})
    inj = e.get("injections", {})
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"游戏崩溃/退出报告  {e.get('collected_at')}")
    out.append("=" * 72)
    out.append(f"进程      : {p.get('name')}  启动 {p.get('started_at') or '未知'}  退出 {p.get('exit_time') or '未知'}"
               + (f"  存活 {p.get('alive_seconds'):.0f} 秒" if p.get("alive_seconds") else ""))
    if is_crash(e):
        verdict = "崩溃（本次运行期间 CrashSight 上传了崩溃转储 uploadCrash）"
        if e.get("normal_exit"):
            verdict += "；Player.log 里的卸载统计是崩溃后 Unity 补写的，不代表正常退出"
    elif e.get("normal_exit"):
        verdict = "正常退出（Player.log 有卸载统计，且本次运行期间没有 uploadCrash）"
    else:
        verdict = "未发现崩溃迹象（无卸载统计、无 uploadCrash，请人工确认）"
    out.append(f"崩溃判定  : {verdict}")
    # ⭐ 运行时采样时间线：看"哪一秒开始异常、崩前新加载了什么模块、内存/句柄怎么涨"
    _samples = e.get("watch_samples") or []
    if _samples:
        try:
            from . import watchsample

            out.append("")
            out.append("── 运行时采样时间线（每 5 秒一次）──")
            out.append(watchsample.summarise(_samples))
        except Exception:  # noqa: BLE001
            pass
    cause = e.get("cause") or {}
    if cause:
        kind_text = {"mod_conflict": "Mod 资源冲突（自检记录）",
                     "crash": "其它原因（看下面的崩溃栈与模块列表）",
                     "exit": "未崩溃"}.get(str(cause.get("kind")), str(cause.get("kind")))
        out.append(f"归因      : {kind_text}" + (f" —— {cause.get('detail')}" if cause.get("detail") else ""))
        if cause.get("checked_at"):
            out.append(f"            自检时间 {cause.get('checked_at')}")
    out.append("")
    out.append("── 注入快照 ──")
    out.append(f"  游戏目录 : {inj.get('game_dir')}")
    for name, size in (inj.get("files") or {}).items():
        out.append(f"    {name:<22} {size} B{'' if size else '  (缺失)'}")
    out.append(f"  XXMI 注入库(enabled={inj.get('injection_enabled')}):")
    for line in (inj.get("extra_libraries") or "(空)").split("\n"):
        out.append(f"    {line}")
    out.append(f"  乳摇插件 : {json.dumps(inj.get('sbm') or {}, ensure_ascii=False)}")
    out.append("")
    out.append("── XXMI 注入记录 ──")
    for line in (e.get("xxmi_inject") or ["(无)"]):
        out.append(f"  {line[-200:]}")
    out.append("")
    out.append("── CrashSight ──")
    out.append("  （reportException = 游戏内被捕获的异常，每次运行都会出现，**不算崩溃**；"
               "uploadCrash = 崩溃转储上传，出现即崩溃）")
    for line in (e.get("crash_sight") or ["(无)"]):
        out.append(f"  {line}")
    if e.get("crash_upload"):
        out.append("  >> 本次运行期间**上传了崩溃转储** uploadCrash:")
        for line in e["crash_upload"]:
            out.append(f"     {line}")
    else:
        out.append("  >> 本次运行期间**没有** uploadCrash")
    out.append("")
    for section in (e.get("crashes") or []):
        out.append(f"── 游戏崩溃栈（{section.get('report_dir')}，共 {section.get('lines')} 行）──")
        if section.get("at") is None:
            out.append("  （该报告里没有 Crash!!! 标记）")
        else:
            out.append("  [崩溃前最后日志]")
            for line in (section.get("before") or [])[-20:]:
                out.append(f"    {line[:180]}")
        if section.get("modules"):
            out.append("  [进程里的相关模块]")
            for line in section["modules"]:
                out.append(f"    {line[:180]}")
        out.append("")
    if e.get("game_errors"):
        out.append("── 终末地自己的报错（[Error]/[Exception]，崩溃前后）──")
        for line in e["game_errors"]:
            out.append(f"  {line}")
        out.append("")
    if e.get("player_log_tail"):
        out.append("── 最新 Player.log 尾部 ──")
        for line in e["player_log_tail"]:
            out.append(f"  {line[:180]}")
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# 后台监控
# ---------------------------------------------------------------------------
_WATCH: dict[str, Any] = {"thread": None, "running": False, "pid": None, "started_at": None, "bundle": None}


def watch_state() -> dict[str, Any]:
    return {
        "running": bool(_WATCH.get("running")),
        "pid": _WATCH.get("pid"),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_WATCH["started_at"]))
        if _WATCH.get("started_at") else None,
        "bundle": _WATCH.get("bundle"),
    }


def take_bundle() -> dict[str, Any] | None:
    """取走（并清空）刚生成的崩溃包，供前端弹窗一次性提示。"""
    bundle = _WATCH.get("bundle")
    _WATCH["bundle"] = None
    return bundle


def arm_runtime_watch(config: AppConfig, pid: int, *,
                      log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """游戏进程**刚出现**时调用：重置采样 + 记一张"终末地启动后"的注入照片。

    返回的 state 要一路交给 `poll_runtime_watch()`（它记着"上次采样是什么时候、
    已经见过哪些模块"）。

    ⚠️ 为什么要抽出来：采样与注入时间线原先只长在 `crashwatch.start_watch` 身上，
    而**主路径跑的是 `diagnostics._monitor_process`** ⇒ 那两样在主路径下**从来没跑过**
    （反馈者的诊断包里连 `watch-samples.jsonl` 都不存在）。现在两个监视器都调这一对函数，
    **判据只有一处**。
    """
    emit: Callable[[str], None] = log or (lambda message: None)
    state: dict[str, Any] = {"known": set(), "last": 0.0}
    try:
        from . import watchsample

        watchsample.reset(config)
    except Exception as exc:  # noqa: BLE001
        emit(f"崩溃监控: 重置采样失败（忽略）: {exc}")
    try:
        from . import injecttrace

        injecttrace.record(config, phase="game-started", pid=pid, log=emit)
    except Exception as exc:  # noqa: BLE001 —— 取证失败绝不能打断跟踪
        emit(f"注入时间线: 记录失败（忽略）: {exc}")
    return state


def poll_runtime_watch(config: AppConfig, pid: int, state: dict[str, Any], *,
                       log: Callable[[str], None] | None = None,
                       interval: float = 5.0) -> bool:
    """监视循环里**每轮**调一次；内部按"距上次 ≥ `interval` 秒"决定是否真采。

    采到就返回 True。失败只记日志、绝不抛 —— 监视器不能因为取证而停摆。
    """
    emit: Callable[[str], None] = log or (lambda message: None)
    now = time.time()
    if now - float(state.get("last") or 0.0) < interval:
        return False
    state["last"] = now
    try:
        from . import nr_autostart, watchsample

        entry = watchsample.sample(
            pid,
            known_modules=state.get("known") or set(),
            feed_log=Path(config.dlss5_path) / "dlss5-feed.log",
            # ⚠️ **必须用生效那份的路径**（2026-10-06 修）：ReShade 按
            # `RESHADE_BASE_PATH_OVERRIDE` 把日志写在 `runtime\reshade\` 下，
            # 而这里原先写的是 `runtime\dlss5\ReShade.log`（那是**部署源**目录，
            # 通常根本没有这个文件）⇒ 采样里的 `reshade_lines` **恒为 0**，
            # 那条判据等于从没生效过（反馈者 1.0.15 的包里 8 条采样全是 0，实测抓到）。
            reshade_log=nr_autostart.reshade_log_path(config),
        )
        if not entry:
            return False
        watchsample.append(config, entry)
        state["known"] = {os.path.basename(m).lower() for m in (entry.get("modules") or [])}
        return True
    except Exception as exc:  # noqa: BLE001 —— 采样失败绝不打断跟踪
        emit(f"崩溃监控: 采样失败 {exc}")
        return False


def on_game_exit(
    config: AppConfig,
    *,
    pid: int | None = None,
    started_at: float | None = None,
    exit_time: float | None = None,
    alive_seconds: float | None = None,
    exit_code: int | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """**游戏退出后的统一取证**：证据 → 报告 → 归因 → 记账 → 崩溃包 → 建议。

    ⚠️ **为什么必须收敛成一个入口**（2026-10-05 从反馈者的包里查出来的真问题）：
    项目里有**两套**进程监视器 ——

    * `diagnostics._monitor_process`：**主路径唯一在跑的那个**（能读退出码、带 NR 自动开启、
      命令行采集、句柄降级）；
    * `crashwatch.start_watch`：只在"以系统默认方式启动 XXMI"那条分支里被调用。

    而**取证这一整套只长在后者身上** ⇒ 主路径下从来没有 5 秒采样、没有注入时间线、
    没有崩溃归因、没有崩溃记忆与跑通台账、**也没有"连续三次失败"计数** ——
    反馈者连崩 5 次都没等到那个弹窗，就是这个原因（他的包里连
    `watch-samples.jsonl` 都不存在）。

    现在两条路径都调它，**判据只有一处**。返回值供调用方写回自己的状态：
    `{"evidence", "report", "crashed", "bundle", "advice", "launch_failure"}`。
    """
    emit: Callable[[str], None] = log or (lambda message: None)
    started = float(started_at if started_at is not None else time.time())
    ended = float(exit_time if exit_time is not None else time.time())
    alive = float(alive_seconds if alive_seconds is not None else max(ended - started, 0.0))
    result: dict[str, Any] = {"crashed": False}

    # ① 注入现场时间线·**时机 4／5：终末地关闭**（用户 2026-10-05 要求）。
    #    必须在"等 WER 落盘那 6 秒"**之前**记，时间戳才贴着真实退出时刻。
    code_note = f"，退出码 {exit_code}" if exit_code is not None else ""
    try:
        from . import injecttrace

        injecttrace.record(config, phase="game-exited", pid=pid,
                           note=f"存活 {alive:.0f} 秒{code_note}", log=emit)
    except Exception as exc:  # noqa: BLE001 —— 取证失败绝不能影响主流程
        emit(f"注入时间线: 记录失败（忽略）: {exc}")

    # ② 等 **6 秒**（2026-10-05 由 3 秒加长）：Windows 的 WER 报告（`AppCrash_*.wer`，
    #    里面写着"故障模块 + 异常代码"）是崩溃取证里最硬的一手材料，而它由 WerFault 在
    #    进程终止后**几秒内**才落盘；等 3 秒时常还没写完 ⇒ "真崩了"被判成"未发现崩溃迹象"。
    time.sleep(6.0)
    try:
        evidence = collect_evidence(config, started_at=started, exit_time=ended,
                                    alive_seconds=alive)
    except Exception as exc:  # noqa: BLE001
        emit(f"崩溃监控: 收集现场失败 {exc}")
        return result
    # 把调用方手里的退出码并进证据（`_monitor_process` 有、`start_watch` 没有）——
    # 归因、报告、包内证据都读这一份，避免两处各写一个。
    if exit_code is not None:
        try:
            from . import diagnostics

            evidence.setdefault("process", {})
            evidence["process"]["exit_code"] = int(exit_code)
            evidence["process"]["exit_text"] = diagnostics.describe_exit_code(int(exit_code))
        except Exception:  # noqa: BLE001
            pass
    try:
        path = write_report(config, evidence)
        crashed = is_crash(evidence)
        emit(f"崩溃监控: {'检测到崩溃' if crashed else '未检测到崩溃（正常退出）'}，报告: {path.name}")
        result.update({"evidence": evidence, "report": str(path), "crashed": bool(crashed)})
    except Exception as exc:  # noqa: BLE001
        emit(f"崩溃监控: 写报告失败 {exc}")
        return result

    # ③ 注入现场时间线·**时机 5／5：崩溃后**（事后状态：注入库/游戏目录有没有被动过）
    try:
        from . import injecttrace

        injecttrace.record(config, phase="crash", pid=pid,
                           note=("检测到崩溃" if crashed else "正常退出"), log=emit)
    except Exception as exc:  # noqa: BLE001
        emit(f"注入时间线: 记录失败（忽略）: {exc}")

    # ④ 记一笔"这次启动算成功还是失败"（2026-10-05 用户要求：连续 3 次失败 ⇒ 弹「强力修复」）。
    #    判据在 `record_launch_result` 里复用 `combo_succeeded`，所以**静默闪退也计数**
    #    （不能只数崩溃 —— 反馈者那台一条 WER 都没有，只数崩溃就永远等不到这个弹窗）。
    try:
        result["launch_failure"] = record_launch_result(config, evidence, log=emit)
    except Exception as exc:  # noqa: BLE001 —— 记账失败绝不影响崩溃取证
        emit(f"崩溃监控: 记录启动结果失败（忽略）: {exc}")

    # ⑤ 崩溃包
    bundle: dict[str, Any] | None = None
    try:
        bundle = make_bundle(config, evidence, log=emit)
        result["bundle"] = bundle
        emit(f"崩溃监控: 崩溃包已就绪（含终末地日志 {len(bundle.get('game_logs') or [])} 份）"
             + ("" if crashed else "，正常退出不提示"))
    except Exception as exc:  # noqa: BLE001
        emit(f"崩溃监控: 打包失败 {exc}")

    # ⑥ 崩溃后的**建议**（2026-10-05 用户要求：「崩溃不要卸掉功能，应该弹窗建议清空依赖并
    #    重新下载重试」）。这里**只产出建议、不动任何开关**；点不点由用户决定。
    try:
        advice = crash_advice(config, evidence)
        if advice:
            result["advice"] = advice
            if isinstance(bundle, dict):
                bundle["advice"] = advice
            emit("崩溃监控: 建议 —— " + str(advice.get("title") or ""))
    except Exception as exc:  # noqa: BLE001 —— 建议算不出来不该影响崩溃包本身
        emit(f"崩溃监控: 生成建议失败（忽略）: {exc}")
    return result


def start_watch(config: AppConfig, *, timeout: float = 6 * 3600.0,
                log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """后台等游戏进程出现→退出，然后自动收集现场并写报告。"""
    if _WATCH.get("running"):
        return {"ok": True, "already": True, **watch_state()}

    def _emit(msg: str) -> None:
        _log(config, msg)
        if log:
            try:
                log(msg)
            except Exception:  # noqa: BLE001
                pass

    def _worker() -> None:
        _WATCH["running"] = True
        deadline = time.time() + timeout
        try:
            # ① 等进程出现
            pid = None
            while time.time() < deadline:
                pids = _process_ids()
                if pids:
                    pid = pids[0]
                    break
                time.sleep(1.0)
            if pid is None:
                _emit("崩溃监控: 等待游戏进程超时，未开始跟踪")
                return
            started = time.time()
            _WATCH["pid"] = pid
            _WATCH["started_at"] = started
            _emit(f"崩溃监控: 已跟踪 {GAME_PROCESS} pid={pid}")
            # ★ 采样 + 注入时间线·**时机 3／5：终末地启动后**。2026-10-05 收敛成共用入口：
            #   `arm_runtime_watch()` 重置采样并记下"**注入到底进没进进程**"的那张照片
            #   （看 `expect_missing` —— 非空就等于"XXMI 报告注入成功、进程里却没有它"，
            #   `0xC0000135` 的两种来源由此分开）。
            sample_state = arm_runtime_watch(config, pid, log=_emit)

            # ② 等进程退出 —— **每 5 秒采一次样**（2026-10-01 用户要求"日志包一次抓全"）：
            #    "跑四十多秒就闪退"这种问题，静态快照看不出任何东西；
            #    必须留下**时间线**（哪个模块在哪一秒才加载、内存/句柄怎么涨、日志有没有停）。
            #    采样增量落盘，即使进程被强杀也已写好前面几次。
            while time.time() < deadline:
                if not _process_ids():
                    break
                poll_runtime_watch(config, pid, sample_state, log=_emit)
                time.sleep(1.0)
            exit_time = time.time()
            alive = exit_time - started
            _emit(f"崩溃监控: 游戏已退出（存活 {alive:.0f} 秒），正在收集现场…")
            # ★ 注入现场时间线·**时机 4／5：终末地关闭**（用户 2026-10-05 要求）。
            #   放在"等 WER 落盘那 6 秒"**之前**记，时间戳才贴着真实退出时刻。
            try:
                from . import injecttrace

                injecttrace.record(config, phase="game-exited", pid=pid,
                                   note=f"存活 {alive:.0f} 秒", log=_emit)
            except Exception as exc:  # noqa: BLE001
                _emit(f"注入时间线: 记录失败（忽略）: {exc}")

            # ③ 收集现场 + 写报告 + 归因 + 记账 + 打崩溃包 + 出建议
            #    —— 全在 `on_game_exit()` 里，**与 `diagnostics._monitor_process` 共用
            #    同一个入口**（判据只有一处）。抽出来之前的教训：这一整套只挂在
            #    `start_watch` 身上，而它只在"以系统默认方式启动 XXMI"那条分支里被调用 ⇒
            #    主路径下从来没有采样/归因/记忆/计数，反馈者崩 5 次都没等到那个弹窗。
            outcome = on_game_exit(config, pid=pid, started_at=started, exit_time=exit_time,
                                   alive_seconds=alive, log=_emit)
            if outcome.get("launch_failure"):
                _WATCH["launch_failure"] = outcome["launch_failure"]
            if outcome.get("crashed") and outcome.get("bundle"):
                _WATCH["bundle"] = outcome["bundle"]
            if outcome.get("advice"):
                _WATCH["advice"] = outcome["advice"]
        except Exception as exc:  # noqa: BLE001
            _emit(f"崩溃监控异常: {exc}")
        finally:
            _WATCH["running"] = False
            _WATCH["pid"] = None

    thread = threading.Thread(target=_worker, name="emc-crash-watch", daemon=True)
    thread.start()
    _WATCH["thread"] = thread
    return {"ok": True, **watch_state()}
