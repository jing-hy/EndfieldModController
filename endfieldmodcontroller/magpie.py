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


# ---------------------------------------------------------------------------
# 一键配置：让 Magpie 的**默认 profile** 直接使用 DLSSNR（= 游戏内 DLSS5 的那一类）
# ---------------------------------------------------------------------------
# 用户原话：「**我需要一键配置**，我刚才进去看大力喜鹊（Magpie）的时候**连 dlss5 在哪都没找到**」
# 以及「**是一键启动的时候自动配置**」。
#
# 为什么他找不到：Magpie 界面上**没有叫 "DLSS5" 的效果** —— 它叫 **DLSSNR**
# （`DLSSNR\DLSSNR_AI_Filter`，参数名 style / intensity / 局部色调 / 局部结构 / 皮肤结构 /
# 界面修正，与游戏内 DLSS5 面板几乎一一对应）。所以"一键配置" = 我们替他把默认 profile
# 选成 DLSSNR。
#
# **安全边界（很重要）**：
# * 只改它**自己已经生成**的 `config.json`（便携 `<exe>/config/v4e/`，否则
#   `%LOCALAPPDATA%\Magpie\config\v4e\`）—— **我们绝不凭空造整份配置**（字段太多，
#   猜错会毁掉他的设置）；
# * **Magpie 正在运行时不写** —— 它退出时会按内存里的状态整份写回，会把我们的改动冲掉
#   （和 XXMI 那次"启动按钮消失"是同一个教训）；
# * 写前备份一份 `.mc.bak`、**写后回读校验**、对不上就从备份回滚；
# * **幂等**：已经是 DLSSNR 就什么都不做。
# * ⚠️ 改了别人的配置属于"动外部对象"，界面上要能看见我们改了什么、以及怎么撤销。
DLSSNR_MODE_NAME = "DLSSNR"
# 参数取自上游 `presets/ScalingModes-v0.6.5-experimental.json` 的 DLSSNR 组（默认值）
DLSSNR_EFFECTS = [
    {
        "name": "DLSSNR\\DLSSNR_AI_Filter",
        "parameters": {
            "style": 0,
            "intensity": 1,
            "residualSaturation": 1,
            "residualLightness": 1,
            "shadowStructureMultiplier": 1,
            "reflectionGlowMultiplier": 1,
            "localToneStrength": 1,
            "localStructureStrength": 1,
            "skinStructureStrength": -1,
            "useAutoMask": 0,
            "uiCorrection": 0,
            "motionVectorQuality": 2,
        },
    }
]
DLSSNR_MODE = {"name": DLSSNR_MODE_NAME, "effects": DLSSNR_EFFECTS}


def config_path(config: AppConfig) -> Path | None:
    """Magpie 的 `config.json` 在哪（**只管找，不创建**）。

    路径规则照它的源码 `src/Magpie/ConfigLocations.h`：便携模式 = `<exe目录>/config/v4e/`，
    否则 = `%LOCALAPPDATA%/Magpie/config/v4e/`。
    """
    candidates: list[Path] = []
    exe = exe_path(config)
    if exe is not None:
        candidates.append(exe.parent / "config" / "v4e" / "config.json")
        candidates.append(exe.parent / "config" / "config.json")      # 旧版布局
    local = os.environ.get("LOCALAPPDATA") or ""
    if local:
        candidates.append(Path(local) / "Magpie" / "config" / "v4e" / "config.json")
        candidates.append(Path(local) / "Magpie" / "config" / "v4" / "config.json")
    for path in candidates:
        if path.is_file():
            return path
    return None


def running() -> bool:
    """Magpie 是否正在运行（在跑就不能改它的配置）。"""
    try:
        import subprocess

        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Magpie.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "magpie.exe" in (out.stdout or "").lower()
    except Exception:  # noqa: BLE001
        return False


def _dlssnr_index(data: Any) -> int | None:
    """DLSSNR 在顶层 `scalingModes` 数组里的索引。

    ⚠️ **`profile.scalingMode` 存的是这个数组的整数索引**，不是名字、也不是内嵌对象 ——
    证据是它自己的序列化代码：写出 `writer.Key("scalingMode"); writer.Int(profile.scalingMode);`、
    读入 `JsonHelper::ReadInt(profileObj, "scalingMode", profile.scalingMode);`
    （2026-10-01 读 `src/Magpie/AppSettings.cpp` 确认；我第一版按"字符串/对象"写是**错的**，
    那种值它读不出来，等于没配）。
    """
    modes = data.get("scalingModes") if isinstance(data, dict) else None
    if not isinstance(modes, list):
        return None
    for i, mode in enumerate(modes):
        if isinstance(mode, dict) and str(mode.get("name") or "").strip().lower() == DLSSNR_MODE_NAME.lower():
            return i
    return None


def _ensure_dlssnr_mode(data: dict) -> int:
    """拿到 DLSSNR 的索引；他配置里没有（被删过）就**照它自己的格式补一条**。"""
    index = _dlssnr_index(data)
    if index is not None:
        return index
    modes = data.get("scalingModes")
    if not isinstance(modes, list):
        modes = []
        data["scalingModes"] = modes
    modes.append(json.loads(json.dumps(DLSSNR_MODE)))   # 深拷贝，别让调用方改到常量
    return len(modes) - 1


def ensure_configured(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """一键启动时把 Magpie 配好（让默认 profile 用 DLSSNR）。**幂等、可回滚。**"""
    from . import fsutil

    def note(message: str) -> None:
        if callable(log):
            log(message)

    if not getattr(config, "magpie_enabled", False):
        return {"ok": True, "changed": False, "reason": "disabled"}
    if not installed(config):
        return {"ok": True, "changed": False, "reason": "not_installed"}

    path = config_path(config)
    if path is None:
        return {
            "ok": True, "changed": False, "reason": "no_config_yet",
            "message": "Magpie 还没生成过配置 —— 先打开它一次（它会自己写出 config.json），"
                       "之后每次「一键启动」都会自动帮你把默认模式设成 DLSSNR（也就是这里的 DLSS5 那一类）。",
        }
    if running():
        return {
            "ok": False, "changed": False, "reason": "magpie_running",
            "message": "Magpie 正在运行，先退出它再改配置 —— 否则它退出时会整份写回、把改动冲掉。",
        }

    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "changed": False, "reason": "read_failed", "message": f"读配置失败：{exc}"}
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, list) or not profiles or not isinstance(profiles[0], dict):
        return {"ok": False, "changed": False, "reason": "unknown_schema",
                "message": f"配置结构不认识（{path} 里没有 profiles[0]）—— 不改它。"}
    current = profiles[0].get("scalingMode")
    target_index = _ensure_dlssnr_mode(data)
    if current == target_index:
        return {"ok": True, "changed": False, "reason": "already", "message": "Magpie 默认模式已经是 DLSSNR。"}

    backup = path.with_name(path.name + ".mc.bak")
    try:
        if not backup.is_file():          # 只锁存一次，别把好备份覆盖成"改过之后"的
            import shutil

            shutil.copy2(path, backup)
        # **写整数索引**（它就是这么存的 —— 见 `_dlssnr_index` 的注释）
        profiles[0]["scalingMode"] = int(target_index)
        fsutil.write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2), newline="\n")
        # 回读校验；对不上就回滚
        check = json.loads(path.read_text(encoding="utf-8"))
        ok = (check.get("profiles") or [{}])[0].get("scalingMode") == target_index
        if not ok:
            raise ValueError("回读校验失败")
    except Exception as exc:  # noqa: BLE001
        try:
            if backup.is_file():
                import shutil

                shutil.copy2(backup, path)
        except OSError:
            pass
        return {"ok": False, "changed": False, "reason": "write_failed",
                "message": f"写 Magpie 配置失败（已尝试回滚）：{exc}"}
    note(f"Magpie 已自动配置：默认模式 → DLSSNR（改动前的配置备份在 {backup.name}）")
    return {
        "ok": True, "changed": True, "reason": "configured",
        "backup": str(backup),
        "message": "已把 Magpie 的默认模式设成 DLSSNR（= 这里的 DLSS5 那一类）。"
                   "打开 Magpie 选好终末地窗口、按它 Home 页显示的快捷键就会生效。",
    }


# ---------------------------------------------------------------------------
# 随游戏自动开关（用户 2026-10-01：「**需要的是你接管它的开关，在终末地开始运行的时候
# 打开，终末地退出的时候关闭**」）
# ---------------------------------------------------------------------------
# 接在崩溃监控那条已有的游戏生命周期跟踪里（`crashwatch.start_watch()` 的"等进程出现 /
# 等进程退出"两处），所以**只有走「一键启动」**才会自动开关 —— 这是刻意的：手动双击
# XXMI 启动游戏时控制器并不知道，不该去动 Magpie。
#
# **只关我们自己启动的那个**：如果 attach 时 Magpie 已经在跑（用户自己开的），我们既不
# 重启它、也不在游戏退出时关它 —— 免得误杀用户正在用的东西。
_ATTACHED_BY_US: dict[str, bool] = {"started": False}


def attach_to_game(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """终末地开始运行时：按需把 Magpie 打开。"""
    if not getattr(config, "magpie_enabled", False):
        return {"ok": True, "skipped": "disabled"}
    if not installed(config):
        return {"ok": True, "skipped": "not_installed"}
    if running():
        return {"ok": True, "skipped": "already_running",
                "message": "Magpie 本来就在跑（你自己开的）—— 不动它，退出游戏时也不会替你关。"}
    result = launch(config, log=log)
    _ATTACHED_BY_US["started"] = bool(result.get("ok"))
    if result.get("ok") and callable(log):
        log("Magpie: 随游戏一起启动（游戏退出时会自动关闭）")
    return result


def detach_from_game(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """终末地退出后：把我们随游戏启动的 Magpie 关掉。"""
    if not _ATTACHED_BY_US.get("started"):
        return {"ok": True, "skipped": "not_started_by_us"}
    _ATTACHED_BY_US["started"] = False
    try:
        subprocess.run(
            ["taskkill", "/IM", EXE_NAME, "/F"],
            capture_output=True, text=True, timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"关闭 Magpie 失败：{exc}"}
    if callable(log):
        log("Magpie: 已随游戏退出关闭")
    return {"ok": True, "closed": True}
