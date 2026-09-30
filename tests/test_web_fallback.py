"""「API 不通 / 额度用尽 → 自动走网页路线」的回归测试（2026-09-30）。

背景：用户指出「**github额度不影响，会自动路由**」—— 本程序查组件 release 早就
"网页优先 + 镜像回退"（`github.releases_latest` → `_release_via_web`），但有**三处漏了**：
① 公告/预警 `alerts.fetch_document`、② 自更新检查 `selfupdate.check_update`、
③ `github.releases_list`（Endfield Poser 只能靠它拿预发布版）。
这里逐条钉住"API 挂了也要能拿到"。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import alerts, github, selfupdate
from endfieldmodcontroller.config import AppConfig

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><link href="https://github.com/o/r/releases/tag/v0.4.92"/></entry>
</feed>
"""
ASSETS = ('<a href="/o/r/releases/download/v0.4.92/Endfield-Poser-v0.4.92-win64.zip">x</a>')


class WebFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-fallback-")
        self.root = Path(self.tmp.name)
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.root / "runtime"),
            builtin_runtime_dir=str(self.root / "runtime" / "builtin"),
        )
        self.config._config_path = str(self.root / "config.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ---------------------------------------------------------------- ① 公告/预警
    def test_alerts_falls_back_to_raw_web(self) -> None:
        document = {"schema": 1, "alerts": [{"id": "from-web", "level": "critical"}]}

        def fake_fetch(url, headers=None, timeout=None):
            self.assertIn("/raw/main/alerts.json", url)
            return url, json.dumps(document).encode("utf-8")

        with mock.patch("endfieldmodcontroller.github.api_get",
                        side_effect=RuntimeError("API 额度用尽")), \
                mock.patch("endfieldmodcontroller.fastnet.fetch", side_effect=fake_fetch):
            got = alerts.fetch_document()
        self.assertEqual([a["id"] for a in alerts.normalize(got)], ["from-web"])

    def test_alerts_reports_both_routes_when_both_fail(self) -> None:
        with mock.patch("endfieldmodcontroller.github.api_get",
                        side_effect=RuntimeError("API 额度用尽")), \
                mock.patch("endfieldmodcontroller.fastnet.fetch",
                           side_effect=RuntimeError("网页也不通")):
            with self.assertRaises(RuntimeError) as ctx:
                alerts.fetch_document()
        message = str(ctx.exception)
        self.assertIn("API 路线", message)
        self.assertIn("网页路线", message)

    # ---------------------------------------------------------------- ② releases_list
    def test_releases_list_falls_back_to_atom(self) -> None:
        def fake_fetch(url, headers=None, timeout=None):
            if url.endswith("releases.atom"):
                return url, ATOM.encode("utf-8")
            return url, ASSETS.encode("utf-8")

        with mock.patch.object(github, "api_get", side_effect=RuntimeError("API 额度用尽")), \
                mock.patch("endfieldmodcontroller.fastnet.fetch", side_effect=fake_fetch):
            release = github.releases_list("o/r", include_prerelease=True)
        self.assertEqual(release["tag_name"], "v0.4.92")
        self.assertEqual([a["name"] for a in release["assets"]],
                         ["Endfield-Poser-v0.4.92-win64.zip"])
        self.assertEqual(release["assets"][0]["browser_download_url"],
                         "https://github.com/o/r/releases/download/v0.4.92/"
                         "Endfield-Poser-v0.4.92-win64.zip")

    def test_releases_list_raises_when_web_has_nothing(self) -> None:
        with mock.patch.object(github, "api_get", side_effect=RuntimeError("API 额度用尽")), \
                mock.patch("endfieldmodcontroller.fastnet.fetch",
                           side_effect=RuntimeError("网页也不通")):
            with self.assertRaises(RuntimeError):
                github.releases_list("o/r")

    # ---------------------------------------------------------------- ③ 自更新检查
    def test_selfupdate_check_uses_web_release(self) -> None:
        web_release = {
            "tag_name": "v9.9.9", "name": "v9.9.9", "source": "web",
            "assets": [{
                "name": "EndfieldModController.exe", "size": 0, "digest": "",
                "browser_download_url": "https://github.com/o/r/releases/download/v9.9.9/EndfieldModController.exe",
            }],
        }
        with mock.patch("endfieldmodcontroller.github.releases_latest", return_value=web_release), \
                mock.patch.object(selfupdate, "_fetch_json",
                                  side_effect=RuntimeError("API 额度用尽")):
            result = selfupdate.check_update(self.config, use_cache=False)
        self.assertEqual(result["latest"], "9.9.9")
        self.assertTrue(result["update_available"])          # 本机版本必然低于 9.9.9
        self.assertTrue(result["download_url"].endswith("EndfieldModController.exe"))
        self.assertFalse(result.get("error"))

    def test_selfupdate_reports_error_when_both_fail(self) -> None:
        with mock.patch("endfieldmodcontroller.github.releases_latest",
                        side_effect=RuntimeError("网页不通")), \
                mock.patch.object(selfupdate, "_fetch_json",
                                  side_effect=RuntimeError("API 额度用尽")):
            result = selfupdate.check_update(self.config, use_cache=False)
        self.assertIn("error", result)
        self.assertFalse(result["update_available"])


if __name__ == "__main__":
    unittest.main()
