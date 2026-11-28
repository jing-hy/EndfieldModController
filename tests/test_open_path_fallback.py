# SPDX-License-Identifier: AGPL-3.0-only
"""「运行目录 → 打开」在目录还没生成时要退到上级，而不是只丢一句「路径不存在」。

现场（2026-11-28 用户反馈）：设置 → 路径 → 运行目录里点 Controller 的「打开」，弹
「路径不存在: …\\MC_Controller」。那个目录要**点过「生成控制器」**才存在，
首次使用 / 刚清空依赖时必然是空的 —— 打开入口不该因此失效。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import diagnostics
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def api(tmp_path: Path, monkeypatch) -> tuple[EndfieldModControllerApi, Path]:
    config_path = tmp_path / "config.json"
    config = AppConfig(
        library_dir=str(tmp_path / "library"),
        runtime_dir=str(tmp_path / "runtime"),
        staging_mods_dir=str(tmp_path / "runtime" / "EFMI" / "Mods"),
    )
    config.save(config_path)
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)

    opened: list[Path] = []

    def fake_open(_config, path):
        opened.append(Path(path))
        if Path(path).is_dir():
            return {"ok": True, "path": str(path)}
        return {"ok": False, "message": f"路径不存在: {path}"}

    monkeypatch.setattr(diagnostics, "open_path", fake_open)
    return EndfieldModControllerApi(config_path), tmp_path


def test_missing_controller_dir_falls_back_to_existing_parent(api) -> None:
    instance, root = api
    target = instance.config.controller_dir          # <runtime>/EFMI/Mods/MC_Controller（不存在）
    assert not target.exists()

    result = instance.open_path_in_explorer(str(target), True)

    assert result.get("ok") is True
    fallback = Path(str(result.get("fallback") or ""))
    assert fallback.is_dir()
    assert fallback in target.parents, "必须退到 target 的某个已存在上级"
    assert "已打开它的上级目录" in str(result.get("message") or "")


def test_without_fallback_it_still_reports_missing(api) -> None:
    instance, _root = api
    target = instance.config.controller_dir

    result = instance.open_path_in_explorer(str(target))

    assert result.get("ok") is False
    assert "路径不存在" in str(result.get("message") or "")


def test_existing_dir_is_opened_directly(api) -> None:
    instance, root = api
    target = root / "runtime"
    assert target.is_dir()

    result = instance.open_path_in_explorer(str(target), True)

    assert result.get("ok") is True
    assert "fallback" not in result
