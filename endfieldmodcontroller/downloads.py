"""下载中心：把两套任务容器归一化成**同一份界面清单**。

用户 2026-10-07 原话：「把下载从依赖里面抽出来，之前是所有下载跳转依赖的现在都跳转下载，
依赖也跳转下载，**下载可以后台进行，可以追加任务**，看商城不用下一个就跳转一次，但是要有动态」。

## 为什么不重写一套下载引擎

下载本体（`moddl` + `fastnet`）已经跑得很稳：并行分块、镜像线路、断点续传、
解压入库、同源旧版移出、卡死判定……全都有测试钉着。这里**一行都不重写**，只做两件事：

① 把两套任务容器读成同一种形状 ——
   * `api._mod_dl`：Mod 下载队列（一个批次里有 N 个 item，每个 item 自己带状态与进度）；
   * `api._dep_task`：依赖 / 组件 / 自更新的**单例**任务（自带 percent / message / log）；
② 提供"活跃数 / 总速度"这类派生量 —— 侧栏徽标与顶部汇总要用的判断只此一份。

（"追加任务"的实现在队列那边：`api.start_mod_download` 把新项塞进待办、
worker 循环取件，因此**同一时刻仍然只有一个 worker** —— 那条约束是 2026-10-04 的教训：
两个 worker 并发改同一份 `_mod_dl` 会让进度乱跳、完成标志互相覆盖。）
"""
from __future__ import annotations

from typing import Any, Iterable

#: "还在跑"的状态集合。
#:
#: ⚠️ **这份集合以前在 `api.py` 里硬编码了两遍**（`active_download_count` 与
#: `clear_mod_downloads` 各写一份），加一种状态就要改两处、漏一处就出 bug
#: （"清记录把正在下的也抹掉"那类）。现在收敛到这里，api 两处都引用它。
ACTIVE_STATUSES: tuple[str, ...] = ("等待中", "读取香蕉网信息", "下载中", "解压中")

#: 任务类型（界面用它的徽标与标题，控制按钮也按类型给）。
KIND_MODS = "mods"
KIND_DEPS = "deps"


def is_active(item: dict) -> bool:
    """一个 Mod 下载项是不是"还在跑"。"""
    return str((item or {}).get("status") or "") in ACTIVE_STATUSES


def mod_item(item: dict) -> dict:
    """挑出界面真正要用的字段（任务项里还挂着内部用的 last_tick / cover 路径等）。

    ⚠️ `cover_data` 必须带上：它把封面图转成 data URI 缓存在任务上，
    而封面文件在下一次收尾时就被删掉了（2026-10-02 用户：「入库或者中断图片也要删」），
    不带它界面上就是一片空白。
    """
    return {
        "id": str(item.get("mod_id") or item.get("url") or ""),
        "url": str(item.get("url") or ""),
        "origin_url": str(item.get("origin_url") or ""),
        "name": str(item.get("name") or ""),
        "title": str(item.get("title") or ""),
        "author": str(item.get("author") or ""),
        "version": str(item.get("version") or ""),
        "page": str(item.get("page") or ""),
        "site_category": str(item.get("site_category") or ""),
        "status": str(item.get("status") or ""),
        "message": str(item.get("message") or ""),
        "percent": int(item.get("percent") or 0),
        "received": int(item.get("received") or 0),
        "size": int(item.get("size") or 0),
        "speed_bps": float(item.get("speed_bps") or 0.0),
        "path": str(item.get("path") or ""),
        "source_path": str(item.get("source_path") or ""),
        "target_dir": str(item.get("target_dir") or ""),
        "retired": list(item.get("retired") or []),
        "unreachable": bool(item.get("unreachable")),
        "stalled": bool(item.get("stalled")),
        "cover_data": str(item.get("cover_data") or ""),
    }


def normalize_mod_task(mod_dl: dict, *, downloads_dir: Any = "", counts: dict | None = None) -> dict:
    """把 Mod 下载队列读成一个任务。**即便没有任务也返回**（前端按 `running` 决定显不显示）。"""
    items = [mod_item(item) for item in (mod_dl or {}).get("items", [])]
    total_bytes = sum(int(item.get("size") or 0) for item in (mod_dl or {}).get("items", []))
    done_bytes = sum(int(item.get("received") or 0) for item in (mod_dl or {}).get("items", []))
    speed = sum(float(item.get("speed_bps") or 0.0) for item in (mod_dl or {}).get("items", []))
    active = [item for item in items if is_active(item)]
    done = bool((mod_dl or {}).get("done", True))
    if active:
        status = "下载中"
    elif items and not done:
        status = "收尾中"
    elif items:
        status = "已完成"
    else:
        status = "空闲"
    percent = round(done_bytes / total_bytes * 100.0, 1) if total_bytes else 0.0
    if done and items:
        percent = 100.0
    return {
        "id": KIND_MODS,
        "kind": KIND_MODS,
        "title": "Mod 下载",
        "status": status,
        "running": bool(active),
        "done": done,
        "percent": percent,
        "byte_percent": percent,
        "done_bytes": done_bytes,
        "total_bytes": total_bytes,
        "speed_bps": speed,
        "message": "",
        "log": [],
        "items": items,
        "counts": counts or {},
        "started_at": str((mod_dl or {}).get("started_at") or ""),
        "dir": str((mod_dl or {}).get("dir") or downloads_dir or ""),
        # Mod 下载有完整的四件控制（依赖任务目前只有"看"）：与后端真实存在的接口一一对应。
        "controls": ["pause", "resume", "cancel", "clear"],
        "paused": bool((mod_dl or {}).get("pause")),
        "stopped": bool((mod_dl or {}).get("cancel")),
    }


def normalize_dep_task(dep_task: dict | None) -> dict | None:
    """把依赖 / 组件 / 自更新那**一个**任务读成同一形状；没有任务时返回 None。

    这类任务的本体在 `api._dep_task`（三处初始化：更新依赖、一键更新全部、自更新），
    字段本来就跟界面对得上（`percent` / `byte_percent` / `speed_bps` / `message` / `log`）。

    ⚠️ 函数名带 `normalize_` 前缀是**必须的**（2026-10-07 被测试抓到的真缺陷）：
    它原来叫 `dep_task`，而 `snapshot()` 的形参也叫 `dep_task` —— 形参遮蔽模块函数，
    于是 `dep = dep_task(dep_task)` 变成"拿一个 dict 当函数调"，直接 `TypeError`。
    """
    if not dep_task:
        return None
    running = bool(dep_task.get("running"))
    items = dep_task.get("results") or []
    percent = float(dep_task.get("byte_percent") or dep_task.get("percent") or 0.0)
    if not running and dep_task.get("percent") == 100.0:
        percent = 100.0
    return {
        "id": KIND_DEPS,
        "kind": KIND_DEPS,
        "title": "依赖 / 组件下载",
        "status": "下载中" if running else ("已完成" if dep_task.get("total") else "空闲"),
        "running": running,
        "done": not running,
        "percent": round(percent, 1),
        "byte_percent": round(float(dep_task.get("byte_percent") or 0.0), 1),
        "done_bytes": int(dep_task.get("computed_bytes") or dep_task.get("bytes_received") or 0),
        "total_bytes": int(dep_task.get("expected_bytes") or 0),
        "speed_bps": float(dep_task.get("speed_bps") or 0.0),
        "message": str(dep_task.get("message") or ""),
        "log": list(dep_task.get("log") or []),
        "items": [],
        "counts": {"done": len(items)},
        "started_at": str(dep_task.get("started_at") or ""),
        "dir": "",
        # 依赖任务暂时**没有**暂停/终止（`ensure_all` 是一条顺下来的流程）——
        # 如实不提供按钮，而不是给个点了没反应的假按钮。
        "controls": [],
        "paused": False,
        "stopped": False,
    }


def snapshot(*, mod_dl: dict | None = None, dep_task: dict | None = None,
             downloads_dir: Any = "", mod_counts: dict | None = None) -> dict:
    """给界面/徽标用的一份总览。"""
    tasks = [normalize_mod_task(mod_dl or {}, downloads_dir=downloads_dir, counts=mod_counts)]
    dep = normalize_dep_task(dep_task)
    if dep is not None and (dep["running"] or dep["total_bytes"] or dep["log"]):
        tasks.append(dep)
    active = [task for task in tasks if task["running"]]
    return {
        "ok": True,
        "tasks": tasks,
        "active": len(active),
        "active_mod_items": sum(len(task["items"]) for task in active if task["kind"] == KIND_MODS),
        "speed_bps": sum(float(task["speed_bps"] or 0.0) for task in tasks),
        "kinds": [task["kind"] for task in tasks],
    }


def active_items(items: Iterable[dict]) -> list[dict]:
    return [item for item in items if is_active(item)]
