# SPDX-License-Identifier: GPL-3.0-or-later
"""本机无障碍 / 自动化通道（2026-11-17 用户要求）。

用户原话：「我还想加个功能，需要一个无障碍功能，能有个 api 或者命令行，允许 ai 操作 ui，
比如切换页面，点击开关，滑动这种」。

本文件钉住的判据：
* 只绑 127.0.0.1；`/state` 与 `/act` **必须带 token**（`/health` 只探活）；
* 命令是「后端排队 → 前端取走执行 → 回传结果」，**前端不响应就如实报超时**，不假装成功；
* 端口与 token 落在 `runtime/_state/ui_api.json`（CLI 靠它），`stop()` 时删掉；
* 前端脚本那一半存在且挂上了 `window.__mcUi`（纯文本断言，防止被误删）。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from endfieldmodcontroller import ui_automation as U
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def channel(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    cfg = AppConfig()
    info = U.start(cfg, port=0)
    assert info["ok"] is True, info
    yield cfg, info, runtime
    U.stop()


def _get(url: str, token: str = "", timeout: float = 5.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=({"X-MC-Token": token} if token else {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post(url: str, token: str, body: dict, timeout: float = 12.0) -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"X-MC-Token": token,
                                          "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _serve_one(responder, deadline: float = 5.0) -> threading.Thread:
    """假装自己是前端：抢到一条命令、调用 responder、把结果回传。"""

    def worker() -> None:
        end = time.time() + deadline
        while time.time() < end:
            polled = U.poll()
            for command in polled["commands"]:
                U.submit_result(command["id"], json.dumps(responder(command), ensure_ascii=False))
                return
            time.sleep(0.01)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def test_start_writes_state_file(channel):
    _cfg, info, runtime = channel
    path = runtime / "_state" / "ui_api.json"
    assert path.is_file(), "端口/token 要落盘给 CLI 读"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["port"] == info["port"] > 0
    assert payload["token"] == info["token"]
    assert payload["url"] == f"http://127.0.0.1:{info['port']}"
    assert U.endpoint_info()["running"] is True


def test_health_needs_no_token(channel):
    _cfg, info, _runtime = channel
    status, body = _get(f"http://127.0.0.1:{info['port']}/health")
    assert status == 200 and body["ok"] is True


def test_state_requires_token(channel):
    _cfg, info, _runtime = channel
    status, body = _get(f"http://127.0.0.1:{info['port']}/state")
    assert status == 401 and body["ok"] is False
    assert "token" in body["message"]


def test_state_roundtrip_through_frontend(channel):
    _cfg, info, _runtime = channel
    seen: list[str] = []

    def responder(command: dict) -> dict:
        seen.append(command["kind"])
        return {"ok": True, "tab": "library", "elements": [{"id": '[data-mc-id="tab:settings"]'}]}

    _serve_one(responder)
    status, body = _get(f"http://127.0.0.1:{info['port']}/state", token=info["token"])
    assert status == 200
    assert seen == ["snapshot"]
    assert body["tab"] == "library" and body["elements"][0]["id"]


def test_act_roundtrip(channel):
    _cfg, info, _runtime = channel
    got: list[dict] = []

    def responder(command: dict) -> dict:
        got.append(command["payload"])
        return {"ok": True, "action": "click"}

    _serve_one(responder)
    status, body = _post(f"http://127.0.0.1:{info['port']}/act", info["token"],
                         {"id": '[data-mc-id="tab:settings"]', "action": "click"})
    assert status == 200 and body["ok"] is True
    assert got and got[0]["id"] == '[data-mc-id="tab:settings"]'
    assert got[0]["action"] == "click"


def test_act_requires_id(channel):
    _cfg, info, _runtime = channel
    status, body = _post(f"http://127.0.0.1:{info['port']}/act", info["token"], {"action": "click"})
    assert status == 400 and "id" in body["message"]


def test_act_rejects_bad_json(channel):
    _cfg, info, _runtime = channel
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/act", data=b"not json",
                                 method="POST",
                                 headers={"X-MC-Token": info["token"],
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            status = resp.status
    except urllib.error.HTTPError as exc:
        status, body = exc.code, json.loads(exc.read().decode("utf-8"))
    assert status == 400 and body["ok"] is False


def test_missing_frontend_reports_timeout_not_success():
    """前端没响应时**必须**如实报超时（不许假装成功）。"""
    result = U.snapshot(timeout=0.15)
    assert result["ok"] is False
    assert "没有响应" in result["message"]


def test_poll_hands_out_pending_command():
    holder: dict = {}

    def caller() -> None:
        holder["result"] = U.snapshot(timeout=3.0)

    thread = threading.Thread(target=caller, daemon=True)
    thread.start()
    deadline = time.time() + 3
    command = None
    while time.time() < deadline and command is None:
        polled = U.poll()
        command = (polled["commands"] or [None])[0]
        if command is None:
            time.sleep(0.01)
    assert command is not None and command["kind"] == "snapshot"
    U.submit_result(command["id"], '{"ok": true, "tab": "launch"}')
    thread.join(timeout=3)
    assert holder["result"]["tab"] == "launch"


def test_submit_result_for_unknown_command_is_rejected():
    assert U.submit_result("nope", "{}")["ok"] is False


def test_stop_removes_state_file(channel):
    _cfg, info, runtime = channel
    path = runtime / "_state" / "ui_api.json"
    assert path.is_file()
    U.stop()
    assert not path.exists(), "退出后不该留一个指向死端口的文件"
    assert U.endpoint_info()["running"] is False


def test_start_is_idempotent(channel):
    cfg, info, _runtime = channel
    again = U.start(cfg, port=0)
    assert again["ok"] is True and again["already"] is True
    assert again["port"] == info["port"]


def test_frontend_half_is_wired():
    """前端那一半必须真的存在并挂上 window.__mcUi（防止被误删）。"""
    root = Path(__file__).resolve().parent.parent / "frontend" / "src"
    module = (root / "lib" / "uiAutomation.js").read_text(encoding="utf-8")
    assert "startUiAutomation" in module
    assert "window.__mcUi" in module
    assert "ui_automation_poll" in module
    assert "ui_automation_result" in module
    main = (root / "main.js").read_text(encoding="utf-8")
    assert "startUiAutomation()" in main
    app = (root / "App.vue").read_text(encoding="utf-8")
    assert "data-mc-current-tab" in app
    assert "tab:" in app
