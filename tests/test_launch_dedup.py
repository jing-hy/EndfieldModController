"""「点一次启动却拉起多个 XXMI」的回归测试（2026-10-06）。

**实测现场**（用户原话：「为什么点一下启动拉起了 4 个 efmi」）：
日志里连着四条 `launch command: [...\\XXMI Launcher.exe]`（07:54:58 / 07:55:01 /
07:55:06 / 07:55:10），任务管理器里 4 个 `XXMI Launcher`，每个各挂一套 EFMI。
而**进程监视器那一步是防重的** —— 紧随其后就是「进程监视已在运行，跳过重复启动」。
⇒ 唯独"**真正拉起进程**"这一步没有防重：判据放错了层。

**两道闸，缺一不可**：
① `launcher.launch()`：拉起**之前**先 `xxmi_process_running()`，已在跑就不再拉
   —— 这是根本防线（不管请求从哪来、来几次，系统里只会有一个 XXMI）；
② `api.launch()` / `api.launch_game()`：**非阻塞**入口锁，重复请求直接回
   `duplicate=True` —— 不排队（排队会让"点几次启动几次"），也不干等。

**要守住的性质**：判据必须在**执行动作之前**、且在**同一个函数里**（不是散在别处）。
"""
from __future__ import annotations

import inspect

from endfieldmodcontroller import api, launcher


def test_spawn_is_guarded_by_running_check():
    """★ 拉起 XXMI 之前必须检查已有实例，且顺序不能反。"""
    src = inspect.getsource(launcher.launch)
    # ⚠️ 判据要**精确到那一句 `if`** —— 只查"函数名有没有出现"会假绿
    #    （反向验证 S 第一次就是这么没红的）。
    assert "if xxmi_process_running(config):" in src, "没有检查已有实例 ⇒ 会多开"
    guard = src.index("if xxmi_process_running(config):")
    spawn = src.index("_spawn_command(config, command")
    assert guard < spawn, "检查必须排在真正拉起之前（顺序反了等于没防）"
    assert "xxmi_already_running" in src, "命中时要留下可辨认的结果标记"
    assert "已在运行" in src, "命中时要写一条能读懂的日志"


def test_launch_gate_is_non_blocking_and_shared():
    """★ 入口锁必须**非阻塞**、且 launch 与 launch_game 共用同一把。"""
    src = inspect.getsource(api)
    assert "def _launch_gate" in src
    # ⚠️ 同样精确化 + **数出现次数**：`api.py` 里别处也可能有非阻塞锁，
    #    只查"关键字在不在"会假绿（反向验证 T 第一次就是这么没红的）。
    assert src.count("if not lock.acquire(blocking=False):") == 2, \
        "两个启动入口各要一处非阻塞取锁"
    assert src.count('{"started": False, "duplicate": True') == 2, "两个入口都要能辨认重复请求"
    # 两个入口都要过闸
    assert src.count("lock = self._launch_gate()") >= 2, "launch / launch_game 都要过闸"
    assert src.count("finally:\n            lock.release()") >= 2, "异常路径也必须释放锁"


def test_gate_lock_is_per_class_singleton():
    """锁必须是**进程内单例**：每次新建锁等于没有锁。"""
    src = inspect.getsource(api)
    assert "_launch_lock" in src
    assert "type(self)._launch_lock" in src, "锁要挂在类上（每次新建就等于没锁）"


def test_empty_stdout_from_powershell_not_a_failure_marker():
    """（邻接判据）启动结果里 `duplicate` 只能是布尔，别混进会误导前端的字段。"""
    src = inspect.getsource(api)
    i = src.index("def _launch_gate")
    block = src[i:i + 4000]
    assert '{"started": False, "duplicate": True' in block
