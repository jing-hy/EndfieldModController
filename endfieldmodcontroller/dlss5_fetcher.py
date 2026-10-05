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
# 首页抓不到版本号时的兜底（2026-10-05 加）：这是**随包那份 `d3d12.dll` 的版本**，
# 实测该 URL 直接下载 → 解包 `ReShade64.dll` = 5,592,064 B，与现网一致。
RESHADE_FALLBACK_VERSION = "6.8.0"
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
def _required_path(config: AppConfig, rel: str) -> Path:
    """组件文件的绝对路径。

    `assets/...` 开头的是**按显卡架构下载的运行库候选**（落在数据根的 assets 下，
    由 `runtime_assets` 的选择逻辑消费）；其余都相对 `runtime\\dlss5`。
    """
    if rel.replace("\\", "/").startswith("assets/"):
        return config.resolve_path(rel)
    return config.dlss5_path / rel


def _component_state(config: AppConfig, component: Component) -> dict[str, Any]:
    missing = [rel for rel in component.required if not _required_path(config, rel).is_file()]
    marker = read_marker(config).get(component.key) or {}
    optional = component.key.startswith("dlssnr_")
    return {
        "display": component.display,
        "source": component.upstream,
        "install_dir": str(config.dlss5_path),
        "present": not missing,
        "required": component.key in {"reshade_base", "dlss5_feed", "immersse"},
        # ⚠️ **可选的运行库变体不算"必须补"**：它缺失是正常状态（随包那份已经覆盖本机
        # 架构），所以 `needed` 固定 False —— 自检与「一键更新全部」都不会去下这 ~110 MB。
        "needed": False if optional else bool(missing),
        "status": ("未安装（可选）" if optional and missing
                   else ("已安装" if not missing else f"缺失 {len(missing)} 个文件")),
        "version": str(marker.get("version") or ""),
        "enabled": True,
        "optional": optional,
        "missing": missing,
        "note": component.note,
    }


def component_report(config: AppConfig) -> dict[str, dict[str, Any]]:
    """依赖页用：每个在线组件的在位状态（含**按本机显卡**决定的可选运行库变体）。"""
    report = {component.key: _component_state(config, component) for component in COMPONENTS}
    optional = dlssnr_variant_component(config)
    if optional is not None:
        report[optional.key] = _component_state(config, optional)
    return report


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
    """从 reshade.me 首页解析 Addon 安装器版本号；**取不到就退回内置基线版本**。

    ⚠️ **2026-10-05 修（用户反馈「下载日志都是别的没问题，就 d3d12 下不下来」）**：
    这条链原先只有"抓首页 → 正则找版本号"一条路，而 `reshade.me/` 现在**恒定返回
    HTTP 500**（实测：本机 curl / 我们的 fastnet 都是 500，带浏览器 UA 也一样；
    响应体 26,786 B 里**其实带着** `ReShade_Setup_6.8.0_Addon.exe`）。于是
    `_http_get` 按 500 判线路失败 → 换镜像 → 镜像也只是转发、源站照样 500 →
    `OSError: 所有线路都取不到 https://reshade.me/：HTTP Error 500` ⇒ 依赖页里
    「ReShade 底座 (d3d12.dll)」**永远装不上**，而其它组件（XXMI / Poser /
    DLSS5-Feeder / iMMERSE）的 URL 都来自 GitHub API、不抓页面，所以"别的都没问题"。

    两处一起改才成立：
      ① 抓取时 **容忍非 2xx**（`tolerate_error_status=True`）—— 正文里能解析出版本号就用；
      ② 连正文都没有时**退回内置基线** `RESHADE_FALLBACK_VERSION`（= 我们随包那份
         `d3d12.dll` 的版本，实测直接下载 + 解包 `ReShade64.dll` 得到 5,592,064 B，
         与现网一致），让"装 d3d12"这件事不至于因为官网首页抽风而彻底做不了。
    """
    versions: list[str] = []
    try:
        raw = dependencies._http_get(RESHADE_HOMEPAGE, tolerate_error_status=True)
        assert isinstance(raw, bytes)
        html = raw.decode("utf-8", errors="replace")
        versions = re.findall(r"ReShade_Setup_(\d+\.\d+\.\d+)_Addon\.exe", html)
    except Exception as exc:  # noqa: BLE001 - 抓不到就退回基线，不让整条安装链失败
        _log(log, f"ReShade 首页取版本号失败（{exc}）→ 改用内置基线 {RESHADE_FALLBACK_VERSION}")
    if not versions:
        _log(log, f"ReShade 首页里没有解析到 Addon 安装器版本号 → 改用内置基线 {RESHADE_FALLBACK_VERSION}")
        return RESHADE_FALLBACK_VERSION
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


# ---------------------------------------------------------------------------
# 按显卡架构的**可选**运行库变体（2026-10-05 接入社区镜像）
# ---------------------------------------------------------------------------
# 用户 2026-10-05 要求：「改造随包内容和下载链路，针对不同 gpu 自动切换下载内容」。
# 随包那份（`official`，只含 sm_120）+ 社区 `sf`（含 sm_75/86/89）**已覆盖全部受支持
# 型号**，所以一键启动永远不需要下载运行库；这里提供的是 40 系的**可选优化**：
# `rtx40` 是把内核重定向到 sm_89 的那一版，比 `sf` 的 FP16 路径更贴合 Ada。
#
# ⚠️ 该镜像的 release **tag 不是版本号语义**（`dlssnr-310.8.0-RTX40` 这种），
# 所以只能按 tag **精确匹配**，不能走 `releases/latest`（那个指向最后发布的任一组件）。
RHI_REPO = "RankFTW/rhi-repo"
DLSSNR_VARIANT_TAGS: dict[str, str] = {
    "official": "dlssnr-310.8.0",
    "rtx40": "dlssnr-310.8.0-RTX40",
    "sf": "dlssnr-310.8.SF-v2",
}
# 每个变体**必须**内含的架构（装错文件时当场拒绝，而不是等进游戏看到 NR 帧恒为 0）
DLSSNR_VARIANT_ARCH: dict[str, int] = {"official": 120, "rtx40": 89, "sf": 86}
# 哪个变体给哪个架构用（依赖页按本机显卡决定显示与 needed）
DLSSNR_VARIANT_FOR_SM: dict[int, str] = {120: "official", 89: "rtx40", 86: "sf", 75: "sf"}


def dlssnr_variant_key(variant: str) -> str:
    return f"dlssnr_{variant}"


def dlssnr_variant_component(config: AppConfig) -> Component | None:
    """按**本机显卡架构**给出"可选优化运行库"组件；这台机器用不上就返回 None。

    只对**下载能得到更贴合版本**的机器显示：
      * 40 系（sm_89）→ `rtx40`（随包给的是 `sf`，能用但非最优）；
      * 50/30/20 系 → None（随包那份就是该架构的首选，没有更好的可下）。
    """
    try:
        from . import deviceinfo

        sm = deviceinfo.best_rtx_sm()
    except Exception:  # noqa: BLE001
        return None
    if sm != 89:
        return None
    return Component(
        dlssnr_variant_key("rtx40"),
        "DLSS NR 运行库 · RTX 40 优化版（可选）",
        f"https://github.com/{RHI_REPO}",
        (f"assets/nvngx/nvngx_dlssnr.rtx40.dll",),
        "把神经渲染内核重定向到 Ada(sm_89) 的那一版，比随包的通用版更贴合 40 系；"
        "不装也能正常用（随包版含 sm_89）,装了一键启动会自动切到它。",
    )


def _dlssnr_variant_target(config: AppConfig, variant: str) -> Path:
    from . import runtime_assets

    root = runtime_assets.group_root(config, "nvngx") or config.resolve_path("assets/nvngx")
    return root / f"nvngx_dlssnr.{variant}.dll"


def install_dlssnr_variant(
    config: AppConfig,
    variant: str = "rtx40",
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """从社区镜像取**按架构重定向的运行库**，放进 `assets\\nvngx\\` 当候选。

    落点是"裸 dll"（不解压成压缩分卷）：`runtime_assets._dlssnr_sources()` 会把它当
    **下载候选**扫到，选中后由 `ensure_dlssnr()` 复制成 `runtime\\dlss5\\nvngx_dlssnr.dll`
    —— 于是"下载链路"和"随包链路"共用同一套选择/落盘逻辑。
    """
    import shutil

    from . import fastnet, github, runtime_assets

    tag = DLSSNR_VARIANT_TAGS.get(variant)
    if not tag:
        return {"ok": False, "changed": False, "message": f"未知的运行库变体：{variant}"}
    want_sm = DLSSNR_VARIANT_ARCH.get(variant)
    dest = _dlssnr_variant_target(config, variant)
    marker = read_marker(config).get(dlssnr_variant_key(variant)) or {}
    if dest.is_file() and not force:
        archs = runtime_assets.dll_architectures(dest)
        if not want_sm or want_sm in archs:
            return {"ok": True, "changed": False, "version": str(marker.get("version") or tag),
                    "message": f"已就位（{variant}，内含 sm_{want_sm}）"}
    try:
        release = github.api_get(f"https://api.github.com/repos/{RHI_REPO}/releases/tags/{tag}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "changed": False,
                "message": f"查询镜像 release 失败（{tag}）: {exc}"}
    assets = (release or {}).get("assets") or []
    asset = next((item for item in assets
                  if str(item.get("name") or "").lower().endswith(".zip")
                  and "dlssnr" in str(item.get("name") or "").lower()), None)
    if asset is None:
        return {"ok": False, "changed": False,
                "message": f"镜像里 {tag} 没有可用的 zip 资产（上游可能已变动）"}
    url = str(asset.get("browser_download_url") or "")
    if not url:
        return {"ok": False, "changed": False, "message": f"{tag} 的资产没有下载地址"}

    with tempfile.TemporaryDirectory(prefix="mc-dlssnr-") as tmp:
        archive = Path(tmp) / str(asset.get("name") or "dlssnr.zip")
        _log(log, f"下载运行库变体 {variant}（{int(asset.get('size') or 0) / 1048576:.1f} MB）…")
        report = fastnet.download(url, archive, log=log, timeout=1800)
        if not report.ok:
            return {"ok": False, "changed": False, "message": f"下载失败：{report.message}"}
        try:
            with zipfile.ZipFile(archive) as archive_zip:
                member = next(
                    (name for name in archive_zip.namelist()
                     if Path(name).name.lower().startswith("nvngx_dlssnr")
                     and name.lower().endswith(".dll")),
                    "",
                )
                if not member:
                    return {"ok": False, "changed": False,
                            "message": f"{tag} 的包里没有 nvngx_dlssnr.dll"}
                dest.parent.mkdir(parents=True, exist_ok=True)
                staging = dest.with_name(dest.name + f".mc-tmp-{os.getpid()}")
                with archive_zip.open(member) as source, open(staging, "wb") as sink:
                    shutil.copyfileobj(source, sink, 1 << 22)
        except (OSError, zipfile.BadZipFile) as exc:
            return {"ok": False, "changed": False, "message": f"解包失败：{exc}"}
        archs = runtime_assets.dll_architectures(staging)
        if want_sm and want_sm not in archs:
            try:
                staging.unlink()
            except OSError:
                pass
            return {"ok": False, "changed": False,
                    "message": (f"这个包与变体 {variant} 不符：它内含 "
                                f"{sorted(archs) or '读不到的架构'}，缺少 sm_{want_sm}"
                                f"（镜像可能换了内容，已拒绝安装）")}
        os.replace(staging, dest)
    _write_marker(config, dlssnr_variant_key(variant), tag, {"variant": variant, "arch": sorted(archs)})
    # 装完立刻按本机架构重选一次：让"一键启动会自动切到它"这句话当场成立
    try:
        switched = runtime_assets.ensure_dlssnr(config, log=log, force=True)
        note = switched.message if switched.ok else f"落位失败：{switched.message}"
    except Exception as exc:  # noqa: BLE001
        note = f"落位失败：{exc}"
    return {"ok": True, "changed": True, "version": tag,
            "message": f"已安装 {variant} 变体（内含 sm_{want_sm}）；{note}"}


INSTALLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "reshade_base": install_reshade_base,
    "dlss5_feed": install_dlss5_feed,
    "immersse": install_immersse,
}


def install(config: AppConfig, key: str, *, log: Callable[[str], None] | None = None,
            force: bool = False) -> dict[str, Any]:
    # 运行库变体（`dlssnr_rtx40` 等）走自己的安装器：它要按**本机架构**去镜像里挑
    # 不同的 release tag，不是固定 URL，所以塞不进 `INSTALLERS` 那张静态表。
    if key.startswith("dlssnr_"):
        result = install_dlssnr_variant(config, key[len("dlssnr_"):], log=log, force=force)
        result.setdefault("key", key)
        return result
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
