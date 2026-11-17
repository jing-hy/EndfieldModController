# SPDX-License-Identifier: GPL-3.0-or-later
"""2026-11-16 反馈：Mod 开关与 EFMI 的 Mods 目录对不上 + 「打开文件夹」不定位。

用户原话（QQ 群）：
① 「我下载 mod 不会自己放到 EFMI 的 mod 文件夹只会在管理器的 mod 文件夹，
   还要我手动放进 EFMI 的 mod 文件夹里才生效这正常吗」
② 「管理器能控制开关 mod，但是不能把 mod 扔到 EF 的 mod 文件夹」
③ 「时而能控制时而不能控制」
④ 「关闭 mod 我去看文件夹里他直接帮我把 mod 删了」
⑤ 「打开文件夹不会跳转到指定文件，大部分情况会跳转到」

诊断包（diagnostics-20261116-220247）里能直接看到 ③ 的现场：EFMI 的 Mods 目录里同时有
Si_Ink_Mist / MC_祀_Si_Ink_Mist、Tangtang_Lil_Undead / MC_汤汤_Tangtang_Lil_Undead
—— 同一个 Mod 的两份同角色副本。EFMI 会把两份都加载，变量与热键互相覆盖 ⇒ 面板时灵时不灵。

本文件钉住四条判据：
* 手动目录（收编时删不掉，游戏运行中文件被占用）还在 Mods 里时，不再 stage 同 namespace 副本；
* 「自动收编」开关关掉时，不复制也不搬走 Mods 里的外来目录；
* 库里的开关能立刻同步到 Mods 目录（apply_selection），并发时明确回「忙」；
* 「打开文件夹」：目录要进入、文件用 explorer "/select,<路径>" 单参数定位（旧写法会退回文档）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import activation, api as A, diagnostics
from endfieldmodcontroller.config import AppConfig


def _write_mod(root: Path, rel: str, namespace: str) -> Path:
    path = root / rel
    path.mkdir(parents=True, exist_ok=True)
    (path / "mod.ini").write_text(
        f"namespace = {namespace}" + chr(10) + "[Constants]" + chr(10) + "global persist $on = 0" + chr(10),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def env(tmp_path):
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    runtime = tmp_path / "runtime"
    for path in (library, staging, runtime):
        path.mkdir(parents=True, exist_ok=True)
    return tmp_path, library, staging, runtime


# ---------------------------------------------------------------- ① 同角色双份
def test_manual_copy_left_in_mods_is_not_staged_again(env):
    """★ 收编删不掉的手动目录还留在 Mods 里时，不能再 stage 一份同 namespace 的副本。

    这就是「时而能控制时而不能控制」的根因：两份同角色 Mod 被 EFMI 同时加载。
    """
    _tmp, library, staging, runtime = env
    _write_mod(library, "祀的衣服", "SiInkMist")          # 库里的那份（用户勾选了）
    _write_mod(staging, "Si_Ink_Mist", "SiInkMist")        # 手动放的那份（收编时没删掉）

    result = activation.stage_and_prepare(library, staging, runtime, selected_ids=None)

    assert result["kept_manual"] == ["Si_Ink_Mist"]
    assert result["skipped_manual_conflict"] == ["祀的衣服"], result
    staged_dirs = [p.name for p in staging.iterdir() if p.is_dir() and p.name.startswith("MC_")]
    assert staged_dirs == ["MC_Controller"], f"不该生成同角色副本，实际：{staged_dirs}"
    # 手动那份一个字都不动（用户红线：宁可留着让他自己删）
    assert (staging / "Si_Ink_Mist" / "mod.ini").is_file()


def test_unrelated_mods_are_still_staged(env):
    """对照：没冲突的 Mod 照常进 staging（别把跳过做成一刀切）。"""
    _tmp, library, staging, runtime = env
    _write_mod(library, "祀的衣服", "SiInkMist")
    _write_mod(library, "另一件", "Another")
    _write_mod(staging, "Si_Ink_Mist", "SiInkMist")

    result = activation.stage_and_prepare(library, staging, runtime, selected_ids=None)

    assert result["skipped_manual_conflict"] == ["祀的衣服"]
    names = [p.name for p in staging.iterdir() if p.is_dir()]
    assert any("另一件" in name for name in names), names


# ---------------------------------------------------------------- ② 收编开关
def _api(tmp_path: Path, staging: Path) -> A.EndfieldModControllerApi:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "library").mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = AppConfig.load(cfg_path)
    cfg.data_root = str(tmp_path)
    cfg.library_dir = "library"
    cfg.staging_mods_dir = str(staging)
    cfg.save()
    return A.EndfieldModControllerApi(str(cfg_path))


def test_adopt_switch_off_keeps_manual_dirs_untouched(tmp_path):
    """★ 「自动收编」关掉时：不复制进库、不搬走（用户报的"关闭 mod 把我的 mod 删了"）。"""
    staging = tmp_path / "Mods"
    staging.mkdir(parents=True, exist_ok=True)
    _write_mod(staging, "手动放的", "Manual")
    api = _api(tmp_path, staging)
    api.config.auto_adopt_manual_mods = False
    api.config.save()

    result = api.import_manual_mods()

    assert result.get("skipped") == "switch_off", result
    assert (staging / "手动放的" / "mod.ini").is_file(), "手动目录必须原样保留"
    assert not (tmp_path / "library" / "手动放的").exists(), "关掉开关时不该往库里复制"


def test_adopt_switch_on_still_imports(tmp_path):
    """对照：开关开着时行为不变（收进库 + 从 Mods 移走）。"""
    staging = tmp_path / "Mods"
    staging.mkdir(parents=True, exist_ok=True)
    _write_mod(staging, "手动放的", "Manual")
    api = _api(tmp_path, staging)
    assert api.config.auto_adopt_manual_mods is True

    result = api.import_manual_mods()

    assert result["imported"] == ["手动放的"], result
    assert (tmp_path / "library" / "手动放的" / "mod.ini").is_file()
    assert not (staging / "手动放的").exists()


# ---------------------------------------------------------------- ③ 开关即时同步
def test_apply_selection_syncs_and_reports(env, monkeypatch):
    """★ 拨开关 → 立刻同步 Mods（后端 apply_selection 复用 prepare）。"""
    tmp_path, _library, staging, _runtime = env
    api = _api(tmp_path, staging)
    calls: list[str] = []

    monkeypatch.setattr(api, "prepare", lambda *a, **k: (calls.append("prepare"), {
        "ok": True, "staged": ["祀的衣服"], "kept_manual": [], "skipped_manual_conflict": [],
    })[1])
    monkeypatch.setattr(api, "game_running", lambda: {"running": False})

    result = api.apply_selection()

    assert calls == ["prepare"]
    assert result["ok"] is True and result["busy"] is False
    assert result["staged"] == ["祀的衣服"]
    assert "EFMI 的 Mods" in result["message"]


def test_apply_selection_reports_game_running_hint(env, monkeypatch):
    """游戏在跑时必须说"点热重载"（否则用户以为改了没生效）。"""
    tmp_path, _library, staging, _runtime = env
    api = _api(tmp_path, staging)
    monkeypatch.setattr(api, "prepare", lambda *a, **k: {
        "ok": True, "staged": ["A"], "kept_manual": [], "skipped_manual_conflict": []})
    monkeypatch.setattr(api, "game_running", lambda: {"running": True})

    result = api.apply_selection()

    assert result["game_running"] is True
    assert "热重载" in result["message"]


def test_apply_selection_is_serialized(env, monkeypatch):
    """并发拨开关：后一次直接回「忙」，不让两次 stage 互相踩。"""
    tmp_path, _library, staging, _runtime = env
    api = _api(tmp_path, staging)
    monkeypatch.setattr(api, "prepare", lambda *a, **k: {"ok": True})
    assert api._apply_lock.acquire(blocking=False)
    try:
        result = api.apply_selection()
    finally:
        api._apply_lock.release()
    assert result["busy"] is True
    assert result["ok"] is True


# ---------------------------------------------------------------- ④ 打开文件夹
def test_reveal_directory_enters_it(tmp_path, monkeypatch):
    """目录要进入（os.startfile），不是 /select, 到父目录高亮。"""
    folder = tmp_path / "某个文件夹"
    folder.mkdir()
    opened: list[str] = []
    monkeypatch.setattr(diagnostics.os, "startfile", lambda p, *a, **k: opened.append(str(p)),
                        raising=False)
    popen: list[list[str]] = []
    monkeypatch.setattr(diagnostics.subprocess, "Popen", lambda args, **k: popen.append(list(args)))

    ok, note = diagnostics._reveal_target(folder, 0)

    assert ok and note == ""
    assert opened == [str(folder)]
    assert popen == [], "目录不该走 explorer /select"


def test_reveal_file_uses_single_select_argument(tmp_path, monkeypatch):
    """文件用单参数 explorer "/select,<路径>"：旧写法拆成两个参数时 explorer 会退回文档。"""
    target = tmp_path / "诊断包.zip"
    target.write_bytes(b"x")
    popen: list[list[str]] = []
    monkeypatch.setattr(diagnostics.subprocess, "Popen",
                        lambda args, **k: popen.append(list(args)))
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")

    ok, note = diagnostics._reveal_target(target, 0)

    assert ok and note == ""
    assert len(popen) == 1
    assert popen[0] == ["explorer", "/select," + str(target)]
    assert "/select," not in popen[0], "不能把 /select, 与路径拆成两个参数"


def test_reveal_path_with_comma_falls_back_to_parent(tmp_path, monkeypatch):
    """路径里有逗号时 /select, 会被截断：退回打开父目录并说明，不静默失败。"""
    folder = tmp_path / "a,b"
    folder.mkdir()
    target = folder / "x.zip"
    target.write_bytes(b"x")
    opened: list[str] = []
    monkeypatch.setattr(diagnostics.os, "startfile", lambda p, *a, **k: opened.append(str(p)),
                        raising=False)

    ok, note = diagnostics._reveal_target(target, 0)

    assert ok is True
    assert opened == [str(folder)]
    assert "逗号" in note


def test_reveal_rejects_non_windows(tmp_path, monkeypatch):
    """非 Windows 平台明确失败（不假装成功）。"""
    target = tmp_path / "x.zip"
    target.write_bytes(b"x")
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    ok, note = diagnostics._reveal_target(target, 0)
    assert ok is False and note


if __name__ == "__main__":
    pytest.main([__file__])
