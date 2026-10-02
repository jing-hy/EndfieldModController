"""「皮肤 Mod」总开关的语义（用户 2026-10-02 实测后的要求）。

用户原话：①「**efmi 关了直接终末地拉不起来**」②「**我手动关了所有皮肤 mod 就可以进了**」。
⇒ 这个开关**不再是"EFMI 注入开关"**：EFMI 的 `d3d11.dll` **始终注入**（注入库空了 XXMI 就
认不了游戏），关掉它只表示"**一个皮肤都不加载**"（staging 清空）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import launcher
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    (lib / "佩丽卡" / "皮肤A").mkdir(parents=True)
    (lib / "佩丽卡" / "皮肤A" / "0.ini").write_text("namespace = Demo\n", encoding="utf-8")
    staging = tmp_path / "runtime" / "EFMI" / "Mods"
    staging.mkdir(parents=True)
    dll_dir = tmp_path / "dlss5"
    dll_dir.mkdir()
    (dll_dir / "d3d12.dll").write_bytes(b"MZ")
    efmi = tmp_path / "efmi" / "d3d11.dll"
    efmi.parent.mkdir()
    efmi.write_bytes(b"MZ")
    config = AppConfig(
        library_dir=str(lib),
        runtime_dir=str(tmp_path / "runtime"),
        staging_mods_dir=str(staging),
    )
    config.save(tmp_path / "config.json")
    monkeypatch.setattr(AppConfig, "dlss5_dll_path", property(lambda self: dll_dir / "d3d12.dll"))
    monkeypatch.setattr(AppConfig, "efmi_dll_path", property(lambda self: efmi))
    return SimpleNamespace(tmp=tmp_path, config=config, lib=lib, staging=staging)


def test_effective_selection_follows_the_master_switch(env):
    env.config.selected_mods = ["a", "b"]
    env.config.efmi_injection = True
    assert env.config.effective_selected_mods == ["a", "b"]
    env.config.efmi_injection = False
    assert env.config.effective_selected_mods == [], "关掉皮肤总开关就该一个都不 stage"


def test_efmi_dll_is_injected_even_when_the_skin_switch_is_off(env):
    """核心：关皮肤**不能**停掉 EFMI 注入 —— 用户实测那样终末地直接拉不起来。"""
    env.config.efmi_injection = True
    on = launcher.dlss5_injection_targets(env.config)
    env.config.efmi_injection = False
    off = launcher.dlss5_injection_targets(env.config)
    assert any("d3d11.dll" in t for t in on), on
    assert any("d3d11.dll" in t for t in off), f"关掉皮肤后 EFMI 的 dll 被移出注入库了: {off}"
    assert on == off, "皮肤开关不该影响注入库内容"


def test_prepare_does_not_wipe_user_selection_when_switch_is_off(env):
    """关皮肤时 `prepare` 传空选择去清空 staging，但**不能**把用户自己的勾选清掉。"""
    api = EndfieldModControllerApi(env.tmp / "config.json")
    api.config.efmi_injection = False
    api.config.selected_mods = ["a", "b"]
    api.config.save()
    result = api.prepare()
    assert result["patch_count"] == 0
    assert api.config.selected_mods == ["a", "b"], "关皮肤把用户的勾选清没了"
    # `MC_Controller` 是控制器自己的产物目录（保留是对的），要查的是**皮肤**有没有残留
    leftovers = [p.name for p in env.staging.glob("MC_*") if p.name != "MC_Controller"]
    assert leftovers == [], f"关皮肤后 Mods 里还有皮肤残留: {leftovers}"


def test_prepare_stages_normally_when_switch_is_on(env):
    api = EndfieldModControllerApi(env.tmp / "config.json")
    api.config.efmi_injection = True
    mods = api._mods()
    assert mods, "测试库应该能扫到那个假皮肤"
    api.config.selected_mods = [mods[0].id]
    api.config.save()
    result = api.prepare()
    # ⚠️ patch_count 与"有没有 stage"不是一回事（这个假 Mod 没有可 patch 的内容），
    #    所以这里断言的是 **staging 目录里真的出现了 MC_***
    assert list(env.staging.glob("MC_*")), "开着皮肤时应该真的 stage 出 MC_*"
    assert result["controller_dir"]
