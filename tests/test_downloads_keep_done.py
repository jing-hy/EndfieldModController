# SPDX-License-Identifier: AGPL-3.0-only
"""下载页「本次已入库」：没重启就不许清零（2026-11-28 用户要求）。

现场：`start_mod_download` 在上一批 `done=True` 时**重建** `_mod_dl`（items=[]），
于是下一批开始时把已入库的项整份丢掉 —— 下载页的「本次已入库」变 0、「已下载」卡片消失。
修法：只重置批次标志，items 保留（重启才清空）。
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


def _api(tmp_path: Path) -> EndfieldModControllerApi:
    config_path = tmp_path / "config.json"
    config = AppConfig(
        library_dir=str(tmp_path / "library"),
        runtime_dir=str(tmp_path / "runtime"),
        staging_mods_dir=str(tmp_path / "runtime" / "EFMI" / "Mods"),
    )
    config.save(config_path)
    return EndfieldModControllerApi(config_path)


def test_new_batch_keeps_previous_done_items(tmp_path: Path, monkeypatch) -> None:
    api = _api(tmp_path)
    api._mod_dl = {
        "done": True, "cancel": False, "pause": False,
        "started_at": "2026-11-28 13:00:00", "dir": str(tmp_path),
        "items": [{"url": "http://x/old.zip", "origin_url": "http://x/old.zip",
                   "name": "old.zip", "status": "已入库", "size": 10, "received": 10}],
    }
    # 不起真实下载线程：只验证队列重置逻辑
    api._mod_download_worker = types.MethodType(lambda self: None, api)

    result = api.start_mod_download("http://example.com/new.zip")

    assert result.get("ok") is True
    items = api._mod_dl.get("items") or []
    statuses = [str(item.get("status") or "") for item in items]
    assert "已入库" in statuses, "新一批开始时把上次已入库的项清掉了"
    assert any("new.zip" in str(item.get("name") or "") for item in items)
    assert api._mod_dl.get("done") is False


def test_fresh_queue_still_initialises(tmp_path: Path, monkeypatch) -> None:
    api = _api(tmp_path)
    api._mod_download_worker = types.MethodType(lambda self: None, api)

    assert api.start_mod_download("http://example.com/first.zip").get("ok") is True
    items = api._mod_dl.get("items") or []
    assert len(items) == 1 and items[0]["status"] == "等待中"