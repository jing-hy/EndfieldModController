"""构建流程的唯一入口：静态检查 → 构建最新版 → 带版本号副本 → 伪旧版 → 归置旧版。

用法：
    python scripts/build_release.py                  # 正常构建（推荐）
    python scripts/build_release.py --skip-checks    # 跳过静态检查（只在明确知道原因时用）

产出（全部在 `dist\\`）：

    EndfieldModController.exe                      最新版（唯一发行的 exe）
    EndfieldModController-<版本>.exe               带版本号副本（本地留档，不上传）
    EndfieldModController-0.1.9-from-<版本>.exe    伪旧版（版本号 0.1.9、代码最新，用于测自更新）
    _old\\                                         上一代及更早的带版本号副本（自动归置）

静态检查（任一失败即中止，**不会**产出半成品）：

    1) 所有 Python 模块 py_compile
    2) `node --check web/app.js`（node 不在 PATH 时跳过并提示）
    3) `python -m pytest tests -q`（必须指定 tests 目录，否则会被 `_tmp\\` 污染）

发布（上传）不在本脚本里 —— 见 `scripts/prepare_release.py`。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
OLD_DIR = DIST / "_old"
VERSION_PY = ROOT / "endfieldmodcontroller" / "version.py"
APP_NAME = "EndfieldModController"
FAKE_VERSION = "0.1.9"


def _fix_console() -> None:
    """中文 Windows 控制台默认 GBK，直接 print 项目里的中文/特殊字符会崩。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_version() -> str:
    match = re.search(r'__version__ = "([^"]+)"', VERSION_PY.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("!! version.py 里找不到 __version__")
    return match.group(1)


def run(cmd: list[str], *, label: str) -> None:
    print(f"[build] {label} …", flush=True)
    started = time.time()
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"!! {label} 失败（exit {result.returncode}），已中止，未产出任何产物")
    print(f"[build] {label} 完成（{time.time() - started:.1f}s）", flush=True)


def static_checks() -> None:
    print("[1/6] 静态检查", flush=True)
    # ① Python 语法/编译
    modules = sorted((ROOT / "endfieldmodcontroller").glob("*.py"))
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", *[str(p) for p in modules]],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"!! py_compile 失败：\n{result.stderr.strip()[:2000]}")
    print(f"      py_compile ok（{len(modules)} 个模块）", flush=True)

    # ② 前端语法
    node = shutil.which("node")
    app_js = ROOT / "web" / "app.js"
    if node and app_js.is_file():
        result = subprocess.run([node, "--check", str(app_js)], cwd=str(ROOT),
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"!! node --check 失败：\n{result.stderr.strip()[:2000]}")
        print("      node --check ok（web/app.js）", flush=True)
    else:
        print("      （跳过 node --check：PATH 里没有 node）", flush=True)

    # ③ 单元测试（必须指定 tests 目录）
    run([sys.executable, "-m", "pytest", "tests", "-q"], label="pytest tests -q")


def archive_old_exes(version: str) -> list[str]:
    """把 dist 里**非当前版本**的带版本号副本挪到 `_old\\`；旧伪旧版直接删。

    用户 2026-10-01 的规则：历史版本在下一版构建后归到单独目录；伪旧版"上一代用完就删"。
    """
    moved: list[str] = []
    OLD_DIR.mkdir(parents=True, exist_ok=True)
    keep = {f"{APP_NAME}.exe", f"{APP_NAME}-{version}.exe",
            f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"}
    for item in sorted(DIST.glob(f"{APP_NAME}*.exe")):
        if item.name in keep:
            continue
        if f"-{FAKE_VERSION}-from-" in item.name:
            item.unlink()
            print(f"      删除上一代伪旧版：{item.name}", flush=True)
            continue
        target = OLD_DIR / item.name
        if target.exists():
            target.unlink()
        shutil.move(str(item), str(target))
        moved.append(item.name)
        print(f"      归置旧版本：{item.name} → _old\\", flush=True)
    return moved


def clean_dist_extras() -> None:
    """让 `dist\\` 只留构建产物：清掉"跑过 exe 留下的运行数据"和 onedir 残留。

    用户 2026-10-01 要求「只留构建产物」。这些都属于可再生成的运行数据：
    `config.json` / `runtime\\` / `library\\` 是 exe 在 dist 里启动时自己建的，
    `EndfieldModController\\` 是早期 `--onedir` 构建的残留目录（与 exe 同名）。
    """
    removed: list[str] = []
    onedir = DIST / APP_NAME
    if onedir.is_dir():
        shutil.rmtree(onedir, ignore_errors=True)
        removed.append(f"{APP_NAME}\\（onedir 残留）")
    for name in ("config.json", "library", "runtime"):
        target = DIST / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(f"{name}\\")
        elif target.is_file():
            target.unlink()
            removed.append(name)
    for item in removed:
        print(f"      清理非构建产物：{item}", flush=True)
    if not removed:
        print("      dist 里没有多余东西", flush=True)


def build_fake_old(version: str) -> None:
    """临时把版本号改成 0.1.9 构建一次，产出伪旧版（版本号旧、代码最新）。"""
    original = VERSION_PY.read_text(encoding="utf-8")
    VERSION_PY.write_text(original.replace(f'__version__ = "{version}"', f'__version__ = "{FAKE_VERSION}"'),
                          encoding="utf-8", newline="\n")
    try:
        run([sys.executable, "scripts/build_exe.py"], label=f"构建伪旧版（{FAKE_VERSION}）")
    finally:
        VERSION_PY.write_text(original, encoding="utf-8", newline="\n")
        restored = read_version()
        print(f"      version.py 已还原为 {restored}", flush=True)
        if restored != version:
            raise SystemExit(f"!! version.py 还原异常：期望 {version}，实际 {restored}")

    built = DIST / f"{APP_NAME}.exe"
    name = f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"
    target = DIST / name
    shutil.move(str(built), str(target))
    shutil.copy2(target, ROOT / name)
    print(f"      伪旧版：dist\\{name} + 根目录同名副本", flush=True)


def main() -> int:
    _fix_console()
    args = sys.argv[1:]
    version = read_version()
    print(f"== 构建 EndfieldModController {version} ==", flush=True)
    if "--skip-checks" not in args:
        static_checks()
    else:
        print("[1/6] 已按参数跳过静态检查", flush=True)

    print("[2/6] 归置历史产物（旧版 → dist\\_old）+ 清理非构建产物", flush=True)
    archive_old_exes(version)
    clean_dist_extras()

    print("[3/6] 构建最新版", flush=True)
    run([sys.executable, "scripts/build_exe.py"], label="构建最新版")
    latest = DIST / f"{APP_NAME}.exe"
    if not latest.is_file():
        raise SystemExit("!! 没找到 dist/EndfieldModController.exe")
    versioned = DIST / f"{APP_NAME}-{version}.exe"
    shutil.copy2(latest, versioned)

    print("[4/6] 构建伪旧版", flush=True)
    build_fake_old(version)

    print("[5/6] 把最新版放回 dist\\EndfieldModController.exe", flush=True)
    shutil.copy2(versioned, latest)

    print("[6/6] 产物清单", flush=True)
    for item in (latest, versioned, DIST / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe",
                 ROOT / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"):
        if item.is_file():
            stamp = time.strftime("%H:%M:%S", time.localtime(item.stat().st_mtime))
            print(f"      {item}  {item.stat().st_size:,} B  {stamp}", flush=True)
            print(f"          sha256={sha256_of(item)[:20]}…", flush=True)
        else:
            print(f"      !! 缺失 {item}", flush=True)
    if OLD_DIR.is_dir():
        olds = sorted(p.name for p in OLD_DIR.glob("*.exe"))
        if olds:
            print(f"      dist\\_old 已归置：{', '.join(olds)}", flush=True)
    print("\n下一步：要发布就跑 `python scripts/prepare_release.py`（备齐附件并打印上传指引）。", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
