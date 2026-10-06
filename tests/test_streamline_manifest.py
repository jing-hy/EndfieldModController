"""Streamline/NGX 的 server manifest 损坏：判据 + 自动修复（2026-10-06）。

**现场**（一台 i9-13980HX + Win11 25H2 + RTX 40 系）：游戏启动后 **15 毫秒**连打 10 条

    [Error][streamline][error] ota.cpp:329[parseServerManifest] Unexpected line in manifest file: <乱码>

随后内存从 627 MB 涨到 **1694 MB**、线程掉到 1、进程**自己退出** ——
**没有 WER、面板 addon 也正常 detach**，所以"崩溃取证"一条都抓不到；
而包内 `%LOCALAPPDATA%\\NVIDIA\\NGX\\models\\config\\versions\\2\\files\\nvngx_server_config.txt`
**是 0 字节**（名字与报错的 `parseServerManifest` 直接对应）。

要守住的三条：
* 判据认得出这种日志（否则这类失败永远查不到）；
* 修复**只搬不删**（`.mc-backup-<时间戳>`，驱动下次启动会重建）；
* 日志干净时**一个字都不说**（不许误报）。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import crashwatch
from endfieldmodcontroller.config import AppConfig

LOG_LINE = ("[Error] [12-56-31][streamline][error][tid:34268][0s:015ms:954us]"
            "ota.cpp:329[parseServerManifest] Unexpected line in manifest file: \ufffdt-")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "logs" / "player").mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    return AppConfig(), runtime


def _write_player_log(runtime: pathlib.Path, body: str) -> None:
    (runtime / "logs" / "player" / "Player.log").write_text(body, encoding="utf-8")


def test_broken_manifest_is_detected(env):
    """★ 判据必须认得出这类日志（它就是"启动后很快自己退出、却无 WER"的成因）。"""
    config, runtime = env
    _write_player_log(runtime, "\n".join([LOG_LINE] * 10) + "\n")
    text = crashwatch.streamline_manifest_broken(config)
    assert "server manifest" in text, text
    assert "10 条" in text, text


def test_healthy_log_is_silent(env):
    """日志干净 ⇒ 一个字都不说（不许误报）。"""
    config, runtime = env
    _write_player_log(runtime, "[Info] 正常启动\n[Info] 进入主界面\n")
    assert crashwatch.streamline_manifest_broken(config) == ""


def test_repair_moves_files_and_keeps_them(env, monkeypatch, tmp_path):
    """★ 修复：**只搬不删**（备份留在原地，可还原），并且不动内容正常的表。"""
    config, _runtime = env
    fake_home = tmp_path / "home"
    ngx_file = (fake_home / "NVIDIA" / "NGX" / "models" / "config" / "versions" / "2"
                / "files" / "nvngx_server_config.txt")
    ngx_file.parent.mkdir(parents=True)
    ngx_file.write_bytes(b"")                      # 就是那个 0 字节的坏文件
    keep = ngx_file.with_name("nvngx_config.txt")
    keep.write_text("[dlss]\napp_X = 1.0.0\n", encoding="utf-8")
    stream = fake_home / "NVIDIA" / "Streamline" / "cache" / "ota-manifest.bin"
    stream.parent.mkdir(parents=True)
    stream.write_bytes(b"garbage")
    monkeypatch.setenv("LOCALAPPDATA", str(fake_home))

    moved = crashwatch.repair_streamline_manifest(config, log=None)

    assert "nvngx_server_config.txt" in moved, moved
    assert "ota-manifest.bin" in moved, moved
    assert not ngx_file.exists(), "坏文件应已移走"
    assert list(ngx_file.parent.glob("nvngx_server_config.txt.mc-backup-*")), "只搬不删：必须留备份"
    assert keep.is_file(), "内容正常的表不能动"
    assert not list((fake_home / "NVIDIA").rglob("nvngx_config.txt.mc-backup-*"))


def test_repair_is_noop_when_nothing_found(env, monkeypatch, tmp_path):
    """找不到任何目标 ⇒ 不动手、返回空列表。"""
    config, _runtime = env
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty-home"))
    assert crashwatch.repair_streamline_manifest(config, log=None) == []
