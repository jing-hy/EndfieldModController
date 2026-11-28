# SPDX-License-Identifier: AGPL-3.0-only
"""设置里新增的 MaaEnd 类设置：Web 服务开关（默认关）、日志自动清理、背景图、调试信息。

2026-11-28 用户要求：「maaend 里那些设置都加一下，想背景图片啊，自动清理运行日志啊，
web 服务啊，调试这些，那个 api 接口要留个开关，默认关闭，还有加一个关于」。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest import mock

import pytest

from endfieldmodcontroller import diagnostics, edition, ui_automation
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


def _make_api(tmp_path: Path) -> EndfieldModControllerApi:
    config_path = tmp_path / "config.json"
    config = AppConfig(
        library_dir=str(tmp_path / "library"),
        runtime_dir=str(tmp_path / "runtime"),
        staging_mods_dir=str(tmp_path / "runtime" / "EFMI" / "Mods"),
    )
    config.save(config_path)
    return EndfieldModControllerApi(config_path)


def test_ui_api_is_disabled_by_default() -> None:
    """用户明确：那个 API 接口要留个开关，**默认关闭**。"""
    config = AppConfig()
    assert config.ui_api_enabled is False
    assert config.ui_api_port == 0


def test_enabling_ui_api_starts_and_disabling_stops_it(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    started: list[int] = []
    stopped: list[int] = []

    def fake_start(_config, log=None, port=0):
        started.append(int(port))
        return {"ok": True, "port": 1234}

    with mock.patch.object(ui_automation, "start", side_effect=fake_start), \
            mock.patch.object(ui_automation, "stop", side_effect=lambda: stopped.append(1)):
        result = api.save_config({"ui_api_enabled": True, "ui_api_port": 0})
        assert result.get("ok") is True
        assert started == [0], "开启时必须真的调用 ui_automation.start"
        assert result.get("ui_api", {}).get("ok") is True

        api.save_config({"ui_api_enabled": False})
        assert stopped, "关闭时必须 stop 掉端口（不能只是改配置）"


def test_changing_port_restarts_the_service(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    started: list[int] = []

    def fake_start(_config, log=None, port=0):
        started.append(int(port))
        return {"ok": True, "port": int(port) or 5678}

    with mock.patch.object(ui_automation, "start", side_effect=fake_start), \
            mock.patch.object(ui_automation, "stop", side_effect=lambda: None):
        api.save_config({"ui_api_enabled": True})
        api.save_config({"ui_api_port": 5678})
        assert started == [0, 5678]


def test_ui_api_status_reports_switch_and_endpoint(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    info = api.ui_api_status()
    assert info["enabled"] is False
    assert info["configured_port"] == 0
    assert "running" in info


def _touch(path: Path, age_days: float, now: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("log line", encoding="utf-8")
    stamp = now - age_days * 86400
    os.utime(path, (stamp, stamp))


def test_auto_clear_logs_removes_only_old_files(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    now = time.time()
    logs = api.config.runtime_path / "logs"
    _touch(logs / "old-a.log", 30, now)
    _touch(logs / "old-b.log", 20, now)
    _touch(logs / "fresh.log", 1, now)
    _touch(logs / "sub" / "deep-old.log", 40, now)

    result = diagnostics.auto_clear_logs(api.config, now=now)

    assert result["ok"] is True
    assert set(result["removed"]) == {"old-a.log", "old-b.log", "sub/deep-old.log"}
    assert (logs / "fresh.log").is_file(), "最近日志必须保留"
    assert (logs / "sub").is_dir(), "只删文件，目录结构保留"


def test_auto_clear_logs_respects_switch_and_force(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    now = time.time()
    logs = api.config.runtime_path / "logs"
    _touch(logs / "old.log", 30, now)

    api.config.auto_clear_logs = False
    assert diagnostics.auto_clear_logs(api.config, now=now).get("skipped") == "switch_off"
    assert (logs / "old.log").is_file()

    forced = diagnostics.auto_clear_logs(api.config, force=True, now=now)
    assert forced["removed"] == ["old.log"], "「立即清理」按钮忽略开关，照常按天数清理"


def test_auto_clear_logs_zero_days_keeps_everything(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    now = time.time()
    logs = api.config.runtime_path / "logs"
    _touch(logs / "old.log", 365, now)

    api.config.log_retention_days = 0
    result = diagnostics.auto_clear_logs(api.config, now=now)

    assert result.get("skipped") == "no_limit"
    assert (logs / "old.log").is_file(), "0 = 不按时间清理，一天都不删"


def test_choose_and_clear_background_image(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    image = tmp_path / "bg.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    with mock.patch.object(api, "choose_path", return_value={"ok": True, "path": str(image)}):
        result = api.choose_background_image()

    assert result.get("ok") is True
    assert api.config.ui_background_image, "选完图必须写进配置"
    assert Path(api.config.resolve_path(api.config.ui_background_image)).is_file()

    cleared = api.clear_background_image()
    assert cleared.get("ok") is True
    assert api.config.ui_background_image == ""


def test_choose_background_rejects_non_image(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    bogus = tmp_path / "not-image.txt"
    bogus.write_text("x", encoding="utf-8")

    with mock.patch.object(api, "choose_path", return_value={"ok": True, "path": str(bogus)}):
        result = api.choose_background_image()

    assert result.get("ok") is False
    assert "图片格式" in str(result.get("message") or "")


def test_mod_store_nsfw_is_remembered_and_validated(tmp_path: Path) -> None:
    """商城 R18 三档要记忆（2026-11-28 用户要求）；非法值按默认模糊处理。"""
    import json

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"mod_store_nsfw": "show"}, ensure_ascii=False),
                           encoding="utf-8")
    assert AppConfig.load(config_path).mod_store_nsfw == "show"

    config_path.write_text(json.dumps({"mod_store_nsfw": "nonsense"}, ensure_ascii=False),
                           encoding="utf-8")
    assert AppConfig.load(config_path).mod_store_nsfw == "blur"


def test_language_defaults_to_chinese_and_is_validated(tmp_path: Path) -> None:
    """界面语言：默认中文，只认 zh / en（2026-11-28 用户要求英文版）。"""
    import json

    config_path = tmp_path / "config.json"
    assert AppConfig().language == "zh"

    config_path.write_text(json.dumps({"language": "en"}, ensure_ascii=False), encoding="utf-8")
    assert AppConfig.load(config_path).language == "en"

    config_path.write_text(json.dumps({"language": "fr"}, ensure_ascii=False), encoding="utf-8")
    assert AppConfig.load(config_path).language == "zh"


def test_debug_info_has_environment_fields(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    info = api.debug_info()

    for key in ("version", "edition", "edition_label", "os", "arch", "python",
                "data_root", "logs", "ui_api"):
        assert key in info, f"debug_info 缺字段 {key}"
    assert info["edition"] in ("full", "lite")
    assert str(info["logs"]).endswith("logs")
