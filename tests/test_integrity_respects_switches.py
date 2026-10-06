"""★ 「关掉的插件」不能被完整性检查判成"缺失"（2026-10-06 用户现场定案）。

**现场**（用户那次一键启动的日志）：
```
注入自检: 统一管理器: 清掉多余副本 endfieldmodcontroller.addon64      ← 按开关对齐做过了
integrity missing: dlss5_enhancer_addon -> …\\renodx-endfield-enhancer.addon64
repair: 展开内置资产 renodx-endfield-enhancer.addon64                ← 又被展开回根目录
```
随后 ReShade 日志显示它**确实被加载了** ⇒ 用户报「**MOD 管理器和第一人称还是注入进去了**」。

**根因**：`integrity.check_integrity()` 对第一人称插件**只判 `is_file()`** —— 而关掉该开关时
这个 addon 被**搬进 `_disabled\\`**，根目录自然没有它 ⇒ 被判"缺失" ⇒ `repair_integrity()`
**又把它展开回根目录** ⇒ **每次启动循环一次，开关形同虚设**（同族的 DLSS5 / DLSS4 同理）。

判据：**开关关着 ⇒ 这一项不算必检项**（本就该不在运行目录里）。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import integrity
from endfieldmodcontroller.config import AppConfig

ENHANCER = "renodx-endfield-enhancer.addon64"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """只造"开关 + 文件位置"两件事，其它检查项缺就缺（本测试只看这一项）。"""
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    (dlss5 / "d3d12.dll").write_bytes(b"base")
    (dlss5 / "ReShade.ini").write_text("[endfield-enhancer]\n", encoding="utf-8")
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    monkeypatch.setattr(AppConfig, "dlss5_dll_path", property(lambda self: dlss5 / "d3d12.dll"))
    monkeypatch.setattr(AppConfig, "dlss5_ini_path", property(lambda self: dlss5 / "ReShade.ini"))
    monkeypatch.setattr(AppConfig, "dlss5_enhancer_addon_path",
                        property(lambda self: dlss5 / ENHANCER))

    disabled = dlss5 / "_disabled"
    disabled.mkdir()
    (disabled / ENHANCER).write_bytes(b"enhancer")      # 关掉时它在这儿
    return AppConfig(), dlss5, disabled


def _keys(config) -> set[str]:
    return {item["key"] for item in integrity.check_integrity(config)["failures"]}


def test_disabled_enhancer_is_not_reported_missing(env):
    """★ 第一人称关着 ⇒ 不能报它缺失（否则 repair 又把它展开回来，开关失效）。"""
    config, _dlss5, _disabled = env
    config.firstperson_addon_enabled = False
    assert "dlss5_enhancer_addon" not in _keys(config), (
        "关掉第一人称后仍被判『缺失』 ⇒ repair 会把它放回根目录（用户报的就是这个）"
    )


def test_enabled_enhancer_is_reported_missing(env):
    """对照：开着时它不在根目录 ⇒ 必须报缺失（判据没有被放水成"永不检查"）。"""
    config, _dlss5, _disabled = env
    config.firstperson_addon_enabled = True
    assert "dlss5_enhancer_addon" in _keys(config)


def test_enabled_enhancer_present_is_fine(env):
    """开着且文件在 ⇒ 不报缺失。"""
    config, dlss5, _disabled = env
    config.firstperson_addon_enabled = True
    (dlss5 / ENHANCER).write_bytes(b"enhancer")
    assert "dlss5_enhancer_addon" not in _keys(config)
