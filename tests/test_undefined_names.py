"""抓「引用了不存在的名字」这类 bug —— 用 **pyflakes**（2026-10-03 实测抓到 3 个真 bug）。

**事故回顾**：`fastnet.py` 里 `CHUNK_GAP_SECONDS` 被引用 4 处，而常量**从来不存在**
（真名 `STALL_SECONDS = 20`）。后果：并行下载一启动就在 `fetch()` 里抛 `NameError`
⇒ 线程当场死 ⇒ 日志写着「用 20 连接补齐剩余」，实际**一条连接都没在下**、
一个字节都没进来 ⇒ 用户看到的正是"进度条不动、速度横杠"。

**为什么现有测试没抓到**：它是**运行时**才炸的 `NameError`，而测试没走到那条分支。
`compile()` 也查不出来（语法是对的）。

**防线**：对整个包跑 `pyflakes`，**只要出现 `undefined name` 就失败**。
（其它类别 —— unused import / local variable assigned but never used —— 只警告不阻断，
因为项目里存量很多，一次全清风险大；但 `undefined name` 是**一定会炸**的，零容忍。）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "endfieldmodcontroller"


def _pyflakes_report(target: Path) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", str(target)],
        capture_output=True, text=True,
    )
    return (proc.stdout or "") + (proc.stderr or "")


def test_pyflakes_is_available() -> None:
    """pyflakes 必须可用 —— 否则这条防线是摆设（`requirements.txt` 里已声明）。"""
    proc = subprocess.run([sys.executable, "-m", "pyflakes", "--version"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, "缺 pyflakes：pip install pyflakes"


def test_no_undefined_names_in_package() -> None:
    """★ 整个包里**不许有任何 `undefined name`**（这次的 `CHUNK_GAP_SECONDS` 就是这类）。"""
    report = _pyflakes_report(PKG)
    bad = [line.strip() for line in report.splitlines() if "undefined name" in line]
    assert not bad, "引用了不存在的名字（运行时必炸）：\n  " + "\n  ".join(bad)


def test_checker_would_catch_the_real_bug(tmp_path: Path) -> None:
    """自检：这个防线**确实能**抓出 `CHUNK_GAP_SECONDS` 那种写法（否则它是摆设）。"""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "STALL_SECONDS = 20\n"
        "def f():\n"
        "    return CHUNK_GAP_SECONDS\n",
        encoding="utf-8",
    )
    report = _pyflakes_report(sample)
    assert "undefined name 'CHUNK_GAP_SECONDS'" in report
