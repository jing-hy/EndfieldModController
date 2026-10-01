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
        self.assertFalse(rows["gh.xmly.dev"]["blocked"])


if __name__ == "__main__":
    unittest.main()
