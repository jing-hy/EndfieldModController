"""程序自我更新：对比 GitHub release 的版本号，可一键下载并在退出后替换自己。

Windows 下**正在运行的 exe 无法覆盖自己**，所以流程是：

1. 检查：`releases/latest` 拿 tag → 与本机 `version.__version__` 比较；
2. 下载：把新 exe 下到 `runtime\\_update\\EndfieldModController.exe.new`，
   有 `digest`（sha256）就校验，避免半截文件把关卡弄坏；
3. 替换：生成一个 **VBS** 脚本——等本进程退出 → 备份旧 exe → 改名替换 →
   重启新版；任何一步失败就回滚成旧 exe；
4. 本进程退出（由 API 层负责调用 `os._exit`）。

**全程不弹 cmd 黑窗**：VBS 用 `WScript.Shell.Run(..., 0, ...)` 隐藏执行，
等进程退出的判断走 WMI 查询而不是 `tasklist`，连 cmd 都不用起。

源码运行（非 exe）时不支持自动替换，只提示用 `git pull`。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .config import AppConfig
from .version import LATEST_API, REPO_URL, USER_AGENT, __version__

UPDATE_DIR_NAME = "_update"
CHECK_CACHE_SECONDS = 6 * 3600


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def current_version() -> str:
    return __version__


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_path() -> Path | None:
    if is_frozen():
        return Path(sys.executable).resolve()
    return None


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(p) for p in parts) or (0,)


def _fetch_json(url: str, timeout: int = 25) -> dict[str, Any]:
    """GitHub 查询统一走 github 模块（token + 缓存 + 把 403 翻成人话）。"""
    from . import github

    return github.api_get(url, timeout=timeout)


def _cache_path(config: AppConfig) -> Path:
    return config.runtime_path / UPDATE_DIR_NAME / "last_check.json"


def _read_cache(config: AppConfig) -> dict[str, Any]:
    try:
        return json.loads(_cache_path(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(config: AppConfig, data: dict[str, Any]) -> None:
    try:
        path = _cache_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except OSError:
        pass


def _pick_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    """优先取 Windows 用的 exe；没有就退回包含 exe 的 zip。"""
    assets = [a for a in (release.get("assets") or []) if a.get("browser_download_url")]
    for suffix in (".exe", ".zip"):
        matches = [a for a in assets if str(a.get("name", "")).lower().endswith(suffix)]
        if matches:
            return sorted(matches, key=lambda a: int(a.get("size") or 0), reverse=True)[0]
    return None


def check_update(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    use_cache: bool = True,
    timeout: int = 25,
) -> dict[str, Any]:
    """查最新 release，返回 {current, latest, update_available, ...}。"""
    current = current_version()
    if use_cache:
        cached = _read_cache(config)
        if cached and (time.time() - float(cached.get("checked_at") or 0)) < CHECK_CACHE_SECONDS:
            cached["cached"] = True
            return cached

    result: dict[str, Any] = {
        "current": current,
        "latest": "",
        "update_available": False,
        "repo": REPO_URL,
        "checked_at": int(time.time()),
        "frozen": is_frozen(),
        "exe": str(executable_path() or ""),
    }
    from . import github

    try:
        release = _fetch_json(LATEST_API, timeout=timeout)
    except github.GitHubError as exc:
        # 限流 / 404 都已经翻译成人话，原样带给界面
        result["error"] = str(exc)
        result["checked_at"] = int(time.time())
        _write_cache(config, result)
        return result
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        result["error"] = f"查询失败：{exc}"
        return result

    tag = str(release.get("tag_name") or "").lstrip("vV")
    asset = _pick_asset(release)
    result.update({
        "latest": tag,
        "tag": str(release.get("tag_name") or ""),
        "name": str(release.get("name") or ""),
        "notes": str(release.get("body") or "")[:4000],
        "published": str(release.get("published_at") or ""),
        "html_url": str(release.get("html_url") or REPO_URL),
        "update_available": bool(tag) and _version_tuple(tag) > _version_tuple(current),
        "asset": str((asset or {}).get("name") or ""),
        "asset_size": int((asset or {}).get("size") or 0),
        "download_url": str((asset or {}).get("browser_download_url") or ""),
        "digest": str((asset or {}).get("digest") or ""),
    })
    _write_cache(config, result)
    _log(log, f"检查更新：本机 v{current}，最新 v{tag or '?'}"
              + ("（有新版）" if result["update_available"] else "（已是最新）"))
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(
    config: AppConfig,
    *,
    url: str = "",
    digest: str = "",
    log: Callable[[str], None] | None = None,
    timeout: int = 900,
) -> dict[str, Any]:
    """下载新版本到 runtime\\_update\\，校验后返回路径。"""
    if not url:
        report = check_update(config, log=log, use_cache=False)
        url = report.get("download_url", "")
        digest = digest or report.get("digest", "")
    if not url:
        return {"ok": False, "message": "没有拿到可用的下载地址"}

    target_dir = config.runtime_path / UPDATE_DIR_NAME
    target_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urlparse(url).path).name or "update.bin"
    target = target_dir / name
    _log(log, f"开始下载更新包 {name}")
    # 走 fastnet：慢/抖时临时并发，直连不通时临时换镜像线路；digest 直接交给它校验
    from . import fastnet

    report = fastnet.download(
        url, target, log=log, timeout=min(timeout, 60),
        expected_sha256=digest.replace("sha256:", "").strip(),
    )
    if not report.ok:
        return {"ok": False, "message": f"下载失败：{report.message}"}
    if report.line and report.line != "直连":
        _log(log, f"（本次经镜像线路 {report.line} 下载，已用 Release 提供的 sha256 校验通过）")

    actual = _sha256(target)
    size = target.stat().st_size
    if size < 1024 * 1024:
        return {"ok": False, "message": f"更新包异常小（{size} 字节），已放弃", "path": str(target)}
    _log(log, f"下载完成：{target}（{size // 1048576} MB，"
              f"{report.seconds:.1f}s / {report.mbps:.2f} MB/s"
              + (f"，并发 {report.threads}" if report.boosted else "") + "）")
    return {
        "ok": True, "path": str(target), "size": size, "sha256": actual, "name": name,
        "line": report.line, "mbps": round(report.mbps, 2), "boosted": report.boosted,
    }


VBS_TEMPLATE = r'''Option Explicit
' EndfieldModController 自我更新脚本（由程序生成，运行完自删）
' 全程隐藏执行：等进程退出用 WMI 查询，不调用 tasklist，不弹任何黑窗。
Dim fso, sh, wmi, procs, target, newFile, backup, i, failed
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
target  = "{target}"
newFile = "{newfile}"
backup  = target & ".old"
failed  = False

' 1) 等主程序退出（最多 60 秒）
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
For i = 1 To 120
  Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='{procname}'")
  If procs.Count = 0 Then Exit For
  WScript.Sleep 500
Next
WScript.Sleep 800

' 2) 备份旧文件 → 替换成新文件
On Error Resume Next
If fso.FileExists(backup) Then fso.DeleteFile backup, True
Err.Clear
fso.MoveFile target, backup
If Err.Number <> 0 Then
  Err.Clear
  fso.CopyFile target, backup, True
End If
Err.Clear
fso.CopyFile newFile, target, True
If Err.Number <> 0 Then failed = True

' 3) 失败则回滚
If failed Then
  Err.Clear
  If fso.FileExists(target) Then fso.DeleteFile target, True
  If fso.FileExists(backup) Then fso.MoveFile backup, target
  Dim ts
  On Error Resume Next
  Set ts = fso.CreateTextFile(fso.GetParentFolderName(target) & "\update-failed.txt", True)
  If Err.Number = 0 Then
    ts.WriteLine "更新失败（" & Now & "），已自动回滚为原版本。"
    ts.Close
  End If
  sh.Run """" & target & """", 1, False
  fso.DeleteFile WScript.ScriptFullName, True
  WScript.Quit 1
End If

' 4) 启动新版并清理
sh.Run """" & target & """", 1, False
WScript.Sleep 3000
On Error Resume Next
fso.DeleteFile backup, True
fso.DeleteFile newFile, True
fso.DeleteFile WScript.ScriptFullName, True
'''


def apply_update(
    config: AppConfig,
    *,
    archive: str = "",
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把下载好的更新包替换到当前 exe（通过 VBS 在退出后完成）。"""
    if not is_frozen():
        return {
            "ok": False,
            "message": "源码运行模式不支持自动替换，请到项目目录执行 git pull 后重启。",
            "repo": REPO_URL,
        }
    target = executable_path()
    if target is None or not target.is_file():
        return {"ok": False, "message": "找不到当前 exe 路径"}

    payload = Path(archive) if archive else None
    if payload is None:
        update_dir = config.runtime_path / UPDATE_DIR_NAME
        candidates = sorted(
            (p for p in update_dir.glob("EndfieldModController*") if p.suffix.lower() in {".exe", ".zip"}),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ) if update_dir.is_dir() else []
        payload = candidates[0] if candidates else None
    if payload is None or not payload.is_file():
        return {"ok": False, "message": "没有找到已下载的更新包，请先点「下载更新」"}

    # zip 里的 exe 先解出来
    if payload.suffix.lower() == ".zip":
        import zipfile

        try:
            with zipfile.ZipFile(payload) as zf:
                members = [n for n in zf.namelist() if n.lower().endswith(".exe")]
                if not members:
                    return {"ok": False, "message": "更新包里没有 exe"}
                member = sorted(members, key=lambda n: len(n))[0]
                extracted = payload.with_name(Path(member).name)
                extracted.write_bytes(zf.read(member))
                payload = extracted
        except (zipfile.BadZipFile, OSError) as exc:
            return {"ok": False, "message": f"解包失败：{exc}"}

    new_exe = payload.with_name("EndfieldModController.exe.new")
    try:
        shutil.copy2(payload, new_exe)
    except OSError as exc:
        return {"ok": False, "message": f"写入更新文件失败：{exc}"}

    script = new_exe.with_suffix(".vbs")
    try:
        script.write_text(
            VBS_TEMPLATE.format(target=str(target), newfile=str(new_exe), procname=target.name),
            encoding="utf-8-sig", newline="\r\n",
        )
    except OSError as exc:
        return {"ok": False, "message": f"生成更新脚本失败：{exc}"}

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # wscript 跑 VBS，全程隐藏（不出现 cmd 黑窗）
        subprocess.Popen(["wscript.exe", "//nologo", str(script)], creationflags=creationflags, close_fds=True)
    except OSError as exc:
        return {"ok": False, "message": f"启动更新脚本失败：{exc}"}

    _log(log, "更新脚本已启动，程序将退出并在 2 秒后自动重启为新版")
    return {
        "ok": True,
        "restart": True,
        "target": str(target),
        "new": str(new_exe),
        "script": str(script),
        "message": f"正在替换为 v{_pending_version(config) or '新版'}，程序会自动重启。",
    }


def _pending_version(config: AppConfig) -> str:
    cached = _read_cache(config)
    return str(cached.get("latest") or "")


def cleanup_stale(config: AppConfig) -> list[str]:
    """启动时清理上次更新留下的 .old / .new / .vbs 残留。"""
    removed: list[str] = []
    exe = executable_path()
    if exe is not None:
        for suffix in (".old", ".new"):
            stale = exe.with_name(exe.name + suffix)
            if stale.is_file():
                try:
                    stale.unlink()
                    removed.append(stale.name)
                except OSError:
                    pass
    update_dir = config.runtime_path / UPDATE_DIR_NAME
    if update_dir.is_dir():
        cutoff = time.time() - 7 * 24 * 3600
        for item in update_dir.glob("*"):
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed.append(item.name)
            except OSError:
                continue
    return removed
