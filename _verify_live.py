"""实测：并行下载时 progress 回调**多久报一次**（改之前是"整块下完才报"）。

用本地 HTTP 服务造一个**慢速**大文件，走 `_download_parallel`，
记录每次 progress 回调的时间与字节 —— 改之前应当"长时间只报一次"，
改之后应当"每 256 KB 报一次"。
"""
import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path
import tempfile

sys.path.insert(0, r"D:\zmdmod\modecontroller")
from endfieldmodcontroller import fastnet

SIZE = 6 * 1024 * 1024          # 6 MB（> MIN_PARALLEL_BYTES，会走并行）
CHUNK_DELAY = 0.02              # 每 256 KB 睡 20ms → 约 12.5 MB/s，够慢到能看清


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):    # 静音
        pass

    def do_GET(self):
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
            n = min(256 * 1024, remaining)
            try:
                self.wfile.write(b"Z" * n)
            except (BrokenPipeError, ConnectionResetError):
                return
            remaining -= n
            time.sleep(CHUNK_DELAY)


srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
srv.daemon_threads = True
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"  本地慢速服务: 127.0.0.1:{port}  文件 {SIZE // 1048576} MB")

calls = []
started = time.time()


def progress(done, total):
    calls.append((time.time() - started, done))


tmp = Path(tempfile.mkdtemp(prefix="mc-live-"))
dest = tmp / "big.bin"
url = f"http://127.0.0.1:{port}/big.bin"

retries = fastnet._download_parallel(
    url, dest, size=SIZE, start=0, threads=8, timeout=30,
    progress=progress, log=lambda m: None,
)

elapsed = time.time() - started
print(f"  完成：{dest.stat().st_size} B / {elapsed:.2f}s，重试 {retries}")
print(f"  progress 回调次数 = {len(calls)}")
firsts = [f"{t:.2f}s/{d // 1024}KB" for t, d in calls[:6]]
print("  前几次回调：", ", ".join(firsts))
gaps = [round(calls[i][0] - calls[i - 1][0], 3) for i in range(1, min(len(calls), 12))]
print("  相邻间隔（秒）：", gaps)

# 断言：回调次数要足够多（"整块下完才报"时只会是个位数）
assert len(calls) >= 15, f"回调太少（{len(calls)} 次），说明还是'整块完成才报'"
max_gap = max(gaps) if gaps else 0
assert max_gap < 2.0, f"相邻回调最大间隔 {max_gap}s，太稀疏"
# 单调不回退
seq = [d for _, d in calls]
assert seq == sorted(seq), "进度不能回退"
print()
print("  ✓ 回调密集且单调递增（边下边报生效）")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
srv.shutdown()
