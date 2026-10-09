"""组件登记必须齐：`component_addon_status()` 与 `set_component_addons()` 不能脱节（2026-10-06）。

**现场**：v1.0.25 发布后，用户点某个插件开关弹窗 `launch failed: 'xxx'`、
日志 `启动失败: 'xxx'` —— 那是 `KeyError`：`ensure_injections` 的组件循环里加了新组件，
而 `component_addon_status()` **没登记它** ⇒ 循环取 `status[组件]` 直接炸 ⇒ **一键启动整个失败**。

要守住两条：
* `component_addon_status()` 的键 **必须覆盖** `set_component_addons()` 认的每个组件；
* `ensure_injections` 里那个组件循环列出的组件也必须在其中（它才是真正取 `status[...]` 的地方）。
"""
from __future__ import annotations

import inspect
import re
import sys

import pytest

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig

# `set_component_addons` 认的组件（它按 component 选 glob）
KNOWN_COMPONENTS = ("dlss5", "firstperson")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    return AppConfig()


def test_api_accepts_every_known_component(env, monkeypatch):
    """★★ **`api.set_component_addon()` 必须接受真源里的每一个组件。**

    用户现场：点某个插件开关弹 `没能改这个开关 / 未知组件: xxx`
    ⇒ 开关**被后端直接拒掉**、配置没改 ⇒ 感受就是"开了没反应"。
    根因是那个方法开头有一张**写死的白名单** `("dlss5", "firstperson")`，
    加组件时漏改（同一天 `component_addon_status` 漏登记是同一类错误）。
    现在白名单从 `launcher.COMPONENT_ADDON_GLOBS` 派生 —— 这条测试遍历真源，
    **以后再加组件会自动被覆盖**，不会再出现"某个入口不认新组件"。
    """
    import inspect

    from endfieldmodcontroller import api as apimod

    cls = next(o for _n, o in vars(apimod).items()
               if inspect.isclass(o) and hasattr(o, "get_state"))
    inst = cls.__new__(cls)                      # 跳过 __init__ 的重活
    cfg_file = env.dlss5_path.parent / "config.json"
    env.save(cfg_file)                           # 给配置一个真实落点（接口内部会 save）
    inst._config = env
    inst._config_path = cfg_file
    inst._config_mtime = None

    for component in launcher.COMPONENT_ADDON_GLOBS:
        result = inst.set_component_addon(component, False)
        assert "未知组件" not in str(result.get("message") or ""), (
            f"api 不认组件 {component!r} ⇒ 用户点那个开关会看到「未知组件」"
        )
    # 未知名仍要拒绝（别把白名单变成"什么都收"）
    assert inst.set_component_addon("definitely-not-a-component", False).get("ok") is False


def test_status_registers_every_known_component(env):
    """★ 每个组件都要在 `component_addon_status()` 里有一份 —— 少一个就是 KeyError。"""
    status = launcher.component_addon_status(env)
    missing = [c for c in launcher.COMPONENT_ADDON_GLOBS if c not in status]
    assert not missing, f"这些组件没登记 ⇒ 一键启动会 KeyError：{missing}（现有 {sorted(status)}）"
    for name in launcher.COMPONENT_ADDON_GLOBS:
        assert set(status[name]) >= {"active", "disabled", "on"}, status[name]


def test_component_loop_in_ensure_injections_is_covered(env):
    """★ `ensure_injections` 的组件循环**列出的组件**必须全都在 status 里（动态核对）。

    直接从源码里把循环里的组件名抠出来，这样以后**新增组件却忘了登记**时，
    这条测试会立刻失败，而不是等用户看到 `launch failed: 'xxx'`。
    """
    source = inspect.getsource(launcher.ensure_injections)
    listed = re.findall(r'\(\s*"([a-z0-9_]+)"\s*,\s*"[a-z0-9_]+"\s*,', source)
    assert listed, "没从 ensure_injections 里抠到组件名 —— 循环写法变了，请更新本测试"
    status = launcher.component_addon_status(env)
    missing = [c for c in listed if c not in status]
    assert not missing, (
        f"组件循环里列了 {listed}，但 status 里缺 {missing} ⇒ "
        f"用户会看到 launch failed: '{missing[0]}'"
    )


def test_set_component_addons_accepts_every_component(env):
    """每个组件都要能被真的搬动（走一遍两个方向，文件不丢）。"""
    name_by_component = {
        "dlss5": launcher.DLSS5_ADDON_GLOBS[0],
        "firstperson": launcher.FIRSTPERSON_ADDON_GLOBS[0],
    }
    disabled = env.dlss5_path / launcher.ADDON_DISABLED_DIR
    disabled.mkdir(parents=True, exist_ok=True)
    for component, name in name_by_component.items():
        (disabled / name).write_bytes(b"addon")
        launcher.set_component_addons(env, component, True)
        assert (env.dlss5_path / name).is_file(), component
        launcher.set_component_addons(env, component, False)
        assert (disabled / name).is_file(), component
