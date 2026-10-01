"""资产包获取与"数据不能写进临时解压目录"的回归测试（2026-10-01，来自一份真实诊断包）。

那台机器的日志给出了完整链条：
```
WARN 初始化: bundled_assets: 找不到随包资产（assets\\nvngx\\manifest.json / assets\\dlss5\\manifest.json）
WARN 初始化: dlss5:renodx-endfield-enhancer.addon64: 缺失且找不到素材来源
WARN 初始化: dlss5:trans-zh.addon64: 缺失且找不到素材来源
WARN 初始化: dlss5:plugin: 找不到 RenoDX-DLSS5 插件
WARN 初始化: dlss5:shader_deps: 缺少 DLSS5 shader 依赖 …
WARN 初始化: game:nvngx_dlssnr.dll: 游戏目录缺该文件，内置副本也没有
资产包获取失败，重试第 1/3 次 … → 未能获取资产包：查询 Release 失败：HTTP Error 403: rate limit exceeded
```
即：**数据根没有 `assets\\`，而自动补资产的那条路只打 API，匿名额度用尽（403）就彻底拿不到** ——
于是三个 addon / 6 个 shader 标准头 / Textures / 两个 nvngx 全缺，用户在游戏里看到的就是
「缺失第一人称插件 renodx-endfield-enhancer.addon64、无法修复」。

同一条日志还暴露了**我们自己引入的 bug**：`乳摇数据补充：… （C:\\Users\\…\\Temp\\_MEI00004bdc2\\assets\\…）`
—— `_assets_root()` 在"数据根没有 assets"时退回了 `_MEIPASS`，把数据写进了 PyInstaller 的临时目录。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import github, runtime_assets, sbm_data_sync, secondary_motion
from endfieldmodcontroller.config import AppConfig


# --------------------------------------------------------------- ① 资产包：网页优先 + 回退
def test_fetch_bundle_prefers_web_route(tmp_path, monkeypatch):
    """网页路线能拿到 release 时，**不允许**再去打 API（API 额度用尽正是那台机器卡死的点）。"""
    monkeypatch.setattr(runtime_assets, "PROJECT_ROOT", tmp_path)
    calls: list[bool] = []

    def fake_latest(repo, *, prefer_api=False, ttl=3600):
        calls.append(prefer_api)
        if prefer_api:
            raise AssertionError("网页路线已经成功，不该再打 API")
        return {
            "tag_name": "v9.9.9", "source": "web",
            "assets": [{
                "name": "assets-bundle.zip",
                "browser_download_url": "https://example.invalid/assets-bundle.zip",
                "size": 0,
            }],
        }

    monkeypatch.setattr(github, "releases_latest", fake_latest)
    # 下载阶段让它失败（不联网）：我们只验证"走到了网页路线"
    monkeypatch.setattr(runtime_assets, "fastnet", SimpleNamespace(
        download=lambda *a, **k: SimpleNamespace(ok=False, message="测试中不下载")),
        raising=False)
    monkeypatch.setattr(github, "api_get", lambda *a, **k: {"assets": []})

    config = AppConfig(runtime_dir=str(tmp_path / "runtime"))
    result = runtime_assets.fetch_bundle(config, force=True)

    assert calls == [False], calls
    assert "查询 Release 失败" not in str(result.get("message") or ""), result
    assert result["ok"] is False and "下载" in str(result.get("message") or "")


def test_fetch_bundle_falls_back_to_api_when_web_fails(tmp_path, monkeypatch):
    """网页路线不通 → 回退 API（而不是直接放弃）。"""
    monkeypatch.setattr(runtime_assets, "PROJECT_ROOT", tmp_path)
    seen: list[bool] = []

    def fake_latest(repo, *, prefer_api=False, ttl=3600):
        seen.append(prefer_api)
        if not prefer_api:
            raise RuntimeError("网页不通")
        return {"tag_name": "v1", "assets": []}

    monkeypatch.setattr(github, "releases_latest", fake_latest)
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"))
    result = runtime_assets.fetch_bundle(config, force=True)

    assert seen == [False, True], seen
    assert "没有 assets-bundle.zip" in str(result.get("message") or "") or result["ok"] is False


# --------------------------------------------------------------- ② 数据不许写进 _MEIPASS
def test_assets_root_returns_data_root_even_when_missing(tmp_path):
    """数据根还没有 `assets\\` 时也必须返回它 —— 早先退回 `_MEIPASS` 就会把数据写进临时目录。"""
    fake_config = SimpleNamespace(base_dir=tmp_path)
    root = secondary_motion._assets_root(fake_config)
    assert root == tmp_path / "assets"
    assert not root.is_dir()          # 目录确实还不存在，但路径必须是数据根下的


def test_sbm_targets_never_point_into_meipass(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI123"), raising=False)
    meipass = tmp_path / "_MEI123"
    (meipass / "assets").mkdir(parents=True)
    monkeypatch.setattr(secondary_motion, "_assets_root",
                        lambda cfg=None: meipass / "assets", raising=False)
    monkeypatch.setattr(secondary_motion, "game_dir", lambda cfg: None, raising=False)
    monkeypatch.setattr(secondary_motion, "_tool_dir", lambda cfg: None, raising=False)

    config = AppConfig(runtime_dir=str(tmp_path / "runtime"))
    targets = sbm_data_sync._targets(config, ("data", "characters.default.json"))

    # 这里的唯一候选就是 `_MEIPASS\assets` → 必须**整条丢弃**（宁可什么都不写，
    # 也不能写进临时解压目录：写完退出即丢，还会污染 PyInstaller 的解压现场）。
    assert targets == [], targets


def test_sbm_targets_keep_data_root_assets(tmp_path, monkeypatch):
    """正常情况下数据根的 `assets\\secondary_motion\\...` 仍是合法落点。"""
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI123"), raising=False)
    monkeypatch.setattr(secondary_motion, "game_dir", lambda cfg: None, raising=False)
    monkeypatch.setattr(secondary_motion, "_tool_dir", lambda cfg: None, raising=False)

    config = SimpleNamespace(base_dir=tmp_path / "root")   # `_targets` 只把它透传给被 mock 的函数
    targets = sbm_data_sync._targets(config, ("data", "characters.default.json"))

    assert targets and all("root" in str(t) for t in targets), targets
