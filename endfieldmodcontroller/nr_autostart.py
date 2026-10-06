"""NR 自动开启：等第一人称插件的相机 hook 装好之后，替用户在游戏里按一次 NR 开关。

## 为什么要有它（2026-10-05 定案 + 用户要求「全自动」）

DLSS5 的 NR 与 **RenoDX Endfield Enhancer 的相机 hook 抢同一块 trampoline 空间**：
NR 一旦**抢在前面**激活，相机 hook 就会 `error 8`（分配 hook trampoline 内存失败）装不上
⇒ 第一人称面板报「不支持相机控制」；反过来先装 hook、后开 NR，两边就都能用。

对照证据（同一台机器、同一天、同一个 enhancer 版本）：

| | 失败那次 | 成功那次 |
|---|---|---|
| ini 里的 `NeuralUplift` | 1（启动就开） | 0（进游戏后才开） |
| `feature 18 created` | **18:05:42**（早） | 18:23:23（晚） |
| 相机 hook | 18:06:28（晚 46 秒）❌ | **18:22:33**（早 50 秒）✅ |

所以启动前由 `initialize._check_defer_nr_until_camera_hook` 把 `NeuralUplift` 压成 0
（保证相机 hook 先装上），**本模块负责把 NR 补开** —— 用户要的是全自动，
不能让他每次进游戏手动按一下。

## 判据（每一步都要能回答"凭什么"）

* **什么时候按**：ReShade 日志里出现 `Endfield enhancer: Camera controls installed.`
  —— 相机 hook 已经装好了；
* **按哪个键**：**每次都从日志里现读**（addon 启动时会打印 `hotkeys: NR toggle F6`），
  **不写死 F6** —— 用户改了键位、或上游换了默认键，这里都跟得上
  （用户 2026-10-05 明确要求「模拟按钮每次都去确认下设的是那个键」）。
  读不到才退回 F6，**并把"没读到、用了默认值"写进日志**；
* **NR 已经开着就不按**：日志里若已出现 `feature 18 created` / `evaluation succeeded`，
  说明它已经在出帧（多半是用户自己开过了），再按一次会把它**关掉**；
* **hook 装失败就明说**（2026-10-05 加）：日志里出现 `camera hook installation failed`
  时**明确报出来**并就此打住 —— 以前"还没走到那一步"与"装失败了"都表现为"一直等"，
  用户看到的就是"没自动开 NR"，而日志里什么线索都没有（实测踩到）；
* **等太久也留一行诊断**（2026-10-05 加）：`_WAIT_DIAG_SECONDS` 秒后既没 `installed`
  也没 `failed`，就写一行"还没等到 + 已读到多少日志"，把"没进到场景"这个最常见原因
  摆在日志里；
* **一次运行只按一次**（`sent` 置位后不再动）。

调用方：`diagnostics._monitor_process` —— 检测到游戏进程时 `arm()`，之后每次轮询 `poll()`。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

# 本次运行的日志累积上限（ReShade.log 单次运行通常几十 KB，2 MB 是保险丝）
_TEXT_LIMIT = 2 * 1024 * 1024

# 「相机 hook 装好了」的唯一判据（enhancer 自己打的原文）
_HOOK_MARK = "Camera controls installed."
# 「相机 hook 装失败了」的判据（同样是 enhancer 自己的原文）—— 看到它就**明确报出来**：
# 这次不能自动开 NR（NR 抢在它前面会把相机控制弄没），而不是继续默默等。
_HOOK_FAIL_MARK = "camera hook installation failed"
# 等太久的兜底诊断（秒）：到点若既没 installed 也没 failed，就写一行"还没等到"。
# 2026-10-05 用户实测「又测了一次，就是没自动开 nr」暴露的正是这个盲区 ——
# 那次 ReShade 日志里 enhancer 只有"已注册"一行，**两种字样都没有**（游戏 87 秒内没进场景）。
_WAIT_DIAG_SECONDS = 60.0
# 「NR 已经在出帧」的两条判据（任一命中就不该再按 —— 再按会把它关掉）
_NR_ACTIVE_MARKS = ("feature 18 created", "evaluation succeeded")
# addon 启动行里的快捷键声明，例如：
#   ... DLSS5 Generic: RenoDX DLSS5 Generic v4.7 (...) loaded (hotkeys: NR toggle F6, screenshot F5) | ...
# ⚠️ 字符类要**带上小键盘的符号**（2026-10-06）：以前只收 `[A-Za-z0-9]`，
#    于是 `NUM+` / `NUM-` 只匹配到 `NUM`，解析成 NumLock 而不是加减号。
_HOTKEY_RE = re.compile(r"hotkeys?\s*:\s*NR\s+toggle\s+([A-Za-z0-9+*/.\-]+)", re.I)

VK_F6 = 0x75  # 兜底：读不到键位时用它（addon 的出厂默认就是 F6）

# 常见键名 → 虚拟键码（够覆盖 addon 那套默认；表里没有的名字会如实报"认不出"）
_VK_BY_NAME: dict[str, int] = {f"F{i}": 0x6F + i for i in range(1, 25)}   # F1=0x70 … F24=0x87
_VK_BY_NAME.update({
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "SPACE": 0x20, "TAB": 0x09,
    # ⚠️ **小键盘一族要认全**（2026-10-06 修）：反馈者把 NR 快捷键改成了小键盘键，
    #    而 addon 在日志里把它缩写成 `NUM`（原文 `hotkeys: NR toggle NUM`）。
    #    以前表里只有 `NUMPAD0..9`，`NUM` 认不出 ⇒ **退回按了 F6** ⇒ NR 从未被打开
    #    （他那台的现象是"能进游戏、面板停在成功NR帧 4" —— 那几帧就是这次误按留下的）。
    "NUM": 0x90, "NUMLOCK": 0x90,
    "NUM+": 0x6B, "NUM-": 0x6D, "NUM*": 0x6A, "NUM/": 0x6F, "NUM.": 0x6E, "NUM,": 0x6E,
    "ADD": 0x6B, "SUBTRACT": 0x6D, "MULTIPLY": 0x6A, "DIVIDE": 0x6F, "DECIMAL": 0x6E,
    "NUMPAD+": 0x6B, "NUMPAD-": 0x6D, "NUMPAD*": 0x6A, "NUMPAD/": 0x6F, "NUMPAD.": 0x6E,
})
for _i in range(10):
    _VK_BY_NAME[f"NUMPAD{_i}"] = 0x60 + _i
    _VK_BY_NAME.setdefault(f"NUM{_i}", 0x60 + _i)
for _ch in "0123456789":
    _VK_BY_NAME[_ch] = 0x30 + int(_ch)
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _VK_BY_NAME[_ch] = ord(_ch)

_STATE: dict[str, Any] = {
    "armed": False,
    "log_pos": 0,
    "text": "",
    "hook_seen": False,
    "sent": False,
    "note": "",
    "armed_at": 0.0,
    "wait_logged": False,
}


def reshade_log_path(config: AppConfig) -> Path:
    """生效那份 `ReShade.log`（ReShade 以 `RESHADE_BASE_PATH_OVERRIDE` 为基准目录写它）。"""
    return Path(config.reshade_runtime_path) / "ReShade.log"


def reset() -> None:
    """清空状态（换了游戏进程 / 监视重开时调）。"""
    _STATE.update({"armed": False, "log_pos": 0, "text": "", "hook_seen": False,
                   "sent": False, "note": "", "armed_at": 0.0, "wait_logged": False})


def _size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _read_new(path: Path) -> str:
    """读 `log_pos` 之后新增的内容并推进位置（日志被重建时从头读）。"""
    size = _size(path)
    pos = int(_STATE.get("log_pos") or 0)
    if size < pos:           # 文件被截断/重建 ⇒ 当作新的一次运行
        pos = 0
    if size <= pos:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(pos)
            text = handle.read()
    except OSError:
        return ""
    _STATE["log_pos"] = size
    return text


def arm(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """游戏进程刚出现时调：记下日志当前位置，只盯**本次运行**新增的内容。"""
    reset()
    path = reshade_log_path(config)
    _STATE["log_pos"] = _size(path)
    _STATE["armed"] = True
    _STATE["armed_at"] = time.time()
    if log is not None:
        log(f"NR 自动开启: 已就位（等相机 hook 装好后按一次 NR 键；日志 {path}）")
    return dict(_STATE)


def _resolve_key(text: str) -> tuple[int, str]:
    """从日志文本里解析 NR 的快捷键，返回 `(vk, 说明)`。

    **每次都现读**（用户要求）—— 这里不写死 F6；认不出时才退回 F6，并说明原因。
    """
    matches = _HOTKEY_RE.findall(text or "")
    if not matches:
        return VK_F6, "日志里没有 `hotkeys: NR toggle …` —— 用 addon 的出厂默认 F6"
    name = str(matches[-1]).strip().upper()
    vk = _VK_BY_NAME.get(name)
    if vk is None:
        return VK_F6, f"日志里的 NR 键 {name!r} 认不出（不在支持的键表里）—— 退回默认 F6"
    return vk, f"日志里的 NR 键 = {name}（vk=0x{vk:02X}）"


def poll(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """每次轮询调一次（轻量：没有新增日志就立刻返回）。"""
    if not _STATE.get("armed") or _STATE.get("sent"):
        return {"ok": True, "action": "skip", "sent": bool(_STATE.get("sent"))}
    # ★ **启动就开时整条路都停用**（2026-10-06）：NR 已经在 `NeuralUplift=1` 下打开，
    #   不需要再等相机 hook、也不需要模拟按键（这一路的唯一价值是"等 hook"，而它
    #   只在第一人称启用时才会出现 —— 不用第一人称的机器会永远卡在这里）。
    # ★ **只有"不用第一人称"时才整条跳过**（2026-10-06 改）：
    #   要用第一人称的机器上，`initialize` 会把 `NeuralUplift` 压成 0 ⇒ 必须靠这条路
    #   在相机 hook 装好后补按一次 NR 键，否则 NR 永远不开。
    from . import reshade_integration

    if (getattr(config, "start_dlss5_nr_immediately", True)
            and not reshade_integration.firstperson_camera_wanted(config)):
        _STATE["sent"] = True
        return {"ok": True, "action": "skip", "reason": "NR 已设为启动就开，无需补按"}
    if not getattr(config, "auto_enable_nr_after_camera_hook", True):
        _STATE["sent"] = True
        return {"ok": True, "action": "skip", "reason": "开关已关闭"}

    fresh = _read_new(reshade_log_path(config))
    if fresh:
        _STATE["text"] = (str(_STATE.get("text") or "") + fresh)[-_TEXT_LIMIT:]
    text = str(_STATE.get("text") or "")
    if not text:
        return {"ok": True, "action": "wait"}

    # NR 已经在出帧 ⇒ 用户自己开过了，再按一次等于把它关掉
    if any(mark in text for mark in _NR_ACTIVE_MARKS):
        _STATE["sent"] = True
        _STATE["note"] = "NR 已在出帧（用户自己开过）—— 不按，免得把它关掉"
        if log is not None:
            log("NR 自动开启: " + str(_STATE["note"]))
        return {"ok": True, "action": "skip", "reason": "nr_active"}

    # ⚠️ **相机 hook 装失败** ⇒ 明确报出来、就此打住（2026-10-05 加）。
    #    以前"还没走到那一步"和"装失败了"都表现为"一直等"，用户看到的现象是
    #    "没自动开 NR"，而日志里连一条线索都没有 —— 实测踩过（enhancer 只打了
    #    "Registered add-on" 一行，`installed` / `failed` 两种字样都没有）。
    if _HOOK_FAIL_MARK in text.lower():
        _STATE["sent"] = True
        _STATE["note"] = ("enhancer 报「相机 hook 安装失败」—— 这次不能自动开 NR"
                          "（NR 抢在它前面会把第一人称的相机控制弄没）")
        if log is not None:
            log("NR 自动开启: " + str(_STATE["note"]))
        return {"ok": True, "action": "skip", "reason": "hook_failed"}

    if _HOOK_MARK not in text:
        # ★ 等太久的兜底诊断（2026-10-05 加）：把"还没进到场景"这个最常见原因摆进日志，
        #   而不是让用户对着"已就位"干等。只写一次，不刷屏。
        waited = time.time() - float(_STATE.get("armed_at") or 0.0)
        if waited >= _WAIT_DIAG_SECONDS and not _STATE.get("wait_logged"):
            _STATE["wait_logged"] = True
            if log is not None:
                log(f"NR 自动开启: 已等 {waited:.0f} 秒还没等到「{_HOOK_MARK}」"
                    f"（也没有 hook 失败记录）—— 多半是**还没进到游戏场景**"
                    f"（相机对象尚未创建）；本次已读到 ReShade 日志 {len(text):,} 字符")
        return {"ok": True, "action": "wait"}      # 相机 hook 还没装好

    vk, why = _resolve_key(text)
    if log is not None:
        log(f"NR 自动开启: 相机 hook 已就位，准备按 NR 键 —— {why}")
    from . import hot_reload

    result = hot_reload.send_key(config, vk, label="NR 自动开启",
                                 log=(lambda message: log(message)) if log else None)
    if result.get("ok"):
        _STATE["sent"] = True
        _STATE["note"] = f"已按 NR 键（{why}）"
        if log is not None:
            log("NR 自动开启: " + str(_STATE["note"]))
        return {"ok": True, "action": "sent", "vk": vk, "reason": why, "result": result}
    # 窗口没拿到前台之类：**不置 sent**，下一轮自然会重试（用户切回游戏就好了）
    if log is not None:
        log(f"NR 自动开启: 这次没按成（{result.get('message')}）—— 会继续重试")
    return {"ok": False, "action": "retry", "message": result.get("message"), "result": result}


def state() -> dict[str, Any]:
    """当前状态（排查 / 测试用）。"""
    return dict(_STATE)
