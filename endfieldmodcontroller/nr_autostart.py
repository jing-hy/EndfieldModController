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
* **一次运行只按一次**（`sent` 置位后不再动）。

调用方：`diagnostics._monitor_process` —— 检测到游戏进程时 `arm()`，之后每次轮询 `poll()`。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

# 本次运行的日志累积上限（ReShade.log 单次运行通常几十 KB，2 MB 是保险丝）
_TEXT_LIMIT = 2 * 1024 * 1024

# 「相机 hook 装好了」的唯一判据（enhancer 自己打的原文）
_HOOK_MARK = "Camera controls installed."
# 「NR 已经在出帧」的两条判据（任一命中就不该再按 —— 再按会把它关掉）
_NR_ACTIVE_MARKS = ("feature 18 created", "evaluation succeeded")
# addon 启动行里的快捷键声明，例如：
#   ... DLSS5 Generic: RenoDX DLSS5 Generic v4.7 (...) loaded (hotkeys: NR toggle F6, screenshot F5) | ...
_HOTKEY_RE = re.compile(r"hotkeys?\s*:\s*NR\s+toggle\s+([A-Za-z0-9]+)", re.I)

VK_F6 = 0x75  # 兜底：读不到键位时用它（addon 的出厂默认就是 F6）

# 常见键名 → 虚拟键码（够覆盖 addon 那套默认；表里没有的名字会如实报"认不出"）
_VK_BY_NAME: dict[str, int] = {f"F{i}": 0x6F + i for i in range(1, 25)}   # F1=0x70 … F24=0x87
_VK_BY_NAME.update({
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "SPACE": 0x20, "TAB": 0x09,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
})
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
}


def reshade_log_path(config: AppConfig) -> Path:
    """生效那份 `ReShade.log`（ReShade 以 `RESHADE_BASE_PATH_OVERRIDE` 为基准目录写它）。"""
    return Path(config.reshade_runtime_path) / "ReShade.log"


def reset() -> None:
    """清空状态（换了游戏进程 / 监视重开时调）。"""
    _STATE.update({"armed": False, "log_pos": 0, "text": "", "hook_seen": False,
                   "sent": False, "note": ""})


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

    if _HOOK_MARK not in text:
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
