#!/usr/bin/env python
"""跑单元测试 —— 与构建脚本拆开的独立入口（**并发按本机开始前的 CPU 占用决定**）。

    python scripts/run_tests.py                    # 全量（tests/）
    python scripts/run_tests.py tests/test_x.py    # 只跑指定文件/目录
    python scripts/run_tests.py -k 关键字          # 其余参数原样透传给 pytest
    python scripts/run_tests.py --attempts 1       # 不重试
    python scripts/run_tests.py --serial           # 强制单线程（忽略 CPU 占用）
    python scripts/run_tests.py -n 4               # 自己指定并发（透传给 pytest）

**为什么单独一个脚本**（2026-10-09 用户要求：「本机不做并行构建和测试，你要拆两个脚本出来」）：

* 构建（`build_release.py`）与测试不再挤在同一次调用里 —— 谁都不替谁做主：
  构建不会顺手跑全量测试，本脚本也绝不会去动 `dist\\`。

**并发规则**（用户 2026-10-09 定：「**如果开始前 cpu 占用小于 30 就用 4 并发**」）：

* 开跑**之前**采一次本机 CPU 占用：**< 30%** ⇒ `-n 4`（这时机器闲着，全量套件能省一半
  以上的时间）；**≥ 30%** ⇒ 单线程（不跟用户正在用的东西抢资源）；
* 读不到占用（非 Windows / API 不可用）⇒ 保守走单线程；
* 没装 `pytest-xdist` ⇒ 自动退回单线程，绝不因为缺插件而失败；
* 想固定行为：`--serial` 强制单线程；或直接传 `-n <N>`，那时本脚本**完全听你的**。

**偶发失败自动重试**（沿用项目已定约定：批量不 fail-fast、失败项自动重试、上限 3 次）：
`test_sbm_data_sync` 会真的调 `robocopy`，在临时目录下有概率失败。重试完仍失败才判失败
（不靠重试掩盖真失败），并把 FAILED 行列出来。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = ("tests",)

#: 开始前 CPU 占用**低于**这个百分比 ⇒ 上并发（用户 2026-10-09 定的阈值）。
CPU_IDLE_BELOW_PERCENT = 30.0
#: 并发 worker 数（与旧构建脚本一致：`-n auto` 会按逻辑核开满，磁盘 IO 反而互相拖）。
PARALLEL_WORKERS = 4


def _fix_console() -> None:
    """中文 Windows 控制台默认 GBK —— 直接 print 项目里的中文/特殊字符会崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def cpu_load_percent(sample_seconds: float = 0.35) -> float | None:
    """本机**当前** CPU 占用百分比（Windows 用 `GetSystemTimes` 两次采样；读不到返回 None）。

    * 不用 `os.getloadavg()`：Windows 上没有它。
    * 不用 psutil：那要额外依赖，而这个脚本要能在"别人 clone 下来"时也跑得起来。
    * 必须采两次：`GetSystemTimes` 给的是**开机以来的累计值**，求差才知道瞬时占用
      （`(kernel + user)` 里已经含 idle，所以占用率 = 1 − Δidle/Δtotal）。
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import time as _time
        from ctypes import wintypes

        class _FileTime(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD)]

        def _snapshot() -> tuple[int, int]:
            idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
            ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            if not ok:
                raise OSError("GetSystemTimes 调用失败")

            def _ticks(ft: "_FileTime") -> int:
                return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

            return _ticks(idle), _ticks(kernel) + _ticks(user)

        idle0, total0 = _snapshot()
        _time.sleep(max(0.05, float(sample_seconds)))
        idle1, total1 = _snapshot()
        delta_idle, delta_total = idle1 - idle0, total1 - total0
        if delta_total <= 0:
            return None
        return max(0.0, min(100.0, (1.0 - delta_idle / delta_total) * 100.0))
    except Exception:  # noqa: BLE001 —— 探测失败一律当"读不到"，绝不因此中断测试
        return None


def choose_parallel_args(*, serial: bool = False, extra: list[str] | None = None) -> list[str]:
    """按「开始前 CPU 占用」决定要不要并发；用户显式给了 `-n` 就完全听用户的。"""
    for item in (extra or []):
        text = str(item)
        if text == "-n" or text.startswith("--numprocesses"):
            print("      并发：你已显式指定 -n → 沿用你的参数", flush=True)
            return []
    if serial:
        print("      并发：--serial → 单线程", flush=True)
        return []
    try:
        import xdist  # noqa: F401
    except ImportError:
        print("      并发：没装 pytest-xdist → 单线程", flush=True)
        return []
    load = cpu_load_percent()
    if load is None:
        print("      并发：读不到本机 CPU 占用 → 保守走单线程", flush=True)
        return []
    if load < CPU_IDLE_BELOW_PERCENT:
        print(f"      并发：开始前 CPU 占用 {load:.0f}% < {CPU_IDLE_BELOW_PERCENT:.0f}% "
              f"→ 用 -n {PARALLEL_WORKERS}", flush=True)
        return ["-n", str(PARALLEL_WORKERS)]
    print(f"      并发：开始前 CPU 占用 {load:.0f}% ≥ {CPU_IDLE_BELOW_PERCENT:.0f}% "
          f"→ 单线程（不跟本机正在用的东西抢资源）", flush=True)
    return []


def run(targets: list[str], *, attempts: int = 3, extra: list[str] | None = None,
        parallel: list[str] | None = None) -> int:
    """跑 pytest；偶发失败自动重试，返回进程退出码。"""
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", *(parallel or []), *(extra or [])]
    last_output = ""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        last_output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            summary = [ln for ln in last_output.splitlines() if " passed" in ln]
            if attempt > 1:
                print(f"[tests] 第 {attempt} 次通过（前 {attempt - 1} 次是偶发失败）", flush=True)
            print(f"      {summary[-1].strip() if summary else 'pytest ok'}", flush=True)
            return 0
        failed = [ln.strip() for ln in last_output.splitlines() if ln.startswith("FAILED")]
        detail = "；".join(failed[:5]) or "（没解析出 FAILED 行，见下方输出）"
        print(f"      pytest 第 {attempt}/{attempts} 次失败：{detail}", flush=True)
    if attempts > 1:
        print(f"!! 连续 {attempts} 次失败 —— 不是偶发，请照上面的失败行排查", flush=True)
    print(last_output[-4000:], flush=True)
    return 1


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    parser = argparse.ArgumentParser(
        description="跑单元测试（并发按开始前的 CPU 占用决定：<30% 用 4 并发，否则单线程）")
    parser.add_argument("targets", nargs="*", help="要跑的路径（默认 tests/）")
    parser.add_argument("--attempts", type=int, default=3,
                        help="偶发失败的重试上限（默认 3；给 1 表示不重试）")
    parser.add_argument("--serial", action="store_true",
                        help="强制单线程（忽略 CPU 占用检测）")
    args, extra = parser.parse_known_args(argv)

    targets = list(args.targets) or list(DEFAULT_TARGETS)
    parallel = choose_parallel_args(serial=bool(args.serial), extra=extra)
    shown = " ".join([*targets, *parallel, *extra])
    print(f"== 跑测试：{shown} ==", flush=True)
    return run(targets, attempts=max(1, int(args.attempts)), extra=extra, parallel=parallel)


if __name__ == "__main__":
    raise SystemExit(main())
