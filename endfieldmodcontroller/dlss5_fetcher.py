"""DLSS5 组件的**在线自动安装**（只覆盖有公开上游的那部分）。

随包资产（`runtime_assets`）负责"没人发布过"的文件；这里负责"上游有 release
可以直接拉"的组件，让依赖页能一键安装、更新页能一键更新：

| key | 组件 | 上游 | 说明 |
| --- | --- | --- | --- |
| `reshade_base` | ReShade Addon 底座（`d3d12.dll`） | reshade.me | 官方只有安装器 exe，但它内嵌 ZIP，**用标准库 zipfile 直读 `ReShade64.dll`**，不需要 7z |
| `dlss5_feed` | `dlss5-feed.addon64` + `DLSS5_Feed.fx` | jlrouzies-fr/DLSS5-Feeder | 该 release 明确支持自动安装；缺了它 DLSS5 静默不工作 |
| `immersse` | `MartysMods_LAUNCHPAD.fx` 及其头文件/贴图 | martymcmodding/iMMERSE | 无 release，走 codeload 分支 zip；preset 要求 Launchpad 排在 DLSS5_Feed 之前 |

没有公开上游的组件（Endfield Enhancer 第一人称、ReShade 面板汉化、RenoDX-DLSS5
汉化版）不在本模块，它们和 DLSS 运行库一起**随包分发**（见 `runtime_assets`）。

所有下载都写到临时目录，校验后再替换，旧文件一律备份成 `*.bak-<时间戳>`。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import dependencies, updates
from .config import AppConfig

USER_AGENT = "EndfieldModController/0.1"
RESHADE_HOMEPAGE = "https://reshade.me/"
RESHADE_ASSET_URL = "https://reshade.me/downloads/ReShade_Setup_{version}_Addon.exe"
FEEDER_REPO = "jlrouzies-fr/DLSS5-Feeder"
IMMERSE_REPO = "martymcmodding/iMMERSE"
IMMERSE_BRANCH = "main"
MARKER_NAME = ".endfieldmodcontroller_components.json"


@dataclass
class Component:
    key: str
    display: str
    upstream: str
    required: tuple[str, ...]      # 相对 dlss5_dir
    note: str = ""


COMPONENTS: tuple[Component, ...] = (
    Component(
        "reshade_base", "ReShade 底座 (d3d12.dll)", RESHADE_HOMEPAGE,
        ("d3d12.dll",),
        "官方 Addon 版安装器内嵌 ZIP，直接取 ReShade64.dll 改名成 d3d12.dll；旧版自动备份。",
    ),
    Component(
        "dlss5_feed", "DLSS5-Feeder (dlss5-feed.addon64 + DLSS5_Feed.fx)",
        f"https://github.com/{FEEDER_REPO}",
        ("dlss5-feed.addon64", "reshade-shaders/Shaders/DLSS5_Feed.fx"),
        "DLSS5 的输入插件。缺了它面板会显示 NGX Hook: 创建0 / 成功NR帧: 0。",
    ),
    Component(
        "immersse", "iMMERSE shader (MartysMods_LAUNCHPAD.fx 等)",
        f"https://github.com/{IMMERSE_REPO}",
        ("reshade-shaders/Shaders/iMMERSE/MartysMods_LAUNCHPAD.fx",),
        "preset 要求 MartysMods_Launchpad 启用且排在 DLSS5_Feed 上方，否则 DLSS5 不工作。",
    ),
)

_BY_KEY = {component.key: component for component in COMPONENTS}


def downloadable_file_names() -> set[str]:
    """**有公开上游、能联网下载补齐**的那些文件名（小写 basename）。

    用途：判断"某个缺失文件是不是能靠下载补上"。用户 2026-10-04 实测「自动修复
    还是有一个修不好」，日志里是：
        `repair: WARN 初始化: dlss5:d3d12.dll: 缺失且找不到素材来源: d3d12.dll`
        `repair: WARN 初始化: dlss5:dlss5-feed.addon64: 缺失且找不到素材来源: dlss5-feed.addon64`
    而这两个文件**上游都有**（ReShade 官网 / DLSS5-Feeder 仓库）——
    只是"自动修复"这条路只找本地随包素材、不联网。用户的要求是：
    「**要是缺下载，应该跳转到依赖进行下载**」⇒ 需要先能**识别**出"这是缺下载"，
    再引导到依赖页（那边有完整的下载链路 + 进度 + 线路切换）。
    """
    names: set[str] = set()
    for component in COMPONENTS:
        for relative in component.required:
            names.add(relative.replace("\\", "/").rsplit("/", 1)[-1].lower())
    return names


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def _stamp() -> str:
    """备份用的时间戳，**精确到毫秒**：只到秒时同一秒内的两次写入会互相覆盖。"""
    return time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"


def _unique_sibling(path: Path) -> Path:
    """目标已存在时换一个名字（备份只增不删）。

    ⚠️ 实现收敛到 `fsutil.unique_sibling`（2026-10-04）：这里原先是同一套逻辑的第二份
    （上限还不同 —— 这里 100、fsutil 1000），"改了备份命名规则只改一处"迟早出事。
    """
    from . import fsutil

    return fsutil.unique_sibling(path)


def _version_tuple(value: str) -> tuple[int, ...]:
    """版本比较一律走 `version.parse_version`（**全项目一套口径**，含 beta 语义）。"""
    from .version import parse_version

    return parse_version(value)


# ---------------------------------------------------------------------------
# marker（记录各组件安装到哪个版本，用来判断"是否已是最新"）
# ---------------------------------------------------------------------------
def _marker_path(config: AppConfig) -> Path:
    return config.dlss5_path / MARKER_NAME


def read_marker(config: AppConfig) -> dict[str, Any]:
    path = _marker_path(config)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_marker(config: AppConfig, key: str, version: str, extra: dict[str, Any] | None = None) -> None:
    data = read_marker(config)
    entry = {"version": version, "installed_at": int(time.time())}
    if extra:
        entry.update(extra)
    data[key] = entry
    try:
        config.dlss5_path.mkdir(parents=True, exist_ok=True)
        _marker_path(config).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
def _component_state(config: AppConfig, component: Component) -> dict[str, Any]:
    missing = [rel for rel in component.required if not (config.dlss5_path / rel).is_file()]
    marker = read_marker(config).get(component.key) or {}
    return {
        "display": component.display,
        "source": component.upstream,
        "install_dir": str(config.dlss5_path),
        "present": not missing,
        "required": component.key in {"reshade_base", "dlss5_feed", "immersse"},
        "needed": bool(missing),
        "status": "已安装" if not missing else f"缺失 {len(missing)} 个文件",
        "version": str(marker.get("version") or ""),
        "enabled": True,
        "missing": missing,
        "note": component.note,
    }


def component_report(config: AppConfig) -> dict[str, dict[str, Any]]:
    """依赖页用：每个在线组件的在位状态。"""
    return {component.key: _component_state(config, component) for component in COMPONENTS}


def check_updates(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """更新页用：查各组件最新版本（联网）。"""
    report: dict[str, Any] = {"errors": []}

    try:
        latest = reshade_latest_version(log)
        current = updates.file_version(config.dlss5_dll_path) if config.dlss5_dll_path.is_file() else ""
        report["reshade_base"] = {
            "current": current,
            "latest": latest,
            "update_available": bool(latest and current and _version_tuple(latest) > _version_tuple(current)),
            "note": "官方新版可能与 DLSS5 插件不兼容（本方案实测版本为 6.8.0），更新前自动备份旧底座。",
        }
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"ReShade 检查失败: {exc}")

    for key, repo, pattern in (
        ("dlss5_feed", FEEDER_REPO, "DLSS5-Feeder"),
        ("immersse", IMMERSE_REPO, "iMMERSE"),
    ):
        try:
            if key == "dlss5_feed":
                from . import github

                release = github.releases_latest(repo)
                tag = str(release.get("tag_name") or "")
                asset = _pick_asset(release, pattern, ".zip")
                report[key] = {
                    "current": str((read_marker(config).get(key) or {}).get("version") or ""),
                    "latest": tag,
                    "update_available": bool(tag and str((read_marker(config).get(key) or {}).get("version") or "") != tag),
                    "asset": str((asset or {}).get("name") or ""),
                    "size": int((asset or {}).get("size") or 0),
                    "download_url": str((asset or {}).get("browser_download_url") or ""),
                }
            else:
                from . import github

                sha = github.latest_commit(repo, IMMERSE_BRANCH)[:12]
                current = str((read_marker(config).get(key) or {}).get("version") or "")
                report[key] = {
                    "current": current,
                    "latest": sha,
                    "update_available": bool(sha and current and sha != current),
                    "note": "仓库没有 release，按 main 分支最新提交比对。",
                }
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"{key} 检查失败: {exc}")
    return report


def _pick_asset(release: dict[str, Any], pattern: str, suffix: str) -> dict[str, Any] | None:
    assets = release.get("assets") or []
    wanted = [a for a in assets
              if pattern.lower() in str(a.get("name", "")).lower()
              and str(a.get("name", "")).lower().endswith(suffix)]
    if not wanted:
        return None
    stable = [a for a in wanted if "beta" not in str(a.get("name", "")).lower()]
    pool = stable or wanted
    return sorted(pool, key=lambda a: _version_tuple(str(a.get("name", ""))))[-1]


# ---------------------------------------------------------------------------
# 下载 / 解包工具
# ---------------------------------------------------------------------------
def reshade_latest_version(log: Callable[[str], None] | None = None) -> str:
    raw = dependencies._http_get(RESHADE_HOMEPAGE)
    assert isinstance(raw, bytes)
    html = raw.decode("utf-8", errors="replace")
    versions = re.findall(r"ReShade_Setup_(\d+\.\d+\.\d+)_Addon\.exe", html)
    if not versions:
        raise RuntimeError("reshade.me 上没有找到 Addon 安装器版本号")
    return max(versions, key=_version_tuple)


def _members_by_basename(zf: zipfile.ZipFile, basename: str) -> list[str]:
    lowered = basename.lower()
    names = [n for n in zf.namelist() if not n.endswith("/")]
    matches = [n for n in names if Path(n).name.lower() == lowered]
    return sorted(matches, key=lambda n: (n.count("/"), len(n)))


def _write_atomic(target: Path, data: bytes, *, log: Callable[[str], None] | None = None, backup: bool = True) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        try:
            if target.read_bytes() == data:
                return          # 内容一致：既不写也不备份，免得每次安装堆一堆 .bak
        except OSError:
            pass
    if backup and target.is_file():
        shutil.copy2(target, _unique_sibling(target.with_name(target.name + f".bak-{_stamp()}")))
    tmp = target.with_name(target.name + f".mc-tmp-{os.getpid()}")
    tmp.write_bytes(data)
    tmp.replace(target)
    _log(log, f"写入 {target}")


# ---------------------------------------------------------------------------
# 安装
# ---------------------------------------------------------------------------
def install_reshade_base(
    config: AppConfig,
    *,
    version: str = "",
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    target = config.dlss5_dll_path
    try:
        latest = version or reshade_latest_version(log)
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        return {"ok": False, "changed": False, "message": f"查询 ReShade 版本失败: {exc}"}

    current = updates.file_version(target) if target.is_file() else ""
    if target.is_file() and current and _version_tuple(current) >= _version_tuple(latest) and not force:
        return {"ok": True, "changed": False, "version": current,
                "message": f"已是 {current}（最新 {latest}），无需下载"}

    url = RESHADE_ASSET_URL.format(version=latest)
    try:
        with tempfile.TemporaryDirectory(prefix="mc-reshade-") as tmp:
            setup = updates.download_file(url, Path(tmp) / f"ReShade_Setup_{latest}_Addon.exe", log=log, timeout=900)
            try:
                with zipfile.ZipFile(setup) as zf:
                    candidates = _members_by_basename(zf, "ReShade64.dll")
                    if not candidates:
                        return {"ok": False, "changed": False, "message": "安装器里没有 ReShade64.dll"}
                    data = zf.read(candidates[0])
            except zipfile.BadZipFile:
                # 兜底：某些版本可能是 7z SFX，需要系统 7z
                return {"ok": False, "changed": False,
                        "message": "该 ReShade 安装器不是 ZIP 结构，需要 7z.exe 才能解包（请手动替换 d3d12.dll）"}
            _write_atomic(target, data, log=log)
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "changed": False, "message": f"下载/替换失败: {exc}"}

    _write_marker(config, "reshade_base", latest, {"source": RESHADE_HOMEPAGE})
    _log(log, f"ReShade 底座已更新到 {latest}")
    return {"ok": True, "changed": True, "version": latest, "target": str(target),
            "message": f"已安装 {latest}", "note": "如 DLSS5 失效，把 d3d12.dll.bak-* 改回 d3d12.dll 即可回退。"}


def install_dlss5_feed(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from . import github

    try:
        release = github.releases_latest(FEEDER_REPO)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "changed": False, "message": f"查询 DLSS5-Feeder release 失败: {exc}"}
    tag = str(release.get("tag_name") or "")
    asset = _pick_asset(release, "DLSS5-Feeder", ".zip")
    if not asset:
        return {"ok": False, "changed": False, "message": "release 里没有 DLSS5-Feeder 的 zip"}
    url = str(asset.get("browser_download_url") or "")

    component = _BY_KEY["dlss5_feed"]
    state = _component_state(config, component)
    installed = str((read_marker(config).get("dlss5_feed") or {}).get("version") or "")
    if state["present"] and installed == tag and not force:
        return {"ok": True, "changed": False, "version": tag, "message": f"已是最新 {tag}"}

    try:
        with tempfile.TemporaryDirectory(prefix="mc-feeder-") as tmp:
            archive = updates.download_file(url, Path(tmp) / str(asset.get("name") or "feeder.zip"), log=log, timeout=900)
            with zipfile.ZipFile(archive) as zf:
                written: list[str] = []
                for basename, relative in (
                    ("dlss5-feed.addon64", "dlss5-feed.addon64"),
                    ("DLSS5_Feed.fx", "reshade-shaders/Shaders/DLSS5_Feed.fx"),
                ):
                    members = _members_by_basename(zf, basename)
                    if not members:
                        return {"ok": False, "changed": False, "message": f"压缩包里没有 {basename}"}
                    _write_atomic(config.dlss5_path / relative, zf.read(members[0]), log=log)
                    written.append(relative)
    except (urllib.error.URLError, OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "changed": False, "message": f"下载/解包失败: {exc}"}

    _write_marker(config, "dlss5_feed", tag, {"asset": str(asset.get("name") or ""), "files": written})
    _log(log, f"DLSS5-Feeder 已更新到 {tag}")
    return {"ok": True, "changed": True, "version": tag, "files": written, "message": f"已安装 {tag}"}


def install_immersse(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from . import github

    try:
        revision = github.latest_commit(IMMERSE_REPO, IMMERSE_BRANCH)[:12]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "changed": False, "message": f"查询 iMMERSE 仓库失败: {exc}"}
    if not revision:
        return {"ok": False, "changed": False, "message": "查不到 iMMERSE 的最新提交"}

    component = _BY_KEY["immersse"]
    state = _component_state(config, component)
    installed = str((read_marker(config).get("immersse") or {}).get("version") or "")
    if state["present"] and installed == revision and not force:
        return {"ok": True, "changed": False, "version": revision, "message": f"已是最新（{revision}）"}

    url = f"https://codeload.github.com/{IMMERSE_REPO}/zip/refs/heads/{IMMERSE_BRANCH}"
    shaders_dir = config.dlss5_path / "reshade-shaders" / "Shaders" / "iMMERSE"
    textures_dir = config.dlss5_path / "reshade-shaders" / "Textures" / "iMMERSE"
    written: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="mc-immersse-") as tmp:
            archive = updates.download_file(url, Path(tmp) / f"iMMERSE-{IMMERSE_BRANCH}.zip", log=log, timeout=900)
            with zipfile.ZipFile(archive) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    parts = name.split("/")
                    basename = parts[-1]
                    lowered = name.lower()
                    if basename.lower().startswith("martysmods_") and lowered.endswith(".fx") and "shaders/" in lowered:
                        _write_atomic(shaders_dir / basename, zf.read(name), log=None, backup=True)
                        written.append(f"Shaders/iMMERSE/{basename}")
                    elif lowered.endswith(".fxh") and "/shaders/martysmods/" in lowered:
                        _write_atomic(shaders_dir / "MartysMods" / basename, zf.read(name), log=None, backup=True)
                        written.append(f"Shaders/iMMERSE/MartysMods/{basename}")
                    elif "/textures/immersse/" in lowered:
                        _write_atomic(textures_dir / basename, zf.read(name), log=None, backup=True)
                        written.append(f"Textures/iMMERSE/{basename}")
    except (urllib.error.URLError, OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "changed": False, "message": f"下载/解包失败: {exc}"}

    if not written:
        return {"ok": False, "changed": False, "message": "压缩包里没有找到匹配的 shader/贴图"}
    _write_marker(config, "immersse", revision, {"files": len(written)})
    _log(log, f"iMMERSE shader 已更新（{revision}，{len(written)} 个文件）")
    return {"ok": True, "changed": True, "version": revision, "files": written,
            "message": f"已安装 {len(written)} 个文件（{revision}）"}


INSTALLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "reshade_base": install_reshade_base,
    "dlss5_feed": install_dlss5_feed,
    "immersse": install_immersse,
}


def install(config: AppConfig, key: str, *, log: Callable[[str], None] | None = None,
            force: bool = False) -> dict[str, Any]:
    installer = INSTALLERS.get(key)
    if installer is None:
        return {"ok": False, "changed": False, "message": f"未知组件: {key}"}
    result = installer(config, log=log, force=force)
    result.setdefault("key", key)
    return result


def ensure_all(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    only_missing: bool = False,
    force: bool = False,
) -> list[dict[str, Any]]:
    """按顺序安装/更新所有在线组件。默认只补缺失的，不动已就位的。

    **单项失败不中断其它项，跑完后再对失败项重试（最多 3 次）** —— 用户 2026-10-01
    要求：「下载一旦失败就停了，改成全部下载完之后如果有失败项，就重试，3 次截止」。
    """
    def work(component: Component, attempt: int) -> dict[str, Any]:
        state = _component_state(config, component)
        if only_missing and state["present"]:
            return {"key": component.key, "ok": True, "changed": False,
                    "message": "已就位，跳过", "status": "跳过"}
        _log(log, f"处理组件 {component.display} …" if attempt == 0
             else f"重试组件 {component.display}（第 {attempt} 次）…")
        result = install(config, component.key, log=log, force=force)
        result["key"] = component.key
        result["status"] = ("已安装" if result.get("changed") else
                            ("已是最新" if result.get("ok") else "失败"))
        if not result.get("ok"):
            raise RuntimeError(str(result.get("message") or f"{component.key}: 安装失败"))
        return result

    def on_retry(attempt: int, pending: list[Component]) -> None:
        _log(log, f"有 {len(pending)} 个组件失败，重试第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次")

    outcomes, _pending = dependencies.run_batch_with_retry(list(COMPONENTS), work, on_retry=on_retry)
    results: list[dict[str, Any]] = []
    for index, component in enumerate(COMPONENTS):
        kind, payload = outcomes[index]
        if kind == "ok":
            results.append(payload)
        else:
            results.append({"key": component.key, "ok": False, "changed": False,
                            "message": str(payload), "status": "失败"})
    return results
