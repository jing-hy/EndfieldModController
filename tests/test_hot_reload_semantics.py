"""热重载与「皮肤 Mod 总开关」的语义（2026-10-06 用户「那做一下」）。

**① 「皮肤 Mod」总开关改到就该立刻重铺 staging**
   「关掉总开关 = 一个皮肤都不加载」这个语义本来成立（`config.effective_selected_mods`
   返回空 ⇒ `stage_and_prepare` 走 `_stage_empty`），但**只在跑过一次重铺之后**才发生；
   而拨开关只走 `save_config`（改配置）⇒ 用户看到"关了但 Mod 还在"
   （实测：关掉后 `Mods\\` 仍有 22 个目录，手动跑一次 `prepare()` 才降到 2 个）。

**② `send_f10` 不该把"文件没变"说成"3DMigoto 没有响应"**
   3DMigoto 的 `SavePersistentSettings()` 只在 `user_config_dirty` 为真时才写
   `d3dx_user.ini` ⇒ 游戏内没改过变量时，F10 生效了文件也不变。旧文案据此断言"没响应"，
   紧接着又打印"热重载: 完成"，自相矛盾（实测：手动按 F10 表现完全一样）。

**③ 热重载不该跑 `prepare_launch()`**
   它会走 `ensure_all()` ⇒ 每次展开 `nvngx_dlssnr.dll`（103 MB，实测 4 秒），
   而游戏正跑着那些文件本来就被占用（`WinError 5` / `WinError 32`）——
   用户说的"卡一下"就是这么来的，且对热重载毫无用处。
"""
from __future__ import annotations

import inspect
import pathlib
import textwrap

import pytest

from endfieldmodcontroller import api as apimod
from endfieldmodcontroller import hot_reload
from endfieldmodcontroller.config import AppConfig

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _instance(tmp_path, monkeypatch):
    """造一个只碰 tmp_path 的 API 实例（不展开资产、不碰真实目录）。

    ⚠️ 样本必须用**真实 Mod 目录的副本**：只放一个 `mod.ini` 的"假 Mod"不足以被
    `stage_and_prepare` 铺进 staging（实测：`prepare()` 报"已恢复加载 2 个"，
    而 `Mods\\` 里只有管理器的两个目录）⇒ 那样测不出"开⇒铺回来"。
    """
    import shutil

    library = tmp_path / "library"
    staging = tmp_path / "runtime" / "builtin" / "XXMI" / "EFMI" / "Mods"
    library.mkdir(parents=True)
    staging.mkdir(parents=True)

    source_root = pathlib.Path(r"D:\zmdmod\modtest\library")
    copied = 0
    if source_root.is_dir():
        for candidate in sorted(source_root.iterdir()):
            if copied >= 2:
                break
            if not candidate.is_dir() or candidate.name.startswith("_"):
                continue
            try:
                shutil.copytree(candidate, library / candidate.name)
                copied += 1
            except OSError:
                continue
    if copied < 2:                       # 兜底：源库不可用时至少保证目录结构成立
        for name in ("mod-a", "mod-b"):
            folder = library / name
            folder.mkdir()
            (folder / "mod.ini").write_text("[TextureOverrideShade]\nhash = bf266dfc\n",
                                            encoding="utf-8")

    monkeypatch.setattr(AppConfig, "library_path",
                        property(lambda self: library))
    monkeypatch.setattr(AppConfig, "staging_mods_path",
                        property(lambda self: staging))

    cls = next(o for _n, o in vars(apimod).items()
               if inspect.isclass(o) and hasattr(o, "get_state"))
    inst = cls.__new__(cls)
    cfg = AppConfig()
    cfg.library_dir = str(library)
    cfg.data_root = str(tmp_path)
    cfg._config_path = str(tmp_path / "config.json")
    cfg.save()
    inst._config = cfg
    inst._config_path = pathlib.Path(tmp_path / "config.json")
    inst._config_mtime = None
    inst._invalidate_mods() if hasattr(inst, "_invalidate_mods") else None
    return inst, cfg, staging, library


def test_toggling_efmi_off_restages_immediately(tmp_path, monkeypatch):
    """★ 关掉总开关 ⇒ **当场**清空 staging（不能等下一次一键启动）。"""
    inst, cfg, staging, library = _instance(tmp_path, monkeypatch)
    cfg.efmi_injection = True
    cfg.selected_mods = [p.name for p in sorted(library.iterdir()) if p.is_dir()][:2]
    inst.prepare()
    assert len([p for p in staging.iterdir() if p.is_dir()]) >= 2, "前置：应该铺上了"

    result = inst.save_config({"efmi_injection": False})

    left = [p.name for p in staging.iterdir() if p.is_dir()]
    assert not [n for n in left if n.startswith("MC_") and "Controller" not in n], (
        f"关掉总开关后 Mods 里还留着 Mod：{left} —— 用户看到的就是「关了但没关掉」"
    )
    assert result.get("staged") is True, "没报告已重铺"
    assert "已全部关闭" in str(result.get("stage_message") or "")


def test_toggling_efmi_back_on_restores(tmp_path, monkeypatch):
    """★ 再打开 ⇒ 当场铺回来（语义可逆）。"""
    inst, cfg, staging, library = _instance(tmp_path, monkeypatch)
    cfg.efmi_injection = False
    cfg.selected_mods = [p.name for p in sorted(library.iterdir()) if p.is_dir()][:2]
    result = inst.save_config({"efmi_injection": True})
    # 与"清空"走同一条 prepare()；这里只验"重铺动作确实跑了、且报成功"
    # （在 tmp 环境里复制进来的 Mod 需要重新扫描才认得出，不适合断言具体目录名）
    assert result.get("staged") is True, "打开总开关时没有重铺"
    assert "已恢复加载" in str(result.get("stage_message") or "")


def test_unrelated_setting_does_not_restage(tmp_path, monkeypatch):
    """改别的设置不该触发重铺（避免白干重活）。"""
    inst, cfg, _staging, _library = _instance(tmp_path, monkeypatch)
    result = inst.save_config({"theme": "light"})
    assert "staged" not in result


def test_send_f10_does_not_claim_no_response():
    """★ 不能再出现"3DMigoto 没有响应"这种断言（那个判据不成立）。"""
    src = pathlib.Path(hot_reload.__file__).read_text(encoding="utf-8")
    assert "3DMigoto **没有**响应" not in src, (
        "又用 d3dx_user.ini 的 mtime 断言'没响应'了 —— 3DMigoto 只在变量脏时才写它"
    )
    assert "无法据此确认" in src, "应改成中性表述"


def test_hot_reload_does_not_expand_runtime_assets():
    """★ `hot_reload()` 里不能再**调用** `prepare_launch()`（它会展开 103 MB 资产、且必然失败）。

    ⚠️ 用 **AST** 判，不要用字符串（注释与 docstring 里会提到 `prepare_launch()` 来说明
    "为什么不要调它"，按字符串判会因为自己的注释而永远红着 —— 实测踩过）。
    """
    import ast as _ast

    cls = next(o for _n, o in vars(apimod).items()
               if inspect.isclass(o) and hasattr(o, "get_state"))
    src = inspect.getsource(cls.hot_reload)
    tree = _ast.parse(textwrap.dedent(src))

    called: set[str] = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            if isinstance(func, _ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, _ast.Name):
                called.add(func.id)

    assert "prepare_launch" not in called, (
        "热重载又去**调用** prepare_launch() 了 —— 那会重复展开 nvngx_dlssnr.dll（103 MB）"
    )
    assert "prepare" in called, "热重载应只重铺 Mod（调用 prepare）"
