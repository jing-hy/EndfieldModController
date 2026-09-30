"""SecondaryMotion（乳摇 / 次级运动管理器）集成。

这个第三方工具靠替换游戏目录里的两个 proxy DLL 注入自己的 loader，再由 loader
加载 ``plugin\\sbm.dll``：

    d3dcompiler_47.dll  (proxy, 十几 KB)  +  d3dcompiler_47.dll.bak  (原版)
    vulkan-1.dll        (proxy, 几十 KB)  +  vulkan-1.dll.bak        (原版)
    plugin\\sbm.dll     (插件本体, 由 loader 加载)

本模块只做四件事：报状态、缺了就补齐、一键卸掉、启动它自己的 Manager.exe。
所有写入都是可回滚的（原版一律留 ``.bak``）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

PROXY_NAMES = ("d3dcompiler_47.dll", "vulkan-1.dll")
# 正版系统 DLL 都是几 MB，proxy 只有十几~几十 KB
PROXY_MAX_SIZE = 200_000
PLUGIN_NAME = "sbm.dll"


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def game_dir(config: AppConfig) -> Path | None:
    from . import reshade_integration

    return reshade_integration.detect_game_dir(config)


def _tool_dir(config: AppConfig) -> Path | None:
    return config.secondary_motion_tool_dir


def _is_proxy(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size < PROXY_MAX_SIZE
    except OSError:
        return False


def _other_plugin_dlls(game: Path) -> list[str]:
    """`plugin\\` 下除 sbm.dll 之外的插件 DLL（例如 Endfield Poser 的 poser.dll）。

    存在的意义：两套 loader 都会加载 plugin 下**所有** dll，所以卸载乳摇时若还有
    别的插件在，就**不能**把 proxy 还原成系统原版（那会把对方一起废掉）。
    """
    try:
        return sorted(
            item.name for item in (game / "plugin").glob("*.dll")
            if item.is_file() and item.name.lower() != PLUGIN_NAME.lower()
        )
    except OSError:
        return []


def status(config: AppConfig) -> dict[str, Any]:
    """工具 / 注入 / 运行时的当前状态，供 UI 显示。"""
    root = config.secondary_motion_root
    tool = _tool_dir(config)
    exe = config.secondary_motion_exe
    result: dict[str, Any] = {
        "tool_root": str(root) if root else "",
        "tool_dir": str(tool) if tool else "",
        "manager_exe": str(exe) if exe else "",
        "manager_exists": bool(exe and exe.is_file()),
        "tool_version": _tool_version(root) if root else "",
        "pack_version": _pack_version(tool) if tool else "",
        "game_dir": "",
        "proxies": {},
        "injected": False,
        "plugin_exists": False,
        "backup_ok": False,
        # 谁在提供 loader（proxy）："sbm" / "poser" / ""。2026-10-01 起 Endfield Poser
        # 也用同一套 proxy + `plugin\*.dll` 机制，两个插件可能共用同一份 proxy。
        "loader_owner": "",
        "other_plugins": [],
        "runtime": {},
        "log_tail": [],
    }
    game = game_dir(config)
    if game is None:
        return result
    result["game_dir"] = str(game)

    for name in PROXY_NAMES:
        target = game / name
        backup = game / f"{name}.bak"
        installed = _is_proxy(target)
        result["proxies"][name] = {
            "installed": installed,
            "size": target.stat().st_size if target.is_file() else 0,
            "backup": backup.is_file(),
        }
    result["injected"] = all(item["installed"] for item in result["proxies"].values())
    result["backup_ok"] = all(item["backup"] for item in result["proxies"].values())

    # 谁在提供 loader：Endfield Poser 也用同一套 proxy + `plugin\*.dll` 机制，
    # 两个插件可以共用一份 proxy（谁提供都能把对方的插件 DLL 加载起来）。
    from . import reshade_integration

    kind_fn = getattr(reshade_integration, "loader_kind", None)
    result["loader_owner"] = kind_fn(game / PROXY_NAMES[0]) if callable(kind_fn) else ""
    result["other_plugins"] = _other_plugin_dlls(game)

    plugin = game / "plugin" / PLUGIN_NAME
    result["plugin_exists"] = plugin.is_file()

    data_dir = game / "SecondaryMotion"
    # 插件是在**游戏目录**里读自己的配置的。少了 data\characters.default.json 它会直接
    # `FAIL: initial config invalid -> DISABLED_SAFE` 自我禁用 —— 表现就是"管理器显示
    # 游戏未启动、游戏里也没效果"，而 proxy 与 plugin\sbm.dll 其实都装好了
    # （2026-09-27 实测踩到：只装那两个文件是不够的）。
    result["data_ready"] = (data_dir / "data" / "characters.default.json").is_file()

    data_dir = game / "SecondaryMotion"
    status_file = data_dir / "runtime" / "runtime_status.json"
    if status_file.is_file():
        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
            payload["age_s"] = round(time.time() - status_file.stat().st_mtime, 1)
            result["runtime"] = payload
        except (OSError, json.JSONDecodeError):
            result["runtime"] = {}
    log_file = game / "plugin" / "sbm_log.txt"
    if log_file.is_file():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            result["log_tail"] = lines[-6:]
        except OSError:
            pass
    return result


def _version_from_name(name: str) -> str:
    """从 ShakingBreastManager-v2.3.5-ZH-win-x64 这种目录名里抠版本号。"""
    import re

    match = re.search(r"[vV](\d+(?:\.\d+)+)", name or "")
    return match.group(0) if match else ""


def _tool_version(root: Path | None) -> str:
    """版本优先读目录里的 version.txt（内嵌副本靠它记住发布版本号），再退回目录名。"""
    if root is None:
        return ""
    for base in (root, root / "SecondaryMotion"):
        version_file = base / "version.txt"
        if version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                text = ""
            if text:
                return text
    return _version_from_name(root.name)


def _pack_version(tool_dir: Path | None) -> str:
    if tool_dir is None:
        return ""
    exe = tool_dir / "SecondaryMotion.Manager.exe"
    if not exe.is_file():
        return ""
    version_file = tool_dir / "version.txt"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _assets_root(config: AppConfig | None = None) -> Path:
    """随包分发的资产根目录（`<数据根>/assets`）。

    ⚠️ **不能用 `Path(__file__).resolve().parents[1]`** —— 打包成单文件 exe 之后
    `__file__` 指向 PyInstaller 的临时解压目录（`sys._MEIPASS`），而 `assets` 既没打进
    exe、也不在那个临时目录里，于是 **exe 版永远报「找不到 sbm 注入源」**，表现为
    「自动安装不会装 sbm」（用户 2026-09-29 实测反馈）。源码运行时路径恰好是对的，
    所以这个 bug 一直没暴露。

    `assets` 和 `config.json` / `runtime` / `library` 一样位于**数据根**（exe 所在目录），
    所以优先用 `config.base_dir`，找不到才回退到源码布局。
    """
    if config is not None:
        base = getattr(config, "base_dir", None)
        if base is not None:
            candidate = Path(base) / "assets"
            if candidate.is_dir():
                return candidate
    return Path(__file__).resolve().parents[1] / "assets"


def _source_candidates(config: AppConfig) -> list[Path]:
    """sbm 部署源的候选列表（按优先级）：**随包 assets 优先**，其次乳摇工具目录。

    为什么改成"逐文件挑选"（2026-09-29 端到端实测）：一开始写的是"选一个源"，
    结果测试环境里**工具目录存在但内容不全**（只有插件本体、没有 data/presets）→
    整个源被判成工具目录、assets 反而没被用上 → `characters.default.json` 补不进去。
    所以改为：每个文件各自在候选列表里找**第一个存在的**，两个源互补。
    """
    candidates: list[Path] = [_assets_root(config) / "secondary_motion"]
    tool = _tool_dir(config)
    if tool is not None:
        candidates.append(tool)
    return [candidate for candidate in candidates if candidate.is_dir()]


def _pick(candidates: list[Path], *relative: str) -> Path | None:
    """在候选源里找第一个存在的文件，例如 `_pick(cands, "plugin", "sbm.dll")`。"""
    for base in candidates:
        path = base.joinpath(*relative)
        if path.is_file():
            return path
    return None


def ensure_injection(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """补齐乳摇注入：两个 proxy + plugin\\sbm.dll + 插件数据。已装的不动，缺失才补。"""
    actions: list[str] = []
    warnings: list[str] = []

    # ⚠️ **这一步必须放在所有提前 return 之前**。它给管理器预写 `settings.json`
    # （记住游戏目录），与"注入源找不找得到"毫无关系；原先挂在函数末尾，于是
    # "找不到 sbm 注入源"那次提前 return 时**根本没写**，用户打开管理器仍然被要求
    # 选文件夹（2026-09-29 实测：从零安装后的工具目录里没有 settings.json）。
    settings_state = ensure_manager_settings(config)
    if settings_state.get("changed"):
        actions.append(str(settings_state.get("message") or "写入乳摇管理器 settings.json"))
    elif not settings_state.get("ok"):
        warnings.append(str(settings_state.get("message")))

    candidates = _source_candidates(config)
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录", "actions": actions, "warnings": warnings}
    if not candidates:
        return {
            "ok": False,
            "message": "找不到 sbm 注入源（assets/secondary_motion 与乳摇工具目录都不存在）",
            "actions": actions,
            "warnings": warnings,
        }

    for name in PROXY_NAMES:
        target = game / name
        source = _pick(candidates, "plugin", name)
        if source is None:
            warnings.append(f"注入源缺少 {name}，跳过")
            continue
        if _is_proxy(target):
            continue
        if target.is_file():
            backup = game / f"{name}.bak"
            if not backup.is_file():
                shutil.copy2(target, backup)
                actions.append(f"备份原版 {name} -> {name}.bak")
        elif (game / f"{name}.bak").is_file():
            # 原版已在 .bak，直接放 proxy
            pass
        try:
            shutil.copy2(source, target)
            actions.append(f"安装注入 {name}")
        except OSError as exc:
            warnings.append(f"写入 {name} 失败: {exc}")

    plugin_target = game / "plugin" / PLUGIN_NAME
    plugin_source = _pick(candidates, "plugin", PLUGIN_NAME)
    if not plugin_target.is_file() and plugin_source is not None:
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plugin_source, plugin_target)
        actions.append(f"安装插件 plugin\\{PLUGIN_NAME}")

    # 插件的数据目录也必须保证在位，否则插件启动即自我禁用（见 status() 的注释）。
    # 只补"缺失的关键文件"，不覆盖用户已有的 presets / 调参结果。
    data_dir = game / "SecondaryMotion"
    default_chars = data_dir / "data" / "characters.default.json"
    if not default_chars.is_file():
        source_default = _pick(candidates, "data", "characters.default.json")
        if source_default is not None:
            default_chars.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_default, default_chars)
            actions.append("安装插件数据 SecondaryMotion\\data\\characters.default.json")
        else:
            warnings.append("注入源缺少 data\\characters.default.json，插件会因配置无效自我禁用")
    # 预设也要在位：sbm 按 runtime\\config.json 里的 active_preset 去读 presets\\<名字>.json，
    # 缺了同样是"配置无效 → DISABLED_SAFE"（2026-09-29 补齐）。
    preset = data_dir / "presets" / "Default.json"
    if not preset.is_file():
        source_preset = _pick(candidates, "presets", "Default.json")
        if source_preset is not None:
            preset.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_preset, preset)
            actions.append("安装插件预设 SecondaryMotion\\presets\\Default.json")
    runtime_cfg = data_dir / "runtime" / "config.json"
    # **文件在、但 enabled 是 false 也要纠正** —— 用户 2026-09-29 实测：工具目录里
    # 那份从发布包解出来的是 `{"enabled": false}`，只判断"文件是否存在"就会放过它，
    # 管理器与插件都因此不工作。
    runtime_data: dict[str, Any] = {}
    if runtime_cfg.is_file():
        try:
            loaded = json.loads(runtime_cfg.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                runtime_data = loaded
        except (OSError, ValueError):
            runtime_data = {}
    if not runtime_data.get("enabled"):
        runtime_data.update({
            "revision": runtime_data.get("revision") or 1,
            "enabled": True,
            "active_preset": runtime_data.get("active_preset") or "Default",
        })
        try:
            runtime_cfg.parent.mkdir(parents=True, exist_ok=True)
            runtime_cfg.write_text(
                json.dumps(runtime_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")
            actions.append("写入插件配置 SecondaryMotion\\runtime\\config.json（enabled=true）")
        except OSError as exc:
            warnings.append(f"写入插件配置失败: {exc}")

    # ③ **乳摇管理器自己用的那份也要有实体文件**（用户 2026-09-29 反馈「sbm 启动管理的
    #    时候还是显示请选择文件」）。原因：工具发布包里只带模板 ——
    #    `data\characters.default.template.json`、`presets\Default.template.json`，
    #    而管理器按 `runtime\config.json` 的 `active_preset` 去读 `presets\<名字>.json`，
    #    读不到就只能让用户手动"选择文件"。这里把模板**实例化**成实体文件：
    #    已存在的一律不动（不覆盖用户调过的参数与预设）。
    tool = _tool_dir(config)
    if tool is not None:
        for relative, template_relative in (
            (("data", "characters.default.json"), ("data", "characters.default.template.json")),
            (("presets", "Default.json"), ("presets", "Default.template.json")),
            (("presets", "User.json"), ("presets", "User.template.json")),
        ):
            target = tool.joinpath(*relative)
            if target.is_file():
                continue
            source = _pick(candidates, *relative)
            if source is None:
                candidate = tool.joinpath(*template_relative)
                source = candidate if candidate.is_file() else None
            if source is None:
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                actions.append(f"生成乳摇管理器文件 {target.name}（来自 {source.name}）")
            except OSError as exc:
                warnings.append(f"生成 {target.name} 失败: {exc}")
        tool_cfg = tool / "runtime" / "config.json"
        tool_data: dict[str, Any] = {}
        if tool_cfg.is_file():
            try:
                loaded = json.loads(tool_cfg.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    tool_data = loaded
            except (OSError, ValueError):
                tool_data = {}
        if not tool_data.get("enabled"):
            tool_data.update({
                "revision": tool_data.get("revision") or 1,
                "enabled": True,
                "active_preset": tool_data.get("active_preset") or "Default",
            })
            try:
                tool_cfg.parent.mkdir(parents=True, exist_ok=True)
                tool_cfg.write_text(
                    json.dumps(tool_data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
                actions.append("修正乳摇管理器 runtime\\config.json（enabled=true）")
            except OSError as exc:
                warnings.append(f"修正乳摇管理器配置失败: {exc}")

    for action in actions:
        _log(log, action)
    for warning in warnings:
        _log(log, f"WARN {warning}")
    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "injected": status(config)["injected"],
    }


def remove_injection(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """卸掉注入：删除 proxy、把 .bak 还原成正式 DLL、移除 plugin\\sbm.dll。"""
    actions: list[str] = []
    warnings: list[str] = []
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录", "actions": [], "warnings": []}

    others = _other_plugin_dlls(game)
    for name in PROXY_NAMES:
        target = game / name
        backup = game / f"{name}.bak"
        # 2026-10-01：**plugin 里还有别的插件时保留 loader**。两套 loader（sbm / Poser）
        # 都会加载 `plugin\*.dll`，把 proxy 还原成系统原版等于把对方插件一起废掉；
        # 上游 Poser 的卸载向导在同样情形下也是"keeping loader"。
        if others:
            actions.append(f"保留 loader {name}（plugin 里还有其它插件：{', '.join(others)}）")
            continue
        # 2026-10-01 修（⑥）：**先恢复、后删除**，且两步各自独立 try —— 原先挤在
        # 同一个 try 里，`copy2` 失败就会留下"proxy 已删、原版未回"的半状态：
        # 游戏目录缺 d3dcompiler_47/vulkan-1，游戏直接起不来。
        if backup.is_file():
            try:
                from . import fsutil

                fsutil.write_bytes_atomic(target, backup.read_bytes())
                actions.append(f"还原原版 {name}")
            except OSError as exc:
                warnings.append(f"还原 {name} 失败（这次不删注入，保持游戏可用）: {exc}")
                continue
        try:
            if _is_proxy(target):
                target.unlink()
                actions.append(f"移除注入 {name}")
        except OSError as exc:
            warnings.append(f"处理 {name} 失败: {exc}")

    # 直接删掉 plugin\sbm.dll（以及历史遗留的 .mc_disabled 残渣），不留在游戏目录：
    # 工具目录里本来就有 sbm.dll 源文件，ensure_injection 随时能装回来，
    # 而在游戏目录留一份"已停用副本"会让「本体是否干净」永远判定不通过。
    plugin_dir = game / "plugin"
    if plugin_dir.is_dir():
        for candidate in sorted(plugin_dir.glob(f"{PLUGIN_NAME}*")):
            if not candidate.is_file():
                continue
            try:
                candidate.unlink()
                actions.append(f"移除 plugin\\{candidate.name}")
            except OSError as exc:
                warnings.append(f"移除 {candidate.name} 失败: {exc}")

    for action in actions:
        _log(log, action)
    for warning in warnings:
        _log(log, f"WARN {warning}")
    # 注：管理器那份 settings.json 已经在函数开头写过（那里不会因提前 return 被跳过），
    # 这里不再重复调用，避免把同一条 action 记两遍。
    return {"ok": not warnings, "actions": actions, "warnings": warnings}


def ensure_manager_settings(config: AppConfig) -> dict[str, Any]:
    """给乳摇管理器预写 `settings.json`，免掉"每次启动都要选游戏文件夹"。

    依据（反编译 `SecondaryMotion.Manager.dll` 的字符串表，2026-09-29）：
      * 它把用户选的游戏目录记在**自己目录下的 `settings.json`** 里，结构就只有两个字段
        —— 字符串表里能直接看到模板 `{ "game_data_dir": ..., "language": ... }`
        以及日志格式 `manager_dir:` / `settings.game_data_dir:` / `(none)`；
      * 缺这个字段时弹 `Msg_GameFolderRequired`，文案是
        "Select the game folder (the one containing Endfield.exe, e.g. ...\\Endfield Game)"；
      * 它自己的校验是"该目录里要有 `plugins\\`、`Endfield.exe` 或 `UnityPlayer.dll`"。
    用户 2026-09-29 反馈「sbm 还是要选文件夹」，而那个 settings.json 从没被写出来过，
    所以初始化时把检测到的游戏目录写进去。已有的 `settings.json` **保留其它字段**，
    只在缺失/为空时补 `game_data_dir`。
    """
    tool = _tool_dir(config)
    if tool is None:
        return {"ok": False, "message": "未找到乳摇工具目录"}
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录"}
    settings_path = tool / "settings.json"
    # ⚠️ `game_data_dir` 要的是**游戏目录下的 `SecondaryMotion` 数据目录**，不是游戏根目录！
    # 2026-09-29 实测：写成游戏根目录（`...\Endfield Game`）时管理器仍然弹「请选择游戏文件夹」；
    # 对照"用户手动选过一次"的原始包 `settings.json` 才知道正确值是
    # `<游戏目录>\SecondaryMotion`。（管理器界面上的提示语写的是"选含 Endfield.exe 的那层"，
    # 但它自己落盘时存的是数据目录 —— 别照提示语的语义写。）
    data_dir = game / "SecondaryMotion"
    data: dict[str, Any] = {}
    if settings_path.is_file():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
    current = str(data.get("game_data_dir") or "").strip()
    if current and Path(current) == data_dir:
        return {"ok": True, "changed": False, "path": str(settings_path),
                "message": "乳摇管理器的游戏目录已记录"}
    data["game_data_dir"] = str(data_dir)
    data.setdefault("language", "zh-CN")
    try:
        if settings_path.is_file():
            backup = settings_path.with_name(settings_path.name + ".bak")
            if not backup.is_file():
                shutil.copy2(settings_path, backup)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
    except OSError as exc:
        return {"ok": False, "message": f"写入 settings.json 失败: {exc}"}
    return {"ok": True, "changed": True, "path": str(settings_path),
            "message": f"已记录乳摇管理器的游戏目录: {game}"}


def launch_manager(config: AppConfig) -> dict[str, Any]:
    """启动它原生的 Manager.exe（保持工具自身界面不变）。"""
    exe = config.secondary_motion_exe
    if exe is None or not exe.is_file():
        return {"ok": False, "message": "未找到 SecondaryMotion.Manager.exe，请在设置页配置工具目录"}
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=creationflags)
    except OSError as exc:
        return {"ok": False, "message": f"启动失败: {exc}"}
    return {"ok": True, "exe": str(exe)}


def import_pack(config: AppConfig, archive: Path, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """用新的发布包（zip）更新工具本体，保留 logs / presets / data / settings.json。

    新包解压后如果顶层只有一层目录，会自动下钻到含 SecondaryMotion.Manager.exe 的那层。
    """
    import tempfile
    import zipfile

    archive = Path(archive)
    if not archive.is_file():
        return {"ok": False, "message": f"压缩包不存在: {archive}"}
    tool = _tool_dir(config)
    if tool is None:
        # 「没装过」也必须能装上：用默认位置 runtime\secondary_motion\SecondaryMotion 就地建出来。
        # （原来这里直接报「请先在设置页配置工具目录」——于是从零安装永远走不通，
        #   用户看到的正是"只显示未找到工具目录"。）
        root = config.secondary_motion_root or (Path(config.runtime_path) / "secondary_motion")
        tool = Path(root) / "SecondaryMotion"
        try:
            tool.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "message": f"无法创建工具目录 {tool}: {exc}"}
        # 记进配置，下次直接能找到
        try:
            if not config.secondary_motion_dir:
                config.secondary_motion_dir = str(tool.parent)
                config.save()
        except OSError:
            pass
        _log(log, f"未装过，将安装到 {tool}")

    keep = ("logs", "presets", "data", "runtime")
    keep_files = ("settings.json", "default_lang.txt")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = tool.parent / f"_backup_{stamp}"

    try:
        with tempfile.TemporaryDirectory(prefix="mc-sbm-") as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp_path)
            # 下钻到含 exe 的目录
            root = tmp_path
            for _ in range(3):
                if (root / "SecondaryMotion.Manager.exe").is_file():
                    break
                children = [c for c in root.iterdir() if c.is_dir()]
                if len(children) == 1:
                    root = children[0]
                else:
                    break
            if not (root / "SecondaryMotion.Manager.exe").is_file():
                return {"ok": False, "message": "压缩包里没找到 SecondaryMotion.Manager.exe"}

            if any(tool.iterdir()):
                shutil.copytree(tool, backup)  # 先整体备份旧版（首次安装是空目录，不用备）
            # 2026-10-01 修（⑥）：不再"就地递归删除"。工具目录只保证"某处有
            # Manager.exe"，用户完全可能把它解压到桌面或游戏目录里 —— 直接 rmtree
            # 会连带删掉同目录里与本工具无关的文件，而 `ignore_errors=True`
            # 又把失败吞了。改成"移动到备份区"：可逆、失败可见。
            removed_dir = backup.with_name(backup.name + "_replaced")
            for child in list(tool.iterdir()):
                if child.name in keep or child.name in keep_files:
                    continue
                try:
                    removed_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(child), str(removed_dir / child.name))
                except OSError as exc:
                    _log(log, f"WARN 无法移走旧文件 {child.name}: {exc}")
            shutil.copytree(root, tool, dirs_exist_ok=True)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "message": f"更新失败: {exc}"}

    _log(log, f"SecondaryMotion 已更新，旧版备份在 {backup}")
    return {"ok": True, "backup": str(backup), "tool_dir": str(tool), "archive": str(archive)}
