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
MAX_THREADS = 16
READ_CHUNK = 262144
# 单次读多久没数据算"抖动/卡死"，切并发续传
STALL_SECONDS = 20
# 探测连接的超时（要短，坏线路要快速跳过）
PROBE_TIMEOUT = 15
# 某条线路失败后多久再试
LINE_FAIL_TTL = 30 * 60
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


def _mbps(size: int, seconds: float) -> float:
    return (size / 1048576.0 / seconds) if seconds > 0 else 0.0


def _open(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30):
    request = urllib.request.Request(url, headers={**BASE_HEADERS, **(headers or {})})
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
) -> tuple[int, bool, str]:
    """单连接下载（offset 起）。

    返回 (本次写入字节数, 是否被"卡住"打断, 说明)。
    stop_after > 0 时下够这么多字节就主动停下（用于测速探测）。
    """
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    written = 0
    mode = "ab" if offset else "wb"
    try:
        with _open(url, headers=headers, timeout=timeout) as response:
            with open(dest, mode) as fh:
                while True:
                    chunk = response.read(READ_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(offset + written, total)
                    if stop_after and written >= stop_after:
                        return written, False, "probe"
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        if written:
            return written, True, f"读取中断（已下 {written // 1024} KB）: {exc}"
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
) -> int:
    """并发分块下载，**块级断点续传**：已完成的块记在 sidecar 里，中断后不重下。

    start：没有块记录时（单连接顺序下载的残留）把前 start 字节视为已完成。
    """
    spans = [(pos, min(pos + chunk - 1, size - 1)) for pos in range(0, size, chunk)]
    done_spans = _load_parts(dest, size)
    if not done_spans and start > 0:
        done_spans = {(a, b) for a, b in spans if b < start}
    todo = [span for span in spans if span not in done_spans]

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
            try:
                headers = {"Range": f"bytes={begin}-{end}"}
                with _open(url, headers=headers, timeout=timeout) as response:
                    data = response.read()
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
                time.sleep(0.4 * (attempt + 1))
        raise OSError(f"分块 {begin}-{end} 重试 4 次仍失败：{last_error}")

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(threads, len(todo)))) as pool:
            list(pool.map(fetch, todo))
    if len(done_spans) >= len(spans):
        _clear_parts(dest)      # 块齐了才算下完
    return state["retries"]


def recommended_threads(size: int) -> int:
    by_size = max(1, size // (4 << 20))
    return int(max(4, min(MAX_THREADS, by_size if by_size > 4 else 8)))


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


def _remember_line(name: str, ok: bool, mbps: float) -> None:
    """记一条线路的成绩（几 KB 的 JSON，不常驻、可随时删）。"""
    cache = _load_lines_cache()
    entry = cache.get(name) if isinstance(cache.get(name), dict) else {}
    if mbps > 0:
        entry["mbps"] = round(float(mbps), 3)
    entry["at"] = int(time.time())
    if ok:
        entry["ok"] = True
        entry.pop("fail_at", None)
    else:
        entry["ok"] = False
        entry["fail_at"] = int(time.time())
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
    entry = cache.get(name) or {}
    fail_at = int(entry.get("fail_at") or 0)
    return bool(fail_at) and (time.time() - fail_at) < LINE_FAIL_TTL


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
    return [DIRECT, *(fresh or mirrors)]


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

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = resolve_lines(url, mode)
    started = time.time()
    errors: list[str] = []

    for line in lines:
        if len(lines) > 1:
            _log(log, f"尝试线路：{line.name}")
        # 多线路时单条线路的等待要短，坏线路要快速跳过
        line_timeout = timeout if len(lines) == 1 else min(timeout, 25)
        report = _attempt_line(
            line.apply(url), dest, line=line,
            log=log, progress=progress, timeout=line_timeout, policy=policy,
            expected_size=expected_size, expected_sha256=expected_sha256,
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
        _remember_line(line.name, False, 0.0)
        errors.append(f"{line.name}: {report.message}")
        _log(log, f"线路 {line.name} 失败：{report.message}")
        try:
            if dest.is_file():
                dest.unlink()
        except OSError:
            pass

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
) -> DownloadReport:
    """在**一条**线路上完成下载；慢/抖时临时上并发。不负责计时汇总与日志收尾。"""
    report = DownloadReport(path=str(dest))
    started = time.time()


    size, supports_range, final_url = probe(url, timeout=min(timeout, PROBE_TIMEOUT))
    if not size:
        size = expected_size
    _log(log, f"开始下载 {dest.name}"
             + (f"（{size / 1048576:.1f} MB）" if size else ""))

    # 已经下完且大小一致 → 直接跳过
    # 已经下完（大小一致 **且没有未完成的分块记录**）→ 直接跳过
    if dest.is_file() and size and dest.stat().st_size == size and not has_partial_parts(dest):
        report.bytes = size
        report.seconds = 0.0
        report.reason = "文件已存在且大小一致"
        report.message = "已存在"
        _log(log, "已存在且大小一致，跳过下载")
        return report

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
        """校验通过后把工作文件落位到目标路径。"""
        _clear_parts(work_path)
        os.replace(work_path, dest)

    try:
        # 断点续传优先：直接用分块把缺的补齐（哪怕设置里关了加速也续，否则前面的白下）
        if (incomplete or resume_from) and supports_range and size:
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
                    timeout=timeout, progress=progress, log=log)
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
        if not supports_range or (size and size < MIN_PARALLEL_BYTES) or policy == "never":
            reason = ("服务器不支持 Range" if not supports_range else
                      "文件较小，不值得并发" if size and size < MIN_PARALLEL_BYTES else "已按设置关闭加速")
            report.reason = reason
            # 已有部分数据时按追加写（不截断），否则从头写
            written, stalled, note = _download_sequential(
                url, work, offset=partial if (supports_range and partial) else 0,
                total=size, timeout=timeout, progress=progress, log=log)
            total_written = (partial if (supports_range and partial) else 0) + written
            report.bytes = total_written
            if size and total_written != size:
                raise OSError(f"下载不完整：{total_written:,} / {size:,} 字节")
            report.ok = True
            report.message = note or "完成"
            finish(work)
            _set_speed(report, started)
            return report

        # ① 单连接探测：先下 PROBE_BYTES 看看这条链路到底行不行
        probe_target = PROBE_BYTES if size > MIN_PARALLEL_BYTES else size
        written, stalled, note = _download_sequential(
            url, work, total=size, timeout=timeout, progress=progress, log=log, stop_after=probe_target)
        probe_seconds = max(time.time() - started, 1e-6)
        report.probe_mbps = _mbps(written, probe_seconds)
        slow = report.probe_mbps < SLOW_MBPS
        need_boost = policy == "always" or slow or stalled

        if not need_boost:
            # 链路够快：接着单连接把剩下的下完（不折腾）
            report.reason = f"单连接 {report.probe_mbps:.2f} MB/s（够快，不启用加速）"
            _log(log, report.reason)
            rest, stalled2, note2 = _download_sequential(
                url, work, offset=written, total=size, timeout=timeout, progress=progress, log=log)
            report.bytes = written + rest
            if size and report.bytes != size:
                raise OSError(f"下载不完整：{report.bytes:,} / {size:,} 字节")
            report.message = note2 or "完成"
            finish(work)
            _set_speed(report, started)
            return report

        # ② 慢/抖 → 临时上并发分块（真正的"加速"）
        threads = recommended_threads(size - written)
        report.boosted = True
        report.threads = threads
        report.resumed_from = written
        report.reason = (
            f"探测速度 {report.probe_mbps:.2f} MB/s（低于 {SLOW_MBPS} MB/s 阈值）→ 临时启用 {threads} 连接并发"
            if slow else
            (f"单连接中断 → 临时启用 {threads} 连接并发续传" if stalled else
             f"已按设置强制启用 {threads} 连接并发")
        )
        _log(log, report.reason)
        with _STATE_LOCK:
            _STATE["active"] = int(_STATE.get("active") or 0) + 1
        try:
            report.retries = _download_parallel(
                url, work, size=size, start=written, threads=threads,
                timeout=timeout, progress=progress, log=log)
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

    if expected_sha256:
        actual = sha256_file(dest)
        if actual.lower() != expected_sha256.replace("sha256:", "").strip().lower():
            report.ok = False
            report.message = "sha256 校验失败"
            _set_speed(report, started)
            return report
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
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
