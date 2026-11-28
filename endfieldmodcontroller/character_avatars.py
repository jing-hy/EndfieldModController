# SPDX-License-Identifier: AGPL-3.0-only
"""角色头像：把官网的角色图标下载到**本机缓存**，供「角色墙」布局显示。

设计要点（都是被现实约束出来的）：

* ⚠️ **不随包分发**（2026-11-28 定案；用户：「角色立绘可以下载后从官方拉取」）——
  官网头像是官方美术，进 exe 既占体积也不该复刻。于是"首次进角色墙时按需抓一次"，
  缓存在 <数据根>/runtime/cache/characters/；下好之后就离线可见。
* ⚠️ **直链里带构建 hash、会随官网改版变** ⇒ 只现抓不写死：URL 由
  character_sync.avatar_map 从官网干员页解析（那份 HTML 我们本来就要拉），
  随包 characters.json 里也留着上次同步时的 avatar 直链 —— 冷启动也能试一把。
* ⚠️ **文件名来自外部页面** ⇒ 拼进本地路径前**必须校验**（只认 [a-z0-9_]+ 这类），
  否则等于把路径穿越的口子交给官网页面（它被改/被劫持时就能写到目录外）。
* 下载复用 modstore._image_get（连接复用那套），并且与商城图片一样支持
  "**后台下 + 界面轮询**"，于是头像也是下好一张显一张，而不是整页一起等。
"""
from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

from . import modstore

#: 允许落到本地的文件名（与 modstore.ThumbServer 的白名单保持一致）
_NAME_RE = re.compile(r"[a-z0-9_]+(?:\.[0-9a-f]{6,})?\.(?:png|jpg|jpeg|webp)", re.I)

#: 后台正在下载的头像（同一个 URL 不重复起任务）
_INFLIGHT: set[str] = set()
_LOCK = threading.Lock()


def avatar_dir(config: Any) -> Path:
    """头像缓存目录。"""
    return Path(config.runtime_path) / "cache" / "characters"


def avatar_name(url: str) -> str:
    """从直链里取**安全的**文件名（如 chen.b0afd1ba.png）；不安全就返回空串。"""
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
        # 走**全局** 6 路闸门（与商城图片共用一把）：头像与商城图同时下时，
        # 以前是 4 + 6 = 10 路，贴着"服务端按 IP 限并发、12 路整批失败"的线。
        with modstore._IMAGE_SLOTS:
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
                   workers: int = 6, background: bool = False,
                   log: Callable[[str], None] | None = None) -> dict:
    """把缺的头像下到本地。

    返回 {"files": {URL: 文件名}, "failed": [...], "pending": [...]}。

    *background=True*（界面走这条）：**只返回已经在本地的那几张**，缺的丢后台线程，
    调用方过一会儿再问一次 pending 里的那些 —— 与商城图片同一套做法，
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


def local_avatar(config: Any, url: str) -> str:
    """这张头像**已经在本地**就返回文件名，否则空串（不联网、不落盘）。"""
    name = avatar_name(url)
    if not name:
        return ""
    return name if (avatar_dir(config) / name).is_file() else ""


def missing_avatars(config: Any) -> list[str]:
    """官网直链里**本地还没有**的那些（角色墙顶部那句"未下载"与下载任务共用）。

    只读本机状态 —— 用户 2026-11-28：「不应该每次启动都连接」。真正发请求只在
    download_avatars() 里，而那次由界面上的下载按钮触发。
    """
    from . import character_sync

    out: list[str] = []
    for url in character_sync.avatar_map(config).values():
        if url and avatar_name(url) and not local_avatar(config, url):
            out.append(url)
    return out


def download_avatars(config: Any, urls: Iterable[str], *, timeout: int = 20,
                     workers: int = 6, progress: Callable[[int, int], None] | None = None,
                     log: Callable[[str], None] | None = None) -> dict:
    """**前台**批量下载（带进度回调）—— 下载中心那条「角色立绘」任务用。

    与 ensure_avatars(background=True) 的区别：这条是用户显式点的，会一直跑到结束，
    并且每完成一张就回报一次，好让下载页的进度条动起来。
    """
    wanted = [str(url) for url in urls if avatar_name(str(url or ""))]
    total = len(wanted)
    if progress:
        progress(0, total)
    if not wanted:
        return {"total": 0, "done": 0, "failed": []}

    lock = threading.Lock()
    state = {"done": 0}

    def one(url: str) -> bool:
        ok = _fetch_one(config, url, timeout, log)
        with lock:
            state["done"] += 1
            done = state["done"]
        if progress:
            try:
                progress(done, total)
            except Exception:  # noqa: BLE001 —— 进度回调坏了不该拖垮下载
                pass
        return ok

    with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as pool:
        results = list(pool.map(one, wanted))
    failed = [url for url, ok in zip(wanted, results) if not ok]
    return {"total": total, "done": total - len(failed), "failed": failed}
