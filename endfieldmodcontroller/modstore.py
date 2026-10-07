"""Mod 商城（GameBanana / 香蕉网）：浏览、搜索、分类、更新判定。

用户 2026-10-07 原话：「我希望加入 mod 商城功能，可以看看 jasm 是怎么做的，
然后匹配现在 emc 的 ui 和接入下载功能」+「mod 批量扫描、一键更新」。

**这个模块只管"看到什么"**：列表 / 搜索 / 分类树 / 详情元数据 / 缩略图 / 更新判定。
"下载什么、怎么下"仍然全在 `moddl`（真实文件直链、按最新更新记录选文件）与
`api.start_mod_download()`（并行下载 → 解压入库 → 角色识别）里 —— 一行都不重写。

## 为什么只走 apiv11（不抓网页）

香蕉网的 Mod 页面是**前端渲染**的，HTML 里没有下载地址；而 `apiv11/*` 一次就把
名称、作者、封面、分类、文件直链给全。JASM（同类成熟项目）也是这么做的 ——
全项目 grep 不到任何 HTML 解析库。这是"读思路不抄代码"的那类借鉴。

## 三个列表端点各有硬约束（2026-10-07 逐条实测，别照直觉改）

* `Mod/Index`  —— **唯一能翻大页**的（`_nPerpage` 上限 50），而且**完全不支持排序**
  （`_sSort` 试了 22 个值一律 400，`_sOrder` 被静默忽略），也不能搜索；
* `Game/<gid>/Subfeed` —— **唯一能排序**的（`_sSort` 只认 new/updated/default），
  但每页**固定 15**（官方 Admin 在 bug 4905 里明说 "This was intentional"），
  且不加 `_csvModelInclusions=Mod` 会混进 Question/Tool（1165 条里只有 707 个 Mod）；
* `Util/Search/Results` —— 搜索专用，限定游戏**只能用 `_idGameRow`**
  （`_aFilters[Generic_Game]` 在这儿无效），`_sSearchString` 必填（空值 400），每页固定 15。

⇒ 结论直接决定了商城的分页策略：**浏览用 Mod/Index 拉全量（707 条 ≈ 15 页）落本地缓存，
排序/筛选在本地做**；"最新/最近更新"用 Subfeed；关键词用 Search。

## 合规（照香蕉网 ToS 的边界来）

ToS 没有禁止自动化访问、robots.txt 也没有 Disallow，但站方保留了
"**restrict, suspend, or terminate your access … for any or no reason**" 的权利，
而且取到的每个 Mod 还可能自带 `CC BY-NC-ND`（禁止再分发）。所以这里：
① **只拿元数据与链接、绝不镜像/重分发文件**（文件永远实时从 `dl/<fileId>` 拉）；
② 自报身份的 UA + 请求串行且间隔 ≥200ms（实测站点无任何速率头 ⇒ 只能保守）；
③ 卡片上必须显示作者与来源页链接（对外那层在 UI 里做）。
"""
from __future__ import annotations

import datetime
import os
import posixpath
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# ── 端点与常量（全部来自 2026-10-07 实测）────────────────────────────────────
BASE_URL = "https://gamebanana.com/apiv11/"
ENDFIELD_GAME_ID = 21842

#: `Mod/Index` 的每页上限 —— 实测 51 直接 400（`_nPerpage cannot exceed 50`）。
PAGE_MAX = 50
#: `Subfeed` / `Search` 的每页固定值 —— 服务端写死，传什么都被忽略。
SUBFEED_PER_PAGE = 15

REQUEST_TIMEOUT = 20
#: 两次请求之间的最小间隔（秒）。站点实测没有任何速率限制头，只能自己保守。
REQUEST_INTERVAL = 0.2

INDEX_TTL_SECONDS = 24 * 3600          # 全量索引：一天一次足够
CATEGORIES_TTL_SECONDS = 7 * 24 * 3600  # 分类树（角色名单）：一周一次

#: 商城**缓存字段版本号**（全量索引与分类树共用）。
#:
#: ⚠️ 归一化口径一变（加字段、换档位），磁盘上的旧缓存就会让新前端读到旧字段 ——
#: 表现是"代码改了、界面没变"，而缓存文件本身完全正常，极难往缓存上想。
#: 2026-10-07 一天内连踩三次（先加 `thumb_big`、再加 `thumb_tiny`、最后加 `character_zh`，
#: 第三次才发现分类树**也有自己的缓存**）。所以：**每次动 `normalize()` 或分类树字段就 +1**。
STORE_SCHEMA = 1

#: NSFW 判据：`Mod/Index` 与 `Subfeed` 都带 `_sInitialVisibility`；实测 "hide" 就是被
#: 站点标为内容分级的那批（JASM 用同一条判据）。`_bHasContentRatings` 是它的旁证。
NSFW_VISIBILITY = "hide"

#: 根分类 id（与 `moddl.GAMEBANANA_ROOT_CATEGORIES` 同一份口径，别各写一套）。
SKINS_CATEGORY_ID = 35464
OPERATORS_CATEGORY_ID = 42770

#: `Mod/<id>?_csvProperties=…` 的**字段白名单**。
#:
#: ⚠️⚠️ 实测：**字段名写错会让整个请求 400**（没有"忽略未知字段"这种宽容），
#: 所以只能拼这一份实测确认过的；要加字段必须先真打一次请求验证，
#: 并做好"某个字段哪天变非法 ⇒ 整个详情接口挂掉"的回退（见 `detail()`）。
CSV_PROPERTIES: tuple[str, ...] = (
    "_idRow", "_sName", "_sProfileUrl", "_sText", "_sDescription", "_sVersion",
    "_nLikeCount", "_nViewCount", "_nPostCount", "_nDownloadCount",
    "_tsDateAdded", "_tsDateModified", "_tsDateUpdated", "_bIsObsolete",
    "_aCategory", "_aSuperCategory", "_aSubmitter", "_aGame", "_aFiles",
    "_aPreviewMedia", "_sLicense",
)

#: 缩略图尺寸降级链 —— 不是每张图都有全部尺寸（实测同一 Mod 的第 2、3 张截图
#: 只有 `_sFile100`），所以必须逐级退，全没有才回退原图。
THUMB_KEYS: tuple[str, ...] = ("_sFile530", "_sFile220", "_sFile100")

Progress = Callable[[str], None] | None
Cancel = Callable[[], bool] | None


class StoreUnreachable(RuntimeError):
    """访问不上香蕉网（超时 / DNS / 证书 / 地区限制）—— 调用方据此提示"检查 VPN"。"""


class StoreBadRequest(RuntimeError):
    """服务端明确回了参数错误（`_sErrorCode`）。

    **这一条不该重试** —— 参数非法重试多少次都一样；正确的反应是去掉可疑参数
    （例如把 `_sSort` 拿掉、把 `_nPerpage` 夹到 50）再来一次。
    """


# ── 请求层 ───────────────────────────────────────────────────────────────────
_throttle_lock = threading.Lock()
_last_request_at = 0.0


def user_agent() -> str:
    """自报身份的 UA（站点在 Cloudflare 后面，伪装浏览器既没必要也不礼貌）。"""
    try:
        from .version import USER_AGENT

        return f"{USER_AGENT} (+https://github.com/jing-hy/EndfieldModController)"
    except Exception:  # noqa: BLE001 —— 版本模块出问题时不该让商城整体不可用
        return "EndfieldModController (+https://github.com/jing-hy/EndfieldModController)"


def _throttle() -> None:
    """串行 + 最小间隔：站点没有公开配额，唯一的办法是自己慢一点。"""
    global _last_request_at

    with _throttle_lock:
        now = time.monotonic()
        wait = REQUEST_INTERVAL - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _get(url: str, *, timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None) -> Any:
    """取一个 apiv11 端点并解析 JSON（列表端点给 `{_aMetadata,_aRecords}`，分类端点给**裸数组**）。

    `tolerate_error_status=True` 是**故意的**：香蕉网在 400 时会带一段 JSON 正文
    （实测 `{"_sErrorCode": "INPUT_ERRORS", "_aErrorData": {...}}`），带上它我们才能
    把"参数写错了"与"网线断了"分开 —— 前者重试一万次也没用。
    """
    from . import fastnet, fsutil

    _throttle()
    try:
        _final, body = fastnet.fetch(
            url,
            headers={"Accept": "application/json", "User-Agent": user_agent()},
            timeout=timeout,
            cancel=cancel,
            tolerate_error_status=True,
        )
    except fastnet.Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 —— 网络层各种异常统一成"访问不上"
        raise StoreUnreachable(str(exc)) from exc

    try:
        data = fsutil.loads_tolerant(body.decode("utf-8", "replace"))
    except ValueError as exc:
        raise StoreUnreachable(f"返回的不是有效数据：{exc}") from exc

    if isinstance(data, dict) and data.get("_sErrorCode"):
        raise StoreBadRequest(f"{data.get('_sErrorCode')}（{url}）")
    return data


def _url(path: str, params: dict[str, Any]) -> str:
    """拼端点 URL。

    ⚠️ `_aFilters[Generic_Game]` 的方括号**不做 URL 编码**：实测编码与不编码都能用，
    但保持原样更贴近站点自己的文档/示例，也便于对着日志肉眼核对。
    """
    query = "&".join(
        f"{key}={urllib.parse.quote(str(value), safe='[],')}"
        for key, value in params.items() if value not in (None, "")
    )
    return f"{BASE_URL}{path}" + (f"?{query}" if query else "")


def _records(data: Any) -> list[dict]:
    """从列表端点响应里取记录数组（**分类端点返回裸数组**，所以两种都要认）。"""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("_aRecords")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _meta_count(data: Any) -> int:
    if isinstance(data, dict):
        try:
            return int((data.get("_aMetadata") or {}).get("_nRecordCount") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


# ── 归一化 ───────────────────────────────────────────────────────────────────
def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _name_of(value: Any) -> str:
    return str((value or {}).get("_sName") or "").strip() if isinstance(value, dict) else ""


def preview_image(raw: dict) -> dict:
    """取第一张预览图（可能就是封面）。返回原始 dict，交给 `thumb_url()` 挑尺寸。"""
    images = ((raw or {}).get("_aPreviewMedia") or {}).get("_aImages") or []
    for image in images:
        if isinstance(image, dict) and (image.get("_sBaseUrl") or "").strip():
            return image
    return {}


def thumb_url(image: dict, prefer: Sequence[str] = THUMB_KEYS) -> str:
    """按降级链拼缩略图 URL；全都没有才回退原图（实测确有这种图）。"""
    base = str((image or {}).get("_sBaseUrl") or "").strip().rstrip("/")
    if not base:
        return ""
    for key in tuple(prefer) + ("_sFile",):
        name = str(image.get(key) or "").strip()
        if name:
            return f"{base}/{name}"
    return ""


def is_nsfw(raw: dict) -> bool:
    """内容分级判据：`_sInitialVisibility == "hide"`（JASM 用同一条）。

    `_bHasContentRatings` 作为旁证 —— 列表里两个字段都有，所以**不需要额外请求**。
    注意这是"标出来给用户看"的信息，不是"过滤掉"的依据（本程序用户的库里本来就有 18+）。
    """
    if not isinstance(raw, dict):
        return False
    if str(raw.get("_sInitialVisibility") or "").strip().lower() == NSFW_VISIBILITY:
        return True
    return bool(raw.get("_bHasContentRatings"))


# ── 角色名中文化 ─────────────────────────────────────────────────────────────
#: 根分类的中文名（只有三个、站点也不常改，所以直接映射；角色则一律查表）
ROOT_NAMES_ZH = {"Skins": "皮肤", "UI": "界面", "Other/Misc": "其它"}

_CHARACTER_CACHE: dict[str, str] | None = None


def _norm_name(value: Any) -> str:
    """归一化到"只有小写字母数字"，用来做跨来源的名字比对（空格/连字符/点都不算）。"""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _character_table() -> dict[str, str]:
    """英文别名 → 中文官方名 的查表。

    直接复用 `core.character_alias_pairs()` —— 那是**下载入库时识别角色用的同一份表**
    （`characters.json` 的 name/codename/aliases，别名里还带拼音）。自己再解析一遍
    `characters.json` 就等于养第二份真相，两边迟早对不上。
    """
    global _CHARACTER_CACHE

    if _CHARACTER_CACHE is None:
        from . import core

        table: dict[str, str] = {}
        for alias, canonical in core.character_alias_pairs():
            key = _norm_name(alias)
            if key:
                table.setdefault(key, canonical)
        _CHARACTER_CACHE = table
    return _CHARACTER_CACHE


def chinese_character(name: str) -> str:
    """香蕉网的英文角色名 → **中文显示名**（用户 2026-10-07：「角色列表我需要中文」）。

    ⚠️ 括号后缀要单独处理：香蕉网把男女管理员拆成两个分类（`Endministrator (F)` /
    `Endministrator (M)`），而我们的表里只有一个「管理员」—— 直接归一化会匹配不上
    （实测 32 个里正好差这两个）。

    **对不上就原样返回**：宁可显示英文，也不猜 —— 猜错会让人以为筛选器坏了。
    """
    text = str(name or "").strip()
    if not text:
        return ""
    suffix = ""
    match = re.search(r"\(([^)]*)\)", text)
    if match:
        suffix = match.group(1).strip().upper()
        text = f"{text[:match.start()]} {text[match.end():]}".strip()
    zh = _character_table().get(_norm_name(text))
    if not zh:
        return str(name)
    if suffix in ("F", "M"):
        zh = f"{zh}（{'女' if suffix == 'F' else '男'}）"
    return zh


def normalize(raw: dict) -> dict:
    """把列表记录归一化成界面直接可用的形状（三个端点的字段差异在这里抹平）。"""
    image = preview_image(raw)
    root = _name_of(raw.get("_aRootCategory"))
    sub = _name_of(raw.get("_aSubCategory"))
    added = _int(raw.get("_tsDateAdded"))
    # ⚠️ `Mod/Index` 有 `_tsDateUpdated`，`Subfeed` / `Search` **没有** —— 用 modified 兜底，
    #    否则"最近更新"排序在最新页签下会整列是 0。
    updated = _int(raw.get("_tsDateUpdated")) or _int(raw.get("_tsDateModified"))
    mod_id = _int(raw.get("_idRow"))
    return {
        "id": mod_id,
        "model": str(raw.get("_sModelName") or "Mod"),
        "name": str(raw.get("_sName") or "").strip(),
        "url": str(raw.get("_sProfileUrl") or f"https://gamebanana.com/mods/{mod_id}"),
        "author": _name_of(raw.get("_aSubmitter")),
        "author_url": str((raw.get("_aSubmitter") or {}).get("_sProfileUrl") or "")
        if isinstance(raw.get("_aSubmitter"), dict) else "",
        "added": added,
        "updated": updated,
        "likes": _int(raw.get("_nLikeCount")),
        "views": _int(raw.get("_nViewCount")),
        "posts": _int(raw.get("_nPostCount")),
        "version": str(raw.get("_sVersion") or "").strip(),
        "root_category": root,
        "root_category_zh": ROOT_NAMES_ZH.get(root, root),
        "character": sub,
        "character_zh": chinese_character(sub),
        "category_path": " / ".join(part for part in (root, sub) if part),
        "category_path_zh": " / ".join(
            part for part in (ROOT_NAMES_ZH.get(root, root), chinese_character(sub)) if part),
        "has_files": bool(raw.get("_bHasFiles")),
        "obsolete": bool(raw.get("_bIsObsolete")),
        "nsfw": is_nsfw(raw),
        # ⚠️ **列表用小档、详情才用大档**（2026-10-07 实测定的口径）：
        # 这台机器到 `images.gamebanana.com` 只有约 **9 KB/s**（530 档 56 KB 要 5.9 秒一张、
        # 800 档 10.4 秒），而列表一屏就是十几张 —— 用大档等于打开商城先等一分多钟。
        # 小档 220（13.5 KB）配"只加载视口内的图"，首屏才秒级；点开详情再换大档（用户主动等）。
        "thumb": thumb_url(image, ("_sFile220", "_sFile100", "_sFile")),
        "thumb_big": thumb_url(image, ("_sFile530", "_sFile800", "_sFile")),
        # 100 档（3.9 KB）单独留一份：在 9 KB/s 的网速下它约 1~2 秒就能到，
        # 先用它把格子填上、再把 220 档换进来 —— 用户看到的是"图很快出现、然后变清晰"。
        "thumb_tiny": thumb_url(image, ("_sFile100", "_sFile220", "_sFile")),
        # 原始记录留着：详情弹窗、更新判定、将来加字段都不用再打一次请求。
        "raw": raw,
    }


# ── 三个列表端点 ─────────────────────────────────────────────────────────────
def list_mods(page: int = 1, per_page: int = PAGE_MAX, category: int = 0,
              *, timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None) -> dict:
    """按游戏（可再按分类）翻页 —— 商城的"浏览全部"。

    ⚠️ **不支持排序**：实测 `_sSort` 传任何值都 400、`_sOrder` 被静默忽略
    （返回顺序与不加时逐字节相同）。所以排序一律在本地做（见 `sort_items`）。
    """
    per_page = max(1, min(int(per_page or PAGE_MAX), PAGE_MAX))
    params: dict[str, Any] = {
        "_nPage": max(1, int(page or 1)),
        "_nPerpage": per_page,
        "_aFilters[Generic_Game]": ENDFIELD_GAME_ID,
    }
    if category:
        params["_aFilters[Generic_Category]"] = int(category)
    data = _get(_url("Mod/Index", params), timeout=timeout, cancel=cancel)
    return {
        "items": [normalize(row) for row in _records(data)],
        "total": _meta_count(data),
        "page": max(1, int(page or 1)),
        "per_page": per_page,
        "source": "index",
    }


def list_recent(page: int = 1, sort: str = "new",
                *, timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None) -> dict:
    """最新 / 最近更新 —— **唯一能排序**的端点（每页固定 15，传什么都改不了）。"""
    sort = sort if sort in ("new", "updated", "default") else "new"
    data = _get(
        _url(f"Game/{ENDFIELD_GAME_ID}/Subfeed", {
            "_nPage": max(1, int(page or 1)),
            "_csvModelInclusions": "Mod",   # 不加这句会混进 Question / Tool（实测 1165 vs 707）
            "_sSort": sort,
        }),
        timeout=timeout, cancel=cancel)
    return {
        "items": [normalize(row) for row in _records(data)],
        "total": _meta_count(data),
        "page": max(1, int(page or 1)),
        "per_page": SUBFEED_PER_PAGE,
        "source": f"subfeed:{sort}",
    }


def search(query: str, order: str = "best_match", page: int = 1,
           *, timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None) -> dict:
    """关键词搜索。

    * 限定游戏**只能用 `_idGameRow`**（实测 `_aFilters[Generic_Game]` 在这儿无效，结果不变）；
    * `_sOrder` 只认 best_match / popularity / date / udate，别的值直接 400；
    * `_sSearchString` 必填（空值 400）—— 所以调用方要先判空。
    """
    text = str(query or "").strip()
    if not text:
        raise StoreBadRequest("搜索词不能为空")
    order = order if order in ("best_match", "popularity", "date", "udate") else "best_match"
    data = _get(
        _url("Util/Search/Results", {
            "_sSearchString": text,
            "_sModelName": "Mod",
            "_sOrder": order,
            "_nPage": max(1, int(page or 1)),
            "_idGameRow": ENDFIELD_GAME_ID,
            # 实测：`_csvFields` 决定"在哪些字段里匹配"（传 name 时命中数 41→34），
            # 所以照抄社区实现（pybanana）的默认值，否则会漏结果。
            "_csvFields": "name,description,article,attribs,studio,owner,credits",
        }),
        timeout=timeout, cancel=cancel)
    return {
        "items": [normalize(row) for row in _records(data)],
        "total": _meta_count(data),
        "page": max(1, int(page or 1)),
        "per_page": SUBFEED_PER_PAGE,
        "source": f"search:{order}",
    }


def sort_items(items: Iterable[dict], key: str = "updated") -> list[dict]:
    """本地排序 —— 服务端只给"最新/最近更新"，点赞/浏览排行只能自己排。"""
    rows = list(items)
    if key == "likes":
        return sorted(rows, key=lambda item: item.get("likes") or 0, reverse=True)
    if key == "views":
        return sorted(rows, key=lambda item: item.get("views") or 0, reverse=True)
    if key == "added":
        return sorted(rows, key=lambda item: item.get("added") or 0, reverse=True)
    return sorted(rows, key=lambda item: item.get("updated") or item.get("added") or 0,
                  reverse=True)


# ── 分类树（根分类 + 角色名单）───────────────────────────────────────────────
def _category_row(row: dict, *, with_sub: bool = False) -> dict:
    """分类记录 → 界面用的形状（`Mod/Categories` 的字段与列表端点**完全不同**）。"""
    item = {
        "id": _int(row.get("_idRow")),
        "name": _name_of(row),
        "count": _int(row.get("_nItemCount")),
    }
    if with_sub:
        item["sub"] = _int(row.get("_nCategoryCount"))
    return item


def _category_page(params: dict, *, timeout: int, cancel: Cancel) -> list[dict]:
    """拉一页分类（不够 50 条就说明到底了）。

    ⚠️ 实测（第一版就踩到、探针一跑现形）：`Mod/Categories` **必须带 `_sSort` 与
    `_nPerpage`** —— 只传 `_idGameRow` 会回 `INPUT_ERRORS`。`_nPerpage` 同样受 50 上限，
    所以这里按"返回条数不足一页"判结束，而不是依赖站点给总数（它返回的是裸数组，没有 `_aMetadata`）。
    """
    rows: list[dict] = []
    for page in range(1, 4):        # 实测角色 32 个（50/页够）；留 3 页余量，不硬编码条数
        data = _get(_url("Mod/Categories", {
            **params, "_sSort": "a_to_z", "_nPerpage": PAGE_MAX, "_nPage": page,
        }), timeout=timeout, cancel=cancel)
        batch = _records(data)
        rows.extend(batch)
        if len(batch) < PAGE_MAX:
            break
    return rows


def categories_path(config: Any) -> Path:
    return Path(config.runtime_path) / "_state" / "modstore_categories.json"


def categories(*, timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None) -> dict:
    """根分类 + 角色名单（商城的两个下拉框）。

    ⚠️ `Mod/Categories` 返回的是**裸数组**（不是列表端点那种 `{_aMetadata,_aRecords}` 壳）——
    实测踩过：照列表解析器写会得到一堆空对象。

    角色的取法（照 JASM 的启发式）：顶级 → 取条目最多的那个（Skins）→ 它的子分类里
    再挑还有下层的（Operators）→ 再下一层就是角色（实测 32 个，带 `_nItemCount`）。
    不硬编码任何角色 id：新角色是站点数据增长出来的，硬编码必然过期。
    """
    roots = [{**_category_row(row), "name_zh": ROOT_NAMES_ZH.get(_name_of(row), _name_of(row))}
             for row in _category_page({"_idGameRow": ENDFIELD_GAME_ID},
                                       timeout=timeout, cancel=cancel)]
    children = [_category_row(row, with_sub=True)
                for row in _category_page({"_idCategoryRow": SKINS_CATEGORY_ID, "_bShowEmpty": "true"},
                                          timeout=timeout, cancel=cancel)]
    group_id = next((row["id"] for row in children
                     if row["sub"] > 0 and row["id"] == OPERATORS_CATEGORY_ID),
                    next((row["id"] for row in sorted(children, key=lambda r: r["count"], reverse=True)
                          if row["sub"] > 0), 0))
    characters: list[dict] = []
    if group_id:
        characters = [
            # `name` 保留香蕉网原文（后端筛选用的就是它），`name_zh` 给界面显示
            {**_category_row(row), "id": _int(row.get("_idRow")),
             "name_zh": chinese_character(_name_of(row))}
            for row in _category_page({"_idCategoryRow": group_id, "_bShowEmpty": "true"},
                                      timeout=timeout, cancel=cancel)
            if _int(row.get("_nItemCount")) > 0
        ]
    return {
        "schema": STORE_SCHEMA,
        "roots": roots,
        # 排序仍按**英文名**（站点原文）：中文名要另查拼音表，而英文名本身稳定，
        # 排出来对用户一样是有序的。
        "characters": sorted(characters, key=lambda row: row["name"].lower()),
        "fetched_at": time.time(),
    }


def load_categories(config: Any, *, ttl: int = CATEGORIES_TTL_SECONDS,
                    force: bool = False, timeout: int = REQUEST_TIMEOUT,
                    cancel: Cancel = None, log: Callable[[str], None] | None = None) -> dict:
    """分类树（带缓存 + 失败静默回退，与 `alerts.load_document` 同一惯例）。

    ⚠️ 缓存**也要比 `STORE_SCHEMA`**：分类树有自己的缓存文件，字段口径同样会变
    （2026-10-07 给角色加 `name_zh` 中文名时就漏了它 —— 索引那边改了、界面却还是英文，
    因为读的是分类树的旧缓存）。
    """
    from . import fsutil

    cached = fsutil.read_json(categories_path(config))
    fresh = (bool(cached.get("roots"))
             and int(cached.get("schema") or 0) == STORE_SCHEMA
             and (time.time() - float(cached.get("fetched_at") or 0)) < ttl)
    if fresh and not force:
        return cached
    try:
        data = categories(timeout=timeout, cancel=cancel)
    except Exception as exc:  # noqa: BLE001 —— 拿不到分类不该让整个商城不可用
        if cached.get("roots") and int(cached.get("schema") or 0) == STORE_SCHEMA:
            _log(log, f"商城：分类树拉取失败，先用上次缓存（{exc}）")
            return cached
        raise
    try:
        fsutil.write_json(categories_path(config), data)
    except OSError as exc:  # noqa: BLE001 —— 缓存写不进去不影响本次使用
        _log(log, f"商城：分类树缓存写入失败（{exc}）")
    return data


# ── 详情 ─────────────────────────────────────────────────────────────────────
def detail(mod_id: int, *, timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None) -> dict:
    """单个 Mod 的详情（含完整文件列表）。

    走 `Mod/<id>?_csvProperties=…`：实测比 `/ProfilePage` 小一个量级
    （0.7~4.9 KB vs 14.5 KB）。⚠️ 白名单里的字段名若哪天变成非法，整个请求会 400
    ⇒ 这里**回退到全量 `/ProfilePage`**（那条路不认 `_csvProperties`，因此永远可用）。
    """
    try:
        data = _get(_url(f"Mod/{int(mod_id)}", {"_csvProperties": ",".join(CSV_PROPERTIES)}),
                    timeout=timeout, cancel=cancel)
    except StoreBadRequest:
        # 字段白名单漂移（站内 Idea #7264 就是别人踩到的同一件事）——退回全量接口。
        data = _get(BASE_URL + f"Mod/{int(mod_id)}/ProfilePage", timeout=timeout, cancel=cancel)
    if not isinstance(data, dict):
        raise StoreUnreachable("详情返回的不是对象")

    files: list[dict] = []
    for entry in data.get("_aFiles") or []:
        if not isinstance(entry, dict):
            continue
        link = str(entry.get("_sDownloadUrl") or "")
        if not link:
            continue
        files.append({
            "id": _int(entry.get("_idRow")),
            "name": str(entry.get("_sFile") or ""),
            "size": _int(entry.get("_nFilesize")),
            "added": _int(entry.get("_tsDateAdded")),
            "downloads": _int(entry.get("_nDownloadCount")),
            "url": link,
            "md5": str(entry.get("_sMd5Checksum") or ""),
            "version": str(entry.get("_sVersion") or ""),
            "archived": bool(entry.get("_bIsArchived")),
            "av": str(entry.get("_sAvResult") or ""),
        })
    files.sort(key=lambda row: row["added"], reverse=True)

    # ── 全部预览图（详情页要横向铺开，用户 2026-10-07：「预览图要更多」）────────
    # 每条给三档：`full`=原图（灯箱）、`big`=800/530（大图）、`thumb`=530/220/100（列表）。
    # ⚠️ 各尺寸都可能缺（实测同一 Mod 的第 2、3 张截图只有 100px 那档）⇒ 逐级回退。
    images: list[dict] = []
    for image in ((data.get("_aPreviewMedia") or {}).get("_aImages") or []):
        if not isinstance(image, dict):
            continue
        base = str(image.get("_sBaseUrl") or "").strip().rstrip("/")
        if not base or not str(image.get("_sFile") or "").strip():
            continue

        def _pick(*keys: str) -> str:
            for key in keys:
                name = str(image.get(key) or "").strip()
                if name:
                    return f"{base}/{name}"
            return ""

        images.append({
            "full": f"{base}/{str(image.get('_sFile')).strip()}",
            "big": _pick("_sFile800", "_sFile530", "_sFile"),
            "thumb": _pick("_sFile530", "_sFile220", "_sFile100", "_sFile"),
        })

    item = normalize(data)
    item.update({
        "description": _plain_text(data.get("_sText") or ""),
        "summary": str(data.get("_sDescription") or "").strip(),
        "downloads": _int(data.get("_nDownloadCount")),
        "license": _plain_text(data.get("_sLicense") or "", limit=160),
        "files": files,
        "latest_file": files[0] if files else None,
        "images": images,
    })
    return item


def _plain_text(value: str, limit: int = 600) -> str:
    """把详情里的 HTML 压成可显示的一行文本（与 `moddl._plain_text` 同一口径）。"""
    import html as _html
    import re

    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.I)
    text = re.sub(r"</(?:p|li|ul|div|h\d)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()[:limit]


# ── 图片：本地只读服务 + 原样缓存 ────────────────────────────────────────────
#: 降级用（本地服务起不来时走 data URI）的默认解码宽度。
#:
#: ⚠️ 正常路径**不再缩放**：站点自己就给了 530/800 两档（`_sFile530` / `_sFile800`），
#: 直接原样存盘最清晰也最省 CPU。曾经按 220 解码再显示在 320px 的框里 —— 那就是用户
#: 2026-10-07 看到的「图片清晰度太低」。
THUMB_WIDTH = 360
PREVIEW_WIDTH = 800


def thumb_root(config: Any) -> Path:
    return Path(config.runtime_path) / "cache" / "modstore" / "thumbs"


def thumb_path(config: Any, url: str) -> Path:
    """图片缓存文件（**按源 URL 哈希**命名，存的是站点给的**原图字节**）。

    用 URL 做键（不是 mod id）：详情页一个 Mod 有多张预览图，用 id 会互相覆盖；
    不同尺寸档（530 / 800）本身就是不同 URL，天然分开存。
    """
    import hashlib

    digest = hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:16]
    return thumb_root(config) / f"{digest}.jpg"


class ThumbServer:
    """本地**只读**图片服务：只服务 `runtime/cache/modstore/thumbs`，绑 `127.0.0.1` + 随机端口。

    为什么需要它（2026-10-07 用户：「缩略图还是模糊而且**速度太慢**」）：
    WebView2 里 `file://` 读本地图片会被拦，于是原先只能把每张图 base64 成 data URI、
    经 pywebview 的桥**一张一张传**过去 —— 一页 24 张就是约 3 MB 字符串注入 + 24 次跨语言
    往返；为了压体积还只能把图缩到 220px，显示在 320px 的框里就是放大的糊图。
    改成让 WebView2 **按 URL 自己取图**后：并发、磁盘缓存、解码都归浏览器管，
    后端只负责把文件放好 —— 又快又清晰（用的就是站点原图）。

    护栏：只绑回环地址、只读、只认"哈希.jpg"这种文件名（`../` 一律挡掉）、
    daemon 线程随进程退出；**起不来就返回 0**，调用方回退到 data URI 老路。
    """

    def __init__(self) -> None:
        self._httpd: Any = None
        self._thread: threading.Thread | None = None
        self._port = 0
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        return self._port

    def ensure(self, root: Path) -> int:
        """起服务（幂等）；返回端口；失败返回 0。"""
        with self._lock:
            if self._httpd is not None:
                return self._port
            try:
                import http.server

                root.mkdir(parents=True, exist_ok=True)

                class _Handler(http.server.SimpleHTTPRequestHandler):
                    def __init__(self, *args: Any, **kwargs: Any) -> None:
                        super().__init__(*args, directory=str(root), **kwargs)

                    def log_message(self, *args: Any) -> None:   # 本项目没有控制台，别刷日志
                        return

                    def end_headers(self) -> None:
                        # 显式给缓存头：WebView2 对"没有 Cache-Control"的响应会用启发式缓存，
                        # 切页回来可能重新请求 —— 这些图按 URL 命名、内容不变，直接长缓存。
                        self.send_header("Cache-Control", "public, max-age=86400")
                        super().end_headers()

                    def translate_path(self, path: str) -> str:
                        # 只认 `<16 位 hex>.jpg` —— `../` 之类一律落到一个不存在的名字上。
                        name = posixpath.basename(urllib.parse.urlsplit(path).path)
                        if not re.fullmatch(r"[0-9a-f]{16}\.jpg", name):
                            return str(root / "__forbidden__")
                        return str(root / name)

                self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
                self._port = int(self._httpd.server_address[1])
                self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True,
                                                name="mc-thumbs")
                self._thread.start()
            except Exception:  # noqa: BLE001 —— 起不来就走降级，绝不让商城打不开
                self._httpd = None
                self._port = 0
            return self._port


#: 进程内单例（端口只分配一次）
_SERVER = ThumbServer()

#: 每线程一条到图片 CDN 的**长连接**（见 `_image_get`）。
_IMAGE_LOCAL = threading.local()


def _image_get(url: str, *, timeout: int = 20, attempts: int = 2) -> bytes:
    """取一张图 —— **复用连接**，这台机器上最关键的一处优化。

    ⚠️ 2026-10-07 实测（推翻了我当天先前的"带宽只有 9 KB/s"判断）：图片慢的**主因不是带宽，
    而是每张图都重建 TCP+TLS** —— 新建连接的首张 TTFB **2.58 秒**（其中 TLS 握手 1.43 秒），
    而同一条连接上的第 2~4 张只要 **0.28~0.55 秒**（快 5~9 倍）。

    所以这里按 host 维护"**每线程一条长连接**"（`http.client` 的连接不是线程安全的，
    用 `threading.local()` 天然隔离）。连接被对端掐掉时丢掉重来一次 —— 这条域实测会
    **间歇性完全不通**（同一 URL 前一刻 1.9 秒成功、后一刻 30 秒超时），所以超时与重试都要有。
    """
    import http.client

    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    pool: dict[str, Any] = getattr(_IMAGE_LOCAL, "pool", None)
    if pool is None:
        pool = {}
        _IMAGE_LOCAL.pool = pool

    last: Exception | None = None
    for _attempt in range(max(1, attempts)):
        conn = pool.get(host)
        try:
            if conn is None:
                conn = http.client.HTTPSConnection(host, timeout=timeout)
                pool[host] = conn
            conn.request("GET", path,
                         headers={"User-Agent": user_agent(), "Accept": "image/*"})
            response = conn.getresponse()
            blob = response.read()
            if response.status != 200:
                raise OSError(f"HTTP {response.status}")
            if not blob:
                raise OSError("空响应")
            return blob
        except Exception as exc:  # noqa: BLE001 —— 连接坏了（对端关闭/超时）就丢掉重来
            last = exc
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
            pool.pop(host, None)
    raise OSError(f"取图失败：{last}")


def prepare_images(config: Any, urls: Iterable[str], *, timeout: int = 20,
                   workers: int = 3, log: Callable[[str], None] | None = None) -> dict:
    """确保这批图都在本地，并返回**可以直接交给 `<img src>` 的本地 URL**。

    * 已缓存的图不再下载（缓存按 URL 哈希，命中就是本地读）；
    * 缺的图**并发下载**，但并发数**刻意开小**（3 路）。

    ⚠️ 并发为什么是 3 而不是 8（2026-10-07 实测踩到）：这台机器到图片 CDN 的**总吞吐**
    只有约 **9 KB/s**。开 8 路时带宽被切成 8 份 ⇒ 每张 13.5 KB 的小图都要 12 秒以上，
    直接撞上超时 ⇒ **整页图片全部失败**（实测 15 张全灭）。改成 3 路后每张约 4~5 秒能收完；
    超时也从 10 秒放宽到 20 秒 —— 在小带宽下"多开几路"只会让每路一起饿死。
    * 单张失败**不中断其它**（项目既定规则：批量不 fail-fast），失败项如实回报。

    返回 `{"base": "http://127.0.0.1:<port>", "files": {源URL: 文件名}, "failed": [源URL]}`；
    本地服务起不来时 `base` 为空字符串，调用方据此回退到 data URI。
    """
    from concurrent.futures import ThreadPoolExecutor

    wanted = [str(url).strip() for url in urls if str(url or "").strip()]
    port = _SERVER.ensure(thumb_root(config))
    if not port:
        return {"base": "", "files": {}, "failed": wanted}

    files: dict[str, str] = {}
    pending: list[str] = []
    for url in wanted:
        path = thumb_path(config, url)
        if path.is_file():
            files[url] = path.name
        else:
            pending.append(url)

    failed: list[str] = []

    def _fetch(url: str) -> None:
        """取一张图（走 `_image_get`：**同一条线程复用一条连接**）。

        ⚠️ 两点都是实测定下来的：
        ① **不要走 `fastnet`**（`dependencies._http_get`）—— 那是给几十 MB 安装包准备的
           线路预检/分块决策，套在小图上代价极高；
        ② **必须复用连接** —— 新建连接的 TLS 握手就要 1.4 秒，而同一连接上的后续图
           只要 0.3~0.5 秒（见 `_image_get`）。
        """
        path = thumb_path(config, url)
        tmp = path.with_name(path.name + ".part")
        try:
            blob = _image_get(url, timeout=timeout)
            tmp.write_bytes(blob)
            os.replace(tmp, path)          # 原子落位：不留半张图当缓存
            files[url] = path.name
        except Exception as exc:  # noqa: BLE001 —— 一张图失败不影响整页
            for leftover in (tmp, path):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass
            failed.append(url)
            _log(log, f"商城：图片下载失败（{exc}）")

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pending)))) as pool:
            list(pool.map(_fetch, pending))

    return {"base": f"http://127.0.0.1:{port}", "files": files, "failed": failed}


def scan_path(config: Any) -> Path:
    """批量扫描（库里已装的 Mod 有没有新版）的结果落盘处 —— 换页/重启后还能看到上次结论。"""
    return Path(config.runtime_path) / "_state" / "modstore_updates.json"


# ── 全量索引（本地排序 / 批量更新扫描都靠它）─────────────────────────────────
def index_path(config: Any) -> Path:
    return Path(config.runtime_path) / "_state" / "modstore_index.json"


def load_index(config: Any) -> dict:
    """读本地索引（读不到/坏了当空 —— 状态文件坏了只该导致"这次当没有"）。

    ⚠️ **还要比对字段版本号**（`STORE_SCHEMA`）：索引里存的是**归一化之后**的条目，
    口径一变旧缓存就会让新前端读到旧字段 —— 表现是"代码改了、界面没变"。
    对不上就当没有缓存，下次自动重建。
    """
    from . import fsutil

    data = fsutil.read_json(index_path(config))
    if data.get("items") and int(data.get("schema") or 0) != STORE_SCHEMA:
        return {}
    return data


def index_age(config: Any) -> float:
    return time.time() - float(load_index(config).get("fetched_at") or 0)


def build_index(*, pages: int = 0, per_page: int = PAGE_MAX,
                timeout: int = REQUEST_TIMEOUT, cancel: Cancel = None,
                progress: Progress = None, log: Callable[[str], None] | None = None) -> dict:
    """把所有 Mod 拉一遍（707 条 = 15 页 × 50）。

    **不 fail-fast**（项目既定规则）：某一页失败就重试，重试完仍失败**记下来继续下一批**，
    最后如实报"哪几页没拿到"——宁可索引不全，也不要因为第 7 页超时就整份丢弃。
    """
    items: list[dict] = []
    failed_pages: list[int] = []
    total = 0
    page = 1
    while True:
        try:
            result = list_mods(page, per_page, timeout=timeout, cancel=cancel)
        except Exception as exc:  # noqa: BLE001 —— 单项失败不中断整批
            _log(log, f"商城索引：第 {page} 页失败（{exc}）")
            failed_pages.append(page)
            if len(failed_pages) > 3:      # 连续多页都不行 ⇒ 网络确实不通，别再硬撑
                break
            page += 1
            continue
        total = result["total"] or total
        rows = result["items"]
        items.extend(rows)
        if progress:
            progress(f"已取 {len(items)}/{total or '?'} 个 Mod…")
        if not rows or (total and len(items) >= total):
            break
        if pages and page >= pages:
            break
        page += 1
    return {
        "items": items,
        "total": total or len(items),
        "failed_pages": failed_pages,
        "fetched_at": time.time(),
    }


def ensure_index(config: Any, *, ttl: int = INDEX_TTL_SECONDS, force: bool = False,
                 cancel: Cancel = None, progress: Progress = None,
                 log: Callable[[str], None] | None = None) -> dict:
    """确保本地索引可用（新鲜就直接用；拉失败**静默回退旧缓存**）。"""
    from . import fsutil

    cached = load_index(config)
    if not force and cached.get("items") and index_age(config) < ttl:
        return cached
    try:
        fresh = build_index(cancel=cancel, progress=progress, log=log)
    except Exception as exc:  # noqa: BLE001
        if cached.get("items"):
            _log(log, f"商城索引：刷新失败，先用上次缓存（{exc}）")
            return cached
        raise
    if not fresh.get("items") and cached.get("items"):
        _log(log, "商城索引：这次一条都没取到，保留上次缓存")
        return cached
    # 只落盘"界面要用的字段"，不把整个 raw 塞进索引（707 条 raw 会让文件胖到几 MB）
    slim = [{key: value for key, value in item.items() if key != "raw"} for item in fresh["items"]]
    try:
        fsutil.write_json(index_path(config),
                          {**fresh, "schema": STORE_SCHEMA, "items": slim})
    except OSError as exc:  # noqa: BLE001
        _log(log, f"商城索引：缓存写入失败（{exc}）")
    return fresh


# ── 更新判定（"批量扫描"的核心，不需要逐个查详情）───────────────────────────
def parse_download_time(text: Any) -> float:
    """把 `download-info.json` 里的「下载时间」（本地时间字符串）转成时间戳。

    这是"本地这份是什么时候下的"的唯一来源（那份文件是给人和程序看的双份记录，
    见 `moddl.write_download_info`）。解析不出来就返回 0 —— 调用方据此**退回目录 mtime**，
    而不是当成"1970 年下载的"从而把每个 Mod 都判成有更新。
    """
    value = str(text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def compare_updates(installed: Sequence[dict], index_items: Sequence[dict]) -> dict:
    """把"库里已装的"与"远端索引"对上，判出**有更新 / 找不到 / 已最新**。

    *installed* 每项：`{id, name, folder, source_id, installed_at}`；
    *index_items* 来自 `ensure_index()`（`Mod/Index` 的记录**带 `_tsDateUpdated`**，
    所以全量扫描**不必逐个查详情** —— 707 次请求 vs 1 次索引）。

    判据：远端"最近更新"时间晚于本地"下载时间" ⇒ 有更新。
    ⚠️ 时钟都取绝对时间戳（远端是 Unix 秒，本地是本地时间字符串转的），不涉及时区换算；
    但如果用户改过系统时间，这里会出现假阳性/假阴性 —— 所以界面只提示"可能有更新"，
    下载照样由用户点（确实判断错了也只是多点一下，不会自己动他的库）。
    """
    by_id = {int(item.get("id") or 0): item for item in index_items}
    updates: list[dict] = []
    missing: list[dict] = []
    current: list[dict] = []
    for local in installed:
        mod_id = _int(local.get("source_id"))
        if not mod_id:
            continue                       # 没有来源 id 的（手工放进来的）**不猜**，直接跳过
        remote = by_id.get(mod_id)
        if remote is None:
            missing.append({**local, "reason": "远端找不到这个 Mod（可能被作者删除或隐藏）"})
            continue
        row = {
            **local,
            "remote_name": remote.get("name") or "",
            "remote_version": remote.get("version") or "",
            "remote_updated": remote.get("updated") or 0,
            "remote_url": remote.get("url") or "",
            "remote_thumb": remote.get("thumb") or "",
            "remote_character": remote.get("character") or "",
        }
        installed_at = float(local.get("installed_at") or 0)
        if installed_at and float(remote.get("updated") or 0) > installed_at:
            updates.append(row)
        else:
            current.append(row)
    updates.sort(key=lambda row: row.get("remote_updated") or 0, reverse=True)
    return {"updates": updates, "current": current, "missing": missing, "scanned": len(installed)}


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001 —— 日志函数不该影响主流程
            pass


__all__ = [
    "BASE_URL", "ENDFIELD_GAME_ID", "PAGE_MAX", "SUBFEED_PER_PAGE", "CSV_PROPERTIES",
    "StoreUnreachable", "StoreBadRequest",
    "user_agent", "normalize", "thumb_url", "preview_image", "is_nsfw",
    "list_mods", "list_recent", "search", "sort_items",
    "categories", "load_categories", "categories_path",
    "detail",
    "index_path", "load_index", "index_age", "build_index", "ensure_index",
    "compare_updates", "parse_download_time",
    "thumb_root", "thumb_path", "prepare_images", "ThumbServer",
]
