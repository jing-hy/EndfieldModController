#!/usr/bin/env python
"""跑单元测试 —— 与构建脚本拆开的独立入口（**并发按本机开始前的 CPU 占用决定**）。

    python scripts/run_tests.py                    # 全量（tests/）
    python scripts/run_tests.py tests/test_x.py    # 只跑指定文件/目录
    python scripts/run_tests.py -k 关键字          # 其余参数原样透传给 pytest
    python scripts/run_tests.py --attempts 1       # 不重试
    python scripts/run_tests.py --serial           # 强制单线程（忽略 CPU 占用）
    python scripts/run_tests.py -n 4               # 自己指定并发（透传给 pytest）
    python scripts/run_tests.py --changed          # 只跑与本次改动相关的测试（日常用）

**为什么单独一个脚本**（2026-10-09 用户要求：「本机不做并行构建和测试，你要拆两个脚本出来」）：

* 构建（`build_release.py`）与测试不再挤在同一次调用里 —— 谁都不替谁做主：
  构建不会顺手跑全量测试，本脚本也绝不会去动 `dist\\`。

**并发规则**（2026-10-10 改：**按"要跑多少"决定，CPU 只在小范围时才参与判断**）：

* **全量（测试文件数 > `PARALLEL_MAX_FILES`）⇒ 一律单线程。** 这套测试是**文件 IO 密集**型
  （复制 / 解压 / 扫描真实目录），并行 worker 之间会互相拖 —— 实测（2026-10-10，本机）：
  `-n 4` 跑全量 **18 分钟仍未完成**，单线程约 15 分钟；并行度越高越容易互相干扰导致偶发失败。
  （这条推翻了 2026-10-09 定的"CPU < 30% 就用 4 并发"：当时只看 CPU 占用，而瓶颈其实是磁盘。）
* **小范围**（只跑几个文件）⇒ 这时看 CPU：开始前占用 **< 30%** 才 `-n 4`，否则单线程。
* 读不到占用（非 Windows / API 不可用）⇒ 保守走单线程；没装 `pytest-xdist` ⇒ 自动退回单线程。
* 想固定行为：`--serial` 强制单线程；直接传 `-n <N>` 则**完全听你的**。

**只跑与改动相关的测试**：`python scripts/run_tests.py --changed` —— 按 `git diff` 找出改过的
模块，挑出对应/引用它的测试文件来跑（日常改动用它，几秒到几十秒；全量只在发版时跑）。

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

#: 开始前 CPU 占用**低于**这个百分比 ⇒ 小范围时才上并发（用户 2026-10-09 定的阈值）。
CPU_IDLE_BELOW_PERCENT = 30.0
#: 要跑的测试文件**多于**这个数（≈ 全量）⇒ 一律单线程：这套测试是文件 IO 密集型，
#: 实测（2026-10-10 本机）`-n 4` 跑全量 18 分钟仍未完成，单线程约 15 分钟。
PARALLEL_MAX_FILES = 12
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


def count_target_files(targets: list[str]) -> int:
    """这些目标下有多少个测试文件（用来判断"是不是全量"）。"""
    total = 0
    for item in targets:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        try:
            if path.is_dir():
                total += sum(1 for _ in path.rglob("test_*.py"))
            elif path.is_file():
                total += 1
        except OSError:
            continue
    return total


def choose_parallel_args(*, serial: bool = False, extra: list[str] | None = None,
                         targets: list[str] | None = None) -> list[str]:
    """决定要不要并发：**范围大就单线程**，范围小才看 CPU（用户显式给了 `-n` 就听用户的）。"""
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
    files = count_target_files(list(targets or DEFAULT_TARGETS))
    if files > PARALLEL_MAX_FILES:
        print(f"      并发：这轮要跑 {files} 个测试文件（> {PARALLEL_MAX_FILES}，算全量）"
              f"→ 单线程（实测并行跑全量更慢：IO 密集、worker 互相拖）", flush=True)
        return []
    load = cpu_load_percent()
    if load is None:
        print("      并发：读不到本机 CPU 占用 → 保守走单线程", flush=True)
        return []
    if load < CPU_IDLE_BELOW_PERCENT:
        print(f"      并发：{files} 个文件 + 开始前 CPU 占用 {load:.0f}% "
              f"< {CPU_IDLE_BELOW_PERCENT:.0f}% → 用 -n {PARALLEL_WORKERS}", flush=True)
        return ["-n", str(PARALLEL_WORKERS)]
    print(f"      并发：开始前 CPU 占用 {load:.0f}% ≥ {CPU_IDLE_BELOW_PERCENT:.0f}% "
          f"→ 单线程（不跟本机正在用的东西抢资源）", flush=True)
    return []


def changed_test_targets() -> list[str]:
    """按 `git diff` 找出改动涉及的模块，挑出**相关**测试文件（日常改动用，省掉全量）。

    两条判据并集：
      ① **文件名对应**：`endfieldmodcontroller/launcher.py` ⇒ `tests/test_launcher*.py`；
      ② **内容引用**：测试文件里出现过该模块名（`\blauncher\b`）—— 抓那些名字对不上、
         但确实依赖它的测试（比如 `test_crash_forensics` 会 import `launcher`）。
    前端改动（`frontend/`、`web/dist/`）一律带上 `test_frontend*.py`。
    """
    import re as _re
    import subprocess as _sp

    def git(*args: str) -> str:
        try:
            done = _sp.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
            return done.stdout if done.returncode == 0 else ""
        except OSError:
            return ""

    changed = [ln.strip() for ln in git("diff", "--name-only", "HEAD").splitlines() if ln.strip()]
    if not changed:
        print("      --changed：工作区相对 HEAD 没有改动", flush=True)
        return []

    tests_dir = ROOT / "tests"
    picked: set[str] = set()
    for rel in changed:
        name = Path(rel).name
        if rel.startswith("tests/") and name.startswith("test_"):
            picked.add(rel)                       # 测试自己改了，直接跑它
        if rel.startswith(("frontend/", "web/dist/")):
            picked.update(str(t.relative_to(ROOT)) for t in tests_dir.glob("test_frontend*.py"))
        stem = Path(rel).stem
        if stem and not stem.startswith("test_"):
            picked.update(str(t.relative_to(ROOT)) for t in tests_dir.glob(f"test_{stem}*.py"))
    for rel in changed:
        stem = Path(rel).stem
        if not stem or stem.startswith("test_"):
            continue
        needle = _re.compile(rf"\b{_re.escape(stem)}\b")
        for tf in tests_dir.glob("test_*.py"):
            try:
                if needle.search(tf.read_text(encoding="utf-8", errors="replace")):
                    picked.add(str(tf.relative_to(ROOT)))
            except OSError:
                continue
    return sorted(picked)


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
    parser.add_argument("--changed", action="store_true",
                        help="只跑与 git 改动相关的测试（日常用；发版请跑全量）")
    args, extra = parser.parse_known_args(argv)

    if args.changed:
        targets = changed_test_targets()
        if not targets:
            print("== --changed：没有需要跑的测试 ==", flush=True)
            return 0
        print(f"== --changed：挑出 {len(targets)} 个测试文件 ==", flush=True)
        for item in targets:
            print(f"      {item}", flush=True)
    else:
        targets = list(args.targets) or list(DEFAULT_TARGETS)
    parallel = choose_parallel_args(serial=bool(args.serial), extra=extra, targets=targets)
    shown = " ".join([*targets, *parallel, *extra])
    print(f"== 跑测试：{shown} ==", flush=True)
    return run(targets, attempts=max(1, int(args.attempts)), extra=extra, parallel=parallel)


if __name__ == "__main__":
    raise SystemExit(main())
