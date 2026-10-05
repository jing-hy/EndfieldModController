"""游戏目录净化判据 + 备份语义 + 「依赖清空并重新下载」的回归测试（v1.0.11）。

三个坑各自都有具体现场：

1. **`system_module_differs()` 原来只比大小** ⇒ "被换成**同大小**的另一份 dll"这种顶替
   完全判不出来，净化会把它当"游戏自带"留在游戏目录里（而它照样会造成同名双实例、
   把图形 hook 打偏）。
2. **`list_backups()` 漏掉"清单存在但读不出来"的备份** ⇒ `restore()` 说"没有备份" ⇒
   「依赖清空」放行后会把这份**唯一的备份**连同 `runtime\\` 一起删掉。
3. **「依赖清空」第二次执行必然报错**：它先还原、再删 `runtime\\`（唯一还原点
   `runtime\\game_backup\\` 就在里面）⇒ 第二次变成"没有找到任何游戏目录备份"，
   撞上"还原失败不许往下清"的保护 ⇒ 用户从此点不动。判据必须区分
   **"没有备份可还原"（放行）** 与 **"有备份却还原不了"（中止）**。

全部离线：不联网、不碰真实游戏目录，路径都指到 tmp_path。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import game_clean, reshade_integration
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig

SYSTEM32_DXGI = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "dxgi.dll"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """假数据根 + 假游戏目录（净化判据全都对着它跑）。"""
    config = AppConfig()
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: tmp_path / "runtime" / "dlss5"))
    monkeypatch.setattr(AppConfig, "game_exe_path", property(lambda self: game / "Endfield.exe"))
    (tmp_path / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    # `detect_game_dir` 在真机上会按启动器推断；这里直接指到假游戏目录
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, game_dir=None, **kw: Path(game_dir) if game_dir else game)
    return SimpleNamespace(tmp=tmp_path, config=config, game=game)


def _findings(env) -> dict[str, dict]:
    """`audit()` 的 findings 是 `Finding.to_dict()` 出来的 dict 列表（按相对路径做索引）。"""
    result = game_clean.audit(env.config)
    return {item["relative"]: item for item in result["findings"]}


# ---------------------------------------------------------------------------
# ① 内容级判定（大小 + sha256）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not SYSTEM32_DXGI.is_file(), reason="这台机器上没有 System32\\dxgi.dll 可作基准")
def test_system_module_differs_detects_same_size_tamper(env):
    """**核心回归**：同大小、内容被改过 ⇒ 必须判为"不同"（退回"只比大小"就会变红）。"""
    original = SYSTEM32_DXGI.read_bytes()
    tampered = env.tmp / "dxgi.dll"
    payload = bytearray(original)
    payload[len(payload) // 2] ^= 0xFF
    tampered.write_bytes(bytes(payload))

    assert tampered.stat().st_size == SYSTEM32_DXGI.stat().st_size, "前提：大小必须一样"
    assert reshade_integration.system_module_differs("dxgi.dll", tampered) is True
    assert reshade_integration.duplicate_of_system_module(tampered) is False


@pytest.mark.skipif(not SYSTEM32_DXGI.is_file(), reason="这台机器上没有 System32\\dxgi.dll 可作基准")
def test_duplicate_of_system_module_true_for_exact_copy(env):
    copy = env.tmp / "dxgi.dll"
    shutil.copy2(SYSTEM32_DXGI, copy)
    assert reshade_integration.duplicate_of_system_module(copy) is True
    assert reshade_integration.system_module_differs("dxgi.dll", copy) is False


# ---------------------------------------------------------------------------
# ② 净化：该搬的搬、不该动的别动
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not SYSTEM32_DXGI.is_file(), reason="这台机器上没有 System32\\dxgi.dll 可作基准")
def test_audit_flags_same_size_tampered_dxgi(env):
    payload = bytearray(SYSTEM32_DXGI.read_bytes())
    payload[len(payload) // 2] ^= 0xFF
    (env.game / "dxgi.dll").write_bytes(bytes(payload))

    assert "dxgi.dll" in _findings(env), "同大小但被改过的 dxgi.dll 必须进净化清单"


@pytest.mark.skipif(not SYSTEM32_DXGI.is_file(), reason="这台机器上没有 System32\\dxgi.dll 可作基准")
def test_audit_leaves_pure_system_copy_alone(env):
    """与 System32 一模一样的副本**不许动**（可能是启动器/官方更新铺的，搬走会让校验失败）。"""
    shutil.copy2(SYSTEM32_DXGI, env.game / "dxgi.dll")
    assert "dxgi.dll" not in _findings(env)


def test_audit_flags_reshade_like_dxgi_once(env):
    """内容像 ReShade 的 `dxgi.dll` 要进清单，而且**同一条只报一次**（两段名单有重叠）。"""
    (env.game / "dxgi.dll").write_bytes(b"MZ" + b"\x00" * 512 + b"crosire ReShade add-on host")
    findings = _findings(env)
    assert "dxgi.dll" in findings
    result = game_clean.audit(env.config)
    assert sum(1 for item in result["findings"] if item["relative"] == "dxgi.dll") == 1


def test_audit_flags_rotated_reshade_log(env):
    """`ReShade.log1`（轮转日志）也是"游戏目录装过 ReShade"的证据，必须能进清单。"""
    (env.game / "ReShade.log1").write_text("23:51:18:684 [ 3252] | INFO | Initializing crosire's ReShade",
                                           encoding="utf-8")
    assert "ReShade.log1" in _findings(env)


# ---------------------------------------------------------------------------
# ③ 备份语义
# ---------------------------------------------------------------------------
def _make_backup(root: Path, stamp: str, *, manifest: str | None, payload: bytes | None) -> Path:
    backup = root / "runtime" / "game_backup" / stamp
    if payload is not None:
        files = backup / "files" / "plugin"
        files.mkdir(parents=True, exist_ok=True)
        (files / "sbm.dll").write_bytes(payload)
    else:
        backup.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (backup / "manifest.json").write_text(manifest, encoding="utf-8")
    return backup


def test_list_backups_reports_broken_manifest_with_payload(env):
    """**核心回归**：清单写坏但 `files\\` 有东西 ⇒ 必须列出来（否则清空会把它一起删掉）。"""
    _make_backup(env.tmp, "20260101-000000", manifest="{ 这不是合法 JSON", payload=b"z" * 16)
    rows = game_clean.list_backups(env.config)
    assert [row["stamp"] for row in rows] == ["20260101-000000"]
    assert rows[0]["kind"] == "clean" and rows[0]["incomplete"] is True
    assert game_clean.restore(env.config)["ok"] is False, "清单读不出来 ⇒ 还原必须如实失败"


def test_list_backups_skips_broken_manifest_without_payload(env):
    """清单坏了、`files\\` 也是空的 ⇒ 空壳不该列（列出来会让"清空"永远被拦下）。"""
    _make_backup(env.tmp, "20260102-000000", manifest="{ 坏", payload=None)
    assert game_clean.list_backups(env.config) == []


def test_list_backups_skips_empty_dir(env):
    _make_backup(env.tmp, "20260103-000000", manifest=None, payload=None)
    assert game_clean.list_backups(env.config) == []


# ---------------------------------------------------------------------------
# ④ 「依赖清空并重新下载」：没有备份就放行，真有备份还原不了才中止
# ---------------------------------------------------------------------------
def _api_case(tmp_path: Path, *, with_broken_backup: bool) -> tuple[Path, EndfieldModControllerApi]:
    root = tmp_path / ("case_bad" if with_broken_backup else "case_none")
    (root / "runtime" / "dlss5").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "dlss5" / "dummy.bin").write_bytes(b"x" * 64)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "junk.bin").write_bytes(b"y" * 32)
    if with_broken_backup:
        _make_backup(root, "20260101-000000", manifest="{ 坏", payload=b"z" * 16)
    (root / "config.json").write_text(json.dumps({
        "library_dir": "library", "runtime_dir": "runtime",
        "game_exe": str(root / "fake" / "Endfield.exe"),     # 假游戏目录：绝不动真游戏
        "data_root": str(root),
    }, ensure_ascii=False), encoding="utf-8")
    return root, EndfieldModControllerApi(root / "config.json")


def test_reset_dependencies_proceeds_without_backup(tmp_path):
    """**核心回归**：第二次点（`game_backup` 已被上一步清掉）必须能继续，而不是报错中止。"""
    root, api = _api_case(tmp_path, with_broken_backup=False)

    result = api.reset_dependencies_and_redownload()

    assert result["ok"] is True, result.get("message")
    assert result.get("aborted") is None
    assert not (root / "assets").exists(), "放行时 assets 应当被清掉"
    assert not (root / "runtime" / "dlss5" / "dummy.bin").exists()


def test_reset_dependencies_aborts_when_backup_unrestorable(tmp_path):
    """真有备份却还原不了 ⇒ 必须中止，而且**一个字节都不许删**（保护唯一还原点）。"""
    root, api = _api_case(tmp_path, with_broken_backup=True)

    result = api.reset_dependencies_and_redownload()

    assert result["ok"] is False and result.get("aborted") == "restore_failed"
    assert (root / "assets" / "junk.bin").exists(), "中止时不许清空"
    assert (root / "runtime" / "dlss5" / "dummy.bin").exists()
    assert "game_backup" in str(result["message"])
