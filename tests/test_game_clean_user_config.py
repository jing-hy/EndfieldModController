# SPDX-License-Identifier: GPL-3.0-or-later
"""净化**不许**动 Poser 的设置与快捷键（2026-10-12，用户报「Poser 的快捷键会被复写」）。

Poser 自带文档原文：`| 设置、快捷键 / 窗口布局 | plugin/poser_config.txt / plugin/poser_layout.ini |`。
而原先这两份都会被净化扫走：

* `plugin/poser_config.txt` —— 被 `plugin/` 下的 `.txt` 规则当成"插件写的日志/探针输出"；
* `plugin/poser_layout.ini` —— 列在 `POSER_DATA_PATHS` 里。

于是每次"启动前净化"都把用户改过的键一起搬走，重新铺设时写回默认值 ⇒ 用户那边就是
「快捷键被复写」。判据依旧是"原版有没有这个文件"，但**用户数据不得因净化而丢失** ——
与"Mod 库只读"是同一条红线。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import game_clean
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    game = tmp_path / "game"
    plugin = game / "plugin"
    plugin.mkdir(parents=True)
    (plugin / "poser.dll").write_bytes(b"poser-dll")
    (plugin / "poser_config.txt").write_text("hk_toggle=L\nfreeze=P\n", encoding="utf-8")
    (plugin / "poser_layout.ini").write_text("[layout]\nwin=120,80\n", encoding="utf-8")
    (plugin / "sbm_log.txt").write_text("probe output\n", encoding="utf-8")
    monkeypatch.setattr(game_clean.reshade_integration, "detect_game_dir",
                        lambda cfg, prefer_actual=False: game, raising=False)
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"), library_dir=str(tmp_path / "library"))
    return type("Env", (), {"config": config, "game": game, "plugin": plugin})()


def _relatives(report: dict) -> set[str]:
    return {str(item.get("relative") or "").replace("\\", "/") for item in report.get("findings", [])}


def test_audit_never_lists_poser_user_config(env):
    """★ 核心回归：设置与快捷键**不能出现在**待净化的清单里。"""
    report = game_clean.audit(env.config)
    relatives = _relatives(report)
    assert "plugin/poser.dll" in relatives, relatives          # 插件本体照旧要清
    assert "plugin/sbm_log.txt" in relatives, relatives        # 日志照旧要清
    assert "plugin/poser_config.txt" not in relatives, relatives
    assert "plugin/poser_layout.ini" not in relatives, relatives


def test_clean_keeps_the_file_on_disk(env):
    """真跑一次净化：两个用户配置文件必须**原样留在游戏目录**、内容不变。"""
    result = game_clean.backup_and_clean(env.config)
    assert result.get("ok") is not False, result
    config_file = env.plugin / "poser_config.txt"
    layout_file = env.plugin / "poser_layout.ini"
    assert config_file.is_file(), "设置文件被净化搬走了"
    assert "hk_toggle=L" in config_file.read_text(encoding="utf-8")
    assert layout_file.is_file(), "快捷键/布局文件被净化搬走了"
    assert not (env.plugin / "poser.dll").is_file(), "插件本体应当被搬走"
