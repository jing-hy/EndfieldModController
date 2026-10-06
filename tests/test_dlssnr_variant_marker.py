"""对照包定案：`_installed_matches()` 不能看 `marker["sm"]`（2026-10-06，两份 40 系包）。

**现场**（用户给的两份包，都是 RTX 40 系 / sm_89）：
| | marker `variant` | marker `arch` | DLSS5 |
|---|---|---|---|
| `104453` | **`rtx40`** | **`[89, 120]`** | ✅ 能开 |
| `165010` | **`official`** | **`[120]`** | ❌ 开不了 |

两者的 `marker["sm"]` **都是 89**（那是"这台机器"的代次），而 `arch` 才是"**这份 dll 真正带的架构**"。
旧判据 `int(marker["sm"]) == sm or sm in archs` 的前半段**恒真** ⇒ 任何已就位的 dll 都被当成
"含本机架构" ⇒ **永不换变体**，于是 40 系机器一直跑只有 sm_120 内核的 `official` ⇒
`feature 18` 建不出来 ⇒ **「DLSS5 打不开」**。

要守住：**只看 `arch`**；`sm` 字段仅用于"记录当时是什么卡"。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from endfieldmodcontroller import runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    return AppConfig(), dlss5


def _write_marker(dlss5: pathlib.Path, *, variant: str, sm: int, arch: list[int],
                  size: int) -> None:
    (dlss5 / runtime_assets.DLSSNR_MARKER).write_text(json.dumps({
        "variant": variant, "sm": sm, "arch": arch,
        "file": runtime_assets.DLSSNR_TARGET, "size": size, "at": 1,
    }), encoding="utf-8")


def _fake_target(dlss5: pathlib.Path, size: int) -> None:
    (dlss5 / runtime_assets.DLSSNR_TARGET).write_bytes(b"x" * 16)
    # 让 size 对得上 marker（测试里不真造 165 MB 的文件）
    pathlib.Path(dlss5 / runtime_assets.DLSSNR_TARGET).write_bytes(b"x" * size)


def test_official_only_arch_is_not_accepted_on_ada(env, monkeypatch):
    """★ `official`（arch=[120]）在 40 系（sm=89）上**必须判 False** —— 这正是打不开那份的状态。

    旧判据因为 `marker["sm"] == 89` 而返回 True ⇒ 永远不换变体 ⇒ 一直跑错内核。
    """
    config, dlss5 = env
    _fake_target(dlss5, 1024)
    _write_marker(dlss5, variant="official", sm=89, arch=[120], size=1024)
    monkeypatch.setattr(runtime_assets, "dll_architectures", lambda _p: {120})

    assert runtime_assets._installed_matches(config, 89) is False, (
        "又把只有 sm_120 的那份当成'含本机架构'了 ⇒ 40 系永远不会被换成 rtx40 ⇒ DLSS5 打不开"
    )


def test_rtx40_arch_is_accepted_on_ada(env, monkeypatch):
    """★ `rtx40`（arch=[89,120]）在 40 系上判 True（能开那份的状态）—— 幂等路径要保留。"""
    config, dlss5 = env
    _fake_target(dlss5, 1024)
    _write_marker(dlss5, variant="rtx40", sm=89, arch=[89, 120], size=1024)
    monkeypatch.setattr(runtime_assets, "dll_architectures", lambda _p: {89, 120})

    assert runtime_assets._installed_matches(config, 89) is True


def test_blackwell_accepts_official(env, monkeypatch):
    """50 系（sm=120）上 `official` 本来就是对的 ⇒ 仍判 True（别把正常路径弄坏）。"""
    config, dlss5 = env
    _fake_target(dlss5, 1024)
    _write_marker(dlss5, variant="official", sm=120, arch=[120], size=1024)
    monkeypatch.setattr(runtime_assets, "dll_architectures", lambda _p: {120})

    assert runtime_assets._installed_matches(config, 120) is True
