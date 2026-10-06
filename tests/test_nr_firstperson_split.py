"""NR 与第一人称相机 hook 的抢位：按 `CameraFirstPerson` 分流（2026-10-06）。

**问题**：enhancer 的**相机 hook** 与 NR 抢同一个位置 —— **NR 先激活 ⇒ hook 装不上**
（日志 `Camera hook installation failed; camera controls disabled.`，`error 8`）⇒
**第一人称与相机控制都不能用**。而 v1.0.16 起默认「启动就开」（`NeuralUplift=1`）⇒ 必然抢先。

**修法**：按"要不要用第一人称"分流 ——
* `CameraFirstPerson=1` ⇒ 压 `NeuralUplift=0`，等 hook 装好后由 `nr_autostart` 补按 NR 键；
* `CameraFirstPerson=0` ⇒ 保持启动就开（没有 hook 要保护）。

要看住：
* 判据读的是**生效那份** ReShade.ini（不是模板），且只在 `[endfield-enhancer]` 段内取值；
* 分流后 `nr_autostart` **不能**再用"启动就开"整条跳过（否则用第一人称的人 NR 永远不开）。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import initialize, nr_autostart, reshade_integration
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    reshade = tmp_path / "runtime" / "reshade"
    reshade.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "reshade_runtime_path", property(lambda self: reshade))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    return AppConfig(), reshade / "ReShade.ini"


def _write_ini(path: pathlib.Path, firstperson: str = "1", other_section: str = "0") -> None:
    path.write_text(
        "[endfield-enhancer]\n"
        f"CameraControls={other_section}\n"
        f"CameraFirstPerson={firstperson}\n"
        "CameraEFMICompatibility=1\n"
        "\n[RenoDX.DLSS5]\nNeuralUplift=1\n"
        "\n[OTHER]\nCameraFirstPerson=1\n",           # 别的段里同名的键不能算
        encoding="utf-8")


def test_firstperson_flag_is_read_from_the_effective_ini(env):
    config, ini = env
    _write_ini(ini, firstperson="1")
    assert reshade_integration.firstperson_camera_wanted(config) is True
    _write_ini(ini, firstperson="0")
    assert reshade_integration.firstperson_camera_wanted(config) is False


def test_missing_ini_falls_back_to_not_wanting_firstperson(env):
    """读不到 ini ⇒ 按"不用第一人称"处理（保持启动就开，不让 NR 白等）。"""
    config, _ini = env
    assert reshade_integration.firstperson_camera_wanted(config) is False


def test_defer_decision_follows_the_split(env, monkeypatch):
    """★ 分流：要用第一人称 ⇒ 不"启动就开"（= 压 0 等 hook）；不用 ⇒ 启动就开。"""
    config, ini = env
    for firstperson, expected_immediate in (("1", False), ("0", True)):
        _write_ini(ini, firstperson=firstperson)
        want = reshade_integration.firstperson_camera_wanted(config)
        immediate = (bool(getattr(config, "start_dlss5_nr_immediately", True)) and not want)
        assert immediate is expected_immediate, (firstperson, immediate)


def test_autostart_does_not_skip_when_firstperson_is_wanted(env, monkeypatch):
    """★ 用第一人称时，`nr_autostart` 不能再整条跳过（否则 NR 永远不开）。"""
    config, ini = env
    _write_ini(ini, firstperson="1")
    nr_autostart.reset()
    nr_autostart.arm(config, log=None)
    result = nr_autostart.poll(config, log=None)
    # 不能是"NR 已设为启动就开，无需补按"那个跳过分支
    assert result.get("reason") != "NR 已设为启动就开，无需补按", result


def test_autostart_still_skips_when_firstperson_not_wanted(env):
    config, ini = env
    _write_ini(ini, firstperson="0")
    nr_autostart.reset()
    nr_autostart.arm(config, log=None)
    result = nr_autostart.poll(config, log=None)
    assert result.get("reason") == "NR 已设为启动就开，无需补按", result
