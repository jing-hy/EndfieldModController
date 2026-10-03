"""香蕉网（GameBanana）下载测速 —— 开/不开 VPN 都能跑，结果可直接对照。

用法（在任意一台机器上，VPN 开着或关着都行）：

    python scripts/speedtest_gamebanana.py

输出三组对照：单连接 4 MB、4 连接、16 连接。**同一台机器、同一条线路**下跑两遍
（关 VPN 一遍、开 VPN 一遍），就能回答两个问题：
  ① VPN 到底提升多少；
  ② 并发在 VPN 环境下还有没有用（旧结论是"并发反而慢 24%"，那是开着 VPN 测的）。

背景（2026-10-03 无 VPN 实测）：
    单连接   0.008 MB/s
    4 连接   0.034 MB/s   （4.3 倍）
    16 连接  0.104 MB/s   （13 倍，16 条连接全部拿到数据）
—— 恰恰是最慢的线路上并发收益最大，据此改掉了 `fastnet` 里"太慢就不许并发"的门槛。
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# 默认拿 RabbitFX 的页面里的某个大文件来测（改动小、稳定、无需登录）。
# 想测别的就改这两个常量。
GB_MOD_ID = 690864          # CharacterChange（有个 912 MB 的大文件）
UA = {"User-Agent": "Mozilla/5.0"}


def _pick_large_file() -> tuple[str, str, int]:
    """从页面里挑最大的那个文件来测（返回 url / 文件名 / 字节数）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from endfieldmodcontroller import moddl

    profile = moddl.gamebanana_profile(GB_MOD_ID)
    main, _aux = moddl.split_mod_files(profile["files"])
    if main is None:
        raise SystemExit("这个页面里没有可下载的文件")
    return main["url"], main["file"], int(main.get("size") or 0)


def _single(url: str, nbytes: int, timeout: int = 25) -> tuple[int, float, str]:
    req = urllib.request.Request(url, headers={**UA, "Range": f"bytes=0-{nbytes - 1}"})
    t0 = time.time()
    got = 0
    err = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            while got < nbytes:
                chunk = r.read(262144)
                if not chunk:
                    break
                got += len(chunk)
    except Exception as exc:  # noqa: BLE001
        err = type(exc).__name__
    return got, time.time() - t0, err


def _parallel(url: str, nthreads: int, each: int = 524288, timeout: int = 25) -> tuple[int, float, int]:
    res: list[tuple[int, float]] = []

    def worker(i: int) -> None:
        begin = i * each
        req = urllib.request.Request(
            url, headers={**UA, "Range": f"bytes={begin}-{begin + each - 1}"})
        t0 = time.time()
        got = 0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                while got < each:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    got += len(chunk)
        except Exception:  # noqa: BLE001
            pass
        res.append((got, time.time() - t0))

    t0 = time.time()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(nthreads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    return sum(g for g, _ in res), wall, len([1 for g, _ in res if g > 0])


def main() -> int:
    print("== 香蕉网下载测速 ==")
    for host in ("gamebanana.com", "images.gamebanana.com"):
        try:
            t0 = time.time()
            ip = socket.gethostbyname(host)
            print(f"  DNS {host} -> {ip}  ({(time.time() - t0) * 1000:.0f} ms)")
        except Exception as exc:  # noqa: BLE001
            print(f"  DNS {host} 失败：{exc}")

    try:
        url, name, size = _pick_large_file()
    except Exception as exc:  # noqa: BLE001
        print(f"  取文件清单失败（香蕉网访问不上？）：{type(exc).__name__}: {exc}")
        return 1
    print(f"  测试文件：{name}  {size / 1048576:.1f} MB")
    print()

    results = {}
    got, dt, err = _single(url, 4 * 1048576)
    mbps = got / 1048576 / max(dt, 1e-6)
    results["single"] = mbps
    print(f"  单连接 4MB  : {got / 1048576:6.2f} MB / {dt:7.1f}s = {mbps:7.3f} MB/s  {err}")

    for n in (4, 16):
        got, dt, ok = _parallel(url, n)
        mbps = got / 1048576 / max(dt, 1e-6)
        results[f"conn{n}"] = mbps
        print(f"  {n:2d} 连接并发 : {got / 1048576:6.2f} MB / {dt:7.1f}s = {mbps:7.3f} MB/s"
              f"  （{ok}/{n} 条有数据）")

    base = results.get("single") or 0
    print()
    if base > 0:
        for key in ("conn4", "conn16"):
            if key in results:
                n = key.replace("conn", "")
                print(f"  {n} 连接 / 单连接 = {results[key] / base:.1f} 倍")
    print()
    print("  （把这段输出连同『当时 VPN 开没开』一起发回来即可）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
