"""「启动前清除所有第三方注入」开关的回归测试（2026-10-04）。

用户原话：「在设置做个开关，一键还原终末地清除所有第三方注入，**默认开**，
开了之后**不管是不是管理器注入的，都要去掉（要备份）**」。

这里钉住四件事：
① 开关关掉时**一个文件都不动**；
② 开关打开时，**别人的**注入（没带我们标记、只是顶替了系统模块的第三方 proxy）
   与 **3DMigoto 残留**（`d3dx.ini` / `ShaderFixes\\`）都被移走；
③ 移走前**先备份**（`game_backup\\<stamp>\\files\\…` + `manifest.json`），
   而且 `restore()` 能把原来那份**原样放回**（备份语义闭环）；
④ 游戏正在运行时**跳过**（文件被占用，也不该动用户正在用的游戏）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import game_clean, reshade_integration
from endfieldmodcontroller.config import AppConfig


def _config(tmp_path: Path, game: Path) -> AppConfig:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(tmp_path / "library"),
        game_exe=str(game / "Endfield.exe"),
        dlss5_dir=str(runtime / "dlss5"),
        builtin_runtime_dir=str(runtime / "builtin"),
        dependency_manifest=str(tmp_path / "dependencies.json"),
    )


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    (game / "Endfield.exe").write_bytes(b"MZ")
    config = _config(tmp_path, game)
    monkeypatch.setattr(reshade_integration, "detect_game_dir", lambda *a, **k: game)
    monkeypatch.setattr(game_clean, "_game_running", lambda *a, **k: False)
    # 假 System32：放两份"系统原版"（大小与游戏目录里那份不同 ⇒ 判为第三方 proxy）
    sysroot = tmp_path / "windows"
    (sysroot / "System32").mkdir(parents=True)
    (sysroot / "System32" / "d3dcompiler_47.dll").write_bytes(b"MZ" + b"\x00" * 400_000)
    (sysroot / "System32" / "winhttp.dll").write_bytes(b"MZ" + b"\x00" * 300_000)
    monkeypatch.setenv("SystemRoot", str(sysroot))
    return config, game


def test_default_is_on():
    """零配置即用：这个开关默认必须是开的。"""
    assert AppConfig().clear_game_injections_on_launch is True


def test_switch_off_does_nothing(env):
    config, game = env
    proxy = game / "d3dcompiler_47.dll"
    proxy.write_bytes(b"MZ" + b"\x00" * 2048)
    config.clear_game_injections_on_launch = False

    result = game_clean.auto_clean_before_launch(config)

    assert result["skipped"] == "switch_off"
    assert proxy.is_file()
    assert not (Path(config.runtime_path) / "game_backup").exists()


def test_skips_while_game_running(env, monkeypatch):
    config, game = env
    proxy = game / "d3dcompiler_47.dll"
    proxy.write_bytes(b"MZ" + b"\x00" * 2048)
    monkeypatch.setattr(game_clean, "_game_running", lambda *a, **k: True)

    result = game_clean.auto_clean_before_launch(config)

    assert result["skipped"] == "game_running"
    assert proxy.is_file()


def test_foreign_proxy_is_moved_and_system_module_put_back(env):
    """**别人的** proxy（只有"与 System32 不同"这一条命中）也要被移走，
    并且必须把系统原版补回去（否则游戏当场起不来）。"""
    config, game = env
    proxy = game / "d3dcompiler_47.dll"
    original = b"MZ" + b"\x00" * 2048
    proxy.write_bytes(original)

    result = game_clean.auto_clean_before_launch(config)

    assert result["moved"], result
    assert "d3dcompiler_47.dll" in {item["relative"] for item in result["moved"]}
    assert proxy.is_file(), "系统原版要补回游戏目录"
    assert proxy.stat().st_size > 200_000, "留下的应该是系统原版，而不是那份 proxy"
    backup = Path(result["backup_dir"])
    assert (backup / "manifest.json").is_file()
    assert (backup / "files" / "d3dcompiler_47.dll").is_file()
    assert (backup / "files" / "d3dcompiler_47.dll").read_bytes() == original


def test_our_own_loader_proxy_is_cleared_too(env):
    """「不管是不是管理器注入的」—— 我们自己铺的 loader proxy 同样要清掉。"""
    config, game = env
    proxy = game / "d3dcompiler_47.dll"
    proxy.write_bytes(b"[LOADER] started" + b"\x00" * 2048)

    result = game_clean.auto_clean_before_launch(config)

    categories = {item["category"] for item in result["moved"]}
    assert "loader_proxy" in categories, result


def test_injector_artifacts_are_cleared(env):
    """3DMigoto / 自造 loader 的残留（非 DLL）也算"第三方注入痕迹"，一并移走。"""
    config, game = env
    (game / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")
    (game / "ShaderFixes").mkdir()
    (game / "ShaderFixes" / "shader.txt").write_text("x", encoding="utf-8")

    result = game_clean.auto_clean_before_launch(config)

    moved = {item["relative"] for item in result["moved"]}
    assert "d3dx.ini" in moved and "ShaderFixes" in moved
    assert not (game / "d3dx.ini").exists()
    assert not (game / "ShaderFixes").exists()


def test_clean_game_dir_needs_no_action_when_already_clean(env):
    config, _game = env
    result = game_clean.auto_clean_before_launch(config)
    assert result["ok"] is True
    assert not result.get("moved")
    assert not (Path(config.runtime_path) / "game_backup").exists()


def test_restore_puts_the_originals_back(env):
    """备份语义闭环：清除之后 `restore()` 能把原来那份 proxy 与 ini 原样放回。"""
    config, game = env
    proxy = game / "d3dcompiler_47.dll"
    original = b"MZ" + b"\x00" * 2048
    proxy.write_bytes(original)
    (game / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")

    result = game_clean.auto_clean_before_launch(config)
    assert result["moved"]

    restored = game_clean.restore(config)

    assert restored["ok"], restored
    assert proxy.is_file() and proxy.read_bytes() == original
    assert (game / "d3dx.ini").is_file()


def test_audit_lists_no_duplicates_for_same_path(env):
    """同一路径不能被两个分类各收一条（否则净化会把同一份东西搬两次、报假错误）。"""
    config, game = env
    (game / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")
    report = game_clean.audit(config)
    relatives = [item["relative"] for item in report["findings"]]
    assert len(relatives) == len(set(relatives)), relatives


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
