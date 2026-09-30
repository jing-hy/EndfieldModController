"""Endfield Poser（摆姿 / MMD 播放插件）集成。

Poser 与乳摇（SecondaryMotion）走的是**同一套注入机制**：游戏目录里的 proxy DLL
（`d3dcompiler_47.dll`，包内带 `vulkan-1.dll` 时也一并装）会把
``<游戏目录>\\plugin\\*.dll`` **全部**加载进游戏进程，插件本体就是
``plugin\\poser.dll``。所以两个插件能同时生效 —— 谁提供 proxy 都能把对方的插件
DLL 加载起来（这一点两边源码/二进制都核实过，见 2026-10-01 的可行性勘查）。

本模块只做五件事：报状态、补齐（下载 + 调**它自己的**安装向导）、开关（重命名
`poser.dll`，可逆）、卸载（走向导）、只读读取它内置的 localhost 摆姿页状态。

三条硬约定：
* **绝不自己写游戏目录的 proxy / poser.dll** —— 一律调用上游
  ``tools\\deploy.ps1 -GameDir <游戏目录> -Action Install|Uninstall``：它自带 PE/x64
  校验、原子写、失败回滚、安装记录，以及"plugin 里还有别的插件就不还原 proxy"保护。
* **loader 归属 = Poser 优先**：它的 proxy 会加载 `plugin` 下所有 dll（含 `sbm.dll`），
  所以初始化时**先**补齐 Poser，再让乳摇走"已注入"分支（见 initialize.py 的顺序）。
* **只读**：它的摆姿 Web UI（http://127.0.0.1:18923）只 GET，不代它下发写操作。

上游许可 **AGPL-3.0**（fork 自 honxi1/Endfield-Poser）：本程序**不随包分发**它的
二进制，只从官方 Release 下载并调用它自己的安装向导；协议由游戏内首次运行时确认。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

# ---------------------------------------------------------------- 常量
REPO = "OedoSoldier/Endfield-Poser"
UPSTREAM_URL = f"https://github.com/{REPO}"
# 资产选择：只要 `-win64.zip`（自动排除 `-source.zip` 与 GitHub 生成的源码包）
ASSET_PATTERN = "win64.zip"
LICENSE_ID = "AGPL-3.0"
LICENSE_NOTE = (
    "上游 OedoSoldier/Endfield-Poser（honxi1/Endfield-Poser 的功能分支，AGPL-3.0）。"
    "本程序只下载它的官方安装包并调用它自己的安装向导，不随包分发其二进制、不修改其内容；"
    "使用前请在游戏内确认它的《用户协议》，并按鹰角官方创作限制使用。"
)

PLUGIN_DLL = "poser.dll"
PLUGIN_DIR_NAME = "plugin"
INSTALL_RECORD_NAME = "poser-install.json"
FACE_RECORD_NAME = "character-faces-install.json"
FACE_DIR_NAME = "character-faces"
MMD_DIR_NAME = "mmd"
POSE_DIR_NAME = "poses"
BACKUP_DIR_NAME = "poser-backups"
LOG_NAME = "poser_log.txt"
PARKED_SUFFIX = ".endfieldmodcontroller.disabled"

PROXY_NAMES = ("d3dcompiler_47.dll", "vulkan-1.dll")
# 需要被上游向导"认领"的文件（与 deploy.ps1 的 ownedNames 一致）
OWNED_NAMES = (f"{PLUGIN_DIR_NAME}\\{PLUGIN_DLL}", PROXY_NAMES[0], PROXY_NAMES[1])

GAME_EXE = "Endfield.exe"
WEB_PORT = 18923
WEB_UI_URL = f"http://127.0.0.1:{WEB_PORT}"
WEB_TIMEOUT = 1.5
WIZARD_TIMEOUT = 600

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        log(message)


# ---------------------------------------------------------------- 基础路径
def game_dir(config: AppConfig) -> Path | None:
    from . import reshade_integration

    return reshade_integration.detect_game_dir(config)


def pack_root(config: AppConfig) -> Path | None:
    """安装包目录（`<主路径>/runtime/poser`，用户在设置页可改）。"""
    root = config.poser_path
    return root if root.is_dir() else None


def _payload_present(root: Path | None) -> bool:
    """安装包是否已经被解压出来（含 plugin\\poser.dll）。"""
    if root is None or not root.is_dir():
        return False
    return (root / PLUGIN_DIR_NAME / PLUGIN_DLL).is_file() or (root / PLUGIN_DLL).is_file()


def _pack_version(root: Path | None) -> str:
    """安装包版本：优先读 runtime_deps 写的 marker（记录上游 tag）。"""
    if root is None:
        return ""
    from .runtime_deps import MARKER_NAME

    marker = root / MARKER_NAME
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return str(data["version"])
        except (OSError, json.JSONDecodeError):
            pass
    version_file = root / "version.txt"
    if version_file.is_file():
        try:
            return version_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
    return ""


def _sha256(path: Path) -> str:
    from . import fsutil

    try:
        return fsutil.sha256_file(path)
    except OSError:
        return ""


def _game_running() -> int:
    """游戏是否在跑（上游向导会拒绝在游戏运行时安装）。"""
    try:
        from . import injector

        return int(injector.find_process_id(GAME_EXE))
    except Exception:  # noqa: BLE001 —— 非 Windows / 探测失败都按"没在跑"处理
        return 0


def _decode_output(raw: bytes) -> str:
    """PowerShell 输出在中文 Windows 上可能是 GBK，逐个编码试。"""
    for encoding in ("utf-8", "mbcs", "gbk"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _read_install_record(game: Path) -> dict[str, Any]:
    """读上游向导写的安装记录 `plugin\\poser-install.json`（状态唯一真源）。"""
    path = game / PLUGIN_DIR_NAME / INSTALL_RECORD_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("product") != "Endfield Poser":
        return {}
    return data


def _record_consistency(game: Path, record: dict[str, Any]) -> bool | None:
    """记录里 `plugin\\poser.dll` 的 sha256 是否与实际文件一致。

    返回 None = 记录里没有这一条（老版本记录或手工装的），不做判断。
    """
    entries = record.get("files") or []
    expected = ""
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("path") or "").replace("/", "\\").lower() == \
                f"{PLUGIN_DIR_NAME}\\{PLUGIN_DLL}".lower():
            expected = str(entry.get("installed_sha256") or "")
            break
    if not expected:
        return None
    actual = _sha256(game / PLUGIN_DIR_NAME / PLUGIN_DLL)
    if not actual:
        return None
    return actual.lower() == expected.lower()


# ---------------------------------------------------------------- 状态
def status(config: AppConfig, *, include_web: bool = True) -> dict[str, Any]:
    """Poser 的完整状态，供 UI / 自检使用。"""
    from . import reshade_integration

    root = config.poser_path
    game = game_dir(config)
    data: dict[str, Any] = {
        "pack_dir": str(root),
        "pack_ready": _payload_present(root),
        "pack_version": _pack_version(root),
        "upstream": UPSTREAM_URL,
        "license": LICENSE_ID,
        "license_note": LICENSE_NOTE,
        "install_dir": str(game / PLUGIN_DIR_NAME) if game else "",
        "game_dir": str(game) if game else "",
        "installed": False,
        "enabled": False,
        "parked": False,
        "loader_kind": "",
        "proxy_owned": False,
        "record_consistent": None,
        "installed_at": "",
        "face_count": 0,
        "pose_count": 0,
        "other_plugins": [],
        "proxies": {},
        "log_tail": [],
        "web": {"url": WEB_UI_URL, "reachable": False, "reason": ""},
    }
    if game is None:
        data["web"] = web_status() if include_web else data["web"]
        return data

    plugin_dir = game / PLUGIN_DIR_NAME
    target = plugin_dir / PLUGIN_DLL
    parked = plugin_dir / (PLUGIN_DLL + PARKED_SUFFIX)
    data["installed"] = target.is_file()
    data["parked"] = parked.is_file()
    data["enabled"] = target.is_file()

    kind_fn = getattr(reshade_integration, "loader_kind", None)
    data["loader_kind"] = kind_fn(game / PROXY_NAMES[0]) if callable(kind_fn) else ""

    for name in PROXY_NAMES:
        path = game / name
        backup = game / f"{name}.bak"
        size = path.stat().st_size if path.is_file() else 0
        data["proxies"][name] = {
            "exists": path.is_file(),
            "size": size,
            "kind": kind_fn(path) if callable(kind_fn) else "",
            "backup": backup.is_file(),
        }

    record = _read_install_record(game)
    data["record"] = bool(record)
    data["installed_at"] = str(record.get("installed_at") or "")
    data["record_consistent"] = _record_consistency(game, record) if record else None
    lowered = {str(entry.get("path") or "").replace("/", "\\").lower()
               for entry in (record.get("files") or []) if isinstance(entry, dict)}
    data["proxy_owned"] = PROXY_NAMES[0].lower() in lowered

    face_dir = plugin_dir / MMD_DIR_NAME / FACE_DIR_NAME
    if face_dir.is_dir():
        data["face_count"] = sum(1 for item in face_dir.glob("*.face.json") if item.is_file())
    pose_dir = plugin_dir / POSE_DIR_NAME
    if pose_dir.is_dir():
        data["pose_count"] = sum(1 for item in pose_dir.iterdir() if item.is_file())

    try:
        data["other_plugins"] = sorted(
            item.name for item in plugin_dir.glob("*.dll")
            if item.is_file() and item.name.lower() != PLUGIN_DLL.lower()
        )
    except OSError:
        data["other_plugins"] = []

    log_file = plugin_dir / LOG_NAME
    if log_file.is_file():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            data["log_tail"] = [line for line in lines[-6:]]
        except OSError:
            pass

    if include_web:
        data["web"] = web_status()
    return data


def web_status(*, timeout: float = WEB_TIMEOUT) -> dict[str, Any]:
    """**只读**读取 Poser 内置摆姿页的状态（不调用任何写接口）。

    未在游戏内确认它的《用户协议》时，非只读接口返回 403 —— 我们只问
    `/api/status`（只读、不受协议门限制），读不到就如实说明原因。
    """
    result: dict[str, Any] = {"url": WEB_UI_URL, "reachable": False, "reason": "",
                              "frozen": None, "model": "", "mmd_active": False,
                              "mmd_file": "", "face_ready": None}

    def get(path: str) -> Any:
        request = urllib.request.Request(WEB_UI_URL + path, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    try:
        payload = get("/api/status")
    except urllib.error.HTTPError as exc:
        result["reason"] = ("游戏内还没确认 Poser 的《用户协议》" if exc.code == 403
                            else f"HTTP {exc.code}")
        return result
    except Exception:  # noqa: BLE001 —— 游戏没跑 / 端口被占 / 超时，都只是"不可达"
        result["reason"] = "读不到（游戏未运行、面板未就绪或端口被占用）"
        return result

    result["reachable"] = True
    if isinstance(payload, dict):
        result["frozen"] = payload.get("frozen")
    for path, key in (("/api/mmd/status", "mmd"), ("/api/face", "face")):
        try:
            payload = get(path)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue
        if key == "mmd":
            result["mmd_active"] = bool(payload.get("active"))
            result["mmd_file"] = str(payload.get("file") or "")
            if payload.get("model"):
                result["model"] = str(payload.get("model"))
        else:
            result["face_ready"] = bool(payload.get("ready"))
            if payload.get("model") and not result["model"]:
                result["model"] = str(payload.get("model"))
    return result


# ---------------------------------------------------------------- 安装 / 开关 / 卸载
def ensure_pack(config: AppConfig, log: Log = None, *, force: bool = False) -> dict[str, Any]:
    """确保安装包就位（下载走 runtime_deps，与 XXMI/EFMI 同一条链路）。"""
    from . import runtime_deps

    try:
        result = runtime_deps.ensure_poser(config, force=force)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Poser 安装包下载失败: {exc}"}
    if str(result.status) in {"installed", "up_to_date", "present"}:
        _log(log, f"Poser 安装包: {result.status} {result.version}（{result.path}）")
        return {"ok": True, "status": result.status, "version": result.version, "path": result.path}
    return {"ok": False, "message": result.message or f"Poser 安装包未就位（{result.status}）"}


def _run_wizard(config: AppConfig, action: str, log: Log = None) -> dict[str, Any]:
    """调用**上游自己的**安装向导（安全安装.bat 的等价调用，可无人值守）。"""
    root = pack_root(config)
    if root is None:
        return {"ok": False, "message": f"找不到 Poser 安装包目录：{config.poser_path}"}
    script = root / "tools" / "deploy.ps1"
    if not script.is_file():
        return {"ok": False, "message": f"安装包里没有 tools\\deploy.ps1：{root}"}
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录"}

    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-GameDir", str(game), "-Action", action, "-SourceRoot", str(root),
    ]
    _log(log, f"Poser 向导 {action}: powershell -File tools\\deploy.ps1 -GameDir \"{game}\" -Action {action}")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=WIZARD_TIMEOUT,
            creationflags=creationflags, cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"Poser 向导超时（{WIZARD_TIMEOUT} 秒未结束）"}
    except OSError as exc:
        return {"ok": False, "message": f"启动 Poser 向导失败: {exc}"}

    out = _decode_output(completed.stdout or b"")
    err = _decode_output(completed.stderr or b"")
    tail = [line.strip() for line in (out + "\n" + err).splitlines() if line.strip()][-12:]
    for line in tail:
        _log(log, f"Poser 向导: {line}")
    if completed.returncode != 0:
        detail = "；".join(tail[-3:]) or f"退出码 {completed.returncode}"
        return {
            "ok": False,
            "message": (f"Poser 向导执行失败（exit {completed.returncode}）：{detail}。"
                        f"手动兜底：双击安装包里的「安全安装.bat」，选含 Endfield.exe 的游戏目录。"),
            "output": out, "error": err,
        }
    return {"ok": True, "message": f"Poser 向导 {action} 完成", "output": out, "error": err, "lines": tail}


def set_enabled(config: AppConfig, enabled: bool, log: Log = None) -> dict[str, Any]:
    """开关的真正落地：重命名 ``plugin\\poser.dll``（可逆、不动 proxy、不动其它插件）。

    为什么不走向导：上游向导只有 Install/Uninstall 两种动作，卸载会连带处理 proxy
    与备份；而"暂时不生效"只需要让 loader 找不到这个 dll —— loader 只扫 `*.dll`。
    """
    game = game_dir(config)
    if game is None:
        return {"ok": False, "changed": False, "message": "未定位到游戏目录"}
    plugin_dir = game / PLUGIN_DIR_NAME
    target = plugin_dir / PLUGIN_DLL
    parked = plugin_dir / (PLUGIN_DLL + PARKED_SUFFIX)

    if enabled:
        if target.is_file():
            return {"ok": True, "changed": False, "message": "Poser 已经是启用状态", "path": str(target)}
        if not parked.is_file():
            return {"ok": False, "changed": False, "message": "还没装 Poser（先在依赖页安装），没法启用"}
        try:
            os.replace(parked, target)
        except OSError as exc:
            return {"ok": False, "changed": False,
                    "message": f"启用失败（游戏在运行时文件会被占用，先退出游戏）: {exc}"}
        _log(log, f"已启用 Poser：{parked.name} → {PLUGIN_DLL}")
        return {"ok": True, "changed": True, "message": "已启用 Poser", "path": str(target)}

    if parked.is_file():
        return {"ok": True, "changed": False, "message": "Poser 已经是停用状态", "path": str(parked)}
    if not target.is_file():
        return {"ok": True, "changed": False, "message": "还没装 Poser，无需停用"}
    try:
        os.replace(target, parked)
    except OSError as exc:
        return {"ok": False, "changed": False,
                "message": f"停用失败（游戏在运行时文件会被占用，先退出游戏）: {exc}"}
    _log(log, f"已停用 Poser：{PLUGIN_DLL} → {parked.name}（loader 与其它插件保持不动）")
    return {"ok": True, "changed": True, "message": "已停用 Poser（下次进游戏不再加载）", "path": str(parked)}


def _needs_install(state: dict[str, Any]) -> tuple[bool, str]:
    """判断是否需要（重新）跑上游安装向导。"""
    if not state.get("installed"):
        if state.get("parked"):
            return False, ""            # 只是被开关停用，不是缺文件
        return True, f"plugin\\{PLUGIN_DLL} 缺失"
    if not state.get("record"):
        return True, "缺少安装记录 plugin\\poser-install.json"
    if state.get("record_consistent") is False:
        return True, "安装记录与实际文件不一致"
    if not state.get("loader_kind"):
        return True, "游戏目录里的 loader proxy 已不在位"
    if not state.get("face_count"):
        return True, "角色表情校准未随包复制"
    return False, ""


def ensure_injection(config: AppConfig, log: Log = None) -> dict[str, Any]:
    """补齐 Poser：开关停用过的先恢复；真缺东西才调上游向导安装/修复。"""
    actions: list[str] = []
    warnings: list[str] = []
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录", "actions": actions, "warnings": warnings}
    root = pack_root(config)
    if not _payload_present(root):
        return {
            "ok": False, "actions": actions, "warnings": warnings,
            "message": (f"Poser 安装包未就位（{config.poser_path}）——"
                        "依赖页点「自动安装/更新」，或直接点「一键启动」会自动下载"),
        }

    state = status(config, include_web=False)
    if state.get("parked") and not state.get("installed"):
        result = set_enabled(config, True, log=log)
        if result.get("changed"):
            actions.append("恢复 plugin\\poser.dll（上次被开关停用）")
        elif not result.get("ok"):
            warnings.append(str(result.get("message")))

    state = status(config, include_web=False)
    needs, reason = _needs_install(state)
    if needs:
        running = _game_running()
        if running:
            return {
                "ok": False, "actions": actions, "warnings": warnings, "state": state,
                "message": f"游戏正在运行（PID {running}）—— Poser 安装向导要求先完全退出游戏再装",
            }
        result = _run_wizard(config, "Install", log=log)
        if not result.get("ok"):
            message = str(result.get("message") or "Poser 安装向导失败")
            warnings.append(message)
            return {"ok": False, "actions": actions, "warnings": warnings, "state": state, "message": message}
        actions.append(f"运行 Poser 安装向导（{reason}）")

    state = status(config, include_web=False)
    problems = [
        text for text, present in (
            (f"plugin\\{PLUGIN_DLL} 不在位", state.get("installed")),
            ("loader proxy 不在位", state.get("loader_kind")),
            ("角色表情校准缺失", state.get("face_count")),
        ) if not present
    ]
    ok = not problems
    if not ok:
        warnings.append("Poser 注入不完整：" + "、".join(problems))
    return {
        "ok": ok, "actions": actions, "warnings": warnings, "state": state,
        "message": "" if ok else "；".join(warnings),
    }


def remove_injection(config: AppConfig, log: Log = None) -> dict[str, Any]:
    """卸载 Poser：走向导（它会备份；`plugin` 里还有别的插件时会保留 loader）。"""
    actions: list[str] = []
    warnings: list[str] = []
    game = game_dir(config)
    if game is None:
        return {"ok": False, "message": "未定位到游戏目录", "actions": actions, "warnings": warnings}
    running = _game_running()
    if running:
        return {"ok": False, "actions": [], "warnings": [],
                "message": f"游戏正在运行（PID {running}）—— 请先完全退出游戏再卸载 Poser"}

    state = status(config, include_web=False)
    if state.get("parked") and not state.get("installed"):
        # 停用过的副本改了名，向导按相对路径找不到它 → 先改回来再交给向导
        set_enabled(config, True, log=log)
        actions.append("先把停用副本改回 plugin\\poser.dll，再交给向导卸载")

    result = _run_wizard(config, "Uninstall", log=log)
    if not result.get("ok"):
        message = str(result.get("message") or "Poser 卸载失败")
        return {"ok": False, "actions": actions, "warnings": [message], "message": message}
    actions.append("运行 Poser 卸载向导")

    state = status(config, include_web=False)
    ok = not state.get("installed") and not state.get("parked")
    if not ok:
        warnings.append("卸载后 plugin\\poser.dll 仍在，请查看向导输出")
    return {"ok": ok, "actions": actions, "warnings": warnings, "state": state,
            "message": "" if ok else "；".join(warnings)}


def import_pack(config: AppConfig, archive: Path, log: Log = None) -> dict[str, Any]:
    """用一份现成的 zip 更新安装包本体（保留不了用户数据 —— 用户数据在游戏目录）。"""
    archive = Path(archive)
    if not archive.is_file():
        return {"ok": False, "message": f"压缩包不存在: {archive}"}
    try:
        with zipfile.ZipFile(archive) as zf:
            names = [name.replace("\\", "/") for name in zf.namelist()]
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "message": f"压缩包无法读取: {exc}"}
    if not any(name.endswith(f"{PLUGIN_DIR_NAME}/{PLUGIN_DLL}") or name.endswith(PLUGIN_DLL) for name in names):
        return {"ok": False, "message": "压缩包里没有 plugin\\poser.dll，不像 Endfield Poser 安装包"}

    from . import dependencies

    root = config.poser_path
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = config.runtime_path / f"poser_backup_{stamp}"
    try:
        if root.is_dir() and any(root.iterdir()):
            shutil.copytree(root, backup)
        dependencies.extract_archive(archive, root, strip_root=True)
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "message": f"更新失败: {exc}"}
    _log(log, f"Poser 安装包已更新到 {root}" + (f"（旧版备份 {backup.name}）" if backup.exists() else ""))
    return {"ok": True, "pack_dir": str(root),
            "backup": str(backup) if backup.exists() else "", "archive": str(archive)}


def open_web_ui(config: AppConfig | None = None) -> dict[str, Any]:
    """在默认浏览器里打开它自带的摆姿页（游戏没跑时也打开，但把原因说清楚）。"""
    info = web_status()
    try:
        import webbrowser

        opened = bool(webbrowser.open(WEB_UI_URL))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": WEB_UI_URL, "message": f"打不开浏览器: {exc}"}
    if info.get("reachable"):
        return {"ok": True, "url": WEB_UI_URL, "message": "已在浏览器打开 Poser 摆姿页"}
    return {
        "ok": opened, "url": WEB_UI_URL, "reachable": False,
        "message": ("游戏还没在跑（或面板未就绪）：先启动游戏并进入可操作角色的场景，再打开摆姿页。"
                    f"（{info.get('reason') or '读不到 18923 端口'}）"),
    }
