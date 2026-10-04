"""Steam++ / 加速器环境下的下载链路回归（2026-10-04 实测后加）。

两条独立的事实（都是本机实测拿到的）：

1. **Release 资产的真实落点是 `release-assets.githubusercontent.com`**（`…/releases/download/…`
   会 302 到它）。Steam++（Watt Toolkit）的 hosts **覆盖了 `objects.githubusercontent.com`
   却没覆盖这个域名** —— 所以它必须进 `MIRRORABLE_HOSTS`，否则那个 URL 永远只走直连。
2. **关掉加速器时，`github.com` 直连是连不上的**（实测用真实 IP 直连，20 秒后 WinError 10060）。
   而 `DEFAULT_LINES` 里直连排第一 ⇒ 每次下载都要先白赔十几秒才轮到镜像 ——
   用户看到的就是"下载一直卡着 / 20 秒超时"。
   现在直连先过一次 **TCP 预检**：连不上就立刻换镜像（只判"连不上"，不误杀"慢"）。

这里钉住这两条，别让它们再退化。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import fastnet


# ---------------------------------------------------------------------------
# ① 可镜像主机名单
# ---------------------------------------------------------------------------


def test_release_asset_host_is_mirrorable():
    """`release-assets.githubusercontent.com` 必须能被镜像前缀认出来。"""
    assert fastnet._mirrorable(
        "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?x=1")
    assert fastnet._mirrorable("https://github.com/a/b/releases/download/v1/c.exe")
    assert not fastnet._mirrorable("https://gamebanana.com/dl/123")


# ---------------------------------------------------------------------------
# ② 直连 TCP 预检
# ---------------------------------------------------------------------------


class _FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_tcp_reachable_true_when_connection_opens(monkeypatch):
    monkeypatch.setattr(fastnet, "get_proxy", lambda: "")
    monkeypatch.setattr(fastnet.socket, "create_connection", lambda *a, **k: _FakeSocket())
    assert fastnet._tcp_reachable("https://github.com/a/b") is True


def test_tcp_reachable_false_when_connection_fails(monkeypatch):
    monkeypatch.setattr(fastnet, "get_proxy", lambda: "")

    def boom(*args, **kwargs):
        raise OSError("timed out")

    monkeypatch.setattr(fastnet.socket, "create_connection", boom)
    assert fastnet._tcp_reachable("https://github.com/a/b") is False


def test_tcp_reachable_checks_proxy_host_when_proxy_configured(monkeypatch):
    """有代理时要连**代理**（否则会在直连被墙的机器上误跳所有线路）。"""
    seen: list[tuple] = []

    def record(address, timeout=None):
        seen.append(address)
        return _FakeSocket()

    monkeypatch.setattr(fastnet, "get_proxy", lambda: "http://127.0.0.1:7897")
    monkeypatch.setattr(fastnet.socket, "create_connection", record)

    assert fastnet._tcp_reachable("https://github.com/a/b") is True
    assert seen == [("127.0.0.1", 7897)]


def test_tcp_precheck_never_blocks_when_it_cannot_decide(monkeypatch):
    """拿不到主机名时保守返回 True（宁可让原流程去试，也不要误跳一条线路）。"""
    monkeypatch.setattr(fastnet, "get_proxy", lambda: "")
    assert fastnet._tcp_reachable("not-a-url") is True


# ---------------------------------------------------------------------------
# ③ download()：直连不可达时**先跳过它**，直接走镜像
# ---------------------------------------------------------------------------


def test_download_skips_direct_when_tcp_unreachable(monkeypatch, tmp_path: Path):
    tried: list[str] = []

    def fake_attempt(url, dest, *, line, **kwargs):
        tried.append(line.name)
        return fastnet.DownloadReport(ok=True, path=str(dest), bytes=123, seconds=0.5,
                                      mbps=1.0, line=line.name, message="ok")

    monkeypatch.setattr(fastnet, "_line_blocked", lambda name, cache: False)
    monkeypatch.setattr(fastnet, "_tcp_reachable", lambda url, **kwargs: False)
    monkeypatch.setattr(fastnet, "_attempt_line", fake_attempt)

    logs: list[str] = []
    report = fastnet.download(
        "https://github.com/jing-hy/EndfieldModController/releases/download/v1.0.8/x.exe",
        tmp_path / "x.exe", log=logs.append, timeout=10, cancel=lambda: False,
    )

    assert report.ok is True
    assert "直连" not in tried, "直连连不上时不该还去试它（那正是十几秒白等）"
    assert tried, "应该落到镜像线路上"
    assert any("直连不可达" in line for line in logs)


def test_download_keeps_direct_when_only_one_line(monkeypatch, tmp_path: Path):
    """`line_mode=direct`（只有直连一条）时**不许**替他跳过 —— 那是用户明确的选择。"""
    tried: list[str] = []

    def fake_attempt(url, dest, *, line, **kwargs):
        tried.append(line.name)
        return fastnet.DownloadReport(ok=True, path=str(dest), bytes=1, seconds=0.1,
                                      mbps=1.0, line=line.name, message="ok")

    monkeypatch.setattr(fastnet, "_line_blocked", lambda name, cache: False)
    monkeypatch.setattr(fastnet, "_tcp_reachable", lambda url, **kwargs: False)
    monkeypatch.setattr(fastnet, "_attempt_line", fake_attempt)

    report = fastnet.download(
        "https://github.com/a/b/releases/download/v1/c.exe", tmp_path / "c.exe",
        line_mode="direct", log=lambda message: None, timeout=5, cancel=lambda: False,
    )

    assert report.ok is True
    assert tried == ["直连"]
