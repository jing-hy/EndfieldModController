# SPDX-License-Identifier: GPL-3.0-or-later
"""EndfieldJiggle-EFMI（触摸形变 Mod）集成。

**它和乳摇 / Poser 不是一类东西**：那两个是"游戏目录 proxy + `plugin\\*.dll`"注入型插件，
而 EndfieldJiggle 只是**一个 EFMI 框架下的 Mod 目录** —— 放进 EFMI 的 `Mods` 就会被加载，
不换任何系统 DLL、不需要 loader、不写游戏目录。所以本模块的"装卸"只是**铺目录 / 移出目录**。

三处落点（全在数据根内，全程可逆，**不改第三方依赖本体、不动 `library/`**）：

    <staging_mods_dir>/EndfieldJiggleEFMI                    启用态（EFMI 会加载它）
    <runtime>/jiggle_efmi/_parked/EndfieldJiggleEFMI         停用态（真的移出了 Mods）
    <runtime>/jiggle_efmi/_payload/EndfieldJiggleEFMI        本地载荷（部署源）
    <runtime>/jiggle_efmi/_pack/*.zip                        上游安装包原文 + version.txt

三条硬约定（2026-10-13 落地时逐条核对过）：

* **「关」必须把目录真的移出 `Mods`**：EFMI 的 `d3dx.ini` 里是 `include_recursive = Mods`
  （见 `launcher.ensure_efmi_early_includes` 的论证），它按**递归扫 ini** 加载，与目录名无关
  ⇒ 改名、或挪到 `Mods` 下的子目录，**都挡不住加载**。
* **不随包分发**：上游 GPL-3.0-only，而且作者在 README / `docs/PROVENANCE.md` 里明确写了
  "项目源码许可**不转授**游戏衍生兼容材料"（`Passes.ini`、native picker 适配与 cache 都是
  从本机抓的游戏 shader 接口生成的）⇒ 一律从上游 Release 下原文（同 Poser 模式）。
* **能不能生效由上游的 shader 抓取决定**：`Passes.ini` 是 12 组 `ShaderRegex`（按游戏着色器
  **反汇编文本**做正则匹配），游戏更新重编译着色器就可能失配，游戏内表现为
  `EJ: NO COMPATIBLE NATIVE PROGRAM`。本模块只如实报状态，不承诺"装了就一定有效果"。

上游：https://github.com/woakato/EndfieldJiggle-EFMI
"""
from __future__ import annotations

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
#   `...-drop-in-win64.zip`（72.7 MB，含配置器 EXE）
#   `...-standalone-win64.zip`（149 MB，内置官方 EFMI + XXMI 渲染库 + 自己的启动器）
# 后两个对本程序**没有意义**（EFMI / XXMI 由我们自己维护），而且一个 149 MB 的包下下来
# 只会白白占地方；所以这里用**精确正则**而不是 `"win64.zip" in name` 那种模糊判据
# —— 后者会把三个包全匹配上，取 max 时按名字里的版本号排序，选中的可能是 149 MB 那个。
ASSET_RE = re.compile(r"^EndfieldJiggleEFMI-v?(\d+(?:\.\d+)+)-win64\.zip$", re.IGNORECASE)

MOD_DIR_NAME = "EndfieldJiggleEFMI"
COMPONENT_DIR_NAME = "jiggle_efmi"
VERSION_FILE = "version.txt"
# 安装时记下的**逐文件 sha256**（内容级完整性基线，见 `verify`）。
CHECKSUMS_FILE = "checksums.json"
# 单个文件超过这个就不进哈希清单：本组件的文件都是几十~几百 KB（ini / hlsl / bin）。
MAX_HASH_BYTES = 8 * 1024 * 1024

# 目录"齐不齐"的判据：上游纯 Mod 包是 13 个文件（ini ×3 + shaders ×3 hlsl + 4 bin+…），
# 这里只钉**功能上必需**的那几个 —— 多出来的编译产物（`*.bin`）随版本变化，不该当判据。
REQUIRED_FILES = ("EndfieldJiggle.ini", "Passes.ini", "Outfits.ini")
SHADER_DIR_NAME = "shaders"
REQUIRED_SHADERS = ("step_cs.hlsl", "input_controller.hlsl", "motion_model.hlsl")

LICENSE_ID = "GPL-3.0-only"
LICENSE_NOTE = (
    "上游 woakato/EndfieldJiggle-EFMI（GPL-3.0-only）。本程序只从它的官方 Release "
    "下载**纯 Mod 包**（约 120 KB）并铺进 EFMI 的 Mods 目录，不随包分发、不修改其内容；"
    "作者声明源码许可不转授其中的游戏衍生兼容材料（Passes.ini 等），故一律走在线下载。"
)

# 它自己声明的 EFMI 框架最低版本（`EndfieldJiggle.ini` 里 `$\EFMIv1\required_version = 1.47`）。
# ⚠️ 上游写法是 `1.47`（两位），含义是 **1.4.7**，不是 1.47.0 —— 别拿它当三位版本号比。
REQUIRED_EFMI_VERSION = "1.4.7"

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        log(message)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- 路径
def staging_root(config: AppConfig) -> Path:
    """EFMI 的 `Mods` 目录（= 控制器的 staging，用户可能把它指到自己的 XXMI 上）。"""
    return config.staging_mods_path


def mod_dir(config: AppConfig) -> Path:
    """启用态：EFMI 会加载它的那个目录。"""
    return staging_root(config) / MOD_DIR_NAME


def component_root(config: AppConfig) -> Path:
    """本组件自己的地盘（载荷 / 上游包 / 停用副本 / 版本号）。"""
    return config.jiggle_efmi_path


def payload_dir(config: AppConfig) -> Path:
    """本地载荷：部署源。停用态与启用态都从它派生。"""
    return component_root(config) / "_payload" / MOD_DIR_NAME


def park_dir(config: AppConfig) -> Path:
    """停用态：从 `Mods` 里搬出来的那份（放在我们自己的目录里，不在 staging 内）。"""
    return component_root(config) / "_parked" / MOD_DIR_NAME


def _version_file(config: AppConfig) -> Path:
    return component_root(config) / VERSION_FILE


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
    """本地有没有**可部署的载荷**（或一份完好的停用副本）。"""
    return bool(_inspect(payload_dir(config))["ok"] or _inspect(park_dir(config))["ok"])


def installed_version(config: AppConfig) -> str:
    """本地已装的版本号（`import_pack` 从上游资产名解析后写进 `version.txt`）。"""
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


def pick_asset(release: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """在某个 release 里挑**纯 Mod 包**，返回 `(版本号, 资产)`；没有可用的返回 None。"""
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
    """本地 EFMI 版本够不够它要求（`required_version = 1.47` ⇒ 1.4.7）。

    ⚠️ 读不到版本时**不判**（返回 `ok=True` + `unknown=True`）：这只说明我们没记下 EFMI
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
                    archive: Path | None = None) -> None:
    """把"刚铺好的这份载荷"的哈希清单落盘 —— 之后 `verify()` 就靠它查损坏。"""
    import hashlib
    import json as _json

    payload: dict[str, Any] = {
        "version": version or installed_version(config),
        "asset": asset,
        "files": _file_hashes(payload_dir(config)),
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


def verify(config: AppConfig) -> dict[str, Any]:
    """把**现在这份 Mod**与安装时记下的哈希逐个比对 —— 查的是**内容**，不是"文件在不在"。

    ★ 用户 2026-10-13 反馈：「**下载后的文件损坏检测按钮和启动检查不出来**」。
    只判 `is_file()` 确实查不出来：zip 半截下载、安全软件破坏、跨盘复制中断，都会留下
    **大小看着正常、内容不对**的文件。这里用三层判据补上：

      ① **下载当场**：上游 Release 的 `SHA256SUMS-*.txt` / asset `digest` 做 sha256 校验
         （见 `_digest_from_release`），外加 zip 的 CRC 全量扫描（见 `import_pack`）；
      ② **装好之后**：本函数按安装时记下的逐文件 sha256 比对，任一个不符就是"损坏"；
      ③ **能自愈**：`repack_from_local()` 用 `_pack` 里留存的原始包重新解出载荷再铺一遍。

    没记过基线（老版本装的 / 手工放的）⇒ `known=False` + `ok=True`：
    **不拿"读不到基线"当"损坏"**，那会误报。
    """
    baseline = load_checksums(config)
    files = baseline.get("files") or {}
    if not files:
        return {"ok": True, "known": False, "missing": [], "corrupt": [],
                "checked": 0, "dir": str(mod_dir(config)), "version": ""}
    target = mod_dir(config) if mod_dir(config).is_dir() else payload_dir(config)
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

    ⚠️ 为什么 `deploy` 需要它（2026-10-13）：`deploy` 原来的短路判据只有
    `_inspect(target)["ok"]`（= 文件在不在）。于是"Mods 里那份已经被下坏/改坏"时，
    它会认定"已就位"直接返回 ⇒ 自愈路径**空转**，界面还全绿。
    """
    baseline = load_checksums(config)
    files = baseline.get("files") or {}
    if not files or not target.is_dir():
        return True
    actual = _file_hashes(target)
    return all(name in actual and actual[name] == str(want) for name, want in files.items())


def repack_from_local(config: AppConfig, log: Log = None) -> dict[str, Any]:
    """用 `_pack` 里留存的原始安装包**重新解出载荷**（损坏时的本地自愈路径，不联网）。

    判据与"能自动做掉的就别让用户手动"一致：本地有原始包就自己修，没有才让他去依赖页重下。
    """
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
    return {"ok": False, "message": "本地没有可用的原始安装包（依赖页点「自动安装/更新」重新下载）"}


def _digest_from_release(release: dict[str, Any], asset_name: str, log: Log = None) -> str:
    """从同一个 Release 的 `SHA256SUMS-*.txt` 附件里取该资产的 sha256（取不到返回空串）。

    ⚠️ 为什么需要它：`github.releases_latest` **默认走网页路线**（省 API 额度、能借镜像线路），
    而网页路线的 asset **没有 `digest` 字段** ⇒ 光靠 `asset["digest"]` 的话，
    绝大多数用户（没 token / 走镜像）那条路上"下载损坏"根本没人校验 —— 这正是
    「下载后的文件损坏检测不出来」的一个来源。上游正好随包发了一份 `SHA256SUMS-v*.txt`
    （几百字节），拿它补上最划算。
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
    target = mod_dir(config)
    parked = park_dir(config)
    payload = payload_dir(config)
    live = _inspect(target)
    parked_info = _inspect(parked)
    payload_info = _inspect(payload)
    efmi = efmi_version_check(config)
    # ★ 内容级校验（用户 2026-10-13：「下载后的文件损坏检测按钮和启动检查不出来」）：
    #   只在**真的铺在 Mods 里**时算它 —— 停用态/未装时算哈希既没意义也白花时间。
    verify_state = (verify(config) if live["ok"]
                    else {"ok": True, "known": False, "missing": [], "corrupt": [],
                          "checked": 0, "dir": str(target), "version": ""})
    return {
        "display": "EndfieldJiggle（触摸形变）",
        "enabled": bool(live["ok"]),          # 真的会在游戏里加载
        "in_mods": target.is_dir(),
        "present": bool(target.is_dir() or parked.is_dir() or payload.is_dir()),
        "parked": parked.is_dir(),
        "payload_ready": bool(payload_info["ok"] or parked_info["ok"]),
        "files_ok": bool(live["ok"]),
        "missing": live["missing"],
        "file_count": live["count"],
        "version": installed_version(config),
        "mod_dir": str(target),
        "parked_dir": str(parked),
        "staging_root": str(staging_root(config)),
        "upstream": UPSTREAM_URL,
        "license": LICENSE_ID,
        "efmi_ok": bool(efmi["ok"]),
        "efmi_version": efmi["version"],
        "efmi_required": efmi["required"],
        "efmi_unknown": bool(efmi.get("unknown")),
        # 内容级校验（前端/自检/完整性检查都用这三项）
        "verify": verify_state,
        "verified": bool(verify_state.get("ok")),
        "corrupt": list(verify_state.get("corrupt") or []),
        "dropped": list(verify_state.get("missing") or []),
    }


# ---------------------------------------------------------------- 部署 / 开关
def deploy(config: AppConfig, log: Log = None) -> dict[str, Any]:
    """确保 `Mods\\EndfieldJiggleEFMI` 就位（幂等，不联网）。"""
    target = mod_dir(config)
    if _inspect(target)["ok"] and _content_ok(config, target):
        return {"ok": True, "changed": False, "actions": [], "state": status(config),
                "message": "EndfieldJiggle 已在 EFMI\\Mods 里就位"}

    parked = park_dir(config)
    payload = payload_dir(config)
    source: Path | None = None
    move_from_park = False
    # ⚠️ **停用副本优先**（2026-10-13 测试抓到）：它本来就是"上次从 Mods 移出去的那一份"，
    # 移动回来零重复；若先认载荷就会 copytree 出一份新的，而停用副本**留在原地** ——
    # 于是每开关一次就多一份副本，界面上还会一直显示"已停用"。
    if _inspect(parked)["ok"]:
        source = parked
        move_from_park = True
    elif _inspect(payload)["ok"]:
        source = payload

    if source is None:
        return {
            "ok": False, "changed": False, "actions": [], "state": status(config),
            "message": ("本地还没有 EndfieldJiggle 的安装包 —— 依赖页点「自动安装/更新」"
                        "会从上游 Release 拉取纯 Mod 包（约 120 KB）"),
        }

    actions: list[str] = []
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        # 目录在、但不完整（半装 / 被别的工具改过）：先整份挪开留证，绝不原地删。
        broken = target.with_name(f"{target.name}.broken-{_stamp()}")
        shutil.move(str(target), str(broken))
        actions.append(f"检测到不完整的旧目录，已整份移到 {broken.name}（没有删除）")
    if move_from_park:
        shutil.move(str(source), str(target))
        # 停用区空了就把那层空目录收掉（留着会让 `status()["parked"]` 之类看着像还有副本）。
        try:
            source.parent.rmdir()
        except OSError:
            pass
        actions.append(f"已把停用副本移回 {target}")
    else:
        shutil.copytree(source, target)
        actions.append(f"已把本地载荷铺进 {target}")
    _log(log, f"EndfieldJiggle：{actions[-1]}")
    state = status(config)
    return {"ok": True, "changed": True, "actions": actions, "state": state,
            "message": "EndfieldJiggle 已就位（进游戏按 Ctrl+Shift+F8 开触摸）"}


def set_enabled(config: AppConfig, enabled: bool, log: Log = None) -> dict[str, Any]:
    """启动页开关：开 = 铺进 `Mods`；关 = **真的移出 `Mods`**（改名挡不住加载）。"""
    target = mod_dir(config)
    if enabled:
        if _inspect(target)["ok"] and _content_ok(config, target):
            return {"ok": True, "changed": False, "actions": [], "state": status(config),
                    "message": "EndfieldJiggle 本来就是开启状态"}
        return deploy(config, log=log)

    if not target.is_dir():
        return {"ok": True, "changed": False, "actions": [], "state": status(config),
                "message": "EndfieldJiggle 不在 EFMI\\Mods 里（已经是关闭状态）"}

    parked = park_dir(config)
    # 只动我们自己地盘里的停用副本：`park_dir` 由 `config.jiggle_efmi_path` 决定，
    # 与用户的 Mod 库（`library/`）无关 —— 「任何情况都不要动用户的 Mod 库」是硬红线。
    parked.parent.mkdir(parents=True, exist_ok=True)
    if parked.is_dir():
        shutil.rmtree(parked, ignore_errors=True)
    shutil.move(str(target), str(parked))
    _log(log, f"EndfieldJiggle：已把 {MOD_DIR_NAME} 移出 Mods（停用态保存在 {parked}）")
    return {"ok": True, "changed": True,
            "actions": [f"已把 {MOD_DIR_NAME} 移出 EFMI\\Mods（EFMI 递归加载，改名挡不住）"],
            "state": status(config),
            "message": "EndfieldJiggle 已关闭（目录移出 Mods，未删除任何文件）"}


# ---------------------------------------------------------------- 安装包
def import_pack(config: AppConfig, archive: Path, *, version: str = "", log: Log = None) -> dict[str, Any]:
    """把上游 zip 变成"可部署载荷"，并把原包留一份、写版本号。

    ⚠️ **不能按固定层级取**：上游纯 Mod 包是三层套法（2026-10-13 实测 v0.2.2）

        EndfieldJiggleEFMI-v0.2.2/Mods/EndfieldJiggleEFMI/EndfieldJiggle.ini

    而拖放包/独立包的层级又不一样 ⇒ 一律"在解压结果里搜 `EndfieldJiggle.ini` 所在的那层"。
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
        # 半截下载 / 传输损坏：与其铺一堆坏文件进 Mods，不如当场说"重新下载"。
        return {"ok": False,
                "message": f"安装包已损坏（无法作为 zip 打开：{exc}）—— "
                           "删掉本地那份后重新下载一次"}
    except OSError as exc:
        return {"ok": False, "message": f"解压安装包失败: {exc}"}

    if not info["ok"]:
        return {"ok": False, "message": "安装包里缺少必需文件：" + "、".join(info["missing"])}
    # ★ 记下逐文件 sha256（内容级基线）：之后 `verify()` / 完整性检查 / 启动自检
    #   就能查出"文件在但内容被换过 / 半截"，而不是只看 `is_file()`。
    write_checksums(config, version=version, asset=archive.name, archive=archive)
    _log(log, f"EndfieldJiggle：安装包已就位（v{version or '?'}，{info['count']} 个文件）")
    return {"ok": True, "changed": True, "version": version, "files": info["count"],
            "path": str(payload_dir(config)), "archive": str(keep),
            "message": f"安装包 v{version or '?'} 已就位"}


def install(config: AppConfig, log: Log = None, *, force: bool = False) -> dict[str, Any]:
    """装/修：本地载荷在位就不联网；否则从上游 Release 下**纯 Mod 包**再铺进 Mods。

    与 `poser.install` 同一套语义（2026-10-03 定的）：
      * 本地已在位 ⇒ **一个字节都不下**（用户只是点了下开关，不该有网络请求）；
      * 本地没有 ⇒ 才去下载（`force=True` 是给依赖页那个显式入口用的）。
    """
    from . import github, updates

    result: dict[str, Any]
    if not force and payload_ready(config):
        _log(log, "EndfieldJiggle：本地载荷已在位 → 不联网，直接铺进 Mods")
        result = deploy(config, log=log)
        result.setdefault("changed", False)
        return result

    # ★ **离线优先**（2026-10-13 补，与内置组件 / ReShade / DLSS5-Feeder / Poser 同一条规矩）：
    #   连不上 GitHub 的机器靠「离线依赖包」搬运 —— 命中就**一个网络请求都不发**
    #   （用户问过「离线包确定有新的这个嘛」：离线包里必须有它，否则默认开着的新组件
    #   在那种机器上首次一键启动必然失败）。
    try:
        from . import offline_deps

        offline = offline_deps.resolve_offline(config, "EndfieldJiggle")
    except Exception:  # noqa: BLE001 —— 离线链路异常不该挡住正常下载
        offline = None
    if offline is not None:
        source, offline_version, offline_asset, _digest = offline
        _log(log, f"EndfieldJiggle：用离线依赖包里的 {offline_asset}"
                  f"（v{offline_version or '?'}），不联网")
        result = import_pack(config, Path(source), version=str(offline_version or ""), log=log)
        if not result.get("ok"):
            return result
        deployed = deploy(config, log=log)
        deployed["pack"] = {"version": offline_version, "asset": offline_asset, "offline": True}
        return deployed

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
    # ★ 下载校验（用户 2026-10-13：「下载后的文件损坏检测不出来」）：
    #   ① API 路线自带 `digest`（`sha256:…`）；
    #   ② **网页路线没有 digest** —— 那就去同一个 Release 取上游那份 `SHA256SUMS-*.txt`；
    #   ③ 两条都拿不到才退化成"只做 zip CRC 扫描"（`import_pack` 里那一步）。
    digest = str(asset.get("digest") or "")
    if not digest:
        digest = _digest_from_release(release, asset_name, log=log)
    _log(log, f"EndfieldJiggle：从上游下载 v{version}（{asset_name}）"
              + ("，并用上游 sha256 校验" if digest else "，拿不到上游 sha256（退化为 zip CRC 校验）"))
    try:
        with tempfile.TemporaryDirectory(prefix="mc-jiggle-") as tmp:
            archive = updates.download_file(url, Path(tmp) / asset_name, log=log, timeout=600,
                                            expected_sha256=digest)
            result = import_pack(config, archive, version=version, log=log)
    except Exception as exc:  # noqa: BLE001 - 校验不过 / 网络断，都给可读原因
        return {"ok": False, "message": f"下载/校验/解压失败: {exc}"}
    if not result.get("ok"):
        return result
    deployed = deploy(config, log=log)
    deployed["pack"] = {"version": version, "asset": str(asset.get("name") or ""),
                        "size": int(asset.get("size") or 0)}
    return deployed


def open_upstream() -> dict[str, Any]:
    """打开上游仓库页面（设置页的入口）。"""
    import webbrowser

    try:
        webbrowser.open(UPSTREAM_URL)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"打不开浏览器: {exc}", "url": UPSTREAM_URL}
    return {"ok": True, "url": UPSTREAM_URL}
