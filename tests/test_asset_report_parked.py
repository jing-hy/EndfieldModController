"""依赖页的资产状态：**「已被开关停用」不能报成「待展开」**（2026-10-07 反馈定案）。

**现场**：依赖页上某个被开关停用的 addon 每次进游戏后又变回「待展开」。

**机制是个死循环**：
一键启动的 `runtime_assets.ensure_*` 按清单把它展开到 `dlss5\\` 根目录，紧接着
`launcher.set_component_addons("<组件>", False)`（该开关关着）又把它搬进
`_disabled\\`；而 `asset_report()` 的判据**只看根目录** ⇒ 每轮都报「待展开」、
每轮都白展开一次、日志也跟着吵。

**判据必须与自检一致**：自检那几项本来就同时看 `present` 与 `parked`，
`asset_report` 却只看前者 —— 同一个事实两处结论不同，用户看到的就是「装了又没装」。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import runtime_assets
from endfieldmodcontroller.config import AppConfig

ADDON = "renodx-endfield-enhancer.addon64"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """把安装目录指到 tmp，但**沿用仓库真实的随包清单**（判据只跟文件位置有关）。"""
    dlss5 = tmp_path / "dlss5"
    (dlss5 / runtime_assets.ADDON_DISABLED_DIR).mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    return dlss5


def _entry(config):
    """从真实清单里取出这个 addon 的条目（拿它的期望尺寸）。"""
    for _group, _root, name, entry in runtime_assets.manifest_entries(config):
        if str(entry.get("install_as") or name) == ADDON:
            return entry
    pytest.skip(f"随包清单里没有 {ADDON}（清单变了，这条测试需要跟着改）")


def _write_sized(path, size: int) -> None:
    """造一个**尺寸与清单一致**的文件 —— 判据里尺寸是要校验的。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def test_parked_addon_is_disabled_not_pending(env):
    """**核心**：文件躺在 `_disabled\\` 里 ⇒ 报「已停用」，而且**不再要求展开**。"""
    config = AppConfig()
    entry = _entry(config)
    size = int(entry.get("size") or 0)
    assert size > 0, "清单条目没有 size，测试前提不成立"
    _write_sized(env / runtime_assets.ADDON_DISABLED_DIR / ADDON, size)

    item = runtime_assets.asset_report(config)[f"dlss5:{ADDON}"]

    assert item["status"] == "已停用", "被停用的 addon 又被报成待展开（用户看到的那个循环）"
    assert item["parked"] is True
    assert item["present"] is False
    assert item["needed"] is False, "停用不是「缺东西」，不该再催着展开"


def test_addon_in_place_is_present(env):
    """对照组：文件在原位 ⇒ 报「已就位」。"""
    config = AppConfig()
    entry = _entry(config)
    _write_sized(env / ADDON, int(entry.get("size") or 0))

    item = runtime_assets.asset_report(config)[f"dlss5:{ADDON}"]

    assert item["status"] == "已就位"
    assert item["present"] is True
    assert item["needed"] is False


def test_missing_addon_still_asks_for_expand(env):
    """另一组对照：两份都没有 ⇒ 仍要报「待展开」并要求展开（别把这条一起修没了）。"""
    config = AppConfig()
    item = runtime_assets.asset_report(config)[f"dlss5:{ADDON}"]

    assert item["status"] == "待展开"
    assert item["needed"] is True
