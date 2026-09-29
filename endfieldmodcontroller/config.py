"""Application configuration for EndfieldModController."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
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


PROJECT_ROOT = _detect_project_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_DATA_ROOT = PROJECT_ROOT / "runtime"


@dataclass
class AppConfig:
    # 默认值一律用**相对 PROJECT_ROOT 的相对路径**，这样配置被清空后一键启动
    # 也能直接指向工作区里的内嵌组件（见 autofill()）。
    library_dir: str = "library"
    runtime_dir: str = "runtime"
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
    firstperson_addon_enabled: bool = True    # Endfield Enhancer 第一人称
    # 是否把 EFMI 的 d3d11.dll（服装 Mod 引擎）也写进 XXMI 注入库
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
    # 防多开：检测到终末地已在运行时**阻止**再启动一个实例。
    # 两个游戏实例同时被注入，Mod/ReShade 会互相抢资源，表现为随机崩溃或 Mod 不生效。
    prevent_game_multi_instance: bool = True
    # 工具自身单实例：已有控制器在跑时，第二个实例直接提示并退出（避免两个进程同时改
    # 注入库/staging 造成互相踩踏）。关掉它就能开多个窗口。
    single_instance: bool = True
    # 是否把内置的新版 DLSS 运行库（nvngx_dlss / nvngx_dlssnr）部署进游戏目录。
    # 默认 False —— 实测新版 nvngx 会让游戏起不来，只在缺失时才补齐。
    deploy_new_nvngx: bool = False
    # 乳摇/次级运动管理器（第三方 SecondaryMotion 工具）所在目录，留空则自动探测
    secondary_motion_dir: str = ""
    # 启动前自动补齐乳摇插件的注入（两个 proxy + plugin\sbm.dll）
    secondary_motion_injection: bool = True
    # 【可选】改用「经 XXMI 注入 sbm.dll」的方式时，sbm.dll 的部署路径。
    # 留空 = 用 proxy 替换方式（老路子，会和 ReShade/EFMI 抢 D3D 链路）；
    # 填了短路径（如 D:\\zmdmod\\SBM\\sbm.dll）= 由 XXMI 注入，游戏目录不换任何系统 DLL。
    secondary_motion_dll: str = ""
    theme: str = "light"
    last_tab: str = "library"
    inject_reshade_ui: bool = True
    dependency_manifest: str = "dependencies.json"
    launch_extra_args: list[str] = field(default_factory=list)
    selected_mods: list[str] = field(default_factory=list)
    auto_update_dependencies: bool = False
    # 默认为 True：XXMI Launcher 的 exe 要求管理员权限（非管理员启动会直接报
    # WinError 740），而用户要的是「零配置启动即用」，所以默认就按管理员处理。
    require_admin: bool = True

    _config_path: str = field(default="", init=False, repr=False)

    # ---------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or DEFAULT_CONFIG_PATH
        if not path.is_file():
            cfg = cls()
            cfg._config_path = str(path)
            cfg.autofill()
            cfg.save(path)
            return cfg
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = cls()
            cfg._config_path = str(path)
            cfg.autofill()
            return cfg
        known = {f.name for f in cls.__dataclass_fields__.values() if not f.name.startswith("_")}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        cfg = cls(**filtered)
        cfg._config_path = str(path)
        if cfg.theme not in {"dark", "light"}:
            cfg.theme = "light"
        # 关键路径留空时按工作区内的内嵌组件补齐并落盘：
        # 这样把 config.json 整个删掉，一键启动依然能自建出完整可用配置。
        if cfg.autofill():
            try:
                cfg.save(path)
            except OSError:
                pass
        return cfg

    def autofill(self) -> list[str]:
        """把留空的关键路径按**内嵌组件**补齐（优先相对路径），返回被填的字段名。"""
        filled: list[str] = []

        # ① XXMI Launcher：优先工作区内嵌那份（写相对路径）
        if not self.xxmi_launcher.strip():
            builtin = self.builtin_runtime_path / "XXMI" / "Resources" / "Bin" / "XXMI Launcher.exe"
            if builtin.is_file():
                self.xxmi_launcher = "runtime/builtin/XXMI/Resources/Bin/XXMI Launcher.exe"
                filled.append("xxmi_launcher")
            else:
                guess = auto_detect_xxmi()
                if guess:
                    self.xxmi_launcher = guess
                    filled.append("xxmi_launcher")

        # ② 乳摇工具：优先工作区内嵌那份
        if not self.secondary_motion_dir.strip():
            builtin_sbm = self.runtime_path / "secondary_motion" / "SecondaryMotion" / "SecondaryMotion.Manager.exe"
            if builtin_sbm.is_file():
                self.secondary_motion_dir = "runtime/secondary_motion"
                filled.append("secondary_motion_dir")
            else:
                guess = auto_detect_secondary_motion()
                if guess:
                    self.secondary_motion_dir = guess
                    filled.append("secondary_motion_dir")

        # ③ DLSS5 底座 DLL：永远指向内嵌 dlss5
        if not self.reshade_dll.strip():
            candidate = self.dlss5_path / "d3d12.dll"
            if candidate.is_file():
                self.reshade_dll = "runtime/dlss5/d3d12.dll"
                filled.append("reshade_dll")

        # ④ 官方启动器 / 3DMigoto loader：自动探测（搜不到就留空，由调用方提示手填）
        if not self.official_launcher.strip():
            guess = auto_detect_official_launcher()
            if guess:
                self.official_launcher = guess
                filled.append("official_launcher")
        if not self.migoto_loader.strip():
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
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

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
        return self.resolve_path(self.xxmi_launcher) if self.xxmi_launcher else None

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
        """EFMI 目录：优先从 XXMI Launcher 路径上溯，再回退到内置 runtime。"""
        candidates: list[Path] = []
        launcher = self.xxmi_launcher_path
        if launcher is not None:
            candidates.extend(launcher.parents)
        if self.use_builtin_runtime:
            candidates.append(self.builtin_runtime_path / "XXMI")
        for parent in candidates:
            if (parent / "EFMI" / "d3d11.dll").is_file():
                return parent / "EFMI"
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

    def ensure_dirs(self) -> None:
        for path in (self.library_path, self.runtime_path, self.builtin_runtime_path, self.staging_mods_path, self.reshade_runtime_path):
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


def auto_detect_game_dir(refresh: bool = False) -> str:
    """自动搜索《终末地》本体目录（即含 Endfield.exe 的那层）。

    依次尝试：常见启动器布局（Hypergryph Launcher / GRYPHLINK）→ 各盘符浅层
    扫描 `\\games\\Endfield Game`。搜不到返回空串，由调用方提示用户手填。
    """
    if not refresh and "game_dir" in _DETECT_CACHE:
        return _DETECT_CACHE["game_dir"]
    result = _scan_game_dir()
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


def auto_detect_xxmi() -> str:
    """找 XXMI Launcher：**优先用工作区内嵌的那份**，再退到外部安装。"""
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
    _DETECT_CACHE["migoto"] = result
    return result


def _scan_migoto_loader() -> str:
    """Find a working 3DMigoto loader directory (loader.exe + d3d11.dll + d3dx.ini)."""
    root = Path(__file__).resolve().parents[1]
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
    for path in candidates:
        if path.is_file():
            return str(path)
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
