"""Magpie Experimental（**可选的扩展功能**）—— 画面级 AI 效果器。

用户 2026-10-01 要求：「做成拓展功能，在依赖上面加一个这个的开关，**默认关，关不下载**，
如果未下载，启动一栏这个就滑块变灰色，介绍加上需要在依赖页开启下载」；
以及「**默认关，需要在这个 dlss5 那里说明效果不如另外那个**」。

**它是什么**：[`SAOG0721/Magpie`](https://github.com/SAOG0721/Magpie) = `Blinue/Magpie` 的
**非官方实验性 fork**（默认分支 `experimental`，**GPL-3.0**）。原本是窗口放大工具，被扩成
"抓窗口画面 → 用效果组处理 → 全屏输出"的**画面级效果器**：

* 空间放大/锐化（Lanczos / FSR…）；
* 实验性时域超分（DLSS SR / FSR 2-4 / XeSS SR）；
* **DLSSNR**（同分辨率 SDR 画质处理：色调/结构/阴影/反射/辉光）—— 用的是
  `nvngx_dlssnr.dll` **310.8.0.0**，与我们随包那份**同版本**；它还额外提供
  "**RTX 40/50 社区兼容版**" DLL；
* 帧生成（DLSSFG / XeSSFG）。

**为什么值得接**：它**不碰游戏进程**（不需要往游戏里注入任何东西），所以能和游戏内
DLSS5 **叠加**，也能在 40 系机器上用社区兼容版 DLL 跑 NR。

**必须讲清的代价**（README 原文依据，别让用户以为它等于 DLSS5）：

* *"Magpie processes complete window images **without access to the game engine's full native
  motion vectors, depth, exposure or separated UI** … **not equivalent to native in-game
  DLSS/FSR/XeSS integration**"* —— 没有原生运动矢量/深度/UI 分离；
* 因此：**会有鬼影**、**文字与 UI 会一起被处理**（README 明说）；
* 所以它**只是可选扩展**，默认关闭，界面上要写明"效果不如游戏内 DLSS5"。

**另外两条硬事实**（决定它怎么接）：

* **主包约 467 MB**（`Magpie-Experimental-x64.zip` = 489,787,536 B，v0.6.8）→ 默认关、
  关着时**任何链路都不下载**，只有用户主动去依赖页打开才下载（下载前还要确认体积）；
* **只发预发布版**（`/releases/latest` 返回 404）→ 必须走 `github.releases_list()`，
  和 Endfield Poser 是同一情况。

**不随包分发**（GPL-3.0 + 非官方实验构建），我们只做"下载 + 解压 + 启动"。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

Log = Callable[[str], None] | None

REPO = "SAOG0721/Magpie"
UPSTREAM_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{UPSTREAM_URL}/releases"
# 主包（必选完整包）。Release 里还有可选的 DLSSNR-DLL-Options-*.zip 与 NGX_OTA_Switch.bat，
# 我们**不**自动取那两个 —— 它们是进阶替换件，让用户自己去 Release 页拿。
ASSET_PATTERN = "Magpie-Experimental-x64.zip"
EXE_NAME = "Magpie.exe"
LICENSE_ID = "GPL-3.0"
LICENSE_NOTE = (
    "Magpie Experimental 是 Blinue/Magpie 的非官方实验性 fork，"
    "以 GPL-3.0 分发；本程序只负责下载与启动，不随包分发它的任何文件。"
)
# 主包体积（v0.6.8 实测 489,787,536 B）——界面里要显示，下载前要确认
APPROX_BYTES = 489_787_536
DISPLAY = "Magpie Experimental（画面级 AI 效果器 · 可选扩展）"

# 效果说明：**必须让用户知道它不如游戏内 DLSS5**（用户明确要求写这句）
EFFECT_NOTE = (
    "Magpie 抓的是**已经渲染完的窗口画面**，拿不到游戏引擎的原生运动矢量、深度、曝光，"
    "也没法把 UI 单独分出来 —— 所以它是**画面级后处理，效果不如游戏内 DLSS5**："
    "动态画面可能出现**鬼影**，**文字与 UI 会一起被处理**（原作者 README 明确写了这一条）。"
    "它的价值在于：① 能与游戏内 DLSS5 **叠加**（多层 NR）；② 不碰游戏进程，"
    "40 系机器也能用它的「RTX 40/50 社区兼容版」NR 运行库。"
)


def _marker_path(config: AppConfig) -> Path:
    return config.magpie_path / ".endfieldmodcontroller.json"


def read_marker(config: AppConfig) -> dict[str, Any]:
    path = _marker_path(config)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_marker(config: AppConfig, payload: dict[str, Any]) -> None:
    try:
        from . import fsutil

        fsutil.write_text_atomic(
            _marker_path(config),
            json.dumps(payload, ensure_ascii=False, indent=2),
            newline="\n",
        )
    except (OSError, ValueError):
        pass


def exe_path(config: AppConfig) -> Path | None:
    """`Magpie.exe` 在哪（解压后常见两种层级：直接在里面，或套一层目录）。"""
    root = config.magpie_path
    direct = root / EXE_NAME
    if direct.is_file():
        return direct
    try:
        for candidate in sorted(root.rglob(EXE_NAME)):
            if candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def installed(config: AppConfig) -> bool:
    return exe_path(config) is not None


def version(config: AppConfig) -> str:
    return str(read_marker(config).get("version") or "")


def status(config: AppConfig) -> dict[str, Any]:
    """给前端的状态（依赖页开关 / 启动页滑块 / 设置页都用它）。"""
    exe = exe_path(config)
    return {
        "enabled": bool(getattr(config, "magpie_enabled", False)),
        "installed": exe is not None,
        "exe": str(exe) if exe else "",
        "dir": str(config.magpie_path),
        "version": version(config),
        "approx_bytes": APPROX_BYTES,
        "license": LICENSE_ID,
        "license_note": LICENSE_NOTE,
        "repo": REPO,
        "url": UPSTREAM_URL,
        "releases_url": RELEASES_URL,
        "effect_note": EFFECT_NOTE,
        "display": DISPLAY,
        # 启动页那一栏是否可用：**未下载就灰掉**并提示去依赖页（用户明确要求）
        "can_toggle": exe is not None,
    }


def launch(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """启动 Magpie（它自己是单实例、会在任务栏托盘里）。"""
    exe = exe_path(config)
    if exe is None:
        return {
            "ok": False,
            "message": "还没下载 Magpie —— 请到依赖页把「Magpie Experimental」那个开关打开（约 467 MB）。",
        }
    try:
        # Magpie 是 GUI 程序：直接交给系统启动（若它的 manifest 要求管理员，系统会弹 UAC）。
        os.startfile(str(exe))  # noqa: S606 - 启动用户自己选择安装的第三方程序
    except OSError as exc:
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        except OSError as exc2:  # noqa: BLE001
            return {"ok": False, "message": f"启动 Magpie 失败：{exc2 or exc}"}
    if callable(log):
        log(f"已启动 Magpie：{exe}")
    return {"ok": True, "exe": str(exe), "message": "已启动 Magpie（它在托盘里，选好效果组与目标窗口后按它的快捷键生效）"}


def open_dir(config: AppConfig) -> dict[str, Any]:
    """打开 Magpie 目录（没装就打开它会落地的位置）。"""
    root = config.magpie_path
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "message": f"创建目录失败：{exc}"}
    return {"ok": True, "path": str(root)}
