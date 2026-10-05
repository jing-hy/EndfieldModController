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
import socket
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
# ⚠️ 实测"4 条不够、十几条才吃满"，而工程上 20 条对 588 MB 的大包也常顶到上限；
# 若服务端是**按连接限速**，加连接能近似线性提速 ⇒ 提到 32（2026-10-03）。
MAX_THREADS = 32
READ_CHUNK = 262144
# 单次读多久没数据算"抖动/卡死"，切并发续传
# ⚠️ **"多久收不到数据算断流"的下限**（2026-10-03 再调）。
# 它原来是硬性的 20 秒，但那只适合正常线路：香蕉网无 VPN 时实测 0.008 MB/s，
# **读满一个 256 KB 缓冲要 32 秒** ⇒ 20 秒必然超时 → 重试 → 再超时，
# 4 次重试白耗 80 秒、块还是下不完。用户看到的就是"速度出来很慢"。
# 现在它只是**下限**，真正的等待窗口由 `_stall_window()` 按"块大小 ÷ 实测速度"算。
STALL_SECONDS = 20
# 自适应窗口的上下限（秒）：够慢的线路等得起，真断流也别无限期挂着。
STALL_WINDOW_MIN = 20
STALL_WINDOW_MAX = 180
# **轮询粒度**：读循环把 socket 超时设成它，于是每秒都能检查一次
# 「用户是不是点了暂停/终止」—— 否则要等整个无数据窗口走完才响应（实测要 3 分钟）。
POLL_SECONDS = 1.0
# 探测连接的超时（要短，坏线路要快速跳过；实测直连会直接超时 15s，白等太久）
PROBE_TIMEOUT = 8
# 探测阶段的时间上限：慢线路不能把探测拖成几十秒
PROBE_SECONDS = 12
# 探测速度低于此值就直接放弃这条线路（连并发都不值得起）
# ⚠️⚠️ **这个阈值从 0.3 降到 0.02**（2026-10-03 实测修正）：
# 0.3 是个**绝对**判据，它假设「低于 0.3 MB/s 就算死线」。可这台机器（开着 Steam++）
# **最快也只有 0.28** ⇒ **每条线路都被判死**，只能靠「全被跳过时退回全部」这条兜底
# 捡回**最慢**的那条来用。实测现场：ghproxy.net 探测 0.20 被判死，
# 而它其实是当场最快的一条（0.279），最后只能用更慢的 gh-proxy.com（0.124）。
#
# 现在它只用来拦「**整条链路都不可用**」（比如 0.008 MB/s 那种）。
# 「谁快谁慢」交给**已经按实测速度排好序的线路表**：最快的先试，
# 试不动就走「并发试用窗口」按实测速度决定去留 —— 比一个静态阈值可靠得多。
DEAD_MBPS = 0.02
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
# 「直连实测速度慢于最快镜像的多少倍，就让它排到镜像后面」（2026-10-03）。
# 用倍数而不是绝对值，避免一次抖动就把直连永久降权（实测 0.009 vs 0.648 = 72 倍）。
DIRECT_SLOW_RATIO = 2.0
# 某条线路失败后多久再试
# （别设太长：一次偶发失败——比如网络抖动导致 DNS 解析失败——就把最快的线路
#   封掉半小时，反而会让用户只能退到慢线路，这正是"感觉还是很慢"的原因之一）
LINE_FAIL_TTL = 5 * 60
# ⚠️ **直连单独用更长的冷却**（2026-10-03 实测）：5 分钟就解封 ⇒
# 「慢→拉黑→用镜像→解封→又试直连」无限循环，用户感受就是"不稳定"。
# 直连慢/不通通常是**这台机器到 GitHub 的稳定事实**而非抖动。
DIRECT_FAIL_TTL = 60 * 60
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


_TOKEN_CACHE: list[bool | None] = [None]


def _has_github_token() -> bool:
    """本机有没有可用的 GitHub token（进程环境或 Windows 用户级环境变量）。

    复用 `github.token()`，保证与"检查更新"用的是**同一处判据**，不出现两套口径。
    延迟导入以避免 `fastnet` ←→ `github` 的循环依赖；结果缓存在进程内。
    """
    if _TOKEN_CACHE[0] is not None:
        return bool(_TOKEN_CACHE[0])
    value = False
    try:
        from . import github as _gh

        token, _source = _gh.token()
        value = bool(token)
    except Exception:                      # noqa: BLE001 —— 判不出来就当作"没有"
        value = False
    _TOKEN_CACHE[0] = value
    return value


def _may_parallel(url: str) -> bool:
    """这个源**在源层面**允许分片吗？（不含"这一刻快不快"的判断）

    ⚠️⚠️ **直连（真实 GitHub 主机）在没有 token 时禁止并发**（2026-10-03 用户明确要求：
    「**直连应该在没有 ghtoken 的时候禁止并发**」）。

    理由：GitHub 对**未认证**请求按 IP 限流 —— 直连开并发只是让同一个 IP 在更短时间内
    发更多请求，更容易 403/429，反而更慢甚至直接失败；有 token 时额度 5000 次/小时，
    并发才有意义。
    **只作用于直连**：镜像线路走第三方中转，请求不计在 GitHub 的 IP 限流上 ——
    实测 `ghproxy.net` 16 连接 2.05 MB/s（单连接 0.19，10 倍），所以镜像照常并发。

    另：`NO_SPLIT_HOSTS` 里那批主机（照 PCL 的经验）仍然一律单线程。

    ⚠️ **2026-10-05 修订**（用户原话：「只要直连不达到单片 1.5MB/s，而且没有 ghtoken，
    就直接进动态抢块测试，如果抢块比直连快就继续，比直连慢就恢复直连」）：
    本函数返回 `False` **不再等于"这一趟一定单连接"** —— 是不是真的禁用并发，由
    `_parallel_gate()` 在**拿到单连接实测速度之后**决定：慢到 `SLOW_MBPS`（1.5 MB/s）
    以下就放行进抢块试用，去留交给试用窗口的实测比较。
    本函数仍是**源层面**的判据（也被"续传"分支用），别把它当成最终结论。
    """
    host = _host_of(url)
    if not host:
        return True
    for blocked in NO_SPLIT_HOSTS:
        if host == blocked or host.endswith("." + blocked):
            # ⚠️ 这里的 blocked 名单里就有 github.com 等 —— 但按用户 2026-10-03 的规则，
            # **有 token 时直连也允许并发**（他实测直连 16 连接 0.203 MB/s vs 单连接 0.032，6.3 倍）。
            # 所以对"真实 GitHub 主机"改成看 token；其它主机（bmclapi 等）照旧禁止。
            if _is_github_host(host):
                return _has_github_token()
            return False
    return True


def _is_github_host(host: str) -> bool:
    """是不是**真实的** GitHub 主机（不是镜像中转域名）。"""
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h)
               for h in ("github.com", "githubusercontent.com", "githubassets.com"))


def _direct_last_mbps(url: str) -> float:
    """这条**直连**上次实测的速度（`0` = 没有记录 / 不是 GitHub 直连）。

    只给**续传**分支用：那一刻还没做单连接探测，但线路成绩缓存里有上次的值。
    """
    if not _is_github_host(_host_of(url)):
        return 0.0
    return float((_load_lines_cache().get(DIRECT.name) or {}).get("mbps") or 0)


def _parallel_gate(url: str, probe_mbps: float, policy: str) -> tuple[bool, str]:
    """**这一刻允许进并发抢块吗**？返回 `(允许, 说明)`。

    规则来自用户 2026-10-05 的原话：「**只要直连不达到单片 1.5MB/s，而且没有 ghtoken，
    就直接进动态抢块测试，如果抢块比直连快就继续，比直连慢就恢复直连**」。

    * `policy="always"`：调用方（或用户）**显式**要加速 ⇒ 允许，不再看下面的门禁；
    * **真实 GitHub 直连**且**没有 token**：
        - 实测 ≥ `SLOW_MBPS`（1.5 MB/s）⇒ **不许并发**（已经够快，没必要拿未认证 IP
          去撞 GitHub 的限流）；
        - 实测 < 1.5 MB/s ⇒ **允许进抢块试用** —— 慢到这份上试一把多连接是值得的，
          去留完全交给试用窗口的实测比较（`BOOST_TRIAL_SECONDS` 后与探测值比，
          不如就把剩下的切回单连接，见 `_attempt_line` 里那段）；
    * 其它**源层面**不许分片的（bmclapi 等，见 `NO_SPLIT_HOSTS`）⇒ 不许；
    * 其余（镜像线路等）⇒ 允许。

    ⚠️ 这是对 2026-10-03「直连在没有 ghtoken 的时候禁止并发」的**延伸**，而不是推翻：
    用户 2026-10-05 又补了一句「**抢块不包含直连**」—— 所以**直连自己永远不开多连接**
    （有没有 token、快不快，都不开）；"慢直连"要走的不是"直连并发"，而是
    **换去镜像抢块**：由 `download()` 对无 token 的直连把 `dead_mbps` 提到 `SLOW_MBPS`，
    让它慢到 1.5 MB/s 以下时直接换线路，镜像那边才开多线路并发抢块。
    """
    if policy == "always":
        return True, "已按设置强制启用并发"
    host = _host_of(url)
    for blocked in NO_SPLIT_HOSTS:
        if host == blocked or host.endswith("." + blocked):
            if _is_github_host(host):
                if _has_github_token():
                    return True, "有 GitHub token，直连允许并发"
                # 没 token：**直连自己一律不并发**（未认证并发只会撞 GitHub 限流）；
                # 它慢的时候由 `download()` 换到镜像去抢块，而不是在这儿把直连拆成多连接。
                return False, ("没有 token 的直连不开并发（抢块不含直连）—— "
                               "慢的话换镜像线路去抢块")
            return False, "这个下载源按连接数限流，单连接反而更快"
    return True, "这条线路允许并发"


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
# ⚠️ 2026-10-04 实测（用户机器，裸网）：**`gh.xmly.dev` 的域名已经不存在了**
# （`Resolve-DnsName` 回"DNS 名称不存在"）—— 它原本排在镜像第一位，于是每次下载都
# 先白试它一遍；而它抛的是 `getaddrinfo failed`，命中下面那段"网络/DNS 故障不计入失败
# 记录"的豁免 ⇒ **永远不进冷却、永远排第一、永远重试**，日志里一秒内能刷十几遍
# 「线路 gh.xmly.dev 失败」+「下载失败：所有线路都失败」。
# 同时实测出可用线路（真实 Release 资产取前 1 MB）：
#   gh.nxnow.top 0.39 MB/s ✓✓（新加，最快） / ghproxy.net 0.21 ✓ / gh-proxy.com 0.06 ✓
#   其余候选（github.moeyy.xyz / gh.llkk.cc / ghgo.xyz / gh.ddlc.top / slink.ltd /
#   cf.ghproxy.cc / ghproxy.1888866.xyz / gh.api.99988866.xyz / ghfast.top /
#   mirror.ghproxy.com / ghproxy.cc / hub.gitmirror.com）本次全部不可用 ——
#   不可用的**一律不进默认表**，只留"实测能跑"的和少数几个偶尔能用的候选，
#   它们失败会被冷却、不会拖慢正常下载。
DEFAULT_LINES: tuple[Line, ...] = (
    DIRECT,
    Line("gh.nxnow.top", "https://gh.nxnow.top/"),
    Line("ghproxy.net", "https://ghproxy.net/"),
    Line("gh-proxy.com", "https://gh-proxy.com/"),
)

# ⚠️ 2026-10-04：**DNS 解析失败的线路必须被临时跳过**。
# 原逻辑把 `getaddrinfo failed` 当成"全网故障、不计入这条线路的失败"（本意很对：
# 一次 DNS 抖动不该把好线路冤枉掉）—— 但后果是**域名已经没了的线路永远不进冷却、
# 永远排在候选里**，每次下载都先白试它一遍。用户实测现场：日志里一秒内刷了十几遍
# 「线路 gh.xmly.dev 失败：getaddrinfo failed」+「下载失败：所有线路都失败」。
# 现在给它单独一个**短冷却**（不动既有缓存结构）：域名真死了，也只会每 10 分钟白试一次。
_DNS_DEAD: dict[str, float] = {}
DNS_DEAD_TTL = 600.0


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
    cancel: Callable[[], bool] | None = None,
    tolerate_error_status: bool = False,
) -> tuple[str, bytes]:
    """按线路取一小段内容（HTML/JSON 这类小请求），返回 ``(最终 URL, 内容)``。

    直连不通时会自动换镜像线路 —— 这是"**不消耗 GitHub API 额度**地读 release 页面"
    的关键：普通用户没有 token，API 只有 60 次/小时，靠网页路线才稳。

    *cancel*（2026-10-04 加）：**读取期间也要能被叫停**。原来这里是 `response.read()`
    一口气读完、中途没有任何检查点 —— 而「读取香蕉网信息」（读那坨 JSON，最长 25 秒）
    走的正是这条路，于是用户点「暂停 / 终止」在探测期间**完全无效**（他的原话：
    「**探测期间无法暂停**」「点了**终止也还是探测中**」）。
    现在复用本项目已有那套"短超时轮询 + `select()` 可读探测"：每秒醒一次检查 `cancel()`，
    被叫停就抛 `Cancelled`（**不是**线路故障，所以不要因此去换下一条线路）。

    *tolerate_error_status*（2026-10-05 加，默认关）：**站点用 4xx/5xx 也能带正文**时别把
    正文丢掉。加它的直接起因：`reshade.me` 首页现在恒定返回 **HTTP 500**，但正文里带着
    `ReShade_Setup_<版本>_Addon.exe` —— 我们据此取版本号的那条链于是全断，
    依赖页里「ReShade 底座 (d3d12.dll)」**永远装不上**（用户原话：「别的都没问题，
    就 d3d12 下不来」）。开启后：只要响应体读到了内容就当成功返回，**错误码照旧记账**，
    由调用方自己判断正文够不够用。默认 False = 维持"非 2xx 即线路失败"的老行为。
    """
    mode = (line_mode or get_line_mode() or "auto").lower()
    if mode not in LINE_MODES:
        mode = "auto"
    lines = resolve_lines(url, mode)
    last_error: Exception | None = None
    for line in lines:
        # ⚠️ 直连先做一次 TCP 预检（2026-10-04）：连不上就立刻换镜像，别白赔十几秒。
        # 与 `download()` 里那条同一判据（只判"连不上"、不误杀"慢"）。
        if line is DIRECT and len(lines) > 1 and not _tcp_reachable(url):
            _log(None, f"直连不可达（{DIRECT_TCP_TIMEOUT:g}s 内连不上 {_host_of(url)}）→ 直接换镜像线路")
            _remember_line(line.name, False, 0.0)
            last_error = urllib.error.URLError(f"直连不可达: {_host_of(url)}")
            continue
        try:
            chunks: list[bytes] = []
            with _open(line.apply(url), headers=headers, timeout=timeout) as response:
                final = response.geturl()
                waited = 0.0
                window = float(max(int(timeout), 1))
                while True:
                    if cancel and cancel():
                        raise Cancelled("用户暂停/终止（读取期间）")
                    # 用 `select()` 探测可读，**绝不重试 read()** —— http.client 的响应对象
                    # 一旦超时就不能再读（`cannot read from timed out object`）。
                    if not _readable(response, POLL_SECONDS):
                        waited += POLL_SECONDS
                        if waited >= window:
                            raise TimeoutError(f"读取 {url} 超时（{waited:.0f}s 无数据）")
                        continue
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    waited = 0.0
            _remember_line(line.name, True, 0.0)   # 成功只清失败标记，不覆盖速度成绩
            return final, b"".join(chunks)
        except Cancelled:
            raise                                   # 用户停的，别当线路故障去换下一条
        except urllib.error.HTTPError as exc:
            # ⚠️ 必须排在 `URLError` 之前（`HTTPError` 是它的子类）。
            if tolerate_error_status:
                try:
                    body = exc.read()
                except OSError:
                    body = b""
                if body:
                    _remember_line(line.name, True, 0.0)
                    return (exc.geturl() or url), body
            last_error = exc
            _remember_line(line.name, False, 0.0)
            continue
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
                # ⚠️ **必须在循环外初始化**（2026-10-03）：放循环里会被每轮重置，
                # 于是"无数据等待"永远累计不到窗口 ⇒ 超时后无限空转。
                # 真正"多久算断流"由它累计判断；socket 超时只用作**轮询粒度**，
                # 这样每秒都能检查一次 `cancel()` ⇒ 点「暂停/终止」立刻生效。
                _seq_waited = 0.0
                _seq_window = float(STALL_SECONDS)
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
                            # ⚠️ **自适应无数据窗口**（2026-10-03）：固定 20 秒对"极慢但通"的
                            # 线路是误杀 —— 香蕉网无 VPN 时实测 0.008 MB/s，读满 256 KB 要 32 秒，
                            # 于是每块都"超时→重试→再超时"，用户看到的就是"速度出来很慢"。
                            # 这里按"已读速度"估窗口；没有速度就用下限兜底。
                            _elapsed = max(time.time() - started, 1e-6)
                            _mbps = (written / 1048576) / _elapsed if written else 0.0
                            _seq_window = _stall_window(READ_CHUNK, _mbps)
                        # ⚠️ **探测期间别拿 180 秒的窗口去等 12 秒的探测**：
                        # 有 deadline 时，单轮最多等到 deadline 剩余时间就够了。
                        if deadline_seconds:
                            _left = deadline_seconds - (time.time() - started)
                            _seq_window = max(1.0, min(_seq_window, _left))
                            # ⚠️ socket 超时用**轮询粒度**（不是整个窗口）：每秒都能检查一次 `cancel()`
                            # ⇒ 点「暂停/终止」立刻生效（原来要等整个窗口走完，实测 3 分钟）。
                            # 真正"多久算断流"由 `_seq_waited` 累计判断。
                            _sock.settimeout(POLL_SECONDS)
                    except Exception:  # noqa: BLE001 - 拿不到底层 socket 就保持原样
                        pass
                    # ⚠️ **短超时轮询**（同并行）：每秒检查一次 cancel，
                    # 累计无数据超过自适应窗口才判线路不通。
                    # ⚠️ `_seq_waited` 必须**在循环外**初始化 —— 放循环里会被每轮重置，
                    # 于是永远累计不到窗口、超时后无限空转。
                    # ⚠️ **用 `select()` 探测可读，绝不"重试 read()"**（2026-10-03）：
                    # `http.client` 的响应对象一旦超时就不能再读
                    #（`cannot read from timed out object`）。
                    if not _readable(response, POLL_SECONDS):
                        _seq_waited += POLL_SECONDS
                        # ⚠️⚠️ **没数据时也要检查 deadline**（2026-10-03 修「死等 180 秒才换线路」）：
                        # 探测的 `PROBE_SECONDS`(12s) 上限原来只在"成功读到一块之后"检查，
                        # 而完全没数据的线路上流程一直走这条 `continue` 分支
                        # ⇒ 那个上限形同虚设 ⇒ 只能等满 `_seq_window`（初始速度未知时是 180 秒）。
                        # 用户实测：点下载后 3 分钟无任何反应、一个字节都没进来。
                        if deadline_seconds and (time.time() - started) > deadline_seconds:
                            return written, False, (
                                f"探测超时（{deadline_seconds:.0f}s 内只下到 "
                                f"{written / 1048576:.1f} MB）")
                        if _seq_waited >= _seq_window:
                            return 0, True, (f"连接建立后 {int(_seq_waited)}s 内没有收到任何数据（线路不通）")
                        continue
                    _seq_waited = 0.0
                    # ⚠️ **同并行：读之前把预算放回去**（否则慢线路上每次 read 都 1 秒超时）
                    _restore_sock_timeout(response, _seq_window)
                    chunk = response.read(READ_CHUNK)
                    _sock_timeout(response, POLL_SECONDS)
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
            return 0, True, f"连接建立后 {STALL_SECONDS}s 内没有收到任何数据（线路不通）"
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


def _partial_artifacts(dest: Path) -> tuple[Path, ...]:
    """某个目标文件**全部**断点续传产物：目标 / 工作文件 / 两份 sidecar 命名。

    单点定义（`discard_partial` 是唯一动作入口）：文件名清单一旦在别处再抄一份，
    就很容易抄漏 —— 2026-10-04 审计发现 `moddl._cleanup_partial` 正是漏了 sidecar，
    导致"重试跳过已删的块 → 落位空洞文件却报成功"。
    """
    target = Path(dest)
    work = target.with_name(target.name + ".mcdownload")
    return (target, work, _parts_path(work), _parts_path(target))


def discard_partial(dest: Path) -> list[Path]:
    """删掉某个目标文件的全部续传产物（工作文件 + sidecar + 可能已落位的一半），返回删掉的文件。

    只在"这次下载彻底失败 / 用户点了终止"时调用 —— 调用方要接受"下次从头下"。
    """
    removed: list[Path] = []
    seen: set[Path] = set()
    for path in _partial_artifacts(dest):
        if path in seen:
            continue
        seen.add(path)
        try:
            if path.exists():
                path.unlink()
                removed.append(path)
        except OSError:
            pass
    return removed


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


def _probe_lines(urls: list[str], *, timeout: float = 3.0, log: Log = None) -> list[str]:
    """并发预检各条线路（每条只取 1 字节），返回**真能拿到数据**的那些。

    ⚠️ 2026-10-04：多线路抢块前**必须先体检**。用户的现场是「下载速度横线、进度条不动」：
    26 个分块线程的第一次尝试全撞同一条线路，而机器上 `github.com` 被 hosts 指向
    `127.0.0.1`（加速器残留）—— 直连**连得上但一个字节都不来**，于是所有线程一起挂到超时。
    花 3 秒把这种线路挡在门外，比让几十个连接白等一分钟划算得多。

    **全都不通时原样返回** —— 预检本身不许把下载卡死（真正的原因留给下载路径去报）。
    """
    if len(urls) < 2:
        return urls

    def one(target: str) -> bool:
        try:
            with _open(target, headers={"Range": "bytes=0-0"}, timeout=timeout) as response:
                return bool(response.read(1))
        except Exception:  # noqa: BLE001 —— 任何异常都只意味着"这条现在不能用"
            return False

    try:
        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            results = list(pool.map(one, urls))
    except Exception:  # noqa: BLE001
        return urls
    alive = [target for target, ok in zip(urls, results) if ok]
    if alive and len(alive) < len(urls):
        dropped: list[str] = []
        for target, ok in zip(urls, results):
            if not ok:
                try:
                    dropped.append(urlsplit(target).netloc or target)
                except ValueError:
                    dropped.append(target)
        _log(log, f"线路预检：{'、'.join(dropped)} 连得上但取不到数据（可能是 hosts/加速器残留"
                  f"或该线路被限流），本次不参与抢块；用 {len(alive)} 条")
    return alive or urls


def _pick_line_url(urls: list[str], dead: set[str], attempt: int) -> str:
    """多线路动态抢块：这一块这次该用哪条线路。

    规则：**第 1 次用主线路（列表首位 = 最快的），失败才轮换到别的可用线路**；
    已淘汰（连挂两次）的不再选，全被淘汰时退回全部（宁可再试一次，也不能把它卡死）。

    ⚠️⚠️ **不许让不同线程从不同线路起步**（2026-10-04 实测，用户报「**速度怎么掉下去了**」）：
    为了修"26 个线程全撞同一条主线路"，我曾按块序号把线程**均匀分散**到各条线路 ——
    结果变成了**静态等分**：慢线路各分到 1/4 的线程、整体被最慢的那条拖住。
    实测同一份 28.5 MB 资产：**分散 0.669 MB/s（42.6 秒） vs 主线路优先 2.955 MB/s（9.6 秒）**，
    **慢了 4.4 倍**。这跟 2026-09-27「多线路混合 4+4+4 只有 1.16 MB/s，是负优化」是同一条教训。
    正确做法：**集中用最快的线路，失败才换下一条**；"撞上一条连得上但不给数据的线路"
    那个问题由 `_probe_lines()` 的**预检**解决（抢块前先各取 1 字节），不是靠分散。
    """
    live = [item for item in urls if item not in dead] or urls
    if not live:
        return urls[0] if urls else ""
    return live[attempt % len(live)]


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
    expected_mbps: float = 0.0,      # ⚠️ 已知单连接速度：用于算"无数据等待窗口"（2026-10-03）
    alt_urls: list[str] | None = None,   # ★ 多线路动态抢块：同一条块的候选线路（2026-10-04）
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
    # ⚠️⚠️ **sidecar 不能盲信**（2026-10-04 审计发现的**数据损坏**级坑）。
    #
    # sidecar 只说"这些块下好了"，但工作文件可能已经被删/被截断过（上一次失败清理只删了
    # `.mcdownload` 而漏删 sidecar；或用户手工删过工作文件）。这时如果照 sidecar 跳过这些块，
    # 新 touch 出来的文件里对应区间**就是空洞**，而块是 seek 写的 ⇒ 文件长度照样能到 `size`
    # ⇒ 上层"`report.bytes == size`"判据通过 ⇒ `finish()` 落位 ⇒ **报成功却给出一个坏包**
    #（rar/7z 只查 8 字节头，坏包会静默进 Mod 库）。
    #
    # 判据：**块必须完全落在文件当前长度之内**才算"真的有这些字节"。
    #   * 正常续传：文件长度 = 已下块的最大结束位置 ⇒ 最后一块 `b == actual - 1 < actual` ✓ 全部保留；
    #   * 空洞场景：工作文件被删后被 touch 成 0 字节 ⇒ 全部过滤 ⇒ **老老实实重下**。
    if done_spans:
        try:
            actual_size = dest.stat().st_size
        except OSError:
            actual_size = 0
        if actual_size < size:
            done_spans = {(a, b) for a, b in done_spans if b < actual_size}
    if not done_spans and start > 0:
        done_spans = {(a, b) for a, b in spans if b < start}
    # **长块优先**：对应 PCL 的"寻找最大碎片"——先让大块开跑，
    # 避免收尾时剩一个大块、其它线程都在空转（那是最典型的"最后 5% 特别慢"）。
    todo = sorted((s for s in spans if s not in done_spans),
                  key=lambda sp: sp[1] - sp[0], reverse=True)

    lock = threading.Lock()
    state = {
        "n": sum(b - a + 1 for a, b in done_spans),      # **已完成**（断点续传判定用）
        # ⚠️ `live` = **已接收但还没落盘的字节**，只用于进度上报（2026-10-03）。
        # 不分这两个量的话，"边下边报"会把同一份字节算两次（读到时加一次、落盘时又加一次）。
        "live": 0,
        # ⚠️ **上报用的高水位**（2026-10-03 修「进度条老是往回跳」）：
        # 进度只能增不能减 —— 重试会把 `live` 清零，直接拿 `n + live` 上报就会往回跳。
        "reported": 0,
        "retries": 0,
    }
    if not dest.exists():
        dest.touch()
    _save_parts(dest, size, done_spans)
    if progress:
        progress(min(state["n"], size), size)
    if done_spans:
        _log(log, f"续传：已完成 {state['n'] // 1048576} MB / {size // 1048576} MB，"
                  f"还需下 {len(todo)} 块")

    # ⚠️ 2026-10-04：**多线路动态抢块**（用户「测一下混合动态并发」→ 实测后落地）。
    # 下面这个 `todo` 队列本来就是"共享队列 + 谁空谁领" ⇒ **动态分配天然成立**
    # （快的线程自然领得多），实测：单线路 0.664 MB/s、静态等分 0.508（**负优化**）、
    # 动态抢块 **0.975 MB/s（+47%）**；复跑脚本 `scripts/speedtest_mixed.py`。
    # 这里只补两件事：① 每次块重试**换一条线路**；② 某条线路连续失败就**淘汰**它。
    urls = [url] + [item for item in (alt_urls or []) if item and item != url]
    line_fails: dict[str, int] = {}
    dead_urls: set[str] = set()
    if len(urls) > 1 and todo:
        # 先体检：把"连得上但不给数据"的线路挡在门外（否则若干线程会一起挂到超时，
        # 界面就是"速度横线 + 进度条不动"）
        urls = _probe_lines(urls, log=log)
        _log(log, f"多线路动态抢块：{len(urls)} 条线路共用 {len(todo)} 块"
                  f"（谁空谁领，连挂两次的线路本次淘汰）")

    def _short(target: str) -> str:
        try:
            return urlsplit(target).netloc or target
        except ValueError:
            return target

    def fetch(span: tuple[int, int]) -> None:
        begin, end = span
        _fetch_started = time.time()          # 用于估算"当下的实际速度"（自适应窗口）
        last_error: Exception | None = None
        for attempt in range(4):
            if cancel and cancel():
                raise Cancelled("用户终止")
            # 换线路：第 1 次用**最快的**主线路，失败才轮到别的（连续失败的已淘汰）。
            # ⚠️ 不要按块序号分散 —— 那等于"静态等分"，会被最慢的线路拖住（实测慢 4.4 倍）
            target_url = _pick_line_url(urls, dead_urls, attempt)
            try:
                headers = {"Range": f"bytes={begin}-{end}"}
                with _open(target_url, headers=headers, timeout=timeout) as response:
                    # ⚠️⚠️ **必须分块读 + 单块间隔超时**（2026-10-03 修「下载到一半一直不动」）。
                    # 原来是 `data = response.read()` **一次性读整块** —— 那个调用只在
                    # `timeout` 到点或数据读完时才返回，**中途一个字节都不给就无限期挂着**，
                    # 单连接那条路的 `STALL_SECONDS` 保护在这里完全不生效。
                    # 实测现场：912 MB 的包切了 20 个并发连接，**全部挂起**，
                    # sidecar 里 `done: []`（一个块都没完成），文件停在 768 KB 不动，
                    # 日志里连一条重试都没有（因为失败路径不记日志）。
                    # 现在跟单连接一个规格：每读一小块就重设"多久没数据算卡死"。
                    # ⚠️ **自适应无数据窗口**（2026-10-03）：固定 20 秒对极慢但通的线路是误杀
                    #（0.008 MB/s 时读满 256 KB 要 32 秒 ⇒ 每块都"超时→重试→再超时"）。
                    # 这里按"这块多大 ÷ 已知速度"给窗口，拿不到速度就用下限兜底。
                    # 速度优先用"这块已经读了多少 / 花了多久"（更贴近当下），
                    # 没有就用调用方给的探测值 —— 两者都没有就落到窗口下限。
                    _live_mbps = (state["live"] / 1048576) / max(time.time() - _fetch_started, 1e-6) \
                        if state.get("live") else 0.0
                    _window = _stall_window(max(1, end - begin + 1),
                                            _live_mbps or float(expected_mbps or 0.0))
                    try:
                        response.fp.raw._sock.settimeout(POLL_SECONDS)  # type: ignore[attr-defined]
                    except (AttributeError, OSError):
                        pass
                    buf = bytearray()
                    # ⚠️⚠️ **轮询用 `select()` 探测，绝不"重试 read()"**（2026-10-03）：
                    # 上一版我在超时后又调了一次 `response.read()` —— 而 `http.client` 的
                    # 响应对象**一旦超时就不能再读**（`cannot read from timed out object`），
                    # 于是每轮"轮询"都变成一次失败、白触发重试，还让进度往回跳。
                    # `select.select([sock], [], [], POLL_SECONDS)` 只是"看一眼有没有数据"，
                    # **不改变 socket 状态**，超时了可以继续等。
                    _waited = 0.0
                    while True:
                        if cancel and cancel():
                            raise Cancelled("用户暂停/终止")
                        if not _readable(response, POLL_SECONDS):
                            _waited += POLL_SECONDS
                            if _waited >= _window:
                                raise TimeoutError(
                                    f"连接建立后 {int(_waited)}s 内没有收到任何数据（线路不通）")
                            continue
                        # ⚠️⚠️ **真读之前要把超时预算放回去**（2026-10-03 修「下载到最后崩了」）：
                        # `select()` 只是"看一眼有没有数据"，1 秒粒度正好；
                        # 但 `read()` 要用**这个块的窗口**做预算 —— 慢线路上读满 256 KB
                        # 可能要几十秒，用 1 秒必然超时 ⇒ 每一块都被记成"失败"。
                        _restore_sock_timeout(response, _window)
                        chunk = response.read(READ_CHUNK)
                        # 读完立刻收回短超时，下一轮轮询才能 1 秒内响应"暂停"
                        _sock_timeout(response, POLL_SECONDS)
                        if not chunk:
                            break
                        _waited = 0.0
                        buf.extend(chunk)
                        # ⚠️⚠️ **边下边报字节**（2026-10-03 修「进度条不动、速度横杠」）。
                        # 原来只在**整块下完**才 `progress()` 一次，而 912 MB 的包一块是
                        # 11.4 MB ⇒ 在 0.01 MB/s 的线路上要 **19 分钟**才报一次，
                        # 界面看起来就是完全卡住。现在每读一小块（256 KB）就报一次。
                        with lock:
                            state["live"] += len(chunk)
                            if progress:
                                # ⚠️ **单调不减**（高水位）：重试会把 live 清零，
                                # 直接上报 `n + live` 就会往回跳（用户实测报过）。
                                _cur = min(state["n"] + state["live"], size)
                                if _cur > state["reported"]:
                                    state["reported"] = _cur
                                progress(state["reported"], size)
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
                    # 这块的"已接收"已经并入 `n`，从 live 里扣掉（否则同一份字节算两次）
                    state["live"] = max(0, state["live"] - len(data))
                    _save_parts(dest, size, done_spans)   # 每块都落盘，断电也不白下
                    if progress:
                        _cur = min(state["n"] + state["live"], size)
                        if _cur > state["reported"]:
                            state["reported"] = _cur
                        progress(state["reported"], size)
                return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_error = exc
                # 多线路：连续失败两次就淘汰这条（只淘汰它的 URL，不影响别人）
                if len(urls) > 1:
                    line_fails[target_url] = line_fails.get(target_url, 0) + 1
                    if line_fails[target_url] >= 2 and len(dead_urls) < len(urls) - 1:
                        dead_urls.add(target_url)
                        _log(log, f"多线路：{_short(target_url)} 连挂两次，本次不再用它")
                with lock:
                    state["retries"] += 1
                    retry_no = state["retries"]
                    # ⚠️ **不要把 live 清零**：`live` 是"已接收"的累计，清零会让上报回跳。
                    # 进度由 `state["reported"]` 高水位保证单调；重试会重读同一段，
                    # 那部分字节本来就已经算进 live 了，重复累加也不影响（有 size 上限）。
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


def _sock_timeout(response: Any, seconds: float) -> None:
    """给 `response` 底层 socket 设读超时（拿不到就静默跳过）。"""
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if sock is None:
        return
    try:
        sock.settimeout(seconds)
    except (OSError, ValueError):
        pass


def _restore_sock_timeout(response: Any, window: float) -> None:
    """`select()` 确认有数据后，**把读超时放回"这块的窗口"**。

    ⚠️ **为什么必须**（2026-10-03 实测）：轮询用的 `POLL_SECONDS`(1 秒) 如果一直留着，
    `response.read(READ_CHUNK)` 就只有 1 秒预算 —— 而慢线路上读满 256 KB 要几十秒
    ⇒ **每次 read 都超时** ⇒ 整包下载必然失败（用户报「下载到最后崩了」）。
    """
    _sock_timeout(response, max(1.0, float(window)))


def _readable(response: Any, wait_seconds: float) -> bool:
    """`response` 底层 socket 在 `wait_seconds` 内**有没有数据可读**。

    ⚠️ **不要用"设短超时 + 超时后重试 read()"来实现轮询**（2026-10-03 实测）：
    `http.client` 的响应对象**一旦超时就不能再读**，会抛
    `cannot read from timed out object`。`select()` 只是"看一眼有没有数据"，
    **不改变 socket 状态**，超时了可以继续等下去。

    拿不到底层 socket 时**保守地返回 True**（让调用方直接去 `read()`，
    退化成原来"靠 socket 超时"的行为，不会因为探测失败而卡住）。
    """
    import select

    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if sock is None:
        return True
    try:
        ready, _, _ = select.select([sock], [], [], wait_seconds)
        return bool(ready)
    except (OSError, ValueError):
        return True          # 探测本身出问题就别拦着读


def _stall_window(piece_bytes: int, mbps: float) -> float:
    """按"这块有多大 ÷ 已知速度"算出**合理的无数据等待窗口**（秒）。

    为什么需要：固定 20 秒对**极慢但通**的线路是误杀 —— 0.008 MB/s 时读满 256 KB
    就要 32 秒，于是每一块都会"超时→重试→再超时"。这里给一个与速度匹配的窗口，
    同时用 `STALL_WINDOW_MAX` 兜住（真断流不能无限等）。
    """
    if mbps <= 0:
        return float(STALL_WINDOW_MAX)
    # 单次 read 的期望耗时（READ_CHUNK 一小块）再放宽若干倍，留出抖动余量
    expected = (READ_CHUNK / 1048576) / mbps            # 读一小块要几秒
    window = max(STALL_WINDOW_MIN, min(STALL_WINDOW_MAX, expected * 8))
    # 也别小于"整块 ÷ 速度"的很小一部分（大块时读循环是连续的，按小块算就够）
    return float(window)


def recommended_threads(size: int) -> int:
    """按体积给并发数。

    2026-09-27 实测（27.6 MB、镜像线路 gh.xmly.dev）：
        单连接 0.71 MB/s → 8 连接 3.21 MB/s → 16 连接 3.96 MB/s
    即并发是主要提速手段（5.6 倍），所以这里给得比以前大方；
2026-10-03：上限从 20 提到 32（实测"4 条不够、十几条才吃满"，大包常顶到上限）；
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

    rate_limited=True 表示被 **403/429 拒绝**：同样是确定性失败（一次就该跳过），
    ⚠️ 但冷却要短得多（`LINE_RATE_LIMIT_TTL` = 5 分钟）—— 限流本来就会自己恢复，
    套用证书错误那个 30 分钟的冷却会让一条好线路白停半小时（2026-10-04 修：
    原先这里把 403/429 **当成证书错误**记进 `entry["cert"]`，于是共用 30 分钟冷却，
    而 `LINE_RATE_LIMIT_TTL` 这个常量、`rate_limited` 这个形参**从来没有被用过**）。
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
        entry.pop("rate", None)
        entry["fails"] = 0        # 成功一次就把失败计数清零，避免历史失败累积成"永久封禁"
    else:
        entry["ok"] = False
        entry["fail_at"] = int(time.time())
        if cert_error:
            entry["cert"] = True
            entry.pop("rate", None)
            entry["fails"] = max(int(entry.get("fails") or 0) + 1, LINE_FAIL_THRESHOLD)
        elif rate_limited:
            entry["rate"] = True
            entry.pop("cert", None)
            entry["fails"] = max(int(entry.get("fails") or 0) + 1, LINE_FAIL_THRESHOLD)
        else:
            entry.pop("cert", None)
            entry.pop("rate", None)
            entry["fails"] = int(entry.get("fails") or 0) + 1
    cache[name] = entry
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写（2026-10-04）：线路成绩是"哪条快"的唯一记忆，写坏半截就白测一场；
        # 且多线程下载会并发读写它（原来直接 write_text）。
        from . import fsutil

        fsutil.write_text_atomic(path, json.dumps(cache, ensure_ascii=False, indent=2), newline="\n")
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
    rate = bool(entry.get("rate"))
    threshold = 1 if (name == DIRECT.name or cert or rate) else LINE_FAIL_THRESHOLD
    if int(entry.get("fails") or 0) < threshold:
        return False
    fail_at = int(entry.get("fail_at") or 0)
    ttl = (LINE_CERT_FAIL_TTL if cert
           else LINE_RATE_LIMIT_TTL if rate          # 403/429：限流会自己恢复，只停 5 分钟
           else DIRECT_FAIL_TTL if name == DIRECT.name
           else LINE_FAIL_TTL)
    return bool(fail_at) and (time.time() - fail_at) < ttl


# ⚠️ **直连的 TCP 预检**（2026-10-04 实测后加）。
#
# 现场：`github.com` 在**没有加速器**的网络下直连是**连不上**的（实测用真实 IP 直连，
# 20 秒后 `WinError 10060`），而 `github.com` 的页面请求之所以"看起来正常",
# 是因为那台机器开着 Steam++（hosts 把 github.com 指向 127.0.0.1 走它的反代）。
# 关掉加速器后，`DEFAULT_LINES` 里排第一的**直连**每次都要先赔掉十几秒才轮到镜像
# —— 用户看到的就是"下载一直卡着 / 20 秒超时"。
#
# 这条预检把"**连不上**"与"**连得上但慢**"分开：只做一次 TCP 连接（不读数据），
# 连不上就**立刻跳到镜像**，连得上就完全按原来的逻辑走（慢线路照样会被探测到、不会被误杀
# —— 记忆里"最快的镜像反被判死"就是这么来的，不能重蹈）。
DIRECT_TCP_TIMEOUT = 5.0


def _tcp_reachable(url: str, *, timeout: float = DIRECT_TCP_TIMEOUT) -> bool:
    """目标（或本地代理）能在 `timeout` 秒内建立 TCP 连接吗？

    只判"连得上/连不上"，**不读任何数据**，所以不会把"慢"误判成"不可用"。
    有代理时检代理地址 —— 那才是真正要连的对端（否则会在直连被墙的机器上误跳）。
    任何异常都保守返回 True（宁可让原来的流程去试，也不要因为预检自己出错而跳过一条线路）。
    """
    host = _host_of(url)
    port = 443
    if urlsplit(url).scheme.lower() == "http":
        port = 80
    proxy = get_proxy()
    if proxy:
        parsed = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
        host = parsed.hostname or host
        port = parsed.port or (443 if (parsed.scheme or "http").lower() == "https" else 80)
    if not host:
        return True
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# 镜像能代理的主机：`github.com`（Release 资产 / 仓库页）与 **`raw.githubusercontent.com`**（raw 文件）。
# ⚠️ 2026-10-04 补（用户：「看看是不是所有下载都接上去了」）：原先只认 `github.com`，
# 于是"角色表 / 乳摇参数 / 公告"这些**走 raw 的请求永远不会换线路** —— 直连一断就整块失败，
# 而镜像其实是支持的（实测 `https://ghproxy.net/https://raw.githubusercontent.com/...` 返回 200）。
# `codeload.github.com`（整仓 tar.gz）与 `objects.githubusercontent.com`（Release 资产的
# 真实落点）同理，一并接上。
MIRRORABLE_HOSTS = (
    "github.com",
    "www.github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    # ⚠️ **2026-10-04 补：`release-assets.githubusercontent.com` —— Release 资产的真实落点。**
    #
    # 实测（本机 hosts + DNS）：Steam++（Watt Toolkit）的 hosts 覆盖了
    # `objects.githubusercontent.com`，**却没有覆盖 `release-assets.githubusercontent.com`**
    # （前者解析成 127.0.0.1 走它的反代，后者仍是真实的 185.199.x.x）。而 GitHub 现在把
    # `…/releases/download/…` **302 到这里** —— 于是链路是：
    #   github.com 拿到 302（有加速/镜像时能通）→ 落点这个域名**不在加速规则里**
    #   → 直连 185.199.x → **20 秒连接超时（WinError 10060）**。
    # 这正是"Release 大文件总是超时、而页面请求正常"的机制。
    # 补进来之后，302 之后的 URL 才能被 `_mirrorable()` 认出来、**也去尝试镜像前缀**。
    "release-assets.githubusercontent.com",
    # 老式/备用落点（早期 Release 资产曾走它，留着不吃亏）
    "github-releases.githubusercontent.com",
)


def _mirrorable(url: str) -> bool:
    """这个 URL 能不能套镜像前缀？（Release 资产 / raw 文件 / 整仓下载）"""
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    return host in MIRRORABLE_HOSTS


def resolve_lines(url: str, mode: str) -> list[Line]:
    """按策略给出尝试顺序（只在需要时才有镜像）。"""
    if mode == "direct" or not _mirrorable(url):
        return [DIRECT]
    mirrors = list(DEFAULT_LINES[1:])
    # ⚠️ **解析不了域名的先剔掉，不管哪种模式**（`mirror` 模式原先直接 return，绕过了这里，
    #    于是"只用镜像"的用户照样每次先白试一遍死域名 —— 2026-10-04 由测试抓到）。
    # 而且**任何兜底都不许把它们放回来**：域名解析不了 = 这条线路确定不可用，试了纯属白等。
    now = time.time()
    dns_ok = [line for line in mirrors if _DNS_DEAD.get(line.name, 0) <= now]
    if mode == "mirror":
        return dns_ok or [DIRECT]
    cache = _load_lines_cache()
    # 有成绩的按速度排前面；失败的临时跳过（**全被跳过时退回"没被 DNS 拉黑的那部分"**，
    # 不能因此不下 —— 但也绝不把解析不了域名的放回来）
    mirrors.sort(key=lambda line: -float((cache.get(line.name) or {}).get("mbps") or 0))
    dns_dead = [line for line in mirrors if _DNS_DEAD.get(line.name, 0) > now]
    if dns_dead:
        _log(None, "[线路] 跳过 " + "、".join(line.name for line in dns_dead)
                   + f"（上次解析不了域名，{int(DNS_DEAD_TTL / 60)} 分钟内不再白试它）")
    fresh = [line for line in dns_ok if not _line_blocked(line.name, cache)] or dns_ok
    # 直连连续失败过就跳过它 —— 否则每次都要白等一个探测超时（实测直连超时是 8 秒）
    # ⚠️⚠️ **直连也要按实测速度决定排不排第一**（2026-10-03 用户：
    #     「**现在下载怎么这么不稳定，这都不换线？**」）。
    #
    # 原逻辑是「直连只要没被拉黑就永远第一位」。实测到的两种情况都会坑：
    #   ① 「成功但极慢」的直连（ok=true, mbps=0.009，28 MB 要 52 分钟）
    #      **永远不会被拉黑**（fails=0）⇒ 每次下载都先陪它耗到底；
    #   ② 拉黑只有 5 分钟 TTL（LINE_FAIL_TTL=300）⇒ 解封后又优先试它，
    #      于是「慢 → 拉黑 → 用镜像 → 解封 → 又试直连」无限循环 —— 这就是不稳定。
    #
    # 现在：直连**实测过**且**明显慢于**最快镜像（DIRECT_SLOW_RATIO 倍）时排到后面。
    # 用**倍数**避免一次抖动就误判；直连没测过（首次）或速度正常时仍保持直连优先。
    direct_mbps = float((cache.get(DIRECT.name) or {}).get("mbps") or 0)
    best_mirror = max(
        (float((cache.get(line.name) or {}).get("mbps") or 0) for line in fresh),
        default=0.0,
    )
    # ⚠️⚠️ **判据不能依赖「镜像有没有速度记录」**（2026-10-03 实测踩到）：
    # 第一版写的是 `best_mirror > direct_mbps * DIRECT_SLOW_RATIO`，而实测那份缓存里
    # **只有直连一条记录、镜像的 mbps 是空的** ⇒ `best_mirror = 0` ⇒ 条件永不成立
    # ⇒ 直连照样排第一（用户报的就是「这都不换线」）。所以判据必须**自足**。
    #
    # 现在两条任一成立就让位：
    #   ① 直连实测速度**低于「可用线」阈值**（DEAD_MBPS）—— 这正是我们判别人家
    #      "死线"用的同一把尺子；它自己都达不到，当然该先试镜像；
    #   ② 或者镜像实测过、且**明显更快**（保留倍数判据，镜像有数据时更精准）。
    direct_too_slow = bool(
        direct_mbps > 0 and (
            direct_mbps < DEAD_MBPS
            or (best_mirror > 0 and best_mirror > direct_mbps * DIRECT_SLOW_RATIO)
        )
    )
    if direct_too_slow:
        _log(None, f"[线路] 直连上次只有 {direct_mbps:.3f} MB/s"
                   f"（镜像 {best_mirror:.3f}）—— 低于可用线 {DEAD_MBPS}，这次先试镜像")
    head = [] if (_line_blocked(DIRECT.name, cache) or direct_too_slow) else [DIRECT]
    # `fresh` 上面已经保证"全被冷却时退回 dns_ok"，所以这里直接拼即可；
    # 若 dns_ok 也是空的（镜像域名全解析不了），就只剩直连 —— 快速失败好过白试死域名。
    return [*head, *fresh]


# ---------------------------------------------------------------------------
# 下载（导出给外部用的入口）
# ---------------------------------------------------------------------------
def _note_speed(done: int, total: int) -> None:
    """把"当下这次下载的速度"记进**全局状态**，让任何界面都能读到。

    ⚠️ 2026-10-04（用户报「进度条只是刷新慢，**速度卡一直横线**」）：
    速度原先只在 `api._make_dep_progress().byte_progress` 里算，而**一键启动**那条路
    （`launcher.launch` → `runtime_deps.ensure_all(progress=...)`）**根本没传 byte_progress**
    ⇒ 依赖页读 `_dep_task.speed_bps` 永远是 0 ⇒ 横线；进度也只能靠"一项完成跳一下"。
    现在改成**在 fastnet 内部采样**（任何调用方、任何路径都经过这里），UI 通过
    `global_speed()` 就能拿到实时速度 —— 不再依赖调用方记不记得接线。
    """
    now = time.time()
    with _STATE_LOCK:
        previous = _STATE.get("speed_sample")
        if not previous:
            _STATE["speed_sample"] = (now, int(done))
            return
        prev_at, prev_done = previous
        span = now - prev_at
        # ⚠️⚠️ **基准点只在间隔够长时才滑动**（2026-10-04 实测踩到）：
        # 回调是"每读 256 KB 一次"，实测间隔只有 **0.12 秒** —— 如果每次都把基准点推到最新，
        # `span` 就永远到不了 0.4 秒，速度**永远算不出来**（实测 `global_speed()` 一直是 0）。
        # 现在保持基准点不动、直到攒够 0.4 秒再算一次并滑动 —— 短间隔的采样直接忽略。
        if span < 0.4:
            return
        if done >= prev_done:
            instant = (int(done) - int(prev_done)) / span
            old = float(_STATE.get("speed_bps") or 0.0)
            _STATE["speed_bps"] = instant if old <= 0 else old * 0.6 + instant * 0.4
            _STATE["speed_at"] = now
        _STATE["speed_sample"] = (now, int(done))


def global_speed() -> float:
    """最近一次下载的平滑速度（MB/s 的字节口径 = B/s）；超过 3 秒没有新数据就归零。

    归零是**故意的**：下载之间的空档（解压 / 安装 / 校验）不该继续挂着一个早就不动的
    速度值，那会让用户以为卡住了（用户 2026-10-03 报过同类现象）。
    """
    with _STATE_LOCK:
        value = float(_STATE.get("speed_bps") or 0.0)
        at = float(_STATE.get("speed_at") or 0.0)
    return value if (time.time() - at) <= 3.0 else 0.0


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

    # ★ 速度的**全局出口**（2026-10-04）：不管调用方给不给 progress，都记一份全局速度。
    # 起因：一键启动那条路（`launcher.launch`）没传 byte_progress ⇒ 依赖页速度卡一直横线。
    # 在这里统一采样，任何下载路径（一键启动 / 安装组件 / Mod 下载）都能被 UI 读到。
    def _tracked(done: int, total: int) -> None:
        _note_speed(done, total)
        if progress:
            progress(done, total)

    # ★ 多线路动态抢块（2026-10-04 落地）：把其它候选线路的 URL 交给**第一条**线路的
    # 并发分块去共用 —— 实测比"单线路内并发"快 47%，而"每条线路各下自己那段"（静态等分）
    # 反而更慢（0.508 vs 0.664）。只给第一条：后面几条是它失败后的兜底，走原逻辑。
    # ★ 「慢直连去抢块、抢块不如直连就回直连」（用户 2026-10-05 原话：
    #   「只要直连不达到单片 1.5MB/s，而且没有 ghtoken，就直接进动态抢块测试，
    #     如果抢块比直连快就继续，比直连慢就恢复直连」＋「**抢块不包含直连**」）。
    #   `multi_alt` 一直就是"镜像线路池"、**不含直连** ✓；这里补的是两个新判据：
    #   ① 无 token 的直连把判死门槛提到 `SLOW_MBPS` —— 慢就直接换线路去抢块；
    #   ② 后面的线路以"直连实测速度"为下限 —— 抢块不如直连快就判死，最后回直连单连接。
    direct_probe_mbps = 0.0        # 直连实测速度（给后面的线路当门槛）
    slow_direct_skipped = False    # 直连因"太慢"被跳过 → 最后要回它兜底
    no_token = not _has_github_token()
    multi_alt = [line.apply(url) for line in lines[1:] if line is not DIRECT]
    if len(multi_alt) >= 1:
        _log(log, "多线路动态抢块已启用（**不含直连**）： "
                  + "、".join(f"{line.name}" for line in lines[1:])
                  + "（谁空谁领，连挂两次的线路本次淘汰）")

    for index, line in enumerate(lines):
        if len(lines) > 1:
            _log(log, f"尝试线路：{line.name}")
        # ⚠️ **直连先做一次 TCP 预检**（2026-10-04 实测后加）：连不上就立刻换镜像，
        # 不要白赔十几秒。只在多线路时做 —— `mode=direct` 是用户明确要直连，不许替他跳。
        # 判据是"连不上"，不是"慢"，所以不会误杀可用的慢直连（见 `_tcp_reachable` 的说明）。
        if line is DIRECT and len(lines) > 1 and not _tcp_reachable(url):
            message = f"直连不可达（{DIRECT_TCP_TIMEOUT:g}s 内连不上 {_host_of(url)}）"
            _log(log, f"{message} → 直接换镜像线路，不再等超时")
            _remember_line(line.name, False, 0.0)
            errors.append(f"{line.name}: {message}")
            continue
        # 多线路时单条线路的等待要短，坏线路要快速跳过
        line_timeout = timeout if len(lines) == 1 else min(timeout, LINE_TIMEOUT_MULTI)
        # ★ 这一条线路的"判死门槛"
        line_dead = dead_mbps
        if line is DIRECT and len(lines) > 1 and no_token:
            # 没有 token ⇒ 直连不开并发（**抢块不含直连**）。那它慢到 `SLOW_MBPS` 以下时
            # 就不该在这儿单连接慢慢磨 —— 把门槛提到 SLOW_MBPS，直接换线路去抢块。
            line_dead = max(dead_mbps, SLOW_MBPS)
        elif direct_probe_mbps > 0:
            # **抢块不如直连快就恢复直连**：拿直连实测速度当门槛，后面的线路连这个都达不到
            # 就判死 → 换下一条 → 都不行时由循环外的兜底回直连单连接。
            line_dead = max(dead_mbps, direct_probe_mbps)
        report = _attempt_line(
            line.apply(url), dest, line=line,
            alt_urls=multi_alt if index == 0 and multi_alt else None,
            log=log, progress=_tracked, timeout=line_timeout, policy=policy,
            expected_size=expected_size, expected_sha256=expected_sha256,
            dead_mbps=line_dead, cancel=cancel,
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
        # ⚠️ 但冷却用**限流专用的 5 分钟**（`LINE_RATE_LIMIT_TTL`），不要复用证书错误那个
        # 30 分钟 —— 限流会自己恢复，停半小时等于白瞎一条好线路（2026-10-04 修）。
        rate_limited = _looks_rate_limited(message)
        if rate_limited and not cert_error:
            _log(log, f"（{line.name} 返回 403/429 —— 这条线路在限流或拒绝访问，"
                      f"本次先跳过它 {int(LINE_RATE_LIMIT_TTL / 60)} 分钟，换个线路继续）")
        if network_wide:
            # ⚠️ 2026-10-04：**不再只是"不计入失败"** —— 那样域名已经没了的线路会永远
            # 排在候选里被反复白试（用户实测日志：一秒刷十几遍「gh.xmly.dev 失败」）。
            # 现在给它一个短冷却，到点自动放行；真正的临时抖动代价只是 10 分钟不试这条。
            _DNS_DEAD[line.name] = time.time() + DNS_DEAD_TTL
            _log(log, f"（{line.name} 这次解析不了域名 —— 已临时跳过它 {int(DNS_DEAD_TTL / 60)} 分钟，"
                      f"先换其它线路继续；域名要是真没了，它不会再拖慢每一次下载）")
        else:
            _remember_line(line.name, False, 0.0, cert_error=cert_error, rate_limited=rate_limited)
        errors.append(f"{line.name}: {report.message}")
        _log(log, f"线路 {line.name} 失败：{report.message}")
        if line is DIRECT:
            # 记下直连实测速度：后面的镜像线路要拿它当"至少得比这个快"的门槛；
            # 同时记住"直连是因为太慢被跳过的"，好在最后回它兜底。
            probe = float(getattr(report, "probe_mbps", 0) or 0)
            if probe > 0:
                direct_probe_mbps = probe
            if "低于" in message and "可用线" in message:
                slow_direct_skipped = True
        if cert_error:
            _log(log, f"（{line.name} 的 HTTPS 证书与你当前网络返回的不符 —— 常见于加速器/运营商"
                      f"劫持镜像域名；已临时跳过这条线路，不影响其它线路）")
        # **不动 dest**：目标文件要么是上一次下载好的完整文件，要么是用户自己的
        # 文件 —— 一条线路失败不代表它该被删（2026-10-01 修：原实现会 unlink 它，
        # 等于"这条线路不通就把你已下好的东西删了"）。半成品始终在 work 文件里，
        # 且只有 finish() 校验通过后才会原子落位到 dest。

    # ★ **抢块都没比直连快 ⇒ 回直连、用单连接把它下完**（用户 2026-10-05：
    # 「如果抢块比直连快就继续，**比直连慢就恢复直连**」）。直连慢，但我们没别的选择。
    # 用 `policy="never"` + `dead_mbps=0`：强制单连接、且不再因慢判死自己。
    if slow_direct_skipped and any(line is DIRECT for line in lines):
        _log(log, f"各线路都没比直连快（直连实测 {direct_probe_mbps:.2f} MB/s）→ 回到直连、"
                  f"用**单连接**下完（不并发：没有 token 时直连开多连接只会撞 GitHub 限流）")
        try:
            fallback = _attempt_line(
                url, dest, line=DIRECT, log=log, progress=_tracked, timeout=timeout,
                policy="never", expected_size=expected_size,
                expected_sha256=expected_sha256, dead_mbps=0.0, cancel=cancel,
            )
        except Exception as exc:  # noqa: BLE001
            fallback = DownloadReport(path=str(dest), ok=False, message=str(exc))
        if fallback.ok:
            fallback.line = DIRECT.name
            fallback.reason = f"{fallback.reason}；抢块不如直连，已回直连单连接".strip("；")
            _remember_line(DIRECT.name, True, fallback.mbps)
            _set_speed(fallback, started)
            return fallback
        errors.append(f"{DIRECT.name}(回退): {fallback.message}")

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
    alt_urls: list[str] | None = None,      # ★ 多线路动态抢块：其它候选线路的 URL
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
        # ⚠️ 续传分支**仍按源层面判**（`_may_parallel`）：没有 token 的直连不许自己开多连接
        # —— 用户 2026-10-05：「**抢块不包含直连**」。
        if ((incomplete or resume_from) and supports_range and size
                and policy != "never" and _may_parallel(url)):
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
                    timeout=timeout, progress=progress, log=log, cancel=cancel,
                    alt_urls=alt_urls)
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
        # ⚠️ 续传 + **没有 token 的直连**：不许直连并发（抢块不含直连），但已知它慢时也不该
        # 在这儿单连接慢慢磨 —— **放弃这条线路**，让 `download()` 换到镜像去抢块。
        # 消息里带"低于…可用线"，与探测判死那句同格式：外层据此认出"是慢直连被跳过"，
        # 好在所有线路都不如它时回它兜底。
        last_mbps = _direct_last_mbps(url)
        if ((incomplete or resume_from) and supports_range and size
                and policy != "never" and not _may_parallel(url)
                and 0 < last_mbps < SLOW_MBPS):
            raise OSError(
                f"直连上次实测只有 {last_mbps:.2f} MB/s（低于 {SLOW_MBPS} MB/s 可用线）"
                f"且没有 token → 不在这儿单连接磨，换线路抢块")

        # ⚠️⚠️ **不再在这里用 `_may_parallel` 一票否决**（2026-10-05 用户要求：
        # 「只要直连不达到单片 1.5MB/s，而且没有 ghtoken，就直接进动态抢块测试，
        #  如果抢块比直连快就继续，比直连慢就恢复直连」）。
        # 真实 GitHub 直连在没有 token 时该不该并发，要看**实测速度** —— 慢到 `SLOW_MBPS`
        # 以下就进抢块试用，那必须等下面的单连接探测拿到速度才能判。所以这里只留与速度无关的几条。
        if not supports_range or (size and size < MIN_PARALLEL_BYTES) or policy == "never":
            reason = ("服务器不支持 Range" if not supports_range else
                      "文件较小，不值得并发" if size and size < MIN_PARALLEL_BYTES else
                      "已按设置关闭加速")
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
        # ⚠️⚠️ **2026-10-03 拆掉"太慢就不许并发"这道门槛**。
        #
        # 原先这里是 `too_slow_to_boost = 0 < probe_mbps < BOOST_FLOOR_MBPS(0.1)` ——
        # 探测低于 0.1 MB/s 就把并发压回单连接。它当时的依据是一次实测
        #（"探测 0.036 时单连接 0.229、8 连接 0.174，并发反而慢 24%"）。
        #
        # **但今天无 VPN 直连香蕉网的三组对照结论正好相反**：
        #     单连接   0.008 MB/s
        #     4 连接   0.034 MB/s   （快 4.3 倍）
        #     16 连接  0.104 MB/s   （快 13 倍）—— 16 条连接全部拿到数据，没被限流拒连
        # **恰恰是最慢的线路上并发收益最大**，而这道门槛正好把最该用并发的场景排除了。
        #
        # 现在：**极慢线路也照样上并发**，去留完全交给下面的**试用窗口**决定 ——
        # 上并发先跑 BOOST_TRIAL_SECONDS 秒，拿实测速度与单连接探测值比，
        # 不划算就切回单连接（那套逻辑本来就在，比一个静态阈值可靠得多）。
        # 只把线程数按探测速度收敛一点：极慢时别一上来就 20 条连接。
        # ⚠️⚠️ **`threads` 必须在任何分支之前就有值**（2026-10-03 又踩一次）：
        # 下面那块"极慢线路也照样上并发"的代码会 `threads = max(12, min(threads, ...))`
        # —— 而 `threads` 原本要到更下面（真正要并发时）才赋值。
        # 以前 `DEAD_MBPS=0.3` 总能把慢线路判死、走不到那段，所以一直没暴露；
        # 阈值降到 0.02 后判死不再触发，当场 `UnboundLocalError: threads`。
        # （这个坑 2026-10-02 因为 `policy="always"` 跳过探测段踩过一次，同因。）
        if not size:
            threads = recommended_threads(0)
        else:
            threads = recommended_threads(max(size - written, 1))

        if 0 < report.probe_mbps < BOOST_FLOOR_MBPS:
            # ⚠️ **别把线程数压太低**（2026-10-03 两组实测的教训）：
            #   * 无 VPN：单连接 0.008 → 4 连接 0.034 → **16 连接 0.104**（13 倍）
            #   * 开 VPN：单连接 0.129 → 4 连接 0.090（**反而慢**）→ **16 连接 0.641**（5 倍）
            # 两次都是"4 条不够、16 条才吃满"。所以慢线路也直接给足 12 条起步
            #（MAX_THREADS=20 是上限，块大小会按线程数自适应，不会切碎）。
            threads = max(12, min(threads, MAX_THREADS))
            _log(log, f"线路很慢（探测 {report.probe_mbps:.3f} MB/s）→ 仍用 {threads} 连接试"
                      f"（实测慢线路上并发收益最大，且 4 条不够、要十几条才吃满），"
                      f"试用窗口后按实测速度决定去留")
        # ★ **这一刻允不允许并发**（用户 2026-10-05 的规则，判据都在 `_parallel_gate` 里）：
        # 没有 token 的真实 GitHub 直连，只有慢到 `SLOW_MBPS` 以下才放行进抢块试用。
        gate, gate_note = _parallel_gate(url, report.probe_mbps, policy)
        need_boost = policy == "always" or (gate and (slow or stalled))
        if gate and need_boost:
            _log(log, f"决定启用并发抢块：{gate_note}")

        if not need_boost:
            # 两种情形都走这里：链路够快（不折腾），或这个源此刻不许并发
            report.reason = (f"单连接 {report.probe_mbps:.2f} MB/s（够快，不启用加速）"
                             if gate else
                             f"单连接 {report.probe_mbps:.2f} MB/s（{gate_note}）")
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
                max_seconds=BOOST_TRIAL_SECONDS, cancel=cancel,
                alt_urls=alt_urls,
                expected_mbps=float(report.probe_mbps or 0.0))          # 试用窗口：到点不再提交新块
            done_now = sum(b - a + 1 for a, b in _load_parts(work, size))
            if size and done_now < size and done_now > written:
                boost_mbps = _mbps(done_now - written, max(time.time() - trial_started, 1e-6))
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
                        timeout=timeout, progress=progress, log=log, cancel=cancel,
                        alt_urls=alt_urls)
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
