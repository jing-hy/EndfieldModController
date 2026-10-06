"""NR 引擎换版（4.70 → 官方 7.0.0-rc8）的回归测试（2026-10-06）。

起因：反馈者「开 DLSS5 神经渲染就闪退」，包内现场是**两个 neural addon 同装**
（`deep-fried-chicken.addon64` + 随包的 `renodx-dlss5-4.7_汉化.addon64`）——
DLSS5-Feeder 原话："Never install two neural add-ons … it does nothing at all for the whole
session"，且 `feature 18 create intercepted` 之后再没有 `feature 18 created`，
evaluate 直接崩在 `nvngx_dlssnr.dll`。

因此这次做了两件事，都要钉住：
① **随包引擎换成官方 7.0.0-rc8**（自带多语言表，中文随系统区域生效 ⇒ 不再维护汉化版）；
② **升级时必须把退役的旧引擎主动搬走** —— ReShade 会加载根目录里所有 `*.addon64`，
   同装时两个都不工作；同时 `DLSS5_ADDON_GLOBS` 收窄成精确名，
   免得旧文件被搬进 `_disabled` 之后、用户一开开关又被"放回"。

⚠️ 另有一条**自我纠正**要钉住：Feeder 官方矩阵写「v4.70 × 617.14 = 0/300」，
但本机对照实测（同驱动）`inline feature 18 evaluation succeeded (count=60)` 正常
⇒ **判据必须先看"这次到底出没出帧"**，不能只看矩阵。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import crashwatch, launcher, runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    monkeypatch.setattr(AppConfig, "reshade_runtime_path",
                        property(lambda self: tmp_path / "runtime" / "reshade"))
    return dlss5, AppConfig()


def test_retired_nr_engine_is_moved_out_of_the_way(env):
    """★ 升级后旧引擎必须**搬走**（只搬不删，可还原）——否则两个 provider 同装、两个都不工作。"""
    dlss5, config = env
    old = dlss5 / "renodx-dlss5-4.7_汉化.addon64"
    old.write_bytes(b"old-engine")
    (dlss5 / "renodx-dlss5.addon64").write_bytes(b"new-engine")

    moved = runtime_assets.retire_stale_nr_addons(config)

    assert moved == ["renodx-dlss5-4.7_汉化.addon64"], moved
    assert not old.exists(), "旧引擎还留在根目录 ⇒ 会被 ReShade 一起加载"
    kept = dlss5 / runtime_assets.RETIRED_DIR / old.name
    assert kept.is_file(), "只搬不删：必须还能还原"
    assert (dlss5 / "renodx-dlss5.addon64").is_file(), "新引擎不能被误搬"


def test_retire_is_idempotent(env):
    """没有旧文件时不该有任何动作，也不该报错。"""
    _dlss5, config = env
    assert runtime_assets.retire_stale_nr_addons(config) == []


def test_the_shipped_asset_is_the_new_engine():
    """随包资产必须已经是 `renodx-dlss5.addon64`（旧的 4.7_汉化 条目要退役掉）。"""
    manifest = runtime_assets.load_manifest(Path(r"D:\zmdmod\modecontroller\assets\dlss5"))
    names = list(manifest["files"])
    assert "renodx-dlss5.addon64" in names
    assert not [n for n in names if n.startswith("renodx-dlss5-4.7")], names
    entry = manifest["files"]["renodx-dlss5.addon64"]
    assert entry["parts"] == ["renodx-dlss5.addon64.xz"]
    assert "rhi-repo" in entry["origin"]


def test_dlss5_addon_globs_do_not_match_the_retired_name():
    """★ glob 必须收窄：否则旧文件被搬进 `_disabled` 后，用户一开开关就被"放回"。"""
    assert launcher.DLSS5_ADDON_GLOBS[0] == "renodx-dlss5.addon64"
    assert "renodx-dlss5*.addon64" not in launcher.DLSS5_ADDON_GLOBS


@pytest.mark.parametrize("raw,expected", [
    ("32.0.16.1714", (617, 14)),
    ("32.0.15.6094", (560, 94)),
    ("32.0.15.7602", (576, 2)[:1] + (2,)),   # 576.02 —— 尾段不足 5 位也要能拆
])
def test_driver_branch_conversion(raw, expected):
    assert crashwatch._driver_branch(raw) == expected


def test_driver_branch_rejects_garbage():
    assert crashwatch._driver_branch("") is None
    assert crashwatch._driver_branch("abc") is None


def _write_log(dlss5: Path, body: str) -> None:
    (dlss5 / "ReShade.log").write_text(
        "Initializing crosire's ReShade\n" + body, encoding="utf-8")


def test_ran_ok_requires_more_than_one_frame(env):
    dlss5, config = env
    _write_log(dlss5, "inline feature 18 evaluation succeeded (count=1, ...)\n")
    assert crashwatch.nr_ran_ok(config) is False, "count=1 不算跑起来"
    _write_log(dlss5, "inline feature 18 evaluation succeeded (count=1)\n"
                      "inline feature 18 evaluation succeeded (count=60)\n")
    assert crashwatch.nr_ran_ok(config) is True


def test_mismatch_judgement_stays_silent_when_frames_flow(env, monkeypatch):
    """★ 自我纠正：出帧正常时**一个字都不说**，哪怕版本×驱动落在矩阵坏格子里。"""
    dlss5, config = env
    _write_log(dlss5,
               "RenoDX DLSS5 Generic v4.7 (build Sep  2 2026) loaded\n"
               "inline feature 18 evaluation succeeded (count=60)\n")
    monkeypatch.setattr(crashwatch, "current_driver_branch", lambda: (617, 14))
    assert crashwatch.nr_engine_driver_mismatch(config) == ""


def test_mismatch_judgement_speaks_only_when_no_frames(env, monkeypatch):
    """没出帧 + 版本×驱动在坏格子里 ⇒ 才把这条当线索说出来。"""
    dlss5, config = env
    _write_log(dlss5, "RenoDX DLSS5 Generic v4.7 (build Sep  2 2026) loaded\n")
    monkeypatch.setattr(crashwatch, "current_driver_branch", lambda: (617, 14))
    text = crashwatch.nr_engine_driver_mismatch(config)
    assert "known-bad" not in text            # 只断言它确实给出了线索
    assert "4.7" in text and "617.14" in text


def test_no_engine_version_means_no_claim(env, monkeypatch):
    """读不到引擎版本就不下结论（日志可能还没写过）。"""
    _dlss5, config = env
    monkeypatch.setattr(crashwatch, "current_driver_branch", lambda: (617, 14))
    assert crashwatch.nr_engine_driver_mismatch(config) == ""
