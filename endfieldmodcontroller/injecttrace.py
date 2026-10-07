"""注入现场时间线：在启动链的**五个时机**各记一份"注入列表"。

用户 2026-10-05 要求：「在一键启动最开始和 xxmi 拉起后和终末地启动后和终末地关闭和
崩溃后都要收注入列表」。

**为什么要五个点，而不是只在崩溃那一刻抓一份**：`0xC0000135` 有两种来源 ——
① 加载器真的找不到依赖；② 进程内某个 `LoadLibrary` 失败、异常没人处理，退出码就等于异常码
（这种情况**不产生 WER、不产生 dump**）。只抓崩溃那一刻，分不出"**本来是对的、中途被改坏了**"
和"**一直都是这样**"：注入库内容在启动链上会被写不止一次（一键启动写一次、XXMI 自己可能再补、
净化与初始化补齐又各写一次），而进程里到底进了哪几个 DLL，只有**游戏起来之后**才看得到。

**与 `watchsample` 的分工**：那个负责"游戏运行期间每 5 秒采一次"（内存/句柄/线程/模块增量）；
这里负责"**关键时机各拍一张照片**"，其中最重要的是把**进程模块**与
**"本来应该进进程的那两条"**（ReShade 底座 `d3d12.dll` + EFMI `d3d11.dll`）做比对 ——
`expect_missing` 非空就说明"看着注入成功、实际没进进程"，这一项就是把上面两种来源分开的钥匙。

采样刻意保持"轻、稳、只读"：不注入、不改动游戏进程；任何一项失败都不影响其它项。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# 五个时机（顺序即启动链顺序）
PHASES = ("launch-begin", "xxmi-started", "game-started", "game-exited", "crash")

_PHASE_LABEL = {
    "launch-begin": "一键启动最开始",
    "xxmi-started": "XXMI 拉起后",
    "game-started": "终末地启动后",
    "game-exited": "终末地关闭",
    "crash": "崩溃后",
}

_TRACE_NAME = "injection-trace.jsonl"

# 「本来应该进游戏进程」的注入项：XXMI 注入库里的两条。
# 进程模块里找不到它们 ⇒ 注入库里写着、实际没进进程（这正是 `0xC0000135` 两种来源的分界）。
_EXPECT_IN_PROCESS = ("d3d12.dll", "d3d11.dll")

# `runtime\dlss5` 里这几个文件的状态每次都要拍（ReShade 底座、生效 ini、两个日志的推进）
_DLSS5_FILES = ("d3d12.dll", "ReShade.ini", "dlss5-feed.log", "ReShade.log")


def trace_path(config: Any) -> Path:
    """时间线落点（与 `watchsample` 的采样文件并列放在 `_state` 下）。"""
    return Path(config.runtime_path) / "_state" / _TRACE_NAME


def _size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _injection_state(config: Any) -> dict[str, Any]:
    """XXMI 注入库此刻的内容（逐条路径）+ 开关 + 签名长度。"""
    from . import launcher

    status = launcher.dlss5_injection_status(config)
    raw = str(status.get("extra_libraries") or "")
    libs = [line.strip() for line in raw.splitlines() if line.strip()]
    signature = str(status.get("extra_libraries_signature") or "")
    return {
        "enabled": bool(status.get("enabled")),
        "extra_libraries": libs,
        "signature_len": len(signature),
        "config_path": str(status.get("config_path") or ""),
    }


def _dlss5_state(config: Any) -> dict[str, Any]:
    """`runtime\\dlss5` 的关键文件 + addon 清单（大小变化能看出"谁什么时候动过它"）。"""
    base = Path(config.dlss5_path)
    sizes = {name: _size(base / name) for name in _DLSS5_FILES}
    try:
        addons = sorted(item.name for item in base.glob("*.addon64") if item.is_file())
    except OSError:
        addons = []
    sizes["addons"] = addons
    return sizes


def _process_state(pid: int | None) -> dict[str, Any]:
    """游戏进程此刻的模块情况 + 「应该进进程的两条在不在」。

    复用 `watchsample.sample()`（它已经处理好了 ctypes 的 argtypes/restype 与权限降级），
    只取这里需要的几项，不重复实现一遍模块枚举。
    """
    if not pid:
        return {}
    try:
        from . import watchsample

        entry = watchsample.sample(pid)
    except Exception as exc:  # noqa: BLE001 —— 采样失败绝不影响其它项
        return {"pid": int(pid), "error": str(exc)}
    if not entry:
        return {"pid": int(pid), "alive": False}
    raw_modules = list(entry.get("modules") or [])
    modules = [os.path.basename(path) for path in raw_modules]
    names = {name.lower() for name in modules}
    # ★★ **同名 loader 进了两份**（2026-10-07，lzh18 现场）：进程里同时出现
    #    `…\library\d3d11.dll` 与 `…\XXMI\EFMI\d3d11.dll` —— 两个 D3D11 loader 抢 hook，
    #    游戏在 `GfxDevice: creating device client` 阶段崩（0xC0000005，故障模块 ACE-Base64.dll）。
    #    光看"该进的两条在不在"是**看不出来**的（都在），必须按**路径**去重计数。
    dupes: dict[str, list[str]] = {}
    for path in raw_modules:
        name = os.path.basename(path).lower()
        if name in ("d3d11.dll", "d3d12.dll", "dxgi.dll"):
            dupes.setdefault(name, []).append(path)
    duplicate_loaders = {name: paths for name, paths in dupes.items() if len(paths) > 1}
    return {
        "pid": int(pid),
        "alive": True,
        "module_count": entry.get("module_count"),
        "third_party_count": entry.get("third_party_count"),
        "modules": modules,
        "third_party_modules": raw_modules,
        "duplicate_loaders": duplicate_loaders,
        "expect_missing": [name for name in _EXPECT_IN_PROCESS if name.lower() not in names],
    }


def snapshot(config: Any, *, phase: str, pid: int | None = None, note: str = "") -> dict[str, Any]:
    """拍一张"注入现场"照片。**任何一项失败都不抛异常**（取证不能反噬主流程）。"""
    from . import game_clean, reshade_integration

    stamp = time.time()
    data: dict[str, Any] = {
        "t": round(stamp, 1),
        "at": time.strftime("%H:%M:%S", time.localtime(stamp)),
        "phase": phase,
        "phase_label": _PHASE_LABEL.get(phase, phase),
        "note": note,
    }
    try:
        data["injection"] = _injection_state(config)
    except Exception as exc:  # noqa: BLE001
        data["injection"] = {"error": str(exc)}
    try:
        data["dlss5"] = _dlss5_state(config)
    except Exception as exc:  # noqa: BLE001
        data["dlss5"] = {"error": str(exc)}
    game_dir: Path | None = None
    try:
        game_dir = reshade_integration.detect_game_dir(config, prefer_actual=True)
    except Exception:  # noqa: BLE001
        game_dir = None
    data["game_dir"] = str(game_dir) if game_dir else ""
    injections: dict[str, int] = {}
    try:
        for name in sorted(game_clean.injection_snapshot(config)):
            path = (game_dir / name) if game_dir else None
            injections[name] = _size(path) if path is not None else 0
    except Exception:  # noqa: BLE001
        pass
    data["game_injections"] = injections
    process = _process_state(pid)
    if process:
        data["process"] = process
    return data


def record(config: Any, *, phase: str, pid: int | None = None, note: str = "",
           log: Any = None) -> dict[str, Any] | None:
    """拍一张照片并**增量**落盘（追加一行 JSON）。返回条目（失败返回 None）。"""
    try:
        entry = snapshot(config, phase=phase, pid=pid, note=note)
    except Exception as exc:  # noqa: BLE001
        if log:
            log(f"注入时间线: 快照失败 {exc}")
        return None
    try:
        path = trace_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        if log:
            log(f"注入时间线: 写盘失败 {exc}")
        return entry
    if log:
        log(f"注入时间线[{entry['phase_label']}]: {_one_line(entry)}")
    return entry


def _one_line(entry: dict[str, Any]) -> str:
    """把一条快照压成一行摘要（日志里用）。"""
    injection = entry.get("injection") or {}
    libs = injection.get("extra_libraries") or []
    parts = [f"注入库 {len(libs)} 条" if libs else "注入库空/读不到"]
    if injection.get("error"):
        parts = [f"注入库读取失败: {injection['error']}"]
    process = entry.get("process") or {}
    if process.get("alive"):
        parts.append(f"进程 pid={process.get('pid')} 第三方模块 {process.get('third_party_count')} 个")
        missing = process.get("expect_missing") or []
        parts.append("**缺 " + "、".join(missing) + "**" if missing else "该进的两条都在")
        for name, paths in (process.get("duplicate_loaders") or {}).items():
            parts.append(f"**{name} 进了 {len(paths)} 份（两个 loader 会撞）**")
    elif process.get("error"):
        parts.append(f"进程采样失败: {process['error']}")
    injections = entry.get("game_injections") or {}
    if injections:
        parts.append(f"游戏目录注入 {len(injections)} 项")
    return "；".join(parts)


def read_all(config: Any) -> list[dict[str, Any]]:
    path = trace_path(config)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
    except OSError:
        return []
    return out


def render(entries: list[dict[str, Any]] | None = None, *, config: Any = None) -> str:
    """渲染成能直接读的时间线（进诊断包与崩溃报告）。"""
    if entries is None:
        entries = read_all(config) if config is not None else []
    head = "-- 注入现场时间线（一键启动最开始 / XXMI 拉起后 / 终末地启动后 / 终末地关闭 / 崩溃后）"
    if not entries:
        return head + "\n   （没有记录 —— 本次会话还没跑过一键启动，或时间线文件被清掉了）\n"
    lines = [head]
    for entry in entries:
        lines.append(f"  [{entry.get('at', '?')}] {entry.get('phase_label') or entry.get('phase')}"
                     f"{('（' + str(entry['note']) + '）') if entry.get('note') else ''}")
        injection = entry.get("injection") or {}
        libs = injection.get("extra_libraries") or []
        if injection.get("error"):
            lines.append(f"      注入库: 读取失败 {injection['error']}")
        else:
            lines.append(f"      注入库(enabled={injection.get('enabled')}, "
                         f"签名长度={injection.get('signature_len')}): "
                         + ("、".join(libs) if libs else "(空)"))
        process = entry.get("process") or {}
        if process.get("alive"):
            lines.append(f"      进程 pid={process.get('pid')}：模块 {process.get('module_count')} 个"
                         f"（第三方 {process.get('third_party_count')} 个）")
            if process.get("modules"):
                lines.append("        第三方模块: " + "、".join(process["modules"][:12])
                             + ("…" if len(process["modules"]) > 12 else ""))
            missing = process.get("expect_missing") or []
            lines.append("        ⚠ 该进进程却没进的: " + "、".join(missing) if missing
                         else "        ✓ 该进进程的两条（d3d12.dll / d3d11.dll）都在")
            # ★ 同名 loader 进了两份：这是"两条都在"却依然起不来的典型（2026-10-07 lzh18）
            for name, paths in (process.get("duplicate_loaders") or {}).items():
                lines.append(f"        ⚠⚠ 进程里有 {len(paths)} 份不同路径的 {name} —— "
                             "多个 loader 抢同一套 hook，游戏会在创建 D3D11 设备时崩：")
                for path in paths:
                    lines.append(f"             {path}")
        elif process.get("error"):
            lines.append(f"      进程采样失败: {process['error']}")
        elif process:
            lines.append(f"      进程 pid={process.get('pid')}：已退出（模块取不到）")
        injections = entry.get("game_injections") or {}
        if injections:
            shown = "、".join(f"{name}({size:,}B)" for name, size in list(injections.items())[:10])
            lines.append(f"      游戏目录注入物 {len(injections)} 项: {shown}"
                         + ("…" if len(injections) > 10 else ""))
        dlss5 = entry.get("dlss5") or {}
        if dlss5 and not dlss5.get("error"):
            lines.append("      runtime\\dlss5: "
                         + "、".join(f"{name}={dlss5.get(name, 0):,}B" for name in _DLSS5_FILES)
                         + "；addon: " + ("、".join(dlss5.get("addons") or []) or "(无)"))
    return "\n".join(lines) + "\n"
