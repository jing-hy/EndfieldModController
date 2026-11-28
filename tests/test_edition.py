# SPDX-License-Identifier: AGPL-3.0-only
"""版本形态（Universal / Lite）的判据测试（2026-11-28）。

两版共用同一份源码与数据根：Lite 靠 `endfieldmodcontroller/edition.py` 在运行期
把 ReShade 链路整体关掉。这里只钉"形态怎么判定"，以及最关键的"总闸语义"：
Lite 必须无视配置里的 `reshade_disabled=False`（否则用户切到 Lite 时 ReShade 还会被注入）。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import edition


@pytest.fixture(autouse=True)
def _clean_edition(monkeypatch):
    monkeypatch.delenv("MC_EDITION", raising=False)
    edition.reset_cache()
    yield
    edition.reset_cache()


def test_default_is_full() -> None:
    assert edition.current() == "full"
    assert edition.is_lite() is False
    assert edition.has_reshade() is True
    assert edition.effective_reshade_disabled(SimpleNamespace(reshade_disabled=False)) is False
    assert edition.effective_reshade_disabled(SimpleNamespace(reshade_disabled=True)) is True


def test_env_switch_to_lite(monkeypatch) -> None:
    monkeypatch.setenv("MC_EDITION", "lite")
    edition.reset_cache()
    assert edition.current() == "lite"
    assert edition.is_lite() is True
    assert edition.has_reshade() is False
    assert edition.label() == "轻量版"
    # ★ Lite 恒为"禁用 ReShade"：哪怕配置里写着 False，也不允许注入
    assert edition.effective_reshade_disabled(SimpleNamespace(reshade_disabled=False)) is True


def test_env_is_case_insensitive_and_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("MC_EDITION", "  LITE ")
    edition.reset_cache()
    assert edition.current() == "lite"


def test_invalid_env_falls_back_to_full(monkeypatch) -> None:
    monkeypatch.setenv("MC_EDITION", "something-else")
    edition.reset_cache()
    assert edition.current() == "full"


def test_edition_json_is_read_from_resource_root(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "edition.json").write_text(json.dumps({"edition": "lite"}), encoding="utf-8")
    monkeypatch.setattr(edition, "_resource_root", lambda: tmp_path)
    edition.reset_cache()
    assert edition.current() == "lite"


def test_env_wins_over_edition_json(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "edition.json").write_text(json.dumps({"edition": "lite"}), encoding="utf-8")
    monkeypatch.setattr(edition, "_resource_root", lambda: tmp_path)
    monkeypatch.setenv("MC_EDITION", "full")
    edition.reset_cache()
    assert edition.current() == "full"


def test_broken_edition_json_falls_back_to_full(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "edition.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(edition, "_resource_root", lambda: tmp_path)
    edition.reset_cache()
    assert edition.current() == "full"


def test_unknown_edition_value_in_json_falls_back_to_full(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "edition.json").write_text(json.dumps({"edition": "lite-plus"}), encoding="utf-8")
    monkeypatch.setattr(edition, "_resource_root", lambda: tmp_path)
    edition.reset_cache()
    assert edition.current() == "full"

def _release(names: list[str]) -> dict:
    return {"assets": [
        {"name": name, "browser_download_url": "https://example.invalid/" + name}
        for name in names
    ]}


def test_self_update_picks_its_own_asset_only(monkeypatch) -> None:
    """两版附件挂在同一个 Release 上时，各自只认自己的包 —— 装错就是换成另一种形态。"""
    from endfieldmodcontroller import selfupdate

    release = _release(["EndfieldModController.exe", "EndfieldModController-Lite.exe"])

    monkeypatch.setenv("MC_EDITION", "lite")
    edition.reset_cache()
    picked = selfupdate._pick_asset(release)
    assert picked is not None and picked["name"] == "EndfieldModController-Lite.exe"
    # 只有完整版附件 ⇒ 找不到，**绝不回退**到另一版
    assert selfupdate._pick_asset(_release(["EndfieldModController.exe"])) is None

    monkeypatch.setenv("MC_EDITION", "full")
    edition.reset_cache()
    picked = selfupdate._pick_asset(release)
    assert picked is not None and picked["name"] == "EndfieldModController.exe"
    assert selfupdate._pick_asset(_release(["EndfieldModController-Lite.exe"])) is None


def test_self_update_works_with_both_assets_after_lite(monkeypatch) -> None:
    """同一份 Release 里两版并存时，Lite 的"最新版"不能被带版本号的副本抢走。"""
    from endfieldmodcontroller import selfupdate

    monkeypatch.setenv("MC_EDITION", "lite")
    edition.reset_cache()
    release = _release([
        "EndfieldModController.exe",
        "EndfieldModController-1.5.2.exe",
        "EndfieldModController-Lite.exe",
        "EndfieldModController-Lite-1.5.2.exe",
    ])
    picked = selfupdate._pick_asset(release)
    assert picked is not None, "两版并存时 Lite 必须能选中自己的主程序包"
    assert picked["name"] == "EndfieldModController-Lite.exe"

def test_lite_does_not_require_reshade_dll(tmp_path, monkeypatch):
    """Lite 版**不该**因为 `reshade_dll` 找不到被拦启动（2026-11-28 实测）。

    现场：Lite 用户点一键启动弹 `launch failed: ReShade DLL not found:
    runtime/dlss5/d3d12.dll`。Lite 根本不含 ReShade（`edition.is_lite()` 一个底座都不注入），
    可 config 里那串 `reshade_dll` 还留着默认值 ⇒ `AppConfig.validate()` 必然报这条 ⇒ 启动被拦。
    这不是"文件缺了要补"，是"这一版不要它"。
    """
    from endfieldmodcontroller.config import AppConfig

    monkeypatch.setenv("MC_EDITION", "lite")
    edition.reset_cache()
    cfg = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                    reshade_dll=str(tmp_path / "nope" / "d3d12.dll"))
    problems = cfg.validate()
    assert not any("ReShade DLL not found" in item for item in problems), problems


def test_full_still_requires_reshade_dll(tmp_path, monkeypatch):
    """完整版仍然要校验（别把这条判据一起删掉）。"""
    from endfieldmodcontroller.config import AppConfig

    monkeypatch.delenv("MC_EDITION", raising=False)
    edition.reset_cache()
    cfg = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                    reshade_dll=str(tmp_path / "nope" / "d3d12.dll"))
    problems = cfg.validate()
    assert any("ReShade DLL not found" in item for item in problems), problems