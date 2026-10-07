"""下载中心：任务归一化、追加队列、旧接口兼容。

用户 2026-10-07 原话：「把下载从依赖里面抽出来，之前是所有下载跳转依赖的现在都跳转下载，
依赖也跳转下载，**下载可以后台进行，可以追加任务**，看商城不用下一个就跳转一次，
但是要有动态」。

这一组钉三件事：
① `downloads` 的归一化（Mod 队列 / 依赖任务读成同一形状，汇总口径一致）；
② **旧接口不破** —— `mod_download_progress` / `pause_mod_downloads` 那套前端与既有测试都在用，
   改造下载中心时它们必须一字不改地继续工作；
③ 控制接口对"不支持的任务类型"**如实拒绝**（不给点了没反应的假按钮）。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from endfieldmodcontroller import downloads


@pytest.fixture
def api(tmp_path):
    from endfieldmodcontroller import core
    from endfieldmodcontroller.api import EndfieldModControllerApi
    from endfieldmodcontroller.config import AppConfig

    library = tmp_path / "library"
    runtime = tmp_path / "runtime"
    staging = tmp_path / "staging"
    for path in (library, runtime, staging):
        path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.json"
    AppConfig(
        library_dir=str(library),
        runtime_dir=str(runtime),
        staging_mods_dir=str(staging),
        dependency_manifest=str(Path(core.__file__).parents[1] / "dependencies.json"),
    ).save(config_path)
    patcher = mock.patch.object(EndfieldModControllerApi, "game_running",
                                return_value={"running": False})
    patcher.start()
    instance = EndfieldModControllerApi(config_path)
    yield instance
    patcher.stop()


# ── 归一化 ───────────────────────────────────────────────────────────────────
def test_active_statuses_are_the_only_definition():
    """「还在跑」的状态集合**只有这一份**（以前 api 里硬编码了两遍，漏一处就出 bug）。"""
    assert downloads.ACTIVE_STATUSES == ("等待中", "读取香蕉网信息", "下载中", "解压中")
    for status in downloads.ACTIVE_STATUSES:
        assert downloads.is_active({"status": status}) is True
    for status in ("已入库", "需手动解压", "失败", "已暂停", "已终止", ""):
        assert downloads.is_active({"status": status}) is False


def test_mod_task_normalises_items_and_totals():
    mod_dl = {
        "items": [
            {"url": "u1", "name": "a.zip", "status": "已入库", "size": 100, "received": 100,
             "percent": 100, "speed_bps": 0, "cover_data": "data:image/jpeg;base64,AAA"},
            {"url": "u2", "name": "b.zip", "status": "下载中", "size": 300, "received": 150,
             "percent": 50, "speed_bps": 2048, "last_tick": 1.0},
        ],
        "done": False, "started_at": "2026-10-07 13:00:00", "dir": "D:\\x\\downloads",
        "pause": False, "cancel": False,
    }
    task = downloads.normalize_mod_task(mod_dl, downloads_dir="D:\\fallback")
    assert task["kind"] == downloads.KIND_MODS and task["running"] is True
    assert task["done_bytes"] == 250 and task["total_bytes"] == 400
    assert task["percent"] == 62.5
    assert task["speed_bps"] == 2048
    assert task["controls"] == ["pause", "resume", "cancel", "clear"]
    # `cover_data` 必须透出来：封面文件在收尾时会被删，不带它卡片就是空白
    assert task["items"][0]["cover_data"].startswith("data:image/jpeg")
    # 内部字段不该漏给前端
    assert "last_tick" not in task["items"][1]


def test_finished_mod_task_reads_as_complete():
    task = downloads.normalize_mod_task({"items": [{"url": "u", "status": "已入库", "size": 10,
                                          "received": 10}], "done": True})
    assert task["running"] is False and task["done"] is True
    assert task["percent"] == 100.0 and task["status"] == "已完成"


def test_empty_queue_is_idle_not_broken():
    task = downloads.normalize_mod_task({"items": [], "done": True})
    assert task["status"] == "空闲" and task["percent"] == 0.0


def test_dep_task_is_none_when_there_is_no_such_task():
    assert downloads.normalize_dep_task(None) is None
    assert downloads.normalize_dep_task({}) is None


def test_dep_task_shape_and_controls():
    task = downloads.normalize_dep_task({
        "running": True, "percent": 40.0, "byte_percent": 37.5, "computed_bytes": 1024,
        "expected_bytes": 4096, "speed_bps": 512.0, "message": "XXMI: 下载中",
        "log": ["a", "b"], "results": [{"ok": True}],
    })
    assert task["kind"] == downloads.KIND_DEPS and task["running"] is True
    assert task["byte_percent"] == 37.5 and task["done_bytes"] == 1024
    assert task["message"] == "XXMI: 下载中" and task["log"] == ["a", "b"]
    # 依赖任务目前**没有**暂停/终止 —— 如实不提供，而不是给个点了没反应的按钮
    assert task["controls"] == []


def test_snapshot_summarises_active_and_speed():
    payload = downloads.snapshot(
        mod_dl={"items": [{"url": "u", "status": "下载中", "size": 10, "received": 5,
                           "speed_bps": 100.0}], "done": False},
        dep_task={"running": True, "percent": 10.0, "speed_bps": 20.0, "log": ["x"]},
    )
    assert payload["active"] == 2
    assert payload["speed_bps"] == 120.0
    assert [task["kind"] for task in payload["tasks"]] == [downloads.KIND_MODS, downloads.KIND_DEPS]


def test_snapshot_hides_an_idle_dep_task():
    payload = downloads.snapshot(mod_dl={"items": [], "done": True}, dep_task=None)
    assert [task["kind"] for task in payload["tasks"]] == [downloads.KIND_MODS]


# ── api 层：旧接口必须原样活着 ───────────────────────────────────────────────
def test_legacy_mod_download_progress_shape_is_unchanged(api):
    """★ `mod_download_progress` 的返回结构是老契约（依赖页 / UpdateBadge / 既有测试都读它）。

    改下载中心时最容易"顺手把它换成新形状" —— 那会让依赖页的进度条与速度卡片直接空掉。
    """
    state = api.mod_download_progress()
    for key in ("ok", "items", "done", "counts", "dir", "started_at", "done_bytes",
                "total_bytes", "speed_bps", "policy", "threads", "accelerating", "last_report"):
        assert key in state, key
    assert state["counts"]["total"] == 0


def test_downloads_snapshot_and_active_count_agree(api):
    with api._mod_dl_lock:
        api._mod_dl = {
            "done": False, "cancel": False, "pause": False, "started_at": "t", "dir": "d",
            "items": [
                {"url": "u1", "status": "下载中", "size": 100, "received": 10, "speed_bps": 5.0},
                {"url": "u2", "status": "已入库", "size": 100, "received": 100},
            ],
        }
    payload = api.downloads_snapshot()
    assert payload["active"] == 1
    assert len(payload["tasks"][0]["items"]) == 2
    assert api.downloads_active_count()["active"] == 1
    assert api.downloads_active_count()["speed_bps"] == 5.0


def test_downloads_controls_route_to_the_mod_queue(api):
    assert api.downloads_pause(downloads.KIND_MODS)["ok"] is True
    with api._mod_dl_lock:
        assert api._mod_dl.get("pause") is True and api._mod_dl.get("cancel") is False
    assert api.downloads_resume(downloads.KIND_MODS)["ok"] is True
    with api._mod_dl_lock:
        assert api._mod_dl.get("pause") is False
    assert api.downloads_cancel(downloads.KIND_MODS)["ok"] is True
    with api._mod_dl_lock:
        assert api._mod_dl.get("cancel") is True


def test_downloads_controls_refuse_unsupported_kinds(api):
    """依赖任务不支持暂停/终止 ⇒ **如实拒绝**（前端据此不显示按钮）。"""
    for method in (api.downloads_pause, api.downloads_resume, api.downloads_cancel,
                   api.downloads_clear):
        result = method(downloads.KIND_DEPS)
        assert result["ok"] is False
        assert "不支持" in result["message"] or "只能" in result["message"]


def test_clear_refuses_while_items_are_active(api):
    with api._mod_dl_lock:
        api._mod_dl = {"done": False, "items": [{"url": "u", "status": "下载中"}],
                       "cancel": False, "pause": False}
    result = api.downloads_clear(downloads.KIND_MODS)
    assert result["ok"] is False and "在跑" in result["message"]


# ── 商城卡片上的「已安装」判据（谁能标、谁绝不能标）─────────────────────────
def _make_mod(library, name: str, *, download_info: dict | None = None) -> None:
    folder = library / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skin.ini").write_text("[TextureOverride]\nhash = 1234\n", encoding="utf-8")
    if download_info is not None:
        (folder / "download-info.json").write_text(
            json.dumps(download_info, ensure_ascii=False), encoding="utf-8")


def test_installed_mod_is_detected_from_the_old_download_info(api):
    """★ 老版本下载进来的 Mod **没有 `source_id`**（那个字段 2026-10-04 才写进
    `mod.meta.json`），但给人看的 `download-info.json` 里一直留着"页面"地址。

    商城卡片上的「已安装」靠它兜底 —— 否则老库永远标不出来（2026-10-07 实测踩到：
    先只认 meta，工作区那份库一个都匹配不上）。
    """
    _make_mod(api.config.library_path, "downloaded-mod", download_info={
        "下载时间": "2026-10-07 12:00:00",
        "页面": "https://gamebanana.com/mods/721442",
        "标题": "某个皮肤",
    })
    api._invalidate_mods()
    rows = api.mod_store_installed_list()
    assert [row["source_id"] for row in rows] == ["721442"]
    assert rows[0]["installed_at"] > 0            # 时间从「下载时间」解析出来
    assert api.mod_store_installed_map()["721442"]["id"]


def test_manual_mods_are_never_marked_installed(api):
    """手工放进库的 Mod（没有来源记录）**绝不猜** —— 标错等于告诉用户"网上有你装过的那个"，
    而他对不上号就会怀疑整个标记体系（同族教训：宁可不标，不要猜）。
    """
    _make_mod(api.config.library_path, "manual-mod")
    _make_mod(api.config.library_path, "manual-mod-2", download_info={
        "下载时间": "2026-10-07 12:00:00",
        "来源网址": "https://example.com/somewhere.zip",     # 不是香蕉网
    })
    api._invalidate_mods()
    assert api.mod_store_installed_list() == []

