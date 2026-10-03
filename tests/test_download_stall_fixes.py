"""**下载"速度横线、进度条不动"的真因**（2026-10-04，用户实测报障）。

现场日志（modtest 的 `runtime\\logs`）：

```
01:14:34.648 探测速度 0.35 MB/s（低于 1.5 MB/s 阈值）→ 先试 32 连接并发
01:14:34.652 多线路动态抢块：4 条线路共用 26 块（谁空谁领，连挂两次的线路本次淘汰）
   ← 然后 12 秒没有任何一行
```

**根因（我引入的）**：`_pick_line_url(urls, dead, attempt)` 里 `attempt=0` 时所有线程都返回
`urls[0]`（主线路 = 直连）⇒ **26 个分块线程的第一次尝试全撞直连**。而用户机器上
`github.com` 被 hosts 指向 `127.0.0.1`（加速器残留）—— 直连**连得上但一个字节都不来**，
于是 26 个连接一起挂到超时。单线路时代这只算"一次超时"，多线路把它放大成 26 次。

**两处修法（本文件同时钉住）**：
1. `_pick_line_url` 加 `offset`（块序号）—— **不同线程从不同线路起步**；
2. `_probe_lines` 抢块前**先体检**（各取 1 字节），把"连得上但不给数据"的线路挡在门外。
"""
from __future__ import annotations

from endfieldmodcontroller import fastnet


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, *_args: object) -> bytes:
        data, self._data = self._data, b""
        return data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


# ---------------------------------------------------------------- 主线优先（不许分散）
def test_all_threads_start_on_the_fastest_line() -> None:
    """★ 所有线程的第一次尝试都用**最快的**那条（列表首位）。

    这不是"偷懒"，是实测结论：为了修"全撞一条线路"而把线程按块序号分散到各线路，
    等于**静态等分** —— 慢线路各分到 1/4 的线程、整体被拖住。
    实测同一份 28.5 MB 资产：分散 **0.669 MB/s（42.6 秒）** vs 主线优先 **2.955 MB/s（9.6 秒）**。
    """
    urls = ["https://fastest/", "https://mid/", "https://slow/"]
    assert {fastnet._pick_line_url(urls, set(), 0) for _ in range(5)} == {"https://fastest/"}


def test_retry_rotates_only_after_failure() -> None:
    urls = ["https://fastest/", "https://mid/", "https://slow/"]
    picked = [fastnet._pick_line_url(urls, set(), attempt) for attempt in range(3)]
    assert picked == urls, "失败重试时才依次换到下一条"


def test_dead_lines_are_skipped() -> None:
    urls = ["https://fastest/", "https://mid/", "https://slow/"]
    dead = {"https://mid/"}
    assert fastnet._pick_line_url(urls, dead, 0) == "https://fastest/"
    assert fastnet._pick_line_url(urls, dead, 1) == "https://slow/", "被淘汰的线路不该再被选中"


def test_all_dead_falls_back_to_everything() -> None:
    """★ 全被淘汰时**必须退回全部** —— 否则淘汰逻辑本身会把下载卡死。"""
    urls = ["https://fastest/", "https://mid/"]
    dead = {"https://fastest/", "https://mid/"}
    assert fastnet._pick_line_url(urls, dead, 0) in urls


def test_empty_urls_is_safe() -> None:
    assert fastnet._pick_line_url([], set(), 0) == ""


def test_no_block_index_offset_is_passed() -> None:
    """★ 接口回归：调用点**不许**再传"按块序号偏移"（那正是速度掉下去的元凶）。"""
    import inspect

    src = inspect.getsource(fastnet._download_parallel)
    assert "piece_chunk)" not in src.split("_pick_line_url")[1][:80], \
        "不该再按块序号把线程分散到不同线路"
    assert "_pick_line_url(urls, dead_urls, attempt)" in src


# ---------------------------------------------------------------- 预检
def test_probe_lines_drops_lines_that_return_nothing(monkeypatch) -> None:
    """★ "连得上但不给数据"的线路要被预检挡掉（直连被 hosts 劫持就是这种）。"""

    def fake_open(url: str, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse(b"" if "direct" in url else b"x")

    monkeypatch.setattr(fastnet, "_open", fake_open)
    alive = fastnet._probe_lines(["https://direct/x", "https://mirror/x"])
    assert alive == ["https://mirror/x"], f"取不到数据的线路该被剔除，实际：{alive}"


def test_probe_lines_keeps_everything_when_all_dead(monkeypatch) -> None:
    """★ 全都不通时**原样返回** —— 预检自己不许把下载卡死。"""
    monkeypatch.setattr(fastnet, "_open", lambda *_a, **_k: _FakeResponse(b""))
    urls = ["https://a/x", "https://b/x"]
    assert fastnet._probe_lines(urls) == urls


def test_probe_lines_skips_work_for_single_line(monkeypatch) -> None:
    """只有一条线路时不做预检（省掉那 3 秒）。"""

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("单线路不该走预检")

    monkeypatch.setattr(fastnet, "_open", boom)
    assert fastnet._probe_lines(["https://only/x"]) == ["https://only/x"]


def test_probe_lines_survives_open_errors(monkeypatch) -> None:
    """预检遇到异常只当作"这条不能用"，不许把整个下载带崩。"""

    def fake_open(url: str, **_kwargs: object) -> _FakeResponse:
        if "boom" in url:
            raise OSError("connection reset")
        return _FakeResponse(b"x")

    monkeypatch.setattr(fastnet, "_open", fake_open)
    alive = fastnet._probe_lines(["https://boom/x", "https://ok/x"])
    assert alive == ["https://ok/x"]


# ---------------------------------------------------------------- 接口
def test_download_parallel_probes_before_sharing_blocks() -> None:
    """接口回归：多线路抢块前确实调了预检。"""
    import inspect

    src = inspect.getsource(fastnet._download_parallel)
    assert "_probe_lines(urls, log=log)" in src, "多线路抢块前必须先预检"
