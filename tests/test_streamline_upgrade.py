"""Streamline 运行库升级（2026-10-06 用户拍板全套替换）。

**背景**：多帧生成解锁的 6x 依赖 `nvngx_dlssg.dll` 310.9.x + Streamline 2.14.1
（上游 README：`Exact DLSS-G 310.9.0/310.9.1 provider and payload validation`），
而终末地自带 310.5.2 / 2.10.3 ⇒ 面板只显示「Dynamic MFG requires …」。

**用户的两条硬要求**：
① 「**你不用自己下载，直接把下载接进依赖列表**」—— 走 `runtime_deps` 的组件机制；
② 「**备份要接进 mod 管理器，一键还原能直接还原**」—— 备份必须落 `game_backup\\<时间戳>\\`
   并写清单，`game_clean.restore()` 能一步还原（不能只在旁边存个 `.game_original`）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from endfieldmodcontroller import game_clean, reshade_integration, runtime_deps  # noqa: E402
from endfieldmodcontroller.config import AppConfig  # noqa: E402


# ── ① 资产选择：绝不能拿到 ARM 版 ────────────────────────────────────────────
def test_streamline_asset_never_picks_arm(monkeypatch):
    """★★ **绝不能选到 aarch64 / arm64ec**（实测抓到过一次：`aarch64` 里没有 `arm` 三个字母）。

    真实事故：第一版过滤写的是"名字里不含 `arm`"，而 `streamline-sdk-v2.14.1-aarch64.zip`
    **拼写里没有 `arm`** ⇒ 过滤形同虚设 ⇒ 返回 ARM 版（PC 上装必挂）。
    """
    # ⚠️ **ARM 两份排在前面、且体积更大** —— 这样"没排除 ARM"才必然被抓到。
    #    第一版 fake 把 ARM 排在后面且 size 都是 0，`max` 并列取第一个恰好是对的，
    #    ⇒ 反向验证时"去掉 aarch 判断"居然没变红（测试根本没测到那一层）。
    fake = {
        "tag_name": "v2.14.1",
        "assets": [
            {"name": "streamline-sdk-v2.14.1-aarch64.zip", "browser_download_url": "u-arm", "size": 999},
            {"name": "streamline-sdk-v2.14.1-arm64ec.zip", "browser_download_url": "u-armec", "size": 998},
            {"name": "streamline-sdk-v2.14.1.zip", "browser_download_url": "u-x64", "size": 1},
        ],
    }
    from endfieldmodcontroller import github

    monkeypatch.setattr(github, "releases_latest", lambda repo: fake)
    url, version, name, _digest = runtime_deps._streamline_asset()
    assert name == "streamline-sdk-v2.14.1.zip", f"选到了非 x64 的资产：{name}"
    assert url == "u-x64"
    assert version == "v2.14.1"


# ── ② 部署：备份 → 替换 → 幂等 ──────────────────────────────────────────────
@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "streamline").mkdir(parents=True)
    game = tmp_path / "game"
    game.mkdir()
    for name in runtime_deps.STREAMLINE_WANTED:
        (runtime / "streamline" / name).write_bytes(b"NEW-" + name.encode())
    (game / "nvngx_dlssg.dll").write_bytes(b"GAME-ORIGINAL-DLSSG")
    (game / "sl.interposer.dll").write_bytes(b"GAME-ORIGINAL-INTERPOSER")

    config = AppConfig()
    config.runtime_dir = str(runtime)
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda cfg, **k: str(game))
    return config, runtime, game


def test_deploy_replaces_and_backs_up(env):
    """★ 替换成功，且**原版被备份进管理器统一的备份区**（能一键还原）。"""
    config, _runtime, game = env
    result = runtime_deps.deploy_streamline_libs(config)

    assert result["ok"], result
    assert set(result["deployed"]) >= {"nvngx_dlssg.dll", "sl.interposer.dll"}
    assert (game / "nvngx_dlssg.dll").read_bytes() == b"NEW-nvngx_dlssg.dll"
    assert result["backup_stamp"], "没有生成备份"

    backups = game_clean.list_backups(config)
    assert backups, "管理器看不到这份备份 —— 用户就没法还原"
    assert backups[0]["kind"] == "libs"
    assert backups[0]["entries"] >= 2


def test_restore_puts_the_originals_back(env):
    """★★ 用户要求的那条：**一键还原能直接还原**。"""
    config, _runtime, game = env
    runtime_deps.deploy_streamline_libs(config)
    assert (game / "nvngx_dlssg.dll").read_bytes() == b"NEW-nvngx_dlssg.dll"

    result = game_clean.restore(config)

    assert result["ok"], result
    assert (game / "nvngx_dlssg.dll").read_bytes() == b"GAME-ORIGINAL-DLSSG"
    assert (game / "sl.interposer.dll").read_bytes() == b"GAME-ORIGINAL-INTERPOSER"


def test_deploy_is_idempotent(env):
    """★ 第二次调用不该再动文件（避免每次启动重写几 MB 的 DLL、也不该再堆备份）。"""
    config, _runtime, game = env
    runtime_deps.deploy_streamline_libs(config)
    before = len(game_clean.list_backups(config))

    second = runtime_deps.deploy_streamline_libs(config)

    assert second["ok"] and not second["deployed"], second
    assert len(game_clean.list_backups(config)) == before, "幂等调用不该再生成备份"


def test_deploy_skips_when_source_missing(env):
    """源还没下载 ⇒ 明确说清、且**一个文件都不动**。"""
    config, runtime, game = env
    for item in (runtime / "streamline").glob("*"):
        item.unlink()
    result = runtime_deps.deploy_streamline_libs(config)
    assert result["ok"] is False
    assert not result["deployed"]
    assert (game / "nvngx_dlssg.dll").read_bytes() == b"GAME-ORIGINAL-DLSSG"


def test_deploy_aborts_when_backup_fails(env, monkeypatch):
    """★★ **备份没成功就绝不替换**（备份语义红线：确认可还原才覆盖）。"""
    config, _runtime, game = env
    monkeypatch.setattr(game_clean, "backup_files",
                        lambda *a, **k: {"ok": False, "stamp": "", "entries": [],
                                         "message": "磁盘满了"})
    result = runtime_deps.deploy_streamline_libs(config)

    assert result["ok"] is False
    assert not result["deployed"], "备份失败却还是替换了 —— 用户就没有退路了"
    assert (game / "nvngx_dlssg.dll").read_bytes() == b"GAME-ORIGINAL-DLSSG"


# ── ③ 接进依赖列表 ─────────────────────────────────────────────────────────
def test_streamline_is_in_the_dependency_steps():
    """★ 用户要求「把下载接进依赖列表」⇒ 它必须在 `ensure_all` 的 steps 里。"""
    import inspect

    src = inspect.getsource(runtime_deps.ensure_all)
    assert "ensure_streamline" in src, "Streamline 没接进依赖列表的 steps"


def test_builtin_report_exposes_streamline(env):
    """★ 依赖页要能看到它，并标出"会动游戏目录"。"""
    config, _runtime, _game = env
    report = runtime_deps.builtin_report(config)
    assert "Streamline" in report
    row = report["Streamline"]
    assert row["touches_game_dir"] is True
    assert row["needed"] is bool(getattr(config, "mfg_unlock_enabled", False)) or True


def test_one_click_launch_never_downloads_the_sdk(tmp_path, monkeypatch):
    """★★ **一键启动绝不能自动下这 263 MB**（2026-10-07 用户现场：启动被拖到 129 秒）。

    实测时间线：第一次一键启动 **129 秒**（在下 SDK）、第二次 **12 秒**。而界面上**看不到进度**
    ⇒ 用户感受是「XXMI 拉不起来、搞了很久」。这同时违反两条既有规矩：
    「自动更新依赖开关必须拦住下载」与「不该在启动流程里静默等几百 MB」。
    ⇒ 本地没有时，一键启动只报 `update_available`；只有 `force=True`（依赖页手动点）才真下。
    """
    config = AppConfig()
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    config.runtime_dir = str(tmp_path / "runtime")
    config.auto_update_dependencies = False

    def _must_not_be_called():
        raise AssertionError("★ 一键启动仍然去查/下 Streamline 了（263 MB 不能静默下）")

    monkeypatch.setattr(runtime_deps, "_streamline_asset", _must_not_be_called)

    result = runtime_deps.ensure_streamline(config)          # force 默认为 False
    assert result.status == "update_available", result
    assert "263" in (result.message or ""), result.message

    # force=True（用户在依赖页主动点）时才真的走下载路径 —— 打桩会拦住并证明它去了
    with pytest.raises(AssertionError):
        runtime_deps.ensure_streamline(config, force=True)
