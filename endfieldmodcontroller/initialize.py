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

import os
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
    # ⚠️ **默认开着**（2026-10-05 改；用户实测要求：「**相机 hook 好像要等我开第一人称才创建**，
    #    你试一下**一开始就开上**」）：
    #    它是 `0`（出厂默认"不常开、用快捷键切换"）时，enhancer **不会去装相机 hook** ⇒
    #    日志里永远不会出现 `Camera controls installed.` ⇒ `nr_autostart` 只能一直等 ⇒
    #    用户看到的现象正是「**又测了一次，就是没自动开 nr**」（实测现场：ReShade.log 里
    #    enhancer 只打了 `Registered add-on` 一行，`installed` / `failed` 都没有）。
    #    用户随时按 F1（`ShortcutFirstPerson=112`）即可切回，不影响他自己的选择。
    "CameraFirstPerson=1\n"
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


def _downloadable_names() -> set[str]:
    """**有公开上游、能联网下载补齐**的文件名（小写）—— 判据委托给 `dlss5_fetcher`。

    为什么需要它（用户 2026-10-04 实测）：「自动修复还是有一个修不好」—— 日志里
    `dlss5:d3d12.dll / dlss5:dlss5-feed.addon64 缺失且找不到素材来源`，看着像"修不好"，
    其实这两个文件上游都有（ReShade 官网 / DLSS5-Feeder），只是修复这条路**只找本地素材**。
    用户的要求：「**要是缺下载，应该跳转到依赖进行下载**」。
    所以这里要先能识别"这是缺下载"，再由 `integrity` 把它标成 `needs_download`、
    前端据此跳依赖页。
    """
    try:
        from . import dlss5_fetcher

        return dlss5_fetcher.downloadable_file_names()
    except Exception:  # noqa: BLE001 —— 判据拿不到时按"不可下载"处理（退回原来的 manual 文案）
        return set()


def _component_key_for_file(name: str) -> str | None:
    """某个文件名属于哪个**可联网安装**的组件（用来在自检里直接补，而不是只喊一声）。

    判据委托给 `dlss5_fetcher.COMPONENTS` 的 `required` 列表 —— 与依赖页共用同一份清单，
    避免"依赖页能装、自检却说没有"的两套判据（同族教训：下载侧与激活侧必须共用判据）。
    """
    try:
        from . import dlss5_fetcher

        wanted = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        for component in dlss5_fetcher.COMPONENTS:
            for relative in component.required:
                if relative.replace("\\", "/").rsplit("/", 1)[-1].lower() == wanted:
                    return component.key
    except Exception:  # noqa: BLE001 - 判据取不到就当"不可下载"，走原来的提示分支
        return None
    return None


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
    # ④ **默认 DLSS5 目录**（`runtime\dlss5`）：用户把 `dlss5_dir` 改到别处之后，程序以前
    #    下载/展开的那一份还在这儿 —— 而"改过目录"恰恰是最容易缺组件的时候。
    candidates.append(config.runtime_path / "dlss5")
    # ⑤ **ReShade 的 base 目录**（`RESHADE_BASE_PATH_OVERRIDE` 的落点）
    candidates.append(config.reshade_runtime_path)
    # ⑥ **DLSS5 目录的上一级**：整合包常见的摆法就是"组件在父目录、游戏在子目录"
    #    （2026-10-04 反馈者那台：`E:\新建文件夹\d3d12.dll` + `E:\新建文件夹\Arknights Endfield\`，
    #    而他的 `dlss5_dir` 填的是那个子目录 ⇒ 以前只会报"缺失"，不会去上一级找）。
    parent = config.dlss5_path.parent
    if parent != config.dlss5_path:
        candidates.append(parent)
    # ⑦ 游戏目录（有人直接把组件铺在游戏目录里）
    game_exe = config.game_exe_path
    if game_exe is not None:
        candidates.append(game_exe.parent)
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
            # ⚠️⚠️ **`ok` 必须是"这个接口调通了"**（2026-10-04 修），不能是"没有待处理项"。
            #
            # 全项目约定 `{ok: bool}` = 调用成功/失败（前端 100+ 处 `r.ok === false` 都当失败
            # 处理）。这里原来写 `"ok": not pending` —— 只要有**一条**需要用户处理的自检项
            # （例如"未定位到游戏目录"），`SettingsPage.run()` 就先弹一个 danger toast
            # 「操作失败」，然后 `return` **把整份 checks/actions 丢掉**；`LaunchPage.run()`
            # 则弹「操作未完成」。结果：**自检功能除了全绿的理想情况之外等于不可用**
            # （用户看不到到底缺什么、也看不到已经自动修好了什么）。
            # "有没有待处理项"另有 `pending_count` / `pending` 表达。
            "ok": True,
            "success": True,
            "pending_count": len(pending),
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
      （第一人称 Enhancer、ReShade 面板汉化、RenoDX-DLSS5 引擎 7.0.0-rc8）。

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

    # ⚠️ **RabbitFX 随包展开**（2026-10-03 用户：「那把他随包」）。
    # 它本体只有 6 KB，而从 GameBanana 拉取在国内线路上实测只有 8 KB/s ——
    # 为这 6 KB 让用户等/失败不值得，所以随包放在 `assets\rabbitfx\`，启动时展开到
    # `<Mod 库>\_deps\RabbitFX`（与 `dependencies.json` 声明的安装位置一致）。
    # 它是**幂等**的：目标已存在就什么都不做（绝不覆盖用户自己更新过的那份）；
    # 库里已有别的副本时不铺（作者明确警告"多份会导致异常与崩溃"），只如实报出来。
    try:
        from . import rabbitfx

        fx = rabbitfx.ensure_bundled(config, log=log)
        if fx.get("status") == "installed":
            report.add("rabbitfx:bundled", True, f"RabbitFX 已随包展开到 {fx.get('dir')}", fixed=True)
            report.action("展开随包前置 RabbitFX（庄方宜菜单包等 Mod 需要它）")
        elif fx.get("status") == "already_elsewhere":
            report.add("rabbitfx:bundled", True, f"库里已有 RabbitFX：{fx.get('dir')}")
        elif fx.get("status") == "present":
            report.add("rabbitfx:bundled", True, "RabbitFX 已就位")
        # `missing` 不报错：依赖下载那条路会兜底（dependencies.json 里也声明了它）
    except Exception as exc:  # noqa: BLE001 —— 随包展开失败不该让自检整体失败
        _log(log, f"RabbitFX 随包展开出错（忽略，依赖下载会兜底）：{exc}")


def _extractall_with_backup(archive: "zipfile.ZipFile", dest: Path) -> list[str]:
    """把 zip 解到 `dest`，**但同名文件先留一份 `.mc.bak`**（2026-10-04 修的 U6）。

    为什么：`extractall` 会**无条件覆盖**同名文件 —— 而随包资产包里恰好有
    `ReShade.ini` 与 `d3d12.dll`（用户可能手改过、或换过别的版本）。
    这**不是** zip-slip（Python 自己会剔除 `..` 与绝对路径），而是"覆盖无备份 ⇒ 回不去"。
    备份只留第一份（最早那份才代表"我们动手之前"）。
    """
    from . import fsutil

    backed: list[str] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        target = fsutil.safe_join(dest, info.filename)
        if target is None or not target.is_file():
            continue
        backup = target.with_name(target.name + ".mc.bak")
        if backup.is_file():
            continue
        try:
            shutil.copy2(target, backup)
            backed.append(str(backup))
        except OSError:
            continue
    archive.extractall(dest)
    return backed


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
        if source is not None and name.lower() == "d3d12.dll":
            # ⚠️ 不是所有叫 `d3d12.dll` 的都是 ReShade 底座：反馈者游戏目录里那份 157,520 B 的
            #    就不是（程序当时判"内容不像 ReShade 载荷"并跳过，那个判断是对的）。往 DLSS5
            #    目录里复制一份错的底座，会把"明摆着缺文件"变成"补齐了却更查不出来"。
            from . import reshade_integration

            if not reshade_integration._looks_like_reshade_dll(source):
                source = None
        if source is None:
            # ⑧ **本机别处都没有 ⇒ 直接联网补齐**（2026-10-04 用户要求①）：`d3d12.dll` /
            #    `dlss5-feed.addon64` **不随包分发**，所以"只找本地素材"这条路上它们永远补不上
            #    ⇒ 用户看到的就是"填错目录 / 组件不全 ⇒ 注入链静默失效 + 一句提示"。
            #    现在：能下就下（判据与依赖页共用 `dlss5_fetcher.COMPONENTS`），下不动才退回
            #    原来那句清楚的手动指引。
            key = _component_key_for_file(name)
            if key:
                try:
                    from . import dlss5_fetcher

                    outcome = dlss5_fetcher.install(config, key, log=log)
                    if target.is_file():
                        report.add(f"dlss5:{name}", True,
                                   f"已联网下载补齐（组件 {key}）", fixed=True)
                        report.action(f"下载补齐 {name}")
                        continue
                    detail = ""
                    if isinstance(outcome, dict):
                        detail = str(outcome.get("message") or "")
                    report.add(f"dlss5:{name}", False,
                               f"缺失，联网补齐失败{('：' + detail) if detail else ''}"
                               "（可到「依赖」页重试）", manual=True)
                    continue
                except Exception as exc:  # noqa: BLE001
                    report.add(f"dlss5:{name}", False,
                               f"缺失，联网补齐失败: {exc}（可到「依赖」页重试）", manual=True)
                    continue
            # ⚠️ 说清"这是**缺下载**，不是坏了"（2026-10-04 用户实测）：
            # 他点「自动修复」后依然报 `dlss5:d3d12.dll / dlss5:dlss5-feed.addon64 缺失且找不到
            # 素材来源`，看起来像"修不好"。其实这两个文件上游都有（ReShade 官网 / DLSS5-Feeder），
            # 只是**修复这条路只找本地随包素材、不联网**。文案要点明这一点，好让前端/用户
            # 知道该去依赖页下载（判据 `dlss5_fetcher.downloadable_file_names()`）。
            downloadable = name.lower() in _downloadable_names()
            report.add(
                f"dlss5:{name}", False,
                (f"缺失（有公开上游，**可到「依赖」页联网下载补齐**）: {name}" if downloadable
                 else f"缺失且找不到素材来源: {name}"),
                manual=True,
            )
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
                    # 同名文件先留备份（U6）：这个包里含 ReShade.ini / d3d12.dll，
                    # 用户可能手改过、或换过别的版本
                    backed = _extractall_with_backup(archive, dlss5)
                note = f"已从 {source_zip.name} 解压恢复"
                if backed:
                    note += f"（{len(backed)} 个同名文件已备份为 .mc.bak）"
                report.add("dlss5:shader_deps", True, note, fixed=True)
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

        def _bare(name: str) -> str:
            return name.split("@", 1)[0] if "@" in name else name

        if front:
            # ⚠️⚠️ **`front` 必须一次性插到最前面**（2026-10-04 修）。
            # 原来对 `required` 逐个 `items.insert(0, name)` —— 这会把列表**反序**：
            # 调用方传 `[launchpad, feed]` 想要"launchpad（provider）在前"，
            # 实际写出来是 **feed 在前**。而 `DLSS5_Feed.fx` 的说明书明确要求
            # provider 排在它**上面**，写反了 addon 就会报
            # `motion-vector provider MartysMods_Launchpad is installed but DISABLED:
            #  enable it above DLSS 5 Feed.` —— 那次"顺序修正"实际从未生效
            #（只有"整行不存在"的追加分支是对的，而真实 preset 里这两行总是存在）。
            missing = [name for name in required if _bare(name) not in have]
            items[:0] = missing
            for name in missing:
                have.add(_bare(name))
        else:
            for name in required:
                bare = _bare(name)
                if bare not in have:
                    items.append(name)
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
                                   else dlss5 / (raw or "").lstrip(".\\/"))
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
    # ⚠️⚠️ **只扫 `Techniques=` 那一行**（2026-10-04 修）。
    # 原来对**整份 preset** 做正则，而 `TechniqueSorting=` / `EffectSorting=` 两行本身
    # 就是 `Name@Effect.fx` 形式、并且**列出全部 technique（含未启用的）** ——
    # 于是只要排序表里出现过 `DLSS5_Feed@DLSS5_Feed.fx`（几乎必然），它就会被记成 "1"，
    # 下面"两项都启用"的分支**恒成立** ⇒ 用户停用后自检**永远报 OK、永不修复**
    #（与注释里批判的"旧判据只看有没有就放行"是同一个洞）。
    # technique 的真实启用状态写在 `Techniques=` 行：列出即启用，也可写 `=1`/`=0`。
    techniques_line = ""
    for line in body.splitlines():
        if line.strip().startswith("Techniques="):
            techniques_line = line.split("=", 1)[1]
            break
    scan_text = techniques_line if techniques_line else body   # 老格式/空 preset 退回旧行为
    for name, value in re.findall(r"([\w.\-]+@[\w.\-]+\.fx)\s*(?:=\s*([01]))?", scan_text):
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
    # ★★ **还必须检查 `DLSS5_MV_PROVIDER=1` 那一行**（2026-10-06 两机对照定案）。
    #    它是**编译预处理宏**（写在 preset 的 `PreprocessorDefinitions=` 行里），决定
    #    DLSS5_Feed.fx 按哪个"运动矢量来源"编译：`1` = iMMERSE Launchpad。
    #    丢了它就按默认值 `0`（texMotionVectors）编译，而那个 provider 并没装 ⇒
    #    `motion vectors will be zero (still images only)` ⇒ NGX 建不出 feature。
    #    ⚠️ 光查 `Techniques` 检查不出这个状态（把那行删掉，`Techniques` 两项照样完好），
    #    所以必须单独判 —— 这正是"更新后仍然开不了"的那位的现场。
    preset_pp = ""
    for line in body.splitlines():
        if line.strip().startswith("PreprocessorDefinitions="):
            preset_pp = line.split("=", 1)[1]
            break
    mv_ok = f"DLSS5_MV_PROVIDER={DLSS5_MV_PROVIDER_LAUNCHPAD}" in preset_pp.replace(" ", "")
    if enabled_map.get(launchpad_name) == "1" and enabled_map.get(feed_name) == "1" and mv_ok:
        if not (order_ok and effect_order_ok):
            _log(log, "DLSS5 preset 顺序提示："
                      f"technique 顺序正确={order_ok}、effect 顺序正确={effect_order_ok} —— "
                      "ReShade 会按自己的规则重排这两行，通常无碍；"
                      "若面板或 dlss5-feed.log 出现 provider DISABLED"
                      "（enable it above DLSS 5 Feed），再把 MartysMods_Launchpad 排到 DLSS 5 Feed 之前")
        report.add("dlss5:preset", True,
                   f"{preset_path.name} 已启用 MartysMods_Launchpad + DLSS5_Feed"
                   "（含 DLSS5_MV_PROVIDER=1）"
                   + ("（顺序也正确）" if (order_ok and effect_order_ok)
                      else "（顺序由 ReShade 自行重排，不影响启用）"))
        return
    _log(log, "DLSS5 preset 需要修复："
              f"MartysMods_Launchpad={enabled_map.get(launchpad_name, '缺失')}、"
              f"DLSS5_Feed={enabled_map.get(feed_name, '缺失')}、"
              f"DLSS5_MV_PROVIDER={'有' if mv_ok else '★缺失'}、"
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
    # ⚠️⚠️ **写入前先确认目标在我们自己的地盘里**（2026-10-04 修的 U5）。
    # `preset_path` 来自 `ReShade.ini` 的 `PresetPath`，而它**可以是任意绝对路径** ——
    # 那份 ini 被第三方整合包改歪、或用户手工填了别处的路径时，这里就会往**游戏目录外面**写
    # （原来没有任何护栏，`core.PathGuard` 在生产代码里零调用）。
    # 允许的只有两处：DLSS5 目录（我们自己的 ReShade 底座）与游戏目录。
    from . import fsutil, reshade_integration as _reshade

    allowed_roots = [dlss5]
    game_dir = _reshade.detect_game_dir(config)
    if game_dir is not None:
        allowed_roots.append(Path(game_dir))
    if not any(fsutil.is_within(root, preset_path) for root in allowed_roots):
        report.add("dlss5:preset", False,
                   f"preset 路径不在 DLSS5/游戏目录内，已拒绝写入: {preset_path}", manual=True)
        return
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


def _check_dlss5_gpu_support(config: AppConfig, report: Report,
                             log: Callable[[str], None] | None) -> None:
    """**按显卡支持范围决定 DLSS5 能不能用**（不支持的机器 → 自动关掉，也不给手动开）。

    判据的唯一实现是 `deviceinfo.dlss5_supported()`：**NVIDIA + 型号名含 RTX
    （= 有 tensor core）⇒ RTX 20 系及以上都支持**。

    支持范围两度变更，这里跟着走、不自己判代次：
    * 2026-10-01：「开启时检测机器，如果不是 50 系就默认关 dlss5，开启 dlss5 的时候
      弹窗说明拒绝」—— 当时 DLSS5 首发只有 50 系运行库；
    * **2026-10-05**：「去掉所有对非 50 系的锁，换成对 a 卡和 10 系及以下和核显」——
      社区的架构重定向运行库到位后，40/30/20 系不再需要被挡（见 `runtime_assets` 的变体表）。

    这里**永远判 ok=True**：不支持的机器不是用户的故障（硬件不支持），不需要"待处理"；
    真发现开关还开着就顺手关掉（`fixed` 语义），并在消息里说清为什么。
    """
    from . import deviceinfo

    try:
        supported, gpu, reason = deviceinfo.dlss5_supported()
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:gpu_support", True, f"读不到设备信息（{exc}）—— 跳过显卡代次检查")
        return
    if supported:
        # ⚠️ **把 `reason` 也带上**（2026-10-05）：支持范围扩大后，"本机该用哪一份运行库
        # 变体"是排查"NR 不出帧"的第一判据，诊断包里必须有它。
        report.add("dlss5:gpu_support", True, f"满足 DLSS5 硬件前提：{gpu}｜{reason}")
        return
    turned_off = False
    if getattr(config, "dlss5_addon_enabled", True):
        config.dlss5_addon_enabled = False
        try:
            config.save()
        except (OSError, ValueError):
            # ValueError = 这份 config 还没落过盘（没有 _config_path）——
            # 自检不能因为"存不下去"就崩，内存里已经改掉了，行为是对的。
            pass
        try:
            from . import launcher

            launcher.set_component_addons(config, "dlss5", False)
            launcher.configure_dlss5_injection(config, enabled=True)
        except Exception:  # noqa: BLE001 - 关不掉文件不影响判词
            pass
        turned_off = True
        _log(log, f"DLSS5 已自动关闭：{gpu} —— {reason}")
    report.add(
        "dlss5:gpu_support",
        True,
        (f"{reason}　" + ("已自动关闭 DLSS5 开关。" if turned_off else "DLSS5 开关保持关闭。")),
    )


def _check_dlssnr_arch(config: AppConfig, report: Report,
                       log: Callable[[str], None] | None) -> None:
    """**运行库架构自检**：`nvngx_dlssnr.dll` 里有没有本机显卡的 CUDA 内核？

    为什么必须有（2026-10-05 换方案的配套）：DLSS5 的运行库是**按架构分别编译**的 ——
    NVIDIA 官方那份只带 sm_120（Blackwell），社区重定向版才带 sm_89 / sm_86 / sm_75。
    换显卡、被整合包替换文件、双卡机器换了主卡，只要落地的文件与本机架构不符，游戏里就是
    `feature 18 create failed with 0xBAD00001`，而用户完全看不出原因（本项目此前实测到的
    40 系失败，根因正是"随包那份只有 sm_120"）。

    判据（实测三份文件得出）：文件 fatbin 里含本机 sm ⇒ 正常；不含/读不出 ⇒ **自动换成
    `select_dlssnr_variant()` 选出的那一份**（旧文件留 `.bak`，可回退）。

    * 不支持的机器（A 卡 / 核显 / GTX）整项跳过 —— 不制造噪音；
    * 快路径先看 marker（不碰 165 MB），只有对不上才真扫 fatbin（实测 0.1 秒）。
    """
    from . import runtime_assets

    try:
        choice = runtime_assets.select_dlssnr_variant(config)
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:nr_arch", True, f"读取运行库变体失败（不影响使用）: {exc}")
        return
    if choice.sm is None:
        report.add("dlss5:nr_arch", True, "本机显卡不使用 DLSS5 神经渲染（跳过运行库架构检查）")
        return
    if choice.source_kind == "installed":
        report.add("dlss5:nr_arch", True,
                   f"运行库架构与本机显卡匹配（{runtime_assets.DLSSNR_TARGET} = 变体 "
                   f"`{choice.effective}`，本机 sm_{choice.sm}）")
        return
    # 快路径说"不确定/不匹配" → 慢路径真扫一次（换卡、被替换、marker 丢失都会走到这里）
    try:
        choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:nr_arch", True, f"扫描运行库架构失败（不影响使用）: {exc}")
        return
    if choice.source_kind == "installed":
        report.add("dlss5:nr_arch", True,
                   f"运行库架构已确认匹配（变体 `{choice.effective}`，本机 sm_{choice.sm}）")
        return
    if not choice.ok:
        report.add("dlss5:nr_arch", False,
                   f"找不到含本机架构（sm_{choice.sm}）的 DLSS5 运行库：{choice.reason}",
                   manual=True)
        return
    try:
        result = runtime_assets.ensure_dlssnr(config, log=log, force=True, rescan=True)
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:nr_arch", False, f"按显卡架构切换运行库失败: {exc}", manual=True)
        return
    if result.ok:
        report.add("dlss5:nr_arch", True,
                   f"已按你的显卡架构切换运行库：{result.message}", fixed=True)
    else:
        report.add("dlss5:nr_arch", False,
                   f"按显卡架构切换运行库没成功：{result.message}", manual=True)


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


def _pe_imports_name_bytes(data: bytes, name: str) -> bool | None:
    """PE 字节流的**导入表**里有没有某个函数名（True / False / None = 不是 PE）。"""
    if len(data) < 0x40 or data[0:2] != b"MZ":
        return None
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    if e_lfanew <= 0 or e_lfanew + 24 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return None
    coff = e_lfanew + 4
    n_sections = int.from_bytes(data[coff + 2:coff + 4], "little")
    opt_size = int.from_bytes(data[coff + 16:coff + 18], "little")
    opt = coff + 20
    if opt + 2 > len(data):
        return None
    magic = int.from_bytes(data[opt:opt + 2], "little")
    is64 = magic == 0x20B
    dd = opt + (112 if is64 else 96)
    if dd + 16 > len(data):
        return None
    imp_rva = int.from_bytes(data[dd + 8:dd + 12], "little")   # 数据目录 1 = 导入表
    if imp_rva == 0:
        return False

    sections: list[tuple[int, int, int]] = []
    sec_off = opt + opt_size
    for index in range(n_sections):
        base = sec_off + index * 40
        if base + 40 > len(data):
            break
        vsize = int.from_bytes(data[base + 8:base + 12], "little")
        va = int.from_bytes(data[base + 12:base + 16], "little")
        raw_size = int.from_bytes(data[base + 16:base + 20], "little")
        raw_ptr = int.from_bytes(data[base + 20:base + 24], "little")
        sections.append((va, max(vsize, raw_size), raw_ptr))

    def to_offset(rva: int) -> int | None:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + (rva - va)
        return None

    table_off = to_offset(imp_rva)
    if table_off is None:
        return None
    target = name.encode("ascii").lower()
    step = 8 if is64 else 4
    # ⚠ `IMAGE_THUNK_DATA.u1.AddressOfData` 是**完整的**指针宽度值（RVA），
    #   别再按"前 4 字节"去截（2026-10-02 自测里踩过：加偏移会让每个名字都读飞）。
    ordinal_flag = 1 << (63 if is64 else 31)
    mask = ordinal_flag - 1

    off = table_off
    for _ in range(4096):                      # 导入描述符数组，以全 0 项结尾
        if off + 20 > len(data) or data[off:off + 20] == b"\0" * 20:
            break
        first_thunk = int.from_bytes(data[off + 16:off + 20], "little")
        lookup = int.from_bytes(data[off:off + 4], "little") or first_thunk
        thunk_off = to_offset(lookup)
        if thunk_off is not None:
            for index in range(8192):
                pos = thunk_off + index * step
                if pos + step > len(data):
                    break
                value = int.from_bytes(data[pos:pos + step], "little")
                if value == 0:
                    break
                if value & ordinal_flag:
                    continue
                name_off = to_offset(value & mask)
                if name_off is None or name_off + 2 > len(data):
                    continue
                end = data.find(b"\0", name_off + 2)
                if end < 0:
                    continue
                if data[name_off + 2:end].lower() == target:
                    return True
        off += 20
    return False


def _pe_imports_name(path: Path, name: str) -> bool | None:
    """PE 文件的导入表里有没有某个函数名（None = 读不了或不是 PE）。

    只读文件头 + 导入表，不加载、不执行 —— 用来回答"这个 dll 靠什么读键"这类事实问题
    （面板能不能生效就取决于 EFMI 的 d3d11.dll 里有没有 `GetAsyncKeyState` 这个入口，
    见 `reshade_addon/src/vkey_inject.h`）。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return _pe_imports_name_bytes(data, name)


def _check_panel_hotkey_conflicts(config: AppConfig, report: Report,
                                  log: Callable[[str], None] | None) -> None:
    """游戏内 Mod 面板的**按键链路**体检。

    面板 2026-10-02 换了形态（用户：「让面板走 mod 的按键」「不要用开关或滑块，都是一个键」）：
    它不再锁 Mod 热键、也不再发合成输入，而是**在游戏进程内让 EFMI 的
    `GetAsyncKeyState` 轮询读到"按下"**（`reshade_addon/src/vkey_inject.h`）。
    这条链路有一个**能提前查、而且一坏就全坏**的前提，所以放在自检里：

    ① **EFMI 的 `d3d11.dll` 必须导入 `GetAsyncKeyState`** —— 直接读它的 PE 导入表。
       没有这个入口 = 面板所有按钮都会"点了没反应"（真 EFMI 实测有且只有这一个键盘入口）。

    ② **保留的旧判据**：ReShade / 其它 addon 有没有绑 `F13..F24`。
       旧合成协议键（`Ctrl+Alt+Shift+F13..F24`）已经退役、面板不再发送，
       `controller.ini` 里那批 `[KeyMC_*]` 段仍原样保留 —— 判据不删，继续报，
       免得将来谁又用起来时重演 2026-10-01 那次撞车（F6 = DLSS5 的 NR 开关、
       F7 = 第一人称切换，那些 addon 只轮询主键、不看修饰键）。
    """
    staged = config.staging_mods_path / "MC_Controller" / "controller.ini"
    efmi_dll = config.staging_mods_path.parent / "d3d11.dll"

    # ① 面板按键通路（新判据）
    injection: bool | None
    if efmi_dll.is_file():
        injection = _pe_imports_name(efmi_dll, "GetAsyncKeyState")
    else:
        injection = None
    if injection is True:
        note_ok = "面板按键通路 OK（EFMI 的 d3d11.dll 有 GetAsyncKeyState 读键入口）"
    elif injection is False:
        note_ok = ("面板按键通路**断了**：EFMI 的 d3d11.dll 里没有 GetAsyncKeyState 入口 —— "
                   "面板按钮会点了没反应（EFMI 大概换了读键方式，请把这条反馈给我们）")
    elif efmi_dll.is_file():
        note_ok = f"面板按键通路：读不了 {efmi_dll.name} 的导入表，无法确认"
    else:
        note_ok = "面板按键通路：还没装 EFMI（面板要靠它在游戏里读键）"

    # ② 旧协议键位的撞车兜底（判据保留）
    ini = config.dlss5_ini_path
    conflicts: list[str] = []
    if ini.is_file():
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("[") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            if not (name.lower().startswith("key") or "shortcut" in name.lower()):
                continue
            first = value.split(",")[0].strip()
            if not first.isdigit():
                continue
            code = int(first)
            if 124 <= code <= 135:                 # VK_F13..VK_F24
                conflicts.append(f"{name}=F{code - 111}")
    legacy: list[str] = []
    if staged.is_file():
        try:
            current = staged.read_text(encoding="utf-8", errors="replace")
        except OSError:
            current = ""
        if current and "VK_F13" not in current:
            legacy.append(str(staged))

    if conflicts:
        report.add(
            "panel:hotkey_conflicts", False,
            f"{note_ok}；另外，这些快捷键占用了旧协议键位 F13..F24：" + "、".join(conflicts)
            + " —— 协议键已退役（面板不再发它们），但 `controller.ini` 里的 `[KeyMC_*]` 段还在，"
              "将来谁再启用就会互相触发。要彻底干净就把这几项改到别的键"
              "（在 `runtime\\dlss5\\ReShade.ini` 的 `[INPUT]` / 各 addon 段里）。",
            manual=True,
        )
        return
    if legacy:
        report.add(
            "panel:hotkey_conflicts", True,
            f"{note_ok}；控制器的合成键位还是旧版（`F1..F12`）—— 下次「一键启动」会自动重写成 `F13..F24`。",
        )
        return
    if injection is False:
        report.add("panel:hotkey_conflicts", False, note_ok, manual=True)
        return
    report.add("panel:hotkey_conflicts", True, note_ok)



def _check_panel_protocol_lint(config: AppConfig, report: Report,
                               log: Callable[[str], None] | None) -> None:
    """面板协议的**语法**体检：读生成 controller.ini 时一起产出的 `controller.lint.txt`。

    2026-10-02 那一版踩的坑：跨命名空间引用写成了大写（`$\\mods\\MC_...\\0.ini\\coat`），
    3DMigoto 按小写登记变量名 ⇒ 那行赋值被**静默丢弃**。诡异之处在于"提交确实执行了"
    （同段里本就小写的 `$mc_action_seen` 正常自增），光看这个会误判成链路通了 ——
    所以生成时就用 3DMigoto 的源码规则体检一遍，并在这里报出来。
    """
    lint_file = config.staging_mods_path / "MC_Controller" / "controller.lint.txt"
    if not lint_file.is_file():
        report.add("panel:protocol_lint", True,
                   "还没有 controller.lint.txt（先跑一次「一键启动」/「生成控制器」）")
        return
    try:
        text = lint_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        report.add("panel:protocol_lint", False, f"读不到 controller.lint.txt（{exc}）", manual=True)
        return
    if not text or text.startswith("OK"):
        report.add("panel:protocol_lint", True, "面板协议体检通过（没有会被 3DMigoto 静默跳过的行）")
        return
    lines = [line for line in text.splitlines() if line.strip()]
    report.add(
        "panel:protocol_lint", False,
        f"面板协议有 {len(lines)} 处会被 3DMigoto **静默跳过**的行（面板点了会没反应）："
        + "；".join(lines[:3])
        + f"（完整清单见 {lint_file}）",
        manual=True,
    )


def _check_dlss5_nr_binding(config: AppConfig, report: Report,
                            log: Callable[[str], None] | None) -> None:
    """**上次进游戏时 DLSS5 的 NR 到底绑上没有？**没绑上就说清是哪一类原因。

    2026-10-01 一份真实反馈（v0.8.0）：「dlss5 也启动不了」——面板 `成功NR帧 0`、
    `超分: 请求ON | 活动OFF | 比例1.00`、`最新NR NGX结果 0xBAD00001`。查 `ReShade.log`
    看到真正的原因（原文）：

        DLSS5 Generic: NR upscaling is not applicable: the game's DLSS already renders at
        output resolution (2560x1440 vs output 2560x1440 (native)) format=28

    也就是**游戏内超分档位选在"原生/DLAA"**：DLSS5 的神经渲染是"重建更高的分辨率"，
    游戏已经按 2560x1440 原生输出，NR 没有放大任务 → NGX 直接拒绝创建 feature
    （`0xBAD00001`）。**这不是装坏了**，但用户不可能从那个码看出来，所以在这里如实报出
    并给出**具体动作**（游戏画面设置里把超分档位改成质量/平衡/性能）。

    判据只认**最近一次运行**的日志（以最后一个 `Initializing crosire's ReShade` 为界），
    没证据就不报 —— 不许拿上一次运行的结果吓人。

    ⚠️ **判据修正（2026-10-01 当天我在这里判错过一次，别再犯）**：`NR upscaling is not
    applicable: the game's DLSS already renders at output resolution` **只是一条 INFO**，
    DLAA / 原生档位下必然出现 —— 而 DLSS5 在那种情况下**照样正常工作**（用户原话：
    「我用的 dlaa 也能正常使用」；本机日志里 `created inline NR resources 3840x2160 ->
    3840x2160 (native)` 与 `inline feature 18 evaluation succeeded` 同时成立）。
    所以这句**绝不能**当失败判据；真正的失败信号是 `feature 18 create failed`。
    """
    if not getattr(config, "dlss5_addon_enabled", True):
        report.add("dlss5:nr_binding", True, "DLSS5 已在启动页关闭（跳过 NR 绑定检查）")
        return
    # ── 读**生效那份** `ReShade.log`（2026-10-06 修）─────────────────────────────
    # ⚠️ 以前这里读 `runtime\dlss5\ReShade.log` —— 那样本判据**在正常配置下永远空转**：
    #    ReShade 的基准目录是 `runtime\reshade`（`RESHADE_BASE_PATH_OVERRIDE`），日志只写
    #    在那里；反馈者诊断包里 `dlss5/ReShade.log` 一直是「按当前配置不存在」⇒ 每次都走
    #    「还没有 ReShade.log（没进过游戏，跳过）」。**判据读错文件 = 判据不存在**。
    log_path: Path | None = None
    try:
        from . import nr_autostart

        candidate = nr_autostart.reshade_log_path(config)
        if candidate.is_file():
            log_path = candidate
    except Exception:  # noqa: BLE001 - 取不到就退回旧位置，不能让自检本身崩掉
        log_path = None
    if log_path is None:
        legacy = config.dlss5_path / "ReShade.log"
        log_path = legacy if legacy.is_file() else None
    if log_path is None:
        report.add("dlss5:nr_binding", True, "还没有 ReShade.log（没进过游戏，跳过）")
        return
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.add("dlss5:nr_binding", True, f"读不到 ReShade.log（{exc}）")
        return
    # 只看最后一次运行：日志是追加的，老结果不能拿来判断现在
    marker = "Initializing crosire's ReShade"
    last = text.rfind(marker)
    recent = text[last:] if last >= 0 else text
    # ★ **"正常出帧"必须是"帧数真的在涨"**（2026-10-06 修）：以前只要日志里出现
    #   `evaluation succeeded` 就算正常 —— 而引擎**第一帧**就会打
    #   `inline feature 18 evaluation succeeded (count=1, ...)`，紧接着
    #   `NR workset pool exhausted; preserving game output for this evaluation`。
    #   于是"建了特征却一帧没出"被这条判据判成了"正常出帧"（反馈者机器上的实况：
    #   面板「成功NR帧 4」永远不动，自检却说一切正常）。
    counts = [int(value) for value in re.findall(r"evaluation succeeded \(count=(\d+)", recent)]
    best = max(counts) if counts else 0
    if best > 1:
        report.add("dlss5:nr_binding", True,
                   f"上次进游戏时 DLSS5 的 NR 正常出帧（日志里评估到第 {best} 帧）")
        return
    # ★ **建了 feature 18 却一帧没出**：引擎的 workset 池 fail closed —— 4 代 scratch
    #   workset 用满后，它认为那批 GPU 提交始终没完成（队列围栏没回来），于是**每一帧都
    #   把游戏自己的画面原样放行**（`preserving game output for this evaluation`）。
    #   2026-10-06 定案"与设置无关"：本机（同显卡、同驱动、同 NR 参数、同注入栈）
    #   复刻后照样出帧到 count=60；反馈者那台换版本、换打开时机（启动即开 / 中途手动开）
    #   结果都一样 ⇒ 改设置、重装组件都不可能修好它，别让用户白折腾。
    if ("workset pool exhausted" in recent
            or "NR workset completion fence could not be signaled" in recent):
        report.add(
            "dlss5:nr_frames", False,
            "上次进游戏时 DLSS5 的神经渲染**建立了特征、但一帧都没产出**：日志里 "
            "`feature 18 created` 之后紧跟 `NR workset pool exhausted` —— 引擎的 workset 池"
            "「fail closed」了（它认为那批 GPU 提交始终没完成，于是每帧都把游戏自己的画面"
            "原样放行）。**这不是设置问题**：改 NR 风格 / 强度 / 超分档位、重装组件、换版本"
            "都改变不了它 —— 请直接导出诊断包反馈，不必再折腾设置。",
            manual=True,
        )
        return
    if "feature 18 create failed" in recent or "NR feature create failed" in recent:
        # 这个码（`0xBAD00001` = NGX 回「不支持该特性」）有**两种完全不同的成因**，必须分开说：
        #   ① 卡本来就跑不了（A 卡 / Intel / 核显 / GTX：没有 tensor core）→ 硬件不支持，别折腾；
        #   ② 卡跑得了，但**落地的那份运行库不含本机架构** —— 2026-10-05 实测定案的根因
        #      （随包那份只有 sm_120，所以 40/30/20 系必然失败）。这种要给出可执行方向。
        sm = None
        gpu = ""
        try:
            from . import deviceinfo

            info = deviceinfo.collect()
            names = " / ".join(str(a.get("name") or "") for a in (info.get("adapters") or []))
            gpu = "、".join(
                str(a.get("name")) for a in (info.get("adapters") or [])
                if "nvidia" in str(a.get("name", "")).lower()
            ) or names
            sm = deviceinfo.best_rtx_sm()
        except Exception:  # noqa: BLE001
            sm = None
        if sm is None:
            report.add(
                "dlss5:nr_binding", True,
                f"上次进游戏时 DLSS5 的 NR 没建起来（`feature 18 create failed with 0xbad00001`）——"
                f"你的显卡是 **{gpu or '未检测到 NVIDIA RTX 显卡'}**。DLSS5 神经渲染需要 NVIDIA 的 "
                f"tensor core（RTX 20 系及以上才有），**这属于硬件不支持、不是装坏了**，"
                f"不用再折腾任何设置。",
            )
            return
        archs: set[int] = set()
        try:
            from . import runtime_assets

            target = config.dlss5_path / runtime_assets.DLSSNR_TARGET
            if target.is_file():
                archs = runtime_assets.dll_architectures(target)
        except Exception:  # noqa: BLE001
            archs = set()
        if archs and sm not in archs:
            report.add(
                "dlss5:nr_binding", False,
                f"上次进游戏时 DLSS5 的 NR 没建起来：**落地的那份运行库不含你显卡的架构**"
                f"（本机需要 sm_{sm}，而文件里只有 "
                f"{'、'.join('sm_' + str(item) for item in sorted(archs))}）—— 这正是 40/30/20 系"
                f"「NR 帧恒为 0」的根因。自检会按架构重新切换一份，切完进游戏再开一次 NR。",
                manual=True,
            )
            return
        report.add(
            "dlss5:nr_binding", False,
            f"上次进游戏时 DLSS5 的 NR 没建起来（`feature 18 create failed with 0xbad00001`），"
            f"而本机显卡（sm_{sm}）与运行库架构是**匹配**的 —— 那就要看驱动与 addon 版本的组合："
            f"`renodx-dlss5` 在驱动 ≥616.64 上有已知的 evaluate 失败（上游实测 4.55 通过 300/300、"
            f"4.7 通过 0/300）。请把显卡型号、驱动版本，以及 `ReShade.log` 里 "
            f"`feature 18 create failed` 前后 20 行发出来。",
            manual=True,
        )
        return
    report.add("dlss5:nr_binding", True, "上次运行的日志里没有 NR 失败记录")


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
    # ⚠️ **DLSS5 总开关关着 ⇒ 本项整项跳过**（2026-10-05 补）。
    # 原来这里只看 `auto_disable_feed_on_native_dlss`，**完全不看 `dlss5_addon_enabled`** ——
    # 于是"非 50 系显卡 → 自动关掉 DLSS5"之后，这段自愈又会以「游戏跑在 D3D11、喂帧组件是
    # DLSS5 的必需环节」为理由把 `dlss5-feed.addon64` **放回顶层**。DLSS5 都关了，
    # "给 DLSS5 喂帧是必需的"这句话本身自相矛盾；后果是一台控制器**自己判定**
    # "没 N 卡、DLSS5 用不了"的机器，NGX 喂帧链却一直活着（还会预加载 165 MB 的
    # `nvngx_dlssnr.dll`）。2026-10-05 反馈者现场：`dlss5_addon_enabled=False`，
    # 而 ReShade 实载 5 个 addon（含 DLSS 5 Neural Rendering 与 feed）。
    if not getattr(config, "dlss5_addon_enabled", True):
        report.add("dlss5:feed", True,
                   "DLSS5 已在启动页关闭 → 喂帧组件一并保持停用（跳过「自带 DLSS」自愈）")
        return
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

    # ⚠️ **光看文件不够**（2026-10-03 核实了用户转来的反馈）：
    # `native_dlss_present()` 只回答"游戏目录里有没有 sl.interposer.dll / nvngx_dlss.dll"，
    # 但 XXMI/EFMI 会强制 `-force_d3d11`，那时游戏**根本建不出 DLSS 特性**
    # （`Player.log` 里是 `Forcing GfxDevice: Direct3D 11`），喂帧组件反而是 DLSS5 的
    # **必需**环节 —— 停掉它等于把 DLSS5 彻底关掉（v0.9.5 就是这么把它弄坏的）。
    # 只有游戏**真的跑在 D3D12 上**、用得上自己那套 DLSS 时，"feeder 多余"才成立。
    # 用的是运行时证据（游戏自己的 Player.log），不是文件存在性。
    try:
        render_api = reshade_integration.detect_render_api(game_dir)
    except Exception:  # noqa: BLE001
        render_api = "unknown"
    feed_redundant = render_api == "d3d12"

    if native.get("present") and status.get("on") and not feed_redundant:
        report.add(
            "dlss5:feed", True,
            f"游戏目录里有自带 DLSS 的组件（{hits}），但**运行时并不是在跑它自己的 DLSS**"
            f"（检测到渲染 API：{render_api}）—— 这种情况下游戏建不出 DLSS 特性，"
            f"喂帧组件（dlss5-feed.addon64）是 DLSS5 的必需环节，**保持启用**"
            f"（停掉它等于把 DLSS5 关掉，v0.9.5 就是这么坏的）。"
            f"若你确实想让游戏用自己的 DLSS，请在 XXMI/EFMI 里去掉强制 -force_d3d11。",
        )
        return

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

    # 需要放回的两种情况：游戏不自带 DLSS；或自带但运行时根本不走它自己的 DLSS
    # （后者正是被 v0.9.5 那个只看文件的判据误停用的机器，必须能自愈）。
    if (not native.get("present") or not feed_redundant) and not status.get("on"):
        result = launcher.set_feed_addon_enabled(config, True, log=log)
        if result.get("ok") and result.get("moved"):
            report.add("dlss5:feed", True,
                       ("当前游戏未检测到自带 DLSS" if not native.get("present")
                        else f"游戏自带 DLSS 但运行时不在 D3D12（{render_api}），喂帧组件是必需的")
                       + " → 已把之前停用的喂帧组件**放回**",
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


# ── NR 必须等「第一人称插件的相机 hook」装好之后再开（2026-10-05 定案）────────────
# 生效那份 ini 的段/键名（ReShade 读的是 `RESHADE_BASE_PATH_OVERRIDE` 指向的那份）。
NR_SECTION = "RenoDX.DLSS5"
NR_KEY = "NeuralUplift"


def _check_mfg_unlock(config: AppConfig, report: Report,
                      log: Callable[[str], None] | None) -> None:
    """自检「**DLSS4 多帧生成解锁（40 系）**」（2026-10-06 用户要求的功能）。

    自检要能回答三件事：**这台机器能不能用**（判据）/ **开关现在什么状态** / **addon 真在不在位**。
    实现在 `deviceinfo.mfg_unlock_supported()` 与 `launcher.MFG_ADDON_GLOBS`。
    """
    from . import deviceinfo, launcher

    ok, reason = deviceinfo.mfg_unlock_supported()
    try:
        enabled = bool(getattr(config, "mfg_unlock_enabled", False))
    except Exception:  # noqa: BLE001
        enabled = False
    base = config.dlss5_path
    disabled = base / launcher.ADDON_DISABLED_DIR
    present = [name for name in launcher.MFG_ADDON_GLOBS if (base / name).is_file()]
    parked = [name for name in launcher.MFG_ADDON_GLOBS if (disabled / name).is_file()]

    if not ok:
        # 机器用不了（50 系 / 30-20 系 / 非 N 卡）⇒ 开关在界面上是禁用的，这里如实说明
        report.add("dlss5:mfg_unlock", True, f"（不适用）{reason}")
        return
    if not enabled:
        report.add("dlss5:mfg_unlock", True,
                   f"已关闭（默认）—— {reason}需要时在启动页打开「DLSS4 多帧生成」。")
        return
    if not present:
        report.add("dlss5:mfg_unlock", False,
                   "开关开着，但 addon 不在 `runtime\\dlss5\\` 里"
                   "（点一次「一键启动」会自动补齐；"+ (f"当前在停用区：{', '.join(parked)}" if parked else "两份都没有") + "）",
                   manual=True)
        return
    report.add("dlss5:mfg_unlock", True,
               f"已启用（{', '.join(present)}）—— {reason}"
               "注意：它与「DLSS5 神经渲染」**互斥**，同时只能开一个。")


def _check_defer_nr_until_camera_hook(config: AppConfig, report: Report,
                                      log: Callable[[str], None] | None) -> None:
    """把生效那份 `ReShade.ini` 的 `[RenoDX.DLSS5] NeuralUplift` 压成 **0**。

    **为什么（2026-10-05 用户在自己机器上实测定案）**：DLSS5 的 NR 若**抢在**
    「RenoDX Endfield Enhancer 装相机 hook」**之前**激活，那次 hook 会
    `error 8`（分配 hook trampoline 内存失败）装不上 ⇒ 第一人称面板报
    「不支持相机控制」。把 NR 推到相机 hook 装好之后再开，两边就都能用 ——
    用户实测原话：「现在可以使用第一人称了，而且我进游戏开了 dlss5，
    nr 帧在增加，第一人称也能用」。

    对照证据（同一台机器两次运行）：
      * 失败那次：`feature 18 created` 在 18:05:42，相机 hook 18:06:28 ❌；
      * 成功那次：相机 hook 18:22:33，`feature 18 created` 18:23:23 ✅。

    **补开 NR 的那一半**由 `nr_autostart` 在游戏运行期间自动做掉（它从 ReShade 日志里
    读出 NR 的实际快捷键，等 `Camera controls installed.` 出现后按一次）。

    ⚠️ **必须每次启动都压**：用户在游戏里开 NR 之后，插件会把 `NeuralUplift=1`
    **写回** ini，下次启动就又变成「NR 先上」⇒ 第一人称又坏（本机实测复现）。
    """
    # ★ **按「要不要用第一人称」分流**（2026-10-06）：enhancer 的相机 hook 与 NR 抢位置 ——
    #   NR 先上 ⇒ hook 装不上（`error 8`）⇒ **第一人称与相机控制都不能用**（实测现场）。
    #   * 要用第一人称 ⇒ 压 `NeuralUplift=0`，等 hook 装好后由 `nr_autostart` 补按 NR 键；
    #   * 不用 ⇒ 保持"启动就开"，NR 照样自动出帧（没有 hook 要保护）。
    from . import reshade_integration

    _want_firstperson = reshade_integration.firstperson_camera_wanted(config)
    immediate = (bool(getattr(config, "start_dlss5_nr_immediately", True))
                 and not _want_firstperson)
    if not immediate and not getattr(config, "auto_enable_nr_after_camera_hook", True):
        report.add("dlss5:nr_defer", True,
                   "「神经渲染延迟到相机 hook 之后自动打开」已在设置页关闭（跳过）")
        return
    if not getattr(config, "dlss5_addon_enabled", True):
        report.add("dlss5:nr_defer", True, "DLSS5 神经渲染已在启动页关闭（跳过）")
        return
    ini = Path(config.reshade_runtime_path) / "ReShade.ini"
    if not ini.is_file():
        report.add("dlss5:nr_defer", True, "生效那份 ReShade.ini 还不存在（跳过）")
        return
    try:
        if ini.stat().st_size > 1_048_576:
            report.add("dlss5:nr_defer", False, "ReShade.ini 异常巨大，跳过（疑损坏）", manual=True)
            return
        text = ini.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.add("dlss5:nr_defer", False, f"读取生效 ReShade.ini 失败: {exc}", manual=True)
        return
    # ★ **启动就开**（2026-10-06 默认）：写 `NeuralUplift=1`，不再等相机 hook。
    #   保守方案（新开关设 False 时）才写 0，并仍由 `nr_autostart` 在 hook 装好后补按。
    want = "1" if immediate else "0"
    updated, changed = _set_ini_key(text, NR_SECTION, NR_KEY, want)
    if not changed:
        report.add("dlss5:nr_defer", True,
                   "神经渲染已处于「启动就开」状态" if immediate
                   else "神经渲染已处于「延迟到相机 hook 之后」状态")
        return
    try:
        ini.write_text(updated.replace("\r\n", "\n").replace("\n", "\r\n"),
                       encoding="utf-8", newline="")
    except OSError as exc:
        report.add("dlss5:nr_defer", False, f"写入生效 ReShade.ini 失败: {exc}", manual=True)
        return
    report.add("dlss5:nr_defer", True,
               ("已把神经渲染设为**启动就开**（NeuralUplift=1）—— 不再依赖"
                "「相机 hook 装好」这个前提，不用第一人称的机器也能出帧")
               if immediate else
               ("已把神经渲染压到相机 hook 之后（NeuralUplift=0）—— 这样第一人称的相机 hook "
                "才装得上；进游戏后会自动补开 NR"), fixed=True)


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
    # ⚠️⚠️ **必须是 0**（2026-10-06 从两份 40 系对照包定案）：ReShade 在游戏退出时会把
    # 面板状态**回写 preset**，而我们增补进去的 `PreprocessorDefinitions=DLSS5_MV_PROVIDER=1`
    # 会随之被抹掉 ⇒ 下次启动 DLSS5_Feed 按默认值 0（texMotionVectors）编译 ⇒
    # 找不到运动矢量 provider ⇒ `motion vectors will be zero` ⇒ NGX 建不出 feature ⇒
    # 面板 `成功NR帧 0` + `0xBAD00007`。
    # 代价：面板里调的效果参数不再保存（那是可选调优）；换来的是"能不能出帧"的前提不被破坏。
    "AutoSavePreset=0\n"
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


# ---------------------------------------------------------------- VC++ 运行库
# 为什么加这一项（2026-10-05，issue #16）：反馈者现场的游戏退出码是
# `0xC0000135 = STATUS_DLL_NOT_FOUND`，而他的开关对照把范围缩到了
# 「只要注入 ReShade 底座（DLSS5 神经渲染 / 第一人称视角任一开启）就崩、
# 不注入就能进」。那条注入链上**唯一依赖 VC++ 运行库**的组件是
# `dlss5-feed.addon64`（它的导入表里写着 MSVCP140 / VCRUNTIME140 / VCRUNTIME140_1），
# 而他那台机器上的运行库是 14.42.34438、开发机是 14.51.36247。
#
# ⚠️ **这不是定案**：这一项的作用是**把判据采下来**（版本号会进自检、也会进诊断包），
# 让"他那台"和"我们这台"能一眼对照；低于下限时**只提示、不当故障** ——
# 运行库"版本旧"并不必然导致加载失败，把它报成故障会误导排查。
VC_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
VC_RUNTIME_MIN = (14, 40, 0)          # 保守下限（VS2022 17.10 那一档），不是硬判据
# 微软官方短链（2026-10-05 实测：302 → download.visualstudio.microsoft.com，
# 国内可直连、首字节 0.6s、支持 Range）。**不是第三方站点，也不是 GitHub。**
VC_RUNTIME_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _vc_runtime_versions() -> dict[str, dict[str, Any]]:
    """System32 里三个 VC 运行库的 `{名字: {path, version, missing}}`。"""
    from . import updates  # 复用现成的版本读取（ctypes + version.dll），不另写一份

    root = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"
    out: dict[str, dict[str, Any]] = {}
    for name in VC_RUNTIME_DLLS:
        path = root / name
        if path.is_file():
            try:
                version = updates.file_version(path) or ""
            except Exception:  # noqa: BLE001
                version = ""
            out[name] = {"path": str(path), "version": version, "missing": False}
        else:
            out[name] = {"path": str(path), "version": "", "missing": True}
    return out


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(x) for x in parts[:4]) if parts else ()


def vc_runtime_outdated(found: dict[str, dict[str, Any]]) -> bool:
    """三个运行库都在、但最低的那个低于 `VC_RUNTIME_MIN` ⇒ True。"""
    versions = [_version_tuple(v.get("version", "")) for v in found.values() if v.get("version")]
    if not versions:
        return False
    return min(versions) < VC_RUNTIME_MIN


def vc_runtime_summary(found: dict[str, dict[str, Any]]) -> str:
    """人能读的一句话：在位版本 / 缺了谁。"""
    missing = [n for n, v in found.items() if v.get("missing")]
    versions = [f"{n} {v.get('version') or '版本读不到'}"
                for n, v in sorted(found.items()) if not v.get("missing")]
    detail = "、".join(versions) or "一个都没找到"
    if missing:
        return f"缺少 {'、'.join(missing)}；现有：{detail}"
    return detail


def _check_vc_runtime(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """VC++ 运行库在位吗、版本够不够（**只报不改** —— 装系统组件要用户自己点）。"""
    try:
        found = _vc_runtime_versions()
    except Exception as exc:  # noqa: BLE001
        report.add("vc_runtime", False, f"读不到 VC++ 运行库信息: {exc}", manual=True)
        return
    missing = [n for n, v in found.items() if v.get("missing")]
    summary = vc_runtime_summary(found)
    if missing:
        report.add(
            "vc_runtime", False,
            f"缺少 VC++ 运行库（{'、'.join(missing)}）—— ReShade 的插件需要它，"
            f"装一次即可（微软官方）：{VC_RUNTIME_URL}",
            manual=True,
        )
        return
    if vc_runtime_outdated(found):
        report.add(
            "vc_runtime", True,
            f"VC++ 运行库 {summary}（比建议下限 "
            f"{'.'.join(str(x) for x in VC_RUNTIME_MIN)} 旧一档；若插件起不来可以先更新它："
            f"{VC_RUNTIME_URL}）",
        )
        return
    # 在位就报版本号 + 更新入口。**刻意不判"旧"**：我没有可靠阈值 —— 反馈者那台是
    # 14.42.34438、开发机是 14.51.36247，谁算"够用"我证明不了；编一个阈值只会把排查带偏
    # （2026-10-05）。把版本号如实摆出来，两台机器一对就知道差在哪。
    report.add("vc_runtime", True,
               f"VC++ 运行库 {summary}"
               f"（ReShade 的插件依赖它；需要更新时用微软官方安装包：{VC_RUNTIME_URL}）")


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

    # ⚠️ `prefer_actual=True`（2026-10-04）：这一步**会把 nvngx 运行库写进游戏目录** ——
    #    打在错的那份安装上毫无意义（反馈者那台正是如此：组件被铺到他根本不玩的 D 盘那份，
    #    而 XXMI 实际跑的是 E 盘）。
    game = reshade_integration.detect_game_dir(config, prefer_actual=True)
    if game is None:
        report.add("game_dir", False, "未定位到游戏目录", manual=True)
        return
    # 游戏目录错位必须**说出来**（配置写的那份 ≠ XXMI 实际启动的那份）：它会让所有
    # "游戏目录"结论一起失效，而用户完全看不到（2026-10-04 反馈者现场就是这样）。
    try:
        configured_exe = config.game_exe_path
        if configured_exe is not None and configured_exe.is_file():
            configured_dir = configured_exe.parent
            if not reshade_integration._same_dir(configured_dir, game):
                report.add(
                    "game_dir:mismatch", False,
                    f"游戏目录以 XXMI 实际启动的那份为准：{game}"
                    f"（配置里写的是 {configured_dir}）—— 建议到设置页把游戏目录改成前者",
                    manual=True)
    except Exception:  # noqa: BLE001 - 这条提示失败不该影响运行库部署
        pass
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


# RenoDX DLSS5 addon 自己的配置段。它在日志里写死过一句：
#   "RenoDX.DLSS5 NRStyle=2 is set -- this crashed at startup on the reference machine
#    (null read on the present path, blamed on whichever module presents next).
#    If this game crashes on launch, set NRStyle=0 in ReShade.ini's [RenoDX.DLSS5] section."
# `NRStyle=2` = 预发布字段 `DLSSNR.Style` 选「神经渲染模型 C」（0/1/2 = 模型 A/B/C，
# 见 addon 自带汉化 translations.txt）—— **不是"电影风格"**。
#
# ⚠️ **2026-10-02 起：只如实报告、绝不改动**。
#    曾经写过"命中崩溃记忆就把 2 改回 0"的自动修复 → 先按用户要求降级成死代码
#    （原话「你先把那个整段变成死代码，**先保留判断机制**，等后面结果出来了说不定还能用」），
#    结果出来后他说「**先把之前那个 nr 风格的死代码删掉**」→ **整段已删除**。
#    依据：实测把它改成 0 之后**照样崩在同一处**；而且当天更晚定案的真正崩因是
#    **RabbitFX 进了 staging**（见 topic 记忆），与 NRStyle 无关。
NRSTYLE_SECTION = "RenoDX.DLSS5"
NRSTYLE_BAD_VALUE = "2"


def _check_dlss5_nrstyle(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """**只报告** `[RenoDX.DLSS5] NRStyle` 的当前值，不做任何改动。"""
    ini = config.dlss5_ini_path
    if not ini.is_file():
        report.add("dlss5:nrstyle", True, "还没有 ReShade.ini（跳过 NRStyle 检查）")
        return
    try:
        text = ini.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.add("dlss5:nrstyle", False, f"读取 ReShade.ini 失败: {exc}", manual=True)
        return
    block = re.search(
        rf"\[{re.escape(NRSTYLE_SECTION)}\](.*?)(?=\n\s*\[|\Z)", text, re.S | re.I
    )
    current = ""
    if block:
        found = re.search(r"^\s*NRStyle\s*=\s*(\S+)\s*$", block.group(1), re.M | re.I)
        if found:
            current = found.group(1).strip()
    if current != NRSTYLE_BAD_VALUE:
        report.add(
            "dlss5:nrstyle",
            True,
            f"NRStyle={current or '未设置'}（不是会崩的 {NRSTYLE_BAD_VALUE}）",
        )
        return
    # NRStyle=2 = 预发布字段 `DLSSNR.Style` 选「神经渲染模型 C」（0/1/2 = 模型 A/B/C）。
    # **这是用户自己的设置，一律保留不动**（2026-10-02 定案：它既不是这里的崩因，
    # 也没有任何证据支持去改它）。
    report.add(
        "dlss5:nrstyle",
        True,
        f"NRStyle={NRSTYLE_BAD_VALUE} 是「神经渲染模型 C」（预发布字段 DLSSNR.Style，"
        "不是电影风格）—— 这是你的设置，**保留不动**",
    )


def _check_bundled_versions(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """随包组件基线校验 + **自动修复**。

    为什么要有这一项（2026-09-30 一个 issue 的教训）：玩家很容易拿别处的「DLSS5 整合包」
    覆盖 `runtime\\dlss5\\` —— 其中 `nvngx_dlssnr.dll`（NR 的签名运行时）被换掉或删掉时，
    DLSS5 面板会显示「NR 未绑定 / 成功 NR 帧 0 / 最新 NR NGX 结果 0xBAD00001」，而文件
    看着都齐、shader 也编得过，极难排查（2026-09-30 issue #3 正是）。

    **2026-10-02 升级为"自动修复"**：用户当天的现场是"配套里有文件偏离基线 ⇒ 游戏每次启动
    几十秒后崩在 `nvgpucomp64`"，而这里原先**只提示不修**，他最后只能自己把整个 `runtime\\`
    删掉重下才好。⇒ 随包组件坏掉就**按基线自动重展开**（先把原文件备份成
    `.bak-before-baseline-restore`，随时可还原）。**在线组件**（`dlss5-feed.addon64`）
    **不自动修** —— 它本来就允许被更新成上游最新版（已知可用集合见 `runtime_assets`）。

    `check_hash=True`：**小文件**逐个校验 sha256，"大小对但内容被换过"也能查出来；
    59/165 MB 的 nvngx 只比大小（全量哈希会把一键启动拖慢几秒，见 runtime_assets）。
    """
    from . import runtime_assets

    try:
        bad = runtime_assets.baseline_mismatches(config, check_hash=True)
    except Exception as exc:  # noqa: BLE001
        report.add("bundled_versions", False, f"随包组件基线校验失败: {exc}", manual=True)
        return
    if not bad:
        total = len(runtime_assets.manifest_entries(config)) + 1
        report.add("bundled_versions", True, f"随包组件与基线一致（{total} 项）")
        return
    repairable = [item for item in bad if str(item.get("group") or "") != "online"]
    online = [item for item in bad if str(item.get("group") or "") == "online"]
    if not repairable:
        report.add(
            "bundled_versions", True,
            "随包组件一致；在线组件：" + "；".join(item["message"] for item in online),
        )
        return
    result = runtime_assets.repair_mismatched(config, repairable, log=log)
    detail = str(result.get("message") or "")
    if online:
        detail += "。在线组件（按设计不改）：" + "；".join(item["message"] for item in online)
    report.add(
        "bundled_versions",
        bool(result.get("ok")),
        detail,
        fixed=bool(result.get("repaired")),
        manual=not bool(result.get("ok")),
    )
    if result.get("repaired"):
        report.action(
            "随包组件与基线不一致，已自动重新展开："
            + "、".join(result["repaired"])
            + "（原文件备份为 *.bak-before-baseline-restore）"
        )


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
    # **已经实测跑通过的组合：它们之间的"独享标识相交"不再报**（用户 2026-10-02 原话：
    #   「报了独享标识可能冲突的，**只要能进，都记忆不再报**」）。
    #   静态推测本来就只说"可能冲突"；用户带着这套进得去游戏，那条就等于被实测否掉了 ——
    #   继续报只会让人白折腾（2026-10-02 外部反馈里"湿润效果修复 vs 各皮肤"那 12 条就是这么来的：
    #   湿润效果修复是通用效果前置包，它跟每个皮肤都有交集是**设计使然**，不是两个 Mod 抢资源）。
    proven_ignored = 0
    try:
        from . import crashwatch

        kept_groups: list[dict[str, Any]] = []
        for item in groups:
            names = [str(x) for x in (item.get("names") or [])]
            if len(names) == 2 and crashwatch.conflict_pair_proven(config, names[0], names[1]):
                proven_ignored += 1
                continue
            kept_groups.append(item)
        groups = kept_groups
    except Exception:  # noqa: BLE001 —— 过滤失败就当没过滤，别把整项自检弄挂
        proven_ignored = 0
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
        extra = f"（另有 {proven_ignored} 条『独享标识相交』以前跑通过、已忽略）" if proven_ignored else ""
        report.add("mod_conflicts", False, detail + extra, manual=True)
        report.action("检测到 Mods 冲突（见上），请在 Mod 库页重新「生成控制器」清理")
    else:
        note = (f"（另有 {proven_ignored} 条『独享标识相交』以前跑通过、已忽略）"
                if proven_ignored else "")
        report.add("mod_conflicts", True, f"{len(staged)} 个 staging Mod，按资源 hash 比对无冲突{note}")


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


def _check_proxy_backups(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """loader proxy 的**原版备份**在不在 —— 缺了就从 System32 自动补齐。

    为什么必须查（2026-10-04，反馈者机器上就是这种状态）：
    游戏目录里 `d3dcompiler_47.dll` / `vulkan-1.dll` 已经是第三方 loader proxy
    （Poser / 乳摇那一套），而 **`.bak` 原版备份一个都没有**。
    这种"半吊子"状态危险在于：**还原 / 停用会把 proxy 删掉却放不回原版**
    ⇒ 游戏目录永久缺这两个系统模块 ⇒ 游戏起不来（历史事故，见 `game_clean` 注释）。
    而自检以前只看 `injected / plugin_exists / data_ready`（`backup_ok` 没算进去），
    于是这种状态 **31/31 全绿**，用户完全看不出来 —— 与"能自动检测处理"的要求相反。

    处理原则（用户定的「能自动补齐的就别让他手动」）：**能从 System32 补的就补掉**
    （记成 `fixed=True`）；确实补不到才提示，并且**明确写出"不要点还原"**。
    """
    from . import reshade_integration, secondary_motion

    try:
        game = reshade_integration.detect_game_dir(config)
    except Exception as exc:  # noqa: BLE001
        report.add("game_dir:proxy_backup", False, f"定位游戏目录失败: {exc}", manual=True)
        return
    if game is None:
        return
    proxies: list[str] = []
    for name in secondary_motion.PROXY_NAMES:
        path = Path(game) / name
        try:
            if path.is_file() and reshade_integration.looks_like_loader_proxy(path):
                proxies.append(name)
        except OSError:
            continue
    if not proxies:
        return                       # 游戏目录里没有 loader proxy，这一项不适用

    fixed: list[str] = []
    pending: list[str] = []
    for name in proxies:
        backup = Path(game) / f"{name}.bak"
        try:
            if backup.is_file() and backup.stat().st_size >= secondary_motion.PROXY_MAX_SIZE:
                continue
        except OSError:
            pass
        try:
            ensured = secondary_motion.ensure_proxy_backup(Path(game), name, log)
        except Exception as exc:  # noqa: BLE001
            report.add("game_dir:proxy_backup", False, f"补齐 {name}.bak 失败: {exc}", manual=True)
            return
        (fixed if ensured is not None else pending).append(name)

    if fixed:
        report.add(
            "game_dir:proxy_backup", True,
            f"已补齐 {len(fixed)} 个 loader proxy 的原版备份（{'、'.join(fixed)}）—— "
            f"「还原游戏本体 / 停用注入」现在能安全执行",
            fixed=True,
        )
    if pending:
        report.add(
            "game_dir:proxy_backup", False,
            f"{'、'.join(pending)} 没有原版备份、系统里也找不到同名原版 —— "
            f"**先别点「还原游戏本体」或「停用注入」**（proxy 删掉就放不回原版，游戏会起不来）；"
            f"确需还原请先手动复制一份该文件留着",
            manual=True,
        )
    if not fixed and not pending:
        report.add("game_dir:proxy_backup", True,
                   f"{len(proxies)} 个 loader proxy 都有原版备份，可安全还原")


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
    if not config.effective_selected_mods:
        report.add("controller", True, "未选择任何 Mod，跳过控制器生成（Mods 目录保持原样）")
        return
    try:
        from . import activation, launcher

        result = activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.effective_selected_mods,
            hotkey_takeover=launcher.resolve_hotkey_takeover(config, config.controller_dir, log=log),
            allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
            prefer_internal_dependencies=bool(
                getattr(config, "prefer_internal_dependencies", True)
            ),
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


def _staging_broken_inis(mods_dir: Path) -> list[dict]:
    """staging 里有没有"被旧版误删了汇编 `endif`"的 ini（我们自己的产物，可以放心重建）。"""
    from . import core

    broken: list[dict] = []
    if not mods_dir.is_dir():
        return broken
    for child in sorted(mods_dir.glob("MC_*")):
        if not child.is_dir() or child.name == "MC_Controller":
            continue
        for item in core.find_unbalanced_asm_inis(child, limit=8):
            broken.append({"mod": child.name, **item})
            break                      # 一个 Mod 记一条就够
    return broken


def _library_sources_broken(config: AppConfig, broken: list[dict]) -> list[dict]:
    """把 staging 里那些坏 ini 映射回**库里的源文件**，看库里的原件是不是也坏了。

    ⚠️ **为什么必须先看这一步**：staging 是**从库复制出来的**。如果库里的原件也被改坏
    （不是我们干的 —— 我们从来只改 staging 副本；可能是别的工具或手动编辑），那"重新生成
    staging"只会把坏文件再复制一遍，**看起来修好了、其实没有**，下次自检又来一遍。
    而**用户的 Mod 库是红线：任何情况都不动**（除非他自己点「移出 Mod 库」）——
    所以这种情况只能**如实报告 + 让他重新下载那些 Mod**，绝不自动改库。
    """
    from . import core

    bad: list[dict] = []
    try:
        mods = core.scan_library(config.library_path, config.staging_mods_path)
    except Exception:  # noqa: BLE001
        return bad
    by_dir = {f"MC_{core.safe_name(m.group)}_{core.safe_name(m.name)}": m for m in mods}
    for item in broken:
        mod = by_dir.get(str(item.get("mod") or ""))
        if mod is None:
            continue
        try:
            rel = Path(item["path"]).relative_to(config.staging_mods_path / str(item["mod"]))
        except (KeyError, ValueError):
            continue
        detail = core.ini_asm_if_unbalanced(mod.path / rel)
        if detail:
            bad.append({"mod": mod.name, "file": str(rel).replace("\\", "/"), **detail})
    return bad


def _check_staging(config: AppConfig, report: Report, log: Callable[[str], None] | None) -> None:
    """选中的 Mod 必须有对应的 MC_ staging 目录；**已有的 staging 还要抽查完整性**。

    ⚠️ **为什么要抽查**（2026-10-02 外部反馈的教训）：0.9.2 之前那个 bug 会把 staging 里
    Mod ini 的 **shader 汇编 `endif`** 删掉（`[ShaderRegex*.Pattern.Replace]` 段，实测
    `RabbitFX.ini` 删 62 行、湿润效果修复删 11 行、旗袍 `CutoutMask.ini` 删 4 行）⇒ 汇编不闭合
    ⇒ 驱动着色器编译器崩（`nvgpucomp64`）或模型干脆不出。它**只改 staging 副本、库里的原件是好的**，
    可是**已经生成过的 staging 会一直带着伤**：用户升级到新版后若不重新「一键启动」，
    游戏读到的仍是坏的，他会以为"新版没用"。所以这里主动发现 + **按库里的原件自动重新生成**。
    """
    if not config.effective_selected_mods:
        report.add("staging", True, "没有选中任何 Mod（跳过）")
        return
    mods_dir = config.staging_mods_path
    existing = [d for d in mods_dir.glob("MC_*") if d.is_dir() and d.name not in {"MC_Controller"}] if mods_dir.is_dir() else []
    broken = _staging_broken_inis(mods_dir) if existing else []
    if existing and not broken:
        report.add("staging", True, f"{len(existing)} 个 MC_ Mod 已 staging")
        return

    # 先确认库里的原件是好的 —— 库要是也坏了，重建 staging 只是把坏文件再复制一遍
    if broken:
        lib_broken = _library_sources_broken(config, broken)
        if lib_broken:
            items = "、".join(f"{i['mod']}（{i['file']}，缺 {i['missing']} 个 endif）"
                             for i in lib_broken[:3])
            report.add(
                "staging", False,
                f"你的 **Mod 库里**有 {len(lib_broken)} 个文件被改坏了：{items} —— 这是**库里的原件**"
                f"受损（不是本程序改的：我们只改给游戏加载的那份副本），重新生成也修不好。"
                f"请重新下载这些 Mod；**我们不会动你的 Mod 库**。",
                manual=True,
            )
            if log:
                log(f"staging 完整性: 库里的原件受损，未自动处理（不动用户库）：{items}")
            return

    try:
        from . import activation, launcher

        result = activation.stage_and_prepare(
            config.library_path,
            config.staging_mods_path,
            config.runtime_path,
            selected_ids=config.effective_selected_mods,
            hotkey_takeover=launcher.resolve_hotkey_takeover(config, config.controller_dir, log=log),
            allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
            prefer_internal_dependencies=bool(
                getattr(config, "prefer_internal_dependencies", True)
            ),
        )
        if broken:
            names = "、".join(item["mod"].replace("MC_", "", 1) for item in broken[:3])
            more = f" 等 {len(broken)} 个" if len(broken) > 3 else ""
            report.add(
                "staging", True,
                f"发现 staging 里有 {len(broken)} 个 Mod 的 ini 被**旧版本**改坏"
                f"（shader 汇编里少了 `endif`，会让游戏崩或模型不显示）：{names}{more}"
                f" —— 已按你库里的原件重新生成（库里的文件一直没动过）",
                fixed=True,
            )
            report.action("按库里原件重新生成被旧版改坏的 staging")
            if log:
                log(f"staging 完整性: 旧版误删 endif 的 Mod 已重新生成：{names}{more}")
        else:
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
    # NR 必须等「第一人称插件的相机 hook」装好之后再开（2026-10-05 定案）——
    # 放在 ini 处理**之后**：这一步直接改生效那份 `ReShade.ini` 的 `[RenoDX.DLSS5]`。
    _check_defer_nr_until_camera_hook(config, report, log)
    _check_mfg_unlock(config, report, log)
    # shader 依赖要先补齐，否则 preset 里启用的 technique 编不过（"编译出错"）
    _check_dlss5_shaders(config, report, log)
    _check_dlss5_preset(config, report, log)
    # NGX 消费者检查：检测到第三方截获（OptiScaler）就**自动移走**（用户要求"自动检测处理"，
    # 不是写一句说明让用户自己看日志）
    # 显卡支持范围决定 DLSS5 能否使用（不支持 → 自动关掉开关）
    _check_dlss5_gpu_support(config, report, log)
    # 运行库架构自检：这份 `nvngx_dlssnr.dll` 含不含**本机显卡的内核**（不含就自动换一份）
    _check_dlssnr_arch(config, report, log)
    _check_dlss5_ngx_consumer(config, report, log)
    # 面板合成键有没有和别的 addon 快捷键撞车（F6/F7 撞车事故的兜底检查）
    _check_panel_hotkey_conflicts(config, report, log)
    # 面板协议的**语法**体检（生成 controller.ini 时同时产出的 controller.lint.txt）
    _check_panel_protocol_lint(config, report, log)
    # DLSS5 的 NR 上次到底绑上没有（游戏内超分档位选成"原生/DLAA"时它永远绑不上）
    _check_dlss5_nr_binding(config, report, log)
    # 游戏自带 DLSS → 自动停用「喂帧组件」（设置页有开关，默认开启）
    _check_dlss5_feed_redundant(config, report, log)
    # ⚠️ `NRStyle` **只报告、不改动**（2026-10-07 更正：这条注释原来写着"→ 自动改回 0"，
    #    而那个自动改动的动作早就按用户要求删掉了 ⇒ 注释与实际行为相反，会误导排查）。
    #    现在只把当前值如实写进自检；`NRStyle=2` 与崩溃的因果归因已定案不成立。
    _check_dlss5_nrstyle(config, report, log)
    _check_game_libs(config, report, log)
    _check_bundled_versions(config, report, log)
    # VC++ 运行库版本（2026-10-05 加）：issue #16 的退出码是 STATUS_DLL_NOT_FOUND，
    # 而注入链上唯一依赖它的组件是 dlss5-feed.addon64 ⇒ 先把版本号这条判据采下来。
    _check_vc_runtime(config, report, log)
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
    # 两个 loader 都在位之后再查"原版备份在不在"（proxy 是它们铺的）：
    # 缺 .bak 时**自动从 System32 补**，补不到就明确告诉用户"先别点还原"。
    _check_proxy_backups(config, report, log)

    # ⚠️⚠️ **总开关关着时，最后再按开关归位一次 addon 位置**（2026-10-05 补，必须放最后）。
    # 为什么非要在最后：本函数**第 1 步** `_check_bundled_assets` 会把随包 addon
    # **无条件展开到 `runtime\dlss5\` 顶层**（它不认识开关），而 `launcher` 按开关做的
    # 停用**发生在本函数之前** ⇒ 展开动作把刚停用的 `renodx-dlss5*.addon64` /
    # `trans-zh.addon64` **又放回了顶层**，ReShade 下次启动照样加载它们。
    # 现场（2026-10-05 反馈者，Intel Arc、无 N 卡）：配置 `dlss5_addon_enabled=False`，
    # launch.log 里却是「停用 → 展开内置资产」的顺序，ReShade 最终实载 5 个 addon。
    # 放在最后还有一个好处：它同时兜住「别的步骤、以后的改动」又把 addon 放回的情况。
    if not getattr(config, "dlss5_addon_enabled", True):
        try:
            from . import launcher as _launcher

            parked = _launcher.set_component_addons(config, "dlss5", False)
            parked_names = list(parked.get("moved") or []) + [
                f"{name}（清掉多余副本）" for name in (parked.get("removed") or [])
            ]
            if parked_names:
                report.add("dlss5:addons_parked", True,
                           "DLSS5 已在启动页关闭 → 已把 DLSS5 相关 addon 移出底座目录（"
                           + "、".join(parked_names) + "），ReShade 下次不会加载它们",
                           fixed=True)
            else:
                report.add("dlss5:addons_parked", True,
                           "DLSS5 已在启动页关闭 → DLSS5 相关 addon 均已处于停用位置")
        except Exception as exc:  # noqa: BLE001
            report.add("dlss5:addons_parked", False,
                       f"DLSS5 已关闭，但按开关停用相关 addon 失败（ReShade 可能仍会加载它们）: {exc}",
                       manual=True)

    # ★★ **最后再清一次「已退役的旧 NR 引擎」**（2026-10-07 实测抓到，与上面那条同源）。
    #
    #    现场（本机）：`runtime\dlss5\` 里同时躺着
    #      `renodx-dlss5-4.7_汉化.addon64`（旧，已退役）与 `renodx-dlss5.addon64`（新版 7.0.0-rc8）。
    #    两者注册名**完全相同**（"DLSS 5 Neural Rendering"）⇒ ReShade 日志：
    #      `ERROR | Failed to register add-on … already registered!`
    #      `ERROR | Failed to load add-on … with error code 1114!`
    #      `ERROR | vtable::Hook(Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C)`
    #    ⇒ **NR 实际没生效**。这正是上游警告的「Never install two neural add-ons … it does
    #    nothing at all for the whole session」。
    #
    #    根因：本函数**第 1 步** `_check_bundled_assets` 会把随包 addon 无条件展开到顶层
    #    （`retire_stale_nr_addons()` 跑在它**之前** ⇒ 展开又把退役那份铺了回来；旧数据根的
    #    `assets\dlss5\manifest.json` 里还列着它）。**与上面"按开关归位"是同一个病**：
    #    展开会撤销前面的动作，所以兜底必须放在最后一步。
    try:
        from . import runtime_assets as _assets

        parked = _assets.retire_stale_nr_addons(config, log=log)
        if parked:
            report.add("dlss5:retired_nr_parked", True,
                       "已把退役的旧 NR 引擎移出底座目录（两个同名 neural addon 同装会让"
                       "**两个都不工作**）：" + "、".join(parked),
                       fixed=True)
    except Exception as exc:  # noqa: BLE001
        report.add("dlss5:retired_nr_parked", False,
                   f"清理退役 NR 引擎失败（ReShade 可能同时加载新旧两份，NR 会失效）: {exc}",
                   manual=True)

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
