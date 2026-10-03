"""照 PCL（ModNet.vb）补的两条判据（2026-10-03）。

PCL 的 `TryBeginThread` 里对 github.com / bmclapi / pcl2-server 这类源**直接不分片**
（它们按连接数限流，多线程只会更容易被拒）；`SourceFail` 里 `(403)`/`(429)`
会**直接禁用那个源**。这两条我们照搬，但要保证**镜像域名不受影响** ——
不然等于把自己最好用的线路也一起降级了。
"""
from endfieldmodcontroller import fastnet


def test_github_direct_is_not_parallel():
    """GitHub 直连按 PCL 的名单强制单线程。"""
    assert fastnet._may_parallel("https://github.com/a/b.zip") is False
    assert fastnet._may_parallel("https://objects.githubusercontent.com/x") is False


def test_mirror_hosts_still_parallel():
    """★ 关键：镜像（加速）域名必须照常分片，否则等于自己把好线路降级。"""
    assert fastnet._may_parallel("https://gh.xmly.dev/https://github.com/a/b.zip") is True
    assert fastnet._may_parallel("https://ghproxy.net/https://github.com/a/b.zip") is True
    assert fastnet._may_parallel("https://example.com/a.zip") is True


def test_host_match_is_exact_suffix():
    """不能误伤"名字里带 github.com"的别的站点。"""
    assert fastnet._may_parallel("https://notgithub.com.evil.test/a.zip") is True
    assert fastnet._may_parallel("https://mygithubcompany.com/a.zip") is True


def test_rate_limit_markers():
    """403/429 属于"这条线路被拒/被限流"，要记账并快速跳过。"""
    assert fastnet._looks_rate_limited("HTTP Error 403: Forbidden") is True
    assert fastnet._looks_rate_limited("HTTP Error 429: Too Many Requests") is True
    assert fastnet._looks_rate_limited("429 rate limit exceeded") is True


def test_timeout_is_not_rate_limited():
    """普通超时/断流**不是**确定性失败，不该把线路封掉。"""
    assert fastnet._looks_rate_limited("read timed out") is False
    assert fastnet._looks_rate_limited("Connection reset by peer") is False
    assert fastnet._looks_rate_limited("") is False


def test_bad_url_does_not_crash():
    assert fastnet._may_parallel("") is True
    assert fastnet._may_parallel("not a url") is True
