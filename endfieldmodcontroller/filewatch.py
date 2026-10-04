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
    # 特殊基准（2026-10-04 加，用于"游戏目录 / System32"这两类**不在数据根下**的文件）：
    #   "game"     = 游戏目录（自动探测；**探测不到就整项跳过**，见 `_path_for`）
    #   "system32" = `%SystemRoot%\System32`（loader proxy **真正去加载真 DLL** 的地方）
    base_kind: str = ""


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
    # ── 游戏目录：注入链的**底座**（2026-10-04 加）─────────────────────────────
    # 为什么原来漏了：这套守护只盯 `runtime\` 里的组件，而**游戏目录里的两个 proxy
    # 才是整条注入链的底座** —— 它被杀毒吃掉时，玩家的表现是"游戏起不来 / 闪退"，
    # 而不是"DLSS5 不出帧"，正好是另一类事故（反馈者那次的退出码就是
    # `0xC0000135 STATUS_DLL_NOT_FOUND`，而旧包里的守护清单压根没往那儿看）。
    # ⚠️ `_present()` 判的是"**这个文件在不在**"：净化流程把 proxy 搬走时会**从 System32
    #    补一份原版回来**，所以"被我们自己搬走"不会命中；只有"真没了"才会计数。
    WatchedFile(
        "game/d3dcompiler_47.dll", "game", "d3dcompiler_47.dll",
        "游戏目录的注入底座 d3dcompiler_47.dll（Poser / 乳摇靠它加载）",
        base_kind="game",
    ),
    WatchedFile(
        "game/vulkan-1.dll", "game", "vulkan-1.dll",
        "游戏目录的注入底座 vulkan-1.dll",
        base_kind="game",
    ),
    WatchedFile(
        "game/plugin/poser.dll", "plugin", "plugin/poser.dll",
        "游戏里的 Poser 插件 poser.dll",
        base_kind="game",
    ),
    WatchedFile(
        "game/plugin/sbm.dll", "plugin", "plugin/sbm.dll",
        "游戏里的乳摇插件 sbm.dll",
        base_kind="game",
    ),
    # ── System32 的转发目标（2026-10-04 加，这次事件暴露的盲区）──────────────────
    # proxy 是**硬编码去 `C:\Windows\System32\<同名>` 加载真 DLL** 的（字符串表里写着
    # `C:\Windows\System32\d3dcompiler_47.D3DCompile` 这种"路径.导出名"）。
    # 所以 System32 里这两个被杀毒隔离 ⇒ proxy 转发不出来 ⇒ 游戏照样
    # `STATUS_DLL_NOT_FOUND`。它们以前不在任何清单里，出事时连"文件还在不在"都答不上来。
    # ⚠️ 没装 Vulkan 运行库的机器上 `vulkan-1.dll` 本来就不存在 —— 而判据要求
    #    `present >= 1`（曾经就位过）才计数，所以不会为此误报。
    WatchedFile(
        "system32/d3dcompiler_47.dll", "system32", "d3dcompiler_47.dll",
        "System32 的 d3dcompiler_47.dll（proxy 的转发目标）",
        base_kind="system32",
    ),
    WatchedFile(
        "system32/vulkan-1.dll", "system32", "vulkan-1.dll",
        "System32 的 vulkan-1.dll（proxy 的转发目标）",
        base_kind="system32",
    ),
)


def _root(config: AppConfig) -> Path:
    try:
        return Path(config.base_dir)
    except Exception:  # noqa: BLE001
        return Path(config.runtime_path).parent


def _path_for(config: AppConfig, item: WatchedFile) -> Path | None:
    """解析出这个项要盯的绝对路径；**当前环境里不适用时返回 None**（调用方必须跳过）。

    为什么不适用就返回 None、而不是退回去拼数据根：游戏目录探测不到时，
    `数据根\\d3dcompiler_47.dll` 是个**根本不该存在的路径** —— 按"在不在"这套判据，
    它下一轮就会被算成"被删了一次"，再下一轮就弹一个纯属冤枉的窗。
    这个守护的全部价值都在"**不误报**"上，宁可这一轮不盯它。
    """
    if item.base_kind == "system32":
        root = os.environ.get("SystemRoot") or r"C:\Windows"
        base = Path(root) / "System32"
        return (base / item.relative) if base.is_dir() else None
    if item.base_kind == "game":
        try:
            from . import reshade_integration

            game = reshade_integration.detect_game_dir(config)
        except Exception:  # noqa: BLE001 —— 探测失败等同于"没定位到"
            game = None
        return (Path(game) / item.relative) if game else None
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


# 我们自己的"停用"后缀（`initialize` / `reshade_integration` / `poser` / `secondary_motion`
# 会这么改名）+ dlss5 目录下约定俗成的 `_disabled` 子目录。
# ⚠️ `.endfieldmodcontroller.disabled` 必须**显式列出来**（2026-10-04 加）：`sbm.dll` 被开关
# 停用时叫 `sbm.dll.endfieldmodcontroller.disabled`，而按 `.disabled` 后缀拼出来的是
# `sbm.dll.disabled` —— 拼不上，于是"用户自己关掉的插件"会被当成"被杀毒删了"。这正是
# 这套判据最不能出的错（模块开头那句"价值全在不误报上"）。
_DISABLED_SUFFIXES = (".disabled-by-mc", ".mc_disabled", ".endfieldmodcontroller.disabled",
                      ".disabled")


def _present(path: Path | None) -> bool:
    """文件在不在 —— **被主动停用**也算"在"，**当前环境不适用**（`None`）算"不在"。

    否则用户按说明关掉某个插件（或把 nvngx 改名停用）之后，会连续几次被判定成
    "被安全软件删了"，那就成了冤案 —— 而这条提醒的价值全在"不误报"上。
    """
    if path is None:
        return False
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


def _presence(config: AppConfig) -> tuple[dict[str, bool], dict[str, bool], set[str]]:
    """当前各文件的在场情况 + 每个分组里是否还有活着的文件 + **本环境里不适用**的项。

    第三项（2026-10-04 加）是给"游戏目录 / System32"那几项用的：没定位到游戏目录时
    它们连路径都算不出来，**绝不能参与计数** —— 否则会被当成"被删了一次"。
    """
    present: dict[str, bool] = {}
    alive: dict[str, bool] = {}
    applicable: set[str] = set()
    for item in WATCHED:
        path = _path_for(config, item)
        if path is None:
            continue
        applicable.add(item.key)
        here = _present(path)
        present[item.key] = here
        if here:
            alive[item.group] = True
    return present, alive, applicable


def _collect(config: AppConfig, present: dict[str, bool], alive: dict[str, bool],
             files: dict[str, Any], applicable: set[str] | None = None
             ) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    dirs: list[str] = []
    for item in WATCHED:
        if applicable is not None and item.key not in applicable:
            continue                       # 本环境不适用（如游戏目录没定位到）—— 不算缺
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
        if path is None:
            continue
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
    # ⚠️ 这里同时给**两套字段名**（2026-10-04 修前后端不匹配）：
    # 前端 `LaunchPage.fileWatchdogGate()` 读的是 `flagged / files[].name / watch_dir /
    # acknowledged`，而本函数原先只给 `items / dirs / note` —— 于是 `st.flagged` 恒为
    # undefined，**用户 2026-10-01 点名要的"建议加杀毒白名单"提醒从来没弹过**
    #（后端为此写的四段计数、`isolated`、`streak>=2` 判据全部无人受益）。
    # 按"以补齐为主"：后端补别名，老的 `items/dirs` 原样保留（诊断与测试都在用）。
    files = [{**item, "name": item.get("label") or item.get("key") or ""} for item in items]
    return {
        "items": items,
        "files": files,
        "dirs": dirs,
        "flagged": bool(items),
        "watch_dir": dirs[0] if dirs else data_root,
        # 没有待提醒项 = 已经被用户处理过（`ack` 之后判据不再命中，flagged 自然变 False）
        "acknowledged": not items,
        # ⚠ 这段文字会被前端 `showModalDialog` 用 **textContent** 原样显示
        # （`web/app.js`），所以**不能写 markdown**（星号会露出来）。
        "note": (
            "这些文件本来是在的，最近连续几次启动却不见了（补上以后又没了）。\n"
            "最常见的原因是被安全软件当成威胁隔离了（Windows Defender / 360 / 火绒），"
            "其次是被「清理垃圾 / 优化」类工具删掉。\n"
            "建议把下面的目录加入杀毒软件的「白名单 / 排除项」。"
            "如果用的是 Windows Defender，也可以用下面的按钮一键加。"
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
            if path is None:
                continue                  # 本环境不适用 —— **一个计数都不动**（见 `_path_for`）
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

    present, alive, applicable = _presence(config)
    items, dirs = _collect(config, present, alive, files, applicable)
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
    present, alive, applicable = _presence(config)
    items, dirs = _collect(config, present, alive, state["files"], applicable)
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
        path = _path_for(config, item)
        rows.append({
            "key": item.key,
            "label": item.label,
            "group": item.group,
            "present": int(entry.get("present") or 0),
            "missing": int(entry.get("missing") or 0),
            "streak": int(entry.get("streak") or 0),
            "exists": _present(path),
            # 本环境里不适用（如游戏目录没定位到）—— 前端可以据此把这行标灰，
            # 免得用户以为"它没在盯"是坏了。2026-10-04 加。
            "applicable": path is not None,
            "path": str(path) if path is not None else "",
        })
    return {"scans": int(state.get("scans") or 0), "items": rows}
