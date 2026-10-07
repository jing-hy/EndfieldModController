"""`modstore`（Mod 商城数据层）—— **全离线**，网络一律打桩。

为什么这些判据值得单独钉住（2026-10-07 加）：

* 香蕉网 apiv11 **没有官方文档**，所有约束都是实测出来的，而且全是"看着像对的、
  一跑就 400"那种：`_nPerpage` 上限 50、**只有 Subfeed 认 `_sSort`**、
  `Mod/Categories` 不传 `_sSort`/`_nPerpage` 就回 `INPUT_ERRORS`、
  `Mod/<id>?_csvProperties=` 里**写错一个字段名整个请求 400**…… 这些坑没有测试兜着，
  就只能等用户撞上（本次开发中我已经踩了"分类端点少参数"和"跟着浅拷贝 extend"两个）。
* 商城对面是**外部站点**：判据（哪个字段算 NSFW、怎么算"有更新"）一旦改错，
  用户看到的是满屏错误标记，而这类错**不会自己暴露**。
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest import mock

from endfieldmodcontroller import modstore


def _body(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _record(**over) -> dict:
    """一条列表记录（字段照 2026-10-07 实测的真实响应写）。"""
    row = {
        "_idRow": 724708,
        "_sModelName": "Mod",
        "_sName": "Last Rite - Bunny Girl",
        "_sProfileUrl": "https://gamebanana.com/mods/724708",
        "_tsDateAdded": 1791274591,
        "_tsDateModified": 1791275250,
        "_bHasFiles": True,
        "_aPreviewMedia": {"_aImages": [{
            "_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
            "_sFile": "full.jpg",
            "_sFile220": "220-90_x.jpg",
            "_sFile530": "530-90_x.jpg",
        }]},
        "_aSubmitter": {"_sName": "BakaMai", "_sProfileUrl": "https://gamebanana.com/members/1"},
        "_aRootCategory": {"_sName": "Skins"},
        "_aSubCategory": {"_sName": "Last Rite"},
        "_sVersion": "1.5.1",
        "_sInitialVisibility": "warn",
        "_bHasContentRatings": True,
        "_nLikeCount": 50,
        "_nViewCount": 2556,
    }
    row.update(over)
    return row


class _FakeFetch:
    """记录每次请求的 URL，并按 URL 里的关键字返回预置响应。"""

    def __init__(self, routes=None, *, default=None):
        self.routes = routes or {}
        self.default = default
        self.calls: list[str] = []

    def __call__(self, url, **_kwargs):
        self.calls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return url, payload if isinstance(payload, bytes) else _body(payload)
        if isinstance(self.default, Exception):
            raise self.default
        return url, _body(self.default if self.default is not None else {})


def _install(monkeypatch, routes=None, *, default=None) -> _FakeFetch:
    from endfieldmodcontroller import fastnet

    fake = _FakeFetch(routes, default=default)
    monkeypatch.setattr(fastnet, "fetch", fake)
    # 免掉请求间隔（真实运行时是 200ms/次，测试里没必要等）
    monkeypatch.setattr(modstore, "_throttle", lambda: None)
    return fake


# ── 端点参数（全是"错了就 400"的硬约束）────────────────────────────────────
def test_index_page_size_is_clamped_to_the_server_limit(monkeypatch):
    """`_nPerpage` 上限 50 —— 实测 51/100/200 一律 400。"""
    fake = _install(monkeypatch, {"Mod/Index": {"_aMetadata": {"_nRecordCount": 1}, "_aRecords": []}})
    modstore.list_mods(page=1, per_page=999)
    assert "_nPerpage=50" in fake.calls[0]
    assert "_aFilters[Generic_Game]=21842" in fake.calls[0]


def test_index_never_sends_a_sort_parameter(monkeypatch):
    """`Mod/Index` **完全不支持排序** —— 实测 22 种 `_sSort` 全是 400。

    这个字段一旦被"顺手加上"，整个浏览页会直接打不开（每条请求都 400）。
    """
    fake = _install(monkeypatch, {"Mod/Index": {"_aMetadata": {"_nRecordCount": 0}, "_aRecords": []}})
    modstore.list_mods(page=2, per_page=50, category=35464)
    assert "_sSort" not in fake.calls[0]
    assert "_aFilters[Generic_Category]=35464" in fake.calls[0]
    assert "_nPage=2" in fake.calls[0]


def test_subfeed_filters_model_server_side(monkeypatch):
    """不加 `_csvModelInclusions=Mod` 会混进 Question/Tool（实测 1165 条里只有 707 个 Mod）。"""
    fake = _install(monkeypatch, {"Subfeed": {"_aMetadata": {"_nRecordCount": 707}, "_aRecords": []}})
    modstore.list_recent(page=1, sort="updated")
    assert "_csvModelInclusions=Mod" in fake.calls[0]
    assert "_sSort=updated" in fake.calls[0]


def test_subfeed_falls_back_to_a_legal_sort_value(monkeypatch):
    """`_sSort` 只认 new/updated/default —— 别的值直接 400，所以要就地纠正而不是原样发出去。"""
    fake = _install(monkeypatch, {"Subfeed": {"_aMetadata": {}, "_aRecords": []}})
    modstore.list_recent(page=1, sort="most_downloaded")
    assert "_sSort=new" in fake.calls[0]


def test_search_uses_game_row_not_filters(monkeypatch):
    """搜索限定游戏**只能用 `_idGameRow`** —— `_aFilters[Generic_Game]` 在这儿是无效的（实测）。"""
    fake = _install(monkeypatch, {"Util/Search": {"_aMetadata": {"_nRecordCount": 39}, "_aRecords": []}})
    modstore.search("chen qianyu")
    url = fake.calls[0]
    assert "_idGameRow=21842" in url
    assert "_aFilters" not in url
    assert "_sModelName=Mod" in url
    # `_csvFields` 决定"在哪些字段里匹配"（实测传 name 时命中数 41→34），必须带上
    assert "_csvFields=" in url


def test_search_rejects_empty_query_without_a_request(monkeypatch):
    """空 `_sSearchString` 会 400 —— 就地拒绝，别把无效请求发出去。"""
    fake = _install(monkeypatch)
    try:
        modstore.search("   ")
    except modstore.StoreBadRequest:
        pass
    else:                                     # pragma: no cover
        raise AssertionError("空搜索词应当直接拒绝")
    assert fake.calls == []


def test_categories_endpoint_needs_sort_and_perpage(monkeypatch):
    """★ 回归：`Mod/Categories` **必须带 `_sSort` 与 `_nPerpage`**。

    实测只传 `_idGameRow` 会回 `INPUT_ERRORS` —— 这是本模块开发时真踩到的第一个坑
    （探针一跑就现形）。分类树挂了 ⇒ 商城的两个筛选下拉全空。
    """
    roots = [{"_idRow": 35464, "_sName": "Skins", "_nItemCount": 654, "_nCategoryCount": 5}]
    children = [{"_idRow": 42770, "_sName": "Operators", "_nItemCount": 620, "_nCategoryCount": 32}]
    chars = [{"_idRow": 42735, "_sName": "Last Rite", "_nItemCount": 30, "_nCategoryCount": 0}]
    fake = _install(monkeypatch, {
        "_idCategoryRow=42770": chars,
        "_idCategoryRow=35464": children,
        "Mod/Categories": roots,
    })
    data = modstore.categories()
    assert len(fake.calls) == 3
    for url in fake.calls:
        assert "_sSort=a_to_z" in url
        assert "_nPerpage=50" in url
    assert [row["name"] for row in data["roots"]] == ["Skins"]
    assert [row["name"] for row in data["characters"]] == ["Last Rite"]


def test_categories_parses_a_bare_array(monkeypatch):
    """★ 分类端点返回的是**裸数组**（不是列表端点那种 `{_aMetadata,_aRecords}` 壳）。

    照列表解析器写会得到一堆空对象 —— 下拉框里全是空白项。
    """
    chars = [{"_idRow": 42735, "_sName": "Last Rite", "_nItemCount": 30, "_nCategoryCount": 0},
             {"_idRow": 42734, "_sName": "Empty Cat", "_nItemCount": 0, "_nCategoryCount": 0}]
    _install(monkeypatch, {
        "_idCategoryRow=42770": chars,
        "_idCategoryRow=35464": [{"_idRow": 42770, "_sName": "Operators", "_nItemCount": 620,
                                  "_nCategoryCount": 32}],
        "Mod/Categories": [{"_idRow": 35464, "_sName": "Skins", "_nItemCount": 654,
                            "_nCategoryCount": 5}],
    })
    data = modstore.categories()
    # 条目为 0 的分类不该出现在筛选器里（选了必然空白）
    assert [row["name"] for row in data["characters"]] == ["Last Rite"]


# ── 详情与字段白名单 ─────────────────────────────────────────────────────────
def test_bad_csv_property_falls_back_to_profile_page(monkeypatch):
    """`_csvProperties` 里**写错一个字段名 → 整个请求 400**（实测）。

    所以要有回退：退回全量 `/ProfilePage`（那条路不认这个参数，因此永远能用）。
    站内 Idea #7264 里另一个管理器作者踩的正是同一件事。
    """
    profile = {"_idRow": 684088, "_sName": "Gilberta", "_aFiles": [
        {"_idRow": 1839859, "_sFile": "a.zip", "_nFilesize": 100, "_sDownloadUrl":
         "https://gamebanana.com/dl/1839859", "_tsDateAdded": 5, "_sMd5Checksum": "abc"}]}
    fake = _install(monkeypatch, {
        "ProfilePage": profile,
        "_csvProperties": {"_sErrorCode": "INPUT_ERRORS"},
    })
    item = modstore.detail(684088)
    assert len(fake.calls) == 2
    assert "_csvProperties=" in fake.calls[0]
    assert fake.calls[1].endswith("/Mod/684088/ProfilePage")
    assert item["name"] == "Gilberta"
    assert item["files"][0]["url"] == "https://gamebanana.com/dl/1839859"


def test_detail_files_are_sorted_by_time_not_array_order(monkeypatch):
    """文件列表**不是按时间排的**，取最新必须排序（这条在下载链路上已经踩过一次）。"""
    profile = {"_idRow": 1, "_sName": "X", "_aFiles": [
        {"_idRow": 1, "_sFile": "old.zip", "_nFilesize": 10, "_tsDateAdded": 100,
         "_sDownloadUrl": "https://gamebanana.com/dl/1"},
        {"_idRow": 2, "_sFile": "new.zip", "_nFilesize": 20, "_tsDateAdded": 900,
         "_sDownloadUrl": "https://gamebanana.com/dl/2"},
    ]}
    _install(monkeypatch, {"ProfilePage": profile, "_csvProperties": {"_sErrorCode": "INPUT_ERRORS"}})
    item = modstore.detail(1)
    assert [row["name"] for row in item["files"]] == ["new.zip", "old.zip"]
    assert item["latest_file"]["name"] == "new.zip"


# ── 解析与判据 ───────────────────────────────────────────────────────────────
def test_normalize_reads_the_fields_we_actually_render():
    item = modstore.normalize(_record())
    assert item["id"] == 724708
    assert item["name"].startswith("Last Rite")
    assert item["author"] == "BakaMai"
    assert item["character"] == "Last Rite"
    assert item["root_category"] == "Skins"
    assert item["category_path"] == "Skins / Last Rite"
    # 列表用**小档**、详情用**大档** —— 2026-10-07 实测定的口径：这台机器到图片 CDN
    # 只有约 9 KB/s（530 档一张 56 KB 要 5.9 秒），而列表一屏十几张 ⇒ 必须小档 + 懒加载。
    assert item["thumb"].endswith("220-90_x.jpg")
    assert item["thumb_big"].endswith("530-90_x.jpg")
    assert item["nsfw"] is True
    assert item["likes"] == 50 and item["views"] == 2556


def test_subfeed_records_without_date_updated_fall_back_to_modified():
    """`Subfeed` / `Search` 的记录**没有 `_tsDateUpdated`**（只有 `Mod/Index` 有）——
    不兜底的话"最近更新"那一列会整列是 0。"""
    item = modstore.normalize(_record(_tsDateModified=1791275250))
    assert item["updated"] == 1791275250


def test_thumb_url_walks_the_size_fallback_chain():
    """不是每张图都有大尺寸（实测同一 Mod 的第 2、3 张只有 100px）⇒ 必须逐级退。"""
    assert modstore.thumb_url({"_sBaseUrl": "https://i/x", "_sFile530": "a.jpg"}).endswith("a.jpg")
    assert modstore.thumb_url({"_sBaseUrl": "https://i/x", "_sFile220": "b.jpg"}).endswith("b.jpg")
    assert modstore.thumb_url({"_sBaseUrl": "https://i/x", "_sFile100": "c.jpg"}).endswith("c.jpg")
    assert modstore.thumb_url({"_sBaseUrl": "https://i/x", "_sFile": "d.jpg"}).endswith("d.jpg")
    assert modstore.thumb_url({}) == ""


def test_nsfw_judgement_uses_visibility_or_content_rating():
    assert modstore.is_nsfw({"_sInitialVisibility": "hide"}) is True
    assert modstore.is_nsfw({"_bHasContentRatings": True}) is True
    assert modstore.is_nsfw({"_sInitialVisibility": "warn"}) is False
    assert modstore.is_nsfw({}) is False


def test_sort_items_supports_the_orders_the_server_refuses_to_give():
    """服务端**不给**点赞/浏览排行 ⇒ 本地排（`Mod/Index` 连 `_sSort` 都会 400）。"""
    rows = [{"name": "a", "likes": 1, "views": 90, "added": 3, "updated": 3},
            {"name": "b", "likes": 9, "views": 10, "added": 1, "updated": 9},
            {"name": "c", "likes": 5, "views": 50, "added": 2, "updated": 5}]
    assert [r["name"] for r in modstore.sort_items(rows, "likes")] == ["b", "c", "a"]
    assert [r["name"] for r in modstore.sort_items(rows, "views")] == ["a", "c", "b"]
    assert [r["name"] for r in modstore.sort_items(rows, "added")] == ["a", "c", "b"]
    assert [r["name"] for r in modstore.sort_items(rows, "updated")] == ["b", "c", "a"]


def test_parse_download_time_and_bad_values():
    ok = modstore.parse_download_time("2026-10-07 13:20:00")
    assert ok > 1_700_000_000
    assert modstore.parse_download_time("") == 0.0
    assert modstore.parse_download_time("昨天") == 0.0


# ── 更新判定（批量扫描的核心）───────────────────────────────────────────────
def test_compare_updates_splits_updated_current_and_missing():
    installed = [
        {"source_id": "111", "id": "m1", "name": "A", "folder": "f1", "installed_at": 1000.0},
        {"source_id": "222", "id": "m2", "name": "B", "folder": "f2", "installed_at": 5000.0},
        {"source_id": "333", "id": "m3", "name": "C", "folder": "f3", "installed_at": 100.0},
        {"source_id": "", "id": "m4", "name": "D", "folder": "f4", "installed_at": 100.0},
    ]
    index = [{"id": 111, "name": "A2", "updated": 2000, "url": "u1"},
             {"id": 222, "name": "B", "updated": 4000, "url": "u2"}]
    verdict = modstore.compare_updates(installed, index)
    assert [row["source_id"] for row in verdict["updates"]] == ["111"]
    assert [row["source_id"] for row in verdict["current"]] == ["222"]
    assert [row["source_id"] for row in verdict["missing"]] == ["333"]
    assert verdict["scanned"] == 4


def test_compare_updates_never_guesses_without_a_source_id():
    """手工放进库的 Mod 没有 `source_id` —— **绝不猜**（猜错会把用户自己的东西标成"网上有更新"）。"""
    verdict = modstore.compare_updates(
        [{"source_id": "", "id": "x", "name": "手工放的", "installed_at": 1.0}],
        [{"id": 999, "name": "看不出来是谁", "updated": 999999}])
    assert verdict["updates"] == [] and verdict["current"] == [] and verdict["missing"] == []


def test_compare_updates_treats_zero_installed_at_as_not_newer():
    """本地时间取不到（`installed_at=0`）时**不判有更新** —— 否则整库都会被标红。"""
    verdict = modstore.compare_updates(
        [{"source_id": "1", "id": "m", "name": "A", "installed_at": 0.0}],
        [{"id": 1, "name": "A", "updated": 1791275250}])
    assert verdict["updates"] == []
    assert [row["source_id"] for row in verdict["current"]] == ["1"]


# ── 缓存与失败降级 ───────────────────────────────────────────────────────────
def test_categories_fall_back_to_cache_when_unreachable(tmp_path):
    """拉不到分类时**静默回退上次缓存**（与 `alerts.load_document` 同一惯例）：
    断网/被墙不该让商城的筛选器整个消失。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    # 缓存要带 `STORE_SCHEMA`：分类树也做字段版本校验，不带就会被判成旧格式而**不回退**
    #（这正是 2026-10-07 加中文名时踩的那个坑 —— 索引改了、界面还是英文）。
    cached = {"schema": modstore.STORE_SCHEMA,
              "roots": [{"id": 35464, "name": "Skins", "count": 10}],
              "characters": [], "fetched_at": 1.0}
    path = modstore.categories_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")

    with mock.patch.object(modstore, "categories", side_effect=modstore.StoreUnreachable("断网")):
        data = modstore.load_categories(config, force=True)
    assert data["roots"][0]["name"] == "Skins"


def test_categories_cache_with_an_old_schema_is_not_used(tmp_path):
    """★ 同族回归：分类树缓存**版本对不上就不该当作可用**（否则界面会一直显示旧字段）。

    这里刻意让远程也失败 ⇒ 期望**如实抛错**，而不是拿一份口径过时的缓存糊弄过去
    （筛选器少个中文名是小事，用错字段渲染整页才是大事）。
    """
    config = SimpleNamespace(runtime_path=tmp_path)
    path = modstore.categories_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"roots": [{"id": 1, "name": "Skins", "count": 1}],
                                "characters": [], "fetched_at": time.time()},
                               ensure_ascii=False), encoding="utf-8")
    with mock.patch.object(modstore, "categories", side_effect=modstore.StoreUnreachable("断网")):
        try:
            modstore.load_categories(config, force=True)
        except modstore.StoreUnreachable:
            return
    raise AssertionError("旧 schema 的缓存不该被当成可用")      # pragma: no cover


def test_categories_raise_when_there_is_no_cache_and_no_network(tmp_path):
    """连缓存都没有时**如实抛错**（接口层据此给"检查 VPN"的提示），不要假装成功。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    with mock.patch.object(modstore, "categories", side_effect=modstore.StoreUnreachable("断网")):
        try:
            modstore.load_categories(config, force=True)
        except modstore.StoreUnreachable:
            return
    raise AssertionError("没有缓存时应当把不可达如实抛给上层")      # pragma: no cover


def test_build_index_does_not_fail_fast_on_a_bad_page(monkeypatch):
    """**不 fail-fast**（项目既定规则）：某一页失败就记下来继续，最后如实报哪几页没拿到。

    宁可索引不全，也不要因为第 7 页超时就整份丢弃（那样"浏览"整页都是空的）。
    """
    calls = {"n": 0}

    def flaky(page, per_page=modstore.PAGE_MAX, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise modstore.StoreUnreachable("这一页超时")
        rows = [_record(_idRow=1000 + calls["n"])]
        return {"items": [modstore.normalize(r) for r in rows], "total": 3,
                "page": page, "per_page": per_page, "source": "index"}

    monkeypatch.setattr(modstore, "list_mods", flaky)
    result = modstore.build_index(pages=3)
    assert result["failed_pages"] == [2]
    assert len(result["items"]) == 2          # 第 1、3 页的条目照样留下


def test_index_cache_is_used_when_refresh_fails(tmp_path):
    """索引刷新失败时用旧缓存，而不是把"浏览"清空。"""
    config = SimpleNamespace(runtime_path=tmp_path)
    path = modstore.index_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ 缓存必须带**当前 schema 版本号** —— `load_index` 用它判"这份缓存是不是旧口径的"
    #（见下面那条测试），不带就会被当成旧格式直接忽略。
    path.write_text(json.dumps({"schema": modstore.STORE_SCHEMA,
                                "items": [{"id": 1, "name": "旧数据"}],
                                "fetched_at": 0.0}, ensure_ascii=False), encoding="utf-8")
    with mock.patch.object(modstore, "build_index",
                           side_effect=modstore.StoreUnreachable("断网")):
        data = modstore.ensure_index(config, force=True)
    assert data["items"][0]["name"] == "旧数据"


def test_index_cache_with_an_old_schema_is_ignored(tmp_path):
    """★ 回归（2026-10-07 一天内踩了两次）：**归一化口径一变，旧索引缓存必须自动失效**。

    索引里存的是"归一化之后"的条目。这天先加了 `thumb_big`/`thumb_tiny`（图片分档），
    又加了 `character_zh`（角色名中文）—— 两次都出现同一个症状：磁盘上的索引文件完全正常，
    前端却拿到旧字段，看起来像"代码改了、界面没变"，极难往缓存上想。
    判据：**schema 对不上就当没有缓存**（`STORE_SCHEMA` 每次动 `normalize()` 的字段就 +1）。
    """
    config = SimpleNamespace(runtime_path=tmp_path)
    path = modstore.index_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 老的：没有 schema 字段（或版本落后）
    path.write_text(json.dumps({"items": [{"id": 1, "name": "老格式"}], "fetched_at": 0.0},
                               ensure_ascii=False), encoding="utf-8")
    assert modstore.load_index(config) == {}
    path.write_text(json.dumps({"schema": modstore.STORE_SCHEMA - 1,
                                "items": [{"id": 1, "name": "上一版"}],
                                "fetched_at": 0.0}, ensure_ascii=False), encoding="utf-8")
    assert modstore.load_index(config) == {}
    # 版本对得上才认
    path.write_text(json.dumps({"schema": modstore.STORE_SCHEMA,
                                "items": [{"id": 1, "name": "当前版"}],
                                "fetched_at": 0.0}, ensure_ascii=False), encoding="utf-8")
    assert modstore.load_index(config)["items"][0]["name"] == "当前版"
