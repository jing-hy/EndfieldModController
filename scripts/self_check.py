"""Run the local self-check and print a concise result summary."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, encoding="utf-8", errors="replace")


def main() -> int:
    # 测试输出里可能含无法用 GBK 编码的字符（子进程用 errors="replace" 捕获），
    # 在中文 Windows 控制台上直接 print 会 UnicodeEncodeError（2026-10-01 实测踩到）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    print("== EndfieldModController self-check ==")
    # ⚠️ 用 **pytest** 而不是 `unittest discover`（2026-10-04 修）：本项目 658 个用例里
    # 绝大多数是 pytest 风格的**模块级 `def test_*`**（还带 49 个 subTest），
    # `unittest discover` **只收集 TestCase 子类** ⇒ 这个自检给出的"通过"是偏乐观的
    # （和构建入口 build_release 跑的不是一套）。两个入口必须跑同一套测试。
    tests = run([sys.executable, "-m", "pytest", "tests", "-q"])
    print(tests.stderr.strip() or tests.stdout.strip())
    if tests.returncode != 0:
        return tests.returncode

    # ⚠️ addon 的实际产物名是 `EndfieldModController.addon` / `*.addon64`（大写），
    # 原来硬写小写，只靠 Windows 不区分大小写才通过（换到任何大小写敏感的环境就误报 missing）。
    dist = ROOT / "dist"
    addons = sorted(p for p in dist.glob("*.addon*")) if dist.is_dir() else []
    addon = addons[0] if addons else (dist / "EndfieldModController.addon")
    print(f"addon: {addon} ({'ok' if addon.is_file() else 'missing'}, {addon.stat().st_size if addon.is_file() else 0} bytes)")

    # 发行形态只有单文件 exe（用户 2026-10-01：「我从来没做过便携版，不用做」），
    # 所以这里检查 dist 里的 exe，而不再去找早已废弃、还硬编码了 0.1.0 的 portable zip。
    exe = ROOT / "dist" / "EndfieldModController.exe"
    exe_ok = exe.is_file() and exe.stat().st_size > 1024 * 1024
    print(f"exe: {exe} ({'ok' if exe_ok else 'missing/too small'}, {exe.stat().st_size if exe.is_file() else 0} bytes)")

    cli = run([sys.executable, "-m", "endfieldmodcontroller", "--cli"])
    print("cli --cli exit:", cli.returncode)
    return 0 if addon.is_file() and exe_ok and cli.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
