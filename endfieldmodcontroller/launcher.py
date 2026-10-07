"""Launch orchestration and ReShade runtime preparation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import activation
from . import core
from . import dependencies
from . import diagnostics
from . import integrity
from . import runtime_deps
from .config import AppConfig
from . import injector
from . import reshade_integration


class LaunchError(RuntimeError):
    pass


def _copy_if_changed(src: Path, dst: Path) -> bool:
    """Copy a runtime file only when content differs.

    This avoids unnecessary writes/locks when the destination is already the
    current version, which is the common case on repeated launches.
    """
    if not src.is_file():
        return False
    if dst.is_file():
        try:
            if src.stat().st_size == dst.stat().st_size:
                src_digest = hashlib.sha256(src.read_bytes()).hexdigest()
                dst_digest = hashlib.sha256(dst.read_bytes()).hexdigest()
                if src_digest == dst_digest:
                    return False
        except OSError:
            pass
    shutil.copy2(src, dst)
    return True


def _built_addon_path() -> Path | None:
    return reshade_integration.built_addon_path()


def _multi_loader_path() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dist" / "migoto_loader.exe",
        root / "scripts" / "migoto_multi_loader.exe",
        root / "runtime" / "migoto" / "loader_new.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _legacy_migoto_source() -> Path | None:
    """Locate the known-working Endfield 3DMigoto v1.4.x package.

    The first working installation used a standalone 3DMigoto package whose
    d3dx.ini contains the original ``$costume_mods`` / ShaderOverrideCharacter
    logic.  EFMI v1.3.x from a newer XXMI package parses the mods but does not
    apply the same costume override path, so prefer the legacy framework when
    it is present.
    """
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "runtime" / "builtin" / "XXMI" / "EFMI",
        root / "runtime" / "migoto",
    ]
    for candidate in candidates:
        if not (candidate / "d3d11.dll").is_file() or not (candidate / "d3dx.ini").is_file():
            continue
        try:
            text = (candidate / "d3dx.ini").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "$costume_mods" in text and "[ShaderOverrideCharacter]" in text:
            return candidate
    return None


def _has_legacy_migoto_config(d3dx_ini: Path) -> bool:
    try:
        text = d3dx_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "$costume_mods" in text and "[ShaderOverrideCharacter]" in text


def _is_legacy_framework_config(d3dx_ini: Path) -> bool:
    try:
        text = d3dx_ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    lower = text.lower()
    return (
        "$costume_mods" in text
        and "[shaderoverridecharacter]" in lower
        and not ("core" in lower and "efmi" in lower and "main.ini" in lower)
    )


def _has_efmi_core_config(d3dx_ini: Path) -> bool:
    try:
        text = d3dx_ini.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return ("core" in text and "efmi" in text and "main.ini" in text) or ("core/efmi/main.ini" in text)


def _bootstrap_path() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dist" / "mc_bootstrap.dll",
        root / "scripts" / "mc_bootstrap.dll",
        root / "runtime" / "builtin" / "XXMI" / "EFMI" / "mc_bootstrap.dll",
        root / "runtime" / "migoto" / "mc_bootstrap.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _running_process_names(names: list[str]) -> list[str]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
        )
    except Exception:
        return []
    running: list[str] = []
    lower_names = {name.lower(): name for name in names}
    for line in result.stdout.splitlines():
        stripped = line.strip().strip('"').lower()
        for low, original in lower_names.items():
            if stripped.startswith(low):
                running.append(original)
                break
    return running


def _stop_locked_files_processes(config: AppConfig, *, include_game: bool = False) -> list[str]:
    """Kill stale loader/game processes before touching runtime files.

    Windows keeps loaded DLLs/EXEs locked, so replacing runtime/migoto files or
    deleting the old Mods staging while a previous loader/game is still running
    raises WinError 32.  Try non-elevated taskkill first; if the processes are
    elevated, request a single elevated cleanup and wait for it to finish.
    """
    names = [
        "migoto_loader2.exe",
        "migoto_loader.exe",
        "loader.exe",
        "loader_new.exe",
        "3dmloader.exe",
        "3DMigoto Loader.exe",
        "3DMigotoLoader.exe",
    ]
    # 2026-10-01 修（④）：`Endfield.exe` 默认**不再**放进这张清理表 ——
    # 原先"打开官方 XXMI"和"3DMigoto 启动"两条路径都会无条件 `taskkill /F`
    # 掉正在运行的终末地（无确认、无提示，未保存的进度可能丢）。
    # 只有显式要求"腾出被占用的文件"时才把游戏一起收掉。
    if include_game:
        names.append("Endfield.exe")
    running = _running_process_names(names)
    if not running:
        return []
    _append_log(config, f"检测到残留进程，先结束: {', '.join(running)}")
    # Best effort without UAC.
    for name in running:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        except Exception:
            pass
    time.sleep(0.5)
    running = _running_process_names(names)
    if not running:
        return []

    runtime = config.runtime_path
    runtime.mkdir(parents=True, exist_ok=True)
    script = runtime / "stop_migoto_processes.cmd"
    marker = runtime / "stop_migoto_processes.done"
    try:
        if marker.exists():
            marker.unlink()
    except OSError:
        pass
    lines = [
        "@echo off",
        "taskkill /F /IM migoto_loader2.exe >nul 2>&1",
        "taskkill /F /IM migoto_loader.exe >nul 2>&1",
        "taskkill /F /IM loader.exe >nul 2>&1",
        "taskkill /F /IM loader_new.exe >nul 2>&1",
    ]
    if include_game:
        lines.append("taskkill /F /IM Endfield.exe >nul 2>&1")
    lines.append(f'> "{marker}" echo done')
    script.write_text(chr(10).join(lines) + chr(10), encoding="utf-8", newline=chr(10))
    _spawn_elevated(config, str(script), str(script.parent), show_window=0)

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if marker.is_file():
            break
        if not _running_process_names(names):
            break
        time.sleep(0.5)
    running = _running_process_names(names)
    try:
        if marker.exists():
            marker.unlink()
    except OSError:
        pass
    if running:
        raise LaunchError(
            "旧游戏或 loader 进程仍占用 runtime 文件（WinError 32）。"
            "请手动关闭 Endfield.exe / migoto_loader2.exe 后重试。"
        )
    return running


def _merge_disabled_addons(game_dir: Path) -> str:
    """把 `renodx-dlss.addon64` **并入**游戏目录 `ReShade.ini` 的 `[ADDON] DisabledAddons`。

    ⚠️⚠️ 三处修正（2026-10-04，都属于**备份语义 / 别毁用户原有配置**）：
      ① **写入必须走 `_write_ini_atomic`**（它就在本文件里，会先留一份 `ReShade.ini.mc.bak`、
         且是原子写）—— 原来直接 `write_text`，**没有备份、写到一半被杀就是半截 ini**；
      ② **`DisabledAddons` 要合并而不是覆盖**：用户/其它整合包可能已经禁用了别的 addon，
         原来整行替换成只留 `renodx-dlss.addon64`，**把用户原有的项静默删掉**；
      ③ `LoadFromDllMain` 行仍然移除（这是原设计的意图，保持）。
    """
    disabled_value = "renodx-dlss.addon64"
    ini_path = game_dir / "ReShade.ini"
    if not ini_path.is_file():
        _write_ini_atomic(ini_path, "[ADDON]" + chr(10) + "DisabledAddons=" + disabled_value + chr(10))
        return disabled_value
    lines = ini_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: list[str] = []
    in_addon = False
    inserted = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_addon and not inserted:
                out.append("DisabledAddons=" + disabled_value)
                inserted = True
            in_addon = stripped.lower() == "[addon]"
            out.append(line)
            continue
        if in_addon and stripped.lower().startswith("loadfromdllmain"):
            continue
        if in_addon and stripped.lower().startswith("disabledaddons"):
            # **保留用户已有的其它项**，只把我们要禁用的这个补进去（去重）
            existing = [item.strip() for item in line.split("=", 1)[1].split(",") if item.strip()]
            if disabled_value not in existing:
                existing.append(disabled_value)
            out.append("DisabledAddons=" + ",".join(existing))
            inserted = True
            continue
        out.append(line)
    if in_addon and not inserted:
        out.append("DisabledAddons=" + disabled_value)
    _write_ini_atomic(ini_path, chr(10).join(out) + chr(10))
    return disabled_value


def _ensure_reshade_disabled_addons(game_dir: Path) -> None:
    """Disable only RenoDX/DLSS add-on while keeping Endfield Enhancer enabled.

    EndfieldModController and the user's ``终末地EE.addon64`` are expected to coexist.
    RenoDX/DLSS is the known conflicting add-on in the current mixed setup, so
    only that one is listed in DisabledAddons.  Files are never deleted.
    """
    _merge_disabled_addons(game_dir)


def resolve_hotkey_takeover(
    config: AppConfig,
    controller_dir: Path,
    *,
    log: Callable[[str], None] | None = None,
) -> bool:
    """「整合 Mod 快捷键」到底能不能接管？能就先把面板铺好，再返回 True。

    用户 2026-10-01 的需求是「开了要**锁 mod 快捷键**，**注入 reshade**」——这两件事
    原本必须绑在一起做：先把面板放进 ReShade 真正会读的目录（见
    `reshade_integration.panel_base_dirs` 的说明），确认这条路可用之后，**才**允许把
    Mod 自己的热键改写成 `VK_F24`。反过来（钥匙收了、门没有）就是 2026-10-01 那次
    事故：用户的按键全失效、面板却不存在。

    **2026-10-02 变更**：面板改成**直接发 Mod 自己的原键**（用户：「让面板走 mod 的按键」
    「不要用开关或滑块，都是一个键，做切换的按键就行」），而锁键恰恰会让这条链路失效
    （见 `activation.HOTKEY_LOCK_ENABLED` 的说明）。所以：**面板照铺，锁键动作停用**，
    本函数在锁键被停用时返回 False（返回值就是
    `stage_and_prepare(hotkey_takeover=...)` 该用的值）。配置项语义相应变成
    「游戏内 Mod 面板：要不要注入这个面板」，默认仍为开（零配置即用）。
    """
    enabled = bool(getattr(config, "hotkey_takeover", False))
    if not enabled:
        return False

    def note(message: str) -> None:
        _append_log(config, message)
        if log is not None:
            log(message)

    possible, reason = reshade_integration.takeover_possible(config)
    result = reshade_integration.deploy_panel(config, Path(controller_dir), log=note)
    for warning in result.get("warnings", []):
        note(f"WARN 统一面板: {warning}")
    # 面板里的中文要靠 ReShade 加载一个中文字体（默认字体只有 ASCII）
    font = reshade_integration.ensure_panel_font(config, log=note)
    if font.get("reason") and not font.get("changed"):
        note(f"面板字体: {font['reason']}")
    if not possible:
        note(f"整合 Mod 快捷键已打开，但面板用不了（{reason}）→ **本次不改写 Mod 热键**，原按键继续可用")
        return False
    if not result.get("deployed"):
        note("整合 Mod 快捷键已打开，但面板文件一个都没写成功 → **本次不改写 Mod 热键**")
        return False
    if not core.HOTKEY_LOCK_ENABLED:
        note(
            "游戏内 Mod 面板已就位: "
            + "、".join(result.get("deployed", [])[:2])
            + "；**不改写 Mod 热键** —— 面板直接发 Mod 自己的按键（游戏内按 Home 打开）"
        )
        return False
    note(
        "整合 Mod 快捷键已接管: 面板已就位 "
        + "、".join(result.get("deployed", [])[:2])
        + "；Mod 自带按键将被锁住（游戏内按 Home 打开 ReShade 面板操作）"
    )
    return True


def _sync_enhancer_section(source: Path, target: Path,
                           keys: tuple[str, ...] = (
                               "CameraEFMICompatibility",
                               # ⚠️ **`CameraFirstPerson` 故意不在这里**（2026-10-05 用户明确要求：
                               #    「**你不要复写我的第一人称开启状态配置**」）。
                               #    它确实是"相机 hook 能不能装上"的关键（值为 `0` 时 enhancer
                               #    不会去装 hook ⇒ 永远等不到 `Camera controls installed.`），
                               #    但**开不开第一人称是用户自己的偏好**，不该由一键启动替他决定。
                               #    想默认开的人自己按一次 F1 即可；我们只保证**不去动它**。
                               "CameraFirstPersonDialogue",
                               "CameraFirstPersonMovement",
                               "CameraMeshHeadHiding",
                               "CameraSmoothPerspectiveTransition",
                               "ShortcutFirstPerson",
                               "Language",
                           ),
                           preserve_user_values: tuple[str, ...] = ("ShortcutFirstPerson",)) -> int:
    """把源 ini 里 `[endfield-enhancer]` 段的关键项同步进目标 ini，返回改了几项。

    为什么需要它：`core.py` 给游戏进程设了 `RESHADE_BASE_PATH_OVERRIDE` = `runtime\\reshade`，
    **ReShade 读的是那一份** `ReShade.ini`；而初始化只维护 `dlss5\\ReShade.ini`。
    两份内容会分叉 —— addon 首次运行会把**出厂值（全 0）**写进它读的那份，于是
    「与 EFMI 共存必需的 `CameraEFMICompatibility`」「F1 快捷键 `ShortcutFirstPerson`」
    「界面语言 `Language`」在生效的那份里都是默认值，用户看到的就是
    「第一人称又是英文 / 面板里点按钮没反应」（2026-10-03、2026-10-04 两次反馈）。

    `Language` 是**故意**纳入同步的（2026-10-03 改变主意）：addon 每次游戏启动都会把它读的
    那份写成出厂值，逐字保留"用户偏好"的结果就是「一键启动同步成中文 → 游戏一跑又变英文」，
    而用户明确要中文 ⇒ 每次一键启动都写回中文。

    ⚠️ **2026-10-04 关键修复（用户报「第一人称的中文没了」）**：原实现只在目标 ini
    **已经有这个段**、且那个键**已经存在**时才改写它 —— 而生效那份在初始化重建
    ReShade.ini 之后**可能整段都没有**（内置模板里只有 GENERAL/INPUT/OVERLAY/STYLE/SCREENSHOT），
    于是同步**一个键都补不上、连备份都不留**（实测：那份 ini 旁边从来没有
    `.bak-before-enhancer-sync`，而它里面是 addon 写的 `Language=0` ⇒ 游戏里永远是英文）。
    现在：段不存在就**补段**、键不存在就**补键**，写进去的才是"生效的那份"。
    """
    # ⚠️ 同 prepare_reshade_runtime 的硬闸：超过 1 MB 的 ini 一律当损坏，别去读它
    # （3 GB 的版本一读就把内存吃爆 —— 2026-10-03 事故）
    try:
        if target.is_file() and target.stat().st_size > 1_048_576:
            return 0
    except OSError:
        return 0
    if not source.is_file() or not target.is_file():
        return 0
    good: dict[str, str] = {}
    inside = False
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if text.startswith("["):
            inside = text == "[endfield-enhancer]"
            continue
        if inside and "=" in text:
            key, _, value = text.partition("=")
            good[key.strip()] = value.strip()
    wanted = {key: good[key] for key in keys if key in good}
    if not wanted:
        return 0

    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    inside = False
    section_seen = False
    present: set[str] = set()
    insert_at: int | None = None          # 段内最后一行之后的位置（用来补缺失的键）
    changed = 0
    for line in lines:
        text = line.strip()
        if text.startswith("["):
            if inside and insert_at is None:
                insert_at = len(out)
            inside = text == "[endfield-enhancer]"
            if inside:
                section_seen = True
            out.append(line)
            continue
        if inside and "=" in text:
            key = text.partition("=")[0].strip()
            present.add(key)
            if key in wanted:
                current = text.partition("=")[2].strip()
                # ⚠️⚠️ **用户自己绑的快捷键不许被我们改回去**（2026-10-05：反馈者报
                # 「管理器会覆写它的快捷键」）。`ShortcutFirstPerson` 是**偏好**（他要绑 F2
                # 就绑 F2），而我们每次一键启动都把它写回 112(F1) ⇒ 他改完又被改回来。
                # 判据：目标里**已有非 0 值 ⇒ 原样保留**；只有"缺失或 0"才算没设过、补默认
                # （`0` 在 enhancer 里是"没有绑定快捷键"，不是用户的选择）。
                # 不在此列的是**功能必需项**（`CameraEFMICompatibility` 那几项：为 0 时
                # 第一人称会被 EFMI 顶掉）与用户明确要的中文 `Language` —— 它们照旧覆盖。
                if key in preserve_user_values and current not in ("", "0"):
                    out.append(line)
                    continue
                if wanted[key] != current:
                    out.append(f"{key}={wanted[key]}")
                    changed += 1
                    continue
        out.append(line)
    if inside and insert_at is None:
        insert_at = len(out)

    missing = [key for key in wanted if key not in present]
    if not section_seen:
        # 整段都不在（初始化重建 ini 后的常态）⇒ 补段，否则这些键在生效那份里根本不存在
        out.extend(["", "[endfield-enhancer]"] + [f"{key}={wanted[key]}" for key in wanted])
        changed += len(wanted)
    elif missing:
        position = insert_at if insert_at is not None else len(out)
        out[position:position] = [f"{key}={wanted[key]}" for key in missing]
        changed += len(missing)

    if changed:
        backup = target.with_name(target.name + ".bak-before-enhancer-sync")
        if not backup.exists():
            try:
                shutil.copy2(target, backup)
            except OSError:
                pass
        target.write_text("\r\n".join(ln.replace("\r", "") for ln in out) + "\r\n",
                          encoding="utf-8", newline="")
    return changed


def _sync_style_section(source: Path, target: Path,
                        keys: tuple[str, ...] = ("Font", "FontSize", "EditorFont", "EditorFontSize")) -> int:
    """把源 ini 里 `[STYLE]` 段的字体相关项同步进目标 ini（**缺段补段、缺键补键**），返回改了几项。

    为什么需要：见调用处注释 —— 生效那份 `[STYLE] Font=` 为空时，第一人称的中文
    会因缺少中文字体而显示不出来（addon 自己会在日志里报 "Chinese font missing"）。
    用户 2026-10-04 报的「中文没了」正是这两层叠在一起：语言被 addon 写回默认（英文），
    字体键在生效那份里也是空的（中文就算选了也画成方块）。

    ⚠️ 与 `_sync_enhancer_section` 同一处修复：原来只改**已存在且为空**的键 ⇒
    生效那份根本没有这两个键时一个都补不上。现在缺键就补。
    仍然只动字体相关键，不碰用户自己调过的配色/圆角那些，也**不覆盖用户已设的非空字体**。
    """
    # ⚠️ 同 prepare_reshade_runtime 的硬闸：超过 1 MB 的 ini 一律当损坏，别去读它
    # （3 GB 的版本一读就把内存吃爆 —— 2026-10-03 事故）
    try:
        if target.is_file() and target.stat().st_size > 1_048_576:
            return 0
    except OSError:
        return 0
    if not source.is_file() or not target.is_file():
        return 0
    good: dict[str, str] = {}
    inside = False
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if text.startswith("["):
            inside = text == "[STYLE]"
            continue
        if inside and "=" in text:
            key, _, value = text.partition("=")
            good[key.strip()] = value.strip()
    wanted = {key: good[key] for key in keys if good.get(key)}
    if not wanted:
        return 0

    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    inside = False
    section_seen = False
    present: set[str] = set()
    insert_at: int | None = None
    changed = 0
    for line in lines:
        text = line.strip()
        if text.startswith("["):
            if inside and insert_at is None:
                insert_at = len(out)
            inside = text == "[STYLE]"
            if inside:
                section_seen = True
            out.append(line)
            continue
        if inside and "=" in text:
            key = text.partition("=")[0].strip()
            present.add(key)
            value = text.partition("=")[2].strip()
            # ⚠️ 只在**目标为空**时才补（不要覆盖用户在 ReShade 里自己挑过的字体）
            if key in wanted and not value:
                out.append(f"{key}={wanted[key]}")
                changed += 1
                continue
        out.append(line)
    if inside and insert_at is None:
        insert_at = len(out)

    # 目标里**压根没有**这些键时也要补（但要避免覆盖用户已设的非空值 —— 上面那一步已经处理过）
    missing = [key for key in wanted if key not in present]
    if missing:
        if not section_seen:
            out.extend(["", "[STYLE]"] + [f"{key}={wanted[key]}" for key in missing])
        else:
            position = insert_at if insert_at is not None else len(out)
            out[position:position] = [f"{key}={wanted[key]}" for key in missing]
        changed += len(missing)

    if changed:
        backup = target.with_name(target.name + ".bak-before-style-sync")
        if not backup.exists():
            try:
                shutil.copy2(target, backup)
            except OSError:
                pass
        target.write_text("\r\n".join(ln.replace("\r", "") for ln in out) + "\r\n",
                          encoding="utf-8", newline="")
    return changed


def sync_effective_reshade_ini(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把**游戏真正读的那份** `ReShade.ini` 对齐成我们配好的样子。

    哪份是"真正读的那份"：`core.py` / `launcher` 给游戏进程设
    `RESHADE_BASE_PATH_OVERRIDE` = `runtime\\reshade` ⇒ ReShade 以它为基准目录
    （`ReShade.log` 也写在那里，2026-10-04 在反馈者的诊断包里确认过）。
    而初始化（`initialize.ensure_all`）、面板字体（`ensure_panel_font`）都只维护
    `dlss5\\ReShade.ini` —— 两份必须显式对齐。

    ⚠️ **必须在初始化之后调用**（2026-10-04 的根因就在顺序上）：
    `prepare_reshade_runtime()` 跑在 `ensure_injections()`（内部会重建 `dlss5\\ReShade.ini`）
    **之前**，那时源 ini 可能还不存在 ⇒ 同步静默空转 ⇒ 生效那份保持 addon 写的
    `Language=0`（英文），用户看到的就是「第一人称的中文没了」。
    所以这个函数是**幂等**的，并且在启动流程里**调用两次**（prepare 之后一次保证目标存在，
    初始化之后再调一次保证内容正确）。
    """
    source = config.dlss5_ini_path
    target = config.reshade_runtime_path / "ReShade.ini"
    result: dict[str, Any] = {"ok": False, "source": str(source), "target": str(target),
                              "created": False, "enhancer": 0, "style": 0, "font": ""}
    if not source.is_file():
        result["reason"] = f"源 ini 还不存在（{source}）—— 初始化生成后会自动再同步一次"
        if log is not None:
            log(f"第一人称设置: {result['reason']}")
        return result
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            # 生效那份不存在（首次运行 / 被清掉）：直接复制我们配好的那份过去。
            # 否则 ReShade 会自建一份**出厂值**的 ini —— 中文、字体、快捷键全丢。
            shutil.copy2(source, target)
            result.update({"ok": True, "created": True})
            if log is not None:
                log(f"第一人称设置: 生效那份 ReShade.ini 不存在 → 已用配好的那份创建（{target}）")
            return result
        result["enhancer"] = _sync_enhancer_section(source, target)
        result["style"] = _sync_style_section(source, target)
        from . import reshade_integration

        font = reshade_integration.ensure_panel_font(config, log=None, ini=target)
        result["font"] = str(font.get("font") or "")
        result["font_reason"] = str(font.get("reason") or "")
        result["ok"] = True
        if log is not None:
            log(f"第一人称设置: 已写入生效那份 ReShade.ini（第一人称 {result['enhancer']} 项、"
                f"字体 {result['style']} 项"
                + (f"，字体指向 {result['font']}" if result["font"] else "")
                + "）")
        return result
    except OSError as exc:
        result["reason"] = f"写入失败: {exc}"
        if log is not None:
            log(f"WARN 第一人称设置: 写入生效那份 ReShade.ini 失败: {exc}")
        return result


def prepare_reshade_runtime(config: AppConfig, controller_dir: Path) -> dict[str, Any]:
    """Prepare the ReShade base directory without writing anything into the game dir.

    ⚠ 2026-10-01 修正：面板必须写到 **ReShade 自己的 base 目录**（`d3d12.dll` 所在处
    = `dlss5`；ReShade 日志写死了 `Searching for add-ons ... in '<base>'`）。旧实现
    写到 `runtime\\reshade\\Addons\\`，那份文件永远不会被加载 —— 见
    `reshade_integration` 模块头的说明。
    """
    reshade_dir = config.reshade_runtime_path
    reshade_dir.mkdir(parents=True, exist_ok=True)
    (reshade_dir / "reshade-shaders" / "Shaders").mkdir(parents=True, exist_ok=True)
    (reshade_dir / "reshade-shaders" / "Textures").mkdir(parents=True, exist_ok=True)

    # 面板的实际落点（base = dlss5，能定位到游戏目录时再补一份）
    result = reshade_integration.deploy_panel(config, Path(controller_dir))
    base = config.dlss5_path
    installed_addon = base / reshade_integration.ADDON_NAME
    if not getattr(config, "inject_reshade_ui", True):
        # 用户明确不要面板：把它挪开（可逆），但**整合 Mod 快捷键**要面板才能用 ——
        # 那种情况下 `resolve_hotkey_takeover` 会拒绝接管，不会出现"锁了键没面板"。
        for name in (reshade_integration.ADDON_NAME,) + reshade_integration.LEGACY_ADDON_NAMES:
            target = base / name
            if target.is_file():
                disabled = target.with_name(target.name + ".disabled")
                try:
                    if disabled.exists():
                        disabled.unlink()
                    target.rename(disabled)
                except OSError:
                    pass

    actions_tsv = base / "actions.tsv"
    # ⚠️ 2026-10-03 实测修正：`core.py` 会给游戏进程设 `RESHADE_BASE_PATH_OVERRIDE`
    # = `runtime\reshade`，**ReShade 就以此为基准目录**（今天 11:36 的 ReShade.log 是
    # `Searching for add-ons ... in 'D:\zmdmod\modtest\runtime\reshade\Addons'` +
    # `Failed to iterate all files ... error code 3`）。也就是说这份 ini **确实会被读**，
    # 而它里面的 `AddonPath=Addons` 指向一个**从来没人创建**的子目录 ⇒ 所有 addon 都加载不到
    # （现象：ReShade 界面在、但 DLSS5 / 第一人称 / 面板的标签全没有）。
    #
    # 所以两件事一起做：
    #   ① `AddonPath` 写成**指向真正放 addon 的目录（dlss5）的绝对路径** —— 不论基准目录是谁都找得到；
    #   ② 同时在基准目录下**建好 `Addons\` 并放一份 addon** 兜底（万一它优先看相对路径）。
    addons_dir = reshade_dir / "Addons"
    try:
        addons_dir.mkdir(parents=True, exist_ok=True)
        for name in (reshade_integration.ADDON_NAME,) + reshade_integration.LEGACY_ADDON_NAMES:
            src = base / name
            if src.is_file():
                shutil.copy2(src, addons_dir / name)
    except OSError as exc:
        _append_log(config, f"往 runtime\\reshade\\Addons 放面板失败（忽略）: {exc}")

    # `initialize._rebuild_ini` 会把这份当"[endfield-enhancer] 段的历史来源"之一，
    # 所以照旧写一份，保持既有行为。同步动作写在本函数末尾（必须在写 ini 之后）。
    #
    # ⚠️ 2026-10-03 实测第三个同源问题：**search path 原先写成相对基准目录的路径**。
    # 这份 ini 由 `RESHADE_BASE_PATH_OVERRIDE`（launcher 启动时设成 `runtime\reshade`）指成
    # 基准目录后被真正读取，而 `AddonPath=Addons` / `EffectSearchPaths=reshade-shaders\...`
    # 都**相对这个基准**解析 ⇒ 找的是 `runtime\reshade\` 下的东西，可 ReShade 本体
    # （`d3d12.dll`）、addon、shader **全都在 `dlss5\`**。ReShade 日志的原话：
    #     Failed to iterate all files in '...\runtime\reshade\Addons' with error code 3
    #     DLSS5_Feed.fx is not loaded (technique/textures missing)
    # ⇒ 一个 addon 都加载不到、feed shader 也找不到，DLSS5 一帧都出不来。
    #
    # 修法：一律用**相对路径**（用户 2026-10-03 明确要求「不要用绝对路径」——
    # 数据根可能整体搬走，写死盘符会失效）。相对谁？相对这个基准目录本身，
    # 所以用 `os.path.relpath` 动态算（`dlss5_dir` 是可配置的，不能写死 `..\dlss5`）。
    # ⚠️⚠️ **2026-10-03 回滚开关**：用户实测「开 DLSS5 或第一人称就崩、两个都关就能启动」，
    # 而这两项唯一共同点是**注入 d3d12.dll**（`want_base = dlss5 or firstperson`）。
    # 记忆里已定案"终末地只有 Vulkan/DX11、靠 D3D11on12 桥接"⇒ **不是 D3D11/D3D12 的固有冲突**，
    # 于是最大嫌疑落在我这轮改过的两处（这份 ini 的路径、extra_libraries 条数）。
    # 改动前用的是**绝对路径**（`AddonPath={base}`），我为了满足"不要绝对路径"改成了
    # `..\dlss5` —— 理论上等价，但实测就是崩，所以不再靠推理：
    # `reshade_use_absolute_paths = True` 时**完全回到改动前的写法**，用来一次判定是不是我改坏的。
    use_abs = bool(getattr(config, "reshade_use_absolute_paths", True))
    if use_abs:
        rel = str(base)                       # 改动前：绝对路径，不论基准目录是谁都找得到
    else:
        try:
            rel = os.path.relpath(base, reshade_dir)
        except ValueError:            # 跨盘符时 relpath 会抛 ValueError，退回用目录名
            rel = base.name
    shaders_rel = os.path.join(rel, "reshade-shaders", "Shaders")
    textures_rel = os.path.join(rel, "reshade-shaders", "Textures")
    wanted_keys = {
        "AddonPath": rel,
        "EffectSearchPaths": shaders_rel + "\\**",
        "TextureSearchPaths": textures_rel + "\\**",
        "PresetPath": os.path.join(rel, "ReShadePreset.ini"),
    }

    # ⚠️⚠️ 2026-10-03 **关键修正：合并写入，绝不整份覆盖**。
    # 旧实现是 `write_text(ini_text)` —— 只生成 `[ADDON]` + `[GENERAL]` 两段就盖掉整个文件，
    # 于是每次一键启动都会把 **`[STYLE]`（字体）、`[endfield-enhancer]`（第一人称的语言等）**
    # 这些段整段抹掉。实测证据：11:56 补好的 `[STYLE] Font=C:\WINDOWS\Fonts\msyh.ttc`，
    # 到 12:15 又变回空 —— 而"字体为空"正是第一人称中文显示不出来的原因
    # （addon 自己会报 `Chinese font missing`）。用户看到的「还是英文」就是这么来的。
    # 现在只更新上面这 4 个键，其它段和键一律原样保留。
    ini_path = reshade_dir / "ReShade.ini"
    existing: list[str] = []
    # ⚠️ **读之前先检查大小**（2026-10-03 事故）：这份 ini 正常情况下 **几 KB**，
    # 而实测出现过 **3 GB 全是空行**的版本 —— 一读就把内存吃到 23 GB、CPU 打满、
    # 界面未响应且关不掉（用户原话「现在mod管理器未响应，关不掉」）。
    # faulthandler 抓到的栈正是卡在 `ini_path.read_text(...)` 这一行。
    # 这里加一道硬闸：超过 1 MB 一律**当作损坏**、丢弃并重建，绝不去读它。
    # （重建内容就是下面 `if not existing:` 那套标准段，功能不受影响。）
    try:
        if ini_path.is_file() and ini_path.stat().st_size > 1_048_576:
            _append_log(
                config,
                f"WARN runtime\\reshade\\ReShade.ini 异常膨胀到 "
                f"{ini_path.stat().st_size / 1048576:.1f} MB，判定为损坏 → 丢弃重建",
            )
            try:
                ini_path.unlink()
            except OSError:
                pass
    except OSError:
        pass
    if ini_path.is_file():
        try:
            # ⚠️⚠️ **必须先把换行规范化**（2026-10-03 定案的真正根因）。
            # 症状：这份 ini 会**指数级膨胀**（6 → 11 → 20 → 40 → … 约 30 次到 3 GB），
            # 而读它时把内存吃到 23 GB、CPU 打满、界面未响应且关不掉
            #（faulthandler 抓到的栈正是卡在这一行的 read_text）。
            #
            # 机制：文件里出现过 `\r\r\n`。`splitlines()` 会把它当成**两个**行分隔 ——
            # 第一行是空的、第二行才是真内容 —— 于是凭空多出一个**空行**；
            # 那个空行被原样写回去，下次读到更多 `\r\r\n`，空行再翻倍。
            # ❗ 光对结果行做 `rstrip("\r")` **没用**：那个 `\r` 早被 splitlines 消耗掉了。
            # 正解是**在拆行之前**把 `\r\r\n`（以及裸 `\r`）规范成 `\n`。
            raw = ini_path.read_text(encoding="utf-8", errors="replace")
            raw = raw.replace("\r\n", "\n").replace("\r", "\n")
            existing = raw.splitlines()
        except OSError:
            existing = []

    if not existing:
        merged = ["[ADDON]", f"AddonPath={rel}", "", "[GENERAL]",
                  f"EffectSearchPaths={wanted_keys['EffectSearchPaths']}",
                  f"TextureSearchPaths={wanted_keys['TextureSearchPaths']}",
                  f"PresetPath={wanted_keys['PresetPath']}", ""]
    else:
        merged, section, seen = [], "", set()
        for line in existing:
            text = line.strip()
            if text.startswith("["):
                # 离开某段时，把它缺的键补上（保证 [ADDON]/[GENERAL] 一定被写好）
                if section == "[ADDON]" and "AddonPath" not in seen:
                    merged.append(f"AddonPath={rel}")
                if section == "[GENERAL]":
                    for key in ("EffectSearchPaths", "TextureSearchPaths", "PresetPath"):
                        if key not in seen:
                            merged.append(f"{key}={wanted_keys[key]}")
                section = text
                seen = set()
                merged.append(line)
                continue
            if "=" in text:
                key = text.partition("=")[0].strip()
                if key in wanted_keys:
                    merged.append(f"{key}={wanted_keys[key]}")
                    seen.add(key)
                    continue
            merged.append(line)
        # ⚠️ **文件末尾那一段也要补全**（2026-10-04 修）。
        # 上面的补键是在"遇到下一个段头"时触发的 ⇒ **最后一段**（通常是 `[GENERAL]`，
        # 后面没有别的段了）永远走不到那段代码：实测 `runtime\reshade\ReShade.ini` 里
        # `[GENERAL]` 少了 `TextureSearchPaths` / `PresetPath` —— 前者缺失意味着
        # **DLSS5 找不到纹理**，而它一直没被补上（直到文件后面出现别的段才顺带补）。
        # 现在循环结束后对"最后那一段"做同样的事，一次调用就收敛（也顺带让
        # 「反复调用 ini 不增长」这条回归重新成立 —— 以前它靠"永远补不全"侥幸通过）。
        if section == "[ADDON]" and "AddonPath" not in seen:
            merged.append(f"AddonPath={rel}")
        if section == "[GENERAL]":
            for key in ("EffectSearchPaths", "TextureSearchPaths", "PresetPath"):
                if key not in seen:
                    merged.append(f"{key}={wanted_keys[key]}")
        # 文件里压根没有这两个段时，补在末尾
        if "[ADDON]" not in [ln.strip() for ln in merged if ln.strip().startswith("[")]:
            merged += ["", "[ADDON]", f"AddonPath={rel}"]
        if "[GENERAL]" not in [ln.strip() for ln in merged if ln.strip().startswith("[")]:
            merged += ["", "[GENERAL]",
                       f"EffectSearchPaths={wanted_keys['EffectSearchPaths']}",
                       f"TextureSearchPaths={wanted_keys['TextureSearchPaths']}",
                       f"PresetPath={wanted_keys['PresetPath']}"]

    try:
        # ⚠️⚠️ **必须显式给 newline=""**（2026-10-03 定案的真正根因，就这一步）。
        # `write_text` 默认 `newline=None` ⇒ 文本模式会把 `\n` **再转一次**成 `\r\n`；
        # 而这里拼串用的是 `"\r\n".join(...)` ⇒ 两个 `\r` 叠加成 **`\r\r\n`**。
        # 后果：`splitlines()` 把 `\r\r\n` 当两个换行 ⇒ 凭空多一个空行 ⇒ 写回又多一个
        # ⇒ **空行指数级翻倍**（6 → 11 → 20 → 40 → … 约 30 次就是 3 GB），
        # 而读它时把内存吃到 23 GB、CPU 打满、界面未响应且关不掉。
        # `newline=""` 表示"不做任何换行转换"，这样拼出去的是什么就写什么。
        # 每行再剥掉裸 `\r` 作为双保险。
        ini_path.write_text(
            "\r\n".join(ln.replace("\r", "") for ln in merged) + "\r\n",
            encoding="utf-8",
            newline="",
        )
    except OSError as exc:
        _append_log(config, f"写入 runtime\\reshade\\ReShade.ini 失败（忽略）: {exc}")

    # ⚠️ 2026-10-03 实测同源问题：**第一人称的配置与中文字体也得同步到这份 ini**。
    # ReShade 以基准目录（= runtime\reshade）为准，所以它读的 `[endfield-enhancer]` /
    # `[STYLE]` 段是**这份**；而初始化只维护 `dlss5\ReShade.ini`。两份会分叉：
    #   * addon 首次运行把它读的那份写成**出厂值（全 0）** ⇒ `CameraEFMICompatibility=0`
    #     （与 EFMI 共存必需）、`ShortcutFirstPerson=0`（F1 没配上）、`Language=0`（英文）；
    #   * `[STYLE] Font` 为空 ⇒ addon 报 `Chinese font missing` ⇒ 中文显示成方块。
    # 2026-10-04 把这段收敛成 `sync_effective_reshade_ini()`（它会补段/补键），并且
    # **启动流程里还会在初始化之后再调一次** —— 因为这一步跑在 `initialize` 之前，
    # 那时 `dlss5\ReShade.ini` 可能还不存在（11:33 那份日志就是 `没有 …dlss5\ReShade.ini`
    # ⇒ 同步静默空转 ⇒ 生效那份留着 addon 写的 `Language=0` ⇒ 用户看到「中文没了」）。
    sync_effective_reshade_ini(config, log=lambda message: _append_log(config, message))

    return {
        "reshade_dir": str(reshade_dir),
        "panel_dir": str(base),
        "addon": str(installed_addon) if installed_addon.is_file() else "",
        "actions_tsv": str(actions_tsv) if actions_tsv.is_file() else "",
        "user_ini_path": str(config.user_ini_path),
        "deploy": result,
    }


def ensure_xxmi_signing_key(config_path: Path) -> dict[str, Any]:
    """确保 XXMI 的签名密钥**和** `Security.user_signature` 都在；缺了就生成一对。

    **为什么必须连 `user_signature` 一起设**（2026-09-29 读 XXMI 源码确认）：
    `xxmi_launcher/core/config_manager.py` 的 `AppConfigSecurity.__init__` 逻辑是

        if public_key is None or not verify(Config.Security.user_signature, ...):
            generate_key_pair(); write_key_pair(keys_path)
            Config.Security.user_signature = sign(os.getlogin())

    也就是说：**只要 `user_signature` 校验不过，XXMI 一启动就会自己重新生成一对密钥**。
    我们之前**只生成了密钥对、没设 `user_signature`**，于是 XXMI 一启动就换掉密钥，
    我们写下的所有 `*_signature` 全部作废 → 它再弹「Failed to validate unsecure
    settings!」→ 用户一点 Reset，`extra_libraries` / `enabled` / `game_folder` 全被
    清空 —— 这就是空环境「注入失败」的真相。

    密钥与签名格式与 XXMI 完全一致：**ECDSA(P-384)**、base64 文本包装的 **DER**、
    **SHA-256**；`user_signature` 签的是 `os.getlogin()`。
    """
    security_dir = config_path.parent / "Resources" / "Security"
    key_file = security_dir / "private_key.der"
    pub_file = security_dir / "public_key.der"
    try:
        import base64
        import os

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:  # pragma: no cover
        return {"ok": False, "generated": False,
                "message": f"缺少 cryptography，无法生成 XXMI 签名密钥：{exc}"}

    data: dict[str, Any] = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    security_block = data.setdefault("Security", {})
    if not isinstance(security_block, dict):
        security_block = {}
        data["Security"] = security_block

    if key_file.is_file() and pub_file.is_file() and str(security_block.get("user_signature") or ""):
        return {"ok": True, "generated": False,
                "message": "XXMI 签名密钥与 user_signature 均已存在"}

    try:
        login = os.getlogin()
    except OSError:                       # 某些服务/无控制台环境会失败
        login = os.environ.get("USERNAME") or ""
    if not login:
        return {"ok": False, "generated": False,
                "message": "取不到当前登录用户名，无法生成 XXMI 的 user_signature"}

    try:
        security_dir.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP384R1())
        private_der = key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_der = key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        key_file.write_bytes(base64.b64encode(private_der))
        pub_file.write_bytes(base64.b64encode(public_der))
        # 关键：连 user_signature 一起写，否则 XXMI 启动时会重新生成密钥、把我们写的签名全废掉
        security_block["user_signature"] = base64.b64encode(
            key.sign(login.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        ).decode("ascii")
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError) as exc:
        return {"ok": False, "generated": False, "message": f"生成 XXMI 签名密钥失败：{exc}"}
    return {"ok": True, "generated": True,
            "message": f"已生成 XXMI 签名密钥并写入 user_signature（{security_dir}）"}


def sign_xxmi_setting(config_path: Path, value: str) -> str:
    """用 XXMI 自己的私钥给「危险设置」的值签名。

    XXMI 把 ``extra_libraries`` / ``unsafe_mode`` / ``custom_launch`` 等标为
    *unsecure settings*：值本身 + 一个 ``*_signature``。校验不过时 XXMI 会弹
    「Failed to validate unsecure settings! [Reset] [Keep]」——点 Reset 会**清空设置**
    （注入列表没了 → ReShade 不注入 → 游戏闪退），所以程序改写后必须自己补签名。

    实测算法：ECDSA(P-384, SHA-256)，待签内容 = 字段值原样，签名 = base64(DER)。
    密钥文件 ``Resources\\Security\\private_key.der`` 是 **base64 文本包装的 DER**。
    """
    try:
        import base64

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:  # pragma: no cover
        raise LaunchError("缺少 cryptography，无法为 XXMI 设置签名（pip install cryptography）") from exc
    key_file = config_path.parent / "Resources" / "Security" / "private_key.der"
    if not key_file.is_file():
        # 便携包里不带这对密钥；空环境因此写不进注入库（2026-09-29 实测）。
        # XXMI 用同目录的 public_key.der 校验，所以缺了就自己生成一对。
        ensure_xxmi_signing_key(config_path)
    if not key_file.is_file():
        raise LaunchError(f"找不到 XXMI 私钥: {key_file}")
    der = base64.b64decode(key_file.read_bytes().strip())
    key = serialization.load_der_private_key(der, None)
    signature = key.sign(value.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


# 同一个 ReShade 底座（d3d12.dll）下挂的两组 addon。
# 一个进程只能有一个 ReShade 底座，所以两者无法用两个 dll 分开注入；
# 正确的"拆开"方式是各自启停 addon 文件——ReShade 只加载底座**根目录**里的
# *.addon64，把文件移进 _disabled 子目录就等于停用。
DLSS5_ADDON_GLOBS = ("renodx-dlss5.addon64", "dlss5-feed.addon64", "trans-zh.addon64", "translations.txt")
# ⚠️ **停用与放回的 glob 故意不对称**（2026-10-06）：
#   * **放回（启用）**只认精确名 —— 退役的旧 NR 引擎（`renodx-dlss5-4.7*`，已被官方
#     7.0.0-rc8 取代）**绝不能放回**：两个 neural addon 同装时两个都不工作
#     （DLSS5-Feeder 原话：Never install two neural add-ons … it does nothing at all）；
#   * **停用**还要覆盖这些退役旧名 —— 关掉 DLSS5 时，残留在底座目录里的旧引擎也必须
#     一起移进 `_disabled\`，否则 ReShade 照样加载它。
DLSS5_RETIRED_GLOBS = ("renodx-dlss5-4.7*.addon64",)
# ★ **DLSS4 多帧生成解锁（40 系）**（2026-10-06 用户要求"单列开关、与 dlss5 互斥"）：
#   上游 `MFGAdaUnlock-RenoDx` 是**一个 ReShade addon**（MIT 1.4.1，只改运行时内存），
#   所以启停方式与 DLSS5 完全一样 —— 在 `runtime\dlss5\` 与 `_disabled\` 之间搬文件。
MFG_ADDON_GLOBS = ("renodx-mfgunlock.addon64",)
FIRSTPERSON_ADDON_GLOBS = ("renodx-endfield-enhancer.addon64",)
# 「喂帧组件」单独一档（2026-10-01）：它平时跟 DLSS5 组件一起启停，但在**游戏自带 DLSS**
# 的机器上会与游戏自己的 DLSS 抢同一条 NGX 链路 —— `dlss5-feed` 组件自己在日志里就写着
# 「this game runs NVIDIA Streamline (sl.interposer.dll): it has DLSS of its own …
#   This project is for games WITHOUT DLSS — use the game's own DLSS with OptiScaler,
#   and remove dlss5-feed.addon64」。用户要求这件事**自动做掉**（默认开启、设置页可关）。
FEED_ADDON_GLOBS = ("dlss5-feed.addon64",)
ADDON_DISABLED_DIR = "_disabled"


def _unique_backup_path(path: Path) -> Path:
    """返回一个**不会覆盖已有文件**的备份名（目标被占就加时间戳/序号）。

    2026-10-01 修：原先两处都是 `if backup.exists(): backup.unlink()` 再改名 ——
    等于每次启动都先删掉上一份备份。游戏目录里的 `.endfieldmodcontroller.disabled`
    很可能正是**游戏自带的原始 dll**（不是我们放的），一旦被删，用户就再也回不到
    原始状态了。备份只增不删。
    """
    if not path.exists():
        return path
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for index in range(1, 100):
        suffix = "" if index == 1 else f"-{index}"
        candidate = path.with_name(f"{path.name}.{stamp}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name}.{stamp}-{os.getpid()}")


def _write_ini_atomic(path: Path, text: str) -> None:
    """原子改写 ini，并在**首次**改动前留一份 `.mc.bak`。

    2026-10-01 修（用户批准的边界外项 ②③）：这些 ini 是整棵注入链的配置源
    （EFMI 的 `d3dx.ini`、游戏目录的 `ReShade.ini`），原先一律 `write_text` 直接
    覆盖 —— 写到一半被杀软拦截 / 断电 / 进程被杀，就留下半截文件（注入全废），
    而且一个备份都没有，用户回不去。现在统一"临时文件 + os.replace"，
    备份只在第一次留，不会被后续轮次覆盖冲掉。
    """
    from . import fsutil

    path = Path(path)
    backup = path.with_name(path.name + ".mc.bak")
    if path.is_file() and not backup.is_file():
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass
    fsutil.write_text_atomic(path, text, newline=chr(10))


def restore_ini_backups(config: AppConfig) -> dict[str, Any]:
    r"""把 `<某个 ini>.mc.bak` 搬回原位（**`.mc.bak` 家族此前没有任何还原入口**）。

    2026-10-04 补。`_write_ini_atomic()` 会在**首次**改写前留一份 `<名>.mc.bak`，覆盖了
    EFMI 的 `d3dx.ini`、`runtime\dlss5\ReShade.ini`、游戏目录 `ReShade.ini` 与
    `user_ini_path.txt`；但全库只有 `restore_xxmi_extra_libraries()` 和 `api.rollback()`
    会读它，而且只覆盖 XXMI 配置与 `d3dx_user.ini` —— 其余几个用户**没有任何办法**搬回去
    （只能在资源管理器里翻出隐藏的 `.mc.bak` 手工改名）。这里统一处理我们能枚举到的那些。

    备份文件**保留不动**（它是唯一的"改之前"副本，删了就真回不去了）。
    """
    candidates: list[Path] = []

    def _add(path: Any) -> None:
        if not path:
            return
        try:
            candidate = Path(path)
        except TypeError:
            return
        if candidate not in candidates:
            candidates.append(candidate)

    _add(getattr(config, "dlss5_ini_path", None))
    _add(getattr(config, "user_ini_path", None))
    loader = getattr(config, "migoto_loader_path", None)
    if loader is not None:
        try:
            loader_dir = Path(loader).parent
            _add(loader_dir / "d3dx.ini")
            _add(loader_dir / "ReShade.ini")
        except (TypeError, OSError):
            pass
    try:
        from . import reshade_integration

        game_dir = reshade_integration.detect_game_dir(config)
        if game_dir is not None:
            _add(game_dir / "ReShade.ini")
            _add(game_dir / "user_ini_path.txt")
    except Exception:  # noqa: BLE001
        pass

    actions: list[str] = []
    warnings: list[str] = []
    for target in candidates:
        backup = target.with_name(target.name + ".mc.bak")
        if not backup.is_file():
            continue
        try:
            shutil.copy2(backup, target)
            actions.append(f"restored {target}（来自 {backup.name}）")
        except OSError as exc:
            warnings.append(f"还原 {target.name} 失败: {exc}")
    return {"ok": not warnings, "actions": actions, "warnings": warnings, "checked": len(candidates)}


def _image_pids(image_name: str) -> set[int]:
    """当前正在运行的某映像名的 PID 集合。

    用于"只收掉自己拉起的那一个进程"：`taskkill /IM <名>` 会连带杀掉用户
    自己刚打开的实例（2026-10-01 修 ⑨）。
    """
    pids: set[int] = set()
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return pids
    for line in (result.stdout or "").splitlines():
        parts = [cell.strip('"') for cell in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == image_name.lower():
            try:
                pids.add(int(parts[1]))
            except ValueError:
                continue
    return pids


def _copy_file_atomic(source: Path, target: Path) -> None:
    """把文件**原子地**复制到目标位置（先写同目录临时文件，再 os.replace）。

    2026-10-01 修（②）：往游戏目录放代理 DLL / `actions.tsv` 时直接 `copy2`
    覆盖，任何人在"写了一半"的那个窗口里启动游戏都会读到半截文件；
    改成原子替换后，目标要么是旧文件完整、要么是新文件完整。
    """
    from . import fsutil

    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fsutil.write_bytes_atomic(target, source.read_bytes())


def _sync_addon_location(source_dir: Path, target_dir: Path,
                         globs: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """把 `source_dir` 里匹配 `globs` 的 addon **搬到** `target_dir`，返回 (移动, 清理)。

    ⚠️ **目标已存在时不能只是 `continue`**（2026-10-04 抽出）：这正是
    `set_feed_addon_enabled` 那处修过的坑 —— 用户机器上 `runtime\\dlss5\\` 与
    `_disabled\\` **各有一份同名 addon**（"放回"时用了复制而不是移动、或手工拷回），
    于是状态判据说"启用中"、这里说"无需处理"，**两处互相矛盾、实际什么都没做**，
    连点几次开关都毫无反应。目标位置已经是我们想要的状态 ⇒ 把源位置那份**多余副本删掉**
    才算真到位。
    """
    moved: list[str] = []
    removed: list[str] = []
    for pattern in globs:
        for path in sorted(source_dir.glob(pattern)):
            target = target_dir / path.name
            if target.exists():
                try:
                    path.unlink()
                except OSError:
                    continue
                removed.append(path.name)
                continue
            try:
                shutil.move(str(path), str(target))
            except OSError:
                continue
            moved.append(path.name)
    return moved, removed


# ★★ **「有哪些插件组件」的唯一真源**（2026-10-06）。
# 为什么要有它：新加一个组件时，需要同步的地方曾经散落在三处 ——
#   ① `api.set_component_addon()` 开头的白名单；
#   ② 本函数的 globs 分支；
#   ③ `component_addon_status()` 的状态登记。
# 加 DLSS4(`mfg`) 那次就漏了 ① ⇒ 点开关被"未知组件: mfg"直接拒掉（用户看到的
# 是"开了没反应"）。现在三处**都从这里派生**，加组件只需改这一个字典。
COMPONENT_ADDON_GLOBS: dict[str, tuple[str, ...]] = {}


def set_component_addons(config: AppConfig, component: str, enabled: bool) -> dict[str, Any]:
    """单独启停 DLSS5 或第一人称插件（移动 addon 文件，可逆）。

    component: "dlss5" | "firstperson" | "mfg"
    """
    globs = COMPONENT_ADDON_GLOBS.get(component)
    if globs is None:
        return {"ok": False, "message": f"未知组件: {component}"}
    if component == "dlss5" and not enabled:
        # 停用要盖住退役旧名（放回**不盖**）—— 见 `DLSS5_RETIRED_GLOBS` 的说明。
        globs = tuple(globs) + DLSS5_RETIRED_GLOBS
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR
    disabled.mkdir(parents=True, exist_ok=True)
    source_dir, target_dir = (disabled, base) if enabled else (base, disabled)
    # ⚠️ 复用 `_sync_addon_location`（2026-10-04）：这里原来与 `set_feed_addon_enabled`
    # 是两套实现，而那处已经为"两处各有一份同名 addon ⇒ 点了开关毫无反应"修过一次
    # —— 只修一处的后果就是同一个 bug 在 DLSS5 / 第一人称这两个开关上继续存在。
    moved, removed = _sync_addon_location(source_dir, target_dir, tuple(globs))
    return {"ok": True, "component": component, "enabled": enabled,
            "moved": moved, "removed": removed}


# ── 「统一管理器」开关（2026-10-06 用户定的语义）───────────────────────────────
# 用户原话：「**那个开关就要叫统一管理器，不要讲那么多，默认开，如果这个不开，
#            锁快捷键强制关，如果开锁快捷键，这个强制开**」。
# 它管的是"**ReShade 底座 + 统一管理器面板**要不要在游戏里"：
#   * 开（默认）= 面板 addon 在 `runtime\dlss5\`；底座是否注入由
#     `reshade_integration.reshade_base_wanted()` 判（那个判据也读本开关）；
#   * 关 = 面板 addon 移进 `_disabled`（ReShade 里就没有统一管理器了），并**强制关掉
#     「Mod 快捷键锁定」** —— 没有面板就没有替代的换装入口，锁着键等于把用户的 Mod
#     按键直接拿走（2026-10-06 反馈者"皮肤打不进去"正是这个现场）。
#   * 它**不动其它插件**：DLSS5 / 第一人称 / 汉化 / 喂帧各按自己的开关。
UNIFIED_PANEL_ADDON = "endfieldmodcontroller.addon64"


def minimal_injection_status(config: AppConfig) -> dict[str, Any]:
    """「统一管理器」现在的状态：开关值 / 面板在根目录还是被停用。"""
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR
    return {
        "enabled": bool(getattr(config, "minimal_injection", False)),
        "panel_active": (base / UNIFIED_PANEL_ADDON).is_file(),
        "panel_parked": (disabled / UNIFIED_PANEL_ADDON).is_file(),
        "addon": UNIFIED_PANEL_ADDON,
    }


def apply_minimal_injection(config: AppConfig,
                            log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """按 `config.minimal_injection`（启动页「统一管理器」）铺上 / 收走面板。

    两层**都真的动**（用户准则：「那些滑块要真的有用，不要就做表面功夫」）：
    文件层把面板 addon 在 `runtime\\dlss5\\` 与 `_disabled\\` 之间搬；
    配置层在关掉时把「Mod 快捷键锁定」一并关掉（否则用户按 Mod 原键没反应、
    面板又不存在 —— 两边都没了）。
    """
    want = bool(getattr(config, "minimal_injection", False))
    actions: list[str] = []
    warnings: list[str] = []
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR

    def emit(text: str) -> None:
        if log is not None:
            try:
                log(text)
            except Exception:  # noqa: BLE001 - 日志失败绝不影响动作
                pass

    try:
        disabled.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "enabled": want, "actions": [],
                "warnings": [f"创建 _disabled 失败: {exc}"], "moved": [],
                "status": minimal_injection_status(config),
                "message": f"创建 _disabled 失败: {exc}"}

    source_dir, target_dir = (disabled, base) if want else (base, disabled)
    moved, removed = _sync_addon_location(source_dir, target_dir, (UNIFIED_PANEL_ADDON,))
    if want:
        if not (base / UNIFIED_PANEL_ADDON).is_file():
            warnings.append("面板没能在 ReShade 目录就位（随包资产缺失？）⇒ 游戏里不会出现统一管理器")
        else:
            actions.append("统一管理器已就位（ReShade 面板 + 统一管理器面板）")
    else:
        actions.append("统一管理器已关闭：面板已从 ReShade 目录移走")
        # ★ 用户 2026-10-06：「如果这个不开，锁快捷键强制关」
        if bool(getattr(config, "hotkey_takeover", False)):
            config.hotkey_takeover = False
            try:
                config.save()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"写配置失败（锁键可能没关干净）: {exc}")
            emit("统一管理器已关闭 → 一并关闭「Mod 快捷键锁定」（Mod 原键恢复可用）")
            actions.append("「Mod 快捷键锁定」已强制关闭")
    if removed:
        emit(f"统一管理器: 清掉多余副本 {', '.join(removed)}")
    return {
        "ok": not warnings,
        "enabled": want,
        "actions": actions,
        "warnings": warnings,
        "moved": sorted(set(moved)),
        "status": minimal_injection_status(config),
        "message": "；".join(actions) if actions else "统一管理器状态已确认",
    }


def set_feed_addon_enabled(
    config: AppConfig,
    enabled: bool,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """单独启停「喂帧组件」`dlss5-feed.addon64`（移动文件，**可逆**；不动 preset / shader）。

    与 `set_component_addons` 同一套机制（底座根目录 ↔ `_disabled` 子目录，ReShade 只加载
    根目录里的 `*.addon`/`*.addon64`），但**粒度更细**：只动这一个文件，避免把
    `renodx-dlss5*.addon64` / 汉化一起停掉。

    为什么需要它：在**游戏自带 DLSS**（`sl.interposer.dll` / 游戏原版 `nvngx_dlss.dll`）的机器上，
    `dlss5-feed` 组件自己就会在日志里建议「这个项目是给没有 DLSS 的游戏用的 —— 用游戏自己的
    DLSS，并移除 dlss5-feed.addon64」；留着它会与游戏自己的 DLSS（以及第三方 NGX 注入器）
    抢同一条 NGX 链路。用户 2026-10-01 要求这件事**自动做掉**（默认开启、设置页可关掉）。
    """
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR
    try:
        disabled.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "enabled": enabled, "moved": [], "message": f"创建 _disabled 失败: {exc}"}
    source_dir, target_dir = (disabled, base) if enabled else (base, disabled)
    moved: list[str] = []
    removed: list[str] = []
    for pattern in FEED_ADDON_GLOBS:
        for path in sorted(source_dir.glob(pattern)):
            target = target_dir / path.name
            if target.exists():
                # ⚠️ **目标已存在不能只是 `continue`**（2026-10-02 反馈者 31002 的现场）：
                # 他那台机器 `runtime\dlss5\` 与 `_disabled\` 里**各有一份**
                # `dlss5-feed.addon64`（大概是"放回"时用复制而不是移动、或手工拷回来的）。
                # 于是 `feed_addon_status` 说"启用中"（走进停用分支）、这里说"无需停用"，
                # 两个判据互相矛盾 ⇒ **什么也没做** ⇒ ReShade 一直加载着 feed，
                # 与 `renodx-dlss5` 抢同一条 NGX 链路 ⇒ 游戏 42 秒静默退出。
                # 目标位置**已经是我们想要的状态** ⇒ 把源位置这份多余的删掉，才算真到位。
                try:
                    path.unlink()
                except OSError as exc:
                    return {"ok": False, "enabled": enabled, "moved": moved, "removed": removed,
                            "message": f"清理多余副本 {path.name} 失败: {exc}"}
                removed.append(path.name)
                if log is not None:
                    try:
                        log(f"喂帧组件 dlss5-feed: 清掉多余副本 {path.name}（两处各有一份）")
                    except Exception:  # noqa: BLE001
                        pass
                continue
            try:
                shutil.move(str(path), str(target))
            except OSError as exc:
                return {"ok": False, "enabled": enabled, "moved": moved,
                        "message": f"移动 {path.name} 失败: {exc}"}
            moved.append(path.name)
            if log is not None:
                try:
                    log(f"喂帧组件 dlss5-feed: {'放回' if enabled else '停用'} {path.name}")
                except Exception:  # noqa: BLE001
                    pass
    action = "放回" if enabled else "停用"
    return {
        "ok": True,
        "enabled": enabled,
        "moved": moved,
        "removed": removed,
        "message": (f"已{action}喂帧组件（{', '.join(moved)}）" if moved
                    else (f"已清掉 {len(removed)} 个多余副本（{', '.join(removed)}），状态已到位"
                          if removed
                          else f"喂帧组件无需{action}（已经到位）")),
    }


def feed_addon_status(config: AppConfig) -> dict[str, Any]:
    """喂帧组件 `dlss5-feed.addon64` 现在在哪（根目录 = 启用中；`_disabled` = 已停用）。"""
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR
    active = [p.name for pattern in FEED_ADDON_GLOBS for p in base.glob(pattern)]
    inactive = [p.name for pattern in FEED_ADDON_GLOBS for p in disabled.glob(pattern)]
    return {
        "active": sorted(active),
        "disabled": sorted(inactive),
        "on": bool(active),
        "present": bool(active or inactive),
    }


# 唯一真源的内容在这里登记（放在 globs 三兄弟都定义好之后）。
COMPONENT_ADDON_GLOBS.update({
    "dlss5": DLSS5_ADDON_GLOBS,
    "firstperson": FIRSTPERSON_ADDON_GLOBS,
    "mfg": MFG_ADDON_GLOBS,
})


def component_addon_status(config: AppConfig) -> dict[str, Any]:
    """各插件的 addon 是否在位。

    ⚠️ **必须覆盖 `set_component_addons` 支持的每一个组件**（2026-10-06 的教训）：
    `ensure_injections` 会按组件名取 `status[component]`，这里少登记一个就是 `KeyError`
    ⇒ 用户看到「**launch failed: 'mfg'**」，而且**一键启动直接失败**。
    新增组件时**两处一起加**（本函数 + `ensure_injections` 的组件循环）。
    """
    base = config.dlss5_path
    disabled = base / ADDON_DISABLED_DIR

    def probe(globs: tuple[str, ...]) -> dict[str, Any]:
        active: list[str] = []
        inactive: list[str] = []
        for pattern in globs:
            active.extend(p.name for p in base.glob(pattern))
            inactive.extend(p.name for p in disabled.glob(pattern))
        return {"active": sorted(active), "disabled": sorted(inactive), "on": bool(active)}

    return {name: probe(globs) for name, globs in COMPONENT_ADDON_GLOBS.items()}


def active_efmi_loader(config: AppConfig) -> Path | None:
    """**当前生效那个 XXMI 自己的 EFMI loader（`d3d11.dll`）**在哪。

    为什么非要"它自己那份"（2026-10-04 两个用户现场一起定出来的）：
      * 注入库里**必须**有 `d3d11.dll` —— 否则 XXMI 会把自带那份**补到列表最前面**，
        变成「EFMI 先、ReShade 后」⇒ **顺序反了游戏起不来**（用户实测：改动前能玩 122 秒、
        改动后 25 秒就退）；
      * 但**只能列它自己那份**：列了别的 XXMI 的（用户装外部 XXMI 时列了内置那份），
        XXMI 去重不掉 ⇒ `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ 第二次注入必然失败
        ⇒ 「注入额外库 … 失败：DLL 注入失败！」**并中断整个启动**。

    路径取自 XXMI 配置的 `Importers.<active_importer>.Importer.importer_folder`：
      * 绝对路径（外部 XXMI 实测 `E:/ENDFIELD/EFMI`）⇒ 直接用；
      * 相对路径（内置 XXMI 实测 `EFMI/`）⇒ 相对 **XXMI 根**
        （`<XXMI 根>\\Resources\\Bin\\XXMI Launcher.exe` 往上三层）。
    """
    launcher = config.xxmi_launcher_path
    if launcher is None:
        return None
    launcher = Path(launcher)
    root = launcher.parent.parent.parent
    folder_text = ""
    try:
        from . import reshade_integration

        config_path = reshade_integration.xxmi_config_path(launcher)
        if config_path is not None and config_path.is_file():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            importers = data.get("Importers") or {}
            active = str((data.get("Launcher") or {}).get("active_importer") or "EFMI")
            block = importers.get(active) or importers.get("EFMI") or {}
            folder_text = str((block.get("Importer") or {}).get("importer_folder") or "")
    except Exception:  # noqa: BLE001 - 读不到就退回默认布局
        folder_text = ""
    candidates: list[Path] = []
    if folder_text.strip():
        folder = Path(folder_text.strip().replace("/", "\\"))
        if not folder.is_absolute():
            folder = root / folder
        candidates.append(folder / "d3d11.dll")
    candidates.append(root / "EFMI" / "d3d11.dll")     # 常规布局兜底
    fallback = config.efmi_dll_path                     # 最后退回我们自己探测到的那份
    if fallback is not None:
        candidates.append(Path(fallback))
    # ★★ **必须再验"它到底是不是这个 XXMI 自己的 loader"**（2026-10-06，`C:\Users\lzh18` 现场）。
    #
    #    原先只判 `is_file()` ⇒ 当 XXMI 配置里的 `importer_folder` 被指向**用户的 Mod 库**
    #    （实测 `C:/Users/lzh18/Downloads/library`）时，库里某个 Mod 自带的同名 `d3d11.dll`
    #    就被当成 loader 列进注入库 ⇒ 注入它之后游戏**极早期退出**：
    #    现场日志 `note=auto-postmortem: exit_code=3221225781`（= `0xC0000135 STATUS_DLL_NOT_FOUND`，
    #    那个 dll 自己依赖的东西找不到），`Player.log` 只写到 `Forcing GfxDevice` 就断了。
    #
    #    ⚠️ **第一版判据（"旁边有 d3dx.ini"）实测没挡住**（他 21:17 / 22:26 仍列着库里的那份）
    #    —— Mod 库里也可能有 `d3dx.ini`（很多 Mod 自带），所以那条不够硬。
    #
    #    ⇒ 现在加一条**结构性**判据：**loader 必须位于这个 XXMI 自己的目录树内**
    #      （`root` = XXMI 根）。EFMI 的 loader 只可能出现在 XXMI 的 `EFMI\` 或它的
    #      `Resources\Packages\XXMI\` 下 —— 用户 Mod 库、桌面、任何 XXMI 之外的位置
    #      一律不认。这条与"文件长什么样"无关，挡得住任何同名文件。
    root_resolved = root.resolve()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            inside = candidate.resolve().is_relative_to(root_resolved)
        except OSError:
            inside = False
        if not inside:
            _append_log(
                config,
                f"注入自检: 跳过 {candidate} —— 它不在这个 XXMI 的目录里"
                f"（{root_resolved}），不可能是它的 EFMI loader"
                "。多半是 XXMI 设置里的 importer 目录被指到了 Mod 库，"
                "把它改回 …\\XXMI\\EFMI 即可"
            )
            continue
        if (candidate.parent / "d3dx.ini").is_file():
            return candidate
        # ⚠️ **XXMI 的包目录那份是"loader 模板"，要照旧认**（2026-10-06）：
        #    EFMI 还没被 XXMI 部署到 `EFMI\` 的那一刻，XXMI 自己用的就是
        #    `Resources\Packages\XXMI\d3d11.dll`，而它旁边**本来就没有** `d3dx.ini`
        #    （那是安装包目录，不是运行目录）。只认 `d3dx.ini` 会把这条合法回退也堵掉
        #    （实测：`test_efmi_loader_deploy` 立刻变红）。
        _parent_text = str(candidate.parent).replace("\\", "/").lower()
        if "/packages/xxmi" in _parent_text:
            return candidate
        _append_log(
            config,
            f"注入自检: 跳过 {candidate} —— 它既不在 EFMI 运行目录（旁边没有 d3dx.ini）、"
            "也不在 XXMI 的包目录，不像 EFMI loader"
            "（多半是 XXMI 配置里的 importer 目录被指到了 Mod 库）"
        )
    return None


def dlss5_injection_targets(config: AppConfig) -> list[str]:
    """本方案写进 XXMI 注入库的内容：DLSS5 的 d3d12.dll + EFMI 的 d3d11.dll。

    视频方案（BV1XMh76UEA5）实测有效的最小集合就是这两条：XXMI 启动游戏时把
    它们注入进程，于是唯一一个 ReShade 底座（DLSS5 的 d3d12.dll）同时带上
    RenoDX-DLSS5 与 Endfield Enhancer 两个插件，EFMI 负责服装 Mod，互不抢 hook。
    """
    targets: list[str] = []
    dll = config.dlss5_dll_path
    if not dll.is_file():
        raise LaunchError(f"DLSS5 ReShade 底座不存在: {dll}")
    # 要不要注入底座：**判据唯一来源**是 `reshade_integration.reshade_base_wanted()`
    # ——「Mod 快捷键锁定」的"能不能锁"也读它。两边必须同一口径，否则就会出现
    # "文件在磁盘上所以放行、可实际根本没注入"那种事故（2026-10-06 反馈者现场）。
    want_base, _base_reason = reshade_integration.reshade_base_wanted(config)
    if want_base:
        targets.append(str(dll))
    # ❌ **绝不要把 EFMI 的 `d3d11.dll` 列进 `extra_libraries`**（2026-10-03 实测定位）。
    #    原因：**XXMI 自己就会注入它** —— 它的日志里那条注入请求长这样：
    #        Inject(library_name='d3d11.dll, d3d12.dll, d3d11.dll')
    #    即「自带 EFMI d3d11.dll ＋ 我们的 d3d12.dll ＋ **我们额外列的那个 d3d11.dll**」。
    #    同一个 DLL（内容相同、路径不同）注入第二次必然失败 ⇒ 用户看到
    #    「注入额外库 …\Packages\XXMI\d3d11.dll 失败：DLL 注入失败！」并且**整个启动中断**。
    #    （这正是记忆里那条「XXMI 可能仍自动注入默认 EFMI d3d11.dll，若再列就会重复加载」。）
    #
    #    而 EFMI 的注入**不会因此丢**：XXMI 那条自带注入照旧执行
    #    （2026-10-02 用户实测「efmi 关了直接终末地拉不起来」⇒ 它确实是必需品，
    #     但由 XXMI 负责，不归我们管）。
    #
    # ⚠️⚠️ **2026-10-03 回滚开关**：`extra_libraries_include_efmi_dll = True` 时
    # **加回 EFMI 的 `d3d11.dll`**（= 我改动之前的写法，用户当时是能跑的）。
    # 用户实测「开 DLSS5 或第一人称就崩、两个都关就能启动」，需要一次判定
    # "去掉这第二条" 是不是崩因之一。默认 True = 回到改动前。
    # ⚠️⚠️ **必须列，但只能列"当前生效 XXMI 自己那份 loader"**（2026-10-04 定案；完整机理见
    #    `config.py` 里该字段的说明与 `active_efmi_loader()`）：
    #      * **不列** ⇒ XXMI 把自带那份补到列表最前面 ⇒ EFMI 先、ReShade 后 ⇒ **游戏起不来**
    #        （用户实测：改动前能玩 122 秒、改动后 25 秒就退）；
    #      * **列错的那份** ⇒ XXMI 去重不掉 ⇒ `Inject('d3d11.dll, d3d12.dll, d3d11.dll')`
    #        ⇒ 第二次注入失败 + **整个启动中断**。
    #    它排在上面那条 `d3d12.dll` **之后**，这正是顺序要求（ReShade 必须先于 EFMI 进进程）。
    if bool(getattr(config, "extra_libraries_include_efmi_dll", True)):
        _efmi = active_efmi_loader(config)
        if _efmi is not None and _efmi.is_file():
            targets.append(str(_efmi))
    # 乳摇：可选用「注入 sbm.dll」的方式（config.secondary_motion_dll 指向短路径下的
    # sbm.dll）。这样游戏目录不用替换 d3dcompiler_47.dll / vulkan-1.dll，
    # 避免和 ReShade/EFMI 抢 D3D 调用链（proxy 方式实测 65 秒崩）。
    sbm_setting = str(getattr(config, "secondary_motion_dll", "") or "").strip()
    # ⚠️ 这里**不再看**「统一管理器」：那个开关只管"面板在不在"，
    #    乳摇注入与否只听它自己的 `secondary_motion_injection`（2026-10-06 语义）。
    if sbm_setting and getattr(config, "secondary_motion_injection", False):
        sbm = config.resolve_path(sbm_setting)
        if sbm.is_file():
            targets.append(str(sbm))
    return targets


def ensure_efmi_loader_deployed(config: AppConfig, *,
                                 log: Callable[[str], None] | None = None) -> str:
    """把 XXMI **包目录**里的 `d3d11.dll` 提前部署到 `EFMI\\d3d11.dll`（返回给人看的一句话）。

    为什么必须提前（2026-10-06 反馈者两次运行对照）：
      * `EFMI\\d3d11.dll` 还不存在时，`active_efmi_loader()` 会**回退到包目录那份**
        `Resources\\Packages\\XXMI\\d3d11.dll`，于是注入库里写到的是**另一条路径**；
      * 而 XXMI 随后**自己会把包目录那份部署到 `EFMI\\d3d11.dll` 并注入它** ⇒
        同一份 DLL、两个路径 ⇒ XXMI **去重不掉** ⇒ 注入请求变成
        `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ **第二次注入失败 + 整个启动中断**
        （用户看到「注入额外库 …\\Packages\\XXMI\\d3d11.dll 失败：DLL 注入失败！」）。
    表现是**时好时坏**：EFMI 已部署的那次就正常，所以"自检无缺失却打不开"。

    这里只做"提前一步"：目标已存在就什么都不动；两份都没有就如实返回空串（交给上层照旧）。
    """
    efmi = config.efmi_dir
    if efmi is None:
        return ""
    target = efmi / "d3d11.dll"
    if target.is_file():
        return ""
    source = config.efmi_dll_path
    if source is None or not source.is_file() or source == target:
        return ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError as exc:
        return f"提前部署 EFMI loader 失败（{exc}）—— 注入库可能会列到错的那份"
    message = (f"已把 XXMI 包目录里的 d3d11.dll 提前部署到 {target}"
               f"（避免注入库列到另一条路径 ⇒ 重复注入导致启动中断）")
    return message


def configure_dlss5_injection(config: AppConfig, enabled: bool = True) -> dict[str, Any]:
    """开/关**注入库**：改写 XXMI 的 EFMI `extra_libraries`（可回滚）。

    ⚠️ 函数名带 `dlss5` 是历史命名，**它管的不是"DLSS5 神经渲染"那个开关**，而是
    **所有功能共用的注入底座**（2026-10-07 用户就被这个名字误导过：
    「为什么我没开 dlss5 日志也说按 dlss5」）：

    开 = 写入注入库（`d3d12.dll` 底座 + `EFMI\\d3d11.dll`）—— DLSS4 多帧生成、DLSS5 神经渲染、
         第一人称、游戏内面板**全靠这两条**；
    关 = 清空注入库（只跑服装 Mod，ReShade 与上面那些插件都不加载）
    """
    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        raise LaunchError("XXMI Launcher 路径未配置")
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        raise LaunchError("找不到 XXMI Launcher Config.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    importer = data.setdefault("Importers", {}).setdefault("EFMI", {}).setdefault("Importer", {})
    backup = config_path.with_suffix(config_path.suffix + ".mc.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    if enabled:
        targets = dlss5_injection_targets(config)
        importer["extra_libraries_enabled"] = True
        importer["extra_libraries"] = "\n".join(targets)
    else:
        targets = []
        importer["extra_libraries_enabled"] = False
        importer["extra_libraries"] = ""
    # 同步签名：不然 XXMI 判定为 unsecure setting 会弹 Reset/Keep，点 Reset 就清空注入列表
    importer["extra_libraries_signature"] = sign_xxmi_setting(config_path, importer["extra_libraries"])
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    config.dlss5_injection = enabled
    config.reshade_injection = "xxmi_extra" if enabled else "none"
    config.save()
    # ⚠️ 日志**不要**写成"DLSS5 注入"（2026-10-07 用户被它误导：「为什么我没开dlss5
    #    日志也说按dlss5」）。这里的 `targets` 是 **XXMI 的注入库**（`extra_libraries`）
    #    —— 即 **ReShade 底座 + EFMI**，**所有功能共用的地基**：
    #    DLSS4 多帧生成、DLSS5 神经渲染、第一人称、游戏内面板全靠这两条。
    #    它与「DLSS5 神经渲染」那个**开关**没有任何关系（关掉那个开关本条照样打印）。
    _append_log(
        config,
        f"注入库已写入（ReShade 底座 + EFMI，DLSS4/DLSS5/第一人称共用）: "
        f"{targets or '(注入库已清空)'}",
    )
    return {
        "ok": True,
        "enabled": enabled,
        "config_path": str(config_path),
        "backup": str(backup),
        "extra_libraries": targets,
    }


def dlss5_injection_status(config: AppConfig) -> dict[str, Any]:
    """当前 DLSS5/第一人称注入状态，供 UI 与自检使用。"""
    launcher = config.xxmi_launcher_path
    status: dict[str, Any] = {
        "xxmi_launcher": str(launcher) if launcher else "",
        "dlss5_dir": str(config.dlss5_path),
        "dlss5_dll": str(config.dlss5_dll_path),
        "dlss5_dll_exists": config.dlss5_dll_path.is_file(),
        "enhancer_addon_exists": config.dlss5_enhancer_addon_path.is_file(),
        "efmi_dll": str(config.efmi_dll_path or ""),
        "config_path": "",
        "extra_libraries": "",
        "enabled": False,
        "has_dlss5": False,
    }
    if launcher is None:
        return status
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        return status
    status["config_path"] = str(config_path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        importer = data.get("Importers", {}).get("EFMI", {}).get("Importer", {})
        libs = str(importer.get("extra_libraries") or "")
        status["extra_libraries"] = libs
        # ⚠️ **签名也要带出来**（2026-10-06 加）：XXMI 靠 `extra_libraries_signature`
        # 判断注入库有没有被人动过，改坏了它会弹 Reset/Keep（点了 Reset 注入列表就空了）。
        # 以前这个 dict 只给"条数"，于是 `injecttrace` 里读签名长度**恒为 0**，
        # 时间线上那条判据等于没有（反馈者 1.0.15 的包里实测：jsonl 里 sig=0，
        # 而 summary 另一段却读出 140 —— 同一份文件两个结论）。
        status["extra_libraries_signature"] = str(importer.get("extra_libraries_signature") or "")
        status["user_signature"] = str((data.get("Security") or {}).get("user_signature") or "")
        status["enabled"] = bool(importer.get("extra_libraries_enabled")) and bool(libs.strip())
        status["has_dlss5"] = str(config.dlss5_dll_path).lower() in libs.lower()
    except Exception as exc:  # noqa: BLE001
        status["error"] = str(exc)
    return status


def xxmi_process_running(config: AppConfig) -> bool:
    """XXMI Launcher 进程当前在不在跑（用 exe 的映像名判断）。"""
    path = config.xxmi_launcher_path
    if path is None:
        return False
    return bool(_image_pids(Path(str(path)).name))


def ensure_xxmi_available(config: AppConfig) -> dict[str, Any]:
    """确保有一个能用的 XXMI Launcher：留空 → 找内置；内置没有 → **自动下载安装**。

    用户 2026-10-01 原话：「显示 xxmi 找不到卡死，**xxmi 如果留空应该就找内置正常会放的
    地方，没有就下载**」。以前 `xxmi_launcher` 一边是空就直接抛
    「没有配置可用的 XXMI Launcher 路径」，用户既看不懂、也不知道该去哪装 —— 而内置那份
    本来就是我们自己负责装的东西，没有理由让他去手填路径。
    """
    path = config.xxmi_launcher_path
    if path is not None and Path(path).is_file():
        return {"ok": True, "path": str(path), "installed": False, "changed": False}

    if not getattr(config, "use_builtin_runtime", True):
        return {
            "ok": False,
            "path": "",
            "installed": False,
            "changed": False,
            "message": ("没有可用的 XXMI Launcher：当前关掉了「使用内置 XXMI/EFMI」，"
                        "程序不会自动下载 —— 请在设置页填上你自己的 XXMI Launcher 路径，"
                        "或者把「使用内置 XXMI/EFMI」打开"),
        }

    from . import runtime_deps

    try:
        result = runtime_deps.ensure_xxmi(config)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "path": "",
            "installed": False,
            "changed": False,
            "message": f"内置 XXMI 缺失且自动下载失败：{exc}（可到「依赖」页点「自动安装/更新」重试）",
        }

    path = config.xxmi_launcher_path
    if path is None or not Path(path).is_file():
        return {
            "ok": False,
            "path": "",
            "installed": True,
            "changed": True,
            "message": "内置 XXMI 装完却找不到 Launcher exe（安装包结构可能变了），请到「依赖」页重新安装",
        }
    return {
        "ok": True,
        "path": str(path),
        "installed": True,
        "changed": True,
        "message": f"已自动安装内置 XXMI：{path}",
        "version": str(getattr(result, "version", "") or ""),
    }


def ensure_injections(config: AppConfig) -> dict[str, Any]:
    """一键启动前的完整自检。

    分工：
      * **XXMI 负责的注入**（进程启动时把 d3d12.dll / d3d11.dll 注进游戏）不在检查范围内，
        这里只保证「XXMI 注入库」这个配置写对了。
      * **文件层面的初始化**全部交给 ``initialize.ensure_all``：DLSS5 目录内容、
        ReShade.ini 与 [endfield-enhancer] 段、游戏目录 nvngx 运行库、控制器文件、
        Mod staging、乳摇注入 —— 缺什么补什么。
    """
    actions: list[str] = []
    warnings: list[str] = []
    # 本次是否"为了生成配置临时拉起过一次 XXMI" —— 是的话说明这是第一次启动，
    # 紧接着那次真正的启动有较大概率失败，UI 要在**拉起 XXMI 之后**据此弹提示
    # （用户 2026-10-01：「我说的第一次启动是在拉起 xxmi 之后再谈，选项应该是
    #   再次启动和先不启动」）。
    xxmi_bootstrapped = False

    # ⓪ **先确保有一个能用的 XXMI Launcher**（用户 2026-10-01：「xxmi 如果留空应该就找内置
    #    正常会放的地方，没有就下载」）。留空 → 内置；内置不在 → 自动下载安装。
    #    以前这一步缺失，`xxmi_launcher` 一旦为空就直接抛「没有配置可用的 XXMI Launcher
    #    路径」，用户看到的是一句看不懂的报错 + 界面像卡住了。
    try:
        available = ensure_xxmi_available(config)
        if available.get("changed"):
            actions.append(str(available.get("message") or "已安装内置 XXMI"))
        elif not available.get("ok"):
            warnings.append(str(available.get("message") or "找不到可用的 XXMI Launcher"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"准备 XXMI Launcher 失败: {exc}")

    # ⓪b **最小注入模式**（2026-10-06 用户要求）：先把"除统一管理器面板以外的东西"停掉
    #     （或按记录恢复），再往下走注入库那几步 —— `dlss5_injection_targets()` 是**按开关
    #     状态**决定注入哪几个 dll 的，顺序反了就会出现"开关关了、注入库里还列着"。
    try:
        minimal = apply_minimal_injection(config, log=lambda message: actions.append(message))
        if minimal.get("enabled"):
            actions.append("最小注入模式：只加载 ReShade 底座与统一管理器面板")
        for warning in minimal.get("warnings") or []:
            warnings.append(str(warning))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"应用最小注入模式失败: {exc}")

    # ⓪c **Streamline/NGX 的 server manifest 坏了就备份移走**（2026-10-06）。
    #     现场（一台 i9-13980HX + Win11 + RTX 40 系）：游戏启动后 **15 毫秒**连打 10 条
    #     `[streamline][error] ota.cpp:329 [parseServerManifest] Unexpected line in manifest file`，
    #     随后内存从 627 MB 涨到 **1694 MB**、线程掉到 1、进程自己退出 ——
    #     **没有 WER、也不像崩溃**，光看崩溃取证什么都抓不到；而包内
    #     `%LOCALAPPDATA%\NVIDIA\NGX\models\config\versions\2\files\nvngx_server_config.txt`
    #     **是 0 字节**（名字与报错的 `parseServerManifest` 直接对应）。
    #     判据读游戏 `Player.log`；命中就把 NGX 的 server manifest 与 Streamline 的 OTA 缓存
    #     **备份移走**（只搬不删，驱动/游戏下次启动会自己重建）。
    try:
        from . import crashwatch

        if crashwatch.streamline_manifest_broken(config):
            moved = crashwatch.repair_streamline_manifest(
                config, log=lambda message: actions.append(message))
            if moved:
                actions.append(f"Streamline 的 server manifest 读不懂 → 已备份移走 "
                               f"{len(moved)} 个缓存文件（驱动下次启动会自动重建）")
            else:
                warnings.append("Streamline 的 server manifest 读不懂，但没找到可清理的缓存文件"
                                "（可能不在标准位置，请把诊断包发来）")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"检查 Streamline 缓存失败: {exc}")

    # ① **XXMI 的配置文件本身必须先存在** —— 它是 XXMI 首次运行时生成的，空环境里没有，
    #    于是下面所有写入（game_folder / enabled_importers / 签名 / extra_libraries）
    #    全都会落空，表现为「注入失败」（2026-09-29 端到端实测定位）。
    try:
        boot = bootstrap_xxmi_config(config, log=lambda m: actions.append(m))
        if boot.get("created"):
            xxmi_bootstrapped = True
            actions.append(str(boot.get("message")))
        elif not boot.get("ok"):
            warnings.append(str(boot.get("message")))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"准备 XXMI 配置文件失败: {exc}")

    # ⚠️ **必须在任何配置改写之前**先确保 XXMI 的签名密钥与 Security.user_signature 就位。
    # 否则会出现"后写覆盖先写"：写 extra_libraries 时才发现缺密钥、于是生成密钥并写好
    # user_signature，可紧接着上层又用手里的**旧配置副本**写回，把 user_signature 盖回空值
    # —— XXMI 启动时发现它无效，就自己重新生成一对密钥，把我们写的所有签名全废掉，
    # 再弹「Failed to validate unsecure settings!」（2026-09-29 实测：user_signature 长度 0）。
    try:
        launcher_path = config.xxmi_launcher_path
        if launcher_path is not None:
            xxmi_config = reshade_integration.xxmi_config_path(launcher_path)
            if xxmi_config is not None and xxmi_config.is_file():
                key_state = ensure_xxmi_signing_key(xxmi_config)
                if key_state.get("generated"):
                    actions.append(str(key_state.get("message") or "已生成 XXMI 签名密钥"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"准备 XXMI 签名密钥失败: {exc}")

    # ⚠️ **2026-10-01 修 NameError（由反馈者诊断包定位）**：本函数里从来没有名为 `log` 的
    # 局部变量（其它调用点用的是 `log=lambda ...`），而下面两处写成了 `log=log` →
    # **抛 `NameError` 被 except 吞成一条 WARN**，后果是：
    #   ① `ensure_xxmi_game_folder()` **从来没执行过** ⇒ XXMI 配置里 `active_importer` /
    #      `enabled_importers` 一直是 None ⇒ **XXMI 界面里不出现终末地的启动按钮**；
    #   ② OptiScaler 的自动移走也从来没执行过。
    # 现在统一给本函数一个局部 logger。
    def _log(message: str) -> None:
        _append_log(config, message)

    # 让 XXMI 知道游戏装在哪 —— 否则它界面里不会出现终末地的启动按钮（2026-09-29 空环境实测）
    try:
        game_folder_state = ensure_xxmi_game_folder(config, log=_log)
        if game_folder_state.get("changed"):
            actions.append(str(game_folder_state.get("message") or "已让 XXMI 指向游戏目录"))
        elif not game_folder_state.get("ok"):
            # 2026-10-01：失败**不再静默** —— 以前这条 message 谁都不记，于是
            # "XXMI 里没有终末地启动按钮"只能靠猜（诊断包里 active_importer=None）。
            warnings.append(str(game_folder_state.get("message") or "XXMI 未能指向游戏目录"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"写入 XXMI 游戏目录失败: {exc}")

    # 第三方 NGX 注入器（OptiScaler）会截走进程里**所有** NGX 调用 —— 连游戏自带的 DLSS
    # 一起 —— 而它自己的 `[DlssNr] Enabled` 默认是 false（只做超分），于是 DLSS5 的神经
    # 渲染一帧都出不来（面板 `成功NR帧 0` / `0xBAD00001`）。用户 2026-10-01 明确要求
    # 「**不是提示的问题，正常用户不会看日志，需要自动检测处理**」→ 这里在**注入之前**
    # 就把它备份移走（`game_clean.quarantine_injector`：先备份、proxy 补回系统原版、可还原）。
    try:
        from . import game_clean

        conflict_state = game_clean.quarantine_injector(config, log=_log)
        if conflict_state.get("changed"):
            actions.append(str(conflict_state.get("message")
                               or "已移走第三方 NGX 注入器（OptiScaler）"))
        elif not conflict_state.get("ok"):
            warnings.append(str(conflict_state.get("message")
                                or "处理第三方 NGX 注入器失败"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"处理第三方 NGX 注入器失败: {exc}")

    # 先按两个开关同步 addon 的启停（同一底座下的 DLSS5 / 第一人称各自独立）
    status = component_addon_status(config)
    for component, key, label in (
        ("dlss5", "dlss5_addon_enabled", "DLSS5 神经渲染"),
        ("firstperson", "firstperson_addon_enabled", "第一人称 Endfield Enhancer"),
        ("mfg", "mfg_unlock_enabled", "DLSS4 多帧生成（40 系解锁）"),
    ):
        want = bool(getattr(config, key, True))
        if bool(status[component]["on"]) != want:
            try:
                moved = set_component_addons(config, component, want)
                detail = ", ".join(moved["moved"]) or "(已一致)"
                actions.append(f"{label} {'启用' if want else '停用'}: {detail}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"切换 {label} 失败: {exc}")

    # ⓪d **写注入库之前，先把 EFMI 的 loader 部署到位**（2026-10-06 现场）：
    #     否则 `active_efmi_loader()` 会回退到 XXMI 包目录那份，注入库里就写到**另一条路径**
    #     ⇒ XXMI 去重不掉 ⇒ `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ 第二次注入失败
    #     并且**中断整个启动**（"自检无缺失却打不开"就是这么来的）。
    try:
        deployed = ensure_efmi_loader_deployed(config, log=_log)
        if deployed:
            actions.append(deployed)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"提前部署 EFMI loader 失败: {exc}")

    if config.dlss5_injection:
        try:
            injection = configure_dlss5_injection(config, enabled=True)
            actions.append("XXMI 注入库: " + " + ".join(injection["extra_libraries"]))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"写入 XXMI 注入库失败: {exc}")
    else:
        # 关闭时必须主动清空，否则会保留上一次写进去的 DLL（滑块看着关了、实际还在注入）
        try:
            configure_dlss5_injection(config, enabled=False)
            actions.append("XXMI 注入库已清空（注入底座关闭）")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"清空 XXMI 注入库失败: {exc}")

    from . import initialize

    report = initialize.ensure_all(config, log=lambda message: _append_log(config, message))
    actions.extend(report.get("actions", []))
    warnings.extend(report.get("warnings", []))

    # ★★ **Streamline 运行库要写进游戏目录**（2026-10-06 用户拍板）。
    #    为什么：多帧生成解锁的 6x 依赖 `nvngx_dlssg.dll` 310.9.x + Streamline 2.14.1
    #    （上游 README：`Exact DLSS-G 310.9.0/310.9.1 provider and payload validation`），
    #    而终末地自带的是 310.5.2 / 2.10.3 ⇒ 面板只会显示「Dynamic MFG requires …」。
    #    ⚠️ **写游戏目录前先备份原版**，且备份走管理器统一的备份区（`game_backup\<时间戳>\`）
    #       ⇒ 依赖页/还原入口能列出它、**一键还原能直接还原**（用户明确要求）。
    #    幂等：内容一致就不动；没下载 / 没开多帧生成时整段跳过。
    if bool(getattr(config, "mfg_unlock_enabled", False)):
        try:
            deployed = runtime_deps.deploy_streamline_libs(
                config, log=lambda message: _append_log(config, message))
            if deployed.get("deployed"):
                actions.append(f"Streamline 运行库: {deployed.get('message')}")
                _append_log(config, f"Streamline 运行库: {deployed.get('message')}"
                                    f"（备份 {deployed.get('backup_stamp')}）")
            elif not deployed.get("ok"):
                warnings.append(f"Streamline 运行库未部署: {deployed.get('message')}")
        except Exception as exc:  # noqa: BLE001 - 部署失败不该拦住启动
            warnings.append(f"Streamline 运行库部署失败: {exc}")
            _append_log(config, f"Streamline 运行库部署失败（忽略）: {exc}")

    # ★★ **展开随包资产之后必须再对齐一次插件位置**（2026-10-06，用户现场定案）——
    #    上面的组件循环做的是"按配置把 addon 留在根目录 / 搬进 `_disabled\`"，
    #    而 `ensure_all()` 展开资产时**只判断"根目录有没有这个文件"**：发现缺，
    #    就**又解压一份回去** ⇒ 刚按配置禁用的插件被自己的展开动作撤销。
    #    实测现场（50 系那台）：`mfg_unlock_enabled = False`，可根目录里
    #    `renodx-mfgunlock.addon64`（1,191,424 B）**还在**、`_disabled\` 是空的
    #    ⇒ ReShade 照样加载它 ⇒ 用户报的就是「**关了为什么还是注入了**」。
    #    ⚠️ 受影响的不止 DLSS4：`dlss5` / `firstperson` 走的是同一条路。
    for _component, _flag in (("dlss5", "dlss5_addon_enabled"),
                              ("firstperson", "firstperson_addon_enabled"),
                              ("mfg", "mfg_unlock_enabled")):
        try:
            set_component_addons(config, _component, bool(getattr(config, _flag, False)))
        except Exception:  # noqa: BLE001 - 对齐失败不该拦住启动
            pass
    # ⚠️ **「统一管理器」的面板 addon 走的是另一条路**（`apply_minimal_injection`），
    #    所以这里要**单独再对齐一次** —— 同一个病换了个函数（2026-10-06 用户现场：
    #    「我除了 dlss4 全关，但是 **MOD 管理器**和第一人称还是注入了」，根目录里
    #    `endfieldmodcontroller.addon64` 还在，而 `_disabled\` 里也有它）。
    try:
        apply_minimal_injection(config, log=lambda message: _append_log(config, message))
    except Exception:  # noqa: BLE001 - 对齐失败不该拦住启动
        pass

    for action in actions:
        _append_log(config, f"注入自检: {action}")
    # ⚠ **失败原因也必须落进日志文件**（rules：批处理失败原因不能只写在内存里）。
    #   2026-10-01 现场：「XXMI 里没有终末地启动按钮」在 launch.log 里**一个字都没有** ——
    #   因为 warnings 只回给前端日志窗、没写盘，事后完全查不出是哪一步没写成功。
    for warning in warnings:
        _append_log(config, f"WARN 注入自检: {warning}")
    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "initialize": report,
        # 供 UI 判断"要不要提示用户再启动一次"（第一次启动才为 True）
        "xxmi_bootstrapped": xxmi_bootstrapped,
    }


def configure_xxmi_extra_libraries(config: AppConfig) -> dict[str, Any]:
    """Add the ReShade DLL to XXMI's EFMI extra_libraries list.

    XXMI validates this setting with a local signature.  The function writes the
    JSON and creates a backup; the first launch may show XXMI's own
    "unsecure setting" prompt where the user can choose Keep once.
    """
    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        raise LaunchError("XXMI Launcher path is not configured")
    reshade_dll = config.reshade_dll_path
    if reshade_dll is None or not reshade_dll.is_file():
        raise LaunchError("ReShade DLL path is not configured")
    config_path = reshade_integration.xxmi_config_path(launcher)
    if config_path is None:
        raise LaunchError("XXMI Launcher Config.json was not found next to XXMI Launcher")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    importer = data.setdefault("Importers", {}).setdefault("EFMI", {}).setdefault("Importer", {})
    # ⚠️ 先把**已经不存在的路径**剔掉再写：这里以前只追加、从不清理，于是程序目录
    # 改名/搬家之后，注入库里会一直躺着旧位置的死路径（XXMI 会去加载一个不存在的 DLL，
    # 而注入列表里的死项还会参与签名）。与「一键启动」的全量重写互为兜底。
    existing = [line.strip() for line in str(importer.get("extra_libraries") or "").splitlines() if line.strip()]
    dropped = [item for item in existing if not Path(item).is_file()]
    existing = [item for item in existing if Path(item).is_file()]
    if dropped:
        _append_log(config, f"XXMI 注入库清理掉 {len(dropped)} 条已不存在的路径: {dropped}")
    reshade_path = str(reshade_dll)
    if reshade_path not in existing:
        existing.append(reshade_path)
    importer["extra_libraries_enabled"] = True
    importer["extra_libraries"] = "\n".join(existing)
    backup = config_path.with_suffix(config_path.suffix + ".mc.bak")
    if not backup.exists():
        shutil.copy2(config_path, backup)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    # 顺便告诉 XXMI 游戏装在哪 —— 否则它界面里不会出现终末地的启动按钮（2026-09-29 实测）
    game_folder = ensure_xxmi_game_folder(config)
    return {
        "config_path": str(config_path),
        "backup": str(backup),
        "extra_libraries": reshade_path,
        "game_folder": game_folder.get("message", ""),
    }



def bootstrap_xxmi_config(config: AppConfig, *, wait_seconds: int = 40,
                          log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """XXMI 的配置是**它首次运行时生成**的；刚从包里解压出来时并不存在。

    不存在时我们写的 `game_folder` / `active_importer` / `enabled_importers` /
    `extra_libraries` / 签名**全都无处落地** —— 这正是空环境「注入失败」的最后一环
    （2026-09-29 端到端实测：`写入 XXMI 注入库失败: 找不到 XXMI Launcher Config.json`）。

    做法：**先用 runas 把它拉起来一次**（XXMI 的 exe 要求管理员），等它把配置写出来
    （通常几秒），再把进程收掉；随后 `ensure_injections()` 才写我们的字段。
    本机 `ConsentPromptBehaviorAdmin=0`（直接提升、不弹 UAC），所以这一步无人值守也能过。
    """
    launcher_path = config.xxmi_launcher_path
    if launcher_path is None or not Path(launcher_path).is_file():
        return {"ok": False, "created": False, "message": "未配置 XXMI Launcher"}
    cfg_path = reshade_integration.xxmi_config_path(launcher_path)
    if cfg_path is not None and cfg_path.is_file():
        return {"ok": True, "created": False, "message": "XXMI 配置已存在"}
    if log:
        log("XXMI 还没有配置文件（它首次运行才会生成），先启动一次让它生成…")
    image_name = Path(str(launcher_path)).name
    pids_before = _image_pids(image_name)
    try:
        _spawn_elevated(config, str(launcher_path), str(Path(launcher_path).parent), show_window=0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "created": False, "message": f"启动 XXMI 失败：{exc}"}
    # ★ 注入现场时间线·**时机 2／5：XXMI 拉起后**（用户 2026-10-05 要求）。
    #   此刻 XXMI 已经在跑，而**它自己也会补写配置** —— 这正是"我们写好的注入库被第三方
    #   改掉"的窗口，所以这一张照片是后面所有点里最不能省的一张。
    try:
        from . import injecttrace

        injecttrace.record(config, phase="xxmi-started", note="拉起 XXMI 生成配置",
                           log=log or (lambda message: None))
    except Exception as exc:  # noqa: BLE001 —— 取证失败绝不能影响启动
        if log:
            log(f"注入时间线: 记录失败（忽略）: {exc}")
    deadline = time.time() + max(5, int(wait_seconds))
    created_path: Path | None = None
    while time.time() < deadline:
        # ⚠️ 必须**每轮重新计算**路径：`xxmi_config_path()` 只在文件存在时才返回路径，
        #    一开始它必然返回 None —— 只算一次就永远等不到（第一次实测"等了 40s 没等到"
        #    就是这个原因，而配置其实早在第 ~20 秒就写好了）。
        created_path = reshade_integration.xxmi_config_path(launcher_path)
        if created_path is not None and created_path.is_file():
            break
        time.sleep(1.0)
    # 收掉这次"只为生成配置"而拉起的 XXMI。它是**提权进程**，普通权限的 taskkill 杀不掉
    # （实测：进程一直留着），所以同样走 runas。
    #
    # 但**只能杀我们自己拉起的那一个**：原先用 `taskkill /IM <映像名>`，会把用户
    # 自己刚打开的 XXMI 一起杀掉（可能丢它还没落盘的配置）。这里改成 PID 差分
    # （2026-10-01 修 ⑨）。
    try:
        import ctypes

        cwd = str(Path(launcher_path).parent)
        started: set[int] = set()
        # XXMI 是**提权启动**的，进程可能要几秒才出现在列表里 —— 先给它一点时间再下结论
        for _ in range(6):                     # 最多约 3 秒
            started = _image_pids(image_name) - pids_before
            if started:
                break
            time.sleep(0.5)
        if started:
            for pid in sorted(started):
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", "taskkill", f"/PID {pid} /F", cwd, 0,
                )
        else:
            # ⚠️⚠️ **绝不回退到 `taskkill /IM <映像名>`**（2026-10-04 修的 U2）。
            # 那个写法会把**用户自己刚打开的** XXMI 一起杀掉（可能丢掉它还没落盘的配置），
            # 而这里的注释一直写着"只杀我们自己拉起的那一个" —— 实现与承诺正好相反。
            # 抓不到就如实说明、让用户自己关：误杀别人的进程比"多开着一个窗口"严重得多。
            if log:
                log(f"没能抓到自己拉起的 {image_name}（可能启动较慢）—— "
                    f"若 XXMI 窗口还开着，请手动关掉它，配置已经写好了。")
        time.sleep(2.0)
    except Exception:  # noqa: BLE001
        pass
    if created_path is not None and created_path.is_file():
        return {"ok": True, "created": True,
                "message": ("第一次启动：已临时拉起 XXMI 生成它的配置文件，随后已关闭。"
                            "**请再点一次「一键启动」**，这一次才会真正进入游戏。")}
    return {"ok": False, "created": False,
            "message": f"等了 {wait_seconds}s 仍没等到 XXMI 写出配置"}


def ensure_xxmi_game_folder(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把游戏目录写进 XXMI 配置的 `Importers.EFMI.Importer.game_folder`。

    **不做这件事，XXMI 界面里就不会出现终末地的启动按钮** —— 实测空环境下该字段是空
    字符串（2026-09-29），XXMI 既搜不到游戏、也没人告诉它路径，于是"没有启动按钮"。
    顺带把 `Launcher.active_importer` 设为 `EFMI`（本方案跑的就是 EFMI / 服装 Mod）。
    以及 **`Launcher.enabled_importers`**（XXMI 界面只显示"已启用"的 importer，
    这个列表为空时连启动按钮都不出现，而且 XXMI 启动后还会把 active_importer 重置回
    `"XXMI"` —— 2026-09-29 对照两份配置才定位到）。

    **2026-10-01 修的两处**（一份真实诊断包暴露）：
    * 定位不到游戏目录时**原先完全静默**（调用方连 message 都不记）→ 用户与排查者都
      看不到"为什么 XXMI 里没有启动按钮"；现在失败会写日志并且 message 交给调用方
      放进自检 warnings。
    * 定位成功后**把 `config.game_exe` 回填**（仅当它原本为空 —— 不覆盖用户设置），
      这样后续所有 `detect_game_dir` 直接命中，不必再扫盘/依赖 XXMI 配置。
    """
    def _log(message: str) -> None:
        """可选日志回调（launcher 里没有全局 _log，就地包一层，失败静默）。"""
        if log is None:
            return
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass

    launcher_path = config.xxmi_launcher_path
    if launcher_path is None:
        message = "未配置 XXMI Launcher，跳过「让 XXMI 指向游戏目录」"
        _log(f"XXMI 游戏目录: {message}")
        return {"ok": False, "changed": False, "message": message}
    # ⚠ **XXMI 正在跑的时候写配置等于白写**（2026-10-01 现场实证）：XXMI 退出时会把自己
    #   内存里的整份配置写回去（它的日志就是 `ApplicationEvents.Close` → `Saving config...`），
    #   我们在它运行期间写的 `game_folder` / `enabled_importers` / `active_importer`
    #   会被一并覆盖 —— 用户看到的现象是"重下 XXMI 之后终末地的启动按钮没了"。
    #   所以这里宁可**先不写**并说清怎么办，也不做这种看着成功、实际被冲掉的写入。
    if xxmi_process_running(config):
        message = ("XXMI 正开着 —— 它退出时会用自己内存里的状态覆盖配置文件，现在写也会被冲掉。"
                   "请先关掉 XXMI，再点一次「一键启动」（或「检查/修复完整性」）即可自动补好。")
        _log(f"WARN XXMI 游戏目录: {message}")
        return {"ok": False, "changed": False, "message": message, "xxmi_running": True}
    game_dir = reshade_integration.detect_game_dir(config)
    if game_dir is None:
        message = ("未定位到游戏目录，所以没能把游戏路径写进 XXMI 配置"
                   "（影响：XXMI 界面里可能不显示终末地的启动按钮）。"
                   "请到设置页把「游戏启动器」或「游戏 exe」填上，"
                   "或在 XXMI 里手动选一次游戏目录后重试。")
        _log(f"WARN XXMI 游戏目录: {message}")
        return {"ok": False, "changed": False, "message": message}
    # 反推/探测成功后回填 config.game_exe —— **只在原本为空时写**，绝不覆盖用户填的值
    # （2026-09-30 的 issue #4 就是"补齐流程覆盖了用户设置"造成的，这个坑不再踩）。
    exe = Path(game_dir) / "Endfield.exe"
    if exe.is_file() and not str(getattr(config, "game_exe", "") or "").strip():
        config.game_exe = str(exe)
        _log(f"XXMI 游戏目录: 已记住游戏位置 {exe}")
        try:
            config.save()
        except OSError:
            pass
    config_path = reshade_integration.xxmi_config_path(launcher_path)
    if config_path is None or not config_path.is_file():
        message = "找不到 XXMI 配置文件（它由 XXMI 首次运行时生成）"
        _log(f"WARN XXMI 游戏目录: {message}")
        return {"ok": False, "changed": False, "message": message}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "changed": False, "message": f"读取 XXMI 配置失败：{exc}"}
    if not isinstance(data, dict):
        return {"ok": False, "changed": False, "message": "XXMI 配置格式异常"}

    changed: list[str] = []
    importer = data.setdefault("Importers", {}).setdefault("EFMI", {}).setdefault("Importer", {})
    if str(importer.get("game_folder") or "") != str(game_dir):
        importer["game_folder"] = str(game_dir)
        changed.append("Importers.EFMI.Importer.game_folder")
    launcher_block = data.setdefault("Launcher", {})
    if launcher_block.get("active_importer") != "EFMI":
        launcher_block["active_importer"] = "EFMI"
        changed.append("Launcher.active_importer")
    # **最关键的一项**：XXMI 界面只显示「已启用」的 importer —— 这个列表为空时，
    # 界面上根本不会出现终末地的启动按钮（2026-09-29 对照两份配置才发现：能用的那份是
    # `["EFMI"]`，失败的那份是 `[]`）。而且它为空时 XXMI 启动后还会把 active_importer
    # 重置回 `"XXMI"`，连我们写进去的值都保不住 —— 前两轮修了 dll 路径和 game_folder
    # 却仍然"没有启动按钮"，原因就在这里。
    enabled = launcher_block.get("enabled_importers")
    if not isinstance(enabled, list):
        enabled = []
    if "EFMI" not in enabled:
        launcher_block["enabled_importers"] = sorted({*enabled, "EFMI"})
        changed.append("Launcher.enabled_importers")
    if not changed:
        return {"ok": True, "changed": False, "game_dir": str(game_dir),
                "message": f"XXMI 已指向游戏目录（{game_dir.name}）"}
    try:
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "changed": False, "message": f"写入 XXMI 配置失败：{exc}"}
    # **写完必须回读校验**（2026-10-01 现场教训：写入"成功"但用户那头配置里还是空的 ——
    # 「重下 XXMI 之后终末地的启动按钮没了」。宁可当场报出来，也不要写了个寂寞）。
    try:
        back = json.loads(config_path.read_text(encoding="utf-8"))
        back_importer = ((back.get("Importers") or {}).get("EFMI") or {}).get("Importer") or {}
        back_launcher = back.get("Launcher") or {}
        back_enabled = back_launcher.get("enabled_importers") or []
        if (str(back_importer.get("game_folder") or "") != str(game_dir)
                or back_launcher.get("active_importer") != "EFMI"
                or "EFMI" not in (back_enabled if isinstance(back_enabled, list) else [])):
            _log("WARN XXMI 游戏目录: 写进去的内容回读不一致（可能有 XXMI 实例正在运行并覆盖配置）")
            return {
                "ok": False,
                "changed": True,
                "game_dir": str(game_dir),
                "message": ("已尝试写入 XXMI 配置，但回读不一致 —— 多半是有 XXMI 实例正开着"
                            "（它退出时会覆盖）。请关掉 XXMI 再点一次「一键启动」。"),
            }
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "changed": True, "message": f"回读 XXMI 配置失败：{exc}"}
    return {"ok": True, "changed": True, "game_dir": str(game_dir),
            "message": f"已让 XXMI 指向游戏目录（{', '.join(changed)}）"}


def restore_xxmi_extra_libraries(config: AppConfig) -> dict[str, Any]:
    launcher_path = config.xxmi_launcher_path
    if launcher_path is None:
        return {"ok": False, "message": "XXMI Launcher path is not configured"}
    config_path = reshade_integration.xxmi_config_path(launcher_path)
    if config_path is None:
        return {"ok": False, "message": "XXMI Launcher Config.json was not found"}
    backup = config_path.with_suffix(config_path.suffix + ".mc.bak")
    if not backup.is_file():
        return {"ok": False, "message": "no XXMI config backup found"}
    shutil.copy2(backup, config_path)
    return {"ok": True, "config_path": str(config_path), "backup": str(backup)}

def enable_anti_cheat_safe_mode(config: AppConfig) -> dict[str, Any]:
    """Move ReShade out of the game directory and inject it through XXMI instead.

    This is intentionally explicit and reversible.  It removes only
    EndfieldModController's integration files, renames the game-directory ReShade
    proxies to ``*.endfieldmodcontroller.disabled``, copies the existing ReShade DLL to
    ``runtime/reshade/ReShade64.dll`` when possible, and switches the launch mode
    to ``xxmi_extra`` so XXMI injects ReShade at process start.
    """
    actions: list[str] = []
    warnings: list[str] = []

    removed = reshade_integration.remove_existing_reshade(config)
    actions.extend(f"removed {item}" for item in removed.get("removed", []))
    actions.extend(f"restored {item}" for item in removed.get("restored", []))

    info = reshade_integration.detect_existing_reshade(config)
    adopted_ok = False
    if info is not None:
        try:
            adopted = reshade_integration.adopt_game_reshade_dll(config, info)
            config.reshade_dll = config.store_path(adopted["target"])
            config.save()
            adopted_ok = True
            actions.append(f"adopted ReShade 6.x from {adopted['source']}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"复制游戏目录 ReShade 失败: {exc}")
        if adopted_ok:
            try:
                disabled = reshade_integration.disable_game_reshade_proxies(config, info)
                for entry in disabled.get("disabled", []):
                    actions.append(f"disabled {entry['original']} -> {entry['disabled']}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"重命名游戏目录 ReShade 代理失败: {exc}")
        else:
            warnings.append("未能从游戏目录复制 ReShade，已保留 dxgi.dll / d3d12.dll 原样。请手动准备 ReShade 6.8 Addon 后再试。")
    else:
        warnings.append("未检测到游戏目录 ReShade，跳过复制和代理重命名。")

    if not config.reshade_dll_path or not config.reshade_dll_path.is_file():
        try:
            from . import reshade
            downloaded = reshade.download_reshade(config.reshade_runtime_path)
            config.reshade_dll = config.store_path(downloaded["dll"])
            config.save()
            actions.append(f"downloaded ReShade {downloaded['version']}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"下载 ReShade 6.8 Addon 失败: {exc}")

    # 记下"进安全模式之前的注入方式"（U4：还原时恢复它，而不是硬写 external）
    _remember_injection(config)
    config.reshade_injection = "xxmi_extra"
    config.save()
    try:
        extra = configure_xxmi_extra_libraries(config)
        actions.append(f"XXMI extra_libraries -> {extra.get('extra_libraries')}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"配置 XXMI extra_libraries 失败: {exc}")

    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "safe_mode": True,
        "reshade_injection": config.reshade_injection,
        "reshade_dll": str(config.reshade_dll_path or ""),
    }


def restore_global_reshade_elevated(config: AppConfig) -> dict[str, Any]:
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    apps = Path(program_data) / "ReShade" / "ReShadeApps.ini"
    backup = Path(str(apps) + ".endfieldmodcontroller.bak")
    if not backup.is_file():
        return {"ok": True, "restored": []}
    script = config.runtime_path / "restore_global_reshade.cmd"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "@echo off" + chr(10)
        + "setlocal" + chr(10)
        + "set \"APPS=%ProgramData%\\ReShade\\ReShadeApps.ini\"" + chr(10)
        + "if exist \"%APPS%.endfieldmodcontroller.bak\" copy /Y \"%APPS%.endfieldmodcontroller.bak\" \"%APPS%\" >nul" + chr(10)
        + "endlocal" + chr(10),
        encoding="utf-8",
    )
    _spawn_elevated(config, str(script), str(script.parent), show_window=0)
    return {"ok": True, "restored": [str(apps)]}


# ⚠️ 「进安全模式 / d3d12 代理模式**之前**用的注入方式」记在各自的 manifest 里，
# 还原时**恢复原值** —— 不许硬写成 `external`（2026-10-04 修的 U4）。
# 用户原本可能是 `xxmi_extra`（推荐）或 `none`；硬写 `external` 会让设置页显示的注入方式
# 与他自己的选择不符，后续 `panel_base_dirs` / 接管判断也跟着偏（状态机残留）。
# 存的是**第一次**进模式之前的值（`setdefault`），重复进模式不会把"我们改过的值"当成原值。
_INJECTION_PREV_KEY = "prev_reshade_injection"


def _remember_injection(config: AppConfig) -> None:
    """把当前的 `reshade_injection` 记进 safe_mode / d3d12 两份 manifest（存在哪份就记哪份）。"""
    current = str(getattr(config, "reshade_injection", "") or "")
    for reader, writer in (
        (reshade_integration._read_safe_mode_manifest, reshade_integration._write_safe_mode_manifest),
        (reshade_integration._read_d3d12_swap_manifest, reshade_integration._write_d3d12_swap_manifest),
    ):
        try:
            data = reader(config)
            if not data:
                continue          # 这份 manifest 还没建（这次不是走那条路）
            data.setdefault(_INJECTION_PREV_KEY, current)
            writer(config, data)
        except Exception:  # noqa: BLE001 —— 记录失败不该挡住安全模式本身
            pass


def _recall_injection(config: AppConfig, *, default: str) -> str:
    """读回"进模式之前的注入方式"；没有记录就返回 `default`（与旧行为一致）。"""
    for reader in (reshade_integration._read_safe_mode_manifest,
                   reshade_integration._read_d3d12_swap_manifest):
        try:
            value = str((reader(config) or {}).get(_INJECTION_PREV_KEY) or "").strip()
        except Exception:  # noqa: BLE001
            value = ""
        if value:
            return value
    return default


def restore_anti_cheat_safe_mode(config: AppConfig) -> dict[str, Any]:
    actions: list[str] = []
    warnings: list[str] = []
    # ⚠️ **必须在 `clear_safe_mode_manifest` 之前读**（它会把 manifest 删掉）
    prev_injection = _recall_injection(config, default="external")
    restored = reshade_integration.restore_game_reshade_proxies(config)
    actions.extend(f"restored {item}" for item in restored.get("restored", []))
    warnings.extend(restored.get("errors", []))
    xxmi = restore_xxmi_extra_libraries(config)
    if xxmi.get("ok"):
        actions.append(f"restored {xxmi.get('config_path')}")
    else:
        warnings.append(str(xxmi.get("message")))
    reshade_integration.clear_safe_mode_manifest(config)
    global_restore = restore_global_reshade_elevated(config)
    actions.extend(f"restored global ReShade apps: {item}" for item in global_restore.get("restored", []))
    if not global_restore.get("ok", True):
        warnings.append(str(global_restore.get("message") or "restore global ReShade apps failed"))
    config.reshade_injection = prev_injection
    config.save()
    actions.append(f"注入方式恢复为 {prev_injection}")
    return {"ok": not warnings, "actions": actions, "warnings": warnings}


def enable_d3d12_proxy_mode(config: AppConfig) -> dict[str, Any]:
    """Use the game-directory ReShade as ``d3d12.dll`` and hide ``dxgi.dll``.

    This matches the common Endfield workaround: the game dynamically loads
    ``d3d12.dll`` even in its DX11 mode, while the anti-cheat message specifically
    complains about the ``dxgi`` module name.
    """
    actions: list[str] = []
    warnings: list[str] = []

    if reshade_integration.safe_mode_active(config):
        restored = restore_anti_cheat_safe_mode(config)
        actions.extend(restored.get("actions", []))
        warnings.extend(restored.get("warnings", []))

    info = reshade_integration.detect_existing_reshade(config)
    if info is None:
        raise LaunchError("没有检测到游戏目录 ReShade，无法切换 dxgi→d3d12 模式。")
    try:
        swapped = reshade_integration.swap_dxgi_to_d3d12(config, info)
        actions.append(f"disabled {swapped.get('disabled_dxgi')}")
        actions.append(f"kept ReShade d3d12 proxy: {swapped.get('d3d12')}")
    except Exception as exc:  # noqa: BLE001
        raise LaunchError(f"切换 dxgi→d3d12 失败: {exc}") from exc

    # 同上（U4）：切 d3d12 代理模式之前先把原注入方式记下来
    _remember_injection(config)
    config.reshade_injection = "none"
    config.save()

    try:
        integration = reshade_integration.deploy_existing_reshade(config, controller_dir=config.controller_dir)
        actions.extend(f"deployed {entry['path']}" for entry in integration.get("files", []))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"写入游戏目录 ReShade 集成文件失败: {exc}")

    return {
        "ok": not warnings,
        "actions": actions,
        "warnings": warnings,
        "d3d12_proxy_mode": True,
        "reshade_injection": config.reshade_injection,
    }


def restore_d3d12_proxy_mode(config: AppConfig) -> dict[str, Any]:
    actions: list[str] = []
    warnings: list[str] = []
    # 同 U4：读回"进这个模式之前的注入方式"（在 dxgi 还原把 manifest 用掉之前读）
    prev_injection = _recall_injection(config, default="external")
    restored = reshade_integration.restore_dxgi_from_d3d12(config)
    actions.extend(restored.get("actions", []))
    warnings.extend(restored.get("errors", []))
    removed = reshade_integration.remove_existing_reshade(config)
    actions.extend(f"removed {item}" for item in removed.get("removed", []))
    actions.extend(f"restored {item}" for item in removed.get("restored", []))
    xxmi = restore_xxmi_extra_libraries(config)
    if xxmi.get("ok"):
        actions.append(f"restored {xxmi.get('config_path')}")
    else:
        warnings.append(str(xxmi.get("message")))
    global_restore = restore_global_reshade_elevated(config)
    actions.extend(f"restored global ReShade apps: {item}" for item in global_restore.get("restored", []))
    if not global_restore.get("ok", True):
        warnings.append(str(global_restore.get("message") or "restore global ReShade apps failed"))
    config.reshade_injection = prev_injection
    config.save()
    actions.append(f"注入方式恢复为 {prev_injection}")
    return {"ok": not warnings, "actions": actions, "warnings": warnings}


def _set_d3dx_loader_target(d3dx_ini: Path, target: str) -> bool:
    """Keep [Loader] target pointing at the real Endfield executable.

    The injected EFMI d3d11.dll validates this value against the process it was
    loaded into.  Updating it outside the loader hot path avoids the old
    QueryFullProcessImageName stall while still making moved installations work.
    """
    if not d3dx_ini.is_file() or not target:
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    in_loader = False
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_loader = stripped.lower() == "[loader]"
        if in_loader and stripped.lower().startswith("target") and "=" in stripped and not replaced:
            out.append(f"target = {target}")
            replaced = True
            continue
        out.append(line)
    if not replaced:
        try:
            index = next(i for i, line in enumerate(out) if line.strip().lower() == "[loader]")
        except StopIteration:
            return False
        out.insert(index + 1, f"target = {target}")
    _write_ini_atomic(d3dx_ini, chr(10).join(out) + chr(10))
    return True


def build_launch_env(config: AppConfig, *, existing_reshade: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    if existing_reshade:
        # Let the existing game-directory ReShade keep its own base path.
        env.pop("RESHADE_BASE_PATH_OVERRIDE", None)
        env.pop("RESHADE_DISABLE_LOADING_CHECK", None)
    else:
        env["RESHADE_BASE_PATH_OVERRIDE"] = str(config.reshade_runtime_path)
        env["RESHADE_DISABLE_LOADING_CHECK"] = "1"
    env["ENDFIELDMODCONTROLLER_USER_INI"] = str(config.user_ini_path)
    return env


def build_launch_command(config: AppConfig, *, start_game: bool = False) -> list[str]:
    launcher = config.xxmi_launcher_path
    if launcher is None:
        raise LaunchError("XXMI Launcher path is not configured")
    if not start_game:
        # Opening XXMI without --xxmi only shows the launcher window.  Passing
        # --xxmi EFMI makes XXMI start the game immediately, which is not what
        # the one-click preparation flow promises.
        return [str(launcher)]
    game_exe = config.game_exe_path
    # Explicit "start game" keeps the normal XXMI window visible.  The
    # headless --nogui form is still available through core.build_xxmi_launch_command.
    return core.build_xxmi_launch_command(launcher, game_exe, nogui=False)


def launch_official_gui(config: AppConfig) -> dict[str, Any]:
    """Open the official XXMI Launcher GUI with the EFMI package selected.

    This deliberately avoids EndfieldModController's custom 3DMigoto loader,
    bootstrap DLL, ReShade proxy deployment and game-directory edits.  It only
    stages the selected mods into the official XXMI/EFMI ``Mods`` folder and
    starts the official XXMI Launcher window; the user then uses XXMI's own
    EFMI interface to start the game.
    """
    config.ensure_dirs()
    # Prevent an old custom loader from injecting a second 3DMigoto proxy.
    try:
        _stop_locked_files_processes(config)
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"清理旧 loader 失败（继续启动官方 XXMI）: {exc}")

    # 先把「手动放进 Mods 目录的 Mod」收编进来，再做 staging。
    #
    # 用户需求（原话）：「手动放进去的和库里的进行比对，如果库里已有，就在 UI 中显示
    # 那个开启，库里没有就把它放到库里，然后显示开启」。
    # 时机很关键：必须在下面对 Mods 的整目录清空**之前**执行，否则手动放的 Mod 会被
    # 直接清掉。收编后它们进入 selected_mods，本次 staging 就会正常生成 MC_* 产物。
    #
    # ★ 2026-10-06 用户要求把它**做成开关**（默认开）：「设置加个按钮，xxmi 自动清理
    #   非管理器插件，默认开，如果 xxmi 中有其他 mod，就反向同步到库里，然后直接删掉」。
    #   关掉 ⇒ `Mods\` 里的外来目录**原样保留**（给"我有特殊摆法"的用户留退路）。
    if not bool(getattr(config, "auto_adopt_manual_mods", True)):
        _append_log(config, "«自动收编 XXMI 里的外来 Mod» 已关闭：Mods 目录里的外来目录保持原样")
    else:
        try:
            synced = activation.import_manual_mods(config, log=lambda m: _append_log(config, m))
            if synced.get("found"):
                detail = (f"手动 Mod 同步: 收进库 {len(synced['imported'])} 个、"
                          f"库中已有 {len(synced['matched'])} 个")
                if synced.get("selected_added"):
                    detail += f"；已在界面勾选: {', '.join(synced['selected_added'])}"
                _append_log(config, detail)
        except activation.LibraryGuardError as exc:
            # 「不要动用户的 Mod 库」（用户 2026-10-01 硬规则）：staging 与库重叠时拒绝执行。
            _append_log(config, f"同步手动 Mod 已拒绝（保护 Mod 库）: {exc}")
        except Exception as exc:  # noqa: BLE001
            _append_log(config, f"同步手动 Mod 失败（已跳过，继续启动）: {exc}")

    # Mods 目录由控制器全权管理：最终只放"用户在 Mod 库勾选的那些"。
    # stage_and_prepare 会先清空整个 Mods 里的 `MC_*`（用户手动放的照样保留），再按选择生成。
    #
    # ⚠️ **一律 stage**（2026-10-02 改）：以前"没勾选 / 皮肤开关关着就**跳过** staging"，
    #    结果是**上一次的 `MC_*` 留在 Mods 里照样被 EFMI 加载**（幽灵 Mod）。现在统一传
    #    `Config.effective_selected_mods` —— 皮肤总开关关着 → 空 → 直接清空 Mods；
    #    一个都没勾 → 同样清空。
    selected_now = config.effective_selected_mods
    if not getattr(config, "efmi_injection", True):
        _append_log(config, "皮肤 Mod 已关闭：EFMI 照常注入，但不加载任何皮肤（Mods 将清空）")
    try:
        activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=selected_now,
            hotkey_takeover=resolve_hotkey_takeover(config, config.controller_dir),
            allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
            prefer_internal_dependencies=bool(
                getattr(config, "prefer_internal_dependencies", True)
            ),
        )
        if selected_now:
            # 每次 staging 之后都刷新一次面板与动作清单（面板读的是 base 目录里的
            # actions.tsv —— 不刷新的话它显示的是上一轮选中的 Mod）。
            reshade_integration.deploy_panel(
                config, config.controller_dir, log=lambda m: _append_log(config, m)
            )
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"暂存所选 mod 失败: {exc}")

    # 拉起 XXMI **之前最后一刻**再做两件事（2026-10-01 现场加固，对应 memory 0mup0ktzd
    # 记的"写早了会被 XXMI 退出时覆盖"）：
    #   ① 兜住 Launcher 路径：留空/被删 → 找内置 → 没有就自动下载（用户明确要求）；
    #   ② 把 game_folder / active_importer / enabled_importers 再确认一次 ——
    #      顺序必须是「我们写 → 它启动 → 它保存」，反了就等于没写。
    try:
        available = ensure_xxmi_available(config)
        if available.get("changed"):
            _append_log(config, f"拉起 XXMI 前: {available.get('message')}")
        elif not available.get("ok"):
            _append_log(config, f"WARN 拉起 XXMI 前: {available.get('message')}")
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"拉起 XXMI 前准备 Launcher 失败（继续）: {exc}")
    try:
        folder_state = ensure_xxmi_game_folder(config, log=lambda m: _append_log(config, m))
        if folder_state.get("changed"):
            _append_log(config, f"拉起 XXMI 前补写配置: {folder_state.get('message')}")
        elif not folder_state.get("ok"):
            _append_log(config, f"WARN 拉起 XXMI 前: {folder_state.get('message')}")
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"拉起 XXMI 前补写 XXMI 配置失败（继续）: {exc}")

    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        raise LaunchError(
            "找不到可用的 XXMI Launcher。到「依赖」页点「自动安装/更新」装好内置 XXMI，"
            "或在设置页填上你自己的 XXMI Launcher 路径。"
        )

    # 用 os.startfile 启动 = **字面意义上的"双击"**：Windows 走 shell 关联，
    # 工作目录 / 权限 / 环境变量全部按系统默认来，不再受本 Python 进程影响。
    # 之前用 subprocess / ShellExecuteW 时，cwd、CREATE_NO_WINDOW、
    # os.environ.copy() 都会把控制器的进程属性带过去，实测会让游戏起不来。
    _append_log(config, f"以系统默认方式启动 XXMI: {launcher}")
    try:
        os.startfile(str(launcher))  # type: ignore[attr-defined]
        process = None
    except OSError as exc:  # noqa: PERF203
        if getattr(exc, "winerror", None) == 740:
            raise LaunchError(
                "XXMI Launcher 需要管理员权限。请关闭本控制器，右键 run.vbs / run.bat 选"
                "「以管理员身份运行」后重试。"
            ) from exc
        raise
    # 启动崩溃监控：游戏是 XXMI 拉起来的，这里起个后台线程等进程出现、跟踪到退出，
    # 自动把崩溃现场（CrashSight / 崩溃栈 / 模块清单 / 注入快照）写成报告。
    try:
        from . import crashwatch

        crashwatch.start_watch(config, log=lambda msg: _append_log(config, msg))
    except Exception as exc:  # noqa: BLE001
        _append_log(config, f"启动崩溃监控失败: {exc}")
    return {
        "mode": "official_xxmi_gui",
        "command": [str(launcher)],
        "pid": None,
        "elevated": False,
        "message": "已以系统默认方式（等同双击）打开 XXMI Launcher；请在它的 EFMI 界面里启动游戏。",
    }



def install_missing_dependencies(config: AppConfig) -> list[dict[str, Any]]:
    """Install dependencies required by the current selection but not present locally."""
    mods = core.scan_library(config.library_path, config.staging_mods_path)
    selected = set(config.selected_mods or [])
    if selected:
        mods = [mod for mod in mods if mod.id in selected or mod.is_dependency]
    required = core.collect_required_dependency_names(mods)
    manifest = dependencies.load_manifest(config.dependency_manifest_path)
    missing = dependencies.select_missing_dependencies(manifest, config.library_path, required)
    if not missing:
        return []
    return [result.__dict__ for result in dependencies.update_all(missing, config.library_path, dry_run=False, enabled_only=False)]


def _append_log(config: AppConfig, message: str) -> None:
    diagnostics.log_event(config, message, category="launch")


_ENV_KEEP = {
    "PATH", "SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT",
    "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramData",
    "ProgramFiles", "ProgramFiles(x86)", "CommonProgramFiles", "CommonProgramFiles(x86)",
    "CommonProgramW6432", "ProgramW6432", "PUBLIC", "ALLUSERSPROFILE",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "OS", "COMPUTERNAME",
    "USERNAME", "USERDOMAIN", "USERDOMAIN_ROAMINGPROFILE",
    "HOMEDRIVE", "HOMEPATH", "LOGONSERVER", "SESSIONNAME",
}
# 不该出现在游戏进程 PATH 里的开发/工具链目录
_ENV_PATH_BLOCK = (
    "windowsapps", "powershell", "\\python", "python3", "scoop", "\\git",
    "nodejs", "vmware", "\\java", "dotnet", "sql server", "msys", "cygwin",
)
# Windows 环境变量名大小写不敏感，比较前统一小写（否则会误剔 ComSpec/ProgramData 等）
_ENV_KEEP_LOWER = {k.lower() for k in _ENV_KEEP}


def clean_launch_env() -> dict[str, str]:
    """给「启动启动器/游戏」用的最小环境。

    控制器自己是从 Python（甚至从别的 shell）启动的，它继承的一堆变量
    （PYTHON*、DSH_*、GIT_*、各种专业软件变量，以及在 PATH 最前面的
    PowerShell/工具链目录）会被 XXMI 继承、再传给游戏进程，可能干扰游戏的
    DLL 查找与初始化。这里只保留系统必需变量，并把工具链目录从 PATH 剔除。
    """
    env = {k: v for k, v in os.environ.items() if k.lower() in _ENV_KEEP_LOWER}
    raw_path = os.environ.get("PATH", "")
    parts = [
        p for p in raw_path.split(os.pathsep)
        if p and not any(bad in p.lower() for bad in _ENV_PATH_BLOCK)
    ]
    if parts:
        env["PATH"] = os.pathsep.join(parts)
    return env


def _spawn_command(config: AppConfig, command: list[str], cwd: str, env: dict[str, str], show_window: int = 1):
    """Start a command, requesting UAC when WinError 740 occurs.

    **不要给 GUI 启动器（XXMI / 官方启动器）加 CREATE_NO_WINDOW**：
    它们随后会用 CreateProcess 拉起游戏，而"无控制台"的父进程会让游戏继承
    异常的标准句柄（stdout/stderr 无效），Unity 游戏在这种环境下可能直接
    进不去（2026-09-27 实测：同一份 XXMI2，双击能进、被本函数加了这个标志
    启动就崩）。只在启动纯控制台工具时才隐藏窗口。
    """
    creationflags = 0
    try:
        name = Path(command[0]).name.lower()
    except Exception:  # noqa: BLE001
        name = ""
    console_tools = ("taskkill", "where", "cmd.exe", "7z.exe", "7za.exe", "tar.exe")
    if os.name == "nt" and name in console_tools:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            creationflags=creationflags,
        )
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 740:
            # 不要在这里自动 runas 提权：UAC 提升后的进程工作目录常被重置为
            # C:\Windows\System32（ShellExecuteW 的 lpDirectory 经常不生效），
            # 而 XXMI 按自身工作目录找资源，cwd 一错游戏就进不去。
            # 正确做法是让用户「以管理员身份」启动本控制器，这样 XXMI 由普通
            # CreateProcess 启动，cwd 正确。
            raise LaunchError(
                "XXMI Launcher 需要管理员权限。请关闭本控制器，右键 run.vbs / run.bat 选"
                "「以管理员身份运行」后重试 —— 自动提权会让它丢失工作目录，导致游戏进不去。"
            ) from exc
        raise

def _elevated_target_is_trusted(config: AppConfig, exe: Path) -> str:
    """提权执行前的白名单校验：返回空串 = 放行，否则返回拒绝原因（2026-10-04 修的 U1）。

    **为什么必须有**：`_spawn_elevated()` 会以**管理员身份**把它拿到的路径执行起来
    （`ShellExecuteW("runas", …)`），而那个路径来自 `config.xxmi_launcher_path`
    —— 用户手填、或我们自动下载解压出来的。触发它的也不只是「点按钮启动 XXMI」：
    `repair_integrity` → `bootstrap_xxmi_config` 这条**常规修复路径**同样会走这里。
    只要那个路径被换成别的东西，就等于**以管理员执行任意程序**。

    允许的两类（覆盖所有正常用法）：
      ① 内置 runtime 里的 XXMI（我们自己下载解压、随包分发的那份）；
      ② 恰好等于 `config.xxmi_launcher_path` 的路径（用户显式选择的安装位置）。
    其它一律拒绝并说清原因 —— 我们要的是"提权只针对用户自己选定的那个启动器"。
    """
    from . import fsutil

    if not exe.is_file():
        return f"目标不存在：{exe}"
    if exe.suffix.lower() != ".exe":
        return f"只允许管理员启动 .exe，收到的是 {exe.name}"
    try:
        if fsutil.is_within(config.builtin_runtime_path, exe):
            return ""
    except Exception:  # noqa: BLE001
        pass
    configured = config.xxmi_launcher_path
    try:
        if configured is not None and Path(configured).resolve() == exe.resolve():
            return ""
    except OSError:
        pass
    return (f"这个路径既不是内置 XXMI、也不是你配置里的启动器：{exe}\n"
            f"（配置的是：{configured}）—— 出于安全，未以管理员身份启动它。")


def _spawn_elevated(config: AppConfig, exe: str, cwd: str, show_window: int = 0) -> None:
    """Run an executable elevated without a console window via ShellExecuteW.

    ⚠️ 执行前先过 `_elevated_target_is_trusted()` 的白名单（见那边的说明）。
    """
    if os.name != "nt":
        subprocess.Popen([exe], cwd=cwd)
        return
    target = Path(str(exe))
    # 我们自己生成的辅助脚本（固定名字、固定内容，见各自的生成处）天然落在白名单外
    # —— 尤其是 `_run_loader.cmd`，它在**loader 目录**里（可能是外部 XXMI 的位置）。
    # 所以按**文件名**放行，而不是按目录。
    _OUR_SCRIPTS = {"stop_migoto_processes.cmd", "restore_global_reshade.cmd", "_run_loader.cmd"}
    is_our_script = target.suffix.lower() in {".cmd", ".bat"} and target.name in _OUR_SCRIPTS
    if not is_our_script:
        reason = _elevated_target_is_trusted(config, target)
        if reason:
            _append_log(config, f"拒绝以管理员身份启动：{reason}")
            raise LaunchError(f"拒绝以管理员身份启动 —— {reason}")
    import ctypes
    _append_log(config, f"正在以管理员权限启动: {exe}")
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, None, cwd, show_window)
    if result <= 32:
        raise LaunchError(f"请求管理员权限失败，ShellExecuteW 返回 {result}")


GAME_PROCESS_NAMES = ("Endfield.exe",)


def running_game_processes() -> list[str]:
    """当前正在运行的终末地进程。"""
    return _running_process_names(GAME_PROCESS_NAMES)


def check_game_multi_instance(config: AppConfig) -> dict[str, Any]:
    """防多开：终末地已经在跑时给出明确结论（不抛异常，交给调用方决定要不要拦）。

    为什么要拦：两个游戏实例同时被注入，ReShade/Mod 会互相抢 D3D 设备与 Mods 目录，
    表现为随机崩溃或"Mod 莫名其妙不生效"，而且崩溃日志会互相污染，没法排查。
    """
    running = running_game_processes()
    prevent = bool(getattr(config, "prevent_game_multi_instance", True))
    return {
        "running": bool(running),
        "processes": running,
        "prevent": prevent,
        "blocked": bool(running) and prevent,
        "message": (
            f"检测到终末地已在运行（{', '.join(running)}）：同时开两个实例会让 Mod 与 ReShade "
            f"互相干扰，请先关闭正在运行的那个再启动。"
            if running else "没有检测到正在运行的终末地"
        ),
    }


_LAUNCH_STAGE: dict[str, Any] = {}
# 阶段文案只在"启动进行中"有意义；超过这个时长还没被下一次启动覆盖，就当它过期
# （避免界面永远停在"正在重建 Mod 目录…"）。
_LAUNCH_STAGE_TTL = 300.0


def set_launch_stage(text: str) -> None:
    """记录"一键启动**当前走到哪一步**"，供界面显示进度（2026-10-07 用户要求）。

    用户原话：「**启动到扫除mod还是很慢，要是要时间就显示加载页面**」——
    启动链上有几处天然要花时间（随包资产校验、`stage_and_prepare` 重建 3.5 GB 的 Mods 目录、
    游戏目录净化…），而界面上只显示按钮文字「正在启动…」⇒ 用户不知道是在干活还是卡死了。

    ⚠️ 这是**纯展示**用的状态：只写内存、不做任何判断、失败也不抛
    （界面读不到就退回原来的按钮文字）。前端已经在按 1~2 秒轮询 `get_state()`，
    所以不需要新增任何通道。
    """
    global _LAUNCH_STAGE
    _LAUNCH_STAGE = {"text": str(text or ""), "at": time.time()}


def current_launch_stage() -> dict[str, Any]:
    """给 `api.get_state()` 用：当前阶段文案 + 开始时刻（空 = 没在启动 / 已过期）。"""
    stage = _LAUNCH_STAGE
    try:
        if stage and (time.time() - float(stage.get("at") or 0)) > _LAUNCH_STAGE_TTL:
            return {}
    except (TypeError, ValueError):
        return {}
    return dict(stage)


def launch(
    config: AppConfig,
    *,
    dry_run: bool = True,
    start_game: bool = False,
    inject_timeout: float = 60.0,
) -> dict[str, Any]:
    config.ensure_dirs()
    # ★ 注入现场时间线·**时机 1／5：一键启动最开始**（用户 2026-10-05 要求：
    #   「在一键启动最开始和 xxmi 拉起后和终末地启动后和终末地关闭和崩溃后都要收注入列表」）。
    #   此刻还没净化、还没写注入库，记的是"**这一趟出发前**"的状态 —— 与后面四个点一比，
    #   就能看出"注入库/游戏目录是被谁、在什么时候改掉的"（`0xC0000135` 的两种来源只有
    #   时间线分得开：真缺依赖 vs 进程内 `LoadLibrary` 失败后异常传播成退出码）。
    if not dry_run:
        try:
            from . import injecttrace

            injecttrace.record(config, phase="launch-begin",
                               log=lambda message: _append_log(config, message))
        except Exception as exc:  # noqa: BLE001 —— 取证失败绝不能影响启动
            _append_log(config, f"注入时间线: 记录失败（忽略）: {exc}")
    # 防多开：真的要启动游戏时，先确认没有别的事例在跑
    if not dry_run and start_game:
        state = check_game_multi_instance(config)
        if state["blocked"]:
            raise LaunchError(state["message"])
        if state["running"]:
            _append_log(config, f"⚠ {state['message']}")
    set_launch_stage("正在检查游戏目录与注入库…")
    game_dir = reshade_integration.detect_game_dir(config)
    if not dry_run:
        diagnostics.begin_launch(config, "xxmi", game_dir=game_dir)
    if config.use_builtin_runtime and not dry_run:
        try:
            set_launch_stage("正在检查随包组件与运行库…")
            runtime_deps.ensure_all(
                config,
                progress=lambda current, total, key, status: _append_log(config, f"builtin {key}: {status}"),
            )
        except Exception as exc:  # noqa: BLE001
            _append_log(config, f"builtin runtime install failed: {exc}")

    dependency_updates: list[dict[str, Any]] = []
    if not dry_run:
        # Install dependencies before staging so newly installed libraries are
        # copied into the active Mods directory in the same launch.
        try:
            dependency_updates = install_missing_dependencies(config)
        except Exception as exc:  # noqa: BLE001
            _append_log(config, f"missing dependency install failed: {exc}")

    if not dry_run:
        set_launch_stage("正在重建 Mod 目录（按当前勾选，可能要复制较大的 Mod）…")
        activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.effective_selected_mods,
            hotkey_takeover=resolve_hotkey_takeover(config, config.controller_dir),
            allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
            prefer_internal_dependencies=bool(
                getattr(config, "prefer_internal_dependencies", True)
            ),
            # 把 staging 的警告（复制失败、旧产物没删干净）写进启动日志 ——
            # 这样"某个 Mod 没就绪"能查到原因，而不是只看到一句无头无尾的失败。
            log=lambda m: _append_log(config, m),
        )

    problems = config.validate()
    if problems:
        raise LaunchError("; ".join(problems))

    controller_dir = config.controller_dir
    if not dry_run and not (controller_dir / "actions.tsv").is_file():
        raise LaunchError("Controller files are missing. Run prepare first.")

    if config.auto_update_dependencies and not dry_run:
        manifest = dependencies.load_manifest(Path(config.dependency_manifest))
        dependency_updates += [r.__dict__ for r in dependencies.update_all(manifest, config.library_path, dry_run=False)]

    set_launch_stage("正在准备 ReShade 底座与游戏内面板…")
    reshade = prepare_reshade_runtime(config, controller_dir)
    existing_reshade = reshade_integration.detect_existing_reshade(config)
    if not dry_run and game_dir is not None:
        diagnostics.log_runtime_snapshot(config, game_dir=game_dir)

    # —— 本方案唯一的注入路径 ——
    # 由 XXMI 在进程启动时把 DLSS5 的 d3d12.dll（唯一 ReShade 底座：DLSS5 +
    # 第一人称两个插件）和 EFMI 的 d3d11.dll（服装 Mod）一起注入。
    # 因此不再往游戏目录写任何文件，也不接管游戏目录里可能残留的旧 ReShade。
    integration: dict[str, Any] | None = None
    if existing_reshade is not None:
        _append_log(
            config,
            "检测到游戏目录仍有 ReShade（"
            + str(existing_reshade.get("ini"))
            + "）——本方案不使用它，唯一底座由 XXMI 注入；"
            "建议用「清理游戏目录注入」把它停放，避免两个 ReShade 抢 hook。",
        )

    # **一键启动前的自动净化**（2026-10-04 用户要求；设置页开关，默认开）。
    #
    # 原话：「在设置做个开关，一键还原终末地清除所有第三方注入，**默认开**，
    # 开了之后**不管是不是管理器注入的，都要去掉（要备份）**」。
    # 顺序**必须**在这里（`ensure_injections` 之前）：先把游戏目录里任何第三方注入
    # 痕迹备份移走、把系统原版补回，再由下面按当前开关重新铺我们自己那一份 ——
    # 反过来的话，刚铺好的注入会被当成"残留"清掉。
    # 只搬不删、写备份清单、随时可一键还原（`game_clean.restore`）。
    purged: set[str] | None = None      # 净化后的"干净基线"，用来算"铺回了哪些"
    if not dry_run:
        try:
            from . import game_clean

            clean_report = game_clean.auto_clean_before_launch(
                config, log=lambda message: _append_log(config, message))
            if clean_report.get("moved"):
                _append_log(config,
                            f"启动前净化完成：移走 {len(clean_report['moved'])} 项；"
                            f"备份在 {clean_report.get('backup_dir')}（可在设置页一键还原）")
            # ★ 记下净化后的现场（用户 2026-10-05 要求：「净化后没有'**按开关铺回了哪些**'
            #   的显式说明也做一下」）：下面按开关铺回之后再扫一次，**差集**就是本次铺回来的
            #   —— 免得读日志的人把"我们又装回来的 poser/sbm"误判成"净化没生效"。
            purged = game_clean.injection_snapshot(config)
        except Exception as exc:  # noqa: BLE001 —— 净化失败不能拦住启动
            _append_log(config, f"WARN 启动前净化失败（继续启动）: {exc}")

    if not dry_run:
        injection_report = ensure_injections(config)
        reshade["injection_report"] = injection_report
        for warning in injection_report.get("warnings", []):
            _append_log(config, f"WARN 注入自检: {warning}")
        # ★ **净化后按开关铺回了哪些**（用户 2026-10-05 要求）：与净化后的基线求差集。
        #   `plugin/poser.dll`、`plugin/sbm.dll`、`d3dcompiler_47.dll`、`vulkan-1.dll` 这些
        #   是**我们按开关铺的**，不是"净化没生效"、也不是第三方残留 —— 不写清楚，
        #   读日志的人（包括我们自己排查崩溃时）就会把它当成污染源。
        if purged is not None:
            try:
                from . import game_clean

                restored = sorted(game_clean.injection_snapshot(config) - purged)
            except Exception:  # noqa: BLE001
                restored = []
            if restored:
                shown = "、".join(restored[:12]) + ("…" if len(restored) > 12 else "")
                _append_log(
                    config,
                    f"净化后按当前开关重新铺设了 {len(restored)} 项：{shown}"
                    f"（这些是**我们要的**注入、不是第三方残留；不想让它们进来就去设置页"
                    f"关掉对应开关 —— Poser / 乳摇 / DLSS5 / 第一人称）")
        # ⚠️ **必须放在 `ensure_injections()` 之后**（2026-10-04 用户报「第一人称的中文没了」的根因）：
        # `initialize.ensure_all()` 会在这一步**重建** `dlss5\ReShade.ini`（里面才带
        # `[endfield-enhancer] Language=1` 与中文字体）；而上面 `prepare_reshade_runtime()`
        # 里的那次同步跑在它**之前** —— 源 ini 还不存在时同步只会静默返回 0，
        # 于是"生效的那份"（`runtime\reshade\ReShade.ini`，由 `RESHADE_BASE_PATH_OVERRIDE`
        # 决定）保持 addon 写的 `Language=0`（英文）⇒ 用户进游戏看到英文。
        # 这里再同步一次是**幂等**的，只补差异项，不会覆盖用户自己调过的值。
        sync_effective_reshade_ini(config, log=lambda message: _append_log(config, message))

    # ⚠ **2026-10-01 根因修复：EFMI 的 `skip_early_includes_load` 必须为 0。**
    #   EFMI 的 `d3dx.ini` 出厂默认是 `skip_early_includes_load = 1`（配套
    #   `config_initialization_delay = 0`）：**Mods/ 下的 ini 不在 DLL 初始化阶段加载**。
    #   而 `[Key*]` 段的**按键注册只发生在初始化阶段** ⇒
    #   **所有按键一律不生效** —— Mod 自己的键、我们面板发的合成键，全都收不到；
    #   可 `[Present]` / `[Constants]` 是**运行时**读取，所以照常工作。
    #   于是现象是「注入正常、面板能开、变量能读能写、每帧探针还在涨，但按什么都没反应」，
    #   极难往 ini 加载时机上想（2026-10-01 排查了整轮才定位，判据是
    #   `$mc_probe_frames` 在涨而 `$mc_hit_F13..F24` 与 `mc_last_wire` 恒为 0）。
    #   原先的纠正函数 `ensure_efmi_early_includes()` 挂在**已废弃**的
    #   `launch_migoto_loader()` 上（该函数全库无人调用），所以从来没执行过。
    if not dry_run:
        try:
            # ⚠️ 这里要的是 **EFMI 自己的 `d3dx.ini`**，所以直接取 `config.efmi_dir`。
            # 原来写的是 `config.auto_detect_migoto_loader()` —— 而 `auto_detect_migoto_loader`
            # 是 `config.py` 里的**模块级函数**、不是 `AppConfig` 的方法，于是每次都抛
            # `'AppConfig' object has no attribute 'auto_detect_migoto_loader'`、
            # 被下面的 except 吞成一句 WARN ⇒ **这段纠正从来没生效过**
            #（用户日志里 14:48 / 14:53 / 14:55 三次全是这个 WARN）。
            # 后果不小：不把 `skip_early_includes_load` 改回 0，`[Key*]` 段就不会在初始化阶段
            # 注册，**所有按键（Mod 自带的、我们面板发的）一律收不到**。
            efmi_dir = config.efmi_dir
            efmi_d3dx = (efmi_dir / "d3dx.ini") if efmi_dir else None
            if efmi_d3dx and efmi_d3dx.is_file() and _has_efmi_core_config(efmi_d3dx) and ensure_efmi_early_includes(efmi_d3dx):
                _append_log(config, "EFMI: 已改为初始化阶段加载 Mods（否则 [Key*] 按键全部不注册）")
        except Exception as exc:  # noqa: BLE001 —— 纠正失败不能拦住启动
            _append_log(config, f"WARN EFMI 提前加载纠正失败: {exc}")

    integrity_report = {"ok": True, "failures": []}
    if not dry_run:
        integrity_report = integrity.check_integrity(config)
        if not integrity_report["ok"]:
            for failure in integrity_report["failures"]:
                _append_log(config, f"integrity missing: {failure['key']} -> {failure['path']}")
            integrity.repair_integrity(config, log=lambda message: _append_log(config, f"repair: {message}"))
            controller_dir = config.controller_dir
            reshade = prepare_reshade_runtime(config, controller_dir)
            if config.dlss5_injection:
                configure_dlss5_injection(config, enabled=True)
            integrity_report = integrity.check_integrity(config)
        if not integrity_report["ok"]:
            raise LaunchError("完整性检查失败: " + "; ".join(item["message"] for item in integrity_report["failures"]))
        _append_log(config, "完整性检查通过")

        # ★★ **修复流程之后必须再按配置对齐一次插件位置**（2026-10-06，实测定案）——
        #    `repair_integrity()` 会调 `ensure_all()` **再展开一轮**，把"按开关搬进
        #    `_disabled\`"的插件又放回根目录。实测现场（用户那次一键启动的日志）：
        #      `注入自检: 统一管理器: 清掉多余副本 endfieldmodcontroller.addon64`   ← 对齐做过了
        #      `integrity missing: dlss5_enhancer_addon -> …\renodx-endfield-enhancer.addon64`
        #      `repair: 展开内置资产 renodx-endfield-enhancer.addon64`             ← 又被放回
        #    随后 ReShade 就加载了它 ⇒ 用户报「关掉了还是注入进去了」。
        #    ⚠️ 治本在 `integrity.check_integrity()` 那一侧（已改成按开关判"要不要检"），
        #       这里再对齐一次是**兜底**：任何"修复/补齐"路径都可能顺手把文件铺回来。
        try:
            apply_minimal_injection(config, log=lambda message: _append_log(config, message))
            for _component, _flag in (("dlss5", "dlss5_addon_enabled"),
                                      ("firstperson", "firstperson_addon_enabled"),
                                      ("mfg", "mfg_unlock_enabled")):
                set_component_addons(config, _component,
                                     bool(getattr(config, _flag, False)))
        except Exception as exc:  # noqa: BLE001 - 对齐失败不该拦住启动
            _append_log(config, f"插件位置对齐失败（忽略）: {exc}")

    set_launch_stage("正在拉起 XXMI 启动器…")
    command = build_launch_command(config, start_game=start_game)
    env = build_launch_env(config, existing_reshade=existing_reshade is not None)
    result: dict[str, Any] = {
        "command": command,
        "env": {k: v for k, v in env.items() if k.startswith(("RESHADE", "ENDFIELDMODCONTROLLER"))},
        "reshade": reshade,
        "existing_reshade": integration if integration is not None else existing_reshade,
        "dependency_updates": dependency_updates,
        "start_game": start_game,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    _append_log(config, f"launch command: {command}")
    _append_log(config, f"RESHADE_BASE_PATH_OVERRIDE={env.get('RESHADE_BASE_PATH_OVERRIDE')}")
    if not start_game:
        _append_log(config, "游戏未由 EndfieldModController 启动；请从 XXMI Launcher 手动启动游戏。")

    # 非管理员时**只记一条日志，不阻止启动**。
    # 原来这里写的是 `hasattr(os, "geteuid") and os.geteuid() != 0` —— 那是 Unix 专用，
    # 在 Windows 上恒为假，等于这个开关从来没生效过（2026-09-29 发现）。
    # 真正需要提权的是 XXMI Launcher（它的 exe 要求管理员），那一步在下面的
    # _spawn_command 里会按 require_admin 自动走 runas 提权；这里补一条可读的提示。
    if config.require_admin and os.name == "nt":
        try:
            import ctypes

            if not ctypes.windll.shell32.IsUserAnAdmin():
                _append_log(config, "当前不是管理员：启动 XXMI 时会自动请求提权（XXMI 需要管理员）")
        except Exception:  # noqa: BLE001
            pass

    launcher_path = config.xxmi_launcher_path
    assert launcher_path is not None
    # ★ **已在运行的 XXMI 不再重复拉起**（2026-10-06 修；实测"点一次启动出现 4 个 XXMI"）。
    #   这一步以前无条件 `_spawn_command` ⇒ 重复送达的每一次请求都真的拉起一个实例，
    #   每个实例各挂一套 EFMI。进程监视器那一步本来就有防重（日志里的"已在运行，
    #   跳过重复启动"），唯独**真正拉起进程**这一步没有 —— 判据要放在执行动作的那一层。
    if xxmi_process_running(config):
        _append_log(config, "XXMI Launcher 已在运行 —— 本次不再重复拉起（避免多开）")
        result["xxmi_already_running"] = True
        diagnostics.start_process_monitor(config, game_dir=game_dir, timeout=1800.0)
        return result
    process = _spawn_command(config, command, str(launcher_path.parent), env)
    if process is not None:
        result["pid"] = process.pid
    else:
        result["elevated"] = True

    _append_log(config, "ReShade/DLSS5 与第一人称插件由 XXMI 注入库在进程启动时加载，无外部注入。")
    diagnostics.start_process_monitor(config, game_dir=game_dir, timeout=1800.0)
    return result


def ensure_migoto_runtime(config: AppConfig, source_dir: Path | None = None) -> dict[str, Any]:
    """Copy the framework files of a working 3DMigoto package into runtime/migoto.

    User Mods and d3dx_user.ini are deliberately not copied; EndfieldModController owns
    its own Mods/_endfieldmodcontroller_managed staging area there.
    """
    source = source_dir or (config.migoto_loader_path.parent if config.migoto_loader_path else None)
    if source is None or not source.is_dir():
        raise LaunchError("没有找到可用的 3DMigoto 包目录")
    target = config.runtime_path / "migoto"
    target.mkdir(parents=True, exist_ok=True)
    (target / "Mods").mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    framework_source = source
    if source.resolve() != target.resolve():
        # Prefer the EFMI core: it supports EFMIv1 / Pool mod sections.
        # The legacy v1.4.x framework is only a fallback.
        legacy = _legacy_migoto_source()
        efmi_dir = config.builtin_runtime_path / "XXMI" / "EFMI"
        if (efmi_dir / "d3d11.dll").is_file() and (efmi_dir / "d3dx.ini").is_file() and (efmi_dir / "Core").is_dir():
            framework_source = efmi_dir
        elif legacy is not None:
            framework_source = legacy
        for name in ("loader.exe",):
            src = source / name
            if src.is_file():
                _copy_if_changed(src, target / name)
                copied.append(name)
        for name in ("d3d11.dll", "d3dcompiler_47.dll", "d3dx.ini", "nvapi64.dll"):
            src = framework_source / name
            if src.is_file():
                _copy_if_changed(src, target / name)
                copied.append(name)
        for dirname in ("Core", "ShaderFixes"):
            src_dir = framework_source / dirname
            if src_dir.is_dir():
                shutil.copytree(src_dir, target / dirname, dirs_exist_ok=True)
                copied.append(dirname)
    bootstrap_src = _bootstrap_path()
    if bootstrap_src is not None:
        bootstrap_dst = target / "mc_bootstrap.dll"
        if bootstrap_src.resolve() != bootstrap_dst.resolve():
            _copy_if_changed(bootstrap_src, bootstrap_dst)
        copied.append("mc_bootstrap.dll")
    config.migoto_loader = config.store_path(target / "loader.exe")
    config.save()
    return {"source": str(source), "framework_source": str(framework_source), "target": str(target), "loader": str(target / "loader.exe"), "copied": copied}


def _efmi_core_global_keys(core_dir: Path | None) -> set[str]:
    keys: set[str] = set()
    if core_dir is None or not core_dir.is_dir():
        return keys
    try:
        files = list(core_dir.rglob("*.ini"))
    except OSError:
        return keys
    for candidate in files:
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("global "):
                match = re.search(r"\$[^=\s]+", stripped)
                keys.add(match.group(0).lower() if match else stripped.lower())
    return keys


def ensure_efmi_library_globals(d3dx_ini: Path, library_root: Path, core_dir: Path | None = None) -> bool:
    """Copy global variable definitions from library-level d3dx.ini files.

    Some Endfield mod packs ship a base d3dx.ini that defines globals such as
    ``$costume_mods``.  Their mod ini files assume those globals exist, but
    EndfieldModController deliberately does not copy per-mod d3dx.ini files into Mods.
    Pull the declarations into the active d3dx.ini [Constants] section so the
    dependency works without replacing the whole EFMI config.

    Globals already owned by EFMI core (for example its own ``$version``) are
    deliberately skipped to avoid breaking EFMI's compatibility checks.
    """
    if not d3dx_ini.is_file() or not library_root.is_dir():
        return False
    declarations: dict[str, str] = {}
    try:
        candidates = list(library_root.rglob("d3dx.ini"))
    except OSError:
        candidates = []
    for candidate in candidates:
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped.lower().startswith("global "):
                continue
            match = re.search(r"\$[^=\s]+", stripped)
            key = match.group(0).lower() if match else stripped.lower()
            declarations.setdefault(key, stripped)
    reserved = _efmi_core_global_keys(core_dir)
    declarations = {key: value for key, value in declarations.items() if key not in reserved}
    if not declarations:
        # Still remove an old generated block if it exists.
        pass

    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        marker = line.strip().lower()
        if marker == "; endfieldmodcontroller library globals begin":
            skipping = True
            continue
        if marker == "; endfieldmodcontroller library globals end":
            skipping = False
            continue
        if not skipping:
            out.append(line)

    try:
        index = next(i for i, line in enumerate(out) if line.strip().lower() == "[constants]")
    except StopIteration:
        return False

    existing = set()
    for line in out:
        stripped = line.strip()
        if stripped.lower().startswith("global "):
            match = re.search(r"\$[^=\s]+", stripped)
            existing.add(match.group(0).lower() if match else stripped.lower())
    missing = [value for key, value in declarations.items() if key not in existing]
    if not missing:
        _write_ini_atomic(d3dx_ini, chr(10).join(out) + chr(10))
        return bool(not skipping or out)
    block = ["; EndfieldModController library globals begin", *missing, "; EndfieldModController library globals end"]
    out[index + 1:index + 1] = block
    _write_ini_atomic(d3dx_ini, chr(10).join(out) + chr(10))
    return True


def ensure_legacy_costume_sections(d3dx_ini: Path) -> bool:
    """Append the legacy ShaderOverrideCharacter/CommandListSkin block.

    The EFMI core handles Pool/EFMIv1 mods, but many costume mods in this pack
    still depend on the original Endfield 3DMigoto v1.4.x overrides:
    ``[ShaderOverrideCharacter]`` runs ``[CommandListSkin]`` and enables the
    per-slot ``checktextureoverride`` entries used by ``VSCheck.ini``.
    """
    if not d3dx_ini.is_file():
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    begin = "; EndfieldModController legacy costume override begin"
    end = "; EndfieldModController legacy costume override end"
    out: list[str] = []
    skipping = False
    for line in lines:
        marker = line.strip().lower()
        if marker == begin.lower():
            skipping = True
            continue
        if marker == end.lower():
            skipping = False
            continue
        if not skipping:
            out.append(line)
    text = chr(10).join(out)
    if "[ShaderOverrideCharacter]" in text and "[CommandListSkin]" in text:
        _write_ini_atomic(d3dx_ini, chr(10).join(out) + chr(10))
        return False
    block = [
        begin,
        "[ShaderOverrideCharacter]",
        "hash = 653c63ba4a73ca8b",
        "run = CommandListSkin",
        "",
        "[CommandListSkin]",
        "if $costume_mods",
        "    checktextureoverride = ps-t0",
        "    checktextureoverride = ps-t1",
        "    checktextureoverride = ps-t2",
        "    checktextureoverride = ps-t3",
        "    checktextureoverride = vb0",
        "    checktextureoverride = vb1",
        "    checktextureoverride = vb2",
        "    checktextureoverride = ib",
        "    checktextureoverride = ps-t13",
        "    checktextureoverride = ps-t14",
        "    checktextureoverride = ps-t15",
        "    checktextureoverride = ps-t16",
        "    checktextureoverride = ps-t17",
        "    x140 = 0",
        "endif",
        end,
    ]
    out.extend(["", *block])
    _write_ini_atomic(d3dx_ini, chr(10).join(out) + chr(10))
    return True


def ensure_efmi_early_includes(d3dx_ini: Path) -> bool:
    """Load [Include]/Mods during EFMI init instead of waiting for the first frame.

    EFMI 1.3.x defaults to ``skip_early_includes_load=1`` with a zero-second
    delayed reload.  In Endfield that delayed reload may not fire before the
    player checks the character, so mods appear "not loaded" even though EFMI
    initialized.  Force the original 3DMigoto behavior instead.
    """
    if not d3dx_ini.is_file():
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    in_system = False
    found_skip = False
    found_delay = False
    changed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_system = stripped.lower() == "[system]"
        if in_system and stripped.lower().startswith("skip_early_includes_load") and "=" in stripped:
            if stripped != "skip_early_includes_load = 0":
                out.append("skip_early_includes_load = 0")
                changed = True
            else:
                out.append(line)
            found_skip = True
            continue
        if in_system and stripped.lower().startswith("config_initialization_delay") and "=" in stripped:
            if stripped != "config_initialization_delay = -1":
                out.append("config_initialization_delay = -1")
                changed = True
            else:
                out.append(line)
            found_delay = True
            continue
        out.append(line)
    if not found_skip or not found_delay:
        try:
            index = next(i for i, line in enumerate(out) if line.strip().lower() == "[system]")
        except StopIteration:
            return changed
        insert_at = index + 1
        if not found_delay:
            out.insert(insert_at, "config_initialization_delay = -1")
            changed = True
        if not found_skip:
            out.insert(insert_at, "skip_early_includes_load = 0")
            changed = True
    # ★ 2026-10-01【按键全无反应的真正根源，读源码定案】：
    #   `[Key*]` 段**必须走显式 include** 才会被注册。
    #   源码 `IniHandler.cpp` 的初始化顺序是：
    #       ParseConstantsSection();        // [Constants]（命令列表）
    #       RegisterPresetKeyBindings();    // ← [Key*] **只在这一刻**从当前 ini_sections 里注册
    #       ParseCommandList(L"Present");   // [Present]（命令列表）
    #   而 `[Constants]` / `[Present]` 是**命令列表** —— 晚一点进也照样生效；
    #   `[Key*]` 却只被取一次 —— 所以**通过 `include_recursive = Mods` 递归进来的段赶不上那一刻**
    #   （EFMI 的 `skip_early_includes_load` 会把递归 include 推后），
    #   于是表现为"**Mod 外观能生效、面板按键一个都不触发**"，且 ini 文本完全正常。
    #   对照：EFMI 自带的 `KeyBindings.ini` 能正常工作，正是因为它走的是**显式 `include =`**。
    #   这里在 `[Include]` 段里补一条显式 include（放在 `include_recursive` 之前）。
    include_marker = "mods\\mc_controller\\controller.ini"
    already = any(include_marker in line.lower() and line.strip().lower().startswith("include")
                  for line in out)
    if not already and any(line.strip().lower().startswith("include_recursive")
                           for line in out):
        insert_at = next(i for i, line in enumerate(out)
                         if line.strip().lower().startswith("include_recursive"))
        out.insert(insert_at, "; MC: [Key*] 段必须显式 include 才会被注册（见 launcher.ensure_efmi_early_includes）")
        out.insert(insert_at + 1, "include = Mods\\MC_Controller\\controller.ini")
        changed = True

    if changed:
        _write_ini_atomic(d3dx_ini, chr(10).join(out) + chr(10))
    return changed


def enable_efmi_debug_logging(d3dx_ini: Path) -> bool:
    """Set a light EFMI/3DMigoto log profile: calls on, per-frame debug off.

    ``debug=1`` logs every API call and is frequently unbuffered, which can
    drop Endfield to single-digit FPS.  Keep only calls/input logging so the
    log stays useful without throttling the game.
    """
    if not d3dx_ini.is_file():
        return False
    lines = d3dx_ini.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    in_logging = False
    changed = False
    wanted = {"calls": "1", "input": "1", "debug": "0", "unbuffered": "0"}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_logging = stripped.lower() == "[logging]"
            out.append(line)
            continue
        if in_logging and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().lower()
            if key in wanted:
                out.append(f"{key} = {wanted[key]}")
                changed = True
                continue
        out.append(line)
    if changed:
        # Drop the run of empty continuation lines that some older packaging
        # steps inserted; the parser ignores them, but they make d3dx.ini huge.
        cleaned = [line for line in out if line.strip()]
        _write_ini_atomic(d3dx_ini, chr(10).join(cleaned) + chr(10))
    return changed


def launch_migoto_loader(
    config: AppConfig,
    *,
    open_official_launcher: bool = True,
) -> dict[str, Any]:
    """Stage controller mods into a working 3DMigoto package and start its loader.exe.

    The loader waits for Endfield.exe, updates d3dx.ini's target, and injects the
    package's own d3d11.dll.  This mirrors the workflow that already worked for
    the user and avoids XXMI/EFMI and ReShade proxy DLLs.
    """
    actions: list[str] = []
    warnings: list[str] = []

    _stop_locked_files_processes(config)
    loader = config.migoto_loader_path
    if loader is None or not loader.is_file():
        raise LaunchError("3DMigoto loader path is not configured")
    target_runtime = (config.runtime_path / "migoto").resolve()
    legacy_source = _legacy_migoto_source()
    efmi_dir = config.builtin_runtime_path / "XXMI" / "EFMI"
    current_ini = target_runtime / "d3dx.ini"
    if not (_is_legacy_framework_config(current_ini) or _has_efmi_core_config(current_ini)):
        if (
            (efmi_dir / "d3d11.dll").is_file()
            and (efmi_dir / "d3dx.ini").is_file()
            and (efmi_dir / "Core").is_dir()
        ):
            ensured = ensure_migoto_runtime(config, efmi_dir)
            loader = Path(ensured["loader"])
        elif legacy_source is not None:
            ensured = ensure_migoto_runtime(config, legacy_source)
            loader = Path(ensured["loader"])
    if loader.parent.resolve() != target_runtime or not (target_runtime / "loader.exe").is_file():
        ensured = ensure_migoto_runtime(config, loader.parent)
        loader = Path(ensured["loader"])
    loader_dir = loader.parent
    legacy_mode = _is_legacy_framework_config(loader_dir / "d3dx.ini")

    if not legacy_mode:
        bootstrap_src = _bootstrap_path()
        if bootstrap_src is None:
            raise LaunchError("未找到 mc_bootstrap.dll，无法启动 EFMI 注入桥")
        _copy_if_changed(bootstrap_src, loader_dir / "mc_bootstrap.dll")

    try:
        d3dx_ini = loader_dir / "d3dx.ini"
        if _has_efmi_core_config(d3dx_ini):
            ensure_efmi_library_globals(d3dx_ini, config.library_path, loader_dir / "Core")
            ensure_efmi_early_includes(d3dx_ini)
        enable_efmi_debug_logging(d3dx_ini)
        old_log = loader_dir / "d3d11_log.txt"
        if old_log.is_file():
            backup_log = loader_dir / "d3d11_log.prev.txt"
            if backup_log.exists():
                backup_log.unlink()
            old_log.rename(backup_log)
    except OSError:
        pass
    game_dir = reshade_integration.detect_game_dir(config)
    diagnostics.begin_launch(config, "migoto_loader", game_dir=game_dir)
    required_files = ["d3d11.dll", "d3dx.ini"]
    if not legacy_mode:
        required_files.append("mc_bootstrap.dll")
    for required in required_files:
        if not (loader_dir / required).is_file():
            raise LaunchError(f"3DMigoto package is missing {required}: {loader_dir}")

    # Reuse the simple loader executable, but use our multi-injector build so
    # ReShade64.dll can be injected before the EFMI d3d11.dll.
    multi_loader = _multi_loader_path()
    if not legacy_mode and multi_loader is not None:
        _copy_if_changed(multi_loader, loader_dir / "migoto_loader2.exe")

    mods_dir = loader_dir / "Mods"
    user_ini = loader_dir / "d3dx_user.ini"
    if not user_ini.is_file():
        user_ini.write_text("; EndfieldModController generated" + chr(10) + "[Constants]" + chr(10), encoding="utf-8")
    result = activation.stage_and_prepare(
        config.library_path,
        mods_dir,
        config.runtime_path,
        selected_ids=config.selected_mods,
        user_ini_path=user_ini,
        hotkey_takeover=resolve_hotkey_takeover(config, config.controller_dir, log=lambda m: _append_log(config, m)),
        allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
        prefer_internal_dependencies=bool(
            getattr(config, "prefer_internal_dependencies", True)
        ),
    )
    controller_dir = Path(result["controller_dir"])

    # 统一面板（如果有）落到 ReShade 真正会读的 base 目录 —— 见
    # reshade_integration 模块头对 ReShade 日志的引用。
    panel = reshade_integration.deploy_panel(config, controller_dir, log=lambda m: _append_log(config, m))
    for warning in panel.get("warnings", []):
        warnings.append(f"统一面板: {warning}")
    built_addon = _built_addon_path()
    installed_addon = config.dlss5_path / reshade_integration.ADDON_NAME
    actions_tsv = controller_dir / "actions.tsv"
    # legacy 路线（ReShade 从 loader 目录加载）以前是往 `<loader>\Addons\` 放的，
    # 这里保留同一行为，只把文件名统一成 `endfieldmodcontroller.addon64`。
    addons_dir = loader_dir / "Addons"
    try:
        addons_dir.mkdir(parents=True, exist_ok=True)
        if getattr(config, "inject_reshade_ui", True) and built_addon is not None:
            shutil.copy2(built_addon, addons_dir / reshade_integration.ADDON_NAME)
        if actions_tsv.is_file():
            shutil.copy2(actions_tsv, loader_dir / "actions.tsv")
    except OSError as exc:
        warnings.append(f"写入 loader 面板失败: {exc}")
    (loader_dir / "user_ini_path.txt").write_text(str(user_ini), encoding="utf-8")
    (loader_dir / "inject_order.txt").write_text("mc_bootstrap.dll" + chr(10), encoding="utf-8")
    reshade_ini = loader_dir / "ReShade.ini"
    if not reshade_ini.is_file():
        ini_lines = [
            "[ADDON]",
            "AddonPath=Addons",
            "",
            "[GENERAL]",
            "EffectSearchPaths=reshade-shaders/Shaders/**",
            "TextureSearchPaths=reshade-shaders/Textures/**",
            "PresetPath=ReShadePreset.ini",
            "",
            "[INPUT]",
            "KeyOverlay=36,0,0,0",
            "",
        ]
        _write_ini_atomic(reshade_ini, chr(10).join(ini_lines))

    # ReShade + EFMI coexistence: put ReShade in the game folder as d3d12.dll
    # (the name Endfield dynamically probes under DX11), and let the EFMI loader
    # inject only d3d11.dll.  Do not inject ReShade64.dll into the same process.
    if game_dir is None:
        game_dir = reshade_integration.detect_game_dir(config)
    reshade_enabled = config.reshade_injection in {"external", "xxmi_extra"}
    if game_dir is not None and not reshade_enabled:
        # Explicitly disable ReShade when the user selects "不注入 ReShade".
        # The previous run may have left a proxying d3d12.dll in the game dir.
        for proxy_name in ("d3d12.dll",):
            proxy = game_dir / proxy_name
            if proxy.is_file():
                # 备份只增不删（见 _unique_backup_path）
                disabled = _unique_backup_path(game_dir / (proxy_name + ".endfieldmodcontroller.disabled"))
                proxy.rename(disabled)
                actions.append(f"已禁用 ReShade 代理: {proxy_name}")
    if game_dir is not None and reshade_enabled:
        for conflict_name in ("dxgi.dll", "d3d11.dll"):
            conflict = game_dir / conflict_name
            if conflict.is_file():
                backup = _unique_backup_path(
                    conflict.with_name(conflict.name + ".endfieldmodcontroller.disabled"))
                conflict.rename(backup)
        reshade_dll = config.reshade_dll_path
        if reshade_dll is not None and reshade_dll.is_file():
            # ⚠️⚠️ **写入前必须备份游戏目录原有的 `d3d12.dll`**（2026-10-04 修的 U7）。
            # 它可能是**游戏自带**的、也可能是第三方注入器放的；而同一个函数对
            # `dxgi.dll` / `d3d11.dll` 都做了唯一备份，唯独真正被我们覆盖的这一个没做
            # ⇒ 还原链路里缺这一份，用户**回不到"注入之前"**（不可逆）。
            # 备份名用 `_unique_backup_path`（只增不删），与上面两处保持一致。
            existing_d3d12 = game_dir / "d3d12.dll"
            if existing_d3d12.is_file():
                try:
                    saved = _unique_backup_path(
                        existing_d3d12.with_name("d3d12.dll.endfieldmodcontroller.disabled"))
                    shutil.copy2(existing_d3d12, saved)
                    actions.append(f"已备份游戏目录原有 d3d12.dll → {saved.name}")
                except OSError as exc:                       # noqa: BLE001
                    warnings.append(f"备份游戏目录原有 d3d12.dll 失败（仍继续写入）: {exc}")
            _copy_file_atomic(reshade_dll, game_dir / "d3d12.dll")
            _ensure_reshade_disabled_addons(game_dir)
            try:
                disabled_addons = reshade_integration.disable_conflicting_addons(
                    game_dir,
                    log=lambda message: _append_log(config, message),
                )
                actions.extend(f"disabled {item}" for item in disabled_addons.get("disabled", []))
                warnings.extend(disabled_addons.get("warnings", []))
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"物理禁用冲突 addon 失败: {exc}")
            built_addon = _built_addon_path()
            game_addon = game_dir / reshade_integration.ADDON_NAME
            if getattr(config, "inject_reshade_ui", True):
                if built_addon is not None:
                    try:
                        shutil.copy2(built_addon, game_addon)
                    except OSError as exc:
                        warnings.append(f"写入面板到游戏目录失败: {exc}")
            else:
                disabled_game_addon = game_addon.with_name(game_addon.name + ".disabled")
                if game_addon.is_file():
                    if disabled_game_addon.exists():
                        disabled_game_addon.unlink()
                    game_addon.rename(disabled_game_addon)
            if actions_tsv.is_file():
                _copy_file_atomic(actions_tsv, game_dir / "actions.tsv")
            _write_ini_atomic(game_dir / "user_ini_path.txt", str(user_ini))
            if not (game_dir / "ReShade.ini").is_file():
                ini_lines = [
                    "[ADDON]",
                    "",
                    "[GENERAL]",
                    "PresetPath=ReShadePreset.ini",
                    "",
                    "[INPUT]",
                    "KeyOverlay=36,0,0,0",
                    "",
                ]
                _write_ini_atomic(game_dir / "ReShade.ini", chr(10).join(ini_lines))
            actions.append("deployed ReShade as game-directory d3d12.dll")

    game_exe = config.game_exe_path
    game_path = ""
    if game_exe is not None and game_exe.is_file():
        game_path = str(game_exe)
    else:
        game_dir = reshade_integration.detect_game_dir(config)
        if game_dir is not None:
            candidate = game_dir / "Endfield.exe"
            if candidate.is_file():
                game_path = str(candidate)
    if not game_path:
        game_path = r"%ProgramData%\ReShade\Endfield.exe"

    if game_path and not game_path.startswith("%"):
        try:
            if _set_d3dx_loader_target(loader_dir / "d3dx.ini", game_path):
                actions.append("已同步 EFMI 的 [Loader] target")
        except OSError as exc:
            warnings.append(f"更新 d3dx.ini target 失败: {exc}")

    env = os.environ.copy()
    # ⚠️⚠️ **全局 ReShade 的 Apps 改写收敛到 Python 这一套**（2026-10-04 修的 U10）。
    #
    # 原来改 `%ProgramData%\ReShade\ReShadeApps.ini` 有**三套**实现、语义还不一致：
    #   ① `reshade_integration.disable_global_reshade_for_game()` —— 按名剔除终末地、
    #      **保留用户其它 Apps**、第一次动之前留备份、把原值写进 manifest（可完整还原）；**全库零调用**；
    #   ② `restore_global_reshade_apps()` —— 同样零调用，`global_reshade_apps.json` 从来没产生过；
    #   ③ 下面那段 batch：`> "%APPS%" echo Apps=…\disabled.exe` —— **把整行覆盖成只有我们这一项**，
    #      用户其它游戏/程序的 Apps 条目被**静默抹掉**（那是全局配置，别的游戏也读它）。
    # 现在只留 ①，并接到「回滚」上；batch 里那段 echo 删除（它既丢用户数据，又让"还原"没有依据）。
    try:
        global_apps = reshade_integration.disable_global_reshade_for_game(config)
        if global_apps.get("changed"):
            actions.append("已从全局 ReShade 注入列表移除终末地（保留其它 Apps）："
                           + (", ".join(global_apps.get("removed") or []) or "（无）"))
        elif global_apps.get("ok"):
            actions.append("全局 ReShade 注入列表里没有终末地，无需改动")
        else:
            warnings.append(f"改写全局 ReShade 注入列表失败：{global_apps.get('message')}")
    except Exception as exc:  # noqa: BLE001 —— 失败只记警告，不挡住启动
        warnings.append(f"改写全局 ReShade 注入列表失败: {exc}")
    run_script = loader_dir / "_run_loader.cmd"
    batch_template = r'''@echo off
setlocal
set "GAME=__GAME__"
rem NOTE: the global ReShade Apps list is rewritten on the Python side
rem (reshade_integration.disable_global_reshade_for_game) so that the user's
rem other Apps entries survive. Do NOT echo over it here.
taskkill /F /IM loader.exe >nul 2>&1

taskkill /F /IM migoto_loader.exe >nul 2>&1

taskkill /F /IM migoto_loader2.exe >nul 2>&1

start "" /B "%~dp0migoto_loader2.exe"
rem NOTE: this used to be `for /L %%i in (1,1,300)` -- killing a batch of loader
rem image names every 2 seconds for FIVE MINUTES. That also killed loaders the
rem USER opened in the meantime. Now we only clean up twice (just before start,
rem and 5 seconds after) so the window for killing someone else's process is a
rem few seconds instead of five minutes.
ping -n 5 -w 1000 127.0.0.1 >nul
taskkill /F /IM loader.exe >nul 2>&1
taskkill /F /IM loader_new.exe >nul 2>&1
taskkill /F /IM 3dmloader.exe >nul 2>&1
taskkill /F /IM "3DMigoto Loader.exe" >nul 2>&1
taskkill /F /IM "3DMigotoLoader.exe" >nul 2>&1
endlocal
'''
    run_script.write_text(batch_template.replace("__GAME__", game_path), encoding="utf-8")
    diagnostics.log_efmi_state(config, user_ini_path=user_ini, staging_root=loader_dir / "Mods")
    _spawn_elevated(config, str(run_script), str(loader_dir), show_window=0)
    if legacy_source is not None and legacy_source.resolve() != target_runtime:
        actions.append(f"检测到旧版 3DMigoto ({legacy_source})，启动期间会自动结束其 loader 以避免双注入")
        warnings.append("请勿同时运行旧版 3DMigoto 的 loader.exe；双注入会导致 EFMI 不生效或游戏卡在黑屏。")
    actions.append("已通过管理员脚本关闭全局 ReShade 注入并启动 3DMigoto loader")
    actions.append("已启用 mc_bootstrap 桥：进程内等待 d3d11/dxgi 后再加载 EFMI")
    # ⚠️ 原来这里有一行 `loader_pid = None` 并把它塞进返回值 —— **恒为 None 的死字段**
    #（loader 是通过 `ShellExecuteW runas` → cmd → `start /B` 拉起来的，我们拿不到它的 PID；
    #  前端也从来没读过这个字段）。2026-10-04 清掉，免得调用方以为它有意义。

    launcher_path = config.official_launcher_path
    launcher_opened = False
    if open_official_launcher and launcher_path is not None and launcher_path.is_file():
        try:
            _spawn_command(
                config,
                [str(launcher_path), "--game=Endfield"],
                str(launcher_path.parent),
                env,
                show_window=1,
            )
            launcher_opened = True
            actions.append(f"已打开官方启动器: {launcher_path.name}")
            _append_log(config, f"official launcher opened: {launcher_path}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"打开官方启动器失败: {exc}")
            _append_log(config, f"official launcher failed: {exc}")
    else:
        warnings.append("未配置官方启动器路径")
        _append_log(config, "official launcher path is not configured")

    diagnostics.log_runtime_snapshot(config, game_dir=game_dir)
    diagnostics.start_process_monitor(config, game_dir=game_dir, timeout=1800.0)
    _append_log(config, f"3DMigoto loader started: {loader}")
    return {
        "ok": True,
        "loader": str(loader),
        "staging_root": result["staging_root"],
        "controller_dir": result["controller_dir"],
        "official_launcher": str(launcher_path) if launcher_opened else "",
        "game_started": False,
        "actions": actions,
        "warnings": warnings,
        "message": "请在官方启动器里点 DirectX 11 启动。",
    }
