"""版本号规则的可执行版本（用户 2026-10-02 澄清）。

**规则**：版本号**只跟"最新 Release"比** ——
本地保持在「最新 Release + 1」；GitHub 上**只推了源码（main 更新）但没发 Release 时，版本号不用改**。

为什么要有这个模块：这条规则以前只写在文档与注释里、靠人记 —— 2026-09-29 就因为
"每加一个改动就 +1"凭空吃掉了两个版本号（用户原话：「**你都没推github你为什么又变版本号**」）。
现在把判据做成一个函数，`build_release.py` 与 `prepare_release.py` 各调一次，
**改号前后都能当场看到结论**。

**联网失败绝不阻断**：查不到最新 Release 时返回 `ok=None`，调用方**只提示、不中止**
（这条规则本身是用户可随时豁免的软约束，不能因为网络卡住发版）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PY = ROOT / "endfieldmodcontroller" / "version.py"
REPO = "jing-hy/EndfieldModController"


def read_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_PY.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("!! version.py 里找不到 __version__")
    return match.group(1)


def _via_gh() -> str:
    """走本机已登录的 gh CLI（用户机器上它通常已认证，且能借到加速通道）。"""
    try:
        result = subprocess.run(
            ["gh", "release", "view", "--repo", REPO, "--json", "tagName"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    try:
        return str(json.loads(result.stdout).get("tagName") or "").lstrip("vV")
    except (json.JSONDecodeError, AttributeError):
        return ""


def _via_api() -> str:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"User-Agent": "EndfieldModController-release-check",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001  （网络/证书/限流都算"查不到"）
        return ""
    return str(data.get("tag_name") or "").lstrip("vV")


def latest_release_version() -> str:
    """GitHub 最新 Release 的版本号（去掉 `v` 前缀）；查不到返回空串。"""
    return _via_gh() or _via_api()


def next_version(version: str) -> str:
    parts = str(version or "").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return ""
    major, minor, patch = (int(p) for p in parts)
    return f"{major}.{minor}.{patch + 1}"


def _commits_since(tag: str) -> int:
    """`<tag>..HEAD` 之间有多少个提交（查不到 tag / 不在 git 仓库里 → 0）。

    用来把"本地 == 最新 Release"分成两种情况：**刚发完版**（没有新提交，正常）与
    **发完版又攒了改动却没升号**（用户明确要求"有改动就领先一个版本"）。查不到就当作
    0（保守：不因为 git 环境问题让构建/推送被拦住）。
    """
    try:
        out = subprocess.run(
            ["git", "rev-list", "--count", f"{tag}..HEAD"],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except Exception:  # noqa: BLE001
        return 0
    if out.returncode != 0:
        return 0
    try:
        return int((out.stdout or "0").strip() or "0")
    except ValueError:
        return 0


def check(local: str | None = None) -> dict[str, object]:
    """核对"本地版本号 vs 最新 Release"。返回 dict（含 `ok` / `kind` / `message`）。"""
    local = str(local or read_version())
    latest = latest_release_version()
    if not latest:
        return {
            "ok": None, "kind": "unknown", "local": local, "latest": "",
            "message": "查不到 GitHub 最新 Release（网络不通或 gh 未登录）—— 规则不变："
                       "本地应保持在「最新 Release + 1」；只推了源码没发 Release 时不动号",
        }
    if local == latest:
        # ⚠️ `local == latest` **不一定是 OK**（2026-10-04 修）：用户规则是"本地/源码只要有
        # 改动就领先 Release 一个号"（原话：「不发 release，但是本地和源码如果有改动要领先
        # release 一个版本」）。原来这里一律 `ok=True`，于是"发完 Release 忘了 +1、又攒了一批
        # 改动"会**静默通过**检查。
        # 判据用 git 说实话：`<tag>..HEAD` 里有提交 ⇒ 有改动却没升号 ⇒ 不通过。
        ahead_commits = _commits_since(f"v{latest}")
        if ahead_commits:
            return {
                "ok": False, "kind": "same-with-commits", "local": local, "latest": latest,
                "message": f"本地 {local} 与最新 Release v{latest} 相同，但**`v{latest}` 之后还有 "
                           f"{ahead_commits} 个提交** —— 按规则应当升到 **{next_version(latest)}**"
                           f"（只有「准备重发同一个版本」才该保持相同）",
            }
        return {
            "ok": True, "kind": "same", "local": local, "latest": latest,
            "message": f"本地 {local} 与最新 Release v{latest} **相同**，且 `v{latest}` 之后没有新提交"
                       f" —— 属于「刚发完版、还没攒新改动」的正常状态",
        }
    if local == next_version(latest):
        return {
            "ok": True, "kind": "ahead-one", "local": local, "latest": latest,
            "message": f"本地 {local} = 最新 Release v{latest} + 1　✅ 符合规则"
                       f"（main 上就算又推了源码没发 Release，这个号也不用动）",
        }
    return {
        "ok": False, "kind": "off", "local": local, "latest": latest,
        "message": f"本地 {local} 不是「最新 Release v{latest} + 1」（应为 {next_version(latest)}）"
                   f" —— 检查是不是凭空吃掉了版本号，或者忘了先发 Release",
    }


def _fix_console() -> None:
    """Windows 控制台默认 GBK，结论里有 ✅ / ⚠ 这类字符会直接崩（单独跑这个脚本时必踩）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def report(prefix: str = "[版本号]") -> dict[str, object]:
    """核对并打印一行结论（给 build_release / prepare_release 直接调）。"""
    _fix_console()
    result = check()
    if result["ok"] is None:
        print(f"{prefix} {result['message']}", flush=True)
    else:
        head = "OK  " if result["ok"] else "WARN"
        print(f"{prefix} {head} {result['message']}", flush=True)
    return result


if __name__ == "__main__":
    result = report()
    raise SystemExit(0 if result["ok"] is not False else 1)
