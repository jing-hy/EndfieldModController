"""发布流程固化：备齐 Release 附件、打印上传指引（**绝不自动上传**）。

用法：
    python scripts/prepare_release.py

做的事：
    1) 校验 `dist\\` 里的 exe 是"当前版本构建出来的"（用同名带版本号副本判断）——
       不是就先跑 `python scripts/build_release.py`；
    2) 生成/刷新 `dist\\assets-bundle.zip`（+ `.sha256`）；
    3) 打印两个附件的名称、大小、sha256；
    4) 打印现成的 `gh release create` 命令 —— **由你自己决定何时执行**。

发布规则（用户 2026-10-01 定）：
    * Release 只上传**不带版本号的** `EndfieldModController.exe`；带版本号副本与伪旧版只留本地；
    * 这条规则**只约束 exe**，`assets-bundle.zip` 照常上传（exe 版靠它获取随包资产）；
    * 不做便携版。
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_version import report as report_version_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION_PY = ROOT / "endfieldmodcontroller" / "version.py"
APP_NAME = "EndfieldModController"
REPO = "jing-hy/EndfieldModController"


def _fix_console() -> None:
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


def main() -> int:
    _fix_console()
    version = read_version()
    print(f"== 准备 v{version} 的发布附件 ==", flush=True)
    # 版本号规则核对（用户 2026-10-02）：本地应为「最新 Release + 1」；只推源码没发 Release 时不动号。
    report_version_rule()

    exe = DIST / f"{APP_NAME}.exe"
    versioned = DIST / f"{APP_NAME}-{version}.exe"
    problems: list[str] = []
    if not exe.is_file():
        problems.append(f"缺少 {exe}")
    if not versioned.is_file():
        problems.append(f"缺少 {versioned}（说明 dist 里的 exe 不是当前版本构建的）")
    if problems:
        print("!! 先完成构建：", flush=True)
        for item in problems:
            print(f"   - {item}", flush=True)
        print("\n   请先运行：python scripts/build_release.py", flush=True)
        return 1

    print("[1/3] 生成随包资产包", flush=True)
    result = subprocess.run([sys.executable, "scripts/build_assets_bundle.py"], cwd=str(ROOT))
    if result.returncode != 0:
        print("!! 资产包生成失败", flush=True)
        return result.returncode

    bundle = DIST / "assets-bundle.zip"
    print("\n[2/3] 本次要上传的附件（Release 只放这两个）", flush=True)
    for item in (exe, bundle):
        if item.is_file():
            print(f"   {item.name}  {item.stat().st_size:,} B", flush=True)
            print(f"     sha256 {sha256_of(item)}", flush=True)
        else:
            print(f"   !! 缺失 {item}", flush=True)
    print("\n   不上传（仅本地留档）：", flush=True)
    for item in (versioned, DIST / f"{APP_NAME}-0.1.9-from-{version}.exe"):
        print(f"   {item.name}{'' if item.is_file() else '（不存在）'}", flush=True)

    tag = f"v{version}"
    print("\n[3/3] 上传指引（我没有替你上传，命令供你确认后自己执行）", flush=True)
    print(f"""
   gh release create {tag} ^
     "dist\\{exe.name}" "dist\\{bundle.name}" ^
     --repo {REPO} ^
     --title "{tag}" ^
     --notes "（把这一版的更新说明填在这里，或用 --notes-file RELEASE_NOTES.md）"

   提醒：
     * 版本号规则 = **只跟"最新 Release"比**、本地领先它一个；只推了源码没发 Release 时**不改号**；
     * 伪旧版（0.1.9-from-{version}）与带版本号副本**不要**上传；
     * 上传前建议先核对 sha256 与上面的值一致。
""", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
