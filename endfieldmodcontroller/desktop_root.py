# SPDX-License-Identifier: GPL-3.0-or-later
"""「程序被放在桌面运行」的检查与清理（用户 2026-10-26 要求）。

用户原话：「如果第一次启动检查目录发现 exe 在桌面，先弹个弹窗，说明如果放桌面会导致
依赖文件夹全部在桌面生成，建议放磁盘根目录，可以忽略或清空已生成依赖并退出」。

为什么在意：本程序的**数据根就是 exe 所在目录** —— `config.json` / `runtime\\` / `assets\\`
都生成在 exe 旁边。放桌面就等于把这些目录全铺在桌面：乱、容易被手滑删掉，OneDrive 之类的
同步客户端还会把它们跟着拖走。放到磁盘根目录（例如 `D:\\EndfieldModController\\`）更稳。

三条边界（别越线）：
* `library\\`（用户的 Mod 库）**永远不删** —— 那是用户数据，红线；
* 只删"程序自己生成"的那几项，而且每个目标都必须是数据根的**直接子项**；
* 拿不到桌面路径 / 判定不了 ⇒ 一律当"不在桌面"，宁可少提示，也不误拦用户。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

#: 「已忽略」标记（放 rt 目录下，与 alerts 的 seen/cache 同风格）
NOTICE_NAME = Path("_state") / "desktop_root_notice.json"

#: 程序自己在数据根下生成的东西 —— 只有这几项会进删除清单
GENERATED_ENTRIES = ("config.json", "runtime", "assets")

#: **红线**：用户 Mod 库。任何情况下都不删、也不"顺便搬走"
PROTECTED_ENTRIES = ("library",)

# ---- 「桌面启动自动搬家」（用户 2026-10-26 追加要求）---------------------
# 用户原话：「在桌面启动直接不启动，在 d 盘（或回退 c 盘）建一个文件夹，把 exe 复制一份进去，
# 然后桌面建个快捷方式，启动复制后的 exe 并关闭这个实例」。
APP_DIR_NAME = "EndfieldModController"
SHORTCUT_NAME = "EndfieldModController.lnk"
#: 搬家标记：新实例带着它启动 ⇒ 绝不再搬（防"搬完还认为自己在桌面"的循环）
RELOCATE_ENV = "EMC_RELOCATED"
#: 搬家**来源**（桌面那份 exe 的路径）：新实例启动后据此把桌面那份删掉
RELOCATE_FROM_ENV = "EMC_RELOCATE_FROM"
#: 删桌面那份时的重试：桌面进程此刻可能刚退出，别一撞到占用就放弃
CLEANUP_RETRIES = 20
CLEANUP_INTERVAL = 0.5
#: 优先 D 盘，回退 C 盘（顺序即优先级）
RELOCATE_DRIVES = ("D", "C")
#: 最近一次搬家的结果（给界面用；进程内只可能有一次）
_LAST_RELOCATE: dict[str, Any] | None = None


def last_relocate() -> dict[str, Any] | None:
    return _LAST_RELOCATE


def desktop_dir() -> Path | None:
    """当前用户的桌面目录（能处理 OneDrive / 被手动改过位置的桌面）；拿不到返回 None。

    先读注册表里的真实桌面路径 —— 桌面被重定向时（OneDrive、用户自己改到 D 盘）
    「用户目录下那个 Desktop 名字」是不存在的，只看它会把"在桌面"误判成"不在桌面"。
    """
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            raw, _kind = winreg.QueryValueEx(key, "Desktop")
        text = str(raw or "").strip()
        if text:
            expanded = Path(os.path.expandvars(text)).expanduser()
            if expanded.is_dir():
                return expanded.resolve()
    except OSError:
        pass
    home = Path.home()
    for candidate in (
        home / "Desktop",
        home / "桌面",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "桌面",
    ):
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _base_dir(config: Any) -> Path:
    raw = str(getattr(config, "base_dir", "") or "")
    path = Path(raw)
    try:
        return path.resolve()
    except OSError:
        return path


def _notice_path(config: Any) -> Path:
    return Path(getattr(config, "runtime_path")) / NOTICE_NAME


def dismissed(config: Any) -> bool:
    """用户之前选过「仍然放在桌面」吗（选过就不再弹，别烦他）。"""
    from . import fsutil

    try:
        data = fsutil.read_json(_notice_path(config))
    except Exception:  # noqa: BLE001
        return False
    return bool((data or {}).get("dismissed"))


def dismiss(config: Any) -> dict[str, Any]:
    """记下「用户已经知道这事、仍然要放桌面」。"""
    from . import fsutil

    payload = {
        "dismissed": True,
        "at": datetime.now().isoformat(timespec="seconds"),
        "dir": str(_base_dir(config)),
    }
    try:
        fsutil.write_json(_notice_path(config), payload)
    except OSError as exc:
        return {"ok": False, "message": f"记不下「已忽略」：{exc}", **payload}
    return {"ok": True, "message": "已记住：以后不再提醒", **payload}


def report(config: Any) -> dict[str, Any]:
    """给界面用的现状（**纯路径判断，不扫盘** —— 它跑在 get_state 里，不能拖慢首屏）。"""
    base = _base_dir(config)
    desktop = desktop_dir()
    on_desktop = bool(desktop is not None and base == desktop)
    generated: list[str] = []
    for name in GENERATED_ENTRIES:
        try:
            if (base / name).exists():
                generated.append(name)
        except OSError:
            continue
    payload: dict[str, Any] = {
        "on_desktop": on_desktop,
        "base": str(base),
        "desktop": str(desktop) if desktop is not None else "",
        "generated": generated,
        "dismissed": dismissed(config),
    }
    # 本次启动有没有尝试过"搬家"（入口第一件事）：成功/失败都带给界面看
    moved = _LAST_RELOCATE
    if moved is not None:
        payload["relocate_failed"] = not bool(moved.get("ok"))
        payload["relocate_reason"] = str(moved.get("reason") or "")
        payload["relocated_to"] = str(moved.get("dir") or "") if moved.get("ok") else ""
    return payload


def wipe_generated(config: Any) -> dict[str, Any]:
    """删掉数据根下**程序自己生成**的东西；`library\\` 一律不动。

    每个目标删之前都重新验一遍：必须是数据根的**直接子项**、且不在保护清单里 ——
    用户可能中途把 exe 搬走或改了配置，那时宁可什么都不做。
    """
    base = _base_dir(config)
    removed: list[str] = []
    kept: list[str] = []
    errors: list[str] = []
    for name in GENERATED_ENTRIES:
        if name in PROTECTED_ENTRIES:
            kept.append(name)
            continue
        target = base / name
        try:
            if not target.exists():
                continue
            if target.resolve().parent != base:
                errors.append(f"跳过 {name}：不是数据根的直接子项")
                continue
        except OSError as exc:
            errors.append(f"跳过 {name}：{exc}")
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append(name)
        except OSError as exc:
            errors.append(f"删除 {name} 失败：{exc}")
    for name in PROTECTED_ENTRIES:
        try:
            if (base / name).exists():
                kept.append(name)
        except OSError:
            continue
    return {
        "ok": not errors,
        "base": str(base),
        "removed": removed,
        "kept": kept,
        "errors": errors,
    }

# ---------------------------------------------------------------- 自动搬家
def drive_roots() -> list[Path]:
    """候选盘根（默认 D → C）。抽成函数是为了让测试能替换掉真盘符。"""
    return [Path(f"{letter}:\\") for letter in RELOCATE_DRIVES]


def target_dir(roots: list[Path] | None = None) -> Path | None:
    """选一个"放程序"的目录：优先 D 盘，写不进去就回退 C 盘；都不行返回 None。

    判据是**真的往里写一个探针文件**，不是只看盘在不在 —— 盘存在但只读
    （BitLocker 未解锁、外置盘、被安全策略限制）时，is_dir() 会骗人。
    """
    for root in (roots or drive_roots()):
        try:
            if not root.is_dir():
                continue
            folder = root / APP_DIR_NAME
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".emc-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return folder
        except OSError:
            continue
    return None


def create_shortcut(lnk: Path, target_exe: Path) -> bool:
    """在桌面建一个指向新 exe 的快捷方式（WScript.Shell 走 PowerShell，带 CREATE_NO_WINDOW）。"""
    if os.name != "nt":
        return False
    script = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{lnk}');"
        f"$s.TargetPath='{target_exe}';"
        f"$s.WorkingDirectory='{target_exe.parent}';"
        f"$s.IconLocation='{target_exe},0';"
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            timeout=30,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        return lnk.is_file()
    except OSError:
        return False


def _write_relocate_log(folder: Path, message: str) -> None:
    try:
        with (folder / "relocate.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
    except OSError:
        pass


def relocate_if_needed() -> dict[str, Any] | None:
    """入口第一件事：exe 在桌面 ⇒ 搬到 D 盘（回退 C 盘）、桌面建快捷方式、启动新实例。

    用户 2026-10-26 原话：「在桌面启动直接不启动，在 d 盘（或回退 c 盘）建一个文件夹，
    把 exe 复制一份进去，然后桌面建个快捷方式，启动复制后的 exe 并关闭这个实例」。

    返回 None 表示"这次不需要搬"；返回 dict 表示"尝试过了"：
    * ok=True  ⇒ 新实例已在目标目录启动，**本进程应当退出**（桌面上那份不再运行）；
    * ok=False ⇒ 搬不动（盘只读 / 复制失败 / 启动失败），**本进程照常启动**，
      把 reason 交给界面提示一句 —— 总比把人挡在门外强。
    """
    global _LAST_RELOCATE
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None                    # 源码运行：不搬
    if os.environ.get(RELOCATE_ENV):
        return None                    # 新实例带着标记启动，别再搬
    try:
        exe = Path(sys.executable).resolve()
    except OSError:
        return None
    desktop = desktop_dir()
    if desktop is None or exe.parent != desktop:
        return None                    # 不在桌面 ⇒ 不归这里管

    result: dict[str, Any] = {"ok": False, "from": str(exe)}
    folder = target_dir()
    if folder is None:
        result["reason"] = "D 盘和 C 盘都写不进去（卷只读或被安全策略限制）"
        _LAST_RELOCATE = result
        return result

    new_exe = folder / exe.name
    try:
        if new_exe.resolve() != exe:
            shutil.copy2(exe, new_exe)
    except OSError as exc:
        result["reason"] = f"复制 exe 到 {folder} 失败：{exc}"
        _write_relocate_log(folder, result["reason"])
        _LAST_RELOCATE = result
        return result

    shortcut = desktop / SHORTCUT_NAME
    shortcut_ok = create_shortcut(shortcut, new_exe)

    env = dict(os.environ)
    env[RELOCATE_ENV] = "1"
    env[RELOCATE_FROM_ENV] = str(exe)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [str(new_exe)],
            cwd=str(folder),
            env=env,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        result["reason"] = f"启动新实例失败：{exc}"
        _write_relocate_log(folder, result["reason"])
        _LAST_RELOCATE = result
        return result

    result.update({
        "ok": True,
        "dir": str(folder),
        "exe": str(new_exe),
        "shortcut": str(shortcut),
        "shortcut_ok": shortcut_ok,
    })
    _write_relocate_log(
        folder,
        f"已从桌面搬来：{exe} → {new_exe}；快捷方式={'ok' if shortcut_ok else '失败'}",
    )
    _LAST_RELOCATE = result
    return result


# ---------------------------------------------------------------- 收拾现场
def schedule_source_cleanup() -> None:
    """新实例启动后，把**桌面上那份旧 exe**删掉（用户 2026-10-26 追加要求）。

    只有"搬家启动"的新实例才做（靠 §RELOCATE_FROM_ENV§ 认出自己是被搬过来的），
    而且三重闸门：那条路径必须在桌面目录里、必须不是自己、必须真的能删。

    为什么放后台线程：桌面那份进程刚刚才被要求退出，文件很可能还被占着 ——
    重试到它松手（最多 §CLEANUP_RETRIES × CLEANUP_INTERVAL§ 秒），
    **绝不阻塞界面**；删不掉就留着，用户手动删也一样，不值得为它卡启动。
    """
    raw = os.environ.pop(RELOCATE_FROM_ENV, None)   # 用后即清，别让孙进程继承
    if not raw or os.name != "nt":
        return
    source = Path(raw)
    desktop = desktop_dir()
    if desktop is None:
        return
    try:
        if source.parent.resolve() != desktop:
            return
        if Path(sys.executable).resolve() == source.resolve():
            return                                  # 绝不会删自己
    except OSError:
        return

    def _worker() -> None:
        for _ in range(CLEANUP_RETRIES):
            try:
                if not source.exists():
                    return
                source.unlink()
                return
            except OSError:
                time.sleep(CLEANUP_INTERVAL)

    threading.Thread(target=_worker, daemon=True).start()
