"""「统一管理器」开关的回归测试（2026-10-06 用户定名与语义）。

用户原话：「**那个开关就要叫统一管理器，不要讲那么多，默认开，如果这个不开，锁快捷键强制关，
          如果开锁快捷键，这个强制开**」。

要守住的性质（每条都对应一个真会踩的坑）：

* **默认开** —— 零配置用户默认就有 ReShade + 统一管理器面板（面板是"换装入口"的前提）；
* **开** = 面板 addon 在 `runtime\\dlss5\\` 根目录（ReShade 只加载底座根目录里的 addon）；
* **关** = 面板移进 `_disabled`，**并强制把「Mod 快捷键锁定」关掉** —— 没有面板就没有
  替代的换装入口（2026-10-06 反馈者"皮肤打不进去"就是这个现场：键被锁、面板不存在）；
* **不动其它插件** —— DLSS5 / 第一人称 / 乳摇 / Poser 的开关与 addon 一律不受影响
  （早先那版"最小注入"会把它们全停掉，语义已改）；
* **反向联动**：开「Mod 快捷键锁定」⇒「统一管理器」强制开。

全部离线：只在 `tmp_path` 里造 addon 文件，不碰真实游戏目录 / runtime。
"""
from __future__ import annotations

import inspect
import shutil

import pytest

from endfieldmodcontroller import launcher
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig

PANEL_ADDON = "endfieldmodcontroller.addon64"
OTHER_ADDONS = ("renodx-dlss5-4.7_汉化.addon64", "dlss5-feed.addon64", "trans-zh.addon64",
                "renodx-endfield-enhancer.addon64")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    runtime = root / "runtime"
    dlss5 = runtime / "dlss5"
    dlss5.mkdir(parents=True)
    for name in (PANEL_ADDON, *OTHER_ADDONS):
        (dlss5 / name).write_bytes(b"MZ")
    (dlss5 / "d3d12.dll").write_bytes(b"MZ")
    config = AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(root / "library"),
        dlss5_dir=str(dlss5),
        builtin_runtime_dir=str(runtime / "builtin"),
    )
    monkeypatch.setattr(AppConfig, "save", lambda self: None, raising=False)
    return config, dlss5


def test_default_is_on():
    """默认开 —— 零配置用户默认就有 ReShade 与统一管理器面板。"""
    assert AppConfig().minimal_injection is True


def test_turning_it_off_parks_the_panel_and_forces_the_lock_off(env):
    """关掉 ⇒ 面板进 `_disabled`，且「Mod 快捷键锁定」被强制关（用户原话）。"""
    config, dlss5 = env
    config.hotkey_takeover = True
    config.minimal_injection = False
    result = launcher.apply_minimal_injection(config)
    assert not (dlss5 / PANEL_ADDON).exists()
    assert (dlss5 / "_disabled" / PANEL_ADDON).is_file()
    assert config.hotkey_takeover is False, "统一管理器关了，锁键必须一起关"
    assert any("强制关闭" in action for action in result["actions"])
    assert launcher.minimal_injection_status(config)["panel_parked"] is True


def test_turning_it_on_puts_the_panel_back(env):
    """开 ⇒ 面板回到 ReShade 会读的目录。"""
    config, dlss5 = env
    disabled = dlss5 / "_disabled"
    disabled.mkdir()
    shutil.move(str(dlss5 / PANEL_ADDON), str(disabled / PANEL_ADDON))
    config.minimal_injection = True
    launcher.apply_minimal_injection(config)
    assert (dlss5 / PANEL_ADDON).is_file()
    status = launcher.minimal_injection_status(config)
    assert status["panel_active"] is True and status["panel_parked"] is False


def test_it_does_not_touch_other_plugins(env):
    """**新语义**：它只管面板 —— 其它插件的开关与 addon 一个都不许动。"""
    config, dlss5 = env
    config.dlss5_addon_enabled = True
    config.firstperson_addon_enabled = True
    config.secondary_motion_injection = True
    config.poser_injection = True
    config.minimal_injection = False
    launcher.apply_minimal_injection(config)
    assert config.dlss5_addon_enabled is True
    assert config.firstperson_addon_enabled is True
    assert config.secondary_motion_injection is True
    assert config.poser_injection is True
    for name in OTHER_ADDONS:
        assert (dlss5 / name).is_file(), f"{name} 不该被统一管理器动到"


def test_repeated_apply_is_idempotent(env):
    config, dlss5 = env
    config.minimal_injection = False
    first = launcher.apply_minimal_injection(config)
    second = launcher.apply_minimal_injection(config)
    assert second["ok"] is True
    assert (dlss5 / "_disabled" / PANEL_ADDON).is_file()
    assert isinstance(first["moved"], list)


def test_enabling_the_lock_switch_forces_the_panel_on():
    """反向联动：开「Mod 快捷键锁定」⇒「统一管理器」强制开（用户原话）。"""
    src = inspect.getsource(EndfieldModControllerApi.set_hotkey_takeover)
    assert "self.config.minimal_injection = True" in src, (
        "开锁键时必须把统一管理器一起打开 —— 否则面板可能是被停用的，锁了键却没有换装入口"
    )


def test_lock_switch_does_not_block_on_the_heavy_prepare():
    """**接口不许被重活堵住**（2026-10-06 用户：「这个按钮反应也太慢了吧，
    过了好几秒才会同步统一管理器和 mod 锁定快捷键」）。

    `prepare()` 要重铺 staging、重生成控制器与 `actions.tsv`，是秒级的 —— 同步跑就会让
    这次点击几秒后才返回；它必须走后台。
    """
    src = inspect.getsource(EndfieldModControllerApi.set_hotkey_takeover)
    assert "self.prepare()" not in src, "重活不能出现在这个接口的同步路径里（按钮会卡好几秒）"
    assert "_reprepare_in_background" in src
