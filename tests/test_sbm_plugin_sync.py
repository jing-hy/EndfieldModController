"""乳摇插件本体「内容变了就换」的回归测试（2026-10-05 用户实测暴露）。

## 症状

用户把乳摇工具包更新到 3.1.2（插件本体 `sbm.dll` 108 KB → 142 KB），
但**游戏里跑的仍然是旧的 108 KB**。两条硬证据：
① 游戏目录 `plugin\\sbm.dll` 大小一直是 108,032；
② v3 的迁移标记 `SecondaryMotion\\data\\.jump_defaults_v3` 从未生成
（说明新插件从没在游戏里跑过）⇒ **新版自带的跳跃 / 惯性系统一律进不去**。

## 根因

`ensure_injection` 里那句是 `if not plugin_target.is_file() and ...`
—— **游戏目录里那份一旦存在，就永远不会再被更新**。

## 修法

**源里那份与游戏目录里那份内容不同 ⇒ 备份旧的、换上**（备份只增不删，可放回）。

全部离线：只在 tmp 里造游戏目录与 assets。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import secondary_motion
from endfieldmodcontroller.config import AppConfig


@pytest.fixture(autouse=True)
def _isolate_assets(tmp_path, monkeypatch):
    """把 `_assets_root` 钉到 tmp。

    ⚠️ 不能只靠 `data_root`：`_assets_root()` 在拿不到 `base_dir` 时会**回退到源码布局**，
    于是测试会去写/读**真实仓库**里那份 `assets\\secondary_motion`（第一版测试正是这样，
    断言拿到的是真实 sbm.dll 的 `MZ` 头）。
    """
    monkeypatch.setattr(secondary_motion, "_assets_root",
                        lambda config=None: tmp_path / "assets")
    yield


def _env(tmp_path: Path, *, plugin_in_game: bytes | None, plugin_in_assets: bytes):
    """造一个最小环境：数据根（含 assets）+ 游戏目录。"""
    assets = tmp_path / "assets" / "secondary_motion" / "plugin"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / secondary_motion.PLUGIN_NAME).write_bytes(plugin_in_assets)

    game = tmp_path / "game"
    (game / "plugin").mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    if plugin_in_game is not None:
        (game / "plugin" / secondary_motion.PLUGIN_NAME).write_bytes(plugin_in_game)

    cfg = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                    # ⚠️ 必须把数据根也指到 tmp：`_assets_root()` 优先用 `config.base_dir`，
                    # 不指的话它会回退到**源码布局的 assets** —— 测试就会去读真实仓库里那份
                    # sbm.dll（第一次跑正是这样，断言拿到的是 PE 的 `MZ` 头）。
                    data_root=str(tmp_path),
                    game_exe=str(game / "Endfield.exe"))
    return cfg, game


def test_installs_plugin_when_missing(tmp_path):
    cfg, game = _env(tmp_path, plugin_in_game=None, plugin_in_assets=b"NEW-PLUGIN")

    result = secondary_motion.ensure_injection(cfg, log=lambda _m: None)

    target = game / "plugin" / secondary_motion.PLUGIN_NAME
    assert target.read_bytes() == b"NEW-PLUGIN"
    assert any("安装插件" in a for a in result["actions"]), result["actions"]


def test_replaces_plugin_when_content_differs(tmp_path):
    """★ 核心：游戏目录里那份是旧的 ⇒ 必须换成新的，并且**留备份**。"""
    cfg, game = _env(tmp_path, plugin_in_game=b"OLD-PLUGIN-108KB", plugin_in_assets=b"NEW-PLUGIN-142KB")

    result = secondary_motion.ensure_injection(cfg, log=lambda _m: None)

    target = game / "plugin" / secondary_motion.PLUGIN_NAME
    assert target.read_bytes() == b"NEW-PLUGIN-142KB", "旧插件没被换成新版"
    backups = list((game / "plugin").glob(f"{secondary_motion.PLUGIN_NAME}.bak*"))
    assert backups, "替换前必须留一份备份（名字唯一、只增不删）"
    assert backups[0].read_bytes() == b"OLD-PLUGIN-108KB"
    assert any("更新插件" in a for a in result["actions"]), result["actions"]


def test_keeps_plugin_when_identical(tmp_path):
    """内容一致 ⇒ 一个字都不动（不要每次都重写、也不要每次都堆备份）。"""
    cfg, game = _env(tmp_path, plugin_in_game=b"SAME", plugin_in_assets=b"SAME")

    result = secondary_motion.ensure_injection(cfg, log=lambda _m: None)

    assert (game / "plugin" / secondary_motion.PLUGIN_NAME).read_bytes() == b"SAME"
    assert not list((game / "plugin").glob(f"{secondary_motion.PLUGIN_NAME}.bak*")), "不该产生备份"
    assert not any(secondary_motion.PLUGIN_NAME in a for a in result["actions"]), result["actions"]


def test_backup_names_are_unique_across_replacements(tmp_path):
    """连着换两次 ⇒ 两份备份都在（绝不互相覆盖）。"""
    cfg, game = _env(tmp_path, plugin_in_game=b"V1", plugin_in_assets=b"V2")
    secondary_motion.ensure_injection(cfg, log=lambda _m: None)

    # 再换一次：assets 里改成 V3
    (tmp_path / "assets" / "secondary_motion" / "plugin" / secondary_motion.PLUGIN_NAME).write_bytes(b"V3")
    secondary_motion.ensure_injection(cfg, log=lambda _m: None)

    backups = sorted(p.read_bytes() for p in (game / "plugin").glob(f"{secondary_motion.PLUGIN_NAME}.bak*"))
    assert b"V1" in backups and b"V2" in backups, f"备份被覆盖了: {backups}"
    assert (game / "plugin" / secondary_motion.PLUGIN_NAME).read_bytes() == b"V3"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
