"""极轻量的下载加速：**平时不用，慢/抖时才临时上，用完立刻放掉**。

借鉴 [SteamTools / Watt Toolkit](https://github.com/BeyondDimension/SteamTools) 的思路，
但只取其中**不需要装证书、不需要常驻服务、不改系统**的那一条：

* SteamTools 用本地反代（Titanium-Web-Proxy）给整个浏览器加速 —— 常驻、要对系统
  装根证书、还要改 hosts，属于"重型加速"；
* 本项目只需要把自己那几个下载跑稳，所以只借它"**单条链路慢就换多条链路**"的核心
  思路，做成进程内的下载器：默认**单连接**，一旦发现慢（低于阈值）或抖动（读超时），
  临时切成**多连接分块并发**，每块独立重试；下载结束线程池即销毁，不留后台、不复用、
  不写 hosts、不起代理。

实测（27.5 MB 的 Release exe，同一 URL）：

    单线程 #1   6.36s   4.33 MB/s
    单线程 #2  35.61s   0.77 MB/s     ← 连接不稳，差 5.6 倍
    8 线程分块 10.62s   2.59 MB/s     ← 把最坏情况压下来
    16 线程    7.42s   3.71 MB/s

结论：并发分块的收益**不是"绝对更快"，而是"更稳"**，所以做成"按需启用"而不是
一直开着 —— 与用户要求一致：「在连接不稳或下载速度不足的时候用，然后用完马上关掉」。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .version import USER_AGENT

# 低于这个速度判定为"链路慢"，值得临时上并发
SLOW_MBPS = 1.5
# 先用这么多字节探一下单连接到底有多快
PROBE_BYTES = 1 << 20
# 小于这个体积不值得并发（小文件起线程的损耗大于收益）
MIN_PARALLEL_BYTES = 4 << 20
# 每块大小 / 最大线程数
CHUNK_BYTES = 2 << 20
# ── 照 PCL（ModNet.vb `TryBeginThread`）的分片策略（2026-10-03）──────────────
# PCL 不预先切死：它每次要开新线程时去找**当前最大的未完成碎片**，从它的
# `DownloadEnd - DownloadUndone * 0.4` 处切开，并且用 `FilePieceLimit` 兜底。
# 我们这边线程数在开始时就定了，所以把那套意图落成两条等价规则：
#   * **每线程至少 PIECES_PER_THREAD 块** —— 收尾时不会有"最后一个巨块"拖后腿；
#   * **块数不超过 MAX_PIECES** —— 大文件别切成上千个碎块（请求开销反而更大）。
PIECES_PER_THREAD = 4
MAX_PIECES = 256
MAX_THREADS = 20
READ_CHUNK = 262144
# 单次读多久没数据算"抖动/卡死"，切并发续传
STALL_SECONDS = 20
# 探测连接的超时（要短，坏线路要快速跳过；实测直连会直接超时 15s，白等太久）
PROBE_TIMEOUT = 8
# 探测阶段的时间上限：慢线路不能把探测拖成几十秒
PROBE_SECONDS = 12
# 探测速度低于此值就直接放弃这条线路（连并发都不值得起）
DEAD_MBPS = 0.3
# 低于这个速度**连并发都别上**：实测（2026-10-02，用户开 VPN 的家宽）同一个 6.6 MB 文件，
# 探测 0.036 MB/s 时 —— 单连接 0.229 MB/s、8 连接只有 0.174 MB/s（**并发反而慢 24%**）。
# 并发只对"本来就还行、只是慢"的线路有效（历史上 0.71 → 3.96 MB/s 那次），
# 对**极慢**的线路纯粹是抢带宽 + 反复建连。
BOOST_FLOOR_MBPS = 0.1
# 并发**试用窗口**：上并发先跑这么久，然后拿实测速度跟单连接探测值比 ——
# 不划算就切回单连接（用户 2026-10-02：「应该动态，慢就并发，更慢就切回来」）。
BOOST_TRIAL_SECONDS = 12
# 并发要"值得继续"至少得比单连接快这么多倍（1.1 = 快 10%）
BOOST_KEEP_RATIO = 1.1
# 多线路时单条线路的等待上限
LINE_TIMEOUT_MULTI = 15
# 某条线路失败后多久再试
# （别设太长：一次偶发失败——比如网络抖动导致 DNS 解析失败——就把最快的线路
#   封掉半小时，反而会让用户只能退到慢线路，这正是"感觉还是很慢"的原因之一）
LINE_FAIL_TTL = 5 * 60
# 连续失败几次才把线路临时封掉
LINE_FAIL_THRESHOLD = 2
# **HTTPS 证书不匹配**的线路要封得久一点：它不是"网络抖动"，而是这个网络端对这条线路
# 做了劫持/篡改（或镜像域名失配），同一网络里不会自愈，每次重试都必然失败。
# 2026-10-01 issue #6 实证：反馈者那边 `https://ghproxy.net/` 返回的证书不含 ghproxy.net
# （`Hostname mismatch`）—— 而我这边同一时刻实测它是 200 正常的，所以**不能因此删掉这条线路**，
# 只能在他那种网络下快速跳过。
LINE_CERT_FAIL_TTL = 30 * 60
# 403/429（限流）单独一档：它是**临时**状态，不该跟证书错误一样冷却半小时
# （多角度审查：复用 30 分钟会把很快恢复的镜像错误排除掉）。
LINE_RATE_LIMIT_TTL = 5 * 60

# ── 照 PCL（ModNet.vb `TryBeginThread` / `SourceFail`）补的两条判据 ─────────
#
# ① **有些源不要分片**：PCL 对 `github.com` / `bmclapi` / `pcl2-server` 这类源**强制单线程** ——
#    它们按连接数限流或干脆限速，开多线程只会更容易被拒、总速度还更慢。
#    注意这里比的是**主机名**（精确后缀），所以 `gh.xmly.dev` 这种镜像**不受影响**、照常分片。
NO_SPLIT_HOSTS = (
    "github.com", "githubusercontent.com", "githubassets.com",
    "bmclapi2.bangbang93.com", "pcl2-server", "meloong.com",
    "optifine.net", "momot.rs",
)

# ② **被限流/拒绝要算这条线路自己的账**：PCL 的做法是 `403/429` 就禁用该源
#    （`SourceFail` 里 `(403)`/`(429)` 直接 `SourcesOnce.Remove`）。
#    否则每次下载都要白试一遍被限的线路，用户看到的就是"卡在 0%"。
RATE_LIMIT_MARKERS = ("403", "429", "too many requests", "rate limit", "forbidden")


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _may_parallel(url: str) -> bool:
    """这个源允许分片吗？（PCL：上面那批主机强制单线程）"""
    host = _host_of(url)
    if not host:
        return True
    for blocked in NO_SPLIT_HOSTS:
        if host == blocked or host.endswith("." + blocked):
            return False
    return True


def _looks_rate_limited(message: str) -> bool:
    """这条线路是不是"被拒/被限流"？（确定性失败，应当记账并快速跳过）"""
    text = (message or "").lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)
# 线路成绩缓存（下次优先用快的），只放几 KB，不常驻
LINE_CACHE = "_net/lines.json"
BASE_HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}

POLICIES = ("auto", "always", "never")
# 下载线路策略：auto=直连优先，慢/断才切镜像；direct=只直连；mirror=只用镜像
LINE_MODES = ("auto", "direct", "mirror")

Progress = Callable[[int, int], None] | None
Log = Callable[[str], None] | None


# ---------------------------------------------------------------------------
# 下载线路（借鉴 SteamTools「换一条链路」的思路，但不装证书、不起常驻服务）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Line:
    name: str
    prefix: str = ""

    def apply(self, url: str) -> str:
        return url if not self.prefix else f"{self.prefix}{url}"


DIRECT = Line("直连")
# 2026-09-27 在**关闭 Steam++ 加速器**的裸网络实测：
#   直连 ✗ 20s 超时；gh.xmly.dev ✓ 0.49 MB/s；ghproxy.net ✓ 0.17；gh-proxy.com ✓ 0.14；
#   ghfast.top / mirror.ghproxy.com / hub.gitmirror.com / ghproxy.cc 全部不可用。
# 镜像会失效，所以失败会被记进缓存并在一段时间内跳过，且**绝不作为首选**。
DEFAULT_LINES: tuple[Line, ...] = (
    DIRECT,
    Line("gh.xmly.dev", "https://gh.xmly.dev/"),
    Line("ghproxy.net", "https://ghproxy.net/"),
    Line("gh-proxy.com", "https://gh-proxy.com/"),
)


@dataclass
class DownloadReport:
    ok: bool = True
    path: str = ""
    bytes: int = 0
    seconds: float = 0.0
    mbps: float = 0.0
    boosted: bool = False          # 本次是否真的启用了并发加速
    reason: str = ""               # 为什么启用/没启用
    threads: int = 0
    probe_mbps: float = 0.0
    retries: int = 0
    resumed_from: int = 0
    line: str = ""                 # 最终成功的是哪条线路
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "path": self.path, "bytes": self.bytes,
            "seconds": round(self.seconds, 2), "mbps": round(self.mbps, 2),
            "boosted": self.boosted, "reason": self.reason, "threads": self.threads,
            "probe_mbps": round(self.probe_mbps, 2), "retries": self.retries,
            "resumed_from": self.resumed_from, "line": self.line, "message": self.message,
        }


# 全局：当前是否有加速下载在跑（给界面显示"加速中 / 已关闭"）
_STATE_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"active": 0, "last": None, "policy": "auto", "line_mode": "auto"}


def set_policy(policy: str) -> None:
    with _STATE_LOCK:
        _STATE["policy"] = policy if policy in POLICIES else "auto"


def get_policy() -> str:
    with _STATE_LOCK:
        return str(_STATE.get("policy") or "auto")


def set_line_mode(mode: str) -> None:
    with _STATE_LOCK:
        _STATE["line_mode"] = mode if mode in LINE_MODES else "auto"


def get_line_mode() -> str:
    with _STATE_LOCK:
        return str(_STATE.get("line_mode") or "auto")


def status() -> dict[str, Any]:
    """界面用：加速是否正在进行、上一次的结果。"""
    with _STATE_LOCK:
        return {
            "policy": _STATE.get("policy"),
            "line_mode": _STATE.get("line_mode"),
            "active": int(_STATE.get("active") or 0),
            "boosting": bool(_STATE.get("active")),
            "last": _STATE.get("last"),
        }



def _log(log: Log, message: str) -> None:
    if log:
        log(message)


# ---------------------------------------------------------------------------
# 代理：VPN / 加速器大多**只对浏览器生效**（浏览器插件代理，或者系统代理开关没开）
# —— 那样本程序的下载就是**直连**，于是出现"浏览器秒下、程序慢得动不了"。
# 用户 2026-10-02 实机确认：`ProxyEnable=0`、无环境变量、`getproxies()` 为空 ⇒ 程序当时
# 确实没走任何代理。这里给出三条来源（优先级从高到低）：
#   ① 用户在设置页填的「下载代理」；
#   ② 环境变量 `HTTPS_PROXY` / `HTTP_PROXY`（命令行党的标准做法）；
#   ③ 系统代理（`urllib.request.getproxies()`，含 Windows 的 IE 代理设置）。
# 一条都没有 ⇒ 直连（保持原行为）。
# ---------------------------------------------------------------------------
_PROXY: str = ""


def set_proxy(value: str | None) -> None:
    """设置下载用的代理（`http://127.0.0.1:7890` 这种；留空 = 回到自动判断）。"""
    global _PROXY
    _PROXY = (value or "").strip()


def get_proxy() -> str:
    """当前生效的代理：用户填的 → 环境变量 → 系统代理 → 空（直连）。"""
    if _PROXY:
        return _PROXY
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    try:
        proxies = urllib.request.getproxies()
    except Exception:  # noqa: BLE001
        return ""
    return (proxies.get("https") or proxies.get("http") or "").strip()


def proxy_in_use() -> str:
    """给界面/日志用：现在到底走不走代理、走哪条。"""
    return get_proxy()


def _mbps(size: int, seconds: float) -> float:
    return (size / 1048576.0 / seconds) if seconds > 0 else 0.0


def _open(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30):
    request = urllib.request.Request(url, headers={**BASE_HEADERS, **(headers or {})})
    proxy = get_proxy()
    if proxy:
        # 显式走代理：http 与 https 都指到同一个地址（本地代理一般都同时支持 CONNECT）
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def probe(url: str, *, timeout: int = 30) -> tuple[int, bool, str]:
    """返回 (总大小, 是否支持 Range, 最终 URL)。"""
    try:
        with _open(url, headers={"Range": "bytes=0-0"}, timeout=timeout) as response:
            final = response.geturl()
            content_range = response.headers.get("Content-Range") or ""
            length = response.headers.get("Content-Length") or "0"
            response.read()
        if content_range and "/" in content_range:
            total = int(content_range.rsplit("/", 1)[1])
            return total, True, final
        return int(length), False, final
    except (urllib.error.URLError, OSError, ValueError):
        pass
    try:
        with _open(url, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            ranges = (response.headers.get("Accept-Ranges") or "").lower() == "bytes"
            return total, ranges, response.geturl()
    except (urllib.error.URLError, OSError, ValueError):
        return 0, False, url


def fetch(
    url: str,
    *,
    timeout: int = 25,
    headers: dict[str, str] | None = None,
    line_mode: str = "",
) -> tuple[str, bytes]:
    """按线路取一小段内容（HTML/JSON 这类小请求），返回 ``(最终 URL, 内容)``。

    直连不通时会自动换镜像线路 —— 这是"**不消耗 GitHub API 额度**地读 release 页面"
    的关键：普通用户没有 token，API 只有 60 次/小时，靠网页路线才稳。
    """
    mode = (line_mode or get_line_mode() or "auto").lower()
    if mode not in LINE_MODES:
        mode = "auto"
    lines = resolve_lines(url, mode)
    last_error: Exception | None = None
    for line in lines:
        try:
            with _open(line.apply(url), headers=headers, timeout=timeout) as response:
                body = response.read()
                final = response.geturl()
            _remember_line(line.name, True, 0.0)   # 成功只清失败标记，不覆盖速度成绩
            return final, body
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            _remember_line(line.name, False, 0.0)
            continue
    raise OSError(f"所有线路都取不到 {url}：{last_error}")


class Cancelled(Exception):
    """用户主动停下（点了「终止」或「暂停」）—— 不是网络故障，别当失败上报。"""


def _download_sequential(
    url: str,
    dest: Path,
    *,
    offset: int = 0,
    total: int = 0,
    timeout: int = 60,
    progress: Progress = None,
    log: Log = None,
    stop_after: int = 0,
    deadline_seconds: float = 0,
    cancel: Callable[[], bool] | None = None,
) -> tuple[int, bool, str]:
    """单连接下载（offset 起）。

    返回 (本次写入字节数, 是否被"卡住"打断, 说明)。
    stop_after > 0 时下够这么多字节就主动停下（用于测速探测）；
    deadline_seconds > 0 时超过该秒数也停下 —— 慢线路（实测直连 0.05 MB/s
    下 1 MB 要 20 秒）不能让它把探测拖成几十秒。
    cancel 返回 True 时抛 `Cancelled`（每个数据块检查一次，够快也够省）。
    """
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    written = 0
    mode = "ab" if offset else "wb"
    started = time.time()
    try:
        with _open(url, headers=headers, timeout=timeout) as response:
            with open(dest, mode) as fh:
                while True:
                    if cancel and cancel():
                        raise Cancelled("用户终止")
                    # ⚠️ 把 socket 超时压到"块间停顿"这个尺度（2026-10-03）：
                    # 只影响"等下一块"的等待，不会误杀慢速但活着的连接（慢线路只是块间隔长，
                    # 仍在持续给数据）。超时会抛 `TimeoutError`，由下面 except 统一转成
                    # `stalled=True` ⇒ 上层自动换镜像线路。
                    # 不这么做的话，遇到"服务器建了连接却吊着不发数据"，`read()` 会一直阻塞：
                    # 没有进度、没有换线路、日志停在"开始下载 X（138.0 MB）"—— 用户实测就是这样。
                    try:
                        _sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                        if _sock is not None:
                            _sock.settimeout(CHUNK_GAP_SECONDS)
                    except Exception:  # noqa: BLE001 - 拿不到底层 socket 就保持原样
                        pass
                    chunk = response.read(READ_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(offset + written, total)
                    if stop_after and written >= stop_after:
                        return written, False, "probe"
                    if deadline_seconds and (time.time() - started) > deadline_seconds:
                        return written, False, (
                            f"探测超时（{deadline_seconds:.0f}s 内只下到 {written / 1048576:.1f} MB）")
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        if written:
            # `stalled=True` ⇒ 上层会判定这条线路不行并**自动换镜像线路**（这正是我们要的）
            return written, True, f"读取中断（已下 {written / 1048576:.1f} MB）: {exc}"
        if isinstance(exc, TimeoutError):
            # 一个字节都没收到就超时 ⇒ 同样算"线路不通"，交上层换线路。
            # 别 `raise` 出去把整次下载打成失败（那样用户只看到一句报错、也没有重试）。
            return 0, True, f"连接建立后 {CHUNK_GAP_SECONDS}s 内没有收到任何数据（线路不通）"
        raise
    return written, False, ""


def _parts_path(dest: Path) -> Path:
    """分块下载的"已完成块"记录（**存在这个文件 = 还没下完**）。

    为什么需要它：文件本体是"边下边 seek 写"的，预分配或空洞都会让文件大小看着
    正好等于总量 —— 所以**文件大小不能代表完整性**，完整性一律以这个 sidecar
    是否还在为准。
    """
    return dest.with_name(dest.name + ".mcparts.json")


def has_partial_parts(dest: Path) -> bool:
    return _parts_path(dest).is_file()


def _load_parts(dest: Path, size: int) -> set[tuple[int, int]]:
    try:
        data = json.loads(_parts_path(dest).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict) or int(data.get("total") or 0) != size:
        return set()
    spans: set[tuple[int, int]] = set()
    for item in data.get("done") or []:
        try:
            spans.add((int(item[0]), int(item[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return spans


def _save_parts(dest: Path, size: int, spans: set[tuple[int, int]]) -> None:
    try:
        _parts_path(dest).write_text(
            json.dumps({"total": size, "done": sorted(spans)}), encoding="utf-8", newline="\n")
    except OSError:
        pass


def _clear_parts(dest: Path) -> None:
    try:
        _parts_path(dest).unlink()
    except OSError:
        pass


def _download_parallel(
    url: str,
    dest: Path,
    *,
    size: int,
    start: int,
    threads: int,
    chunk: int = CHUNK_BYTES,
    timeout: int = 60,
    progress: Progress = None,
    log: Log = None,
    max_seconds: float = 0,
    cancel: Callable[[], bool] | None = None,
) -> int:
    """并发分块下载，**块级断点续传**：已完成的块记在 sidecar 里，中断后不重下。

    start：没有块记录时（单连接顺序下载的残留）把前 start 字节视为已完成。
    max_seconds > 0：**试用窗口** —— 到点就不再提交新块（在跑的让它跑完），
    用于"先试试并发到底有没有用，没用就切回单连接"（见 `_attempt_line` 的②段）。
    """
    # 块大小跟着线程数与文件大小走（PCL 的分片意图见上面的常量注释）。
    # 原来固定 2 MB：大文件会切成上千块（每块一次 Range 请求），
    # 而且线程数一多，尾部总有几个块在单独跑、其它线程空转。
    piece_chunk = max(CHUNK_BYTES, -(-size // max(1, threads * PIECES_PER_THREAD)))
    piece_chunk = max(piece_chunk, -(-size // MAX_PIECES))
    spans = [(pos, min(pos + piece_chunk - 1, size - 1)) for pos in range(0, size, piece_chunk)]
    done_spans = _load_parts(dest, size)
    if not done_spans and start > 0:
        done_spans = {(a, b) for a, b in spans if b < start}
    # **长块优先**：对应 PCL 的"寻找最大碎片"——先让大块开跑，
    # 避免收尾时剩一个大块、其它线程都在空转（那是最典型的"最后 5% 特别慢"）。
    todo = sorted((s for s in spans if s not in done_spans),
                  key=lambda sp: sp[1] - sp[0], reverse=True)

    lock = threading.Lock()
    state = {"n": sum(b - a + 1 for a, b in done_spans), "retries": 0}
    if not dest.exists():
        dest.touch()
    _save_parts(dest, size, done_spans)
    if progress:
        progress(min(state["n"], size), size)
    if done_spans:
        _log(log, f"续传：已完成 {state['n'] // 1048576} MB / {size // 1048576} MB，"
                  f"还需下 {len(todo)} 块")

    def fetch(span: tuple[int, int]) -> None:
        begin, end = span
        last_error: Exception | None = None
        for attempt in range(4):
            if cancel and cancel():
                raise Cancelled("用户终止")
            try:
                headers = {"Range": f"bytes={begin}-{end}"}
                with _open(url, headers=headers, timeout=timeout) as response:
                    # ⚠️⚠️ **必须分块读 + 单块间隔超时**（2026-10-03 修「下载到一半一直不动」）。
                    # 原来是 `data = response.read()` **一次性读整块** —— 那个调用只在
                    # `timeout` 到点或数据读完时才返回，**中途一个字节都不给就无限期挂着**，
                    # 单连接那条路的 `CHUNK_GAP_SECONDS` 保护在这里完全不生效。
                    # 实测现场：912 MB 的包切了 20 个并发连接，**全部挂起**，
                    # sidecar 里 `done: []`（一个块都没完成），文件停在 768 KB 不动，
                    # 日志里连一条重试都没有（因为失败路径不记日志）。
                    # 现在跟单连接一个规格：每读一小块就重设"多久没数据算卡死"。
                    try:
                        response.fp.raw._sock.settimeout(CHUNK_GAP_SECONDS)  # type: ignore[attr-defined]
                    except (AttributeError, OSError):
                        pass
                    buf = bytearray()
                    while True:
                        chunk = response.read(READ_CHUNK)
                        if not chunk:
                            break
                        buf.extend(chunk)
                    data = bytes(buf)
                if len(data) != end - begin + 1:
                    raise OSError(f"分块长度不符：{len(data)} != {end - begin + 1}")
                # 每个线程自己开句柄 + seek，互不干扰
                with open(dest, "r+b") as fh:
                    fh.seek(begin)
                    fh.write(data)
                with lock:
                    done_spans.add(span)
                    state["n"] += len(data)
                    _save_parts(dest, size, done_spans)   # 每块都落盘，断电也不白下
                    if progress:
                        progress(min(state["n"], size), size)
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_error = exc
                with lock:
                    state["retries"] += 1
                    retry_no = state["retries"]
                # ⚠️ **失败必须可见**（原来这条路径一声不响：20 个连接全挂、日志里什么都没有，
                # 用户只能看到"下载中但进度条不动"）。前几次记一条，避免刷屏。
                if retry_no <= 6:
                    _log(log, f"分块 {begin}-{end} 第 {attempt + 1} 次失败：{exc}")
                time.sleep(0.4 * (attempt + 1))
        raise OSError(f"分块 {begin}-{end} 重试 4 次仍失败：{last_error}")

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(threads, len(todo)))) as pool:
            futures = []
            deadline = (time.time() + max_seconds) if max_seconds else 0.0
            for index, span in enumerate(todo):
                # 试用窗口到点：不再提交新块（已经在跑的等它跑完），剩下的留给调用方决定
                if deadline and index >= max(1, min(threads, len(todo))) and time.time() > deadline:
                    break
                futures.append(pool.submit(fetch, span))
            for future in futures:
                future.result()
    if len(done_spans) >= len(spans):
        _clear_parts(dest)      # 块齐了才算下完
    return state["retries"]


def recommended_threads(size: int) -> int:
    """按体积给并发数。

    2026-09-27 实测（27.6 MB、镜像线路 gh.xmly.dev）：
        单连接 0.71 MB/s → 8 连接 3.21 MB/s → 16 连接 3.96 MB/s
    即并发是主要提速手段（5.6 倍），所以这里给得比以前大方；
    同时实测"多线路混合"反而更慢（被慢线路拖累），所以只加连接、不铺线路。
    """
    by_size = max(1, size // (1536 * 1024))          # 每 1.5 MB 一个连接
    return int(max(8, min(MAX_THREADS, by_size)))


# ---------------------------------------------------------------------------
# 线路选择（直连优先；慢/断才切镜像；成绩缓存起来，下次先试快的）
# ---------------------------------------------------------------------------
def _cache_path() -> Path:
    from .config import PROJECT_ROOT

    return PROJECT_ROOT / "runtime" / LINE_CACHE


def _load_lines_cache() -> dict[str, Any]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _remember_line(name: str, ok: bool, mbps: float, *, cert_error: bool = False,
                  rate_limited: bool = False) -> None:
    """记一条线路的成绩（几 KB 的 JSON，不常驻、可随时删）。

    cert_error=True 表示这次失败是 **HTTPS 证书不匹配**（不是超时/抖动）：那种失败是
    确定性的，所以直接把失败计数顶到阈值，配合更长的冷却一次就跳过它。
    """
    cache = _load_lines_cache()
    entry = cache.get(name) if isinstance(cache.get(name), dict) else {}
    if mbps > 0:
        entry["mbps"] = round(float(mbps), 3)
    entry["at"] = int(time.time())
    if ok:
        entry["ok"] = True
        entry.pop("fail_at", None)
        entry.pop("cert", None)
        entry["fails"] = 0        # 成功一次就把失败计数清零，避免历史失败累积成"永久封禁"
    else:
        entry["ok"] = False
        entry["fail_at"] = int(time.time())
        if cert_error:
            entry["cert"] = True
            entry["fails"] = max(int(entry.get("fails") or 0) + 1, LINE_FAIL_THRESHOLD)
        else:
            entry.pop("cert", None)
            entry["fails"] = int(entry.get("fails") or 0) + 1
    cache[name] = entry
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except OSError:
        pass


def clear_line_cache() -> None:
    try:
        _cache_path().unlink()
    except OSError:
        pass


def line_status() -> list[dict[str, Any]]:
    cache = _load_lines_cache()
    rows: list[dict[str, Any]] = []
    for line in DEFAULT_LINES:
        entry = cache.get(line.name) or {}
        rows.append({
            "line": line.name,
            "mbps": entry.get("mbps", 0.0),
            "ok": entry.get("ok"),
            "fails": entry.get("fails", 0),
            "at": entry.get("at", 0),
            "blocked": _line_blocked(line.name, cache),
        })
    return rows


def _line_blocked(name: str, cache: dict[str, Any]) -> bool:
    """某条线路是否要临时跳过。

    **只在连续失败达到阈值时才跳** —— 一次 DNS 抖动/超时不该把最快的那条线路封掉。
    例外：① **直连**的阈值是 1 —— 它失败通常是"这台机器根本连不上 GitHub"这种稳定事实，
    再试一次只会白等一个探测超时（实测每次约 8 秒）；② **证书不匹配**的线路阈值也是 1、
    冷却用 `LINE_CERT_FAIL_TTL`（见那里的注释）。
    """
    entry = cache.get(name) or {}
    cert = bool(entry.get("cert"))
    threshold = 1 if (name == DIRECT.name or cert) else LINE_FAIL_THRESHOLD
    if int(entry.get("fails") or 0) < threshold:
        return False
    fail_at = int(entry.get("fail_at") or 0)
    ttl = LINE_CERT_FAIL_TTL if cert else LINE_FAIL_TTL
    return bool(fail_at) and (time.time() - fail_at) < ttl


def _mirrorable(url: str) -> bool:
    """只有 github.com 的直链才能套镜像前缀。"""
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    return host in {"github.com", "www.github.com"}


def resolve_lines(url: str, mode: str) -> list[Line]:
    """按策略给出尝试顺序（只在需要时才有镜像）。"""
    if mode == "direct" or not _mirrorable(url):
        return [DIRECT]
    mirrors = list(DEFAULT_LINES[1:])
    if mode == "mirror":
        return mirrors or [DIRECT]
    cache = _load_lines_cache()
    # 有成绩的按速度排前面；失败的临时跳过；全被跳过时退回全部（不能因此不下）
    mirrors.sort(key=lambda line: -float((cache.get(line.name) or {}).get("mbps") or 0))
    fresh = [line for line in mirrors if not _line_blocked(line.name, cache)]
    # 直连连续失败过就跳过它 —— 否则每次都要白等一个探测超时（实测直连超时是 8 秒）
    head = [] if _line_blocked(DIRECT.name, cache) else [DIRECT]
    return [*head, *(fresh or mirrors)]


# ---------------------------------------------------------------------------
# 下载（导出给外部用的入口）
# ---------------------------------------------------------------------------
def download(
    url: str,
    dest: Path,
    *,
    log: Log = None,
    progress: Progress = None,
    timeout: int = 60,
    policy: str = "",
    force_boost: bool = False,
    expected_size: int = 0,
    expected_sha256: str = "",
    line_mode: str = "",
    dead_mbps: float | None = None,
    cancel: Callable[[], bool] | None = None,
) -> DownloadReport:
    """下载一个文件；慢/抖时**临时**启用并发分块，直连不通时**临时**换镜像线路。

    三件事都是按需的、用完即放的：并发线程池在函数内销毁，镜像只是本次替换 URL，
    不装证书、不改 hosts、不起代理、也没有后台线程残留。

    policy:    auto（默认，慢才并发）/ always（直接并发）/ never（只单连接）
    line_mode: auto（直连优先，慢/断才切镜像）/ direct（只直连）/ mirror（只用镜像）
    """
    policy = (policy or get_policy() or "auto").lower()
    if policy not in POLICIES:
        policy = "auto"
    if force_boost:
        policy = "always"
    mode = (line_mode or get_line_mode() or "auto").lower()
    if mode not in LINE_MODES:
        mode = "auto"
    # 「低于这个速度就放弃这条线路」的阈值在这里先归一化 —— **必须在任何分支之前**，
    # 因为 `policy="always"`（强制并发）会跳过下面整段探测逻辑，那里面才赋值的话
    # 就会 UnboundLocalError（2026-10-02 当场踩到）。
    dead_mbps = DEAD_MBPS if dead_mbps is None else max(0.0, float(dead_mbps))

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = resolve_lines(url, mode)
    started = time.time()
    errors: list[str] = []

    for line in lines:
        if len(lines) > 1:
            _log(log, f"尝试线路：{line.name}")
        # 多线路时单条线路的等待要短，坏线路要快速跳过
        line_timeout = timeout if len(lines) == 1 else min(timeout, LINE_TIMEOUT_MULTI)
        report = _attempt_line(
            line.apply(url), dest, line=line,
            log=log, progress=progress, timeout=line_timeout, policy=policy,
            expected_size=expected_size, expected_sha256=expected_sha256,
            dead_mbps=dead_mbps, cancel=cancel,
        )
        if report.ok:
            _remember_line(line.name, True, report.mbps)
            if line is not DIRECT:
                _log(log, f"直连不通，已临时改用镜像线路 {line.name}"
                          f"（第三方中转，仅用于公开文件，下载后会校验完整性）")
                report.reason = f"{report.reason}；经镜像线路 {line.name}".strip("；")
            report.line = line.name
            _set_speed(report, started)
            return report
        # 只有"这条线路自己的问题"才算它的账：DNS 解析失败 / 网络不可达属于**全网故障**
        # （所有线路都会一样），记进去只会把最快的好线路冤枉地封掉 —— 实测踩过：
        # gh.xmly.dev 因一次 DNS 抖动被跳过，结果只能退到最慢的那条（0.26 MB/s）。
        message = str(report.message)
        network_wide = ("getaddrinfo" in message or "Name or service not known" in message
                        or "No address associated" in message)
        # **HTTPS 证书不匹配**：这条线路在这个网络下被劫持/域名失配，是确定性失败，
        # 一次就该跳过（否则每次下载都要白试一遍）。2026-10-01 issue #6 实证。
        cert_error = ("CERTIFICATE_VERIFY_FAILED" in message
                      or "certificate verify failed" in message.lower())
        # 被 403/429 拒绝也是**确定性失败**：PCL（`SourceFail`）就直接把源禁用掉。
        # 复用 cert_error 的语义 —— 它与证书错误一样"一次就该跳过"，否则每次下载都白试。
        rate_limited = _looks_rate_limited(message)
        if rate_limited and not cert_error:
            cert_error = True          # 复用"确定性失败"的阈值语义（一次就跳）
            _log(log, f"（{line.name} 返回 403/429 —— 这条线路在限流或拒绝访问，"
                      f"本次先跳过它，换个线路继续）")
        if network_wide:
            _log(log, f"（{line.name} 这次是网络/DNS 故障，不计入该线路的失败记录）")
        else:
            _remember_line(line.name, False, 0.0, cert_error=cert_error, rate_limited=rate_limited)
        errors.append(f"{line.name}: {report.message}")
        _log(log, f"线路 {line.name} 失败：{report.message}")
        if cert_error:
            _log(log, f"（{line.name} 的 HTTPS 证书与你当前网络返回的不符 —— 常见于加速器/运营商"
                      f"劫持镜像域名；已临时跳过这条线路，不影响其它线路）")
        # **不动 dest**：目标文件要么是上一次下载好的完整文件，要么是用户自己的
        # 文件 —— 一条线路失败不代表它该被删（2026-10-01 修：原实现会 unlink 它，
        # 等于"这条线路不通就把你已下好的东西删了"）。半成品始终在 work 文件里，
        # 且只有 finish() 校验通过后才会原子落位到 dest。

    report = DownloadReport(
        ok=False, path=str(dest),
        message="所有线路都失败 → " + "；".join(errors),
    )
    report.seconds = time.time() - started
    _log(log, f"下载失败：{report.message}")
    _emit_finish(report)
    return report


def _attempt_line(
    url: str,
    dest: Path,
    *,
    line: Line,
    log: Log = None,
    progress: Progress = None,
    timeout: int = 60,
    policy: str = "auto",
    expected_size: int = 0,
    expected_sha256: str = "",
    dead_mbps: float = DEAD_MBPS,
    cancel: Callable[[], bool] | None = None,
) -> DownloadReport:
    """在**一条**线路上完成下载；慢/抖时临时上并发。不负责计时汇总与日志收尾。"""
    report = DownloadReport(path=str(dest))
    started = time.time()


    size, supports_range, final_url = probe(url, timeout=min(timeout, PROBE_TIMEOUT))
    if not size:
        size = expected_size
    _log(log, f"开始下载 {dest.name}"
             + (f"（{size / 1048576:.1f} MB）" if size else ""))

    # 已经下完（大小一致 **且没有未完成的分块记录**）→ 直接跳过。
    # 有 expected_sha256 时必须**核对内容**才算数：大小一致但内容被换掉的文件
    # 不能当成"已下好"，否则镜像/缓存投毒会直接落位（2026-10-01 修）。
    if dest.is_file() and size and dest.stat().st_size == size and not has_partial_parts(dest):
        if not expected_sha256 or sha256_file(dest).lower() == norm_sha256(expected_sha256):
            report.bytes = size
            report.seconds = 0.0
            report.reason = "文件已存在且大小一致"
            report.message = "已存在"
            _log(log, "已存在且大小一致，跳过下载")
            return report
        _log(log, "已存在的文件 sha256 与期望不符 → 丢弃并重新下载")
        try:
            dest.unlink()
        except OSError:
            pass

    # 一切下载都写"工作文件"，**成功后才落位到目标路径**。
    # 这样任何一条线路失败、任何一次中断都不会破坏已经下到的数据，
    # 换线路 / 重试时还能继续用（之前的写法是直接写目标文件，直连失败那次
    # 就把续传数据截断了，等于白下）。
    work = dest.with_name(dest.name + ".mcdownload")
    if not work.exists() and dest.is_file():
        try:
            dest.replace(work)
        except OSError:
            pass
    # 分块记录要**跟着工作文件一起搬家**，否则续传信息会"跟不上"目标路径
    dest_parts = _parts_path(dest)
    if dest_parts.is_file() and not _parts_path(work).is_file():
        try:
            dest_parts.replace(_parts_path(work))
        except OSError:
            pass

    partial = work.stat().st_size if work.is_file() else 0
    # sidecar 还在 = 上次分块下载没完成。**此时不能只看大小**：块是 seek 写的，
    # 文件大小可能已经等于总量、里面却是空洞。
    incomplete = has_partial_parts(work)

    # 断点续传：支持 Range 且已有部分数据（或上次的分块记录还在）
    resume_from = partial if (supports_range and size and 0 < partial < size) else 0
    if incomplete and supports_range and size:
        resume_from = partial
    if resume_from and size:
        _log(log, f"发现未下载完的数据（{partial // 1048576} MB / {size // 1048576} MB），"
                  f"{'按上次的分块记录' if incomplete else '从断点'}继续")
        report.resumed_from = partial

    def finish(work_path: Path) -> None:
        """校验通过后把工作文件落位到目标路径。

        **所有成功路径都必须经过这里。** sha256 校验原先写在函数末尾，而
        单连接 / 断点续传 / 文件已存在这几条分支都在前面 return 了 ——
        等于"有没有校验"取决于网速（2026-10-01 实测：单连接路径期望值与实际
        哈希完全不同也照样报成功）。现在把校验收口到落位之前，任何一条路径
        都无法绕过。
        """
        if expected_sha256:
            actual = sha256_file(work_path).lower()
            expected = norm_sha256(expected_sha256)
            if actual != expected:
                # 内容不符：连同工作文件与分块记录一起丢弃，
                # 否则下一次续传会把这份错误内容当成"已下好的部分"。
                _clear_parts(work_path)
                try:
                    work_path.unlink()
                except OSError:
                    pass
                raise OSError(
                    f"sha256 校验失败（期望 {expected[:12]}…，实际 {actual[:12]}…），已丢弃下载内容")
        _clear_parts(work_path)
        os.replace(work_path, dest)

    try:
        # 断点续传优先：直接用分块把缺的补齐（哪怕设置里关了加速也续，否则前面的白下）
        # ⚠️ 续传分支**也要**遵守"这个源不许分片"（多角度审查抓到：原先只在小文件分支判了
        #    `_may_parallel`，续传路径直接进并发，于是 github.com 这类限流源在续传时照样开多连接）。
        if (incomplete or resume_from) and supports_range and size \
                and policy != "never" and _may_parallel(url):
            threads = recommended_threads(size)
            report.boosted = True
            report.threads = threads
            report.reason = (f"断点续传：{size // 1048576} MB 中已下 {partial // 1048576} MB，"
                             f"用 {threads} 连接补齐剩余")
            _log(log, report.reason)
            with _STATE_LOCK:
                _STATE["active"] = int(_STATE.get("active") or 0) + 1
            try:
                report.retries = _download_parallel(
                    url, work, size=size, start=resume_from, threads=threads,
                    timeout=timeout, progress=progress, log=log, cancel=cancel)
            finally:
                with _STATE_LOCK:
                    _STATE["active"] = max(0, int(_STATE.get("active") or 0) - 1)
            report.bytes = work.stat().st_size if work.is_file() else 0
            if report.bytes != size:
                raise OSError(f"下载不完整：{report.bytes:,} / {size:,} 字节")
            finish(work)
            report.message = "完成（断点续传）"
            _set_speed(report, started)
            return report

        # 小文件 / 不支持 Range / 明确不要加速 → 老老实实单连接
        # PCL 的 `TryBeginThread` 里对 github.com 这类源直接 Return Nothing（不分片）——
        # 它们按连接数限流，分片只会更容易被拒。
        if (not supports_range or (size and size < MIN_PARALLEL_BYTES)
                or policy == "never" or not _may_parallel(url)):
            reason = ("服务器不支持 Range" if not supports_range else
                      "文件较小，不值得并发" if size and size < MIN_PARALLEL_BYTES else
                      "这个下载源限流，单连接反而更快" if not _may_parallel(url)
                      else "已按设置关闭加速")
            report.reason = reason
            # 已有部分数据时按追加写（不截断），否则从头写
            written, stalled, note = _download_sequential(
                url, work, offset=partial if (supports_range and partial) else 0,
                total=size, timeout=timeout, progress=progress, log=log, cancel=cancel)
            total_written = (partial if (supports_range and partial) else 0) + written
            report.bytes = total_written
            if size and total_written != size:
                raise OSError(f"下载不完整：{total_written:,} / {size:,} 字节")
            report.ok = True
            report.message = note or "完成"
            finish(work)
            _set_speed(report, started)
            return report

        # ① 单连接探测：先下 PROBE_BYTES / PROBE_SECONDS 看看这条链路到底行不行
        probe_target = PROBE_BYTES if size > MIN_PARALLEL_BYTES else size
        written, stalled, note = _download_sequential(
            url, work, total=size, timeout=timeout, progress=progress, log=log,
            stop_after=probe_target, deadline_seconds=PROBE_SECONDS, cancel=cancel)
        probe_seconds = max(time.time() - started, 1e-6)
        report.probe_mbps = _mbps(written, probe_seconds)
        # 探测**极慢**就放弃这条线路，别硬起并发死磕：实测直连 0.05 MB/s 时上了 17 个连接，
        # 每块重试 4 次全失败，白耗 83 秒；换到 gh.xmly.dev 后 3.5 秒就下完了剩下的 26 MB。
        #
        # `dead_mbps` 由调用方覆盖（用户 2026-10-02：「这个限速感觉有点高了」）——
        # GitHub 组件那边有镜像可换，用默认 0.3 让"极慢的直连"尽早换线路是对的；
        # 而 Mod 下载（香蕉网之类**没有镜像**的站点）宁可慢也不该直接判死，所以传更宽松的值。
        # `policy="always"`（并行加速）下**根本不判这条**。阈值在函数开头已归一化。
        if report.probe_mbps < dead_mbps and policy != "always":
            raise OSError(f"探测速度仅 {report.probe_mbps:.2f} MB/s（低于 {dead_mbps} MB/s 可用线），"
                          f"放弃这条线路")
        slow = report.probe_mbps < SLOW_MBPS
        # 极慢线路**别并发**（见 BOOST_FLOOR_MBPS 的实测数据）：这里把并发压回单连接，
        # 但**不判死** —— 慢慢下也比下不到强。
        too_slow_to_boost = 0 < report.probe_mbps < BOOST_FLOOR_MBPS
        need_boost = (policy == "always" or slow or stalled) and not too_slow_to_boost
        if too_slow_to_boost:
            _log(log, f"线路很慢（探测 {report.probe_mbps:.3f} MB/s）→ 用单连接继续下，不并发")

        if not need_boost:
            # 链路够快：接着单连接把剩下的下完（不折腾）
            # ⚠️ 也可能是"太慢到连并发都别上"（too_slow_to_boost）—— 两种情况要分开说，
            # 否则会打出"0.01 MB/s（够快）"这种自相矛盾的日志。
            report.reason = (
                f"线路很慢（{report.probe_mbps:.3f} MB/s）→ 单连接慢慢下"
                f"（并发在这种线路上反而更慢）"
                if too_slow_to_boost else
                f"单连接 {report.probe_mbps:.2f} MB/s（够快，不启用加速）"
            )
            _log(log, report.reason)
            rest, stalled2, note2 = _download_sequential(
                url, work, offset=written, total=size, timeout=timeout, progress=progress,
                log=log, cancel=cancel)
            report.bytes = written + rest
            if size and report.bytes != size:
                raise OSError(f"下载不完整：{report.bytes:,} / {size:,} 字节")
            report.message = note2 or "完成"
            finish(work)
            _set_speed(report, started)
            return report

        # ② 慢/抖 → 临时上并发分块（真正的"加速"）
        #
        # **动态**：先并发**试一小段**，跟单连接的探测速度比一比（用户 2026-10-02 原话：
        # 「应该动态，慢就并发，更慢就切回来」）—— 实测过 8 连接反而比单连接慢 24% 的情况，
        # 所以并发不是"开了就好"，得看这条线路吃不吃多连接。
        threads = recommended_threads(size - written)
        report.boosted = True
        report.threads = threads
        report.resumed_from = written
        report.reason = (
            f"探测速度 {report.probe_mbps:.2f} MB/s（低于 {SLOW_MBPS} MB/s 阈值）→ 先试 {threads} 连接并发"
            if slow else
            (f"单连接中断 → 先试 {threads} 连接并发续传" if stalled else
             f"已按设置强制启用 {threads} 连接并发")
        )
        _log(log, report.reason)
        with _STATE_LOCK:
            _STATE["active"] = int(_STATE.get("active") or 0) + 1
        try:
            trial_started = time.time()
            report.retries = _download_parallel(
                url, work, size=size, start=written, threads=threads,
                timeout=timeout, progress=progress, log=log,
                max_seconds=BOOST_TRIAL_SECONDS, cancel=cancel)          # 试用窗口：到点不再提交新块
            done_now = sum(b - a + 1 for a, b in _load_parts(work, size))
            if size and done_now < size and done_now > written:
                boost_mbps = _mbps(done_now - written, max(time.time() - trial_start, 1e-6))
                if boost_mbps < report.probe_mbps * BOOST_KEEP_RATIO:
                    # **并发没变快 → 切回单连接**（threads=1 仍走块机制，已下的块不重下）
                    _log(log, f"并发只有 {boost_mbps:.3f} MB/s（单连接探测 {report.probe_mbps:.3f}）"
                              f"→ 切回单连接继续下剩下的")
                    report.reason += f"；实测并发更慢（{boost_mbps:.3f} MB/s）→ 已切回单连接"
                    report.threads = 1
                    report.retries += _download_parallel(
                        url, work, size=size, start=done_now, threads=1,
                        timeout=timeout, progress=progress, log=log, cancel=cancel)
                else:
                    _log(log, f"并发有效（{boost_mbps:.3f} MB/s ＞ 单连接 {report.probe_mbps:.3f}）"
                              f"→ 继续用 {threads} 连接下完")
                    report.retries += _download_parallel(
                        url, work, size=size, start=done_now, threads=threads,
                        timeout=timeout, progress=progress, log=log, cancel=cancel)
        finally:
            with _STATE_LOCK:
                _STATE["active"] = max(0, int(_STATE.get("active") or 0) - 1)
        report.bytes = work.stat().st_size if work.is_file() else 0
        if size and report.bytes != size:
            raise OSError(f"下载不完整：{report.bytes:,} / {size:,} 字节")
        finish(work)
        report.message = "完成（并发加速）"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        report.ok = False
        report.message = str(exc)
        # 失败时**保留工作文件**：下次同一条线路（或换线路）还能接着下
        report.bytes = work.stat().st_size if work.is_file() else 0
        _set_speed(report, started)
        return report

    # 校验已经在 finish() 里统一完成（所有成功路径都经过它），
    # 这里不再对同一个文件重复哈希一遍。
    _set_speed(report, started)
    return report


def _set_speed(report: DownloadReport, started: float) -> None:
    report.seconds = time.time() - started
    report.mbps = _mbps(report.bytes, report.seconds)


def _finish(report: DownloadReport, started: float, log: Log) -> None:
    _set_speed(report, started)
    _log(log, f"下载{'完成' if report.ok else '失败'}：{report.bytes / 1048576:.1f} MB / "
              f"{report.seconds:.1f}s = {report.mbps:.2f} MB/s"
              + (f"（并发 {report.threads}，重试 {report.retries} 次）" if report.boosted else ""))
    _emit_finish(report)


def _emit_finish(report: DownloadReport) -> None:
    with _STATE_LOCK:
        _STATE["last"] = report.to_dict()


def sha256_file(path: Path) -> str:
    """对外保留这个入口（多处调用它），实现统一在 fsutil。"""
    from . import fsutil

    return fsutil.sha256_file(path)


def norm_sha256(value: str) -> str:
    """把 ``sha256:xxxx`` / 大小写混杂的期望值规范成纯小写十六进制。"""
    from . import fsutil

    return fsutil.norm_sha256(value)
