"""Run the local self-check and print a concise result summary."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, encoding="utf-8", errors="replace")


def main() -> int:
    print("== EndfieldModController self-check ==")
    tests = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    print(tests.stderr.strip() or tests.stdout.strip())
    if tests.returncode != 0:
        return tests.returncode

    addon = ROOT / "dist" / "endfieldmodcontroller.addon"
    print(f"addon: {addon} ({'ok' if addon.is_file() else 'missing'}, {addon.stat().st_size if addon.is_file() else 0} bytes)")

    release = ROOT / "dist" / "EndfieldModController-0.1.0-portable.zip"
    release_ok = False
    if release.is_file():
        with zipfile.ZipFile(release) as zf:
            names = set(zf.namelist())
            release_ok = any(name.endswith("endfieldmodcontroller/core.py") for name in names) and any(
                name.endswith("dist/endfieldmodcontroller.addon") for name in names
            )
    print(f"release zip: {release} ({'ok' if release_ok else 'missing/incomplete'})")

    cli = run([sys.executable, "-m", "endfieldmodcontroller", "--cli"])
    print("cli --cli exit:", cli.returncode)
    return 0 if addon.is_file() and release_ok and cli.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
