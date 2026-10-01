"""文件守护：发现"某个文件被反复删掉"时提醒用户加杀毒软件白名单。

**为什么要有（用户 2026-10-01 要求）**：
「加入对文件的检测，如果某一文件老是被删掉，要在启动的时候出个弹窗提醒用户，
建议把某个文件夹加入杀毒软件白名单」。

这个需求来自真实反馈：`nvngx_dlssnr.dll`（165 MB）这类大文件、以及 DLSS5 的几个
`*.addon64`，很容易被安全软件（Windows Defender / 360 / 火绒）当威胁"隔离"掉。表现是
玩家看到的「明明修好了，第二天又缺文件 / DLSS5 又不出帧」，而我们的日志里只能看到
"缺失 → 重新展开"反复出现，**看不出是谁删的**。

**判据（关键，避免误报）**：
1. 只有**曾经就位过**（`present >= 1`）的文件才算"被删" —— 从没装过的是"还没下载"，
   不算。
2. 只有**连续两次启动**都缺（`streak >= 2`）才提醒 —— 一次缺失很正常（更新、
   用户自己清理、我们文档里就建议过"把 runtime\\dlss5 改名备份后重跑一键启动"）。
3. 还要**同组的其它文件还在**（`isolated`）—— 安全软件删的是**单个文件**；
   用户主动清理/重装是**一整片**都没了。这条能把"用户自己把 dlss5 目录改名了"
   和"被隔离了一个 dll"区分开。
4. 提醒节奏节流：每多缺 2 次才再提醒一次，别每次启动都弹。

采样频率 = **每次启动控制器一次**（同一进程内重复调用只返回上次结论、不重复计数），
所以上面说的"连续两次启动"就是字面意思。

**弹窗时机（用户 2026-10-01 决定）**：挂在**「一键启动」**那条路上 —— 点一键启动后、
自检补齐**之前**弹（那时"补了又被删"的现场最清楚）。**打开管理器时不弹**，只在日志里
留一行。前端唯一调用点是 `runOneClickLaunch()`。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

# 本次进程的唯一标识：同一进程里"一次启动"只采样一次计数
_PROCESS_STARTED = time.time()
_SESSION = f"{os.getpid()}-{int(_PROCESS_STARTED)}"

STATE_RELATIVE = Path("_state") / "file_watch.json"


@dataclass(frozen=True)
class WatchedFile:
    key: str
    group: str
    relative: str
    label: str
    # 用哪个 config 路径属性当基准（空 = 用 base_dir）。这样用户自定义了 dlss5 目录、
    # 换了内置运行时目录，也照样盯得准。
    base_attr: str = ""


# 被盯的文件：挑"体积大 / 容易被安全软件盯上 / 缺了就会明显出问题"的那些。
WATCHED: tuple[WatchedFile, ...] = (
    WatchedFile(
        "dlss5/nvngx_dlssnr.dll", "dlss5", "nvngx_dlssnr.dll",
        "DLSS5 的 NR 运行库 nvngx_dlssnr.dll（165 MB，最常被误删）",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/nvngx_dlss.dll", "dlss5", "nvngx_dlss.dll",
        "DLSS 超分运行库 nvngx_dlss.dll（59 MB）",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/d3d12.dll", "dlss5", "d3d12.dll",
        "DLSS5 的 ReShade 底座 d3d12.dll",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/dlss5-feed.addon64", "dlss5", "dlss5-feed.addon64",
        "DLSS5 出帧插件 dlss5-feed.addon64",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/renodx-endfield-enhancer.addon64", "dlss5",
        "renodx-endfield-enhancer.addon64",
        "第一人称插件 renodx-endfield-enhancer.addon64",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/renodx-dlss5-4.7.addon64", "dlss5", "renodx-dlss5-4.7_汉化.addon64",
        "DLSS5 汉化插件 renodx-dlss5-4.7_汉化.addon64",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/trans-zh.addon64", "dlss5", "trans-zh.addon64",
        "ReShade 面板汉化插件 trans-zh.addon64",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "dlss5/ReShade.ini", "dlss5", "ReShade.ini",
        "DLSS5 的 ReShade.ini（含 [endfield-enhancer] 段）",
        base_attr="dlss5_path",
    ),
    WatchedFile(
        "xxmi/xxmi-launcher.exe", "xxmi", "XXMI/Resources/Bin/XXMI Launcher.exe",
        "内置 XXMI Launcher",
        base_attr="builtin_runtime_path",
    ),
    WatchedFile(
        "xxmi/efmi-d3d11.dll", "xxmi", "XXMI/Resources/Packages/XXMI/d3d11.dll",
        "EFMI 的注入库 d3d11.dll",
        base_attr="builtin_runtime_path",
    ),
    WatchedFile(
        "sbm/sbm.dll", "sbm", "runtime/secondary_motion/SecondaryMotion/plugin/sbm.dll",
        "乳摇插件 sbm.dll",
    ),
)


def _root(config: AppConfig) -> Path:
    try:
        return Path(config.base_dir)
    except Exception:  # noqa: BLE001
        return Path(config.runtime_path).parent


def _path_for(config: AppConfig, item: WatchedFile) -> Path:
    if item.base_attr:
        try:
            base = getattr(config, item.base_attr)
            if base is not None:
                return Path(base) / item.relative
        except Exception:  # noqa: BLE001
            pass
    return _root(config) / item.relative


def state_path(config: AppConfig) -> Path:
    return Path(config.runtime_path) / STATE_RELATIVE


def load_state(config: AppConfig) -> dict[str, Any]:
    try:
        data = json.loads(state_path(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    return data


def save_state(config: AppConfig, data: dict[str, Any]) -> None:
    path = state_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except OSError:
        pass


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# 我们自己的"停用"后缀（`initialize` / `reshade_integration` 会这么改名）+
# dlss5 目录下约定俗成的 `_disabled` 子目录。
_DISABLED_SUFFIXES = (".disabled-by-mc", ".mc_disabled", ".disabled")


def _present(path: Path) -> bool:
    """文件在不在 —— **被主动停用**也算"在"。

    否则用户按说明关掉某个插件（或把 nvngx 改名停用）之后，会连续几次被判定成
    "被安全软件删了"，那就成了冤案 —— 而这条提醒的价值全在"不误报"上。
    """
    if path.is_file():
        return True
    for suffix in _DISABLED_SUFFIXES:
        if path.with_name(path.name + suffix).exists():
            return True
    if (path.parent / "_disabled" / path.name).exists():
        return True
    return False


def _entry(state: dict[str, Any], item: WatchedFile, path: Path) -> dict[str, Any]:
    entry = state["files"].get(item.key)
    if not isinstance(entry, dict):
        entry = {}
        state["files"][item.key] = entry
    entry["label"] = item.label
    entry["path"] = str(path)
    entry["group"] = item.group
    entry.setdefault("present", 0)
    entry.setdefault("missing", 0)
    entry.setdefault("streak", 0)
    entry.setdefault("alerted_at", 0)
    return entry


def _alertable(entry: dict[str, Any], *, isolated: bool) -> bool:
    """该不该把这条放进提醒（判据见模块开头）。"""
    try:
        present = int(entry.get("present") or 0)
        missing = int(entry.get("missing") or 0)
        streak = int(entry.get("streak") or 0)
        alerted = int(entry.get("alerted_at") or 0)
    except (TypeError, ValueError):
        return False
    if present < 1 or streak < 2:
        return False
    if not isolated and streak < 5:
        # 同组文件**全都没了** —— 更像"用户自己清理 / 换版本 / 改名备份"，不是安全软件
        # 删单个文件。只有缺得足够久（5 次启动）才勉强提示一下。
        return False
    # 每多缺 2 次才再提醒一次，避免每次启动都弹
    return (missing - alerted) >= 2


def _presence(config: AppConfig) -> tuple[dict[str, bool], dict[str, bool]]:
    """当前各文件的在场情况 + 每个分组里是否还有活着的文件。"""
    present = {item.key: _present(_path_for(config, item)) for item in WATCHED}
    alive: dict[str, bool] = {}
    for item in WATCHED:
        if present.get(item.key):
            alive[item.group] = True
    return present, alive


def _collect(config: AppConfig, present: dict[str, bool], alive: dict[str, bool],
             files: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    dirs: list[str] = []
    for item in WATCHED:
        if present.get(item.key):
            continue
        entry = files.get(item.key)
        if not isinstance(entry, dict):
            continue
        isolated = bool(alive.get(item.group)) and any(
            other.group == item.group and present.get(other.key) for other in WATCHED
        )
        if not _alertable(entry, isolated=isolated):
            continue
        path = _path_for(config, item)
        items.append({
            "key": item.key,
            "label": item.label,
            "path": str(path),
            "group": item.group,
            "missing": int(entry.get("missing") or 0),
            "streak": int(entry.get("streak") or 0),
            "last_present": entry.get("last_present") or "",
            "isolated": isolated,
        })
        parent = str(path.parent)
        if parent not in dirs:
            dirs.append(parent)
    return items, dirs


def _payload(config: AppConfig, items: list[dict[str, Any]], dirs: list[str]) -> dict[str, Any]:
    data_root = str(_root(config))
    if data_root not in dirs:
        dirs.append(data_root)
    return {
        "items": items,
        "dirs": dirs,
        # ⚠ 这段文字会被前端 `showModalDialog` 用 **textContent** 原样显示
        # （`web/app.js`），所以**不能写 markdown**（星号会露出来）。
        "note": (
            "这些文件本来是在的，最近连续几次启动却不见了（补上以后又没了）。\n"
            "最常见的原因是被安全软件当成威胁隔离了（Windows Defender / 360 / 火绒），"
            "也可能是被「清理垃圾 / 优化」类工具删掉了。\n"
            "建议把下面的目录加入杀毒软件的「白名单 / 排除项」。"
        ),
    }


def scan(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """采样一次（每次启动控制器只真正采样一次，之后重复调用直接返回上次结论）。"""
    state = load_state(config)
    files = state["files"]

    def _emit(message: str) -> None:
        if log:
            try:
                log(message)
            except Exception:  # noqa: BLE001
                pass

    fresh_session = str(state.get("last_session") or "") != _SESSION
    if fresh_session:
        # —— 本次启动的第一次采样：更新计数 ——
        for item in WATCHED:
            path = _path_for(config, item)
            entry = _entry(state, item, path)
            if _present(path):
                entry["present"] = int(entry.get("present") or 0) + 1
                entry["streak"] = 0
                entry["last_present"] = _now()
            elif int(entry.get("present") or 0) >= 1:
                # 曾经就位过、这次却不在 → 按"被删掉"计一次
                entry["missing"] = int(entry.get("missing") or 0) + 1
                entry["streak"] = int(entry.get("streak") or 0) + 1
                entry["last_missing"] = _now()
        state["last_session"] = _SESSION
        state["scans"] = int(state.get("scans") or 0) + 1
        save_state(config, state)

    present, alive = _presence(config)
    items, dirs = _collect(config, present, alive, files)
    alert = _payload(config, items, dirs) if items else None
    if alert:
        _emit(
            "文件守护: 检测到"
            + "、".join(str(item["label"]) for item in items)
            + f"（已缺 {max(int(item['missing']) for item in items)} 次）—— 疑似被杀毒软件删除"
        )
    return {
        "ok": True,
        "scans": int(state.get("scans") or 0),
        "checked": len(WATCHED),
        "alert": alert,
    }


def pending(config: AppConfig) -> dict[str, Any] | None:
    """读回"当前该弹给用户的提醒"（**不重新采样**，供 get_state 用）。"""
    state = load_state(config)
    present, alive = _presence(config)
    items, dirs = _collect(config, present, alive, state["files"])
    return _payload(config, items, dirs) if items else None


def ack(config: AppConfig, keys: list[str] | None = None) -> dict[str, Any]:
    """记下"已经提醒过"，避免下次启动重复弹同一件事。"""
    state = load_state(config)
    targets = {str(key) for key in (keys or []) if str(key)}
    changed = 0
    for key, entry in state["files"].items():
        if not isinstance(entry, dict):
            continue
        if targets and key not in targets:
            continue
        entry["alerted_at"] = int(entry.get("missing") or 0)
        changed += 1
    if changed:
        save_state(config, state)
    return {"ok": True, "acknowledged": changed}


def status(config: AppConfig) -> dict[str, Any]:
    """给设置页/排查看的历史（不采样）。"""
    state = load_state(config)
    rows = []
    for item in WATCHED:
        entry = state["files"].get(item.key)
        if not isinstance(entry, dict):
            continue
        rows.append({
            "key": item.key,
            "label": item.label,
            "present": int(entry.get("present") or 0),
            "missing": int(entry.get("missing") or 0),
            "streak": int(entry.get("streak") or 0),
            "exists": _present(_path_for(config, item)),
        })
    return {"scans": int(state.get("scans") or 0), "items": rows}
