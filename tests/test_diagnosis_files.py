"""`collect_diagnosis_files`（排查素材一次收齐）的测试（2026-10-05）。

用户原话：「**你自己怎么查的，就把那些文件全收进日志包**」。

背景：这次定位「`0xC0000135` / NR 不自动开 / 资产展开失败」时，实际打开过一份清单
（生效的 ReShade 日志与 ini、面板 addon 日志、feed 日志、**运行库变体 marker**、
游戏自己的 `Player.log`、XXMI 配置与日志、**各 addon 的身份**、随包资产清单、
游戏目录里的 proxy 本体），而它们在包里**有些只收了一半** —— 于是每次排查都要
回头再找用户要一轮，与「日志包一次抓齐所有数据，不要搞好几轮」直接冲突。

**要守住的性质**：
* 那批文件**真的都被收进去**（尤其是变体 marker、addon 身份清单、资产 manifest）；
* addon 身份用"名 + 字节 + sha256 前 16"表示（4 MB 的本体不收，包不能爆）；
* 缺文件/读不到**安静跳过**，绝不抛（取证不能反噬打包）；
* **崩溃包与手动诊断包共用这一个入口**（判据只有一处）。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from endfieldmodcontroller import crashwatch, diagnostics, runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    for sub in ("dlss5", "reshade", "logs", "builtin"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: root))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: root / "dlss5"))
    monkeypatch.setattr(AppConfig, "reshade_runtime_path", property(lambda self: root / "reshade"))
    monkeypatch.setattr(AppConfig, "xxmi_launcher_path", property(lambda self: None))
    return root, config


def test_collects_the_whole_diagnosis_set(env, monkeypatch, tmp_path):
    """★ 这次排查用到的那批文件要**全都在**（少一个就又要回头要一轮）。"""
    root, config = env
    (root / "reshade" / "ReShade.log").write_text("cam\n", encoding="utf-8")
    (root / "reshade" / "ReShade.ini").write_text("[x]\n", encoding="utf-8")
    (root / "reshade" / "modecontroller.addon.log").write_text("panel\n", encoding="utf-8")
    (root / "dlss5" / "dlss5-feed.log").write_text("feed\n", encoding="utf-8")
    (root / "dlss5" / ".dlssnr_variant.json").write_text('{"variant":"sf"}', encoding="utf-8")
    addon = root / "dlss5" / "renodx-dlss5.addon64"
    addon.write_bytes(b"fake-addon-body")
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda config: [])
    # 让 proxy 采集那份也不折腾真实游戏目录
    monkeypatch.setattr(crashwatch, "_collect_injection_files", lambda config, dest: None)

    dest = tmp_path / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)

    for expected in ("reshade-effective-ReShade.log", "reshade-effective-ReShade.ini",
                     "reshade-modecontroller.addon.log", "dlss5-feed.log",
                     "dlss5-variant.json", "dlss5-addons.txt"):
        assert expected in taken, f"少了 {expected}（收进去的是 {taken}）"
        assert (dest / expected).is_file(), expected


def test_addon_identity_uses_sha256_prefix(env, monkeypatch, tmp_path):
    """addon 只收**身份**（名/字节/sha256 前 16），不收 4 MB 的本体。"""
    root, config = env
    (root / "dlss5" / "x.addon64").write_bytes(b"abc")
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda config: [])
    monkeypatch.setattr(crashwatch, "_collect_injection_files", lambda config, dest: None)

    dest = tmp_path / "out"
    crashwatch.collect_diagnosis_files(config, dest)
    text = (dest / "dlss5-addons.txt").read_text(encoding="utf-8")
    assert "x.addon64" in text and "3 B" in text
    assert "ba7816bf8f01cfea" in text, f"要带 sha256 前 16：{text}"
    assert not (dest / "x.addon64").exists(), "本体不该被收（包会爆）"


def test_asset_manifests_are_collected(env, monkeypatch, tmp_path):
    """随包资产清单（每组一份 manifest.json）要收 —— 判"资产齐不齐/分卷对不对"全靠它。"""
    root, config = env
    group = tmp_path / "assets" / "nvngx"
    group.mkdir(parents=True)
    (group / "manifest.json").write_text('{"version":1}', encoding="utf-8")
    monkeypatch.setattr(runtime_assets, "manifest_entries",
                        lambda config: [("nvngx", group, "a.dll", {})])
    monkeypatch.setattr(crashwatch, "_collect_injection_files", lambda config, dest: None)

    dest = tmp_path / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)
    assert "assets-nvngx-manifest.json" in taken
    assert (dest / "assets-nvngx-manifest.json").is_file()


def test_missing_files_are_skipped_silently(env, monkeypatch, tmp_path):
    """什么都没造时也不能抛（取证不能反噬打包）。"""
    _root, config = env
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda config: [])
    monkeypatch.setattr(crashwatch, "_collect_injection_files", lambda config, dest: None)
    taken = crashwatch.collect_diagnosis_files(config, tmp_path / "out")
    assert isinstance(taken, list)


def test_both_channels_use_the_same_collector():
    """★ 崩溃包与手动诊断包**共用这一个入口**（判据只有一处）。"""
    assert "collect_diagnosis_files" in inspect.getsource(crashwatch.make_bundle)
    assert "collect_diagnosis_files" in inspect.getsource(diagnostics)


def test_keylines_excerpt_for_big_log(env, monkeypatch, tmp_path):
    """★ 大日志**节选**（用户规矩：「特别大文件可以节选你要的」）—— 只留判据相关行。

    `ReShade.log` 动辄上百 KB，而第一轮排查真正要看的只有"相机 hook 装没装 / NR 有没有
    建帧 / addon 注册 / 报错"那几类行。节选出来，就不必再回头找用户要文件。
    """
    root, config = env
    log = root / "reshade" / "ReShade.log"
    log.write_text(
        "00:22:11 noise line 1\n"
        "00:22:23 | INFO | [RenoDX: Arknights Endfield Enhancer] Endfield enhancer: "
        "Camera controls installed.\n"
        "00:22:24 noise line 2\n"
        "00:22:25 | INFO | DLSS5 Generic: feature 18 created via the signed snippet\n"
        "00:22:26 | ERROR | something broke\n",
        encoding="utf-8")
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda config: [])
    monkeypatch.setattr(crashwatch, "_collect_injection_files", lambda config, dest: None)

    dest = tmp_path / "out"
    taken = crashwatch.collect_diagnosis_files(config, dest)

    assert "reshade-keylines.txt" in taken, taken
    text = (dest / "reshade-keylines.txt").read_text(encoding="utf-8")
    assert "Camera controls installed" in text
    assert "feature 18 created" in text
    assert "something broke" in text
    assert "noise line 1" not in text, "噪音行不该进来 —— 节选的意义就在这里"
