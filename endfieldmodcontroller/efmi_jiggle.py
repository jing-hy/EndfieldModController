# SPDX-License-Identifier: GPL-3.0-or-later
"""EndfieldJiggle-EFMI（触摸形变 Mod）集成 —— **装进 Mod 库**（2026-10-19 起重做）。

**它和乳摇 / Poser 不是一类东西**：那两个是"游戏目录 proxy + plugin DLL"注入型插件，
而 EndfieldJiggle 只是**一个 EFMI 框架下的 Mod 目录** —— 放进 EFMI 的 Mods 就会被加载，
不换任何系统 DLL、不需要 loader、不写游戏目录。

⚠️ **2026-10-19 用户要求「触摸 mod 移出自带，加入自动识别进辅助 mod」**：
它不再是"启动页开关 + 依赖页组件"，而是**库里的一个普通辅助 Mod**：

    <Mod 库>/EndfieldJiggleEFMI                          启用态（勾选后由 staging 铺进 Mods）
    <runtime>/jiggle_efmi/_payload/EndfieldJiggleEFMI    本地载荷（安装源）
    <runtime>/jiggle_efmi/_pack/*.zip                    上游安装包原文 + version.txt

于是它走**和其它 Mod 完全相同的开关**（辅助 Mod 页勾选），而一键启动的
stage_and_prepare 会把它当成普通 Mod 铺进 EFMI\\Mods\\MC_其它辅助_EndfieldJiggleEFMI ——
这正好修掉"一键启动不管用、必须手动把目录移进 Mods"（旧实现只在初始化自检那条路上
部署，而 launcher.launch 根本不跑 initialize）。

三条硬约定（不变）：

* **「关」= 不勾选**：staging 本来就会清掉没选中的 MC_* 产物 ⇒ 游戏里不加载。
  旧版"把目录移出 Mods"的 _parked 只剩迁移读取用途。
* **不随包分发**：上游 GPL-3.0-only，且作者声明源码许可不转授游戏衍生兼容材料
  （Passes.ini 等）⇒ 一律从上游 Release 下原文（同 Poser 模式）。
* **能不能生效由上游的 shader 抓取决定**：Passes.ini 是 12 组 ShaderRegex，
  游戏更新重编译着色器就可能失配（游戏内表现为 EJ: NO COMPATIBLE NATIVE PROGRAM）。
  本模块只如实报状态，不承诺"装了就一定有效果"。

上游：https://github.com/woakato/EndfieldJiggle-EFMI
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

# ---------------------------------------------------------------- 常量
REPO = "woakato/EndfieldJiggle-EFMI"
UPSTREAM_URL = f"https://github.com/{REPO}"

# ⚠️ **只要纯 Mod 包**。同一个 Release 里还挂着另外两个资产（2026-10-13 实测 v0.2.2）：
#   ...-drop-in-win64.zip（72.7 MB，含配置器 EXE）
#   ...-standalone-win64.zip（149 MB，内置官方 EFMI + XXMI 渲染库 + 自己的启动器）
# 后两个对本程序**没有意义**（EFMI / XXMI 由我们自己维护），而且一个 149 MB 的包下下来
# 只会白白占地方；所以这里用**精确正则**而不是 "win64.zip" in name 那种模糊判据
# —— 后者会把三个包全匹配上，取 max 时按名字里的版本号排序，选中的可能是 149 MB 那个。
ASSET_RE = re.compile(r"^EndfieldJiggleEFMI-v?(\d+(?:\.\d+)+)-win64\.zip$", re.IGNORECASE)

MOD_DIR_NAME = "EndfieldJiggleEFMI"
COMPONENT_DIR_NAME = "jiggle_efmi"
VERSION_FILE = "version.txt"
# 安装时记下的**逐文件 sha256**（内容级完整性基线，见 verify）。
CHECKSUMS_FILE = "checksums.json"
# 单个文件超过这个就不进哈希清单：本组件的文件都是几十~几百 KB（ini / hlsl / bin）。
MAX_HASH_BYTES = 8 * 1024 * 1024

# 放回 Mod 库时用的显示名（辅助 Mod 页上看到的就是它）。
DISPLAY_NAME = "EndfieldJiggle（触摸形变）"
# 辅助 Mod 页里的子类（与 core.ASSIST_GROUP_OTHER 一致；这里不 import core，避免循环导入）。
ASSIST_GROUP = "其它辅助"

# 目录"齐不齐"的判据：上游纯 Mod 包是 13 个文件（ini ×3 + shaders ×3 hlsl + 4 bin+…），
# 这里只钉**功能上必需**的那几个 —— 多出来的编译产物（*.bin）随版本变化，不该当判据。
REQUIRED_FILES = ("EndfieldJiggle.ini", "Passes.ini", "Outfits.ini")
SHADER_DIR_NAME = "shaders"
REQUIRED_SHADERS = ("step_cs.hlsl", "input_controller.hlsl", "motion_model.hlsl")

LICENSE_ID = "GPL-3.0-only"
LICENSE_NOTE = (
    "上游 woakato/EndfieldJiggle-EFMI（GPL-3.0-only）。本程序只从它的官方 Release "
    "下载**纯 Mod 包**（约 120 KB）并放进 Mod 库，不随包分发、不修改其内容；"
    "作者声明源码许可不转授其中的游戏衍生兼容材料（Passes.ini 等），故一律走在线下载。"
)

# 它自己声明的 EFMI 框架最低版本（EndfieldJiggle.ini 里 $\EFMIv1\required_version = 1.47）。
# ⚠️ 上游写法是 1.47（两位），含义是 **1.4.7**，不是 1.47.0 —— 别拿它当三位版本号比。
REQUIRED_EFMI_VERSION = "1.4.7"

# 自动安装失败后的节流（秒）：6 小时。避免"没网的用户每次一键启动都白等一轮下载"。
RETRY_INTERVAL = 6 * 3600

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- 路径
def staging_root(config: AppConfig) -> Path:
    """EFMI 的 Mods 目录（= 控制器的 staging，用户可能把它指到自己的 XXMI 上）。"""
    return config.staging_mods_path


def component_root(config: AppConfig) -> Path:
    """本组件自己的地盘（载荷 / 上游包 / 版本号 / 状态）。"""
    return config.jiggle_efmi_path


def payload_dir(config: AppConfig) -> Path:
    """本地载荷：安装源。"""
    return component_root(config) / "_payload" / MOD_DIR_NAME


def park_dir(config: AppConfig) -> Path:
    """旧版"停用态"目录（只剩迁移读取用途；2026-10-19 起不再写入）。"""
    return component_root(config) / "_parked" / MOD_DIR_NAME


def library_dir(config: AppConfig) -> Path:
    """它在 Mod 库里的位置（用户能看见、卡片能勾选的那个目录）。"""
    return Path(config.library_path) / MOD_DIR_NAME


def current_dir(config: AppConfig) -> Path:
    """它现在实际所在的位置：库里那份优先，否则回退到本地载荷目录。"""
    return _find_in_library(config) or payload_dir(config)


def staging_legacy_dir(config: AppConfig) -> Path:
    """旧版直接铺在 EFMI\\Mods 顶层的目录（迁移源）。"""
    return staging_root(config) / MOD_DIR_NAME


def _version_file(config: AppConfig) -> Path:
    return component_root(config) / VERSION_FILE


def _state_file(config: AppConfig) -> Path:
    return Path(config.runtime_path) / "_state" / "jiggle_state.json"


def _backup_root(config: AppConfig) -> Path:
    return Path(config.runtime_path) / "backups" / "jiggle"


# ---------------------------------------------------------------- 状态文件
def _read_state(config: AppConfig) -> dict[str, Any]:
    try:
        data = json.loads(_state_file(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(config: AppConfig, payload: dict[str, Any]) -> None:
    from . import fsutil

    try:
        _state_file(config).parent.mkdir(parents=True, exist_ok=True)
        fsutil.write_json(_state_file(config), payload)
    except OSError:
        pass


def mark_optout(config: AppConfig, reason: str = "") -> None:
    """用户自己把这个 Mod 移出库 / 彻底删除 ⇒ 之后**不再自动装回来**。"""
    state = _read_state(config)
    state["optout"] = True
    state["optout_at"] = int(time.time())
    state["optout_reason"] = reason
    _write_state(config, state)


def clear_optout(config: AppConfig) -> None:
    state = _read_state(config)
    state.pop("optout", None)
    _write_state(config, state)


# ---------------------------------------------------------------- 目录体检
def _inspect(root: Path) -> dict[str, Any]:
    """某个目录里的 Mod 是否完整（只看功能上必需的那几个文件）。"""
    missing: list[str] = []
    if not root.is_dir():
        return {"ok": False, "missing": list(REQUIRED_FILES), "count": 0}
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            missing.append(name)
    shaders = root / SHADER_DIR_NAME
    for name in REQUIRED_SHADERS:
        if not (shaders / name).is_file():
            missing.append(f"{SHADER_DIR_NAME}/{name}")
    count = sum(1 for item in root.rglob("*") if item.is_file())
    return {"ok": not missing, "missing": missing, "count": count}


def payload_ready(config: AppConfig) -> bool:
    """本地有没有**可安装的载荷**（或一份完好的旧停用副本 / 已经在库里的那份）。"""
    return bool(_inspect(payload_dir(config))["ok"]
                or _inspect(park_dir(config))["ok"]
                or _find_in_library(config) is not None)


def _find_in_library(config: AppConfig) -> Path | None:
    """在 Mod 库里找触摸 Mod（用户可能改过目录名 ⇒ 用 core.is_touch_mod 认）。"""
    from . import core

    library = Path(config.library_path)
    try:
        children = sorted(library.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        if core.is_touch_mod(child, (child.name,)):
            return child
    return None


def installed_version(config: AppConfig) -> str:
    """本地已装的版本号（优先读库里那份 Mod 的 sidecar，其次旧的 version.txt）。"""
    for target in (_find_in_library(config), payload_dir(config)):
        if target is None or not target.is_dir():
            continue
        meta = target / "mod.meta.json"
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        version = str((data or {}).get("jiggle_version") or "").strip().lstrip("vV")
        if version:
            return version
    path = _version_file(config)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip().lstrip("vV")
    except OSError:
        return ""


def _write_version(config: AppConfig, version: str) -> None:
    if not version:
        return
    path = _version_file(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"v{version.lstrip('vV')}\n", encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 - 版本号只是显示用，写不进去不该让安装失败
        _log(None, f"⚠ 写 EndfieldJiggle 版本号失败: {exc}")


def _mod_name(target: Path) -> str:
    try:
        data = json.loads((target / "mod.meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return str((data or {}).get("name") or DISPLAY_NAME)


def _mod_id(target: Path, name: str) -> str:
    from .core import stable_id

    return stable_id(str(Path(target).resolve()), name)


def _write_sidecar(config: AppConfig, target: Path, version: str) -> bool:
    """给库里那份写 sidecar：kind=assist ⇒ 辅助 Mod 页可见、不参与同角色互斥。"""
    from . import fsutil

    meta_path = Path(target) / "mod.meta.json"
    payload: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, ValueError):
            payload = {}
    payload.setdefault("name", DISPLAY_NAME)
    payload.setdefault("id", _mod_id(target, _mod_name(target)))
    payload["kind"] = "assist"
    payload["group"] = ASSIST_GROUP
    payload["source"] = UPSTREAM_URL
    payload["jiggle_version"] = str(version or "").lstrip("vV")
    try:
        fsutil.write_json(meta_path, payload)
    except OSError as exc:  # noqa: BLE001
        _log(None, f"⚠ 写 EndfieldJiggle 的 mod.meta.json 失败: {exc}")
        return False
    return True


def _select_in_config(config: AppConfig, target: Path) -> str:
    """把它标记为**已启用**（= 加进 selected_mods），返回 id。

    ⚠️ 只在"刚装进来"时调用；用户之后自己取消勾选就保持关着 —— 不做"每次启动重新选中"。
    """
    name = _mod_name(target)
    mod_id = _mod_id(target, name)
    try:
        selected = list(config.selected_mods or [])
    except Exception:  # noqa: BLE001
        selected = []
    if mod_id not in selected:
        selected.append(mod_id)
        try:
            config.selected_mods = selected
            config.save()
        except Exception as exc:  # noqa: BLE001
            _log(None, f"⚠ 保存 EndfieldJiggle 勾选状态失败: {exc}")
    return mod_id


# ---------------------------------------------------------------- 上游资产
def pick_asset(release: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """在某个 release 里挑**纯 Mod 包**，返回 (版本号, 资产)；没有可用的返回 None。"""
    from .version import parse_version

    best: tuple[str, dict[str, Any]] | None = None
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        match = ASSET_RE.match(name)
        if not match:
            continue
        version = match.group(1)
        if best is None or parse_version(version) > parse_version(best[0]):
            best = (version, asset)
    return best


def efmi_version_check(config: AppConfig) -> dict[str, Any]:
    """本地 EFMI 版本够不够它要求（required_version = 1.47 ⇒ 1.4.7）。

    ⚠️ 读不到版本时**不判**（返回 ok=True + unknown=True）：这只说明我们没记下 EFMI
    的版本（例如用户用的是外部 XXMI），不代表它不满足 —— 拿"读不到"当"不兼容"会误导。
    """
    from .version import parse_version

    version = ""
    try:
        from . import updates

        version = updates._builtin_local_version(config, "EFMI")   # noqa: SLF001 - 复用同一口径
    except Exception:  # noqa: BLE001
        version = ""
    if not version:
        return {"ok": True, "unknown": True, "version": "", "required": REQUIRED_EFMI_VERSION}
    ok = parse_version(version) >= parse_version(REQUIRED_EFMI_VERSION)
    return {"ok": bool(ok), "unknown": False, "version": version,
            "required": REQUIRED_EFMI_VERSION}


# ---------------------------------------------------------------- 完整性（内容级）
def checksums_path(config: AppConfig) -> Path:
    """安装时记下的**每个文件的 sha256**（内容级基线）。"""
    return component_root(config) / CHECKSUMS_FILE


def _file_hashes(root: Path) -> dict[str, str]:
    """目录下每个文件的 sha256（相对路径 → 小写 hex）。"""
    from . import fsutil

    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for item in sorted(root.rglob("*")):
        try:
            if not item.is_file() or item.stat().st_size > MAX_HASH_BYTES:
                continue
            out[item.relative_to(root).as_posix()] = fsutil.sha256_file(item)
        except OSError:
            continue
    return out


def write_checksums(config: AppConfig, *, version: str = "", asset: str = "",
                    archive: Path | None = None, target: Path | None = None) -> None:
    """把"刚铺好的这份 Mod"的哈希清单落盘 —— 之后 verify() 就靠它查损坏。"""
    import hashlib
    import json as _json

    root = Path(target) if target is not None else payload_dir(config)
    payload: dict[str, Any] = {
        "version": version or installed_version(config),
        "asset": asset,
        "dir": str(root),
        "files": _file_hashes(root),
        "at": int(time.time()),
    }
    if archive is not None and archive.is_file():
        try:
            digest = hashlib.sha256()
            with archive.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            payload["archive_sha256"] = digest.hexdigest()
        except OSError:
            pass
    try:
        path = checksums_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 - 记不下基线不该让安装失败，但要留痕
        _log(None, f"⚠ 写 EndfieldJiggle 哈希清单失败: {exc}")


def load_checksums(config: AppConfig) -> dict[str, Any]:
    import json as _json

    path = checksums_path(config)
    if not path.is_file():
        return {}
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _verify_target(config: AppConfig) -> Path:
    return _find_in_library(config) or payload_dir(config)


def verify(config: AppConfig) -> dict[str, Any]:
    """把**现在这份 Mod**与安装时记下的哈希逐个比对 —— 查的是**内容**，不是"文件在不在"。

    ★ 用户 2026-10-13 反馈：「**下载后的文件损坏检测按钮和启动检查不出来**」。
    只判 is_file() 确实查不出来：zip 半截下载、安全软件破坏、跨盘复制中断，都会留下
    **大小看着正常、内容不对**的文件。这里用三层判据补上：

      ① **下载当场**：上游 Release 的 SHA256SUMS-*.txt / asset digest 做 sha256 校验
         （见 _digest_from_release），外加 zip 的 CRC 全量扫描（见 import_pack）；
      ② **装好之后**：本函数按安装时记下的逐文件 sha256 比对，任一个不符就是"损坏"；
      ③ **能自愈**：repack_from_local() 用 _pack 里留存的原始包重新解出载荷再铺一遍。

    没记过基线（老版本装的 / 手工放的）⇒ known=False + ok=True：
    **不拿"读不到基线"当"损坏"**，那会误报。
    """
    baseline = load_checksums(config)
    files = baseline.get("files") or {}
    if not files:
        return {"ok": True, "known": False, "missing": [], "corrupt": [],
                "checked": 0, "dir": str(_verify_target(config)), "version": ""}
    target = _verify_target(config)
    actual = _file_hashes(target)
    missing = [name for name in files if name not in actual]
    corrupt = [name for name, want in files.items()
               if name in actual and actual[name] != str(want)]
    return {
        "ok": not missing and not corrupt,
        "known": True,
        "missing": missing,
        "corrupt": corrupt,
        "checked": len(files),
        "dir": str(target),
        "version": str(baseline.get("version") or ""),
    }


def _content_ok(config: AppConfig, target: Path) -> bool:
    """目标目录的**内容**是否与安装基线一致（没记过基线时**不判**，返回 True）。

    ⚠️ 为什么需要它（2026-10-13）：只判文件在不在时，"那份已经被下坏/改坏"会被认定
    "已就位"⇒ 自愈路径**空转**，界面还全绿。
    """
    baseline = load_checksums(config)
    files = baseline.get("files") or {}
    if not files or not Path(target).is_dir():
        return True
    actual = _file_hashes(target)
    return all(name in actual and actual[name] == str(want) for name, want in files.items())


def repack_from_local(config: AppConfig, log: Log = None) -> dict[str, Any]:
    """用 _pack 里留存的原始安装包**重新解出载荷**（损坏时的本地自愈路径，不联网）。"""
    pack_dir_path = component_root(config) / "_pack"
    archives: list[Path] = []
    try:
        archives = sorted((p for p in pack_dir_path.glob("*.zip") if p.is_file()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        archives = []
    for archive in archives:
        result = import_pack(config, archive, log=log)
        if result.get("ok"):
            result["archive"] = str(archive)
            return result
    return {"ok": False, "message": "本地没有可用的原始安装包（下载页点「安装/更新」会重新下载）"}


def _digest_from_release(release: dict[str, Any], asset_name: str, log: Log = None) -> str:
    """从同一个 Release 的 SHA256SUMS-*.txt 附件里取该资产的 sha256（取不到返回空串）。

    ⚠️ 为什么需要它：github.releases_latest **默认走网页路线**（省 API 额度、能借镜像线路），
    而网页路线的 asset **没有 digest 字段** ⇒ 光靠 asset["digest"] 的话，
    绝大多数用户（没 token / 走镜像）那条路上"下载损坏"根本没人校验。
    """
    from . import updates

    for item in release.get("assets") or []:
        name = str(item.get("name") or "")
        if not name.lower().startswith("sha256sums"):
            continue
        url = str(item.get("browser_download_url") or "")
        if not url:
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="mc-jiggle-sums-") as tmp:
                path = updates.download_file(url, Path(tmp) / name, log=log, timeout=120)
                text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - 拿不到校验和就退化成"不校验哈希"
            _log(log, f"EndfieldJiggle：取上游校验和失败（跳过 sha256 校验）: {exc}")
            return ""
        for line in text.splitlines():
            parts = line.replace("*", " ").split()
            if len(parts) >= 2 and parts[-1].strip() == asset_name:
                return parts[0].strip()
    return ""


# ---------------------------------------------------------------- 状态
def status(config: AppConfig) -> dict[str, Any]:
    """给 UI / 自检用的完整状态。"""
    library = _find_in_library(config)
    payload = payload_dir(config)
    payload_info = _inspect(payload)
    parked_info = _inspect(park_dir(config))
    legacy = staging_legacy_dir(config)
    efmi = efmi_version_check(config)
    target = library or payload
    live = _inspect(target) if target.is_dir() else {"ok": False, "missing": [], "count": 0}
    verify_state = (verify(config) if library is not None else
                    {"ok": True, "known": False, "missing": [], "corrupt": [],
                     "checked": 0, "dir": str(target), "version": ""})
    return {
        "display": DISPLAY_NAME,
        "in_library": library is not None,
        "library_dir": str(library or library_dir(config)),
        "enabled": library is not None,        # 兼容旧字段：= 在库里（勾选与否看 selected_mods）
        "present": bool(library or payload.is_dir() or park_dir(config).is_dir()),
        "payload_ready": bool(payload_info["ok"] or parked_info["ok"]),
        "in_mods": legacy.is_dir(),            # 旧版直接铺在 Mods 顶层的那份（待迁移）
        "legacy_mods_dir": str(legacy),
        "files_ok": bool(live["ok"]),
        "missing": live["missing"],
        "file_count": live["count"],
        "version": installed_version(config),
        "mod_dir": str(target),
        "staging_root": str(staging_root(config)),
        "upstream": UPSTREAM_URL,
        "license": LICENSE_ID,
        "efmi_ok": bool(efmi["ok"]),
        "efmi_version": efmi["version"],
        "efmi_required": efmi["required"],
        "efmi_unknown": bool(efmi.get("unknown")),
        # 内容级校验（前端/自检用这三项）
        "verify": verify_state,
        "verified": bool(verify_state.get("ok")),
        "corrupt": list(verify_state.get("corrupt") or []),
        "dropped": list(verify_state.get("missing") or []),
    }


# ---------------------------------------------------------------- 安装进库
def _backup_library_copy(config: AppConfig, target: Path) -> Path | None:
    """覆盖库里的那份之前先整份备份（备份语义：先落盘、可还原、失败保留原状）。"""
    if not Path(target).is_dir():
        return None
    root = _backup_root(config) / _stamp()
    dest = root / Path(target).name
    try:
        root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, dest)
    except OSError as exc:  # noqa: BLE001
        _log(None, f"⚠ 备份 EndfieldJiggle 失败: {exc}")
        return None
    return dest


def _source_dir(config: AppConfig) -> Path | None:
    """可用的安装源（载荷 → 旧停用副本）。"""
    for candidate in (payload_dir(config), park_dir(config)):
        if _inspect(candidate)["ok"]:
            return candidate
    return None


def install_to_library(config: AppConfig, *, force: bool = False,
                       log: Log = None) -> dict[str, Any]:
    """把上游纯 Mod 包**装进 Mod 库**（幂等；已有则不动，除非 force）。"""
    target = library_dir(config)
    if target.is_dir() and not force:
        _write_sidecar(config, target, installed_version(config))
        _select_in_config(config, target)
        return {"ok": True, "changed": False, "in_library": True,
                "path": str(target), "version": installed_version(config),
                "message": "EndfieldJiggle 已经在 Mod 库里"}

    version = installed_version(config)
    asset_name = ""
    archive: Path | None = None

    source = _source_dir(config)
    if source is None:
        # 离线依赖包优先（命中就一个网络请求都不发）
        try:
            from . import offline_deps

            offline = offline_deps.resolve_offline(config, "EndfieldJiggle")
        except Exception:  # noqa: BLE001 —— 离线链路异常不该挡住正常下载
            offline = None
        if offline is not None:
            source_path, offline_version, offline_asset, _digest = offline
            _log(log, f"EndfieldJiggle：用离线依赖包里的 {offline_asset}"
                      f"（v{offline_version or '?'}），不联网")
            result = import_pack(config, Path(source_path),
                                 version=str(offline_version or ""), log=log)
            if not result.get("ok"):
                return result
            version = str(offline_version or result.get("version") or "")
            asset_name = str(offline_asset or "")
            archive = Path(source_path)
            source = _source_dir(config)
        else:
            from . import github, updates

            try:
                release = github.releases_latest(REPO)
            except Exception as exc:  # noqa: BLE001 - 网络问题要给可读原因，不能抛给 UI
                return {"ok": False, "message": f"查上游 Release 失败: {exc}"}
            picked = pick_asset(release)
            if picked is None:
                return {"ok": False,
                        "message": f"上游 {REPO} 的 Release 里没有可用的纯 Mod 包（*win64.zip）"}
            version, asset = picked
            asset_name = str(asset.get("name") or "pack.zip")
            url = str(asset.get("browser_download_url") or "")
            if not url:
                return {"ok": False, "message": "没拿到纯 Mod 包的下载地址"}
            digest = str(asset.get("digest") or "")
            if not digest:
                digest = _digest_from_release(release, asset_name, log=log)
            _log(log, f"EndfieldJiggle：从上游下载 v{version}（{asset_name}）"
                      + ("，并用上游 sha256 校验" if digest else "，拿不到上游 sha256（退化为 zip CRC 校验）"))
            try:
                with tempfile.TemporaryDirectory(prefix="mc-jiggle-") as tmp:
                    archive = updates.download_file(url, Path(tmp) / asset_name, log=log,
                                                    timeout=600, expected_sha256=digest)
                    result = import_pack(config, archive, version=version, log=log)
                    if not result.get("ok"):
                        return result
                    keep = component_root(config) / "_pack" / asset_name
                    if not keep.is_file():
                        try:
                            shutil.copy2(archive, keep)
                        except OSError:
                            pass
                        archive = keep
            except Exception as exc:  # noqa: BLE001 - 校验不过 / 网络断，都给可读原因
                return {"ok": False, "message": f"下载/校验/解压失败: {exc}"}
            source = _source_dir(config)

    if source is None:
        return {"ok": False, "message": "本地没有可安装的 EndfieldJiggle 载荷"}

    actions: list[str] = []
    backup = _backup_library_copy(config, target) if target.is_dir() else None
    if backup is not None:
        actions.append(f"旧版本已备份到 {backup}")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    except OSError as exc:
        return {"ok": False, "message": f"复制进 Mod 库失败: {exc}"}

    if not version:
        version = installed_version(config)
    _write_version(config, version)
    _write_sidecar(config, target, version)
    write_checksums(config, version=version, asset=asset_name, archive=archive, target=target)
    mod_id = _select_in_config(config, target)
    _log(log, f"EndfieldJiggle：已装进 Mod 库 {target}（v{version or '?'}）")
    return {"ok": True, "changed": True, "in_library": True, "path": str(target),
            "version": version, "id": mod_id, "actions": actions,
            "message": f"EndfieldJiggle 已装进 Mod 库（v{version or '?'}，辅助 Mod 页可开关）"}


def _adopt_from_staging(config: AppConfig, legacy: Path, log: Log = None) -> dict[str, Any]:
    """把旧版直接铺在 Mods 顶层的那份**收进库**（先复制成功、再移除来源）。"""
    from . import fsutil

    target = library_dir(config)
    if target.exists():
        target = Path(config.library_path) / f"{MOD_DIR_NAME}_imported"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy, target)
    except OSError as exc:
        return {"ok": False, "message": f"把旧目录收进 Mod 库失败: {exc}"}
    version = installed_version(config)
    _write_sidecar(config, target, version)
    write_checksums(config, version=version, target=target)
    mod_id = _select_in_config(config, target)

    # 收进库之后才移除 staging 里那份：EFMI 是 include_recursive，两份同 namespace 会打架。
    guard = fsutil.library_conflict(Path(config.library_path), legacy)
    removed = False
    if guard:
        _log(log, f"WARN 保留 {legacy.name}：{guard}")
    else:
        try:
            shutil.rmtree(legacy)
            removed = True
        except OSError as exc:  # noqa: BLE001
            _log(log, f"WARN 移除旧 Mods 目录失败: {exc}")
    _log(log, f"EndfieldJiggle：已把旧目录 {legacy} 收进 Mod 库")
    return {"ok": True, "changed": True, "adopted": True, "moved_from": str(legacy),
            "removed_source": removed, "path": str(target), "id": mod_id,
            "message": "已把 EFMI\\Mods 里那份 EndfieldJiggle 收进 Mod 库"
                       "（以后由辅助 Mod 的开关统一管理）"}


def ensure_in_library(config: AppConfig, *, install_if_missing: bool = True,
                      force: bool = False, log: Log = None) -> dict[str, Any]:
    """一键启动 / 生成控制器 / 自检共用：保证触摸 Mod **在 Mod 库里**。

    1. 库里已有 ⇒ 内容与基线不符就先用本地原包自愈；**不改勾选状态**（用户关掉就保持关）。
    2. 库里没有、但 EFMI\\Mods 顶层有旧目录 ⇒ 收进库（先复制成功再移除来源）。
    3. 都没有 ⇒ 自动安装（本地载荷零网络；否则离线包 / 上游下载）。
    4. 失败 ⇒ 记状态并 6 小时节流，**不拦启动**。
    """
    library = _find_in_library(config)
    if library is not None:
        damaged = (not _content_ok(config, library)) and bool(load_checksums(config).get("files"))
        if damaged:
            _log(log, "EndfieldJiggle：库里的文件与安装基线不符 → 用本地原包重铺")
            repack = repack_from_local(config, log=log)
            if repack.get("ok"):
                _backup_library_copy(config, library)
                try:
                    shutil.copytree(payload_dir(config), library, dirs_exist_ok=True)
                    write_checksums(config, target=library)
                except OSError as exc:  # noqa: BLE001
                    _log(log, f"WARN 重铺 EndfieldJiggle 失败: {exc}")
            else:
                _log(log, f"EndfieldJiggle：本地原始包不可用（{repack.get('message')}）")
        return {"ok": True, "changed": False, "in_library": True, "path": str(library),
                "damaged": damaged, "message": "EndfieldJiggle 已在 Mod 库"}

    state = _read_state(config)
    last = int(state.get("last_attempt") or 0)
    if state.get("optout"):
        return {"ok": True, "skipped": True, "reason": "optout",
                "message": "EndfieldJiggle 已被你移出 Mod 库，不再自动安装"}
    if not install_if_missing:
        return {"ok": True, "skipped": True, "reason": "disabled",
                "message": "未启用自动安装 EndfieldJiggle"}
    # ⚠️ 皮肤 Mod 总开关关着 ⇒ 一个 Mod 都不加载（staging 会被清空），这时**不要**
    # 往库里装它并替用户勾上（用户第一步就说了"不要这些 Mod"，悄悄加一条是反直觉的）。
    if not getattr(config, "efmi_injection", True):
        return {"ok": True, "skipped": True, "reason": "efmi-off",
                "message": "皮肤 Mod 总开关关着，未自动安装 EndfieldJiggle"}

    legacy = staging_legacy_dir(config)
    if legacy.is_dir():
        result = _adopt_from_staging(config, legacy, log=log)
        if result.get("ok"):
            state.pop("last_attempt", None)
            state.pop("last_error", None)
            _write_state(config, state)
        return result

    if last and (time.time() - last) < RETRY_INTERVAL and not force:
        return {"ok": True, "skipped": True, "reason": "retry-throttle",
                "message": "EndfieldJiggle 上次安装失败，6 小时内不再自动重试"
                           "（可以在下载页手动安装）"}

    result = install_to_library(config, force=force, log=log)
    state = _read_state(config)
    if result.get("ok"):
        state.pop("last_attempt", None)
        state.pop("last_error", None)
    else:
        state["last_attempt"] = int(time.time())
        state["last_error"] = str(result.get("message") or "")
    _write_state(config, state)
    return result


# 兼容旧名字（updates / 下载页更新链路都调 install）
def install(config: AppConfig, log: Log = None, *, force: bool = False) -> dict[str, Any]:
    return install_to_library(config, force=force, log=log)


# ---------------------------------------------------------------- 安装包解包
def import_pack(config: AppConfig, archive: Path, *, version: str = "", log: Log = None) -> dict[str, Any]:
    """把上游 zip 变成"可安装载荷"，并把原包留一份、写版本号。

    ⚠️ **不能按固定层级取**：上游纯 Mod 包是三层套法（2026-10-13 实测 v0.2.2）

        EndfieldJiggleEFMI-v0.2.2/Mods/EndfieldJiggleEFMI/EndfieldJiggle.ini

    而拖放包/独立包的层级又不一样 ⇒ 一律"在解压结果里搜 EndfieldJiggle.ini 所在的那层"。
    """
    archive = Path(archive)
    if not archive.is_file():
        return {"ok": False, "message": f"安装包不存在：{archive}"}
    if not version:
        match = ASSET_RE.match(archive.name) or re.search(r"v?(\d+(?:\.\d+)+)", archive.name)
        version = match.group(1) if match else ""

    root = component_root(config)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="mc-jiggle-unpack-") as tmp:
            with zipfile.ZipFile(archive) as bundle:
                # ★ **CRC 全量扫描**（这个包只有 ~120 KB，代价可忽略）：半截下载、传输损坏的
                #   zip 在这里当场露馅，而不是等铺进游戏才变成"文件在、内容不对"的哑弹。
                broken = bundle.testzip()
                if broken:
                    return {"ok": False,
                            "message": f"安装包已损坏（CRC 校验失败：{broken}）"
                                       "—— 删掉本地那份后重新下载一次"}
                bundle.extractall(tmp)
            source: Path | None = None
            for ini in sorted(Path(tmp).rglob("EndfieldJiggle.ini")):
                source = ini.parent
                break
            if source is None:
                return {"ok": False,
                        "message": f"压缩包里找不到 EndfieldJiggle.ini（{archive.name}）——"
                                   "确认下的是纯 Mod 包而不是源码归档"}
            target = payload_dir(config)
            if target.is_dir():
                backup = target.with_name(f"{target.name}.bak-{_stamp()}")
                shutil.move(str(target), str(backup))
                _log(log, f"EndfieldJiggle：旧载荷已备份为 {backup.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
            info = _inspect(target)
        # 原包留一份（约 120 KB）：离线重装 / 回滚时要它，不值得为省这点空间丢掉。
        pack_dir = root / "_pack"
        pack_dir.mkdir(parents=True, exist_ok=True)
        keep = pack_dir / (archive.name if version else f"EndfieldJiggleEFMI-{_stamp()}.zip")
        try:
            shutil.copy2(archive, keep)
        except OSError:
            pass
        _write_version(config, version)
    except zipfile.BadZipFile as exc:
        # 半截下载 / 传输损坏：与其铺一堆坏文件进库，不如当场说"重新下载"。
        return {"ok": False,
                "message": f"安装包已损坏（无法作为 zip 打开：{exc}）—— "
                           "删掉本地那份后重新下载一次"}
    except OSError as exc:
        return {"ok": False, "message": f"解压安装包失败: {exc}"}

    if not info["ok"]:
        return {"ok": False, "message": "安装包里缺少必需文件：" + "、".join(info["missing"])}
    _log(log, f"EndfieldJiggle：安装包已就位（v{version or '?'}，{info['count']} 个文件）")
    return {"ok": True, "changed": True, "version": version, "files": info["count"],
            "path": str(payload_dir(config)), "archive": str(keep),
            "message": f"安装包 v{version or '?'} 已就位"}


def open_upstream() -> dict[str, Any]:
    """打开上游仓库页面（设置页的入口）。"""
    import webbrowser

    try:
        webbrowser.open(UPSTREAM_URL)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"打不开浏览器: {exc}", "url": UPSTREAM_URL}
    return {"ok": True, "url": UPSTREAM_URL}
