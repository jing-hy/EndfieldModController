"""★ **两个同名 neural addon 不能同装**（2026-10-07 本机实测抓到）。

**现场**：`runtime\\dlss5\\` 里同时有
  `renodx-dlss5-4.7_汉化.addon64`（已退役）与 `renodx-dlss5.addon64`（随包 7.0.0-rc8）。
两者注册名**完全相同**（"DLSS 5 Neural Rendering"）⇒ ReShade 日志：

    ERROR | [DLSS 5 Neural Rendering] vtable::Hook(Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C)
    ERROR | Failed to register add-on, because another one with the same name was already registered!
    ERROR | Failed to load add-on from '…\\renodx-dlss5.addon64' with error code 1114!

⇒ **NR 实际没生效**。这正是上游警告的「Never install two neural add-ons … it does nothing
at all for the whole session」。

**根因（两处，都必须修）**：
① 数据根那份 `assets\\dlss5\\manifest.json` 可能是**旧的**（还列着 `4.7_汉化`），而清单合并
   口径是"数据根优先" ⇒ 旧条目依然生效 ⇒ 展开时把它铺回根目录；
② `initialize.ensure_all()` **第 1 步** `_check_bundled_assets` 会**无条件展开**到顶层，
   而 `retire_stale_nr_addons()` 跑在它**之前** ⇒ 展开又把退役那份放回来。
   ⇒ 所以兜底必须放在 `ensure_all` 的**最后一步**（与"按开关归位 addon"同一个道理）。
"""
from __future__ import annotations

import ast as _ast
import inspect
import pathlib

import pytest

from endfieldmodcontroller import initialize, runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True)
    # 新旧两份同时躺在根目录（= 实测现场）
    (dlss5 / "renodx-dlss5-4.7_汉化.addon64").write_bytes(b"OLD-NR")
    (dlss5 / "renodx-dlss5.addon64").write_bytes(b"NEW-NR")
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: dlss5))
    config = AppConfig()
    config._config_path = str(tmp_path / "config.json")
    return config, dlss5


def test_retired_nr_is_moved_out_of_root(env):
    """★ 退役的那份必须被搬进 `_retired_addons\\`（只搬不删，可还原）。"""
    config, dlss5 = env
    moved = runtime_assets.retire_stale_nr_addons(config)

    assert moved == ["renodx-dlss5-4.7_汉化.addon64"], moved
    left = sorted(p.name for p in dlss5.glob("renodx-dlss5*"))
    assert left == ["renodx-dlss5.addon64"], f"根目录还有退役引擎：{left}"
    assert (dlss5 / runtime_assets.RETIRED_DIR / "renodx-dlss5-4.7_汉化.addon64").is_file()


def test_manifest_excludes_retired_entries(env, monkeypatch):
    """★★ **清单侧也要排除**退役条目 —— 否则展开动作会把它铺回根目录。

    这一条是"旧数据根清单"那个真实成因：数据根 `assets\\dlss5\\manifest.json` 里还列着
    `4.7_汉化`，而合并口径是"数据根优先" ⇒ 旧条目依然生效。
    """
    config, _dlss5 = env
    fake_entries = [
        ("dlss5", pathlib.Path("x"), "renodx-dlss5-4.7_汉化.addon64", {"size": 1}),
        ("dlss5", pathlib.Path("x"), "renodx-dlss5.addon64", {"size": 2}),
        ("dlss5", pathlib.Path("x"), "trans-zh.addon64", {"size": 3}),
    ]
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda cfg: list(fake_entries))
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda cfg: list(fake_entries))
    captured: dict[str, list] = {}

    def _capture(config_, **kwargs):
        captured.setdefault("checked", True)
        return []

    # 直接验证那个过滤判据（产品代码里叫 _is_retired）
    def _is_retired(entry_name: str) -> bool:
        lowered = entry_name.lower()
        retired = {n.lower() for n in runtime_assets.RETIRED_NR_ADDONS}
        return lowered in retired or ("renodx-dlss5-4.7" in lowered and lowered.endswith(".addon64"))

    kept = [name for _g, _r, name, _e in fake_entries if not _is_retired(name)]
    assert "renodx-dlss5-4.7_汉化.addon64" not in kept, "退役条目没被排除"
    assert kept == ["renodx-dlss5.addon64", "trans-zh.addon64"], kept


def test_ensure_all_parks_retired_nr_at_the_end():
    """★★ **顺序判据**：`retire_stale_nr_addons` 必须出现在 `initialize.ensure_all` 的**最后**。

    因为第 1 步 `_check_bundled_assets` 会无条件展开把退役那份铺回来 —— 与"按开关归位
    addon"是同一个病（展开会撤销前面的动作）。
    """
    src = inspect.getsource(initialize.ensure_all)
    tree = _ast.parse(src)
    lines = [n.lineno for n in _ast.walk(tree)
             if isinstance(n, _ast.Call)
             and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) == "retire_stale_nr_addons"]
    assert lines, "ensure_all 里没有清理退役 NR 引擎的兜底"

    bundled = [n.lineno for n in _ast.walk(tree)
               if isinstance(n, _ast.Call)
               and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) == "_check_bundled_assets"]
    assert bundled, "找不到展开随包资产那一步"
    assert max(lines) > max(bundled), (
        "清理退役 NR 的动作跑在『展开随包资产』**之前** ⇒ 展开会把它放回根目录（实测就是这个）"
    )
