"""角色头像：把官网的角色图标下载到**本机缓存**，供「角色墙」布局显示。

设计要点（都是被现实约束出来的）：

* ⚠️ **不随包分发** —— 官网头像是官方美术，进 assets-bundle 有版权问题。所以是
  "首次进角色墙时按需抓一次"，缓存在 `<数据根>/runtime/cache/characters/`。
* ⚠️ **直链里带构建 hash、会随官网改版变** ⇒ 只现抓不写死：URL 由
  `character_sync.parse_official` 从官网干员页里解析出来（那份 HTML 我们本来就要拉）。
* ⚠️ **文件名来自外部页面** ⇒ 拼进本地路径前**必须校验**（只认 `[a-z0-9_]+` 这类），
  否则等于把路径穿越的口子交给官网页面（它被改/被劫持时就能写到目录外）。
* 下载复用 `modstore._image_get`（连接复用那套），并且与商城图片一样支持
  "**后台下 + 界面轮询**"，于是头像也是下好一张显一张，而不是整页一起等。
"""
from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

from . import modstore

#: 允许落到本地的文件名（与 `modstore.ThumbServer` 的白名单保持一致）
_NAME_RE = re.compile(r"[a-z0-9_]+(?:\.[0-9a-f]{6,})?\.(?:png|jpg|jpeg|webp)", re.I)

#: **随包**头像目录（与 `characters.json` 同级、一起打进 exe）。
#: 用户 2026-10-07：「角色表和图直接随包」「**是随 exe**」—— 于是离线也有头像，
#: 不用等官网、也不受官网改版（直链带构建 hash）影响。
BUNDLED_DIR = Path(__file__).with_name("characters")

#: 后台正在下载的头像（同一个 URL 不重复起任务）
_INFLIGHT: set[str] = set()
_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, str] | None = None


def bundled_index() -> dict[str, str]:
    """随包索引 `{角色名: 头像文件名}`（缺失/坏掉都当空表，不抛）。"""
    global _INDEX_CACHE

    if _INDEX_CACHE is None:
        table: dict[str, str] = {}
        try:
            data = json.loads((BUNDLED_DIR / "index.json").read_text(encoding="utf-8"))
            for name, file_name in (data.get("avatars") or {}).items():
                if str(name).strip() and str(file_name).strip():
                    table[str(name).strip()] = str(file_name).strip()
        except Exception:  # noqa: BLE001 —— 没有随包索引就退回"按 key 找/联网下"
            table = {}
        _INDEX_CACHE = table
    return _INDEX_CACHE


def find_avatar(config: Any, name: str) -> str:
    """按**角色名**找本地头像文件名（随包优先、运行时缓存兜底）；找不到返回空串。

    ⚠️ 走随包索引而**不是"按 key 猜文件名"**：官网对同一角色的拼写可能与我们不同
    （实测：佩丽卡的头像文件叫 `prelica.*.png`，而表里的 key 是 `perlica`；
    管理员在官网还被拆成男女两条）—— 靠拼凑要么漏、要么认错人。
    """
    key = str(name or "").strip()
    if not key:
        return ""
    file_name = bundled_index().get(key, "")
    if not file_name:
        return ""
    for folder in (BUNDLED_DIR, avatar_dir(config)):
        if (folder / file_name).is_file():
            return file_name
    return ""


def avatar_dir(config: Any) -> Path:
    """头像缓存目录。"""
    return Path(config.runtime_path) / "cache" / "characters"


def avatar_name(url: str) -> str:
    """从直链里取**安全的**文件名（如 `chen.b0afd1ba.png`）；不安全就返回空串。"""
    tail = str(url or "").rsplit("/", 1)[-1].strip()
    return tail.lower() if _NAME_RE.fullmatch(tail) else ""


def avatar_path(config: Any, url: str) -> Path:
    return avatar_dir(config) / avatar_name(url)


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def _fetch_one(config: Any, url: str, timeout: int,
               log: Callable[[str], None] | None) -> bool:
    """下一张头像并原子落盘；失败不留半张。"""
    name = avatar_name(url)
    if not name:
        _log(log, "角色头像：直链文件名不合法，跳过（不拼进本地路径）")
        return False
    target = avatar_dir(config) / name
    tmp = target.with_name(target.name + ".part")
    try:
        blob = modstore._image_get(url, timeout=timeout)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(blob)
        os.replace(tmp, target)
        return True
    except Exception as exc:  # noqa: BLE001 —— 一张头像失败不影响别人
        for leftover in (tmp, target):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
        _log(log, f"角色头像：下载失败（{exc}）")
        return False


def _drain(config: Any, urls: list[str], timeout: int, workers: int,
           log: Callable[[str], None] | None) -> None:
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(urls)))) as pool:
            list(pool.map(lambda item: _fetch_one(config, item, timeout, log), urls))
    finally:
        with _LOCK:
            _INFLIGHT.difference_update(urls)


def ensure_avatars(config: Any, urls: Iterable[str], *, timeout: int = 20,
                   workers: int = 4, background: bool = False,
                   log: Callable[[str], None] | None = None) -> dict:
    """把缺的头像下到本地。

    返回 `{"files": {URL: 文件名}, "failed": [...], "pending": [...]}`。

    *background=True*（界面走这条）：**只返回已经在本地的那几张**，缺的丢后台线程，
    调用方过一会儿再问一次 `pending` 里的那些 —— 与商城图片同一套做法，
    于是头像也是"下好一张显一张"。并发 4 路：官网 CDN 与香蕉网不是一回事，保守一点。
    """
    wanted = [str(url).strip() for url in urls if str(url or "").strip()]
    files: dict[str, str] = {}
    pending: list[str] = []
    for url in wanted:
        name = avatar_name(url)
        if not name:
            continue
        if (avatar_dir(config) / name).is_file():
            files[url] = name
        else:
            pending.append(url)

    if not pending:
        return {"files": files, "failed": [], "pending": []}

    if background:
        with _LOCK:
            fresh = [item for item in pending if item not in _INFLIGHT]
            _INFLIGHT.update(fresh)
        if fresh:
            threading.Thread(target=_drain, args=(config, fresh, timeout, workers, log),
                             daemon=True, name="mc-avatars").start()
        return {"files": files, "failed": [], "pending": pending}

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pending)))) as pool:
        results = list(pool.map(lambda item: _fetch_one(config, item, timeout, log), pending))
    failed: list[str] = []
    for url, ok in zip(pending, results):
        if ok:
            files[url] = avatar_name(url)
        else:
            failed.append(url)
    return {"files": files, "failed": failed, "pending": []}
