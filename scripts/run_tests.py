#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
"""跑单元测试 —— 与构建脚本拆开的独立入口（**一律串行**）。

    python scripts/run_tests.py                    # 全量（tests/）
    python scripts/run_tests.py tests/test_x.py    # 只跑指定文件/目录
    python scripts/run_tests.py -k 关键字          # 其余参数原样透传给 pytest
    python scripts/run_tests.py --attempts 1       # 不重试
    python scripts/run_tests.py --changed          # 只跑与本次改动相关的测试（日常用）

**为什么单独一个脚本**（2026-10-09 用户要求：「本机不做并行构建和测试，你要拆两个脚本出来」）：

* 构建（`build_release.py`）与测试不再挤在同一次调用里 —— 谁都不替谁做主：
  构建不会顺手跑全量测试，本脚本也绝不会去动 `dist\\`。

**并发规则（2026-10-12 用户拍板：「以后构建测试都用串行」）**：

* **一律单线程**，不采 CPU 占用、也不看"要跑多少" —— 之前那套「全量单线程 / 小范围 CPU < 30%
  才上 `-n 4`」的判断**整段删除**。两个理由都还在，只是结论改成"永远别并发"：
  ① 这套测试是**文件 IO 密集型**（复制 / 解压 / 扫描真实目录），并行 worker 互相拖
  （实测 2026-10-10：`-n 4` 跑全量 18 分钟仍未完成，串行约 15 分钟）；
  ② xdist 是**多进程**，跨进程共享状态会带来随机失败（`runtime\\_net\\lines.json` 这类缓存被
  多个 worker 交叉读写，表现为"随机翻、每次挂的方法还不一样"）。
* 真想强行并发（不推荐）：自己传 `-n N`（脚本原样透传给 pytest，不做拦截）。

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


def _fix_console() -> None:
    """中文 Windows 控制台默认 GBK —— 直接 print 项目里的中文/特殊字符会崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def wants_parallel(extra: list[str]) -> bool:
    """用户是不是显式要求并发（`-n` / `--numprocesses`）—— 一律串行的唯一例外。"""
    for item in extra:
        text = str(item)
        if text == "-n" or text.startswith("--numprocesses"):
            return True
    return False


def changed_test_targets() -> list[str]:
    """按 `git diff` 找出改动涉及的模块，挑出**相关**测试文件（日常改动用，省掉全量）。

    两条判据并集：
      ① **文件名对应**：`endfieldmodcontroller/launcher.py` ⇒ `tests/test_launcher*.py`；
      ② **内容引用**：测试文件里出现过该模块名（`\\blauncher\\b`）—— 抓那些名字对不上、
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


def run(targets: list[str], *, attempts: int = 3, extra: list[str] | None = None) -> int:
    """跑 pytest（**串行**，除非用户自己传了 `-n`）；偶发失败自动重试，返回进程退出码。"""
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
    parser = argparse.ArgumentParser(description="跑单元测试（一律串行，不并发）")
    parser.add_argument("targets", nargs="*", help="要跑的路径（默认 tests/）")
    parser.add_argument("--attempts", type=int, default=3,
                        help="偶发失败的重试上限（默认 3；给 1 表示不重试）")
    parser.add_argument("--serial", action="store_true",
                        help="（现在默认就是串行；此开关为兼容旧命令保留）")
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

    if wants_parallel(extra):
        print("      并发：⚠️ 你显式传了 -n/--numprocesses —— 按你的参数跑（**不推荐**："
              "这套测试是 IO 密集型，多进程还会因共享缓存出现随机失败）", flush=True)
    else:
        print("      并发：串行（用户 2026-10-12：「以后构建测试都用串行」）", flush=True)
    print(f"== 跑测试：{' '.join([*targets, *extra])} ==", flush=True)
    return run(targets, attempts=max(1, int(args.attempts)), extra=extra)


if __name__ == "__main__":
    raise SystemExit(main())
