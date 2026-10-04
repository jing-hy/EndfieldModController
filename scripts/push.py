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
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_version import report as report_version_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = "jing-hy/EndfieldModController"
ENV_NAME = "GH_TOKEN"


def _latest_snapshot_dir(output: str) -> Path | None:
    """从 `snapshot.py` 的输出里解析出这次快照的目录（它最后会打印 `SNAPSHOT=<路径>`）。"""
    for line in reversed(str(output or "").splitlines()):
        text = line.strip()
        if text.startswith("SNAPSHOT="):
            candidate = Path(text.split("=", 1)[1].strip())
            return candidate if candidate.is_dir() else None
    return None


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


def _refresh_memory_log(version: str, *, dry_run: bool = False) -> None:
    """导出「记忆日志」并**单独提交**这一个文件（用户 2026-10-03 的要求）。

    原话：「还有 dsh 的记忆也一起上传源码」→「每次传源码记忆都一起」→
    「**或者不传记忆但是需要一个类似记忆的日志，每次上传**」。
    也就是说：**不要把 `memory.db` 本身推上去**（二进制、夹着本机路径与第三方反馈者的设备信息），
    而是每次推送时刷新一份**可读、可 diff** 的 `docs/AI-记忆日志.md`。

    三条安全约定：
    * 生成失败 / 没有记忆库（别人 clone 下来跑）⇒ 只提示，**绝不阻断推送**；
    * 用 `git commit -- <该文件>` 提交 —— **只动这一个文件**，不碰工作区里其它未提交的改动，
      也不清空别人已暂存的内容；
    * `--dry-run` 时只生成、不提交。
    """
    script = ROOT / "scripts" / "memory_log.py"
    target = ROOT / "docs" / "AI-记忆日志.md"
    if not script.is_file():
        print("      没有 scripts/memory_log.py —— 跳过", flush=True)
        return
    run = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    for line in ((run.stdout or "") + (run.stderr or "")).strip().splitlines():
        print("      " + line, flush=True)
    if run.returncode != 0 or not target.is_file():
        print("      !! 记忆日志没生成 —— 跳过（不影响推送）", flush=True)
        return
    if dry_run:
        print("      --dry-run：只生成，不提交", flush=True)
        return
    rel = str(target.relative_to(ROOT))
    changed = git("status", "--porcelain", "--", rel).stdout.strip()
    if not changed:
        print("      记忆日志无变化，无需提交", flush=True)
        return
    # ⚠️ 它是**未跟踪的新文件**时，`git commit -- <路径>` 是不认的，必须先 add
    git("add", "--", rel)
    commit = git("commit", "-m", f"记忆日志：随 {version or 'main'} 自动刷新", "--", rel)
    out = ((commit.stdout or "") + (commit.stderr or "")).strip().splitlines()
    for line in out[-3:]:
        print("      " + line, flush=True)
    if commit.returncode != 0:
        print("      !! 记忆日志提交失败（不影响推送，下次会再试）", flush=True)


def _refresh_structure(version: str, *, dry_run: bool = False) -> None:
    """把 normify 结构树同步进 `docs/structure/` 并单独提交（用户 2026-10-03：「结构树也一起上传」）。

    结构数据平时落在 dsh 的 profile 目录（不进 git）；这里每次推送前整份镜像到仓库，
    别人 clone 下来能直接看架构图、也能跟着源码 diff。同步失败同样**不阻断推送**。
    """
    script = ROOT / "scripts" / "sync_structure.py"
    if not script.is_file():
        print("      没有 scripts/sync_structure.py —— 跳过", flush=True)
        return
    run = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    for line in ((run.stdout or "") + (run.stderr or "")).strip().splitlines():
        print("      " + line, flush=True)
    rel = "docs/structure"
    if run.returncode != 0 or not (ROOT / rel).is_dir():
        print("      !! 结构树没同步成功 —— 跳过（不影响推送）", flush=True)
        return
    if dry_run:
        print("      --dry-run：只同步，不提交", flush=True)
        return
    if not git("status", "--porcelain", "--", rel).stdout.strip():
        print("      结构树无变化，无需提交", flush=True)
        return
    git("add", "--", rel)
    commit = git("commit", "-m", f"结构树：随 {version or 'main'} 自动同步", "--", rel)
    out = ((commit.stdout or "") + (commit.stderr or "")).strip().splitlines()
    for line in out[-3:]:
        print("      " + line, flush=True)
    if commit.returncode != 0:
        print("      !! 结构树提交失败（不影响推送，下次会再试）", flush=True)


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
        # ⚠️ 退出码 0 **不等于**"快照里真有东西"（2026-10-04 修）：`snapshot.py` 在
        # "数据根不存在 / 没定位到游戏目录"时只打印一行、仍然返回 0 —— 那样推上去的记录里
        # 既没有 config/Mod 清单也没有游戏目录清单，回溯价值为零，而这里会静默放行。
        # 现在按 manifest 里的 `complete` 给醒目警告（不中止：这类快照仍可能是有用的，
        # 但绝不能让"这次快照是空的"这件事无声无息地过去）。
        snap_dir = _latest_snapshot_dir(out)
        if snap_dir is not None:
            try:
                manifest = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
            if manifest and not manifest.get("complete", True):
                reasons = "；".join(str(x) for x in (manifest.get("incomplete_reasons") or []))
                print(f"      !! 快照不完整（{reasons}）—— 已照常继续，但这次快照回溯价值有限",
                      flush=True)

    # ② 记忆日志：**每次推送都刷新并单独提交**（用户 2026-10-03 的要求）
    print("[2/5] 刷新记忆日志（docs/AI-记忆日志.md，随源码一起走）…", flush=True)
    _refresh_memory_log(version, dry_run=args.dry_run)

    # ③ 结构树：同样每次推送都同步一份进仓库（用户 2026-10-03：「结构树也一起上传」）
    print("[3/5] 同步结构树（docs/structure/）…", flush=True)
    _refresh_structure(version, dry_run=args.dry_run)

    # ④ 准备 token 与命令
    token = get_token()
    if not token:
        print("      !! 找不到 GH_TOKEN（进程环境与 HKCU\\Environment 都没有）—— 无法推送", flush=True)
        return 1
    url = f"https://{token}@github.com/{REPO}.git"
    print(f"[4/5] 远端：https://github.com/{REPO}.git  （token {mask(token)}）", flush=True)

    before_local = git("rev-parse", args.branch).stdout.strip()
    ahead = git("rev-list", "--count", f"origin/{args.branch}..{args.branch}").stdout.strip()
    print(f"      本地 {args.branch} = {before_local[:12]}   领先 origin  {ahead or '?'} 个提交", flush=True)

    if args.dry_run:
        print("[5/5] --dry-run：不执行 git push", flush=True)
        return 0

    # ⑤ 推
    print(f"[5/5] git push {args.branch}:{args.branch} …", flush=True)
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
