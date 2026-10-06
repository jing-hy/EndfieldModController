"""上传 Release 附件（**绕过 Steam++ / Watt Toolkit 之类 hosts 反代**，专治大文件上传被掐）。

背景（2026-10-01 实测）：
    本机开着 Steam++ 时，它把 github 相关域名全部写进 hosts 指向 `127.0.0.1` 的本地反代
    （`uploads.github.com` 也在列表里）。该反代对**大 body 的 POST 上传**支持不好：
    1 / 5 / 20 / 60 MB 都能过，而 126 MB 的 `assets-bundle.zip` 会在发出约 100 KB 后
    被强断（`RequestBodyDestination: 远程主机强迫关闭了一个现有的连接 … but Content-Length
    specified 132789495`），`gh release upload` 与 urllib 直传都失败（HTTP 502）。
    —— 但 **只影响上传大文件，下载不受影响**。

绕过办法（实测有效）：
    用 DoH 查到 `uploads.github.com` 的真实 IP，再用 `curl --resolve` 直连上传 ——
    126 MB / 23.2s / 5.7 MB/s 成功（HTTP 201）。
    只影响本次 curl 的解析，**不改 hosts、不动系统代理**。

用法：
    python scripts/upload_release_assets.py                  # 上传 dist 里的两个附件到 v<当前版本>
    python scripts/upload_release_assets.py --tag v0.3.0     # 指定 tag
    python scripts/upload_release_assets.py --dry-run        # 只打印将要做什么

附件清单（与用户规则一致）：`EndfieldModController.exe`（不带版本号）+ `assets-bundle.zip`。
不上传带版本号副本与伪旧版。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION_PY = ROOT / "endfieldmodcontroller" / "version.py"
APP_NAME = "EndfieldModController"
REPO = "jing-hy/EndfieldModController"
UPLOAD_HOST = "uploads.github.com"
DOH_ENDPOINTS = (
    "https://dns.alidns.com/resolve?name={host}&type=A",
    "https://doh.pub/dns-query?name={host}&type=A",
    "https://cloudflare-dns.com/dns-query?name={host}&type=A",
)


def _fix_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def read_version() -> str:
    match = re.search(r'__version__ = "([^"]+)"', VERSION_PY.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("!! version.py 里找不到 __version__")
    return match.group(1)


def token() -> str:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name in ("GH_TOKEN", "GITHUB_TOKEN"):
                try:
                    value, _kind = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if value and str(value).strip():
                    return str(value).strip()
    except OSError:
        pass
    raise SystemExit("!! 找不到 GH_TOKEN（用户级环境变量）")


def resolve_real_ip(host: str) -> str:
    """用 DoH 查真实 IP —— 本机 hosts 把它指到 127.0.0.1 了，必须绕开。"""
    for template in DOH_ENDPOINTS:
        url = template.format(host=urllib.parse.quote(host))
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=20) as response:
                data = json.load(response)
        except Exception:  # noqa: BLE001
            continue
        answers = [a.get("data") for a in (data.get("Answer") or []) if a.get("type") == 1]
        if answers:
            return str(answers[0])
    raise SystemExit(f"!! DoH 查不到 {host} 的真实 IP")


def _release_data(tag: str, headers: dict[str, str]) -> dict:
    """按 tag 找 Release；**draft 也能找到**（draft 的 tag 尚未建立，按 tag 查会 404，
    这时退回到列表接口里找）。"""
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    list_url = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
    req = urllib.request.Request(list_url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        releases = json.load(response)
    for item in releases:
        if str(item.get("tag_name")) == tag:
            return item
    # ★ **兜底：draft 阶段 tag 还没建立**（2026-10-06 实测踩到）。
    #   `gh release create <tag> --draft` 给出的 `tag_name` 是 `untagged-<hash>`，
    #   而 `push.py` **只推 main、不推 tag** ⇒ 列表里按 tag 名永远匹配不上 ⇒ 上传步骤
    #   直接中止（v1.0.24 那次就是手工 `gh release upload` 补的附件）。
    #   发版流程一次只开一个 draft，所以"当前唯一的 draft"就是它。
    drafts = [item for item in releases if item.get("draft")]
    if len(drafts) == 1:
        print(f"   注意：按 tag `{tag}` 没匹配上，改用当前唯一的 draft"
              f"（tag_name={drafts[0].get('tag_name')}）—— draft 阶段 tag 尚未建立属正常。")
        return drafts[0]
    if len(drafts) > 1:
        raise SystemExit(f"!! 有 {len(drafts)} 个 draft，无法确定上传目标；"
                         f"请先把多余的 draft 删掉或转正，再重跑。")
    raise SystemExit(f"!! GitHub 上找不到 tag {tag} 的 Release（含 draft）")


def release_id(tag: str, headers: dict[str, str]) -> int:
    return int(_release_data(tag, headers)["id"])


def existing_assets(tag: str, headers: dict[str, str]) -> dict[str, int]:
    data = _release_data(tag, headers)
    return {str(a.get("name")): int(a.get("size") or 0) for a in (data.get("assets") or [])}


def upload(path: Path, rid: int, ip: str, secret: str) -> bool:
    """用 curl --resolve 直连真实 IP 上传单个附件。"""
    if not shutil.which("curl"):
        print("   !! PATH 里没有 curl，无法直连上传")
        return False
    url = f"https://{UPLOAD_HOST}/repos/{REPO}/releases/{rid}/assets?name={urllib.parse.quote(path.name)}"
    cmd = [
        "curl", "--resolve", f"{UPLOAD_HOST}:443:{ip}", "-sS", "-X", "POST",
        "-H", f"Authorization: Bearer {secret}",
        "-H", "Content-Type: application/octet-stream",
        "--data-binary", f"@{path}",
        "-w", "\nHTTP=%{http_code} sent=%{size_upload} time=%{time_total}s",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
    ok = "HTTP=201" in tail[0] or "HTTP=200" in tail[0] or "HTTP=422" in tail[0]
    print(f"   {'[ok]' if ok else '[!!]'} {path.name}  {tail[0]}")
    if not ok and result.stderr:
        print(f"        stderr: {result.stderr.strip()[:200]}")
    return ok


def main() -> int:
    _fix_console()
    args = sys.argv[1:]
    tag = ""
    for index, item in enumerate(args):
        if item == "--tag" and index + 1 < len(args):
            tag = args[index + 1]
    dry_run = "--dry-run" in args
    tag = tag or f"v{read_version()}"

    assets = [DIST / f"{APP_NAME}.exe", DIST / "assets-bundle.zip"]
    print(f"== 上传 {tag} 的附件到 {REPO} ==", flush=True)
    for item in assets:
        print(f"   {item.name}  {item.stat().st_size:,} B" if item.is_file() else f"   !! 缺少 {item}", flush=True)
    if not all(item.is_file() for item in assets):
        return 1

    secret = token()
    headers = {"Authorization": f"Bearer {secret}", "User-Agent": APP_NAME,
               "Accept": "application/vnd.github+json"}
    rid = release_id(tag, headers)
    before = existing_assets(tag, headers)
    print(f"\nrelease id = {rid}；已有资产 = {before or '（无）'}", flush=True)
    if dry_run:
        print("\n（--dry-run：不实际上传）", flush=True)
        return 0

    ip = resolve_real_ip(UPLOAD_HOST)
    print(f"真实 IP（DoH）= {ip}  —— 用它绕过 hosts 反代直连上传\n", flush=True)

    failures: list[str] = []
    for item in assets:
        if before.get(item.name) == item.stat().st_size:
            print(f"   [skip] {item.name} 已在 Release 上且大小一致", flush=True)
            continue
        if not upload(item, rid, ip, secret):
            failures.append(item.name)

    after = existing_assets(tag, headers)
    print("\n上传后资产：", flush=True)
    for name, size in after.items():
        print(f"   {name:44s} {size:>14,} B", flush=True)
    if failures:
        print(f"\n!! 失败：{', '.join(failures)}", flush=True)
        return 1
    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
