# SPDX-License-Identifier: AGPL-3.0-only
"""Mod 库「移出库」的离线单测（以及"修复功能已彻底移除"的回归钉）。

2026-11-27 用户要求：**完全移除修复损坏 Mod 的功能**（ps-t+1 修复 / 回滚 / 备份索引 /
前端「修复 Mod 文件」「回滚」菜单项），只保留用户在卡片菜单里主动点的「移出 Mod 库」。

这里钉住两件事：
* 移出库仍然是"删除 ≠ 真删"：只移到 runtime 下的 backups/mod-trash，内容原样可找回；
* 修复那一套入口一个都不能复活（模块 / 函数 / 前端接口名）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import modlib
from endfieldmodcontroller.config import AppConfig


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
    (mod_dir / "d3dx.ini").write_text("[TextureOverrideA]\nhash = aaaa\n", encoding="utf-8")
    (mod_dir / "sub" / "extra.ini").write_text("[Other]\nkey = value\n", encoding="utf-8")
    return SimpleNamespace(config=config, library=library, runtime=runtime, mod_dir=mod_dir)


# --------------------------------------------------------------- 移出库
def test_delete_moves_to_trash(env):
    before = (env.mod_dir / "sub" / "extra.ini").read_text(encoding="utf-8")
    result = modlib.delete_mod(env.config, env.mod_dir)
    assert result["ok"], result.get("message")
    assert not env.mod_dir.exists()
    moved = Path(result["moved_to"])
    assert moved.is_dir()
    assert (moved / "d3dx.ini").is_file()
    # 内容原样搬走（不是复制一半、也不是被压缩）
    assert (moved / "sub" / "extra.ini").read_text(encoding="utf-8") == before


def test_delete_missing_dir_is_reported_not_created(env):
    result = modlib.delete_mod(env.config, env.mod_dir / "不存在")
    assert result["ok"] is False and "不存在" in result["message"]


# --------------------------------------------------------------- 修复功能必须彻底消失
def test_repair_module_and_entrypoints_are_gone():
    assert importlib.util.find_spec("endfieldmodcontroller.modfix") is None, (
        "modfix 模块必须已被删除（2026-11-27 用户要求完全移除修复功能）"
    )
    for name in ("fix_mod", "rollback_mod", "backup_mod", "list_backups",
                 "is_fixed", "has_legacy_shift_minus_one", "PS_T_RE", "RULE_ID"):
        assert not hasattr(modlib, name), f"modlib.{name} 不应该存在"

    from endfieldmodcontroller.api import EndfieldModControllerApi

    for name in ("fix_mod", "rollback_mod", "mod_more_info", "_enrich_modfix_state"):
        assert not hasattr(EndfieldModControllerApi, name), f"API {name} 不应该存在"
