"""随仓库分发的二进制资产（DLSS 运行库 + 无上游的 DLSS5 组件）——首次启动自动展开。

两类资产都放在 `assets/` 下、**压缩 + 按需分卷**，由本模块在启动自检时自动
解压回 `dlss5_dir`，让用户拿到仓库/便携包就能开箱即用：

* `assets/nvngx/` —— `nvngx_dlss.dll` / `nvngx_dlssnr.dll`。后者压缩后 103 MB，
  超过 GitHub 单文件 100 MiB 上限，所以切成 `.part1` / `.part2`；
  NVIDIA 官方 SDK 也**没有** `nvngx_dlssnr.dll` 的直链，只能随包。
* `assets/dlss5/` —— DLSS5 底座里**查不到公开上游**的三个 addon
  （Endfield Enhancer 第一人称、ReShade 面板汉化、RenoDX-DLSS5 汉化版）。

有公开上游的组件（ReShade 底座、DLSS5-Feeder、iMMERSE shader、XXMI/EFMI）
不在这里，走 `dlss5_fetcher` 的在线自动安装。

设计要点（都对应用户踩过的坑）：

* **流式**：按分卷顺序喂 `LZMADecompressor`，全程不把 165 MB 读进内存；
* **先校验后落盘**：解压到同目录的 `.mc-tmp`，比对大小与 sha256 通过后
  `os.replace` 原子改名——中途断电/磁盘满不会留下半截的 DLL；
* **幂等**：目标文件大小与清单一致就直接跳过，不重复解压（每次重解 5~15 秒
  会让"一键启动"变慢）；
* **有进度**：解压是慢操作，必须给 UI/日志可见的进度，不能黑着。

资产由 `scripts/pack_nvngx_assets.py` 生成，清单见各目录下的 `manifest.json`。
"""
from __future__ import annotations

import hashlib
import json
import lzma
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import PROJECT_ROOT, AppConfig

# 资产组：目录名 → 说明（都解压到 dlss5_dir）
ASSET_GROUPS: dict[str, str] = {
    "nvngx": "NVIDIA DLSS 运行库（随包，压缩分卷）",
    "dlss5": "DLSS5 组件包（随包内置：第一人称插件 + 面板汉化 + NR 引擎 7.0.0-rc8）",
}
MANIFEST_NAME = "manifest.json"
CHUNK = 1 << 22
TMP_SUFFIX = ".mc-tmp"

# ★ 展开的**并发保护**（2026-10-05 修；反馈者 23:50 那份日志是现场）：
#   一键启动会在两条路径上各展开一次（`initialize.ensure_all` 与 `ensure_injections`），
#   而临时文件原先用**固定名**（`<目标>.mc-tmp`）⇒ 两个线程踩同一个 tmp：
#   一个在算 sha256 时读到另一个正在写的内容 ⇒ 日志报
#   「sha256 校验失败（得到 2d8b3e2f…，期望 e16bcf15…）」，**运气差还会把半成品落位**。
#   现在两道闸：① `ensure_all` 整段串行（省掉重复的 165 MB 干活）；
#   ② 临时文件名带 pid + 线程号（即便真有并发也互不踩，各写各的、各自校验后原子替换）。
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_ENSURE_ALL_LOCK = threading.Lock()


def _target_lock(target: Path) -> threading.Lock:
    """取这个目标文件专属的进程内锁（懒建；键按小写路径，Windows 不区分大小写）。"""
    key = str(target).lower()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _tmp_path(target: Path) -> Path:
    """展开用的临时文件：**每次独一无二**。

    必须和目标**同目录**（`os.replace` 跨盘会报 `WinError 17`），所以只加后缀、不换目录。
    """
    return target.with_name(f"{target.name}.{os.getpid()}-{threading.get_ident()}{TMP_SUFFIX}")

Progress = Callable[[str, int, int], None] | None


@dataclass
class AssetResult:
    name: str
    status: str          # present | extracted | missing_source | error
    message: str = ""
    size: int = 0
    sha256: str = ""
    path: str = ""
    group: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in {"present", "extracted"}


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def asset_roots(config: AppConfig, group: str) -> list[Path]:
    """某组资产的**全部**候选根（按优先级，只留真正带 manifest.json 的）。

    ⚠️ 为什么要"全部"而不是"第一个"（2026-10-06 定案）：清单原先只取**第一个**命中的根，
    而**数据根排在 exe 内嵌之前** ⇒ 用户那句旧的 `<数据根>/assets/` 会一直命中，
    内嵌的新清单**永远轮不到** ⇒ "只换 exe"的升级拿不到任何新增/替换的随包资产。
    实测：DLSS4 的 addon 条目不在旧清单里 ⇒ 开着一键启动也永远展不出来。
    ⇒ 现在把全部候选交出去，由 `manifest_entries()` **按条目合并**（数据根优先、缺的从内嵌补）。
    """
    subdir = Path("assets") / group
    candidates: list[Path] = []
    # 允许用配置项覆盖根目录（个别用户会把 assets 挪到别处）
    configured = getattr(config, "nvngx_assets_dir", "") or ""
    if configured and group == "nvngx":
        candidates.append(config.resolve_path(configured))
        candidates.append(config.resolve_path(configured).parent / "dlss5")
    candidates.append(PROJECT_ROOT / subdir)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / subdir)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / subdir)
    candidates.append(Path(__file__).resolve().parents[1] / subdir)

    found: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if (candidate / MANIFEST_NAME).is_file():
                found.append(candidate)
        except OSError:
            continue
    return found


def group_root(config: AppConfig, group: str) -> Path | None:
    """某组资产目录（**优先级最高**的那个候选）—— 落盘/解压目标仍用它。"""
    roots = asset_roots(config, group)
    return roots[0] if roots else None


def load_manifest(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def iter_assets(config: AppConfig) -> Iterator[tuple[str, Path, str, dict[str, Any]]]:
    """依次产出 (组名, **该条目所在的**资产目录, 文件名, 清单条目)。

    ★★ **按条目合并多个候选根**（2026-10-06 定案）：见 `asset_roots()` ——
    只取"第一个命中的根"时，用户机器上那句旧的 `<数据根>\\assets\\` 会一直命中，
    **exe 内嵌的新清单永远轮不到** ⇒ "只换 exe"的升级拿不到任何新增/替换的随包资产
    （实测：DLSS4 的 addon 条目不在旧清单里 ⇒ 开着开关也永远展不出来；
    NR 引擎换代还变成"停用了旧的、又按旧清单把旧的装回来"）。
    合并口径：**优先级高的根先出**，同名条目取先出现的那个（数据根里用户自放的仍优先）。
    ⚠️ 每个条目都带上**它自己所在的 root** —— 解压/校验要按那个目录去找 `.xz` 分卷，
    不能拿"第一个命中的根"去凑。
    """
    for group in ASSET_GROUPS:
        roots = asset_roots(config, group)
        if not roots:
            continue
        emitted: set[str] = set()
        for root in roots:
            for name, entry in (load_manifest(root).get("files") or {}).items():
                key = str(name)
                if key in emitted or not isinstance(entry, dict):
                    continue
                emitted.add(key)
                yield group, root, key, dict(entry)


def manifest_entries(config: AppConfig) -> list[tuple[str, Path, str, dict[str, Any]]]:
    return list(iter_assets(config))


# ---------------------------------------------------------------------------
# 随包组件基线校验（2026-09-30 加）
# ---------------------------------------------------------------------------
# 「DLSS5-Feeder」是在线组件（不随包、由 dlss5_fetcher 安装），所以它的基线写在这里。
# ⚠ 2026-09-30 实测更正：**0.1.0（76,800 B）与 1.18.0-beta.1（332,800 B）在终末地上都能
# 正常出帧**（modtest 实测：1.18 从 13:19 跑到 13:22、frame 7200、35 fps、NGX 310.8），
# 所以"与随包不同"**只是差异提示，不是故障判定** —— 别再写"1.18 不会出帧"这种断言
# （此前 README 与自检文案都这么写，是错的）。真不出帧时要看 dlss5-feed.log 与面板 NR 帧。
def _baseline_hint(name: str) -> str:
    """给"缺失/大小不符"补一句"这意味着什么、该怎么修"。

    2026-09-30 issue #3：用户 `runtime\\dlss5\\nvngx_dlssnr.dll` 被动过，自检只报
    "与基线不一致"，看不出后果与动作 —— 而面板那边其实已经在喊 NR 起不来。

    ⚠️ 判据用 `variant_from_name()` 而不是写死文件名：运行库现在有 `official` / `sf` /
    `rtx40` 三个变体（`nvngx_dlssnr.sf.dll` 等），提示不能只认不带后缀那个名字。
    """
    if variant_from_name(name):
        return (
            "；这是 DLSS5 神经渲染(NR)用的**签名运行时**，缺了/被换过就会"
            "「NR feature 未绑定、成功 NR 帧恒为 0、最新 NR NGX 结果 0xBAD00001」。"
            "删掉该文件后点「一键启动」会重新展开；若它反复消失，把 runtime\\dlss5 "
            "加进杀毒软件白名单"
        )
    return ""


# 哈希校验只对小资产做：`nvngx_dlss.dll`(59 MB) / `nvngx_dlssnr.dll`(165 MB) 全量 sha256
# 每次自检要读两百多 MB，会把"一键启动"拖慢好几秒 —— 大文件只比大小；几个 addon
# （合计约 6 MB）才逐个校验内容，"大小对但内容被换过"就能查出来了。
MAX_HASH_BYTES = 16 << 20

FEED_NAME = "dlss5-feed.addon64"
FEED_BASELINE_SIZE = 76_800
FEED_BASELINE_SHA256 = "6ea59b3237ed9f1e2bdc6e258518347ccb7e03dfdc2f96fc08addc8974527dad"
# **已知可用的 feed 版本集合**（按字节数认）。它是在线组件，「一键安装/更新全部组件」
# 本来就会装上游最新版 —— 所以"**不等于随包那一版**"**不算异常**，只有落在集合之外才提醒。
#   76,800  = 0.1.0（随包那一版，"built Aug 29"）
#   332,800 = 1.18.0-beta.1（上游 2026-09-29 发布；09-30 与 10-02 两次实测在终末地上正常出帧）
#   344,064 = 1.18.0-beta.2（上游 2026-10-06 04:30 发布）
#             ★ 2026-10-07 本机实测：**正常** —— ReShade 日志
#               `Registered add-on "DLSS 5 Feed 1.18.0-beta.2" v1.18.0.2`，
#               NR `inline feature 18 evaluation succeeded (count=1 → count=60)`，
#               游戏 `Player.log` 444 行、正常退出收尾（非早退）。
#             ⚠️ 这条实测是必要的：此前集合停在 10-02，而 beta.2 是 10-06 发的，
#               **落在集合外** ⇒ 每次自检都报"不在已知可用的版本里"（纯噪音，用户 10-02
#               就为此抱怨过一次），且会让人误以为"上游新版有问题"。**实测不支持这个推断**：
#               那次反馈者崩溃的诱因另有其因（他跑 v1.0.28，而"数据根优先 ⇒ 拿不到新随包资产"
#               的修复在 v1.0.29）。
FEED_KNOWN_GOOD_SIZES = (76_800, 332_800, 344_064)


# ---------------------------------------------------------------------------
# DLSS5 神经渲染运行库：按显卡架构自动选变体（2026-10-05 新增）
# ---------------------------------------------------------------------------
# 背景（用户 2026-10-05 原话）：「把目前管理器采用的 dlss5 方案换成现在这个，
# 去掉所有对非 50 系的锁」+「不论任何支持的型号，都能相同步骤一键启动」。
#
# DLSS5 的神经渲染代码跑在 `nvngx_dlssnr.dll` 里，而那份运行库是**按 CUDA 架构分别
# 编译**的 —— NVIDIA 官方那份只带 sm_120（Blackwell）。本项目实测的三份候选：
#
#   变体        来源                            内含内核（fatbin 记录，2026-10-05 实测）
#   official    310.8.0（NVIDIA 官方）          sm_120 ×30
#   rtx40       310.8.0-RTX40（社区重定向）     sm_89 ×15 + sm_120 ×30
#   sf          310.8.SF-v2（社区 FP16 路径）   sm_75 ×15 + sm_86 ×15 + sm_89 ×15 + sm_120 ×23
#
# **随包 `official` + `sf` 两份即可覆盖 RTX 20/30/40/50 全部受支持型号** ⇒ 一键启动
# 永远不需要为运行库下载任何东西（四种机器走完全同一条链、耗时同量级）。
# `rtx40` 是 40 系的**可选优化**（依赖页下载）：不装也完整可用，装了一键启动自动切到它。
DLSSNR_TARGET = "nvngx_dlssnr.dll"
DLSSNR_MARKER = ".dlssnr_variant.json"
# 目标架构 → 候选变体优先级（取第一个"在位且含本机架构"的）
DLSSNR_ORDER: dict[int, tuple[str, ...]] = {
    120: ("official", "sf", "rtx40"),
    89: ("rtx40", "sf", "official"),
    86: ("sf", "official", "rtx40"),
    75: ("sf",),
}
# CUDA fatbin 魔数（0xBA55ED50 小端）与已知 sm 号（同上游工具的判据集合）
_FATBIN_MAGIC = (0xBA55ED50).to_bytes(4, "little")
_KNOWN_SM = frozenset({75, 80, 86, 87, 89, 90, 100, 120, 121})


@dataclass
class DlssnrChoice:
    """「本机该用哪一份 DLSS5 运行库」的结论。"""
    sm: int | None                 # 本机最高架构（None = 不支持）
    variant: str                   # 首选变体（`deviceinfo` 的建议）
    effective: str                 # 实际会用的变体；空 = 一份可用的都没有
    source_name: str = ""          # 候选源文件名（随包资产名或裸 dll 名）
    source_kind: str = ""          # packed（随包压缩包，需解压）| plain（裸 dll，复制即可）
    target: str = ""               # 目标路径
    reason: str = ""               # 给用户看的理由
    candidates: tuple[str, ...] = ()   # 在位且含本机架构的变体

    @property
    def ok(self) -> bool:
        return bool(self.effective)


def dll_architectures(path: Path) -> set[int]:
    """读 DLL 里 **CUDA fatbin 记录**声明的架构集合（如 `{75, 86, 89, 120}`）。

    为什么不用 PE/ELF 头：内核 cubin 是压缩的，架构号写在 fatbin entry 的 header 里。
    做法与社区工具（DLSS5-Autopilot `core/gpu.py`）同源：扫 `0xBA55ED50` 魔数 →
    读 headerSize/fatSize → 逐个 entry 试偏移 24/28/20 上的 sm 字段。

    ⚠️ 这是**启发式识别**（不是反汇编），但对"这份文件能不能在本机跑"足够 ——
    它给出的正是我们要的判据，且与上游一致。用 mmap，只把真正读到的页换进来
    （文件有 165 MB，整份读进内存没必要）。
    """
    import mmap
    import struct

    found: set[int] = set()
    try:
        with open(path, "rb") as handle:
            try:
                data: Any = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                data = handle.read()
            try:
                offset = 0
                while True:
                    hit = data.find(_FATBIN_MAGIC, offset)
                    if hit < 0:
                        break
                    offset = hit + 4
                    try:
                        header_size = struct.unpack_from("<H", data, hit + 6)[0]
                        fat_size = struct.unpack_from("<Q", data, hit + 8)[0]
                        if header_size < 16 or not (0 < fat_size <= len(data)):
                            continue
                        walk, end = hit + header_size, hit + header_size + fat_size
                        while walk < end - 32:
                            entry_header = struct.unpack_from("<I", data, walk + 4)[0]
                            payload = struct.unpack_from("<Q", data, walk + 8)[0]
                            if entry_header < 24 or entry_header > 4096 or not (0 < payload <= len(data)):
                                break
                            for shift in (24, 28, 20):
                                if walk + shift + 4 > len(data):
                                    continue
                                sm = struct.unpack_from("<I", data, walk + shift)[0]
                                if sm in _KNOWN_SM:
                                    found.add(sm)
                                    break
                            walk += entry_header + payload
                    except Exception:  # noqa: BLE001 - 启发式扫描，坏块跳过即可
                        continue
            finally:
                if hasattr(data, "close"):
                    data.close()
    except OSError:
        return set()
    return found


def variant_from_name(name: str) -> str:
    """`nvngx_dlssnr.sf.dll` → `sf`；`nvngx_dlssnr.dll.xz.part1` → `official`。

    命名约定（`scripts/pack_nvngx_assets.py` 与依赖页下载都照它）：
    `nvngx_dlssnr.dll`（official，不带后缀）/ `nvngx_dlssnr.<变体>.dll`。
    """
    import re

    stem = str(name).lower()
    stem = re.sub(r"\.part\d+$", "", stem)
    if stem.endswith(".xz"):
        stem = stem[:-3]
    if not stem.endswith(".dll"):
        return ""
    stem = stem[: -len(".dll")]
    if stem == "nvngx_dlssnr":
        return "official"
    if stem.startswith("nvngx_dlssnr."):
        return stem.split(".", 1)[1]
    return ""


def _dlssnr_sources(config: AppConfig) -> dict[str, tuple[str, Path | None, dict[str, Any] | None]]:
    """{变体: (源文件名, 裸文件路径, manifest 条目)}。

    * **随包候选**：manifest 里"装成 `nvngx_dlssnr.dll`"的条目（压缩分卷，需解压）；
    * **下载候选**：直接躺在 `assets\\nvngx\\` 的**裸 dll**（如 `nvngx_dlssnr.rtx40.dll`）
      —— 依赖页下载或"导入本地 zip"放进去的，复制即可、不必解压。
    随包的优先级更高（离线可用）。
    """
    out: dict[str, tuple[str, Path | None, dict[str, Any] | None]] = {}
    root = group_root(config, "nvngx")
    for _group, _root, name, entry in manifest_entries(config):
        if str(entry.get("install_as") or name) != DLSSNR_TARGET:
            continue
        variant = str(entry.get("variant") or variant_from_name(name))
        if variant:
            out[variant] = (name, None, entry)
    if root is not None:
        for path in sorted(root.glob("nvngx_dlssnr*.dll")):
            variant = variant_from_name(path.name)
            if variant and variant not in out:
                out[variant] = (path.name, path, None)
    return out


def dlssnr_marker_path(config: AppConfig) -> Path:
    return Path(config.dlss5_path) / DLSSNR_MARKER


def read_dlssnr_marker(config: AppConfig) -> dict[str, Any]:
    """上次把哪一份落成了目标文件（用来**免去每次启动重扫 165 MB**）。"""
    from . import fsutil

    data = fsutil.read_json(dlssnr_marker_path(config))
    return data if isinstance(data, dict) else {}


def write_dlssnr_marker(
    config: AppConfig, *, variant: str, sm: int | None, path: Path,
    archs: set[int] | None = None,
) -> None:
    """记下"这份文件是哪一变体、含哪些架构、多大" —— 让下次启动**不必再扫 165 MB**。

    `archs` 是**文件实际内含**的架构集合（不是本机 sm）：同一份 `sf` 同时服务 20/30/40 系，
    换卡后靠它就能判定"还是这一份、不用换"，省掉一次扫描。
    """
    from . import fsutil

    try:
        fsutil.write_json(dlssnr_marker_path(config), {
            "variant": variant,
            "sm": sm,
            "arch": sorted(int(item) for item in (archs or set())),
            "file": path.name,
            "size": path.stat().st_size if path.is_file() else 0,
            "at": int(time.time()),
        })
    except (OSError, ValueError):
        pass


def _installed_matches(config: AppConfig, sm: int | None, *, rescan: bool = False) -> bool:
    """目标文件是否已经是"含本机架构"的那一份。

    快路径看 marker（不碰那 165 MB）；marker 丢了/对不上时**扫一次 fatbin**
    （实测 0.1 秒）—— 比"重新解压 165 MB（5~15 秒）"划算得多，而且升级、清缓存、
    被整合包替换过之后都能自愈。`rescan=True` = 无条件真扫（自检用）。
    """
    target = Path(config.dlss5_path) / DLSSNR_TARGET
    if not target.is_file() or sm is None:
        return False
    if not rescan:
        marker = read_dlssnr_marker(config)
        if marker and int(marker.get("size") or 0) == target.stat().st_size:
            # ⚠️⚠️ **只能看 `arch`，绝不能看 `marker["sm"]`**（2026-10-06 定案，两个 40 系对照包）：
            #   marker 里两个字段的语义**完全不同** ——
            #     `sm`   = **这台机器**的代次（`89`）；
            #     `arch` = **这份 dll 真正带的架构**（`official` 那份是 `[120]`）。
            #   旧写法 `int(marker["sm"]) == sm or sm in archs` 里，前半段**恒真**
            #   ⇒ 任何"已就位"的 dll 都被判成"含本机架构" ⇒ **永不换变体** ⇒
            #   40 系机器上会一直跑着只有 sm_120 内核的 `official` ⇒ **feature 建不出来、
            #   DLSS5 打不开**（对照包铁证：能开的 marker 是 `rtx40 / arch=[89,120]`，
            #   开不了的是 `official / arch=[120]`，两者 `sm` 都是 89）。
            if sm in _marker_archs(marker):
                return True
    return sm in dll_architectures(target)


def _marker_archs(marker: dict[str, Any]) -> set[int]:
    return {int(item) for item in (marker.get("arch") or []) if str(item).isdigit()}


def select_dlssnr_variant(config: AppConfig, *, rescan: bool = False) -> DlssnrChoice:
    """决定本机用哪一份运行库，并说明依据（"按 GPU 自动切换"的唯一判据）。

    顺序：
      ① 目标文件已就位、且确认含本机架构 → 直接用它（幂等，一键启动走这条最快）；
      ② 否则按 `DLSSNR_ORDER` 挑**在位且含本机架构**的候选（随包优先，其次下载来的裸 dll）；
      ③ 都没有 → `effective` 留空，`reason` 说清缺的是哪一份、该怎么办。
    """
    from . import deviceinfo

    target = str(Path(config.dlss5_path) / DLSSNR_TARGET)
    # 判据唯一入口：`best_rtx_sm()` 从 adapters 现算。**不要**读 `collect()` 的派生字段
    # （`dlss5_sm`）—— 那样打桩或精简的调用方会得到"不支持"的错误结论。
    sm = deviceinfo.best_rtx_sm()
    preferred = deviceinfo.dlss5_runtime_variant(sm)
    if sm is None:
        return DlssnrChoice(
            sm=None, variant=preferred, effective="", target=target,
            reason="这台机器没有可用的 NVIDIA RTX 显卡（需要 tensor core，RTX 20 系及以上）",
        )
    sources = _dlssnr_sources(config)
    if _installed_matches(config, sm, rescan=rescan):
        marker = read_dlssnr_marker(config)
        variant = str(marker.get("variant") or preferred)
        return DlssnrChoice(
            sm=sm, variant=preferred, effective=variant,
            source_name=DLSSNR_TARGET, source_kind="installed", target=target,
            reason=f"{_sm_text(sm)} ⇒ 当前已就位的就是含本机架构的那一份（{variant}）",
            candidates=tuple(sources),
        )
    # 候选要真扫 fatbin 才能说"含本机架构"（一个 165 MB 文件约 1 秒级，只在这条慢路径上付）
    usable: list[str] = []
    for variant in DLSSNR_ORDER.get(sm, ()):
        found = sources.get(variant)
        if found is None:
            continue
        name, plain, entry = found
        probe = plain
        if probe is None and entry is not None:
            root = group_root(config, "nvngx")
            if root is not None:
                parts = [root / str(item) for item in (entry.get("parts") or [])]
                if parts and all(item.is_file() for item in parts):
                    # 压缩包不能直接扫 —— 只在"已解压到目标之外"时才扫得动，
                    # 所以随包候选的架构由 manifest 的 `arch` 字段声明（打包时写入实测值）。
                    declared = {int(item) for item in (entry.get("arch") or []) if str(item).isdigit()}
                    if declared:
                        if sm in declared:
                            usable.append(variant)
                        continue
                    usable.append(variant)
                    continue
            continue
        if probe is not None and probe.is_file():
            archs = dll_architectures(probe)
            if not archs or sm in archs:
                usable.append(variant)
    if not usable:
        return DlssnrChoice(
            sm=sm, variant=preferred, effective="", target=target,
            reason=(f"{_sm_text(sm)} 需要变体 `{preferred}`，但**随包/本地都没有含该架构的运行库**"
                    f"（已找到的候选：{'、'.join(sources) or '无'}）—— "
                    f"可在依赖页点「一键安装/更新全部组件」，或用「导入本地 zip」导入资产包"),
            candidates=tuple(sources),
        )
    chosen = usable[0]
    name, plain, _entry = sources[chosen]
    return DlssnrChoice(
        sm=sm, variant=preferred, effective=chosen,
        source_name=name, source_kind="plain" if plain is not None else "packed",
        target=target,
        reason=(f"{_sm_text(sm)} ⇒ 用变体 `{chosen}`"
                + (f"（首选 `{preferred}` 不在位，已按候选顺序回落）" if chosen != preferred else "")),
        candidates=tuple(usable),
    )


def _sm_text(sm: int | None) -> str:
    from . import deviceinfo

    return deviceinfo._sm_label(sm) if sm else "未识别的显卡"


def ensure_dlssnr(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    progress: Progress = None,
    force: bool = False,
    rescan: bool = False,
) -> AssetResult:
    """把**本机该用的那一份**运行库落到 `runtime\\dlss5\\nvngx_dlssnr.dll`。

    这是"按显卡架构自动切换"的**唯一落点** —— 一键启动、启动自检、完整性修复都只调它，
    所以换卡、被整合包替换、双卡换主卡都能自愈。
    """
    group = "nvngx"
    choice = select_dlssnr_variant(config, rescan=rescan)
    target = Path(config.dlss5_path) / DLSSNR_TARGET
    if not choice.ok:
        status = "missing_source" if choice.sm is None else "missing_source"
        return AssetResult(DLSSNR_TARGET, status, choice.reason, 0, "", str(target), group)
    if choice.source_kind == "installed" and not force:
        return AssetResult(
            DLSSNR_TARGET, "present",
            f"已就位（变体 {choice.effective}；{choice.reason}）",
            target.stat().st_size if target.is_file() else 0, "", str(target), group,
        )
    sources = _dlssnr_sources(config)
    found = sources.get(choice.effective)
    if found is None:
        return AssetResult(DLSSNR_TARGET, "missing_source",
                           f"变体 {choice.effective} 的源文件已经不在了", 0, "", str(target), group)
    name, plain, entry = found
    if entry is not None:
        root = group_root(config, "nvngx")
        if root is None:
            return AssetResult(DLSSNR_TARGET, "missing_source", "找不到 assets\\nvngx 目录", 0, "", str(target), group)
        result = ensure_file(
            config, name, entry, root, group=group, progress=progress, log=log,
            force=True, install_as=DLSSNR_TARGET,
        )
        # ⚠️ `ensure_file` 报的是**源文件名**（如 `nvngx_dlssnr.sf.dll`），但这一项对
        # 调用方与用户来说都叫目标文件 `nvngx_dlssnr.dll` —— 统一过来，否则按名字筛的
        # 地方（`ensure_all` 的结果、依赖页的 key、自检）会筛不到它。
        result.name = DLSSNR_TARGET
    else:
        result = _install_plain_dll(config, plain, target, log=log)
    if result.ok:
        try:
            archs = dll_architectures(target) if target.is_file() else set()
        except Exception:  # noqa: BLE001 - 记不下架构不影响本次切换
            archs = set()
        write_dlssnr_marker(
            config, variant=choice.effective, sm=choice.sm, path=target, archs=archs,
        )
        result.message = f"{result.message}｜变体 {choice.effective}（{choice.reason}）"
    return result


def _install_plain_dll(
    config: AppConfig, source: Path | None, target: Path,
    *, log: Callable[[str], None] | None = None,
) -> AssetResult:
    """把下载来的**裸 dll** 复制成目标名（旧的先备份成 `.bak-<时间戳>`）。"""
    import shutil

    if source is None or not source.is_file():
        return AssetResult(DLSSNR_TARGET, "missing_source", "下载来的运行库不在位", 0, "", str(target), "nvngx")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            backup = target.with_name(target.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                shutil.copy2(target, backup)
            except OSError:
                pass
        # ⚠️ 临时文件必须**独一无二**（2026-10-05 修）：固定名时两个并发展开会互踩，
        #    一个算出的是另一个正在写的内容 ⇒ 假报 sha256 失败、甚至把半成品落位。
        tmp = _tmp_path(target)
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
    except OSError as exc:
        return AssetResult(DLSSNR_TARGET, "error", f"复制运行库失败: {exc}", 0, "", str(target), "nvngx")
    _log(log, f"已按显卡架构切换运行库：{source.name} → {target.name}")
    return AssetResult(
        DLSSNR_TARGET, "extracted",
        f"已从 {source.name} 切换（{target.stat().st_size:,} B）",
        target.stat().st_size, "", str(target), "nvngx",
    )


def baseline_mismatches(config: AppConfig, *, check_hash: bool = False) -> list[dict[str, Any]]:
    """随包组件与「实测可用基线」的差异列表（供启动自检告警）。

    判据一律用**文件大小 +（可选）sha256**，**不要**用崩溃日志里模块的 `size`
    ——那是 SizeOfImage（内存映像），2026-09-30 我拿它当文件大小用，误判过一整轮。

    ⚠️⚠️ **DLSS5 运行库按"本机生效的那一份"判**（2026-10-05）：目标文件是**按显卡架构
    选出来的变体**，若拿固定条目去比，40/30/20 系机器上那份**正确的** `sf` 会被判成
    "偏离随包基线" ⇒ 触发 `repair_mismatched` 换回 `official` ⇒ 下次再被判不符 ⇒
    **每次启动来回替换 165 MB 的死循环**。所以：只校验与 `effective` 同名的那条，
    其余变体的源文件本来就不该出现在 `dlss5_dir`。
    """
    target_root = Path(config.dlss5_path)
    mismatches: list[dict[str, Any]] = []
    try:
        effective = select_dlssnr_variant(config).effective
    except Exception:  # noqa: BLE001 - 判据异常时退化成"不校验运行库"，也不误报
        effective = ""

    for group, _root, name, entry in manifest_entries(config):
        install_as = str(entry.get("install_as") or name)
        if install_as == DLSSNR_TARGET:
            if variant_from_name(name) != effective:
                continue
            path = target_root / install_as
        else:
            path = target_root / name
        expected = int(entry.get("size") or 0)
        want_sha = str(entry.get("sha256") or "")
        if not path.is_file():
            mismatches.append({
                "name": name, "group": group, "kind": "missing",
                "expected": expected, "actual": 0,
                "message": (f"{name} 不在 runtime\\dlss5（随包基线 {expected:,} 字节）"
                            + _baseline_hint(name)),
            })
            continue
        actual = path.stat().st_size
        if expected and actual != expected:
            mismatches.append({
                "name": name, "group": group, "kind": "size",
                "expected": expected, "actual": actual,
                "message": (f"{name} 是 {actual:,} 字节，随包基线 {expected:,} 字节 —— "
                            f"可能被别的整合包替换或手动升级过" + _baseline_hint(name)),
            })
            continue
        if check_hash and want_sha and 0 < expected <= MAX_HASH_BYTES:
            got = sha256_file(path)
            if got and got.lower() != want_sha.lower():
                mismatches.append({
                    "name": name, "group": group, "kind": "hash",
                    "expected": expected, "actual": actual,
                    "message": f"{name} 大小对但内容与基线不一致（sha256 不符）",
                })

    feed = target_root / FEED_NAME
    if feed.is_file():
        size = feed.stat().st_size
        if size not in FEED_KNOWN_GOOD_SIZES:
            mismatches.append({
                "name": FEED_NAME, "group": "online", "kind": "size",
                "expected": FEED_BASELINE_SIZE, "actual": size,
                "message": (f"{FEED_NAME} 是 {size:,} 字节，**不在已知可用的版本**里"
                            f"（随包 {FEED_BASELINE_SIZE:,} = 0.1.0；"
                            f"上游 1.18.0-beta.1 = 332,800、1.18.0-beta.2 = 344,064）—— "
                            f"若面板「成功NR帧」长期为 0，点「一键安装/更新全部组件」换回上游版"),
            })
        elif check_hash and size == FEED_BASELINE_SIZE:
            got = sha256_file(feed)
            if got and got.lower() != FEED_BASELINE_SHA256:
                mismatches.append({
                    "name": FEED_NAME, "group": "online", "kind": "hash",
                    "expected": FEED_BASELINE_SIZE, "actual": size,
                    "message": f"{FEED_NAME} 大小对但内容被改过（sha256 与随包基线不一致）",
                })
    return mismatches


def baseline_summary(config: AppConfig, *, check_hash: bool = False) -> dict[str, Any]:
    """给自检 / 界面用的一行式摘要。"""
    mismatches = baseline_mismatches(config, check_hash=check_hash)
    total = len(manifest_entries(config)) + 1      # +1 = dlss5-feed.addon64
    return {
        "ok": not mismatches,
        "total": total,
        "mismatches": mismatches,
        "detail": "；".join(item["message"] for item in mismatches),
    }


# 运行时清单里算 sha256 的上限。比 `MAX_HASH_BYTES` 大得多：`nvngx_dlssnr.dll` 有 165 MB，
# 而它恰恰是最需要留指纹的那个（2026-09-30 一整轮误判就是因为它被换过）。
INVENTORY_HASH_LIMIT = 512 << 20


def repair_mismatched(
    config: AppConfig,
    mismatches: list[dict[str, Any]],
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把"与基线不一致的**随包**组件"重新展开（原文件先备份一份）。

    用户 2026-10-02 的现场：配套里有文件偏离了随包基线 ⇒ 游戏每次启动后几十秒崩在
    `nvgpucomp64`，而自检**只提示、不修**，他最后只能自己把整个 `runtime\\` 删掉重下才好。
    ⇒ 我们自己发出去的组件坏掉，必须**自动修**（准则：「能自动处理的故障，不要用提示来交付」）。

    **在线组件（`dlss5-feed.addon64`）不在这里修** —— 它本来就允许被更新成上游最新版。
    **备份**：`<文件名>.bak-before-baseline-restore`（只留第一份 —— 那才是用户当时在用的）。
    """
    import shutil

    targets = sorted({str(item.get("name")) for item in mismatches
                      if str(item.get("group") or "") != "online"})
    if not targets:
        return {"ok": True, "repaired": [], "failed": [], "message": "没有需要自动修复的随包组件"}
    entries = {
        name: (group, root, entry) for group, root, name, entry in manifest_entries(config)
    }
    target_root = Path(config.dlss5_path)
    repaired: list[str] = []
    failed: list[str] = []
    # DLSS5 运行库要**按本机架构重新选一份**，而不是"把源文件展开成同名文件" ——
    # 它的正确形态取决于这台机器是哪一代卡（见 `select_dlssnr_variant`）。
    dlssnr_targets = [name for name in targets if variant_from_name(name)]
    targets = [name for name in targets if not variant_from_name(name)]
    if dlssnr_targets:
        try:
            outcome = ensure_dlssnr(config, log=log, force=True, rescan=True)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{DLSSNR_TARGET}（按显卡架构重选失败：{exc}）")
        else:
            if outcome.ok:
                repaired.append(f"{DLSSNR_TARGET}（已按本机架构重选：{outcome.message}）")
            else:
                failed.append(f"{DLSSNR_TARGET}（{outcome.message}）")
    for name in targets:
        dest = target_root / name
        found = entries.get(name)
        if found is None:
            failed.append(f"{name}（随包资产里没有这一项，只能手动处理）")
            continue
        group, root, entry = found
        if dest.is_file():
            backup = dest.with_name(dest.name + ".bak-before-baseline-restore")
            try:
                if not backup.exists():
                    shutil.copy2(dest, backup)
            except OSError as exc:
                failed.append(f"{name}（备份失败：{exc}，为安全起见没有覆盖它）")
                continue
        try:
            result = ensure_file(config, name, entry, root, group=group, force=True, log=log)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}（重新展开失败：{exc}）")
            continue
        status = str(getattr(result, "status", "") or "")
        if status in ("present", "extracted"):
            repaired.append(name)
            _log(log, f"随包组件已按基线重新展开: {name}")
        else:
            failed.append(f"{name}（{getattr(result, 'message', '') or status or '未知'}）")
    parts: list[str] = []
    if repaired:
        parts.append("已按随包基线重新展开 " + "、".join(repaired))
    if failed:
        parts.append("以下项需要手动处理：" + "；".join(failed))
    return {
        "ok": not failed,
        "repaired": repaired,
        "failed": failed,
        "message": "；".join(parts) or "无需修复",
    }


def runtime_inventory(config: AppConfig, *, with_hash: bool = True) -> list[dict[str, Any]]:
    """**运行时组件清单**：文件名 / 字节 / sha256 / 与随包基线是否一致。

    给崩溃包与诊断包用（用户 2026-10-01 要求「一次抓全」）。2026-10-02 的现场里正是
    因为它缺失，才回答不了"崩溃那一刻装的是哪一版组件" —— 用户把 runtime 删掉重下之后，
    旧现场连清单都不剩，崩因只能停在"配套损坏"这个类别上。
    """
    root = Path(config.dlss5_path)
    if not root.is_dir():
        return []
    baseline = {item["name"]: item for item in baseline_mismatches(config, check_hash=with_hash)}
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        size = path.stat().st_size
        row: dict[str, Any] = {"name": path.name, "size": size}
        if with_hash and size <= INVENTORY_HASH_LIMIT:
            try:
                row["sha256"] = sha256_file(path)
            except OSError:
                row["sha256"] = ""
        bad = baseline.get(path.name)
        row["baseline"] = "ok" if bad is None else f"{bad['kind']}(基线 {bad['expected']:,})"
        rows.append(row)
    return rows


def inventory_text(config: AppConfig, *, with_hash: bool = True) -> str:
    """把运行时清单渲染成一段可直接塞进崩溃包 / 诊断包的文本。"""
    rows = runtime_inventory(config, with_hash=with_hash)
    if not rows:
        return "（runtime\\dlss5 目录不存在）"
    lines = [f"runtime\\dlss5 共 {len(rows)} 个文件（OK=与随包基线一致，!!=偏离基线）", ""]
    for row in rows:
        mark = "OK" if row.get("baseline") == "ok" else "!!"
        sha = str(row.get("sha256") or "")[:16]
        lines.append(
            f"{mark}  {row['size']:>13,} B  {sha:<16}  {row['name']}   [{row.get('baseline')}]"
        )
    return "\n".join(lines)


def sha256_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    """复用 fsutil 的那一份实现（这里只保留对外签名与 progress 回调语义）。"""
    from . import fsutil

    return fsutil.sha256_file(path, progress)


def _decompress_parts(parts: list[Path], dest: Path, *, progress: Progress, name: str) -> int:
    """按序拼接分卷并流式解压到 dest，返回写出的字节数。"""
    total = sum(part.stat().st_size for part in parts)
    written = 0
    done = 0
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    with open(dest, "wb") as out:
        for part in parts:
            with open(part, "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    data = decompressor.decompress(chunk)
                    if data:
                        out.write(data)
                        written += len(data)
                    if progress:
                        progress(name, done, total)
            if decompressor.eof:
                break
        if not decompressor.eof:
            raise lzma.LZMAError("压缩流不完整（分卷缺失或被截断）")
    return written


def ensure_file(
    config: AppConfig,
    name: str,
    entry: dict[str, Any],
    root: Path,
    *,
    group: str = "",
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
    install_as: str = "",
) -> AssetResult:
    """确保 `dlss5_dir\\<name>` 在位（缺失/损坏时从内置资产展开）。

    `install_as`：把源资产落成**另一个目标名** —— DLSS5 运行库的变体机制用它
    （源文件叫 `nvngx_dlssnr.sf.dll`，但 NGX 只认 `nvngx_dlssnr.dll`）。留空 = 原名。
    """
    target = config.dlss5_path / (install_as or name)
    expected_size = int(entry.get("size") or 0)
    expected_sha = str(entry.get("sha256") or "")

    if target.is_file() and not force:
        size = target.stat().st_size
        if not expected_size or size == expected_size:
            if verify and expected_sha:
                actual = sha256_file(target)
                if actual == expected_sha:
                    return AssetResult(name, "present", f"{size:,} B（已校验）", size, actual, str(target), group)
                _log(log, f"{name}: 内容校验不符，将从内置资产修复")
            else:
                return AssetResult(name, "present", f"{size:,} B 已就位", size, "", str(target), group)
        else:
            _log(log, f"{name}: 现有文件 {size:,} B 与内置版本 {expected_size:,} B 不符，重新展开")

    part_names = [str(p) for p in (entry.get("parts") or [])]
    if not part_names:
        return AssetResult(name, "missing_source", "清单里没有分卷记录", 0, "", str(target), group)
    parts = [root / part for part in part_names]
    missing = [part.name for part in parts if not part.is_file()]
    if missing:
        return AssetResult(
            name, "missing_source",
            f"内置资产缺分卷 {missing}（重新运行 scripts\\pack_nvngx_assets.py）",
            0, "", str(target), group,
        )

    packed_bytes = sum(part.stat().st_size for part in parts)
    try:
        config.dlss5_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return AssetResult(name, "error", f"无法创建 {config.dlss5_path}: {exc}", 0, "", str(target), group)

    try:
        free = shutil.disk_usage(config.dlss5_path).free
        if expected_size and free < expected_size + (16 << 20):
            return AssetResult(
                name, "error",
                f"磁盘空间不足：需要约 {expected_size // 1048576} MB，可用 {free // 1048576} MB",
                0, "", str(target), group,
            )
    except OSError:
        pass

    # ⚠️ 临时文件必须**独一无二**（2026-10-05 修）：固定名时两个并发展开会互踩，
    #    一个算出的是另一个正在写的内容 ⇒ 假报 sha256 失败、甚至把半成品落位。
    tmp = _tmp_path(target)
    started = time.time()
    _log(log, f"展开内置资产 {name}（{packed_bytes / 1048576:.1f} MB 压缩包 → {expected_size / 1048576:.1f} MB）")
    actual_sha = ""
    try:
        written = _decompress_parts(parts, tmp, progress=progress, name=name)
        if expected_size and written != expected_size:
            raise lzma.LZMAError(f"解压大小不符：得到 {written:,} B，清单要求 {expected_size:,} B")
        actual_sha = sha256_file(tmp)
        if expected_sha and actual_sha != expected_sha:
            raise lzma.LZMAError(f"sha256 校验失败（得到 {actual_sha[:16]}…，期望 {expected_sha[:16]}…）")
        os.replace(tmp, target)
    except (OSError, lzma.LZMAError, EOFError) as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return AssetResult(name, "error", f"展开失败: {exc}", 0, "", str(target), group)
    elapsed = time.time() - started
    return AssetResult(
        name, "extracted",
        f"已从内置资产展开（{target.stat().st_size:,} B，{elapsed:.1f}s）",
        target.stat().st_size, actual_sha, str(target), group, elapsed,
    )


def _is_dlssnr_item(item: tuple[str, Path, str, dict[str, Any]]) -> bool:
    """这条资产是不是"DLSS5 神经渲染运行库"（含各变体）？

    判据：它最终要落成的名字就是 `nvngx_dlssnr.dll`（`install_as` 优先，其次自身名）。
    """
    _group, _root, name, entry = item
    return str(entry.get("install_as") or name) == DLSSNR_TARGET


# 已退役的随包 NR 引擎（2026-10-06：由 4.70 换成官方 7.0.0-rc8）。
# 为什么必须**主动搬走**而不是只报出来：ReShade 会加载底座根目录里的**所有** `*.addon64`，
# 而两个 neural addon 同装时**两个都不工作**（DLSS5-Feeder 原话：
# "Never install two neural add-ons … it does nothing at all for the whole session"）；
# 且旧版 4.70 在驱动 616.64 及以上会 evaluate 崩在 NVIDIA 自己的 `nvngx_dlssnr.dll`
# （Feeder issue #54，官方矩阵 0/300）。用户升级后旧文件会留在原地
# ⇒ 不搬走就等于"升级了还是坏的"。
RETIRED_NR_ADDONS = ("renodx-dlss5-4.7.addon64", "renodx-dlss5-4.7_汉化.addon64")
# 匹配用的通配（覆盖中文/拼音等历史命名：`_汉化` / `_hanhua` / 无后缀）
RETIRED_NR_GLOB = "renodx-dlss5-4.7*.addon64"
# 换代后**新** NR 引擎在随包清单里的条目名 —— `retire_stale_nr_addons()` 用它校验
# "停用了旧的之后，新的到底在不在清单里"；不在就说明这台机器的 `assets\` 是旧的一份
# （换 exe 不会更新它），必须明确报警而不是照旧清单把旧的装回去（2026-10-06 定案）。
NEW_NR_ENTRY = "renodx-dlss5.addon64"
RETIRED_DIR = "_retired_addons"


def retire_stale_nr_addons(config: AppConfig, *,
                           log: Callable[[str], None] | None = None) -> list[str]:
    """把**已退役**的旧 NR 引擎从 `dlss5` 根目录搬进 `_retired_addons\\`（只搬不删，可还原）。"""
    base = Path(config.dlss5_path)
    if not base.is_dir():
        return []
    moved: list[str] = []
    found: list[Path] = []
    for pattern in (RETIRED_NR_GLOB, *RETIRED_NR_ADDONS):
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path not in found:
                found.append(path)
    for source in found:
        name = source.name

        target_dir = base / RETIRED_DIR
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / name
            if dest.exists():
                import time as _time

                dest = target_dir / f"{name}.{_time.strftime('%Y%m%d-%H%M%S')}"
            shutil.move(str(source), str(dest))
        except OSError as exc:
            _log(log, f"旧版 NR 引擎 {name} 搬走失败（忽略）：{exc}")
            continue
        moved.append(name)
        _log(log, "已停用旧版 NR 引擎 " + name + f"（搬到 {RETIRED_DIR}\\，可还原）——"
                  "旧版在驱动 616.64 及以上会崩在 nvngx_dlssnr.dll，已改用随包的 7.0.0-rc8")
    # ★★ **搬走旧的之后，必须确认"新版那份在清单里到底有没有"**（2026-10-06 定案）。
    #    否则就是实测里那种自相矛盾：先"已停用旧版…已改用 7.0.0-rc8"，
    #    紧接着又照**旧清单**把 `4.7汉化` 展开回来 —— 用户看到的是一句"已改用新的"
    #    加一句"展开 4.7汉化"，而真正该出现的新 addon 永远不会来。
    #    根因是资产清单取自 `<数据根>\assets\<组>\manifest.json`，**换 exe 不会更新它**。
    if moved:
        try:
            entries = {n for _g, _r, n, _e in iter_assets(config)}
        except Exception:  # noqa: BLE001
            entries = set()
        if NEW_NR_ENTRY not in entries:
            _log(log,
                 f"⚠ 已停用旧版 NR 引擎，但清单里**没有**新版（{NEW_NR_ENTRY}）—— "
                 "这台机器的 `assets\\` 可能是旧的一份（**换 exe 不会更新它**）。"
                 "去「依赖页 → 导入随包 zip…」重新导入 `assets-bundle.zip`，"
                 "之后点一次一键启动即可拿到新版")
    return moved


def ensure_all(
    config: AppConfig,
    *,
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
    allow_fetch: bool = True,
) -> list[AssetResult]:
    """展开所有随包资产里缺失的文件（**同一进程内串行**）。已就位的直接跳过。

    本地没有 `assets\\`（典型情况：用户只下了单文件 exe，没下资产包）时，
    会尝试从本仓库 Release 拉一次 `assets-bundle.zip` 再展开。

    ★ 串行化（2026-10-05 修）：一键启动会在 `initialize.ensure_all` 与
    `ensure_injections` 两条路径上各调一次，于是同一个 165 MB 资产被**并发展开两遍** ——
    加上当时临时文件用固定名，日志里就出现了
    「sha256 校验失败（得到 2d8b3e2f…，期望 e16bcf15…）」（反馈者 23:50 那份日志即现场）。
    加这把锁之后，第二次进来时文件已在位，直接走"已就位"快路径。
    """
    with _ENSURE_ALL_LOCK:
        return _ensure_all_locked(config, progress=progress, log=log, force=force,
                                  verify=verify, allow_fetch=allow_fetch)


def _ensure_all_locked(
    config: AppConfig,
    *,
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
    allow_fetch: bool = True,
) -> list[AssetResult]:
    """`ensure_all` 的实现体 —— **调用方必须已持有 `_ENSURE_ALL_LOCK`**。"""
    # **必须在任何分支之前导入**：之前只把它放在"本地没有 assets"的分支里，结果本地
    # 有 assets 时后面的 `dependencies.run_batch_with_retry` 直接 UnboundLocalError
    # （2026-10-01 实测抓到）。
    import time as _time

    from . import dependencies

    # ⚠️ **先搬走退役的旧 NR 引擎**（2026-10-06）：两个 neural addon 同装时两个都不工作。
    retire_stale_nr_addons(config, log=log)

    # ⚠️⚠️ **清单里也要把它们排除掉**（2026-10-07 实测抓到）：
    #    数据根那份 `assets\dlss5\manifest.json` 可能是**旧的**（上面还列着
    #    `renodx-dlss5-4.7_汉化.addon64`），而合并口径是"数据根优先" ⇒ 旧条目依然生效
    #    ⇒ **展开时又把退役引擎铺回根目录** ⇒ 与新版**同名**（都叫 "DLSS 5 Neural Rendering"）
    #    ⇒ ReShade 报 `Failed to register add-on … already registered! (error 1114)`
    #    ⇒ **NR 实际没生效**（本机实测：`vtable::Hook(Failed to find …EvaluateFeature_C)`）。
    #    这是上游明确警告过的「Never install two neural add-ons … it does nothing at all」。
    #    ⇒ 在**展开之前**就把退役条目从清单里剔掉，从源头上不让它落盘。
    _found_before_filter = manifest_entries(config)
    retired_names = {name.lower() for name in RETIRED_NR_ADDONS}

    def _is_retired(entry_name: str) -> bool:
        lowered = entry_name.lower()
        return lowered in retired_names or (
            "renodx-dlss5-4.7" in lowered and lowered.endswith(".addon64"))

    found = [item for item in _found_before_filter if not _is_retired(item[2])]
    if len(found) != len(_found_before_filter):
        _log(log, "随包清单里剔除了已退役的旧 NR 引擎（两个同名 neural addon 会导致两个都不工作）："
                  + "、".join(sorted(n for _g, _r, n, _e in _found_before_filter if _is_retired(n))))
    if not found and allow_fetch:
        # 拉资产包是**网络下载**，失败要重试（用户 2026-10-01 要求「全部下载完之后如果
        # 有失败项，就重试，3 次截止」）。以前一次失败就直接报"找不到随包资产"，
        # 界面上看起来就是"完成，但有 1 项失败"。
        for attempt in range(dependencies.MAX_BATCH_RETRIES + 1):
            if attempt:
                _log(log, f"资产包获取失败，重试第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次 …")
            fetched = fetch_bundle(config, log=log, force=bool(attempt))
            if fetched.get("changed"):
                found = manifest_entries(config)
                break
            if attempt >= dependencies.MAX_BATCH_RETRIES:
                if fetched.get("message"):
                    _log(log, f"未能获取资产包：{fetched['message']}")
            else:
                _time.sleep(1.5)
    if not found:
        return [AssetResult(
            "*", "missing_source",
            "找不到随包资产目录 assets\\nvngx、(assets\\dlss5)"
            "（源码/便携包不完整，或用的是旧版 Release）",
        )]

    # ⚠️ **DLSS5 运行库（含变体）不在这里逐个展开** —— 它由 `ensure_dlssnr()` 按本机
    # 显卡架构**只选一份**落成 `nvngx_dlssnr.dll`。这正是"任何受支持型号都走同一条链、
    # 耗时同量级"的前提（展开两份 = 白解压 165 MB）。过滤放在"确认资产目录存在"之后，
    # 否则只剩运行库条目时会被上面那句误判成"找不到随包资产"。
    fixed_items = [item for item in found if _is_dlssnr_item(item)]
    found = [item for item in found if not _is_dlssnr_item(item)]

    def worker(item: tuple[str, Path, str, dict[str, Any]], attempt: int) -> AssetResult:
        group, root, name, entry = item
        if attempt:
            _log(log, f"重试展开资产 {name}（第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次）…")
        result = ensure_file(
            config, name, entry, root,
            group=group, progress=progress, log=log,
            force=force or bool(attempt), verify=verify,
        )
        # **缺失也要重试**（用户 2026-10-01 明确要求）—— 状态不是"已就位 / 已展开"就
        # 当作失败交给重试逻辑；缺失通常是分卷没解开或上次下载中断，force 重跑一次
        # 往往就补上了。只有重试完仍缺，才在结果里如实报"缺失"。
        status = str(getattr(result, "status", "") or "")
        if status not in ("present", "extracted"):
            raise RuntimeError(getattr(result, "message", "") or f"{name}: {status or '缺失'}")
        return result

    # 单项失败不中断其它项，失败项再重试（与下载同一套策略）
    outcomes, _pending = dependencies.run_batch_with_retry(list(found), worker)
    results: list[AssetResult] = []
    # ① **先按显卡架构把运行库落好**（放在最前：后面的 DLSS5 组件与游戏目录补齐都可能用到它）。
    #    不支持的机器（A 卡 / 核显 / GTX）报 `skipped` 而不是"缺失"，避免制造噪音。
    try:
        choice = select_dlssnr_variant(config)
    except Exception as exc:  # noqa: BLE001 - 判不动就退回"不支持"，不拖垮整套展开
        choice = DlssnrChoice(sm=None, variant="", effective="", reason=f"判据异常: {exc}")
    if choice.sm is None:
        results.append(AssetResult(DLSSNR_TARGET, "skipped", choice.reason, group="nvngx"))
    else:
        try:
            # ⚠️⚠️ **不能写 `force=force or bool(fixed_items)`**（2026-10-07 实测抓到的真凶）。
            #    `fixed_items` = 清单里那两条 `nvngx_dlssnr*` 条目（official + sf）⇒ **恒非空**
            #    ⇒ 那个表达式**恒为 True** ⇒ **每一轮 `ensure_all` 都强制重解压 165 MB**。
            #    代价：本机实测单轮 4.6~4.8 秒，而同一次启动里 `ensure_all` 最多被调 **4 轮**
            #    （`ensure_injections` → `integrity.repair` → `initialize` → `launch`）⇒
            #    **累计约 19 秒**，那段时间主线程被占住，用户看到的是
            #    「刚启动时注入开关全是关的」「过很久才能打开」「DLSS5↔DLSS4 互斥超级慢」。
            #    而"按架构选对那一份 / 换卡或被整合包替换后自愈"这件事，
            #    `ensure_dlssnr` 内部的 `_installed_matches()` **本来就做了**
            #    （marker 快路径 0 秒；marker 丢了才扫一次 fatbin，实测 0.1 秒）
            #    ⇒ 强制重解压纯属多余。
            #    `force` 仍然透传：依赖页「一键更新全部组件」传的就是 `force=True`，那时**要**真重解。
            results.append(ensure_dlssnr(
                config, log=log, progress=progress, force=force,
            ))
        except Exception as exc:  # noqa: BLE001
            results.append(AssetResult(
                DLSSNR_TARGET, "error", f"按显卡架构切换运行库失败: {exc}", group="nvngx"))
    for index, (_group, _root, name, _entry) in enumerate(found):
        kind, payload = outcomes[index]
        if kind == "ok":
            results.append(payload)
        else:
            results.append(AssetResult(name, "error", str(payload)))
    return results


# ---------------------------------------------------------------------------
# 资产包：单文件 exe 用户没有本地 assets 时，从 Release 拉一次
# ---------------------------------------------------------------------------
BUNDLE_PATTERN = "assets-bundle"
BUNDLE_STALE_SECONDS = 24 * 3600


def _extract_bundle(archive: Path, dest_root: Path) -> int:
    """只接受压缩包里 `assets/...` 下的条目（防目录穿越 / 防乱写）。"""
    import zipfile

    written = 0
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
            if "assets" not in parts or ".." in parts:
                continue
            relative = parts[parts.index("assets"):]
            target = dest_root.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            written += 1
    return written


def fetch_bundle(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """从本仓库 Release 下载 `assets-bundle.zip` 并解到工作区（得到 assets\\）。"""
    if not force and any(
        (PROJECT_ROOT / "assets" / group / MANIFEST_NAME).is_file() for group in ASSET_GROUPS
    ):
        return {"ok": True, "changed": False, "message": "本地已有 assets"}

    import urllib.error
    import urllib.request

    from . import github
    from .version import LATEST_API, REPO, USER_AGENT

    stamp = PROJECT_ROOT / "runtime" / "_update" / "bundle-fetch.json"
    if not force and stamp.is_file():
        try:
            last = json.loads(stamp.read_text(encoding="utf-8"))
            if time.time() - float(last.get("at") or 0) < BUNDLE_STALE_SECONDS:
                previous = str(last.get("message") or "")
                # 成功时记的是 "ok:N"（见 remember），直接拿它当"失败原因"会输出
                # "未能获取资产包：ok:5" 这种莫名其妙的话（2026-10-01 修）。
                if previous.startswith("ok:"):
                    previous = "上次已成功展开过内置资产；本次未找到资产包，已跳过（可点重试强制重新拉取）"
                return {"ok": False, "changed": False,
                        "message": previous or "24 小时内已尝试过，跳过"}
        except (OSError, json.JSONDecodeError):
            pass

    def remember(message: str) -> None:
        try:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(json.dumps({"at": int(time.time()), "message": message},
                                        ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # **网页优先 → 失败才打 API**（2026-10-01 修）：原先这里直接请求 `LATEST_API`，
    # 匿名额度一用尽就是 `HTTP Error 403: rate limit exceeded` —— 一份真实诊断包里那台机器
    # **整套随包资产都因此拿不到**（nvngx×2、6 个 shader 标准头、Textures、三个 addon 全缺），
    # 用户看到的就是「缺失 renodx-endfield-enhancer.addon64、无法修复」，界面还一直提示
    # 「随包组件与基线不一致」。自更新检查 / Poser / 公告早就补了网页+镜像回退（`0muo6sow`），
    # **唯独资产包这条路径漏了** —— 现在统一走 `github.releases_latest()`（网页优先、可借镜像）。
    release: dict[str, Any] | None = None
    last_error: object = ""
    for prefer_api in (False, True):
        try:
            release = github.releases_latest(REPO, prefer_api=prefer_api)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        if isinstance(release, dict):
            break
    if not isinstance(release, dict):
        message = f"查询 Release 失败：{last_error}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    # 网页路线拿不到 `digest`（asset 的 sha256）—— **能补就补**：它用来防止第三方镜像
    # 中转时把大文件换掉。API 额度还在就顺手取一份；取不到也不拦着下载。
    if str(release.get("source") or "") == "web":
        try:
            api_release = github.api_get(LATEST_API)
            digests = {
                str(item.get("name") or ""): str(item.get("digest") or "")
                for item in (api_release.get("assets") or [])
            }
            for item in release.get("assets") or []:
                item["digest"] = digests.get(str(item.get("name") or ""), "")
                item["size"] = item.get("size") or next(
                    (int(a.get("size") or 0) for a in (api_release.get("assets") or [])
                     if str(a.get("name") or "") == str(item.get("name") or "")), 0)
        except Exception:  # noqa: BLE001
            pass

    candidates = [
        asset for asset in (release.get("assets") or [])
        if BUNDLE_PATTERN in str(asset.get("name", "")).lower()
        and str(asset.get("name", "")).lower().endswith(".zip")
    ]
    if not candidates:
        message = (f"Release {release.get('tag_name') or ''} 里没有 {BUNDLE_PATTERN}.zip"
                   "（发布时需把 assets 目录压成该附件一起上传）")
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    asset = sorted(candidates, key=lambda a: int(a.get("size") or 0), reverse=True)[0]
    url = str(asset.get("browser_download_url") or "")
    size_mb = int(asset.get("size") or 0) / 1048576
    _log(log, f"本地没有 assets\\，从 Release 下载资产包 {asset.get('name')}（{size_mb:.0f} MB）")
    target = PROJECT_ROOT / "runtime" / "_update" / str(asset.get("name") or "assets-bundle.zip")
    # 资产包走 fastnet（慢/抖时临时并发、直连不通时临时换镜像）：
    # digest 由 GitHub API 给出，用来防止第三方镜像中转时被替换。
    from . import fastnet

    report = fastnet.download(
        url, target, log=log, expected_sha256=str(asset.get("digest") or ""),
    )
    if not report.ok:
        message = f"下载资产包失败：{report.message}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}
    try:
        written = _extract_bundle(target, PROJECT_ROOT)
    except Exception as exc:  # noqa: BLE001
        message = f"解包资产包失败：{exc}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    if not written:
        message = "资产包里没有 assets\\ 内容，已忽略"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    remember(f"ok:{written}")
    _log(log, f"资产包已解出 {written} 个文件")
    return {"ok": True, "changed": True, "files": written, "message": f"已下载并解出 {written} 个文件"}


def variant_for_architectures(archs: set[int]) -> str:
    """按**内含架构**判定一份运行库属于哪个变体（"导入本地 zip"用它认文件）。

    三份变体的内核是包含关系，所以从"最宽"往下判：
      含 sm_75/sm_86 ⇒ `sf`（社区 FP16 路径版，覆盖 20/30/40）
      只多出 sm_89    ⇒ `rtx40`（针对 Ada 重定向的那版）
      只有 sm_120     ⇒ `official`（NVIDIA 官方 Blackwell 版）
    """
    if not archs:
        return ""
    if 75 in archs or 86 in archs:
        return "sf"
    if 89 in archs:
        return "rtx40"
    if 120 in archs:
        return "official"
    return ""


def inspect_assets_zip(archive_zip: Any, names: list[str]) -> dict[str, Any]:
    """**逐条校验**一个"依赖的随包 zip"够不够用（只读，不落地）。

    ⚠️ 为什么不能只看"有没有 `assets/` 目录"（用户 2026-10-05：「**而且也要检查**」）：
    打包/搬运/网盘转存时丢一个分卷是常事，而缺卷的后果是"导入看起来成功、之后解压报错"，
    用户完全不知道哪里不对。同类教训：构造离线素材时**只看文件数/总体积一定会翻车**，
    必须逐条核对关键条目。

    判据（对 zip 里每个 `assets/<组>/manifest.json`）：
      * manifest 要能解析、要有文件清单；
      * 它列出的每个文件，**要么** `assets/<组>/<文件名>`（未压缩形态）在包里，
        **要么**它声明的**全部分卷**都在包里 —— 少一卷就算不完整。
    """
    normalized = {str(name).replace("\\", "/") for name in names}
    groups: dict[str, str] = {}          # 组名 → manifest 在 zip 里的路径
    for name in normalized:
        parts = [part for part in name.split("/") if part not in ("", ".")]
        if len(parts) >= 3 and parts[0] == "assets" and parts[-1] == MANIFEST_NAME:
            groups[parts[1]] = name
    if not groups:
        return {"kind": "", "ok": False, "groups": [], "problems": []}

    problems: list[str] = []
    for group in sorted(groups):
        manifest_name = groups[group]
        try:
            data = json.loads(archive_zip.read(manifest_name).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{group}/manifest.json 读不出来（{exc}）")
            continue
        entries = (data or {}).get("files") if isinstance(data, dict) else None
        if not isinstance(entries, dict) or not entries:
            problems.append(f"{group}/manifest.json 里没有文件清单")
            continue
        for file_name, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            if f"assets/{group}/{file_name}" in normalized:
                continue                  # 未压缩形态直接给出来了，算数
            parts = [str(item) for item in (entry.get("parts") or [])]
            if not parts:
                problems.append(f"{group}：{file_name} 既没有分卷记录、包里也没有这个文件")
                continue
            missing = [item for item in parts if f"assets/{group}/{item}" not in normalized]
            if missing:
                problems.append(f"{group}：{file_name} 缺分卷 {'、'.join(missing)}")
    return {
        "kind": "bundle",
        "ok": not problems,
        "groups": sorted(groups),
        "problems": problems,
    }


def import_bundle(
    config: AppConfig,
    archive: Path,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """**导入"依赖的随包 zip"**（依赖页那个「导入随包 zip…」按钮）。

    ⚠️ 这里只收**依赖组件**，**不收 Mod 压缩包**（Mod 走 Mod 库那条路）—— 界面上也这么写，
    免得用户把皮肤包拖进依赖页。接受两种形态，自动识别：

    ① **完整资产包**（`assets-bundle.zip`）—— 里面是 `assets/<组>/manifest.json` + 分卷。
       解包复用 `_extract_bundle()`（只接受 `assets/` 下的条目、拒绝 `..` 穿越），
       而且**导入前先逐条校验**（`inspect_assets_zip`）：manifest 要能解析、它列出的每个文件
       的**全部分卷都得在包里** —— 少了任何一卷就**拒绝导入**并列出缺什么，
       而不是"看起来导入了、之后解压到处报错"；
    ② **单份组件 zip**（例如社区镜像的 `nvngx_dlssnr_310.8.SF-v2.zip`，里面是裸
       `nvngx_dlssnr.dll`）—— 按**文件内容**（fatbin 记录）判定它属于哪个变体，落到
       `assets\\nvngx\\nvngx_dlssnr.<变体>.dll`，随后的选择逻辑就会自动用它。

    失败时一律**带上这个 zip 的路径与目标位置**（用户准则：凡是让用户自己动手的提示，
    都要给全他能用的地址）。
    """
    import shutil
    import zipfile

    path = Path(archive)
    if not path.is_file():
        return {"ok": False, "message": f"找不到这个文件：{path}"}
    try:
        with zipfile.ZipFile(path) as archive_zip:
            names = [name for name in archive_zip.namelist() if not name.endswith("/")]
    except (zipfile.BadZipFile, OSError) as exc:
        return {"ok": False, "message": f"这个 zip 打不开（{exc}）。文件：{path}"}
    if not names:
        return {"ok": False, "message": f"这个 zip 是空的。文件：{path}"}

    def _has_assets(name: str) -> bool:
        parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
        return "assets" in parts

    asset_entries = [name for name in names if _has_assets(name)]
    runtime_entries = [
        name for name in names
        if Path(name).name.lower().startswith("nvngx_dlssnr") and name.lower().endswith(".dll")
    ]

    if asset_entries:
        # **导入前逐条校验**（用户 2026-10-05：「而且也要检查」）：缺分卷的包**直接拒绝**，
        # 否则会出现"导入看着成功、之后解压到处报错"这种最难查的状态。
        try:
            with zipfile.ZipFile(path) as archive_zip:
                report = inspect_assets_zip(archive_zip, names)
        except (zipfile.BadZipFile, OSError) as exc:
            return {"ok": False, "message": f"这个 zip 读不出来（{exc}）。\n文件：{path}"}
        if report.get("kind") != "bundle":
            return {"ok": False, "message": (
                f"这个 zip 里有 assets 目录，却没有 `assets/<组>/manifest.json` ——\n"
                f"程序没法确认它是**依赖的随包资产**，所以不导入。\n\n"
                f"文件：{path}\n"
                f"目标位置：{PROJECT_ROOT}\\assets\n\n"
                f"（依赖的随包 zip = 完整的 assets-bundle.zip，必须带 manifest.json 与它列出的"
                f"全部分卷。若这是 Mod 压缩包，请到 Mod 库导入，不是这里。）")}
        if not report.get("ok"):
            problems = report.get("problems") or []
            detail = "\n".join("· " + str(item) for item in problems[:12])
            more = f"\n…另有 {len(problems) - 12} 条" if len(problems) > 12 else ""
            return {"ok": False, "message": (
                f"这个 zip 是依赖的随包资产，但**不完整**，导入只会留下半截资产：\n{detail}{more}\n\n"
                f"文件：{path}\n"
                f"（重新拿一份完整的 assets-bundle.zip 再导入；本地没有 assets\\ 时"
                f"一键启动也会自动拉取。）")}
        try:
            written = _extract_bundle(path, PROJECT_ROOT)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": (
                f"解包失败（{exc}）。\n文件：{path}\n应解到：{PROJECT_ROOT}\\assets")}
        if not written:
            return {"ok": False, "message": (
                f"zip 里没有可用的 assets\\ 内容。\n文件：{path}\n应解到：{PROJECT_ROOT}\\assets")}
        # 落地后再确认一次：manifest 真的解到了该去的位置（防"解了但没解对地方"）
        landed = sorted(
            item.parent.name for item in (PROJECT_ROOT / "assets").glob(f"*/{MANIFEST_NAME}")
            if item.is_file()
        )
        if not landed:
            return {"ok": False, "message": (
                f"解包执行了，但 `{PROJECT_ROOT}\\assets` 下没找到任何 manifest.json —— "
                f"资产可能没落到程序会读的位置。\n文件：{path}")}
        _log(log, f"已导入依赖的随包资产：{path.name}（{written} 个文件，组：{'、'.join(landed)}）")
        return {
            "ok": True, "kind": "bundle", "files": written, "groups": landed,
            "message": (f"已导入依赖的随包资产：{written} 个文件（含 {'、'.join(landed)} 组）"
                        f"（来自 {path.name}）。下一步点「一键安装/更新全部组件」或直接一键启动即可。"),
        }

    if runtime_entries:
        member = runtime_entries[0]
        dest_dir = group_root(config, "nvngx") or (PROJECT_ROOT / "assets" / "nvngx")
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "message": (
                f"无法创建目标目录（{exc}）。\n文件：{path}\n目标目录：{dest_dir}")}
        # ⚠️ 临时文件**必须放在目标目录里**（同一卷）：放到别处（例如 `runtime\\_update`）
        # 再 `os.replace` 会报 `WinError 17 系统无法将文件移到不同的磁盘驱动器` ——
        # 用户的资产目录完全可以配在另一个盘上。
        staging = dest_dir / f"nvngx_dlssnr.import-{os.getpid()}.tmp"
        try:
            with zipfile.ZipFile(path) as archive_zip, archive_zip.open(member) as source:
                with open(staging, "wb") as sink:
                    shutil.copyfileobj(source, sink, CHUNK)
        except Exception as exc:  # noqa: BLE001
            try:
                staging.unlink()
            except OSError:
                pass
            return {"ok": False, "message": f"读这个运行库失败（{exc}）。文件：{path}"}
        archs = dll_architectures(staging)
        variant = variant_for_architectures(archs)
        if not variant:
            try:
                staging.unlink()
            except OSError:
                pass
            return {"ok": False, "message": (
                f"认不出这份运行库的架构（它内含 {sorted(archs) or '读不到'}）——"
                f"不是 NVIDIA 的 DLSS 神经渲染运行库。\n文件：{path}")}
        dest = dest_dir / f"nvngx_dlssnr.{variant}.dll"
        try:
            if dest.is_file() and dest.stat().st_size == staging.stat().st_size:
                staging.unlink()
            else:
                os.replace(staging, dest)
        except OSError as exc:
            try:
                staging.unlink()
            except OSError:
                pass
            return {"ok": False, "message": (
                f"写入失败（{exc}）。\n文件：{path}\n目标目录：{dest_dir}")}
        _log(log, f"已导入运行库变体 `{variant}`（内含 {sorted(archs)}）→ {dest_dir}")
        return {
            "ok": True, "kind": "runtime", "variant": variant,
            "arch": sorted(archs), "files": 1,
            "message": (f"已导入 DLSS 神经渲染运行库，识别为变体 **{variant}**"
                        f"（内含架构 {', '.join('sm_' + str(item) for item in sorted(archs))}）。"
                        f"下一步点「一键安装/更新全部组件」让它按你的显卡落位。"),
        }

    return {"ok": False, "message": (
        f"这个 zip 里既没有 assets\\ 目录、也没有 `nvngx_dlssnr*.dll` —— 不是随包资产包。\n"
        f"文件：{path}\n"
        f"（随包资产包应含 assets/…；单份运行库 zip 应含 nvngx_dlssnr.dll）")}


def asset_report(config: AppConfig) -> dict[str, dict[str, Any]]:
    """给依赖页用的状态：内置包是否可用、本地是否已展开、本机在用哪个运行库变体。"""
    report: dict[str, dict[str, Any]] = {}
    try:
        effective = select_dlssnr_variant(config).effective
    except Exception:  # noqa: BLE001
        effective = ""
    for group, root, name, entry in manifest_entries(config):
        install_as = str(entry.get("install_as") or name)
        variant = variant_from_name(name) if install_as == DLSSNR_TARGET else ""
        target = config.dlss5_path / install_as
        parts = list(entry.get("parts") or [])
        parts_ok = all((root / part).is_file() for part in parts)
        expected_size = int(entry.get("size") or 0)
        size_ok = target.is_file() and (not expected_size or target.stat().st_size == expected_size)
        # 运行库有多份变体，而 dlss5_dir 里**只有本机在用的那一份**：只有它该判"已就位"，
        # 其余是备用候选（它们在 assets 里躺着，需要时才展开）。
        in_use = (not variant) or variant == effective
        present = bool(size_ok and in_use)
        packed_bytes = int(entry.get("packed_bytes") or 0)
        if variant and not in_use:
            status = "备用候选"
        elif present:
            status = "已就位"
        elif parts_ok:
            status = "待展开"
        else:
            status = "内置资产缺失"
        report[f"{group}:{name}"] = {
            "display": (f"{ASSET_GROUPS.get(group, group)} · {name}"
                        + (f"（变体 {variant}{'，本机在用' if in_use else ''}）" if variant else "")),
            "source": f"仓库内置 assets/{group}",
            "install_dir": str(config.dlss5_path),
            "present": bool(present),
            "required": bool(in_use),
            "needed": bool(in_use and not present),
            "status": status,
            "enabled": True,
            "version": f"{expected_size / 1048576:.1f} MB",
            "packed": f"{packed_bytes / 1048576:.2f} MB / {len(parts)} 卷" if packed_bytes else "",
            "asset_dir": str(root),
            "variant": variant,
            "in_use": bool(in_use),
            "arch": [int(item) for item in (entry.get("arch") or []) if str(item).isdigit()],
        }
    # 资产包整体一条：本地 `assets\` 有没有展开、要不要去 Release 取或导入本地 zip。
    groups = sorted({group for group, _root, _name, _entry in manifest_entries(config)})
    report["bundle"] = {
        # ⚠️ 名字要写全（用户 2026-10-05：「需要写明是**依赖的随包 zip**」）：
        # 依赖页上必须一眼看出它是"依赖组件"，不是给 Mod 压缩包用的入口。
        "display": "依赖的随包资产包（assets-bundle.zip）· 不是 Mod 包",
        "source": "本地 assets\\；缺失时一键启动会自动拉取，也可导入依赖的随包 zip",
        "install_dir": str(PROJECT_ROOT / "assets"),
        "present": bool(groups),
        "required": True,
        "needed": not groups,
        "status": ("已展开（" + "、".join(groups) + "）") if groups else "缺失",
        "enabled": True,
        "version": "" if not groups else f"{len(groups)} 组",
        "packed": "",
        "asset_dir": str(PROJECT_ROOT / "assets"),
        "variant": "",
        "in_use": True,
        "arch": [],
    }
    return report


def stage_report(config: AppConfig) -> dict[str, Any]:
    """资产整体可用性（供"完整性检查"用）。"""
    present = extracted = 0
    problems: list[str] = []
    for group, root, name, entry in manifest_entries(config):
        target = config.dlss5_path / name
        if target.is_file() and target.stat().st_size == int(entry.get("size") or 0):
            extracted += 1
        else:
            missing = [p for p in (entry.get("parts") or []) if not (root / p).is_file()]
            if missing:
                problems.append(f"{name}: 内置资产缺 {missing}")
        present += 1
    return {"total": present, "extracted": extracted, "problems": problems}
