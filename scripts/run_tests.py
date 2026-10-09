#!/usr/bin/env python
"""跑单元测试 —— **单线程、不并行**，与构建脚本拆开的独立入口。

    python scripts/run_tests.py                    # 全量（tests/）
    python scripts/run_tests.py tests/test_x.py    # 只跑指定文件/目录
    python scripts/run_tests.py -k 关键字          # 其余参数原样透传给 pytest
    python scripts/run_tests.py --attempts 1       # 不重试

**为什么单独一个脚本**（2026-10-09 用户要求：「本机不做并行构建和测试，你要拆两个脚本出来」）：

* 构建（`build_release.py`）与测试不再挤在同一次调用里 —— 谁都不替谁做主：
  构建不会顺手跑全量测试，本脚本也绝不会去动 `dist\\`。
* 本脚本一律**单线程**跑，不再用 `-n 4`：这套测试有大量真实文件 IO（复制 / 解压 / 扫描真实
  目录），多个 worker 之间会互相拖，也更容易出现互相干扰导致的偶发失败
  （构建脚本因此白跑重试）。实测单线程 15 秒上下，在本机代价可以接受。

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


def _fix_console() -> None:
    """中文 Windows 控制台默认 GBK —— 直接 print 项目里的中文/特殊字符会崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def run(targets: list[str], *, attempts: int = 3, extra: list[str] | None = None) -> int:
    """跑 pytest；偶发失败自动重试，返回进程退出码。"""
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", *(extra or [])]
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
    parser = argparse.ArgumentParser(description="跑单元测试（单线程、不并行）")
    parser.add_argument("targets", nargs="*", help="要跑的路径（默认 tests/）")
    parser.add_argument("--attempts", type=int, default=3,
                        help="偶发失败的重试上限（默认 3；给 1 表示不重试）")
    args, extra = parser.parse_known_args(argv)

    targets = list(args.targets) or list(DEFAULT_TARGETS)
    shown = " ".join([*targets, *extra])
    print(f"== 跑测试（单线程）：{shown} ==", flush=True)
    return run(targets, attempts=max(1, int(args.attempts)), extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
