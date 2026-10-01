"""「冲突 → 一键关闭其中一个（自行选择）」的回归测试（2026-10-01 用户要求）。

用户原话：「**如果确定是皮肤冲突导致崩溃，弹窗加个选项，一键关闭其中一个（自行选择），
然后点了这个之后关掉这个弹窗，再弹一个，选择要保留的，然后在冲突的中间下拉框选择要保留的，
每组冲突单独下拉框**」。

后端要守住的性质：
* 冲突是**结构化**的（每组含涉及的 Mod 名 + **库内 id**）—— 前端才能"每组一个下拉框"；
* `resolve_mod_conflicts(keep)` 只**取消勾选**没被保留的那些，**绝不动 Mod 库**（不删不移）；
* 处理完要**重新生成控制器**（否则用户进游戏照样撞）；
* 库内定位不到的（手动放进 Mods 的目录）标 `resolvable=False`，不硬处理。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import core, crashwatch, diagnostics, initialize
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig

# 两个 Mod 只要共有一段 `[TextureOverride_<hash>_…]` 就算覆盖同一批资源
SHARED_INI = """
namespace = Test{tag}
[TextureOverride_aaaa1111_body]
hash = aaaa1111
[TextureOverride_bbbb2222_head]
hash = bbbb2222
[Constants]
global persist $coat = 0
[KeyCoat]
key = no_modifiers VK_9
type = cycle
$coat = 0,1
"""

MOD_A = "庄方宜 水墨旗袍大招黑丝"
MOD_B = "Zhuang Fangyi Ink Cheongsam full ver 5.2"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(EndfieldModControllerApi, "_warm_up", lambda self: None)
    library = tmp_path / "library"
    runtime = tmp_path / "runtime"
    staging = runtime / "EFMI" / "Mods"
    for index, name in enumerate((MOD_A, MOD_B)):
        target = library / name
        target.mkdir(parents=True)
        (target / "0.ini").write_text(SHARED_INI.format(tag=chr(65 + index)), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config = AppConfig(library_dir=str(library), runtime_dir=str(runtime),
                       staging_mods_dir=str(staging))
    config.save(config_path)
    return SimpleNamespace(root=tmp_path, library=library, runtime=runtime, staging=staging,
                           config_path=config_path, config=config)


def _stage(env, mods: list, *, alias: dict[str, str] | None = None) -> list[str]:
    """按 staging 命名规则 (`MC_{safe_name(group)}_{safe_name(name)}`) 造出 staging 目录。"""
    names: list[str] = []
    for mod in mods:
        shown = (alias or {}).get(mod.name, mod.name)
        name = f"MC_{core.safe_name(mod.group)}_{core.safe_name(shown)}"
        target = env.staging / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "0.ini").write_text(SHARED_INI.format(tag="S"), encoding="utf-8")
        names.append(name)
    return names


def _library_mods(env) -> list:
    return list(core.scan_library(env.library, env.staging))


# --------------------------------------------------------------- 结构化
def test_conflict_summary_is_structured(env):
    names = _stage(env, _library_mods(env))
    groups = initialize._mod_conflict_summary(env.config, env.staging, names)

    assert groups, "两个覆盖同一批资源的 Mod 必须被判为冲突"
    assert groups[0]["names"] == names
    assert len(groups[0]["shared"]) >= 2
    assert groups[0]["shared"] == sorted(groups[0]["shared"])
    assert "覆盖同一批资源" in groups[0]["text"]


def test_check_mod_conflicts_records_groups_with_mod_ids(env):
    _stage(env, _library_mods(env))
    report = initialize.Report()

    initialize._check_mod_conflicts(env.config, report, None)

    state = diagnostics.mod_conflict_state(env.config)
    assert state.get("ok") is False
    groups = state.get("groups") or []
    assert groups, state
    ids = [entry["id"] for group in groups for entry in group["mods"]]
    assert all(ids), f"每个冲突 Mod 都要能反查回库内 id（前端要靠它取消勾选）: {groups}"
    assert all(group.get("resolvable") for group in groups)


def test_unresolvable_when_staged_dir_not_in_library(env):
    """手动放进 Mods 的目录（库里没有）→ resolvable=False，不能硬处理。"""
    mods = _library_mods(env)
    _stage(env, [mods[0]])
    manual = env.staging / f"MC_{core.safe_name(mods[0].group)}_手动放的"
    manual.mkdir(parents=True, exist_ok=True)
    (manual / "0.ini").write_text(SHARED_INI.format(tag="M"), encoding="utf-8")

    initialize._check_mod_conflicts(env.config, initialize.Report(), None)

    groups = [g for g in (diagnostics.mod_conflict_state(env.config).get("groups") or [])]
    assert groups
    assert any(group.get("resolvable") is False for group in groups), groups


def test_prelaunch_risks_carries_groups(env):
    _stage(env, _library_mods(env))
    initialize._check_mod_conflicts(env.config, initialize.Report(), None)

    risks = crashwatch.prelaunch_risks(env.config)

    assert risks["blocking"] is True
    assert risks["conflicts"] and risks["groups"]
    assert risks["groups"][0]["mods"][0]["id"]


# --------------------------------------------------------------- 一键处理
def test_resolve_mod_conflicts_drops_unkept(env, monkeypatch):
    mods = _library_mods(env)
    keep = mods[0]
    drop = mods[1]
    env.config.selected_mods = [keep.id, drop.id]
    env.config.save(env.config_path)
    diagnostics.record_mod_conflicts(env.config, ok=False, conflicts=["冲突"],
                                     groups=[{
                                         "names": [keep.name, drop.name],
                                         "shared": ["h:aaaa1111", "h:bbbb2222"],
                                         "mods": [{"name": keep.name, "id": keep.id},
                                                  {"name": drop.name, "id": drop.id}],
                                         "resolvable": True,
                                     }])
    calls: list = []
    monkeypatch.setattr(EndfieldModControllerApi, "prepare",
                        lambda self, ids=None: (calls.append(ids), {"patch_count": 0, "action_count": 0})[1])
    api = EndfieldModControllerApi(env.config_path)

    result = api.resolve_mod_conflicts([keep.id])

    assert result["ok"] is True and result["changed"] is True, result
    assert result["dropped"] == [drop.id]
    assert api.config.selected_mods == [keep.id], "只该取消勾选没被保留的那个"
    assert calls and calls[0] == [keep.id], "处理完必须重新生成控制器"
    # **绝不动 Mod 库**（数据安全红线）
    assert (env.library / MOD_A).is_dir() and (env.library / MOD_B).is_dir()


def test_resolve_reports_when_nothing_to_do(env):
    api = EndfieldModControllerApi(env.config_path)
    result = api.resolve_mod_conflicts(["whatever"])
    assert result["ok"] is False
    assert "没有可以自动处理" in result["message"]


def test_conflict_groups_api_returns_groups(env):
    _stage(env, _library_mods(env))
    initialize._check_mod_conflicts(env.config, initialize.Report(), None)
    api = EndfieldModControllerApi(env.config_path)

    payload = api.conflict_groups()

    assert payload["ok"] is True
    assert payload["groups"], payload
    assert payload["conflicts"]
