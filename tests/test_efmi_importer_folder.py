"""XXMI 的 `importer_folder` 被指到 Mod 库时**必须自动改回来**（2026-10-07，lzh18 现场）。

**现场**（诊断包 `diagnostics-20261007-124733`，`C:\\Users\\lzh18`）：
* `Importers.EFMI.Importer.importer_folder = 'C:/Users/lzh18/Downloads/library'`
  —— 指到了**用户的 Mod 库**；XXMI 于是把 `…\\library\\d3d11.dll` 当 EFMI loader 注入，
  并去库里找 `d3dx.ini`（XXMI 自己的日志：`缺少关键文件：d3dx.ini！`）；
* 注入库那边（为了让 ReShade 排在 EFMI 之前）列的是
  `…\\runtime\\builtin\\XXMI\\EFMI\\d3d11.dll` —— **同名的另一份**；
* ⇒ 进程里同时进了**两份 D3D11 loader**（WER：`LoadedModule[16]` 与 `[61]`），
  `Player.log` 走到 `GfxDevice: creating device client` 就 `Crash!!!`，
  `exit_code=0xC0000005`、故障模块 `ACE-Base64.dll`，游戏活 24~39 秒
  ⇒ XXMI 等不到窗口，弹「EFMI 加载失败：无法检测到游戏进程 Endfield.exe 的窗口」。

**为什么 v1.0.10 / v1.0.29 两次修复都没解决它**：那两次改的都是"**我们往注入库里列哪一份**"，
而 **XXMI 自己那份一直照旧被注入** —— 从"单份假 loader（`0xC0000135`）"变成
"**双份 loader（`0xC0000005`）**"。这次的判据是**那个配置字段本身**。

要守住的性质：
* 指向树外（Mod 库）⇒ **自动改回这个 XXMI 自己的 importer 目录**（写绝对路径、先备份、
  其它字段一个不动、可回滚）；
* 已经是对的 / 相对路径（`EFMI/`）/ 外部 XXMI 自己的绝对路径 ⇒ **一个字节都不动**；
* 改不回来（目标位置没有 loader）⇒ **如实报 `ok=False`，不写配置**（别制造更坏的状态）；
* 配置改不回来时，注入库**不再叠加第二条 loader**（宁可少列一条，也不要两份 loader 撞死）。

全部离线：只碰 tmp 里的假 XXMI 布局与假 Mod 库。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import injecttrace, launcher, watchsample
from endfieldmodcontroller.config import AppConfig

CONFIG_NAME = "XXMI Launcher Config.json"


def _make_xxmi(root: Path) -> tuple[Path, Path]:
    """造一套内置 XXMI 布局，返回 (launcher.exe, EFMI 目录)。"""
    bin_dir = root / "Resources" / "Bin"
    bin_dir.mkdir(parents=True)
    launcher_exe = bin_dir / "XXMI Launcher.exe"
    launcher_exe.write_bytes(b"MZ")
    efmi = root / "EFMI"
    efmi.mkdir(parents=True)
    (efmi / "d3d11.dll").write_bytes(b"REAL-EFMI-LOADER")
    (efmi / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")
    return launcher_exe, efmi


def _write_config(root: Path, launcher_exe: Path, *, importer_folder: str,
                  extra_libraries: str = "") -> Path:
    path = root / CONFIG_NAME
    path.write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI", "enabled_importers": ["EFMI"]},
        "Importers": {
            "EFMI": {
                "Importer": {
                    "importer_folder": importer_folder,
                    "extra_libraries_enabled": bool(extra_libraries),
                    "extra_libraries": extra_libraries,
                    "extra_libraries_signature": "SIG-KEEP-ME",
                }
            }
        },
        "Security": {"user_signature": "USER-SIG-KEEP-ME"},
    }, ensure_ascii=False, indent=4), encoding="utf-8")
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """内置 XXMI + 一个"被指到 Mod 库"的 importer_folder（复刻 lzh18 现场）。"""
    root = tmp_path / "runtime" / "builtin" / "XXMI"
    launcher_exe, real_efmi = _make_xxmi(root)
    library = tmp_path / "library"                      # 用户的 Mod 库
    library.mkdir(parents=True)
    (library / "d3d11.dll").write_bytes(b"MOD-BUNDLED-DLL")     # 同名，但不是 loader
    config_path = _write_config(root, launcher_exe,
                                importer_folder=str(library).replace("\\", "/"))
    cfg = AppConfig(
        runtime_dir=str(tmp_path / "runtime"),
        library_dir=str(library),
        dlss5_dir=str(tmp_path / "runtime" / "dlss5"),
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
        staging_mods_dir=str(root / "EFMI" / "Mods"),
    )
    cfg.xxmi_launcher = str(launcher_exe)
    cfg.save(tmp_path / "config.json")
    return SimpleNamespace(root=root, launcher_exe=launcher_exe, real_efmi=real_efmi,
                           library=library, config_path=config_path, config=cfg,
                           tmp=tmp_path)


# --------------------------------------------------------------------------
# ① 读出来的现状必须能描述"XXMI 会去注入哪份 loader"
# --------------------------------------------------------------------------
def test_importer_folder_state_reports_foreign_folder(env):
    state = launcher.xxmi_importer_folder(env.config)
    assert state["raw"] == str(env.library).replace("\\", "/")
    assert Path(state["path"]).resolve() == env.library.resolve()
    assert state["has_loader"] is True          # 库里确实有同名 dll（所以 XXMI 会注入它）
    assert state["has_d3dx_ini"] is False       # 但那不是 EFMI 运行目录
    assert state["in_xxmi_tree"] is False


def test_foreign_loader_points_at_the_mod_library_copy(env):
    foreign = launcher.xxmi_foreign_loader(env.config)
    assert foreign is not None
    assert Path(foreign).resolve() == (env.library / "d3d11.dll").resolve(), (
        "★ XXMI 会注入库里那份 —— 这正是与注入库那条撞成两个 loader 的来源"
    )


# --------------------------------------------------------------------------
# ② 指向 Mod 库 ⇒ 自动改回这个 XXMI 自己的目录
# --------------------------------------------------------------------------
def test_importer_folder_pointing_at_mod_library_is_fixed(env):
    state = launcher.ensure_efmi_importer_folder(env.config)
    assert state["ok"] is True and state["changed"] is True
    data = json.loads(env.config_path.read_text(encoding="utf-8"))
    importer = data["Importers"]["EFMI"]["Importer"]
    assert importer["importer_folder"].replace("\\", "/") == str(env.real_efmi).replace("\\", "/")
    # 其它字段一个都不能动（尤其是签名 —— 它盖回空值会让 XXMI 弹 Reset）
    assert importer["extra_libraries_signature"] == "SIG-KEEP-ME"
    assert data["Security"]["user_signature"] == "USER-SIG-KEEP-ME"
    assert data["Launcher"]["enabled_importers"] == ["EFMI"]
    # 改之前先备份（可回滚，且不覆盖历史备份 ⇒ 名字带时间戳）
    backups = list(env.config_path.parent.glob(CONFIG_NAME + ".mc-before-importer-folder-*.bak"))
    assert backups, "改配置前必须留下备份"
    assert json.loads(backups[0].read_text(encoding="utf-8"))["Importers"]["EFMI"]["Importer"][
        "importer_folder"] == str(env.library).replace("\\", "/")


def test_fix_is_idempotent(env):
    launcher.ensure_efmi_importer_folder(env.config)
    first = env.config_path.read_bytes()
    again = launcher.ensure_efmi_importer_folder(env.config)
    assert again["changed"] is False
    assert env.config_path.read_bytes() == first, "第二次不该再动配置"


def test_normal_absolute_folder_is_untouched(env):
    """对照：已经指向真正的 EFMI 目录 ⇒ 一个字节都不许改。"""
    env.config_path.write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI"},
        "Importers": {"EFMI": {"Importer": {
            "importer_folder": str(env.real_efmi).replace("\\", "/")}}},
    }, ensure_ascii=False, indent=4), encoding="utf-8")
    before = env.config_path.read_bytes()
    state = launcher.ensure_efmi_importer_folder(env.config)
    assert state["changed"] is False
    assert env.config_path.read_bytes() == before
    assert launcher.xxmi_foreign_loader(env.config) is None


def test_relative_folder_is_untouched(env):
    """`EFMI/`（XXMI 出厂默认形式）解析到 XXMI 根下 ⇒ 合法，不许改成绝对路径。"""
    _write_config(env.root, env.launcher_exe, importer_folder="EFMI/")
    before = env.config_path.read_bytes()
    state = launcher.ensure_efmi_importer_folder(env.config)
    assert state["changed"] is False
    assert env.config_path.read_bytes() == before


def test_external_xxmi_layout_is_untouched(tmp_path):
    """用户用**外部 XXMI** 时，它的绝对路径就是对的 ⇒ 不能按"内置 XXMI"的树去判非法。"""
    other = tmp_path / "ENDFIELD"
    launcher_exe, efmi = _make_xxmi(other)
    config_path = other / CONFIG_NAME
    config_path.write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI"},
        "Importers": {"EFMI": {"Importer": {
            "importer_folder": str(efmi).replace("\\", "/")}}},
    }, ensure_ascii=False, indent=4), encoding="utf-8")
    cfg = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                    dlss5_dir=str(tmp_path / "runtime" / "dlss5"),
                    builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"))
    cfg.xxmi_launcher = str(launcher_exe)
    cfg.save(tmp_path / "config.json")
    before = config_path.read_bytes()
    state = launcher.ensure_efmi_importer_folder(cfg)
    assert state["changed"] is False
    assert config_path.read_bytes() == before
    picked = launcher.active_efmi_loader(cfg)
    assert picked is not None and picked.resolve() == (efmi / "d3d11.dll").resolve()


def test_missing_target_loader_reports_failure_without_writing(env):
    """目标位置没有 loader ⇒ 如实报失败、**不写配置**（改过去只会更糟）。"""
    (env.real_efmi / "d3d11.dll").unlink()
    (env.real_efmi / "d3dx.ini").unlink()
    before = env.config_path.read_bytes()
    state = launcher.ensure_efmi_importer_folder(env.config)
    assert state["ok"] is False and state["changed"] is False
    assert "没有 loader" in state["message"]
    assert env.config_path.read_bytes() == before


# --------------------------------------------------------------------------
# ③ 配置改不动时，注入库**不再叠加第二条 loader**（防"两份 loader 撞死"）
# --------------------------------------------------------------------------
def _targets(env, monkeypatch) -> list[str]:
    dlss5 = Path(env.config.dlss5_path)
    dlss5.mkdir(parents=True, exist_ok=True)
    (dlss5 / "d3d12.dll").write_bytes(b"RESHADE-BASE")
    monkeypatch.setattr(launcher.reshade_integration, "reshade_base_wanted",
                        lambda _config: (True, "test"))
    return launcher.dlss5_injection_targets(env.config)


def test_no_second_loader_when_xxmi_injects_a_foreign_one(env, monkeypatch):
    """★ 现场复现：XXMI 会注入库里的那份 ⇒ 我们**不能**再列 `…\\XXMI\\EFMI\\d3d11.dll`。"""
    targets = _targets(env, monkeypatch)
    assert len(targets) == 1, f"★ 又叠加了第二条 loader，进程里就会有两份：{targets}"
    assert targets[0].lower().endswith("d3d12.dll")


def test_second_loader_is_still_listed_on_a_normal_layout(env, monkeypatch):
    """对照：`importer_folder` 正常时照旧列两条（顺序：ReShade 先、EFMI 后）。"""
    _write_config(env.root, env.launcher_exe,
                  importer_folder=str(env.real_efmi).replace("\\", "/"))
    targets = _targets(env, monkeypatch)
    assert len(targets) == 2
    assert targets[0].lower().endswith("d3d12.dll")
    assert targets[1].lower().endswith("d3d11.dll")


def test_foreign_folder_without_the_dll_is_still_foreign(env):
    """★ 判据不看"那个文件现在在不在"：XXMI 会把自带那份**部署到它认的目录里**再注入，
    所以"字段指向树外"本身就已经意味着会有另一份。"""
    (env.library / "d3d11.dll").unlink()
    assert launcher.xxmi_foreign_loader(env.config) is not None


def test_no_second_loader_even_when_foreign_folder_has_no_dll(env, monkeypatch):
    (env.library / "d3d11.dll").unlink()
    targets = _targets(env, monkeypatch)
    assert len(targets) == 1, f"★ 树外的 importer_folder 一样会引来第二份 loader：{targets}"


# --------------------------------------------------------------------------
# ④ 取证：进程里"同名 loader 进了两份"必须被报出来（否则"两条都在"看着一切正常）
# --------------------------------------------------------------------------
def _sample_with_two_loaders() -> dict:
    return {
        "module_count": 64,
        "third_party_count": 3,
        "modules": [
            r"C:\Users\lzh18\Downloads\library\d3d11.dll",
            r"C:\Users\lzh18\Downloads\runtime\builtin\XXMI\EFMI\d3d11.dll",
            r"C:\Users\lzh18\Downloads\runtime\dlss5\d3d12.dll",
        ],
    }


def test_duplicate_loaders_are_detected_in_process_snapshot(monkeypatch):
    monkeypatch.setattr(watchsample, "sample", lambda pid, **kw: _sample_with_two_loaders())
    state = injecttrace._process_state(4242)
    dupes = state["duplicate_loaders"]
    assert "d3d11.dll" in dupes and len(dupes["d3d11.dll"]) == 2
    assert state["expect_missing"] == [], "这两条确实都在进程里 —— 光看它看不出问题"


def test_duplicate_loaders_are_printed_in_timeline(monkeypatch):
    monkeypatch.setattr(watchsample, "sample", lambda pid, **kw: _sample_with_two_loaders())
    entry = {
        "at": "12:45:39",
        "phase": "game-started",
        "phase_label": "终末地启动后",
        "injection": {"enabled": True, "extra_libraries": ["d3d12.dll"], "signature_len": 140},
        "process": injecttrace._process_state(4242),
    }
    text = injecttrace.render([entry])
    assert "份不同路径的 d3d11.dll" in text
    assert "library\\d3d11.dll" in text


# --------------------------------------------------------------------------
# ⑤ 诊断包必须把这两件事写出来（下次再有这种包，不用靠旁证去猜）
# --------------------------------------------------------------------------
def test_diagnosis_summary_reports_importer_folder_and_both_loaders(env):
    from endfieldmodcontroller import diagnostics

    text = "\n".join(diagnostics._xxmi_summary(env.config))
    assert "EFMI.importer_folder" in text
    assert "d3dx.ini" in text
    assert "在这个 XXMI 目录内: **否**" in text
    assert "不是同一份" in text, f"诊断包必须点出『两侧 loader 不是同一份』：\n{text}"


def test_diagnosis_summary_is_quiet_on_a_normal_layout(env):
    from endfieldmodcontroller import diagnostics

    _write_config(env.root, env.launcher_exe,
                  importer_folder=str(env.real_efmi).replace("\\", "/"))
    text = "\n".join(diagnostics._xxmi_summary(env.config))
    assert "在这个 XXMI 目录内: 是" in text
    assert "不是同一份" not in text
