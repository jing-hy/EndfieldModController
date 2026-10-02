"""随包组件基线：**自动修复**与运行时清单（2026-10-02 用户现场驱动）。

用户那天的经历：配套里有文件偏离随包基线 ⇒ 游戏每次启动几十秒后崩在 `nvgpucomp64`，
而自检**只提示、不修**，他最后只能自己把整个 `runtime\\` 删掉重下才好。
⇒ 随包组件坏掉要**自动按基线重展开（先备份）**；在线组件（feed）**不自动修**。

全部离线：路径都指到 tmp_path，不碰工作区真实文件。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    # **必须给它一个落盘路径**：`base_dir` 在 `_config_path` 为空时会退回「项目根」，
    # 那样 assets / runtime 会落到工作区真实目录（同族坑见 lesson 0muqfp9u）。
    config.save(tmp_path / "config.json")
    dlss5 = tmp_path / "dlss5"
    dlss5.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    # 造一份"随包资产"：一个 addon
    group = "dlss5"
    assets = tmp_path / "assets" / group
    assets.mkdir(parents=True)
    # 资产在磁盘上存的是 **xz 压缩分卷**（`ensure_file` 解的是 `parts` 里的分卷，不是明文）
    # —— 所以造资产必须连 `.xz` 一起造，否则修复路径根本跑不通。
    import hashlib
    import lzma

    payload = b"BASELINE-CONTENT" * 4
    packed = lzma.compress(payload)
    (assets / "demo.addon64.xz").write_bytes(packed)
    (assets / "manifest.json").write_text(
        json.dumps({
            "files": {
                "demo.addon64": {
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "packed_bytes": len(packed),
                    "packed_sha256": hashlib.sha256(packed).hexdigest(),
                    "parts": ["demo.addon64.xz"],
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_assets, "ASSET_GROUPS", (group,))

    # ⚠️ `group_root` 是按**项目根**（不是数据根 `base_dir`）推导随包资产目录的 ——
    # 不打桩就会读到**工作区真实的** `assets\dlss5\manifest.json`，测试等于在测别人的资产。
    def _fake_group_root(config, name):
        return assets if name == group else None

    monkeypatch.setattr(runtime_assets, "group_root", _fake_group_root)
    return SimpleNamespace(
        tmp=tmp_path, config=config, dlss5=dlss5, assets=assets, payload=payload
    )


def test_repair_restores_the_baseline_and_keeps_a_backup(env):
    broken = env.dlss5 / "demo.addon64"
    broken.write_bytes(b"TAMPERED" * 10)          # 被别的整合包换过
    bad = runtime_assets.baseline_mismatches(env.config)
    assert [item["name"] for item in bad] == ["demo.addon64"]
    result = runtime_assets.repair_mismatched(env.config, bad)
    assert result["ok"] is True
    assert result["repaired"] == ["demo.addon64"]
    assert broken.read_bytes() == env.payload      # 已按基线还原
    backup = env.dlss5 / "demo.addon64.bak-before-baseline-restore"
    assert backup.is_file() and b"TAMPERED" in backup.read_bytes()   # 原文件留了备份


def test_repair_never_touches_online_components(env):
    """在线组件（`dlss5-feed.addon64`）**不自动修** —— 它本来就允许换成上游最新版。"""
    # 先把随包那一项就位（否则它自己也属于"缺失"，会被一起修、干扰断言）
    (env.dlss5 / "demo.addon64").write_bytes(env.payload)
    feed = env.dlss5 / runtime_assets.FEED_NAME
    feed.write_bytes(b"x" * 999_999)
    bad = runtime_assets.baseline_mismatches(env.config)
    assert [item["name"] for item in bad] == [runtime_assets.FEED_NAME]
    result = runtime_assets.repair_mismatched(env.config, bad)
    assert result["repaired"] == []
    assert feed.stat().st_size == 999_999          # 一个字节都没动


def test_missing_asset_is_repaired_too(env):
    """整个文件丢了也能补回来（"缺失"同样属于随包不一致）。"""
    bad = runtime_assets.baseline_mismatches(env.config)
    assert any(item["kind"] == "missing" for item in bad)
    result = runtime_assets.repair_mismatched(env.config, bad)
    assert result["ok"] is True
    assert (env.dlss5 / "demo.addon64").read_bytes() == env.payload


def test_inventory_lists_files_with_hash_and_baseline_mark(env):
    (env.dlss5 / "demo.addon64").write_bytes(b"TAMPERED")
    text = runtime_assets.inventory_text(env.config)
    assert "demo.addon64" in text
    assert "!!" in text                            # 偏离基线的会被标出来
    assert "runtime\\dlss5" in text
