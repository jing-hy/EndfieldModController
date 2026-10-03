"""照 PCL（ModNet.vb）补的两条判据（2026-10-03）。

PCL 的 `TryBeginThread` 里对 github.com / bmclapi / pcl2-server 这类源**直接不分片**
（它们按连接数限流，多线程只会更容易被拒）；`SourceFail` 里 `(403)`/`(429)`
会**直接禁用那个源**。这两条我们照搬，但要保证**镜像域名不受影响** ——
不然等于把自己最好用的线路也一起降级了。
"""
from endfieldmodcontroller import fastnet


def test_github_direct_depends_on_token(monkeypatch):
    """★ GitHub 直连能不能并发，**由有没有 token 决定**（2026-10-03 用户规则）。

    用户原话：「**直连应该在没有 ghtoken 的时候禁止并发**」。
    理由：GitHub 对**未认证**请求按 IP 限流 —— 直连开并发只是让同一个 IP 在更短时间内
    发更多请求，更容易 403/429，反而更慢甚至失败；有 token 时额度 5000 次/小时，
    并发才有意义（用户实测直连 16 连接 0.203 MB/s vs 单连接 0.032，**6.3 倍**）。

    ⚠️ 这条**取代**了原来"照 PCL 名单一律单线程"的老判据 ——
    那批主机现在改成看 token；其它主机（bmclapi 等）仍一律单线程。
    """
    monkeypatch.setattr(fastnet, "_has_github_token", lambda: False)
    assert fastnet._may_parallel("https://github.com/a/b.zip") is False
    assert fastnet._may_parallel("https://objects.githubusercontent.com/x") is False
    monkeypatch.setattr(fastnet, "_has_github_token", lambda: True)
    assert fastnet._may_parallel("https://github.com/a/b.zip") is True
    assert fastnet._may_parallel("https://objects.githubusercontent.com/x") is True


def test_non_github_blocked_hosts_stay_single(monkeypatch):
    """名单里**非 GitHub** 的那批主机仍然一律单线程（token 与它们无关）。"""
    monkeypatch.setattr(fastnet, "_has_github_token", lambda: True)
    for url in ("https://bmclapi2.bangbang93.com/a.zip",
                "https://meloong.com/a.zip",
                "https://optifine.net/a.zip"):
        assert fastnet._may_parallel(url) is False, f"{url} 仍应单线程"


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
