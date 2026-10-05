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
    return Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "Hypergryph" / "Endfield"


def _crash_root() -> Path:
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("TEMP", "")):
        if not base:
            continue
        root = Path(base) / "Temp" / "Hypergryph" / "Endfield" / "Crashes"
        if root.is_dir():
            return root
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / "Hypergryph" / "Endfield" / "Crashes"


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

            # ② 等进程退出 —— **每 5 秒采一次样**（2026-10-01 用户要求"日志包一次抓全"）：
            #    "跑四十多秒就闪退"这种问题，静态快照看不出任何东西；
            #    必须留下**时间线**（哪个模块在哪一秒才加载、内存/句柄怎么涨、日志有没有停）。
            #    采样增量落盘，即使进程被强杀也已写好前面几次。
            from . import watchsample

            watchsample.reset(config)
            known_modules: set[str] = set()
            last_sample = 0.0
            while time.time() < deadline:
                if not _process_ids():
                    break
                now = time.time()
                if now - last_sample >= 5.0:
                    try:
                        entry = watchsample.sample(
                            pid,
                            known_modules=known_modules,
                            feed_log=Path(config.dlss5_path) / "dlss5-feed.log",
                            reshade_log=Path(config.dlss5_path) / "ReShade.log",
                        )
                        if entry:
                            watchsample.append(config, entry)
                            known_modules = {os.path.basename(m).lower()
                                             for m in (entry.get("modules") or [])}
                    except Exception as exc:  # noqa: BLE001 —— 采样失败绝不打断跟踪
                        _emit(f"崩溃监控: 采样失败 {exc}")
                    last_sample = now
                time.sleep(1.0)
            exit_time = time.time()
            alive = exit_time - started
            _emit(f"崩溃监控: 游戏已退出（存活 {alive:.0f} 秒），正在收集现场…")

            # ③ 收集现场 + 写报告 + 打崩溃包
            # ⚠️ 等 **6 秒**（2026-10-05 由 3 秒加长）：Windows 的 **WER 报告**
            #    （`AppCrash_*.wer`，里面写着"故障模块 + 异常代码"）是崩溃取证里最硬的一手材料，
            #    而它由 WerFault 在进程终止后**几秒内**才落盘；等 3 秒时常常还没写完，
            #    于是"真崩了"被判成"未发现崩溃迹象"（2026-10-05 那份诊断包里 8 次真崩
            #    全是这个下场）。多等这 3 秒只影响崩溃包生成时间，换的是判据不再漏。
            time.sleep(6.0)   # 等崩溃报告（CrashSight / WER / 游戏自身的 Crash_* 目录）落盘
            evidence = collect_evidence(config, started_at=started, exit_time=exit_time, alive_seconds=alive)
            path = write_report(config, evidence)
            crashed = is_crash(evidence)
            _emit(f"崩溃监控: {'检测到崩溃' if crashed else '未检测到崩溃（正常退出）'}，报告: {path.name}")

            # ③-a **记一笔"这次启动算成功还是失败"**（2026-10-05 用户要求）：
            #     连续 3 次失败 ⇒ 前端弹「强力修复」。判据在 `record_launch_result` 里
            #     复用 `combo_succeeded`，所以"静默闪退"也计数（不能只数崩溃 —— 反馈者那台
            #     一条 WER 都没有，只数崩溃就永远等不到这个弹窗）。
            try:
                outcome = record_launch_result(config, evidence, log=_emit)
                _WATCH["launch_failure"] = outcome
            except Exception as exc:  # noqa: BLE001 —— 记账失败绝不影响崩溃取证
                _emit(f"崩溃监控: 记录启动结果失败（忽略）: {exc}")
            try:
                bundle = make_bundle(config, evidence, log=_emit)
                # 只有真的崩了才让前端弹窗提示反馈；正常退出只留日志与包，不打扰用户
                if crashed:
                    _WATCH["bundle"] = bundle
                _emit(f"崩溃监控: 崩溃包已就绪（含终末地日志 {len(bundle.get('game_logs') or [])} 份）"
                      + ("" if crashed else "，正常退出不提示"))
            except Exception as exc:  # noqa: BLE001
                _emit(f"崩溃监控: 打包失败 {exc}")

            # ③-b 崩溃后的**建议**（用户 2026-10-05：「崩溃不要卸掉功能，应该弹窗建议清空
            #      依赖并重新下载重试」）。这里**只产出建议、不动任何开关**；
            #      前端弹窗据此多给一个「清空依赖并重新下载」按钮，点不点由用户决定。
            try:
                advice = crash_advice(config, evidence)
                if advice:
                    _WATCH["advice"] = advice
                    if isinstance(bundle, dict):
                        bundle["advice"] = advice
                    _emit("崩溃监控: 建议 —— " + str(advice.get("title") or ""))
            except Exception as exc:  # noqa: BLE001 —— 建议算不出来不该影响崩溃包本身
                _emit(f"崩溃监控: 生成建议失败（忽略）: {exc}")
        except Exception as exc:  # noqa: BLE001
            _emit(f"崩溃监控异常: {exc}")
        finally:
            _WATCH["running"] = False
            _WATCH["pid"] = None

    thread = threading.Thread(target=_worker, name="emc-crash-watch", daemon=True)
    thread.start()
    _WATCH["thread"] = thread
    return {"ok": True, **watch_state()}
