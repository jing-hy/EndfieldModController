# SPDX-License-Identifier: AGPL-3.0-only
"""钉住 2026-11-28 的两条下载策略调整（用户：「**应该默认抢块**」）。

实测现场（用户网络：直连约 0.028 MB/s，4 线路抢块约 1.7 MB/s）：

    XXMI-Libs-Package  3.4 MB  122 秒    ← 旧阈值 4 MB ⇒ 只走单连接
    Poser              7.8 MB  81 秒
    Streamline SDK   263.2 MB 157 秒

阈值降到 512 KB 后，3.4 MB 的包也能进探测 + 抢块；探测上限从 12 秒降到 6 秒，
每个包少等一半。这里守的是"别悄悄调回去"：改这两条要有明确的实测依据。
"""
from __future__ import annotations

from endfieldmodcontroller import fastnet


def test_small_packages_can_use_parallel_pieces() -> None:
    """小于 4 MB 的包也要能进并发抢块（原来 4 MB 阈值把它挡在单连接里）。"""
    assert fastnet.MIN_PARALLEL_BYTES <= 512 * 1024, (
        f"MIN_PARALLEL_BYTES={fastnet.MIN_PARALLEL_BYTES} —— 3.4 MB 的组件包会退回单连接"
    )


def test_probe_deadline_is_short() -> None:
    """探测上限要短（每个包下载前都要探一次，串行下载时全是纯等待）。"""
    assert fastnet.PROBE_SECONDS <= 6, (
        f"PROBE_SECONDS={fastnet.PROBE_SECONDS} —— 探测又变成长等待了"
    )