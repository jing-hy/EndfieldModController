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

import json
import os
import re
import shutil
import subprocess
import sys
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
    """版本比较一律走 `version.parse_version`（**全项目一套口径**，含 beta 语义）。"""
    from .version import parse_version

    return parse_version(value)


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


def _asset_rank(name: str) -> int:
    """0 = 主程序包，1 = 其它/特殊包（例如 `…-0.1.9-from-0.2.8.exe` 这种伪旧版）。"""
    return 0 if Path(str(name)).stem.lower() == "endfieldmodcontroller" else 1


def _pick_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    """优先取 Windows 用的 exe；没有就退回包含 exe 的 zip。

    **不能只按体积挑**：Release 里可能同时挂着主程序与"伪旧版"测试包
    （`EndfieldModController-0.1.9-from-0.2.8.exe`），体积最大的未必是主程序 ——
    一旦自更新装错包，版本号会倒着走。顺序是：先精确匹配主程序名 →
    再按名字里的版本号（复用 github.asset_sort_key）→ 最后才比体积。
    """
    from . import github

    assets = [a for a in (release.get("assets") or []) if a.get("browser_download_url")]
    for suffix in (".exe", ".zip"):
        matches = [a for a in assets if str(a.get("name", "")).lower().endswith(suffix)]
        if not matches:
            continue
        preferred = [a for a in matches if _asset_rank(str(a.get("name") or "")) == 0]
        return max(preferred or matches, key=github.asset_sort_key)
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
            # 缓存里的 update_available 是**按当时的版本**算出来的；本机版本可能已经变了
            # （典型：刚自更新完），所以一律用当前版本重新判定，否则会出现
            # "v0.2.0 → v0.2.0 可更新"这种自相矛盾的状态。
            latest = str(cached.get("latest") or "")
            cached["current"] = current
            cached["update_available"] = bool(latest) and _version_tuple(latest) > _version_tuple(current)
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

    # ⚠ 2026-09-30：这里以前**只打 API**（`LATEST_API`），匿名额度用尽就整条自更新检查失败、
    # 界面显示"GitHub API 额度用尽"。用户点出「额度不影响，会自动路由」—— 本程序查组件
    # release 早就"网页优先 + 镜像回退"了，只有自更新这条漏了。现在同样先走网页，
    # 再尽量用 API 把 size / digest / 正文补全（有额度时更完整，补不到就算了）。
    repo_slug = REPO_URL.rsplit("github.com/", 1)[-1].strip("/")
    release: dict[str, Any] = {}
    error = ""
    try:
        release = github.releases_latest(repo_slug, ttl=0)
    except Exception as exc:  # noqa: BLE001 —— 网页不通/仓库没 release
        error = str(exc)
    if release:
        try:
            detail = _fetch_json(LATEST_API, timeout=timeout)
            if isinstance(detail, dict):
                # ⚠️⚠️ **只有两条路线指向同一个 release 时才补全**（2026-10-06 修）。
                # `github.releases_latest`（网页/镜像路线）与官方 API 的 CDN 缓存**不同步**：
                # 实测发版 4 分钟后，网页路线已给 v1.0.20，而 API 仍返回 v1.0.19
                # ⇒ 于是拼出 `latest=1.0.20` + `asset_size=30,154,976`（v1.0.19 的大小）
                # ⇒ `_payload_stale_reason` 把**真下载好的** v1.0.20 判成"不是最新版"
                # ⇒ **永久拒绝安装**（用户现象：「一直让我重启并更新，重启后还是旧版」）。
                # 宁可不补全（少一层校验），也绝不用**另一版**的 size/digest 去卡自己。
                api_tag = str(detail.get("tag_name") or "").lstrip("vV")
                web_tag = str(release.get("tag_name") or "").lstrip("vV")
                if api_tag and web_tag and api_tag == web_tag:
                    by_name = {str(a.get("name") or ""): a for a in (detail.get("assets") or [])}
                    for asset in (release.get("assets") or []):
                        extra = by_name.get(str(asset.get("name") or ""))
                        if isinstance(extra, dict):
                            asset["size"] = int(extra.get("size") or 0)
                            asset["digest"] = str(extra.get("digest") or "")
                    for key in ("body", "name", "published_at", "html_url"):
                        if detail.get(key):
                            release.setdefault(key, detail[key])
                else:
                    _log(log, f"检查更新：两条路线版本不一致（网页 v{web_tag or '?'} / "
                              f"API v{api_tag or '?'}）→ 不补全 size/digest，只用版本号判断")
        except Exception:  # noqa: BLE001 —— 只是补全信息，失败不影响检查更新
            pass
    if not release:
        result["error"] = error or "查询失败"
        result["checked_at"] = int(time.time())
        _write_cache(config, result)
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
    """文件哈希 —— 复用 fastnet 里那份实现，不再维护第二份。"""
    from . import fastnet

    return fastnet.sha256_file(path)


def _looks_like_exe(path: Path) -> bool:
    """没有 digest 可用时的最低限度检查：必须是带 PE 头的 Windows 可执行文件。"""
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"MZ"
    except OSError:
        return False


def download_update(
    config: AppConfig,
    *,
    url: str = "",
    digest: str = "",
    log: Callable[[str], None] | None = None,
    timeout: int = 900,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """下载新版本到 runtime\\_update\\，校验后返回路径。

    progress(done, total) 会一路透传给 fastnet，界面据此画进度条。
    """
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
        progress=progress,
    )
    if not report.ok:
        return {"ok": False, "message": f"下载失败：{report.message}"}
    if report.line and report.line != "直连":
        _log(log, f"（本次经镜像线路 {report.line} 下载，已用 Release 提供的 sha256 校验通过）")

    actual = _sha256(target)
    size = target.stat().st_size
    if size < 1024 * 1024:
        return {"ok": False, "message": f"更新包异常小（{size} 字节），已放弃", "path": str(target)}
    # 独立复核一次，不依赖下游：Release 带 digest 就必须对上；没带 digest
    # 时至少要求它是真正的 PE 可执行文件（2026-10-01 修：原先算了 actual
    # 却只往界面显示，等于"没有哈希就完全没校验"）。
    expected = digest.replace("sha256:", "").strip().lower()
    if expected and actual.lower() != expected:
        try:
            target.unlink()
        except OSError:
            pass
        return {
            "ok": False,
            "message": f"更新包 sha256 校验失败（期望 {expected[:12]}…，实际 {actual[:12]}…），已删除",
            "path": str(target),
        }
    if not expected and not _looks_like_exe(target):
        try:
            target.unlink()
        except OSError:
            pass
        return {"ok": False, "message": "更新包不是有效的 Windows 可执行文件，已删除", "path": str(target)}
    _log(log, f"下载完成：{target}（{size // 1048576} MB，"
              f"{report.seconds:.1f}s / {report.mbps:.2f} MB/s"
              + (f"，并发 {report.threads}" if report.boosted else "") + "）")
    return {
        "ok": True, "path": str(target), "size": size, "sha256": actual, "name": name,
        "line": report.line, "mbps": round(report.mbps, 2), "boosted": report.boosted,
    }


VBS_TEMPLATE = r'''Option Explicit
' EndfieldModController self-update script (generated; deletes itself when done).
' Runs fully hidden: waits for the main process via WMI, never calls tasklist, no console window.
'
' NOTE: keep this file ASCII-only. Windows Script Host reads .vbs as ANSI and does NOT
' accept a UTF-8 BOM -- a BOM makes it fail with "Invalid character" (0x800A0408) on
' line 1, char 1, which is exactly what happened before (2026-09-27).
Dim fso, sh, wmi, procs, target, newFile, backup, i, failed, ts, procname, rolled_ok
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
' Paths come from the COMMAND LINE, never inlined: this script has to stay pure
' ASCII (WSH reads .vbs as ANSI), while the exe may well live under a non-ASCII
' path (C:\Users\<CJK>\...). Inlining them made write_text(encoding="ascii")
' raise UnicodeEncodeError -> self-update was completely unusable on such paths.
If WScript.Arguments.Count < 3 Then WScript.Quit 2
target   = WScript.Arguments(0)
newFile  = WScript.Arguments(1)
procname = WScript.Arguments(2)
backup   = target & ".old"
failed  = False

' 1) wait until the running program exits (up to 60 seconds)
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
For i = 1 To 120
  Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='" & procname & "'")
  If procs.Count = 0 Then Exit For
  WScript.Sleep 500
Next
' Give the OS a short moment to release the file lock before touching the exe.
' (Kept short on purpose: the longer this window, the more likely the user starts
'  the old exe while it is being swapped -- see the note in step 2.)
WScript.Sleep 1000

' 2) swap in the new file
'    Write the new build to "<target>.new" FIRST, then rename it into place.
'    Reason: a plain CopyFile over the running exe leaves a half-written file for a
'    moment, and anyone starting the exe in that window reads a broken file
'    (seen as "Failed to load Python DLL" / "Error -3 while decompressing data",
'    2026-09-27). With a rename, the target is either the complete old file or the
'    complete new file -- never a partial one.
On Error Resume Next
If fso.FileExists(backup) Then fso.DeleteFile backup, True
If fso.FileExists(target & ".new") Then fso.DeleteFile target & ".new", True
Err.Clear
fso.CopyFile newFile, target & ".new", True
If Err.Number <> 0 Then failed = True
Err.Clear
If Not failed Then
  fso.MoveFile target, backup
  If Err.Number <> 0 Then
    Err.Clear
    fso.CopyFile target, backup, True
  End If
  Err.Clear
  If fso.FileExists(target) Then fso.DeleteFile target, True
  fso.MoveFile target & ".new", target
  If Err.Number <> 0 Then failed = True
End If

' 3) on failure, roll back to the previous version
If failed Then
  Err.Clear
  If fso.FileExists(target & ".new") Then fso.DeleteFile target & ".new", True
  ' NOTE (2026-10-04): the rollback must NOT "delete target first, then MoveFile backup".
  ' It used to be exactly that, under `On Error Resume Next`: if the MoveFile failed
  ' (antivirus lock / permissions) the target was ALREADY deleted while the backup sat
  ' on disk unnoticed, and the script still wrote "Rolled back to the previous version."
  ' => the user saw "update failed" but the program file was simply gone.
  ' Now: CopyFile back over the target (the backup is left untouched), then verify the
  ' target really exists; if verification fails we write the backup path into the notice
  ' file so the user can copy it back manually, and we do NOT try to launch anything.
  rolled_ok = False
  If fso.FileExists(backup) Then
    fso.CopyFile backup, target, True
    If Err.Number = 0 Then rolled_ok = fso.FileExists(target)
    Err.Clear
  End If
  On Error Resume Next
  Set ts = fso.CreateTextFile(fso.GetParentFolderName(target) & "\update-failed.txt", True)
  If Err.Number = 0 Then
    If rolled_ok Then
      ts.WriteLine "Update failed (" & Now & "). Rolled back to the previous version."
    Else
      ts.WriteLine "Update failed (" & Now & ") and the automatic rollback did NOT succeed."
      ts.WriteLine "The previous version is still at: " & backup
      ts.WriteLine "Copy it over EndfieldModController.exe manually."
    End If
    ts.Close
  End If
  If Not rolled_ok Then
    ' Nothing to launch: exit quietly instead of silently failing to start a missing exe.
    fso.DeleteFile WScript.ScriptFullName, True
    WScript.Quit 1
  End If
  WScript.Sleep 1500
  sh.Run """" & target & """", 1, False
  ' Same wait as in step 4: the rollback branch used to delete this script and exit
  ' right away, which makes the new instance report
  ' "invalid originating onefile parent process (PID not found)".
  For i = 1 To 40
    Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='" & procname & "'")
    If procs.Count > 0 Then Exit For
    WScript.Sleep 1000
  Next
  WScript.Sleep 15000
  fso.DeleteFile WScript.ScriptFullName, True
  WScript.Quit 1
End If

' 4) start the new version and clean up
' The exe was renamed into place (not half-written), so a short settle is enough.
WScript.Sleep 1000
sh.Run """" & target & """", 1, False

' PyInstaller 6.x (onefile) validates the PARENT process of the child it spawns --
' see pyinstaller issue #9513 / PR #9520: having another program in between breaks
' the check. The chain here is: old exe -> this script (wscript.exe) -> new exe.
' If this script exits while the new instance's bootloader is still unpacking, the
' new instance shows "Security validation failure: invalid originating onefile
' parent process (PID not found)!". The 2026-10-01 occurrence was NOT fixed by
' waiting longer -- the real cause was inherited _MEIPASS2/_PYI_* env vars in the
' launching process (see apply_update()). Still, keep this script alive until the
' new build is really up: a finished onefile start shows TWO processes (parent
' bootloader + the child it spawns after unpacking), so wait for count >= 2.
' (This template must stay pure ASCII: WSH reads .vbs as ANSI. Comments included!)
For i = 1 To 120
  Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='" & procname & "'")
  If procs.Count >= 2 Then Exit For
  WScript.Sleep 1000
Next
WScript.Sleep 5000
On Error Resume Next
fso.DeleteFile backup, True
fso.DeleteFile newFile, True
fso.DeleteFile target & ".new", True
' Also delete the ORIGINAL download (newFile is "<payload>.new"): leaving it in
' runtime\_update\ makes pending_payload() report a pending update forever,
' so the UI keeps saying "restart to finish updating" after a successful swap
' (2026-10-06, user: "clicked restart but it still says update finished").
If InStr(newFile, ".new") > 0 Then
  fso.DeleteFile Left(newFile, Len(newFile) - 4), True
End If
fso.DeleteFile WScript.ScriptFullName, True
'''


def _apply_fail(log: Callable[[str], None] | None, message: str) -> dict[str, Any]:
    """`apply_update` 的失败出口。

    ⚠️ **每条失败都必须落日志**（2026-10-06）：原来所有失败分支都只
    `return {"ok": False, "message": …}`，一个字都不写日志 —— 于是用户点了「重启安装」
    没反应时，事后连"是哪一步拦下的"都查不出来（反馈者原话：「手动按重启也没用」，
    而我们手上只有一句"下载完成"）。
    """
    _log(log, f"自更新：替换未执行 —— {message}")
    return {"ok": False, "message": message}


def apply_update(
    config: AppConfig,
    *,
    archive: str = "",
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把下载好的更新包替换到当前 exe（通过 VBS 在退出后完成）。"""
    if not is_frozen():
        result = _apply_fail(log, "当前是源码运行模式，不支持自动替换（改用 git pull 后重启）")
        result["repo"] = REPO_URL
        return result
    target = executable_path()
    if target is None or not target.is_file():
        return _apply_fail(log, "找不到当前 exe 路径")

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
        return _apply_fail(log, "没有找到已下载的更新包（_update 目录里没有 exe/zip）")
    # 装之前严格核一遍：这个包必须是"当前 latest 那一份"（size + sha256）。
    # 2026-09-30 实测 bug：`_update\` 里躺着更早下载的 0.6.0，却被当成 0.6.1 装上，
    # 结果"装了还是旧版 → 又提示 → 又装"。这里直接拒绝，让用户重新下载。
    if payload.suffix.lower() == ".exe":
        reason = _payload_stale_reason(config, payload, check_hash=True)
        if reason:
            result = _apply_fail(log, f"已下载的更新包不是最新版：{reason}")
            result["stale"] = True
            return result

    # zip 里的 exe 先解出来
    if payload.suffix.lower() == ".zip":
        import zipfile

        try:
            with zipfile.ZipFile(payload) as zf:
                members = [n for n in zf.namelist() if n.lower().endswith(".exe")]
                if not members:
                    return _apply_fail(log, "更新包里没有 exe")
                member = sorted(members, key=lambda n: len(n))[0]
                extracted = payload.with_name(Path(member).name)
                extracted.write_bytes(zf.read(member))
                payload = extracted
        except (zipfile.BadZipFile, OSError) as exc:
            return _apply_fail(log, f"解包失败：{exc}")

    new_exe = payload.with_name("EndfieldModController.exe.new")
    try:
        shutil.copy2(payload, new_exe)
    except OSError as exc:
        return _apply_fail(log, f"写入更新文件失败：{exc}")

    script = new_exe.with_suffix(".vbs")
    try:
        # **必须 ASCII + 无 BOM**：Windows Script Host 按 ANSI 读 .vbs，遇到 UTF-8 BOM
        # 会在第 1 行第 1 个字符报「无效字符 800A0408」（2026-09-27 实测踩到）。
        # 三个路径改为命令行参数传给脚本（见模板头部注释），所以这里不再 .format()：
        # 既不会因路径含中文抛 UnicodeEncodeError，也不会因路径含 {} 被 format 解析。
        #
        # 2026-10-01 加保险：模板里**连注释都不能出现非 ASCII**（我写中文注释就踩了，
        # 结果 write_text 抛 UnicodeEncodeError → 下载成功却"替换失败"，界面报
        # "完成，但有 1 项失败"）。回归测试见 tests/test_selfupdate_template.py。
        VBS_TEMPLATE.encode("ascii")
    except UnicodeEncodeError as exc:
        return _apply_fail(log, f"更新脚本模板含非 ASCII 字符（程序缺陷，请反馈）：{exc}")
    try:
        script.write_text(VBS_TEMPLATE, encoding="ascii", newline="\r\n")
    except OSError as exc:
        return _apply_fail(log, f"生成更新脚本失败：{exc}")

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # **先清掉 PyInstaller 的 onefile 环境变量**（2026-10-01 读 bootloader 源码确认）：
        # 本进程是 onefile 的"子进程"，环境里带着 `_MEIPASS2` / `_PYI_*`；它们会被
        # wscript 继承、再传给新 exe —— 而 PyInstaller 只在"application home dir 是
        # 继承来的"（即看到 `_MEIPASS2`）时才去校验"originating onefile parent PID"，
        # 且该校验在**提权运行**时强制启用（我们的 exe 带 --uac-admin）。于是新 exe 把
        # 自己当成子进程、去找一个早已退出的父 PID，弹出
        # `Security validation failure: invalid originating onefile parent process
        # (PID not found)!`。清掉后新 exe 以"父 bootloader"身份干净启动，不进这段校验。
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(("_MEI", "_PYI"))}
        # wscript 跑 VBS，全程隐藏（不出现 cmd 黑窗）；路径走参数，中文路径同样可用
        subprocess.Popen(
            ["wscript.exe", "//nologo", str(script), str(target), str(new_exe), target.name],
            creationflags=creationflags,
            close_fds=True,
            env=env,
        )
    except OSError as exc:
        return _apply_fail(log, f"启动更新脚本失败（wscript 没起来）：{exc}")

    # 记下"这一份装过"（见 `pending_payload` 里"装过却没生效"的判据）
    _write_applied(config, payload, _pending_version(config))
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


def _payload_stale_reason(config: AppConfig, payload: Path, *, check_hash: bool = False) -> str:
    """这个"已下载的更新包"已经过时了吗？是就返回原因，否则返回空串。

    **为什么必须查**（2026-09-30 实测的 bug）：`pending_payload()` 原先只比较
    「latest 比当前版本新」，**完全没看 `_update\\` 里那个包到底是哪一版** —— 于是把
    更早下载的 0.6.0（29,445,166 B）当成 v0.6.1 装上去，重启后还是旧版，又提示、又装、
    又旧；用户看到的就是「**拉取的都是 0.6.0**」＋「打开又提示有 0.6.1」＋「反复弹弹窗」。

    判据用 `check_update()` 存下来的同一份缓存：`latest` 与它对应的 `asset_size` / `digest`。
    `check_hash=False` 时只比大小（微秒级，可放在 `get_state()` 这种频繁路径上）；
    真要安装前再 `check_hash=True` 严格核一遍内容。
    """
    cached = _read_cache(config)
    latest = str(cached.get("latest") or "")
    expected_size = int(cached.get("asset_size") or 0)
    expected_sha = str(cached.get("digest") or "").replace("sha256:", "").strip().lower()
    try:
        actual_size = payload.stat().st_size
    except OSError as exc:
        return f"读不到已下载的包：{exc}"
    if expected_size and actual_size != expected_size:
        return (f"已下载的包是 {actual_size:,} 字节，而 v{latest} 是 {expected_size:,} 字节"
                f"（多半是更早版本留下的旧包）")
    if check_hash and expected_sha:
        if _sha256(payload).lower() != expected_sha:
            return f"已下载的包与 v{latest} 的 sha256 不一致（内容不是这一版）"
    return ""


APPLIED_NAME = "applied.json"


def _applied_path(config: AppConfig) -> Path:
    return config.runtime_path / UPDATE_DIR_NAME / APPLIED_NAME


def _read_applied(config: AppConfig) -> dict[str, Any]:
    """上一次"点重启安装"时到底装了哪一份载荷（没有记录就返回空 dict）。"""
    try:
        data = json.loads(_applied_path(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_applied(config: AppConfig, payload: Path, tag: str) -> None:
    try:
        stat = payload.stat()
    except OSError:
        return
    try:
        _applied_path(config).write_text(json.dumps({
            "tag": tag,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "sha256": _sha256(payload),
            "at": int(time.time()),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _payload_identity(payload: Path) -> tuple[int, int] | None:
    """载荷的轻量身份（size + mtime，微秒级）—— 判"是不是同一份"够用且不读大文件。"""
    try:
        stat = payload.stat()
    except OSError:
        return None
    return (stat.st_size, int(stat.st_mtime))


def pending_payload(config: AppConfig) -> dict[str, Any]:
    """有没有"已下载但还没安装"的更新包。

    用户 2026-10-01 要求「下载完应该跳一个弹窗，让用户选择是立即重启程序更新还是稍后」，
    选"稍后"的包就留在这里；下次启动时由前端根据本函数的结果再问一次。
    """
    payload = Path(config.runtime_path) / "_update" / "EndfieldModController.exe"
    if not payload.is_file():
        return {"pending": False}
    from .version import __version__

    latest = _pending_version(config)
    if latest and _version_tuple(latest) <= _version_tuple(__version__):
        # 已经是最新（或本地更高）→ 这个包没必要再装
        return {"pending": False, "stale": True, "latest": latest}
    # 还必须确认这个包**就是 latest 那一份**（只比"latest 更新"是不够的 —— 见
    # `_payload_stale_reason` 里那个"装了还是旧版、反复提示"的实测 bug）
    reason = _payload_stale_reason(config, payload)
    if reason:
        return {"pending": False, "stale": True, "latest": latest, "reason": reason}
    # ⚠️ **"装过却没生效"就不再提示**（2026-10-06）：发布出去的那个 exe 可能**自身带着
    #    beta 标识**（打包流程问题）⇒ 装上后版本号没变 ⇒ 又提示 ⇒ **无限循环**，用户
    #    点多少次都没用。判据 = 这份载荷与**上次实际安装的那一份**完全相同（size + mtime）。
    #    一旦发布方**重打了附件**（文件变了），判据自动失效 ⇒ **仍能正常更新**（自愈保留）。
    applied = _read_applied(config)
    identity = _payload_identity(payload)
    if applied and identity is not None and (applied.get("size"), applied.get("mtime")) == identity:
        return {"pending": False, "ineffective": True, "latest": latest,
                "reason": "上一次安装的就是这一份，但装完版本号没有变 —— "
                          "说明发布出来的这个版本自身带了 beta 标识，重复安装也没用"}
    return {"pending": True, "latest": latest, "path": str(payload),
            "size": payload.stat().st_size}


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
        # 与当前 latest 对不上的旧包**立刻**清掉（2026-09-30：正是它让用户看到
        # "反复弹窗、装的还是旧版"）—— 别等下面那条"7 天"规则。
        candidate = update_dir / "EndfieldModController.exe"
        if candidate.is_file():
            reason = _payload_stale_reason(config, candidate)
            if reason:
                try:
                    candidate.unlink()
                    removed.append(candidate.name)
                except OSError:
                    pass
        cutoff = time.time() - 7 * 24 * 3600
        for item in update_dir.glob("*"):
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed.append(item.name)
            except OSError:
                continue
    return removed
