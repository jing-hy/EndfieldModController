"""钉住「线路排序：直连不能凭"曾经成功过"就一直排第一」。

**用户报**（2026-10-03）：「**现在下载怎么这么不稳定，这都不换线？**」

**实测证据链**：
* `_net/lines.json` 里 `"直连": {ok: true, fails: 0, mbps: 0.009}` ——
  "能连上但慢到 0.009 MB/s"（28 MB 要 52 分钟），却因为 `fails=0` **永远不会被拉黑**；
* 拉黑只有 `LINE_FAIL_TTL = 300` 秒 ⇒ 解封后又优先试它 ⇒
  「慢 → 拉黑 → 用镜像 → 解封 → 又试直连」无限循环 —— 这就是"不稳定"。

**两处修复**（本文件钉住）：
① 判据必须**自足**：直连实测速度低于 `DEAD_MBPS`（可用线阈值）就让位 ——
   **不能**写成"跟最快的镜像比"，因为实测那份缓存里**镜像根本没有 mbps 记录**
   （`best_mirror = 0` ⇒ 条件永不成立，我第一版就是这么错的）；
② 直连的冷却改用更长的 `DIRECT_FAIL_TTL`（1 小时），别 5 分钟就放它回来。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import fastnet as F

GH_URL = ("https://github.com/jing-hy/EndfieldModController/releases/download/"
          "v1.0.3/EndfieldModController.exe")


def test_constants_exist() -> None:
    """两个新常量在位，且直连冷却明显长于通用冷却。"""
    assert hasattr(F, "DIRECT_SLOW_RATIO"), "缺 DIRECT_SLOW_RATIO"
    assert hasattr(F, "DIRECT_FAIL_TTL"), "缺 DIRECT_FAIL_TTL"
    assert F.DIRECT_FAIL_TTL > F.LINE_FAIL_TTL, "直连的冷却应当比通用线路更长"


def test_slow_direct_yields_to_mirrors(monkeypatch) -> None:
    """★ 直连实测极慢（且镜像**没有任何记录**）时，必须让位给镜像。

    这条正是"判据要自足"的回归：第一版拿 `best_mirror` 比，而镜像没记录 ⇒ 永远不生效。
    """
    fake_cache = {
        F.DIRECT.name: {"ok": True, "fails": 0, "mbps": 0.009},   # 成功但极慢
        # 刻意**不给镜像任何记录** —— 复刻实测那份缓存
    }
    monkeypatch.setattr(F, "_load_lines_cache", lambda: fake_cache)
    order = [line.name for line in F.resolve_lines(GH_URL, "auto")]
    assert order, "不该是空顺序"
    assert order[0] != F.DIRECT.name, (
        f"直连只有 0.009 MB/s 却仍排第一：{order}")


def test_fast_direct_still_first(monkeypatch) -> None:
    """直连**正常**时仍然保持"直连优先"（不能矫枉过正）。"""
    fake_cache = {
        F.DIRECT.name: {"ok": True, "fails": 0, "mbps": 5.0},
        "gh-proxy.com": {"ok": True, "fails": 0, "mbps": 0.6},
    }
    monkeypatch.setattr(F, "_load_lines_cache", lambda: fake_cache)
    order = [line.name for line in F.resolve_lines(GH_URL, "auto")]
    assert order[0] == F.DIRECT.name, f"直连很快时应当仍是首选：{order}"


def test_unknown_direct_is_not_penalised(monkeypatch) -> None:
    """直连**没测过**（首次运行）时不该被降权。"""
    monkeypatch.setattr(F, "_load_lines_cache", lambda: {})
    order = [line.name for line in F.resolve_lines(GH_URL, "auto")]
    assert order[0] == F.DIRECT.name, f"首次运行应当先试直连：{order}"


def test_direct_mode_still_forces_direct(monkeypatch) -> None:
    """用户显式选「只用直连」时，必须**强制**直连（降权只作用于 auto）。"""
    fake_cache = {F.DIRECT.name: {"ok": True, "fails": 0, "mbps": 0.001}}
    monkeypatch.setattr(F, "_load_lines_cache", lambda: fake_cache)
    order = [line.name for line in F.resolve_lines(GH_URL, "direct")]
    assert order == [F.DIRECT.name], f"direct 模式应只给直连：{order}"


def test_direct_blocked_state_still_works(monkeypatch) -> None:
    """失败拉黑那条老逻辑不能被破坏（直连刚失败过就跳过它）。"""
    import time

    fake_cache = {
        F.DIRECT.name: {"ok": False, "fails": 1, "mbps": 0.0,
                        "fail_at": int(time.time()) - 10},
    }
    monkeypatch.setattr(F, "_load_lines_cache", lambda: fake_cache)
    order = [line.name for line in F.resolve_lines(GH_URL, "auto")]
    assert F.DIRECT.name not in order, f"刚失败过的直连不该出现：{order}"
