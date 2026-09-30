"""Mod 修复 / 回滚 / 移出库的离线单测（不真的跑那个 exe）。

覆盖的都是"错了会伤用户数据"的点：
* 修复状态判定（靠工具写下的 `; PS-T DRAW-SECTION SHIFT -1 APPLIED` 标记）；
* **修复前一定先备份**、备份按数量滚动、回滚能把目录恢复到备份时的样子（含删掉多出来的文件）；
* **工具在临时目录里跑**（不在 Mod 库/Mods 里留 `_ps_t_draw_fix_backup_*` 与日志）、带 `CREATE_NO_WINDOW`、做完喂回车；
* 移出库是"移动"不是"删除"。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import modfix
from endfieldmodcontroller.config import AppConfig

FIX_MARK_LINE = f"; {modfix.FIX_MARK} v2.1"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    library = tmp_path / "library"
    runtime = tmp_path / "runtime"
    library.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: library))

    mod_dir = library / "测试Mod"
    (mod_dir / "sub").mkdir(parents=True, exist_ok=True)
    (mod_dir / "d3dx.ini").write_text(
        "[TextureOverrideA]\nhash = aaaa\nchecktextureoverride = ps-t3\n", encoding="utf-8")
    (mod_dir / "sub" / "extra.ini").write_text("[Other]\nkey = value\n", encoding="utf-8")
    tool = tmp_path / "fake-tool.exe"
    tool.write_bytes(b"MZ fake tool")
    return SimpleNamespace(tmp=tmp_path, config=config, library=library,
                           mod_dir=mod_dir, tool=tool)


# --------------------------------------------------------------- 状态判定
def test_is_fixed_reads_marker(env):
    assert modfix.is_fixed(env.mod_dir)["fixed"] is False
    (env.mod_dir / "sub" / "extra.ini").write_text(FIX_MARK_LINE + "\n", encoding="utf-8")
    state = modfix.is_fixed(env.mod_dir)
    assert state["fixed"] is True
    assert state["files"] == ["sub/extra.ini"] or state["files"] == ["sub\\extra.ini"]


# --------------------------------------------------------------- 备份 / 回滚
def test_backup_then_rollback_restores_exactly(env):
    backup = modfix.backup_mod(env.config, "mod-1", env.mod_dir)
    assert backup["ok"] and Path(backup["path"]).is_dir()

    # 模拟"被修复过"：改内容 + 多出文件（工具会留下备份目录/日志）
    (env.mod_dir / "d3dx.ini").write_text("checktextureoverride = ps-t1\n" + FIX_MARK_LINE, encoding="utf-8")
    (env.mod_dir / "PS_T_Draw_Section_Fix_log.txt").write_text("log", encoding="utf-8")
    (env.mod_dir / "_ps_t_draw_fix_backup_x").mkdir()

    result = modfix.rollback_mod(env.config, "mod-1")
    assert result["ok"], result.get("message")
    assert "ps-t3" in (env.mod_dir / "d3dx.ini").read_text(encoding="utf-8")
    assert not (env.mod_dir / "PS_T_Draw_Section_Fix_log.txt").exists()
    assert not (env.mod_dir / "_ps_t_draw_fix_backup_x").exists()
    # 回滚会把那条备份消费掉，避免反复回滚
    assert modfix.list_backups(env.config, "mod-1") == []


def test_backup_keeps_only_three_per_mod(env):
    for _ in range(5):
        modfix.backup_mod(env.config, "mod-1", env.mod_dir)
    assert len(modfix.list_backups(env.config, "mod-1")) == modfix.BACKUP_KEEP_PER_MOD


def test_rollback_without_backup_is_readable(env):
    result = modfix.rollback_mod(env.config, "mod-404")
    assert result["ok"] is False and "备份" in result["message"]


# --------------------------------------------------------------- 移出库
def test_delete_moves_to_trash(env):
    result = modfix.delete_mod(env.config, env.mod_dir)
    assert result["ok"], result.get("message")
    assert not env.mod_dir.exists()
    assert Path(result["moved_to"]).is_dir()
    assert (Path(result["moved_to"]) / "d3dx.ini").is_file()


# --------------------------------------------------------------- 工具调用（打桩）
class _FakeProc:
    def __init__(self, work: Path):
        import io

        self.stdin = io.BytesIO()
        self._work = work
        self.fed_enter = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_fix_mod_runs_tool_in_temp_dir_after_backup(env, monkeypatch):
    seen: dict = {}

    def fake_popen(args, **kwargs):
        work = Path(kwargs["cwd"])
        seen["args"] = list(args)
        seen["cwd"] = work
        seen["creationflags"] = kwargs.get("creationflags")
        # 模拟工具：写自己的日志 + 改临时目录里的 ini（并带上标记）
        (work / modfix.LOG_NAME).write_text(
            "Endfield PS-T Draw Section Fix -1 v2.1.0\n"
            "FIXED-V2.1 | replacements=1 | v2-migrations=0 | sections=1 | ps-t0-skipped=0 | d3dx.ini\n",
            encoding="utf-8")
        target = next(work.rglob("d3dx.ini"))
        target.write_text("checktextureoverride = ps-t1\n" + FIX_MARK_LINE + "\n", encoding="utf-8")
        # 工具还会在临时目录里留备份目录 —— 它必须随临时目录一起消失
        (work.parent / (modfix.BACKUP_PREFIX + "_20260101_000000")).mkdir(exist_ok=True)
        return _FakeProc(work)

    monkeypatch.setattr(modfix.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(modfix, "ensure_tool",
                        lambda config, log=None: {"ok": True, "path": str(env.tool)})

    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"], result.get("message")
    assert result["changed_count"] == 1
    assert result["marked"] is True
    assert result["tool_log"] and "FIXED-V2.1" in result["tool_log"][1]

    # ① 工具跑在临时目录里（不是库目录）
    assert seen["cwd"] != env.mod_dir and "mc-modfix-" in str(seen["cwd"])
    # ② 无黑窗
    assert seen["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # ③ 库里已被更新 + 带了标记
    assert modfix.is_fixed(env.mod_dir)["fixed"] is True
    # ④ 改之前先备份了（回滚点）
    assert modfix.list_backups(env.config, "mod-1")
    # ⑤ 库目录里没有工具留下的备份/日志残留，临时目录也没了
    leftovers = [p.name for p in env.mod_dir.iterdir()
                 if p.name.startswith(modfix.BACKUP_PREFIX) or p.name == modfix.LOG_NAME]
    assert leftovers == []
    assert not seen["cwd"].exists()


def test_fix_mod_skips_when_already_fixed(env, monkeypatch):
    (env.mod_dir / "d3dx.ini").write_text("checktextureoverride = ps-t1\n" + FIX_MARK_LINE, encoding="utf-8")
    monkeypatch.setattr(modfix, "ensure_tool",
                        lambda config, log=None: {"ok": True, "path": str(env.tool)})
    called: list = []
    monkeypatch.setattr(modfix.subprocess, "Popen", lambda *a, **k: called.append(1))

    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir, skip_if_fixed=True)
    assert result["ok"] and result["skipped"] is True
    assert called == []                                  # 没再跑工具
    assert modfix.list_backups(env.config, "mod-1") == []  # 也没白备份


def test_fix_mod_aborts_when_backup_fails(env, monkeypatch):
    monkeypatch.setattr(modfix, "ensure_tool",
                        lambda config, log=None: {"ok": True, "path": str(env.tool)})
    monkeypatch.setattr(modfix, "backup_mod",
                        lambda *a, **k: {"ok": False, "message": "磁盘满了"})
    called: list = []
    monkeypatch.setattr(modfix.subprocess, "Popen", lambda *a, **k: called.append(1))

    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"] is False and "备份失败" in result["message"]
    assert called == []                                  # 备份失败就绝不跑工具


# --------------------------------------------------------------- 批量
def test_fix_all_keeps_going_after_one_failure(env, monkeypatch):
    mods = [SimpleNamespace(id="a", name="A", path=env.mod_dir),
            SimpleNamespace(id="b", name="B", path=env.tmp / "does-not-exist")]

    def fake_fix(config, mod_id, mod_dir, **kwargs):
        if mod_id == "a":
            return {"ok": True, "changed_count": 2, "skipped": False}
        return {"ok": False, "message": "Mod 目录不存在"}

    monkeypatch.setattr(modfix, "fix_mod", fake_fix)
    result = modfix.fix_all(env.config, mods, skip_if_fixed=True)
    assert result["total"] == 2 and result["succeeded"] == 1
    assert result["changed_total"] == 2
    assert any(not item["ok"] for item in result["results"])


# --------------------------------------------------------------- 工具就位
def test_ensure_tool_reports_missing_readable(env, monkeypatch):
    monkeypatch.setattr(modfix, "_tool_candidates", lambda config: [env.tmp / "nope.exe"])
    result = modfix.ensure_tool(env.config)
    assert result["ok"] is False and "找不到修复工具" in result["message"]


def test_ensure_tool_copies_from_assets_and_verifies_sha(env, monkeypatch):
    from endfieldmodcontroller import fsutil

    asset_dir = env.tmp / "assets" / "modfix"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset = asset_dir / modfix.TOOL_NAME
    asset.write_bytes(b"MZ real tool")
    (asset_dir / modfix.MANIFEST_NAME).write_text(json.dumps({
        "files": {modfix.TOOL_NAME: {"sha256": fsutil.sha256_file(asset)}},
    }), encoding="utf-8")
    monkeypatch.setattr(modfix, "_tool_candidates", lambda config: [asset])

    result = modfix.ensure_tool(env.config)
    assert result["ok"] and result["changed"] is True
    assert modfix.tool_path(env.config).is_file()

    # 清单里的 sha256 对不上时必须拒绝
    (asset_dir / modfix.MANIFEST_NAME).write_text(json.dumps({
        "files": {modfix.TOOL_NAME: {"sha256": "0" * 64}},
    }), encoding="utf-8")
    modfix.tool_path(env.config).unlink()
    bad = modfix.ensure_tool(env.config)
    assert bad["ok"] is False and "sha256" in bad["message"]
