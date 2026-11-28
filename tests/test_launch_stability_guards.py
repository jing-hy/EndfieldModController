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
    r"""乳摇工具目录不存在 ⇒ **只跳过**，游戏目录里的文件一个都不动。

    2026-11-28 口径（用户：「sbm 本来就是独立加载的，应该保持独立加载」）：
    乳摇走自己的 loader proxy；工具目录缺失时我们只是**这一轮不铺**，
    绝不替用户拆掉已经铺着的那套 proxy（它可能是 Poser 的，两个组件共用同一个 loader），
    也不删 `plugin\sbm.dll`。要拆只有用户点「清理游戏目录注入」才算数。
    """
    game = tmp_path / "game"
    game.mkdir()
    # 造一个"以前铺过"的 proxy（小文件 + 标记串）
    proxy_bytes = b"[LOADER] started " + b"x" * 1024
    (game / "d3dcompiler_47.dll").write_bytes(proxy_bytes)
    cfg = _config(tmp_path, game,
                  secondary_motion_dir=str(tmp_path / "no-such-tool"),
                  secondary_motion_injection=True)
    result = secondary_motion.ensure_injection(cfg)
    assert result.get("ok") is True, result
    assert result.get("skipped") == "no-tool-dir", result
    # 原有那份 proxy 原样不动（不拆、不还原、不覆盖）
    assert (game / "d3dcompiler_47.dll").read_bytes() == proxy_bytes
    # 也没新写 vulkan-1.dll / plugin\sbm.dll
    assert not (game / "vulkan-1.dll").is_file()
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

def test_proxy_backup_never_fakes_game_original(tmp_path: Path) -> None:
    """没有 `.bak` 且本体已是 proxy ⇒ 返回 None，**不拿 System32 冒充游戏原版**。

    2026-11-28 实测：`d3dcompiler_47.dll` 游戏原版 4,524,496 B / System32 版 4,669,440 B；
    `vulkan-1.dll` 游戏原版 831,488 B / System32 版 1,730,096 B —— 根本不是同一个文件。
    以前这里"缺 .bak 就从 System32 拷一份"，结果 `.bak` 变成系统版、之后"还原"永远
    还原不出游戏原本那份（本机 `.bak` 现在就是这样）。
    """
    game = tmp_path / "game"
    game.mkdir()
    (game / "vulkan-1.dll").write_bytes(b"[LOADER] started " + b"x" * 1024)
    assert secondary_motion.ensure_proxy_backup(game, "vulkan-1.dll") is None
    assert not (game / "vulkan-1.dll.bak").is_file(), "不许凭空造一份假的游戏原版"