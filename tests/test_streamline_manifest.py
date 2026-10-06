"""Streamline/NGX 的 server manifest 损坏：判据 + 自动修复（2026-10-06）。

**现场**（两位反馈者，形态完全相同）：游戏启动后 **13~15 毫秒**连打 10 条

    [Error][streamline][error] ota.cpp:329[parseServerManifest] Unexpected line in manifest file: <乱码>

随后内存一路涨（35.7 MB → 1159.6 MB / 627 MB → 1694 MB）、线程掉到 1、进程**自己退出**（退出码
`0xC0000135`）—— **没有 WER、面板 add-on 也正常 detach**，所以"崩溃取证"一条都抓不到。

⚠️ **两个必须钉住的坑**（都是 2026-10-06 实际踩到的）：
① **判据必须读"游戏真正写日志的地方"**（`_endfield_local_low()/Player.log`）。我第一版只拼了
   `runtime\\logs\\player\\Player.log` —— **该路径根本不存在** ⇒ 判据一次没命中 ⇒ 自动修复从未执行
   （反馈者升级到含该修复的版本后，包里仍带同样的报错，而"Streamline："那行压根没出现）。
② **清理目标要按内容判**：一位坏的 `nvngx_server_config.txt`（0 字节）、另一位坏的
   `nvngx_mapping.json`（0 字节），报的却是同一条错 ⇒ 只按文件名挑会漏掉一半。

要守住的三条：判据认得出、修复**只搬不删**、日志干净时**一个字都不说**（不许误报，
也不许去读测试机/开发机真实的 Player.log）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from endfieldmodcontroller import crashwatch
from endfieldmodcontroller.config import AppConfig

LOG_LINE = ("[Error] [14-43-40][streamline][error][tid:26744][0s:013ms:840us]"
            "ota.cpp:329[parseServerManifest] Unexpected line in manifest file: \ufffdt-")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    low = tmp_path / "localLow"                  # 游戏真正写日志的地方（本测试里为空）
    low.mkdir(parents=True)
    monkeypatch.setattr(crashwatch, "_endfield_local_low", lambda: low)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    # ⚠️ **必须把两处环境变量也打桩**（2026-10-06 实测教训）：`nvidia_config_roots()` 读的是
    #    `USERPROFILE` 与 `PROGRAMDATA` ⇒ 不打桩时测试会去动**开发机真实的 NVIDIA 配置**
    #    （实测把 `<ProgramData>\NVIDIA\NGX\models\config\versions\2\files\nvngx_server_config.txt`
    #    搬成了 `.mc-backup-<时间戳>`）。**测试永远不许碰真实环境。**
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "nohome"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "noprogramdata"))
    return AppConfig(), runtime, low


def test_broken_manifest_is_detected_from_the_real_game_log(env):
    """★ 判据必须从**游戏真正写日志的地方**读得到（v1.0.22 就是这里写错了路径）。"""
    config, _runtime, low = env
    (low / "Player.log").write_text("\n".join([LOG_LINE] * 10) + "\n", encoding="utf-8")
    text = crashwatch.streamline_manifest_broken(config)
    assert "server manifest" in text, text
    assert "10 条" in text, text


def test_broken_manifest_is_detected_from_our_archived_copy(env):
    """兜底：我们自己归档的 `runtime\\player\\Endfield-Player.log` 也要能命中。"""
    config, runtime, _low = env
    (runtime / "player").mkdir(parents=True)
    (runtime / "player" / "Endfield-Player.log").write_text(LOG_LINE + "\n", encoding="utf-8")
    assert "server manifest" in crashwatch.streamline_manifest_broken(config)


def test_healthy_log_is_silent(env):
    """日志干净 ⇒ 一个字都不说（不许误报）。"""
    config, _runtime, low = env
    (low / "Player.log").write_text("[Info] 正常启动\n[Info] 进入主界面\n", encoding="utf-8")
    assert crashwatch.streamline_manifest_broken(config) == ""


def test_nothing_anywhere_is_silent(env):
    """两个位置都没有日志 ⇒ 静默（不许去读真实机器的日志）。"""
    config, _runtime, _low = env
    assert crashwatch.streamline_manifest_broken(config) == ""


def test_repair_moves_files_and_keeps_them(env, monkeypatch, tmp_path):
    """★ 修复：**只搬不删**（备份留在原地、可还原），并且不动内容正常的表。"""
    config, _runtime, _low = env
    fake_home = tmp_path / "home"
    local = fake_home / "AppData" / "Local"
    ngx_dir = local / "NVIDIA" / "NGX" / "models" / "config" / "versions" / "2" / "files"
    ngx_dir.mkdir(parents=True)
    ngx_file = ngx_dir / "nvngx_server_config.txt"
    ngx_file.write_bytes(b"")                       # 就是那个 0 字节的坏文件
    keep = ngx_dir / "nvngx_config.txt"
    keep.write_text("[dlss]\napp_X = 1.0.0\n", encoding="utf-8")
    stream = local / "NVIDIA" / "Streamline" / "cache" / "ota-manifest.bin"
    stream.parent.mkdir(parents=True)
    stream.write_bytes(b"garbage")
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))

    moved = crashwatch.repair_streamline_manifest(config, log=None)

    assert "nvngx_server_config.txt" in moved, moved
    assert "ota-manifest.bin" in moved, moved
    assert not ngx_file.exists(), "坏文件应已移走"
    assert list(ngx_dir.glob("nvngx_server_config.txt.mc-backup-*")), "只搬不删：必须留备份"
    assert keep.is_file(), "内容正常的表不能动"
    assert not list(ngx_dir.glob("nvngx_config.txt.mc-backup-*"))


def test_repair_also_catches_broken_json_by_content(env, monkeypatch, tmp_path):
    """★ 按**内容**判：坏掉的是 `nvngx_mapping.json`（0 字节）时也要能挑中。

    另一位反馈者的 `nvngx_server_config.txt` 有 5,296 B（正常），空的是 mapping.json ——
    两人报的是同一条 `parseServerManifest` 错，所以只按文件名挑会漏。
    """
    config, _runtime, _low = env
    fake_home = tmp_path / "home"
    local = fake_home / "AppData" / "Local"
    files = local / "NVIDIA" / "NGX" / "models" / "config" / "versions" / "1" / "files"
    files.mkdir(parents=True)
    (files / "nvngx_mapping.json").write_bytes(b"")                  # 0 字节
    (files / "nvngx_deny_list.txt").write_text("[streamline-ota]\napp_X = 1\n", encoding="utf-8")
    good = files / "nvngx_other.json"
    good.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))

    moved = crashwatch.repair_streamline_manifest(config, log=None)

    assert "nvngx_mapping.json" in moved, moved
    assert good.is_file(), "能正常解析的 JSON 不能动"
    assert not list(files.glob("nvngx_other.json.mc-backup-*"))


def test_repair_searches_every_known_root(env, monkeypatch, tmp_path):
    """★ **必须遍历全部已知根**（2026-10-06 第二次踩坑）。

    现场：诊断采集列出了 6 个候选根，而清理一度只查 `%LOCALAPPDATA%\\NVIDIA\\NGX` 一个 ⇒
    反馈者那台的坏配置在 `%PROGRAMDATA%` 那个根里 ⇒ 日志写着"判据命中、但没找到可清理的
    缓存文件"，修复实际没做。这一条钉住"跨根也要找得到"。
    """
    config, _runtime, _low = env
    fake_home = tmp_path / "home"
    (fake_home / "AppData" / "Local").mkdir(parents=True)
    programdata = tmp_path / "ProgramData"
    files = programdata / "NVIDIA" / "NGX" / "models" / "config" / "versions" / "2" / "files"
    files.mkdir(parents=True)
    (files / "nvngx_server_config.txt").write_bytes(b"")            # 空文件，且在 PROGRAMDATA 根
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PROGRAMDATA", str(programdata))

    moved = crashwatch.repair_streamline_manifest(config, log=None)

    assert "nvngx_server_config.txt" in moved, f"跨根没找到 ⇒ 修复又会空手而归：{moved}"


def test_repair_clears_the_whole_ota_group(env, monkeypatch, tmp_path):
    """★ `nvngx_deny_list.txt` 必须与 `nvngx_server_config.txt` **成组**被清掉。

    2026-10-06 定案：`ota.cpp` 的 **OTA** 指 `[streamline-ota]` 段，**它就在
    `nvngx_deny_list.txt` 里**（正常机器 33 B）。反馈者那台该文件 **0 字节** ⇒
    `parseServerManifest Unexpected line in manifest file` ⇒ 内存暴涨后进程自己退出。
    v1.0.24 只清了 `server_config` ⇒ 驱动重建 OTA 时又把 `deny_list` 写坏 ⇒ 症状照旧。
    这一条钉住"成组清"（另有一条钉住"内容正常的表不许动"）。
    """
    config, _runtime, _low = env
    fake_home = tmp_path / "home"
    local = fake_home / "AppData" / "Local"
    files = local / "NVIDIA" / "NGX" / "models" / "config" / "versions" / "1" / "files"
    files.mkdir(parents=True)
    (files / "nvngx_deny_list.txt").write_bytes(b"")                 # ★ 真凶：0 字节
    (files / "nvngx_mapping.json").write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))

    moved = crashwatch.repair_streamline_manifest(config, log=None)

    assert "nvngx_deny_list.txt" in moved, f"真凶没被清 ⇒ 症状会照旧：{moved}"
    assert "nvngx_mapping.json" not in moved, "内容正常的文件不许动"


def test_repair_is_noop_when_nothing_found(env, monkeypatch, tmp_path):
    """找不到任何目标 ⇒ 不动手、返回空列表。"""
    config, _runtime, _low = env
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "nohome2"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "empty-home"))
    assert crashwatch.repair_streamline_manifest(config, log=None) == []
