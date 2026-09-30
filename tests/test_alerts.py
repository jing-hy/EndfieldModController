"""公告 / 异常状态预警（alerts.json）的离线测试。

覆盖：contents 响应解码、条目规范化、过期判定、强制停留秒数的优先级、
「公告只弹一次」与「critical 每次都弹」这两条相反的行为，以及「还原配置」的可逆性。
全程不发网络请求（overview 支持直接喂文档）。
"""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import alerts
from endfieldmodcontroller.config import AppConfig


def _doc(items, **extra):
    return {"schema": 1, "alerts": items, **extra}


class AlertsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-alerts-")
        self.root = Path(self.tmp.name)
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.root / "runtime"),
            builtin_runtime_dir=str(self.root / "runtime" / "builtin"),
        )
        self.config._config_path = str(self.root / "config.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ------------------------------------------------------------ 解码 / 规范化
    def test_decode_contents_base64(self) -> None:
        payload = {"content": base64.b64encode(json.dumps(_doc([])).encode()).decode(), "encoding": "base64"}
        self.assertEqual(alerts.decode_contents(payload), _doc([]))

    def test_decode_contents_accepts_plain_document(self) -> None:
        self.assertEqual(alerts.decode_contents(_doc([{"id": "a"}])), _doc([{"id": "a"}]))

    def test_decode_contents_rejects_garbage(self) -> None:
        for bad in ({"foo": 1}, [], "x"):
            with self.assertRaises(ValueError):
                alerts.decode_contents(bad)

    def test_normalize_skips_items_without_id(self) -> None:
        items = alerts.normalize(_doc([{"title": "无 id"}, {"id": "ok", "title": "有 id"}]))
        self.assertEqual([i["id"] for i in items], ["ok"])

    def test_normalize_level_and_hold(self) -> None:
        items = alerts.normalize(_doc([
            {"id": "a", "level": "CRITICAL"},
            {"id": "b", "level": "乱写"},
            {"id": "c", "hold_seconds": 999},
            {"id": "d", "hold_seconds": -5},
        ]))
        self.assertEqual(items[0]["level"], "critical")
        self.assertEqual(items[1]["level"], "info")            # 非法级别兜底成 info
        self.assertEqual(items[2]["hold_seconds"], alerts.MAX_HOLD_SECONDS)
        self.assertEqual(items[3]["hold_seconds"], 0)

    # ------------------------------------------------------------ 过期 / 停留
    def test_is_expired(self) -> None:
        now = datetime(2026, 9, 30, 12, 0, 0)
        self.assertFalse(alerts.is_expired("", now))
        self.assertFalse(alerts.is_expired("2026-09-30", now))     # 当天仍有效
        self.assertTrue(alerts.is_expired("2026-09-29", now))
        self.assertTrue(alerts.is_expired("2026-09-30T11:00:00", now))
        self.assertFalse(alerts.is_expired("2026-09-30T13:00:00", now))
        self.assertFalse(alerts.is_expired("看不懂的日期", now))    # 解析不了就当不过期

    def test_hold_seconds_precedence(self) -> None:
        doc = _doc([], default_hold_seconds=20)
        self.assertEqual(alerts.hold_seconds(doc, None), 20)                     # 文档默认
        self.assertEqual(alerts.hold_seconds(doc, {"hold_seconds": 5}), 5)       # 条目优先
        self.assertEqual(alerts.hold_seconds(_doc([]), None), alerts.DEFAULT_HOLD_SECONDS)

    # ------------------------------------------------------------ 两档行为
    def test_announcements_pop_once_critical_always(self) -> None:
        doc = _doc(
            [{"id": "news", "level": "info", "title": "公告"},
             {"id": "ban", "level": "critical", "title": "封号预警"}],
            default_hold_seconds=7,
        )
        first = alerts.overview(self.config, document=doc)
        self.assertEqual([a["id"] for a in first["announcements"]], ["news"])
        self.assertEqual([a["id"] for a in first["critical"]], ["ban"])
        self.assertEqual(first["critical"][0]["hold_seconds"], 7)

        alerts.mark_seen(self.config, ["news"])
        second = alerts.overview(self.config, document=doc)
        self.assertEqual(second["announcements"], [])                          # 公告不再弹
        self.assertEqual([a["id"] for a in second["critical"]], ["ban"])       # 预警照样弹

    def test_expired_alert_not_returned(self) -> None:
        doc = _doc([{"id": "old", "level": "critical", "until": "2000-01-01"}])
        self.assertEqual(alerts.overview(self.config, document=doc)["critical"], [])

    def test_mark_seen_dedupes_and_caps(self) -> None:
        alerts.mark_seen(self.config, ["a", "a", "b"])
        alerts.mark_seen(self.config, ["b", "c"])
        ids = alerts._read_json(alerts.seen_path(self.config))["ids"]
        self.assertEqual(ids, ["a", "b", "c"])

    def test_load_document_falls_back_to_cache(self) -> None:
        alerts._write_json(alerts.cache_path(self.config), _doc([{"id": "cached"}]))
        with mock.patch.object(alerts, "fetch_document", side_effect=RuntimeError("断网")):
            doc = alerts.load_document(self.config)
        self.assertEqual([i["id"] for i in alerts.normalize(doc)], ["cached"])

    def test_overview_without_any_data(self) -> None:
        with mock.patch.object(alerts, "fetch_document", side_effect=RuntimeError("断网")):
            overview = alerts.overview(self.config)
        self.assertFalse(overview["ok"])
        self.assertEqual(overview["announcements"], [])
        self.assertEqual(overview["critical"], [])

    # ------------------------------------------------------------ 还原配置（可逆）
    def test_safe_mode_closes_injections_and_is_undoable(self) -> None:
        self.config.dlss5_injection = True
        self.config.efmi_injection = True
        self.config.secondary_motion_injection = True
        self.config.poser_injection = True
        with mock.patch("endfieldmodcontroller.launcher.ensure_injections", return_value={"ok": True}), \
                mock.patch("endfieldmodcontroller.game_clean.backup_and_clean",
                           return_value={"ok": True, "moved": ["d3d12.dll"], "backup_dir": "x"}):
            result = alerts.safe_mode(self.config)
        self.assertTrue(result["ok"])
        for name in alerts.INJECTION_FIELDS:
            self.assertFalse(getattr(self.config, name), name)
        self.assertTrue(alerts.restore_point_path(self.config).is_file())

        with mock.patch("endfieldmodcontroller.launcher.ensure_injections", return_value={"ok": True}):
            undo = alerts.undo_safe_mode(self.config)
        self.assertTrue(undo["ok"])
        for name in alerts.INJECTION_FIELDS:
            self.assertTrue(getattr(self.config, name), name)

    def test_undo_without_restore_point(self) -> None:
        self.assertFalse(alerts.undo_safe_mode(self.config)["ok"])


if __name__ == "__main__":
    unittest.main()
