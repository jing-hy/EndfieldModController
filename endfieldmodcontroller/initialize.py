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
from .config import AppConfig, PROJECT_ROOT

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

# ── 语言：第一人称插件与 ReShade 面板都配成中文 ──────────────────────────────
# 用户 2026-10-01：「我进去之后发现第一人称 mod 有个开关，跳（勾）了之后才能把
# 语言变成中文，你看一下配置在哪里，我要初始化的时候就配置成中文」。
#
# 取证（2026-10-01，直接读 `renodx-endfield-enhancer.addon64` 的字符串表）：
#   * 开关的 ini 键就是 `[endfield-enhancer] Language` —— 菜单里的搜索索引串是
#     `EndfieldEnhancerMenu / ##search / Pages / Language / EN / ZH`，即它的选项
#     只有两个：EN / ZH；
#   * 缺中文字体时它自己的报错原文是
#     "Chinese font missing: in ReShade Settings, select Chinese as the overlay
#      language or choose a Chinese-capable Global font (for example
#      Windows/Fonts/msyh.ttc)" → 说明**ReShade 面板语言也要设成中文**；
#   * 它内嵌的 ReShade 语言表是 `en` = English、`zh-CN` = 简体中文 (Simplified
#     Chinese)，所以 `[OVERLAY] Language` 要写 `zh-CN`。
#
# 数值映射（2026-09-29 由**用户手动切换后的文件**定案）：**`1` = 中文（ZH），`2` = 英文（EN）**。
# 决定性证据（唯一一种真正携带用户意图的证据）：用户手动在面板里把语言切到中文后，
# addon 把配置写进 `D:\zmdmod\modtest\runtime\dlss5\ReShade.ini`（18:57:22，清空重建后的
# 环境），里面 `[endfield-enhancer] Language=1`。闭环验证：初始化曾写 2 → 用户看到英文
# （「第一人称mod还是英语」）→ 他手动切中文 → 写回 1。
# ⚠️ 这个值我反复错过两次，教训写在记忆里：① **出厂默认值 = 1 并不能说明它代表哪个选项**
#    （addon 首次运行写出的全是出厂值，其中 Language=1 恰好就是中文）；
#    ② 一度拿"用户实机那份 ini 里是 1"当依据 —— 但那份里 Language 从未被他改过，无效；
#    ③ 只有"**用户亲手改过的那个键**"（对照出厂快照能看出变更）才能定值。
FIRSTPERSON_LANGUAGE_ZH = "1"
FIRSTPERSON_LANGUAGE_EN = "2"

# 重建 ini 时给 `[endfield-enhancer]` 的**可用默认段**。
# ⚠️ 只写 `Language` 是错的（2026-09-29 踩过）：其余键会由 addon 按它自己的默认补成 0 ——
# 其中 `ShortcutFirstPerson=0` 意味着**根本没有切换第一人称的快捷键**，用户按什么键都没
# 反应，表现就是「第一人称没效果」；`CameraEFMICompatibility=0` 还会让它与 EFMI 服装 Mod
# 共存不了。这里按**主环境（已验证可用）**的取值给一套能直接用的默认，符合用户
# "零配置启动即用"的准则。
FIRSTPERSON_DEFAULT_SECTION = (
    "[endfield-enhancer]\n"
    "CameraEFMICompatibility=1\n"            # 与 EFMI 服装 Mod 共存所必需
    "CameraFirstPerson=0\n"                  # 默认不常开，用快捷键切换
    "CameraFirstPersonDialogue=1\n"
    "CameraFirstPersonFOV=60\n"
    "CameraFirstPersonFOVOverride=0\n"
    "CameraFirstPersonMovement=1\n"
    "CameraMeshHeadHiding=1\n"
    "CameraSmoothPerspectiveTransition=1\n"
    f"Language={FIRSTPERSON_LANGUAGE_ZH}\n"  # 界面语言：中文
    "ShortcutFirstPerson=112\n"              # F1 切换第一人称
)

# DLSS5 的 ReShade preset 必须启用的 technique。
# **顺序有意义** —— DLSS5_Feed.fx 明确要求 MartysMods_Launchpad 启用且排在它上面。
#
# 运动矢量来源（`DLSS5_MV_PROVIDER` 预处理宏）也必须指定，否则 DLSS5_Feed 会报
# 「motion vectors will be zero (still images only)」—— 表现就是"不生成帧 / 只有静止
# 画面有效"（用户 2026-09-29 反馈「dlss5 还是没生成帧」）。取值见 DLSS5_Feed.fx 头部：
#   0 texMotionVectors（qUINT_motionvectors / DRME / dh_uber_motion，**需要另装 provider**）
#   1 Launchpad（iMMERSE Deferred::MotionVectorsTex）← 我们本来就随包带了它，选这个
#   2 VORT    3 LumeniteFX Kernel    4 LumeniteFX QuantMotion
DLSS5_MV_PROVIDER_LAUNCHPAD = 1
# preset 里 `EffectSorting` 的顺序：provider 的效果文件必须排在 DLSS5_Feed 之前，
# 否则 addon 会报「provider is installed but DISABLED: enable it above DLSS 5 Feed.」。
DLSS5_PRESET_EFFECT_ORDER = "MartysMods_LAUNCHPAD.fx,DLSS5_Feed.fx"
DLSS5_PROVIDER_EFFECT = "MartysMods_LAUNCHPAD.fx"
DLSS5_FEED_EFFECT = "DLSS5_Feed.fx"
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
            report.add("dlss5:shader_deps", False, "reshade-shaders 缺失且找不到 reshade-shaders.zip", manual=True)
        else:
            try:
                with zipfile.ZipFile(source_zip) as archive:
                    archive.extractall(dlss5)
                report.add("dlss5:shader_deps", True, f"已从 {source_zip.name} 解压恢复", fixed=True)
                report.action("解压恢复 reshade-shaders")
            except (OSError, zipfile.BadZipFile) as exc:
                report.add("dlss5:shader_deps", False, f"解压失败: {exc}", manual=True)


# DLSS5 的 shader 编译依赖（**缺一个整条链就废**）。
# 2026-09-29 用户报「reshade 提示编译出错」，`ReShade.log` 原文：
#     ERROR | Failed to compile '...\reshade-shaders\Shaders\DLSS5_Feed.fx':
#     DLSS5_Feed.fx(60, 1): preprocessor error: could not open included file 'ReShade.fxh'
# 原因：从零环境只展开了 `DLSS5_Feed.fx` 与 `iMMERSE\`，**没有 ReShade 的 6 个标准头**，
# 也没有 `Textures\` 目录（`AreaLUT.png` 等找不到，ReShade 另报 WARN）。
# 这里按需补齐；源优先用随包 `assets\dlss5\`，其次用 dlss5 目录自身（开发机是全量的）。
DLSS5_SHADER_FILES: tuple[tuple[str, ...], ...] = (
    ("Shaders", "ReShade.fxh"),
    ("Shaders", "ReShadeUI.fxh"),
    ("Shaders", "Blending.fxh"),
    ("Shaders", "DrawText.fxh"),
    ("Shaders", "Macros.fxh"),
    ("Shaders", "TriDither.fxh"),
    ("Shaders", "DLSS5_Feed.fx"),
    ("Shaders", "iMMERSE", "MartysMods_LAUNCHPAD.fx"),
)


def _check_dlss5_shaders(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """DLSS5 需要的 shader 与 ReShade 标准头必须在位、Textures 目录必须存在。"""
    if not config.dlss5_injection:
        report.add("dlss5:shader_deps", True, "DLSS5 已在启动页关闭（跳过 shader 依赖检查）")
        return
    root = config.dlss5_path / "reshade-shaders"
    # ⚠️ **不能用 `Path(__file__).resolve().parents[1]`** —— 打包成单文件 exe 后 `__file__`
    # 指向 PyInstaller 的临时解压目录（`sys._MEIPASS`），而 assets 既没打进 exe、也不在那里，
    # 于是 exe 版**永远补不上 shader 标准头**，用户看到的就是
    # `Failed to compile 'DLSS5_Feed.fx': preprocessor error: could not open included file
    #  'ReShade.fxh'`（2026-09-29 实测）。`assets` 和 config.json / runtime / library 一样位于
    # **数据根**（exe 所在目录），所以走 `config.base_dir`。
    base_dir = getattr(config, "base_dir", None) or PROJECT_ROOT
    project_assets = Path(base_dir) / "assets" / "dlss5"
    sources = [project_assets / "shaders", root / "Shaders"]
    sources = [p for p in sources if p.is_dir()]

    missing: list[str] = []
    installed: list[str] = []
    for relative in DLSS5_SHADER_FILES:
        target = root.joinpath(*relative)
        if target.is_file():
            continue
        source = next((base.joinpath(*relative[1:]) for base in sources
                       if base.joinpath(*relative[1:]).is_file()), None)
        if source is None:
            missing.append("/".join(relative))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            installed.append("/".join(relative))
            report.action(f"补齐 DLSS5 shader 依赖 {relative[-1]}")
        except OSError as exc:
            missing.append(f"{'/'.join(relative)}（写入失败: {exc}）")

    # Textures 目录：不存在时 ReShade 会刷 "Failed to resolve search path ... error code 2"
    # ⚠️ 判据必须是"目录存在**且里面有文件**" —— 只看目录在不在的话，**空目录会被跳过**，
    # 而空目录同样会让 ReShade 报错、也会让 iMMERSE / DLSS5_Feed 找不到 AreaLUT.png 之类的
    # 纹理（2026-09-29 实测：从零安装后目录已存在但 0 个文件，于是永远补不上）。
    textures = root / "Textures"
    try:
        has_textures = textures.is_dir() and any(textures.iterdir())
    except OSError:
        has_textures = False
    if not has_textures:
        texture_sources = [project_assets / "textures", root / "Textures"]
        source_dir = next((p for p in texture_sources
                           if p.is_dir() and any(p.iterdir())), None)
        try:
            textures.mkdir(parents=True, exist_ok=True)
            copied = 0
            if source_dir is not None:
                for item in source_dir.iterdir():
                    if item.is_file():
                        shutil.copy2(item, textures / item.name)
                        copied += 1
                report.action(f"补齐 DLSS5 纹理（{copied} 个文件 → reshade-shaders\\Textures）")
        except OSError as exc:
            missing.append(f"Textures 目录（创建失败: {exc}）")

    if missing:
        report.add("dlss5:shader_deps", False,
                   "缺少 DLSS5 shader 依赖（会导致 ReShade 编译出错）: " + "、".join(missing),
                   manual=True)
    else:
        report.add("dlss5:shader_deps", True,
                   f"DLSS5 shader 依赖就绪（本轮补齐 {len(installed)} 个）" if installed
                   else "DLSS5 shader 依赖就绪（DLSS5_Feed.fx + ReShade 标准头）",
                   fixed=bool(installed))
    if log and installed:
        _log(log, f"补齐 DLSS5 shader 依赖: {', '.join(installed)}")


def _merge_preset_line(body: str, key: str, required: list[str], *, front: bool = False) -> str:
    """把 `required` 并入 preset 里 `key=` 那一行（逗号分隔、去重、保序）。

    ⚠️ **绝不要整体重写 preset**：ReShade 自己写出来的那份有 17 KB —— 含 500 多个
    technique 的排序，以及每个效果的变量表（`[MartysMods_LAUNCHPAD.fx]` 之类）。
    整体重写会把它们全砸掉，**连 technique 的"已启用"状态一起丢**，于是下次启动
    Launchpad 又变回 DISABLED（2026-09-29 反复踩这个坑）。所以只能"就地增补"。
    """
    lines = [line.rstrip("\r") for line in body.split("\n")]
    for index, line in enumerate(lines):
        if line.lstrip().startswith("[") or "=" not in line:
            continue
        if line.split("=", 1)[0].strip() != key:
            continue
        items = [item.strip() for item in line.split("=", 1)[1].split(",") if item.strip()]
        have = {item.split("@", 1)[0] if "@" in item else item for item in items}
        for name in required:
            bare = name.split("@", 1)[0] if "@" in name else name
            if bare not in have:
                items.insert(0, name) if front else items.append(name)
                have.add(bare)
        lines[index] = f"{key}=" + ",".join(items)
        return "\n".join(lines)
    # 没有这一行就追加
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append(f"{key}=" + ",".join(required))
    return "\n".join(lines)


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

    # 判据必须严：**"出现过"不算数** —— 两项都要启用（=1）且排序里 Launchpad 在前。
    # 2026-10-01 用户报「DLSS5 又出现不开始」，日志里写着
    # `LaunchPad technique found (DISABLED)`；而旧判据只看"有没有 DLSS5_Feed@DLSS5_Feed.fx"
    # 就直接放行（第 281 行），所以这种"写了但没启用 / 顺序不对"的状态**永远不会被修**，
    # 用户只能看到面板 NGX Hook 创建0 / 成功NR帧 0。
    launchpad_name, feed_name = DLSS5_PRESET_TECHNIQUES
    # ReShade 的 preset 里 technique 有两种写法：`Name@Effect.fx`（**列出即启用**，ReShade
    # 自己写出来的就是这种）与 `Name@Effect.fx=1`/`=0`（显式启用/禁用）。两种都要认 ——
    # 只认 `=1` 会把 ReShade 写的合法格式误判成"没启用"，于是每次启动都去"修"一遍
    # （2026-09-29 实测：ReShade 写的是不带 `=1` 的形式）。
    enabled_map: dict[str, str] = {}
    for name, value in re.findall(r"([\w.\-]+@[\w.\-]+\.fx)\s*(?:=\s*([01]))?", body):
        enabled_map[name] = value or "1"
    sorting_line = ""
    for line in body.splitlines():
        if line.strip().startswith("TechniqueSorting="):
            sorting_line = line.split("=", 1)[1]
            break
    order_ok = True
    if sorting_line:
        pos_launchpad = sorting_line.find(launchpad_name)
        pos_feed = sorting_line.find(feed_name)
        order_ok = pos_launchpad != -1 and (pos_feed == -1 or pos_launchpad < pos_feed)
    # `EffectSorting` 也必须查：addon 判断 provider 能不能用，看的是 **effect list** 的顺序
    # （DLSS5_Feed.fx 说明书第 16-24 行），少了它只会得到
    # `motion-vector provider MartysMods_Launchpad is installed but DISABLED:
    #  enable it above DLSS 5 Feed.`（2026-09-29 实测）—— 而且旧判据不查它，
    # 这种状态永远不会被修。
    effect_order_line = ""
    for line in body.splitlines():
        if line.strip().startswith("EffectSorting="):
            effect_order_line = line.split("=", 1)[1]
            break
    effect_order_ok = False
    if effect_order_line:
        pos_provider = effect_order_line.find(DLSS5_PROVIDER_EFFECT)
        pos_feed_fx = effect_order_line.find(DLSS5_FEED_EFFECT)
        effect_order_ok = (pos_provider != -1
                           and (pos_feed_fx == -1 or pos_provider < pos_feed_fx))
    # **判据 = 两项都启用**（2026-10-01 修）：顺序**不再**作为"必须修复"的条件 ——
    # 我们写入的顺序和 ReShade 自己重排后的顺序都可能变，拿顺序当判据会陷入
    # "每轮一键启动都报需要修复、修完自己又判不过"的死循环：一份真实诊断包里
    # `DLSS5 preset 需要修复：… technique 顺序正确=False、effect 顺序正确=False`
    # 从 10:33 一路报到 11:09，而 DLSS5 其实完全正常（feature ready + 帧统计都有），
    # 这种日志只会把用户和排查的人一起带偏。
    # 顺序不对时**只提示**：真出问题时面板与 `dlss5-feed.log` 会写明
    # `enable it above DLSS 5 Feed`，那时再按提示手动调。
    if enabled_map.get(launchpad_name) == "1" and enabled_map.get(feed_name) == "1":
        if not (order_ok and effect_order_ok):
            _log(log, "DLSS5 preset 顺序提示："
                      f"technique 顺序正确={order_ok}、effect 顺序正确={effect_order_ok} —— "
                      "ReShade 会按自己的规则重排这两行，通常无碍；"
                      "若面板或 dlss5-feed.log 出现 provider DISABLED"
                      "（enable it above DLSS 5 Feed），再把 MartysMods_Launchpad 排到 DLSS 5 Feed 之前")
        report.add("dlss5:preset", True,
                   f"{preset_path.name} 已启用 MartysMods_Launchpad + DLSS5_Feed"
                   + ("（顺序也正确）" if (order_ok and effect_order_ok)
                      else "（顺序由 ReShade 自行重排，不影响启用）"))
        return
    _log(log, "DLSS5 preset 需要修复："
              f"MartysMods_Launchpad={enabled_map.get(launchpad_name, '缺失')}、"
              f"DLSS5_Feed={enabled_map.get(feed_name, '缺失')}、"
              f"technique 顺序正确={order_ok}、effect 顺序正确={effect_order_ok}")

    techniques = ",".join(DLSS5_PRESET_TECHNIQUES)
    # **就地增补，绝不整体重写**（ReShade 自己写的那份有 17 KB，含 500+ technique 排序和
    # 各效果的变量表；整体重写会把"已启用"状态一起丢掉 —— 2026-09-29 反复踩）。
    # 同时**不带 `=1`**、与 ReShade 自己写出来的格式保持一致（它认"列出即启用"）。
    updated = body or ""
    updated = _merge_preset_line(
        updated, "PreprocessorDefinitions",
        [f"DLSS5_MV_PROVIDER={DLSS5_MV_PROVIDER_LAUNCHPAD}"],
    )
    # provider 必须排在 DLSS5_Feed **之上**（effect list 与 technique 顺序都要）。
    # ⚠️ 2026-10-01 修正：这里原来写的是 `[feed_name, launchpad_name]`（**feed 在前**），
    #    与上面的判据、与这里的注释、与 addon 的要求**全都相反** —— 于是每轮修完自己
    #    还是判不过，日志永远在报"需要修复"。现在统一成"launchpad（provider）在前"。
    # ⚠️ **不要写 `=1`** —— 照 ReShade 自己写出来的格式（"列出即启用"）。
    # 2026-09-29 实测：手写 `DLSS5_Feed@DLSS5_Feed.fx=1` 时 addon 一直不开 session，
    # 而 ReShade 自己写成不带 `=1` 之后 `feature ready / frame delivered` 才出现。
    updated = _merge_preset_line(updated, "Techniques", [launchpad_name, feed_name])
    updated = _merge_preset_line(updated, "TechniqueSorting",
                                 [launchpad_name, feed_name], front=True)
    updated = _merge_preset_line(updated, "EffectSorting",
                                 [DLSS5_PROVIDER_EFFECT, DLSS5_FEED_EFFECT], front=True)
    try:
        if body:
            backup = preset_path.with_name(f"{preset_path.name}.bak-before-fix")
            if not backup.is_file():
                shutil.copy2(preset_path, backup)
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        preset_path.write_text(updated + "\n", encoding="utf-8", newline="\r\n")
    except OSError as exc:
        report.add("dlss5:preset", False, f"写入 preset 失败: {exc}", manual=True)
        return

    report.add(
        "dlss5:preset",
        True,
        f"已{'修复' if body else '重建'} {preset_path.name}"
        "（启用 MartysMods_Launchpad + DLSS5_Feed，保留其余内容）",
        fixed=True,
    )
    report.action(f"增补 {preset_path.name}（不覆盖 ReShade 写的内容）")


def _check_dlss5_ngx_consumer(config: AppConfig, report: Report,
                              log: Callable[[str], None] | None) -> None:
    """有没有第三方在**截获 NGX**（目前已知的是 OptiScaler）—— **有就自动处理掉**。

    2026-10-01 加，起因是一份真实诊断包 + 用户发的三张面板截图：`ReShade.log` 报
    `Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C`，面板 `成功NR帧 ≈ 0`、
    `最新NR NGX结果 0xBAD00001`，用户说「未启动 DLSS5 / NR 也是 0」。根因是那台机器装了
    **OptiScaler DLSS-NR（`WINHTTP.dll` 注入）**：它把进程里**所有** NGX 调用截走
    （连游戏自带的 DLSS 一起），而它自己的 `[DlssNr] Enabled` 默认是 `false`、只做超分 ——
    于是 DLSS5 的神经渲染一帧都出不来。

    ⚠️ 我第一版把这里写成"给用户一句说明（这都属正常）"，方向是错的：
    ① OptiScaler 接管并**不是"正常"**，它让功能真的不工作；② 用户 2026-10-01 明确说
    「**不是提示的问题，正常用户不会看日志，需要自动检测处理**」。
    现在改成：**检测到就备份移走**（`game_clean.quarantine_injector`，proxy 补回系统原版、
    备份区可还原），并只报一项 `dlss5:ngx_conflict`（`fixed=True`）。
    """
    if not getattr(config, "dlss5_addon_enabled", True):
        report.add("dlss5:ngx_consumer", True, "DLSS5 已在启动页关闭（跳过 NGX 消费者检查）")
        return
    from . import reshade_integration      # 本模块其余检查也都是函数内导入，保持一致

    game_dir = reshade_integration.detect_game_dir(config, allow_scan=False)
    if game_dir is None:
        game_dir = reshade_integration.detect_game_dir(config)
    try:
        info = reshade_integration.optiscaler_present(game_dir)
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:ngx_consumer", True, f"检查 NGX 消费者时出错（不影响使用）: {exc}")
        return
    if info.get("present"):
        files = "、".join(info.get("files") or [])
        from . import game_clean

        result = game_clean.quarantine_injector(config, log=log)
        if result.get("changed"):
            report.add(
                "dlss5:ngx_conflict", True,
                f"检测到 OptiScaler（第三方 NGX 注入器：{files}）会截走 NGX 调用，"
                f"导致 DLSS5 的神经渲染一帧都出不来（面板会显示「成功NR帧 0」与 "
                f"「最新NR NGX结果 0xBAD00001」）——**已自动备份并移走** → "
                f"{result.get('backup_dir')}（要恢复就把里面的文件放回游戏目录）。"
                f"请重新进游戏，确认面板的「成功 NR 帧」开始增长、`NGX Hook 创建` > 0。",
                fixed=True,
            )
            _log(log, f"DLSS5 NGX 冲突: 已自动移走 OptiScaler（{files}）→ {result.get('backup_dir')}")
        else:
            report.add(
                "dlss5:ngx_conflict", False,
                f"检测到 OptiScaler（{files}），但自动移走失败：{result.get('message')}",
                manual=True,
            )
        return
    report.add("dlss5:ngx_consumer", True, "未检测到第三方 NGX 接管（走 ReShade 自己的 NGX hook 路线）")


def _check_dlss5_feed_redundant(config: AppConfig, report: Report,
                                log: Callable[[str], None] | None) -> None:
    """游戏**自带 DLSS** 时，自动停用「喂帧组件」（`dlss5-feed.addon64`）。

    2026-10-01，用户原话：「**你把 2 做了，然后在设置留个这个开关，默认开启自动停用**」。
    起因是 `dlss5-feed` 组件自己在日志里写的诊断：
    「this game runs NVIDIA Streamline (sl.interposer.dll): it has DLSS of its own …
      This project is for games WITHOUT DLSS — use the game's own DLSS with OptiScaler,
      and remove dlss5-feed.addon64」—— 自带 DLSS 的游戏上它多余，还会与游戏自己的 DLSS
    （以及 OptiScaler 这类第三方 NGX 注入器）抢同一条 NGX 链路。

    行为（都**可逆**，只移动 addon 文件，不动 preset/shader）：
    * 自带 DLSS 且喂帧组件在启用状态 → **停用**（移进 `_disabled`），报 `fixed=True`；
    * 不自带 DLSS 但它是被"上次按开关停用"的 → **自动放回**（换了游戏/换了版本也能自愈）；
    * 设置页把 `auto_disable_feed_on_native_dlss` 关掉 → 整项跳过（用户自己决定）。
    """
    if not getattr(config, "auto_disable_feed_on_native_dlss", True):
        report.add("dlss5:feed", True,
                   "已在设置页关闭「游戏自带 DLSS 时自动停用喂帧组件」（跳过）")
        return
    from . import launcher, reshade_integration

    try:
        status = launcher.feed_addon_status(config)
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:feed", True, f"读取喂帧组件状态失败（不影响使用）: {exc}")
        return
    if not status.get("present"):
        report.add("dlss5:feed", True, "喂帧组件不在位（跳过）")
        return

    game_dir = reshade_integration.detect_game_dir(config, allow_scan=False)
    if game_dir is None:
        game_dir = reshade_integration.detect_game_dir(config)
    native = reshade_integration.native_dlss_present(game_dir)
    hits = "、".join(native.get("files") or [])

    if native.get("present") and status.get("on"):
        result = launcher.set_feed_addon_enabled(config, False, log=log)
        if result.get("ok") and result.get("moved"):
            report.add(
                "dlss5:feed", True,
                f"检测到游戏**自带 DLSS**（{hits}）：喂帧组件（dlss5-feed.addon64）对这个游戏是"
                f"多余的，还会与游戏自己的 DLSS 抢同一条 NGX 链路 —— **已自动停用**"
                f"（移到 runtime\\dlss5\\_disabled\\，想在设置页关掉这个行为就会自动放回）。",
                fixed=True,
            )
        else:
            report.add("dlss5:feed", False,
                       f"检测到游戏自带 DLSS（{hits}），但停用喂帧组件失败：{result.get('message')}",
                       manual=True)
        return

    if not native.get("present") and not status.get("on"):
        result = launcher.set_feed_addon_enabled(config, True, log=log)
        if result.get("ok") and result.get("moved"):
            report.add("dlss5:feed", True,
                       "当前游戏未检测到自带 DLSS → 已把之前停用的喂帧组件**放回**",
                       fixed=True)
        else:
            report.add("dlss5:feed", True, "喂帧组件已停用，且当前游戏未检测到自带 DLSS（放回失败，稍后重试）")
        return

    report.add("dlss5:feed", True,
               f"喂帧组件状态正常（{'启用中' if status.get('on') else '已停用'}；"
               f"游戏自带 DLSS={'是' if native.get('present') else '否'}）")


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

    # ⚠️ 光有 `[endfield-enhancer]` 段**不足以**判定 ini 完好：从零环境里 ReShade.ini
    #    可能只剩各个 addon 运行时自己写进去的段（`[endfield-enhancer]` / `[INSTALL]` /
    #    `[RenoDX.DLSS5]`），**没有 `[GENERAL]`** —— 于是既没有 `EffectSearchPaths`
    #    （ReShade 不知道去哪找 shader）也没有 `PresetPath`（没有 preset），DLSS5 整条链
    #    都不工作。用户 2026-09-29 报「dlss5 还是没启动」，日志原文：
    #        DLSS5_Feed.fx is not loaded (technique/textures missing)
    #    所以这里把这些关键项一并作为"需要重建"的判据。
    needs_rebuild = (
        (not text)
        or (ENHANCER_SECTION not in text)
        or ("[GENERAL]" not in text)
        or ("EffectSearchPaths" not in text)
        or ("PresetPath" not in text)
    )
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
    # 中文补丁（终末地EE.addon64 / renodx-endfield-enhancer.addon64）的说明书
    # （包里的 `ini文件修改内容.txt`）只写了一件事：
    #     [INSTALL]
    #     PreventUnloading=1
    # 没有它，ReShade 卸载时会把 addon 一并卸掉，表现就是"补丁装了但面板还是英文/没生效"。
    # 2026-10-01 用户反馈「第一人称中文补丁还是没打上」—— 查下来 dlss5 目录那份
    # ReSade.ini（真正生效的那份）缺这一段，而 migoto 目录那份有。
    if "PreventUnloading" not in text:
        block = "[INSTALL]" + chr(10) + "PreventUnloading=1" + chr(10) + chr(10)
        candidate = (block + text) if text.strip() else block
        try:
            if ini.is_file():
                backup = ini.with_name(ini.name + ".bak-before-preventunloading")
                if not backup.is_file():
                    shutil.copy2(ini, backup)
            ini.write_text(candidate, encoding="utf-8", newline="\r\n")
            text = candidate
            did_rebuild = True
            report.action("写入 [INSTALL] PreventUnloading=1（第一人称中文补丁要求）")
        except OSError as exc:
            report.add("reshade_ini", False, f"写入 PreventUnloading 失败: {exc}", manual=True)
            return

    # 语言：初始化就把第一人称插件与 ReShade 面板配成中文（用户 2026-10-01 要求）
    try:
        # DLSS5 的运动矢量来源：不写这个宏，运动矢量全零 ⇒ 只对静止画面有效（"不生成帧"）
        text, mv_changed = _ensure_mv_provider(text)
        if mv_changed:
            ini.write_text(text, encoding="utf-8", newline="\r\n")
            report.action("写入 DLSS5_MV_PROVIDER=1（运动矢量来源：iMMERSE Launchpad）")
        language_text, language_changed = _ensure_chinese_language(text)
        if language_changed:
            if ini.is_file():
                backup = ini.with_name(ini.name + ".bak-before-language")
                if not backup.is_file():
                    shutil.copy2(ini, backup)
            ini.write_text(language_text, encoding="utf-8", newline="\r\n")
            text = language_text
            report.action("写入中文语言（第一人称插件 Language=ZH、ReShade 面板 Language=zh-CN）")
    except OSError as exc:  # noqa: PERF203
        report.add("reshade_language", False, f"写入中文语言设置失败: {exc}", manual=True)

    report.add(
        "reshade_ini",
        True,
        "已重建/修正 ReShade.ini（含 [endfield-enhancer] 段，路径正确）"
        if did_rebuild
        else "ReShade.ini 就绪（含 [endfield-enhancer] 段，路径正确）",
        fixed=did_rebuild,
    )


def _set_ini_key(text: str, section: str, key: str, value: str) -> tuple[str, bool]:
    """在 `[section]` 段内把 `key` 设为 `value`（存在就替换、不存在就插到段首）。

    返回 `(新文本, 是否有改动)`；无改动时原样返回输入（调用方据此决定要不要写盘）。
    段不存在时把整段追加到文件末尾。**只在目标段内动手**，不会碰同名的其它段。
    """
    lines = [line.rstrip("\r") for line in text.split("\n")]
    header = f"[{section}]"
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip().lower() == header.lower():
            start = index
            break
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", header, f"{key}={value}", ""])
        return "\n".join(lines), True
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].lstrip().startswith("["):
            end = index
            break
    for index in range(start + 1, end):
        if pattern.match(lines[index]):
            if lines[index].strip() == f"{key}={value}":
                return text, False
            lines[index] = f"{key}={value}"
            return "\n".join(lines), True
    lines.insert(start + 1, f"{key}={value}")
    return "\n".join(lines), True


def _ensure_mv_provider(text: str) -> tuple[str, bool]:
    """确保 `[GENERAL]` 的 `PreprocessorDefinitions` 里有 `DLSS5_MV_PROVIDER=1`（Launchpad）。

    不加这一项，DLSS5_Feed 的运动矢量全为零 ⇒ **只对静止画面有效、动态画面等于没效果**
    （用户 2026-09-29 报「dlss5 还是没生成帧」）。选 1 是因为随包就带了
    `iMMERSE\\MartysMods_LAUNCHPAD.fx`，它提供 `Deferred::MotionVectorsTex`；
    而默认的 0（texMotionVectors）需要另装 qUINT/DRME 之类的 provider，我们没带。
    """
    want = f"DLSS5_MV_PROVIDER={DLSS5_MV_PROVIDER_LAUNCHPAD}"
    lines = [line.rstrip("\r") for line in text.split("\n")]
    header_seen = False
    for index, line in enumerate(lines):
        if line.strip().lower() == "[general]":
            header_seen = True
            continue
        if header_seen and line.lstrip().startswith("["):
            break
        if header_seen and re.match(r"^\s*PreprocessorDefinitions\s*=", line, re.I):
            value = line.split("=", 1)[1]
            parts = [p.strip() for p in value.split(",") if p.strip()]
            if any(p.upper().startswith("DLSS5_MV_PROVIDER=") for p in parts):
                return text, False
            parts.append(want)
            lines[index] = "PreprocessorDefinitions=" + ",".join(parts)
            return "\n".join(lines), True
    if not header_seen:
        return text, False
    # 段在但没有这一行 → 插到 [GENERAL] 后面
    for index, line in enumerate(lines):
        if line.strip().lower() == "[general]":
            lines.insert(index + 1, "PreprocessorDefinitions=" + want)
            return "\n".join(lines), True
    return text, False


def _ensure_chinese_language(text: str) -> tuple[str, bool]:
    """把第一人称插件的界面语言设成中文（用户要求「初始化的时候就配置成中文」）。

    **只写 `[endfield-enhancer] Language` 这一处。**依据：用户手动把面板语言切成中文后，
    addon 写回的只有这一个键（实测 `modtest\\runtime\\dlss5\\ReShade.ini` 里只有
    `[endfield-enhancer] Language=1`，`[OVERLAY]` 段连 Language 键都没有）⇒ 中文**不需要**
    动 ReShade 面板语言。因此**不要**顺手改 `[OVERLAY] Language` —— 那会让 ReShade 自己的
    面板也变中文，属于需求外的改动（我一度加过 `zh-CN`，已撤掉）。
    """
    return _set_ini_key(text, "endfield-enhancer", "Language", FIRSTPERSON_LANGUAGE_ZH)


# ── 内置的 ReShade.ini 底稿（官方 DLSS5 模板的等价内容）────────────────────────
# 为什么必须内置：从零环境（用户只下 exe + 资产包）里 `ReShade.ini.dlss5-template`
# **不存在**，`_rebuild_ini()` 于是返回 None → **ReShade.ini 从未被正确生成**，
# 最终只剩各个 addon 运行时自己写进去的段（`[endfield-enhancer]` / `[INSTALL]` /
# `[RenoDX.DLSS5]`）——**没有 `[GENERAL]`** ⇒ ReShade 拿不到 `EffectSearchPaths`
# （不知道去哪找 shader）与 `PresetPath`（没有 preset）⇒ **DLSS5 整条链不工作**。
# 用户 2026-09-29 报「dlss5 还是没启动」，`dlss5-feed.log` 原文就是：
#     DLSS5_Feed.fx is not loaded (technique/textures missing) -- install it into
#     reshade-shaders\Shaders.
# 路径故意写成 `.\` 相对形式，随后由 `_rebuild_ini()` 统一替换成本机绝对路径。
BUILTIN_RESHADE_INI_BASE = (
    "[GENERAL]\n"
    r"EffectSearchPaths=.\reshade-shaders\Shaders\**" "\n"
    r"IntermediateCachePath=.\Temp\ReShade" "\n"
    "NoDebugInfo=1\n"
    "NoEffectCache=0\n"
    "NoReloadOnInit=0\n"
    "PerformanceMode=0\n"
    "PreprocessorDefinitions=RESHADE_DEPTH_INPUT_IS_UPSIDE_DOWN=1,RESHADE_DEPTH_INPUT_IS_REVERSED=1\n"
    r"PresetPath=.\ReShadePreset.ini" "\n"
    "PresetShortcutKeys=\n"
    "PresetShortcutPaths=\n"
    "PresetTransitionDuration=1000\n"
    "SkipLoadingDisabledEffects=0\n"
    "StartupPresetPath=\n"
    r"TextureSearchPaths=.\reshade-shaders\Textures\**" "\n"
    "\n"
    "[INPUT]\n"
    "ForceShortcutModifiers=1\n"
    "InputProcessing=2\n"
    "KeyEffects=0,0,0,0\n"
    "KeyFPS=0,0,0,0\n"
    "KeyFrametime=0,0,0,0\n"
    "KeyNextPreset=0,0,0,0\n"
    "KeyOverlay=36,0,0,0\n"
    "KeyPerformanceMode=0,0,0,0\n"
    "KeyPreviousPreset=0,0,0,0\n"
    "KeyReload=0,0,0,0\n"
    "KeyScreenshot=44,0,0,0\n"
    "\n"
    "[OVERLAY]\n"
    "AutoSavePreset=1\n"
    "ClockFormat=0\n"
    "FPSPosition=1\n"
    "Language=\n"
    "ShowClock=0\n"
    "ShowForceLoadEffectsButton=1\n"
    "ShowFPS=2\n"
    "ShowFrameTime=0\n"
    "ShowPresetName=0\n"
    "ShowPresetTransitionMessage=1\n"
    "ShowScreenshotMessage=1\n"
    "TutorialProgress=4\n"
    "VariableListHeight=200.000000\n"
    "VariableListUseTabs=0\n"
    "\n"
    "[SCREENSHOT]\n"
    "ClearAlpha=1\n"
    "FileFormat=1\n"
    "FileNaming=%AppName% %Date% %Time%\n"
    "JPEGQuality=90\n"
    "PostSaveCommand=\n"
    'PostSaveCommandArguments="%TargetPath%"\n'
    "PostSaveCommandHideWindow=0\n"
    "PostSaveCommandWorkingDirectory=." + "\\" + "\n"
    "SaveBeforeShot=0\n"
    "SaveOverlayShot=0\n"
    "SavePath=." + "\\" + "\n"
    "SavePresetFile=0\n"
    "SoundPath=\n"
    "\n"
    "[STYLE]\n"
    "Alpha=1.000000\n"
    "ChildRounding=0.000000\n"
    "ColFPSText=1.000000,1.000000,0.784314,1.000000\n"
    "EditorFont=\n"
    "EditorFontSize=20\n"
    "EditorStyleIndex=0\n"
    "Font=\n"
    "FontSize=20\n"
    "FPSScale=1.000000\n"
    "FrameRounding=0.000000\n"
    "GrabRounding=0.000000\n"
    "HdrOverlayBrightness=203.000000\n"
    "HdrOverlayOverwriteColorSpaceTo=0\n"
    "LatinFont=\n"
    "PopupRounding=0.000000\n"
    "ScrollbarRounding=0.000000\n"
    "StyleIndex=2\n"
    "TabRounding=4.000000\n"
    "WindowRounding=0.000000\n"
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
    # **找不到模板也要能重建** —— 用内置底稿兜底。从零环境里模板文件根本不存在，
    # 原来这里直接 `return None`，于是 ReShade.ini 永远生不出 `[GENERAL]` 段 ——
    # 那正是用户 2026-09-29 报的「dlss5 还是没启动」的根因（详见 BUILTIN_RESHADE_INI_BASE）。
    base = BUILTIN_RESHADE_INI_BASE
    if template.is_file():
        try:
            base = template.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            base = BUILTIN_RESHADE_INI_BASE

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
        # 连历史备份里都没有 `[endfield-enhancer]` 段时，至少写一个能用的最小段 ——
        # Language 直接给中文（用户要求"初始化就配成中文"），其余值交给 addon 自己补。
        section = FIRSTPERSON_DEFAULT_SECTION

    dlss5 = config.dlss5_path
    base = base.replace(r".\reshade-shaders\Shaders\**", str(dlss5 / "reshade-shaders" / "Shaders" / "**"))
    base = base.replace(r".\reshade-shaders\Textures\**", str(dlss5 / "reshade-shaders" / "Textures" / "**"))
    base = base.replace(r".\Temp\ReShade", str(dlss5 / "Temp" / "ReShade"))
    base = base.replace(r".\ReShadePreset.ini", str(dlss5 / "ReShadePreset.ini"))
    # [endfield-enhancer] 要放最上面一层（与教程一致）
    # ⚠️ **保留原文件里除"标准段"之外的所有段** —— 只用模板重建会丢掉各个 addon
    # 自己的配置段（`[RENODX-DLSS]` / `[RENODX-DLSS-preset1]` / `[RenoDX.DLSS5]` …），
    # 而那些段正是 DLSS5 能不能工作的关键：2026-09-29 实测，`[RENODX-DLSS]` 被丢之后
    # 面板显示「成功NR帧 0 / 超分 请求ON 活动OFF」，补回来才继续往下走。
    # 标准段（GENERAL/INPUT/OVERLAY/SCREENSHOT/STYLE）继续由模板提供 —— 它们含
    # `EffectSearchPaths` / `PresetPath` 这些必须指向本机绝对路径的键。
    preserved: list[str] = []
    if current:
        standard = {"general", "input", "overlay", "screenshot", "style"}
        for match in re.finditer(r"^\[([^\]]+)\][^\r\n]*\r?\n(.*?)(?=^\[|\Z)", current, re.S | re.M):
            name = match.group(1).strip()
            if name.lower() in standard or name.lower() == ENHANCER_SECTION.strip("[]").lower():
                continue
            body = match.group(2).rstrip()
            preserved.append(f"[{name}]\n" + (body + "\n" if body else ""))

    tail = base.rstrip() + "\n"
    if preserved:
        tail += "\n" + "\n".join(preserved)
    return section + "\n" + tail


def _check_game_libs(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """游戏目录的 DLSS 运行库。

    **DLSS5 的 NR 运行时不在游戏目录**（2026-09-30 更正）：`NVSDK_NGX_D3D12_EvaluateFeature_C`
    住在 `nvngx_dlssnr.dll` 里，而 RenoDX 的 DLSS5 addon 是**从 addon 自己所在目录**加载那份
    签名运行时 —— 即 `<数据根>\\runtime\\dlss5\\nvngx_dlssnr.dll`（addon 内的提示串就写着
    "the nvngx_dlssnr.dll in the addon folder"）。所以游戏目录里的 `nvngx_dlssnr.dll` 属于
    **游戏原版本来就没有**的文件，缺失是正常状态；要不要额外放一份进游戏目录，由
    `GAME_LIBS_OPTIONAL` + `deploy_new_nvngx` 决定。

    ⚠️ 历史包袱：2026-09-27 曾记录"写进新版 nvngx 游戏就起不来"（真正原因是注入链顺序，
    后来改用 Bypass + ReShade 先注入已修复）。但**替换游戏原版的 `nvngx_dlss.dll` 仍有让
    游戏起不来的风险**，所以 `deploy_new_nvngx` 保持默认 **False**：打开后才在大小不符时
    替换，替换前把原版锁存成 `*.game_original`（只锁存一次），用户可随时回滚。
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
                    original = target.with_name(name + ".game_original")
                    # **原版只锁存一次**：第二次替换时 target 已经是内置新版，
                    # 再备份就把"游戏原版"冲掉了 —— 而上面的注释记着
                    # "写进新版 nvngx 会让游戏起不来"，原版没了就回不去（2026-10-01 修）。
                    if not original.is_file():
                        shutil.copy2(target, original)
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


def _mod_conflict_summary(config: AppConfig, mods_dir: Path, names: list[str]) -> list[dict[str, Any]]:
    """按「实际覆盖的资源标识相交」判定冲突。

    注意：很多 Mod 会同时 override 一批**公共资源**（实测有 4 个 hash 被 5 个以上
    Mod 共用），直接用交集会大量误报。所以先统计频率，把"被本组里超过 1/3 的 Mod
    覆盖"的标识当作公共资源排除，只看**两个 Mod 独享**的低频标识 —— 那才是真冲突。

    **返回结构化冲突组**（2026-10-01 改）：不再只是给人看的字符串 —— 前端要
    「每组冲突一个下拉框、让用户挑保留哪个」（用户要求"一键关闭其中一个（自行选择）…
    在冲突的中间下拉框选择要保留的，每组冲突单独下拉框"），所以这里给出
    ``[{"names": [a, b], "shared": [...], "text": "「a」与「b」覆盖同一批资源（…）"}]``。
    """
    from collections import Counter

    groups: list[dict[str, Any]] = []
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
                ordered = sorted(shared)
                sample = ", ".join(ordered[:3])
                groups.append({
                    "names": [a, b],
                    "shared": ordered,
                    "text": f"「{a}」与「{b}」覆盖同一批资源（{len(ordered)} 个独享标识: {sample}…）",
                })
    return groups


def _check_bundled_versions(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """随包组件基线校验：`runtime\\dlss5` 里那几个文件是不是「我们实测可用的那一版」。

    为什么要有这一项（2026-09-30 一个 issue 的教训）：玩家很容易拿别处的「DLSS5 整合包」
    覆盖 `runtime\\dlss5\\` —— 其中 `nvngx_dlssnr.dll`（NR 的签名运行时）被换掉或删掉时，
    DLSS5 面板会显示「NR 未绑定 / 成功 NR 帧 0 / 最新 NR NGX 结果 0xBAD00001」，而文件
    看着都齐、shader 也编得过，极难排查（2026-09-30 issue #3 正是）。这里**只提示、
    不自动覆盖**用户文件（他的东西他做主）。

    `check_hash=True`：**小文件**逐个校验 sha256，"大小对但内容被换过"也能查出来；
    59/165 MB 的 nvngx 只比大小（全量哈希会把一键启动拖慢几秒，见 runtime_assets）。
    """
    from . import runtime_assets

    try:
        summary = runtime_assets.baseline_summary(config, check_hash=True)
    except Exception as exc:  # noqa: BLE001
        report.add("bundled_versions", False, f"随包组件基线校验失败: {exc}", manual=True)
        return
    if summary["ok"]:
        report.add("bundled_versions", True, f"随包组件与基线一致（{summary['total']} 项）")
        return
    report.add("bundled_versions", False, str(summary["detail"]), manual=True)
    report.action("随包组件与基线不一致（见上）：把 runtime\\dlss5 改名备份后重跑「一键启动」会重新展开随包版本")


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

    groups = _mod_conflict_summary(config, mods_dir, staged)
    problems: list[str] = [str(item.get("text") or "") for item in groups]

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
                already = any(all(n in str(p) for n in group_names) for p in problems)
                if not already:
                    problems.append(f"角色「{char}」有 {len(group_names)} 个 Mod: {', '.join(group_names)}")
    except Exception:  # noqa: BLE001
        pass

    if manual:
        shown = ", ".join(manual[:4]) + ("…" if len(manual) > 4 else "")
        problems.append(f"Mods 里有 {len(manual)} 个非控制器生成的目录（手动放的）: {shown}")

    # **把结构化冲突组补上库内 mod id**（2026-10-01）：前端「选择要保留的 Mod」弹窗
    # 要按 mod id 取消勾选。staging 目录名 = `MC_{safe_name(group)}_{safe_name(name)}`，
    # 所以扫一遍库、按同一公式重建名字就能精确反查（不靠猜、不比字符串相似度）。
    if groups:
        try:
            from . import core

            index = {
                f"MC_{core.safe_name(mod.group)}_{core.safe_name(mod.name)}": mod
                for mod in core.scan_library(config.library_path, config.staging_mods_path)
            }
        except Exception:  # noqa: BLE001
            index = {}
        for group in groups:
            entries = []
            for name in group.get("names") or []:
                found = index.get(name)
                entries.append({"name": name, "id": str(getattr(found, "id", "") or "")})
            group["mods"] = entries
            # resolvable = 每个 Mod 都能在库里定位到 id（定位不到就只能提示、不能自动处理）
            group["resolvable"] = all(entry["id"] for entry in entries)

    detail = "；".join(problems)
    # 留痕：崩溃监视要用它判断"这次崩溃是不是 Mod 冲突造成的" —— 是的话弹窗要走
    # 另一套文案与按钮（用户 2026-09-30 要求「确定是 mod 冲突要区别于其他崩溃情况」）。
    try:
        from . import diagnostics

        diagnostics.record_mod_conflicts(config, ok=not problems, detail=detail,
                                         conflicts=problems, groups=groups,
                                         mods=staged)
    except Exception:  # noqa: BLE001
        pass

    if problems:
        report.add("mod_conflicts", False, detail, manual=True)
        report.action("检测到 Mods 冲突（见上），请在 Mod 库页重新「生成控制器」清理")
    else:
        report.add("mod_conflicts", True, f"{len(staged)} 个 staging Mod，按资源 hash 比对无冲突")


def _check_poser(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """Endfield Poser（摆姿 / MMD 播放插件）自检。

    与乳摇同一套注入机制（游戏目录 proxy + `plugin\\*.dll` 全量加载），区别在于它的
    文件由**上游自己的安装向导**写入 —— 我们只下载安装包（`runtime\\poser`）再调向导，
    所以这里只做四件事：报状态、缺了就补齐、开关真正落地、把可读原因交给用户。
    """
    from . import poser

    if not getattr(config, "poser_injection", True):
        # 开关关着 = 「进游戏不加载 Poser」。已经装了的**不停用不卸载**（用户可能是
        # 临时关掉），但已经被开关停用过、又新装了 dll 的，按开关停用掉。
        try:
            state = poser.status(config, include_web=False)
            if state.get("installed"):
                result = poser.set_enabled(config, False, log=log)
                if result.get("changed"):
                    report.add("poser", True, "已按开关停用 Poser（重命名 plugin\\poser.dll，可逆）", fixed=True)
                    report.action("停用 Poser（启动页开关已关闭）")
                    return
                report.add("poser", False, str(result.get("message") or "停用 Poser 失败"), manual=True)
                return
        except Exception as exc:  # noqa: BLE001
            report.add("poser", False, f"停用 Poser 失败: {exc}", manual=True)
            return
        report.add("poser", True, "已在启动页关闭 Endfield Poser")
        return

    state = poser.status(config, include_web=False)
    if not state.get("pack_ready"):
        report.add(
            "poser", False,
            f"Endfield Poser 安装包未就位（{config.poser_path}）——"
            "依赖页点「自动安装/更新」，或再点一次「一键启动」会自动下载",
            manual=True,
        )
        return

    result = poser.ensure_injection(config, log=log)
    for action in result.get("actions", []):
        report.action(f"Poser：{action}")
    state = result.get("state") or poser.status(config, include_web=False)
    if result.get("ok"):
        detail = (f"plugin\\poser.dll + loader（{state.get('loader_kind') or '?'}）+ "
                  f"角色表情校准 {state.get('face_count', 0)} 份")
        others = state.get("other_plugins") or []
        if others:
            detail += f"；与 plugin 里的其它插件共存：{', '.join(others)}"
        report.add("poser", True, detail, fixed=bool(result.get("actions")))
        return
    report.add("poser", False, str(result.get("message") or "Poser 注入准备失败"), manual=True)


def _check_secondary_motion(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    from . import secondary_motion

    if not config.secondary_motion_injection:
        # 开关关着 = 「乳摇不生效」。若游戏目录里还留着上次装进去的注入，顺手卸干净：
        # 否则会出现"界面关了、游戏里其实还在生效"，做干净本体对照测试时也会一直被它干扰。
        try:
            state = secondary_motion.status(config)
            if state.get("injected") or state.get("plugin_exists"):
                result = secondary_motion.remove_injection(config, log=log)
                count = len(result.get("actions") or [])
                report.add("sbm", True, f"已按开关关闭乳摇注入（移走 {count} 项）", fixed=True)
                report.action("卸掉乳摇注入（开关已关闭）")
                return
        except Exception as exc:  # noqa: BLE001
            report.add("sbm", False, f"卸掉乳摇注入失败: {exc}", manual=True)
            return
        report.add("sbm", True, "已在设置里关闭乳摇注入自检")
        return

    # 注入源现在是「随包 assets 优先、乳摇工具目录可选」（见 secondary_motion._source_dir），
    # 所以**不再要求用户先配好工具目录** —— 直接尝试补齐即可（2026-09-29 用户反馈
    # 「bsm 不会自动跟随自动寻找的终末地目录，让 Mod 启动器先帮它配好」）。
    result = secondary_motion.ensure_injection(config, log=log)
    if not result.get("ok") and not result.get("actions"):
        report.add("sbm", False, str(result.get("message") or "sbm 注入准备失败"), manual=True)
        return
    state = secondary_motion.status(config)
    if result.get("warnings"):
        report.add("sbm", False, "; ".join(result["warnings"]), manual=True)
        return
    for action in result.get("actions", []):
        report.action(f"乳摇：{action}")
    ok = state.get("injected") and state.get("plugin_exists") and state.get("data_ready", True)
    report.add(
        "sbm",
        bool(ok),
        ("proxy、plugin\\sbm.dll 与插件数据均已就位" if ok else
         "注入不完整（proxy / plugin\\sbm.dll / SecondaryMotion 数据三者缺一，"
         "插件会自我禁用，表现为管理器显示游戏未启动、游戏里也没效果）"),
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
        from . import activation, launcher

        result = activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.selected_mods,
            hotkey_takeover=launcher.resolve_hotkey_takeover(config, config.controller_dir, log=log),
            allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
        )
        report.add("controller", True, f"已重新生成控制器（staging {result.get('patch_count', 0)} 个 Mod）", fixed=True)
        report.action("重新生成控制器与 staging")
    except Exception as exc:  # noqa: BLE001
        report.add("controller", False, f"生成控制器失败: {exc}", manual=True)


def _check_hotkey_panel(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """「整合 Mod 快捷键」打开时，统一面板必须真的躺在 ReShade 会读的目录里。

    用户 2026-10-01 的需求原话：「**开了要锁 mod 快捷键，注入 reshade**」—— 这两件事
    必须绑在一起。所以这里不只检查，还**自动补齐**（能自动做的就别让用户手动）；
    而面板根本用不了时（没开 ReShade 注入 / 底座缺失 / addon 文件丢了），启动链路
    会拒绝锁键，这里如实报出来，而不是假装一切正常。
    """
    from . import reshade_integration

    status = reshade_integration.panel_status(config)
    if not getattr(config, "hotkey_takeover", False):
        if status["addon_present"]:
            report.add("hotkey_panel", True, "统一面板已就位（「整合 Mod 快捷键」未开启，Mod 自带按键照常生效）")
        else:
            report.add("hotkey_panel", True, "「整合 Mod 快捷键」未开启：不注入面板，Mod 自带按键直接生效")
        return

    if not status["possible"]:
        report.add(
            "hotkey_panel",
            False,
            f"「整合 Mod 快捷键」开着但面板用不了（{status['reason']}）→ 已保持 Mod 热键不被锁死",
            manual=True,
        )
        return

    result = reshade_integration.deploy_panel(config, config.controller_dir, log=log)
    for warning in result.get("warnings", []):
        report.add("hotkey_panel", False, f"面板部署: {warning}", manual=True)
    refreshed = reshade_integration.panel_status(config)
    if refreshed["ready"]:
        report.add(
            "hotkey_panel",
            True,
            "统一面板已注入 ReShade（游戏内按 Home 打开；Mod 自带按键已交给控制器接管）",
            fixed=True,
        )
    else:
        report.add("hotkey_panel", False, "统一面板缺失：面板或动作清单没写进 ReShade 目录", manual=True)


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
        from . import activation, launcher

        result = activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.selected_mods,
            hotkey_takeover=launcher.resolve_hotkey_takeover(config, config.controller_dir, log=log),
            allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
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
    # shader 依赖要先补齐，否则 preset 里启用的 technique 编不过（"编译出错"）
    _check_dlss5_shaders(config, report, log)
    _check_dlss5_preset(config, report, log)
    # NGX 消费者检查：检测到第三方截获（OptiScaler）就**自动移走**（用户要求"自动检测处理"，
    # 不是写一句说明让用户自己看日志）
    _check_dlss5_ngx_consumer(config, report, log)
    # 游戏自带 DLSS → 自动停用「喂帧组件」（设置页有开关，默认开启）
    _check_dlss5_feed_redundant(config, report, log)
    _check_game_libs(config, report, log)
    _check_bundled_versions(config, report, log)
    _check_controller(config, report, log)
    # 统一面板（整合 Mod 快捷键用）：必须在控制器生成之后 —— 它要读 actions.tsv
    _check_hotkey_panel(config, report, log)
    _check_staging(config, report, log)
    _check_mod_conflicts(config, report, log)
    # Endfield Poser 必须在乳摇**之前**：它的 proxy 会加载 plugin 下所有 dll（含
    # sbm.dll），而乳摇的 ensure_injection 看到"proxy 已经在位"就会跳过 —— 顺序反了
    # 会先生成 sbm 版 loader，白多一次覆盖（两个 loader 都能加载对方的插件，但统一
    # 用 Poser 那份更省事，它还带身份标记可自证）。
    _check_poser(config, report, log)
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
