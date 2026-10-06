"""Application configuration for EndfieldModController."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def _detect_project_root() -> Path:
    """数据根目录（config.json / runtime / library 的所在地）。

    **打包成 exe 时必须落在 exe 所在目录**：PyInstaller 会把 `__file__` 指向它自己的
    临时解压目录（`sys._MEIPASS`），若照旧用 `parents[1]`，用户的配置、Mod 库和日志
    会被写进临时目录，一退出就凭空消失。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


# 内置 XXMI 里 Launcher exe 的已知布局（先精确、后兜底）。
# 用户 2026-10-01：「xxmi 如果留空应该就找内置正常会放的地方，没有就下载」。
_BUILTIN_XXMI_EXE_NAMES = ("XXMI Launcher.exe", "XXMI-Launcher.exe")


def builtin_xxmi_launcher(builtin_runtime_root: Path) -> Path | None:
    """在内置运行环境里找 XXMI Launcher（找不到返回 None，调用方会去下载）。"""
    root = Path(builtin_runtime_root) / "XXMI"
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    for name in _BUILTIN_XXMI_EXE_NAMES:
        candidates.append(root / "Resources" / "Bin" / name)
        candidates.append(root / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # 兜底：XXMI 换过目录布局（Resources/Bin 之外），浅层扫两层即可，不做全盘扫描
    for name in _BUILTIN_XXMI_EXE_NAMES:
        for hit in sorted(root.glob(f"*/{name}")) + sorted(root.glob(f"*/*/{name}")):
            if hit.is_file():
                return hit
    return None


PROJECT_ROOT = _detect_project_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_DATA_ROOT = PROJECT_ROOT / "runtime"

# 主题白名单：**必须与 `frontend/src/store.js` 的 `THEMES` 完全一致**（2026-10-04 加）。
# 加载配置时会用它做校验 —— 两侧一旦不一致，用户选的主题就会被静默改回默认
# （历史上这里只认 dark/light，而前端有 6 套，于是琥珀/青蓝/紫罗兰/翡翠**存不住**）。
THEMES = ("light", "dark", "amber", "cyan", "violet", "emerald")


def resource_root() -> Path:
    """**只读资源根**（`web/`、随包 addon 等）—— 与数据根正好相反。

    打包后 `--add-data` 的东西被解压到 PyInstaller 临时目录（`sys._MEIPASS`），
    所以这里必须走 `_MEIPASS`；源码方式跑就是工作区根。
    这是全项目**唯一**一份实现，`app._resource_root()` 与 ReShade addon 的定位都
    复用它 —— 曾经因为两处各写一份，发布版里 addon 路径恒为 None（lesson
    2026-10-01：onefile 下 `__file__` 派生路径必须单独验）。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    return Path(__file__).resolve().parents[1]


def _safe_save(cfg: "AppConfig", path: Path) -> bool:
    """保存配置，失败只记不抛 —— 配置目录只读（如装在 Program Files）不该让程序起不来。"""
    try:
        cfg.save(path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _apply_gpu_defaults(cfg: "AppConfig") -> bool:
    """按**显卡支持范围**决定 DLSS5 的默认开关；只在"还没跟过当前这套范围"时执行一次。

    用户 2026-10-01 要求：「开启时检测机器，如果不是 50 系就默认关 dlss5，开启 dlss5 的
    时候弹窗说明拒绝」。理由：当时 DLSS5 首发只支持 RTX 50 系，40 系及更早在 NGX 层会被
    `0xBAD00001` 拒掉，默认开着只会让人以为坏了。

    **2026-10-05 范围扩大**（原话：「去掉所有对非 50 系的锁，换成对 a 卡和 10 系及以下和
    核显」）⇒ 判据变成"有 tensor core 的 RTX（20 系及以上）"。于是**老 40/30/20 系用户
    那份配置里的 `False` 是旧判据写进去的，必须替他们打开** —— 这就是第二个标记
    `dlss5_gpu_scope_applied` 的用途。

    ⚠️ **只动"旧判据不支持、新判据支持"那部分机器**（`sm < 120`）：
    * 50 系：旧判据本来就支持 ⇒ 现在的 `False` 只可能是**用户自己关的**，绝不覆盖；
    * A 卡 / 核显 / GTX：新判据也不支持 ⇒ 保持关闭；
    * 探测失败（读不到设备信息）：**一个字都不改、也不置标记**，下次启动再试
      —— 绝不因为一次读取失败就把用户的功能关掉。

    返回是否改动过配置（调用方据此决定要不要落盘）。读设备信息是毫秒级注册表查询且有
    进程内缓存，只在迁移那一次真正取值。
    """
    if getattr(cfg, "dlss5_gpu_scope_applied", False):
        return False
    sm: int | None = None
    detected = False
    try:
        from . import deviceinfo

        info = deviceinfo.collect()
        adapters = info.get("adapters")
        detected = adapters is not None
        # **从 adapters 自己算**，不去读 `collect()` 里的派生字段：判据只有一处
        # （`rtx_cards`），打桩测试与真实运行才会得出同一个结论。
        cards = deviceinfo.rtx_cards(adapters or [])
        sm = cards[-1][1] if cards else None
    except Exception:  # noqa: BLE001 - 探测失败不改配置（见 docstring）
        detected = False
    if not detected:
        return False
    cfg.dlss5_gpu_scope_applied = True
    cfg.dlss5_gpu_default_applied = True     # 旧标记一并置位，免得两条迁移互相打架
    if sm is None:
        cfg.dlss5_addon_enabled = False      # 新判据也不支持（A 卡 / 核显 / GTX 10/16）
    elif sm < 120:
        cfg.dlss5_addon_enabled = True       # 40/30/20 系：旧判据关掉的，现在替用户打开
    return True


def _quarantine_broken_config(path: Path) -> None:
    """把解析不了的 config.json 挪成带时间戳的副本，便于事后排查。

    2026-10-01 修：原先损坏分支只是"重新造一份默认配置"、既不落盘也不留证据，
    于是每次启动都重复解析失败，用户看到的是"配置莫名清空/改了不生效"。
    """
    try:
        if path.is_file():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path.replace(path.with_name(f"{path.name}.broken-{stamp}"))
    except OSError:
        pass


# ---------------------------------------------------------------
# 数据根自愈（2026-10-02 群反馈）
# ---------------------------------------------------------------
# 这些字段的值**本该是"相对数据根"的相对路径**，但历史上可能被写成绝对路径：
#   * `secondary_motion.import_pack` 装 sbm 时写的是 `str(tool.parent)`（绝对）；
#   * `autofill(deep=True)` 的全盘探测（XXMI / migoto / 官方启动器）返回的也是绝对路径；
#   * 前端在字段留空时会把 `detected_xxmi` 这类绝对路径回写进配置。
# 一旦用户把程序目录改名或搬走，这些"旧数据根的绝对路径"就全成了指向别处的死路径。
_DATA_ROOT_RELATIVE_FIELDS = (
    "library_dir",
    "runtime_dir",
    "mod_backup_dir",
    "builtin_runtime_dir",
    "staging_mods_dir",
    "dlss5_dir",
    "reshade_dll",
    "poser_dir",
    "dlss5_source_dir",
    "nvngx_assets_dir",
    "dependency_manifest",
    "secondary_motion_dir",
    "secondary_motion_dll",
    "xxmi_launcher",
    "migoto_loader",
    "official_launcher",
)
# 数据根内部的固定子目录名：绝对路径里一旦出现这些段，它后面那截就是"数据根内的布局"。
_DATA_ROOT_MARKERS = ("runtime", "library", "mod-backup", "assets")


def _data_root_of(config_path: Path) -> str:
    return str(Path(config_path).resolve().parent)


def _within(root: Path, path: Path) -> bool:
    """`path` 是否落在 `root` 里面（data_root 搬迁判据、目录创建护栏都要用）。"""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _data_root_split(value: Path) -> tuple[str, Path | None]:
    """把"某个数据根里的绝对路径"拆成（相对数据根的尾部, 疑似数据根本身）。

    例：`D:\\应用\\zmd_mod管理\\runtime\\secondary_motion`
        → (`runtime/secondary_motion`, `D:\\应用\\zmd_mod管理`)
    认不出布局特征时返回 `("", None)`。

    ⚠️ 取**最左边**那个标志段，不能取最右边的：数据根布局总是从第一个
    `runtime` / `library` / `mod-backup` / `assets` 段开始。取最右边会把
    `<数据根>\\library\\mod-backup` 拆成 (`mod-backup`, `<数据根>\\library`)，于是
    "Mod 备份目录"被误当成"旧数据根残留"改写掉，绕过"备份不许落在库内"的检查
    （单测 `test_backup_dir_inside_library_is_refused` 抓到过）。
    """
    parts = Path(value).parts
    for index, part in enumerate(parts):
        if part.lower() in _DATA_ROOT_MARKERS:
            tail = "/".join(parts[index:])
            prefix = Path(*parts[:index]) if index else None
            return tail, prefix
    return "", None


def _data_root_tail(value: Path) -> str:
    """只要"相对数据根的尾部"（目录创建护栏用）。"""
    return _data_root_split(value)[0]


def _is_empty_shell(prefix: Path, limit: int = 200) -> bool:
    """`prefix` 是不是"一棵只有空目录、一个文件都没有"的壳。

    用途：判断某个疑似旧数据根是不是**被历史版本重建出来的空目录树** ——
    那种壳里不可能有用户数据，认定成残留是安全的。里面有任何一个文件就返回 False。
    """
    stack = [Path(prefix)]
    seen = 0
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    seen += 1
                    if seen > limit:
                        return False        # 条目太多 = 像真目录，别当空壳
                    try:
                        if entry.is_file(follow_symlinks=False):
                            return False
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        return False
        except OSError:
            return False
    return True


def _relocate_stale_paths(cfg: "AppConfig", config_path: Path) -> list[str]:
    """把配置里"旧数据根的绝对路径"改写回相对路径，返回改动说明（空 = 没改）。

    三条判据，从可靠到保守：
    ① **有旧数据根记录**（`cfg.data_root`，上次运行的路径）且与当前不同 → 落在旧根之下
       的绝对路径一律跟着走。这条与"旧目录是否还在"无关：哪怕用户只是把目录复制了一份，
       也不会继续用旧那份。
    ② **没有记录**（老配置第一次升级上来）→ 只对一个**已经不存在的**（或已被历史版本
       重建成空壳的）、**长得像数据根布局**（含 `runtime` / `library` / `mod-backup` /
       `assets` 段）、**且那截疑似数据根本身也已经不在用了的**绝对路径动手。
       在用的目录一律不碰 —— 那可能是用户故意指定的外部 XXMI / 外部 Mod 目录，
       或者只是"用户配了、还没建出来"的路径。
    ③ 同上，但"疑似数据根本身"是个**只有空目录的空壳**（被历史版本重建出来的）也算残留。
       ⚠️ 判据必须保守：把"用户自定义、只是还没建出来"的目录（例如刚填的 Mod 库路径）
       当成残留改掉，会把配置改坏 —— 单测 `test_backup_dir_inside_library_is_refused`
       正是这么抓到的。
    """
    base = Path(config_path).resolve().parent
    base_key = os.path.normcase(str(base))
    recorded = str(getattr(cfg, "data_root", "") or "").strip()
    old_root: Path | None = None
    if recorded:
        try:
            old_root = Path(recorded).expanduser()
        except (OSError, ValueError):
            old_root = None
    if old_root is not None and os.path.normcase(str(old_root)) == base_key:
        old_root = None                      # 数据根没变，不需要迁移

    changed: list[str] = []
    for name in _DATA_ROOT_RELATIVE_FIELDS:
        raw = str(getattr(cfg, name, "") or "").strip()
        if not raw:
            continue
        value = Path(raw).expanduser()
        if not value.is_absolute():
            continue                     # 已经是相对路径 = 天然跟随数据根，不动
        relocated = ""
        if old_root is not None:
            try:
                relocated = value.resolve().relative_to(old_root.resolve()).as_posix()
            except (OSError, ValueError):
                relocated = ""
        if not relocated:
            try:
                exists = value.exists()
            except OSError:
                continue
            tail, prefix = _data_root_split(value)
            if not tail or prefix is None:
                continue
            try:
                if prefix.exists() and not _is_empty_shell(prefix):
                    continue         # 疑似数据根还在、而且里面还有东西 → 不是残留，别动
            except OSError:
                continue
            if exists and tail.split("/", 1)[0] not in ("runtime", "assets"):
                continue             # 已经存在的路径、又不是程序自己管的区域 → 保守不动
            relocated = tail
        if not relocated:
            continue
        setattr(cfg, name, relocated)
        changed.append(f"{name}: {raw} -> {relocated}")
    if changed:
        cfg.data_root = str(base)
    return changed


@dataclass
class AppConfig:
    # 默认值一律用**相对 PROJECT_ROOT 的相对路径**，这样配置被清空后一键启动
    # 也能直接指向工作区里的内嵌组件（见 autofill()）。
    library_dir: str = "library"
    runtime_dir: str = "runtime"
    # **Mod 备份仓**（用户 2026-10-01 要求）：「在根目录下放一个文件夹做 mod 备份，这个
    # 文件夹只增不减，只要见到新 mod，就打包 zip 放进去」。默认与 `library/` 平级、
    # 就放在数据根下，用户一眼能看到、能自己拷到别处；程序**只往里加，从不删**。
    mod_backup_dir: str = "mod-backup"
    # **Mod 备份总开关**（用户 2026-10-02 要求：「给 mod 备份做一个开关，默认开，关了就不备份」）。
    # 默认 True = 老行为（库里每见到一个新 Mod 就整份复制进备份仓）；关掉 = **一个字节都不复制**、
    # 连备份目录都不会创建；**已有的备份一个都不动**（"只增不减"这条红线不受开关影响）。
    mod_backup_enabled: bool = True
    # **依赖去重与内外优先级**（用户 2026-10-02 要求：「加个去重，在设置里加个内部
    # RabbitFX 优先，默认开，开的话如果还有外部 RabbitFX 就把外部的屏蔽掉，没开就把
    # 内部屏蔽掉、就算外部优先，如果外部有多个，按最后安装的优先」）。
    # True（默认）= 优先用控制器自己维护的 `<库>\_deps\<名字>` 那份，屏蔽你手动放进库的；
    # 关掉 = 反过来（外部优先）。无论哪种，同一依赖**只允许一份进 staging** ——
    # RabbitFX 作者在发布页写死过"多个实例会导致异常行为与游戏崩溃"。
    prefer_internal_dependencies: bool = True
    builtin_runtime_dir: str = "runtime/builtin"
    use_builtin_runtime: bool = True
    staging_mods_dir: str = "runtime/builtin/XXMI/EFMI/Mods"
    xxmi_launcher: str = ""
    migoto_loader: str = ""
    official_launcher: str = ""
    game_exe: str = ""
    reshade_dll: str = ""
    # xxmi_extra = 由 XXMI 注入 DLSS5 的 d3d12.dll（本方案唯一推荐方式）
    # none       = 不注入 ReShade/DLSS5，只跑服装 Mod
    reshade_injection: str = "xxmi_extra"
    # 内置 DLSS5 / 第一人称 ReShade 目录（d3d12.dll + ReShade.ini + 两个 addon + reshade-shaders）
    dlss5_dir: str = "runtime/dlss5"
    dlss5_injection: bool = True
    # 底座下两个插件可独立启停（同一 ReShade 底座，靠移动 addon 文件实现）
    dlss5_addon_enabled: bool = True          # RenoDX-DLSS5 神经渲染
    # ★ **DLSS5 神经渲染：启动就开**（2026-10-06 定为默认）。
    # 用户 2026-10-06 原话：「**nr 我不是改了吗，现在应该是不用管 hook**，另外超分开不开没关系」。
    # 此前默认是"启动前把 `NeuralUplift` 压成 0 → 等 `Camera controls installed.`
    # → 由 `nr_autostart` 替用户按一次 NR 键"。问题在于 **enhancer 只在第一人称启用
    # （`CameraFirstPerson=1`）时才去装相机 hook** ⇒ 不用第一人称的用户**永远等不到那句话**
    # ⇒ NR 永远打不开（反馈者那台：面板「成功NR帧 4」「超分: 请求ON|活动OFF」，
    # 日志里 `NeuralUplift=0` —— 他看到的其实是游戏自己的 DLSS 输出）。
    #   ① `CameraFirstPerson=1`：2026-10-05 实测定案"NR 启动就开与相机 hook **可以共存**"；
    #   ② `CameraFirstPerson=0`：根本没有 hook 要保护；
    # ⇒ 两种情况都该**启动就开**。
    start_dlss5_nr_immediately: bool = True

    # **（保守方案：仅当上面为 `False` 时才有意义）延迟到「相机 hook 装好之后」再打开**。
    # 为什么：NR 若抢在第一人称插件装相机 hook 之前激活，那个 hook 会 `error 8`
    # （分配 trampoline 失败）装不上 ⇒ 面板报「不支持相机控制」。压成 0 让相机 hook 先上，
    # 再由 `nr_autostart` 在游戏里替用户按一次 NR 快捷键补开 ⇒ 两者共存、用户零操作。
    # 见 `initialize._check_defer_nr_until_camera_hook` 与 `nr_autostart`。
    auto_enable_nr_after_camera_hook: bool = True
    firstperson_addon_enabled: bool = True    # Endfield Enhancer 第一人称
    # 是否把 EFMI 的 d3d11.dll（服装 Mod 引擎）也写进 XXMI 注入库
    # ⚠️ **语义已改（2026-10-02 用户实测后的要求）**：这个开关**不再**控制"要不要注入
    #    EFMI 的 `d3d11.dll`"，而是**"要不要加载皮肤 Mod"**。
    #    原因（用户原话）：①「**efmi 关了直接终末地拉不起来**」—— 注入库空了 XXMI 就认不了
    #    游戏；②「**我手动关了所有皮肤 mod 就可以进了**」—— 真正该关的是**皮肤**，不是注入。
    #    现在关掉它的效果：**EFMI 照常注入**（否则游戏起不来），但 staging 里**一个皮肤都不放**
    #    （`effective_selected_mods` 返回空 → `stage_and_prepare(selected_ids=[])` 清空 Mods）。
    #    字段名保留（老配置零迁移），但**别再按字面理解成"EFMI 注入开关"**。
    efmi_injection: bool = True
    # DLSS5 素材目录（缺文件时从这里补齐），留空则自动探测
    dlss5_source_dir: str = ""
    # 随包分发的运行库资产目录（assets/nvngx，内含 manifest.json 与压缩分卷）。
    # **一般不用改**：留空即自动探测（工作区 / exe 旁边 / PyInstaller 解包目录）。
    # 首次启动会把缺失的 nvngx_dlss*.dll 从这里展开到 dlss5_dir。
    nvngx_assets_dir: str = ""
    # 下载加速：auto=平时单连接，慢/抖时才临时上并发；always=强制并发；never=只用单连接。
    # 下载线路：auto=直连优先，不通才临时换镜像；direct=只直连；mirror=只用镜像。
    # 两者都是"按需临时启用、用完即放"，不常驻、不改系统（见 fastnet）。
    download_boost: str = "auto"
    download_line: str = "auto"
    # 下载用的代理（留空 = 自动：环境变量 → 系统代理 → 直连）。
    # 用户 2026-10-02 实测：VPN 只对浏览器生效时，本程序是**直连**，于是出现
    # "浏览器秒下、程序慢得动不了" ⇒ 让他把代理地址填这儿（如 http://127.0.0.1:7890）。
    download_proxy: str = ""
    # 防多开：检测到终末地已在运行时**阻止**再启动一个实例。
    # 两个游戏实例同时被注入，Mod/ReShade 会互相抢资源，表现为随机崩溃或 Mod 不生效。
    prevent_game_multi_instance: bool = True
    # 工具自身单实例：已有控制器在跑时，第二个实例直接提示并退出（避免两个进程同时改
    # 注入库/staging 造成互相踩踏）。关掉它就能开多个窗口。
    single_instance: bool = True
    # 新手引导是否已完成/已跳过（用户 2026-10-01 要求把"首次使用提示"做成分步引导）
    onboarding_done: bool = False
    # 是否把内置的新版 DLSS 运行库（nvngx_dlss / nvngx_dlssnr）部署进游戏目录。
    # 默认 False：替换游戏原版的 nvngx_dlss.dll 有让游戏起不来的风险，而 DLSS5 的 NR
    # 签名运行时本来就不在游戏目录（由 addon 从 `<数据根>\runtime\dlss5` 加载），
    # 所以默认不去动游戏目录；打开后才会在大小不符时替换/补齐并锁存 `*.game_original`。
    deploy_new_nvngx: bool = False
    # 乳摇/次级运动管理器（第三方 SecondaryMotion 工具）所在目录，留空则自动探测
    secondary_motion_dir: str = ""
    # 启动前自动补齐乳摇插件的注入（两个 proxy + plugin\sbm.dll）
    secondary_motion_injection: bool = True
    # 【可选】改用「经 XXMI 注入 sbm.dll」的方式时，sbm.dll 的部署路径。
    # 留空 = 用 proxy 替换方式（老路子，会和 ReShade/EFMI 抢 D3D 链路）；
    # 填了短路径（如 D:\\zmdmod\\SBM\\sbm.dll）= 由 XXMI 注入，游戏目录不换任何系统 DLL。
    secondary_motion_dll: str = ""
    # Endfield Poser（摆姿 / MMD 播放插件）安装包目录，留空 = <主路径>/runtime/poser。
    # 包本体不随我们分发（上游 AGPL-3.0），由依赖页/一键启动从官方 Release 下载到这里。
    poser_dir: str = ""
    # 启动前自动补齐 Poser 的注入（d3dcompiler_47 proxy + plugin\poser.dll）。
    # 默认 True —— 与 DLSS5 / EFMI / 乳摇三个组件一致：装不上就报可读原因，不静默。
    poser_injection: bool = True

    theme: str = "light"
    last_tab: str = "library"
    inject_reshade_ui: bool = True
    # **「整合 Mod 快捷键」总开关**（2026-10-01 落地，取代旧的"面板还没做好"状态）。
    # True = 把每个 Mod 的 `[Key*]` 统一改写成 `VK_F24`，操作改到游戏内的统一面板
    # （自研 ReShade addon，按 Home 打开）—— 用户原话：「开了要锁 mod 快捷键，注入 reshade」。
    # **默认 True**（2026-10-01 用户要求：「把快捷键整合设为默认开启」）：零配置用户装完
    # 直接就有统一面板，不必先去设置页找开关。
    # ⚠ 打开后**面板是必须存在的**：`launcher.resolve_hotkey_takeover` 会先确认面板真的
    #   躺在 ReShade 会读的目录、且 ReShade 注入可用，否则**拒绝锁键**（2026-10-01 的事故
    #   就是"键锁死了、面板却不存在"，见 lesson `0muovz4ap`）—— 所以"默认开"不会造成
    #   任何"键没了、面板也没有"的后果，最多是"开关看着是开的、键还没锁"。
    hotkey_takeover: bool = True
    # **默认值迁移标记**：`hotkey_takeover` 从 False 改成 True 时，老配置文件里存的是显式的
    # `false`，改默认值对它们不生效 → 所以做**一次性**迁移（见 `load()`）。这个字段为 True
    # 表示"这份配置已经跟过新默认"，之后用户自己关掉不会再被改回来。
    hotkey_default_applied: bool = False
    # **按显卡代次决定 DLSS5 默认开关的迁移标记**（2026-10-01 用户要求：「开启时检测机器，
    # 如果不是 50 系就默认关 dlss5，开启 dlss5 的时候弹窗说明拒绝」）。
    # 为 True = 这份配置已经按机器代次定过默认值，之后用户手动设的不会被改回来。
    dlss5_gpu_default_applied: bool = False
    # **支持范围扩大后的第二次迁移标记**（2026-10-05 用户要求：「去掉所有对非 50 系的锁，
    # 换成对 a 卡和 10 系及以下和核显」）。
    # 旧判据"只支持 RTX 50 系"曾把 40/30/20 系机器的开关**写成 False** —— 光改判据不够，
    # 那些配置里的 False 得被重新打开，否则老 40 系用户升级后依然用不了 DLSS5。
    # 为 True = 已按新范围处理过；之后用户自己关掉的不再改回来。
    dlss5_gpu_scope_applied: bool = False
    # **面板的中文字体**：ReShade 默认字体（ProggyClean）没有中文字形，面板里的中文含义
    # 会显示成方块。True（默认）= 打开「整合 Mod 快捷键」时，若 `ReShade.ini` 的
    # `[STYLE] Font=` 还是空的，就自动指向系统中文字体（`msyh.ttc` 等，写前备份）。
    # ImGui 1.92（ReShade 6.8 用的那版）是**动态字体**，字体文件里有字就能画出来。
    reshade_panel_font: bool = True
    # **强行关闭角色 Mod 互斥**（用户 2026-10-01 要求：「设置…拨钮…强行关闭角色 mod 互斥，
    # 这个可以禁用互斥功能，介绍写便于部分同角色但不冲突的 mod」）。
    # True = 勾选时不再自动取消同角色的其它 Mod，控制器生成时也不再按角色去重 ——
    # 用于"同角色但资源不冲突"的搭配（例如一个改服装、一个只改贴图）。
    # 默认 False：同角色两个 Mod 同时生效**常会崩游戏**，只在确认不冲突时才开。
    allow_same_character_mods: bool = False
    # **乳摇（SBM）角色参数的拉取来源**（用户 2026-10-01 要求：「在作者改之前，mod 管理器
    # 自行拉取新的参数文件」）。留空 = 上游仓库默认（`Sp1cHless/...Secondary-bodyphysics@main`）；
    # 也可以填 `owner/repo` 或 `owner/repo@分支`（例如你自己 fork 的仓库 —— 在自己的仓库里
    # 改角色数据、push 即生效，不用等我们发版）。只**补缺失的角色**，不覆盖你调过的数值。
    sbm_data_source: str = ""
    # **游戏自带 DLSS 时，自动停用「喂帧组件」（`dlss5-feed.addon64`）**（用户 2026-10-01 要求，
    # 原话：「你把 2 做了，然后在设置留个这个开关，默认开启自动停用」）。
    # 理由：`dlss5-feed` 自己的日志写着「this game runs NVIDIA Streamline … it has DLSS of its
    # own … This project is for games WITHOUT DLSS — remove dlss5-feed.addon64」——
    # 自带 DLSS 的游戏上它多余，且会与游戏自己的 DLSS（以及 OptiScaler 这类第三方 NGX
    # 注入器）抢同一条 NGX 链路。停用 = 把文件移进 `runtime\dlss5\_disabled\`（**可逆**：
    # 关掉这个开关，下次自检会自动放回）。默认 True。
    #
    # ⚠️ **判据是「文件 + 运行时证据」两条**（2026-10-03 修）：
    # 只看游戏目录里有没有 `sl.interposer.dll` / `nvngx_dlss.dll` **不够** ——
    # XXMI/EFMI 会强制 `-force_d3d11`，那时游戏**根本建不出 DLSS 特性**
    # （`Player.log` 里是 `Forcing GfxDevice: Direct3D 11`），喂帧组件反而是 DLSS5 的
    # **必需**环节，停掉它等于把 DLSS5 彻底关掉。所以现在还要 `detect_render_api()` 判定
    # **运行时确实跑在 D3D12**（读的是游戏自己的 Player.log）才停用；d3d11 / unknown 一律
    # **保持启用**，并且会把被误停用的自动放回。
    auto_disable_feed_on_native_dlss: bool = True
    dependency_manifest: str = "dependencies.json"
    launch_extra_args: list[str] = field(default_factory=list)
    # ⚠️ 2026-10-03 回滚开关：写 `runtime\reshade\ReShade.ini` 时用**绝对路径**
    # （= 我改动之前的写法）。用户实测"开 DLSS5 或第一人称就崩"，需要一次判定
    # 是不是"我把绝对路径改成相对路径"造成的；默认 True = 回到改动前。
    reshade_use_absolute_paths: bool = True
    # ⚠️ **2026-10-04 定案：这条 `d3d11.dll` 必须列，而且必须排在 `d3d12.dll` 之后**。
    #
    # 机理（两个用户现场 + XXMI 自己的日志一起定出来的）：
    #   * XXMI 的注入列表 = **它自己的 EFMI loader** + 我们写的 `extra_libraries`；
    #   * 但只要我们的列表里**已经有** `d3d11.dll`，它就**不再自己补**那一份 ⇒ **顺序完全由我们决定**；
    #   * 不列它 ⇒ XXMI 把自带那份**补到最前面** ⇒ 变成「EFMI 先、ReShade 后」——
    #     **顺序反了游戏起不来**（用户 2026-10-04 实测：改动前 122 秒能玩、改动后 25 秒就退；
    #     这与 2026-09-27 那条"ReShade 先注入才修好崩溃"是同一条机理）；
    #   * 列**错的那一份**（用户装外部 XXMI 时列了内置那份）⇒ XXMI 去重不掉
    #     ⇒ `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ 第二次注入必然失败
    #     ⇒ 「注入额外库 … 失败：DLL 注入失败！」**并中断整个启动**（2026-10-04 第二个用户）。
    #
    # ⇒ 所以：**列，但只列"当前生效 XXMI 自己的那份 loader"** —— 由 `launcher.active_efmi_loader()`
    #   从 XXMI 配置的 `Importers.<active>.Importer.importer_folder` 解析出来。
    extra_libraries_include_efmi_dll: bool = True
    # 这条策略改过两版（True → False → True），老配置里躺着显式值 ⇒ 需要**一次性迁移**到新策略
    # （同 `hotkey_default_applied` 的做法：迁过一次就不再动用户后来的选择）。
    efmi_dll_order_applied: bool = False
    # **热重载**（2026-10-04 用户要求）找游戏窗口用的标题关键字（逗号分隔；留空 = 用默认那组）。
    # 终末地的窗口标题随语言/启动方式变化，所以做成可配置 + 一组宽松默认值；
    # 命中不了就会明确报"没找到游戏窗口"，而不是静默什么都不做。
    game_window_keywords: str = ""
    # ⚠️ **一键启动前自动净化游戏目录**（2026-10-04 用户要求，**默认开**）。
    #
    # 原话：「在设置做个开关，一键还原终末地清除所有第三方注入，**默认开**，
    # 开了之后**不管是不是管理器注入的，都要去掉（要备份）**」。
    #
    # 语义：只要游戏目录里出现**原版不会有的**注入痕迹（proxy DLL、`plugin\*.dll`、
    # 别的工具留下的 `d3dx.ini` / `ShaderFixes\` / OptiScaler / ReShade 残留…），
    # 一律**先备份再移走**、并把系统原版补回去；随后自检按**当前开关**把我们自己
    # 要用的那一份重新铺好 —— 于是"清干净"与"功能还在"不再互斥。
    # 备份落在 `runtime\game_backup\<时间戳>\`，随时可一键还原。默认 True。
    clear_game_injections_on_launch: bool = True
    # ⚠️ **自动把游戏目录 / 数据根加进 Windows Defender 白名单**（2026-10-04 用户要求，
    # **默认开**：原话是「3 默认开，在设置留个开关」）。
    #
    # 为什么需要：安全软件把文件当威胁隔离掉，是这个项目**已知的问题类** ——
    # 表现是「明明修好了，第二天又缺文件 / 玩着玩着游戏起不来了」；而这次反馈者的退出码正是
    # `0xC0000135 STATUS_DLL_NOT_FOUND`（有 DLL 没加载起来），"杀毒隔离"是最吻合的机制之一。
    # 与其每次弹窗让用户自己去点，不如默认替他加好 —— 用户一贯的判据是
    # 「**能自动补齐的就别让他手动**」。
    #
    # ⚠️ 代价（用户已知情并选择默认开）：这些目录下的文件不再被 Defender 实时扫描。
    # ⚠️ **对 360 / 火绒这类第三方杀毒无效** —— 它们没有通用的命令行排除接口，
    #    那种情况只能继续用弹窗引导用户手动加白名单。
    defender_exclusions_enabled: bool = True
    selected_mods: list[str] = field(default_factory=list)
    auto_update_dependencies: bool = False
    # 默认为 True：XXMI Launcher 的 exe 要求管理员权限（非管理员启动会直接报
    # WinError 740），而用户要的是「零配置启动即用」，所以默认就按管理员处理。
    require_admin: bool = True
    # **上次运行时的数据根**（= config.json 所在目录；打包后就是 exe 所在目录）。
    # 用途（2026-10-02 群反馈修）：把程序目录**改名 / 搬到别的路径**之后，配置里那些
    # "旧数据根的绝对路径"会失效 —— 界面一直显示旧目录、灰色的又改不了，还会在旧位置
    # 重建出一整条空目录树（反馈原话：「我把主路径改了文件名，然后他没识别出来」
    # 「又重新给我新建了一个空白文件」）。加载时拿它跟当前数据根一比，就能把这些残留
    # 路径**自动改写回相对路径**（见 `_relocate_stale_paths`）—— 用户什么都不用做。
    data_root: str = ""

    _config_path: str = field(default="", init=False, repr=False)
    # 最近一次加载时被自动纠正的路径字段（"字段: 旧值 -> 新值"），供日志留痕。
    _relocated: list[str] = field(default_factory=list, init=False, repr=False)

    # ---------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        # 兼容 str 入参：这里的类型标注是 Path，但传字符串时原先会直接
        # AttributeError（str 没有 `.is_file()`）—— 单元测试都传 Path 所以一直
        # 没暴露（2026-10-01 实测：`EndfieldModControllerApi("...config.json")`）。
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not path.is_file():
            cfg = cls()
            cfg._config_path = str(path)
            cfg.data_root = _data_root_of(path)   # 记下这一版的数据根，下次搬家才对得上
            cfg.hotkey_default_applied = True   # 新配置天然就是新默认，无需迁移
            _apply_gpu_defaults(cfg)            # 按显卡支持范围定 DLSS5 默认（读注册表，毫秒级）
            cfg.autofill(deep=False)   # 只填内嵌路径（毫秒级）；全盘探测交给后台预热
            _safe_save(cfg, path)
            return cfg
        try:
            # ⚠️ **编码必须容错**（2026-10-04 修）：Windows 用户用记事本「另存为 ANSI」
            # （GBK）改 config.json 是常见操作，而 `read_text(encoding="utf-8")` 抛的是
            # `UnicodeDecodeError` —— **既不是 OSError 也不是 JSONDecodeError**，于是下面
            # 那条"隔离 + 重建默认配置"的自愈分支**完全走不到**，异常直接冒到
            # `AppConfig.load()` 外面（`api.py` 构造 API 时没有 try）⇒ **程序起不来**。
            # 编码容错的唯一实现在 `fsutil.read_text_tolerant`（core.read_text 也转调它）。
            from . import fsutil

            data = json.loads(fsutil.read_text_tolerant(path))
        except (OSError, ValueError):
            _quarantine_broken_config(path)
            cfg = cls()
            cfg._config_path = str(path)
            cfg.data_root = _data_root_of(path)
            cfg.hotkey_default_applied = True
            _apply_gpu_defaults(cfg)
            cfg.autofill(deep=False)   # 只填内嵌路径（毫秒级）；全盘探测交给后台预热
            _safe_save(cfg, path)
            return cfg
        known = {f.name for f in cls.__dataclass_fields__.values() if not f.name.startswith("_")}  # type: ignore[attr-defined]
        # 合法 JSON 也可能是数组/字符串/数字，`data.items()` 会直接 AttributeError
        # 把整个启动搞崩（2026-10-01 修：实测 json.loads("[1,2]") 成功但 .items() 抛错）。
        if not isinstance(data, dict):
            _quarantine_broken_config(path)
            data = {}
        filtered = {k: v for k, v in data.items() if k in known}
        cfg = cls(**filtered)
        cfg._config_path = str(path)
        # ⚠️ 主题白名单**必须与前端一致**（2026-10-04 修）：前端 `store.js` 的 `THEMES`
        # 有 6 套（light/dark/amber/cyan/violet/emerald），而这里只认 dark/light ⇒
        # 用户选「琥珀/青蓝/紫罗兰/翡翠」存进 config.json 后，**下次启动被静默改回 light**
        # （设置页下拉显示「浅色」而界面还是琥珀色，两处还对不上）。
        if cfg.theme not in THEMES:
            cfg.theme = "light"
        # **一次性默认值迁移**（2026-10-01 用户要求「把快捷键整合设为默认开启」）：
        # 老配置里躺着显式的 `"hotkey_takeover": false`，光改 dataclass 默认值对它无效 ——
        # 所以只要这份配置**没跟过新默认**（`hotkey_default_applied` 不为 True），就把它设成
        # True 并落盘标记。用户之后自己关掉开关，标记已经是 True，下次不会再被改回来。
        migrated = False
        if not cfg.hotkey_default_applied:
            cfg.hotkey_takeover = True
            cfg.hotkey_default_applied = True
            migrated = True
        # 同族的第二次一次性默认值迁移（2026-10-04）：`extra_libraries_include_efmi_dll`
        # 的策略定案为"**列，但只列当前生效 XXMI 自己那份 loader**"（理由见字段定义处）。
        # 这条中间被改成过 False（那会让 XXMI 把自带那份补到最前面 ⇒ EFMI 先、ReShade 后
        # ⇒ **游戏起不来**，用户实测 122 秒 → 25 秒），所以老配置必须迁回 True。
        if not cfg.efmi_dll_order_applied:
            cfg.extra_libraries_include_efmi_dll = True
            cfg.efmi_dll_order_applied = True
            migrated = True
        # 同一次加载里顺手按显卡代次定 DLSS5 的默认（非 50 系 → 关）
        if _apply_gpu_defaults(cfg):
            migrated = True
        # **数据根自愈**（2026-10-02 群反馈）：程序目录被改名/搬走后，配置里残留的
        # "旧数据根绝对路径"会让设置页一直显示旧目录、还会在旧位置重建空目录树
        # （见 `_relocate_stale_paths` 的注释）。必须排在 autofill 之前 —— 那些路径
        # 先变回相对路径，autofill 的"是否内置 staging"判断才会得出正确结论。
        relocated = _relocate_stale_paths(cfg, path)
        if relocated:
            cfg._relocated = relocated
            migrated = True
        base_now = _data_root_of(path)
        if str(cfg.data_root or "").strip() != base_now:
            cfg.data_root = base_now
            migrated = True
        # 「留空 = 自动」的字段被清空过 → 补回默认值（空串会被解析成数据根本身）
        if cfg.normalize_blank_paths():
            migrated = True
        # 关键路径留空时按工作区内的内嵌组件补齐并落盘：
        # 这样把 config.json 整个删掉，一键启动依然能自建出完整可用配置。
        # **必须 deep=False**：默认的 deep=True 会扫遍所有盘符找 XXMI/乳摇/官方启动器/
        # migoto loader —— 实测这一行让"config 已存在"的加载路径多花 6.93 秒，
        # 而从零分支（上面那两处）反而是快的，正好造成"从零启动慢、之后快"的错觉
        # （2026-10-01 实测定位：窗口要等到 9.8 秒才可见）。缺的字段交给后台预热补。
        if cfg.autofill(deep=False) or migrated:
            try:
                cfg.save(path)
            except OSError:
                pass
        return cfg

    def autofill(self, *, deep: bool = True) -> list[str]:
        """把留空的关键路径按**内嵌组件**补齐（优先相对路径），返回被填的字段名。

        `deep=False` 时**只查内嵌/相对路径**（毫秒级），跳过所有全盘扫描 ——
        启动时用它，界面才不会被"扫遍所有盘符找 XXMI/migoto"拖住
        （2026-10-01 改：加载页要尽早出现）。全盘探测由后台预热线程补做。
        """
        filled: list[str] = []

        # ① XXMI Launcher：优先工作区内嵌那份（写相对路径）
        if not self.xxmi_launcher.strip():
            builtin = self.builtin_runtime_path / "XXMI" / "Resources" / "Bin" / "XXMI Launcher.exe"
            if builtin.is_file():
                self.xxmi_launcher = "runtime/builtin/XXMI/Resources/Bin/XXMI Launcher.exe"
                filled.append("xxmi_launcher")
            elif deep:
                guess = auto_detect_xxmi()
                if guess:
                    self.xxmi_launcher = guess
                    filled.append("xxmi_launcher")

        # ①b Staging Mods 跟着「当前用的那份 XXMI」走：用户指定了**外部** XXMI 时，他的
        #     Mod 全在那份里，再把 Mod stage 到内置 `EFMI\Mods` 等于白装
        #     （2026-09-30 issue #4：用户问"怎么用我自己之前那份 xxmi"）。
        #     只在当前值为空、或还是内置默认值(相对路径)时纠正；用户自己填的路径一律不动。
        if not self.staging_mods_dir.strip() or self._is_builtin_staging():
            external_mods = self._external_efmi_mods()
            if external_mods is not None:
                self.staging_mods_dir = str(external_mods)
                filled.append("staging_mods_dir")

        # ② 乳摇工具：优先工作区内嵌那份
        if not self.secondary_motion_dir.strip():
            builtin_sbm = self.runtime_path / "secondary_motion" / "SecondaryMotion" / "SecondaryMotion.Manager.exe"
            if builtin_sbm.is_file():
                self.secondary_motion_dir = "runtime/secondary_motion"
                filled.append("secondary_motion_dir")
            elif deep:
                guess = auto_detect_secondary_motion()
                if guess:
                    self.secondary_motion_dir = guess
                    filled.append("secondary_motion_dir")

        # ③ Endfield Poser 安装包：默认落在 runtime/poser（由依赖页/一键启动下载）
        if not self.poser_dir.strip():
            if (self.runtime_path / "poser" / "tools" / "deploy.ps1").is_file():
                self.poser_dir = "runtime/poser"
                filled.append("poser_dir")

        # ④ DLSS5 底座 DLL：永远指向内嵌 dlss5
        if not self.reshade_dll.strip():
            candidate = self.dlss5_path / "d3d12.dll"
            if candidate.is_file():
                self.reshade_dll = "runtime/dlss5/d3d12.dll"
                filled.append("reshade_dll")

        # ⑤ 官方启动器 / 3DMigoto loader：自动探测（搜不到就留空，由调用方提示手填）
        if deep and not self.official_launcher.strip():
            guess = auto_detect_official_launcher()
            if guess:
                self.official_launcher = guess
                filled.append("official_launcher")
        if deep and not self.migoto_loader.strip():
            guess = auto_detect_migoto_loader()
            if guess:
                self.migoto_loader = guess
                filled.append("migoto_loader")
        return filled

    def save(self, path: Path | None = None) -> None:
        if path is None:
            if not self._config_path:
                raise ValueError(
                    "AppConfig.save() called without a path and without a loaded config file. "
                    "Pass an explicit path or use AppConfig.load() first."
                )
            path = Path(self._config_path)
        else:
            path = Path(path)
        self._config_path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        # **原子写 + 退避重试**：直接 write_text 覆盖时，写到一半被杀/断电会留下半截 JSON，
        # 下次启动解析失败 → 配置静默重置（"配置莫名清空"就是这么来的）。
        #
        # ⚠️ 这套"临时文件 + 每次换名 + 6 次退避重试"原先只在本方法里实现（2026-10-03 用户
        # 实测 `[WinError 2] 'config.json.tmp-10116' -> 'config.json'` —— 杀软实时扫描把刚写出的
        # 临时文件吃掉），而 activation 的清单、MC_Probe.ini、注入库写入等**同样会被杀软吃**。
        # 2026-10-04 把它下沉成 `fsutil.write_text_atomic`（唯一实现），这里复用它 ——
        # 一处修好，全项目的原子写都跟着受益。
        from . import fsutil

        fsutil.write_text_atomic(path, payload, newline="\n")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if not k.startswith("_")}

    # ---------------------------------------------------------------
    # Path helpers
    # ---------------------------------------------------------------
    @property
    def base_dir(self) -> Path:
        if self._config_path:
            return Path(self._config_path).resolve().parent
        return PROJECT_ROOT

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.base_dir / path).resolve()

    @property
    def library_path(self) -> Path:
        return self.resolve_path(self.library_dir)

    @property
    def effective_selected_mods(self) -> list[str]:
        """**真正要 stage 的 Mod**：所有"游戏里会加载什么"的入口都必须走这里。

        * 「皮肤 Mod」总开关（`efmi_injection`）关掉时 → **一律空**。
          注意这**不是**"不注入 EFMI"（那会让终末地直接起不来，用户 2026-10-02 实测：
          「efmi 关了直接终末地拉不起来」），而是"一个皮肤都不加载"—— 注入照旧、
          `Mods` 目录清空。用户原话：「**我手动关了所有皮肤 mod 就可以进了**」。
        * 开关开着时 = 用户在库里勾选的那些。

        为什么要收成一个入口：这个项目里决定 staging 的调用点有 8 处（一键启动、生成控制器、
        自检补齐、检查修复…），各写各的就会出现"某个入口把皮肤又装回去了"（多入口一致性，
        2026-10-01 issue #6 的教训）。
        """
        if not self.efmi_injection:
            return []
        return list(self.selected_mods or [])

    @property
    def runtime_path(self) -> Path:
        return self.resolve_path(self.runtime_dir)

    @property
    def builtin_runtime_path(self) -> Path:
        return self.resolve_path(self.builtin_runtime_dir)

    @property
    def staging_mods_path(self) -> Path:
        return self.resolve_path(self.staging_mods_dir)

    @property
    def dependency_manifest_path(self) -> Path:
        return self.resolve_path(self.dependency_manifest)

    @property
    def xxmi_launcher_path(self) -> Path | None:
        """XXMI Launcher 的 exe。

        用户 2026-10-01 反馈：「显示 xxmi 找不到卡死，**xxmi 如果留空应该就找内置正常会
        放的地方，没有就下载**」。所以这里不再"留空就返回 None 把锅丢给界面"，而是：

        ① 填了且文件在 → 用它；
        ② 填了但文件不在了（被删/被整合包挪走）→ 也走内置回落，而不是直接报"找不到"；
        ③ 留空 → 在内置运行环境里按已知布局找（`XXMI\\Resources\\Bin\\XXMI Launcher.exe`
           等）；
        ④ 都没有 → 返回 None，调用方（`launcher.ensure_xxmi_available`）据此**自动下载**
           内置 XXMI。
        """
        if self.xxmi_launcher:
            resolved = self.resolve_path(self.xxmi_launcher)
            if resolved.is_file():
                return resolved
        return builtin_xxmi_launcher(self.builtin_runtime_path)

    @property
    def migoto_loader_path(self) -> Path | None:
        return self.resolve_path(self.migoto_loader) if self.migoto_loader else None

    @property
    def official_launcher_path(self) -> Path | None:
        return self.resolve_path(self.official_launcher) if self.official_launcher else None

    @property
    def game_exe_path(self) -> Path | None:
        return self.resolve_path(self.game_exe) if self.game_exe else None

    @property
    def reshade_dll_path(self) -> Path | None:
        """DLSS5 的 ReShade 底座（d3d12.dll）。留空时回退到内置 dlss5 目录。"""
        if self.reshade_dll:
            return self.resolve_path(self.reshade_dll)
        candidate = self.dlss5_dll_path
        return candidate if candidate.is_file() else None

    @property
    def dlss5_path(self) -> Path:
        return self.resolve_path(self.dlss5_dir)

    @property
    def dlss5_dll_path(self) -> Path:
        return self.dlss5_path / "d3d12.dll"

    @property
    def dlss5_ini_path(self) -> Path:
        return self.dlss5_path / "ReShade.ini"

    @property
    def dlss5_enhancer_addon_path(self) -> Path:
        return self.dlss5_path / "renodx-endfield-enhancer.addon64"

    @property
    def efmi_dir(self) -> Path | None:
        """EFMI 目录：优先从 XXMI Launcher 路径上溯，再回退到内置 runtime。

        ⚠️ **判据是"EFMI 目录在不在"，而不是"`EFMI\\d3d11.dll` 在不在"**（2026-10-02 修，
        由反馈者截图定位）：以前这里要求 `<XXMI>\\EFMI\\d3d11.dll` 已经存在才算找到 EFMI，
        于是"刚解压好、还没被 XXMI 部署过"的内置 XXMI（dll 此时只在
        `Resources\\Packages\\XXMI\\d3d11.dll`）会被判成**根本没有 EFMI** →
        `efmi_dll_path` 返回 None → 每次启动都弹
        「发现缺失文件：EFMI d3d11.dll（注入用）是否自动修复?」，而点"继续"也修不好
        （判据是死结：修复链里没有任何一步能把它变"存在"），EFMI 的 d3d11.dll 也永远
        不会被写进注入库。放宽之后，`efmi_dll_path` 里那段"回退到包目录"的逻辑才真正
        生效 —— 那段回退 2026-09-29 就写了，却因为进不来而**永远走不到**。
        """
        candidates: list[Path] = []
        launcher = self.xxmi_launcher_path
        if launcher is not None:
            candidates.extend(launcher.parents)
        if self.use_builtin_runtime:
            candidates.append(self.builtin_runtime_path / "XXMI")
        for parent in candidates:
            efmi = parent / "EFMI"
            if ((efmi / "d3d11.dll").is_file()
                    or (efmi / "Core").is_dir()
                    or (efmi / "Mods").is_dir()):
                return efmi
        return None

    def _is_builtin_staging(self) -> bool:
        """当前 staging 目录是不是"内置那份"（空值或落在内置 runtime 下都算）。"""
        value = self.staging_mods_dir.strip()
        if not value:
            return True
        try:
            self.resolve_path(value).relative_to(self.builtin_runtime_path)
            return True
        except (OSError, ValueError):
            return False

    def _external_efmi_mods(self) -> Path | None:
        """用户**自己那份** XXMI 的 `EFMI\\Mods`；内置那份不算"外部"，找不到返回 None。

        刻意不走 `efmi_dir`：那个属性内置优先兜底，会把"内置 EFMI"也返回回来，
        而这里要回答的是"用户到底有没有在用一份外部 XXMI"。
        """
        launcher = self.xxmi_launcher_path
        if launcher is None:
            return None
        for parent in launcher.parents:
            try:
                parent.relative_to(self.builtin_runtime_path)
                continue                      # 内置那份不算外部
            except ValueError:
                pass
            if (parent / "EFMI" / "d3d11.dll").is_file():
                return parent / "EFMI" / "Mods"
        return None

    @property
    def efmi_dll_path(self) -> Path | None:
        """EFMI 注入用的 `d3d11.dll`。

        XXMI 装好后这个 dll 可能在**两处**：已经部署过的 `EFMI/d3d11.dll`，或者
        包目录 `Resources/Packages/XXMI/d3d11.dll`（还没部署到 EFMI/ 时就只有这里）。
        实测空环境（2026-09-29）**只有后者**，而这里原先只找前者 → 一键启动报
        「注入失败」。
        """
        efmi = self.efmi_dir
        if efmi is None:
            return None
        direct = efmi / "d3d11.dll"
        if direct.is_file():
            return direct
        # 回退：XXMI 自带的包目录（efmi 是 <XXMI>/EFMI，所以 parent 就是 <XXMI>）
        for rel in ("Resources/Packages/XXMI/d3d11.dll", "Resources/Packages/EFMI/d3d11.dll"):
            candidate = efmi.parent / rel
            if candidate.is_file():
                return candidate
        return direct            # 两处都没有 → 返回原路径，供上层给出可读的报错

    # ---------------------------------------------------------------
    # SecondaryMotion（乳摇管理器）
    # ---------------------------------------------------------------
    @property
    def secondary_motion_root(self) -> Path | None:
        value = self.secondary_motion_dir or auto_detect_secondary_motion()
        if not value:
            return None
        path = self.resolve_path(value)
        return path if path.is_dir() else None

    @property
    def secondary_motion_exe(self) -> Path | None:
        root = self.secondary_motion_root
        if root is None:
            return None
        for candidate in (
            root / "SecondaryMotion" / "SecondaryMotion.Manager.exe",
            root / "SecondaryMotion.Manager.exe",
        ):
            if candidate.is_file():
                return candidate
        return None

    @property
    def secondary_motion_tool_dir(self) -> Path | None:
        exe = self.secondary_motion_exe
        return exe.parent if exe is not None else None

    # ---------------------------------------------------------------
    # Endfield Poser（摆姿 / MMD 播放插件）
    # ---------------------------------------------------------------
    @property
    def poser_path(self) -> Path:
        """Poser 安装包目录：默认 `<主路径>/runtime/poser`。

        包本体不随我们分发（上游 AGPL-3.0），由依赖页 / 一键启动从官方 Release
        下载到这里；它自己的安装向导再把这几个文件复制进游戏目录。
        """
        value = self.poser_dir.strip()
        return self.resolve_path(value) if value else self.runtime_path / "poser"

    @property
    def reshade_runtime_path(self) -> Path:
        return self.runtime_path / "reshade"

    @property
    def user_ini_path(self) -> Path:
        return self.staging_mods_path.parent / "d3dx_user.ini"

    @property
    def managed_mods_path(self) -> Path:
        return self.staging_mods_path / "EndfieldModControllerManaged"

    @property
    def controller_dir(self) -> Path:
        return self.staging_mods_path / "MC_Controller"

    def store_path(self, value: str | Path) -> str:
        """把"程序自己算出来的路径"按**配置该有的存法**归一化，然后才写进配置。

        * 落在**数据根里**的 → 存**相对路径**：数据根改名/搬家后天然跟随，不会变成指向
          旧目录的死路径（2026-10-02 群反馈：「我把主路径改了文件名，然后他没识别出来」）；
        * 落在数据根外的（你自己那份 XXMI、游戏目录、外部 Mod 库…）→ **原样保留**绝对路径。

        凡是"把程序算出来的路径写进配置"的地方都该过这一道，别再直接写 `str(path)`。
        """
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            path = Path(text).expanduser()
            if path.is_absolute():
                return path.resolve().relative_to(Path(self.base_dir).resolve()).as_posix()
        except (OSError, ValueError):
            return text
        return text

    def normalize_blank_paths(self) -> list[str]:
        """把「留空 = 自动」的路径字段补回默认值，返回被回填的字段名。

        设置页里这些框**可以自己填、也可以留空**（用户 2026-10-02：「全部放开吧」）。
        但"留空"不能真的存成空串：`resolve_path("")` 会解析成**数据根本身**
        （`dlss5_dir` 一空，`dlss5_path` 就变成数据根，DLSS5 直接失效）。所以每次
        加载/保存都按 dataclass 的默认值回填：
          * `library_dir` / `runtime_dir` / `dlss5_dir` / `staging_mods_dir` 这类**有默认值**
            的 → 填回默认（`library` / `runtime` / `runtime/dlss5` …）；
          * `xxmi_launcher` / `reshade_dll` / `secondary_motion_dir` / `poser_dir` 默认就是空
            → 保持空，由 `autofill()` 或各组件自己的探测去补（真正的"自动"）。
        """
        defaults: dict[str, str] = {}
        for item in fields(self):
            if item.name.startswith("_") or item.default is MISSING:
                continue
            if isinstance(item.default, str):
                defaults[item.name] = item.default
        filled: list[str] = []
        for name in _DATA_ROOT_RELATIVE_FIELDS:
            if str(getattr(self, name, "") or "").strip():
                continue
            default = defaults.get(name, "")
            if default:
                setattr(self, name, default)
                filled.append(name)
        return filled

    def ensure_dirs(self) -> None:
        """建出本程序要用的目录。

        ⚠️ **绝不在"数据根之外 + 当前不存在 + 长得像数据根布局"的位置建目录**：配置里
        残留的旧数据根绝对路径，会让这里把**一整条空目录树重建回旧位置** —— 用户看到
        的是「我没动它，它又给我新建了一个空白文件夹」（2026-10-02 群反馈，本地已复现：
        `staging_mods_dir` 指向旧根时会重建 `<旧根>\\runtime\\builtin\\XXMI\\EFMI\\Mods`）。
        数据根内的目录、以及用户真指定的**已存在**的外部目录，行为完全不变。
        """
        root = self.base_dir
        for path in (self.library_path, self.runtime_path, self.builtin_runtime_path, self.staging_mods_path, self.reshade_runtime_path):
            if not _within(root, path) and not path.is_dir() and _data_root_tail(path):
                continue
            path.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.xxmi_launcher and (self.xxmi_launcher_path is None or not self.xxmi_launcher_path.is_file()):
            problems.append(f"XXMI Launcher not found: {self.xxmi_launcher}")
        if self.game_exe and (self.game_exe_path is None or not self.game_exe_path.is_file()):
            problems.append(f"Game executable not found: {self.game_exe}")
        if self.migoto_loader and (self.migoto_loader_path is None or not self.migoto_loader_path.is_file()):
            problems.append(f"3DMigoto loader not found: {self.migoto_loader}")
        if self.official_launcher and (self.official_launcher_path is None or not self.official_launcher_path.is_file()):
            problems.append(f"Official launcher not found: {self.official_launcher}")
        if self.reshade_dll and (self.reshade_dll_path is None or not self.reshade_dll_path.is_file()):
            problems.append(f"ReShade DLL not found: {self.reshade_dll}")
        # **绝不允许 staging 与 Mod 库重叠**（用户 2026-10-01 硬规则：「任何情况都不要动
        # 用户的 mod 库」）。清理 staging 是无条件 rmtree，一旦两者相同/互相嵌套，
        # 就是把用户的 Mod 全删掉 —— 一条外部反馈正是这么丢的库。
        from . import fsutil      # 局部导入，避免 config ↔ fsutil 的模块级循环引用

        conflict = fsutil.library_conflict(self.library_path, self.staging_mods_path)
        if conflict:
            problems.append(
                f"Staging Mods 目录与 Mod 库重叠：{conflict}；"
                f"请把 staging 改到 Mod 库之外（默认的内置 XXMI 目录是安全的）"
            )
        return problems


def auto_detect_secondary_motion() -> str:
    """找 SecondaryMotion 工具目录（含 Manager exe 的那层）。

    优先用工作区内嵌的那份（runtime\\secondary_motion），再扫外部安装目录。
    """
    builtin = DEFAULT_DATA_ROOT / "secondary_motion"
    for candidate in (
        builtin / "SecondaryMotion" / "SecondaryMotion.Manager.exe",
        builtin / "SecondaryMotion.Manager.exe",
    ):
        if candidate.is_file():
            return str(builtin)

    candidates: list[Path] = []
    for root in [Path(d) for d in available_drives()]:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            low = child.name.lower()
            if "shakingbreast" in low or low.startswith("secondarymotion") or "secondary-motion" in low:
                for candidate in (
                    child / "SecondaryMotion" / "SecondaryMotion.Manager.exe",
                    child / "SecondaryMotion.Manager.exe",
                ):
                    if candidate.is_file():
                        candidates.append(child)
                        break
        if candidates:
            break
    return str(candidates[0]) if candidates else ""


def available_drives() -> list[str]:
    """动态列出当前可用盘符（不写死 C:/D:/E:）。"""
    import string

    drives: list[str] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:/")
        try:
            if root.is_dir():
                drives.append(f"{letter}:/")
        except OSError:
            continue
    return drives


# 探测结果缓存：这些函数会被 get_state 每次调用，全盘扫描一次要 5 秒以上，
# 不缓存会把界面拖死（表现为 Mod 列表迟迟渲染不出来）。需要重新探测时传 refresh=True。
_DETECT_CACHE: dict[str, str] = {}


def cached_detect(key: str) -> str:
    """**只读**探测缓存，绝不触发全盘扫描。

    界面刷新（`get_state()`）原先会同步跑 `auto_detect_xxmi/migoto_loader/
    official_launcher`，首次全盘扫一遍能把加载页卡住十几秒。现在改成读这里：
    值由后台预热线程填（`AppConfig.autofill(deep=True)` 会走同一套探测），
    还没填好就先返回空串，前端稍后再刷新一次即可（2026-10-01 改）。
    """
    return _DETECT_CACHE.get(key, "")


def auto_detect_game_dir(refresh: bool = False) -> str:
    """自动搜索《终末地》本体目录（即含 Endfield.exe 的那层）。

    依次尝试：常见启动器布局（Hypergryph Launcher / GRYPHLINK）→ 各盘符浅层
    扫描 `\\games\\Endfield Game`。搜不到返回空串，由调用方提示用户手填。
    """
    if not refresh and "game_dir" in _DETECT_CACHE:
        return _DETECT_CACHE["game_dir"]
    result = _scan_game_dir()
    # **不要缓存空结果**：搜索失败常常是一时的（程序刚启动、某个盘暂时不可访问等），
    # 一旦把空串固化下来，之后所有调用都会拿到空 —— 表现为「游戏目录未定位」，并连带
    # sbm 检查报「注入不完整」（2026-09-29 定位到的两个现象是同一个根因）。
    if result:
        _DETECT_CACHE["game_dir"] = result
    return result


def _scan_game_dir() -> str:
    layouts = (
        "games/Endfield Game",
        "games/EndField Game",
        "Endfield Game",
        "EndField Game",
    )
    # ① 常见启动器目录
    for drive in available_drives():
        for parent in ("Hypergryph Launcher", "GRYPHLINK", "Program Files/GRYPHLINK", "Games/Hypergryph Launcher"):
            base = Path(drive) / parent
            if not base.is_dir():
                continue
            for layout in layouts:
                candidate = base / layout
                if (candidate / "Endfield.exe").is_file():
                    return str(candidate)
    # ② 盘符下一层扫描（覆盖自定义安装位置）
    for drive in available_drives():
        base = Path(drive)
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            for layout in layouts:
                candidate = child / layout
                try:
                    if (candidate / "Endfield.exe").is_file():
                        return str(candidate)
                except OSError:
                    continue
    return ""


def auto_detect_xxmi(refresh: bool = False) -> str:
    """找 XXMI Launcher：**优先用工作区内嵌的那份**，再退到外部安装。

    带缓存（与 migoto / launcher 的探测保持一致）：它会浅扫所有盘符，
    界面刷新时同步调用能把加载页卡住十几秒（2026-10-01 改）。
    """
    if not refresh and "xxmi" in _DETECT_CACHE:
        return _DETECT_CACHE["xxmi"]
    result = _scan_xxmi()
    if result:
        _DETECT_CACHE["xxmi"] = result
    return result


def _scan_xxmi() -> str:
    builtin = DEFAULT_DATA_ROOT / "builtin" / "XXMI"
    for candidate in (
        builtin / "Resources" / "Bin" / "XXMI Launcher.exe",
        builtin / "XXMI Launcher.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    appdata = Path(os.environ.get("APPDATA", ""))
    localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
    home = Path.home()
    roots = [
        appdata / "XXMI Launcher",
        localappdata / "XXMI Launcher",
        localappdata / "Programs" / "XXMI Launcher",
        home / "XXMI Launcher",
        Path("C:/XXMI Launcher"),
        Path("D:/XXMI Launcher"),
        Path("C:/Program Files/XXMI Launcher"),
        Path("D:/Program Files/XXMI Launcher"),
    ]
    for root in roots:
        for candidate in (
            root / "Resources" / "Bin" / "XXMI Launcher.exe",
            root / "XXMI Launcher.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    # Shallow scan of common drive roots for folders whose name contains xxmi.
    for drive in available_drives():
        base = Path(drive)
        if not base.is_dir():
            continue
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for child in children:
            if "xxmi" not in child.name.lower() or not child.is_dir():
                continue
            for candidate in (
                child / "Resources" / "Bin" / "XXMI Launcher.exe",
                child / "XXMI Launcher.exe",
            ):
                if candidate.is_file():
                    return str(candidate)
    found = shutil.which("XXMI Launcher.exe")
    return found or ""


def auto_detect_migoto_loader(refresh: bool = False) -> str:
    if not refresh and "migoto" in _DETECT_CACHE:
        return _DETECT_CACHE["migoto"]
    result = _scan_migoto_loader()
    # ⚠️ **空结果不进缓存**（2026-10-04 修，与 game_dir / xxmi 对齐）：
    # 探测失败常常是**一时**的（刚启动时盘还没就绪、被杀软拖慢、UAC 未提权），
    # 一旦把空串固化进进程内缓存，之后所有调用都拿空 —— 一键启动时就会"定位不到
    # 3DMigoto loader"。同一个问题另两处早已按这个写法处理（见 auto_detect_game_dir），
    # 这里与 launcher 是漏改的同一处。
    if result:
        _DETECT_CACHE["migoto"] = result
    return result


def _scan_migoto_loader() -> str:
    """Find a working 3DMigoto loader directory (loader.exe + d3d11.dll + d3dx.ini)."""
    # 打包后 `__file__` 指向 PyInstaller 的临时解包目录，这里必须用 PROJECT_ROOT
    # （= exe 所在目录），否则永远找不到内嵌的 runtime/migoto ——
    # 与 _detect_project_root() 的约定保持一致（2026-10-01 修）。
    root = PROJECT_ROOT
    candidates: list[Path] = []
    for internal in (root / "runtime" / "migoto" / "loader.exe", root / "runtime" / "builtin" / "XXMI" / "EFMI" / "loader.exe"):
        if internal.is_file():
            candidates.append(internal)
    roots = [Path(d) for d in available_drives()]
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                depth = len(Path(dirpath).parts) - base_depth
                if depth > 4:
                    dirnames[:] = []
                    continue
                if "loader.exe" not in {name.lower() for name in filenames}:
                    continue
                directory = Path(dirpath)
                if (directory / "d3d11.dll").is_file() and (directory / "d3dx.ini").is_file():
                    candidates.append(directory / "loader.exe")
                    break
        except OSError:
            continue
        if candidates:
            break
    return str(candidates[0]) if candidates else ""


def auto_detect_official_launcher(refresh: bool = False) -> str:
    if not refresh and "launcher" in _DETECT_CACHE:
        return _DETECT_CACHE["launcher"]
    result = _scan_official_launcher()
    # ⚠️ **空结果不进缓存**（2026-10-04 修，理由同 auto_detect_migoto_loader）
    if result:
        _DETECT_CACHE["launcher"] = result
    return result


def _scan_official_launcher() -> str:
    """Find the Hypergryph official launcher near the game directory."""
    candidates: list[Path] = []
    # 先由自动搜到的游戏目录反推启动器（游戏目录通常是 <root>\games\Endfield Game）
    game = auto_detect_game_dir()
    if game:
        for parent in list(Path(game).parents)[:3]:
            for name in ("Launcher.exe", "1.6.0/Launcher.exe"):
                candidate = parent / name
                if candidate.is_file():
                    candidates.append(candidate)
    if candidates:
        return str(candidates[0])
    for drive in available_drives():
        base = Path(drive)
        if not base.is_dir():
            continue
        try:
            for child in base.iterdir():
                if "hypergryph" not in child.name.lower() or not child.is_dir():
                    continue
                for candidate in (child / "Launcher.exe", child / "1.6.0" / "Launcher.exe"):
                    if candidate.is_file():
                        return str(candidate)
        except OSError:
            continue
    return ""
