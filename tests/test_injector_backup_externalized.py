"""游戏目录里的**备份文件**也要搬到外部（2026-10-09 用户要求）。

用户原话：「在终末地本体清空之后，不要留备份在终末地的文件夹，全部处理到外面，
如果部分用户之前用过还原，那些备份文件也要能自动处理到外部，还原也是用外部还原」。

**现场**：`<game>\\d3dcompiler_47.dll.bak` 这类原版备份是**注入过程的副产品**
（loader 把原版挪成 `.bak`、再把自己的 proxy 放上去）。净化把 proxy 移走后，它们就成了
没有主人的残留 —— 原版游戏目录不该有它们，而用户看到的是"我点了还原、目录里还是一堆
备份文件"。所以现在连它们一起搬进**游戏目录之外**的备份区。

本文件守住五件事：

① `audit()` 要看见它们（新分类 `injector_backup`）；
② 净化后**游戏目录里一个注入备份都不剩**，而备份区（游戏目录之外）里有它们；
③ **完全还原**：`restore()` 之后游戏目录与净化**前**逐文件一致（备份文件也回来）；
④ 不误伤：与注入无关的 `.bak`（游戏自己的 / 用户自己放的）一律不碰；
⑤ 顺序：`.bak` 必须**先**用来把系统原版放回游戏目录，**之后**才被搬走。

全部离线：不联网、不碰真实游戏目录，路径都指到 tmp_path。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import game_clean, reshade_integration
from endfieldmodcontroller.config import AppConfig

# 判据是**标记级**的（`looks_like_loader_proxy()` 认这些串），所以造一个带标记的小文件
# 就等价于"这是个 loader proxy"，不需要真的 DLL。
POSER_PROXY = b"MZ" + b"\x00" * 64 + b"[PROXY] plugins loaded via d3dcompiler_47.dll\n"
REAL_MODULE = b"MZ" + b"\x00" * 4096
PROXY_NAME = "d3dcompiler_47.dll"


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


def _findings(env) -> dict[str, dict]:
    result = game_clean.audit(env.config)
    return {item["relative"]: item for item in result["findings"]}


def _inject(env) -> None:
    """造一个"注入过"的游戏目录：proxy 在位 + 它的原版备份 + 两者无关的备份。"""
    game = env.game
    (game / PROXY_NAME).write_bytes(POSER_PROXY)
    (game / f"{PROXY_NAME}.bak").write_bytes(REAL_MODULE)
    (game / "nvngx_dlss.dll.game_original").write_bytes(REAL_MODULE)
    (game / "readme.txt.bak").write_bytes(b"not ours")
    (game / "存档.bak").write_bytes(b"user data")


# ---------------------------------------------------------------------------
# ① 被看见
# ---------------------------------------------------------------------------
def test_audit_sees_injector_backups(env):
    """备份文件必须进净化清单 —— 看不见就永远留在游戏目录里。"""
    _inject(env)
    found = _findings(env)

    assert found[f"{PROXY_NAME}.bak"]["category"] == "injector_backup"
    assert found["nvngx_dlss.dll.game_original"]["category"] == "injector_backup"


def test_audit_ignores_unrelated_backups(env):
    """④ 与注入无关的备份一律不碰（只认已知注入相关名字的变体）。"""
    _inject(env)
    found = _findings(env)

    assert "readme.txt.bak" not in found
    assert "存档.bak" not in found


# ---------------------------------------------------------------------------
# ② 净化后游戏目录里不留备份
# ---------------------------------------------------------------------------
def test_clean_leaves_no_backup_in_game_dir(env):
    """② 净化之后，注入备份一个都不许剩，而且必须落在**游戏目录之外**。"""
    _inject(env)
    result = game_clean.backup_and_clean(env.config)

    assert result["ok"], result
    assert not (env.game / f"{PROXY_NAME}.bak").exists(), "原版备份不许留在游戏目录里"
    assert not (env.game / "nvngx_dlss.dll.game_original").exists()
    # 与注入无关的东西原样留着
    assert (env.game / "readme.txt.bak").is_file()
    assert (env.game / "存档.bak").is_file()

    backup_root = Path(result["backup_dir"])
    assert not backup_root.is_relative_to(env.game), "备份区必须在游戏目录之外"
    assert (backup_root / "files" / f"{PROXY_NAME}.bak").is_file()
    assert (backup_root / "files" / "nvngx_dlss.dll.game_original").is_file()


# ---------------------------------------------------------------------------
# ③ ★ 完全还原
# ---------------------------------------------------------------------------
def test_restore_round_trip_is_complete(env):
    """③ ★ 完全还原：净化 → 还原之后，游戏目录与净化**前**逐文件一致。"""
    _inject(env)
    before = _relative_files(env.game)

    result = game_clean.backup_and_clean(env.config)
    assert result["ok"], result
    assert _relative_files(env.game) != before, "前提：净化确实动过游戏目录"

    restored = game_clean.restore(env.config, stamp=Path(result["backup_dir"]).name)

    assert restored["ok"], restored
    assert _relative_files(env.game) == before, "还原必须完全回到净化前（含被搬走的备份文件）"
    assert (env.game / f"{PROXY_NAME}.bak").read_bytes() == REAL_MODULE
    assert (env.game / "nvngx_dlss.dll.game_original").read_bytes() == REAL_MODULE


# ---------------------------------------------------------------------------
# ⑤ 顺序：先用来放回原版，再搬走
# ---------------------------------------------------------------------------
def test_system_module_is_restored_from_the_bak_before_it_moves(env):
    """⑤ `.bak` 要**先**把游戏原本那份系统模块放回去，之后才被搬走。

    反过来（先搬 `.bak`）也能跑完，但放回的是 System32 那一份 —— 不是游戏原本那份。
    这条断言正好能区分两种顺序。
    """
    _inject(env)
    game_clean.backup_and_clean(env.config)

    assert (env.game / PROXY_NAME).read_bytes() == REAL_MODULE, "必须用游戏原本的 .bak 恢复"
