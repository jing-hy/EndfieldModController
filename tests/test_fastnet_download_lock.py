# SPDX-License-Identifier: AGPL-3.0-only
"""钉住「同一目标文件不许两个任务同时下」（2026-11-28 用户日志实测）。

现场（`endfieldmodcontroller-20261128.log`，21:32:39）：

    分块 4194304-4318423 第 4 次失败：工作文件在下载过程中不见了
    （ReShade_Setup_6.8.0_Addon.exe.mcdownload）—— 可能是杀软隔离或并发清理

真因是两个流程同时在下 `ReShade_Setup_6.8.0_Addon.exe`：工作文件名只按目标名派生，
于是它们共用同一个 `.mcdownload` 与 `.mcparts`，互相删/覆盖。分块临时文件被两个任务
共写，可能产成长度正确、内容带空洞的坏包 —— 比"这一份让别人下"严重得多。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import fastnet


def test_same_destination_is_rejected_while_busy(tmp_path: Path) -> None:
    """目标文件正被另一个任务下载时，本任务必须**明确拒绝**，而不是共用临时文件。"""
    dest = tmp_path / "ReShade_Setup_6.8.0_Addon.exe"
    lock = fastnet._destination_lock(dest)
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(OSError) as ctx:
            # 地址故意不可达：没有锁检查时会去连它，报的就**不是**这句话了
            fastnet.download("http://127.0.0.1:1/none", dest)
    finally:
        lock.release()
    assert "另一个下载任务" in str(ctx.value)


def test_lock_key_is_case_insensitive(tmp_path: Path) -> None:
    """同一个目标文件的不同写法要落到同一把锁上（Windows 路径大小写不敏感）。"""
    a = fastnet._destination_lock(tmp_path / "Same.exe")
    b = fastnet._destination_lock(tmp_path / "same.EXE")
    assert a is b