# SPDX-License-Identifier: AGPL-3.0-only
r"""钉住 2026-11-28 那次「走启动器就崩、独立启动 EFMI 能进」的三处编排层修复。

诊断包 `diagnostics-20261128-220053`（用户 `D:\EndfieldModController`，完整版）：

```
22:00:19 备份原版 d3dcompiler_47.dll -> d3dcompiler_47.dll.bak
22:00:19 安装注入 d3dcompiler_47.dll          ← 乳摇 loader proxy 顶替系统模块
22:00:19 安装注入 vulkan-1.dll
22:00:19 WARN 未找到乳摇工具目录               ← 工具都没有，却照样铺
22:00:19 WARN …这种状态游戏会在启动约 30 秒后退出
```

三处修复：① 工具目录缺失 ⇒ 一条注入都不铺；② 合法的外部 EFMI 布局（`D:\XXMI` +
`D:\EFMI`）不再被判成"指错了"；③ 系统模块真被顶替时**拒绝启动**。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import launcher, secondary_motion
from endfieldmodcontroller.config import AppConfig
from endfieldmodcontroller import reshade_integration


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


def test_sbm_skips_injection_when_tool_dir_missing(tmp_path: Path) -> None:
    """乳摇工具目录不存在 ⇒ 一条注入都不铺（也不装 sbm.dll）。"""
    game = tmp_path / "game"
    game.mkdir()
    # 造一个"以前铺过"的 proxy（小文件 + 标记串）
    (game / "d3dcompiler_47.dll").write_bytes(b"[LOADER] started " + b"x" * 1024)
    cfg = _config(tmp_path, game,
                  secondary_motion_dir=str(tmp_path / "no-such-tool"),
                  secondary_motion_injection=True)
    result = secondary_motion.ensure_injection(cfg)
    assert result.get("ok") is True, result
    assert result.get("skipped") == "no-tool-dir", result
    # 没铺新的 proxy：留下的（若有）必须是**原版**，不能还是 loader proxy
    assert not reshade_integration.looks_like_loader_proxy(game / "vulkan-1.dll")
    assert not reshade_integration.looks_like_loader_proxy(game / "d3dcompiler_47.dll")
    # 也没装 plugin/sbm.dll
    assert not (game / "plugin" / "sbm.dll").is_file()


def test_external_efmi_install_is_sane(tmp_path: Path) -> None:
    r"""`importer_folder` 指向 XXMI 之外的独立 EFMI 安装是**合法布局**。

    现场：`D:\XXMI` + `D:\EFMI`（EFMI 根带 Core/EFMI 与 d3d11.dll）。原来这条判据
    要求"必须在 XXMI 树内"⇒ 每轮启动都去改用户的 importer_folder。
    """
    xxmi_root = tmp_path / "XXMI"
    xxmi_root.mkdir()
    external = tmp_path / "EFMI"
    (external / "Core" / "EFMI").mkdir(parents=True)
    (external / "d3d11.dll").write_bytes(b"loader")
    assert launcher._efmi_folder_is_sane(external, xxmi_root) is True


def test_mod_library_lookalike_is_still_rejected(tmp_path: Path) -> None:
    """但"被误指到 Mod 库"那种散落 dll 仍要判不合规（原来那条保护不能丢）。"""
    xxmi_root = tmp_path / "XXMI"
    xxmi_root.mkdir()
    library = tmp_path / "library"
    (library / "some_mod").mkdir(parents=True)
    (library / "d3d11.dll").write_bytes(b"mod dll")
    assert launcher._efmi_folder_is_sane(library, xxmi_root) is False


def test_system_modules_hijacked_detected(tmp_path: Path) -> None:
    """系统模块被 loader proxy 顶替时能被判出来（启动据此中止）。"""
    game = tmp_path / "game"
    game.mkdir()
    cfg = _config(tmp_path, game)
    assert launcher._system_modules_hijacked(cfg) == []
    (game / "vulkan-1.dll").write_bytes(b"[PROXY] plugins loaded via " + b"x" * 512)
    assert launcher._system_modules_hijacked(cfg) == ["vulkan-1.dll"]


def test_genuine_system_module_is_not_hijacked(tmp_path: Path) -> None:
    """真原版（大文件、无标记串）不许被误判成 proxy。"""
    game = tmp_path / "game"
    game.mkdir()
    cfg = _config(tmp_path, game)
    (game / "d3dcompiler_47.dll").write_bytes(b"MZ" + b"\x00" * (300 * 1024))
    assert launcher._system_modules_hijacked(cfg) == []