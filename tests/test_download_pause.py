"""「暂停 / 终止」必须在**秒级**生效 —— 2026-10-03 用户实测报「没实际暂停」。

**根因**：`cancel()` 原来只在**读循环之外**检查（并行是 `fetch()` 的重试循环开头、
单连接是每轮 `read()` 之前），而真正耗时的是 `read()` **阻塞在等数据**上。
我把"无数据窗口"放宽到最长 180 秒之后 ⇒ **点暂停最多要等 3 分钟才生效**。

**修法**：读循环改成**短超时轮询**（socket 超时 = `POLL_SECONDS`，1 秒），
每轮先检查 `cancel()`，超时只累加"已等待量"，到窗口上限才判线路不通。
这样"慢线路等得起"与"暂停立刻响应"同时成立。

这里用一个**故意很慢**的本地服务把这件事钉住：点暂停后必须在 3 秒内停下来。
"""
from __future__ import annotations

import http.server
import socketserver
import threading
import time
from pathlib import Path

import pytest

from endfieldmodcontroller import fastnet

SIZE = 4 * 1024 * 1024


class _SlowHandler(http.server.BaseHTTPRequestHandler):
    """每 64 KB 睡 0.5 秒 —— 模拟"很慢但通"的线路（正好是触发这个 bug 的场景）。"""

    def log_message(self, *args):        # noqa: D102
        pass

    def do_GET(self):                    # noqa: N802
        rng = self.headers.get("Range")
        start, end = 0, SIZE - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = int(b) if b else SIZE - 1
        length = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{SIZE}")
        self.end_headers()
        remaining = length
        while remaining > 0:
            n = min(65536, remaining)
            try:
                self.wfile.write(b"Z" * n)
            except Exception:            # noqa: BLE001 - 客户端断开是正常的
                return
            remaining -= n
            time.sleep(0.5)


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


def test_pause_takes_effect_within_seconds(tmp_path: Path, slow_server: str) -> None:
    """★ 点暂停后必须**秒级**停下（改之前要等整个无数据窗口，实测 3 分钟）。"""
    flag = {"stop": False}

    def run() -> None:
        try:
            fastnet._download_parallel(
                slow_server, tmp_path / "x.bin",
                size=SIZE, start=0, threads=4, timeout=30,
                cancel=lambda: flag["stop"], log=lambda m: None,
            )
        except fastnet.Cancelled:
            flag["cancelled"] = True
        except Exception as exc:                 # noqa: BLE001
            flag["err"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(1.5)                              # 先让它真的跑起来
    flag["stop"] = True                          # ← 用户点「暂停」
    started = time.time()
    worker.join(timeout=15)
    elapsed = time.time() - started

    assert flag.get("cancelled"), f"应当抛 Cancelled，实际：{flag.get('err')}"
    assert elapsed < 3.0, f"暂停响应太慢：{elapsed:.1f}s（应当秒级）"


def test_cancel_before_start_is_immediate(tmp_path: Path, slow_server: str) -> None:
    """已经置了取消标志时，任务**立刻**结束（不该再下任何数据）。"""
    started = time.time()
    with pytest.raises(fastnet.Cancelled):
        fastnet._download_parallel(
            slow_server, tmp_path / "y.bin",
            size=SIZE, start=0, threads=4, timeout=30,
            cancel=lambda: True, log=lambda m: None,
        )
    assert time.time() - started < 3.0
