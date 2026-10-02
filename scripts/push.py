"""推送 main 到 GitHub —— **每次推送前先做一次状态快照**。

用户 2026-10-01 的要求：「**你在推送脚本改一下，每次推 github 都要做快照**」。
起因是当天排查一个 bug 时环境被改了多处，之后每一次"还是不行"都不再是同一条件下的
复现；有了快照就能回溯"那一版发布时到底是什么环境"。

行为：
1. **先跑 `scripts/snapshot.py`**（带版本号标签）—— **快照失败就不推**（用户要的是"每次都要做"）；
2. 读本机**用户级**环境变量 `GH_TOKEN`（本机 git 凭据助手不可用，推 HTTPS 必须带它；
   进程环境里没有就去注册表 `HKCU\\Environment` 里取 —— 与 `gh-token-pr` 技能里的做法一致）；
3. `git push https://<token>@github.com/<repo>.git <local>:<remote>`；
4. 打印**推送前后**的本地/远端 hash 以便核对（**token 在输出里一律打码**）。

**只推 main，不会建 Release** —— 发 Release 要用户明确说了才做（那是另一条流程：
`prepare_release.py` → `upload_release_assets.py` → `gh release edit --latest`）。

用法：
    python scripts/push.py                 # 快照 + 推 main
    python scripts/push.py --dry-run       # 只看会发生什么（不推）
    python scripts/push.py --skip-snapshot # 例外情况：跳过快照（不推荐）
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_version import report as report_version_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = "jing-hy/EndfieldModController"
ENV_NAME = "GH_TOKEN"


def get_token() -> str:
    """取 GH_TOKEN：先看进程环境，再读用户级环境变量（注册表）。"""
    import os

    tok = os.environ.get(ENV_NAME, "").strip()
    if tok:
        return tok
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, ENV_NAME)
            return str(value).strip()
    except (ImportError, OSError):
        return ""


def mask(token: str) -> str:
    return f"{token[:4]}…{token[-4:]}" if len(token) > 12 else "****"


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def local_version() -> str:
    path = ROOT / "endfieldmodcontroller" / "version.py"
    if not path.is_file():
        return ""
    m = re.search(r'__version__\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def _fix_console() -> None:
    """Windows 下控制台/管道默认是 GBK —— 快照输出里只要有一个非 GBK 字符（Mod 名里的
    生僻字、文件名里的替换字符 U+FFFD 等），`print` 就会抛 `UnicodeEncodeError` 把**整个
    推送**打断（2026-10-02 实测：崩在"打印快照输出"这一步，推送根本没发出去）。
    同 `prepare_release.py` 的做法：把两个流改成 utf-8 + errors=replace。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="快照 + 推 main 到 GitHub")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不真的推")
    ap.add_argument("--skip-snapshot", action="store_true", help="跳过快照（不推荐）")
    ap.add_argument("--branch", default="main", help="推哪个分支（默认 main）")
    args = ap.parse_args(argv)

    _fix_console()
    version = local_version()
    print(f"== 推送 {REPO} {args.branch} ==  版本 {version or '(未知)'}", flush=True)
    # 版本号规则核对（用户 2026-10-02）：**推 main ≠ 发 Release** —— 只推源码时版本号不用改，
    # 保持在「最新 Release + 1」；只有发过 Release 之后才轮到下一个号。
    report_version_rule()
    print("      推 main ≠ 发 Release：本次只更新源码，下载页 / Latest 不变 —— 版本号保持不动", flush=True)

    # ① 快照（**失败就不推**）
    if args.skip_snapshot:
        print("[1/3] 快照：已跳过（--skip-snapshot）", flush=True)
    else:
        print("[1/3] 快照（推之前必备，出问题时可回溯环境）…", flush=True)
        snap = subprocess.run([sys.executable, str(ROOT / "scripts" / "snapshot.py"),
                               "--label", version or "manual"],
                              cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        out = (snap.stdout or "") + (snap.stderr or "")
        for line in out.strip().splitlines():
            print("      " + line, flush=True)
        if snap.returncode != 0:
            print("      !! 快照失败 —— 按约定中止推送（修好快照，或用 --skip-snapshot 显式跳过）", flush=True)
            return 1

    # ② 准备 token 与命令
    token = get_token()
    if not token:
        print("      !! 找不到 GH_TOKEN（进程环境与 HKCU\\Environment 都没有）—— 无法推送", flush=True)
        return 1
    url = f"https://{token}@github.com/{REPO}.git"
    print(f"[2/3] 远端：https://github.com/{REPO}.git  （token {mask(token)}）", flush=True)

    before_local = git("rev-parse", args.branch).stdout.strip()
    ahead = git("rev-list", "--count", f"origin/{args.branch}..{args.branch}").stdout.strip()
    print(f"      本地 {args.branch} = {before_local[:12]}   领先 origin  {ahead or '?'} 个提交", flush=True)

    if args.dry_run:
        print("[3/3] --dry-run：不执行 git push", flush=True)
        return 0

    # ③ 推
    print(f"[3/3] git push {args.branch}:{args.branch} …", flush=True)
    res = subprocess.run(["git", "push", url, f"{args.branch}:{args.branch}"], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in ((res.stdout or "") + (res.stderr or "")).strip().splitlines():
        print("      " + line.replace(token, "****"), flush=True)
    if res.returncode != 0:
        print("      !! 推送失败", flush=True)
        return res.returncode

    git("fetch", "origin", "--quiet")
    after_remote = git("rev-parse", f"origin/{args.branch}").stdout.strip()
    print(f"      完成：远端 {args.branch} = {after_remote[:12]}（本地 {before_local[:12]}）"
          f"{'  ✓ 一致' if after_remote == before_local else '  ⚠ 不一致，请核对'}", flush=True)
    print("      注意：**只推了 main，没有发 Release** —— 要发版请明确说了再走 "
          "prepare_release.py → upload_release_assets.py。", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
