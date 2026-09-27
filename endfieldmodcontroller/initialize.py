"""启动前初始化自检：把所有**非 XXMI 负责**的准备工作逐项校验并补齐。

XXMI 负责的部分（进程启动时把 d3d12.dll / d3d11.dll 注入进去、EFMI 加载 Mods）不在
这里检查——那由 XXMI 的注入库配置决定，本模块只保证「配置文件写对了」。

这里检查的是文件层面的初始化，缺什么补什么，来源优先级：

    1. config.dlss5_source_dir（显式配置的素材目录）
    2. 自动探测的素材目录（D:\\zmdmod\\DLSS5、D:\\zmdmod\\终末地 下的 dlss5 素材）
    3. runtime\\backups 下的历史备份
    4. 内置 runtime\\dlss5 里的同类文件

任何一项补不了都会在报告里标成 manual，提示人工处理，而不会让启动静默失败。
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import runtime_assets
from .config import AppConfig

# DLSS5 目录里必须具备的最小文件集（缺一不可，否则三件套跑不起来）
DLSS5_REQUIRED_FILES = (
    "d3d12.dll",
    "dlss5-feed.addon64",
    "renodx-endfield-enhancer.addon64",
    "trans-zh.addon64",
)
DLSS5_PLUGIN_GLOBS = ("renodx-dlss5*.addon64",)
# 游戏目录里必须有的 DLSS 运行库（从内置副本补齐）
GAME_LIBS = ("nvngx_dlss.dll", "nvngx_dlssnr.dll")
# 其中游戏原版**并不存在**、属于 DLSS5 专属的文件：只在 deploy_new_nvngx=True 时部署
GAME_LIBS_OPTIONAL = ("nvngx_dlssnr.dll",)
ENHANCER_SECTION = "[endfield-enhancer]"
# DLSS5 的 ReShade preset 必须启用的 technique。
# **顺序有意义** —— DLSS5_Feed.fx 明确要求 MartysMods_Launchpad 启用且排在它上面。
DLSS5_PRESET_TECHNIQUES = (
    "MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx",
    "DLSS5_Feed@DLSS5_Feed.fx",
)


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def source_dirs(config: AppConfig) -> list[Path]:
    """可用的素材来源目录（按优先级）。"""
    candidates: list[Path] = []
    if config.dlss5_source_dir:
        candidates.append(config.resolve_path(config.dlss5_source_dir))
    # 兜底来源一律在工作区内（不再硬编码外部素材路径）：
    # ① config.dlss5_source_dir（用户显式指定）② runtime\dlss5_backup（手动放的素材备份）
    # ③ runtime\backups\*（历史备份）
    candidates.append(config.runtime_path / "dlss5_backup")
    backups = config.runtime_path / "backups"
    if backups.is_dir():
        try:
            candidates.extend([d for d in backups.iterdir() if d.is_dir()])
        except OSError:
            pass
    result: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.is_dir() and candidate not in result:
                result.append(candidate)
        except OSError:
            continue
    return result


def _find_file(config: AppConfig, name: str) -> Path | None:
    """在素材来源里找一个文件。"""
    target = config.dlss5_path / name
    for directory in source_dirs(config):
        candidate = directory / name
        if candidate.is_file() and candidate != target:
            return candidate
    return None


def _find_plugin(config: AppConfig) -> Path | None:
    for pattern in DLSS5_PLUGIN_GLOBS:
        found = list(config.dlss5_path.glob(pattern))
        if found:
            return found[0]
    for directory in source_dirs(config):
        for pattern in DLSS5_PLUGIN_GLOBS:
            found = list(directory.glob(pattern))
            if found:
                return found[0]
    return None


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.actions: list[str] = []
        self.warnings: list[str] = []

    def add(self, key: str, ok: bool, message: str, *, fixed: bool = False, manual: bool = False) -> None:
        self.checks.append({"key": key, "ok": ok, "fixed": fixed, "manual": manual, "message": message})
        if not ok and manual:
            self.warnings.append(f"{key}: {message}")

    def action(self, text: str) -> None:
        self.actions.append(text)

    def to_dict(self) -> dict[str, Any]:
        pending = [c for c in self.checks if not c["ok"] and not c["fixed"]]
        return {
            "ok": not pending,
            "checks": self.checks,
            "actions": self.actions,
            "warnings": self.warnings,
            "pending": pending,
        }


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------
def _check_bundled_assets(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """随包分发的二进制资产：缺失时从 `assets\\` 下的压缩分卷展开。

    两组：

    * `assets\\nvngx\\` —— DLSS 运行库（`nvngx_dlss.dll` / `nvngx_dlssnr.dll`）。
      NVIDIA 官方 SDK 只给 `nvngx_dlss.dll`，`nvngx_dlssnr.dll` 没有官方直链；
      压缩后 103 MB 又超过 GitHub 单文件 100 MiB 上限，所以只能压缩 + 分卷随包。
    * `assets\\dlss5\\` —— DLSS5 底座里**没有公开上游**的三个 addon
      （第一人称 Enhancer、ReShade 面板汉化、RenoDX-DLSS5 汉化版）。

    展开是一次性慢操作（合计约 6 秒），所以只补缺失的，并且必须给进度。
    """
    found = runtime_assets.manifest_entries(config)
    if not found:
        report.add(
            "bundled_assets", False,
            "找不到随包资产（assets\\nvngx\\manifest.json / assets\\dlss5\\manifest.json）"
            "—— 请确认源码/便携包完整",
            manual=True,
        )
        return

    state: dict[str, int] = {}

    def on_progress(name: str, done: int, total: int) -> None:
        if not total:
            return
        step = done * 4 // total
        if state.get(name) != step:
            state[name] = step
            _log(log, f"  展开 {name}: {step * 25}% ({done // 1048576}/{total // 1048576} MB)")

    results = runtime_assets.ensure_all(config, progress=on_progress, log=log)
    for result in results:
        key = f"{result.group}:{result.name}" if result.group and result.name != "*" else "bundled_assets"
        if result.status == "present":
            report.add(key, True, result.message)
        elif result.status == "extracted":
            report.add(key, True, result.message, fixed=True)
            report.action(f"展开内置资产 {result.name}")
        else:
            report.add(key, False, result.message, manual=True)


def _check_dlss5_dir(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    dlss5 = config.dlss5_path
    if not dlss5.is_dir():
        report.add("dlss5_dir", False, f"DLSS5 目录不存在: {dlss5}", manual=True)
        return

    for name in DLSS5_REQUIRED_FILES:
        target = dlss5 / name
        if target.is_file():
            report.add(f"dlss5:{name}", True, "已就位")
            continue
        # 被单独停用（挪到 _disabled）的插件不算缺失
        if (dlss5 / "_disabled" / name).is_file():
            report.add(f"dlss5:{name}", True, "已按开关停用（在 _disabled 目录）")
            continue
        source = _find_file(config, name)
        if source is None:
            report.add(f"dlss5:{name}", False, f"缺失且找不到素材来源: {name}", manual=True)
            continue
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            report.add(f"dlss5:{name}", False, f"复制失败: {exc}", manual=True)
            continue
        report.add(f"dlss5:{name}", True, f"已从 {source.parent} 补齐", fixed=True)
        report.action(f"补齐 {name}")

    plugin = _find_plugin(config)
    if plugin is None:
        report.add("dlss5:plugin", False, "找不到 RenoDX-DLSS5 插件(renodx-dlss5*.addon64)", manual=True)
    else:
        report.add("dlss5:plugin", True, plugin.name)

    # shader 包：只看关键 shader 是否在
    feed_fx = dlss5 / "reshade-shaders" / "Shaders" / "DLSS5_Feed.fx"
    if feed_fx.is_file():
        report.add("dlss5:shaders", True, "reshade-shaders 已就位")
    else:
        source_zip = None
        for directory in source_dirs(config):
            candidate = directory / "reshade-shaders.zip"
            if candidate.is_file():
                source_zip = candidate
                break
            parent_zip = directory.parent / "reshade-shaders.zip"
            if parent_zip.is_file():
                source_zip = parent_zip
                break
        if source_zip is None:
            report.add("dlss5:shaders", False, "reshade-shaders 缺失且找不到 reshade-shaders.zip", manual=True)
        else:
            try:
                with zipfile.ZipFile(source_zip) as archive:
                    archive.extractall(dlss5)
                report.add("dlss5:shaders", True, f"已从 {source_zip.name} 解压恢复", fixed=True)
                report.action("解压恢复 reshade-shaders")
            except (OSError, zipfile.BadZipFile) as exc:
                report.add("dlss5:shaders", False, f"解压失败: {exc}", manual=True)


def _check_dlss5_preset(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """DLSS5 的 ReShade preset 必须存在、且启用 `DLSS5_Feed`。

    2026-09-27 查到的一个「静默失效」：`ReShade.ini` 里 `PresetPath` 指向的
    `ReShadePreset.ini` **缺失**时，ReShade 不会启用任何 technique —— 而 DLSS5 addon
    **只在 `DLSS5_Feed` technique 执行之后**才会去调 DLSS / NGX。于是面板上表现为
    「NGX Hook: 创建0 / 成功NR帧: 0 / 0xBAD00007」，看起来像插件坏了、D3D11 挡路或
    显卡不支持，实际只是没人把 technique 打开。

    `DLSS5_Feed.fx` 自身写明还要求 `MartysMods_Launchpad` 启用**且排在上面**，
    所以两条一起写、按此顺序。
    """
    if not getattr(config, "dlss5_addon_enabled", True):
        report.add("dlss5:preset", True, "DLSS5 已在启动页关闭（跳过 preset 检查）")
        return

    dlss5 = config.dlss5_path
    ini = config.dlss5_ini_path
    if not ini.is_file():
        report.add("dlss5:preset", False, "ReShade.ini 不存在，无法确定 preset 路径", manual=True)
        return

    preset_path: Path | None = None
    try:
        for line in ini.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("PresetPath="):
                raw = stripped.split("=", 1)[1].strip()
                if raw:
                    candidate = Path(raw)
                    preset_path = (candidate if candidate.is_absolute()
                                   else dlss5 / raw.lstrip(".\\/"))
                break
    except OSError as exc:
        report.add("dlss5:preset", False, f"读取 ReShade.ini 失败: {exc}", manual=True)
        return

    if preset_path is None:
        report.add("dlss5:preset", False, "ReShade.ini 里没有 PresetPath", manual=True)
        return

    body = ""
    if preset_path.is_file():
        try:
            body = preset_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            body = ""

    if "DLSS5_Feed@DLSS5_Feed.fx" in body:
        report.add("dlss5:preset", True, f"{preset_path.name} 已启用 DLSS5_Feed")
        return

    techniques = ",".join(DLSS5_PRESET_TECHNIQUES)
    try:
        if body:
            backup = preset_path.with_name(f"{preset_path.name}.bak-before-fix")
            if not backup.is_file():
                shutil.copy2(preset_path, backup)
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        preset_path.write_text(
            f"PreprocessorDefinitions=\nTechniques={techniques}\nTechniqueSorting={techniques}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        report.add("dlss5:preset", False, f"写入 preset 失败: {exc}", manual=True)
        return

    report.add(
        "dlss5:preset",
        True,
        f"已{'修复' if body else '重建'} {preset_path.name}"
        "（启用 MartysMods_Launchpad + DLSS5_Feed）",
        fixed=True,
    )
    report.action(f"写入 {preset_path.name}")


def _check_reshade_ini(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """ReShade.ini 必须存在、含 [endfield-enhancer] 段、且路径指向当前 DLSS5 目录。"""
    ini = config.dlss5_ini_path
    dlss5 = config.dlss5_path
    text = ""
    if ini.is_file():
        try:
            text = ini.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            report.add("reshade_ini", False, f"读取失败: {exc}", manual=True)
            return

    needs_rebuild = (not text) or (ENHANCER_SECTION not in text)
    did_rebuild = False
    if needs_rebuild:
        rebuilt_text = _rebuild_ini(config, text)
        if rebuilt_text is None:
            report.add("reshade_ini", False, "ReShade.ini 缺失/缺少 [endfield-enhancer] 段，且找不到可用的模板或备份", manual=True)
            return
        try:
            if ini.is_file():
                shutil.copy2(ini, ini.with_suffix(".ini.bak-before-rebuild"))
            ini.write_text(rebuilt_text, encoding="utf-8", newline="\r\n")
        except OSError as exc:
            report.add("reshade_ini", False, f"重建失败: {exc}", manual=True)
            return
        report.action("重建 ReShade.ini")
        text = rebuilt_text
        did_rebuild = True

    # 路径是否指向当前目录（目录被搬动过就要重写）
    if str(dlss5).lower() not in text.lower():
        rewritten = re.sub(
            r"^((?:EffectSearchPaths|TextureSearchPaths|IntermediateCachePath|PresetPath)=).*$",
            lambda m: m.group(1) + _default_path_for(m.group(1), dlss5),
            text,
            flags=re.M,
        )
        try:
            ini.write_text(rewritten, encoding="utf-8", newline="\r\n")
            text = rewritten
            did_rebuild = True
            report.action("重写 ReShade.ini 路径")
        except OSError as exc:
            report.add("reshade_ini", False, f"重写路径失败: {exc}", manual=True)
            return
    report.add(
        "reshade_ini",
        True,
        "已重建/修正 ReShade.ini（含 [endfield-enhancer] 段，路径正确）"
        if did_rebuild
        else "ReShade.ini 就绪（含 [endfield-enhancer] 段，路径正确）",
        fixed=did_rebuild,
    )


def _default_path_for(key: str, dlss5: Path) -> str:
    if key.startswith("EffectSearchPaths"):
        return str(dlss5 / "reshade-shaders" / "Shaders" / "**")
    if key.startswith("TextureSearchPaths"):
        return str(dlss5 / "reshade-shaders" / "Textures" / "**")
    if key.startswith("IntermediateCachePath"):
        return str(dlss5 / "Temp" / "ReShade")
    return str(dlss5 / "ReShadePreset.ini")


def _rebuild_ini(config: AppConfig, current: str) -> str | None:
    """用模板 + 历史备份里的 enhancer 段重建。"""
    template = config.dlss5_path / "ReShade.ini.dlss5-template"
    if not template.is_file():
        for directory in source_dirs(config):
            candidate = directory / "ReShade.ini.dlss5-template"
            if candidate.is_file():
                template = candidate
                break
            candidate = directory / "ReShade.ini"
            if candidate.is_file():
                template = candidate
                break
    if not template.is_file():
        return None
    try:
        base = template.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None

    section: str | None = None
    # 从历史备份里取 enhancer 段（候选一律由配置推导，不硬编码本机路径）
    candidates = [config.reshade_runtime_path / "ReShade.ini"]
    backups = config.runtime_path / "backups"
    if backups.is_dir():
        try:
            candidates.extend([p / "ReShade.ini" for p in backups.iterdir() if p.is_dir()])
        except OSError:
            pass
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        match = re.search(r"^\[endfield-enhancer\][^\r\n]*\r?\n(.*?)(?=^\[|\Z)", text, re.S | re.M)
        if match:
            section = "[endfield-enhancer]\n" + match.group(1).rstrip() + "\n"
            break
    if section is None:
        return None

    dlss5 = config.dlss5_path
    base = base.replace(r".\reshade-shaders\Shaders\**", str(dlss5 / "reshade-shaders" / "Shaders" / "**"))
    base = base.replace(r".\reshade-shaders\Textures\**", str(dlss5 / "reshade-shaders" / "Textures" / "**"))
    base = base.replace(r".\Temp\ReShade", str(dlss5 / "Temp" / "ReShade"))
    base = base.replace(r".\ReShadePreset.ini", str(dlss5 / "ReShadePreset.ini"))
    # [endfield-enhancer] 要放最上面一层（与教程一致）
    return section + "\n" + base.rstrip() + "\n"


def _check_game_libs(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """游戏目录的 DLSS 运行库。

    **默认绝不覆盖游戏目录里已有的文件** —— 2026-09-27 实测：方案里的新版
    `nvngx_dlss.dll`(58,977,904 B) + `nvngx_dlssnr.dll`(165,840,496 B) 一旦被
    写进游戏目录，游戏就起不来；把 nvngx 还原成游戏原版(54,779,504 B) 并移走
    dlssnr 后，同一套注入能正常进游戏。而本函数原来的逻辑是"大小不符就从内置
    副本补齐"，于是**每次一键启动都会把用户刚还原好的原版又覆盖成新版**，
    表现为"手动启动没事、用控制器就崩"。

    现在的策略：
      * 文件已存在（无论大小）→ 保持原样，只在报告里注明；
      * 文件缺失 → 才从内置副本补齐（并先备份游戏原版）。
    需要主动部署新版运行库时，用 config.deploy_new_nvngx = True 显式开启。
    """
    from . import reshade_integration

    game = reshade_integration.detect_game_dir(config)
    if game is None:
        report.add("game_dir", False, "未定位到游戏目录", manual=True)
        return
    deploy_new = bool(getattr(config, "deploy_new_nvngx", False))
    for name in GAME_LIBS:
        source = config.dlss5_path / name
        target = game / name
        # nvngx_dlssnr.dll 是 DLSS5 专属、游戏原版**没有**这个文件，
        # 只有显式开启 deploy_new_nvngx 时才考虑放进去；否则"缺失"是正常状态。
        optional = name in GAME_LIBS_OPTIONAL
        if target.is_file():
            size = target.stat().st_size
            if deploy_new and source.is_file() and size != source.stat().st_size:
                try:
                    shutil.copy2(target, target.with_name(name + ".game_original"))
                    shutil.copy2(source, target)
                    report.add(f"game:{name}", True, "已替换为内置新版（deploy_new_nvngx=True）", fixed=True)
                    report.action(f"替换 {name} 为内置新版")
                except OSError as exc:
                    report.add(f"game:{name}", False, f"替换失败: {exc}", manual=True)
                continue
            report.add(f"game:{name}", True, f"{size} B（保持游戏现有文件不动）")
            continue
        if not source.is_file():
            report.add(f"game:{name}", False, f"游戏目录缺该文件，内置副本也没有: {source}", manual=True)
            continue
        if optional and not deploy_new:
            report.add(f"game:{name}", True, "游戏原版不含此文件，按设计保持不部署（DLSS5 专属）")
            continue
        try:
            shutil.copy2(source, target)
            report.add(f"game:{name}", True, "缺失，已从内置副本补齐", fixed=True)
            report.action(f"补齐 {name}")
        except OSError as exc:
            report.add(f"game:{name}", False, f"写入失败: {exc}", manual=True)


_RES_ID_PATTERNS = (
    re.compile(r"TextureOverride_([0-9a-fA-F]{8})"),          # 节名里的资源 hash
    re.compile(r"^\s*hash\s*=\s*([0-9a-fA-F]{8})\s*$", re.M),  # 行内 hash = xxxxxxxx
    re.compile(r"object_guid\s*=\s*(\d+)"),                    # EFMI ALPHA-1 的对象 id
    re.compile(r"mesh_vertex_count\s*=\s*(\d+)"),              # EFMI 的网格顶点数（辅助）
)


def _mod_resource_hashes(mod_dir: Path, limit_files: int = 40) -> set[str]:
    """提取一个 Mod 实际覆盖的游戏资源标识。

    终末地 Mod 的 ini 有几种写法（实测）：
      * `[TextureOverride_723fa5f9_别礼纱_VertexLimitRaise]` —— 节名里带 hash
      * `[TextureOverridehairib]` + 下一行 `hash = c88d3e16` —— 行内 hash
      * EFMI ALPHA-1 格式：`global $object_guid = 204102` —— 对象 id
    这些标识比"角色名"精确：两个 Mod 撞上同一批标识就一定会互相覆盖。
    返回带类型前缀的集合（`h:` 资源 hash / `g:` 对象 id / `v:` 顶点数）。
    """
    found: set[str] = set()
    try:
        inis = [p for p in mod_dir.rglob("*.ini")][:limit_files]
    except OSError:
        return found
    for ini in inis:
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for idx, pattern in enumerate(_RES_ID_PATTERNS):
            prefix = ("h:", "h:", "g:", "v:")[idx]
            for m in pattern.finditer(text):
                found.add(prefix + m.group(1).lower())
    return found


def _mod_conflict_summary(config: AppConfig, mods_dir: Path, names: list[str]) -> list[str]:
    """按「实际覆盖的资源标识相交」判定冲突。

    注意：很多 Mod 会同时 override 一批**公共资源**（实测有 4 个 hash 被 5 个以上
    Mod 共用），直接用交集会大量误报。所以先统计频率，把"被本组里超过 1/3 的 Mod
    覆盖"的标识当作公共资源排除，只看**两个 Mod 独享**的低频标识 —— 那才是真冲突。
    """
    from collections import Counter

    problems: list[str] = []
    ids: dict[str, set[str]] = {name: _mod_resource_hashes(mods_dir / name) for name in names}
    freq: Counter[str] = Counter()
    for values in ids.values():
        freq.update(values)
    threshold = 2   # 只被"这两个 Mod"覆盖的标识才算独享；被 3 个以上 Mod 共用的都是公共资源
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            # 单个标识相交可能是巧合，要求至少 2 个独享标识同时相交
            shared = {x for x in (ids[a] & ids[b]) if freq[x] <= threshold}
            if len(shared) >= 2:
                sample = ", ".join(sorted(shared)[:3])
                problems.append(f"「{a}」与「{b}」覆盖同一批资源（{len(shared)} 个独享标识: {sample}…）")
    return problems


def _check_mod_conflicts(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """检测 EFMI\\Mods 里的 Mod 冲突。

    判据分两层：
      ① **精确层**：解析每个 Mod 的 ini，比较它实际覆盖的资源 hash
         （`TextureOverride_<hash>_<部位>`）——相交即为真冲突；
      ② **角色层**：用 core 的角色别名表从目录名推断角色，同角色多个给出提示
         （同角色未必冲突，所以只提示不阻断）。
    另外任何**不带 `MC_` 前缀**的目录都视为"控制器不知道的手动 Mod"并报出。
    """
    mods_dir = config.staging_mods_path
    if not mods_dir.is_dir():
        report.add("mod_conflicts", True, "Mods 目录不存在（跳过）")
        return
    ignore_prefix = ("MC_Controller", "MC_Probe", "MC__deps")
    ignore_names = {"EndfieldModControllerManaged", "ModeControllerManaged", "DISABLED"}
    try:
        children = sorted(mods_dir.iterdir())
    except OSError as exc:
        report.add("mod_conflicts", False, f"读取 Mods 失败: {exc}", manual=True)
        return

    staged: list[str] = []
    manual: list[str] = []
    for child in children:
        if not child.is_dir() or child.name in ignore_names or child.name.startswith(ignore_prefix):
            continue
        (staged if child.name.startswith("MC_") else manual).append(child.name)

    problems = _mod_conflict_summary(config, mods_dir, staged)

    # 角色层：用 core 的别名解析（比 MC_ 前缀可靠）
    try:
        from . import core

        by_char: dict[str, list[str]] = {}
        for name in staged:
            kind, group = core.infer_kind_and_group([name], {})
            if kind == "character" and group:
                by_char.setdefault(group, []).append(name)
        for char, group_names in sorted(by_char.items()):
            if len(group_names) > 1:
                already = any(all(n in p for n in group_names) for p in problems)
                if not already:
                    problems.append(f"角色「{char}」有 {len(group_names)} 个 Mod: {', '.join(group_names)}")
    except Exception:  # noqa: BLE001
        pass

    if manual:
        shown = ", ".join(manual[:4]) + ("…" if len(manual) > 4 else "")
        problems.append(f"Mods 里有 {len(manual)} 个非控制器生成的目录（手动放的）: {shown}")

    if problems:
        report.add("mod_conflicts", False, "；".join(problems), manual=True)
        report.action("检测到 Mods 冲突（见上），请在 Mod 库页重新「生成控制器」清理")
    else:
        report.add("mod_conflicts", True, f"{len(staged)} 个 staging Mod，按资源 hash 比对无冲突")


def _check_secondary_motion(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    if not config.secondary_motion_injection:
        report.add("sbm", True, "已在设置里关闭乳摇注入自检")
        return
    from . import secondary_motion

    if config.secondary_motion_exe is None:
        report.add("sbm", False, "未找到乳摇工具目录（可在设置页配置）", manual=True)
        return
    result = secondary_motion.ensure_injection(config, log=log)
    state = secondary_motion.status(config)
    if result.get("warnings"):
        report.add("sbm", False, "; ".join(result["warnings"]), manual=True)
        return
    for action in result.get("actions", []):
        report.action(f"乳摇：{action}")
    ok = state.get("injected") and state.get("plugin_exists")
    report.add(
        "sbm",
        bool(ok),
        "proxy 与 plugin\\sbm.dll 已就位" if ok else "注入不完整",
        fixed=bool(result.get("actions")),
        manual=not ok,
    )


def _check_controller(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    controller_ini = config.controller_dir / "controller.ini"
    actions_tsv = config.controller_dir / "actions.tsv"
    if controller_ini.is_file() and actions_tsv.is_file():
        report.add("controller", True, "controller.ini / actions.tsv 已就位")
        return
    # ⚠ 空列表的语义是「全部激活」：selected_mods 为空时绝不能调 stage_and_prepare，
    # 否则会把整个 library stage 进 Mods，并把用户自己放进去的 Mod 全部清掉
    # （2026-09-27 实测：这个调用点导致"用控制器启动就崩、手动启动正常"，
    #  因为每次启动都因 controller.ini 缺失而重新 stage 全部 21 个 Mod）。
    if not config.selected_mods:
        report.add("controller", True, "未选择任何 Mod，跳过控制器生成（Mods 目录保持原样）")
        return
    try:
        from . import activation

        result = activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.selected_mods,
        )
        report.add("controller", True, f"已重新生成控制器（staging {result.get('patch_count', 0)} 个 Mod）", fixed=True)
        report.action("重新生成控制器与 staging")
    except Exception as exc:  # noqa: BLE001
        report.add("controller", False, f"生成控制器失败: {exc}", manual=True)


def _check_staging(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """选中的 Mod 必须有对应的 MC_ staging 目录，否则服装 Mod 不会生效。"""
    if not config.selected_mods:
        report.add("staging", True, "没有选中任何 Mod（跳过）")
        return
    mods_dir = config.staging_mods_path
    existing = [d for d in mods_dir.glob("MC_*") if d.is_dir() and d.name not in {"MC_Controller"}] if mods_dir.is_dir() else []
    if existing:
        report.add("staging", True, f"{len(existing)} 个 MC_ Mod 已 staging")
        return
    try:
        from . import activation

        result = activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.selected_mods,
        )
        report.add("staging", True, f"已重新 staging {result.get('patch_count', 0)} 个 Mod", fixed=True)
        report.action("重新 staging 选中的 Mod")
    except Exception as exc:  # noqa: BLE001
        report.add("staging", False, f"staging 失败: {exc}", manual=True)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def ensure_all(config: AppConfig, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """逐项校验 + 补齐，返回完整报告。"""
    report = Report()
    # 先把随包资产展开（DLSS5 底座与游戏目录补齐都要用到它们）
    _check_bundled_assets(config, report, log)
    _check_dlss5_dir(config, report, log)
    _check_reshade_ini(config, report, log)
    _check_dlss5_preset(config, report, log)
    _check_game_libs(config, report, log)
    _check_controller(config, report, log)
    _check_staging(config, report, log)
    _check_mod_conflicts(config, report, log)
    _check_secondary_motion(config, report, log)

    payload = report.to_dict()
    for action in payload["actions"]:
        _log(log, f"初始化补齐: {action}")
    for warning in payload["warnings"]:
        _log(log, f"WARN 初始化: {warning}")
    ok_count = sum(1 for c in payload["checks"] if c["ok"])
    _log(
        log,
        f"初始化自检: {ok_count}/{len(payload['checks'])} 项就绪"
        + (f"，已补齐 {len(payload['actions'])} 项" if payload["actions"] else "")
        + (f"，待人工处理 {len(payload['pending'])} 项" if payload["pending"] else ""),
    )
    return payload
