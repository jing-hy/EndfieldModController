"""诊断包采集的回归测试（2026-10-04）。

对应 issue #13 的三条缺陷 + 用户当天的要求（「日志包尽量多塞东西，不要老是判据不够」）：

① **EFMI 路径取错** ⇒ 报表里一串 `exists=False` 误报（真实 staging 在 config 指的位置）；
② **一处异常吞掉后面全部采集** ⇒ 最需要现场的那次，取证代码自己整段放弃；
③ **`ReShade.log` 只从游戏目录抓** ⇒ 它其实按 `RESHADE_BASE_PATH_OVERRIDE` 落在
   `runtime\\reshade\\`，于是那份真实日志整条丢失（包里连占位都没有）；
④ **采集失败静默** ⇒ 分不清"没有现场"和"没去抓"；
⑤ **缺 `.bak` 时 `remove_injection` 会删掉 proxy 却不补回原版** ⇒ 游戏目录永久缺
   `d3dcompiler_47.dll`（违反"失败保留原状"红线）。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from endfieldmodcontroller import diagnostics, initialize, secondary_motion
from endfieldmodcontroller.config import AppConfig


def _make_config(tmp_path: Path, *, staging: Path | None = None, loader: Path | None = None):
    """造一个"数据根 + 游戏目录"齐全的配置（游戏目录固定为 `<tmp>/game`）。"""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "runtime_dir": str(runtime),
        "library_dir": str(tmp_path / "library"),
        "game_exe": str(game / "Endfield.exe"),
        # ⚠️ 全部指到 tmp 下：相对路径会按数据根解析，不写死的话测试会读到
        #    开发机上**真实存在**的 runtime/dlss5（上一次实测就踩到：包里混进了
        #    本机的 dlss5-feed.log，断言随即失败）。
        "dlss5_dir": str(runtime / "dlss5"),
        "builtin_runtime_dir": str(runtime / "builtin"),
        "secondary_motion_dir": str(runtime / "secondary_motion"),
        "poser_dir": str(runtime / "poser"),
        "dependency_manifest": str(tmp_path / "dependencies.json"),
    }
    if staging is not None:
        kwargs["staging_mods_dir"] = str(staging)
    if loader is not None:
        kwargs["migoto_loader"] = str(loader)
    return AppConfig(**kwargs), game, runtime


def _quiet_collectors(monkeypatch) -> None:
    """把会碰真实机器/网络的采集换成空实现（测试只验证"收没收、留没留痕"）。"""
    monkeypatch.setattr(diagnostics, "collect_environment_report", lambda *a, **k: ("(测试环境)", ""))
    monkeypatch.setattr(diagnostics, "player_log_candidates", lambda *a, **k: [])
    monkeypatch.setattr(diagnostics, "wer_report_paths", lambda *a, **k: [])
    monkeypatch.setattr(diagnostics, "unity_crash_logs", lambda *a, **k: [])


def _write_proxy(path: Path, *, size: int = 2048) -> None:
    """造一个"看起来像 loader proxy"的文件（判定靠二进制里的标记串）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"[LOADER] started" + b"\x00" * max(0, size - 16))


# ---------------------------------------------------------------------------
# ① EFMI 路径：以 config 为准，loader 推导只作兜底（**两个都探**）
# ---------------------------------------------------------------------------


def test_efmi_probe_paths_keeps_config_first_and_loader_as_fallback(tmp_path: Path):
    efmi_mods = tmp_path / "XXMI Launcher" / "EFMI" / "Mods"
    efmi_mods.mkdir(parents=True)
    loader_dir = tmp_path / "d3dxSkinManage" / "work"
    loader_dir.mkdir(parents=True)
    (loader_dir / "loader.exe").write_bytes(b"MZ")

    config, _game, _runtime = _make_config(tmp_path, staging=efmi_mods, loader=loader_dir / "loader.exe")
    probes = diagnostics.efmi_probe_paths(config)

    staging = [str(path) for _label, path in probes["staging"]]
    assert staging[0] == str(efmi_mods)                       # config 优先
    assert any("d3dxSkinManage" in item for item in staging)  # 兜底位置也在（不静默切换）
    ini = [str(path) for _label, path in probes["user_ini"]]
    assert any(item.endswith("d3dx_user.ini") for item in ini)


def test_log_efmi_state_reports_real_staging_and_survives_missing_dir(tmp_path: Path):
    """缺陷一 + 二：真实 staging 必须报 `exists=True`；不存在的候选**不许抛异常**，
    而且它后面的 loader 日志采集**仍然要执行**。"""
    staging = tmp_path / "EFMI" / "Mods"
    (staging / "MC_Controller").mkdir(parents=True)
    (staging / "MC_Controller" / "controller.ini").write_text("", encoding="utf-8")
    (staging / "MC_Probe.ini").write_text("", encoding="utf-8")
    (staging / "EndfieldModControllerManaged").mkdir()
    loader_dir = tmp_path / "work"
    loader_dir.mkdir()
    (loader_dir / "loader.exe").write_bytes(b"MZ")
    (loader_dir / "d3d11_log.txt").write_text("MC_Probe attached\n", encoding="utf-8")

    config, _game, runtime = _make_config(tmp_path, staging=staging, loader=loader_dir / "loader.exe")
    # 故意传一个**不存在**的 staging（旧代码就是这么误报的）
    diagnostics.log_efmi_state(config, staging_root=tmp_path / "nope" / "Mods")

    text = (runtime / "launch.log").read_text(encoding="utf-8", errors="replace")
    assert "staged probe" in text and "exists=True" in text
    assert "staged Mods 目录不存在" in text                 # 不存在的候选如实报出来
    assert "loader d3d11_log token" in text                 # ← 缺陷二回归：后面的采集没被吞掉


# ---------------------------------------------------------------------------
# ③④ 采集失败留痕 + ReShade.log 多候选
# ---------------------------------------------------------------------------


def test_capture_tail_writes_placeholder_and_manifest_when_source_missing(tmp_path: Path):
    manifest = diagnostics._new_capture_manifest()
    target = tmp_path / "logs" / "ReShade-x.log"
    ok = diagnostics._capture_tail(tmp_path / "nope.log", target,
                                   manifest=manifest, arcname="logs/ReShade-x.log")
    assert ok is False
    assert target.is_file(), "采集不到也要留占位，不能整条消失"
    assert "采集不到" in target.read_text(encoding="utf-8")
    assert manifest[0]["status"] == "missing"
    assert "logs/ReShade-x.log" in diagnostics.capture_manifest_text(manifest)


def test_bundle_collects_reshade_log_from_runtime_dir(tmp_path: Path, monkeypatch):
    """缺陷三回归：`ReShade.log` 实际在 `runtime\\reshade\\`，必须被收进包。"""
    _quiet_collectors(monkeypatch)
    staging = tmp_path / "EFMI" / "Mods"
    staging.mkdir(parents=True)
    config, game, runtime = _make_config(tmp_path, staging=staging)
    reshade_dir = runtime / "reshade"
    reshade_dir.mkdir(parents=True)
    (reshade_dir / "ReShade.log").write_text(
        "Initializing crosire's ReShade version '6.8.0'\nUnregistered add-on \"x\"\n", encoding="utf-8")

    bundle = diagnostics.create_diagnostic_bundle(config, game_dir=game, note="test")

    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        manifest = archive.read("capture-manifest.txt").decode("utf-8")
        inventory = archive.read("game-inventory.txt").decode("utf-8")
        assert any(name.startswith("reshade/runtime-ReShade.log") for name in names), names
        assert "environment.txt" in names
        assert "capture-manifest.txt" in names
        assert "game-inventory.txt" in names
    assert "reshade/runtime-ReShade.log" in manifest
    assert "[ok] reshade/runtime-ReShade.log" in manifest
    assert "游戏目录清单" in inventory


def test_manifest_marks_stale_logs_not_from_this_run(tmp_path: Path, monkeypatch):
    """旧日志要被标出来："上次运行留下的旧文件"不能当本次现场用。"""
    _quiet_collectors(monkeypatch)
    staging = tmp_path / "EFMI" / "Mods"
    staging.mkdir(parents=True)
    config, game, _runtime = _make_config(tmp_path, staging=staging)
    stale = game / "d3d11_log.txt"
    stale.write_text("old run\n", encoding="utf-8")

    old = stale.stat().st_mtime - 3600
    import os

    os.utime(stale, (old, old))
    diagnostics._LAST_GAME_START = 0.0
    manifest = diagnostics._new_capture_manifest()
    diagnostics._capture_tail(stale, tmp_path / "out.log", manifest=manifest, arcname="logs/out.log")
    assert manifest[0]["fresh"] is None            # 不知道游戏什么时候起的 → 不下结论

    diagnostics._LAST_GAME_START = stale.stat().st_mtime + 60
    manifest2 = diagnostics._new_capture_manifest()
    diagnostics._capture_tail(stale, tmp_path / "out2.log", manifest=manifest2, arcname="logs/out2.log")
    assert manifest2[0]["fresh"] is False
    assert "旧文件" in diagnostics.capture_manifest_text(manifest2)
    diagnostics._LAST_GAME_START = 0.0


def test_sanitized_xxmi_config_hides_signatures(tmp_path: Path):
    launcher = tmp_path / "XXMI" / "Resources" / "Bin" / "XXMI Launcher.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"MZ")
    config_path = tmp_path / "XXMI" / "XXMI Launcher Config.json"
    config_path.write_text(
        '{"Launcher": {"active_importer": "EFMI"}, '
        '"Importers": {"EFMI": {"Importer": {"extra_libraries_signature": "AAAA"}}}, '
        '"Security": {"user_signature": "BBBBBB"}}',
        encoding="utf-8",
    )
    config, _game, _runtime = _make_config(tmp_path, staging=tmp_path / "Mods")
    config.xxmi_launcher = str(launcher)

    text, note = diagnostics.sanitized_xxmi_config(config)

    assert text and "AAAA" not in text and "BBBBBB" not in text
    assert "<已省略，长度 4>" in text and "<已省略，长度 6>" in text
    assert note == ""


# ---------------------------------------------------------------------------
# ⑤ 缺 `.bak` 的 loader proxy：先补齐，补不到就**保留注入不动**
# ---------------------------------------------------------------------------


def _fake_system32(tmp_path: Path, name: str, *, size: int = 300_000) -> Path:
    root = tmp_path / "windows"
    target = root / "System32" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"MZ" + b"\x00" * max(0, size - 2))
    return root


def test_ensure_proxy_backup_copies_system_module(tmp_path: Path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    _write_proxy(game / "d3dcompiler_47.dll")
    monkeypatch.setenv("SystemRoot", str(_fake_system32(tmp_path, "d3dcompiler_47.dll")))

    backup = secondary_motion.ensure_proxy_backup(game, "d3dcompiler_47.dll", None)

    assert backup is not None and backup.is_file()
    assert backup.stat().st_size >= secondary_motion.PROXY_MAX_SIZE


def test_remove_injection_keeps_proxy_when_no_backup_available(tmp_path: Path, monkeypatch):
    """红线回归：**没有原版可放回时，绝不允许把 proxy 删掉**。"""
    config, game, _runtime = _make_config(tmp_path, staging=tmp_path / "Mods")
    (game / "plugin").mkdir(parents=True)
    proxy = game / "d3dcompiler_47.dll"
    _write_proxy(proxy)
    monkeypatch.setenv("SystemRoot", str(_fake_system32(tmp_path, "something_else.dll")))  # 拿不到原版

    result = secondary_motion.remove_injection(config, log=None)

    assert proxy.is_file(), "拿不到原版还删 proxy ⇒ 游戏目录永久缺这个系统模块"
    assert result["warnings"]


def test_remove_injection_restores_from_system32_when_backup_missing(tmp_path: Path, monkeypatch):
    config, game, _runtime = _make_config(tmp_path, staging=tmp_path / "Mods")
    (game / "plugin").mkdir(parents=True)
    proxy = game / "d3dcompiler_47.dll"
    _write_proxy(proxy)
    monkeypatch.setenv("SystemRoot", str(_fake_system32(tmp_path, "d3dcompiler_47.dll")))

    secondary_motion.remove_injection(config, log=None)

    assert proxy.is_file()
    assert not secondary_motion._is_proxy(proxy), "应该已经换回系统原版，而不是留着 proxy"
    assert (game / "d3dcompiler_47.dll.bak").is_file()


def test_self_check_fixes_missing_proxy_backup(tmp_path: Path, monkeypatch):
    """自检要**自动补** .bak（`fixed=True`），而不是把这种状态当"全绿"。"""
    config, game, _runtime = _make_config(tmp_path, staging=tmp_path / "Mods")
    (game / "plugin").mkdir(parents=True)
    _write_proxy(game / "d3dcompiler_47.dll")
    _write_proxy(game / "vulkan-1.dll")
    monkeypatch.setenv("SystemRoot", str(_fake_system32(tmp_path, "d3dcompiler_47.dll")))
    root = Path(__import__("os").environ["SystemRoot"])
    (root / "System32" / "vulkan-1.dll").write_bytes(b"MZ" + b"\x00" * 300_000)

    report = initialize.Report()
    initialize._check_proxy_backups(config, report, None)

    checks = {item["key"]: item for item in report.to_dict()["checks"]}
    assert checks["game_dir:proxy_backup"]["ok"] is True
    assert checks["game_dir:proxy_backup"]["fixed"] is True
    assert (game / "d3dcompiler_47.dll.bak").is_file()
    assert (game / "vulkan-1.dll.bak").is_file()


def test_self_check_warns_when_backup_cannot_be_fixed(tmp_path: Path, monkeypatch):
    config, game, _runtime = _make_config(tmp_path, staging=tmp_path / "Mods")
    (game / "plugin").mkdir(parents=True)
    _write_proxy(game / "d3dcompiler_47.dll")
    monkeypatch.setenv("SystemRoot", str(_fake_system32(tmp_path, "nothing.dll")))

    report = initialize.Report()
    initialize._check_proxy_backups(config, report, None)

    checks = {item["key"]: item for item in report.to_dict()["checks"]}
    check = checks["game_dir:proxy_backup"]
    assert check["ok"] is False and check["manual"] is True
    assert "还原" in check["message"]


def test_end_to_end_matches_real_feedback_shape(tmp_path: Path, monkeypatch):
    """复刻 2026-10-04 那份反馈包的形状，验证新包能回答"当时回答不了"的问题。

    形状（逐条来自那份包）：
      * `migoto_loader` 指向**另一套** 3DMigoto（d3dxSkinManage），staging 却在 XXMI/EFMI；
      * 游戏目录 `d3dcompiler_47.dll` / `vulkan-1.dll` 是 loader proxy，且**没有 `.bak`**；
      * `ReShade.log` 在 `runtime\\reshade\\`（游戏目录里没有）；
      * `runtime\\dlss5\\dlss5-feed.log` 里有 attach 与 clean shutdown。
    期望：包里**一眼能看到** proxy 归属 / 无原版备份 / ReShade 现场 / 两侧日志与采集清单。
    """
    _quiet_collectors(monkeypatch)
    monkeypatch.setenv("SystemRoot", str(_fake_system32(tmp_path, "nothing-here.dll")))

    efmi_mods = tmp_path / "XXMI Launcher" / "EFMI" / "Mods"
    (efmi_mods / "MC_Controller").mkdir(parents=True)
    (efmi_mods / "MC_Probe.ini").write_text("", encoding="utf-8")
    other_work = tmp_path / "d3dxSkinManage" / "home" / "Arknights Endfield" / "work"
    other_work.mkdir(parents=True)
    (other_work / "loader.exe").write_bytes(b"MZ")
    (other_work / "d3d11_log.txt").write_text("historical run\n", encoding="utf-8")

    config, game, runtime = _make_config(tmp_path, staging=efmi_mods, loader=other_work / "loader.exe")
    (game / "plugin").mkdir(parents=True)
    (game / "plugin" / "sbm.dll").write_bytes(b"\x00" * 4096)
    (game / "plugin" / "sbm_log.txt").write_text("[LOADER] started\n", encoding="utf-8")
    _write_proxy(game / "d3dcompiler_47.dll", size=35840)
    _write_proxy(game / "vulkan-1.dll", size=56832)
    reshade_dir = runtime / "reshade"
    reshade_dir.mkdir(parents=True)
    (reshade_dir / "ReShade.log").write_text("Initializing crosire's ReShade\n", encoding="utf-8")
    dlss5 = runtime / "dlss5"
    dlss5.mkdir(parents=True)
    (dlss5 / "dlss5-feed.log").write_text("11:04:02 attached.\n11:04:22 shut down cleanly.\n", encoding="utf-8")

    bundle = diagnostics.create_diagnostic_bundle(config, game_dir=game, note="auto-postmortem: exit_code=3221225781")

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        inventory = archive.read("game-inventory.txt").decode("utf-8")
        summary = archive.read("summary.txt").decode("utf-8")
        manifest = archive.read("capture-manifest.txt").decode("utf-8")
        feed = archive.read("dlss5/dlss5-feed.log").decode("utf-8")

    # 游戏目录注入：谁铺的、有没有原版备份 —— 一眼可见
    assert "loader proxy" in inventory
    assert "原版备份" in inventory and "缺失" in inventory
    assert "plugin\\sbm.dll" in inventory or "sbm.dll" in inventory
    assert "游戏目录注入" in summary
    # ReShade 现场（缺陷三）：runtime\reshade 那份进包了，游戏目录那份如实记 missing
    assert "reshade/runtime-ReShade.log" in names
    assert "[ok] reshade/runtime-ReShade.log" in manifest
    assert "dlss5/dlss5-feed.log" in names and "shut down cleanly" in feed
    # 两侧日志都在清单里（EFMI 侧 + loader 侧）
    assert "loader/efmi-d3d11_log.txt" in manifest or "loader/loader-d3d11_log.txt" in manifest
    assert "missing" in manifest


# ---------------------------------------------------------------------------
# ⑤ 游戏 SDK 日志 + 「游戏自有文件本次写过没有」（2026-10-05 补的判据）
# ---------------------------------------------------------------------------


def test_bundle_collects_game_sdk_logs(tmp_path: Path, monkeypatch):
    """`sdklogs\\*.log` 必须**收内容**进包，不能只列个文件名。

    为什么（2026-10-05）：反馈者那台游戏只活 20 秒、**一帧都没渲染**、Windows 侧一条
    WER 都没有 —— 那种现场里唯一能回答"游戏走到哪一步才死的"就是游戏自己的 SDK
    事件日志。以前 `sdklogs\\` 只出现在"值得看的子目录"里（只有文件名与大小），
    等于知道那儿有东西却看不到内容 ⇒ 判据又断一次。
    """
    _quiet_collectors(monkeypatch)
    staging = tmp_path / "EFMI" / "Mods"
    staging.mkdir(parents=True)
    config, game, _runtime = _make_config(tmp_path, staging=staging)
    sdklogs = game / "sdklogs"
    sdklogs.mkdir(parents=True)
    (sdklogs / "HGEventLog.log").write_text("sdk event line\n", encoding="utf-8")

    bundle = diagnostics.create_diagnostic_bundle(config, game_dir=game, note="test")

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        manifest = archive.read("capture-manifest.txt").decode("utf-8")
        body = archive.read("game/sdklogs/HGEventLog.log").decode("utf-8")

    assert "game/sdklogs/HGEventLog.log" in names, names
    assert "sdk event line" in body
    assert "game/sdklogs/HGEventLog.log" in manifest


def test_game_dir_inventory_flags_files_not_written_this_run(tmp_path: Path, monkeypatch):
    """「游戏自有文件：本次运行写过没有」这一段必须存在 **而且判对**。

    现场用法：游戏跑了 20 秒，而 `sdklogs\\HGEventLog.log` / `eld_Endfield.db` 的 mtime
    全停在**上一次运行** ⇒ 一眼看出"游戏死得非常早"。以前这个结论要人肉把清单里每个
    时间戳跟启动时刻对一遍才知道。反向验证：删掉那一段 ⇒ 本测试变红。
    """
    import os
    import time as _time

    config, game, _runtime = _make_config(tmp_path, staging=tmp_path / "Mods")
    (game / "sdklogs").mkdir(parents=True, exist_ok=True)
    (game / "sdklogs" / "HGEventLog.log").write_text("old", encoding="utf-8")
    (game / "eld_Endfield.db").write_bytes(b"db")
    old = 1_600_000_000
    os.utime(game / "sdklogs" / "HGEventLog.log", (old, old))
    os.utime(game / "eld_Endfield.db", (old, old))

    monkeypatch.setattr(diagnostics, "_LAST_GAME_START", _time.time())
    text = diagnostics.game_dir_inventory_text(config, game)
    assert "游戏自有文件：本次运行写过没有" in text
    assert "· 本次没写" in text and "HGEventLog.log" in text
    assert "本次运行写过 0 个" in text

    # 本次真的写过 ⇒ 必须标成 ✔（否则"没写"这个判据没有对照，等于永远在报警）
    (game / "sdklogs" / "HGEventLog.log").write_text("new", encoding="utf-8")
    text2 = diagnostics.game_dir_inventory_text(config, game)
    assert "✔ 本次写过" in text2 and "本次运行写过 1 个" in text2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
