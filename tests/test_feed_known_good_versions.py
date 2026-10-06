"""★ feed（`dlss5-feed.addon64`）的"已知可用版本"白名单。

**为什么要有这个白名单**：它是**在线组件**，「一键安装/更新全部组件」本来就会装上游最新版
⇒ "不等于随包那一版"**不算异常**；只有落在集合之外才提醒，否则每次自检都刷噪音
（用户 2026-10-02 就是为此要求改成集合法）。

**2026-10-07 加 `344,064`（上游 1.18.0-beta.2）的依据** —— 本机实测，不是推测：
  * ReShade 日志：`Registered add-on "DLSS 5 Feed 1.18.0-beta.2" v1.18.0.2`（注册成功）
  * 同一次运行：NR `inline feature 18 evaluation succeeded (count=1 → count=60)`
  * 游戏 `Player.log` 444 行、末行是正常退出收尾（不是早退）
  * 与上游 Release 附件逐字节比对：sha256 `12011433dbdcc4ef…`（**未篡改**）

⚠️ 加它之前我一度想当然地说"新版不能用"，被用户质疑后用实测推翻 ——
这次把"实测依据"写进注释，避免以后又凭印象判断。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    # 不要碰真实的随包清单：只测 feed 那一条判据
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda cfg: [])
    config = AppConfig()
    config._config_path = str(tmp_path / "config.json")
    return config, dlss5


def test_beta2_is_known_good(env):
    """★ 上游 1.18.0-beta.2（344,064 B）必须**不再**被判成"不在已知可用的版本里"。"""
    config, dlss5 = env
    (dlss5 / runtime_assets.FEED_NAME).write_bytes(b"x" * 344_064)

    assert 344_064 in runtime_assets.FEED_KNOWN_GOOD_SIZES
    mismatches = runtime_assets.baseline_mismatches(config)
    assert mismatches == [], f"beta.2 仍被判为偏离：{mismatches}"


def test_beta1_and_bundled_still_known_good(env):
    """老的两个版本不能被弄丢（回归）。"""
    config, dlss5 = env
    for size in (76_800, 332_800):
        (dlss5 / runtime_assets.FEED_NAME).write_bytes(b"x" * size)
        assert runtime_assets.baseline_mismatches(config) == [], f"{size} 被判偏离"


def test_unknown_size_still_warns(env):
    """★★ 反向对照：**集合外**的尺寸仍要报警 —— 白名单不能变成"什么都不报"。"""
    config, dlss5 = env
    (dlss5 / runtime_assets.FEED_NAME).write_bytes(b"x" * 999_999)

    mismatches = runtime_assets.baseline_mismatches(config)
    assert len(mismatches) == 1, mismatches
    msg = mismatches[0]["message"]
    assert "不在已知可用" in msg
    # 文案里要把"已知可用的都有哪些"列出来，便于用户/我们对照
    assert "344,064" in msg and "332,800" in msg, msg


def test_bundled_size_still_verifies_hash(env, monkeypatch):
    """随包那一版（76,800）**仍要**校验 sha256（内容被换过要能查出来）。"""
    config, dlss5 = env
    (dlss5 / runtime_assets.FEED_NAME).write_bytes(b"x" * 76_800)
    monkeypatch.setattr(runtime_assets, "sha256_file", lambda p: "deadbeef" * 8)

    mismatches = runtime_assets.baseline_mismatches(config, check_hash=True)
    assert len(mismatches) == 1 and mismatches[0]["kind"] == "hash", mismatches
