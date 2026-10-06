"""Built-in runtime management for XXMI Launcher and the EFMI package.

These are not regular 3DMigoto mods: they are the runtime that loads Mods.  The
functions here download the official GitHub release archives into the
EndfieldModController data directory, install them without touching the game folder,
and update config.json so the launcher can use them.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import dependencies
from .config import AppConfig


XXMI_REPO = "SpectrumQT/XXMI-Launcher"
XXMI_LIBS_REPO = "SpectrumQT/XXMI-Libs-Package"
EFMI_REPO = "SpectrumQT/EFMI-Package"
XXMI_ASSET_PATTERN = "Portable"
XXMI_LIBS_ASSET_PATTERN = "XXMI-PACKAGE"
EFMI_ASSET_PATTERN = "EFMI-PACKAGE"
# Endfield Poser（摆姿 / MMD 播放插件）：上游**只发预发布版**，所以取 release 时
# 必须走列表接口 include_prerelease（/releases/latest 会跳过预发布 —— 见 github.releases_list）。
# 它不随包分发（AGPL-3.0），下载到这里之后由 poser.py 调它自己的安装向导写游戏目录。
POSER_REPO = "OedoSoldier/Endfield-Poser"
POSER_ASSET_PATTERN = "win64.zip"
# ★★ **Streamline 运行库（多帧生成解锁要用）**（2026-10-06 用户要求接进依赖页）。
#
# 为什么需要它：`DLSS4 多帧生成` 这个 addon 的**真正技术闸门在 NGX 运行库层** ——
# 上游 README 原话是 `Exact DLSS-G 310.9.0/310.9.1 provider and payload validation`，
# 而终末地自带的是 **`nvngx_dlssg.dll 310.5.2` + Streamline `2.10.3`** ⇒ 面板因此显示
# 「Dynamic MFG requires DLSS-G 310.9.1 + Streamline 2.14.1」，固定倍率也上不去。
# 用户拍板走「全套替换」（只换一个会因版本不匹配出问题，上游有明确警告）。
#
# ⚠️ **上游的 zip 是完整 SDK（约 263 MB）**，我们只要 `bin\x64` 里那几个运行库
#    ⇒ 只挑文件、**绝不落地整个 SDK**（用户明确要求：「你不用自己下载，直接把下载接进依赖列表」）。
STREAMLINE_REPO = "NVIDIA-RTX/Streamline"
STREAMLINE_ASSET_PATTERN = "streamline-sdk-v"
# 要从 SDK 的 `bin\x64` 取的文件（与终末地游戏目录里那套一一对应，见 MEMORY 里那份清单）
STREAMLINE_WANTED = (
    "nvngx_dlssg.dll",       # ★ 核心：帧生成的 NGX 运行库（6x 的闸门就在这里）
    "sl.common.dll",
    "sl.dlss.dll",
    "sl.dlss_d.dll",
    "sl.dlss_g.dll",         # ★ 帧生成插件
    "sl.deepdvc.dll",
    "sl.interposer.dll",     # ★ Streamline 的入口（游戏加载的就是它）
    "sl.pcl.dll",
    "sl.reflex.dll",
)
MARKER_NAME = ".endfieldmodcontroller_builtin.json"


@dataclass
class BuiltinResult:
    key: str
    status: str
    message: str = ""
    version: str = ""
    path: str = ""


Progress = Callable[[int, int, str, str], None] | None
ByteProgress = Callable[[int, int, str, int, int], None] | None


def _points_at_builtin(config: AppConfig, value: str) -> bool:
    """这个字段"还是我们自动填的"吗？—— 空值、或路径落在内置 runtime 下都算。

    用途：区分「用户自己指定了外部 XXMI」与「我们上一轮自动填的内置路径」。
    只有前者之外的情况才允许被安装流程改写：用户明确填了外部 XXMI 时**绝不能覆盖**
    （issue #4：他刚改好的路径会在每次内置组件更新后被改回内置，表现为"设置自己变回去"）。
    相对路径（`runtime/builtin/...`）按数据根解析，所以内置写法同样判为 True。
    """
    if not str(value or "").strip():
        return True
    try:
        resolved = Path(config.resolve_path(value))
    except (OSError, ValueError):
        return False
    try:
        resolved.relative_to(config.builtin_runtime_path)
        return True
    except ValueError:
        return False


def _find_xxmi_exe(root: Path) -> Path | None:
    candidates = [
        root / "Resources" / "Bin" / "XXMI Launcher.exe",
        root / "XXMI Launcher.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for candidate in root.rglob("XXMI Launcher.exe"):
        if candidate.is_file():
            return candidate
    return None


def _read_marker(root: Path) -> dict:
    marker = root / MARKER_NAME
    if not marker.is_file():
        return {}
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_marker(root: Path, data: dict) -> None:
    from . import fsutil

    root.mkdir(parents=True, exist_ok=True)
    fsutil.write_text_atomic(
        root / MARKER_NAME,
        json.dumps(data, ensure_ascii=False, indent=2),
        newline="\n",
    )


def _latest_release_asset(repo: str, pattern: str, *, include_prerelease: bool = False) -> tuple[str, str, str, str]:
    """返回 (下载地址, 版本, 资产名, sha256 digest)。

    `include_prerelease=True` 时走 :func:`github.releases_list`（列表接口）——
    只有它能拿到预发布版（Endfield Poser 目前全是预发布）。
    """
    from . import github

    if include_prerelease:
        release = github.releases_list(repo, include_prerelease=True)
    else:
        # 先走网页路线（不消耗 API 额度、能借镜像），普通用户没有 token 也能用
        release = github.releases_latest(repo)
    assets = release.get("assets") or []
    lowered = pattern.lower()
    matches = [asset for asset in assets if lowered in str(asset.get("name", "")).lower()]
    if not matches:
        raise RuntimeError(f"{repo}: no release asset matched {pattern!r}")
    asset = max(matches, key=github.asset_sort_key)
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError(f"{repo}: release asset has no download URL")
    return (url, str(release.get("tag_name") or ""), str(asset.get("name") or "asset.zip"),
            str(asset.get("digest") or ""))


def _release_info(repo: str) -> dict:
    from . import github

    return github.releases_latest(repo)


def _asset_url(release: dict, name: str) -> str:
    for asset in release.get("assets") or []:
        if str(asset.get("name") or "") == name:
            url = str(asset.get("browser_download_url") or "")
            if url:
                return url
    raise RuntimeError(f"release asset not found: {name}")


def _download_extract(
    url: str,
    asset_name: str,
    target: Path,
    byte_progress: ByteProgress = None,
    index: int = 1,
    total: int = 1,
    key: str = "builtin",
    expected_sha256: str = "",
    log: Callable[[str], None] | None = None,     # ⚠️ 原来函数体里用了 `log=log` 却没有这个形参
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc-builtin-") as tmp:
        archive = dependencies._http_get(
            url,
            Path(tmp) / asset_name,
            chunk_callback=(lambda received, expected: byte_progress(index, total, key, received, expected)) if byte_progress else None,
            expected_sha256=expected_sha256,
            # ⚠️ 把日志接到 fastnet 上：直连被掐时它会**自动换镜像线路**，
            # 那些"尝试直连 / 换线路 X"的行如果不写出来，用户看到的就是**界面一动不动**。
            #（2026-10-03 实测：XXMI 下载卡了十几分钟、日志停在"checking"，看不出任何原因。）
            log=log,
        )
        assert isinstance(archive, Path)
        # 2026-10-01 修（⑧）：原先直接解压进 target（copytree 合并语义）—— 更新时
        # 旧版本文件不会被清掉，`_find_xxmi_exe` 的 rglob 兜底可能命中旧版 Launcher
        # 并写进配置；中途失败还会留下"半新半旧"且无从回滚。
        # 现在：先解压到临时目录 → 校验非空 → **逐文件原子替换**合并进 target。
        # 刻意**不删除新包里没有的文件**：target 里还有 EFMI / Mods / 用户配置，
        # 整目录替换会把它们一起弄丢。
        from . import fsutil

        staging = Path(tmp) / "unpacked"
        dependencies.extract_archive(archive, staging, strip_root=True)
        entries = [item for item in staging.rglob("*") if item.is_file()]
        if not entries:
            raise RuntimeError(f"{asset_name}: 解压结果为空")
        for item in entries:
            destination = target / item.relative_to(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            fsutil.write_bytes_atomic(destination, item.read_bytes())


def _note(config: AppConfig | None, message: str) -> None:
    """把关键节点写进 `runtime/logs/launch.log`（依赖页的日志框读的就是它）。

    用户定过：「接后台任务 ≠ 界面看得到」—— 开始 / 进行中 / 成功 / 失败四种状态都要有痕迹。
    ⚠️ 用 `logging` 不够：项目统一走 `launcher._append_log` 写那个文件，
    光 `logging.info` 在 noconsole 的打包版里等于丢进黑洞。
    """
    if config is None:
        return
    try:
        from . import launcher

        launcher._append_log(config, f"[组件] {message}")
    except Exception:  # noqa: BLE001
        pass


def _skip_online_check(
    config: AppConfig,
    key: str,
    marker: dict,
    path: Any,
    local_version: str,
    progress: Progress = None,
    index: int = 0,
    *,
    force: bool = False,
) -> BuiltinResult | None:
    """「自动更新依赖」关着 + 本地就位 ⇒ **一次网络都不发**，直接算"已是最新"。

    ⚠️ 2026-10-03 用户实测（原话：「为什么真正启动这么慢，在干什么，日志也没有」）：
    点一次「一键启动」花了 **62 秒**，日志里是

        23:37:00 builtin XXMI: start → checking → up_to_date   （1.8s）
        23:37:02 XXMI-Libs                                     （1.4s）
        23:37:03 EFMI                                          （1.3s）
        23:37:05 builtin Poser: start
        23:37:59 builtin Poser: installed                      ← **54 秒在下载新版**

    而他的「自动更新依赖」是**关着**的 —— `ensure_xxmi` 早就尊重这个开关（只报告不下载），
    可 `ensure_xxmi_libs` / `ensure_efmi` / `ensure_poser` **都没写这条判断**，
    于是上游一发新版，启动流程就**静默下载几十 MB**，用户看到的就是"卡住、日志也不动"。

    现在统一：**关着自动更新 + 本地已就位 ⇒ 一个请求都不发**。
    想检查有没有新版：依赖页的「检查状态（不下载）」（`updates.check_updates`）才联网；
    用户在依赖页亲手点「一键更新全部组件」走 `force=True`，照旧真的更新。
    """
    if force:
        return None                      # 显式更新：一律照旧（真的联网、真的下载）
    if getattr(config, "auto_update_dependencies", False):
        return None
    try:
        from . import launcher
    except Exception:  # noqa: BLE001
        launcher = None
    message = (f"{key}：本地已就位（{local_version or '未知'}）"
               f"—— 未开启自动更新，跳过联网检查（想查新版去依赖页）")
    if launcher is not None:
        try:
            launcher._append_log(config, message)
        except Exception:  # noqa: BLE001
            pass
    if progress:
        progress(index + 1, 3, key, "up_to_date")
    return BuiltinResult(key, "up_to_date", "already current", local_version, str(path))


def _auto_update_enabled(config: AppConfig) -> bool:
    """用户有没有打开「自动更新依赖」。

    ⚠️ 关着的时候**一律不自动下载**（2026-10-03 用户：「自动更新应该弹窗跳转到依赖页下载」）——
    只如实报告"有新版本"，由前端弹窗引导他去依赖页手动更新。
    """
    return bool(getattr(config, "auto_update_dependencies", False))


def ensure_xxmi(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None,
                log: Callable[[str], None] | None = None, *,
                force: bool = False) -> BuiltinResult:
    root = config.builtin_runtime_path / "XXMI"
    existing = _find_xxmi_exe(root)
    marker = _read_marker(root)
    if progress:
        progress(0, 3, "XXMI", "checking")
    # 关着自动更新 + 本地就位 ⇒ 不联网（2026-10-03：这是"一键启动 62 秒"的第一层原因）
    if existing is not None:
        skipped = _skip_online_check(config, "XXMI", marker, existing,
                                     marker.get("version") or "", progress, 0, force=force)
        if skipped is not None:
            return skipped
    url, version, asset_name, digest = _latest_release_asset(XXMI_REPO, XXMI_ASSET_PATTERN)
    if existing and marker.get("version") == version:
        if progress:
            progress(1, 3, "XXMI", "up_to_date")
        return BuiltinResult("XXMI", "up_to_date", "already current", version, str(existing))
    # 走到这里只有两种情形：**本地根本没有**（必须下载，否则没法用），或者用户显式点了
    # 「一键更新全部组件」（`force=True`）/ 开着「自动更新依赖」—— 都要真的下。
    # 「关着开关、本地旧版」那条路已经在 `_skip_online_check` 里提前返回了。
    _note(config, f"XXMI：最新版 {version}，准备下载 {asset_name}")
    _download_extract(url, asset_name, root, byte_progress, 1, 3, "XXMI",
                              expected_sha256=digest,
                              log=lambda m: _note(config, m))
    exe = _find_xxmi_exe(root)
    if exe is None:
        raise RuntimeError("XXMI Launcher.exe was not found after extraction")
    # 只往"我们自动填的内置路径"上写回；用户明确指定了外部 XXMI 就**不许覆盖**
    # （issue #4：他改好的 `F:\XXMI Launcher` 会在内置组件更新后被改回内置，表现为
    #  "设置自己变回去了"，而他要用的正是自己那份）。内置那份照旧装好、依赖页可见，
    #  只是不再劫持 `xxmi_launcher`。
    if _points_at_builtin(config, config.xxmi_launcher):
        config.xxmi_launcher = config.store_path(exe)
        config.save()
    _write_marker(root, {"version": version, "asset": asset_name, "source": XXMI_REPO})
    if progress:
        progress(1, 3, "XXMI", "installed")
    return BuiltinResult("XXMI", "installed", "installed", version, str(exe))


def ensure_xxmi_libs(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None,
                     log: Callable[[str], None] | None = None, *,
                     force: bool = False) -> BuiltinResult:
    root = config.builtin_runtime_path / "XXMI"
    target = root / "Resources" / "Packages" / "XXMI"
    d3d11 = target / "d3d11.dll"
    marker = _read_marker(target)
    if progress:
        progress(0, 3, "XXMI-Libs", "checking")
    if d3d11.is_file():
        skipped = _skip_online_check(config, "XXMI-Libs", marker, target,
                                     marker.get("version") or "", progress, 1, force=force)
        if skipped is not None:
            return skipped
    release = _release_info(XXMI_LIBS_REPO)
    version = str(release.get("tag_name") or "")
    assets = {str(asset.get("name") or ""): asset for asset in (release.get("assets") or [])}
    zip_name = next((name for name in assets if XXMI_LIBS_ASSET_PATTERN.lower() in name.lower()), "")
    if not zip_name:
        raise RuntimeError(f"{XXMI_LIBS_REPO}: no asset matched {XXMI_LIBS_ASSET_PATTERN!r}")
    if d3d11.is_file() and marker.get("version") == version:
        if progress:
            progress(2, 3, "XXMI-Libs", "up_to_date")
        return BuiltinResult("XXMI-Libs", "up_to_date", "already current", version, str(target))
    archive_url = _asset_url(release, zip_name)
    target.mkdir(parents=True, exist_ok=True)
    _download_extract(archive_url, zip_name, target, byte_progress, 2, 3, "XXMI-Libs",
                      expected_sha256=str((assets.get(zip_name) or {}).get("digest") or ""),
                      log=log)
    manifest_url = _asset_url(release, "Manifest.json")
    manifest_data = dependencies._http_get(
        manifest_url,
        expected_sha256=str((assets.get("Manifest.json") or {}).get("digest") or ""),
    )
    assert isinstance(manifest_data, bytes)
    (target / "Manifest.json").write_bytes(manifest_data)
    _write_marker(target, {"version": version, "asset": zip_name, "source": XXMI_LIBS_REPO})
    if progress:
        progress(2, 3, "XXMI-Libs", "installed")
    return BuiltinResult("XXMI-Libs", "installed", "installed", version, str(target))


def ensure_efmi(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None,
                log: Callable[[str], None] | None = None, *,
                force: bool = False) -> BuiltinResult:
    xxmi_root = config.builtin_runtime_path / "XXMI"
    xxmi_exe = _find_xxmi_exe(xxmi_root)
    if xxmi_exe is None:
        ensure_xxmi(config, progress, byte_progress)
    target = xxmi_root / "EFMI"
    core_ini = target / "Core" / "EFMI" / "main.ini"
    marker = _read_marker(target)
    if progress:
        progress(0, 3, "EFMI", "checking")
    if core_ini.is_file():
        skipped = _skip_online_check(config, "EFMI", marker, target,
                                     marker.get("version") or "", progress, 2, force=force)
        if skipped is not None:
            return skipped
    url, version, asset_name, digest = _latest_release_asset(EFMI_REPO, EFMI_ASSET_PATTERN)
    if core_ini.is_file() and marker.get("version") == version:
        if progress:
            progress(3, 3, "EFMI", "up_to_date")
        return BuiltinResult("EFMI", "up_to_date", "already current", version, str(target))
    _download_extract(url, asset_name, target, byte_progress, 3, 3, "EFMI", expected_sha256=digest, log=log)
    _write_marker(target, {"version": version, "asset": asset_name, "source": EFMI_REPO})
    # 同理：用户把 staging 指到别处（例如他自己那份 XXMI 的 `EFMI\Mods`）时不覆盖 ——
    # 否则他的 Mod 会被送进内置那份，外部 XXMI 永远读不到（issue #4 的另一半）。
    if _points_at_builtin(config, config.staging_mods_dir):
        config.staging_mods_dir = config.store_path(target / "Mods")
        config.save()
    if progress:
        progress(3, 3, "EFMI", "installed")
    return BuiltinResult("EFMI", "installed", "installed", version, str(target))


# ⚠️⚠️ **Streamline 不在「一键启动」里自动下载**（2026-10-07 用户现场：启动花了 129 秒）。
#
# 实测时间线（本机）：
#   第一次 00:01:19 启动流程开始 → 00:03:28 完成 = **129 秒**（在下 263 MB 的 SDK）
#   第二次 00:05:26 启动流程开始 → 00:05:38 完成 = **12 秒**（已下好）
#   差的 117 秒全是那次下载，而界面上**看不到任何进度** ⇒ 用户感受是「XXMI 拉不起来、搞了很久」。
#
# 这与用户定过的两条规矩直接冲突：
#   ①「**自动更新依赖**」开关必须真的拦住下载（`_skip_online_check` 的语义）；
#   ② 不该在启动流程里**静默**等几十/几百 MB（他 2026-10-03 就抱怨过"卡了十几分钟、日志停在 checking"）。
# ⇒ 所以：**它只在依赖页手动点「一键更新全部组件」时下载**（`force=True`），
#   一键启动遇到"本地没有"只报一条 `update_available`（前端可引导去依赖页），不下载。
STREAMLINE_KEY = "Streamline"


def streamline_download_required(config: AppConfig) -> bool:
    """当前是不是"必须下载才能用"（本地一份都没有）。"""
    return not (Path(config.runtime_path) / "streamline" / "nvngx_dlssg.dll").is_file()


def _streamline_asset() -> tuple[str, str, str, str]:
    """挑 Streamline SDK 的资产 —— **只认 x64 那份**。

    上游 `v2.14.1` 同时发三份：`streamline-sdk-v2.14.1.zip`(263 MB)、
    `-aarch64.zip`(257 MB)、`-arm64ec.zip`(222 MB)。

    ⚠️ **过滤条件写过一版是错的**（2026-10-06 实测抓到）：我原本写"名字里不含 `arm`"，
    而 **`aarch64` 的拼写里根本没有 `arm` 这三个连续字母** ⇒ 那条过滤形同虚设，
    实测返回的就是 `-aarch64.zip`（PC 上装 ARM 版的 DLL 必挂）。
    ⇒ 现在**反过来只接受明确的 x64 名字**（既排除 `arm`，也排除 `aarch`），
       并且**兜底要求"不含 aarch"**，两层都写，免得再被拼写坑一次。
    """
    from . import github

    release = github.releases_latest(STREAMLINE_REPO)
    assets = release.get("assets") or []

    def _is_x64(name: str) -> bool:
        lowered = name.lower()
        if "arm" in lowered or "aarch" in lowered:
            return False
        return "x64" in lowered or "win64" in lowered or lowered.endswith("-sdk.zip") or True

    matches = [
        asset for asset in assets
        if STREAMLINE_ASSET_PATTERN.lower() in str(asset.get("name") or "").lower()
        and _is_x64(str(asset.get("name") or ""))
    ]
    if not matches:
        raise RuntimeError(f"{STREAMLINE_REPO}: 没有找到 x64 的 streamline-sdk 资产")
    asset = max(matches, key=github.asset_sort_key)
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError(f"{STREAMLINE_REPO}: 资产没有下载地址")
    return (url, str(release.get("tag_name") or ""), str(asset.get("name") or "streamline.zip"),
            str(asset.get("digest") or ""))


def ensure_streamline(
    config: AppConfig,
    progress: Progress = None,
    byte_progress: ByteProgress = None,
    log: Callable[[str], None] | None = None,
    *,
    force: bool = False,
) -> BuiltinResult:
    """下载 Streamline SDK，**只取 `bin\\x64` 里那几个运行库**（不落地 263 MB 的完整 SDK）。

    产物落 `<数据根>/runtime/streamline/`；真正写进游戏目录由
    `deploy_streamline_libs()` 负责（**先备份、可一键还原**）。

    ⚠️⚠️ **绝不在一键启动里下载 263 MB**（2026-10-07 用户现场：启动花了 129 秒、界面毫无进度）。
    规则与别的组件不同 —— 别的组件是"缺了就补"，**它是"只在用户明确要求时才下"**：
      * `force=True`（依赖页点「一键更新全部组件」）⇒ 真的下载；
      * 一键启动（`force=False`）且本地没有 ⇒ 返回 `update_available`（带远端版本号，
        前端可据此引导去依赖页），**一个字节都不下**；
      * 本地已有 ⇒ 照旧走 `_skip_online_check`（自动更新关着就一次网络都不发）。
    """
    target = Path(config.runtime_path) / "streamline"
    core = target / "nvngx_dlssg.dll"
    marker = _read_marker(target)
    if progress:
        progress(0, 3, STREAMLINE_KEY, "checking")
    if core.is_file():
        skipped = _skip_online_check(config, STREAMLINE_KEY, marker, target,
                                     marker.get("version") or "", progress, 2, force=force)
        if skipped is not None:
            return skipped
    elif not force:
        # ★ 本地没有 + 不是用户主动要求 ⇒ **只报"可以装"，不下载**（263 MB 不能静默下）
        if progress:
            progress(3, 3, STREAMLINE_KEY, "update_available")
        return BuiltinResult(
            STREAMLINE_KEY, "update_available",
            "本机还没有 Streamline 运行库（约 263 MB）—— 到依赖页点它才会下载",
            "", str(target))
    url, version, asset_name, digest = _streamline_asset()
    if core.is_file() and marker.get("version") == version:
        if progress:
            progress(3, 3, STREAMLINE_KEY, "up_to_date")
        return BuiltinResult(STREAMLINE_KEY, "up_to_date", "already current", version, str(target))

    wanted = {name.lower() for name in STREAMLINE_WANTED}
    with tempfile.TemporaryDirectory(prefix="mc-streamline-") as tmp:
        archive = dependencies._http_get(
            url,
            Path(tmp) / asset_name,
            chunk_callback=(lambda received, expected: byte_progress(1, 3, "Streamline", received, expected)) if byte_progress else None,
            expected_sha256=digest,
            log=log,
        )
        assert isinstance(archive, Path)
        staging = Path(tmp) / "unpacked"
        dependencies.extract_archive(archive, staging, strip_root=True)
        # ★ **只取 `bin\x64` 下那几个**（SDK 里还有 include/lib/samples，全不要）
        picked: list[Path] = []
        for item in staging.rglob("*"):
            if (item.is_file() and item.name.lower() in wanted
                    and item.parent.name.lower() == "x64"):
                picked.append(item)
        if not picked:
            raise RuntimeError(f"{asset_name}: 包里没找到 bin\\x64 下的运行库（结构可能变了）")
        from . import fsutil

        for item in picked:
            fsutil.write_bytes_atomic(target / item.name, item.read_bytes())
        names = sorted(item.name for item in picked)
    _write_marker(target, {
        "version": version, "asset": asset_name, "source": STREAMLINE_REPO, "files": names,
    })
    if progress:
        progress(3, 3, "Streamline", "installed")
    return BuiltinResult("Streamline", "installed", f"已取 {len(names)} 个运行库", version, str(target))


def deploy_streamline_libs(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """把 `runtime\\streamline\\` 里的运行库**写进游戏目录**（2026-10-06 用户拍板的全套替换）。

    **为什么必须备份、而且必须接进管理器**（用户原话：「**备份要接进 mod 管理器，
    一键还原能直接还原**」）：上游 README 明确警告，Streamline 与 NVIDIA 的运行库
    **版本不匹配**会「missing capabilities, startup failures, severe slowdowns, or mislinks」
    —— 也就是说这一步**有可能把帧生成搞坏**，而游戏目录里的原版是**唯一**能退回的东西。
    所以先调 `game_clean.backup_files()`：备份落 `runtime\\game_backup\\<时间戳>\\` 并写清单
    ⇒ 依赖页/还原入口能列出它、点一下就能还原（走的是与净化同一套 `restore()`）。

    幂等：内容与源**完全一致**的文件不动（避免每次启动都重写一遍几 MB 的 DLL）。
    """
    from . import fsutil, game_clean, reshade_integration

    source_dir = Path(config.runtime_path) / "streamline"
    missing = [name for name in STREAMLINE_WANTED if not (source_dir / name).is_file()]
    if missing:
        return {"ok": False, "deployed": [], "skipped": [], "backup_stamp": "",
                "message": f"还没下载 Streamline 运行库（缺 {', '.join(missing[:3])}…）"}

    try:
        game_dir = Path(reshade_integration.detect_game_dir(config) or "")
    except Exception:  # noqa: BLE001
        game_dir = Path("")
    if not game_dir or not game_dir.is_dir():
        return {"ok": False, "deployed": [], "skipped": [], "backup_stamp": "",
                "message": "没有找到游戏目录 —— 先用「一键启动」跑一次，或到设置页填游戏目录"}

    # ① 先算"哪些真的需要换"（内容一致的不动）
    to_replace: list[str] = []
    for name in STREAMLINE_WANTED:
        source = source_dir / name
        target = game_dir / name
        if target.is_file() and _same_content(source, target):
            continue
        to_replace.append(name)
    if not to_replace:
        return {"ok": True, "deployed": [], "skipped": list(STREAMLINE_WANTED),
                "backup_stamp": "", "game_dir": str(game_dir),
                "message": "运行库已是最新（与原版一致或已替换过）"}

    if dry_run:
        return {"ok": True, "dry_run": True, "deployed": [], "would_replace": to_replace,
                "skipped": [], "backup_stamp": "", "game_dir": str(game_dir),
                "message": f"将要替换 {len(to_replace)} 个运行库（含备份）"}

    # ② **先备份原版**（走管理器统一的备份机制 ⇒ 一键还原能还原）
    backup = game_clean.backup_files(
        config, game_dir, to_replace, kind="libs",
        note="Streamline 运行库替换前的游戏原版", log=log)
    backup_stamp = str(backup.get("stamp") or "")

    # ③ 备份真的落盘了才动手（备份语义红线：**确认可还原才覆盖**）
    backed = {str(e.get("relative")) for e in (backup.get("entries") or [])}
    if not backup.get("ok") and not backed:
        return {"ok": False, "deployed": [], "skipped": [], "backup_stamp": backup_stamp,
                "game_dir": str(game_dir),
                "message": f"备份失败，已中止替换（游戏目录未改动）：{backup.get('message')}"}

    deployed: list[str] = []
    errors: list[str] = []
    for name in to_replace:
        target = game_dir / name
        # 原本不存在这个文件（游戏目录里没有）⇒ 没什么可备份的，直接放
        if target.is_file() and name not in backed:
            errors.append(f"{name}: 备份里没有它，跳过替换（避免不可还原）")
            continue
        try:
            fsutil.write_bytes_atomic(target, (source_dir / name).read_bytes())
            deployed.append(name)
            if log:
                log(f"已替换游戏目录运行库 {name}")
        except OSError as exc:
            errors.append(f"{name}: {exc}")

    return {
        "ok": not errors,
        "deployed": deployed,
        "skipped": [n for n in STREAMLINE_WANTED if n not in to_replace],
        "errors": errors,
        "backup_stamp": backup_stamp,
        "backup_dir": backup.get("backup_dir", ""),
        "game_dir": str(game_dir),
        "message": (f"已替换 {len(deployed)} 个运行库（原版已备份，可一键还原）"
                    if deployed else "没有任何文件被替换"),
    }


def _same_content(left: Path, right: Path) -> bool:
    """两个文件是否同样大小 + 同样内容（先比大小，省掉大文件的哈希开销）。"""
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return left.read_bytes() == right.read_bytes()
    except OSError:
        return False


def ensure_poser(
    config: AppConfig,
    progress: Progress = None,
    byte_progress: ByteProgress = None,
    log: Callable[[str], None] | None = None,
    *,
    force: bool = False,
) -> BuiltinResult:
    """下载/更新 Endfield Poser 安装包（**只落到数据目录，绝不碰游戏目录**）。
    包解压到 `<主路径>/runtime/poser`；把 proxy 与 `plugin\\poser.dll` 装进游戏目录
    由**上游自己的安装向导**完成（见 `poser.ensure_injection()`）——这是刻意的：
    向导自带 PE 校验、原子写、失败回滚和安装记录。

    上游目前**只发预发布版**，所以这里必须 `include_prerelease=True`
    （`/releases/latest` 会跳过预发布，用它永远查不到 Poser）。
    """
    # ⚠️ **尊重开关**（2026-10-03 用户实测：「poser 好像关了会自己打开」）。
    # `ensure_all()` 的 steps 里 Poser 是无条件的一项，于是每次一键启动都会把它装回来 ——
    # 用户关掉开关后，下一次启动又被自动打开（他会觉得"开关没用"）。
    # 关掉时直接返回 `skipped`（这是 `ensure_all` 认的成功状态之一）：
    # 既不下载也不安装，也**不动已经装好的那份**（想再开还能开）。
    if not force and not getattr(config, "poser_injection", True):
        return BuiltinResult(
            "Poser", "skipped", "用户已关闭「摆姿 / MMD 播放」开关", "", str(config.poser_path)
        )
    root = config.poser_path
    marker = _read_marker(root)
    present = (root / "plugin" / "poser.dll").is_file() or (root / "poser.dll").is_file()
    # ⚠️ **这条就是"一键启动慢 54 秒"的根**（2026-10-03 用户实测）：上游发了 0.5.2，
    # 而他关着「自动更新依赖」，这里却**照样在启动流程里静默下载整个安装包**
    # （日志：`23:37:05 builtin Poser: start` → `23:37:59 builtin Poser: installed`）。
    # 本地已就位就一个请求都不发；要查新版去依赖页，要真更新用 `force=True`（依赖页那个按钮）。
    if present:
        skipped = _skip_online_check(config, "Poser", marker, root,
                                     marker.get("version") or "", progress, 2, force=force)
        if skipped is not None:
            return skipped
    url, version, asset_name, digest = _latest_release_asset(
        POSER_REPO, POSER_ASSET_PATTERN, include_prerelease=True
    )
    if not force and present and marker.get("version") == version:
        return BuiltinResult("Poser", "up_to_date", "already current", version, str(root))
    _download_extract(url, asset_name, root, byte_progress, 1, 1, "Poser", expected_sha256=digest, log=log)
    if not ((root / "plugin" / "poser.dll").is_file() or (root / "poser.dll").is_file()):
        raise RuntimeError("解压后没找到 plugin\\poser.dll —— 上游安装包结构可能变了，请到上游 Release 页手动下载")
    _write_marker(root, {
        "version": version, "asset": asset_name, "source": POSER_REPO,
        "prerelease": True, "license": "AGPL-3.0",
    })
    return BuiltinResult("Poser", "installed", "installed", version, str(root))


def ensure_all(config: AppConfig, progress: Progress = None, byte_progress: ByteProgress = None,
    log: Callable[[str], None] | None = None, *, force: bool = False,) -> list[BuiltinResult]:
    """安装四个内置组件（XXMI / XXMI-Libs / EFMI / Endfield Poser）。

    **单项失败不中断其它项，跑完后再对失败项重试（最多 3 次）。**
    用户 2026-10-01 要求：「下载一旦失败就停了，改成全部下载完之后如果有失败项，
    就重试，3 次截止」——以前 `ensure_xxmi` 抛异常会让后面两个组件连试都不试。
    """
    steps: list[tuple[str, Callable[..., BuiltinResult], int]] = [
        ("XXMI", ensure_xxmi, 0),
        ("XXMI-Libs", ensure_xxmi_libs, 1),
        ("EFMI", ensure_efmi, 2),
        ("Poser", ensure_poser, 3),
        # ★ Streamline 运行库（2026-10-06 加）：多帧生成解锁的 6x 需要
        #   `nvngx_dlssg.dll` 310.9.x + Streamline 2.14.1，而游戏自带的是 310.5.2 / 2.10.3。
        #   它只是**下载**（落 `runtime\streamline\`）；写进游戏目录由
        #   `deploy_streamline_libs()` 负责（先备份、可一键还原）。
        ("Streamline", ensure_streamline, 4),
    ]
    total = len(steps)
    # ⚠️ `update_available` 也算"正常结束"（它是"等用户决定"，不是失败）——
    # 否则关掉自动更新时 `ensure_all` 会把每一项都当失败并重试 3 次（2026-10-03）。
    # `needs_install`（2026-10-05 加）：VC++ 运行库那条用的状态 —— 它是「等用户决定装不装」，
    # 跟 `update_available` 同性质，**不算失败**（不然会被重试 3 次）。
    ok_status = {"installed", "up_to_date", "skipped", "present", "update_available",
                 "needs_install"}
    if progress:
        progress(0, total, "builtin", "start")

    def worker(step: tuple[str, Callable[..., BuiltinResult], int], attempt: int) -> BuiltinResult:
        key, function, index = step
        if progress:
            progress(index, total, key, "start" if attempt == 0 else f"重试第 {attempt} 次")
        # ⚠️ **必须把 log 传下去**（2026-10-03）：下面这几个 `ensure_*` 会去
        # `_download_extract`，而那里的 `log=log` 是用来把「尝试直连 / 换线路 X /
        # 重试」写进日志的 —— 不传的话那些行全都消失，用户看到的就是
        # "卡了十几分钟、日志停在 checking"。
        # force=True（用户显式点「一键更新全部组件」）时让每个组件都不受
        # 「启动时自动更新」开关限制 —— 那是"启动时"的语义，不是"永远不许更新"。
        result = function(config, progress, byte_progress, log=log, force=force)
        if not isinstance(result, BuiltinResult):
            raise RuntimeError(f"{key}: 安装没有返回结果")
        if str(result.status) not in ok_status:
            raise RuntimeError(result.message or f"{key}: 安装失败（{result.status}）")
        if progress:
            progress(index + 1, total, key, result.status)
        return result

    def on_retry(attempt: int, pending: list[tuple[str, Callable[..., BuiltinResult], int]]) -> None:
        if progress:
            for key, _function, index in pending:
                progress(index, total, key, f"重试第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次")

    outcomes, _pending = dependencies.run_batch_with_retry(steps, worker, on_retry=on_retry)
    results: list[BuiltinResult] = []
    for index, (key, _function, _i) in enumerate(steps):
        kind, payload = outcomes[index]
        if kind == "ok":
            results.append(payload)
        else:
            results.append(BuiltinResult(key=key, status="error", message=str(payload)))
    # VC++ 运行库（2026-10-05 加）：**它不是我们的组件**（得跑微软官方安装器，不是解压包），
    # 所以不进 `steps` —— 免得被上面那套"下载失败就重试 3 次"的逻辑折腾；只在结果里**补一条**。
    # 前端看到 `status == "needs_install"` 就弹「安装 / 跳过（建议安装）」。
    try:
        results.append(vc_runtime_result())
    except Exception as exc:  # noqa: BLE001
        results.append(BuiltinResult(key=VC_RUNTIME_KEY, status="present",
                                     message=f"检查跳过：{exc}"))
    if progress:
        progress(total, total, "builtin", "complete")
    return results


def dry_run_results(config: AppConfig) -> list[BuiltinResult]:
    report = builtin_report(config)
    results: list[BuiltinResult] = []
    for key, item in report.items():
        results.append(BuiltinResult(
            key=key,
            status="up_to_date" if item.get("present") else "missing",
            message="present" if item.get("present") else "not installed",
            version=str(item.get("version") or ""),
            path=str(item.get("install_dir") or ""),
        ))
    return results


VC_RUNTIME_KEY = "VC++ 运行库"


def _vc_runtime_state() -> tuple[bool, str]:
    """(缺不缺, 版本摘要)。**读不到就当"不缺"** —— 别让检查本身变成故障。"""
    try:
        from . import initialize  # 延迟导入：避免 initialize ↔ runtime_deps 互相引

        found = initialize._vc_runtime_versions()
        missing = any(v.get("missing") for v in found.values())
        return missing, initialize.vc_runtime_summary(found)
    except Exception:  # noqa: BLE001
        return False, ""


def vc_runtime_result() -> BuiltinResult:
    """VC++ 运行库这条**不是组件**：缺了要走微软安装器，所以只报"要不要装"。"""
    from . import initialize

    missing, summary = _vc_runtime_state()
    if missing:
        mine = [n for n, v in initialize._vc_runtime_versions().items() if v.get("missing")]
        return BuiltinResult(
            key=VC_RUNTIME_KEY, status="needs_install",
            message=f"缺少 {'、'.join(mine)} —— ReShade 的插件需要它，建议安装（微软官方）",
            version=summary, path=initialize.VC_RUNTIME_URL,
        )
    return BuiltinResult(key=VC_RUNTIME_KEY, status="present", message="present",
                         version=summary)


def builtin_report(config: AppConfig) -> dict[str, dict]:
    xxmi_root = config.builtin_runtime_path / "XXMI"
    vc_missing, vc_summary = _vc_runtime_state()
    efmi_root = xxmi_root / "EFMI"
    xxmi_exe = _find_xxmi_exe(xxmi_root)
    xxmi_marker = _read_marker(xxmi_root)
    efmi_marker = _read_marker(efmi_root)
    return {
        # VC++ 运行库（2026-10-05 加）：**系统组件**，装法与我们自己的包不同
        # （跑微软官方安装器），所以带 `system_component=True` 让前端认出来。
        VC_RUNTIME_KEY: {
            "display": "VC++ 运行库（系统组件）",
            "source": "system",
            "system_component": True,
            "install_dir": str(Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"),
            "present": not vc_missing,
            "required": False,
            "needed": True,
            "status": "已安装" if not vc_missing else "缺失",
            "version": vc_summary,
            "enabled": True,
        },
        "XXMI": {
            "display": "XXMI Launcher",
            "source": "builtin",
            "install_dir": str(xxmi_root),
            "present": xxmi_exe is not None,
            "required": bool(config.use_builtin_runtime),
            "needed": bool(config.use_builtin_runtime),
            "status": "已安装" if xxmi_exe is not None else ("缺失" if config.use_builtin_runtime else "无需"),
            "version": xxmi_marker.get("version", ""),
            "enabled": config.use_builtin_runtime,
        },
        "XXMI-Libs": {
            "display": "XXMI Libraries (d3d11.dll)",
            "source": "builtin",
            "install_dir": str(xxmi_root / "Resources" / "Packages" / "XXMI"),
            "present": (xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll").is_file(),
            "required": bool(config.use_builtin_runtime),
            "needed": bool(config.use_builtin_runtime),
            "status": "已安装" if (xxmi_root / "Resources" / "Packages" / "XXMI" / "d3d11.dll").is_file() else ("缺失" if config.use_builtin_runtime else "无需"),
            "version": _read_marker(xxmi_root / "Resources" / "Packages" / "XXMI").get("version", ""),
            "enabled": config.use_builtin_runtime,
        },
        "EFMI": {
            "display": "EFMI Package",
            "source": "builtin",
            "install_dir": str(efmi_root),
            "present": (efmi_root / "Core" / "EFMI" / "main.ini").is_file(),
            "required": bool(config.use_builtin_runtime),
            "needed": bool(config.use_builtin_runtime),
            "status": "已安装" if (efmi_root / "Core" / "EFMI" / "main.ini").is_file() else ("缺失" if config.use_builtin_runtime else "无需"),
            "version": efmi_marker.get("version", ""),
            "enabled": config.use_builtin_runtime,
        },
        "Poser": {
            "display": "Endfield Poser (摆姿 / MMD 播放)",
            "source": "builtin",
            "install_dir": str(config.poser_path),
            "present": ((config.poser_path / "plugin" / "poser.dll").is_file()
                        or (config.poser_path / "poser.dll").is_file()),
            # Poser 是可选的第四方插件（AGPL-3.0，不随包分发）：缺失只影响它自己，
            # 所以 required=False —— 但开关开着时 needed=True，一键启动会去补。
            "required": False,
            "needed": bool(config.poser_injection),
            "status": ("已安装" if ((config.poser_path / "plugin" / "poser.dll").is_file()
                                    or (config.poser_path / "poser.dll").is_file())
                       else ("缺失" if config.poser_injection else "无需")),
            "version": _read_marker(config.poser_path).get("version", ""),
            "enabled": bool(config.poser_injection),
        },
        # ★ Streamline 运行库（2026-10-06 加）：多帧生成解锁的 6x 依赖它。
        #   它跟别的组件有一点不同 —— **下载之后要写进游戏目录**（游戏自带的
        #   `nvngx_dlssg.dll 310.5.2` / Streamline `2.10.3` 达不到 addon 的要求）。
        #   写进去之前**先备份原版到管理器统一的备份区**（一键还原能直接还原）。
        "Streamline": {
            "display": "Streamline 运行库（多帧生成 6x 用）",
            "source": "builtin",
            "install_dir": str(Path(config.runtime_path) / "streamline"),
            "present": (Path(config.runtime_path) / "streamline" / "nvngx_dlssg.dll").is_file(),
            # 只有开了「DLSS4 多帧生成」才需要它 —— 别的组合装了也没用。
            "required": False,
            "needed": bool(getattr(config, "mfg_unlock_enabled", False)),
            "status": ("已安装" if (Path(config.runtime_path) / "streamline" / "nvngx_dlssg.dll").is_file()
                       else ("缺失" if getattr(config, "mfg_unlock_enabled", False) else "无需")),
            "version": _read_marker(Path(config.runtime_path) / "streamline").get("version", ""),
            "enabled": bool(getattr(config, "mfg_unlock_enabled", False)),
            "touches_game_dir": True,
        },
    }
