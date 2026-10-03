"""钉住「用户亲手点的更新必须真的更新」（2026-10-03 用户报的两个症状）。

**症状**：「**一键更新没动态**」「**告诉我更新完了，但是一键启动又说没有**」。

**同一个根因**：依赖页「一键更新全部组件」→ `start_full_update` → worker 里调
`runtime_deps.ensure_all(...)` **没传 `force`** ⇒ `ensure_xxmi` 撞上守卫
`if existing and not _auto_update_enabled(config):`（用户 `auto_update_dependencies=False`）
⇒ **只检查、不下载**。于是"更新完成"却一个字节没下、"没动态"（秒退）、
下一次启动版本表比对又报有新版。

**判据**：那个开关的语义是「**启动时**要不要自动更新」（用户原话：「自动更新应该弹窗
跳转到依赖页下载」= 不自动下载、引导到依赖页）。用户在依赖页**亲手点**的更新是**显式指令**。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from endfieldmodcontroller import api as A
from endfieldmodcontroller import runtime_deps as R


def test_ensure_all_accepts_force() -> None:
    """`ensure_all` 与四个 `ensure_*` 都要接受 `force`（关键词参数）。"""
    for fn in (R.ensure_all, R.ensure_xxmi, R.ensure_xxmi_libs, R.ensure_efmi, R.ensure_poser):
        sig = inspect.signature(fn)
        assert "force" in sig.parameters, f"{fn.__name__} 缺 force 参数"
        assert sig.parameters["force"].default is False, f"{fn.__name__} 的 force 默认应为 False"


def test_local_copy_short_circuits_the_online_check() -> None:
    """★ 关着「自动更新依赖」+ 本地已就位 ⇒ **一次网络都不发**。

    2026-10-03 用户实测「为什么真正启动这么慢，在干什么，日志也没有」：一次「一键启动」
    花了 **62 秒**，其中 Poser 那步 54 秒在**静默下载新版**（`23:37:05 builtin Poser: start`
    → `23:37:59 builtin Poser: installed`）—— 而他的「自动更新依赖」是关着的。
    `ensure_xxmi` 早就有那条守卫，**其余三个（Libs / EFMI / Poser）都漏了**。
    """
    for fn in (R.ensure_xxmi, R.ensure_xxmi_libs, R.ensure_efmi, R.ensure_poser):
        src = inspect.getsource(fn)
        assert "_skip_online_check(" in src, (
            f"{fn.__name__} 缺「本地已就位就不联网」这条早退 —— "
            "关着自动更新的用户会在启动流程里被静默下载几十 MB")


def test_ensure_all_passes_force_down() -> None:
    """★ `ensure_all` 要把 force 透传给每个组件，别只是收下不用。"""
    src = inspect.getsource(R.ensure_all)
    assert "force=force" in src, "ensure_all 没有把 force 透传给各 ensure_*"


def test_start_full_update_sends_force() -> None:
    """★ 「一键更新全部组件」那条链路（`start_full_update`）必须传 force=True。

    这是用户实际点的按钮 —— 漏了它，整个修复就不生效。
    """
    src = inspect.getsource(A.EndfieldModControllerApi.start_full_update)
    assert "ensure_all(" in src, "start_full_update 里应当调 ensure_all"
    assert "force=True" in src, (
        "start_full_update 调 ensure_all 时没传 force=True —— "
        "用户在依赖页点「一键更新全部组件」会只检查不下载")


def test_force_actually_bypasses_switch(monkeypatch, tmp_path: Path) -> None:
    """行为验证：本地就位时，`force=False` **不联网**，`force=True` 照旧真的去下载。

    场景："远端有新版、本地有旧版、自动更新开关关着"。
    * `force=False` ⇒ 一个请求都不发（返回 `up_to_date`，用本地版本号）；
    * `force=True`  ⇒ 继续往下走（真的去下载）—— 用户在依赖页亲手点的更新不能被开关挡住。
    """
    from endfieldmodcontroller.config import AppConfig

    cfg = AppConfig.load(tmp_path / "config.json")
    monkeypatch.setattr(R, "_auto_update_enabled", lambda _cfg: False)
    monkeypatch.setattr(R, "_find_xxmi_exe", lambda _root: tmp_path / "XXMI Launcher.exe")
    (tmp_path / "XXMI Launcher.exe").write_bytes(b"MZ")
    monkeypatch.setattr(R, "_read_marker", lambda _root: {"version": "v1.0.0"})

    queried: list[str] = []
    monkeypatch.setattr(R, "_latest_release_asset",
                        lambda *a, **k: (queried.append("query"), ("http://x/y.zip", "v9.9.9", "y.zip", ""))[1])

    r1 = R.ensure_xxmi(cfg, force=False)
    assert str(r1.status) == "up_to_date", f"本地就位且未开自动更新时应直接算最新，实际 {r1.status}"
    assert queried == [], "这时**不该联网**（用户实测就是它把启动拖到 62 秒）"

    def _boom(*a, **k):
        raise RuntimeError("REACHED_DOWNLOAD")

    monkeypatch.setattr(R, "_download_extract", _boom)
    with pytest.raises(RuntimeError, match="REACHED_DOWNLOAD"):
        R.ensure_xxmi(cfg, force=True)
