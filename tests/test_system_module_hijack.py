"""游戏目录的系统模块被 loader proxy 顶替 —— 自检必须把它指出来（2026-10-07 事故）。

**现场**：`<game>\\d3dcompiler_47.dll`（原版 4,524,496 B）与 `<game>\\vulkan-1.dll`
（原版 1,730,096 B）被 Poser / 乳摇 的 loader proxy（35,840 / 56,832 B）顶替时，
**每一次**启动都在 25–30 秒后以 `exit_code=0xC0000135 STATUS_DLL_NOT_FOUND` 结束
（`Player.log` 首行即 `Could not load symbol HGSetupCustomVulkan`）。

**为什么当时查不出来**：`initialize._check_proxy_backups` 的职责只是"proxy 有没有
`.bak` 可安全还原"——那种状态下它报的是"**可安全还原**"，于是自检**全部就绪**、
界面全绿，用户在界面上完全看不出游戏其实进不去。
`docs\\dev\\可用状态配方.md` 与 `docs\\dev\\交接文档.md` §5.3 记的「游戏能进」基线明确要求
这两个文件是**游戏原版**，所以"proxy 在位"本身就是一个必须报出来的状态。

本文件守住：

* proxy 在位 + 对应开关**开着** ⇒ 报待人工确认，**点名后果**（0xC0000135 /
  `HGSetupCustomVulkan`）并给出确切出口（关掉开关再一键启动）；
* proxy 在位 + 开关**都关着** ⇒ 一样要报（多半是独立安装的 Poser/乳摇 留下的），
  并指向「清理游戏目录注入」；
* 两个文件是原版 ⇒ 通过（不能把正常机器报成故障）；
* 定位不到游戏目录 ⇒ 静默跳过（不是故障）；
* 这一项必须排在**三套 loader 检查之后**——它要看的是"铺完之后"的最终状态；
* 诊断包 summary 里同样要写出冲突与后果（用户唯一的现场就是诊断包）。

全部离线：`detect_game_dir` 被 monkeypatch 到 `tmp_path`，不碰真实游戏目录。
"""
from __future__ import annotations

import inspect

import pytest

from endfieldmodcontroller import diagnostics, initialize, reshade_integration
from endfieldmodcontroller.config import AppConfig

# Poser 的 loader 标记（`reshade_integration._POSER_PROXY_MARKER`）——判定按标记，
# 不按文件名，所以这里造一个带标记的小文件就等价于"这是个 proxy"。
POSER_PROXY = b"MZ" + b"\x00" * 64 + b"[PROXY] plugins loaded via d3dcompiler_47.dll\n"
REAL_MODULE = b"MZ" + b"\x00" * 4096          # 没有 loader 标记 ⇒ 当作原版

PROXY_NAMES = ("d3dcompiler_47.dll", "vulkan-1.dll")
CHECK_KEY = "game_dir:system_modules"


@pytest.fixture()
def hijacked(tmp_path, monkeypatch):
    """造一个"两个系统模块都被 proxy 顶替"的游戏目录。"""
    root = tmp_path / "root"
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    game = root / "game"
    game.mkdir()
    for name in PROXY_NAMES:
        (game / name).write_bytes(POSER_PROXY)
        (game / f"{name}.bak").write_bytes(REAL_MODULE)   # .bak 在 ⇒ 旧的检查会报 OK
    (game / "plugin").mkdir()
    config = AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(root / "library"),
        dlss5_dir=str(runtime / "dlss5"),
        builtin_runtime_dir=str(runtime / "builtin"),
    )
    monkeypatch.setattr(AppConfig, "save", lambda self: None, raising=False)
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda *args, **kwargs: game, raising=False)
    return config, game


def _run(config: AppConfig) -> tuple[dict, dict | None]:
    report = initialize.Report()
    initialize._check_system_modules_not_hijacked(config, report, None)
    payload = report.to_dict()
    match = [c for c in payload["checks"] if c["key"] == CHECK_KEY]
    return payload, (match[0] if match else None)


def test_switch_on_reports_the_real_consequence(hijacked):
    """开关开着是我们自己铺的 —— 但仍必须报，因为可用配方要求这两个是原版。"""
    config, _ = hijacked
    config.poser_injection = True
    config.secondary_motion_injection = False

    payload, check = _run(config)

    assert check is not None and check["ok"] is False
    assert check["manual"] is True, "这是要让用户做的决定，不能只记成已修复"
    # 不能只说"有个 proxy"：必须点名后果与出口
    assert "0xC0000135" in check["message"]
    assert "HGSetupCustomVulkan" in check["message"]
    assert "Poser" in check["message"]
    assert "关掉" in check["message"]
    # 走 warnings 通道 ⇒ 启动日志里会出现 `WARN 初始化: ...`
    assert payload["pending_count"] == 1
    assert any(CHECK_KEY in warning for warning in payload["warnings"])


def test_switches_off_still_reported_and_points_at_cleanup(hijacked):
    """开关都关着却还有 proxy ⇒ 多半是独立安装留下的，要指向清理入口。"""
    config, _ = hijacked
    config.poser_injection = False
    config.secondary_motion_injection = False

    _, check = _run(config)

    assert check is not None and check["ok"] is False
    assert check["manual"] is True
    assert "清理游戏目录注入" in check["message"]
    assert "0xC0000135" in check["message"]


def test_both_switches_listed_when_both_are_on(hijacked):
    config, _ = hijacked
    config.poser_injection = True
    config.secondary_motion_injection = True

    _, check = _run(config)

    assert "Poser" in check["message"] and "乳摇" in check["message"]


def test_original_modules_pass(hijacked):
    """正常机器（两个文件都是原版）不能被报成故障。"""
    config, game = hijacked
    for name in PROXY_NAMES:
        (game / name).write_bytes(REAL_MODULE)

    payload, check = _run(config)

    assert check is not None and check["ok"] is True
    assert check["manual"] is False
    assert payload["pending_count"] == 0


def test_missing_game_dir_is_skipped(tmp_path, monkeypatch):
    """定位不到游戏目录时静默跳过 —— 别的检查已经在报这一项了。"""
    config = AppConfig(
        runtime_dir=str(tmp_path / "runtime"),
        library_dir=str(tmp_path / "library"),
        dlss5_dir=str(tmp_path / "runtime" / "dlss5"),
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
    )
    monkeypatch.setattr(AppConfig, "save", lambda self: None, raising=False)
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda *args, **kwargs: None, raising=False)

    payload, check = _run(config)

    assert check is None
    assert payload["pending_count"] == 0


def test_only_system_modules_are_covered(hijacked):
    """只认这两个系统模块：别的 proxy 名（d3d12.dll / dxgi.dll…）不归这一项管。"""
    config, game = hijacked
    for name in PROXY_NAMES:
        (game / name).write_bytes(REAL_MODULE)
    (game / "dxgi.dll").write_bytes(POSER_PROXY)      # 合法用途的 proxy，不该被报

    _, check = _run(config)

    assert check is not None and check["ok"] is True


def test_ensure_all_runs_it_after_the_loader_checks():
    """必须排在三套 loader 检查之后 —— 它要看的是"铺完之后"的最终状态。"""
    src = inspect.getsource(initialize.ensure_all)
    call = "_check_system_modules_not_hijacked(config, report, log)"
    assert call in src, "新自检必须接进 ensure_all，否则界面照样全绿"
    assert src.index("_check_proxy_backups(config, report, log)") < src.index(call)


def test_diagnostics_summary_names_the_conflict(hijacked):
    """诊断包 summary 是用户唯一的现场 —— 也要写清冲突与后果。"""
    config, game = hijacked
    config.poser_injection = True

    blob = "\n".join(diagnostics._game_injection_summary(config, game))

    assert "系统模块被 loader proxy 顶替" in blob
    assert "0xC0000135" in blob
    assert "HGSetupCustomVulkan" in blob


def test_diagnostics_summary_quiet_when_clean(hijacked):
    config, game = hijacked
    for name in PROXY_NAMES:
        (game / name).write_bytes(REAL_MODULE)

    blob = "\n".join(diagnostics._game_injection_summary(config, game))

    assert "系统模块被 loader proxy 顶替" not in blob
    assert "没有检测到第三方注入 proxy" in blob
