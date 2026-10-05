"""热重载：给**正在运行**的终末地发一次 F10（3DMigoto / EFMI 的 `config_reload`）。

## 为什么要有这个模块（2026-10-04 用户要求「加一个热重载」）

改完 `d3dx_user.ini`、重铺了 Mod 之后，3DMigoto **不会**自己重读配置 —— 官方文档写得很明确：

> Mark a variable as persist[ent] to automatically save it to the **d3dx_user.ini on exit or
> F10 (config_reload)**. Use **Ctrl+Alt+F10 (wipe_user_config)** to discard persistent values.
> —— <https://leotorrez.github.io/modding/docs/constants>

同生态的两个管理器也都是"改配置 → 发 F10"：
  * **EMOPM**（终末地专用，开源）`app/f10_sender.py`：EnumWindows 找窗口 → `ShowWindow(SW_RESTORE)`
    → `AttachThreadInput` 绕前台锁 → `SetForegroundWindow` → `SendInput` F10；
  * **JASM**（同类成熟项目）：同样"用 F10 刷新模组"，额外用一个**提权辅助进程 + 命名管道**
    来解决"管理器权限比游戏低时 F10 会被 Windows 丢掉"。

## 两条硬约束（少一条 F10 就收不到）

① **必须 `SendInput`（真实按键），不能 `PostMessage`** —— 3DMigoto / EFMI 是每帧轮询
   `GetAsyncKeyState` 的（这一点在 `vkey_inject.h` 里也实测过），只有真实输入才会进
   全局键盘状态；直接往窗口投消息它读不到。
② **游戏窗口必须是前台** —— `d3dx.ini` 的 `check_foreground_window`（默认 1）是 3DMigoto
   处理按键的总门禁，所以这里要先 `AttachThreadInput` + `SetForegroundWindow` 把游戏拉前台，
   再发键。代价是**会抢一次焦点**（EMOPM 同样如此），所以调用点要把它写进日志。

顺带一提：本程序是 `--uac-admin` 打包的，与游戏同级，**不需要** JASM 那种提权辅助进程。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

VK_F10 = 0x79

SW_RESTORE = 9
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

# 窗口标题关键字（用户可在设置里覆盖）：终末地的窗口标题随语言/启动方式变化，
# 所以给一组宽松的默认值，命中一个即可。
DEFAULT_WINDOW_KEYWORDS = ("Endfield", "终末地", "Arknights")

# 拉前台之后等窗口真正拿到焦点再发键（EMOPM 用 100ms；我们再加一档，见下面的实测教训）
FOREGROUND_SETTLE_SECONDS = 0.30

# **按键保持时长**（down 与 up 之间的间隔）—— 这是本次最关键的一处。
#
# ⚠️ 2026-10-04 实测教训（用户第二次报"热重载还是没效果"）：第一版 `down` 与 `up` **之间没有延时**，
# 而 3DMigoto / EFMI 是**每帧轮询 `GetAsyncKeyState`** 的（60fps ⇒ 一帧 16ms）—— 按下与抬起落在同一
# 瞬间，轮询型程序**整帧错过**，等于没按。同一个坑在面板合成键上踩过（按下时长 70ms → 160ms）。
HOLD_SECONDS = 0.18


def _force_foreground(hwnd: int) -> bool:
    """把窗口拉到前台（绕开 Windows 的前台锁），返回**是否真的成了前台**。

    单纯 `SetForegroundWindow` 在"调用进程不是前台进程"时会被系统拒绝 —— 手法是把
    当前线程与**当前前台窗口所在线程**用 `AttachThreadInput` 临时绑在一起，再调用就生效
    （EMOPM 同样是这么做的）。

    返回值很关键：**没拿到前台就发键，3DMigoto 的 `check_foreground_window` 会把这次按键丢掉**
    —— 那正是"日志说发了 F10、游戏里却没反应"的第二种可能。所以这里如实回报，让调用方写进日志。
    """
    foreground = _user32.GetForegroundWindow()
    current_thread = _kernel32.GetCurrentThreadId()
    fg_pid = wintypes.DWORD()
    target_thread = _user32.GetWindowThreadProcessId(foreground, ctypes.byref(fg_pid)) if foreground else 0
    attached = False
    if target_thread and target_thread != current_thread:
        attached = bool(_user32.AttachThreadInput(target_thread, current_thread, True))
    try:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(target_thread, current_thread, False)
    return int(_user32.GetForegroundWindow() or 0) == int(hwnd)


def _send_key(vk: int, hold_seconds: float = HOLD_SECONDS) -> None:
    """发一次真实按键：`down` → **保持 `hold_seconds`** → `up`。

    ⚠️ 保持时间是必须的（原因见 `HOLD_SECONDS` 的注释）：轮询 `GetAsyncKeyState` 的程序
    需要按键**跨越至少一帧**才读得到。虚拟键与扫描码都填，兼容只认其中一种的进程。
    """
    scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)

    def _emit(flags: int) -> None:
        item = _INPUT()
        item.type = INPUT_KEYBOARD
        item.ki.wVk = vk
        item.ki.wScan = scan
        item.ki.dwFlags = flags
        item.ki.time = 0
        item.ki.dwExtraInfo = None
        _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))

    _emit(KEYEVENTF_SCANCODE)
    time.sleep(max(0.0, hold_seconds))
    _emit(KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)


def window_keywords(config: AppConfig) -> tuple[str, ...]:
    """找游戏窗口用的标题关键字（配置留空 ⇒ 用默认那组）。"""
    raw = getattr(config, "game_window_keywords", None)
    if isinstance(raw, str):
        items = [part.strip() for part in raw.replace("，", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = [str(part).strip() for part in raw]
    else:
        items = []
    items = [item for item in items if item]
    return tuple(items) if items else DEFAULT_WINDOW_KEYWORDS


if os.name == "nt":  # pragma: no cover - 非 Windows 上整个模块退化为"不支持"
    from ctypes import wintypes

    _ULONG_PTR = ctypes.c_void_p  # 64 位安全

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.c_ulong),
            ("wParamL", ctypes.c_ushort),
            ("wParamH", ctypes.c_ushort),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _is_windows() -> bool:
    return os.name == "nt" and sys.platform.startswith("win")


def _process_basename(pid: int) -> str:
    """某个进程的可执行文件名（失败返回空串）。"""
    if not _is_windows() or not pid:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = None
    try:
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if handle:
            try:
                _kernel32.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass


# 明确**不是游戏主窗口**的标题特征：覆盖层 / 注入器的辅助窗口。
# ⚠️ 2026-10-04 实测踩到：Poser 的 `EndfieldPoserOverlay` 窗口**属于 Endfield.exe 进程**、
# 标题又含 "Endfield" ⇒ 只按"进程名 + 标题关键字"挑，会把它当主窗口 ⇒ F10 打给覆盖层、
# 还把 overlay 拉成前台（游戏主窗口因此不是前台，3DMigoto 的 check_foreground_window 直接丢键）
# ⇒ 用户看到的正是"热重载没生效"。
EXCLUDED_TITLE_HINTS = ("overlay", "poser", "reshade", "imgui", "debug", "console")

# Unity 游戏主窗口的窗口类名（终末地是 Unity 引擎）。命中它就基本可以确定是主窗口。
PREFERRED_WINDOW_CLASSES = ("UnityWndClass",)


def _window_info(hwnd: int) -> tuple[str, str, int, int]:
    """取窗口的 `(类名, 标题, 宽, 高)`（失败项给空/0）。"""
    cls = ""
    title = ""
    width = height = 0
    try:
        buffer = ctypes.create_unicode_buffer(256)
        if _user32.GetClassNameW(hwnd, buffer, 256):
            cls = buffer.value
        length = _user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            text = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, text, length + 1)
            title = text.value
        rect = wintypes.RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            width = max(0, int(rect.right) - int(rect.left))
            height = max(0, int(rect.bottom) - int(rect.top))
    except Exception:  # noqa: BLE001
        pass
    return cls, title, width, height


def list_game_windows(keywords: tuple[str, ...],
                      process_names: tuple[str, ...] = ("Endfield.exe",)
                      ) -> list[dict[str, Any]]:
    """列出**游戏进程的所有可见顶层窗口**（含被排除的），供选择与"判据可见"用。

    返回每项：`{hwnd, title, cls, width, height, excluded}` —— `excluded=True` 表示它标题像
    覆盖层/辅助窗口（`EXCLUDED_TITLE_HINTS`），不会被选作发键目标。
    """
    if not _is_windows():
        return []
    wanted_proc = tuple(item.lower() for item in process_names if item)
    rows: list[dict[str, Any]] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) == os.getpid():
                return True
            basename = _process_basename(int(pid.value)).lower()
            if not basename or basename not in wanted_proc:
                return True                      # **只有游戏进程的窗口才算**
            cls, title, width, height = _window_info(int(hwnd))
            low = title.lower()
            rows.append({
                "hwnd": int(hwnd), "title": title, "cls": cls,
                "width": width, "height": height,
                "excluded": any(hint in low for hint in EXCLUDED_TITLE_HINTS),
            })
        except Exception:  # noqa: BLE001
            return True
        return True

    try:
        _user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    except Exception:  # noqa: BLE001
        return []
    return rows


def pick_game_window(rows: list[dict[str, Any]],
                     keywords: tuple[str, ...]) -> dict[str, Any] | None:
    """从候选里挑**游戏主窗口**：先剔覆盖层，再优先 Unity 类名、标题命中、最后比面积。"""
    usable = [row for row in rows if not row.get("excluded")]
    if not usable:
        return None
    lowered = tuple(item.lower() for item in keywords if item)

    def _score(row: dict[str, Any]) -> tuple[int, int, int]:
        title = str(row.get("title") or "")
        return (
            1 if row.get("cls") in PREFERRED_WINDOW_CLASSES else 0,
            1 if (title and any(item in title.lower() for item in lowered)) else 0,
            int(row.get("width") or 0) * int(row.get("height") or 0),
        )

    return max(usable, key=_score)


def find_game_window(keywords: tuple[str, ...],
                     process_names: tuple[str, ...] = ("Endfield.exe",)
                     ) -> tuple[int, str] | None:
    """找一个**属于游戏进程**的可见顶层窗口。返回 `(hwnd, title)`，找不到返回 `None`。

    判据分三层（每一层都是踩过坑之后加的）：

    ① **窗口所属进程的可执行名必须是 `Endfield.exe`**（默认）—— 第一版按**标题**找，
       结果把开着的浏览器标签页（标题含 "…Endfield…"）当成了游戏；标题**永不跨进程兜底**。

    ② **剔掉覆盖层/辅助窗口** —— Poser 的 `EndfieldPoserOverlay` 属于同一个
       `Endfield.exe` 进程、标题还含 "Endfield"，只按①挑会把 F10 打给它（2026-10-04 实测：
       用户报"热重载没生效"，日志里发键目标正是这个 overlay）。

    ③ 然后优先 **`UnityWndClass`**（Unity 引擎主窗口的类名），再按**窗口面积从大到小**
       选最大那个 —— 游戏主窗口总是最大、且不是覆盖层。
    """
    best = pick_game_window(list_game_windows(keywords, process_names), keywords)
    if best is None:
        return None
    return (int(best["hwnd"]), str(best.get("title") or ""))


def _user_ini_path(config: AppConfig) -> Path:
    """3DMigoto 的 `d3dx_user.ini`（persist 变量的落盘文件）。"""
    try:
        path = config.user_ini_path
        if path is not None:
            return Path(path)
    except Exception:  # noqa: BLE001
        pass
    return Path(getattr(config, "runtime_path", ".")) / "d3dx_user.ini"


def _safe_mtime(path: Path) -> float:
    """文件 mtime（取不到给 0.0）。"""
    try:
        return float(Path(path).stat().st_mtime)
    except OSError:
        return 0.0


def send_f10(config: AppConfig, *, log: Callable[[str], None] | None = None,
             keywords: tuple[str, ...] | None = None) -> dict[str, Any]:
    """给游戏窗口发一次 F10（= 3DMigoto 的 `config_reload`）。

    返回 `{ok, hwnd, window, keywords}` 或 `{ok: False, message}` —— **失败一定要给原因**，
    因为最常见的两种失败（没找到窗口 / 焦点被系统拒绝）用户都能自己处理。
    """
    def note(message: str) -> None:
        if log is not None:
            log(message)

    if not _is_windows():
        return {"ok": False, "message": "热重载只支持 Windows"}

    keys = keywords or window_keywords(config)
    rows = list_game_windows(keys)
    best = pick_game_window(rows, keys)
    if best is None:
        detail = "；".join(
            f"{row['title'] or '(无标题)'}[{row['cls']}|{row['width']}x{row['height']}"
            f"{'|已排除' if row['excluded'] else ''}]" for row in rows[:5]
        ) or "（Endfield.exe 进程下一个可见窗口都没有）"
        return {
            "ok": False,
            "message": "没找到可发键的游戏窗口（按进程名 Endfield.exe 找、并会跳过覆盖层）"
                       f" —— 候选：{detail}",
            "keywords": list(keys),
            "candidates": rows,
        }
    hwnd = int(best["hwnd"])
    title = str(best.get("title") or "")
    # **判据可见**（2026-10-04）：把候选与最终选中项都写进日志 —— 上次"没生效"就是因为
    # 选中的是 Poser 的覆盖层窗口，而当时的日志只写了标题，看不出选错。
    note("热重载: 候选窗口 " + "；".join(
        f"{row['title'] or '(无标题)'}[{row['cls']}|{row['width']}x{row['height']}"
        f"{'|已排除' if row['excluded'] else ''}]" for row in rows[:5]))
    note(f"热重载: 选中主窗口 {title!r} (hwnd={hwnd}, class={best.get('cls')}, "
         f"{best.get('width')}x{best.get('height')})，拉前台后发 F10")
    try:
        focused = _force_foreground(hwnd)
    except Exception as exc:  # noqa: BLE001 - 拉前台失败仍然试一次发键
        note(f"热重载: 拉前台失败（仍尝试发键）: {exc}")
        focused = False
    time.sleep(FOREGROUND_SETTLE_SECONDS)
    if not focused:
        focused = int(_user32.GetForegroundWindow() or 0) == hwnd
    if focused:
        note("热重载: 游戏窗口已在前台")
    else:
        note("热重载: ⚠ 游戏窗口**没能拿到前台** —— 3DMigoto 的 check_foreground_window "
             "会把这次按键丢掉，多半不生效（把游戏切到前台再点一次）")
    # **"F10 到底有没有被 3DMigoto 处理"的判据**：收到 F10 后它会把 persist 变量写回
    # `d3dx_user.ini`（官方文档：persist 变量在 exit 或 F10 时落盘）⇒ 看那个文件的 mtime 变没变。
    user_ini = _user_ini_path(config)
    before_mtime = _safe_mtime(user_ini)
    sent = 0
    try:
        for attempt in (1, 2):
            _send_key(VK_F10)
            sent += 1
            note(f"热重载: 已发送 F10（第 {attempt} 次，按下保持 {int(HOLD_SECONDS * 1000)}ms）")
            if attempt == 1:
                time.sleep(0.45)      # 补发一次：轮询型程序偶尔整帧错过（同面板合成键的教训）
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"发送 F10 失败: {exc}", "hwnd": hwnd, "window": title}
    time.sleep(0.6)
    after_mtime = _safe_mtime(user_ini)
    handled: bool | None = None
    if before_mtime and after_mtime:
        handled = after_mtime > before_mtime
        if handled:
            note(f"热重载: 3DMigoto 已响应（{user_ini.name} 被更新）")
        else:
            note(f"热重载: ⚠ 3DMigoto **没有**响应 F10（{user_ini.name} 时间戳没变）"
                 " —— 按键没被它读到，看上面那条「是否在前台」")
    if not focused:
        return {
            "ok": False, "hwnd": hwnd, "window": title, "focused": False, "sent": sent,
            "message": "F10 已发送，但**游戏窗口没能拿到前台** —— 3DMigoto 只在游戏是前台时"
                       "处理按键，这次多半不生效。请把游戏切到前台后再点一次热重载。",
        }
    note("热重载: 完成（3DMigoto 会重新加载配置/重扫 Mod）")
    return {"ok": True, "hwnd": hwnd, "window": title, "keywords": list(keys),
            "focused": True, "sent": sent}


def send_key(config: AppConfig, vk: int, *, label: str = "按键",
             keywords: tuple[str, ...] | None = None,
             log: Callable[[str], None] | None = None,
             repeat: int = 2, gap: float = 0.45) -> dict[str, Any]:
    """给游戏主窗口发一次**真实按键**（复用 `send_f10` 那套：选窗口 → 拉前台 → `SendInput`）。

    与 `send_f10` 的唯一区别：**不做 F10 特有的"`d3dx_user.ini` 有没有被更新"验证** ——
    那个判据只对 3DMigoto 的 `config_reload` 成立，对 **addon 自己的快捷键**（比如 DLSS5 的
    NR 开关）不适用。所以这里的成功判据只到"窗口确实在前台 + 键已发出"，其余如实回报。

    用途：`nr_autostart` 用它替用户在游戏里按一次 NR 开关（用户 2026-10-05 要求「全自动」）。
    仍然**必须 `SendInput` + 窗口在前台**（两条硬约束见模块头），并且按 `repeat` 补发一次
    —— 轮询 `GetAsyncKeyState` 的程序偶尔整帧错过（`HOLD_SECONDS` 的注释里有实测教训）。
    """
    def note(message: str) -> None:
        if log is not None:
            log(message)

    if not _is_windows():
        return {"ok": False, "message": "发键只支持 Windows"}

    keys = keywords or window_keywords(config)
    rows = list_game_windows(keys)
    best = pick_game_window(rows, keys)
    if best is None:
        detail = "；".join(
            f"{row['title'] or '(无标题)'}[{row['cls']}|{row['width']}x{row['height']}"
            f"{'|已排除' if row['excluded'] else ''}]" for row in rows[:5]
        ) or "（Endfield.exe 进程下一个可见窗口都没有）"
        return {"ok": False, "message": f"{label}: 没找到可发键的游戏窗口 —— 候选：{detail}",
                "keywords": list(keys), "candidates": rows}
    hwnd = int(best["hwnd"])
    title = str(best.get("title") or "")
    note(f"{label}: 目标主窗口 {title!r} (hwnd={hwnd}, class={best.get('cls')}, "
         f"{best.get('width')}x{best.get('height')})")
    try:
        focused = _force_foreground(hwnd)
    except Exception as exc:  # noqa: BLE001 - 拉前台失败仍然试一次发键
        note(f"{label}: 拉前台失败（仍尝试发键）: {exc}")
        focused = False
    time.sleep(FOREGROUND_SETTLE_SECONDS)
    if not focused:
        focused = int(_user32.GetForegroundWindow() or 0) == hwnd
    if not focused:
        return {"ok": False, "hwnd": hwnd, "window": title, "focused": False, "sent": 0,
                "message": f"{label}: 游戏窗口**没能拿到前台** —— 按键多半被丢掉"
                           "（把游戏切到前台后会自己重试）"}
    sent = 0
    attempts = max(1, int(repeat))
    try:
        for attempt in range(1, attempts + 1):
            _send_key(vk)
            sent += 1
            note(f"{label}: 已发送（第 {attempt} 次，按下保持 {int(HOLD_SECONDS * 1000)}ms）")
            if attempt < attempts:
                time.sleep(gap)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"{label}: 发送失败: {exc}", "hwnd": hwnd,
                "window": title, "focused": True, "sent": sent}
    note(f"{label}: 完成（目标窗口 {title!r}）")
    return {"ok": True, "hwnd": hwnd, "window": title, "focused": True, "sent": sent,
            "keywords": list(keys)}
