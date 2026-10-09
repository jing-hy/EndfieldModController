"""把终末地本体恢复成「完全干净」，而且**先备份、随时可还原**。

为什么需要：这套方案会在游戏目录留下第三方加载器的痕迹 —— `d3dcompiler_47.dll` /
`vulkan-1.dll` 这类 proxy（会转发系统导出并把 `plugin/*.dll` 注入游戏进程）、
`plugin/` 里的 payload、插件写的日志与数据目录。只要这些还在，任何"游戏本体是否
正常"的对照测试都不成立（崩溃日志也会被它们污染）。

做法（**只移动，不删除**）：

1. **备份**：把所有要被移走的东西整体搬进 `runtime\\game_backup\\<时间戳>\\`，
   保持相对路径，并写 `manifest.json`（相对路径 / 大小 / sha256 / 分类 / proxy 还原信息）；
2. **净化**：移走 proxy → 用同目录的 `<name>.bak`（没有就从 System32 复制）把**真正的
   系统模块**放回去，这样官方启动器校验能过；再移走 plugin payload、插件日志、
   插件数据目录、ReShade 痕迹、DLSS5 专属运行库；
3. **还原**：`restore()` 按 manifest 原样搬回来，一步回到净化前的状态。

判定依据：**原版会不会有这个文件** —— 原版终末地目录里不会有 `plugin/`、
不会有覆盖系统 dll 的 proxy、不会有 `nvngx_dlssnr.dll`（DLSS5 专属）。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import reshade_integration
from .config import AppConfig

BACKUP_DIR_NAME = "game_backup"
MANIFEST_NAME = "manifest.json"
# 插件在游戏目录里写的东西（原版不可能有）
PLUGIN_DATA_DIRS = ("SecondaryMotion",)
# Endfield Poser 在游戏目录里写的东西（原版同样不可能有）。2026-10-01 补：它的
# `plugin\poser.dll` 会被上面的 plugin_payload 规则移走，但**安装记录、姿态库、
# 表情校准、它自己的备份**都不是 .dll/.txt —— 不补这一段就会留下"记录说装了、
# 文件却不在"的半状态，而且还原时也回不来。
POSER_DATA_PATHS = (
    "plugin/poser-install.json",
    "plugin/poser-backups",
    "plugin/poses",
    "plugin/mmd",
    "plugin/poser_layout.ini",
)
# ReShade 的痕迹（本方案承诺不写游戏目录，出现就是残留）。
# ⚠️ **2026-10-05 补 `dxgi.dll`**（用户批准）：反馈者那台游戏目录里就躺着一份
# `dxgi.dll`(1,294,864 B) + `d3d12.dll`(146,152 B)（同为 9-14 生成），而这份名单里**只有
# `d3d12.dll`** —— 于是 `dxgi.dll` 从来没人管（诊断包里它的归属一直是"未知"）。
# 补进来是安全的：`.dll` 一律走 `_looks_like_reshade_payload()` 的**内容级**判定
# （loader 标记 / OptiScaler 特征 / 与 System32 原版不同 / 正文里有 `ReShade`/`crosire`），
# **同名但是官方原版的模块一个都不会动** —— 这正是"同名的官方文件一律不动"那条承诺。
RESHADE_MARKERS = ("d3d12.dll", "dxgi.dll", "ReShade.ini", "ReShade.log", "ReShadePreset.ini", "reshade-shaders")
# DLSS5 专属运行库：游戏原版**没有**这个文件
DLSS5_ONLY_LIBS = ("nvngx_dlssnr.dll",)
# 方案里的"新版"nvngx（出现即说明游戏原版被替换过）
NEW_NVNGX_SIZES = {"nvngx_dlss.dll": 58977904}

CATEGORY_LABELS = {
    "loader_proxy": "第三方加载器 DLL（proxy，会注入 plugin/*.dll）",
    "injector_data": "第三方注入器的配置/日志（如 OptiScaler）",
    "plugin_payload": "plugin/ 下会被注入的插件 DLL",
    "plugin_log": "插件日志 / 探针输出",
    "plugin_data": "插件在游戏目录写的数据目录",
    "poser_data": "Endfield Poser 的数据（安装记录 / 姿态库 / 表情校准 / 它的备份）",
    "reshade": "ReShade 注入痕迹",
    "dlss5_lib": "DLSS5 专属运行库（游戏原版没有）",
    "nvngx_overridden": "被替换过的 NVIDIA 运行库",
    "injector_backup": "注入器/加载器遗留的备份文件（原版游戏目录不会有）",
}

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        log(message)


def _sha256(path: Path) -> str:
    """失败返回空串（调用方用它判断"读不到"）；实现复用 fsutil，不再维护第三份。"""
    from . import fsutil

    try:
        return fsutil.sha256_file(path)
    except OSError:
        return ""


def _relative_label(game_dir: Path, path: Path) -> str:
    """条目在**备份清单**里的相对路径（相对游戏目录，用 `/` 分隔）。

    ⚠️ 子目录里的条目**必须**带上目录名（`AntiCheatExpert/dxgi.dll`）：它同时是
    `_move_finding()` 写进备份区的落点、也是 `restore()` 放回时的唯一依据 ——
    丢了目录名就会把文件还原到游戏根目录去（净化前它在子目录里）。
    """
    try:
        return path.relative_to(game_dir).as_posix()
    except ValueError:
        return path.name


def _looks_like_reshade_payload(path: Path) -> bool:
    """内容级判定：这个 dll 是否真的是 ReShade / 我们的注入载荷。

    2026-10-01 修（⑤a）：`d3d12.dll` 这类文件**只凭文件名**判定太宽 —— 终末地
    是 DX12 游戏，游戏自带或他方放的正版 d3d12.dll 会被当成"ReShade 痕迹"移走，
    而它不在补回名单里。这里复用 `reshade_integration` 已有的一套判定
    （proxy 名单 + 内容特征），判定不了时保守保持原行为（当作载荷）。
    """
    from . import reshade_integration

    try:
        checker = getattr(reshade_integration, "looks_like_loader_proxy", None)
        if callable(checker) and checker(path):
            return True
        # 2026-10-01：补一条更宽的第三方判定（OptiScaler 特征 / 顶替了系统模块），
        # 否则 OptiScaler 那类注入会被当成游戏自带文件而留下。
        third = getattr(reshade_integration, "is_third_party_proxy", None)
        if callable(third) and third(path):
            return True
        inner = getattr(reshade_integration, "_looks_like_reshade_dll", None)
        if callable(inner):
            return bool(inner(path))
    except (OSError, ValueError):
        # ⚠️ **判不出就返回 False**（2026-10-04 修：原来返回 True）。
        # 这个函数是"要不要把这个文件移走"的判据，返回 True = 判它是 ReShade 载荷
        # ⇒ 会被备份并从游戏目录**移走**。判定本身抛错时保守当作"不是我们的载荷"：
        # 漏移只是体检少报一项（用户毫无感觉），而误移会让**游戏当场起不来**
        #（游戏自带的 d3d12.dll 被搬走，要用户自己点还原才能回来）。
        return False
    return False


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_root(config: AppConfig) -> Path:
    return Path(config.runtime_path) / BACKUP_DIR_NAME


@dataclass
class Finding:
    category: str
    relative: str            # 相对游戏目录
    absolute: str
    is_dir: bool = False
    size: int = 0
    sha256: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": CATEGORY_LABELS.get(self.category, self.category),
            "relative": self.relative,
            "absolute": self.absolute,
            "path": self.absolute,
            "is_dir": self.is_dir,
            "size": self.size,
            "sha256": self.sha256,
            "detail": self.detail,
        }


def audit(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """列出游戏目录里所有**原版不会有**的东西。"""
    # ⚠️ `prefer_actual=True`（2026-10-04）：审计必须针对"**用户实际在玩的那份**"——
    #    反馈者那台 `config.game_exe` 指向 D 盘、XXMI 实际跑 E 盘，于是整份审计结论
    #    （含"游戏目录里没有检测到第三方注入 proxy"）都指向一个他根本不玩的安装。
    game_dir = reshade_integration.detect_game_dir(config, prefer_actual=True)
    if game_dir is None:
        return {"ok": False, "message": "没有找到游戏目录", "game_dir": "", "findings": [], "clean": False}

    findings: list[Finding] = []

    # ① 加载器 proxy（**含可执行文件的子目录也要扫**，2026-10-09 —— 见
    #    `reshade_integration.GAME_INJECTION_SCAN_DIRS` 的注释：反作弊目录之类同样是
    #    有效的劫持位，只扫根目录会整体漏掉"反作弊目录里躺着一整套 ReShade"）。
    for root in reshade_integration.injection_scan_roots(game_dir):
        for name in reshade_integration.LOADER_PROXY_MODULES:
            path = root / name
            if not path.is_file():
                continue
            # 2026-10-01：判据从"内容像 loader proxy（sbm / poser 标记）"放宽为
            # `is_third_party_proxy()` —— 内容标记、**OptiScaler 特征**、或"与 System32
            # 原版不同（被顶替）"三条任一命中即算第三方。用户要求「**一键还原游戏本体要
            # 全部移走**」：原先 OptiScaler 的 `winhttp.dll` 既不在名单、内容也没有我们的
            # 标记 → **整体漏判**，用户以为还原干净了、其实注入链还挂在那儿。
            origin = reshade_integration.is_third_party_proxy(path)
            if not origin:
                continue
            backup = path.with_name(name + ".bak")
            origin_label = {
                "sbm": "乳摇 loader",
                "poser": "Poser loader",
                "optiscaler": "OptiScaler（DLSS-NR 注入器）",
                "third-party": "第三方 proxy（顶替了系统模块）",
            }.get(origin, origin)
            findings.append(Finding(
                "loader_proxy", _relative_label(game_dir, path), str(path),
                size=path.stat().st_size, sha256=_sha256(path),
                detail=f"{origin_label}；系统原版备份{'存在' if backup.is_file() else '不存在'}（{backup.name}）",
            ))

    # ①.5 第三方注入器留下的**配置/日志**（OptiScaler.ini / OptiScaler.log / OptiScaler.dll）：
    #      proxy 都移走了、这些还留着，用户会以为"没还原干净"。用户 2026-10-01 明确要求
    #      「一键还原游戏本体要**全部移走**」，所以一并备份移走（restore 时原样放回）。
    for name in getattr(reshade_integration, "INJECTOR_DATA_NAMES", ()):
        path = game_dir / name
        if path.is_file():
            findings.append(Finding(
                "injector_data", name, str(path), size=path.stat().st_size,
                sha256=_sha256(path),
                detail="第三方注入器（OptiScaler）的配置/日志，原版游戏不会有",
            ))

    # ② plugin/ 里的 payload 与日志（含已被停用但没删掉的副本）
    plugin_dir = game_dir / reshade_integration.PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        for item in sorted(plugin_dir.iterdir()):
            if not item.is_file():
                continue
            name = item.name.lower()
            disabled = (item.name.endswith(reshade_integration.PLUGIN_DISABLED_SUFFIX)
                        or "disabled" in name)
            if name.endswith(".dll") or disabled:
                findings.append(Finding(
                    "plugin_payload", f"{plugin_dir.name}/{item.name}", str(item),
                    size=item.stat().st_size, sha256=_sha256(item),
                    detail=("已被停用的插件副本（残留，同样不是原版）" if disabled
                            else "会被加载器代理注入游戏进程"),
                ))
            elif item.suffix.lower() in {".txt", ".log"}:
                findings.append(Finding(
                    "plugin_log", f"{plugin_dir.name}/{item.name}", str(item),
                    size=item.stat().st_size, detail="插件写的日志/探针输出",
                ))

    # ③ 插件数据目录 / ReShade 痕迹 / DLSS5 专属运行库
    for name in PLUGIN_DATA_DIRS:
        path = game_dir / name
        if path.is_dir():
            total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            findings.append(Finding(
                "plugin_data", name, str(path), is_dir=True, size=total,
                detail="插件在游戏目录写的数据（characters/presets/logs/runtime）",
            ))
    # ③-b Endfield Poser 的数据（安装记录 / 它的备份 / 姿态库 / 表情校准）
    # 只移动不删除；还原时按 manifest 原样搬回（与其它分类同一条路径）。
    for relative in POSER_DATA_PATHS:
        path = game_dir / relative
        if path.is_file():
            findings.append(Finding(
                "poser_data", relative, str(path), size=path.stat().st_size,
                sha256=_sha256(path),
                detail="Endfield Poser 写的文件（净化会先备份，可用「一键还原」搬回）",
            ))
        elif path.is_dir():
            total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            findings.append(Finding(
                "poser_data", relative, str(path), is_dir=True, size=total,
                detail="Endfield Poser 的数据目录（姿态库 / 表情校准 / 安装备份）",
            ))

    # ③ ReShade 痕迹（**含可执行文件的子目录也要扫**，2026-10-09）：真实误装的形态就是
    #    子目录里躺着一整套（`AntiCheatExpert\dxgi.dll` + `ReShade.ini` + `reshade-shaders\`）。
    for root in reshade_integration.injection_scan_roots(game_dir):
        for name in RESHADE_MARKERS:
            path = root / name
            label = _relative_label(game_dir, path)
            # ⚠️ **去重**（2026-10-05）：`d3d12.dll` / `dxgi.dll` 这些名字**同时**出现在
            # ① 段的 `LOADER_PROXY_MODULES` 里 —— 一个文件既被判"第三方 proxy"（① 段）、
            # 内容又像 ReShade 载荷（这一段）时会被报**两次**，净化清单里同一份文件出现两条
            # （备份/还原时两边互相打架）。同相对路径只留先出现的那条。
            if any(item.relative == label for item in findings):
                continue
            if path.is_file():
                # dll 走内容级判定（见 _looks_like_reshade_payload）：只有真的像
                # ReShade 载荷才移走，避免误伤游戏自带/他方的 d3d12.dll。
                if name.lower().endswith(".dll") and not _looks_like_reshade_payload(path):
                    _log(log, f"跳过 {label}：内容不像 ReShade 载荷（可能是游戏自带或他方注入）")
                    continue
                findings.append(Finding(
                    "reshade", label, str(path), size=path.stat().st_size, sha256=_sha256(path),
                    detail="ReShade 痕迹：本方案的承诺是不往游戏目录写这些东西",
                ))
            elif path.is_dir():
                total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                findings.append(Finding(
                    "reshade", label, str(path), is_dir=True, size=total,
                    detail="ReShade shader 目录残留",
                ))
    # ReShade 的**轮转日志**（`ReShade.log1` / `ReShade.log2`…）：`RESHADE_MARKERS` 只能列精确名，
    # 于是"游戏目录里装过 ReShade"的铁证会一直留着（2026-10-05 反馈者的包里就有 `ReShade.log1`，
    # 净化完全不认它）。按 `ReShade.log<数字>` 扫，一并备份移走；`ReShade.log` 本身由上面那段管。
    for extra in sorted(game_dir.glob("ReShade.log[0-9]*")):
        if extra.is_file():
            findings.append(Finding(
                "reshade", extra.name, str(extra), size=extra.stat().st_size, sha256=_sha256(extra),
                detail="ReShade 的轮转日志（说明游戏目录里装过 ReShade）",
            ))
    for name in DLSS5_ONLY_LIBS:
        path = game_dir / name
        if path.is_file():
            findings.append(Finding(
                "dlss5_lib", name, str(path), size=path.stat().st_size, sha256=_sha256(path),
                detail="DLSS5 神经渲染专用运行库，游戏原版没有这个文件",
            ))

    # ①.6 第三方加载器/注入器留下的**非 DLL 痕迹**（2026-10-04 加）。
    #
    # 用户当天原话：「在设置做个开关，一键还原终末地**清除所有第三方注入**，默认开，
    # 开了之后**不管是不是管理器注入的，都要去掉（要备份）**」。
    # 上面 ①/①.5 只覆盖"proxy DLL"与 OptiScaler 的几个文件；3DMigoto / 自造 loader
    # 在游戏目录里还会留下 `d3dx.ini` / `d3dx_user.ini` / `ShaderFixes\` /
    # `loader_debug.log` / `inject_order.txt` / `mc_bootstrap.*` —— 那些同样是
    # "原版不会有"的东西，留着就谈不上"清干净"。只移动不删除，随时可还原。
    for name in getattr(reshade_integration, "GAME_INJECTION_ARTIFACTS", ()):
        path = game_dir / name
        try:
            if path.is_file():
                findings.append(Finding(
                    "injector_data", name, str(path), size=path.stat().st_size,
                    sha256=_sha256(path),
                    detail="第三方加载器/注入器留下的配置或日志（原版游戏不会有）",
                ))
            elif path.is_dir():
                total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                findings.append(Finding(
                    "injector_data", name, str(path), is_dir=True, size=total,
                    detail="第三方加载器的 shader 缓存目录（原版游戏不会有）",
                ))
        except OSError:
            continue

    # ④ 被替换过的 nvngx（原版大小不同即可疑，另看 .game_original 备份）
    for name, new_size in NEW_NVNGX_SIZES.items():
        path = game_dir / name
        if path.is_file() and path.stat().st_size == new_size:
            original = path.with_name(name + ".game_original")
            findings.append(Finding(
                "nvngx_overridden", name, str(path), size=path.stat().st_size, sha256=_sha256(path),
                detail=(f"是方案里的新版（{new_size:,} B）；游戏原版备份"
                        f"{'在 ' + original.name if original.is_file() else '不存在，需重装或校验文件'}"),
            ))

    # ⑤ 游戏目录里遗留的**备份文件**（2026-10-09 用户要求：「在终末地本体清空之后，不要留
    #    备份在终末地的文件夹，全部处理到外面」）。
    #
    # 为什么单列一类：`<game>\d3dcompiler_47.dll.bak` 这类原版备份是**注入过程的副产品**
    # （loader 把原版挪成 `.bak`、再把自己的 proxy 放上去）。净化把 proxy 移走后，这些 `.bak`
    # 就成了没有主人的残留 —— 原版游戏目录里不会有它们，而用户看到的是"我点了还原、目录里
    # 还是一堆备份文件"。所以它们要和 proxy 一样被搬进**外部**备份区（只移动、可还原）。
    #
    # ⚠️ 只认**已知注入相关名字**的备份变体（`<名字>.bak*` / `<名字>.game_original` /
    #    `<名字>.mc.bak*`）：游戏自己带的、用户自己放的 `.bak` 一律不碰。
    # ⚠️⚠️ 顺序上它们必须**最后搬**（见 `backup_and_clean`）：`<name>.bak` 是"把系统原版放回
    #    游戏目录"的来源，先搬走就只能退而从 System32 取，用的就不是游戏原本那份了。
    backup_bases = (
        list(reshade_integration.LOADER_PROXY_MODULES)
        + list(RESHADE_MARKERS)
        + list(DLSS5_ONLY_LIBS)
        + list(NEW_NVNGX_SIZES)
        + list(getattr(reshade_integration, "INJECTOR_DATA_NAMES", ()))
        + list(getattr(reshade_integration, "GAME_INJECTION_ARTIFACTS", ()))
    )
    for base in backup_bases:
        if "/" in base or "\\" in base:
            continue                      # 带路径的条目不是根目录文件名，跳过
        for pattern in (f"{base}.bak*", f"{base}.game_original", f"{base}.mc.bak*"):
            try:
                candidates = sorted(game_dir.glob(pattern))
            except OSError:
                continue
            for item in candidates:
                try:
                    if not item.is_file():
                        continue
                    findings.append(Finding(
                        "injector_backup", item.name, str(item),
                        size=item.stat().st_size, sha256=_sha256(item),
                        detail=("第三方注入器/加载器留下的备份文件；净化会一并搬到外部备份区，"
                                "还原时按清单原样搬回（完全可还原）"),
                    ))
                except OSError:
                    continue

    # 去重（2026-10-04 加）：同一路径可能被两个分类扫到（例如 `ShaderFixes` 既在
    # 加载器痕迹清单里、目录里又可能有 ReShade 痕迹）—— 重复条目会让净化把同一份
    # 东西搬两次，第二次源已不在 ⇒ 报成错误、`ok=False`（"失败保留原状"看起来坏了）。
    # 按绝对路径去重，先出现的分类优先。
    unique: list[Finding] = []
    seen_paths: set[str] = set()
    for finding in findings:
        key = finding.absolute.lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        unique.append(finding)
    findings = unique

    return {
        "ok": not findings,
        "clean": not findings,
        "game_dir": str(game_dir),
        "findings": [f.to_dict() for f in findings],
        "counts": {category: sum(1 for f in findings if f.category == category)
                   for category in CATEGORY_LABELS if any(f.category == category for f in findings)},
    }


def _copy_tree(src: Path, dest: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _move_finding(finding: Finding, files_dir: Path, log: Log,
                  entries: list[dict[str, Any]], moved: list[dict[str, Any]],
                  errors: list[str]) -> bool:
    """把一条 finding **复制进备份区**、再从原位移走（只移动、不删除）。

    ① 和 ② 的顺序不能反：**先确认备份区里已经有完整一份，才允许动原位** —— 反过来
    （先移走再备份）一旦中途失败，那份文件就既不在游戏目录、也不在备份区，**不可还原**。

    备份区在**游戏目录之外**（`runtime\\game_backup\\<时间戳>\\files\\`），清单里的相对路径
    就是还原时唯一的落点依据：`restore()` 按 `files/<相对路径>` 原样搬回游戏目录，
    所以子目录下的条目（如 `AntiCheatExpert/dxgi.dll`）同样完全可还原。
    """
    source = Path(finding.absolute)
    dest = files_dir / finding.relative
    try:
        _copy_tree(source, dest)          # ① 先复制一份到备份区
        if source.is_dir():
            shutil.rmtree(source)          # ② 确认备份成功后才移除原位
        else:
            source.unlink()
    except OSError as exc:
        errors.append(f"{finding.relative}: {exc}")
        _log(log, f"⚠ 处理 {finding.relative} 失败: {exc}")
        return False
    entries.append({**finding.to_dict(), "backup_relative": finding.relative})
    moved.append(finding.to_dict())
    _log(log, f"备份并移走 [{finding.category}] {finding.relative}")
    return True


def _restore_system_module(game_dir: Path, name: str, log: Log) -> dict[str, Any] | None:
    """proxy 移走后，把真正的系统模块放回游戏目录（官方启动器会校验它）。"""
    backup = game_dir / (name + ".bak")
    target = game_dir / name
    if backup.is_file():
        try:
            shutil.copy2(backup, target)
            _log(log, f"已用 {backup.name} 恢复系统模块 {name}（{target.stat().st_size:,} B）")
            return {"name": name, "source": "bak", "sha256": _sha256(target)}
        except OSError as exc:
            _log(log, f"恢复 {name} 失败: {exc}")
            return None
    # 2026-10-01 修（⑤c）：不再硬编码 C:\Windows —— 系统装在 D 盘时这里必然失败，
    # 而失败的后果是"游戏目录缺 d3dcompiler_47/vulkan-1 + 界面仍报成功"。
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    source = Path(system_root) / "System32" / name
    if source.is_file():
        try:
            shutil.copy2(source, target)
            _log(log, f"已从 System32 复制系统模块 {name}（{target.stat().st_size:,} B）")
            return {"name": name, "source": "system32", "sha256": _sha256(target)}
        except OSError as exc:
            _log(log, f"复制 {name} 失败: {exc}")
            return None
    _log(log, f"⚠ 找不到 {name} 的系统原版（既没有 .bak 也不在 System32），游戏目录里暂时没有这个模块")
    return None


def quarantine_injector(
    config: AppConfig,
    *,
    log: Log = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """把「会截获 NGX 的第三方注入器」（目前已知 = OptiScaler）**备份移走**。

    **为什么是自动处理、而不是弹一句提示**：用户 2026-10-01 原话 ——
    「**不是提示的问题，正常用户不会看日志，需要自动检测处理**」。
    背景：装了 OptiScaler 的机器上，它会把进程里**所有** NGX 调用截走（连游戏自带的
    DLSS 一起），于是 ReShade 的 DLSS5 addon hook 不到
    `NVSDK_NGX_D3D12_EvaluateFeature_C`；而 OptiScaler 自己的 `[DlssNr] Enabled` 默认又是
    `false`（只做超分）→ 面板表现为 `成功NR帧 ≈ 0` + `最新NR NGX结果 0xBAD00001`，
    用户看到的就是"DLSS5 没启动、NR 也是 0"，而日志里那几行他根本不会去看。

    语义与「一键还原游戏本体」一致：**先备份 → 再移走 → proxy 补回系统原版**，
    随时能从 `runtime\\game_backup\\ngx-conflict-<时间戳>\\files\\` 放回去。
    只动"确定是注入器"的文件（OptiScaler 的配置/日志，以及被顶替/带 OptiScaler 特征的 proxy），
    **不碰 Mod 库、不碰游戏本体资源、不碰我们自己的注入**。
    """
    from . import reshade_integration

    # ⚠️ `prefer_actual=True`（2026-10-04）：这一步**会真的移走文件**，打在错的那份安装上
    #    既没用、又会在另一个安装上留下"被我们动过"的痕迹。以"用户实际在玩的那份"为准。
    game_dir = reshade_integration.detect_game_dir(config, prefer_actual=True)
    if game_dir is None:
        return {"ok": False, "changed": False, "moved": [], "message": "没有找到游戏目录"}
    try:
        info = reshade_integration.optiscaler_present(game_dir)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "changed": False, "moved": [], "message": f"检测失败：{exc}"}
    if not info.get("present"):
        return {"ok": True, "changed": False, "moved": [],
                "message": "未检测到第三方 NGX 注入器"}

    proxy_names = {name.lower() for name in reshade_integration.LOADER_PROXY_MODULES}
    plan: list[Path] = []
    for relative in info.get("files") or []:
        path = game_dir / str(relative).replace("\\", "/")
        if path.is_file():
            plan.append(path)
    if not plan:
        return {"ok": True, "changed": False, "moved": [],
                "message": "第三方注入器已不在游戏目录"}

    stamp = _stamp()
    # ⚠️ 目录名与清单里的 `stamp` **必须一致**（见下面写清单处），且同秒两次调用不能互相覆盖
    # —— 两条都由 `fsutil.unique_sibling` + `"stamp": root.name` 保证（2026-10-04 修）。
    from . import fsutil

    root = fsutil.unique_sibling(backup_root(config) / f"ngx-conflict-{stamp}")
    files_dir = root / "files"
    moved: list[dict[str, Any]] = []
    restored: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in plan:
        # ⚠️ **用相对游戏目录的路径**（2026-10-04 修）：原来只取 `path.name`，而
        # `optiscaler_present()` 报的文件可能是 `plugin\xxx.dll` ⇒ 还原时会被放回
        # **游戏目录根**而不是原位置（位置错 = 第三方注入器回不去、或顶掉别的文件）。
        try:
            relative = path.relative_to(game_dir).as_posix()
        except ValueError:
            relative = path.name
        try:
            size = path.stat().st_size
            digest = _sha256(path)
        except OSError as exc:
            errors.append(f"{relative}: {exc}")
            continue
        if not dry_run:
            try:
                _copy_tree(path, files_dir / relative)   # ① 先备份
                path.unlink()                            # ② 确认备份后才移走
            except OSError as exc:
                errors.append(f"{relative}: {exc}")
                _log(log, f"⚠ 移走 {relative} 失败: {exc}")
                continue
        moved.append({"relative": relative, "size": size, "sha256": digest})
        _log(log, f"已备份并移走第三方 NGX 注入器文件: {relative}（{size:,} B）")
        # proxy 被移走后要把系统原版补回，否则游戏可能找不到这个模块
        if path.name.lower() in proxy_names and not dry_run:
            module = _restore_system_module(game_dir, path.name, log)
            if module:
                restored.append(module)

    if not dry_run and moved:
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / MANIFEST_NAME).write_text(json.dumps({
                # ⚠️ 用**目录名**（不是 `_stamp()` 的结果）：`fsutil.unique_sibling` 可能给它
                # 加上 `-1` 后缀，清单里必须跟着变，否则"按 stamp 还原"取错份。
                "stamp": root.name,
                "kind": "ngx_conflict",
                "created_at": int(time.time()),
                "reason": "OptiScaler 截获 NGX 调用，导致 DLSS5 的神经渲染无法生效（成功NR帧 0 / 0xBAD00001）",
                "game_dir": str(game_dir),
                "entries": moved,
                "restored_modules": restored,
                "errors": errors,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        except OSError as exc:
            errors.append(f"写清单失败: {exc}")

    names = "、".join(item["relative"] for item in moved)
    return {
        "ok": not errors,
        "changed": bool(moved),
        "moved": moved,
        "restored": restored,
        "errors": errors,
        "backup_dir": str(root) if moved and not dry_run else "",
        "message": (f"已把第三方 NGX 注入器（OptiScaler）备份并移走：{names} → {root}"
                    if moved else "没有需要处理的文件"),
    }


def backup_and_clean(
    config: AppConfig,
    *,
    log: Log = None,
    dry_run: bool = False,
    include_plugin_data: bool = True,
) -> dict[str, Any]:
    """先整体备份，再把游戏目录净化成原版状态（只移动，不删除）。"""
    report = audit(config, log=log)
    if not report.get("game_dir"):
        return {"ok": False, "message": report.get("message", "没有找到游戏目录"), "moved": [], "backup_dir": ""}
    game_dir = Path(report["game_dir"])
    findings = [Finding(**{k: v for k, v in item.items() if k in Finding.__dataclass_fields__})
                for item in report["findings"]]
    if not include_plugin_data:
        findings = [f for f in findings if f.category != "plugin_data"]
    if not findings:
        return {"ok": True, "message": "游戏目录已经是干净的（没有发现非原版文件）",
                "moved": [], "backup_dir": "", "game_dir": str(game_dir)}

    stamp = _stamp()
    # ⚠️ 同一秒内连做两次备份不能互相覆盖（第一次的"净化前"状态才是有价值的那份）。
    # 判据收敛到 `fsutil.unique_sibling`（2026-10-04）：项目里"取一个不覆盖的名字"
    # 曾有 4 份各写各的，这里是其中一份。
    from . import fsutil

    root = fsutil.unique_sibling(backup_root(config) / stamp)
    stamp = root.name
    files_dir = root / "files"
    if dry_run:
        return {
            "ok": True, "dry_run": True, "game_dir": str(game_dir), "backup_dir": str(root),
            "moved": [f.to_dict() for f in findings],
            "message": f"预演：将备份并移走 {len(findings)} 项",
        }

    entries: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    restored_modules: list[dict[str, Any]] = []
    errors: list[str] = []

    # ⚠️⚠️ **先落一份"计划清单"，再动第一个文件**（2026-10-04 修，备份语义）。
    #
    # 原顺序是"逐个搬完 → 最后才写清单"，而 `list_backups()` 只认**带清单**的目录
    # ⇒ 中途断电/进程被杀/写清单失败时，真实的备份就躺在 `files\` 里**却没人看得见**：
    # `restore()` 会说"没有找到任何游戏目录备份"，而游戏目录已经被切掉一半。
    # 现在：动第一份之前先写 `status="in_progress"` 的清单（哪怕 entries 还是空的），
    # 全部搬完再原子地改成 `status="complete"` —— 任何时刻都能被 `list_backups` 看见。
    manifest_path = root / MANIFEST_NAME
    try:
        root.mkdir(parents=True, exist_ok=True)
        from . import fsutil

        fsutil.write_json(manifest_path, {
            "stamp": stamp,
            "kind": "clean",
            "status": "in_progress",
            "created_at": int(time.time()),
            "game_dir": str(game_dir),
            "entries": [],
            "restored_modules": [],
            "errors": [],
        })
    except OSError as exc:
        errors.append(f"写清单失败: {exc}")

    # ⚠️ **备份文件（`injector_backup`）要最后搬**（2026-10-09）：它们是"把系统原版放回
    #    游戏目录"的来源（`<name>.bak`）。先搬走它们，`_restore_system_module` 就只能退而
    #    从 System32 取 —— 能跑，但用的不是**游戏原本那份**。所以顺序是：
    #    ① 搬走注入物 → ② 用 .bak 把系统原版放回 → ③ 再把 .bak 搬进外部备份区。
    backup_findings = [f for f in findings if f.category == "injector_backup"]
    main_findings = [f for f in findings if f.category != "injector_backup"]

    for finding in main_findings:
        _move_finding(finding, files_dir, log, entries, moved, errors)

    # proxy 移走后必须把系统模块补回去，否则游戏会缺 d3dcompiler_47/vulkan-1
    for finding in main_findings:
        if finding.category != "loader_proxy":
            continue
        name = Path(finding.relative).name
        module = _restore_system_module(game_dir, name, log)
        if module:
            restored_modules.append(module)
        elif not dry_run:
            # 2026-10-01 修（⑤c）：proxy 已移走却补不回系统模块 → 游戏目录会缺
            # d3dcompiler_47/vulkan-1（游戏可能起不来），不能只写一行日志还报 ok=True。
            errors.append(f"{name}: 已移走但无法补回系统原版，游戏可能启动失败（请用「还原」）")

    # ③ **最后**把游戏目录里遗留的备份文件也搬进外部备份区（用户 2026-10-09：
    #    「在终末地本体清空之后，不要留备份在终末地的文件夹，全部处理到外面」）。
    #    只移动、不删除，照样写进同一份清单 ⇒ `restore()` 会把它们原样搬回，**完全可还原**。
    #    这一步也让"以前用过还原、备份文件留在游戏目录"的老用户，在下次净化时自动被搬到外部。
    for finding in backup_findings:
        _move_finding(finding, files_dir, log, entries, moved, errors)

    manifest = {
        "stamp": stamp,
        # ⚠️ `kind` 是**区分备份用途**的唯一判据（2026-10-04 加）：`restore()` 默认要挑
        # "净化备份（clean）"，不能挑到 `quarantine_injector` 留下的 `ngx-conflict-*`
        # —— 那份里是 OptiScaler 的文件，把它"还原"回游戏目录正是我们要避免的事。
        # 旧备份没有这个字段，`list_backups` 会按目录名/清单内容推断（见那边）。
        "kind": "clean",
        # `complete` = 所有项都已搬完（`restore()` 对 `in_progress` 的清单也照样能用，
        # 它只用 `entries`；这个字段是给 `list_backups` 标"这份可能不完整"用的）。
        "status": "complete",
        "created_at": int(time.time()),
        "game_dir": str(game_dir),
        "entries": entries,
        "restored_modules": restored_modules,
        "errors": errors,
    }
    try:
        # 原子写（2026-10-04）：清单是还原的唯一索引，半截 JSON 等于没有索引。
        from . import fsutil

        fsutil.write_json(root / MANIFEST_NAME, manifest)
    except OSError as exc:
        errors.append(f"写清单失败: {exc}")

    return {
        "ok": not errors,
        "game_dir": str(game_dir),
        "backup_dir": str(root),
        "moved": moved,
        "restored_modules": restored_modules,
        "errors": errors,
        "message": f"已备份并移走 {len(moved)} 项；备份在 {root}",
    }


def injection_snapshot(config: AppConfig) -> set[str]:
    """游戏目录里**此刻**有哪些"原版不会有"的注入物 → 相对路径集合。

    只回答"在不在"、**不算 sha256**：它给"**净化后按开关铺回了哪些**"做前后差集用
    （用户 2026-10-05 要求：「净化后没有'按开关铺回了哪些'的显式说明也做一下」）。
    每次一键启动要跑两遍，不该为它哈希几十 MB。

    与 `audit()` 同一套判据（同一批常量与 `is_third_party_proxy`），只是省掉哈希与详情。
    """
    game_dir = reshade_integration.detect_game_dir(config, prefer_actual=True)
    if game_dir is None:
        return set()
    found: set[str] = set()
    for name in reshade_integration.LOADER_PROXY_MODULES:
        path = game_dir / name
        try:
            if path.is_file() and reshade_integration.is_third_party_proxy(path):
                found.add(name)
        except OSError:
            continue
    for name in getattr(reshade_integration, "INJECTOR_DATA_NAMES", ()):
        try:
            if (game_dir / name).is_file():
                found.add(name)
        except OSError:
            continue
    plugin_dir = game_dir / reshade_integration.PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        try:
            for item in plugin_dir.iterdir():
                if item.is_file():
                    found.add(f"{plugin_dir.name}/{item.name}")
        except OSError:
            pass
    return found


def _game_running(image: str = "Endfield.exe") -> bool:
    """游戏（或它的启动器进程）是不是正在跑 —— 冲突时才跳过清理，不抛异常。"""
    from . import diagnostics

    try:
        return bool(diagnostics._find_process_ids(image))
    except Exception:  # noqa: BLE001
        return False


def auto_clean_before_launch(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """一键启动前的自动净化（设置页开关 `clear_game_injections_on_launch`，**默认开**）。

    用户 2026-10-04 原话：「在设置做个开关，一键还原终末地清除所有第三方注入，
    **默认开**，开了之后**不管是不是管理器注入的，都要去掉（要备份）**」。

    为什么"清干净"与"功能还在"可以同时成立：清理**只搬走**并写一份可还原的备份
    （`backup_and_clean` 的既有语义），随后启动流程里的 `ensure_injections()`
    会按**当前开关**把我们自己要用的注入重新铺好。因此顺序必须是
    **先净化 → 后补齐**（反了会把刚铺好的当成残留清掉）。

    游戏正在跑时**跳过**：proxy 被游戏进程占用，动它既可能失败，也会毁掉用户
    正在用的那次会话。
    """
    if not getattr(config, "clear_game_injections_on_launch", True):
        return {"ok": True, "skipped": "switch_off", "moved": [], "backup_dir": "",
                "message": "设置里关掉了「启动前清除第三方注入」"}
    if _game_running():
        _log(log, "游戏正在运行 —— 跳过启动前净化（文件被占用，也不该动你正在用的游戏）")
        return {"ok": True, "skipped": "game_running", "moved": [], "backup_dir": "",
                "message": "游戏正在运行，跳过启动前净化"}
    report = backup_and_clean(config, log=log)
    moved = report.get("moved") or []
    if moved:
        _log(log, f"启动前净化：已备份并移走 {len(moved)} 项第三方注入 → {report.get('backup_dir')}")
    elif report.get("ok"):
        _log(log, "启动前净化：游戏目录本来就是干净的（没有第三方注入）")
    return report


def list_backups(config: AppConfig) -> list[dict[str, Any]]:
    """列出游戏目录备份（**最近的在最前**），并标出它是哪一类备份。

    ⚠️⚠️ **两类备份不能混着当"净化备份"用**（2026-10-04 审计发现的 P1）：
      * `clean`（`backup_and_clean` 的产物）= 游戏目录被净化前的文件，**还原用它**；
      * `ngx_conflict`（`quarantine_injector` 的产物，目录名 `ngx-conflict-*`）= 被移走的
        OptiScaler 文件，**它是"要移走的东西"**。
    原来两者都被当成净化备份，而排序是字符串降序（`'n' > '2'`）⇒ `backups[0]`
    **永远是 ngx-conflict 那份** ⇒ 点「从备份还原游戏目录」/「依赖清空」会把刚移走的
    OptiScaler 原样搬回游戏目录、并删掉补回的系统模块，DLSS5 立刻又失效，界面上毫无提示。
    现在返回 `kind`，并由 `restore()` 只认 `clean`（旧备份按目录名/清单内容推断）。
    """
    root = backup_root(config)
    if not root.is_dir():
        return []
    from . import fsutil

    rows: list[dict[str, Any]] = []
    for item in sorted(root.iterdir(), reverse=True):
        if not item.is_dir():
            continue
        manifest = item / MANIFEST_NAME
        if not manifest.is_file():
            # ⚠️⚠️ **没有清单但确实存了文件的目录也要列出来**（2026-10-04 修，备份语义）。
            # 旧版这里 `continue` 直接跳过 ⇒ 一次"搬到一半就断电/被杀"的过程会留下
            # `files\` 里真实的备份，而用户看到的是"没有找到任何游戏目录备份"、
            # 游戏目录却已经被移走了一半 —— 那是最容易让人彻底失去数据的组合。
            # 现在：只要 `files\` 非空就当作"一份可能不完整的净化备份"报出来。
            files_dir = item / "files"
            try:
                has_payload = files_dir.is_dir() and any(files_dir.rglob("*"))
            except OSError:
                has_payload = False
            if not has_payload:
                continue
            rows.append({
                "stamp": item.name,
                "kind": "ngx_conflict" if item.name.startswith("ngx-conflict-") else "clean",
                "status": "unknown",
                "incomplete": True,
                "created_at": 0,
                "entries": 0,
                "game_dir": "",
                "path": str(item),
                "note": "这份备份没有清单（多半是备份过程被打断），内容在 files\\ 下，可手动取回",
            })
            continue
        data = fsutil.read_json(manifest)
        if not data:
            # ⚠️⚠️ **清单在、但读不出来（JSON 写坏 / 只写了一半）也要列出来**（2026-10-05 补）。
            #    上面那段处理的是"**没有**清单"，这里处理的是"**有**清单但解析失败"——
            #    两者都可能是"备份搬到一半被打断"。而备份语义第一条就是「**备份必须能被找到**」：
            #    漏掉这一类的后果非常具体 —— `restore()` 会说"没有找到任何游戏目录备份"，
            #    于是「依赖清空重新下载」把 `runtime\` 连同这份**唯一的备份**一起删掉
            #    （2026-10-04 那条 P0 保护的判据正好因此失效）。
            #    判据与上面保持同一口径：**`files\` 里真的有东西才列**（空壳删了没损失，
            #    列出来反而会让"清空"永远被拦下）。
            files_dir = item / "files"
            try:
                has_payload = files_dir.is_dir() and any(files_dir.rglob("*"))
            except OSError:
                has_payload = False
            if not has_payload:
                continue
            rows.append({
                "stamp": item.name,
                "kind": "ngx_conflict" if item.name.startswith("ngx-conflict-") else "clean",
                "status": "unknown",
                "incomplete": True,
                "created_at": 0,
                "entries": 0,
                "game_dir": "",
                "path": str(item),
                "note": "这份备份的清单读不出来（写坏或写了一半），内容在 files\\ 下，可手动取回",
            })
            continue
        kind = str(data.get("kind") or "")
        if not kind:
            # 兼容旧备份：目录名带 `ngx-conflict-` 前缀的就是第三方注入器备份
            kind = "ngx_conflict" if item.name.startswith("ngx-conflict-") else "clean"
        rows.append({
            "stamp": data.get("stamp") or item.name,
            "kind": kind,
            "status": str(data.get("status") or "complete"),
            "incomplete": str(data.get("status") or "complete") != "complete",
            "created_at": data.get("created_at", 0),
            "entries": len(data.get("entries") or []),
            "game_dir": data.get("game_dir", ""),
            "path": str(item),
        })
    # **净化备份 / 运行库备份排前面**（同 kind 内保持上面的"名字降序 = 时间新在前"）——
    # Python 的 sort 是稳定的，所以这一句就够了，`restore()` 的"取第一个"永远取到该取的那份。
    # ★ 2026-10-06：`libs`（Streamline 运行库替换前的原版）**也是"能一键还原"的备份**，
    #   与 `clean` 同权；只有 `ngx_conflict`（装的是"要移走的东西"）才不许被当成还原源。
    rows.sort(key=lambda row: row["kind"] not in ("clean", "libs"))
    return rows


def backup_files(
    config: AppConfig,
    game_dir: Path,
    relatives: list[str],
    *,
    kind: str = "libs",
    note: str = "",
    log: Log = None,
) -> dict[str, Any]:
    """把游戏目录里指定的若干文件**备份进 `runtime\\game_backup\\<时间戳>\\`**（通用入口）。

    为什么要它（2026-10-06 用户要求：「**备份要接进 mod 管理器，一键还原能直接还原**」）：
    原先"往游戏目录替换新版运行库"（`initialize` 的 `deploy_new_nvngx`）只在旁边存一份
    `<名字>.game_original` —— 那对用户**不可见、也不在还原链路上**：管理器里点「还原」
    不会碰它，用户根本不知道有这份东西。而 Streamline 替换**必须**可还原（上游明确警告
    版本不匹配会让帧生成起不来），所以备份要走**与净化同一套清单机制** ⇒ `list_backups`
    能列出、`restore()` 能一步还原。

    ⚠️ 三条备份语义（项目红线，照 `backup_and_clean` 同款）：
      ① **先写 `status=in_progress` 的清单再搬文件**，搬完改 `complete` —— 任何时刻都能被列出；
      ② **复制成功后才覆盖原位置**（调用方负责），这里只保证"备份真的落盘了"；
      ③ 文件不存在就跳过（不报错）—— 它本来就不在游戏目录里，没什么可备份的。
    """
    from . import fsutil

    stamp = _stamp()
    root = backup_root(config) / stamp
    files_dir = root / "files"
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        files_dir.mkdir(parents=True, exist_ok=True)
        fsutil.write_json(root / MANIFEST_NAME, {
            "stamp": stamp,
            "kind": kind,
            "status": "in_progress",
            "created_at": int(time.time()),
            "game_dir": str(game_dir),
            "entries": [],
            "restored_modules": [],
            "errors": [],
            "note": note,
        })
    except OSError as exc:
        return {"ok": False, "stamp": "", "backup_dir": "", "entries": [],
                "message": f"创建备份目录失败: {exc}"}

    for relative in relatives:
        source = game_dir / relative
        if not source.is_file():
            continue
        try:
            dest = files_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            entries.append({
                "relative": relative,
                "category": "game_lib",
                "size": source.stat().st_size,
                "sha256": _sha256(source),
                "backup_relative": relative,
            })
            _log(log, f"备份 [{kind}] {relative}（{source.stat().st_size:,} B）")
        except OSError as exc:
            errors.append(f"{relative}: {exc}")
            _log(log, f"⚠ 备份 {relative} 失败: {exc}")

    try:
        fsutil.write_json(root / MANIFEST_NAME, {
            "stamp": stamp,
            "kind": kind,
            "status": "complete",
            "created_at": int(time.time()),
            "game_dir": str(game_dir),
            "entries": entries,
            "restored_modules": [],
            "errors": errors,
            "note": note,
        })
    except OSError as exc:
        errors.append(f"写清单失败: {exc}")

    return {
        "ok": bool(entries) and not errors,
        "stamp": stamp,
        "backup_dir": str(root),
        "entries": entries,
        "errors": errors,
        "message": (f"已备份 {len(entries)} 个文件到 {stamp}" if entries
                    else "游戏目录里没有需要备份的文件"),
    }


def restore(config: AppConfig, *, stamp: str = "", log: Log = None) -> dict[str, Any]:
    """按备份清单把游戏目录还原回去（**净化备份 或 运行库备份**）。"""
    backups = list_backups(config)
    if not backups:
        return {"ok": False, "message": "没有找到任何游戏目录备份", "restored": []}
    # ⚠️ 只从 `clean` / `libs` 里挑（见 list_backups 的说明）：ngx-conflict 那份装的是**被移走的**
    #    第三方注入器文件，把它"还原"回游戏目录等于把问题装回去。
    #    ★ 2026-10-06：`libs`（Streamline 运行库替换前的原版）**必须能还原** ——
    #      用户要求「备份要接进 mod 管理器，一键还原能直接还原」。
    usable = [b for b in backups if b.get("kind") in ("clean", "libs")] or backups
    if stamp:
        target = next((b for b in usable if b["stamp"] == stamp), None)
        if target is None:
            # ⚠️ **不许静默回落到最新那份**（原来 `next(..., backups[0])`）：
            # 用户以为还原的是 A，实际还原的是 B —— 而"还原错备份"在游戏目录上是破坏性的。
            stamps = "、".join(str(b["stamp"]) for b in usable[:8])
            return {"ok": False, "restored": [],
                    "message": f"找不到 stamp 为 {stamp} 的备份。可用的是：{stamps}"}
    else:
        target = usable[0]
    root = Path(target["path"])
    try:
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"备份清单损坏: {exc}", "restored": []}

    game_dir = Path(manifest.get("game_dir") or "")
    if not game_dir.is_dir():
        return {"ok": False, "message": f"原游戏目录不存在: {game_dir}", "restored": []}

    restored: list[str] = []
    errors: list[str] = []
    # ⚠️⚠️ **系统模块要"确认能还原 proxy 了再删"**（2026-10-04 修）。
    #
    # 净化时我们把 proxy（`d3dcompiler_47.dll` / `vulkan-1.dll`）搬走、并从 System32
    # **补回一份系统原版**（否则游戏当场起不来）。还原时必须反过来：先删补回的那份、
    # 再放回我们搬走的 proxy —— 顺序反了会被覆盖。
    # 但原实现是**无条件先全删**，然后才逐个尝试还原：只要某个 proxy 的备份源缺失
    #（清单损坏 / 备份被清理 / 复制失败），游戏目录就**永远缺这个模块**
    #（官方启动器校验失败、游戏起不来），而函数只返回一个 errors 数组。
    #
    # 现在逐个判：**只有该名字对应的 proxy 条目确实能从备份还原时，才删系统模块**。
    proxy_entries: list[dict[str, Any]] = [e for e in (manifest.get("entries") or [])
                                           if isinstance(e, dict)]
    for module in manifest.get("restored_modules") or []:
        name = str(module.get("name") or "")
        if not name:
            continue
        path = game_dir / name
        if not path.is_file():
            continue
        restorable = any(
            Path(str(entry.get("relative") or "")).name.lower() == name.lower()
            and (root / "files" / str(entry.get("relative") or "")).exists()
            for entry in proxy_entries
        )
        if not restorable:
            # 还原不回来 ⇒ **留着系统原版**（游戏至少能起），并如实说清
            errors.append(
                f"{name}: 备份里没有可还原的 proxy，已保留系统原版（游戏仍可启动）")
            continue
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"清理 {path.name}: {exc}")

    for entry in manifest.get("entries") or []:
        relative = str(entry.get("relative") or "")
        if not relative:
            continue
        source = root / "files" / relative
        dest = game_dir / relative
        # 2026-10-01 修（⑤b）：`relative` 来自 manifest（外部可改的数据），拼出来的
        # 目标必须落在游戏目录之内 —— 否则清单被改坏/从别处拷来时，这里会
        # "先 rmtree 现位置、再复制"，把游戏目录之外的目录删掉且不可逆。
        try:
            resolved = dest.resolve()
        except OSError:
            errors.append(f"{relative}: 路径无法解析，已跳过")
            continue
        if not resolved.is_relative_to(game_dir.resolve()):
            errors.append(f"{relative}: 目标不在游戏目录内，已跳过（{resolved}）")
            continue
        dest = resolved
        if not source.exists():
            errors.append(f"备份里缺少 {relative}")
            continue
        try:
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            _copy_tree(source, dest)
            restored.append(relative)
            _log(log, f"还原 {relative}")
        except OSError as exc:
            errors.append(f"{relative}: {exc}")

    return {
        "ok": not errors,
        "stamp": target["stamp"],
        "game_dir": str(game_dir),
        "restored": restored,
        "errors": errors,
        "message": f"已从 {target['stamp']} 的备份还原 {len(restored)} 项",
    }
