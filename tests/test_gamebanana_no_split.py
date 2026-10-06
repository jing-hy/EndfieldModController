"""香蕉网（GameBanana）的下载 CDN **不许分块**（2026-10-06 实测）。

**实测**（同一个 6.9 MB 文件，开了加速器的环境）：
  * 单连接 **1.07 ~ 1.40 MB/s**（正常水平）；
  * CDN **支持 Range**（`HTTP 206`）；
  * 但 **4 路分块只有 0.08 MB/s** —— 比单连接**慢约 15 倍**。
⇒ 它对同 IP 的同文件并发 Range 请求有严格限流，"慢就试并发"在这里只会拖垮速度。

**为什么只写根域 `gamebanana.com`**（用户 2026-10-06 明确要求"**要动态，不要写死**"）：
下载会 302 到 `filecache<NN>.gamebanana.com`，而 `_parallel_gate` 的匹配是
"**相等或后缀**" ⇒ 写根域即可覆盖**任意编号**（含以后新增的），不需要枚举。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import fastnet


@pytest.mark.parametrize("host", [
    "gamebanana.com",
    "www.gamebanana.com",
    "filecache1.gamebanana.com",
    "filecache54.gamebanana.com",
    "filecache999.gamebanana.com",          # 以后新增的编号也必须覆盖
])
def test_gamebanana_subdomains_never_split(host: str) -> None:
    """★ 香蕉网全部子域都不许并发分块（后缀匹配 ⇒ 编号动态覆盖，不写死）。"""
    allowed, _reason = fastnet._parallel_gate(f"https://{host}/dl/1820618", probe_mbps=0.2, policy="auto")
    assert allowed is False, f"{host} 被允许分块了 —— 实测分块会慢 15 倍"


def test_other_hosts_still_split() -> None:
    """别的域名（镜像线路等）照常允许分块 —— 别把整个机制关掉。"""
    allowed, _reason = fastnet._parallel_gate("https://ghproxy.net/x/y", probe_mbps=0.2, policy="auto")
    assert allowed is True


def test_explicit_always_still_wins() -> None:
    """用户/调用方显式要求加速时仍然放行（`policy="always"`），不改变既有语义。"""
    allowed, _reason = fastnet._parallel_gate(
        "https://filecache54.gamebanana.com/dl/1", probe_mbps=0.2, policy="always")
    assert allowed is True
