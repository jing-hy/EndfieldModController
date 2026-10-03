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


def test_force_guard_present_in_ensure_xxmi() -> None:
    """★ 那道守卫必须写 `and not force`，否则显式更新会被自动更新开关挡掉。"""
    src = inspect.getsource(R.ensure_xxmi)
    assert "_auto_update_enabled(config) and not force" in src, (
        "ensure_xxmi 的守卫没有 `and not force` —— "
        "关着自动更新的用户在依赖页点「一键更新」会只检查不下载")


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
    """行为验证：force=True 时**不能**走 `update_available` 那条早退分支。

    用一个"远端有新版、本地有旧版、开关关着"的场景：
    * `force=False` ⇒ 应当返回 `update_available`（只提示不下载）；
    * `force=True`  ⇒ 应当**继续往下走**（真的去下载）。
    """
    from endfieldmodcontroller.config import AppConfig

    cfg = AppConfig.load(tmp_path / "config.json")
    monkeypatch.setattr(R, "_auto_update_enabled", lambda _cfg: False)
    monkeypatch.setattr(R, "_find_xxmi_exe", lambda _root: tmp_path / "XXMI Launcher.exe")
    (tmp_path / "XXMI Launcher.exe").write_bytes(b"MZ")
    monkeypatch.setattr(R, "_read_marker", lambda _root: {"version": "v1.0.0"})
    monkeypatch.setattr(R, "_latest_release_asset",
                        lambda *a, **k: ("http://x/y.zip", "v9.9.9", "y.zip", ""))

    # force=False：早退成 update_available
    r1 = R.ensure_xxmi(cfg, force=False)
    assert str(r1.status) == "update_available", f"未开自动更新时应只提示，实际 {r1.status}"

    # force=True：必须继续走到下载（这里让下载抛错，以证明它**没有**早退）
    def _boom(*a, **k):
        raise RuntimeError("REACHED_DOWNLOAD")

    monkeypatch.setattr(R, "_download_extract", _boom)
    with pytest.raises(RuntimeError, match="REACHED_DOWNLOAD"):
        R.ensure_xxmi(cfg, force=True)
