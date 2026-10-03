"""下载线路的"失败记账"规则（2026-10-01）。

背景（issue #6）：反馈者那边的 `https://ghproxy.net/` 返回的证书不含 ghproxy.net
（`Hostname mismatch`），于是每次下载都要在它身上白试一遍。但**同一时刻我这边实测
它是 200 正常的** —— 所以正确做法不是删掉这条线路，而是把"证书不匹配"识别成
**确定性失败**：一次就跳过、且冷却更久（同一网络里不会自愈）。

这里钉住四条：证书错一次即封、普通超时仍要连续两次才封、成功一次就解封、
以及两种冷却时长不同。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import fastnet


class LineFailureAccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-lines-")
        self.root = Path(self.tmp.name)
        self.cache_path = self.root / "lines.json"
        patcher = mock.patch.object(fastnet, "_cache_path", lambda: self.cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _blocked(self, name: str) -> bool:
        return fastnet._line_blocked(name, fastnet._load_lines_cache())

    def test_cert_error_blocks_after_one_failure(self) -> None:
        fastnet._remember_line("ghproxy.net", False, 0.0, cert_error=True)
        self.assertTrue(self._blocked("ghproxy.net"))

    def test_plain_timeout_needs_two_failures(self) -> None:
        fastnet._remember_line("ghproxy.net", False, 0.0)
        self.assertFalse(self._blocked("ghproxy.net"), "一次超时不该封掉线路")
        fastnet._remember_line("ghproxy.net", False, 0.0)
        self.assertTrue(self._blocked("ghproxy.net"))

    def test_success_clears_cert_mark(self) -> None:
        fastnet._remember_line("ghproxy.net", False, 0.0, cert_error=True)
        self.assertTrue(self._blocked("ghproxy.net"))
        fastnet._remember_line("ghproxy.net", True, 1.23)
        self.assertFalse(self._blocked("ghproxy.net"))
        entry = fastnet._load_lines_cache()["ghproxy.net"]
        self.assertNotIn("cert", entry)
        self.assertEqual(int(entry["fails"]), 0)

    def test_cert_cooldown_is_longer_than_plain(self) -> None:
        self.assertGreater(fastnet.LINE_CERT_FAIL_TTL, fastnet.LINE_FAIL_TTL)
        fastnet._remember_line("ghproxy.net", False, 0.0, cert_error=True)
        # 普通冷却（5 分钟）已经过去、证书冷却（30 分钟）还没到时，仍应被跳过
        base = fastnet._load_lines_cache()["ghproxy.net"]["fail_at"]
        with mock.patch.object(fastnet.time, "time", lambda: base + fastnet.LINE_FAIL_TTL + 1):
            self.assertTrue(self._blocked("ghproxy.net"))
        with mock.patch.object(fastnet.time, "time", lambda: base + fastnet.LINE_CERT_FAIL_TTL + 1):
            self.assertFalse(self._blocked("ghproxy.net"))

    def test_line_status_exposes_blocked_flag(self) -> None:
        fastnet._remember_line("ghproxy.net", False, 0.0, cert_error=True)
        rows = {row["line"]: row for row in fastnet.line_status()}
        self.assertTrue(rows["ghproxy.net"]["blocked"])
        self.assertFalse(rows["gh.nxnow.top"]["blocked"])

    def test_dead_mirror_is_not_in_default_lines(self) -> None:
        """★ `gh.xmly.dev` 的域名 2026-10-04 实测**已经不存在**了。

        它原本排在镜像第一位 —— 而 DNS 失败又命中"不计入失败"的豁免，于是
        **永远不进冷却、永远排第一、每次下载都白试**。用户现场日志：一秒刷十几遍
        「线路 gh.xmly.dev 失败：getaddrinfo failed」。
        """
        names = {line.name for line in fastnet.DEFAULT_LINES}
        self.assertNotIn("gh.xmly.dev", names, "域名已死的镜像不该留在默认线路表里")
        self.assertNotIn("hub.gitmirror.com", names, "同上（域名不存在）")
        # 实测能跑的三条必须在（2026-10-04 真实 Release 资产并发实测）
        self.assertIn("gh.nxnow.top", names)
        self.assertIn("ghproxy.net", names)
        self.assertIn("gh-proxy.com", names)

    def test_dns_failure_puts_line_on_short_cooldown(self) -> None:
        """★ DNS 解析失败 → 临时跳过这条线路（否则死域名会被无限白试）。"""
        fastnet._DNS_DEAD.clear()
        self.addCleanup(fastnet._DNS_DEAD.clear)
        with mock.patch.object(fastnet, "_attempt_line") as attempt:
            attempt.return_value = fastnet.DownloadReport(
                ok=False, message="<urlopen error [Errno 11001] getaddrinfo failed>")
            with mock.patch.object(fastnet, "_load_lines_cache", lambda: {}), \
                 mock.patch.object(fastnet, "_line_blocked", lambda name, cache: False), \
                 mock.patch.object(fastnet, "_log", lambda *a, **k: None):
                fastnet.download("https://github.com/o/r/releases/download/v1/f.zip",
                                 Path("_unused.zip"), line_mode="mirror")
        skipped = [name for name in ("gh.nxnow.top", "ghproxy.net", "gh-proxy.com")
                   if fastnet._DNS_DEAD.get(name, 0) > 0]
        self.assertTrue(skipped, "DNS 失败的线路必须被记进短冷却")

        # 冷却期内它不该再出现在候选里
        with mock.patch.object(fastnet, "_load_lines_cache", lambda: {}):
            lines = [line.name for line in fastnet.resolve_lines(
                "https://github.com/o/r/releases/download/v1/f.zip", "mirror")]
        for name in skipped:
            self.assertNotIn(name, lines, "冷却期内的死线路不该再被白试")


if __name__ == "__main__":
    unittest.main()
