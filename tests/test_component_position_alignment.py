"""验证「开关关着就不该留在根目录」这条（2026-10-06 用户现场）。

现场：`config.mfg_unlock_enabled = False`，而 `runtime\\dlss5\\renodx-mfgunlock.addon64` 还在
根目录、`_disabled\\` 是空的 ⇒ ReShade 照样加载它 ⇒ 用户报「关了为什么还是注入了」。
根因是 `ensure_injections()` 里"按配置搬运"跑在"展开资产"**之前**，展开又把文件放回根目录。

这里不跑完整 `ensure_injections`（会拉起一堆重活），而是**直接验证那条对齐逻辑本身**，
并静态钉住"展开之后必须再对齐一次"这个顺序（顺序正是这次的根因）。
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    return AppConfig(), dlss5


def test_disabled_component_must_not_stay_in_root(env):
    """★ 关着的组件不能留在根目录（留在那儿 = ReShade 会加载它 = 开关形同虚设）。"""
    config, dlss5 = env
    name = launcher.MFG_ADDON_GLOBS[0]
    (dlss5 / name).write_bytes(b"addon")           # 模拟"展开之后又被放回根目录"

    launcher.set_component_addons(config, "mfg", False)

    assert not (dlss5 / name).is_file(), "关掉之后根目录里不能还有它"
    assert (dlss5 / launcher.ADDON_DISABLED_DIR / name).is_file(), "应当被搬进 _disabled\\"


def test_expand_is_followed_by_a_realign():
    """★★ **顺序判据**（这次的真根因）：`ensure_all` 之后必须再对齐一次插件位置。

    展开资产只看"根目录有没有这个文件"，发现缺就解压回去 ⇒ 若对齐只跑在展开之前，
    刚禁用的插件会被展开动作撤销。用 AST 判"`ensure_all` 调用之后还有 `set_component_addons`"。
    """
    import ast as _ast

    src = inspect.getsource(launcher.ensure_injections)
    tree = _ast.parse(src)
    # 收集顶层语句顺序：找 ensure_all(...) 与后续的 set_component_addons(...) 调用
    ensure_all_lines: list[int] = []
    set_component_lines: list[int] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name == "ensure_all" and isinstance(func, _ast.Attribute):
                ensure_all_lines.append(node.lineno)
            if name == "set_component_addons":
                set_component_lines.append(node.lineno)

    assert ensure_all_lines, "ensure_injections 里没找到 ensure_all 调用"
    last_ensure = max(ensure_all_lines)
    after = [n for n in set_component_lines if n > last_ensure]
    assert after, (
        "★ 展开资产（ensure_all）之后没有再次对齐插件位置 ⇒ 关掉的插件会被展开动作放回根目录"
        "（用户报的「关了还是注入了」就是这个）"
    )


def test_enabling_puts_it_back(env):
    """对照：打开时应当把 addon 放回根目录。"""
    config, dlss5 = env
    name = launcher.MFG_ADDON_GLOBS[0]
    disabled = dlss5 / launcher.ADDON_DISABLED_DIR
    disabled.mkdir(parents=True, exist_ok=True)
    (disabled / name).write_bytes(b"addon")

    launcher.set_component_addons(config, "mfg", True)

    assert (dlss5 / name).is_file(), "打开后应当回到根目录"
