# SPDX-License-Identifier: GPL-3.0-or-later
"""总闸：「禁用所有 ReShade 注入」（2026-10-09 用户要求）。

用户原话：「在注入开关最上边做一个和其他不一样一点、明显一点的，写禁用所有 reshade 注入，
详情写明阻止所有 reshade 注入，会导致…（所有需要 reshade 的）不可用，但能大幅提升账号
安全性（风险不为零）……这个开了之后就……阻止所有 reshade 注入，要加一层保险，就算之前有
reshade 注入，也能清理出终末地」。随后明确：「**不是 dlss4 互斥，是禁用，直接不能点开开关
那种**」。

本文件守住八件事：

① `reshade_base_wanted()` **最优先**判总闸 ⇒ 开着就一个底座都不注入
   （压过 `minimal_injection` 与三个 addon 开关）；
② 总闸开着时，**四个**依赖 ReShade 的开关直接拒、且不写配置（"点不开"那种）
   —— 第四个是「Mod 快捷键锁定」（2026-10-13 用户：「**mod 快捷键锁定在 reshade 注入
   防护开的时候一起锁**」；面板就在 ReShade 里，没注入就没面板，锁了原键等于拿走入口）；
③ 开总闸把那四个开关**实际关掉**（留着"开着"会让人以为还在生效），
   包括 `minimal_injection` 本来就没开时也要单独补一次锁键；
④ **保险**：开总闸会把游戏目录里已有的 ReShade 痕迹搬出去（有备份、可还原）；
⑤ `auto_clean_before_launch` 在总闸开着时**无视**「启动前清除第三方注入」那个设置；
⑥ 前端：总闸排在 `SWITCHES` **第一个**、四个开关挂了锁、文案写明了所有受影响的功能；
⑦ **默认值**（2026-10-13 用户定：「默认状态是开关 reshade 防护开，reshade 管的关，
   其他都开」）⇒ `reshade_disabled=True`、`minimal_injection=False`、其余开关仍为 True；
⑧ **开锁键不得绕过总闸**：总闸开着时 `set_hotkey_takeover(True)` 既要被拒，也不能把
   `minimal_injection` 带开（用户实测报的 bug：「开锁快捷键，就算开了防 reshade 注入，
   统一面板的开关也会开」）。

全部离线：不联网、不碰真实游戏目录（`detect_game_dir` 一律指向 tmp_path）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import api as api_mod
from endfieldmodcontroller import game_clean, reshade_integration
from endfieldmodcontroller.config import AppConfig

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_PAGE = ROOT / "frontend" / "src" / "pages" / "LaunchPage.vue"

DEPENDENT = ("minimal_injection", "dlss5_addon_enabled",
             "firstperson_addon_enabled", "hotkey_takeover")

#: 「关掉时」在 `set_reshade_disabled` 返回里出现的标签（与四个依赖开关一一对应）。
DEPENDENT_LABELS = {"统一管理器", "DLSS5 神经渲染", "第一人称视角", "Mod 快捷键锁定"}

#: 假的 ReShade 载荷（内容里有 `ReShade` 字样 ⇒ 判据会认它是第三方注入物）。
RESHADE_PAYLOAD = b"MZ" + b"\x00" * 64 + b"ReShade\x00crosire"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """假数据根 + 假游戏目录 + 一个**绕过 __init__** 的 api 实例（不碰真实环境）。"""
    game = tmp_path / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "Endfield.exe").write_bytes(b"MZ")
    # 游戏目录里的 ReShade 痕迹（净化该搬走的东西）
    (game / "d3d12.dll").write_bytes(RESHADE_PAYLOAD)
    (game / "ReShade.ini").write_text("[ReShade]\n", encoding="utf-8")

    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: tmp_path / "runtime" / "dlss5"))
    monkeypatch.setattr(AppConfig, "game_exe_path", property(lambda self: game / "Endfield.exe"))
    monkeypatch.setattr(AppConfig, "save", lambda self: None, raising=False)
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, game_dir=None, **kw: Path(game_dir) if game_dir else game)
    (tmp_path / "runtime" / "logs").mkdir(parents=True, exist_ok=True)

    inst = api_mod.EndfieldModControllerApi.__new__(api_mod.EndfieldModControllerApi)
    inst.config = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                            library_dir=str(tmp_path / "library"),
                            dlss5_dir=str(tmp_path / "runtime" / "dlss5"),
                            builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"))
    return SimpleNamespace(inst=inst, game=game, tmp=tmp_path, config=inst.config)


# ---------------------------------------------------------------------------
# ⓪ 默认值（2026-10-13 用户定）
# ---------------------------------------------------------------------------
def test_defaults_are_safe_and_consistent():
    """★ 默认：**防护开、ReShade 管的关、其他都开**。

    用户原话：「默认状态是开关 reshade 防护开，reshade 管的关，其他都开」。
    """
    config = AppConfig()

    assert config.reshade_disabled is True, "「禁用所有 ReShade 注入」默认要开着"
    assert config.minimal_injection is False, "统一管理器（ReShade 管的）默认要关着"
    for key in ("dlss5_injection", "dlss5_addon_enabled", "firstperson_addon_enabled",
                "efmi_injection", "secondary_motion_injection", "poser_injection",
                "hotkey_takeover", "jiggle_efmi_injection"):
        assert getattr(config, key) is True, f"{key} 应保持默认开"


# ---------------------------------------------------------------------------
# ① 总闸压过一切
# ---------------------------------------------------------------------------
def test_master_switch_beats_every_other_switch():
    """★ 总闸开着 ⇒ 一个底座都不注入，哪怕其它开关全开。"""
    config = AppConfig(reshade_disabled=True, minimal_injection=True,
                       dlss5_addon_enabled=True, firstperson_addon_enabled=True)

    wanted, reason = reshade_integration.reshade_base_wanted(config)

    assert wanted is False
    assert "禁用所有 ReShade 注入" in reason


def test_without_master_switch_nothing_changes():
    """关着时行为与以前**完全一致**（不能把正常用户也挡了）。

    ⚠️ 这里必须**显式**传 `reshade_disabled=False`：默认值自 2026-10-13 起是 True
    （安全默认），不写就会变成"总闸开着"，把这些断言全部误判成失败。
    """
    assert reshade_integration.reshade_base_wanted(
        AppConfig(minimal_injection=True, reshade_disabled=False))[0] is True
    assert reshade_integration.reshade_base_wanted(
        AppConfig(minimal_injection=False, dlss5_addon_enabled=True,
                  reshade_disabled=False))[0] is True
    assert reshade_integration.reshade_base_wanted(
        AppConfig(minimal_injection=False, dlss5_addon_enabled=False,
                  firstperson_addon_enabled=False, reshade_disabled=False))[0] is False


# ---------------------------------------------------------------------------
# ② "点不开"：后端直接拒
# ---------------------------------------------------------------------------
def test_dependent_switches_are_rejected_while_master_is_on(env):
    env.config.reshade_disabled = True

    for call_it in (lambda: env.inst.set_minimal_injection(True),
                    lambda: env.inst.set_component_addon("dlss5", True),
                    lambda: env.inst.set_component_addon("firstperson", True),
                    lambda: env.inst.set_hotkey_takeover(True)):
        result = call_it()
        assert result["ok"] is False, result
        assert result.get("rejected") == "reshade_disabled", result
        assert "禁用所有 ReShade 注入" in result["message"]


def test_rejected_switch_does_not_write_config(env):
    """被拒时**不写配置** —— 前端正是据此把开关弹回去的。"""
    env.config.reshade_disabled = True
    env.config.dlss5_addon_enabled = False

    env.inst.set_component_addon("dlss5", True)

    assert env.config.dlss5_addon_enabled is False


def test_locking_hotkeys_cannot_sneak_the_panel_open(env):
    """★ 用户实测报的 bug（原话：「**现在如果开锁快捷键，就算开了防 reshade 注入，
    统一面板的开关也会开**」）。

    根因是 `set_hotkey_takeover` 无条件把 `minimal_injection` 置 True，绕过了总闸闸门。
    这里同时钉住"被拒"和"一个字都没改"。
    """
    env.config.reshade_disabled = True
    env.config.hotkey_takeover = False
    env.config.minimal_injection = False

    result = env.inst.set_hotkey_takeover(True)

    assert result["ok"] is False and result.get("rejected") == "reshade_disabled"
    assert env.config.hotkey_takeover is False, "被拒就不该锁键"
    assert env.config.minimal_injection is False, "更不该把被禁用的统一管理器带开"


def test_locking_hotkeys_still_force_opens_the_panel_without_the_master(env):
    """总闸关着时，2026-10-06 的既定语义不变：开锁键 ⇒ 统一管理器强制开。"""
    env.config.reshade_disabled = False
    env.config.minimal_injection = False
    env.config.hotkey_takeover = False

    result = env.inst.set_hotkey_takeover(True)

    assert result["ok"] is not False, result
    assert env.config.hotkey_takeover is True
    assert env.config.minimal_injection is True, "面板是锁键的前提，必须一起开"


# ---------------------------------------------------------------------------
# ③ 开总闸 ⇒ 把那四个实际关掉
# ---------------------------------------------------------------------------
def test_enabling_master_switch_closes_the_dependents(env):
    for key in DEPENDENT:
        setattr(env.config, key, True)

    result = env.inst.set_reshade_disabled(True)

    assert result["ok"] is True
    assert env.config.reshade_disabled is True
    for key in DEPENDENT:
        assert getattr(env.config, key) is False, f"{key} 应该被关掉"
    assert set(result["closed"]) == DEPENDENT_LABELS


def test_enabling_master_switch_still_closes_hotkey_lock_alone(env):
    """★ 统一管理器**本来就是关的**时，锁键也要被关掉。

    这条是 2026-10-13 补的：`set_reshade_disabled` 里那个循环对"本来就是 False"的项会
    `continue`，而"关锁键"那句正写在 `apply_minimal_injection()` 里面 ⇒ 不单独补一次，
    锁键就会残留成"开着、却没有面板"。
    """
    env.config.minimal_injection = False
    env.config.dlss5_addon_enabled = False
    env.config.firstperson_addon_enabled = False
    env.config.hotkey_takeover = True

    result = env.inst.set_reshade_disabled(True)

    assert env.config.hotkey_takeover is False, "总闸开着时锁键必须一起关"
    assert "Mod 快捷键锁定" in result["closed"]


def test_disabling_master_switch_does_not_turn_anything_back_on(env):
    """关总闸只落盘 —— 要不要开那些功能由用户自己决定。"""
    for key in DEPENDENT:
        setattr(env.config, key, False)
    env.config.reshade_disabled = True

    result = env.inst.set_reshade_disabled(False)

    assert result["ok"] is True
    assert env.config.reshade_disabled is False
    for key in DEPENDENT:
        assert getattr(env.config, key) is False, f"{key} 不该被自动打开"


# ---------------------------------------------------------------------------
# ④ 保险：把已有 ReShade 注入清理出终末地
# ---------------------------------------------------------------------------
def test_enabling_master_switch_cleans_reshade_out_of_the_game_dir(env):
    """★「就算之前有 reshade 注入，也能清理出终末地」—— 而且必须可还原。"""
    result = env.inst.set_reshade_disabled(True)

    assert result["ok"] is True
    assert not (env.game / "ReShade.ini").exists(), "ReShade 痕迹必须被搬出游戏目录"
    # ⚠️ `d3d12.dll` 是**系统模块名**：净化搬走注入物后必须**补回系统原版**
    #    （否则游戏缺这个模块直接起不来）—— 所以这里断言的是"不再是我们那份假载荷"，
    #    而不是"不存在"。补回的来源见 `game_clean._restore_system_module()`。
    assert (env.game / "d3d12.dll").read_bytes() != RESHADE_PAYLOAD
    assert result["backup_dir"], "搬走必须留下可还原的备份"
    assert (Path(result["backup_dir"]) / "files" / "d3d12.dll").read_bytes() == RESHADE_PAYLOAD
    assert any(item["category"] in ("reshade", "loader_proxy") for item in result["moved"])


# ---------------------------------------------------------------------------
# ⑤ 启动前净化：总闸开着时那道设置关不掉保险
# ---------------------------------------------------------------------------
def test_auto_clean_is_forced_while_master_is_on(env, monkeypatch):
    monkeypatch.setattr(game_clean, "_game_running", lambda: False)
    env.config.clear_game_injections_on_launch = False      # 用户把那个设置关了
    env.config.reshade_disabled = True                      # 但总闸开着

    report = game_clean.auto_clean_before_launch(env.config)

    assert report.get("skipped") != "switch_off", "总闸开着时不许因为那个设置而跳过清理"
    assert not (env.game / "ReShade.ini").exists(), "总闸开着时这道保险必须真的动手"


def test_auto_clean_respects_the_setting_when_master_is_off(env, monkeypatch):
    monkeypatch.setattr(game_clean, "_game_running", lambda: False)
    env.config.clear_game_injections_on_launch = False
    env.config.reshade_disabled = False

    report = game_clean.auto_clean_before_launch(env.config)

    assert report.get("skipped") == "switch_off"
    assert (env.game / "d3d12.dll").is_file(), "总闸没开时照旧尊重用户设置"


# ---------------------------------------------------------------------------
# ⑥ 前端
# ---------------------------------------------------------------------------
def test_frontend_master_switch_is_the_first_one():
    text = LAUNCH_PAGE.read_text(encoding="utf-8")
    first = text.index('k: "reshade_disabled"')

    for other in (*DEPENDENT, "efmi_injection", "secondary_motion_injection", "poser_injection"):
        assert text.index(f'k: "{other}"') > first, f"{other} 不该排在总闸前面"


def test_frontend_locks_the_dependents_while_master_is_on():
    text = LAUNCH_PAGE.read_text(encoding="utf-8")

    for key in DEPENDENT:
        assert f'reshadeLocked("{key}")' in text, f"{key} 没挂上总闸的锁"
    assert "emphasis" in text, "总闸要标记成'明显一点'的那一行"


def test_frontend_copy_names_every_affected_feature():
    """用户明确要求详情里**写明所有需要 ReShade 的**功能与代价。"""
    text = LAUNCH_PAGE.read_text(encoding="utf-8")

    for probe in ("禁用所有 ReShade 注入", "阻止所有 ReShade 注入", "DLSS5 神经渲染",
                  "第一人称视角", "统一管理器面板",
                  "大幅提升账号安全性", "风险不为零"):
        assert probe in text, f"文案缺「{probe}」"


def test_frontend_hotkey_lock_sits_right_under_the_panel_switch():
    """用户 2026-10-13：「**mod 快捷键锁定放到聚合面板开关下面**」。

    两者本来是一体的（面板不开 ⇒ 锁键会被强制关），排在隔壁一眼就能看懂联动。
    """
    text = LAUNCH_PAGE.read_text(encoding="utf-8")
    panel = text.index('k: "minimal_injection"')
    lock = text.index('k: "hotkey_takeover"')
    others = [text.index(f'k: "{key}"') for key in
              ("dlss5_addon_enabled", "firstperson_addon_enabled", "efmi_injection")]

    assert lock > panel, "锁键要排在统一管理器之后"
    assert all(lock < pos for pos in others), "锁键要**紧接着**统一管理器，别被别的开关隔开"


# ---------------------------------------------------------------------------
# ⑦ 配置一致性收敛（老配置升级上来时把"两个都开"纠正掉）
# ---------------------------------------------------------------------------
def test_consistency_sweep_closes_dependents_left_over_from_an_old_config(env):
    """★ 用户 2026-10-13：「现在还是聚合面板和禁用 reshade 都开，**只要禁用 reshade 开了，
    那几个都被关**」。

    老版本里总闸默认关、统一管理器默认开 ⇒ 升级后配置里两个都为真；配置自己不会纠正
    （`set_reshade_disabled` 只在"点它的那一刻"收敛），所以要有一道幂等的收敛。
    """
    env.config.reshade_disabled = True
    for key in DEPENDENT:
        setattr(env.config, key, True)

    changed = env.inst._enforce_master_switch_consistency()          # noqa: SLF001

    assert set(changed) == set(DEPENDENT), f"这四个都要被收敛: {changed}"
    for key in DEPENDENT:
        assert getattr(env.config, key) is False, f"{key} 必须落成关"


def test_consistency_sweep_is_idempotent_and_harmless(env):
    """一致时**什么都不做**（也不写盘），总闸关着时更不许动别人的开关。"""
    env.config.reshade_disabled = True
    for key in DEPENDENT:
        setattr(env.config, key, False)
    assert env.inst._enforce_master_switch_consistency() == []        # noqa: SLF001

    env.config.reshade_disabled = False
    env.config.minimal_injection = True           # 总闸关着 ⇒ 用户爱开就开着
    assert env.inst._enforce_master_switch_consistency() == []        # noqa: SLF001
    assert env.config.minimal_injection is True


def test_get_state_runs_the_consistency_sweep():
    """收敛要**挂在 `get_state()` 上** —— 界面一刷新就纠正老配置，不必等用户点开关。

    ⚠️ 这里用**静态钉住**而不是真跑 `get_state()`：本文件的 `env` 用 `__new__` 绕过构造，
    没有 `_ui_ready` 这些运行期成员，真调会直接炸在第一步（实测过）。
    收敛**本身**的行为已由上面两条用例覆盖。
    """
    source = Path(api_mod.__file__).read_text(encoding="utf-8")
    body = source.split("def get_state(self)", 1)[1].split("\n    def ", 1)[0]

    assert "_enforce_master_switch_consistency()" in body, "get_state 里必须调用一致性收敛"
