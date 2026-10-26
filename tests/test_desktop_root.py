# SPDX-License-Identifier: GPL-3.0-or-later
"""「程序被放在桌面运行」的处理（用户 2026-10-26）。

两轮需求：
① 先说「发现 exe 在桌面就弹窗说明，可忽略或清空已生成依赖并退出」；
② 再改成「在桌面启动直接不启动：到 D 盘（回退 C 盘）建文件夹、复制 exe 过去、
   桌面建快捷方式、启动复制后的 exe 并关闭这个实例」—— 当前代码走这条。

这里钉住三件最要紧的事：
* 判定只比「数据根 == 桌面」；
* 搬家**只在打包后的 exe** 且**没搬过**时才做（防循环）；
* 清理只删程序自己生成的那几项，**library（用户的 Mod 库）永不删**。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from endfieldmodcontroller import desktop_root as DR


def _config(tmp_path, base=None):
    root = base or (tmp_path / "app")
    root.mkdir(parents=True, exist_ok=True)
    (root / "runtime").mkdir(exist_ok=True)
    return SimpleNamespace(base_dir=str(root), runtime_path=root / "runtime")


def _fake_exe(folder: Path) -> Path:
    exe = folder / "EndfieldModController.exe"
    exe.write_bytes(b"MZ fake")
    return exe


# ---------------------------------------------------------------- 桌面判定
def test_on_desktop_when_base_equals_desktop(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    cfg = _config(tmp_path, base=desktop)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())

    report = DR.report(cfg)

    assert report["on_desktop"] is True
    assert report["dismissed"] is False


def test_not_on_desktop_for_other_folders(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    cfg = _config(tmp_path)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())

    assert DR.report(cfg)["on_desktop"] is False


def test_unknown_desktop_means_no_warning(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    monkeypatch.setattr(DR, "desktop_dir", lambda: None)

    assert DR.report(cfg)["on_desktop"] is False


def test_dismiss_is_remembered(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    cfg = _config(tmp_path, base=desktop)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())

    assert DR.dismiss(cfg)["ok"] is True
    assert DR.report(cfg)["dismissed"] is True
    data = json.loads((cfg.runtime_path / DR.NOTICE_NAME).read_text(encoding="utf-8"))
    assert data["dismissed"] is True


# ---------------------------------------------------------------- 选目录
def test_drive_roots_order():
    assert [str(p) for p in DR.drive_roots()] == ["D:\\", "C:\\"]


def test_target_dir_prefers_first_writable(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    chosen = DR.target_dir([first, second])

    assert chosen == first / DR.APP_DIR_NAME
    assert chosen.is_dir()
    assert not (second / DR.APP_DIR_NAME).exists()


def test_target_dir_falls_back_to_second(tmp_path):
    missing = tmp_path / "no-such-drive"
    second = tmp_path / "second"
    second.mkdir()

    chosen = DR.target_dir([missing, second])

    assert chosen == second / DR.APP_DIR_NAME


def test_target_dir_returns_none_when_all_unusable(tmp_path):
    assert DR.target_dir([tmp_path / "nope-1", tmp_path / "nope-2"]) is None


# ---------------------------------------------------------------- 搬家
def _setup_desktop(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    exe = _fake_exe(desktop)
    target = tmp_path / "D-drive" / DR.APP_DIR_NAME
    target.mkdir(parents=True)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())
    monkeypatch.setattr(DR, "target_dir", lambda roots=None: target)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    monkeypatch.delenv(DR.RELOCATE_ENV, raising=False)
    monkeypatch.setattr(DR, "_LAST_RELOCATE", None)
    return desktop, exe, target


def test_relocate_copies_exe_makes_shortcut_and_restarts(tmp_path, monkeypatch):
    desktop, exe, target = _setup_desktop(tmp_path, monkeypatch)
    calls = []

    monkeypatch.setattr(DR, "create_shortcut", lambda lnk, target_exe: calls.append(("shortcut", lnk, target_exe)) or True)
    monkeypatch.setattr(DR.subprocess, "Popen", lambda *a, **kw: calls.append(("popen", a, kw)))

    result = DR.relocate_if_needed()

    assert result is not None
    assert result["ok"] is True
    new_exe = target / exe.name
    assert new_exe.is_file()
    assert new_exe.read_bytes() == b"MZ fake"
    kinds = [c[0] for c in calls]
    assert kinds == ["shortcut", "popen"]
    shot = calls[0]
    assert shot[1] == desktop / DR.SHORTCUT_NAME
    assert shot[2] == new_exe
    popen = calls[1]
    assert popen[1][0] == [str(new_exe)]
    assert popen[2]["cwd"] == str(target)
    assert popen[2]["env"][DR.RELOCATE_ENV] == "1"
    assert (target / "relocate.log").is_file()


def test_relocate_skipped_when_not_on_desktop(tmp_path, monkeypatch):
    desktop, exe, target = _setup_desktop(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "elsewhere" / exe.name), raising=False)

    assert DR.relocate_if_needed() is None


def test_relocate_skipped_when_not_frozen(tmp_path, monkeypatch):
    _desktop, _exe, _target = _setup_desktop(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert DR.relocate_if_needed() is None


def test_relocate_skipped_when_already_relocated(tmp_path, monkeypatch):
    _desktop, _exe, _target = _setup_desktop(tmp_path, monkeypatch)
    monkeypatch.setenv(DR.RELOCATE_ENV, "1")

    assert DR.relocate_if_needed() is None


def test_relocate_reports_reason_when_no_writable_target(tmp_path, monkeypatch):
    desktop, exe, _target = _setup_desktop(tmp_path, monkeypatch)
    monkeypatch.setattr(DR, "target_dir", lambda roots=None: None)

    result = DR.relocate_if_needed()

    assert result is not None
    assert result["ok"] is False
    assert "写不进去" in result["reason"]


def test_report_exposes_relocate_failure(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    cfg = _config(tmp_path, base=desktop)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())
    monkeypatch.setattr(DR, "_LAST_RELOCATE", {"ok": False, "reason": "盘只读"})

    report = DR.report(cfg)

    assert report["relocate_failed"] is True
    assert report["relocate_reason"] == "盘只读"
    assert report["relocated_to"] == ""


# ---------------------------------------------------------------- 清理
def test_wipe_removes_generated_but_keeps_library(tmp_path):
    """★ 清理只动程序自己的东西：library（Mod 库）必须原地不动。"""
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    cfg = _config(tmp_path, base=desktop)
    base = desktop
    (base / "config.json").write_text("{}", encoding="utf-8")
    (base / "assets").mkdir()
    (base / "assets" / "manifest.json").write_text("{}", encoding="utf-8")
    (base / "library").mkdir()
    (base / "library" / "我的Mod").mkdir()
    (base / "library" / "我的Mod" / "a.ini").write_text("x", encoding="utf-8")
    (base / "EndfieldModController.exe").write_text("stub", encoding="utf-8")

    result = DR.wipe_generated(cfg)

    assert result["ok"] is True
    assert set(result["removed"]) == {"config.json", "runtime", "assets"}
    assert not (base / "config.json").exists()
    assert not (base / "runtime").exists()
    assert not (base / "assets").exists()
    assert (base / "library" / "我的Mod" / "a.ini").is_file()
    assert (base / "EndfieldModController.exe").is_file()
    assert "library" in result["kept"]


def test_wipe_only_touches_inside_base(tmp_path):
    cfg = _config(tmp_path)
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "config.json").write_text("keep", encoding="utf-8")

    result = DR.wipe_generated(cfg)

    assert result["ok"] is True
    assert result["removed"] == ["runtime"]
    assert (outside / "config.json").is_file()


# ---------------------------------------------------------------- 收拾桌面
def test_schedule_source_cleanup_removes_desktop_exe(tmp_path, monkeypatch):
    """★ 新实例启动后要把桌面那份旧 exe 删掉（用户 2026-10-26 追加要求）。"""
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    old_exe = _fake_exe(desktop)
    new_exe = tmp_path / "D-drive" / DR.APP_DIR_NAME / old_exe.name
    new_exe.parent.mkdir(parents=True)
    new_exe.write_bytes(b"MZ new")
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())
    monkeypatch.setattr(sys, "executable", str(new_exe), raising=False)
    monkeypatch.setenv(DR.RELOCATE_FROM_ENV, str(old_exe))
    monkeypatch.setattr(DR, "CLEANUP_INTERVAL", 0.01)

    DR.schedule_source_cleanup()

    deadline = time.time() + 3
    while time.time() < deadline and old_exe.exists():
        time.sleep(0.02)
    assert not old_exe.exists()
    assert DR.RELOCATE_FROM_ENV not in __import__("os").environ   # 用后即清


def test_schedule_source_cleanup_noop_without_env(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    old_exe = _fake_exe(desktop)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())
    monkeypatch.delenv(DR.RELOCATE_FROM_ENV, raising=False)

    DR.schedule_source_cleanup()
    time.sleep(0.1)

    assert old_exe.is_file()


def test_schedule_source_cleanup_ignores_non_desktop_source(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stray = _fake_exe(elsewhere)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / stray.name), raising=False)
    monkeypatch.setenv(DR.RELOCATE_FROM_ENV, str(stray))
    monkeypatch.setattr(DR, "CLEANUP_INTERVAL", 0.01)

    DR.schedule_source_cleanup()
    time.sleep(0.15)

    assert stray.is_file()


def test_schedule_source_cleanup_never_deletes_itself(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    myself = _fake_exe(desktop)
    monkeypatch.setattr(DR, "desktop_dir", lambda: desktop.resolve())
    monkeypatch.setattr(sys, "executable", str(myself), raising=False)
    monkeypatch.setenv(DR.RELOCATE_FROM_ENV, str(myself))
    monkeypatch.setattr(DR, "CLEANUP_INTERVAL", 0.01)

    DR.schedule_source_cleanup()
    time.sleep(0.15)

    assert myself.is_file()

