# SPDX-License-Identifier: AGPL-3.0-only
"""角色立绘改成「显式下载」（2026-11-28 用户要求）。

用户原话：「不应该每次启动都连接，可以如果没下载就在角色 mod 那页上面提示一个
角色立绘未下载并提供一个下载按钮到下载页去下载」。

钉三件事：

① 进角色墙**不再**触发下载（一个网络请求都不发）；
② 缺口由 character_avatars.missing_avatars 算，下载页能看到 kind=avatars 的任务；
③ 任务结束后如实收尾（running=False + 一句结果），进度条不会永远转。
"""
from __future__ import annotations

import time
from pathlib import Path

from endfieldmodcontroller import character_avatars, character_sync, downloads
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        library_dir=str(tmp_path / "library"),
        runtime_dir=str(tmp_path / "runtime"),
        staging_mods_dir=str(tmp_path / "runtime" / "EFMI" / "Mods"),
    )


def _api(tmp_path: Path) -> EndfieldModControllerApi:
    config_path = tmp_path / "config.json"
    _config(tmp_path).save(config_path)
    return EndfieldModControllerApi(config_path)


def test_avatar_task_shape() -> None:
    task = downloads.normalize_avatar_task({"running": True, "total": 37, "done": 12})
    assert task["kind"] == downloads.KIND_AVATARS
    assert task["running"] is True
    assert round(task["percent"]) == 32

    finished = downloads.normalize_avatar_task(
        {"running": False, "total": 37, "done": 37, "message": "完成 37 张"})
    assert finished["percent"] == 100.0
    assert finished["message"] == "完成 37 张"
    assert finished["finished"] == 37
    assert downloads.normalize_avatar_task(None) is None


def test_gallery_never_starts_downloads(tmp_path: Path, monkeypatch) -> None:
    """★ 进角色墙只读本地缓存 —— 不该有任何下载动作。"""
    api = _api(tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("进角色墙时不该发起下载（用户：不应该每次启动都连接）")

    monkeypatch.setattr(character_avatars, "ensure_avatars", boom)
    monkeypatch.setattr(character_avatars, "download_avatars", boom)
    payload = api.character_gallery()
    assert payload["ok"] is True
    assert payload["pending"] == []
    assert isinstance(payload["avatar_missing"], int)


def test_missing_avatars_only_counts_missing_ones(tmp_path: Path, monkeypatch) -> None:
    urls = {"甲": "https://cdn/x/a.12345678.png", "乙": "https://cdn/x/b.87654321.png"}
    monkeypatch.setattr(character_sync, "avatar_map", lambda config: dict(urls))
    monkeypatch.setattr(character_avatars, "avatar_dir", lambda config: tmp_path)
    (tmp_path / "a.12345678.png").write_bytes(b"png")

    missing = character_avatars.missing_avatars(_config(tmp_path))
    assert missing == ["https://cdn/x/b.87654321.png"], "只报本地没有的那一张"


def test_download_task_finishes_with_a_message(tmp_path: Path, monkeypatch) -> None:
    api = _api(tmp_path)
    monkeypatch.setattr(character_avatars, "missing_avatars", lambda config: ["https://x/u.12345678.png"])
    monkeypatch.setattr(
        character_avatars, "download_avatars",
        lambda *args, **kwargs: {"total": 1, "done": 1, "failed": []})

    result = api.download_character_avatars()
    assert result["ok"] is True and result["started"] is True
    for _ in range(300):
        if not (api._avatar_task or {}).get("running"):
            break
        time.sleep(0.01)
    assert api._avatar_task["running"] is False
    assert "完成 1 张" in api._avatar_task["message"]


def test_download_task_is_rejected_when_nothing_missing(tmp_path: Path, monkeypatch) -> None:
    api = _api(tmp_path)
    monkeypatch.setattr(character_avatars, "missing_avatars", lambda config: [])
    result = api.download_character_avatars()
    assert result["ok"] is True and result["started"] is False
    assert api._avatar_task is None
