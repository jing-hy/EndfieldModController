# SPDX-License-Identifier: AGPL-3.0-only
"""钉住 2026-11-28 的「进度显示 994.9/994.9 MB，结果整单报失败」。

外部反馈现场（香蕉网 994.9 MB 的包）：进度条已经满格，但状态是「失败」：

    分块 839504693-847655223 重试 4 次仍失败：连接建立后 20s 内没有收到任何数据（线路不通）

两个原因都在 `_download_parallel` 的 `fetch()` 里：

1. **速度算错** —— 用的是全局 `state["live"]`（所有线程的字节）除以本块耗时，
   20 条并发时虚高几十倍 ⇒ 停顿窗口被压到 20 秒下限 ⇒ 慢线路每块都判"没数据"；
2. **进度虚高** —— 重试时本轮读到但没落盘的字节没被扣回，重读一遍就再累加一次，
   `n + live` 一路顶到 `size`（满格），而块本身其实没完成。
"""
from __future__ import annotations

from endfieldmodcontroller import fastnet


def test_chunk_speed_ignores_other_threads() -> None:
    """本块速度只认**自己本轮**读到的字节（别的线程的进度不参与）。"""
    # 本块 1 秒读了 0.5 MB ⇒ 0.5 MB/s（不因为别的线程在读就虚高）
    assert fastnet._chunk_mbps(512 * 1024, 1.0) == 0.5
    # 还没有字节 / 时间非法 ⇒ 0（调用方会退回探测值或窗口下限）
    assert fastnet._chunk_mbps(0, 1.0) == 0.0
    assert fastnet._chunk_mbps(1024, 0.0) == 0.0


def test_discard_unflushed_keeps_progress_honest() -> None:
    """重试前把没落盘的字节扣回去 —— 否则重读会让进度一路顶到 100%。"""
    state = {"live": 300}
    fastnet._discard_unflushed(state, 200)
    assert state["live"] == 100
    # 本轮一个字节都没读到（比如连接都没建立）⇒ 不动
    fastnet._discard_unflushed(state, 0)
    assert state["live"] == 100
    # 读到比记账还多（历史高水位被别的路径清过）⇒ 归零，绝不出现负数
    fastnet._discard_unflushed(state, 500)
    assert state["live"] == 0


def test_retry_does_not_zero_progress() -> None:
    """扣减只扣**本轮**的字节，不能把已完成块的进度也清掉（那条是"进度往回跳"的老 bug）。"""
    state = {"live": 1000}
    fastnet._discard_unflushed(state, 0)
    assert state["live"] == 1000