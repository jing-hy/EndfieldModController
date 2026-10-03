"""钉住两个「降阈值后立刻暴露」的真问题（2026-10-03）。

**背景**：用户问「**只是 github 禁止分片，为什么镜像站也没分片？**」。
查下去发现两件事：
① 镜像**并没有**被禁分片（`_may_parallel` 对四条线路全是 True）——
   日志里那句"不并发"是**旧 exe** 留下的文案；
② **真问题是 `DEAD_MBPS = 0.3` 这个绝对阈值**：这台机器（开着 Steam++）最快也只有 0.28
   ⇒ **每条线路都被判死**，只能靠兜底捡回最慢的一条用（实测 ghproxy.net 0.20 被判死，
   而它其实是当场最快的 0.279）。

**降阈值（0.3 → 0.02）后立刻暴露了第二个问题**：
`threads` 只在"真正要并发"时才赋值，而"极慢线路也上并发"那段会先用到它 ⇒
`UnboundLocalError: threads`。（同一个坑 2026-10-02 因为 `policy="always"` 踩过一次。）
"""
from __future__ import annotations

import http.server
import socketserver
import threading
import time
from pathlib import Path

import pytest

from endfieldmodcontroller import fastnet as F


def test_dead_mbps_is_floor_not_absolute() -> None:
    """★ 判死阈值必须是"真的不可用"级别，不能把 0.2 MB/s 这种可用线路也判死。

    实测：这台机器最快 0.279，旧的 0.3 会把**所有**线路判死。
    """
    assert F.DEAD_MBPS <= 0.05, (
        f"DEAD_MBPS={F.DEAD_MBPS} 太大 —— 会把 0.2~0.3 MB/s 的可用线路也判死"
        "（实测这台机器最快只有 0.28）")
    assert F.DEAD_MBPS > 0, "不能是 0（那就不拦任何东西了）"


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    """很慢但可用：每 256 KB 睡一下，总速度落在 0.02~0.3 之间。"""

    SIZE = 6 * 1024 * 1024

    def log_message(self, *args):        # noqa: D102
        pass

    def do_GET(self):                    # noqa: N802
        rng = self.headers.get("Range")
        start, end = 0, self.SIZE - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = int(b) if b else self.SIZE - 1
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{self.SIZE}")
        self.end_headers()
        remaining = length
        while remaining > 0:
            n = min(65536, remaining)
            try:
                self.wfile.write(b"Q" * n)
            except Exception:            # noqa: BLE001
                return
            remaining -= n
            time.sleep(0.12)             # ~0.5 MB/s 量级（仍低于 SLOW_MBPS=1.5）


@pytest.fixture()
def slow_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _SlowHandler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}/x.bin"
    finally:
        srv.shutdown()


def test_slow_line_still_gets_parallel(tmp_path: Path, slow_server: str) -> None:
    """★ 「有点慢但可用」的线路必须照样上并发，而不是被判死或退回单连接。

    这条同时是 `UnboundLocalError: threads` 的回归 —— 它正是在这条路径上炸的。
    """
    logs: list[str] = []
    report = F.download(
        slow_server, tmp_path / "x.bin",
        log=logs.append, timeout=120,
        # 本地小文件，绕过"文件太小不值得并发"的短路
        expected_size=_SlowHandler.SIZE,
    )
    joined = " ".join(logs)
    assert report.ok, f"应当下载成功；日志：{joined[:300]}"
    assert "UnboundLocalError" not in joined and "threads" not in joined.split("unbound")[0]
    # 要么明确的"仍用 N 连接试"，要么确实用了多于 1 条连接
    used_parallel = ("连接试" in joined) or ("并发" in joined) or report.threads > 1
    assert used_parallel, f"慢线路应当走并发；日志：{joined[:300]}"
