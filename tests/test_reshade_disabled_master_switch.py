"""总闸：「禁用所有 ReShade 注入」（2026-10-09 用户要求）。

用户原话：「在注入开关最上边做一个和其他不一样一点、明显一点的，写禁用所有 reshade 注入，
详情写明阻止所有 reshade 注入，会导致…（所有需要 reshade 的）不可用，但能大幅提升账号
安全性（风险不为零）……这个开了之后就……阻止所有 reshade 注入，要加一层保险，就算之前有
reshade 注入，也能清理出终末地」。随后明确：「**不是 dlss4 互斥，是禁用，直接不能点开开关
那种**」。

本文件守住六件事：

① `reshade_base_wanted()` **最优先**判总闸 ⇒ 开着就一个底座都不注入
   （压过 `minimal_injection` 与三个 addon 开关）；
② 总闸开着时，四个依赖 ReShade 的开关**直接拒、且不写配置**（"点不开"那种）；
③ 开总闸把那四个开关**实际关掉**（留着"开着"会让人以为还在生效）；
④ **保险**：开总闸会把游戏目录里已有的 ReShade 痕迹搬出去（有备份、可还原）；
⑤ `auto_clean_before_launch` 在总闸开着时**无视**「启动前清除第三方注入」那个设置；
⑥ 前端：总闸排在 `SWITCHES` **第一个**、四个开关挂了锁、文案写明了所有受影响的功能。

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
             "firstperson_addon_enabled", "mfg_unlock_enabled")

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
# ① 总闸压过一切
# ---------------------------------------------------------------------------
def test_master_switch_beats_every_other_switch():
    """★ 总闸开着 ⇒ 一个底座都不注入，哪怕其它开关全开。"""
    config = AppConfig(reshade_disabled=True, minimal_injection=True,
                       dlss5_addon_enabled=True, firstperson_addon_enabled=True,
                       mfg_unlock_enabled=True)

    wanted, reason = reshade_integration.reshade_base_wanted(config)

    assert wanted is False
    assert "禁用所有 ReShade 注入" in reason


def test_without_master_switch_nothing_changes():
    """关着时行为与以前**完全一致**（不能把正常用户也挡了）。"""
    assert reshade_integration.reshade_base_wanted(AppConfig(minimal_injection=True))[0] is True
    assert reshade_integration.reshade_base_wanted(
        AppConfig(minimal_injection=False, dlss5_addon_enabled=True))[0] is True
    assert reshade_integration.reshade_base_wanted(
        AppConfig(minimal_injection=False, dlss5_addon_enabled=False,
                  firstperson_addon_enabled=False, mfg_unlock_enabled=False))[0] is False


# ---------------------------------------------------------------------------
# ② "点不开"：后端直接拒
# ---------------------------------------------------------------------------
def test_dependent_switches_are_rejected_while_master_is_on(env):
    env.config.reshade_disabled = True

    for call_it in (lambda: env.inst.set_minimal_injection(True),
                    lambda: env.inst.set_component_addon("dlss5", True),
                    lambda: env.inst.set_component_addon("firstperson", True),
                    lambda: env.inst.set_component_addon("mfg", True)):
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
    assert set(result["closed"]) == {"统一管理器", "DLSS5 神经渲染", "第一人称视角", "DLSS4 多帧生成"}


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
                  "第一人称视角", "DLSS4 多帧生成解锁", "统一管理器面板",
                  "大幅提升账号安全性", "风险不为零"):
        assert probe in text, f"文案缺「{probe}」"
