"""`pedeps`（注入 DLL 依赖预检）与"净化后铺回清单"的测试（2026-10-05）。

**为什么要有 `pedeps`**：那份 `diagnostics-20261005-223225` 的机器上，游戏以
`0xC0000135 STATUS_DLL_NOT_FOUND` **极早期**退出（现象："滴滴两声、任务栏只闪一下
终末地图标、没有窗口"），而诊断包只能看出"它死得早"—— **看不出缺的是哪个 DLL**，
反馈者又自称"电脑小白"。这个模块把"缺哪个"变成诊断包里能直接读到的结论。

**要守住的性质**：
* 能读出 PE 的静态导入表与目标架构；
* ⭐ **缺依赖必须被报出来**（这是它存在的唯一理由）；
* API set 虚拟名（`api-ms-win-*`）**不许**被当成"缺失"（否则满屏假阳性）；
* 报告里必须写明"**只覆盖静态导入表**"这条限制（否则会被当成全量体检）；
* 非 PE 文件与读不出来的文件要如实进 `skipped`，不许把整个诊断包拖垮。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from endfieldmodcontroller import game_clean, pedeps, reshade_integration

SYSTEM32 = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"
KERNEL32 = SYSTEM32 / "kernel32.dll"
needs_kernel32 = pytest.mark.skipif(
    not KERNEL32.is_file(), reason=r"没有 System32\kernel32.dll（非 Windows？）")


@needs_kernel32
def test_reads_imports_and_machine():
    """真实样本：能读出架构与静态导入表。"""
    assert pedeps.pe_machine(KERNEL32) == "x64"
    imports = pedeps.pe_imports(KERNEL32)
    assert imports, "kernel32 至少有几个导入"
    assert all(item.lower().endswith(".dll") for item in imports), imports[:5]
    assert len(imports) == len(set(imports)), "导入表要去重"


@needs_kernel32
def test_missing_dependency_is_reported(tmp_path):
    """⭐ 命根子：依赖解析不到时必须报出来（用一个空目录当搜索路径）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    result = pedeps.check_paths([KERNEL32], search_dirs=[empty])
    assert str(KERNEL32) in result["checked"]
    assert result["missing"], "空搜索目录下，依赖必然全部找不到"
    assert all(item["file"] == str(KERNEL32) for item in result["missing"])
    assert all(item["dep"].lower().endswith(".dll") for item in result["missing"])
    # 报出来的依赖名必须是导入表里真实存在的
    imports = {name.lower() for name in pedeps.pe_imports(KERNEL32)}
    assert all(item["dep"].lower() in imports for item in result["missing"])


@needs_kernel32
def test_dependency_resolves_when_search_dir_has_it(tmp_path):
    """搜索目录里放上同名文件就算找到（**文件名级**解析，这是明说的限制）。"""
    fake_system = tmp_path / "sys"
    fake_system.mkdir()
    for name in pedeps.pe_imports(KERNEL32):
        (fake_system / name).write_bytes(b"")
    result = pedeps.check_paths([KERNEL32], search_dirs=[fake_system])
    assert result["missing"] == [], result["missing"]


def test_api_set_names_are_not_dependencies():
    """`api-ms-win-*` 是虚拟名 —— 当依赖要跳过，当**输入文件**也要跳过。"""
    assert pedeps.is_api_set("api-ms-win-core-file-l1-1-0.dll")
    assert pedeps.is_api_set("ext-ms-win-ntuser-window-l1-1-0.dll")
    assert not pedeps.is_api_set("kernel32.dll")


def test_api_set_input_file_is_ignored(tmp_path):
    """游戏目录里那些 `api-ms-win-*.dll` stub **不该**被拿去解析（会刷满噪音）。"""
    stub = tmp_path / "api-ms-win-core-file-l1-1-0.dll"
    stub.write_bytes(b"MZ" + b"\0" * 200)
    result = pedeps.check_paths([stub], search_dirs=[tmp_path])
    assert result["checked"] == []
    assert result["skipped"] == [], "它是被明确跳过，不是'解析失败'"


def test_non_pe_file_is_skipped_not_crash(tmp_path):
    """非 PE 文件 → 进 `skipped`，绝不让整个诊断包炸掉。"""
    junk = tmp_path / "notes.txt"
    junk.write_text("hello", encoding="utf-8")
    result = pedeps.check_paths([junk, tmp_path / "不存在.dll"], search_dirs=[tmp_path])
    assert result["checked"] == []
    assert any(item["file"] == str(junk) for item in result["skipped"])
    assert result["missing"] == []


@needs_kernel32
def test_report_states_its_limits():
    """报告必须自带限制说明 —— 否则会被当成"全量体检"。"""
    result = pedeps.check_paths([KERNEL32], search_dirs=[SYSTEM32])
    text = "\n".join(pedeps.report_lines(result))
    assert "注入 DLL 依赖检查" in text
    assert "静态导入表" in text
    assert "LoadLibrary" in text, "要写明运行期拉起的 DLL 不在覆盖范围"
    assert "没报缺" in text and "不等于" in text
    assert "0xC0000135" in text, "要说清这类缺失的表现"


@needs_kernel32
def test_report_lists_missing_names(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = pedeps.check_paths([KERNEL32], search_dirs=[empty])
    text = "\n".join(pedeps.report_lines(result, limit=3))
    assert "解析不到" in text
    assert "kernel32.dll" in text


# --------------------------------------------------------------------------- 接入
def test_diagnostics_section_uses_pedeps(monkeypatch, tmp_path):
    """诊断包里的那一段走 `pedeps`，并且**缺依赖会出现在 summary 里**。"""
    from endfieldmodcontroller import diagnostics

    calls: list[list[str]] = []

    def fake_check(paths, *, game_dir=None, extra_dirs=None, search_dirs=None):
        calls.append([Path(p).name for p in paths])
        return {
            "checked": [str(paths[0])],
            "missing": [{"file": str(paths[0]), "machine": "x64", "dep": "缺失的.dll",
                         "searched": []}],
            "skipped": [],
        }

    monkeypatch.setattr(pedeps, "check_paths", fake_check)
    game_dir = tmp_path / "game"
    (game_dir / "plugin").mkdir(parents=True)
    (game_dir / "Endfield.exe").write_bytes(b"MZ")
    (game_dir / "d3dcompiler_47.dll").write_bytes(b"MZ")
    (game_dir / "plugin" / "poser.dll").write_bytes(b"MZ")

    class _Config:
        dlss5_path = str(tmp_path / "runtime" / "dlss5")

    lines = diagnostics._pe_deps_summary(_Config(), game_dir)
    text = "\n".join(lines)
    assert "缺失的.dll" in text
    assert calls, "必须真的调用了 pedeps"
    assert "Endfield.exe" in calls[0] and "d3dcompiler_47.dll" in calls[0]
    assert "poser.dll" in calls[0], f"plugin 目录下的 DLL 也要查：{calls[0]}"


def test_diagnostics_section_empty_without_candidates(monkeypatch, tmp_path):
    """没有可查的文件时**不产出空段**（免得 summary 里多一段废话）。"""
    from endfieldmodcontroller import diagnostics

    class _Config:
        dlss5_path = str(tmp_path / "nope")

    assert diagnostics._pe_deps_summary(_Config(), tmp_path / "空的游戏目录") == []


# --------------------------------------------------------------------------- 净化铺回清单
def test_injection_snapshot_lists_plugin_and_proxies(monkeypatch, tmp_path):
    """净化后的基线快照：`plugin/` 下的东西与 loader proxy 都要在（**不算 sha256**）。"""
    game_dir = tmp_path / "game"
    (game_dir / "plugin").mkdir(parents=True)
    (game_dir / "plugin" / "poser.dll").write_bytes(b"x" * 32)
    (game_dir / "plugin" / "sbm.dll").write_bytes(b"x" * 32)
    proxy = game_dir / "d3dcompiler_47.dll"
    proxy.write_bytes(b"...poser loader marker..." * 8)

    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, prefer_actual=False: game_dir)
    snapshot = game_clean.injection_snapshot(None)
    assert "plugin/poser.dll" in snapshot
    assert "plugin/sbm.dll" in snapshot
    assert "d3dcompiler_47.dll" in snapshot


def test_injection_snapshot_is_empty_without_game_dir(monkeypatch):
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, prefer_actual=False: None)
    assert game_clean.injection_snapshot(None) == set()


def test_restored_names_are_the_set_difference(monkeypatch, tmp_path):
    """★ 净化后铺回了哪些 = **两次快照的差集**（launcher 就是这么做说明的）。"""
    game_dir = tmp_path / "game"
    (game_dir / "plugin").mkdir(parents=True)
    (game_dir / "plugin" / "third_party.dll").write_bytes(b"x")
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, prefer_actual=False: game_dir)

    purged = game_clean.injection_snapshot(None)          # 净化后（还剩第三方的）
    assert "plugin/third_party.dll" in purged
    (game_dir / "plugin" / "poser.dll").write_bytes(b"x")  # 按开关铺回
    restored = sorted(game_clean.injection_snapshot(None) - purged)
    assert restored == ["plugin/poser.dll"], restored
