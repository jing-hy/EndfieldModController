# SPDX-License-Identifier: GPL-3.0-or-later
"""Mod 修复（ps-t+1）/ 回滚 / 移出库的离线单测。

2026-10-19 用户定的新规则：把该 Mod 的 .ini 里所有 ps-tN（**N < 21**）整体 +1
（ps-t0 → ps-t1、ps-t01 → ps-t02、ps-t20 → ps-t21；21 及以上不动）。
不再跑随包 exe，也不再有一键修复；每个 Mod 只能单独修，修前整份备份、可回滚。

覆盖的都是"错了会伤用户数据"的点：
* 边界（0/20/21/70、前导零、大小写）；
* 只改 .ini、跳过 d3dx.ini；
* 编码与换行原样保留（GBK / CRLF 的 Mod 不能变成乱码）；
* 已修过默认拒绝、force 才再 +1；
* 备份失败即中止、回滚精确还原、旧工具标记只作提示。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import modfix
from endfieldmodcontroller.config import AppConfig

LEGACY_MARK = "; PS-T DRAW-SECTION SHIFT -1 APPLIED v2.1"


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
    return SimpleNamespace(config=config, library=library, runtime=runtime, mod_dir=mod_dir)


# --------------------------------------------------------------- 规则本身
def test_shift_rule_bounds_and_zero_padding(env):
    ini = env.mod_dir / "mod.ini"
    ini.write_text(
        "[A]\nps-t0 = a\nps-t3 = b\nps-t20 = c\nps-t21 = d\nps-t70 = e\nps-t01 = f\n",
        encoding="utf-8")
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"], result
    assert result["replacements"] == 4, result          # 0 / 3 / 20 / 01
    text = ini.read_text(encoding="utf-8")
    assert "ps-t1 = a" in text
    assert "ps-t4 = b" in text
    assert text.count("ps-t21 = ") == 2                 # 20→21 与原有 21 并存
    assert "ps-t70 = e" in text                          # 70 高于 21，必须原样
    assert "ps-t02 = f" in text                         # 保留两位宽度


def test_case_insensitive_and_prefix_kept(env):
    ini = env.mod_dir / "mod.ini"
    ini.write_text("[A]\nPS-T3 = a\nPs-T9 = b\n", encoding="utf-8")
    modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    text = ini.read_text(encoding="utf-8")
    assert "PS-T4 = a" in text and "Ps-T10 = b" in text


def test_d3dx_ini_and_non_ini_untouched(env):
    (env.mod_dir / "readme.txt").write_text("ps-t3\n", encoding="utf-8")
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"] and result["replacements"] == 0
    assert "ps-t3" in (env.mod_dir / "d3dx.ini").read_text(encoding="utf-8")
    assert (env.mod_dir / "readme.txt").read_text(encoding="utf-8") == "ps-t3\n"


def test_no_match_reports_without_backup(env):
    ini = env.mod_dir / "mod.ini"
    ini.write_text("[A]\nps-t30 = a\n", encoding="utf-8")
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"] and result["replacements"] == 0
    assert "没有找到" in result["message"]
    assert modfix.list_backups(env.config, "mod-1") == []


def test_subdirectory_ini_is_processed(env):
    sub = env.mod_dir / "sub" / "deep"
    sub.mkdir()
    (sub / "x.ini").write_text("ps-t5 = a\n", encoding="utf-8")
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"] and result["replacements"] == 1
    assert "ps-t6 = a" in (sub / "x.ini").read_text(encoding="utf-8")


def test_encoding_and_newline_preserved(env):
    ini = env.mod_dir / "gbk.ini"
    raw = "# 中文注释\r\nps-t2 = 值\r\n".encode("gbk")
    ini.write_bytes(raw)
    modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    data = ini.read_bytes()
    text = data.decode("gbk")                       # 仍是 GBK，不是被改写成 UTF-8
    assert "中文注释" in text and "ps-t3 = 值" in text
    assert b"\r\n" in data                         # 换行没被统一成 \n


# --------------------------------------------------------------- 备份 / 回滚
def test_fix_writes_sidecar_record_and_rollback_restores(env):
    ini = env.mod_dir / "mod.ini"
    ini.write_text("[A]\nps-t3 = a\n", encoding="utf-8")
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"] and result["changed"] == ["mod.ini"]
    assert modfix.is_fixed(env.mod_dir)["fixed"] is True
    assert modfix.list_backups(env.config, "mod-1")

    rolled = modfix.rollback_mod(env.config, "mod-1")
    assert rolled["ok"], rolled.get("message")
    assert "ps-t3 = a" in ini.read_text(encoding="utf-8")
    assert modfix.is_fixed(env.mod_dir)["fixed"] is False
    assert modfix.list_backups(env.config, "mod-1") == []


def test_fix_twice_needs_force(env):
    ini = env.mod_dir / "mod.ini"
    ini.write_text("[A]\nps-t3 = a\n", encoding="utf-8")
    first = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert first["ok"]
    second = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert second["ok"] is False and second["already"] is True
    assert "ps-t4 = a" in ini.read_text(encoding="utf-8")     # 没被再动
    forced = modfix.fix_mod(env.config, "mod-1", env.mod_dir, force=True)
    assert forced["ok"]
    assert "ps-t5 = a" in ini.read_text(encoding="utf-8")     # 明确要再 +1 才动


def test_backup_failure_aborts_without_touching_files(env, monkeypatch):
    ini = env.mod_dir / "mod.ini"
    ini.write_text("[A]\nps-t3 = a\n", encoding="utf-8")
    monkeypatch.setattr(modfix, "backup_mod",
                        lambda *a, **k: {"ok": False, "message": "磁盘满了"})
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"] is False and "备份失败" in result["message"]
    assert "ps-t3 = a" in ini.read_text(encoding="utf-8")
    assert modfix.is_fixed(env.mod_dir)["fixed"] is False


def test_legacy_marker_is_only_reported(env):
    ini = env.mod_dir / "mod.ini"
    ini.write_text("[A]\nps-t3 = a\n" + LEGACY_MARK + "\n", encoding="utf-8")
    result = modfix.fix_mod(env.config, "mod-1", env.mod_dir)
    assert result["ok"]
    assert result["legacy_shift_minus_one"] == ["mod.ini"]


# --------------------------------------------------------------- 移出库
def test_delete_moves_to_trash(env):
    result = modfix.delete_mod(env.config, env.mod_dir)
    assert result["ok"], result.get("message")
    assert not env.mod_dir.exists()
    assert Path(result["moved_to"]).is_dir()
    assert (Path(result["moved_to"]) / "d3dx.ini").is_file()


# --------------------------------------------------------------- 旧接口必须消失
def test_old_tool_entrypoints_are_gone():
    for name in ("fix_all", "ensure_tool", "tool_status", "tool_path", "ensure_tool"):
        assert not hasattr(modfix, name), f"{name} 应该已经删除"
    assert not hasattr(modfix, "FIX_MARK") or modfix.LEGACY_FIX_MARK
