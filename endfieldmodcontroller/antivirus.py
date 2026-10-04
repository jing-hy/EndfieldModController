"""与杀毒软件打交道：**查它对谁动过手**，以及**把它该放过的目录加进白名单**。

为什么要单独一个模块（2026-10-04，`filewatch` 的姊妹件）：

* `filewatch` 回答的是"**我们自己的文件**是不是反复不见了"——间接推断；
* 这里回答的是"**杀毒到底动了哪个文件**"（Defender 的隔离清单里有真实路径），
  以及"**把该放过的目录加进白名单**"（自动处理，别再让用户手动点）。

用户原话：「杀毒有没有办法处理，或者检测加弹窗」+「3 默认开，在设置留个开关」。

⚠️ 边界（不越界，三条都重要）：
  1. **只处理 Windows Defender**（`Get-MpPreference` / `Add-MpPreference` /
     `Get-MpThreatDetection` / `MpCmdRun.exe`）。360 / 火绒这类**没有通用命令行排除接口**，
     对它们只保留"弹窗引导用户手动加"这条路，**绝不假装能自动处理**。
  2. **只加"我们自己的目录"**（数据根、游戏目录）。不碰系统目录、不关实时防护、
     不做"把整台机器加白"这种事。
  3. 所有操作**幂等**、失败**静默降级**（拿不到就当作"不支持"，绝不影响主流程，
     也绝不让用户看到一句"成功了"但其实没做）。

⚠️ 本模块只负责"**事实与动作**"，不负责归因：查到隔离记录就说"查到这条记录"，
   不会替用户断定"你的闪退就是它干的"（单次时间相关性不构成因果）。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import AppConfig

# Defender 的排除项命令在**没有 Defender 模块**的精简系统上会直接失败 —— 一律容错。
_PS_TIMEOUT = 30.0


def _powershell(command: str, *, timeout: float = _PS_TIMEOUT) -> tuple[str, str]:
    """跑一条 PowerShell 取 stdout；失败返回 `("", 原因)`。

    ⚠️ 三个细节都是踩过的坑：
      * **必须带 `CREATE_NO_WINDOW`** —— 用户明确要求"启动与运行过程中不允许出现任何
        cmd/控制台黑窗"；
      * 先在命令前面摆一句 `[Console]::OutputEncoding` —— 否则中文系统上拿到的是 GBK，
        `text=True` 按 UTF-8 解会得到乱码（路径都读不出来）；
      * 用 `-NoProfile`，别让用户的 profile 脚本拖慢或污染输出。
    """
    if os.name != "nt":
        return "", "非 Windows 平台"
    exe = str(Path(os.environ.get("SystemRoot") or r"C:\Windows")
              / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    if not Path(exe).is_file():
        exe = "powershell.exe"
    wrapped = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command
    try:
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", wrapped],
            capture_output=True, timeout=timeout, text=True, encoding="utf-8",
            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"[:300]
    stdout = (result.stdout or "").strip()
    if not stdout and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        return "", (stderr[:300] or f"退出码 {result.returncode}")
    return stdout, ""


def is_admin() -> bool:
    """当前进程是否提权 —— 白名单的**读**与**写**都要求管理员。

    我们是 `--uac-admin` 启动的，所以正常路径下这里是 True；非管理员时（源码直跑、
    或用户手动降权）如实返回 False，调用方据此把动作降级成"提示"而不是报错。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def targets(config: AppConfig) -> list[Path]:
    """该加进白名单的目录：**我们自己的那两个**。

    只放这两个，理由要能说清楚（这函数决定了往用户系统里写什么）：
      * **数据根** —— 我们展开组件、写 DLSS5 那几个大文件的地方（`nvngx_dlssnr.dll`
        165 MB 这类最常被误判成威胁）；
      * **游戏目录** —— 注入底座（`d3dcompiler_47.dll` / `vulkan-1.dll`）与我们铺的
        `plugin\\*.dll` 都在这儿，被杀掉就是"游戏起不来"。
    两个都拿不到时返回空列表（调用方跳过，不报错）。
    """
    found: list[Path] = []
    try:
        root = Path(config.base_dir)
        if root.is_dir():
            found.append(root)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import reshade_integration

        game = reshade_integration.detect_game_dir(config)
        if game:
            game_path = Path(game)
            if game_path.is_dir() and game_path not in found:
                found.append(game_path)
    except Exception:  # noqa: BLE001
        pass
    return found


def current_exclusions() -> tuple[list[str], str]:
    """Defender 当前的排除路径清单；失败返回 `([], 原因)`。"""
    out, err = _powershell("(Get-MpPreference -ErrorAction Stop).ExclusionPath")
    if err:
        return [], err
    paths = [line.strip() for line in out.splitlines() if line.strip()]
    return paths, ""


def status(config: AppConfig) -> dict[str, Any]:
    """给界面用的一行状态：支持吗、提权了吗、白名单里有没有我们的目录。"""
    wanted = targets(config)
    info: dict[str, Any] = {
        "supported": False,
        "admin": is_admin(),
        "exclusions": [],
        "missing": [],
        "wanted": [str(p) for p in wanted],
        "note": "",
    }
    paths, err = current_exclusions()
    if err:
        info["note"] = err
        return info
    info["supported"] = True
    info["exclusions"] = paths
    lowered = {str(p).rstrip("\\").lower() for p in paths}
    info["missing"] = [str(p) for p in wanted if str(p).rstrip("\\").lower() not in lowered]
    return info


def apply_exclusions(config: AppConfig, *, log: Callable[[str], None] | None = None,
                     paths: Sequence[Path] | None = None) -> dict[str, Any]:
    """把该放过的目录加进 Defender 白名单（**幂等**：已经在里面的不动）。

    *paths* 不给就用 `targets(config)`。

    为什么默认做（用户 2026-10-04：「3 默认开」）：这是"能自动补齐的就别让他手动"的
    又一次落地 —— 每次弹窗让用户自己去点系统设置，最后的结果就是没人去点，
    然后文件继续被吃。设置页留有开关（`config.defender_exclusions_enabled`）。

    ⚠️ 只在**确实需要**时才写（已经在清单里的跳过），并且**逐条报告结果** ——
    不允许出现"界面说加好了、其实一条都没加"。
    """
    wanted = [Path(p) for p in (paths if paths is not None else targets(config))]
    result: dict[str, Any] = {"ok": False, "added": [], "skipped": [], "failed": [], "message": ""}
    if not wanted:
        result["message"] = "没有需要加白名单的目录（数据根与游戏目录都没定位到）"
        return result
    if not is_admin():
        # 不报错 —— 这是"当前身份做不了"，如实说出来让上层降级成提示。
        result["message"] = "需要管理员权限才能修改 Defender 白名单"
        return result
    existing, err = current_exclusions()
    if err:
        result["message"] = f"读不到 Defender 排除项：{err}"
        return result
    lowered = {p.rstrip("\\").lower() for p in existing}
    for path in wanted:
        key = str(path).rstrip("\\").lower()
        if key in lowered:
            result["skipped"].append(str(path))
            continue
        safe = str(path).replace("'", "''")
        _, perr = _powershell(
            f"Add-MpPreference -ExclusionPath '{safe}' -ErrorAction Stop")
        if perr:
            result["failed"].append(f"{path}（{perr}）")
            continue
        result["added"].append(str(path))
        if log:
            try:
                log(f"已把 {path} 加进 Windows Defender 白名单")
            except Exception:  # noqa: BLE001
                pass
    result["ok"] = not result["failed"]
    if not result["added"] and not result["failed"]:
        result["message"] = "这些目录本来就在白名单里"
    return result


def recent_detections(roots: Sequence[Path], *, limit: int = 10) -> tuple[list[dict[str, Any]], str]:
    """Defender 近期的**检测/处置记录**，只留**路径落在 roots 下**的那些。

    这是整套"杀毒"线里最有价值的一条：`filewatch` 只能说"文件不见了，多半是杀毒"，
    而这里能给出**被处置文件的原路径**（`Resources` 字段）。

    ⚠️ 用 `-ErrorAction Stop` + 判空，而不是把"命令失败"当成"没有记录" ——
    "查不到"与"没有"是两回事（判据准则：拿不到证据时要说拿不到）。
    """
    out, err = _powershell(
        "Get-MpThreatDetection -ErrorAction Stop | Sort-Object InitialDetectionTime "
        f"-Descending | Select-Object -First {int(limit)} | "
        "ForEach-Object { "
        "'{0}|{1}|{2}' -f $_.InitialDetectionTime, $_.ThreatID, ($_.Resources -join ';') }"
    )
    if err:
        return [], err
    lowered = [str(p).rstrip("\\").lower() for p in roots if p]
    hits: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        when, threat, resources = parts[0].strip(), parts[1].strip(), parts[2].strip()
        files = [item.strip() for item in resources.split(";") if item.strip()]
        related = [f for f in files
                   if any(f.rstrip("\\").lower().startswith(prefix) for prefix in lowered)]
        if not related:
            continue                      # 与本项目无关的隔离记录 —— 不打扰用户
        hits.append({"time": when, "threat_id": threat, "files": related})
    return hits, ""


def restore(config: AppConfig, file_path: str, *,
            log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """把某个被 Defender 隔离的文件**从隔离区还原**回原位置。

    `MpCmdRun.exe -Restore -Path <原路径>` —— 路径就是 `recent_detections()` 给出的那个。

    ⚠️ 如实报告结果：这条命令**可能因为威胁名/路径不匹配而失败**（不同 Defender 版本
    行为有差异），失败时把原始错误原样带回给界面，**不粉饰成成功**。
    """
    if os.name != "nt":
        return {"ok": False, "message": "非 Windows 平台"}
    if not is_admin():
        return {"ok": False, "message": "需要管理员权限才能从隔离区还原"}
    mp = (Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
          / "Windows Defender" / "MpCmdRun.exe")
    if not mp.is_file():
        alt = Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "Microsoft" / "Windows Defender" / "MpCmdRun.exe"
        mp = alt if alt.is_file() else mp
    if not mp.is_file():
        return {"ok": False, "message": f"找不到 MpCmdRun.exe（{mp}）"}
    try:
        result = subprocess.run(
            [str(mp), "-Restore", "-Path", str(file_path)],
            capture_output=True, timeout=120, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"[:300]}
    ok = result.returncode == 0
    if ok and log:
        try:
            log(f"已从 Defender 隔离区还原 {file_path}")
        except Exception:  # noqa: BLE001
            pass
    message = "" if ok else ((result.stdout or "") + (result.stderr or "")).strip()[:300]
    return {"ok": ok, "message": message, "path": str(file_path)}


# ── 进程内快照 ────────────────────────────────────────────────────────────────
# 一条 Defender 查询要 1~3 秒，而界面每次刷新都会读 state ⇒ 绝不能在 `get_state()` 里
# 现算。这里缓存"本次进程的结论"，前端在启动页异步调一次 `antivirus_check()` 把它填上。
_CACHE: dict[str, Any] | None = None


def cached() -> dict[str, Any] | None:
    """读回本次进程已经算好的结论；**没算过就是 None**（不触发任何查询）。"""
    return _CACHE


def reset_cache() -> None:
    """丢掉缓存（手动改过白名单之后要让界面看到真实状态）。"""
    global _CACHE
    _CACHE = None


def scan_once(config: AppConfig, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """检测一次：**Defender 动过哪些相关文件** + **白名单缺不缺**（缺了按开关自动补）。

    返回结构里的每一项都对应界面上要显示的一句话：
      * `detections` —— 被处置文件的原路径（`filewatch` 只能猜，这里能点名）；
      * `missing` / `exclusions` / `wanted` —— 白名单现状（前端可以一键补齐）；
      * `applied` —— 本次自动加了什么（`None` = 开关关着或本来就不缺）；
      * `supported` / `admin` —— 做不到时**如实说做不到**，别给假成功。
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    info = status(config)
    hits, det_error = recent_detections([Path(p) for p in info.get("wanted") or []])

    applied: dict[str, Any] | None = None
    if getattr(config, "defender_exclusions_enabled", True) and info.get("missing"):
        # 用户 2026-10-04：「3 默认开」—— 该放过的目录不在白名单里就**直接加上**，
        # 而不是再弹一个窗等用户自己去点系统设置（"能自动补齐的就别让他手动"）。
        applied = apply_exclusions(config, log=log)
        if applied.get("added"):
            # 用刚加成功的那几条**就地更新**状态，省掉再一次 PowerShell 往返。
            added = {p.rstrip("\\").lower() for p in applied["added"]}
            info["missing"] = [p for p in (info.get("missing") or [])
                               if p.rstrip("\\").lower() not in added]
            info["exclusions"] = list(info.get("exclusions") or []) + list(applied["added"])

    _CACHE = {
        "supported": bool(info.get("supported")),
        "admin": bool(info.get("admin")),
        "wanted": info.get("wanted") or [],
        "exclusions": info.get("exclusions") or [],
        "missing": info.get("missing") or [],
        "detections": hits,
        "detections_error": det_error,
        "applied": applied,
        "note": info.get("note") or "",
    }
    return _CACHE
