# SPDX-License-Identifier: GPL-3.0-or-later
"""Mod 商城：**分类数字必须与列表同源**、**残缺索引不许让 Mod 消失**（2026-11-07 修）。

用户实测两条：
 ①「mod商城分类显示的数字和右上角的不符」—— 点「皮肤」时标签写 744，右上角/列表只有 666；
 ②「分类中展示的 mod 与实际显示不符，前一小时还在的 mod 现在消失了」。

根因（两条都对得上）：
 ① **两个数据源**：数字取站点 Mod/Categories 的 _nItemCount（分类树缓存 7 天），
    列表取本地索引（缓存 1 天、刷新失败还会更旧）—— 时间点不同，数字必然对不上；
 ② ensure_index 把"这次只拿到一半"的**残缺结果原样覆盖**了完整缓存，
    而且无论成功/失败/残缺都写"索引就绪" ⇒ 用户看到的就是"Mod 凭空消失、界面还说一切正常"。

修法（这些测试逐条钉住）：
 ① 数字改由 category_counts() 从**列表用的那份索引**里数，标签上的数 == 点进去的条数；
 ② 每页失败先重试；仍残缺就**与旧缓存按 id 合并**、标 complete=False、10 分钟后自动重试，
    并在状态行如实写"不完整（719/796）"。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from endfieldmodcontroller import alerts, character_sync, filewatch, sbm_data_sync, selfupdate
from endfieldmodcontroller import api as api_mod
from endfieldmodcontroller import moddl, modstore
# 预热线程的全局桩在 tests/conftest.py（对所有测试生效，避免后台线程跨用例污染）


def _item(mod_id, root, character, *, nsfw=False, updated=1000):
    return {"id": mod_id, "name": "m" + str(mod_id), "root_category": root,
            "character": character, "nsfw": nsfw, "updated": updated}


def _payload(items, total=0, failed_pages=None, complete=None):
    return {"items": list(items), "total": total or len(items),
            "failed_pages": list(failed_pages or []),
            "complete": (not (failed_pages or [])) if complete is None else bool(complete),
            "fetched_at": time.time()}


def _write_index(config, items, *, total=None, complete=True, fetched_at=None):
    path = modstore.index_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": modstore.STORE_SCHEMA,
        "items": list(items),
        "total": int(total if total is not None else len(items)),
        "complete": bool(complete),
        "fetched_at": float(time.time() if fetched_at is None else fetched_at),
    }, ensure_ascii=False), encoding="utf-8")


def _api(tmp_path) -> api_mod.EndfieldModControllerApi:
    root = Path(tmp_path)
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "library").mkdir(parents=True, exist_ok=True)
    cfg = root / "config.json"
    cfg.write_text(json.dumps({"data_root": "", "runtime_dir": "runtime",
                               "library_dir": "library"}, ensure_ascii=False), encoding="utf-8")
    return api_mod.EndfieldModControllerApi(str(cfg))


# ── ① 分类数字 == 点进去看到的条数 ──────────────────────────────────────────
def test_category_counts_equal_what_the_filter_returns():
    """分类/角色的数字必须**等于**用它筛选出来的条数（本次修复的核心判据）。"""
    items = [
        _item(1, "Skins", "Chen Qianyu"),
        _item(2, "Skins", "Chen Qianyu", nsfw=True),
        _item(3, "Skins", "Last Rite"),
        _item(4, "UI", ""),
        _item(5, "Other/Misc", ""),
    ]
    counts = modstore.category_counts(items)
    assert counts["total"] == len(items)
    assert sum(counts["roots"].values()) == counts["total"]

    for cat_id, name in moddl.GAMEBANANA_ROOT_CATEGORIES.items():
        got = api_mod.EndfieldModControllerApi._store_filter(items, category=cat_id)
        assert len(got) == counts["roots"].get(name, 0), name + " 的数字与筛选结果不符"

    for character, number in counts["characters"].items():
        got = api_mod.EndfieldModControllerApi._store_filter(items, character=character)
        assert len(got) == number, character + " 的数字与筛选结果不符"


def test_category_counts_follow_the_nsfw_hide_mode():
    """R18 选「隐藏」时数字也要跟着少 —— 否则又变成"写着 N 个、点进去只有 N 减 R18"。"""
    items = [_item(1, "Skins", "A"), _item(2, "Skins", "A", nsfw=True),
             _item(3, "Skins", "B", nsfw=True)]
    counts = modstore.category_counts(items, nsfw="hide")
    assert counts["total"] == 1
    assert counts["roots"]["Skins"] == 1
    assert counts["characters"]["A"] == 1
    assert "B" not in counts["characters"]


def test_list_payload_category_counts_match_the_list_total(tmp_path):
    """接口层：右上角总数、点分类后的条数、分类标签上的数字**三者相等**（用户看到的那三处）。"""
    inst = _api(tmp_path)
    items = [
        _item(1, "Skins", "Chen Qianyu"),
        _item(2, "Skins", "Chen Qianyu"),
        _item(3, "Skins", "Last Rite"),
        _item(4, "UI", ""),
        _item(5, "Other/Misc", ""),
    ]
    _write_index(inst.config, items)

    payload = inst.mod_store_list({"per_page": 24})
    assert payload["ok"] and payload["source"] == "index"
    assert payload["total"] == len(items)
    assert payload["counts"]["total"] == payload["total"]          # 全部 == 右上角
    assert payload["index"]["complete"] is True

    skins = moddl.GAMEBANANA_ROOT_CATEGORIES[35464]
    filtered = inst.mod_store_list({"per_page": 24, "category": 35464})
    assert filtered["total"] == payload["counts"]["roots"][skins]   # 皮肤标签 == 点进去的条数

    by_character = inst.mod_store_list({"per_page": 24, "character": "Chen Qianyu"})
    assert by_character["total"] == payload["counts"]["characters"]["Chen Qianyu"]


def test_categories_endpoint_uses_index_counts(tmp_path, monkeypatch):
    """分类接口也不再信站点的 _nItemCount（那是另一份 7 天缓存）—— 以索引为准。"""
    inst = _api(tmp_path)
    _write_index(inst.config, [
        _item(1, "Skins", "Chen Qianyu"),
        _item(2, "Skins", "Last Rite"),
    ])
    site = {
        "schema": modstore.STORE_SCHEMA,
        "roots": [{"id": 35464, "name": "Skins", "count": 744},
                  {"id": 42780, "name": "Other/Misc", "count": 27}],
        "characters": [{"id": 42721, "name": "Chen Qianyu", "count": 31}],
        "fetched_at": time.time(),
    }
    monkeypatch.setattr(modstore, "load_categories", lambda *a, **k: site)
    payload = inst.mod_store_categories()
    assert payload["ok"] and payload["counts_source"] == "index"
    assert {row["name"]: row["count"] for row in payload["roots"]} == {
        "Skins": 2, "Other/Misc": 0}                     # 索引里没有的就如实报 0
    assert payload["characters"][0]["count"] == 1
    # 站点那份原始数字不许再冒充"分类实际条数"
    assert payload["counts"]["roots"]["Skins"] == 2


# ── ② 残缺刷新不许让 Mod 消失 ───────────────────────────────────────────────
def test_build_index_retries_a_transient_page_failure(monkeypatch):
    """线路抖一下（单页失败一次）⇒ 重试后拿全，不算残缺、不丢条目。"""
    state = {"page2": 0}

    def flaky(page, per_page=modstore.PAGE_MAX, **kwargs):
        if page == 2:
            state["page2"] += 1
            if state["page2"] == 1:
                raise modstore.StoreUnreachable("抖了一下")
        return {"items": [{"id": page}], "total": 3, "page": page,
                "per_page": per_page, "source": "index"}

    monkeypatch.setattr(modstore, "list_mods", flaky)
    monkeypatch.setattr(modstore.time, "sleep", lambda *_: None)
    result = modstore.build_index()
    assert result["failed_pages"] == []
    assert result["complete"] is True
    assert len(result["items"]) == 3


def test_incomplete_refresh_keeps_items_that_were_already_cached(tmp_path):
    """⭐ 核心回归：刷新只拿到一部分时，用旧缓存把缺的条目**补回来**（不许让 Mod 消失）。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    _write_index(config, [{"id": 1, "name": "old-1"}, {"id": 2, "name": "old-2"}], total=5)
    with mock.patch.object(modstore, "build_index",
                           return_value=_payload([{"id": 3, "name": "new-3"}],
                                                 total=5, failed_pages=[2])):
        data = modstore.ensure_index(config, force=True)
    assert sorted(int(item["id"]) for item in data["items"]) == [1, 2, 3]
    assert data["complete"] is False
    assert data["reused"] == 2
    saved = modstore.load_index(config)
    assert sorted(int(item["id"]) for item in saved["items"]) == [1, 2, 3]


def test_complete_refresh_drops_items_removed_from_the_site(tmp_path):
    """完整刷新时**不合并**：站点上真下架的条目该跟着消失（否则会越攒越多）。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    _write_index(config, [{"id": 1}, {"id": 2}], total=2)
    with mock.patch.object(modstore, "build_index",
                           return_value=_payload([{"id": 2}, {"id": 3}], total=2, complete=True)):
        data = modstore.ensure_index(config, force=True)
    assert sorted(int(item["id"]) for item in data["items"]) == [2, 3]
    assert data["complete"] is True
    assert data["reused"] == 0


def test_incomplete_index_is_retried_before_the_normal_ttl(tmp_path):
    """残缺索引 10 分钟后就能再试；完整索引仍按一天算（别每次都重拉十几页）。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    stale_at = time.time() - (modstore.INDEX_INCOMPLETE_RETRY_SECONDS + 60)
    calls = {"n": 0}

    def fake_build(**kwargs):
        calls["n"] += 1
        return _payload([{"id": 1}], total=1, complete=True)

    def write(complete):
        _write_index(config, [{"id": 1}], total=1, complete=complete, fetched_at=stale_at)

    with mock.patch.object(modstore, "build_index", fake_build):
        write(complete=False)
        modstore.ensure_index(config)          # 残缺 + 11 分钟前 ⇒ 重建
        assert calls["n"] == 1
        write(complete=True)
        modstore.ensure_index(config)          # 完整 + 11 分钟前 ⇒ 不重建（TTL 一天）
        assert calls["n"] == 1


def test_index_status_message_is_honest():
    """状态行必须说清"残缺 / 用的旧索引"，不许一律报"索引就绪"。"""
    cls = api_mod.EndfieldModControllerApi
    incomplete = {"items": 719, "total": 796, "complete": False, "reused": 77,
                  "failed_pages": [15], "age": 0.0}
    message = cls._store_index_message({}, incomplete)
    assert "不完整" in message and "719/796" in message and "77" in message

    ready = {"items": 796, "total": 796, "complete": True, "reused": 0,
             "failed_pages": [], "age": 0.0}
    assert "索引就绪" in cls._store_index_message({}, ready)

    stale = dict(ready, age=3 * 86400)
    message = cls._store_index_message({"reused_cache": True}, stale)
    assert "刷新失败" in message and "3 天前" in message

# ── ④ 增量刷新：只拉最上面几页（2026-11-07 追加要求）────────────────────────
def test_head_refresh_merges_only_the_top_pages(tmp_path, monkeypatch):
    """顶部增量刷新：新条目并入、老条目一条不丢、更新的字段以这次为准。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    _write_index(config, [{"id": 1, "name": "old-1"}, {"id": 2, "name": "old-2"},
                          {"id": 3, "name": "old-3"}], total=3, fetched_at=111.0)

    def fake_list(page, per_page=modstore.PAGE_MAX, **kwargs):
        rows = {1: [{"id": 2, "name": "updated-2"}, {"id": 4, "name": "new-4"}],
                2: [{"id": 5, "name": "new-5"}]}[page]
        return {"items": rows, "total": 5, "page": page,
                "per_page": per_page, "source": "index"}

    monkeypatch.setattr(modstore, "list_mods", fake_list)
    result = modstore.head_refresh(config, pages=2)
    assert result["ok"] is True and result["added"] == 2

    saved = modstore.load_index(config)
    assert sorted(int(item["id"]) for item in saved["items"]) == [1, 2, 3, 4, 5]
    # 全量刷新时间**不许**被顶部刷新改掉（否则就永远不再全量核对了）
    assert saved["fetched_at"] == 111.0
    assert saved["head_at"] > 0
    assert next(item for item in saved["items"] if int(item["id"]) == 2)["name"] == "updated-2"


def test_head_refresh_needs_a_full_index_first(tmp_path):
    config = SimpleNamespace(runtime_path=tmp_path)
    result = modstore.head_refresh(config)
    assert result["ok"] is False and result["need_full"] is True


def test_head_refresh_stands_down_while_a_full_build_is_running(tmp_path):
    """全量构建持锁时顶部刷新必须让开（别两个线程读-改-写同一份缓存）。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    _write_index(config, [{"id": 1}], total=1)
    assert modstore._INDEX_LOCK.acquire(blocking=False)
    try:
        result = modstore.head_refresh(config)
    finally:
        modstore._INDEX_LOCK.release()
    assert result["ok"] is False and result["busy"] is True


def test_ensure_index_returns_the_cache_when_another_refresh_holds_the_lock(tmp_path):
    config = SimpleNamespace(runtime_path=tmp_path)
    _write_index(config, [{"id": 1}], total=1, fetched_at=0.0)
    assert modstore._INDEX_LOCK.acquire(blocking=False)
    try:
        data = modstore.ensure_index(config, force=True)
    finally:
        modstore._INDEX_LOCK.release()
    assert data["busy"] is True
    assert data["items"][0]["id"] == 1


def test_api_head_refresh_returns_counts(tmp_path, monkeypatch):
    """接口层：顶部刷新要带回与列表同源的计数（R18 隐藏时一起少）。"""
    inst = _api(tmp_path)
    _write_index(inst.config, [_item(1, "Skins", "Chen Qianyu")])

    def fake_list(page, per_page=modstore.PAGE_MAX, **kwargs):
        return {"items": [_item(2, "Skins", "Chen Qianyu", nsfw=True)], "total": 2,
                "page": page, "per_page": per_page, "source": "index"}

    monkeypatch.setattr(modstore, "list_mods", fake_list)
    monkeypatch.setattr(api_mod.launcher, "_append_log", lambda cfg, line: None)
    result = inst.mod_store_head_refresh("hide")
    assert result["ok"] is True and result["added"] == 1
    assert result["counts"]["total"] == 1        # 隐藏 R18 ⇒ 只算没标 R18 的那条
    assert result["index"]["items"] == 2

# ── ③ 开机就自动刷新索引（2026-11-07 追加要求）──────────────────────────────
def test_prefetch_starts_a_task_for_a_stale_index(tmp_path, monkeypatch):
    """索引过期 ⇒ 进商城页/开机预热都会发起后台任务，进度走同一条状态行。"""
    inst = _api(tmp_path)
    _write_index(inst.config, [{"id": 1}], total=1, fetched_at=time.time() - 3 * 86400)
    monkeypatch.setattr(
        api_mod.EndfieldModControllerApi, "_store_index",
        lambda self, **kwargs: {"items": [{"id": 1}], "total": 1, "complete": True,
                                "failed_pages": [], "fetched_at": time.time()})
    result = inst.mod_store_prefetch()
    assert result["ok"] and result["started"]
    status = inst.mod_store_task_status()
    for _ in range(100):
        status = inst.mod_store_task_status()
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["kind"] == "index"
    assert "索引就绪" in status["message"]


def test_prefetch_does_nothing_when_the_index_is_fresh(tmp_path):
    inst = _api(tmp_path)
    _write_index(inst.config, [{"id": 1}], total=1, fetched_at=time.time())
    result = inst.mod_store_prefetch()
    assert result.get("cached") is True
    assert inst.mod_store_task_status()["running"] is False


def test_warm_up_store_index_logs_what_it_did(tmp_path, monkeypatch):
    """预热里的日志要让人看得出"这次刷了/没刷、为什么"。"""
    inst = _api(tmp_path)
    lines: list[str] = []
    monkeypatch.setattr(api_mod.launcher, "_append_log", lambda cfg, line: lines.append(line))

    monkeypatch.setattr(inst, "mod_store_prefetch", lambda: {"ok": True, "started": True})
    inst._warm_up_store_index()
    assert "自动刷新已开始" in lines[-1]

    monkeypatch.setattr(inst, "mod_store_prefetch",
                        lambda: {"ok": True, "cached": True, "age": 7200, "total": 796})
    inst._warm_up_store_index()
    assert "本次不刷新" in lines[-1] and "2 小时前" in lines[-1]


def test_warm_up_calls_the_store_index_refresh(tmp_path, monkeypatch):
    """⭐ 用户要求：**点开管理器就开始刷新**，不必先进商城页。

    只加个方法不接进预热线程等于没做，所以这里把整段预热真跑一遍。
    """
    inst = _api(tmp_path)
    calls: list[int] = []
    monkeypatch.setattr(inst, "_mods", lambda: [])
    monkeypatch.setattr(inst, "_ui_ready",
                        SimpleNamespace(wait=lambda timeout=0: True, set=lambda: None))
    monkeypatch.setattr(inst.config, "autofill", lambda **kwargs: False)
    monkeypatch.setattr(selfupdate, "cleanup_stale", lambda cfg: [])
    monkeypatch.setattr(character_sync, "sync", lambda cfg, **kwargs: {})
    monkeypatch.setattr(sbm_data_sync, "sync", lambda cfg, **kwargs: {})
    monkeypatch.setattr(inst, "_backup_new_mods", lambda **kwargs: {})
    monkeypatch.setattr(alerts, "overview", lambda cfg, **kwargs: {})
    monkeypatch.setattr(filewatch, "scan", lambda cfg, **kwargs: {})
    monkeypatch.setattr(inst, "_warm_up_store_index", lambda: calls.append(1))
    inst._warm_up()
    assert calls == [1]