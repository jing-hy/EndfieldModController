# SPDX-License-Identifier: GPL-3.0-or-later
"""自更新徽章的收尾判据（2026-10-16，反馈者报「更新不了」）。

**事故**：后端在"已有下载任务在跑"时会**静默**把那个任务的进度当成自更新的结果回给界面
（见 `api._dep_busy_result` 的说明）。前端 `pollDownload()` 又只看一条消息文本判"是否下好"：

    const ok = /已下载|完成/.test(msg);

而组件更新任务正常结束时的消息正是「完成」⇒ 徽章报「更新包已下载，等待你选择何时安装」，
其实什么都没下、程序还是旧版 ⇒ 用户看到的就是「更新不了」，日志里还一句都没有。

**现在钉住两条**：① 轮询必须按 `app_update` 认任务、按 `pending_apply` 认结果；
② 后端明确拒绝（`busy`）时必须给用户一句人话，不能装作开始下载了。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BADGE = ROOT / "frontend" / "src" / "components" / "UpdateBadge.vue"
DIST = ROOT / "web" / "dist" / "index.html"


@pytest.fixture(scope="module")
def source() -> str:
    assert BADGE.is_file(), f"找不到自更新徽章源码: {BADGE}"
    return BADGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def code(source: str) -> str:
    """剥掉 `//` 行注释 —— 判据只看**真正会执行的代码**（注释里会引用旧写法做说明）。"""
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))


def test_polling_never_trusts_message_text(code: str):
    """不许再用"消息里含完成/已下载"判自更新下好了 —— 那是误报的源头。"""
    assert "/已下载|完成/" not in code, (
        "又用消息文本判自更新结果了：任何以『完成』结尾的任务都会被误判成『更新包已下载』")


def test_polling_is_keyed_on_the_app_update_task(code: str, source: str):
    """轮询要认任务类型，并且只认后端明说的 `pending_apply`。"""
    assert "p.app_update" in code, "轮询没有按 app_update 认任务"
    assert "pending_apply" in code, "没有用 pending_apply 作为『包已就绪』的判据"
    assert "p.pending_apply" in code, "pending_apply 没被当成收尾判据用"
    assert "app_update" in source


def test_busy_refusal_is_surfaced_to_the_user(code: str):
    """后端拒绝（busy）时要告诉用户，别沉默地什么都不做。"""
    assert "busy" in code, "没有处理后端的 busy 拒绝"
    assert "showAlert" in code


def test_dist_bundle_contains_the_fix():
    """**产物必须跟着源码走**（程序加载的是 `web/dist/index.html`，不是源码）。"""
    if not DIST.is_file():
        pytest.skip("没有构建产物（本地没跑过 vite build）")
    html = DIST.read_text(encoding="utf-8", errors="replace")
    assert "app_update" in html, "产物里没有这次修复 —— 改了 frontend/ 但没重建 web/dist/index.html"
