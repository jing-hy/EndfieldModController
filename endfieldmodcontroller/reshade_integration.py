"""Integration helpers for a ReShade installation that already lives in the game folder.

The game folder must stay untouched by the generic staging flow, but when ReShade is
already installed next to the game executable there is no reliable way to make its
add-on UI visible from an external runtime directory.  In that specific case
EndfieldModController deploys only three small integration files into the game folder and
keeps a manifest so the operation is fully reversible:

* ``endfieldmodcontroller.addon64``
* ``actions.tsv``
* ``user_ini_path.txt``

Existing files with the same names are backed up first.

⚠ **addon 必须放在 ReShade 自己的 base 目录**（2026-10-01 实测证据，见
`lesson 0muovz4ap`）：ReShade 6.8 的日志写死了

    Searching for add-ons (*.addon, *.addon64) in '<d3d12.dll 所在目录>'

也就是**只搜 d3d12.dll 所在的那个目录**（xxmi_extra 方式下 = `<数据根>\\runtime\\dlss5`，
它的日志原文就是 `loaded from '...\\runtime\\dlss5\\d3d12.dll'`）。此前代码把面板写进
`runtime\\reshade\\Addons\\`、`runtime\\migoto\\Addons\\`，两处都不在搜索范围内 ——
于是"键被改死了、面板却不存在"，用户的 Mod 快捷键全没了。所以本模块的部署目标是
:func:`panel_base_dirs` 给出的目录（dlss5 优先，能定位到游戏目录时再补一份）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig, resource_root
from . import core

MANIFEST_NAME = "existing_reshade_files.json"
ADDON_NAME = "endfieldmodcontroller.addon64"
# 我们自己写过的历史文件名（清理旧部署时用；不会碰别人的 addon）
LEGACY_ADDON_NAMES = ("endfieldmodcontroller.addon", "EndfieldModController.addon")

CONFLICTING_ADDON_NAMES = ("renodx-dlss.addon64", "renodx-dlss.addon", "renodx-dlss.addon64.disabled")



def built_addon_path() -> Path | None:
    """随包的自研 ReShade 面板（addon）在哪。

    ① 资源根（打包后 = PyInstaller 的 `_MEIPASS`，源码 = 工作区）——
       这是**唯一**在发布版里也能命中的位置（旧实现用
       `Path(__file__).parents[1] / "dist"`，onefile 下永远返回 None，
       部署那一步被静默跳过）；
    ② 开发期的构建产物目录。找不到时**由调用方记日志**，绝不静默。
    """
    roots = [resource_root()]
    if not getattr(sys, "frozen", False):
        roots.append(Path(__file__).resolve().parents[1])
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        for candidate in (
            root / "assets" / "addon" / ADDON_NAME,
            root / ADDON_NAME,
            root / "reshade_addon" / "build" / ADDON_NAME,
            root / "reshade_addon" / "build" / "endfieldmodcontroller.addon",
            root / "dist" / ADDON_NAME,
            root / "dist" / "endfieldmodcontroller.addon",
        ):
            if candidate.is_file():
                return candidate
    return None


def panel_base_dirs(config: AppConfig) -> list[Path]:
    """面板要落地的目录（按优先级）。

    * **`xxmi_extra`（推荐方式）**：base = DLSS5 目录（`d3d12.dll` 的家），只装那儿一份
      —— 游戏目录里既不需要、也不该多出文件（用户的规矩：不往游戏本体目录塞东西）。
    * **`external`（用户自己在游戏目录装了 ReShade）**：base 就是游戏目录，那里也装一份。
    * **`none`（不注入 ReShade）**：没有 base，**一个地方都不装**（面板也没法出现，
      所以 `takeover_possible` 会拒绝锁键）。
    """
    injection = str(getattr(config, "reshade_injection", "") or "").lower()
    if injection not in {"external", "xxmi_extra"}:
        return []
    dirs: list[Path] = [config.dlss5_path]
    if injection == "external":
        try:
            game_dir = detect_game_dir(config, allow_scan=False)
        except Exception:  # noqa: BLE001 - 探测失败不该拦住部署
            game_dir = None
        if game_dir is not None:
            resolved = Path(game_dir)
            if all(str(resolved).lower() != str(item).lower() for item in dirs):
                dirs.append(resolved)
    return dirs


def takeover_possible(config: AppConfig) -> tuple[bool, str]:
    """现在这套配置下，面板真的能出现在游戏里吗？（"锁键"必须先过这一关）

    教训（2026-10-01）：把用户原本能用的东西改成"由我们中转"之前，必须先证明
    中转件真的会被加载。所以只要有一条不满足，调用方就**不许**改写 Mod 热键。
    """
    injection = str(getattr(config, "reshade_injection", "") or "").lower()
    if injection not in {"external", "xxmi_extra"}:
        return False, "当前设置为「不注入 ReShade」，游戏里没有面板可供操作"
    dll = config.reshade_dll_path
    if dll is None or not Path(dll).is_file():
        return False, "找不到 ReShade 底座 d3d12.dll"
    if built_addon_path() is None:
        return False, "随包的面板 addon 文件缺失（安装不完整）"
    return True, ""


def panel_status(config: AppConfig) -> dict[str, Any]:
    """面板现状（自检 / 界面共用一套判据）。"""
    base = config.dlss5_path
    addon = base / ADDON_NAME
    actions = base / "actions.tsv"
    possible, reason = takeover_possible(config)
    return {
        "base_dir": str(base),
        "addon": str(addon),
        "addon_present": addon.is_file(),
        "actions_present": actions.is_file(),
        "built_addon": str(built_addon_path() or ""),
        "possible": possible,
        "reason": reason,
        "ready": possible and addon.is_file() and actions.is_file(),
    }


def ensure_panel_font(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """让 ReShade 用一个**带中文字形**的字体，否则面板里的中文全是方块。

    ReShade 默认字体是内置的 `ProggyClean`（纯 ASCII）。ReShade 6.8 用的 ImGui 1.92 是
    **动态字体**：字体文件里有字就能画出来，不需要预先声明字形范围 —— 所以只要把
    `ReShade.ini` 的 `[STYLE] Font=` 指向系统里的中文字体（`C:\\Windows\\Fonts\\msyh.ttc`），
    面板的中文含义就能正常显示（写前备份，且**只在原来为空时**才写，绝不覆盖用户的选择）。
    """
    if not getattr(config, "reshade_panel_font", True):
        return {"changed": False, "reason": "面板字体开关已关闭"}
    ini = config.dlss5_ini_path
    if not ini.is_file():
        return {"changed": False, "reason": f"没有 {ini}"}

    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    chosen: Path | None = None
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "Deng.ttf", "simsun.ttc"):
        candidate = font_dir / name
        if candidate.is_file():
            chosen = candidate
            break
    if chosen is None:
        return {"changed": False, "reason": "系统里找不到中文字体（msyh/simhei/…）"}

    try:
        text = ini.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return {"changed": False, "reason": f"读取失败: {exc}"}

    section = ""
    lines = text.splitlines()
    changed = False
    out: list[str] = []
    insert_at: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "style" and insert_at is None:
                insert_at = len(out)
            section = stripped[1:-1].strip().lower()
            out.append(line)
            continue
        if section == "style":
            match = re.match(r"^(\s*)Font\s*=\s*(.*)$", line, re.IGNORECASE)
            if match and match.group(2).strip():
                # 用户已经设过字体，尊重它（只要不是空值）
                return {"changed": False, "reason": "ReShade 已配置自定义字体，未改动"}
            if match:
                out.append(f"{match.group(1)}Font={chosen}")
                changed = True
                continue
        out.append(line)
    if not changed:
        if insert_at is None:
            out.extend(["", "[STYLE]", f"Font={chosen}"])
        else:
            out.insert(insert_at, f"Font={chosen}")
        changed = True

    try:
        backup = ini.with_name(ini.name + ".bak-before-panel-font")
        if not backup.exists():
            shutil.copy2(ini, backup)
        ini.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\r\n")
        if log is not None:
            log(f"统一面板字体: ReShade 字体已指向 {chosen.name}（备份 {backup.name}）")
    except OSError as exc:
        return {"changed": False, "reason": f"写入失败: {exc}"}
    return {"changed": True, "font": str(chosen), "reason": ""}


def cleanup_legacy_panels(config: AppConfig, *, log: Callable[[str], None] | None = None) -> list[str]:
    """删掉以前放在错误目录里的那一份面板（只删我们自己命名的文件）。"""
    removed: list[str] = []
    stale_dirs = [config.reshade_runtime_path / "Addons", config.reshade_runtime_path]
    for directory in stale_dirs:
        for name in LEGACY_ADDON_NAMES + (ADDON_NAME,):
            target = directory / name
            if not target.is_file():
                continue
            # 别把新位置的文件删了（两个目录理论上不会重叠，防一手）
            if any(
                str(target).lower() == str(base / ADDON_NAME).lower()
                for base in panel_base_dirs(config)
            ):
                continue
            try:
                target.unlink()
                removed.append(str(target))
                if log is not None:
                    log(f"清理旧位置的面板: {target}")
            except OSError as exc:
                if log is not None:
                    log(f"清理旧面板失败（忽略）: {target} -> {exc}")
    return removed


def deploy_panel(
    config: AppConfig,
    controller_dir: Path,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把统一面板装进 ReShade 会读的目录。

    写三样东西到每个 base 目录：`endfieldmodcontroller.addon64`、`actions.tsv`、
    `user_ini_path.txt`（addon 靠最后这个找到 `d3dx_user.ini`）。
    任何一步失败都**记进结果与日志**，绝不静默跳过（这正是上次翻车的地方）。
    """
    addon_source = built_addon_path()
    actions_source = Path(controller_dir) / "actions.tsv"
    deployed: list[str] = []
    warnings: list[str] = []

    def note(message: str) -> None:
        warnings.append(message)
        if log is not None:
            log(message)

    if addon_source is None:
        note("面板 addon 文件缺失：没有可部署的 endfieldmodcontroller.addon64")
    if not actions_source.is_file():
        note(f"动作清单缺失：{actions_source}（先跑一次「生成控制器」）")

    cleanup_legacy_panels(config, log=log)

    for base in panel_base_dirs(config):
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            note(f"创建目录失败 {base}: {exc}")
            continue
        if addon_source is not None:
            target = base / ADDON_NAME
            try:
                shutil.copy2(addon_source, target)
                deployed.append(str(target))
            except OSError as exc:
                # 游戏/XXMI 正在运行时会占住这个文件；这不是致命错误，
                # 但要留痕（下次一键启动会再试一遍）。
                note(f"写入面板失败 {target}: {exc}")
        if actions_source.is_file():
            try:
                shutil.copy2(actions_source, base / "actions.tsv")
            except OSError as exc:
                note(f"写入 actions.tsv 失败 {base}: {exc}")
        try:
            (base / "user_ini_path.txt").write_text(
                str(config.user_ini_path), encoding="utf-8", newline="\n"
            )
        except OSError as exc:
            note(f"写入 user_ini_path.txt 失败 {base}: {exc}")

    possible, reason = takeover_possible(config)
    # `panel_info.txt` 的 `takeover` 字段只有**一个**含义：Mod 原键到底有没有被锁住 ——
    # 面板靠它决定要不要显示"原键被锁、面板按键不会生效"那条橙色警告。
    # 2026-10-02：锁键动作已停用（见 `core.HOTKEY_LOCK_ENABLED` 的说明）⇒ 恒为 0，
    # 于是面板不会误报"按键不会生效"（它现在是直接发原键的遥控器）。
    takeover = (
        core.HOTKEY_LOCK_ENABLED
        and bool(getattr(config, "hotkey_takeover", False))
        and possible
    )
    action_count = 0
    if actions_source.is_file():
        try:
            with actions_source.open(encoding="utf-8", errors="replace") as handle:
                action_count = max(0, sum(1 for _ in handle) - 1)
        except OSError:
            action_count = 0
    info_text = (
        f"takeover={'1' if takeover else '0'}\n"
        f"actions={action_count}\n"
        f"generated={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"base={config.dlss5_path}\n"
    )
    for base in panel_base_dirs(config):
        try:
            (base / "panel_info.txt").write_text(info_text, encoding="utf-8", newline="\n")
        except OSError:
            pass

    return {
        "addon_source": str(addon_source) if addon_source else "",
        "base_dirs": [str(item) for item in panel_base_dirs(config)],
        "deployed": deployed,
        "warnings": warnings,
        "possible": possible,
        "reason": reason,
        "takeover": takeover,
        "action_count": action_count,
    }


def xxmi_config_path(launcher: Path) -> Path | None:
    candidates = [
        launcher.parent.parent.parent / "XXMI Launcher Config.json",
        launcher.parent.parent / "XXMI Launcher Config.json",
        launcher.parent / "XXMI Launcher Config.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def disable_conflicting_addons(game_dir: Path, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Physically hide add-ons known to conflict with the EFMI/ReShade mix.

    ``ReShade.ini`` ``DisabledAddons`` is not reliably honoured by every
    ReShade build, so the conflicting add-on file is renamed instead.  The
    original file is kept next to the game executable and can be restored by
    renaming it back.
    """
    disabled: list[str] = []
    warnings: list[str] = []
    for name in ("renodx-dlss.addon64", "renodx-dlss.addon"):
        source = game_dir / name
        if not source.is_file():
            continue
        target = source.with_name(source.name + ".endfieldmodcontroller.disabled")
        try:
            if target.exists():
                target.unlink()
            source.rename(target)
            disabled.append(f"{source} -> {target}")
            if log is not None:
                log(f"已物理禁用冲突 addon: {source.name} -> {target.name}")
        except OSError as exc:
            warnings.append(f"禁用 {source.name} 失败: {exc}")
    return {"disabled": disabled, "warnings": warnings}


def restore_conflicting_addons(game_dir: Path, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Restore add-ons renamed by :func:`disable_conflicting_addons`."""
    restored: list[str] = []
    warnings: list[str] = []
    for name in ("renodx-dlss.addon64.endfieldmodcontroller.disabled", "renodx-dlss.addon.endfieldmodcontroller.disabled"):
        source = game_dir / name
        if not source.is_file():
            continue
        target_name = name.replace(".endfieldmodcontroller.disabled", "")
        target = game_dir / target_name
        try:
            if target.exists():
                target.unlink()
            source.rename(target)
            restored.append(f"{source} -> {target}")
            if log is not None:
                log(f"已恢复冲突 addon: {target.name}")
        except OSError as exc:
            warnings.append(f"恢复 {target_name} 失败: {exc}")
    return {"restored": restored, "warnings": warnings}


def detect_game_dir(config: AppConfig, *, allow_scan: bool = True) -> Path | None:
    game_exe = config.game_exe_path
    if game_exe is not None and game_exe.is_file():
        return game_exe.parent

    # ② 从**官方启动器路径**推断 `<启动器根>/games/<游戏目录>`。
    #    空环境里往往是这种情况：`official_launcher` 有值、`game_exe` 为空，而这里以前
    #    没有这一步，于是只能靠全盘扫描兜底（在 exe 里可能失败、或被缓存成空）→
    #    「未定位到游戏目录」→ 连带 XXMI 的 `game_folder` 写不进去、sbm 检查也报
    #    「注入不完整」（2026-09-29 定位：这两个现象其实是同一个根因）。
    launcher_hint = str(getattr(config, "official_launcher", "") or "").strip()
    if launcher_hint:
        try:
            root = config.resolve_path(launcher_hint).parent
        except Exception:  # noqa: BLE001
            root = None
        if root is not None:
            for games_name in ("games", "Games"):
                games_dir = root / games_name
                if not games_dir.is_dir():
                    continue
                try:
                    children = sorted(games_dir.iterdir())
                except OSError:
                    continue
                for child in children:
                    if child.is_dir() and (child / "Endfield.exe").is_file():
                        return child

    launcher = config.xxmi_launcher_path
    if launcher is None:
        return None
    config_path = xxmi_config_path(launcher)
    data: dict = {}
    if config_path is not None:
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    # ③ **遍历所有 importer 的 game_folder**（2026-10-01 修）：原先只读 EFMI 一家 ——
    #    用户换过 importer、或只有别的 importer 配过游戏目录时，这里就整体读不到，
    #    于是"未定位到游戏目录"→ XXMI 的 game_folder/active_importer/enabled_importers
    #    三个字段全都写不进去（一份真实诊断包里 `active_importer: None` 就是这么来的）。
    #    顺序：`Launcher.active_importer` 指向的那个优先，然后其余 importer；
    #    带 `Endfield.exe` 的目录优先，只有目录（没 exe）的作为兜底。
    if data:
        importers = data.get("Importers") if isinstance(data.get("Importers"), dict) else {}
        active = str((data.get("Launcher") or {}).get("active_importer") or "")
        order = ([active] if active else []) + [name for name in importers if name != active]
        fallback: Path | None = None
        for name in order:
            block = importers.get(name)
            if not isinstance(block, dict):
                continue
            folder = (block.get("Importer") or {}).get("game_folder")
            if not folder:
                continue
            path = Path(str(folder))
            if not path.is_dir():
                continue
            if (path / "Endfield.exe").is_file():
                return path
            if fallback is None:
                fallback = path
        if fallback is not None:
            return fallback
    # ③.5 **从 XXMI 自己的启动日志里捞真实路径**（2026-10-01 加）：XXMI 每次注入都会记
    #     `Successfully injected DLL to process Endfield.exe … ` 与
    #     `exe_path=WindowsPath('…/Endfield Game/Endfield.exe')` —— 只要用户用它启动过一次
    #     （哪怕配置里的 game_folder 是空的），日志里就有真路径，比全盘扫描可靠得多。
    from_log = game_dir_from_xxmi_log(launcher, config_path)
    if from_log is not None:
        return from_log
    # ④ 兜底：自动搜索游戏本体（不硬编码任何盘符/目录）
    #
    # `allow_scan=False` 时**绝不扫盘** —— 界面刷新（get_state）走的就是这条路。
    # pywebview 的 js_api 调用是在 GUI 线程上执行的，这里一旦扫遍所有盘符，窗口渲染
    # 会被一起冻住：2026-10-01 实测从零启动时窗口出现后一直白屏，日志里
    # `get_state()` → `scan()` 之间隔了 18 秒，用户看到的就是"窗口亮得慢、没有加载页"。
    if not allow_scan:
        return None
    from .config import auto_detect_game_dir

    guess = auto_detect_game_dir()
    return Path(guess) if guess else None


GAME_EXE_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\r\n'\"<>|]*?[\\/]Endfield\.exe)", re.IGNORECASE)


def game_dir_from_xxmi_log(launcher: Path, config_path: Path | None = None) -> Path | None:
    """从 `XXMI Launcher Log.txt` 里捞游戏目录（XP 那台机器游戏在 W 盘时救过场）。

    只要用户用 XXMI 启动过一次游戏，日志里就会留下
    `Successfully injected DLL to process Endfield.exe (PID: …)` 或
    `exe_path=WindowsPath('…/Endfield Game/Endfield.exe')` —— 直接解析出路径，
    **不必依赖配置里的 `game_folder`，也不必全盘扫描**。
    只读日志末尾 256 KB；路径必须真实存在才采用。
    """
    bases = [p for p in (config_path.parent if config_path else None,
                         launcher.parent, launcher.parent.parent,
                         launcher.parent.parent.parent) if p is not None]
    seen: set[Path] = set()
    for base in bases:
        if base in seen:
            continue
        seen.add(base)
        log_path = base / "XXMI Launcher Log.txt"
        if not log_path.is_file():
            continue
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as handle:
                if size > 262_144:
                    handle.seek(size - 262_144)
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for match in reversed(GAME_EXE_PATH_RE.findall(text)):
            candidate = Path(match)
            if candidate.is_file():
                return candidate.parent
    return None


def detect_render_api(game_dir: Path) -> str:
    """Heuristically detect the main graphics API from the latest ReShade.log entries."""
    player_log = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "Hypergryph" / "Endfield" / "Player.log"
    if player_log.is_file():
        try:
            player_text = player_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            player_text = ""
        # Endfield may initialize auxiliary Vulkan/DLSS subsystems even when the
        # launcher is told to use DX11.  The explicit "Forcing GfxDevice" line is
        # the API actually selected for the render device, so it must win over the
        # later auxiliary Vulkan lines.
        if "Forcing GfxDevice: Direct3D 11" in player_text or "Forcing GfxDevice: Direct3D11" in player_text:
            return "d3d11"
        if "Forcing GfxDevice: Direct3D 12" in player_text or "Forcing GfxDevice: Direct3D12" in player_text:
            return "d3d12"
        if "Forcing GfxDevice: Vulkan" in player_text:
            return "vulkan"
        if "Vulkan init" in player_text or "VK_LAYER" in player_text:
            return "vulkan"
        if "DirectX 11" in player_text or "D3D11" in player_text:
            return "d3d11"
        if "D3D12" in player_text or "DirectX 12" in player_text:
            return "d3d12"
    log_path = Path(game_dir) / "ReShade.log"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown"
    if not text:
        return "unknown"
    swap = max(text.rfind("CreateSwapChainForHwnd"), text.rfind("CreateSwapChain"))
    if swap < 0:
        swap = len(text)
    pos11 = text.rfind("D3D11CreateDeviceAndSwapChain", 0, swap + 1)
    pos12 = text.rfind("D3D12CreateDevice", 0, swap + 1)
    if pos12 > pos11:
        return "d3d12"
    if pos11 > pos12:
        return "d3d11"
    overall12 = text.rfind("D3D12CreateDevice")
    overall11 = text.rfind("D3D11CreateDeviceAndSwapChain")
    if overall12 > overall11:
        return "d3d12"
    if overall11 >= 0:
        return "d3d11"
    return "unknown"


def detect_existing_reshade(config: AppConfig) -> dict[str, Any] | None:
    game_dir = detect_game_dir(config)
    if game_dir is None:
        return None
    ini = game_dir / "ReShade.ini"
    proxies = [game_dir / name for name in ("dxgi.dll", "d3d12.dll") if (game_dir / name).is_file()]
    if ini.is_file() and proxies:
        return {
            "game_dir": str(game_dir),
            "ini": str(ini),
            "proxies": [str(path) for path in proxies],
        }
    return None


def manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / MANIFEST_NAME


def _read_manifest(config: AppConfig) -> dict[str, Any]:
    """读集成清单 —— 实现收敛到 `fsutil.read_json`（2026-10-04）。

    原先 `_read_manifest` / `_read_safe_mode_manifest` / `_read_d3d12_swap_manifest`
    三份逐字节相同；对应的三份 `_write_*` 也都不是原子写。任一处修好另两处不会跟着修
    —— 本次审计里"安全模式 manifest 非原子"与"d3d12 swap manifest 非原子"就是这么重复出来的。
    """
    from . import fsutil

    return fsutil.read_json(manifest_path(config))


def _backup_name(path: Path) -> Path:
    """给"即将被我们覆盖的文件"取一个备份名 —— **名字里带内容指纹**（2026-10-04 改）。

    为什么不再用固定名（原来叫 `<名>.endfieldmodcontroller.bak`）：那份备份**只建一次**
    （`if not candidate.exists()`），于是"目标后来被游戏或用户更新过"时，我们覆盖它
    **不留新备份**，而 `remove_existing_reshade()` 还原回去的是**更早那份内容** ——
    用户以为回到了"我们动手之前"，其实回到了更早的状态（**还原失真**）。
    带 sha256 之后：内容变了就是新备份名（保留历史、不覆盖），内容没变则复用同一份
    （不会每启动一次就多一个垃圾文件）。
    """
    from . import fsutil

    try:
        digest = fsutil.sha256_file(path)[:12]
    except OSError:
        digest = "unreadable"
    return path.with_name(f"{path.name}.endfieldmodcontroller.{digest}.bak")


# 我们自己装进游戏目录的文件都带这个标记（addon 的版本资源、面板 ini 的注释头…）。
# 用在 manifest 丢失时**别把我们自己的文件当成"用户原件"备份**（那会让还原把我们的
# addon 当原版放回去）。只读文件头，开销可忽略。
_OUR_MARKER = b"EndfieldModController"


def _looks_like_ours(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            head = handle.read(1 << 16)
    except OSError:
        return False
    return _OUR_MARKER in head


def _install_file(
    target: Path,
    source: Path | None,
    content: str | None = None,
    *,
    owned: bool = False,
    previous_backup: str | None = None,
) -> dict[str, str | None]:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.is_file():
        # ⚠️ manifest 丢失时，**别把我们自己的文件当成"用户原件"备份**（2026-10-04 修）：
        # 那会在还原时把我们的 addon 当原版放回游戏目录（`remove_existing_reshade` 就是
        # 照着 manifest 的 `backup` 复制的）。判据 = 内容里有我们的标记 ⇒ 视为自有文件。
        if not owned and _looks_like_ours(target):
            owned = True
        if owned:
            if previous_backup:
                candidate = Path(previous_backup)
                if candidate.is_file():
                    backup = candidate
        else:
            candidate = _backup_name(target)
            if not candidate.exists():
                shutil.copy2(target, candidate)
            backup = candidate
    if source is not None:
        shutil.copy2(source, target)
    elif content is not None:
        target.write_text(content, encoding="utf-8")
    else:  # pragma: no cover - defensive, callers always pass one
        raise ValueError("source or content is required")
    return {"path": str(target), "backup": str(backup) if backup else None}


def deploy_existing_reshade(
    config: AppConfig,
    info: dict[str, Any] | None = None,
    *,
    controller_dir: Path | None = None,
) -> dict[str, Any]:
    info = info or detect_existing_reshade(config)
    if info is None:
        raise RuntimeError("no existing ReShade installation was detected")
    game_dir = Path(info["game_dir"])
    addon = built_addon_path()
    if addon is None:
        raise RuntimeError("EndfieldModController ReShade add-on is missing")

    actions_source: Path | None = None
    if controller_dir is not None:
        candidate = controller_dir / "actions.tsv"
        if candidate.is_file():
            actions_source = candidate
    if actions_source is None:
        candidate = config.reshade_runtime_path / "actions.tsv"
        if candidate.is_file():
            actions_source = candidate
    if actions_source is None:
        raise RuntimeError("actions.tsv is missing; run prepare before launching")

    previous: dict[str, dict[str, str | None]] = {}
    for entry in _read_manifest(config).get("files", []):
        if isinstance(entry, dict) and entry.get("path"):
            previous[str(entry["path"])] = entry

    def install(target: Path, source: Path | None, content: str | None = None) -> dict[str, str | None]:
        old = previous.get(str(target))
        return _install_file(
            target,
            source,
            content,
            owned=old is not None,
            previous_backup=(old or {}).get("backup"),
        )

    entries: list[dict[str, str | None]] = []
    entries.append(install(game_dir / ADDON_NAME, addon))
    entries.append(install(game_dir / "actions.tsv", actions_source))
    entries.append(install(game_dir / "user_ini_path.txt", None, str(config.user_ini_path)))

    data = {
        "game_dir": str(game_dir),
        "files": entries,
    }
    path = manifest_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return {"manifest": str(path), "game_dir": str(game_dir), "files": entries}


def remove_existing_reshade(config: AppConfig) -> dict[str, Any]:
    """把"我们装进游戏目录的那套 ReShade 集成"撤掉，并把用户原件放回去。

    ⚠️ **失败时不许把清单删掉**（2026-10-04 修）：清单是"原件存在哪个 .bak"的唯一索引。
    原来删除目标失败只 `continue`、回拷失败只 `pass`，**随后无条件删清单** ⇒ 之后再也
    没法重试还原、`.endfieldmodcontroller.bak` 变成没人认领的孤儿文件（用户只能手工去
    改名）。现在：只有全部成功才删清单，有失败就把失败项如实返回、清单留着。
    """
    path = manifest_path(config)
    if not path.is_file():
        return {"ok": True, "removed": [], "restored": []}
    data = _read_manifest(config)
    removed: list[str] = []
    restored: list[str] = []
    failures: list[str] = []
    for entry in data.get("files", []):
        if not isinstance(entry, dict):
            continue
        target = Path(str(entry.get("path") or ""))
        backup = Path(str(entry.get("backup") or "")) if entry.get("backup") else None
        if target.is_file():
            try:
                target.unlink()
                removed.append(str(target))
            except OSError as exc:
                failures.append(f"删除 {target.name} 失败: {exc}")
                continue
        if backup is not None and backup.is_file():
            try:
                shutil.copy2(backup, target)
                # ⚠️ 备份**不再删掉**：它是唯一一份用户原件。删了之后万一这次复制是坏的，
                # 就再也回不去了（"有备份但还原不回去"是本项目最忌讳的一类问题）。
                restored.append(str(target))
            except OSError as exc:
                failures.append(f"还原 {target.name} 失败: {exc}")
    if not failures:
        try:
            path.unlink()
        except OSError:
            pass
    return {"ok": not failures, "removed": removed, "restored": restored,
            "warnings": failures}


SAFE_MODE_MANIFEST_NAME = "anti_cheat_safe_mode.json"


def safe_mode_manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / SAFE_MODE_MANIFEST_NAME


def _read_safe_mode_manifest(config: AppConfig) -> dict[str, Any]:
    from . import fsutil

    return fsutil.read_json(safe_mode_manifest_path(config))


def _write_safe_mode_manifest(config: AppConfig, data: dict[str, Any]) -> None:
    """**原子写**（2026-10-04 修）：这份清单是"安全模式改过哪些文件"的唯一还原依据，
    原来直接 `write_text` —— 写到一半被杀/断电就留下半截 JSON，`_read_*` 只能返回 {}，
    而 `safe_mode_active()` 只看文件在不在 ⇒ 界面说"安全模式开着"，点还原却什么都不做。"""
    from . import fsutil

    fsutil.write_json(safe_mode_manifest_path(config), data)


def safe_mode_active(config: AppConfig) -> bool:
    """安全模式是不是真的生效中 —— **判据是"清单能解析且条目非空"**（2026-10-04 修）。

    原来只看 `manifest.is_file()`：文件存在但内容半截（写坏）/ 是空 `{}` 时同样返回 True，
    于是 `enable_d3d12_proxy_mode` 会去调 `restore_anti_cheat_safe_mode`，而那边一条条目
    都拿不到、空转一遍再把清单删掉 —— 用户看到"还原了"但文件其实没动。
    """
    data = _read_safe_mode_manifest(config)
    if not data:
        return False
    for key in ("disabled_proxies", "restored", "moved", "apps", "entries"):
        value = data.get(key)
        if value:
            return True
    # 认不出的清单结构：保守认为"生效中"（宁可让用户看到还原按钮，也别隐瞒状态）
    return bool(data)


def _looks_like_reshade_dll(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return b"ReShade" in data or b"reshade" in data or b"crosire" in data


def _game_reshade_dll_candidates(config: AppConfig, info: dict[str, Any] | None = None) -> list[Path]:
    info = info or detect_existing_reshade(config)
    if info is None:
        return []
    game_dir = Path(info["game_dir"])
    preferred = [game_dir / "dxgi.dll", game_dir / "d3d12.dll"]
    existing = [Path(item) for item in info.get("proxies", [])]
    result: list[Path] = []
    for path in preferred + existing:
        if path.is_file() and path not in result:
            result.append(path)
    return result


def adopt_game_reshade_dll(config: AppConfig, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Copy the game-directory ReShade DLL into runtime/reshade for XXMI injection.

    The existing game-directory ReShade is known to match the installed game and
    supports the same add-on API as the EndfieldModController add-on, so it is safer
    than downloading a different ReShade version.
    """
    candidates = _game_reshade_dll_candidates(config, info)
    source = next((path for path in candidates if _looks_like_reshade_dll(path)), None)
    if source is None:
        raise RuntimeError("no ReShade DLL was found in the game directory")
    target = config.reshade_runtime_path / "ReShade64.dll"
    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.is_file():
        candidate = _backup_name(target)
        if not candidate.exists():
            shutil.copy2(target, candidate)
        backup = candidate
    shutil.copy2(source, target)
    data = _read_safe_mode_manifest(config)
    data["adopted_reshade_dll"] = str(target)
    data["adopted_from"] = str(source)
    data["reshade_dll_backup"] = str(backup) if backup else None
    _write_safe_mode_manifest(config, data)
    return {
        "source": str(source),
        "target": str(target),
        "backup": str(backup) if backup else None,
    }


def disable_game_reshade_proxies(config: AppConfig, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """把游戏目录里的 ReShade proxy 改名停用（**改名不删**，可还原）。

    ⚠️⚠️ 两处修正（2026-10-04，都属于**备份名互相覆盖 / 还原信息丢失**）：
      ① 原来若 `<proxy>.endfieldmodcontroller.disabled` 已存在就**先 unlink 再 rename** ——
         那个 `.disabled` 里很可能就是**游戏自带的原始 dll**（不是我们放的），
         删掉就永久无主了。现在改用 `fsutil.unique_sibling` 取一个不冲突的名字
         （与 `launcher._unique_backup_path` 的"备份只增不删"同一原则）。
      ② 原来 `data["disabled_proxies"] = entries` **整份覆盖**，上一次的条目连同
         "怎么还回去"的信息一起丢失 ⇒ `restore_game_reshade_proxies()` 再也找不到它们。
         现在**追加合并**（按 disabled 路径去重）。
    """
    from . import fsutil

    info = info or detect_existing_reshade(config)
    if info is None:
        return {"ok": True, "disabled": []}
    game_dir = Path(info["game_dir"])
    entries: list[dict[str, str]] = []
    for proxy in [Path(item) for item in info.get("proxies", [])]:
        if not proxy.is_file():
            continue
        disabled = fsutil.unique_sibling(proxy.with_name(proxy.name + ".endfieldmodcontroller.disabled"))
        proxy.rename(disabled)
        entries.append({"original": str(proxy), "disabled": str(disabled)})
    data = _read_safe_mode_manifest(config)
    data["game_dir"] = str(game_dir)
    known = {str(item.get("disabled")) for item in (data.get("disabled_proxies") or [])
             if isinstance(item, dict)}
    merged = [item for item in (data.get("disabled_proxies") or []) if isinstance(item, dict)]
    merged.extend(item for item in entries if item["disabled"] not in known)
    data["disabled_proxies"] = merged
    _write_safe_mode_manifest(config, data)
    return {"ok": True, "game_dir": str(game_dir), "disabled": entries}


def restore_game_reshade_proxies(config: AppConfig) -> dict[str, Any]:
    data = _read_safe_mode_manifest(config)
    restored: list[str] = []
    errors: list[str] = []
    for entry in data.get("disabled_proxies", []):
        if not isinstance(entry, dict):
            continue
        original = Path(str(entry.get("original") or ""))
        disabled = Path(str(entry.get("disabled") or ""))
        if disabled.is_file() and not original.exists():
            try:
                disabled.rename(original)
                restored.append(str(original))
            except OSError as exc:
                errors.append(f"{disabled}: {exc}")
    return {"ok": not errors, "restored": restored, "errors": errors}


def clear_safe_mode_manifest(config: AppConfig) -> None:
    try:
        safe_mode_manifest_path(config).unlink()
    except OSError:
        pass


D3D12_SWAP_MANIFEST_NAME = "dxgi_to_d3d12.json"


def d3d12_swap_manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / D3D12_SWAP_MANIFEST_NAME


def _read_d3d12_swap_manifest(config: AppConfig) -> dict[str, Any]:
    from . import fsutil

    return fsutil.read_json(d3d12_swap_manifest_path(config))


def _write_d3d12_swap_manifest(config: AppConfig, data: dict[str, Any]) -> None:
    """**原子写**（2026-10-04 修，理由同 `_write_safe_mode_manifest`）。"""
    from . import fsutil

    fsutil.write_json(d3d12_swap_manifest_path(config), data)


def swap_dxgi_to_d3d12(config: AppConfig, info: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rename only ``dxgi.dll`` away, leaving a ReShade ``d3d12.dll`` proxy in place.

    Endfield dynamically loads ``d3d12.dll`` even in its DX11 path, so this is a
    common workaround when the anti-cheat rejects the ``dxgi.dll`` module name.
    """
    info = info or detect_existing_reshade(config)
    if info is None:
        raise RuntimeError("no existing ReShade installation was detected")
    game_dir = Path(info["game_dir"])
    dxgi = game_dir / "dxgi.dll"
    d3d12 = game_dir / "d3d12.dll"
    old_data = _read_d3d12_swap_manifest(config)

    disabled: Path | None = None
    if dxgi.is_file():
        disabled = dxgi.with_name("dxgi.dll.endfieldmodcontroller.disabled")
        if disabled.exists():
            disabled.unlink()
        dxgi.rename(disabled)
    elif old_data.get("disabled_dxgi"):
        candidate = Path(str(old_data["disabled_dxgi"]))
        if candidate.is_file():
            disabled = candidate

    marker = game_dir / "dxgi.dll.dlss5oneclick"
    disabled_marker: Path | None = None
    if marker.is_file():
        disabled_marker = marker.with_name("dxgi.dll.dlss5oneclick.endfieldmodcontroller.disabled")
        if disabled_marker.exists():
            disabled_marker.unlink()
        marker.rename(disabled_marker)
    elif old_data.get("disabled_marker"):
        candidate = Path(str(old_data["disabled_marker"]))
        if candidate.is_file():
            disabled_marker = candidate

    created_d3d12 = bool(old_data.get("created_d3d12"))
    if not d3d12.is_file():
        source = disabled
        if source is None:
            source = next((Path(item) for item in info.get("proxies", []) if Path(item).name == "dxgi.dll"), None)
        if source is None or not source.is_file():
            raise RuntimeError("no ReShade DLL is available to use as d3d12.dll")
        shutil.copy2(source, d3d12)
        created_d3d12 = True
    data = {
        "game_dir": str(game_dir),
        "disabled_dxgi": str(disabled) if disabled else None,
        "disabled_marker": str(disabled_marker) if disabled_marker else None,
        "created_d3d12": created_d3d12,
    }
    _write_d3d12_swap_manifest(config, data)
    return {
        "game_dir": str(game_dir),
        "disabled_dxgi": data["disabled_dxgi"],
        "disabled_marker": data["disabled_marker"],
        "d3d12": str(d3d12),
        "created_d3d12": created_d3d12,
    }


def restore_dxgi_from_d3d12(config: AppConfig) -> dict[str, Any]:
    data = _read_d3d12_swap_manifest(config)
    actions: list[str] = []
    errors: list[str] = []
    game_dir = Path(str(data.get("game_dir") or ""))
    disabled = Path(str(data.get("disabled_dxgi"))) if data.get("disabled_dxgi") else None
    if disabled is not None and disabled.is_file():
        original = game_dir / "dxgi.dll"
        if not original.exists():
            try:
                disabled.rename(original)
                actions.append(str(original))
            except OSError as exc:
                errors.append(f"{disabled}: {exc}")
    disabled_marker = Path(str(data.get("disabled_marker"))) if data.get("disabled_marker") else None
    if disabled_marker is not None and disabled_marker.is_file():
        original_marker = game_dir / "dxgi.dll.dlss5oneclick"
        if not original_marker.exists():
            try:
                disabled_marker.rename(original_marker)
                actions.append(str(original_marker))
            except OSError as exc:
                errors.append(f"{disabled_marker}: {exc}")
    if data.get("created_d3d12"):
        d3d12 = game_dir / "d3d12.dll"
        if d3d12.is_file():
            try:
                d3d12.unlink()
                actions.append(f"removed {d3d12}")
            except OSError as exc:
                errors.append(f"{d3d12}: {exc}")
    try:
        d3d12_swap_manifest_path(config).unlink()
    except OSError:
        pass
    return {"ok": not errors, "actions": actions, "errors": errors}


GLOBAL_RESHADE_MANIFEST_NAME = "global_reshade_apps.json"


def global_reshade_apps_path() -> Path:
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    return Path(program_data) / "ReShade" / "ReShadeApps.ini"


def global_reshade_manifest_path(config: AppConfig) -> Path:
    return config.runtime_path / GLOBAL_RESHADE_MANIFEST_NAME


def _parse_global_reshade_apps(text: str) -> list[str]:
    apps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("apps="):
            continue
        value = stripped[5:].strip()
        if not value:
            continue
        for part in value.replace(",", ";").split(";"):
            part = part.strip()
            if part:
                apps.append(part)
    return apps


def disable_global_reshade_for_game(config: AppConfig) -> dict[str, Any]:
    """Remove Endfield.exe from ReShade's global injection list, reversibly.

    A global ReShade install (``C:/ProgramData/ReShade/ReShadeApps.ini``)
    loads ReShade before 3DMigoto and conflicts with it, even if the game
    directory has no dxgi.dll/d3d12.dll proxy.
    """
    path = global_reshade_apps_path()
    if not path.is_file():
        return {"ok": True, "path": str(path), "changed": False, "removed": []}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return {"ok": False, "path": str(path), "message": str(exc)}
    apps = _parse_global_reshade_apps(text)
    game_exe = config.game_exe_path
    game_names = {"endfield.exe"}
    if game_exe is not None:
        game_names.add(game_exe.name.lower())
    removed = [app for app in apps if Path(app).name.lower() in game_names]
    kept = [app for app in apps if Path(app).name.lower() not in game_names]
    if not removed and apps == kept:
        return {"ok": True, "path": str(path), "changed": False, "removed": []}
    backup = path.with_name(path.name + ".endfieldmodcontroller.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    if not kept:
        # An empty Apps= is treated by ReShade as "all applications" by some
        # global installs, so use an explicit non-matching path instead.
        kept = [str(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "ReShade" / "disabled.exe")]
    payload = "Apps=" + ";".join(kept) + chr(13) + chr(10)

    path.write_text(payload, encoding="utf-8-sig")
    manifest = {
        "path": str(path),
        "backup": str(backup),
        "original_apps": apps,
        "kept_apps": kept,
        "removed_apps": removed,
    }
    manifest_path = global_reshade_manifest_path(config)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(path), "changed": True, "removed": removed, "kept": kept, "backup": str(backup)}


def restore_global_reshade_apps(config: AppConfig) -> dict[str, Any]:
    """把 `%ProgramData%\\ReShade\\ReShadeApps.ini` 还原成我们动手之前的样子。

    ⚠️⚠️ **备份丢了就不许报成功**（2026-10-04 修的"假还原"）：原来 `backup` 不存在时
    **什么都不做**，却返回 `ok=True, restored=[target]` 并把清单删掉 —— 界面上显示
    "已还原"，实际 `Apps=` 里根本没把 Endfield.exe 加回去，用户**永久**失去全局注入
    且再也查不出原因。现在：缺备份 → `ok=False` + 说清该怎么手工补，并且**保留清单**。
    """
    manifest_path = global_reshade_manifest_path(config)
    if not manifest_path.is_file():
        return {"ok": True, "restored": []}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "message": "global_reshade_apps.json is invalid"}
    backup = Path(str(manifest.get("backup") or ""))
    target = Path(str(manifest.get("path") or ""))
    if not target.parts:
        return {"ok": False, "restored": [],
                "message": "还原清单里没有记录目标路径（global_reshade_apps.json 不完整），未做任何改动"}
    if not backup.is_file():
        return {
            "ok": False, "restored": [],
            "message": (
                f"找不到备份文件，**没有做任何改动**：\n  {backup}\n\n"
                f"你可以手动编辑 {target}，把 Endfield.exe 加回 `Apps=` 那一行"
                f"（或直接删掉这一行让 ReShade 自己重新收集）。\n"
                "清单已保留，修好备份后可以再点一次还原。"
            ),
        }
    try:
        shutil.copy2(backup, target)
    except OSError as exc:
        return {"ok": False, "restored": [], "message": f"还原 {target} 失败: {exc}"}
    try:
        manifest_path.unlink()
    except OSError:
        pass
    return {"ok": True, "restored": [str(target)]}


def integration_state(config: AppConfig) -> dict[str, Any]:
    info = detect_existing_reshade(config)
    if info is None:
        return {"detected": False}
    game_dir = Path(info["game_dir"])
    return {
        "detected": True,
        "game_dir": str(game_dir),
        "addon": (game_dir / ADDON_NAME).is_file(),
        "actions": (game_dir / "actions.tsv").is_file(),
        "user_ini": (game_dir / "user_ini_path.txt").is_file(),
        "manifest": manifest_path(config).is_file(),
    }


# ---------------------------------------------------------------------------
# Game directory injection audit
# ---------------------------------------------------------------------------
# Third-party loaders (older EndfieldModController builds, unrelated mod installers)
# drop a small proxy DLL next to the game executable.  Windows then loads that
# proxy instead of the real system module, the proxy forwards the exports *and*
# silently loads everything found in ``<game>/plugin/*.dll``.  That hides the
# genuine DLL and injects arbitrary code into the game process, so it must be
# detected and removed before any crash report can be trusted.
LOADER_PROXY_MODULES = (
    "dxgi.dll",
    "d3d12.dll",
    "d3d11.dll",
    "d3dcompiler_47.dll",
    "vulkan-1.dll",
    "nvapi64.dll",
    "winmm.dll",
    "version.dll",
    # 2026-10-01 补：注入器常用、原先**完全没纳入审计**的 proxy 名。
    # 起因是一份诊断包：那台机器装着 **OptiScaler DLSS-NR**（以 `WINHTTP.dll` 形式注入、
    # 接管 NGX 调用），而我们的名单里没有 winhttp → 「一键还原游戏本体」**根本不知道
    # 它在**，用户以为已经还原干净。用户明确要求「**一键还原游戏本体要全部移走**」。
    "winhttp.dll",
    "wininet.dll",
    "dbghelp.dll",
    "dinput8.dll",
    "d3d9.dll",
    "opengl32.dll",
    "nvngx.dll",
    # 2026-10-04 补：用户要求「一键还原终末地**清除所有第三方注入**，不管是不是
    # 管理器注入的，都要去掉（要备份）」—— 上面那份名单只覆盖了我们/XXMI 生态
    # 与 OptiScaler 常用的名字。下面这批是**注入器同样常用、原版终末地不会有**的
    # proxy 名（手柄 / 音频 / 主题 / 显示相关），补进来才能真的做到"全部移走"。
    # 判定仍走 `is_third_party_proxy()`（内容标记 / OptiScaler 特征 / 与 System32
    # 原版不同三条任一命中），所以**不会**误伤游戏自带的同名文件。
    "xinput1_3.dll",
    "xinput1_4.dll",
    "xinput9_1_0.dll",
    "dwmapi.dll",
    "uxtheme.dll",
    "msacm32.dll",
    "d3d8.dll",
    "dsound.dll",
    "winspool.drv",
    "cryptbase.dll",
)
# 第三方注入器/加载器留在游戏目录里的**非 DLL 痕迹**（原版绝不会有）：
# 3DMigoto 的 `d3dx.ini` / `d3dx_user.ini` / `ShaderFixes\`、自造 loader 的
# `loader_debug.log` / `inject_order.txt` / `mc_bootstrap.*`。
# 用途：`game_clean.audit()` 会把它们一并**备份移走**（用户 2026-10-04：
# 「不管是不是管理器注入的，都要去掉」）。
GAME_INJECTION_ARTIFACTS = (
    "d3dx.ini",
    "d3dx_user.ini",
    "d3dx.ini.bak",
    "d3dx_user.ini.bak",
    "loader_debug.log",
    "inject_order.txt",
    "mc_bootstrap.dll",
    "mc_bootstrap.log",
    "ShaderFixes",
)

LOADER_PROXY_DISABLED_SUFFIX = ".loader.endfieldmodcontroller.disabled"
PLUGIN_DISABLED_SUFFIX = ".endfieldmodcontroller.disabled"
GAME_INJECTION_MANIFEST = "game_dir_injections.json"
PLUGIN_DIR_NAME = "plugin"
# 游戏目录里的 loader proxy 有**两套血统**（两者都会把 `<游戏目录>\plugin\*.dll`
# 全部加载进游戏进程，所以"任一命中"都算 loader proxy）：
#   * SecondaryMotion（乳摇）的 proxy：`[LOADER] started` / `[LOADER] loading` / …
#   * Endfield Poser 的 proxy：`[PROXY] plugins loaded via …`（它自己的安装器
#     `Test-OurProxy` 也认这个串）。
# 2026-10-01 补：此前只认第一套，于是 Poser 的 proxy 在审计 / 停用 / 「一键还原游戏
# 本体」里会被**整体漏判** —— 表现为"游戏目录已经干净"，其实还挂着注入。
_SBM_PROXY_MARKERS = (b"[LOADER] started", b"no plugin dlls found", b"[LOADER] loading")
_POSER_PROXY_MARKER = b"[PROXY] plugins loaded via "
_BOOTSTRAP_MARKERS = _SBM_PROXY_MARKERS + (_POSER_PROXY_MARKER,)


def loader_kind(path: Path) -> str:
    """这个 DLL 属于哪套 loader proxy：``"sbm"`` / ``"poser"`` / ``""``（不是 proxy）。

    谁提供 proxy 决定"哪个插件能被加载"，所以状态显示与两个插件之间的协调都要用它。
    """
    try:
        with path.open("rb") as handle:
            blob = handle.read(512 * 1024)
    except OSError:
        return ""
    if _POSER_PROXY_MARKER in blob:
        return "poser"
    if any(marker in blob for marker in _SBM_PROXY_MARKERS):
        return "sbm"
    return ""


def game_injection_manifest_path(config: AppConfig) -> Path:
    return Path(config.runtime_path) / GAME_INJECTION_MANIFEST


def looks_like_loader_proxy(path: Path) -> bool:
    """Return True when *path* is a loader proxy rather than a genuine module.

    The check is marker based on purpose: a real ReShade ``d3d12.dll`` or the
    original Microsoft ``d3dcompiler_47.dll`` must never be reported.
    """
    try:
        with path.open("rb") as handle:
            blob = handle.read(512 * 1024)
    except OSError:
        return False
    return any(marker in blob for marker in _BOOTSTRAP_MARKERS)


# OptiScaler（DLSS-NR 替换注入器）：它自带的特征串，以及它注入时用的 proxy 名
# （默认就是 `winhttp.dll`）。2026-10-01 加 —— 一份诊断包里 `ReShade.log` 报
# `Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C`、面板 `NGX Hook 创建: 0`，
# 真相是 NGX 被 OptiScaler 接管，而我们的审计/净化**完全不认识它**。
_OPTISCALER_MARKERS = (
    b"OptiScaler",
    b"OptiScaler.ini",
    b"OptiScaler.log",
    b"dlss-nr",
    b"DLSS-NR",
    b"OptiScaler-DLSSNR",
)

# 第三方注入器留在游戏目录里的**配置/日志**（原版绝不会有）：proxy 移走了它们还留着，
# 用户会以为"没弄干净"。净化时会一并备份移走（用户 2026-10-01：「一键还原游戏本体要全部移走」）。
INJECTOR_DATA_NAMES = ("OptiScaler.ini", "OptiScaler.log", "OptiScaler.dll")


def looks_like_optiscaler(path: Path) -> bool:
    """这个文件是不是 OptiScaler（按内容特征，不看文件名）。"""
    try:
        with path.open("rb") as handle:
            blob = handle.read(512 * 1024)
    except OSError:
        return False
    return any(marker in blob for marker in _OPTISCALER_MARKERS)


def optiscaler_present(game_dir: Path | None, *, plugin_dir: Path | None = None) -> dict[str, Any]:
    """游戏目录（含 `plugin\\`）里有没有 OptiScaler —— 给自检与诊断包用。

    返回 ``{"present": bool, "files": [相对路径…], "ini": bool}``。
    判定三路任一命中：① 同名配置/日志文件（`OptiScaler.ini` / `OptiScaler.log`）；
    ② 名单里的 proxy dll 内容带 OptiScaler 特征；③ proxy dll 与 System32 原版**不同**
    且旁边就有 OptiScaler 的 ini/log（避免把游戏自带的同名模块误判进来）。
    """
    result: dict[str, Any] = {"present": False, "files": [], "ini": False}
    if game_dir is None:
        return result
    game_dir = Path(game_dir)
    for name in INJECTOR_DATA_NAMES:
        if (game_dir / name).is_file():
            result["ini"] = result["ini"] or name.endswith(".ini")
            result["files"].append(name)
    roots = [game_dir]
    if plugin_dir is None:
        plugin_dir = game_dir / PLUGIN_DIR_NAME
    if Path(plugin_dir).is_dir():
        roots.append(Path(plugin_dir))
    for root in roots:
        for name in LOADER_PROXY_MODULES:
            path = root / name
            if not path.is_file():
                continue
            if looks_like_optiscaler(path) or (
                result["ini"] and system_module_differs(name, path)
            ):
                relative = f"{root.name}\\{name}" if root != game_dir else name
                if relative not in result["files"]:
                    result["files"].append(relative)
    result["present"] = bool(result["files"])
    return result


# 「游戏自带 DLSS」的判据（2026-10-01）：`sl.interposer.dll`（NVIDIA Streamline 的调度层，
# 只有自带 DLSS/帧生成的游戏才会带）或 `nvngx_dlss.dll`（NGX 的 DLSS 运行库，游戏原版就有）。
NATIVE_DLSS_FILES = ("sl.interposer.dll", "nvngx_dlss.dll")


def native_dlss_present(game_dir: Path | None) -> dict[str, Any]:
    """游戏是否**自带 DLSS**？

    返回 ``{"present": bool, "files": [命中的文件名…]}``。
    为什么要问这个：`dlss5-feed`（喂帧组件）自己的日志写着 —
    「this game runs NVIDIA Streamline (sl.interposer.dll): it has DLSS of its own …
      This project is for games WITHOUT DLSS — use the game's own DLSS with OptiScaler,
      and remove dlss5-feed.addon64」。也就是说**自带 DLSS 的游戏上它多余**，留着会与游戏
    自己的 DLSS（以及第三方 NGX 注入器）抢同一条 NGX 链路。用户 2026-10-01 要求
    「游戏自带 DLSS 时自动停用喂帧组件」（默认开启、设置页可关）。
    """
    result: dict[str, Any] = {"present": False, "files": []}
    if game_dir is None:
        return result
    game_dir = Path(game_dir)
    for name in NATIVE_DLSS_FILES:
        try:
            if (game_dir / name).is_file():
                result["files"].append(name)
        except OSError:
            continue
    result["present"] = bool(result["files"])
    return result


def system_module_differs(name: str, path: Path) -> bool:
    """游戏目录里这个模块与 `System32` 的原版**是不是不同的东西**（被第三方换过）。

    只比大小（够用且便宜）：OptiScaler 这类工具正是把 `winhttp.dll` 放在游戏目录
    顶替系统模块 —— 大小必然不同。系统里没有这个名字时返回 False（不据此判定，
    免得误伤游戏自带的同名文件）。
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    original = Path(root) / "System32" / name
    try:
        if not original.is_file():
            return False
        return original.stat().st_size != path.stat().st_size
    except OSError:
        return False


def is_third_party_proxy(path: Path) -> str:
    """这个 DLL 是不是"第三方塞进游戏目录的 proxy"？返回血统（``""`` = 不是）。

    三条判据任一命中：
      ① 内容带我们生态的 loader 标记 → ``"sbm"`` / ``"poser"``；
      ② 内容带 **OptiScaler** 特征 → ``"optiscaler"``；
      ③ 名字是系统模块但**与 System32 原版不同** → ``"third-party"``
         （OptiScaler 用 `winhttp.dll` 顶替系统模块就是这一类；用户 2026-10-01 明确
         要求「一键还原游戏本体要**全部移走**」）。
    """
    origin = loader_kind(path)
    if origin:
        return origin
    if looks_like_optiscaler(path):
        return "optiscaler"
    if system_module_differs(path.name, path):
        return "third-party"
    return ""


def _resolve_game_dir(config: AppConfig, game_dir: Path | None = None) -> Path | None:
    if game_dir is not None:
        return Path(game_dir)
    return detect_game_dir(config)


def audit_game_dir_injections(config: AppConfig, game_dir: Path | None = None) -> dict[str, Any]:
    """Report foreign injection artifacts that live in the game directory."""
    target = _resolve_game_dir(config, game_dir)
    if target is None:
        return {"ok": False, "message": "没有找到游戏目录", "suspicious": [], "disabled": []}

    suspicious: list[dict[str, Any]] = []
    disabled: list[dict[str, Any]] = []
    for name in LOADER_PROXY_MODULES:
        path = target / name
        if path.is_file() and looks_like_loader_proxy(path):
            backup = path.with_name(name + ".bak")
            suspicious.append({
                "kind": "loader_proxy",
                "name": name,
                "path": str(path),
                "size": path.stat().st_size,
                "backup": str(backup) if backup.is_file() else None,
                "detail": "第三方加载器 DLL：转发系统导出并注入 plugin/*.dll",
            })
        parked = path.with_name(name + LOADER_PROXY_DISABLED_SUFFIX)
        if parked.is_file():
            backup = path.with_name(name + ".bak")
            disabled.append({
                "kind": "loader_proxy",
                "name": name,
                "disabled": str(parked),
                "original_present": path.is_file(),
                "backup": str(backup) if backup.is_file() else None,
            })

    plugin_dir = target / PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        for payload in sorted(plugin_dir.glob("*.dll")):
            suspicious.append({
                "kind": "plugin_payload",
                "name": payload.name,
                "path": str(payload),
                "size": payload.stat().st_size,
                "backup": None,
                "detail": "会被加载器代理注入游戏进程的插件 DLL",
            })
        for parked in sorted(plugin_dir.glob("*" + PLUGIN_DISABLED_SUFFIX)):
            original = plugin_dir / parked.name[: -len(PLUGIN_DISABLED_SUFFIX)]
            disabled.append({
                "kind": "plugin_payload",
                "name": original.name,
                "disabled": str(parked),
                "original_present": original.is_file(),
                "backup": None,
            })

    return {
        "ok": not suspicious,
        "game_dir": str(target),
        "suspicious": suspicious,
        "disabled": disabled,
    }



def disable_game_dir_injections(config: AppConfig, game_dir: Path | None = None) -> dict[str, Any]:
    """Park loader proxies (and their ``plugin`` payloads) next to the game.

    The genuine module is restored from ``<name>.bak`` when such a backup
    exists, so the game directory returns to a state the official launcher can
    verify.  Everything is recorded in ``runtime/game_dir_injections.json`` so
    :func:`restore_game_dir_injections` can undo it.
    """
    target = _resolve_game_dir(config, game_dir)
    if target is None:
        return {"ok": False, "message": "没有找到游戏目录", "disabled": [], "restored": [], "plugins": [], "warnings": []}

    from . import fsutil      # 给"取唯一备份名"用（见下面两处 rename 的注释）

    disabled: list[str] = []
    restored: list[str] = []
    plugins: list[str] = []
    warnings: list[str] = []
    entries: list[dict[str, Any]] = []

    for name in LOADER_PROXY_MODULES:
        path = target / name
        if not path.is_file() or not looks_like_loader_proxy(path):
            continue
        # ⚠️ **不许"先 unlink 旧的 `.disabled` 再 rename"**（2026-10-04 修）：
        # 那个 `.disabled` 里很可能就是**游戏自带的原始 dll**，删掉就永久无主了。
        # 用 `fsutil.unique_sibling` 取不冲突的名字（备份只增不删）。
        parked = fsutil.unique_sibling(path.with_name(name + LOADER_PROXY_DISABLED_SUFFIX))
        try:
            path.rename(parked)
            disabled.append(str(parked))
        except OSError as exc:
            warnings.append(f"{name}: 无法重命名代理 DLL: {exc}")
            continue
        restored_from: str | None = None
        backup = path.with_name(name + ".bak")
        if backup.is_file():
            try:
                shutil.copy2(backup, path)
                restored.append(str(path))
                restored_from = str(backup)
            except OSError as exc:
                warnings.append(f"{name}: 恢复原文件失败: {exc}")
        entries.append({
            "name": name,
            "disabled": str(parked),
            "restored_from": restored_from,
        })

    plugin_dir = target / PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        for payload in sorted(plugin_dir.glob("*.dll")):
            # 同上：不删旧副本，取唯一名（原来 `parked.unlink()` 会把上一份原件删掉）
            parked = fsutil.unique_sibling(payload.with_name(payload.name + PLUGIN_DISABLED_SUFFIX))
            try:
                payload.rename(parked)
                plugins.append(str(parked))
            except OSError as exc:
                warnings.append(f"{payload.name}: 无法重命名插件 DLL: {exc}")

    if entries or plugins:
        data = {
            "game_dir": str(target),
            "entries": entries,
            "plugins": plugins,
        }
        manifest_path = game_injection_manifest_path(config)
        try:
            # ⚠️ 原子写（2026-10-04）：这份清单是"被停用的注入文件怎么还回去"的唯一依据，
            # 写到一半被杀就成了半截 JSON ⇒ 还原时会当"清单损坏"直接失败。
            from . import fsutil

            fsutil.write_json(manifest_path, data)
        except OSError as exc:
            warnings.append(f"写入清单失败: {exc}")

    return {
        "ok": not warnings,
        "game_dir": str(target),
        "disabled": disabled,
        "restored": restored,
        "plugins": plugins,
        "warnings": warnings,
    }


def _strip_disable_suffix(name: str, suffix: str) -> str:
    """从"被停用的文件名"里还原出原始文件名。

    `foo.dll.endfieldmodcontroller.disabled` → `foo.dll`；
    也容忍"唯一名"后缀（`…disabled-1`，见 `fsutil.unique_sibling` 的使用处）。
    """
    index = name.find(suffix)
    if index == -1:
        return name
    return name[:index]


def restore_game_dir_injections(config: AppConfig) -> dict[str, Any]:
    """Undo :func:`disable_game_dir_injections` using its manifest.

    ⚠️⚠️ **清单里的路径必须先过"在游戏目录内"这一关**（2026-10-04 修的 P1）：
    `parked` / `target` 全部直接来自 manifest 字符串，原来**没有任何校验** ——
    清单被改坏、或从别处拷来的清单，就能让这里 `unlink()`/`rename()` **任意路径的文件**。
    对照 `game_clean.restore()` 早就有 `is_relative_to(game_dir)` 的判断，这里漏了。
    另外原来 1471-1475 那段"大小相同才删"的保护被紧随其后的 `if target.exists(): unlink()`
    **完全抹掉**（死逻辑），现在改成：**大小一致才认为"这是我们自己放的那份"并删掉，
    否则保留**（那是用户/游戏自己写的新文件，删了就是数据丢失）。
    """
    manifest_path = game_injection_manifest_path(config)
    if not manifest_path.is_file():
        return {"ok": False, "message": "没有找到注入清理记录", "restored": [], "warnings": []}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": f"读取清单失败: {exc}", "restored": [], "warnings": []}

    game_dir_raw = str(data.get("game_dir") or "")
    game_dir = Path(game_dir_raw) if game_dir_raw else None

    def _inside(path: Path) -> bool:
        """这个路径落在记录的游戏目录里吗（没有记录游戏目录时不放行）。"""
        if game_dir is None:
            return False
        try:
            return path.resolve().is_relative_to(game_dir.resolve())
        except (OSError, ValueError):
            return False

    restored: list[str] = []
    warnings: list[str] = []
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        parked = Path(str(entry.get("disabled") or ""))
        if not parked.is_file():
            continue
        # ⚠️ 名字推导要**容忍唯一名后缀**（2026-10-04）：`disable_*` 现在用
        # `fsutil.unique_sibling` 取名，冲突时会变成 `x.dll.endfieldmodcontroller.disabled-1`
        # —— 直接按固定后缀切片会得到 `x.dll.endfieldmodcontroller.disabled-1`（切错）。
        name = _strip_disable_suffix(parked.name, LOADER_PROXY_DISABLED_SUFFIX)
        target = parked.with_name(name)
        if not (_inside(parked) and _inside(target)):
            warnings.append(f"{name}: 清单里的路径不在游戏目录内，已跳过（{parked}）")
            continue
        restored_from = entry.get("restored_from")
        try:
            if target.is_file() and restored_from:
                backup = Path(str(restored_from))
                # 大小一致 ⇒ 这份就是我们（或系统补回的模块）放下的，可以覆盖；
                # 不一致 ⇒ 游戏/用户后来自己写了新内容，**保留它**并如实说明。
                if backup.is_file() and target.stat().st_size == backup.stat().st_size:
                    target.unlink()
                else:
                    warnings.append(f"{name}: 游戏目录里已有一份同名文件，内容与记录不同，未覆盖")
                    continue
            parked.rename(target)
            restored.append(str(target))
        except OSError as exc:
            warnings.append(f"{name}: {exc}")
    for item in data.get("plugins", []):
        parked = Path(str(item))
        if not parked.is_file():
            continue
        target = parked.with_name(_strip_disable_suffix(parked.name, PLUGIN_DISABLED_SUFFIX))
        if not (_inside(parked) and _inside(target)):
            warnings.append(f"{target.name}: 清单里的路径不在游戏目录内，已跳过")
            continue
        try:
            if target.exists():
                target.unlink()
            parked.rename(target)
            restored.append(str(target))
        except OSError as exc:
            warnings.append(f"{target.name}: {exc}")

    if not warnings:
        try:
            manifest_path.unlink()
        except OSError:
            pass
    return {"ok": not warnings, "restored": restored, "warnings": warnings}
