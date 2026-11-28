# SPDX-License-Identifier: AGPL-3.0-only
"""本机 UI 无障碍 / 自动化通道（2026-11-17 用户要求）。

用户原话：「我还想加个功能，需要一个无障碍功能，能有个 api 或者命令行，允许 ai 操作 ui，
比如切换页面，点击开关，滑动这种」。

设计（为什么是"排队 + 前端轮询"而不是后端直接 evaluate_js）：

* pywebview 的 `window.evaluate_js()` 在 EdgeChromium 后端要落到 **UI/STA 线程**执行，
  从 HTTP 工作线程直接调用是不保险的（可能抛错或干脆挂住，把整个界面一起卡死）。
* 前端**本来就在**有 js_api 桥（`window.pywebview.api`），所以让「前端每 300ms 问一次
  有没有活要干」最稳：命令入队 → 前端取走 → 在页面里真实地点/填/滚 → 把结果回传。
  它走的全是**真实的 DOM 交互**（`el.click()`、原生 value setter + input 事件），
  不是"直接改后端配置"那种表面功夫 —— 界面上的反应与用户手点完全一致。

对外暴露的入口（只绑 127.0.0.1，带 token）：

    GET  /health          进程与端口探活（不需要 token）
    GET  /state           当前页面 + 可交互元素快照（AI 用来找元素）
    POST /act             执行动作 {"id": ..., "action": ..., "value": ...}

token 与端口写在 `<数据根>/runtime/_state/ui_api.json`（`scripts/ui_ctl.py` 读它，
命令行用户可以完全不关心 token）。
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# 前端轮询间隔（毫秒）。前端也用同一数值 —— 别在这里单独调，容易两边漂。
POLL_INTERVAL_MS = 300
# 单条命令等前端回传的最长时间（秒）。窗口没开 / 界面卡住时靠它给出可读错误。
COMMAND_TIMEOUT = 8.0

_STATE_LOCK = threading.RLock()
_SEQ = count(1)
# {command_id: {"action": {...}, "event": Event, "result": dict}}
_PENDING: dict[str, dict[str, Any]] = {}
_SERVER: ThreadingHTTPServer | None = None
_TOKEN = ""
_STATE_PATH: Path | None = None
_LOG = None


def _note(message: str) -> None:
    """写进 launch.log（可选）；失败一律吞掉 —— 无障碍通道不能影响主流程。"""
    callback = _LOG
    if callback is None:
        return
    try:
        callback(message)
    except Exception:  # noqa: BLE001
        pass


def state_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "_state" / "ui_api.json"


def _enqueue(kind: str, payload: dict, timeout: float = COMMAND_TIMEOUT) -> dict[str, Any]:
    """把一条动作交给前端执行并等结果。前端没响应就返回"没响应"，绝不假装成功。"""
    command_id = f"c{next(_SEQ)}"
    entry: dict[str, Any] = {"kind": kind, "payload": payload,
                             "event": threading.Event(), "result": None}
    with _STATE_LOCK:
        _PENDING[command_id] = entry
    try:
        if not entry["event"].wait(timeout):
            return {"ok": False,
                    "message": (f"界面在 {timeout:.0f} 秒内没有响应这条指令"
                                "（窗口还没创建好、或者界面正忙）")}
        result = entry["result"]
        return result if isinstance(result, dict) else {"ok": False, "message": "界面返回了空结果"}
    finally:
        with _STATE_LOCK:
            _PENDING.pop(command_id, None)


def poll() -> dict[str, Any]:
    """前端每 `POLL_INTERVAL_MS` 调一次：取走待执行的动作（没有就回空表）。"""
    with _STATE_LOCK:
        commands = [{"id": cid, "kind": item["kind"], "payload": item["payload"]}
                    for cid, item in _PENDING.items() if not item["event"].is_set()]
    return {"ok": True, "poll_ms": POLL_INTERVAL_MS, "commands": commands}


def submit_result(command_id: str, payload: str) -> dict[str, Any]:
    """前端执行完把结果回传（payload 是 JSON 字符串）。"""
    with _STATE_LOCK:
        entry = _PENDING.get(str(command_id))
        if entry is None:
            return {"ok": False, "message": "这条指令已经超时或不存在"}
        if entry["event"].is_set():
            return {"ok": True, "ignored": True}
        try:
            parsed = json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            parsed = {"ok": False, "message": "前端回传的不是合法 JSON"}
        entry["result"] = parsed if isinstance(parsed, dict) else {"ok": True, "value": parsed}
        entry["event"].set()
    return {"ok": True}


def snapshot(timeout: float = COMMAND_TIMEOUT) -> dict[str, Any]:
    """当前界面快照：所在页面 + 可交互元素（AI 靠它找"点哪个"）。"""
    return _enqueue("snapshot", {}, timeout)


def act(element_id: str, action: str, value: Any = None,
        timeout: float = COMMAND_TIMEOUT) -> dict[str, Any]:
    """在界面上执行一个真实动作（click / set / type / scroll / focus）。"""
    return _enqueue("act", {"id": str(element_id), "action": str(action), "value": value}, timeout)


class _Handler(BaseHTTPRequestHandler):
    server_version = "EndfieldModControllerUI/1"

    # 默认实现往 stderr 打日志 —— 打包版没有控制台，而且这里本来就该安静。
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    # ---- 工具 ----
    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        token = self.headers.get("X-MC-Token") or (query.get("token") or [""])[0]
        return bool(_TOKEN) and token == _TOKEN

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的固定命名
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in ("/health", "/ping"):
            self._send(200, {"ok": True, "app": "EndfieldModController",
                             "pid": os.getpid(), "poll_ms": POLL_INTERVAL_MS})
            return
        if parsed.path in ("/state", "/snapshot"):
            if not self._authorized(query):
                self._send(401, {"ok": False, "message": "缺少或错误的 token（看 runtime/_state/ui_api.json）"})
                return
            self._send(200, snapshot())
            return
        self._send(200, {
            "ok": True,
            "usage": {
                "GET /health": "探活（无需 token）",
                "GET /state": "界面快照：当前页面 + 可交互元素",
                "POST /act": "执行动作：{id, action, value}",
                "actions": ["click", "set", "type", "scroll", "focus"],
            },
        })

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path != "/act":
            self._send(404, {"ok": False, "message": "只有 POST /act"})
            return
        if not self._authorized(query):
            self._send(401, {"ok": False, "message": "缺少或错误的 token（看 runtime/_state/ui_api.json）"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(400, {"ok": False, "message": f"请求体不是合法 JSON: {exc}"})
            return
        if not isinstance(body, dict):
            self._send(400, {"ok": False, "message": "请求体必须是 JSON 对象"})
            return
        element_id = str(body.get("id") or "").strip()
        action = str(body.get("action") or "click").strip().lower()
        if not element_id and action != "scroll-by":
            self._send(400, {"ok": False, "message": "缺少 id（先用 GET /state 找元素）"})
            return
        result = act(element_id, action, body.get("value"))
        self._send(200 if result.get("ok") else 422, result)


def _stop_locked() -> None:
    global _SERVER, _TOKEN, _STATE_PATH
    server = _SERVER
    _SERVER = None
    path = _STATE_PATH
    _STATE_PATH = None
    if server is not None:
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            server.server_close()
        except Exception:  # noqa: BLE001
            pass
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def start(config: Any, log: Any = None, port: int = 0) -> dict[str, Any]:
    """起本机无障碍通道（幂等）：已有就复用，不再起第二个。

    只绑 127.0.0.1；端口默认随机（写进 `runtime/_state/ui_api.json`）。any 失败都**不抛**：
    无障碍通道起不来不该挡住用户开程序，只写一条日志。
    """
    global _SERVER, _TOKEN, _STATE_PATH, _LOG
    _LOG = log
    with _STATE_LOCK:
        if _SERVER is not None:
            return {"ok": True, "already": True, "port": _SERVER.server_address[1],
                    "token": _TOKEN}
        try:
            server = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
        except OSError as exc:
            _note(f"WARN 无障碍通道没能启动（端口绑定失败，忽略）: {exc}")
            return {"ok": False, "message": str(exc)}
        server.daemon_threads = True
        _SERVER = server
        _TOKEN = secrets.token_urlsafe(24)
        bound = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, name="mc-ui-api", daemon=True)
        thread.start()
        runtime_dir = getattr(config, "runtime_path", None)
        if runtime_dir is not None:
            path = state_path(Path(runtime_dir))
            payload = {
                "url": f"http://127.0.0.1:{bound}",
                "port": bound,
                "token": _TOKEN,
                "pid": os.getpid(),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8", newline="\n")
                _STATE_PATH = path
            except OSError as exc:
                _note(f"WARN 无障碍通道状态文件没写成（不影响服务）: {exc}")
        _note(f"无障碍通道已开启：http://127.0.0.1:{bound}（token 见 runtime/_state/ui_api.json）")
        return {"ok": True, "already": False, "port": bound, "token": _TOKEN}


def stop() -> None:
    with _STATE_LOCK:
        _stop_locked()


def is_running() -> bool:
    return _SERVER is not None


def endpoint_info(config: Any = None) -> dict[str, Any]:
    """给设置页/诊断用的只读信息（不含 token）。

    `token_file` 是 `runtime/_state/ui_api.json`（里面才有 token）—— 设置页直接把它
    显示出来，用户/脚本不用猜路径。2026-11-28 起服务默认关闭，前端按 running 显示状态。
    """
    server = _SERVER
    token_file = str(_STATE_PATH) if _STATE_PATH else ""
    if server is None:
        return {"ok": True, "running": False, "token_file": token_file,
                "poll_ms": POLL_INTERVAL_MS}
    return {"ok": True, "running": True,
            "url": f"http://127.0.0.1:{server.server_address[1]}",
            "port": int(server.server_address[1]),
            "token_file": token_file,
            "poll_ms": POLL_INTERVAL_MS}
