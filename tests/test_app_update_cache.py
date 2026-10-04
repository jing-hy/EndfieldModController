"""钉住"检查更新"的缓存契约（2026-10-04 用户实测踩到的坑）。

**现场**：用户跑伪旧版，结果只更新到 **1.0.7**，而线上 Latest 已经是 **1.0.8**。
根因既不是构建、也不是 GitHub（`gh release list` 明确标着 v1.0.8 是 Latest），
而是 `selfupdate.CHECK_CACHE_SECONDS = 6 小时` 那份**落盘**的检查结果：

    last_check.json 写于 11:32（latest=v1.0.7）
    → v1.0.8 是 11:51 才发布的
    → 之后 6 小时内、所有走缓存的检查都说"已是最新"

而设置页那个「检查程序更新」按钮走的**恰好是不传参的默认值** —— 用户点了也白点。

这组测试钉两件事：

1. **契约**：`check_app_update` 的默认必须是**强制查**（`use_cache=False`）。
   分工是明确的 —— "用户主动点"的入口走默认值（点了就真的打网络）；
   "启动时自动检查"（`UpdateBadge.autoCheck`）**显式**传 `True`（省额度、离线静默）。
2. **行为**：缓存新鲜且允许用缓存时确实复用（不查网络）；强制查时忽略它。
"""
from __future__ import annotations

import inspect
import json
import time
import types
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import selfupdate
from endfieldmodcontroller.api import EndfieldModControllerApi


def _config(root: Path):
    # `_cache_path` 只用 `config.runtime_path`，所以一个最小桩就够。
    return types.SimpleNamespace(runtime_path=root)


def _write_cache(root: Path, payload: dict) -> Path:
    path = selfupdate._cache_path(_config(root))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_app_update_api_defaults_to_force() -> None:
    """★ 用户主动点的入口靠的就是这个默认值 ⇒ 它必须是"强制查"。"""
    param = inspect.signature(EndfieldModControllerApi.check_app_update).parameters["use_cache"]
    assert param.default is False, (
        "check_app_update 的 use_cache 默认值必须是 False —— 设置页「检查程序更新」按钮不传参，"
        "靠这个默认值；一旦改回 True，它就会在该缓存（6 小时）内只回旧结论、点了也白点"
    )


def test_fresh_cache_is_reused_when_allowed(tmp_path: Path) -> None:
    """缓存新鲜 + 允许用缓存 ⇒ 复用结论，**一次网络都不打**。"""
    _write_cache(tmp_path, {
        "current": "0.0.1", "latest": "1.0.7",
        "update_available": True, "checked_at": int(time.time()),
    })
    with mock.patch("endfieldmodcontroller.github.releases_latest",
                    side_effect=AssertionError("用了新鲜缓存就不该再查网络")):
        result = selfupdate.check_update(_config(tmp_path), use_cache=True)
    assert result["latest"] == "1.0.7"
    assert result.get("cached") is True


def test_force_ignores_a_stale_conclusion(tmp_path: Path) -> None:
    """★ 强制查必须忽略缓存里的旧结论 —— 这正是用户那次"只能更到 1.0.7"的现场。"""
    _write_cache(tmp_path, {"latest": "0.0.1", "checked_at": int(time.time())})
    release = {
        "tag_name": "v9.9.9", "name": "v9.9.9", "source": "web",
        "assets": [{
            "name": "EndfieldModController.exe", "size": 0, "digest": "",
            "browser_download_url":
                "https://github.com/o/r/releases/download/v9.9.9/EndfieldModController.exe",
        }],
    }
    with mock.patch("endfieldmodcontroller.github.releases_latest", return_value=release), \
         mock.patch.object(selfupdate, "_fetch_json", side_effect=RuntimeError("无额度")):
        result = selfupdate.check_update(_config(tmp_path), use_cache=False)
    assert result["latest"] == "9.9.9", "强制查不能被那份说 0.0.1 的缓存挡住"
    assert result.get("cached") is not True


def test_expired_cache_is_not_reused(tmp_path: Path) -> None:
    """超过 6 小时的缓存不算数（否则会永远卡在旧结论上）。"""
    _write_cache(tmp_path, {
        "latest": "0.0.1",
        "checked_at": int(time.time()) - selfupdate.CHECK_CACHE_SECONDS - 60,
    })
    release = {"tag_name": "v9.9.9", "assets": [], "source": "web"}
    with mock.patch("endfieldmodcontroller.github.releases_latest", return_value=release), \
         mock.patch.object(selfupdate, "_fetch_json", side_effect=RuntimeError("无额度")):
        result = selfupdate.check_update(_config(tmp_path), use_cache=True)
    assert result["latest"] == "9.9.9"
