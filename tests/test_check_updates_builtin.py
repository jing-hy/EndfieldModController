"""钉住「`check_updates` 必须覆盖**内置组件**」—— 2026-10-03 的"点了没反应"就是这个漏的。

**经过**：用户报「**下载并更新不是应该跳转到依赖页然后下载吗，点了没反应**」。
一查：`check_updates()` 只返回 `reshade` / `secondary_motion` / `poser`，
**内置组件（XXMI / XXMI-Libs / EFMI）根本不在里面** —— 而他要更新的正是 XXMI
（本地 v2.2.1 → 远端 v2.3.8）⇒ 前端"有更新就弹窗"的检查永远匹配不到 ⇒ 弹窗不出现。

这里钉两条不变式：
① `check_updates()` 的返回里**必须有 `builtin` 段**，且至少含 XXMI；
② `builtin` 里每项都有 `current` / `latest` / `update_available` 三个键，
   且 `update_available` 是 **bool**（前端据此过滤，类型不对就静默失效）。

⚠️ 这两条**不联网也能验一半**（结构），联网时才验得出真实版本号，
所以对"网络失败"的情形允许 `latest` 为空、但不允许缺少键。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import runtime_deps, updates
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def cfg(tmp_path: Path) -> AppConfig:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    config = AppConfig.load(cfg_path)
    config.data_root = str(tmp_path)
    config.library_dir = "library"
    config.save()
    return config


def test_check_updates_covers_builtin_components(cfg: AppConfig) -> None:
    """★ `builtin` 段必须存在，且含 XXMI（用户最常要更新的就是它）。"""
    report = updates.check_updates(cfg)
    assert "builtin" in report, f"缺少 builtin 段：{list(report.keys())}"
    builtin = report["builtin"]
    assert builtin, "builtin 段是空的 —— 内置组件又漏检了"
    assert "XXMI" in builtin, f"builtin 里没有 XXMI：{list(builtin.keys())}"


def test_builtin_entries_have_required_keys(cfg: AppConfig) -> None:
    """每项都要有 current/latest/update_available，且 update_available 必须是 bool。"""
    report = updates.check_updates(cfg)
    for key, info in (report.get("builtin") or {}).items():
        for field in ("current", "latest", "update_available"):
            assert field in info, f"{key} 缺字段 {field}"
        assert isinstance(info["update_available"], bool), (
            f"{key}.update_available 必须是 bool，实际 {type(info['update_available']).__name__}"
            "（前端靠它过滤，类型不对就静默失效）")


def test_errors_is_a_list_not_a_component(cfg: AppConfig) -> None:
    """`errors` 是**列表**，不是组件 —— 前端遍历时要区分（否则会当成 dict 处理）。"""
    report = updates.check_updates(cfg)
    assert isinstance(report.get("errors"), list)


def test_builtin_local_version_does_not_borrow_xxmi_version(cfg: AppConfig) -> None:
    """★ Libs / EFMI 的本地版本**不许借用 XXMI 的**（实测踩过：三个都显示 v2.2.1）。

    三者在同一个 marker 文件里；图省事一律读 `version` 会让 Libs/EFMI 报出 XXMI 的版本号，
    "有没有更新"的判断随之整个错掉。找不到自己的键就应当**如实留空**。
    """
    root = cfg.builtin_runtime_path / "XXMI"
    root.mkdir(parents=True, exist_ok=True)
    runtime_deps._write_marker(root, {"version": "v9.9.9", "asset": "x.zip", "source": "t"})

    assert updates._builtin_local_version(cfg, "XXMI") == "v9.9.9"
    assert updates._builtin_local_version(cfg, "XXMI-Libs") == ""
    assert updates._builtin_local_version(cfg, "EFMI") == ""
