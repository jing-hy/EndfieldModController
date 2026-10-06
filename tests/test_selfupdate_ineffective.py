"""「就算是 beta 版也必须能正常更新」的根治测试（2026-10-06）。

**现场**：发布出去的 exe 自称 `-beta`（打包流程问题）⇒ 用户装上后版本号没变 ⇒
更新检测又发现"有同号的正式版" ⇒ **无限循环提示**（「一直让我重启并更新」），
而且**永远修不好**，因为每次装到的还是同一份带 beta 标识的文件。

**根治**：`apply_update()` 记下"这一份装过"（size/mtime/sha256）⇒
`pending_payload()` 遇到"**同一份载荷装过、却仍提示有更新**"就不再提示，并给出 `ineffective`。
判据带 size/mtime ⇒ **发布方一旦重打附件，判据自动失效、恢复提示**。

要看住的两条：
* 装过却没生效 ⇒ 不再重复提示（否则用户点多少次都没用）；
* **重打后的附件仍能被正常更新**（自愈通道不能被这条判据堵死）。
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest

from endfieldmodcontroller import selfupdate
from endfieldmodcontroller.config import AppConfig

BODY = b"payload-body" * 20


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "_update").mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    return AppConfig(), runtime / "_update"


def _make_payload(update_dir, body: bytes = BODY):
    """放一份载荷，并写出**与它一致**的检查缓存（否则会被 sha256 校验拦下）。"""
    payload = update_dir / "EndfieldModController.exe"
    payload.write_bytes(body)
    (update_dir / "last_check.json").write_text(json.dumps({
        "current": "1.0.19-beta", "latest": "9.9.9", "update_available": True,
        "asset": "EndfieldModController.exe",
        "asset_size": len(body),
        "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
        "checked_at": int(time.time()),
    }), encoding="utf-8")
    return payload


def _record_applied(update_dir, payload, tag: str = "1.0.20"):
    stat = payload.stat()
    (update_dir / "applied.json").write_text(json.dumps({
        "tag": tag, "size": stat.st_size, "mtime": int(stat.st_mtime),
        "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(), "at": int(time.time()),
    }), encoding="utf-8")


def test_first_time_still_prompts(env):
    """没装过 ⇒ 照常提示（不能把正常路径也堵掉）。"""
    config, update_dir = env
    _make_payload(update_dir)
    result = selfupdate.pending_payload(config)
    assert result["pending"] is True, result


def test_installed_but_ineffective_stops_prompting(env):
    """★ 同一份载荷装过一次、却仍提示有更新 ⇒ 判为"装了没生效"、不再重复提示。"""
    config, update_dir = env
    payload = _make_payload(update_dir)
    _record_applied(update_dir, payload)

    result = selfupdate.pending_payload(config)

    assert result["pending"] is False, result
    assert result.get("ineffective") is True, result
    assert "beta" in str(result.get("reason") or ""), result


def test_rebuilt_asset_restores_prompting(env):
    """★ 发布方**重打了附件**（文件变了）⇒ 判据失效、恢复提示 —— 自愈通道必须保留。"""
    config, update_dir = env
    payload = _make_payload(update_dir)
    _record_applied(update_dir, payload)

    time.sleep(1.1)                      # 让 mtime 明确变化
    _make_payload(update_dir, BODY + b"rebuilt")   # 重打后的附件：内容/大小都变了

    result = selfupdate.pending_payload(config)

    assert result["pending"] is True, result


def test_apply_records_what_was_installed(env, monkeypatch, tmp_path):
    """`apply_update` 真的启动替换时，要记下"装了哪一份"（判据的数据来源）。"""
    config, update_dir = env
    _make_payload(update_dir)
    target = tmp_path / "EndfieldModController.exe"
    target.write_bytes(b"me")
    monkeypatch.setattr(selfupdate, "is_frozen", lambda: True)
    monkeypatch.setattr(selfupdate, "executable_path", lambda: target)
    monkeypatch.setattr(selfupdate.subprocess, "Popen", lambda *a, **k: None)

    out = selfupdate.apply_update(config, log=None)

    assert out["ok"] is True, out
    applied = json.loads((update_dir / "applied.json").read_text(encoding="utf-8"))
    assert applied["tag"] == "9.9.9"          # = 缓存里的 latest
    assert applied["size"] == (update_dir / "EndfieldModController.exe").stat().st_size
