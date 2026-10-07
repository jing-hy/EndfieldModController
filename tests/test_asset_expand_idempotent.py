"""`ensure_all` 不许**每轮强制重解压 165 MB**（2026-10-07 真凶）。

**现场**（用户报的是三件事，其实是同一件）：
  「刚启动的时候每次都是注入开关全部变成关的」「过很久才能打开」
  「dlss5 和 dlss4 的互斥也超级慢」

原因是 `ensure_all` 里那行
```python
ensure_dlssnr(config, ..., force=force or bool(fixed_items))
```
`fixed_items` = 清单里那两条 `nvngx_dlssnr*` 条目（official + sf）⇒ **恒非空**
⇒ 表达式**恒为 True** ⇒ 每轮都重解压 165 MB（实测 4.6~4.8 秒/轮）。

而同一次启动里 `ensure_all` 最多被调 **4 轮**：
  `launcher.ensure_injections` → `integrity.repair_integrity` → `initialize.ensure_all`
  → `launcher.launch`
⇒ 累计约 19 秒主线程被占住 ⇒ 那期间：addon 文件还在 `_disabled\\`（开关看着是关的）、
点开关没反应、互斥切换也慢。

**修后实测**：三轮分别 0.09 / 0.00 / 0.00 秒（原来 4.8 / 4.67 / 4.65）。

⚠️ `force` 仍要透传：依赖页「一键更新全部组件」传的就是 `force=True`，那时**要**真重解。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import runtime_assets as ra
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    config = AppConfig()
    config._config_path = str(tmp_path / "config.json")
    return config, dlss5


def test_second_round_does_not_redecompress(env, monkeypatch):
    """★★ 第二轮必须是 `present`（跳过），不能被强制重解压。"""
    config, _dlss5 = env
    calls: list[bool] = []

    # 打桩 ensure_dlssnr：只记录 force 的取值，不真的解压
    def fake_ensure_dlssnr(cfg, *, log=None, progress=None, force=False, rescan=False):
        calls.append(bool(force))
        return ra.AssetResult(ra.DLSSNR_TARGET, "present", "已就位", 0, "", "", "nvngx")

    monkeypatch.setattr(ra, "ensure_dlssnr", fake_ensure_dlssnr)
    monkeypatch.setattr(ra, "manifest_entries", lambda cfg: [
        ("nvngx", pathlib.Path("r"), "nvngx_dlssnr.dll",
         {"install_as": "nvngx_dlssnr.dll", "variant": "official", "size": 1}),
        ("nvngx", pathlib.Path("r"), "nvngx_dlssnr.sf.dll",
         {"install_as": "nvngx_dlssnr.dll", "variant": "sf", "size": 1}),
    ])
    monkeypatch.setattr(ra, "select_dlssnr_variant", lambda cfg, rescan=False: ra.DlssnrChoice(
        sm=120, variant="official", effective="official", source_kind="installed",
        source_name=ra.DLSSNR_TARGET, target=str(_dlss5 / ra.DLSSNR_TARGET), reason="test"))

    ra.ensure_all(config, log=None)
    ra.ensure_all(config, log=None)

    assert calls, "ensure_dlssnr 没被调用"
    assert calls == [False, False], (
        f"force 被写成了 True（fixed_items 恒非空 ⇒ 每轮重解压 165 MB）：{calls}")


def test_explicit_force_still_forces(env, monkeypatch):
    """★ 反向对照：依赖页「一键更新全部组件」传 `force=True` ⇒ 照旧强制重解。"""
    config, _dlss5 = env
    calls: list[bool] = []

    def fake_ensure_dlssnr(cfg, *, log=None, progress=None, force=False, rescan=False):
        calls.append(bool(force))
        return ra.AssetResult(ra.DLSSNR_TARGET, "present", "已就位", 0, "", "", "nvngx")

    monkeypatch.setattr(ra, "ensure_dlssnr", fake_ensure_dlssnr)
    monkeypatch.setattr(ra, "manifest_entries", lambda cfg: [
        ("nvngx", pathlib.Path("r"), "nvngx_dlssnr.dll",
         {"install_as": "nvngx_dlssnr.dll", "variant": "official", "size": 1}),
    ])
    monkeypatch.setattr(ra, "select_dlssnr_variant", lambda cfg, rescan=False: ra.DlssnrChoice(
        sm=120, variant="official", effective="official", source_kind="installed",
        source_name=ra.DLSSNR_TARGET, target=str(_dlss5 / ra.DLSSNR_TARGET), reason="test"))

    ra.ensure_all(config, force=True, log=None)
    assert calls == [True], f"显式 force 没透传下去：{calls}"


def test_source_no_longer_multiplies_by_fixed_items():
    """★ 静态判据：不许再出现 `force=force or bool(fixed_items)` 那种写法。

    ⚠️ **只看代码行**：注释里为了说明"为什么不能这么写"会**引用**那个表达式
    （2026-10-07 我就被自己的注释弄红过一次 —— 同族的坑在
    `test_component_toggle_log_labels.py` 也踩过，两处都按"去掉整行注释"处理）。
    """
    code = "\n".join(
        line for line in pathlib.Path(ra.__file__).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "force or bool(fixed_items)" not in code, \
        "那行『fixed_items 恒非空 ⇒ force 恒真』的写法又回来了（会让每轮重解压 165 MB）"
    assert "force=force," in code or "force=force)" in code, \
        "ensure_dlssnr 的 force 应当原样透传（只受调用方控制）"
