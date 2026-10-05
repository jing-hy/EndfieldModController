"""「没 token 的慢直连 → 去镜像抢块；抢块不如直连 → 回直连单连接」的回归测试（2026-10-05）。

用户原话：「**只要直连不达到单片 1.5MB/s，而且没有 ghtoken，就直接进动态抢块测试，
如果抢块比直连快就继续，比直连慢就恢复直连**」＋「**抢块不包含直连**」。

要守住的性质：
* **无 token 时直连自己永不开多连接**（`_parallel_gate` 对它一律 False）—— 这就是"抢块不含直连"；
* 无 token + 直连 **慢**（< `SLOW_MBPS`）⇒ 直连那条线路的判死门槛被提到 `SLOW_MBPS`，
  于是**换到镜像去抢块**，而不是在直连上单连接慢慢磨；
* 后面的线路以"**直连实测速度**"为下限 ⇒ 抢块不如直连快就判死；
* 所有线路都不如直连 ⇒ **回直连、用单连接把它下完**（`policy="never"`、`dead_mbps=0`）。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import fastnet

URL = "https://github.com/o/r/releases/download/v1/f.zip"


def _isolate(monkeypatch, attempts) -> list[tuple[str, str, float]]:
    """打桩成一个"只有直连与镜像两条线路、且不碰真网络"的环境。"""
    calls: list[tuple[str, str, float]] = []

    def fake_attempt(url, dest, *, line, policy="auto", dead_mbps=0.0, **kwargs):
        calls.append((line.name, policy, float(dead_mbps)))
        return attempts(line, str(dest), policy, float(dead_mbps))

    monkeypatch.setattr(fastnet, "_has_github_token", lambda: False)
    monkeypatch.setattr(fastnet, "_load_lines_cache", lambda: {})
    monkeypatch.setattr(fastnet, "_line_blocked", lambda name, cache: False)
    monkeypatch.setattr(fastnet, "_tcp_reachable", lambda url, **kwargs: True)
    monkeypatch.setattr(fastnet, "_remember_line", lambda *a, **k: None)
    monkeypatch.setattr(fastnet, "_attempt_line", fake_attempt)
    monkeypatch.setattr(fastnet, "probe", lambda url, timeout=0: (10_000_000, True, url))
    return calls


def _slow_probe(dest: str, mbps: float, floor: float) -> fastnet.DownloadReport:
    return fastnet.DownloadReport(
        ok=False, path=dest, probe_mbps=mbps,
        message=f"探测速度仅 {mbps:.2f} MB/s（低于 {floor} MB/s 可用线），放弃这条线路",
    )


def test_parallel_gate_never_lets_direct_go_multi(tmp_path, monkeypatch):
    """★ 无 token 的真实 GitHub 直连：**不论快慢**都不许自己开多连接（抢块不含直连）。"""
    monkeypatch.setattr(fastnet, "_has_github_token", lambda: False)
    for mbps in (0.2, 1.0, 5.0, 50.0):
        allowed, note = fastnet._parallel_gate("https://github.com/o/r/x.zip", mbps, "auto")
        assert allowed is False, f"直连在 {mbps} MB/s 时也不该被允许并发：{note}"
        assert "不含直连" in note or "不开并发" in note, note
    # 有 token 时允许直连并发
    monkeypatch.setattr(fastnet, "_has_github_token", lambda: True)
    assert fastnet._parallel_gate("https://github.com/o/r/x.zip", 0.5, "auto")[0] is True


def test_mirror_lines_may_go_parallel(tmp_path, monkeypatch):
    """镜像线路（抢块池里那些）不受限制 —— 慢直连换过去才有意义。"""
    monkeypatch.setattr(fastnet, "_has_github_token", lambda: False)
    allowed, note = fastnet._parallel_gate("https://ghproxy.net/https://github.com/o/r/x.zip",
                                           0.3, "auto")
    assert allowed is True, note


def test_slow_direct_without_token_hands_over_to_mirror(tmp_path, monkeypatch):
    """⭐ 无 token + 直连慢 ⇒ 直连的门槛被提到 SLOW_MBPS，直接换镜像（去抢块）。"""
    def attempts(line, dest, policy, dead_mbps):
        if line is fastnet.DIRECT:
            return _slow_probe(dest, 0.50, dead_mbps)
        return fastnet.DownloadReport(ok=True, path=dest, bytes=10_000_000, seconds=2.0, mbps=5.0)

    calls = _isolate(monkeypatch, attempts)
    report = fastnet.download(URL, tmp_path / "f.zip", log=lambda *_: None)
    assert report.ok, report.message
    assert calls[0][0] == fastnet.DIRECT.name, f"先试直连：{calls}"
    assert calls[0][2] >= fastnet.SLOW_MBPS, (
        f"无 token 的直连门槛要提到 SLOW_MBPS（{fastnet.SLOW_MBPS}），实际 {calls[0][2]}")
    assert len(calls) >= 2 and calls[1][0] != fastnet.DIRECT.name, f"慢直连之后应当换线路：{calls}"


def test_mirrors_are_held_to_the_direct_speed(tmp_path, monkeypatch):
    """⭐ 抢块（镜像）**不如直连快就恢复直连**：镜像门槛 = 直连实测速度。"""
    direct_mbps = 1.20

    def attempts(line, dest, policy, dead_mbps):
        if line is fastnet.DIRECT and policy == "never":
            return fastnet.DownloadReport(ok=True, path=dest, bytes=10_000_000,
                                          seconds=10.0, mbps=direct_mbps)
        if line is fastnet.DIRECT:
            return _slow_probe(dest, direct_mbps, dead_mbps)
        # 镜像比直连慢 → 应当被判死（门槛就是直连速度）
        return _slow_probe(dest, 0.30, dead_mbps)

    calls = _isolate(monkeypatch, attempts)
    report = fastnet.download(URL, tmp_path / "f.zip", log=lambda *_: None)
    assert report.ok, report.message
    assert calls[-1][0] == fastnet.DIRECT.name, f"最后应当回直连：{calls}"
    assert calls[-1][1] == "never", f"回直连必须用单连接（policy=never）：{calls}"
    assert calls[-1][2] == 0.0, f"回直连不该再因慢判死自己：{calls}"
    # 中间那些镜像线路的门槛必须 ≥ 直连实测速度
    mirror_calls = [item for item in calls[1:-1] if item[0] != fastnet.DIRECT.name]
    assert mirror_calls, f"应当试过镜像线路：{calls}"
    assert all(item[2] >= direct_mbps for item in mirror_calls), (
        f"镜像的门槛要拿直连速度当底线：{mirror_calls} vs 直连 {direct_mbps}")


def test_direct_slow_peak_does_not_reopen_boost_for_it(tmp_path, monkeypatch):
    """连"回直连兜底"那一次也不许直连并发（否则等于绕过"抢块不含直连"）。"""
    seen: list[str] = []

    def attempts(line, dest, policy, dead_mbps):
        seen.append(f"{line.name}/{policy}")
        if line is fastnet.DIRECT and policy == "never":
            return fastnet.DownloadReport(ok=True, path=dest, bytes=1, seconds=1.0, mbps=0.9)
        if line is fastnet.DIRECT:
            return _slow_probe(dest, 0.90, dead_mbps)
        return _slow_probe(dest, 0.10, dead_mbps)

    _isolate(monkeypatch, attempts)
    with monkeypatch.context() as patch:
        # 兜底那次必须走 policy="never"（`_attempt_line` 内部据此不并发）
        patch.setattr(fastnet, "_parallel_gate",
                      lambda url, mbps, policy: (False, "没有 token 的直连不开并发（抢块不含直连）"))
        report = fastnet.download(URL, tmp_path / "f.zip", log=lambda *_: None)
    assert report.ok
    assert any(item.startswith(f"{fastnet.DIRECT.name}/never") for item in seen), seen
