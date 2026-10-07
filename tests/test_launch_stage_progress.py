"""「一键启动走到哪一步」要能在界面上看见（2026-10-07 用户要求）。

用户原话：「**启动到扫除mod还是很慢，要是要时间就显示加载页面**」。

启动链上有几处天然要花时间：检查注入库 → 随包组件校验 → **`stage_and_prepare` 重建
几 GB 的 Mods 目录** → 净化游戏目录 → 拉起 XXMI。以前界面只有按钮文字「正在启动…」，
用户分不清"在干活"还是"卡死了"。现在后端在关键节点写 `launch_stage`，
前端（本来就按 1~2 秒轮询 `get_state()`）直接显示。

⚠️ 这是**纯展示**状态：不参与任何判断，读不到/过期就当没有（界面退回按钮文字）。
"""
from __future__ import annotations

import time

from endfieldmodcontroller import launcher


def test_stage_roundtrip():
    """★ 写进去要能读出来（含时刻）。"""
    launcher.set_launch_stage("正在重建 Mod 目录…")
    stage = launcher.current_launch_stage()
    assert stage.get("text") == "正在重建 Mod 目录…", stage
    assert isinstance(stage.get("at"), float) and stage["at"] > 0, stage


def test_stage_expires(monkeypatch):
    """★ 超过 TTL 就当没在启动 —— 否则界面会永远停在最后那句阶段文案。"""
    launcher.set_launch_stage("正在拉起 XXMI 启动器…")
    assert launcher.current_launch_stage(), "刚开始应当是有效的"

    # 把 TTL 临时改小，再把时刻往前挪
    monkeypatch.setattr(launcher, "_LAUNCH_STAGE_TTL", 0.01, raising=False)
    time.sleep(0.05)
    assert launcher.current_launch_stage() == {}, "过期后应当返回空"


def test_empty_stage_is_empty():
    """没启动过（或文案为空）⇒ 返回空 dict / 空文案，界面据此隐藏那一行。"""
    launcher.set_launch_stage("")
    stage = launcher.current_launch_stage()
    assert stage.get("text") == "", stage


def test_get_state_exposes_launch_stage():
    """★ `get_state()` 必须把它带出去（前端就是从这里读的）。"""
    import inspect

    from endfieldmodcontroller import api as api_module

    src = inspect.getsource(api_module.EndfieldModControllerApi.get_state)
    assert "launch_stage" in src, "get_state 没有把启动阶段带给前端"
    assert "current_launch_stage" in src, "应当走 launcher.current_launch_stage()"


def test_launch_writes_stages_at_key_points():
    """★ 静态判据：启动链上的几个关键节点都要写阶段（少了哪个，界面就会停在上一句）。"""
    import inspect
    import re

    src = inspect.getsource(launcher.launch)
    texts = re.findall(r'set_launch_stage\("([^"]+)"\)', src)
    assert len(texts) >= 4, f"阶段点太少（{len(texts)} 个）：{texts}"
    joined = " ".join(texts)
    # 用户点名的那一步必须在（"扫除 mod" = 重建 Mod 目录）
    assert "Mod 目录" in joined, f"没有'重建 Mod 目录'这一步：{texts}"
    assert any("XXMI" in t for t in texts), f"没有'拉起 XXMI'这一步：{texts}"
