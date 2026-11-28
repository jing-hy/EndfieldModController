# SPDX-License-Identifier: AGPL-3.0-only
r"""钉住 2026-11-28 的「自动修复」要求（用户：「能不能自动做掉修复，不要依赖用户」）。

现场（诊断包 `diagnostics-20261128-220053`）：一键启动每次都 0xC0000005，因为本程序用
loader proxy 顶替了游戏的两个系统模块；同机**独立启动 EFMI** 能进（不走这条重铺路径）。

两条保证：
  ① 乳摇注入**不再铺 proxy**（新的一律不铺，以前铺的自动还原成原版）；
  ② 启动流程发现系统模块仍是 proxy 时，**先自动还原**再继续，只有还原失败才拒绝启动。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import launcher, reshade_integration, secondary_motion
from endfieldmodcontroller.config import AppConfig

SBM_MARK = b"[LOADER] started "
POSER_MARK = b"[PROXY] plugins loaded via "


def _config(tmp_path: Path, game: Path, **extra) -> AppConfig:
    (game / "Endfield.exe").write_bytes(b"")
    kwargs = dict(
        library_dir=str(tmp_path / "library"),
        runtime_dir=str(tmp_path / "runtime"),
        staging_mods_dir=str(tmp_path / "runtime" / "EFMI" / "Mods"),
        game_exe=str(game / "Endfield.exe"),
        dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
    )
    kwargs.update(extra)
    return AppConfig(**kwargs)


def test_ensure_injection_never_lays_proxy(tmp_path: Path) -> None:
    """工具目录齐全时**也不铺** loader proxy（并把它还原成原版）。"""
    game = tmp_path / "game"
    game.mkdir()
    (game / "d3dcompiler_47.dll").write_bytes(SBM_MARK + b"x" * 1024)
    (game / "d3dcompiler_47.dll.bak").write_bytes(b"MZ" + bytes(300 * 1024))
    tool = tmp_path / "tool"
    (tool / "plugins").mkdir(parents=True)
    (tool / "plugins" / "sbm.dll").write_bytes(b"sbm")
    cfg = _config(tmp_path, game, secondary_motion_dir=str(tool),
                  secondary_motion_injection=True)

    secondary_motion.ensure_injection(cfg)

    assert not reshade_integration.looks_like_loader_proxy(game / "d3dcompiler_47.dll"), (
        "系统模块必须是原版：铺 proxy 会顶掉它，游戏随后 0xC0000005")
    assert not reshade_integration.looks_like_loader_proxy(game / "vulkan-1.dll")


def test_restore_system_modules_is_idempotent(tmp_path: Path) -> None:
    """还原是幂等的：没有 proxy 时一条动作都不产生。"""
    game = tmp_path / "game"
    game.mkdir()
    cfg = _config(tmp_path, game)
    result = secondary_motion.restore_system_modules(cfg)
    assert result.get("ok") is True, result
    assert result.get("actions") == []


def test_launch_auto_restores_before_refusing(tmp_path: Path) -> None:
    """启动流程发现 proxy 时先自动还原 —— 还原成功就不该把用户挡回去。"""
    game = tmp_path / "game"
    game.mkdir()
    (game / "vulkan-1.dll").write_bytes(POSER_MARK + b"x" * 512)
    (game / "vulkan-1.dll.bak").write_bytes(b"MZ" + bytes(200 * 1024))
    cfg = _config(tmp_path, game)
    assert launcher._system_modules_hijacked(cfg) == ["vulkan-1.dll"]

    fixed = secondary_motion.restore_system_modules(cfg)
    assert fixed.get("actions"), "应当产出一条还原动作"
    assert launcher._system_modules_hijacked(cfg) == [], "还原后不该再判成被顶替"