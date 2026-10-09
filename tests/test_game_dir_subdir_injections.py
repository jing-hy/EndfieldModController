"""含可执行文件的**子目录**里的注入物：要看得见、要清得掉、还要**完全可还原**（2026-10-09）。

**现场**（反馈者材料）：第三方一键工具 `dlss5oneclick 0.13.20` 把反作弊的服务程序
`ACE-Service64.exe` 认成了游戏主程序（它自己的报告里写着 `wrong exe picked`），于是把整套
ReShade 装进了 `<game>\\AntiCheatExpert\\`（`dxgi.dll` 5,592,064 B + `ReShade.ini` +
`reshade-shaders\\`）。而审计只扫游戏根目录 ⇒ **13 份诊断包一份都没报过它**。

**为什么子目录同样有效**：Windows 解析非 KnownDLL 时**先找"应用程序所在目录"**，
所以游戏目录下任何一个含 exe 的子目录都是有效的劫持位。

用户要求：「新 issue 也加进来，**要求能完全还原**」—— 所以本文件除了"看得见 / 清得掉"，
还钉住**还原之后子目录里的东西原样回到子目录**（相对路径要是 `AntiCheatExpert/dxgi.dll`；
只记文件名的话会把它还原到游戏根目录去）。

全部离线：不联网、不碰真实游戏目录。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import diagnostics, game_clean, reshade_integration
from endfieldmodcontroller.config import AppConfig

PROXY_MARKER = b"[PROXY] plugins loaded via d3dcompiler_47.dll\n"
RESHADE_PAYLOAD = b"MZ" + b"\x00" * 64 + PROXY_MARKER
SUBDIR = "AntiCheatExpert"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """假数据根 + 假游戏目录（净化 / 还原全都对着它跑）。"""
    config = AppConfig()
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: tmp_path / "runtime" / "dlss5"))
    monkeypatch.setattr(AppConfig, "game_exe_path", property(lambda self: game / "Endfield.exe"))
    (tmp_path / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, game_dir=None, **kw: Path(game_dir) if game_dir else game)
    return SimpleNamespace(tmp=tmp_path, config=config, game=game)


def _relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _inject_into_subdir(env) -> Path:
    """造出反馈者那种现场：反作弊目录里躺着整套 ReShade，旁边还有反作弊自己的 exe。"""
    ace = env.game / SUBDIR
    ace.mkdir(parents=True, exist_ok=True)
    (ace / "ACE-Service64.exe").write_bytes(b"MZ")            # 反作弊自己的，绝不能碰
    (ace / "dxgi.dll").write_bytes(RESHADE_PAYLOAD)           # ← 第三方注入物
    (ace / "ReShade.ini").write_text("[ReShade]\n", encoding="utf-8")
    shaders = ace / "reshade-shaders"
    shaders.mkdir()
    (shaders / "a.fx").write_text("// shader\n", encoding="utf-8")
    return ace


# ---------------------------------------------------------------------------
# ① 看得见
# ---------------------------------------------------------------------------
def test_audit_sees_injection_inside_subdir(env):
    """净化清单必须包含**子目录里**的注入物（只扫根目录 = 整体漏报）。"""
    _inject_into_subdir(env)
    result = game_clean.audit(env.config)
    relatives = {item["relative"] for item in result["findings"]}

    assert f"{SUBDIR}/dxgi.dll" in relatives
    assert f"{SUBDIR}/ReShade.ini" in relatives
    assert f"{SUBDIR}/reshade-shaders" in relatives


def test_injection_audit_reports_subdir_entries(env):
    """`audit_game_dir_injections()`（界面/自检那一路）同样要看得见。"""
    _inject_into_subdir(env)
    result = reshade_integration.audit_game_dir_injections(env.config)

    names = {item["name"] for item in result["suspicious"]}
    assert f"{SUBDIR}/dxgi.dll" in names, "子目录条目要带目录名，否则用户以为说的是根目录"


def test_diagnostics_summary_sees_subdir(env):
    """诊断包 summary 是用户唯一的现场 —— 也要报出来。"""
    _inject_into_subdir(env)
    blob = "\n".join(diagnostics._game_injection_summary(env.config, env.game))

    assert f"{SUBDIR}/dxgi.dll" in blob


# ---------------------------------------------------------------------------
# ② 清得掉，且不误伤
# ---------------------------------------------------------------------------
def test_clean_moves_subdir_injection_out(env):
    """净化把子目录里的注入物搬走，但反作弊自己的 exe 必须原样留着。"""
    ace = _inject_into_subdir(env)
    result = game_clean.backup_and_clean(env.config)

    assert result["ok"], result
    assert not (ace / "dxgi.dll").exists()
    assert not (ace / "ReShade.ini").exists()
    assert not (ace / "reshade-shaders").exists()
    assert (ace / "ACE-Service64.exe").is_file(), "反作弊自己的程序绝不能被搬走"

    backup_root = Path(result["backup_dir"])
    assert (backup_root / "files" / SUBDIR / "dxgi.dll").is_file()


# ---------------------------------------------------------------------------
# ③ ★ 完全还原（含目录结构）
# ---------------------------------------------------------------------------
def test_restore_puts_subdir_files_back_into_the_subdir(env):
    """★ 还原之后，子目录里的东西要**回到子目录**（而不是被倒进游戏根目录）。"""
    ace = _inject_into_subdir(env)
    before = _relative_files(env.game)

    result = game_clean.backup_and_clean(env.config)
    assert result["ok"], result

    restored = game_clean.restore(env.config, stamp=Path(result["backup_dir"]).name)

    assert restored["ok"], restored
    assert _relative_files(env.game) == before, "必须完全回到净化前的样子"
    assert (ace / "dxgi.dll").read_bytes() == RESHADE_PAYLOAD
    assert (ace / "reshade-shaders" / "a.fx").is_file()
    assert not (env.game / "dxgi.dll").exists(), "不许被还原到游戏根目录去"
