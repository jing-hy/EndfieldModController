# SPDX-License-Identifier: GPL-3.0-or-later
r"""**有没有控制器实例在跑？** —— 一个命令给出可核对的答案（2026-11-07）。

为什么需要它：我（AI）以前判断"实例在不在"只跑
    Get-Process -Name EndfieldModController
—— 这有两个坑，都真实踩过：
  ① **源码方式启动**（pythonw run.py / run.bat）时进程名是 pythonw.exe，名字对不上，
     于是"明明开着"被判成"没开"；反过来，一个同名僵尸/别人的 exe 也会被当成我们的；
  ② **只看进程名不看占用**：真正决定"能不能替换 exe / 清理目录"的是
     **exe 文件有没有被独占占用**，跟进程名无关。

现在的判据是四条**独立证据**（任一条成立就按"在跑"处理）：
  1. **窗口**：EnumWindows 里标题以 EndfieldModController 开头的可见窗口
     （exe 与源码两种启动方式标题一样，这条最不容易骗人）；
  2. **进程**：tasklist 里名字是 EndfieldModController.exe 的；
  3. **锁文件**：<数据根>\runtime\.mc.lock 里那个 PID 活着**且**进程指纹
     （exe 路径 + 创建时间）对得上 —— 光 PID 活着不算（PID 会被复用）；
  4. **占用**：dist\ 与 modtest\ 的 exe 能否独占打开（不能 = 被某个进程占着）。

用法：
    python scripts\who_is_running.py            # 人看
    python scripts\who_is_running.py --json     # 机器读
退出码：0 = 没在跑；1 = 在跑（或某些证据说不清）；2 = 检查本身出错。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from endfieldmodcontroller import app as appmod  # noqa: E402

EXE_NAME = "EndfieldModController.exe"
# 可能的数据根（锁文件都在 <数据根>\runtime\.mc.lock）
# ⚠️ 测试副本 `modtest` 在**工作区**下（D:\zmdmod\modtest），不是仓库子目录 ——
#    这里踩过一次：写成 ROOT / "modtest" 就永远查不到那份锁和 exe。
DATA_ROOTS = (ROOT, ROOT.parent / "modtest", ROOT / "dist")


def _named_processes() -> list[dict]:
    """tasklist 里叫 EndfieldModController.exe 的进程（带 PID）。"""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[dict] = []
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) < 2 or EXE_NAME.lower() not in parts[0].lower():
            continue
        try:
            rows.append({"pid": int(parts[1]), "image": parts[0]})
        except (TypeError, ValueError):
            continue
    return rows


def _lock_verdict(lock: Path) -> dict:
    """这把锁说明什么：不存在 / 陈旧 / 真的有人在持有。"""
    if not lock.is_file():
        return {"path": str(lock), "state": "missing"}
    info = appmod._read_lock(lock)
    pid = int(info.get("pid") or 0)
    if not pid:
        return {"path": str(lock), "state": "broken", "raw": str(info)[:80]}
    if not appmod._pid_alive(pid):
        return {"path": str(lock), "state": "stale", "pid": pid, "reason": "PID 已退出"}
    recorded = str(info.get("fp") or "")
    current = appmod._process_fingerprint(pid)
    if recorded and current and recorded == current:
        return {"path": str(lock), "state": "held", "pid": pid}
    return {"path": str(lock), "state": "pid-reused", "pid": pid,
            "reason": "PID 活着但不是写锁的那个进程（PID 被复用）"}


def _exe_replaceable(path: Path) -> dict:
    """这个 exe 现在能不能被替换（独占打开成功 = 没被占用）。"""
    if not path.is_file():
        return {"path": str(path), "exists": False}
    try:
        with open(path, "r+b"):
            pass
        return {"path": str(path), "exists": True, "replaceable": True}
    except OSError as exc:
        return {"path": str(path), "exists": True, "replaceable": False,
                "error": f"{type(exc).__name__}: {exc}"}


def judge(evidence: dict) -> tuple[bool, list[str]]:
    """把四类证据汇总成一个判定（纯函数，方便测试）。"""
    reasons: list[str] = []
    for title in evidence.get("windows") or []:
        reasons.append(f"屏幕上有窗口：{title}")
    for row in evidence.get("named_processes") or []:
        reasons.append(f"进程 {row.get('image')} 在跑（PID {row.get('pid')}）")
    for lock in evidence.get("locks") or []:
        if lock.get("state") == "held":
            reasons.append(f"锁被持有：{lock.get('path')}（PID {lock.get('pid')}）")
    running = bool(reasons)
    # 锁陈旧/被复用时**不算在跑**，但要说明（避免下次又误判成"有实例"）
    notes: list[str] = []
    for lock in evidence.get("locks") or []:
        if lock.get("state") in ("stale", "pid-reused", "broken"):
            notes.append(f"{lock.get('path')} 是陈旧锁（{lock.get('reason') or lock.get('state')}）")
    for row in evidence.get("exe") or []:
        if row.get("exists") and row.get("replaceable") is False:
            notes.append(f"{row.get('path')} 被占用，但没找到我们的进程/窗口 —— 先查是谁占着")
    return running, reasons + notes


def collect() -> dict:
    windows = []
    try:
        windows = [f"hwnd {hwnd}" for hwnd in appmod._our_windows()]
    except Exception:  # noqa: BLE001
        windows = []
    locks = [_lock_verdict(root / "runtime" / ".mc.lock") for root in DATA_ROOTS]
    exe = [_exe_replaceable(root / EXE_NAME) for root in (ROOT / "dist", ROOT.parent / "modtest")]
    return {
        "windows": windows,
        "named_processes": _named_processes(),
        "locks": locks,
        "exe": exe,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查是否有 EndfieldModController 实例在跑")
    parser.add_argument("--json", action="store_true", help="输出 JSON（给脚本/Agent 读）")
    args = parser.parse_args()
    try:
        evidence = collect()
    except Exception as exc:  # noqa: BLE001
        print(f"!! 检查失败：{type(exc).__name__}: {exc}")
        return 2
    running, reasons = judge(evidence)
    if args.json:
        print(json.dumps({"running": running, "reasons": reasons, **evidence},
                         ensure_ascii=False, indent=2))
        return 1 if running else 0
    print("== 实例检查 ==")
    print(f"窗口      : {evidence['windows'] or '无'}")
    print(f"同名进程  : {evidence['named_processes'] or '无'}")
    for lock in evidence["locks"]:
        print(f"锁        : {lock['path']} → {lock['state']}"
              + (f"（{lock.get('reason')}）" if lock.get("reason") else ""))
    for row in evidence["exe"]:
        if not row.get("exists"):
            print(f"exe       : {row['path']} 不存在")
        else:
            print(f"exe       : {row['path']} → "
                  + ("可替换" if row.get("replaceable") else "被占用！"))
    print("----------")
    if running:
        print("结论：**有实例在跑** → 先关掉再替换 exe / 清理目录")
        for reason in reasons:
            print("  · " + reason)
        return 1
    print("结论：**没有实例在跑**（窗口 / 同名进程 / 锁 / 占用 四条证据都不成立）")
    for note in reasons:
        print("  · 提示：" + note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
