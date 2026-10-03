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


# ---------------------------------------------------------------------------
# 2026-10-03 多角度审查后补的回归
# ---------------------------------------------------------------------------

def test_rate_limited_uses_shorter_cooldown():
    """★ 403/429 是**临时**限流，冷却不该跟证书错误一样长（审查：30 分钟太久）。

    `_line_blocked` 是纯函数（缓存当参数传），所以直接喂两个缓存就能对照两档 TTL。
    """
    from endfieldmodcontroller import fastnet as f
    assert f.LINE_RATE_LIMIT_TTL < f.LINE_CERT_FAIL_TTL

    # 同一个时间点（已经过了限流那档的冷却）：限流线路该解封、证书线路仍该封着
    past = int(f.time.time()) - (f.LINE_RATE_LIMIT_TTL + 5)
    rate_cache = {"镜像A": {"ok": False, "rate": True, "fails": 99, "fail_at": past}}
    cert_cache = {"镜像B": {"ok": False, "cert": True, "fails": 99, "fail_at": past}}
    assert f._line_blocked("镜像A", rate_cache) is False, "限流冷却过了就该重新试它"
    assert f._line_blocked("镜像B", cert_cache) is True, "证书错误仍是长冷却"


def test_fresh_failure_blocks_then_recovers():
    """刚失败 → 跳过；过了普通 TTL → 恢复。"""
    from endfieldmodcontroller import fastnet as f
    now = int(f.time.time())
    cache = {"镜像C": {"ok": False, "fails": f.LINE_FAIL_THRESHOLD, "fail_at": now}}
    assert f._line_blocked("镜像C", cache) is True
    cache["镜像C"]["fail_at"] = now - (f.LINE_FAIL_TTL + 5)
    assert f._line_blocked("镜像C", cache) is False
