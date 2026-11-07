# SPDX-License-Identifier: GPL-3.0-or-later
"""全局测试桩：**别让被测进程留下后台线程**。

`EndfieldModControllerApi.__init__` 会起一条预热线程（扫 Mod 库、等 `ui_ready`、
拉角色表 / 公告 / 商城索引…）。测试里创建完实例用例就结束了，但那条线程还在跑：

* 轻则在下个用例打桩的 `fastnet.fetch` 上留下"莫名多出来的请求"
  （2026-11-07：`detail()` 用例断言 2 次请求，实际 3 次）；
* 重则长时间占着 **商城索引的读写锁**（全量拉 16 页要二三十秒），让后面的索引用例拿到
  `busy=True` 而不是真的刷新（同一天实测：全量跑 5 条索引用例失败，单独跑全绿）。

所以这里统一把"起预热线程"这一步桩掉。**`_warm_up` 本身不桩** —— 有测试（预热顺序、
索引自动刷新）要直接调它。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import api


@pytest.fixture(autouse=True)
def _no_background_warm_up_threads(monkeypatch):
    monkeypatch.setattr(api.EndfieldModControllerApi, "_start_warm_up", lambda self: None)
