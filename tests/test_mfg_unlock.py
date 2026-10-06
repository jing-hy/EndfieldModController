"""DLSS4 多帧生成解锁（40 系）：判据 / 组件开关 / 与 DLSS5 互斥（2026-10-06）。

用户定的形态（原话）：「**dlss4做一下，单列开关，与 dlss5 互斥，50 系和其他用不了的锁，默认关**」。

上游：`mavismmg/MFGAdaUnlock-RenoDx` 1.4.1（MIT）—— 一个 ReShade addon，
"unlocks 3x/4x/6x frame generation on RTX 40-series cards and corrects the temporal
midpoint. **In-memory only**."（只改运行时内存，不写游戏目录、不碰磁盘上的 NGX 库）。

要守住四条：
* **默认关**（可选增强，不是"能不能玩"的必需品）；
* **只放 40 系**（`sm_89`）—— 50 系官方本来就有、30/20 系连 Ada 插值内核都没有；
* **与 DLSS5 互斥**（两者都是 ReShade addon，上游有"双 addon 同载劣化"的记录）——
  在**真正执行动作的那一层**判，不只靠前端；
* 启停方式与 DLSS5 一致：在 `runtime\\dlss5\\` 与 `_disabled\\` 之间搬文件（可逆）。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import deviceinfo, initialize, launcher
from endfieldmodcontroller.config import AppConfig


def _fake_adapters(*names: str) -> dict:
    return {"adapters": [{"name": n, "driver": "32.0.16.1714"} for n in names]}  # type: ignore[list-item]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    return AppConfig(), dlss5


# ── 判据：只放 40 系 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("card,expected", [
    ("NVIDIA GeForce RTX 4060 Laptop GPU", True),      # 40 系 ⇒ 放行
    ("NVIDIA GeForce RTX 4070 Ti SUPER", True),
    ("NVIDIA GeForce RTX 5080", False),                # 50 系 ⇒ 锁（官方本来就有）
    ("NVIDIA GeForce RTX 3080", False),                 # 30 系 ⇒ 锁
    ("NVIDIA GeForce RTX 2060", False),                 # 20 系 ⇒ 锁
])
def test_supported_only_for_ada(monkeypatch, card, expected):
    monkeypatch.setattr(deviceinfo, "collect", lambda refresh=False: _fake_adapters(card))
    ok, reason = deviceinfo.mfg_unlock_supported()
    assert ok is expected, reason
    assert reason


def test_locked_when_no_nvidia(monkeypatch):
    monkeypatch.setattr(deviceinfo, "collect",
                        lambda refresh=False: _fake_adapters("AMD Radeon(TM) Graphics"))
    ok, reason = deviceinfo.mfg_unlock_supported()
    assert ok is False
    assert "RTX" in reason or "NVIDIA" in reason


def test_multi_gpu_takes_the_best(monkeypatch):
    """双卡机器（一张 4060 + 一张 5080）⇒ 取最高代次 ⇒ **锁**（50 系不需要它）。"""
    monkeypatch.setattr(deviceinfo, "collect", lambda refresh=False: _fake_adapters(
        "NVIDIA GeForce RTX 4060", "NVIDIA GeForce RTX 5080"))
    ok, _reason = deviceinfo.mfg_unlock_supported()
    assert ok is False


# ── 组件开关：搬文件（可逆）────────────────────────────────────────────────
def test_default_is_off(env):
    config, _dlss5 = env
    assert config.mfg_unlock_enabled is False, "默认必须是关"


def test_component_moves_the_addon_both_ways(env):
    config, dlss5 = env
    name = launcher.MFG_ADDON_GLOBS[0]
    (dlss5 / launcher.ADDON_DISABLED_DIR).mkdir(parents=True, exist_ok=True)
    (dlss5 / launcher.ADDON_DISABLED_DIR / name).write_bytes(b"addon")

    out = launcher.set_component_addons(config, "mfg", True)
    assert (dlss5 / name).is_file(), out
    assert not (dlss5 / launcher.ADDON_DISABLED_DIR / name).is_file()

    out = launcher.set_component_addons(config, "mfg", False)
    assert (dlss5 / launcher.ADDON_DISABLED_DIR / name).is_file(), out
    assert not (dlss5 / name).is_file()


# ── 自检 ────────────────────────────────────────────────────────────────────
class _Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, bool, str, dict]] = []

    def add(self, key, ok, msg, **kw):        # noqa: ANN001
        self.items.append((key, ok, msg, kw))


def test_check_says_not_applicable_on_blackwell(env, monkeypatch):
    config, _dlss5 = env
    monkeypatch.setattr(deviceinfo, "collect",
                        lambda refresh=False: _fake_adapters("NVIDIA GeForce RTX 5080"))
    monkeypatch.setattr(deviceinfo, "mfg_unlock_supported",
                        lambda refresh=False: (False, "50 系不需要这个解锁"))
    report = _Report()
    initialize._check_mfg_unlock(config, report, lambda m: None)
    assert report.items, "自检必须至少报一条"
    key, ok, msg, _kw = report.items[0]
    assert key == "dlss5:mfg_unlock"
    assert ok is True, "不适用不算失败（界面上开关是禁用的）"


def test_check_warns_when_enabled_but_addon_missing(env, monkeypatch):
    config, _dlss5 = env
    config.mfg_unlock_enabled = True
    monkeypatch.setattr(deviceinfo, "mfg_unlock_supported",
                        lambda refresh=False: (True, "40 系可以解锁"))
    report = _Report()
    initialize._check_mfg_unlock(config, report, lambda m: None)
    key, ok, msg, kw = report.items[0]
    assert key == "dlss5:mfg_unlock"
    assert ok is False and kw.get("manual") is True, (ok, kw, msg)
    assert "一键启动" in msg
