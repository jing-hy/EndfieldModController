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
    config = AppConfig()
    # ⚠️ 必须落到一个**真实路径**上：关掉「统一管理器」时会连带关掉「Mod 快捷键锁定」并
    #    保存配置（`apply_minimal_injection` 的既有行为），没有路径时 `save()` 会抛异常。
    config.save(tmp_path / "config.json")
    return config, dlss5


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
    刚禁用的插件会被展开动作撤销。用 AST 判"`ensure_all` 调用之后还有归位调用"。

    ⚠️ 2026-10-07 收口：判据从"必须直接调 `set_component_addons`"改成
    "必须调 `realign_component_addons`" —— 归位逻辑收进那一个函数了（它内部覆盖
    三个组件 + 面板）。**判据本身没放松**：这一行删掉照样变红。
    """
    import ast as _ast

    src = inspect.getsource(launcher.ensure_injections)
    tree = _ast.parse(src)
    ensure_all_lines: list[int] = []
    realign_lines: list[int] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name == "ensure_all" and isinstance(func, _ast.Attribute):
                ensure_all_lines.append(node.lineno)
            if name == "realign_component_addons":
                realign_lines.append(node.lineno)

    assert ensure_all_lines, "ensure_injections 里没找到 ensure_all 调用"
    last_ensure = max(ensure_all_lines)
    assert [n for n in realign_lines if n > last_ensure], (
        "★ 展开资产（ensure_all）之后没有再次归位插件 ⇒ 关掉的插件会被展开动作放回根目录"
        "（用户报的「关了还是注入了」就是这个）"
    )


def test_unified_manager_panel_is_moved_out_when_off(env):
    """★ 「统一管理器」关掉 ⇒ **面板 addon 不能留在根目录**（2026-10-06 用户现场）。

    原话：「我除了 dlss4 全关，但是 **MOD 管理器**和第一人称还是注入了」——
    面板 addon 走的是**另一条路**（`apply_minimal_injection`），和组件那套不是同一个函数，
    所以对齐的时候必须**单独**再调它一次。
    """
    config, dlss5 = env
    name = launcher.UNIFIED_PANEL_ADDON
    config.minimal_injection = False                 # ⚠️ 默认是 True，必须显式关掉
    (dlss5 / name).write_bytes(b"panel")            # 模拟"展开之后又被放回根目录"

    launcher.apply_minimal_injection(config)

    assert not (dlss5 / name).is_file(), "统一管理器关着，面板却还在根目录 ⇒ 照样会被加载"
    assert (dlss5 / launcher.ADDON_DISABLED_DIR / name).is_file(), "应当被搬进 _disabled\\"


def test_unified_manager_panel_comes_back_when_on(env):
    """对照：打开统一管理器 ⇒ 面板回到根目录。"""
    config, dlss5 = env
    name = launcher.UNIFIED_PANEL_ADDON
    disabled = dlss5 / launcher.ADDON_DISABLED_DIR
    disabled.mkdir(parents=True, exist_ok=True)
    (disabled / name).write_bytes(b"panel")

    config.minimal_injection = True
    launcher.apply_minimal_injection(config)

    assert (dlss5 / name).is_file(), "打开后应当回到根目录"


def test_panel_realign_also_happens_after_expand():
    """★★ 顺序判据（第二处）：`ensure_all` 之后必须**也**再归位一次面板。

    面板走 `apply_minimal_injection`，与组件那套是两条路 ⇒ 只补组件那一半不够
    （2026-10-06 实测：组件都归位了，面板还留在根目录）。2026-10-07 起这两条路都收进
    `realign_component_addons()`，所以这里验的是"归位之后 `apply_minimal_injection`
    确实被调到"——用 AST 同时钉住"调了归位函数"与"归位函数内部真的调面板那一步"。
    """
    import ast as _ast

    src = inspect.getsource(launcher.ensure_injections)
    tree = _ast.parse(src)
    ensure_all_lines: list[int] = []
    realign_lines: list[int] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name == "ensure_all" and isinstance(func, _ast.Attribute):
                ensure_all_lines.append(node.lineno)
            if name == "realign_component_addons":
                realign_lines.append(node.lineno)

    assert ensure_all_lines, "ensure_injections 里没找到 ensure_all 调用"
    last_ensure = max(ensure_all_lines)
    assert [n for n in realign_lines if n > last_ensure], (
        "★ 展开资产之后没有再归位插件 ⇒ 「统一管理器」关掉后展开动作会把面板放回根目录"
    )
    # 归位函数内部必须**同时**管面板（它走的是另一条函数路径）
    inner = _ast.parse(inspect.getsource(launcher.realign_component_addons))
    called = {
        getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        for node in _ast.walk(inner) if isinstance(node, _ast.Call)
    }
    assert "apply_minimal_injection" in called, (
        "realign_component_addons 里没有管面板 ⇒ 面板会被展开动作放回根目录"
    )
    assert "set_component_addons" in called, "realign_component_addons 里没有管三个组件"


def test_enabling_puts_it_back(env):
    """对照：打开时应当把 addon 放回根目录。"""
    config, dlss5 = env
    name = launcher.MFG_ADDON_GLOBS[0]
    disabled = dlss5 / launcher.ADDON_DISABLED_DIR
    disabled.mkdir(parents=True, exist_ok=True)
    (disabled / name).write_bytes(b"addon")

    launcher.set_component_addons(config, "mfg", True)

    assert (dlss5 / name).is_file(), "打开后应当回到根目录"


# ---------------------------------------------------------------------------
# ★★ 2026-10-07：归位必须**所有入口都做**，而且**三个组件 + 面板一个都不能漏**
#    （现场：`mfg_unlock_enabled=False`，走"初始化自检"这条路时
#     `renodx-mfgunlock.addon64` 被展开放回顶层 ⇒ ReShade 照样加载它）
# ---------------------------------------------------------------------------
def _plant_all(dlss5: pathlib.Path, *, at_root: bool = True) -> list[str]:
    """把四个对象摆到（或搬离）底座根目录，返回它们的文件名。"""
    names = ["renodx-dlss5.addon64", "dlss5-feed.addon64", "trans-zh.addon64",
             launcher.FIRSTPERSON_ADDON_GLOBS[0], launcher.MFG_ADDON_GLOBS[0],
             launcher.UNIFIED_PANEL_ADDON]
    target = dlss5 if at_root else dlss5 / launcher.ADDON_DISABLED_DIR
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        (target / name).write_bytes(b"addon")
    return names


def test_realign_covers_every_component_and_the_panel(env):
    """★ 开关全关 ⇒ 四个对象**一个都不许留在根目录**（含 DLSS4 那把）。"""
    config, dlss5 = env
    names = _plant_all(dlss5)
    config.dlss5_addon_enabled = False
    config.firstperson_addon_enabled = False
    config.mfg_unlock_enabled = False          # 本作禁用时的默认值
    config.minimal_injection = False

    result = launcher.realign_component_addons(config)

    assert not result["errors"], result["errors"]
    for name in names:
        assert not (dlss5 / name).is_file(), f"★ 关着的 {name} 还在根目录 ⇒ ReShade 会加载它"
        assert (dlss5 / launcher.ADDON_DISABLED_DIR / name).is_file(), f"{name} 没停到位"


def test_realign_puts_enabled_ones_back(env):
    """对照：开关开着 ⇒ 该在根目录（别把归位做成"一律搬走"）。"""
    config, dlss5 = env
    names = _plant_all(dlss5, at_root=False)
    config.dlss5_addon_enabled = True
    config.firstperson_addon_enabled = True
    config.mfg_unlock_enabled = True
    config.minimal_injection = True

    launcher.realign_component_addons(config)

    for name in names:
        assert (dlss5 / name).is_file(), f"开着的 {name} 应当回到根目录"


def test_initialize_ensure_all_also_realigns():
    """★★ **收口判据**：`initialize.ensure_all` 也必须归位（它自己就会展开资产）。

    2026-10-07 之前这里只处理 DLSS5（`if not dlss5_addon_enabled: …`）⇒ 走"初始化自检"
    这条路时 MFG / 第一人称 / 面板都会被展开放回顶层。判据写在 AST 上：这一行删掉就红。
    """
    import ast as _ast

    from endfieldmodcontroller import initialize

    src = inspect.getsource(initialize.ensure_all)
    called = {
        getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        for node in _ast.walk(_ast.parse(src)) if isinstance(node, _ast.Call)
    }
    assert "realign_component_addons" in called, (
        "★ ensure_all 展开过随包资产，末尾却没有归位插件 ⇒ 关掉的插件会被放回底座目录"
        "（「dlss4 还是能开」就是这个）"
    )


def test_ensure_all_parks_the_mfg_addon_when_disabled(tmp_path, monkeypatch):
    """★ 现场复现：`mfg_unlock_enabled=False` + 展开把 `renodx-mfgunlock.addon64` 放回顶层
    ⇒ `ensure_all()` 结束时它必须回到 `_disabled\\`。"""
    from endfieldmodcontroller import initialize

    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    config = AppConfig()
    config.mfg_unlock_enabled = False
    (dlss5 / launcher.MFG_ADDON_GLOBS[0]).write_bytes(b"addon")     # 模拟"展开放回顶层"

    for name in ("_check_bundled_assets", "_check_dlss5_dir", "_check_reshade_ini",
                 "_check_dlss5_shaders", "_check_dlss5_preset", "_check_dlss5_gpu_support",
                 "_check_dlss5_ngx_consumer", "_check_panel_hotkey_conflicts",
                 "_check_panel_protocol_lint", "_check_dlss5_nr_binding",
                 "_check_dlss5_feed_redundant", "_check_dlss5_nrstyle", "_check_game_libs",
                 "_check_bundled_versions", "_check_controller", "_check_hotkey_panel",
                 "_check_staging", "_check_mod_conflicts", "_check_poser",
                 "_check_secondary_motion", "_check_proxy_backups",
                 "_check_defer_nr_until_camera_hook", "_check_dlssnr_arch", "_check_vc_runtime",
                 "_check_mfg_unlock", "_check_dlss5_nr_binding"):
        monkeypatch.setattr(initialize, name, lambda *a, **k: None)

    payload = initialize.ensure_all(config, log=None)

    name = launcher.MFG_ADDON_GLOBS[0]
    assert not (dlss5 / name).is_file(), "★ DLSS4 关着，addon 却留在根目录 ⇒ 游戏里还能开"
    assert (dlss5 / launcher.ADDON_DISABLED_DIR / name).is_file(), "没停到位"
    checks = [c for c in payload["checks"] if c["key"] == "addons:realigned"]
    assert checks, payload["checks"]
