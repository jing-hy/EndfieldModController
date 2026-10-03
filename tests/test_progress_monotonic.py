"""实测「进度条往回跳」是否修好 —— 用**会中途失败重试**的慢速服务。

**用户报**：「开 vpn 下载快，但是**为什么进度条老是往回跳**」。
根因：每次读超时 → 重试 → 我把 `state["live"] = 0` ⇒ 上报值从"已完成+已接收"
掉回"已完成" ⇒ 进度回跳。
现在上报走**高水位** `state["reported"]`，无论重试多少次都只增不减。

这里记录每次 progress 回调的值，断言**单调不减**。
"""
from __future__ import annotations

import http.server
import random
import socketserver
import threading
import time
from pathlib import Path

import pytest

from endfieldmodcontroller import fastnet

SIZE = 3 * 1024 * 1024


class _FlakySlowHandler(http.server.BaseHTTPRequestHandler):
    """慢 + **随机中途断连** —— 制造"失败重试"，正是会触发进度回跳的场景。"""

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
        sent = 0
        while remaining > 0:
            n = min(65536, remaining)
            try:
                self.wfile.write(b"Z" * n)
            except Exception:            # noqa: BLE001
                return
            remaining -= n
            sent += n
            time.sleep(0.05)
            # 送了 1/4 之后有一定概率**直接断开**，逼客户端重试
            if sent > length // 4 and random.random() < 0.5:
                try:
                    self.wfile.flush()
                    self.connection.close()
                except Exception:        # noqa: BLE001
                    pass
                return


@pytest.fixture()
def flaky_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _FlakySlowHandler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}/x.bin"
    finally:
        srv.shutdown()


def test_progress_never_goes_backwards(tmp_path: Path, flaky_server: str) -> None:
    """★ 进度回调必须**单调不减**（重试也不许回跳）。

    注意：这个服务会**随机中途断连**，所以整次下载**可能最终失败**（重试次数有限）——
    那没关系，本测试只关心"**过程中的进度有没有往回跳**"，
    这正是用户报的现象（「进度条老是往回跳」）。
    """
    seen: list[int] = []

    def progress(done: int, total: int) -> None:
        seen.append(int(done))

    try:
        fastnet._download_parallel(
            flaky_server, tmp_path / "x.bin",
            size=SIZE, start=0, threads=4, timeout=30,
            progress=progress, log=lambda m: None,
        )
    except OSError:
        pass          # 允许因为服务端反复断连而最终失败

    assert seen, "应当有进度回调"
    for i in range(1, len(seen)):
        assert seen[i] >= seen[i - 1], (
            f"进度回跳：第 {i} 次 {seen[i]} < 上一次 {seen[i - 1]}"
            f"（序列前 24 个：{seen[:24]}）")


def test_no_timed_out_object_errors(tmp_path: Path) -> None:
    """轮询必须用 `select()` 探测 —— 不能出现 `cannot read from timed out object`。

    上一版拿 POLL_SECONDS 当 socket 超时、超时后 continue 再 read，
    而 `http.client` 超时后就不能再读 ⇒ 每轮轮询都变成一次失败。
    这里用一个**只发 1 字节就停住**的服务，逼出轮询路径，断言不产生那个错。
    """
    class _StallHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):       # noqa: D102
            pass

        def do_GET(self):                # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b"Z")       # 只发 1 字节
            self.wfile.flush()
            time.sleep(4)                # 然后挂住（触发多次轮询）

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _StallHandler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    logs: list[str] = []
    try:
        with pytest.raises(Exception):   # 超窗口后会抛（线路不通）
            fastnet._download_parallel(
                f"http://127.0.0.1:{port}/x.bin", tmp_path / "y.bin",
                size=10, start=0, threads=1, timeout=5,
                log=logs.append,
            )
    finally:
        srv.shutdown()

    joined = " ".join(logs)
    assert "timed out object" not in joined, f"不该出现 http.client 的超时残留错误：{joined[:300]}"
