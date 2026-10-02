"""「程序目录改名/搬走后自动跟上」的回归测试（2026-10-02 群反馈）。

反馈原话：
  * 「**我把文件目录修改了，可是这些识别的还是原目录**怎么办」
  * 「**我把主路径改了文件名，然后他没识别出来**」
  * 「**又重新给我新建了一个空白文件**」
现象（截图）：设置页「乳摇工具目录」显示 `D:\\应用\\zmd_mod管理\\runtime\\secondary_motion`
（那是**很早以前**的数据根），而程序其实已经在新目录里跑；同时旧位置被**重新建出**
一整条 `runtime\\...` 空目录树。

根因（本地已复现）：
  ① 配置里存在"旧数据根的**绝对**路径"（`import_pack` 装 sbm 时写 `str(tool.parent)`、
     全盘探测/前端回写也会写绝对路径）；
  ② 数据根（config.json 所在目录）改名后这些值不会自愈 → 界面一直显示旧目录，而
     readonly 又改不了；
  ③ `AppConfig.ensure_dirs()` 无条件对配置路径 `mkdir(parents=True)` → **在旧位置重建
     出 `<旧根>\\runtime\\builtin\\XXMI\\EFMI\\Mods` 这一整条空目录树**（用户看到的就是
     「又重新给我新建了一个空白文件」）。

修法：`config._relocate_stale_paths()`（加载时把旧数据根绝对路径改回相对路径）
     + `ensure_dirs()` 的"不在数据根外凭空建目录"护栏。
"""
from __future__ import annotations

import json
from pathlib import Path

from endfieldmodcontroller.config import AppConfig

STAGING_TAIL = "runtime/builtin/XXMI/EFMI/Mods"
SBM_TAIL = "runtime/secondary_motion"
XXMI_TAIL = "runtime/builtin/XXMI/Resources/Bin/XXMI Launcher.exe"


def _write_config(path: Path, **fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------
# 判据①：记录过旧数据根（正常路径 —— 打开过一次就会记下来）
# ---------------------------------------------------------------
def test_paths_follow_when_data_root_is_renamed(tmp_path):
    old_root = tmp_path / "应用" / "zmd_mod管理"
    new_root = tmp_path / "apps" / "zmd_modtoos"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    _write_config(
        new_root / "config.json",
        data_root=str(old_root),
        staging_mods_dir=str(old_root / STAGING_TAIL.replace("/", "\\")),
        secondary_motion_dir=str(old_root / SBM_TAIL.replace("/", "\\")),
        xxmi_launcher=str(old_root / XXMI_TAIL.replace("/", "\\")),
    )

    cfg = AppConfig.load(new_root / "config.json")

    assert cfg.staging_mods_dir == STAGING_TAIL
    assert cfg.secondary_motion_dir == SBM_TAIL
    assert cfg.xxmi_launcher == XXMI_TAIL
    # 解析出来的实际位置全部落到**新**数据根
    assert cfg.staging_mods_path == (new_root / STAGING_TAIL).resolve()
    assert cfg.data_root == str(new_root.resolve())
    # 已经落盘：下次启动不会又变回旧路径
    saved = _read_config(new_root / "config.json")
    assert saved["staging_mods_dir"] == STAGING_TAIL
    assert saved["secondary_motion_dir"] == SBM_TAIL


def test_relocation_is_idempotent(tmp_path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    _write_config(
        new_root / "config.json",
        data_root=str(old_root),
        secondary_motion_dir=str(old_root / "runtime" / "secondary_motion"),
    )
    first = AppConfig.load(new_root / "config.json")
    second = AppConfig.load(new_root / "config.json")
    assert first.secondary_motion_dir == second.secondary_motion_dir == SBM_TAIL


# ---------------------------------------------------------------
# 判据②：老配置没有记录（第一次升级上来）→ 保守推断
# ---------------------------------------------------------------
def test_legacy_config_without_recorded_root_uses_layout_heuristic(tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    ghost = tmp_path / "ghost" / "zmd_mod管理"          # 早已不存在的老数据根
    _write_config(
        root / "config.json",
        staging_mods_dir=str(ghost / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods"),
        secondary_motion_dir=str(ghost / "runtime" / "secondary_motion"),
    )

    cfg = AppConfig.load(root / "config.json")

    assert cfg.staging_mods_dir == STAGING_TAIL
    assert cfg.secondary_motion_dir == SBM_TAIL


def test_existing_external_path_is_never_rewritten(tmp_path):
    """用户**故意**指到外部（且那份东西真的在）时，一个字符都不许动。"""
    root = tmp_path / "current"
    root.mkdir()
    external_mods = tmp_path / "XXMI Launcher" / "EFMI" / "Mods"
    external_mods.mkdir(parents=True)
    _write_config(root / "config.json", staging_mods_dir=str(external_mods))

    cfg = AppConfig.load(root / "config.json")

    assert cfg.staging_mods_dir == str(external_mods)


def test_external_path_kept_even_with_recorded_root(tmp_path):
    """有旧数据根记录、但值是**旧根之外**的真实路径 → 不动（那是有意为之的配置）。"""
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    external_mods = tmp_path / "external" / "EFMI" / "Mods"
    external_mods.mkdir(parents=True)
    _write_config(new_root / "config.json", data_root=str(old_root), staging_mods_dir=str(external_mods))

    cfg = AppConfig.load(new_root / "config.json")

    assert cfg.staging_mods_dir == str(external_mods)


def test_relative_values_are_left_alone(tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    _write_config(root / "config.json", library_dir="library", dlss5_dir="runtime/dlss5", poser_dir="runtime/poser")

    cfg = AppConfig.load(root / "config.json")

    assert (cfg.library_dir, cfg.dlss5_dir, cfg.poser_dir) == ("library", "runtime/dlss5", "runtime/poser")


def test_new_config_records_the_data_root(tmp_path):
    cfg = AppConfig.load(tmp_path / "brand-new" / "config.json")
    assert cfg.data_root == str((tmp_path / "brand-new").resolve())


# ---------------------------------------------------------------
# 护栏：ensure_dirs 绝不在旧位置重建空目录树
# ---------------------------------------------------------------
def test_ensure_dirs_never_recreates_a_stale_root(tmp_path):
    ghost = tmp_path / "应用" / "zmd_mod管理"
    root = tmp_path / "apps" / "zmd_modtoos"
    root.mkdir(parents=True)
    _write_config(root / "config.json")
    cfg = AppConfig.load(root / "config.json")
    # 绕过自愈，直接塞一个"旧数据根残留值"（模拟修复前那份配置的处境）
    cfg.staging_mods_dir = str(ghost / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods")

    cfg.ensure_dirs()

    assert not ghost.exists(), "旧数据根不允许被重建（这正是用户看到的『又新建了一个空白文件』）"
    assert (root / "library").is_dir()
    assert (root / "runtime").is_dir()


def test_ensure_dirs_still_builds_the_normal_tree(tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    _write_config(root / "config.json")
    cfg = AppConfig.load(root / "config.json")

    cfg.ensure_dirs()

    assert (root / "library").is_dir()
    assert (root / "runtime" / "builtin").is_dir()
    assert (root / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods").is_dir()


def test_existing_external_staging_dir_is_kept_by_ensure_dirs(tmp_path):
    """外部目录**已经存在**时不受护栏影响（用外部 XXMI 的用户照常）。"""
    root = tmp_path / "current"
    root.mkdir()
    external_mods = tmp_path / "XXMI Launcher" / "EFMI" / "Mods"
    external_mods.mkdir(parents=True)
    _write_config(root / "config.json", staging_mods_dir=str(external_mods))
    cfg = AppConfig.load(root / "config.json")

    cfg.ensure_dirs()

    assert external_mods.is_dir()


# ---------------------------------------------------------------
# 判据必须保守：别把"用户自定义、只是还没建出来"的路径当残留改掉
# ---------------------------------------------------------------
def test_missing_subdir_of_a_live_root_is_not_relocated(tmp_path):
    """疑似数据根里**还有文件**（是个在用的目录）→ 不能动（哪怕子目录还不存在）。

    这条是 `tests/test_mod_backup.py::test_backup_dir_inside_library_is_refused`
    抓出来的漏洞：早先的判据只看"路径不存在"，于是把 `<tmp>/library/mod-backup`
    这种"用户配的、还没建出来"的路径也相对化了，绕过"备份目录不许落在 Mod 库内"的检查。
    """
    root = tmp_path / "current"
    root.mkdir()
    live_root = tmp_path / "in-use"
    (live_root / "runtime").mkdir(parents=True)
    (live_root / "自定义").mkdir(parents=True)
    (live_root / "自定义" / "note.txt").write_text("这是用户在用的目录", encoding="utf-8")
    wanted = str(live_root / "runtime" / "secondary_motion")
    _write_config(root / "config.json", secondary_motion_dir=wanted)

    cfg = AppConfig.load(root / "config.json")

    assert cfg.secondary_motion_dir == wanted


def test_wrecked_empty_shell_root_is_relocated(tmp_path):
    """疑似数据根只剩一棵空壳目录树（历史版本重建出来的）→ 认定残留并改写。"""
    root = tmp_path / "current"
    root.mkdir()
    shell = tmp_path / "应用" / "zmd_mod管理"
    (shell / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods").mkdir(parents=True)
    _write_config(
        root / "config.json",
        staging_mods_dir=str(shell / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods"),
    )

    cfg = AppConfig.load(root / "config.json")

    assert cfg.staging_mods_dir == STAGING_TAIL


# ---------------------------------------------------------------
# 从源头不再产生绝对路径：乳摇工具首次安装时记的是相对路径
# ---------------------------------------------------------------
def test_sbm_first_install_records_relative_dir(tmp_path, monkeypatch):
    import zipfile

    from endfieldmodcontroller import config as config_mod
    from endfieldmodcontroller import secondary_motion

    # 别让它扫盘找到开发机上那份工具
    monkeypatch.setattr(config_mod, "auto_detect_secondary_motion", lambda: "")

    root = tmp_path / "data"
    root.mkdir()
    cfg = config_mod.AppConfig()
    cfg.save(root / "config.json")
    pack = tmp_path / "sbm.zip"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("SecondaryMotion.Manager.exe", b"MZ fake")

    result = secondary_motion.import_pack(cfg, pack)

    assert result["ok"], result
    assert cfg.secondary_motion_dir == SBM_TAIL
    assert Path(result["tool_dir"]).samefile(root / "runtime" / "secondary_motion" / "SecondaryMotion")


# ---------------------------------------------------------------
# 「留空 = 自动」：这些框放开成可编辑之后，空串不许原样留着
# ---------------------------------------------------------------
def test_blank_paths_fall_back_to_defaults(tmp_path):
    """空串会被 `resolve_path("")` 解析成**数据根本身**（`dlss5_path` 就废了）→ 必须回填。"""
    root = tmp_path / "current"
    root.mkdir()
    _write_config(
        root / "config.json",
        library_dir="",
        dlss5_dir="",
        staging_mods_dir="",
        reshade_dll="",
        secondary_motion_dir="",
    )

    cfg = AppConfig.load(root / "config.json")

    assert cfg.library_dir == "library"
    assert cfg.dlss5_dir == "runtime/dlss5"
    assert cfg.staging_mods_dir == STAGING_TAIL
    assert cfg.dlss5_path == (root / "runtime" / "dlss5").resolve()
    # 默认本来就是空的（= 真正的自动探测）→ 保持空，别乱填
    assert cfg.reshade_dll == ""
    assert cfg.secondary_motion_dir == ""


def test_save_config_refills_blank_paths(tmp_path, monkeypatch):
    """走一遍 `api.save_config`：用户在设置页清空某一项 → 保存后它自己填回该有的值。"""
    from endfieldmodcontroller.api import EndfieldModControllerApi

    root = tmp_path / "current"
    root.mkdir()
    _write_config(root / "config.json")
    cfg = AppConfig.load(root / "config.json")

    # 不跑 __init__（免得起后台预热线程），只借这个方法来验它真的做了回填
    api = object.__new__(EndfieldModControllerApi)
    api.config = cfg
    monkeypatch.setattr(api, "_invalidate_mods", lambda: None, raising=False)

    result = api.save_config({"dlss5_dir": "", "staging_mods_dir": "", "secondary_motion_dir": ""})

    assert result["config"]["dlss5_dir"] == "runtime/dlss5"
    assert result["config"]["staging_mods_dir"] == STAGING_TAIL
    assert result["config"]["secondary_motion_dir"] == ""
    # 也落盘了，下次启动不会再变回空
    assert _read_config(root / "config.json")["dlss5_dir"] == "runtime/dlss5"
