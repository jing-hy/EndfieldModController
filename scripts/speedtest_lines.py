#!/usr/bin/env python
"""测每条 GitHub 加速线路的**单连接 / 4 连接 / 8 连接**下载速度，给出综合排序。

**为什么必须测并发**（用户 2026-10-03 的实测结论，香蕉网那次）：
| 状态 | 单连接 | 4 连接 | 16 连接 |
|---|---|---|---|
| 无 VPN 直连 | 0.008 MB/s | 0.034（4.3×） | **0.104（13×）** |
| 开 VPN | 0.129 MB/s | 0.090（**0.7×**） | **0.641（5×）** |
⇒ **并发收益极大，而且越慢的线路收益越大**；只看单连接速度会把能跑的线路排错。

用法：
    python scripts/speedtest_lines.py                 # 测内置线路表
    python scripts/speedtest_lines.py --mb 4          # 每组总数据量（默认 2 MB）
    python scripts/speedtest_lines.py --only gh.nxnow.top,ghproxy.net
    python scripts/speedtest_lines.py --asset <URL>   # 换测速用的文件

测的是**我们真正要下的东西**（Release 资产，走 Range 分块），所以结果可以直接用来排序。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time
import urllib.error
import urllib.request

DEFAULT_ASSET = ("https://github.com/jing-hy/EndfieldModController/releases/download/"
                 "v1.0.5/EndfieldModController.exe")
# (标签, 前缀) —— 前缀空 = 直连
DEFAULT_LINES: list[tuple[str, str]] = [
    ("直连", ""),
    ("gh.nxnow.top", "https://gh.nxnow.top/"),
    ("ghproxy.net", "https://ghproxy.net/"),
    ("gh-proxy.com", "https://gh-proxy.com/"),
    ("github.moeyy.xyz", "https://github.moeyy.xyz/"),
    ("gh.llkk.cc", "https://gh.llkk.cc/"),
    ("gh.ddlc.top", "https://gh.ddlc.top/"),
    ("ghproxy.cn", "https://ghproxy.cn/"),
    ("gh-proxy.net", "https://gh-proxy.net/"),
]
# (连接数, 每连接拿多少 MB)
GROUPS = ((1, 2.0), (4, 0.5), (8, 0.25))
TIMEOUT = 25.0


def _fetch(url: str, start: int, length: int, timeout: float = TIMEOUT) -> tuple[int, float]:
    """取 [start, start+length) 这一段，返回（字节数, 秒）。失败返回 (0, 秒)。"""
    req = urllib.request.Request(url, headers={
        "Range": f"bytes={start}-{start + length - 1}",
        "User-Agent": "EndfieldModController-speedtest/1.0",
    })
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return len(data), time.time() - started
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return 0, time.time() - started


def measure(prefix: str, asset: str, conns: int, per_conn_mb: float) -> tuple[float, int]:
    """跑一组并发下载，返回（MB/s, 实际拿到的字节数）。"""
    url = f"{prefix}{asset}" if prefix else asset
    chunk = int(per_conn_mb * 1024 * 1024)
    started = time.time()
    got = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=conns) as pool:
        futures = [pool.submit(_fetch, url, index * chunk, chunk) for index in range(conns)]
        for future in concurrent.futures.as_completed(futures):
            size, _ = future.result()
            got += size
    elapsed = max(time.time() - started, 0.001)
    return (got / 1024 / 1024) / elapsed, got


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub 加速线路并发测速")
    parser.add_argument("--asset", default=DEFAULT_ASSET)
    parser.add_argument("--mb", type=float, default=0.0, help="每组总数据量 MB（默认按内置分档）")
    parser.add_argument("--only", default="", help="只测这些线路（逗号分隔的名字）")
    args = parser.parse_args()

    lines = DEFAULT_LINES
    if args.only:
        wanted = {item.strip().lower() for item in args.only.split(",") if item.strip()}
        lines = [item for item in lines if item[0].lower() in wanted]

    groups = GROUPS
    if args.mb > 0:
        groups = tuple((conns, args.mb / conns) for conns, _ in GROUPS)

    print(f"测速文件：{args.asset}")
    print(f"分组：{', '.join(f'{c}连接×{mb:.2f}MB' for c, mb in groups)}   超时 {TIMEOUT:.0f}s\n")
    header = f"{'线路':<20}" + "".join(f"{c}连接".rjust(12) for c, _ in groups) + "   最佳    综合"
    print(header)
    print("-" * len(header))

    rows: list[tuple[float, str, list[float]]] = []
    for name, prefix in lines:
        speeds: list[float] = []
        for conns, per in groups:
            mbps, got = measure(prefix, args.asset, conns, per)
            speeds.append(mbps)
            sys.stdout.write("." if got else "x")
            sys.stdout.flush()
        best = max(speeds) if speeds else 0.0
        # 综合分：最佳速度为主，四连接那档给一点权重（它最能代表"真下整包"的体验）
        score = best + (speeds[1] if len(speeds) > 1 else 0.0) * 0.5
        rows.append((score, name, speeds))
        print(f"\r{name:<20}" + "".join(f"{value:>11.3f} " for value in speeds)
              + f"{best:>7.3f} {score:>7.3f}")

    print("\n=== 按综合表现排序（可直接照这个顺序写进 DEFAULT_LINES）===")
    for rank, (score, name, speeds) in enumerate(sorted(rows, reverse=True), 1):
        best = max(speeds) if speeds else 0.0
        flag = "✓" if best >= 0.05 else ("慢" if best > 0 else "✗ 不可用")
        print(f"{rank}. {name:<20} 最佳 {best:5.3f} MB/s   {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
