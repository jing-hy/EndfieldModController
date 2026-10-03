#!/usr/bin/env python
"""混合 / 动态并发的对照实验：**单线路并发 vs 多线路等分 vs 多线路动态抢块**。

**为什么要测**（两个互相矛盾的既有结论）：
* 2026-09-27 实测：「多线路混合（4+4+4）只有 1.16 MB/s —— **是负优化**」
  （慢线路成了木桶短板，且每个镜像对单 IP 的总带宽有限）；
* 2026-10-03 香蕉网实测：「**越慢的线路，并发收益越大**」（0.008 → 0.104，13×）。
⇒ 前者用的是**静态等分**（每条线路固定分 4 块）。**动态**分配（快的多领、停滞的淘汰）
   能不能把"木桶短板"消掉，是这次要回答的问题。

**三种模式**：
1. `single`  —— 只用最快那条线路，N 连接并发（当前程序的做法）；
2. `static`  —— 每条线路各 N/K 连接（复现"负优化"的那种）；
3. `dynamic` —— **共享块队列 + 每条线路一个 worker 循环领块**：快的自然多领，
   连续超时/停滞的线路被踢出队列（这就是"动态"的部分）。

用法：
    python scripts/speedtest_mixed.py                    # 默认 8 MB、三条线路
    python scripts/speedtest_mixed.py --mb 16 --conns 12
    python scripts/speedtest_mixed.py --asset <URL>
"""
from __future__ import annotations

import argparse
import threading
import time
import urllib.error
import urllib.request

DEFAULT_ASSET = ("https://github.com/jing-hy/EndfieldModController/releases/download/"
                 "v1.0.5/EndfieldModController.exe")
DEFAULT_LINES: list[tuple[str, str]] = [
    ("gh.nxnow.top", "https://gh.nxnow.top/"),
    ("ghproxy.net", "https://ghproxy.net/"),
    ("gh-proxy.com", "https://gh-proxy.com/"),
]
TIMEOUT = 20.0
BLOCK = 256 * 1024          # 每块 256 KB（小块才好动态调度）


def fetch(url: str, start: int, length: int, timeout: float = TIMEOUT) -> int:
    """取 [start, start+length) 这一段，返回实际字节数（失败返回 0）。"""
    req = urllib.request.Request(url, headers={
        "Range": f"bytes={start}-{start + length - 1}",
        "User-Agent": "EndfieldModController-speedtest/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return len(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return 0


def run_static(avatar: str, lines: list[tuple[str, str]], conns: int, total: int) -> tuple[float, dict]:
    """每条线路各 conns/K 个线程，各自顺序把自己那段下完（**静态等分**）。"""
    share = max(1, conns // max(1, len(lines)))
    per_line = total // max(1, len(lines))
    got = {name: 0 for name, _ in lines}
    lock = threading.Lock()
    started = time.time()

    def worker(prefix: str, name: str, begin: int, end: int) -> None:
        pos = begin
        while pos < end:
            size = fetch(f"{prefix}{avatar}" if prefix else avatar, pos, min(BLOCK, end - pos))
            if size <= 0:
                return
            with lock:
                got[name] += size
            pos += size

    threads = []
    for index, (name, prefix) in enumerate(lines):
        begin = index * per_line
        end = total if index == len(lines) - 1 else begin + per_line
        for _ in range(share):
            threads.append(threading.Thread(target=worker, args=(prefix, name, begin, end), daemon=True))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return (sum(got.values()) / 1024 / 1024) / max(time.time() - started, 0.001), got


def run_dynamic(avatar: str, lines: list[tuple[str, str]], conns: int, total: int,
                stall_after: float = 8.0) -> tuple[float, dict]:
    """**共享块队列**：所有线程从同一个队列领块，快的自然领得多；
    某条线路连续 `stall_after` 秒没拿到数据 ⇒ 把它从队列里**踢出去**（动态淘汰）。"""
    queue: list[int] = list(range(0, total, BLOCK))
    cursor = 0
    lock = threading.Lock()
    got = {name: 0 for name, _ in lines}
    alive = {name: True for name, _ in lines}
    last_progress = {name: time.time() for name, _ in lines}
    started = time.time()

    def next_block() -> int | None:
        nonlocal cursor
        with lock:
            if cursor >= len(queue):
                return None
            value = queue[cursor]
            cursor += 1
            return value

    def worker(name: str, prefix: str) -> None:
        while True:
            # 停滞淘汰：轮到自己时先看看还能不能用（至少留一条线路活着）
            with lock:
                living = [key for key, value in alive.items() if value]
                if not alive[name]:
                    return
                if len(living) > 1 and time.time() - last_progress[name] > stall_after:
                    alive[name] = False
                    return
            offset = next_block()
            if offset is None:
                return
            size = fetch(f"{prefix}{avatar}" if prefix else avatar, offset, min(BLOCK, total - offset))
            if size <= 0:
                with lock:
                    alive[name] = False
                return
            with lock:
                got[name] += size
                last_progress[name] = time.time()

    threads = [threading.Thread(target=worker, args=(name, prefix), daemon=True)
               for name, prefix in lines for _ in range(max(1, conns // max(1, len(lines))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return (sum(got.values()) / 1024 / 1024) / max(time.time() - started, 0.001), got


def main() -> int:
    parser = argparse.ArgumentParser(description="混合 / 动态并发对照实验")
    parser.add_argument("--asset", default=DEFAULT_ASSET)
    parser.add_argument("--mb", type=float, default=8.0, help="总数据量 MB（默认 8）")
    parser.add_argument("--conns", type=int, default=12, help="总连接数（默认 12）")
    parser.add_argument("--lines", default="", help="用哪些线路（逗号分隔名字，默认内置三条）")
    args = parser.parse_args()

    lines = DEFAULT_LINES
    if args.lines:
        wanted = {item.strip() for item in args.lines.split(",") if item.strip()}
        lines = [item for item in lines if item[0] in wanted]
    total = int(args.mb * 1024 * 1024)

    print(f"测速文件：{args.asset}")
    print(f"总量 {args.mb:.0f} MB / 总连接 {args.conns} / 块 {BLOCK // 1024} KB\n")

    fastest = lines[0]
    speed, got = run_static(args.asset, [fastest], args.conns, total)
    print(f"① 单线路并发（{fastest[0]}，{args.conns} 连接）      {speed:6.3f} MB/s   {sum(got.values()) // 1024} KB")

    speed, got = run_static(args.asset, lines, args.conns, total)
    print(f"② 多线路**静态等分**（{len(lines)} 条各 {max(1, args.conns // len(lines))} 连接）"
          f"   {speed:6.3f} MB/s   " + "  ".join(f"{k}:{v // 1024}KB" for k, v in got.items()))

    speed, got = run_dynamic(args.asset, lines, args.conns, total)
    print(f"③ 多线路**动态抢块**（共享队列 + 停滞淘汰）    {speed:6.3f} MB/s   "
          + "  ".join(f"{k}:{v // 1024}KB" for k, v in got.items()))

    print("\n注：③ 的每线路字节数就是「动态分配」的实际结果 —— 快的拿得多、停滞的会被踢掉。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
