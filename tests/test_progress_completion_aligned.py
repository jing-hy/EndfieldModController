"""钉住「完成时进度条必须也在 100%」（2026-10-03 用户报的进度问题）。

**症状**：「**动态显示安装完成，但是进度条才走了一半**」。

**根因**：前端进度条**优先用 byte_percent**（字节进度）：

    DepsPage.vue:234   if (typeof p.byte_percent === "number" && p.expected_bytes > 0)
    DepsPage.vue:235       percent.value = … p.byte_percent;

而后端完成分支**只把 percent 对齐到 100**，byte_percent 仍停在「按预估总字节算出的
比例」上 —— 预估偏大时就只走一半：文字说完成、条停在一半。

与既有的那条约定同理（api.py 注释）：「完成时 100% 必须和 N/N 对得上」。
"""
from __future__ import annotations

import inspect
from pathlib import Path

from endfieldmodcontroller import api as A

PERCENT100 = 'task["percent"] = 100.0'
BYTEPERCENT100 = 'task["byte_percent"] = 100.0'
EXPECTED = 'task["expected_bytes"] = int('


def _deps_page_source() -> str:
    return (Path(__file__).resolve().parents[1]
            / "frontend" / "src" / "pages" / "DepsPage.vue").read_text(encoding="utf-8")


def test_completion_aligns_byte_percent() -> None:
    """完成分支必须把 byte_percent 一起对齐到 100。"""
    src = inspect.getsource(A.EndfieldModControllerApi.start_full_update)
    assert PERCENT100 in src, "完成分支应当有 percent = 100"
    assert BYTEPERCENT100 in src, (
        "完成分支没有对齐 byte_percent —— 前端进度条优先用它，"
        "会停在「完成 + 一半」")


def test_completion_aligns_expected_bytes() -> None:
    """完成时把 expected_bytes 收敛到实际值，免得字节数那行也停在半路。"""
    src = inspect.getsource(A.EndfieldModControllerApi.start_full_update)
    assert EXPECTED in src, "完成分支应当收敛 expected_bytes"


def test_frontend_falls_back_to_100_when_finished() -> None:
    """前端要有兜底：任务已跑完（running=False 且有结果）时进度条就是 100。"""
    src = _deps_page_source()
    marker = "const finished = p.running === false"
    assert marker in src, "前端没有「跑完即 100%」的兜底"
    # 兜底必须排在 byte_percent 分支之前，否则永远不会生效
    assert src.index(marker) < src.index("typeof p.byte_percent"), (
        "兜底分支必须排在 byte_percent 之前，否则不生效")


def test_frontend_reads_both_fields() -> None:
    """记下前端「优先 byte_percent」这个事实 —— 后端对齐后就靠它了。"""
    src = _deps_page_source()
    assert "p.byte_percent" in src and "p.percent" in src
