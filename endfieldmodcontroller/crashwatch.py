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

    判定顺序：uploadCrash → normal_exit → Player.log 崩溃标记。
    """
    # ① 真正上传了崩溃转储 —— 最可靠的崩溃证据
    if evidence.get("crash_upload"):
        return True
    # ② 有正常退出卸载统计 —— 正常退出
    if evidence.get("normal_exit"):
        return False
    # ③ 两者都没有时，再看 Player.log 里有没有崩溃标记
    return bool(evidence.get("player_log_crash"))


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
    evidence: dict[str, Any] = {
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "process": {"name": GAME_PROCESS, "started_at": None, "exit_time": None, "alive_seconds": alive_seconds},
        "injections": injection_snapshot(config),
        "xxmi_inject": _xxmi_inject_lines(config),
        "crash_sight": _crash_sight_lines(config, since=started_at),
        "crash_upload": _crash_sight_upload_lines(config, since=started_at),
        "normal_exit": _normal_exit_marker(),
        "crashes": [],
        "player_log_tail": [],
        "game_errors": _extract_game_errors(config),
    }
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


def make_bundle(config: AppConfig, evidence: dict[str, Any] | None = None,
                *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把崩溃现场 + 控制器日志 + 终末地日志打成 zip，返回路径信息。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    bundle_dir = bundles_root(config) / f"crash-{ts}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    if evidence is None:
        evidence = collect_evidence(config)

    # ① 崩溃报告正文
    try:
        report_text = _render_report(evidence)
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

    # ⑤ 打包
    zip_path = bundles_root(config) / f"crash-{ts}.zip"
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
        "game_logs": game_logs,
        "crashed": is_crash(evidence),
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
    return {
        "zip": str(latest),
        "dir": str(latest.with_suffix("")),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest.stat().st_mtime)),
        "size_mb": round(latest.stat().st_size / 1048576, 2),
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

            # ② 等进程退出
            while time.time() < deadline:
                if not _process_ids():
                    break
                time.sleep(2.0)
            exit_time = time.time()
            alive = exit_time - started
            _emit(f"崩溃监控: 游戏已退出（存活 {alive:.0f} 秒），正在收集现场…")

            # ③ 收集现场 + 写报告 + 打崩溃包
            time.sleep(3.0)   # 等崩溃报告落盘
            evidence = collect_evidence(config, started_at=started, exit_time=exit_time, alive_seconds=alive)
            path = write_report(config, evidence)
            crashed = is_crash(evidence)
            _emit(f"崩溃监控: {'检测到崩溃' if crashed else '未检测到崩溃（正常退出）'}，报告: {path.name}")
            try:
                bundle = make_bundle(config, evidence, log=_emit)
                # 只有真的崩了才让前端弹窗提示反馈；正常退出只留日志与包，不打扰用户
                if crashed:
                    _WATCH["bundle"] = bundle
                _emit(f"崩溃监控: 崩溃包已就绪（含终末地日志 {len(bundle.get('game_logs') or [])} 份）"
                      + ("" if crashed else "，正常退出不提示"))
            except Exception as exc:  # noqa: BLE001
                _emit(f"崩溃监控: 打包失败 {exc}")
        except Exception as exc:  # noqa: BLE001
            _emit(f"崩溃监控异常: {exc}")
        finally:
            _WATCH["running"] = False
            _WATCH["pid"] = None

    thread = threading.Thread(target=_worker, name="emc-crash-watch", daemon=True)
    thread.start()
    _WATCH["thread"] = thread
    return {"ok": True, **watch_state()}
