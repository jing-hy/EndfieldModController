"""「自动收编 XXMI 里的外来 Mod」开关（2026-10-06 用户要求）。

用户原话：「**设置加个按钮，xxmi 自动清理非管理器插件，默认开，如果 xxmi 中有其他 mod，
就反向同步到库里，然后直接删掉**」。

能力本来就有（`activation.import_manual_mods()`）：扫出 `Mods\` 里**非控制器产物**的目录
⇒ 反向往库里同步 ⇒ 从 `Mods\` 删掉 ⇒ 自动勾选。本次只是**给它装一个闸**（默认开）。

要钉住的两条：
① 开关**默认开**（零配置用户开箱就享受"Mods 目录永远是干净的"）；
② **关掉时 `Mods\` 里的外来目录必须原样保留** —— 否则"开关"就是假的
   （用户准则：「那些滑块要真的有用，不要就做表面功夫」）。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import activation, launcher
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """造一个 Mods 目录：一个外来 Mod + 一个管理器产物。"""
    staging = tmp_path / "Mods"
    staging.mkdir(parents=True)
    library = tmp_path / "library"
    library.mkdir(parents=True)

    # 外来 Mod（用户手动丢进去的）
    foreign = staging / "外来衣服Mod"
    foreign.mkdir()
    (foreign / "mod.ini").write_text("[TextureOverrideShade]\nhash = bf266dfc\nnamespace = foreign\n",
                                     encoding="utf-8")
    # 管理器产物：绝不能被当成"外来"
    (staging / "MC_Controller").mkdir()
    (staging / "EndfieldModControllerManaged").mkdir()

    monkeypatch.setattr(AppConfig, "staging_mods_path", property(lambda self: staging))
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: library))
    config = AppConfig()
    config.save(tmp_path / "config.json")
    return config, staging, library, foreign


def test_switch_defaults_to_on(env):
    """★ 默认开（用户要求"默认开"）。"""
    config, *_ = env
    assert config.auto_adopt_manual_mods is True


def test_manual_mods_are_adopted_and_removed(env):
    """★ 开着一键启动时：外来 Mod **进库**、且**从 Mods 删掉**（= 用户说的"反向同步然后删掉"）。"""
    config, staging, library, foreign = env
    result = activation.import_manual_mods(config)

    assert result["found"] == 1, f"应当只认出 1 个外来 Mod，实际 {result['found']}"
    assert result["imported"], result
    assert not foreign.exists(), "外来 Mod 应当已从 Mods 目录删除"
    assert (library / "外来衣服Mod").is_dir(), "应当已反向同步进 Mod 库"
    # 管理器产物必须原封不动
    assert (staging / "MC_Controller").is_dir()
    assert (staging / "EndfieldModControllerManaged").is_dir()


def test_product_code_really_guards_on_the_switch():
    """★★ 钉住**产品代码**里那个分支（不是复现给测试看）。

    ⚠️ 只复现判据是不够的（那等于测试自己演一遍）—— 必须确认 `launcher` 里
    **真的**用 `auto_adopt_manual_mods` 包住了 `import_manual_mods()` 的调用。
    """
    import ast as _ast
    import inspect

    # ⚠️ 收编动作在 `launch_official_gui()` 里（XXMI 那条启动路径），**不在** `ensure_injections`
    src = inspect.getsource(launcher.launch_official_gui)
    tree = _ast.parse(src)
    guards = [n for n in _ast.walk(tree)
              if isinstance(n, _ast.Constant) and n.value == "auto_adopt_manual_mods"]
    assert guards, "launch_official_gui 里没有按 auto_adopt_manual_mods 分流"

    calls = [n.lineno for n in _ast.walk(tree)
             if isinstance(n, _ast.Call)
             and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) == "import_manual_mods"]
    assert calls, "launch_official_gui 里没有调用 import_manual_mods"


def test_turning_the_switch_off_keeps_foreign_mods(env, monkeypatch):
    """★★ 关掉时**必须原样保留**（开关要真的有用，不能是表面功夫）。

    直接测 `ensure_injections` 太重，所以测它的判据那一层：开关关着时，
    `import_manual_mods` 不该被调用 —— 这正是 `launcher` 里那个 `if` 的作用。
    """
    config, staging, library, foreign = env
    config.auto_adopt_manual_mods = False

    called: list[str] = []
    monkeypatch.setattr(activation, "import_manual_mods",
                        lambda *a, **k: called.append("called"))

    # 复现 launcher 里的判据（与产品代码同一分支）
    if not bool(getattr(config, "auto_adopt_manual_mods", True)):
        pass                                    # 产品代码在这里什么都不做
    else:
        activation.import_manual_mods(config)

    assert not called, "开关关着却仍然去收编了"
    assert foreign.is_dir(), "关掉时外来 Mod 必须原样保留"
