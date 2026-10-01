"""2026-10-01 两个真 bug 的回归测试（来自一份真实诊断包的分析结论）。

**① DLSS5 preset 判据自相矛盾** —— 判据要求 `TechniqueSorting`/`EffectSorting` 里
Launchpad 排在 DLSS5_Feed **之前**，而写入代码写的是 `[feed, launchpad]`（**反的**）：
于是每轮一键启动都报「DLSS5 preset 需要修复」、修完自己又判不过 —— 死循环，
而 DLSS5 其实完全正常（诊断包里从 10:33 报到 11:09，把用户和排查者一起带偏）。
现在：**判据只看"两项都启用"**，顺序降级为提示；写入顺序统一成 provider 在前。

**② 游戏目录定位失败时完全静默** —— `ensure_xxmi_game_folder()` 第一步就要
`detect_game_dir()`，拿不到就直接 return（连 message 都没人记），于是
`Launcher.active_importer` / `Launcher.enabled_importers` / `game_folder` 三个字段
一直写不进去（诊断包里 `active_importer: None`），表现是"XXMI 界面里没有终末地的启动按钮"。
现在：① `detect_game_dir` 会**遍历所有 importer**、并**从 `XXMI Launcher Log.txt` 捞真实路径**；
② 失败会写日志并把原因交给调用方（自检 warnings）；③ 定位成功且 `game_exe` 原本为空时回填。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from endfieldmodcontroller import initialize, launcher, reshade_integration
from endfieldmodcontroller.config import AppConfig

FEED = "DLSS5_Feed@DLSS5_Feed.fx"
LAUNCHPAD = "MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx"


def _preset_config(tmp_path: Path, preset_text: str, monkeypatch) -> tuple[AppConfig, Path]:
    """造一个最小 dlss5 目录（ReShade.ini + ReShadePreset.ini）并指给 config。"""
    dlss5 = tmp_path / "dlss5"
    dlss5.mkdir(parents=True, exist_ok=True)
    (dlss5 / "ReShade.ini").write_text("PresetPath=ReShadePreset.ini\n", encoding="utf-8")
    preset_path = dlss5 / "ReShadePreset.ini"
    preset_path.write_text(preset_text, encoding="utf-8")
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"))
    config.dlss5_dir = str(dlss5)
    config.dlss5_addon_enabled = True
    monkeypatch.setattr(config, "save", lambda: None, raising=False)
    return config, preset_path


# --------------------------------------------------------------- ① preset 判据
def test_both_enabled_with_reversed_order_is_accepted(tmp_path, monkeypatch):
    """两项都启用、但顺序与"要求"相反（ReShade 自己写回的形态）→ **不算问题、不改文件**。"""
    preset = (
        "PreprocessorDefinitions=DLSS5_MV_PROVIDER=1\n"
        f"Techniques={FEED},{LAUNCHPAD}\n"
        f"TechniqueSorting={FEED},{LAUNCHPAD}\n"
        "EffectSorting=DLSS5_Feed.fx,MartysMods_LAUNCHPAD.fx\n"
    )
    config, preset_path = _preset_config(tmp_path, preset, monkeypatch)
    report = initialize.Report()
    logs: list[str] = []

    initialize._check_dlss5_preset(config, report, logs.append)

    assert not any("需要修复" in line for line in logs), logs
    assert any("已启用" in c["message"] for c in report.checks if c["key"] == "dlss5:preset")
    assert preset_path.read_text(encoding="utf-8") == preset, "判据通过时不该改写文件"
    assert report.to_dict()["ok"] is True


def test_missing_technique_is_repaired_with_provider_first(tmp_path, monkeypatch):
    """真缺项 → 仍然修；而且写进去的顺序必须是 **provider 在前**（与判据一致，否则又死循环）。"""
    config, preset_path = _preset_config(tmp_path, "Techniques=\n", monkeypatch)
    report = initialize.Report()
    logs: list[str] = []

    initialize._check_dlss5_preset(config, report, logs.append)

    assert any("需要修复" in line for line in logs), logs
    text = preset_path.read_text(encoding="utf-8")
    techniques = next(line for line in text.splitlines() if line.startswith("Techniques="))
    sorting = next(line for line in text.splitlines() if line.startswith("TechniqueSorting="))
    effects = next(line for line in text.splitlines() if line.startswith("EffectSorting="))
    # 注意大小写：Techniques/TechniqueSorting 里是 `MartysMods_Launchpad`，
    # EffectSorting 里是文件名 `MartysMods_LAUNCHPAD.fx`。
    for line, provider, feed in (
        (techniques, LAUNCHPAD, FEED),
        (sorting, LAUNCHPAD, FEED),
        (effects, "MartysMods_LAUNCHPAD.fx", "DLSS5_Feed.fx"),
    ):
        assert line.index(provider) < line.index(feed), line


def test_repair_then_second_pass_is_stable(tmp_path, monkeypatch):
    """修完再跑一遍必须"已经 OK"（这正是原来死循环的地方）。"""
    config, preset_path = _preset_config(tmp_path, "Techniques=\n", monkeypatch)
    initialize._check_dlss5_preset(config, initialize.Report(), lambda _m: None)

    logs: list[str] = []
    second = initialize.Report()
    initialize._check_dlss5_preset(config, second, logs.append)

    assert not any("需要修复" in line for line in logs), f"第二轮仍在报需要修复: {logs}"
    assert second.to_dict()["ok"] is True


# --------------------------------------------------------------- ② 游戏目录定位
def _fake_xxmi(tmp_path: Path, *, importers: dict, log_text: str = "") -> tuple[Path, Path]:
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    xxmi = tmp_path / "xxmi"
    (xxmi / "Resources" / "Bin").mkdir(parents=True, exist_ok=True)
    launcher_exe = xxmi / "Resources" / "Bin" / "XXMI Launcher.exe"
    launcher_exe.write_bytes(b"MZ")
    (xxmi / "XXMI Launcher Config.json").write_text(
        json.dumps({"Launcher": {"active_importer": "EFMI"}, "Importers": importers},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    if log_text:
        (xxmi / "XXMI Launcher Log.txt").write_text(log_text, encoding="utf-8")
    return xxmi, launcher_exe


def test_detect_game_dir_reads_other_importers(tmp_path):
    """EFMI 的 game_folder 为空、但别的 importer 有 → 也要能定位（原来只读 EFMI 一家）。"""
    xxmi, launcher_exe = _fake_xxmi(tmp_path, importers={
        "EFMI": {"Importer": {}},
        "GIMI": {"Importer": {"game_folder": str(tmp_path / "game")}},
    })
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"), xxmi_launcher=str(launcher_exe))

    assert reshade_integration.detect_game_dir(config, allow_scan=False) == tmp_path / "game"


def test_detect_game_dir_falls_back_to_xxmi_log(tmp_path):
    """配置里一个 game_folder 都没有 → 从 XXMI 自己的启动日志里捞（他这台游戏在 W 盘就是这么救的）。"""
    game = tmp_path / "game"
    xxmi, launcher_exe = _fake_xxmi(
        tmp_path,
        importers={"EFMI": {"Importer": {}}},
        log_text=(
            "2026-10-01 11:09:26 DEBUG Successfully injected DLL to process Endfield.exe "
            "(PID: 4508): W:\\x\\d3d12.dll\n"
            f"exe_path=WindowsPath('{game.as_posix()}/Endfield.exe'), start_args=['-force-d3d11'], "
            "work_dir='x', use_hook=False)\n"
        ),
    )
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"), xxmi_launcher=str(launcher_exe))

    assert reshade_integration.detect_game_dir(config, allow_scan=False) == game


def test_ensure_xxmi_game_folder_logs_when_game_dir_unknown(tmp_path, monkeypatch):
    """定位不到 → **必须写日志并带上可读原因**（原来完全静默）。"""
    config = AppConfig(
        runtime_dir=str(tmp_path / "runtime"),
        # 内置运行环境也指到 tmp：留空的 `xxmi_launcher` 会回落到内置那份
        # （2026-10-01 新增行为），这里刻意让它没有可回落的东西。
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
    )
    monkeypatch.setattr(config, "save", lambda: None, raising=False)
    logs: list[str] = []

    state = launcher.ensure_xxmi_game_folder(config, log=logs.append)

    assert state["ok"] is False
    assert "未配置 XXMI Launcher" in state["message"] or "未定位到游戏目录" in state["message"]
    assert logs and any("XXMI 游戏目录" in line for line in logs)


def test_nr_binding_check_explains_native_dlss(tmp_path):
    """游戏内超分选成"原生/DLAA"时，DLSS5 的 NR 永远绑不上 —— 自检要说清并给动作。

    真实反馈（2026-10-01，v0.8.0）：面板 `成功NR帧 0` / `0xBAD00001`，
    `ReShade.log` 原文 `NR upscaling is not applicable: the game's DLSS already renders at
    output resolution`。
    """
    from endfieldmodcontroller import initialize

    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    config = AppConfig(
        runtime_dir=str(tmp_path / "runtime"),
        dlss5_dir=str(dlss5),
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
    )
    log = dlss5 / "ReShade.log"
    log.write_text(
        "Initializing crosire's ReShade version '6.8.0'\n"
        "DLSS5 Generic: NR upscaling is not applicable: the game's DLSS already renders at "
        "output resolution (2560x1440 vs output 2560x1440 (native))\n"
        "DLSS5 Generic: NR feature create failed with 0xbad00001\n",
        encoding="utf-8",
    )
    report = initialize.Report()
    initialize._check_dlss5_nr_binding(config, report, None)
    check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:nr_binding")
    assert check["ok"] is False
    assert "原生" in check["message"] and "质量" in check["message"]

    # 老日志里的失败不许拿来吓人：只看最后一次运行
    log.write_text(
        "Initializing crosire's ReShade\nNR feature create failed with 0xbad00001\n"
        "Initializing crosire's ReShade\nDLSS5 Generic: feature ready: 2560x1440\n",
        encoding="utf-8",
    )
    report = initialize.Report()
    initialize._check_dlss5_nr_binding(config, report, None)
    check = next(c for c in report.to_dict()["checks"] if c["key"] == "dlss5:nr_binding")
    assert check["ok"] is True, check


def test_xxmi_launcher_falls_back_to_builtin(tmp_path):
    """`xxmi_launcher` 留空 → 自动找内置那份（用户 2026-10-01：「xxmi 如果留空应该就找内置
    正常会放的地方，没有就下载」）。"""
    from endfieldmodcontroller.config import builtin_xxmi_launcher

    builtin = tmp_path / "runtime" / "builtin" / "XXMI" / "Resources" / "Bin"
    builtin.mkdir(parents=True)
    exe = builtin / "XXMI Launcher.exe"
    exe.write_bytes(b"MZ")

    config = AppConfig(
        runtime_dir=str(tmp_path / "runtime"),
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
    )
    assert config.xxmi_launcher_path == exe
    assert builtin_xxmi_launcher(tmp_path / "runtime" / "builtin") == exe

    # 填了但文件已经不在（被删/被整合包挪走）→ 也回落到内置，而不是直接报"找不到"
    config.xxmi_launcher = str(tmp_path / "gone" / "XXMI Launcher.exe")
    assert config.xxmi_launcher_path == exe


def test_ensure_xxmi_game_folder_writes_fields_and_backfills(tmp_path, monkeypatch):
    """定位成功 → 写入三个字段 + game_folder；并且**回填 game_exe**（原本为空时才写）。"""
    xxmi, launcher_exe = _fake_xxmi(tmp_path, importers={
        "EFMI": {"Importer": {"game_folder": str(tmp_path / "game")}},
    })
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                       xxmi_launcher=str(launcher_exe), game_exe="")
    monkeypatch.setattr(config, "save", lambda: None, raising=False)

    state = launcher.ensure_xxmi_game_folder(config, log=lambda _m: None)

    assert state["ok"] is True
    data = json.loads((xxmi / "XXMI Launcher Config.json").read_text(encoding="utf-8"))
    assert data["Importers"]["EFMI"]["Importer"]["game_folder"] == str(tmp_path / "game")
    assert data["Launcher"]["active_importer"] == "EFMI"
    assert data["Launcher"]["enabled_importers"] == ["EFMI"]
    assert config.game_exe.endswith("Endfield.exe"), "应该回填 game_exe 供下次直接命中"


def test_ensure_xxmi_game_folder_does_not_overwrite_user_game_exe(tmp_path, monkeypatch):
    """用户自己填过 `game_exe` → **不许覆盖**（issue #4 的教训）。"""
    xxmi, launcher_exe = _fake_xxmi(tmp_path, importers={
        "EFMI": {"Importer": {"game_folder": str(tmp_path / "game")}},
    })
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                       xxmi_launcher=str(launcher_exe), game_exe=r"D:\my\own\Endfield.exe")
    monkeypatch.setattr(config, "save", lambda: None, raising=False)

    launcher.ensure_xxmi_game_folder(config, log=lambda _m: None)

    assert config.game_exe == r"D:\my\own\Endfield.exe"
