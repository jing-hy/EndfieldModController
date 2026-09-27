"""GitHub 查询的公共入口：带 token、带缓存、把 403/限流翻译成人话。

为什么要专门包一层（2026-09-27 踩到）：

* **匿名额度只有 60 次/小时**，而我们查版本、查 release 资产、检查更新都要打
  `api.github.com` —— 一轮调研 + 几次点「自动安装/更新」就能把额度用光，之后
  用户看到的就是一个**光秃秃的 403**，完全不知道发生了什么、要等多久。
* 本机通常已经存在 `GH_TOKEN` / `GITHUB_TOKEN`（用户级环境变量），带上它额度是
  **5000 次/小时**。注意：**用户级环境变量要主动去注册表读** —— 如果程序是在设置
  该变量之前启动的，进程环境里根本没有它。
* 同一份 release 信息在半小时内不该反复请求，于是加一层磁盘缓存
  （`runtime\\_net\\github_cache.json`，几 KB，随 runtime 一起被 git 忽略）。

对外只暴露 :func:`api_get` 和 :func:`releases_latest`，错误统一是
:class:`GitHubError`（消息已经是给用户看的中文）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .version import USER_AGENT

CACHE_NAME = Path("_net") / "github_cache.json"
DEFAULT_TTL = 30 * 60          # 半小时内不重复问同一个地址
RATE_LIMIT_HINT = (
    "GitHub API 额度用尽（匿名 60 次/小时）。"
    "设置环境变量 GH_TOKEN 或 GITHUB_TOKEN 后可提升到 5000 次/小时，"
    "否则请等额度重置后再试。"
)


class GitHubError(RuntimeError):
    """消息已经是可以直接展示给用户的中文说明。"""


def _cache_path() -> Path:
    from .config import PROJECT_ROOT

    return PROJECT_ROOT / "runtime" / CACHE_NAME


def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    # 别让缓存无限膨胀
    if len(data) > 400:
        newest = sorted(data.items(), key=lambda kv: float((kv[1] or {}).get("at") or 0), reverse=True)[:200]
        data = dict(newest)
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except OSError:
        pass


def clear_cache() -> None:
    try:
        _cache_path().unlink()
    except OSError:
        pass


def token() -> tuple[str, str]:
    """返回 ``(token, 来源)``。

    先看进程环境，再补一刀**读 Windows 用户级环境变量**（`HKCU\\Environment`）——
    程序若是"设置 token 之前"启动的，进程环境里不会有它，但注册表里有。
    """
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip(), "process-env"
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                for name in ("GITHUB_TOKEN", "GH_TOKEN"):
                    try:
                        value, _kind = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    if value and str(value).strip():
                        return str(value).strip(), "user-registry"
        except OSError:
            pass
    return "", ""


def _http_error_message(exc: urllib.error.HTTPError, has_token: bool) -> str:
    code = exc.code
    headers = exc.headers or {}
    remaining = headers.get("X-RateLimit-Remaining")
    reset = headers.get("X-RateLimit-Reset")
    if code in (403, 429) and (remaining == "0" or not has_token):
        wait = ""
        try:
            if reset:
                minutes = max(0, int((int(reset) - time.time()) // 60))
                wait = f"约 {minutes} 分钟后自动恢复。" if minutes else "额度即将重置。"
        except (TypeError, ValueError):
            wait = ""
        return f"{RATE_LIMIT_HINT}{wait}"
    if code == 404:
        return "GitHub 上找不到这个仓库或 Release（可能还没发布，或名字写错了）。"
    if code in (401, 403):
        return "GitHub 拒绝了这个请求（token 无效或权限不足）。"
    return f"GitHub 请求失败：HTTP {code}。"


def api_get(
    url: str,
    *,
    timeout: int = 25,
    ttl: int = DEFAULT_TTL,
    use_cache: bool = True,
) -> Any:
    """GET 一个 GitHub API 地址，返回解析后的 JSON。

    * 命中缓存（默认 30 分钟内）直接返回，不再消耗额度；
    * 失败抛 :class:`GitHubError`，消息是给用户看的中文。
    """
    now = time.time()
    if use_cache:
        entry = _load_cache().get(url)
        if isinstance(entry, dict) and now - float(entry.get("at") or 0) < ttl:
            return entry.get("data")

    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    secret, _source = token()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise GitHubError(_http_error_message(exc, bool(secret))) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise GitHubError(f"连不上 GitHub：{exc}（网络不通时可到设置页把「下载线路」设为自动/镜像）") from exc
    except json.JSONDecodeError as exc:
        raise GitHubError(f"GitHub 返回的内容无法解析：{exc}") from exc

    if use_cache:
        cache = _load_cache()
        cache[url] = {"at": int(now), "data": payload}
        _save_cache(cache)
    return payload


ASSET_LINK_RE = re.compile(r'/releases/download/[^"]+/([^"/?]+)')
COMMIT_ID_RE = re.compile(r"Grit::Commit/([0-9a-f]{7,40})")


def latest_commit(repo: str, branch: str = "main", *, ttl: int = DEFAULT_TTL) -> str:
    """按分支取最新 commit sha。

    走 `commits/<branch>.atom`（Atom feed，**不消耗 API 额度**），失败才回退 API。
    用于那些**没有 release**、只能按提交比对的仓库（如 iMMERSE）。
    """
    from . import fastnet

    cache_key = f"web://{repo}/commits/{branch}"
    entry = _load_cache().get(cache_key)
    if isinstance(entry, dict) and time.time() - float(entry.get("at") or 0) < ttl:
        return str(entry.get("data") or "")

    sha = ""
    try:
        _final, body = fastnet.fetch(f"https://github.com/{repo}/commits/{branch}.atom")
        match = COMMIT_ID_RE.search(body.decode("utf-8", errors="replace"))
        sha = match.group(1) if match else ""
    except Exception:  # noqa: BLE001
        sha = ""
    if not sha:
        data = api_get(f"https://api.github.com/repos/{repo}/commits/{branch}")
        sha = str(data.get("sha") or "")
    if sha:
        cache = _load_cache()
        cache[cache_key] = {"at": int(time.time()), "data": sha}
        _save_cache(cache)
    return sha


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(p) for p in parts) or (0,)


def asset_sort_key(asset: dict[str, Any]) -> tuple:
    """挑资产用：**先看名字里的版本号**，再退回体积。

    网页路线拿不到 size（都是 0），所以不能只按体积排序 —— 否则会挑错资产。
    """
    return (_version_tuple(str(asset.get("name") or "")), int(asset.get("size") or 0))


def _release_via_web(repo: str) -> dict[str, Any]:
    """**不消耗 API 额度**地拿 release：302 重定向取 tag + expanded_assets 页面取资产名。

    网页请求走 :mod:`fastnet`，所以直连不通时会自动经镜像线路 —— 没有 token 的用户
    也能正常工作，这正是"不是每个人都有 token"的解法。
    """
    from . import fastnet

    final, _body = fastnet.fetch(f"https://github.com/{repo}/releases/latest")
    tag = final.rstrip("/").rsplit("/", 1)[-1]
    if not tag or tag in {"latest", "releases", "tags"}:
        raise GitHubError(f"{repo} 还没有可用的 Release")
    _final, html = fastnet.fetch(
        f"https://github.com/{repo}/releases/expanded_assets/{tag}",
        headers={"Accept": "text/html"}, timeout=25,
    )
    names = ASSET_LINK_RE.findall(html.decode("utf-8", errors="replace"))
    assets = [
        {
            "name": name,
            "browser_download_url": f"https://github.com/{repo}/releases/download/{tag}/{name}",
            "size": 0,      # 网页上没有可靠的大小，排序时按版本号
        }
        for name in dict.fromkeys(names)   # 去重且保持顺序
    ]
    return {"tag_name": tag, "assets": assets, "source": "web"}


def releases_latest(
    repo: str,
    *,
    ttl: int = DEFAULT_TTL,
    prefer_api: bool = False,
) -> dict[str, Any]:
    """某个仓库的最新 release。

    默认**先走网页**（不消耗 API 额度、能借镜像线路），失败才回退 API。
    这样即便没有 token、或者 API 已被限流，检查更新/自动安装照样能用。
    """
    if not prefer_api:
        cache_key = f"web://{repo}/releases/latest"
        entry = _load_cache().get(cache_key)
        if isinstance(entry, dict) and time.time() - float(entry.get("at") or 0) < ttl:
            return entry.get("data")
        try:
            data = _release_via_web(repo)
        except Exception:  # noqa: BLE001  —— 网页路线不通就走 API
            data = None
        if isinstance(data, dict):
            cache = _load_cache()
            cache[cache_key] = {"at": int(time.time()), "data": data}
            _save_cache(cache)
            return data
    return api_get(f"https://api.github.com/repos/{repo}/releases/latest", ttl=ttl)


def status() -> dict[str, Any]:
    """给界面/日志用：token 有没有、缓存多大。"""
    secret, source = token()
    return {
        "token": bool(secret),
        "token_source": source,
        "cache_entries": len(_load_cache()),
        "hourly_limit": 5000 if secret else 60,
    }
