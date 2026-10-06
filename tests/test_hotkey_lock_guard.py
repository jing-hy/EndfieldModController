"""「Mod 快捷键锁定」必须先证明**面板这次真的会被加载**（2026-10-06 修）。

真实反馈（数据根 `G:\\`、游戏 `G:\\Hypergryph Launcher\\games\\Arknights Endfield`）：
用户原话是「**皮肤打不进去**」。包内证据链：

* Mod 其实**加载了**（`d3dx_user.ini` 里两个 Mod 的部件变量都在，staging 里 `mod_dirs=3`）；
* 但 `config`：`dlss5_addon_enabled=false` **且** `firstperson_addon_enabled=false`
  ⇒ 日志里注入库 = `['…\\EFMI\\d3d11.dll']`，**没有 `d3d12.dll`**（ReShade 底座）；
* 而 `hotkey_takeover=true` ⇒ Mod 的 `[Key*]` 仍被改写成 `VK_F24` ⇒ **手按原键不生效**，
  而面板住在 ReShade 里、**根本没被注入** ⇒ 也没有面板可用
  （他的 `panel_info.txt: takeover=1` + `mc_action_seen = 0` 正是这个状态）。

根因：`takeover_possible()` 只查"配置文件在不在磁盘上"，**没查"当前配置下底座会不会真的被注入"**
—— 文件当然还在磁盘上，于是判据放行、键被锁死。这就是 2026-10-01 那次事故
（"键锁死了、面板却不存在"）换了一条路径重演。

**2026-10-06 晚些的语义调整**：启动页新增「**统一管理器**」开关并**默认开**（用户原话
「默认开，如果这个不开，锁快捷键强制关，如果开锁快捷键，这个强制开」）⇒ 默认配置下
底座一定注入、面板一定在，所以**默认就是安全的**；只有"统一管理器被关掉、且两个插件也关着"
这一种组合才会拒绝锁键。

要守住的性质：
* 默认配置（统一管理器开）⇒ `takeover_possible` 为 **True**（默认就能锁键）；
* 统一管理器关 + 两个插件都关 ⇒ **False**（且理由说人话）⇒ `resolve_hotkey_takeover`
  返回 False ⇒ **不改写 Mod 热键**（原键继续可用）；
* 任一插件开着 ⇒ 底座会被注入 ⇒ 允许锁键；
* **注入库与"能不能锁"读同一判据**（`reshade_integration.reshade_base_wanted`）。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import launcher, reshade_integration
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    runtime = root / "runtime"
    dlss5 = runtime / "dlss5"
    dlss5.mkdir(parents=True)
    (dlss5 / "d3d12.dll").write_bytes(b"MZ")
    panel = tmp_path / "endfieldmodcontroller.addon64"
    panel.write_bytes(b"MZ")
    # `built_addon_path()` 会去找随包资产 —— 测试里换成临时文件，保持全离线
    monkeypatch.setattr(reshade_integration, "built_addon_path", lambda: panel, raising=False)
    config = AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(root / "library"),
        dlss5_dir=str(dlss5),
        builtin_runtime_dir=str(runtime / "builtin"),
        reshade_injection="xxmi_extra",
        dlss5_addon_enabled=True,
        firstperson_addon_enabled=False,
    )
    return config


def test_default_config_is_safe(env):
    """**默认**（统一管理器开）⇒ 底座必注入 ⇒ 允许锁键。"""
    env.dlss5_addon_enabled = False
    env.firstperson_addon_enabled = False
    assert env.minimal_injection is True      # 默认开
    possible, reason = reshade_integration.takeover_possible(env)
    assert possible is True, f"默认配置下不该拒绝锁键（理由: {reason}）"


def test_lock_is_refused_when_nothing_injects_the_base(env):
    """统一管理器也关掉 + 两个插件都关 ⇒ 底座不注入 ⇒ **不许锁键**。"""
    env.minimal_injection = False
    env.dlss5_addon_enabled = False
    env.firstperson_addon_enabled = False
    possible, reason = reshade_integration.takeover_possible(env)
    assert possible is False
    assert "底座不会被注入" in reason


def test_lock_is_allowed_when_a_plugin_keeps_the_base(env):
    env.minimal_injection = False
    env.dlss5_addon_enabled = True
    env.firstperson_addon_enabled = False
    assert reshade_integration.takeover_possible(env)[0] is True


def test_resolve_hotkey_takeover_returns_false_so_hotkeys_stay(env, monkeypatch):
    """端到端：判据说不该锁 ⇒ `resolve_hotkey_takeover` 必须返回 False。
    （返回值就是 `stage_and_prepare(hotkey_takeover=...)` 用的那个值，
      返回 False = Mod 原键不被改写 = 用户按键继续可用。）"""
    env.minimal_injection = False
    env.dlss5_addon_enabled = False
    env.firstperson_addon_enabled = False
    monkeypatch.setattr(reshade_integration, "deploy_panel",
                        lambda *a, **k: {"deployed": ["endfieldmodcontroller.addon64"], "warnings": []},
                        raising=False)
    monkeypatch.setattr(reshade_integration, "ensure_panel_font",
                        lambda *a, **k: {"changed": False, "reason": ""}, raising=False)
    assert launcher.resolve_hotkey_takeover(env, env.dlss5_path) is False


def test_injection_targets_follow_the_same_verdict(env):
    """注入库与"能不能锁键"必须同一判据（这次漏就是漏在这里）。"""
    env.minimal_injection = False
    env.dlss5_addon_enabled = False
    env.firstperson_addon_enabled = False
    assert not any(t.endswith("d3d12.dll") for t in launcher.dlss5_injection_targets(env))
    env.minimal_injection = True                       # 统一管理器开着 ⇒ 底座必列
    assert any(t.endswith("d3d12.dll") for t in launcher.dlss5_injection_targets(env))


def test_only_dlss4_still_injects_the_base(env):
    """★★ **只开 DLSS4 时也必须注入 ReShade 底座**（2026-10-06 用户现场）。

    原话：「**我现在只开 dlss4 根本不注入**」。原因：`renodx-mfgunlock.addon64`
    **本身就是个 ReShade addon**，它和 DLSS5 / 第一人称**共用同一个底座**；而
    **DLSS4 与 DLSS5 互斥**（开一个就关另一个）⇒ "只开 DLSS4"时前两项必然都是关的
    ⇒ 旧判据直接返回"不要底座" ⇒ addon 没有宿主 ⇒ 用户看到的就是"根本不注入"。
    """
    env.minimal_injection = False
    env.dlss5_addon_enabled = False                 # 互斥 ⇒ DLSS5 必关
    env.firstperson_addon_enabled = False
    env.mfg_unlock_enabled = True

    want, reason = reshade_integration.reshade_base_wanted(env)
    assert want is True, f"只开 DLSS4 却不注入底座 ⇒ addon 没有宿主（原因：{reason}）"
    assert any(t.endswith("d3d12.dll") for t in launcher.dlss5_injection_targets(env)), (
        "注入库里必须有 ReShade 底座，否则 MFG Unlock 不会被加载"
    )


def test_all_three_off_means_no_base(env):
    """对照：三个入口都关着 ⇒ 底座确实不该注入（判据没有被放水成"永远 True"）。"""
    env.minimal_injection = False
    env.dlss5_addon_enabled = False
    env.firstperson_addon_enabled = False
    env.mfg_unlock_enabled = False
    assert reshade_integration.reshade_base_wanted(env)[0] is False
    assert not any(t.endswith("d3d12.dll") for t in launcher.dlss5_injection_targets(env))
