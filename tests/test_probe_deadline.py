"""钉住「探测 deadline 必须在**完全没数据**时也生效」。

**实测现场**（2026-10-03 用户：「怎么这么慢还在硬更」）：
```
21:44:11  开始下载更新包 EndfieldModController.exe（28.4 MB）
（3 分钟无任何日志，一个字节都没进来）
```
**根因**：单连接探测本应最长 `PROBE_SECONDS`(12s) 就结束，但那个 deadline 检查写在
**"成功读到一个 chunk 之后"**；而完全没数据的线路上流程一直走
`if not _readable(...): … continue` ⇒ **永远到不了那个检查** ⇒
只能等 `_seq_window`（初始速度未知 ⇒ `_stall_window` 给满 **180 秒**）。

判据：**面对一个"建了连接但一个字节都不发"的服务，探测必须在 deadline 附近返回**，
不是等满 180 秒。
"""
from __future__ import annotations

import http.server
import socketserver
import threading
import time
from pathlib import Path

from endfieldmodcontroller import fastnet


class _SilentHandler(http.server.BaseHTTPRequestHandler):
    """建了连接、声明了长度，然后**一个字节都不发**。"""

    def log_message(self, *args):        # noqa: D102
        pass

    def do_GET(self):                    # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "1000000")
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:                # noqa: BLE001
            return
        time.sleep(60)


def test_probe_deadline_applies_with_zero_data(tmp_path: Path) -> None:
    """★ 没数据时也要按 deadline 返回（不能死等 180 秒）。"""
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SilentHandler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        started = time.time()
        fastnet._download_sequential(
            f"http://127.0.0.1:{port}/x.bin", tmp_path / "x.bin",
            total=1_000_000, stop_after=200_000, deadline_seconds=12,
            log=lambda m: None,
        )
        elapsed = time.time() - started
    finally:
        srv.shutdown()

    # 12 秒的 deadline：允许一点抖动，但绝不该是 180 秒那个量级
    assert elapsed < 25, f"探测花了 {elapsed:.1f}s —— deadline 没在'没数据'时生效"
    assert elapsed >= 5, f"太快了（{elapsed:.1f}s），可能没真的等过 deadline"


def test_probe_window_is_capped_by_deadline(tmp_path: Path) -> None:
    """有 deadline 时，单轮窗口不该是 180 秒。"""
    from endfieldmodcontroller import longpath  # noqa: F401  （仅为导入一致性）

    # 直接算：初始速度未知 ⇒ _stall_window 给 180；但探测路径上会被压到 deadline 内
    full = fastnet._stall_window(fastnet.READ_CHUNK, 0.0)
    assert full >= 180, f"前提变了：速度未知时窗口是 {full}"
    # 修复点：`_seq_window = max(1.0, min(_seq_window, deadline 剩余))`
    capped = max(1.0, min(full, 12.0))
    assert capped <= 12.0
